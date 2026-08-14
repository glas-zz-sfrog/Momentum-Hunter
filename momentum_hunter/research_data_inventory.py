"""Read-only inventory of local research evidence and proven data gaps.

The inventory accepts explicit filesystem paths, never contacts a provider, and
never alters source evidence. Its classifications describe research
sufficiency only; they grant no scoring, selection, broker, or execution
authority.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from momentum_hunter.config import DATA_DIR


SCHEMA_VERSION = 1
ENGINE_VERSION = "research-data-inventory-v1"
TASK_ID = "ARGUS-RESEARCH-DATA-001"
EXECUTION_AUTHORITY = "NONE"

SUFFICIENT = "SUFFICIENT"
PARTIAL = "PARTIAL"
INSUFFICIENT = "INSUFFICIENT"
UNVERIFIED = "UNVERIFIED"

CANONICAL = "CANONICAL"
RESEARCH_ONLY = "RESEARCH_ONLY"
PROSPECTIVE_RESEARCH = "PROSPECTIVE_RESEARCH"

MAX_JSON_BYTES = 128 * 1024 * 1024
SESSION_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EASTERN = ZoneInfo("America/New_York")
SECURITY_ID_KEYS = frozenset(
    {"securityid", "cusip", "isin", "figi", "permanentid", "instrumentid"}
)
CORPORATE_ACTION_KEYS = frozenset(
    {
        "adjustmentfactor",
        "splitfactor",
        "splitratio",
        "corporateactionid",
        "effectiveat",
    }
)


class ResearchDataInventoryError(RuntimeError):
    """Raised when local evidence is malformed or contradicts its contract."""


@dataclass(frozen=True)
class ResearchDataPaths:
    canonical_minute_root: Path
    canonical_daily_root: Path
    research_daily_path: Path
    analysis_captures_path: Path
    analysis_outcomes_path: Path
    opening_captures_root: Path
    successor_setup_root: Path

    @classmethod
    def defaults(cls) -> "ResearchDataPaths":
        return cls(
            canonical_minute_root=DATA_DIR / "schwab-candles-v1",
            canonical_daily_root=DATA_DIR / "schwab-daily-candles-v1",
            research_daily_path=DATA_DIR / "daily-ohlc-bars.json",
            analysis_captures_path=DATA_DIR / "analysis-captures.csv",
            analysis_outcomes_path=DATA_DIR / "analysis-outcomes.csv",
            opening_captures_root=DATA_DIR / "captures",
            successor_setup_root=(
                DATA_DIR / "research" / "successor-setup-research-20260813-v1"
            ),
        )


def build_research_data_inventory(
    paths: ResearchDataPaths,
    *,
    as_of: str,
) -> dict[str, Any]:
    """Build one deterministic inventory from explicit local evidence paths."""

    _parse_aware(as_of)
    datasets = [
        _inventory_canonical_minutes(paths.canonical_minute_root),
        _inventory_canonical_daily(paths.canonical_daily_root),
        _inventory_research_daily(paths.research_daily_path),
        _inventory_candidate_history(
            paths.analysis_captures_path,
            paths.analysis_outcomes_path,
            paths.opening_captures_root,
        ),
        _inventory_successor_setup(paths.successor_setup_root),
    ]
    by_id = {str(item["datasetId"]): item for item in datasets}
    universe = _universe_integrity(datasets)
    capabilities = _capability_matrix(by_id, universe)
    gaps = _proven_gaps(by_id, universe)
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "engineVersion": ENGINE_VERSION,
        "task": TASK_ID,
        "asOf": as_of,
        "classification": "LOCAL_EVIDENCE_INVENTORIED_RESEARCH_SCALE_GAPS_PROVEN",
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "networkAccess": "PROHIBITED",
        "productionMutation": False,
        "providerSelection": "NOT_PERFORMED",
        "datasets": datasets,
        "universeIntegrity": universe,
        "capabilityMatrix": capabilities,
        "provenGaps": gaps,
        "providerMinimalism": {
            "decision": "USE_EXISTING_EVIDENCE_AND_PROSPECTIVE_ACCUMULATION_FIRST",
            "newProviderRequiredNow": False,
            "reason": (
                "This inventory proves capability gaps but does not yet prove that "
                "existing Schwab history plus prospective accumulation cannot close them."
            ),
        },
    }
    payload["inventoryFingerprint"] = fingerprint_payload(payload)
    return payload


def _inventory_canonical_minutes(root: Path) -> dict[str, Any]:
    if not root.exists():
        return _missing_dataset(
            "canonicalSchwabMinute", root, CANONICAL, "Schwab price history"
        )
    files = sorted(
        path
        for date_dir in root.iterdir()
        if date_dir.is_dir() and SESSION_DATE.fullmatch(date_dir.name)
        for path in date_dir.glob("*.json")
    )
    symbols: Counter[str] = Counter()
    session_dates: set[str] = set()
    sources: set[str] = set()
    session_counts: Counter[str] = Counter()
    session_symbol_dates: dict[str, set[str]] = defaultdict(set)
    states: Counter[str] = Counter()
    timestamps: list[str] = []
    partition_hashes: list[dict[str, str]] = []
    duplicate_identities = 0
    observed_gap_minutes: Counter[str] = Counter()
    noncanonical_bars = 0
    has_security_identity = False
    has_corporate_action_lineage = False
    per_symbol_dates: dict[str, set[str]] = defaultdict(set)
    for path in files:
        payload, digest = _read_json_with_hash(path)
        if not isinstance(payload, Mapping):
            raise ResearchDataInventoryError(f"Minute partition was not an object: {path}")
        symbol = _required_text(payload, "symbol", path)
        session_date = _required_text(payload, "sessionDate", path)
        if session_date != path.parent.name:
            raise ResearchDataInventoryError(
                f"Minute partition date contradicted its directory: {path}"
            )
        if payload.get("legacySourceMixed") is not False:
            raise ResearchDataInventoryError(
                f"Minute partition did not prove legacy-source isolation: {path}"
            )
        if payload.get("schemaVersion") != 1 or payload.get("storeKind") != "SCHWAB_INCREMENTAL_MINUTE_CANDLES":
            raise ResearchDataInventoryError(
                f"Minute partition schema/store identity was invalid: {path}"
            )
        raw_bars = payload.get("bars")
        if not isinstance(raw_bars, list):
            raise ResearchDataInventoryError(f"Minute partition bars were invalid: {path}")
        symbols[symbol] += 1
        session_dates.add(session_date)
        per_symbol_dates[symbol].add(session_date)
        sources.add(str(payload.get("canonicalSource") or "UNSPECIFIED"))
        has_security_identity |= _contains_key(payload, SECURITY_ID_KEYS)
        has_corporate_action_lineage |= _contains_key(payload, CORPORATE_ACTION_KEYS)
        seen: set[str] = set()
        by_derived_session: dict[str, list[datetime]] = defaultdict(list)
        for raw_bar in raw_bars:
            if not isinstance(raw_bar, Mapping):
                raise ResearchDataInventoryError(f"Minute bar was invalid: {path}")
            identity = _required_text(raw_bar, "minuteIdentity", path)
            if identity in seen:
                duplicate_identities += 1
            seen.add(identity)
            state = str(raw_bar.get("state") or "UNSPECIFIED")
            states[state] += 1
            candle = raw_bar.get("canonicalCandle")
            if not isinstance(candle, Mapping):
                noncanonical_bars += 1
                continue
            if str(candle.get("symbol") or "") != symbol:
                raise ResearchDataInventoryError(
                    f"Minute candle symbol contradicted its partition: {path}"
                )
            timestamp = _parse_aware(str(candle.get("timestamp") or ""))
            timestamps.append(timestamp.astimezone(timezone.utc).isoformat())
            session = _derived_market_session(timestamp)
            session_counts[session] += 1
            session_symbol_dates[session].add(f"{symbol}|{session_date}")
            by_derived_session[session].append(timestamp)
            sources.add(str(candle.get("source") or "UNSPECIFIED"))
            has_security_identity |= _contains_key(candle, SECURITY_ID_KEYS)
            has_corporate_action_lineage |= _contains_key(
                candle, CORPORATE_ACTION_KEYS
            )
        for session, values in by_derived_session.items():
            if session == "OUTSIDE_STANDARD_EQUITY_SESSIONS":
                continue
            ordered = sorted(set(values))
            for previous, current in zip(ordered, ordered[1:]):
                delta = int((current - previous).total_seconds() // 60)
                if delta > 1:
                    observed_gap_minutes[session] += delta - 1
        partition_hashes.append(
            {"path": f"{path.parent.name}/{path.name}", "sha256": digest}
        )
    return {
        "datasetId": "canonicalSchwabMinute",
        "path": str(root),
        "present": True,
        "authority": CANONICAL,
        "source": sorted(sources),
        "schemaVersion": SCHEMA_VERSION,
        "priceBasis": "PROVIDER_BASIS_UNSPECIFIED",
        "recordCount": sum(session_counts.values()),
        "fileCount": len(files),
        "symbolCount": len(symbols),
        "symbols": sorted(symbols),
        "sessionDateCount": len(session_dates),
        "firstTimestamp": min(timestamps) if timestamps else None,
        "lastTimestamp": max(timestamps) if timestamps else None,
        "sessionCoverage": dict(sorted(session_counts.items())),
        "sessionSymbolDateCount": {
            session: len(values)
            for session, values in sorted(session_symbol_dates.items())
        },
        "perSymbolSessionDates": {
            symbol: len(dates) for symbol, dates in sorted(per_symbol_dates.items())
        },
        "states": dict(sorted(states.items())),
        "duplicateIdentityCount": duplicate_identities,
        "observedInternalGapMinutes": sum(observed_gap_minutes.values()),
        "observedInternalGapMinutesBySession": dict(
            sorted(observed_gap_minutes.items())
        ),
        "noncanonicalBarCount": noncanonical_bars,
        "legacySourceMixed": False,
        "stableSecurityIdentity": has_security_identity,
        "corporateActionLineage": has_corporate_action_lineage,
        "partitionFingerprint": fingerprint_payload(partition_hashes),
        "limitations": [
            "Ticker is the only security identity.",
            "Provider price basis and split-event lineage are not explicit.",
            "Observed internal gaps do not prove full expected-session completeness.",
            "Bars outside standard 04:00-20:00 ET equity sessions require separate timestamp/session adjudication.",
        ],
    }


def _inventory_canonical_daily(root: Path) -> dict[str, Any]:
    if not root.exists():
        return _missing_dataset(
            "canonicalSchwabDaily", root, CANONICAL, "Schwab price history"
        )
    files = sorted(root.glob("*.json"))
    symbols: set[str] = set()
    dates: list[str] = []
    sources: set[str] = set()
    states: Counter[str] = Counter()
    bar_count = 0
    duplicate_identities = 0
    hashes: list[dict[str, str]] = []
    has_security_identity = False
    has_corporate_action_lineage = False
    per_symbol_bars: dict[str, int] = {}
    for path in files:
        payload, digest = _read_json_with_hash(path)
        if not isinstance(payload, Mapping):
            raise ResearchDataInventoryError(f"Daily symbol file was invalid: {path}")
        symbol = _required_text(payload, "symbol", path)
        if payload.get("legacySourceMixed") is not False:
            raise ResearchDataInventoryError(
                f"Daily symbol file did not prove legacy-source isolation: {path}"
            )
        if payload.get("schemaVersion") != 1 or payload.get("storeKind") != "SCHWAB_CANONICAL_DAILY_CANDLES":
            raise ResearchDataInventoryError(
                f"Daily symbol schema/store identity was invalid: {path}"
            )
        raw_bars = payload.get("bars")
        if not isinstance(raw_bars, list):
            raise ResearchDataInventoryError(f"Daily bars were invalid: {path}")
        symbols.add(symbol)
        sources.add(str(payload.get("canonicalSource") or "UNSPECIFIED"))
        seen: set[str] = set()
        valid_for_symbol = 0
        for raw_bar in raw_bars:
            if not isinstance(raw_bar, Mapping):
                raise ResearchDataInventoryError(f"Daily bar was invalid: {path}")
            identity = _required_text(raw_bar, "dailyIdentity", path)
            if identity in seen:
                duplicate_identities += 1
            seen.add(identity)
            states[str(raw_bar.get("state") or "UNSPECIFIED")] += 1
            candle = raw_bar.get("canonicalCandle")
            if not isinstance(candle, Mapping):
                continue
            if str(candle.get("symbol") or "") != symbol:
                raise ResearchDataInventoryError(
                    f"Daily candle symbol contradicted its file: {path}"
                )
            dates.append(_required_text(candle, "sessionDate", path))
            sources.add(str(candle.get("source") or "UNSPECIFIED"))
            valid_for_symbol += 1
            has_security_identity |= _contains_key(candle, SECURITY_ID_KEYS)
            has_corporate_action_lineage |= _contains_key(
                candle, CORPORATE_ACTION_KEYS
            )
        per_symbol_bars[symbol] = valid_for_symbol
        bar_count += valid_for_symbol
        has_security_identity |= _contains_key(payload, SECURITY_ID_KEYS)
        has_corporate_action_lineage |= _contains_key(payload, CORPORATE_ACTION_KEYS)
        hashes.append({"path": path.name, "sha256": digest})
    return {
        "datasetId": "canonicalSchwabDaily",
        "path": str(root),
        "present": True,
        "authority": CANONICAL,
        "source": sorted(sources),
        "schemaVersion": SCHEMA_VERSION,
        "priceBasis": "PROVIDER_BASIS_UNSPECIFIED",
        "recordCount": bar_count,
        "fileCount": len(files),
        "symbolCount": len(symbols),
        "symbols": sorted(symbols),
        "firstDate": min(dates) if dates else None,
        "lastDate": max(dates) if dates else None,
        "perSymbolBars": dict(sorted(per_symbol_bars.items())),
        "states": dict(sorted(states.items())),
        "duplicateIdentityCount": duplicate_identities,
        "legacySourceMixed": False,
        "stableSecurityIdentity": has_security_identity,
        "corporateActionLineage": has_corporate_action_lineage,
        "partitionFingerprint": fingerprint_payload(hashes),
        "limitations": [
            "Ticker is the only security identity.",
            "The store does not identify adjustment basis or split-event lineage.",
        ],
    }


def _inventory_research_daily(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _missing_dataset(
            "researchDaily263", path, RESEARCH_ONLY, "local research cache"
        )
    payload, digest = _read_json_with_hash(path)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
        raise ResearchDataInventoryError(f"Research Daily cache was invalid: {path}")
    if payload.get("schema_version") != 1 or payload.get("research_only") is not True:
        raise ResearchDataInventoryError(
            f"Research Daily cache did not prove its research-only schema: {path}"
        )
    records = payload["records"]
    symbols: set[str] = set()
    dates: list[str] = []
    sources: set[str] = set()
    adjusted: Counter[str] = Counter()
    identities: Counter[str] = Counter()
    per_symbol_bars: Counter[str] = Counter()
    has_security_identity = False
    has_corporate_action_lineage = False
    for record in records:
        if not isinstance(record, Mapping):
            raise ResearchDataInventoryError(f"Research Daily row was invalid: {path}")
        symbol = _required_text(record, "symbol", path)
        date = _required_text(record, "date", path)
        symbols.add(symbol)
        per_symbol_bars[symbol] += 1
        dates.append(date)
        sources.add(str(record.get("source") or "UNSPECIFIED"))
        adjusted[str(record.get("adjusted")).lower()] += 1
        identities[f"{symbol}|{date}"] += 1
        has_security_identity |= _contains_key(record, SECURITY_ID_KEYS)
        has_corporate_action_lineage |= _contains_key(record, CORPORATE_ACTION_KEYS)
    return {
        "datasetId": "researchDaily263",
        "path": str(path),
        "present": True,
        "authority": RESEARCH_ONLY,
        "source": sorted(sources),
        "schemaVersion": payload.get("schema_version"),
        "engineVersion": payload.get("engine_version"),
        "generatedAt": payload.get("generated_at"),
        "priceBasis": "ADJUSTED_OHLCV_WITHOUT_EVENT_LEVEL_FACTOR_LINEAGE",
        "recordCount": len(records),
        "fileCount": 1,
        "symbolCount": len(symbols),
        "symbols": sorted(symbols),
        "perSymbolBars": dict(sorted(per_symbol_bars.items())),
        "minimumBarsPerSymbol": min(per_symbol_bars.values()) if per_symbol_bars else 0,
        "maximumBarsPerSymbol": max(per_symbol_bars.values()) if per_symbol_bars else 0,
        "symbolsWithAtLeast200Bars": sum(
            count >= 200 for count in per_symbol_bars.values()
        ),
        "symbolsWithFewerThan200Bars": sorted(
            symbol for symbol, count in per_symbol_bars.items() if count < 200
        ),
        "firstDate": min(dates) if dates else None,
        "lastDate": max(dates) if dates else None,
        "adjustedValues": dict(sorted(adjusted.items())),
        "duplicateIdentityCount": sum(count - 1 for count in identities.values() if count > 1),
        "stableSecurityIdentity": has_security_identity,
        "corporateActionLineage": has_corporate_action_lineage,
        "fileSha256": digest,
        "limitations": [
            "Research-only Yahoo-derived data is not canonical execution evidence.",
            "Ticker is the only security identity.",
            "Adjusted values lack per-event factors and raw-to-adjusted lineage.",
            "The universe is evidence-derived rather than point-in-time survivor-safe.",
        ],
    }


def _inventory_candidate_history(
    captures_path: Path,
    outcomes_path: Path,
    opening_root: Path,
) -> dict[str, Any]:
    captures = _read_csv(captures_path)
    outcomes = _read_csv(outcomes_path)
    capture_symbols = {str(row.get("ticker") or "").strip() for row in captures}
    capture_symbols.discard("")
    capture_times = sorted(
        str(row.get("capture_time") or "") for row in captures if row.get("capture_time")
    )
    selected = sum(_csv_bool(row.get("selected")) for row in captures)
    reviewed = sum(_csv_bool(row.get("reviewed")) for row in captures)
    complete_outcomes = sum(
        str(row.get("outcome_status") or "").lower() == "complete" for row in outcomes
    )
    opening_files = sorted(opening_root.glob("*/opening.json")) if opening_root.exists() else []
    opening_candidate_count = 0
    nonempty_openings = 0
    raw_denominator_sessions = 0
    opening_hashes: list[dict[str, str]] = []
    for path in opening_files:
        payload, digest = _read_json_with_hash(path)
        if not isinstance(payload, Mapping) or not isinstance(payload.get("candidates"), list):
            raise ResearchDataInventoryError(f"Opening capture was invalid: {path}")
        candidates = payload["candidates"]
        opening_candidate_count += len(candidates)
        nonempty_openings += bool(candidates)
        if any(
            key in payload
            for key in ("rawRows", "parsedRows", "rejectedRows", "admissionDenominator")
        ):
            raw_denominator_sessions += 1
        opening_hashes.append(
            {"path": f"{path.parent.name}/{path.name}", "sha256": digest}
        )
    has_security_identity = any(
        key.lower() in SECURITY_ID_KEYS
        for row in captures[:1]
        for key in row
    )
    return {
        "datasetId": "candidateOutcomeHistory",
        "path": [str(captures_path), str(outcomes_path), str(opening_root)],
        "present": bool(captures or outcomes or opening_files),
        "authority": RESEARCH_ONLY,
        "source": ["persisted candidate captures", "derived outcome maintenance"],
        "schemaVersion": "CSV_AND_CAPTURE_JSON_MIXED",
        "priceBasis": "CAPTURE_PRICE_PLUS_DERIVED_OUTCOMES",
        "recordCount": len(captures),
        "outcomeRecordCount": len(outcomes),
        "completeOutcomeCount": complete_outcomes,
        "symbolCount": len(capture_symbols),
        "firstTimestamp": capture_times[0] if capture_times else None,
        "lastTimestamp": capture_times[-1] if capture_times else None,
        "selectedRowCount": selected,
        "reviewedRowCount": reviewed,
        "openingSessionCount": len(opening_files),
        "openingCandidateCount": opening_candidate_count,
        "nonemptyOpeningSessionCount": nonempty_openings,
        "emptyOpeningSessionCount": len(opening_files) - nonempty_openings,
        "rawAdmissionDenominatorSessionCount": raw_denominator_sessions,
        "fullRejectedCandidateHistory": raw_denominator_sessions == len(opening_files) and bool(opening_files),
        "stableSecurityIdentity": has_security_identity,
        "corporateActionLineage": False,
        "openingFingerprint": fingerprint_payload(opening_hashes),
        "captureFileSha256": _sha256_file(captures_path),
        "outcomeFileSha256": _sha256_file(outcomes_path),
        "limitations": [
            "Historical rows preserve qualified candidates, not a complete point-in-time rejected universe.",
            "Ticker plus capture time is not a durable security identity.",
            "Outcome rows do not provide a corporate-action-safe source lineage.",
            "Legacy selected/reviewed flags are not an immutable setup/outcome denominator.",
            "An empty legacy opening capture is not accepted as a strategy NO_TRADE without separate integrity evidence.",
        ],
    }


def _inventory_successor_setup(root: Path) -> dict[str, Any]:
    if not root.exists():
        return _missing_dataset(
            "successorSetupProspective", root, PROSPECTIVE_RESEARCH, "SETUP-002"
        )
    charter_path = root / "sample-charter.json"
    activation_path = root / "activation.json"
    charter = _read_json(charter_path) if charter_path.exists() else {}
    activation = _read_json(activation_path) if activation_path.exists() else {}
    pass_one = 0
    pass_two = 0
    other_packets = 0
    hashes: list[dict[str, str]] = []
    for path in sorted(root.rglob("*.json")):
        payload, digest = _read_json_with_hash(path)
        if not isinstance(payload, Mapping):
            raise ResearchDataInventoryError(f"SETUP-002 packet was invalid: {path}")
        packet_pass = payload.get("pass")
        if packet_pass == "PASS_1_OUTCOME_BLIND_DECISION":
            pass_one += 1
        elif packet_pass == "PASS_2_TERMINAL_OUTCOME":
            pass_two += 1
        elif path not in (charter_path, activation_path):
            other_packets += 1
        hashes.append({"path": str(path.relative_to(root)), "sha256": digest})
    return {
        "datasetId": "successorSetupProspective",
        "path": str(root),
        "present": True,
        "authority": PROSPECTIVE_RESEARCH,
        "source": ["SETUP-002 write-once observer"],
        "schemaVersion": activation.get("schemaVersion") or charter.get("schemaVersion"),
        "sampleId": activation.get("sampleId") or charter.get("sampleId"),
        "status": activation.get("status") or charter.get("status") or "UNVERIFIED",
        "activatedAt": activation.get("activatedAt"),
        "firstEligibleSessionDate": activation.get("firstEligibleSessionDate"),
        "expectedGitHead": activation.get("expectedGitHead"),
        "executionAuthority": activation.get("executionAuthority") or "NONE",
        "passOneCount": pass_one,
        "passTwoCount": pass_two,
        "otherPacketCount": other_packets,
        "recordCount": pass_one + pass_two,
        "symbolCount": 0,
        "stableSecurityIdentity": False,
        "corporateActionLineage": False,
        "partitionFingerprint": fingerprint_payload(hashes),
        "limitations": [
            "The sample is prospective and may currently contain zero eligible sessions.",
            "The provider-bound evaluation ceiling preserves exclusions but does not create broad universe history.",
            "Ticker remains the security identity in the current research packets.",
        ],
    }


def _universe_integrity(datasets: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    stable = any(bool(item.get("stableSecurityIdentity")) for item in datasets)
    actions = any(bool(item.get("corporateActionLineage")) for item in datasets)
    return {
        "stableSecurityIdentityAvailable": stable,
        "symbolChangeHistoryAvailable": False,
        "renamedSecurityContinuityAvailable": False,
        "delistedSecurityCoverageAvailable": False,
        "pointInTimeUniverseMembershipAvailable": False,
        "corporateActionEventLineageAvailable": actions,
        "survivorshipBiasControl": "INSUFFICIENT",
        "classification": INSUFFICIENT,
        "reason": (
            "All inspected histories are ticker-keyed and no point-in-time universe, "
            "symbol lineage, delisting history, or corporate-action event chain is present."
        ),
    }


def _capability_matrix(
    datasets: Mapping[str, Mapping[str, Any]],
    universe: Mapping[str, Any],
) -> list[dict[str, Any]]:
    minute = datasets["canonicalSchwabMinute"]
    daily = datasets["canonicalSchwabDaily"]
    research_daily = datasets["researchDaily263"]
    candidates = datasets["candidateOutcomeHistory"]
    setup = datasets["successorSetupProspective"]
    minute_sessions = int(minute.get("sessionDateCount") or 0)
    minute_symbols = int(minute.get("symbolCount") or 0)
    daily_symbols = int(daily.get("symbolCount") or 0)
    research_daily_symbols = int(research_daily.get("symbolCount") or 0)
    research_daily_deep_symbols = int(
        research_daily.get("symbolsWithAtLeast200Bars") or 0
    )
    setup_passes = int(setup.get("passOneCount") or 0)
    full_denominator = bool(candidates.get("fullRejectedCandidateHistory"))
    identity_safe = bool(universe.get("stableSecurityIdentityAvailable")) and bool(
        universe.get("corporateActionEventLineageAvailable")
    )
    return [
        _capability(
            "dailyTechnicalPatterns",
            PARTIAL if research_daily_deep_symbols >= 200 else INSUFFICIENT,
            "At least 200 adjusted Daily bars per symbol plus event-level adjustment and security lineage.",
            (
                f"Research Daily covers {research_daily_symbols} symbols, including "
                f"{research_daily_deep_symbols} with at least 200 bars, while canonical Daily covers "
                f"{daily_symbols}; adjustment-event and security lineage are absent."
            ),
        ),
        _capability(
            "intradayTechnicalPatternsAndAnalogs",
            INSUFFICIENT,
            "At least 60 complete canonical sessions across a broad candidate universe.",
            f"Canonical minute history covers {minute_symbols} symbols and {minute_sessions} session dates.",
        ),
        _capability(
            "premarketStructure",
            INSUFFICIENT,
            "Repeated complete 04:00-09:29 ET histories for candidate and benchmark symbols.",
            (
                f"Only {minute_sessions} session dates exist and current evidence does not prove "
                "complete true 04:00-07:00 ET coverage."
            ),
        ),
        _capability(
            "failedBreakouts",
            INSUFFICIENT,
            "Prospective immutable breakout triggers linked to complete post-trigger minute outcomes.",
            "Current candidate history is not a complete setup-identified prospective denominator.",
        ),
        _capability(
            "continuationPullbackReclaimStatistics",
            INSUFFICIENT if setup_passes == 0 else PARTIAL,
            "Prospective SETUP-002 Pass 1/Pass 2 pairs with a frozen denominator.",
            f"SETUP-002 is activated but currently has {setup_passes} Pass 1 observations.",
        ),
        _capability(
            "regimeConditioning",
            INSUFFICIENT,
            "Candidate outcomes aligned to broad benchmark/regime evidence over multiple regimes.",
            "Benchmark minute history is narrow and no broad point-in-time universe or regime outcome panel exists.",
        ),
        _capability(
            "eventReactionStudies",
            INSUFFICIENT,
            "Durable issuer/security identity plus attributed event time, type, and surprise context.",
            "Current catalyst and ticker records do not provide a survivor-safe event/security panel.",
        ),
        _capability(
            "timeOfDayEffects",
            INSUFFICIENT,
            "Complete intraday sessions across enough symbols/days to separate clock effects from selection effects.",
            f"Only {minute_symbols} symbols and {minute_sessions} canonical minute dates are present.",
        ),
        _capability(
            "rankAndSetupConditionedOutcomes",
            PARTIAL if int(candidates.get("recordCount") or 0) else INSUFFICIENT,
            "Full admitted/rejected denominator with immutable setup identity and terminal outcomes.",
            (
                f"{candidates.get('recordCount', 0)} candidate rows exist, but complete rejected history is "
                f"{'present' if full_denominator else 'absent'}."
            ),
        ),
        _capability(
            "historicalAnalogModeling",
            INSUFFICIENT if not identity_safe else UNVERIFIED,
            "Broad survivor-safe, corporate-action-safe feature/outcome panel with walk-forward splits.",
            "Stable security identity, delisting coverage, point-in-time membership, and action lineage are absent.",
        ),
    ]


def _proven_gaps(
    datasets: Mapping[str, Mapping[str, Any]],
    universe: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        _gap(
            "CANONICAL_INTRADAY_DEPTH_AND_BREADTH",
            "Canonical one-minute OHLCV, session labels, gap/correction lineage, at least 60 complete sessions per studied symbol.",
            f"Current store: {datasets['canonicalSchwabMinute'].get('symbolCount', 0)} symbols / "
            f"{datasets['canonicalSchwabMinute'].get('sessionDateCount', 0)} session dates.",
            "CANONICAL_RESEARCH_EVIDENCE_ONLY",
            "No execution, scoring, or selection authority.",
            "Existing Schwab backfill plus prospective collection reaches the required panel with verified completeness.",
        ),
        _gap(
            "EXTENDED_SESSION_TIMESTAMP_SEMANTICS",
            "Provider-session identity and timestamp semantics that distinguish true premarket, regular, after-hours, and unavailable overnight intervals.",
            f"The canonical minute store includes {datasets['canonicalSchwabMinute'].get('sessionCoverage', {}).get('OUTSIDE_STANDARD_EQUITY_SESSIONS', 0)} bars outside standard 04:00-20:00 ET equity sessions.",
            "RESEARCH_SESSION_CLASSIFICATION_ONLY",
            "No overnight execution authority and no reinterpretation of preserved timestamps.",
            "Preserved provider evidence and contract tests deterministically classify every timestamp without inventing unavailable sessions.",
        ),
        _gap(
            "SECURITY_MASTER_AND_SYMBOL_CONTINUITY",
            "Durable security identifier, ticker effective dates, rename/delist history, and point-in-time universe membership.",
            str(universe.get("reason")),
            "RESEARCH_IDENTITY_ONLY",
            "No broker/account identity and no automatic symbol substitution.",
            "Every studied row resolves to a durable identity with tested rename/delist continuity.",
        ),
        _gap(
            "CORPORATE_ACTION_PRICE_BASIS_LINEAGE",
            "Raw bars, adjusted analysis bars, effective action timestamps, factors, and transformation lineage.",
            "Adjusted Daily values exist, but no per-event factors or raw-to-adjusted lineage exist.",
            "ANALYSIS_TRANSFORMATION_ONLY",
            "Raw provider evidence must remain immutable; no strategy bonus or authority.",
            "Split fixtures and real preserved cases prove returns, levels, ATR, patterns, and volume remain basis-consistent.",
        ),
        _gap(
            "PROSPECTIVE_OPPORTUNITY_DENOMINATOR",
            "Every admitted, rejected, provider-bound, regime-vetoed, and unavailable candidate with immutable setup/outcome identity.",
            "Legacy history contains qualified candidates but not a complete rejected point-in-time denominator.",
            "PROSPECTIVE_RESEARCH_ONLY",
            "No retrospective trade creation and no rewriting prior samples.",
            "A prospective sample preserves every expected decision opportunity and terminal data failure.",
        ),
        _gap(
            "EVENT_ATTRIBUTION_HISTORY",
            "Issuer/security identity, event type/time, relationship, expected-versus-actual result, and source lineage.",
            "Current catalyst records are insufficient for survivor-safe event reaction statistics.",
            "RESEARCH_ONLY",
            "No catalyst score, readiness, or execution authority.",
            "Attributed event fixtures and prospective records support deterministic event-window studies.",
        ),
    ]


def render_inventory_markdown(inventory: Mapping[str, Any]) -> str:
    lines = [
        "# ARGUS-RESEARCH-DATA-001 Research Data Inventory",
        "",
        f"- As of: `{inventory['asOf']}`",
        f"- Classification: `{inventory['classification']}`",
        f"- Inventory fingerprint: `{inventory['inventoryFingerprint']}`",
        f"- Execution authority: `{inventory['executionAuthority']}`",
        f"- Provider selection: `{inventory['providerSelection']}`",
        "",
        "## Dataset Inventory",
        "",
        "| Dataset | Authority | Records | Symbols | Coverage | Identity / action lineage |",
        "|---|---:|---:|---:|---|---|",
    ]
    for dataset in inventory["datasets"]:
        coverage = _coverage_text(dataset)
        lineage = (
            f"security={str(bool(dataset.get('stableSecurityIdentity'))).lower()}, "
            f"actions={str(bool(dataset.get('corporateActionLineage'))).lower()}"
        )
        lines.append(
            f"| {dataset['datasetId']} | {dataset['authority']} | "
            f"{dataset.get('recordCount', 0)} | {dataset.get('symbolCount', 0)} | "
            f"{coverage} | {lineage} |"
        )
    lines.extend(
        [
            "",
            "## Research Capability Matrix",
            "",
            "| Research use | Status | Evidence | Minimum requirement |",
            "|---|---:|---|---|",
        ]
    )
    for item in inventory["capabilityMatrix"]:
        lines.append(
            f"| {item['researchUse']} | {item['status']} | {item['evidence']} | "
            f"{item['minimumRequirement']} |"
        )
    lines.extend(["", "## Universe Integrity", ""])
    universe = inventory["universeIntegrity"]
    lines.extend(
        [
            f"- Classification: `{universe['classification']}`",
            f"- Stable security identity: `{universe['stableSecurityIdentityAvailable']}`",
            f"- Symbol-change history: `{universe['symbolChangeHistoryAvailable']}`",
            f"- Delisted-security coverage: `{universe['delistedSecurityCoverageAvailable']}`",
            f"- Point-in-time membership: `{universe['pointInTimeUniverseMembershipAvailable']}`",
            f"- Corporate-action event lineage: `{universe['corporateActionEventLineageAvailable']}`",
            f"- Finding: {universe['reason']}",
            "",
            "## Proven Gaps",
            "",
        ]
    )
    for gap in inventory["provenGaps"]:
        lines.extend(
            [
                f"### {gap['gapId']}",
                "",
                f"- Required: {gap['requiredFieldsAndDepth']}",
                f"- Current evidence: {gap['currentEvidence']}",
                f"- Proposed authority: `{gap['proposedAuthority']}`",
                f"- Denied authority: {gap['deniedAuthority']}",
                f"- Cost: `{gap['cost']}`",
                f"- Exit condition: {gap['exitCondition']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Provider-Minimal Decision",
            "",
            "No new provider is selected or recommended by this task. Existing Schwab history, "
            "the current research Daily cache, and prospective evidence must be measured against "
            "the explicit exit conditions before procurement is considered.",
            "",
            "This inventory makes no edge, profitability, scoring, readiness, selection, broker, "
            "Paper, Shadow, or live-execution claim.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_inventory_outputs(
    inventory: Mapping[str, Any],
    *,
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_bytes = (
        json.dumps(inventory, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    ).encode("ascii")
    markdown_bytes = render_inventory_markdown(inventory).encode("ascii")
    _write_once(json_path, json_bytes)
    _write_once(markdown_path, markdown_bytes)


def fingerprint_payload(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest().upper()


def _capability(name: str, status: str, minimum: str, evidence: str) -> dict[str, str]:
    return {
        "researchUse": name,
        "status": status,
        "minimumRequirement": minimum,
        "evidence": evidence,
    }


def _gap(
    gap_id: str,
    requirement: str,
    current: str,
    authority: str,
    denied: str,
    exit_condition: str,
) -> dict[str, str]:
    return {
        "gapId": gap_id,
        "requiredFieldsAndDepth": requirement,
        "currentEvidence": current,
        "proposedAuthority": authority,
        "deniedAuthority": denied,
        "cost": "NOT_EVALUATED_NO_PROVIDER_SELECTED",
        "exitCondition": exit_condition,
    }


def _missing_dataset(dataset_id: str, path: Path, authority: str, source: str) -> dict[str, Any]:
    return {
        "datasetId": dataset_id,
        "path": str(path),
        "present": False,
        "authority": authority,
        "source": [source],
        "recordCount": 0,
        "symbolCount": 0,
        "stableSecurityIdentity": False,
        "corporateActionLineage": False,
        "limitations": ["Expected local evidence is missing."],
    }


def _coverage_text(dataset: Mapping[str, Any]) -> str:
    first = dataset.get("firstTimestamp") or dataset.get("firstDate")
    last = dataset.get("lastTimestamp") or dataset.get("lastDate")
    if first or last:
        return f"{first or 'unknown'} to {last or 'unknown'}"
    if dataset.get("firstEligibleSessionDate"):
        return f"eligible from {dataset['firstEligibleSessionDate']}"
    return "none"


def _derived_market_session(timestamp: datetime) -> str:
    local = timestamp.astimezone(EASTERN).time()
    if time(4, 0) <= local < time(9, 30):
        return "PREMARKET"
    if time(9, 30) <= local < time(16, 0):
        return "REGULAR"
    if time(16, 0) <= local < time(20, 0):
        return "AFTER_HOURS"
    return "OUTSIDE_STANDARD_EQUITY_SESSIONS"


def _contains_key(value: Any, keys: frozenset[str]) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).replace("_", "").lower() in keys:
                return True
            if _contains_key(nested, keys):
                return True
    elif isinstance(value, list):
        return any(_contains_key(item, keys) for item in value)
    return False


def _required_text(payload: Mapping[str, Any], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ResearchDataInventoryError(f"Missing {key} in {path}")
    return value.strip()


def _read_json(path: Path) -> Any:
    value, _ = _read_json_with_hash(path)
    return value


def _read_json_with_hash(path: Path) -> tuple[Any, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ResearchDataInventoryError(f"Unable to read local evidence: {path}") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise ResearchDataInventoryError(f"Local evidence exceeded the size bound: {path}")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchDataInventoryError(f"Local evidence was invalid JSON: {path}") from exc
    return payload, hashlib.sha256(raw).hexdigest().upper()


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except (OSError, csv.Error) as exc:
        raise ResearchDataInventoryError(f"Local evidence was invalid CSV: {path}") from exc


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest().upper()
    except OSError as exc:
        raise ResearchDataInventoryError(f"Unable to hash local evidence: {path}") from exc


def _csv_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _parse_aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchDataInventoryError(f"Timestamp was invalid: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchDataInventoryError(f"Timestamp lacked an explicit offset: {value}")
    return parsed


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == content:
            return
        raise ResearchDataInventoryError(f"Conflicting inventory output already exists: {path}")
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except OSError as exc:
        raise ResearchDataInventoryError(f"Unable to write inventory output: {path}") from exc


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    defaults = ResearchDataPaths.defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical-minute-root", type=Path, default=defaults.canonical_minute_root)
    parser.add_argument("--canonical-daily-root", type=Path, default=defaults.canonical_daily_root)
    parser.add_argument("--research-daily", type=Path, default=defaults.research_daily_path)
    parser.add_argument("--analysis-captures", type=Path, default=defaults.analysis_captures_path)
    parser.add_argument("--analysis-outcomes", type=Path, default=defaults.analysis_outcomes_path)
    parser.add_argument("--opening-captures-root", type=Path, default=defaults.opening_captures_root)
    parser.add_argument("--successor-setup-root", type=Path, default=defaults.successor_setup_root)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    paths = ResearchDataPaths(
        canonical_minute_root=args.canonical_minute_root,
        canonical_daily_root=args.canonical_daily_root,
        research_daily_path=args.research_daily,
        analysis_captures_path=args.analysis_captures,
        analysis_outcomes_path=args.analysis_outcomes,
        opening_captures_root=args.opening_captures_root,
        successor_setup_root=args.successor_setup_root,
    )
    inventory = build_research_data_inventory(paths, as_of=args.as_of)
    write_inventory_outputs(
        inventory,
        json_path=args.output_json,
        markdown_path=args.output_md,
    )
    print(
        json.dumps(
            {
                "classification": inventory["classification"],
                "inventoryFingerprint": inventory["inventoryFingerprint"],
                "outputJson": str(args.output_json),
                "outputMarkdown": str(args.output_md),
                "networkAccess": inventory["networkAccess"],
                "executionAuthority": inventory["executionAuthority"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
