"""Deterministic two-pass research for premarket and opening setup structure."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 1
DECISION_ENGINE_VERSION = "premarket-structure-decision-research-v1"
OUTCOME_ENGINE_VERSION = "premarket-structure-outcome-research-v2"
EASTERN = ZoneInfo("America/New_York")
CANONICAL_SOURCE = "schwab_marketdata_v1_pricehistory:v1"
RETROSPECTIVE_HISTORY = "RETROSPECTIVE_CANONICAL_HISTORY_RESEARCH_ONLY"
TRUE_OVERNIGHT_UNOBSERVED = "TRUE_OVERNIGHT_PATH_UNOBSERVED"
EXPECTED_CANDIDATES = ("CRWV", "NBIS", "IREN", "HPE", "SMCI")
BENCHMARKS = ("SPY", "QQQ", "IWM")
MAX_ENTRY_EXTENSION_PCT = 0.25
MIN_EXECUTION_RR = 1.5


class PremarketStructureResearchError(RuntimeError):
    """Raised when research evidence is incomplete, conflicting, or altered."""


@dataclass(frozen=True)
class ResearchBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    state: str
    first_received_at: datetime
    identity: str


def build_decision_packet(
    *,
    trade_plan_path: Path,
    capture_path: Path,
    minute_store_root: Path,
    backfill_result_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Build immutable Pass 1 using completed bars before the quote-time minute."""

    trade_report = _read_json(trade_plan_path)
    capture = _read_json(capture_path)
    backfill = _read_json(backfill_result_path)
    candidates = _candidate_rows(trade_report)
    symbols = tuple(row["symbol"] for row in candidates)
    if symbols != EXPECTED_CANDIDATES:
        raise PremarketStructureResearchError(
            f"Expected Aug. 13 candidates {EXPECTED_CANDIDATES}, received {symbols}."
        )
    if backfill.get("status") != "COMPLETE":
        raise PremarketStructureResearchError("Historical backfill is not terminal COMPLETE.")
    expected_backfill_symbols = set(EXPECTED_CANDIDATES + BENCHMARKS)
    actual_backfill_symbols = {
        str(item.get("symbol") or "") for item in backfill.get("symbols", [])
    }
    if actual_backfill_symbols != expected_backfill_symbols:
        raise PremarketStructureResearchError("Backfill symbol scope is not the bounded universe.")

    decision_at = max(_quote_receipt(row) for row in candidates)
    session_date = decision_at.astimezone(EASTERN).date().isoformat()
    completed_cutoff = decision_at.astimezone(EASTERN).replace(
        minute=decision_at.astimezone(EASTERN).minute,
        second=0,
        microsecond=0,
    )
    if completed_cutoff.time() != time(9, 35):
        raise PremarketStructureResearchError(
            f"Expected an approximately 09:35 ET decision, received {decision_at.isoformat()}."
        )

    source_hashes = {
        "capture": _sha256_file(capture_path),
        "tradePlanReport": _sha256_file(trade_plan_path),
        "backfillResult": _sha256_file(backfill_result_path),
    }
    candidate_results: list[dict[str, Any]] = []
    for row in candidates:
        symbol = row["symbol"]
        partition_path = minute_store_root / session_date / f"{symbol}.json"
        bars = load_research_bars(partition_path, expected_symbol=symbol)
        source_hashes[f"minute:{symbol}"] = _sha256_file(partition_path)
        available = [bar for bar in bars if bar.timestamp < completed_cutoff]
        if not available:
            raise PremarketStructureResearchError(f"No completed bars existed for {symbol}.")
        if any(bar.first_received_at <= decision_at for bar in bars):
            raise PremarketStructureResearchError(
                f"{symbol} history is not wholly retrospective; mixed availability is ambiguous."
            )
        candidate_results.append(
            reconstruct_candidate(
                row=row,
                bars=available,
                decision_at=decision_at,
                completed_cutoff=completed_cutoff,
            )
        )

    regime_results = []
    for symbol in BENCHMARKS:
        partition_path = minute_store_root / session_date / f"{symbol}.json"
        bars = load_research_bars(partition_path, expected_symbol=symbol)
        if any(bar.first_received_at <= decision_at for bar in bars):
            raise PremarketStructureResearchError(
                f"{symbol} benchmark history has ambiguous evidence availability."
            )
        source_hashes[f"minute:{symbol}"] = _sha256_file(partition_path)
        available = [bar for bar in bars if bar.timestamp < completed_cutoff]
        regime_results.append(_benchmark_context(symbol, available))

    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "engineVersion": DECISION_ENGINE_VERSION,
        "task": "ARGUS-SETUP-001",
        "pass": "PASS_1_DECISION_RECONSTRUCTION",
        "decisionAt": decision_at.isoformat(),
        "completedBarCutoff": completed_cutoff.isoformat(),
        "sessionDate": session_date,
        "outcomeEvidenceInspected": False,
        "productionAuthority": "NONE_RESEARCH_ONLY",
        "strategySemanticsChanged": False,
        "evidenceAvailability": {
            "actualRuntimeCandles": "UNAVAILABLE_AT_DECISION",
            "backfilledCandles": RETROSPECTIVE_HISTORY,
            "trueOvernightPath": TRUE_OVERNIGHT_UNOBSERVED,
            "earliestTrustedPremarket": "07:00 ET where a returned bar exists",
        },
        "frozenRules": {
            "maxEntryExtensionPct": MAX_ENTRY_EXTENSION_PCT,
            "minimumExecutionRewardRisk": MIN_EXECUTION_RR,
            "thresholdStatus": "EXISTING_RULES_UNCHANGED",
            "verticalityThresholds": "EXPLORATORY_NOT_PRODUCTION",
        },
        "sourceHashes": dict(sorted(source_hashes.items())),
        "captureIdentity": {
            "captureTime": trade_report["metadata"]["source_capture_time"],
            "captureProvider": trade_report["metadata"]["source_provider"],
            "candidateCount": len(candidates),
            "captureStatus": capture.get("status") or "PRESERVED",
        },
        "marketRegime": {
            "preservedLabel": _preserved_market_regime(capture),
            "benchmarks": regime_results,
            "researchInterpretation": _market_regime_interpretation(regime_results),
        },
        "candidates": candidate_results,
        "limitations": [
            "The actual 09:35 runtime had no Aug. 13 canonical candles.",
            "Schwab history was fetched after the session and is research-only.",
            "The returned authoritative intraday path begins at 07:00 ET, not 04:00 ET.",
            "Volume-weighted averages are deterministic bar-derived approximations, not provider VWAP fields.",
            "Five candidates from one session cannot freeze strategy thresholds.",
        ],
    }
    payload["decisionFingerprint"] = packet_fingerprint(payload)
    _write_once_json(output_path, payload)
    return payload


def build_outcome_packet(
    *,
    decision_path: Path,
    minute_store_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Build Pass 2 only after validating the immutable Pass 1 fingerprint."""

    decision = _read_json(decision_path)
    expected = decision.get("decisionFingerprint")
    if not expected or expected != packet_fingerprint(decision):
        raise PremarketStructureResearchError("Pass 1 fingerprint is missing or invalid.")
    if decision.get("outcomeEvidenceInspected") is not False:
        raise PremarketStructureResearchError("Pass 1 is not an outcome-blind decision packet.")
    cutoff = _parse_datetime(decision["completedBarCutoff"])
    session_date = str(decision["sessionDate"])
    results = []
    outcome_hashes: dict[str, str] = {}
    for candidate in decision["candidates"]:
        symbol = candidate["symbol"]
        partition_path = minute_store_root / session_date / f"{symbol}.json"
        if _sha256_file(partition_path) != decision["sourceHashes"][f"minute:{symbol}"]:
            raise PremarketStructureResearchError(
                f"{symbol} source changed after Pass 1 was frozen."
            )
        bars = load_research_bars(partition_path, expected_symbol=symbol)
        later = [bar for bar in bars if bar.timestamp >= cutoff]
        outcome_hashes[f"minute:{symbol}"] = _sha256_file(partition_path)
        results.append(_candidate_outcome(candidate, later))

    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "engineVersion": OUTCOME_ENGINE_VERSION,
        "task": "ARGUS-SETUP-001",
        "pass": "PASS_2_OUTCOME_REVIEW",
        "decisionFingerprint": expected,
        "decisionPacketSha256": _sha256_file(decision_path),
        "outcomeEvidenceInspected": True,
        "productionAuthority": "NONE_RESEARCH_ONLY",
        "sourceHashes": dict(sorted(outcome_hashes.items())),
        "candidates": results,
        "interpretationRule": (
            "Later outcomes describe the frozen research decision; they do not validate or alter its rules."
        ),
    }
    payload["outcomeFingerprint"] = packet_fingerprint(payload)
    _write_once_json(output_path, payload)
    return payload


def reconstruct_candidate(
    *,
    row: Mapping[str, Any],
    bars: Sequence[ResearchBar],
    decision_at: datetime,
    completed_cutoff: datetime,
) -> dict[str, Any]:
    symbol = str(row["symbol"])
    trade_plan = row["trade_plan"]
    levels = row["technical_levels"]
    market = row["market_data"]
    original_entry = float(trade_plan["bullish_entry"])
    original_stop = float(trade_plan["bullish_stop"])
    original_target = float(trade_plan["bullish_target_1"])
    ask = float(market["current_ask"])
    bid = float(market["current_bid"])
    atr = float(levels["atr"])

    premarket = _between(bars, time(4, 0), time(9, 30))
    last_15 = _between(bars, time(9, 15), time(9, 30))
    opening = _between(bars, time(9, 30), time(9, 35))
    if len(last_15) != 15 or len(opening) != 5:
        raise PremarketStructureResearchError(
            f"{symbol} lacks the required completed 15-minute/opening windows."
        )
    pm = aggregate_bars(premarket)
    prior_15 = aggregate_bars(last_15)
    opening_range = aggregate_bars(opening)
    first_cross = _first_cross(premarket, original_entry)
    crossed_before_earliest = (
        bool(premarket) and premarket[0].open > original_entry and first_cross == premarket[0]
    )
    original_cross_status = "NOT_CROSSED_PREMARKET"
    original_cross_time = None
    if first_cross is not None:
        if crossed_before_earliest:
            original_cross_status = "BEFORE_EARLIEST_TRUSTED_BAR"
        else:
            original_cross_status = "CROSSED_PREMARKET"
            original_cross_time = first_cross.timestamp.isoformat()

    original_model = _model_plan(
        name="MODEL_A_DAILY_REFERENCE_ONLY",
        family="OPENING_BREAKOUT",
        trigger=original_entry,
        stop=original_stop,
        target=original_target,
        ask=ask,
        evidence_ids=[str(trade_plan["setup_evidence"]["fingerprint"])],
    )
    last_15_model = _model_plan(
        name="MODEL_B_PRIOR_15_MINUTE_DOMINANT",
        family="CONTINUATION_BREAKOUT",
        trigger=prior_15["high"],
        stop=prior_15["low"],
        target=None,
        ask=ask,
        evidence_ids=[bar.identity for bar in last_15],
    )
    last_15_model["warning"] = (
        "The 15-minute aggregate is a feature, not independently proven setup chronology."
    )

    full_model = classify_full_structure(
        symbol=symbol,
        original_entry=original_entry,
        original_stop=original_stop,
        original_target=original_target,
        original_setup_fingerprint=str(trade_plan["setup_evidence"]["fingerprint"]),
        ask=ask,
        atr=atr,
        premarket=premarket,
        last_15=last_15,
        opening=opening,
    )
    original_crossed_before_decision = _first_cross(premarket + opening, original_entry) is not None
    original_model["lifecycleStatus"] = (
        "MISSED_ENTRY_BEFORE_DECISION"
        if original_crossed_before_decision
        else "PENDING_TRIGGER"
    )
    original_extension = _pct(ask, original_entry)
    result_class = _result_classification(
        original_cross_status=original_cross_status,
        original_crossed_before_decision=original_crossed_before_decision,
        original_model=original_model,
        full_model=full_model,
    )
    features = _verticality_features(
        bars=bars,
        premarket=premarket,
        last_15=last_15,
        opening=opening,
        prior_close=float(levels["previous_day_close"]),
        atr=atr,
        ask=ask,
    )
    return {
        "symbol": symbol,
        "rank": int(row["rank"]),
        "decisionAt": decision_at.isoformat(),
        "completedBarCutoff": completed_cutoff.isoformat(),
        "sourceTruth": {
            "quote": "PRESERVED_PROSPECTIVE_SCHWAB_QUOTE",
            "quoteSource": row["market_tape"]["field_provenance"]["current_ask"]["source"],
            "quoteEvidenceId": row["market_tape"]["field_provenance"]["current_ask"][
                "provider_timestamp"
            ],
            "candles": RETROSPECTIVE_HISTORY,
            "firstCandleReceivedAt": min(bar.first_received_at for bar in bars).isoformat(),
            "trueOvernightPath": TRUE_OVERNIGHT_UNOBSERVED,
            "earliestTrustedBar": min(bar.timestamp for bar in bars).isoformat(),
        },
        "priorReference": {
            "priorClose": float(levels["previous_day_close"]),
            "priorHigh": float(levels["previous_day_high"]),
            "priorLow": float(levels["previous_day_low"]),
            "originalEntry": original_entry,
            "originalStop": original_stop,
            "originalTarget1": original_target,
            "atr": atr,
            "sourceSetupFingerprint": trade_plan["setup_evidence"]["fingerprint"],
        },
        "premarket": {
            **pm,
            "firstOriginalCrossStatus": original_cross_status,
            "firstOriginalCrossAt": original_cross_time,
            "distanceFromOriginalEntryPctAtDecision": round(original_extension, 6),
            "vwapKind": "BAR_DERIVED_TYPICAL_PRICE_VOLUME_WEIGHTED_APPROXIMATION",
        },
        "last15": {
            **prior_15,
            "classification": classify_aggregate(prior_15),
            "relationshipToPremarketHighPct": round(_pct(prior_15["close"], pm["high"]), 6),
        },
        "openingRange": {
            **opening_range,
            "classification": classify_aggregate(opening_range),
            "acceptedAbovePremarketHigh": opening_range["close"] > pm["high"],
            "rejectedPremarketHigh": opening_range["high"] > pm["high"]
            and opening_range["close"] < pm["high"],
        },
        "decisionQuote": {
            "bid": bid,
            "ask": ask,
            "spreadPct": float(market["spread_percent"]),
            "originalExtensionPct": round(original_extension, 6),
            "distanceFromPremarketHighPct": round(_pct(ask, pm["high"]), 6),
            "distanceFromOpeningHighPct": round(_pct(ask, opening_range["high"]), 6),
            "distanceFromPremarketVwapPct": round(_pct(ask, pm["vwapApprox"]), 6),
            "originalExecutionRewardRisk": _execution_rr(
                entry=ask, stop=original_stop, target=original_target
            ),
        },
        "verticalityFeatures": features,
        "models": {
            "dailyOnly": original_model,
            "last15Only": last_15_model,
            "fullStructure": full_model,
        },
        "answers": _candidate_answers(
            original_cross_status=original_cross_status,
            original_cross_time=original_cross_time,
            original_crossed_before_decision=original_crossed_before_decision,
            original_model=original_model,
            last_15_model=last_15_model,
            full_model=full_model,
            result_class=result_class,
        ),
        "resultClassification": result_class,
    }


def classify_full_structure(
    *,
    symbol: str,
    original_entry: float,
    original_stop: float,
    original_target: float,
    original_setup_fingerprint: str,
    ask: float,
    atr: float,
    premarket: Sequence[ResearchBar],
    last_15: Sequence[ResearchBar],
    opening: Sequence[ResearchBar],
) -> dict[str, Any]:
    pm = aggregate_bars(premarket)
    l15 = aggregate_bars(last_15)
    op = aggregate_bars(opening)
    first_cross = _first_cross(premarket, original_entry)
    crossed_premarket = first_cross is not None
    crossed_opening = _first_cross(opening, original_entry) is not None
    if not crossed_premarket and not crossed_opening:
        plan = _model_plan(
            name="MODEL_C_FULL_STRUCTURE",
            family="OPENING_BREAKOUT",
            trigger=original_entry,
            stop=original_stop,
            target=original_target,
            ask=ask,
            evidence_ids=[original_setup_fingerprint] + [bar.identity for bar in opening],
        )
        plan.update(
            {
                "newSetup": False,
                "predecessorSetupFingerprint": original_setup_fingerprint,
                "chronology": "ORIGINAL_LEVEL_UNTOUCHED_PREMARKET_THEN_OPENING_RANGE",
                "researchFinding": "ORIGINAL_SETUP_REMAINS_CURRENT",
            }
        )
        return plan

    if crossed_opening and not crossed_premarket:
        return {
            "name": "MODEL_C_FULL_STRUCTURE",
            "family": "NO_NEW_STRUCTURE",
            "newSetup": False,
            "setupId": None,
            "predecessorSetupFingerprint": original_setup_fingerprint,
            "trigger": None,
            "stop": None,
            "targets": [],
            "executionRewardRisk": None,
            "extensionPct": None,
            "extensionStatus": "NOT_APPLICABLE",
            "hypotheticalDecision": "BLOCK",
            "researchFinding": "ORIGINAL_SETUP_CROSSED_BEFORE_DECISION_NO_SUCCESSOR",
            "chronology": "ORIGINAL_LEVEL_CROSSED_DURING_OPENING_NO_SUCCESSOR_STRUCTURE",
            "evidenceIds": [bar.identity for bar in premarket + opening],
        }

    pm_high_bar = max(premarket, key=lambda bar: (bar.high, -bar.timestamp.timestamp()))
    pullback_after_high = [bar for bar in premarket if bar.timestamp > pm_high_bar.timestamp]
    pullback_depth = (
        pm_high_bar.high - min(bar.low for bar in pullback_after_high)
        if pullback_after_high
        else 0.0
    )
    opening_high_bar = max(opening, key=lambda bar: (bar.high, -bar.timestamp.timestamp()))
    confirmation_after_opening_high = sum(
        bar.timestamp > opening_high_bar.timestamp for bar in opening
    )
    continuation_chronology = (
        pm_high_bar.timestamp.astimezone(EASTERN).time() < time(9, 15)
        and pullback_depth >= 0.15 * atr
        and l15["close"] < pm["high"]
        and op["high"] >= pm["high"]
        and confirmation_after_opening_high >= 1
    )
    if continuation_chronology:
        trigger = op["high"]
        if ask >= trigger:
            plan = _model_plan(
                name="MODEL_C_FULL_STRUCTURE",
                family="CONTINUATION_BREAKOUT",
                trigger=trigger,
                stop=max(l15["low"], op["low"]),
                target=None,
                ask=ask,
                evidence_ids=[bar.identity for bar in premarket + opening],
            )
            if plan["extensionStatus"] == "WITHIN_0_25_PCT" and plan[
                "executionRewardRisk"
            ] >= MIN_EXECUTION_RR:
                setup_id = _fingerprint(
                    {
                        "symbol": symbol,
                        "family": "CONTINUATION_BREAKOUT",
                        "trigger": trigger,
                        "stop": plan["stop"],
                        "predecessor": original_setup_fingerprint,
                        "evidenceIds": plan["evidenceIds"],
                    }
                )
                plan.update(
                    {
                        "newSetup": True,
                        "setupId": setup_id,
                        "predecessorSetupFingerprint": original_setup_fingerprint,
                        "chronology": "PREMARKET_IMPULSE_PULLBACK_THEN_COMPLETED_OPENING_RANGE_BREAK",
                        "researchFinding": "POTENTIAL_NEW_SETUP",
                    }
                )
                return plan
    reclaimed = _reclaim_event(premarket + opening, original_entry)
    return {
        "name": "MODEL_C_FULL_STRUCTURE",
        "family": "NO_NEW_STRUCTURE",
        "newSetup": False,
        "setupId": None,
        "predecessorSetupFingerprint": original_setup_fingerprint,
        "trigger": None,
        "stop": None,
        "targets": [],
        "executionRewardRisk": None,
        "extensionPct": None,
        "extensionStatus": "NOT_APPLICABLE",
        "hypotheticalDecision": "BLOCK",
        "researchFinding": "NO_NEW_DEFENSIBLE_STRUCTURE_BY_DECISION",
        "chronology": (
            "ORIGINAL_LEVEL_RECLAIMED_BUT_FRESH_TRIGGER_NOT_AVAILABLE"
            if reclaimed
            else "ORIGINAL_LEVEL_MISSED_THEN_VERTICAL_OR_UNCONFIRMED"
        ),
        "evidenceIds": [bar.identity for bar in premarket + opening],
    }


def aggregate_bars(bars: Sequence[ResearchBar]) -> dict[str, Any]:
    if not bars:
        raise PremarketStructureResearchError("Cannot aggregate an empty bar window.")
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    high_bar = max(ordered, key=lambda bar: (bar.high, -bar.timestamp.timestamp()))
    low_bar = min(ordered, key=lambda bar: (bar.low, bar.timestamp.timestamp()))
    volume = sum(bar.volume for bar in ordered)
    vwap = (
        sum(((bar.high + bar.low + bar.close) / 3.0) * bar.volume for bar in ordered)
        / volume
        if volume > 0
        else None
    )
    result = {
        "barCount": len(ordered),
        "firstTimestamp": ordered[0].timestamp.isoformat(),
        "lastTimestamp": ordered[-1].timestamp.isoformat(),
        "open": ordered[0].open,
        "high": high_bar.high,
        "highAt": high_bar.timestamp.isoformat(),
        "low": low_bar.low,
        "lowAt": low_bar.timestamp.isoformat(),
        "close": ordered[-1].close,
        "volume": volume,
        "range": high_bar.high - low_bar.low,
        "body": abs(ordered[-1].close - ordered[0].open),
        "upperWick": high_bar.high - max(ordered[0].open, ordered[-1].close),
        "lowerWick": min(ordered[0].open, ordered[-1].close) - low_bar.low,
        "vwapApprox": round(vwap, 6) if vwap is not None else None,
    }
    return result


def classify_aggregate(aggregate: Mapping[str, Any]) -> str:
    span = float(aggregate["range"])
    if span <= 0:
        return "AMBIGUOUS_STRUCTURE"
    open_price = float(aggregate["open"])
    close = float(aggregate["close"])
    body_ratio = abs(close - open_price) / span
    close_location = (close - float(aggregate["low"])) / span
    if close < open_price and body_ratio >= 0.4:
        return "PULLBACK"
    if float(aggregate["upperWick"]) / span >= 0.4 and close_location < 0.65:
        return "REJECTION"
    if body_ratio <= 0.3:
        return "CONSOLIDATION"
    if close > open_price and body_ratio >= 0.6 and close_location >= 0.75:
        return "CONTINUATION"
    return "AMBIGUOUS_STRUCTURE"


def load_research_bars(path: Path, *, expected_symbol: str) -> list[ResearchBar]:
    payload = _read_json(path)
    if payload.get("canonicalSource") != CANONICAL_SOURCE:
        raise PremarketStructureResearchError(f"Unexpected canonical source in {path}.")
    if payload.get("legacySourceMixed") is not False:
        raise PremarketStructureResearchError(f"Legacy source mixing detected in {path}.")
    if str(payload.get("symbol") or "").upper() != expected_symbol:
        raise PremarketStructureResearchError(f"Symbol mismatch in {path}.")
    expected_session_date = str(payload.get("sessionDate") or "")
    if not expected_session_date:
        raise PremarketStructureResearchError(f"Session date is missing in {path}.")
    bars: list[ResearchBar] = []
    for item in payload.get("bars", []):
        candle = item.get("canonicalCandle")
        versions = item.get("historyVersions")
        if item.get("state") not in {"RECONCILED", "CORRECTED", "HISTORY_ONLY_GAP_FILL"}:
            continue
        if not isinstance(candle, Mapping) or not isinstance(versions, list) or not versions:
            raise PremarketStructureResearchError(f"Incomplete canonical bar in {path}.")
        if candle.get("source") != CANONICAL_SOURCE or candle.get("ohlcvComplete") is not True:
            raise PremarketStructureResearchError(f"Untrusted candle in {path}.")
        if str(candle.get("symbol") or "").upper() != expected_symbol:
            raise PremarketStructureResearchError(f"Candle symbol mismatch in {path}.")
        if str(candle.get("sessionDate") or "") != expected_session_date:
            raise PremarketStructureResearchError(f"Candle session mismatch in {path}.")
        candle_timestamp = str(candle.get("timestamp") or "")
        expected_identity = (
            f"schwab-equity-1m:v1|{expected_symbol}|{candle_timestamp}"
        )
        if str(item.get("timestamp") or "") != candle_timestamp:
            raise PremarketStructureResearchError(f"Bar timestamp mismatch in {path}.")
        if str(item.get("minuteIdentity") or "") != expected_identity:
            raise PremarketStructureResearchError(f"Minute identity mismatch in {path}.")
        if versions[-1].get("candle") != candle:
            raise PremarketStructureResearchError(
                f"Canonical candle does not match the final history version in {path}."
            )
        values = [float(candle[key]) for key in ("open", "high", "low", "close", "volume")]
        if values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
            raise PremarketStructureResearchError(f"Invalid OHLC ordering in {path}.")
        bars.append(
            ResearchBar(
                symbol=expected_symbol,
                timestamp=_parse_datetime(candle_timestamp).astimezone(EASTERN),
                open=values[0],
                high=values[1],
                low=values[2],
                close=values[3],
                volume=values[4],
                source=str(candle["source"]),
                state=str(item["state"]),
                first_received_at=min(
                    _parse_datetime(str(version["firstReceivedAt"])) for version in versions
                ),
                identity=str(item["minuteIdentity"]),
            )
        )
    bars.sort(key=lambda bar: bar.timestamp)
    identities = [bar.identity for bar in bars]
    if len(identities) != len(set(identities)):
        raise PremarketStructureResearchError(f"Duplicate minute identities in {path}.")
    return bars


def packet_fingerprint(payload: Mapping[str, Any]) -> str:
    copy = dict(payload)
    copy.pop("decisionFingerprint", None)
    copy.pop("outcomeFingerprint", None)
    return _fingerprint(copy)


def _candidate_outcome(candidate: Mapping[str, Any], bars: Sequence[ResearchBar]) -> dict[str, Any]:
    model = candidate["models"]["fullStructure"]
    regular_bars = [
        bar
        for bar in bars
        if time(9, 35) <= bar.timestamp.astimezone(EASTERN).time() <= time(15, 55)
    ]
    if not regular_bars:
        return {
            "symbol": candidate["symbol"],
            "frozenDecision": model.get("hypotheticalDecision", "BLOCK"),
            "setupId": model.get("setupId"),
            "outcomeClass": "INSUFFICIENT_LATER_SESSION_EVIDENCE",
            "targetStopSequence": "UNAVAILABLE",
        }
    entry = float(candidate["decisionQuote"]["ask"])
    observation = {
        "source": RETROSPECTIVE_HISTORY,
        "classification": "POST_DECISION_MARKET_OBSERVATION_NOT_A_TRADE",
        "lastObservedAt": regular_bars[-1].timestamp.isoformat(),
        "lastClose": regular_bars[-1].close,
        "maximumHigh": max(bar.high for bar in regular_bars),
        "minimumLow": min(bar.low for bar in regular_bars),
        "maximumFavorableExcursionFromDecisionAskPct": round(
            _pct(max(bar.high for bar in regular_bars), entry), 6
        ),
        "maximumAdverseExcursionFromDecisionAskPct": round(
            _pct(min(bar.low for bar in regular_bars), entry), 6
        ),
    }
    if model.get("hypotheticalDecision") != "ALLOW":
        return {
            "symbol": candidate["symbol"],
            "frozenDecision": model.get("hypotheticalDecision", "BLOCK"),
            "setupId": model.get("setupId"),
            "outcomeClass": "NO_HYPOTHETICAL_TRADE",
            "mfePct": None,
            "maePct": None,
            "targetStopSequence": "NOT_APPLICABLE",
            "note": "No later outcome is promoted into a trade when Pass 1 blocked the setup.",
            "postDecisionObservation": observation,
            "currentMhRejectionAvoidedHypotheticalLoss": "INDETERMINATE_NO_FROZEN_TRADE",
        }
    stop = float(model["stop"])
    target = float(model["targets"][0])
    target_at = next((bar.timestamp for bar in regular_bars if bar.high >= target), None)
    stop_at = next((bar.timestamp for bar in regular_bars if bar.low <= stop), None)
    if target_at and stop_at and target_at == stop_at:
        sequence = "AMBIGUOUS_SAME_BAR"
    elif target_at and (not stop_at or target_at < stop_at):
        sequence = "TARGET_FIRST"
    elif stop_at:
        sequence = "STOP_FIRST"
    else:
        sequence = "NEITHER"
    terminal_at = None
    if sequence == "TARGET_FIRST":
        terminal_at = target_at
    elif sequence == "STOP_FIRST":
        terminal_at = stop_at
    elif sequence == "AMBIGUOUS_SAME_BAR":
        terminal_at = target_at
    lifecycle_bars = [
        bar for bar in regular_bars if terminal_at is None or bar.timestamp <= terminal_at
    ]
    mfe = max(bar.high for bar in lifecycle_bars) - entry
    mae = min(bar.low for bar in lifecycle_bars) - entry
    decision_at = _parse_datetime(str(candidate["decisionAt"]))
    return {
        "symbol": candidate["symbol"],
        "frozenDecision": "ALLOW",
        "setupId": model.get("setupId"),
        "hypotheticalEntry": entry,
        "stop": stop,
        "target1": target,
        "mfePct": round((mfe / entry) * 100.0, 6),
        "maePct": round((mae / entry) * 100.0, 6),
        "targetStopSequence": sequence,
        "targetAt": target_at.isoformat() if target_at else None,
        "triggerAt": decision_at.isoformat(),
        "minutesToTrigger": 0.0,
        "stopAt": stop_at.isoformat() if stop_at else None,
        "terminalAt": terminal_at.isoformat() if terminal_at else None,
        "minutesToTerminal": (
            round((terminal_at - decision_at).total_seconds() / 60.0, 3)
            if terminal_at
            else None
        ),
        "currentMhRejectionAvoidedHypotheticalLoss": sequence == "STOP_FIRST",
        "postDecisionObservation": observation,
        "outcomeClass": "RESEARCH_HYPOTHETICAL_ONLY",
    }


def _model_plan(
    *,
    name: str,
    family: str,
    trigger: float,
    stop: float,
    target: float | None,
    ask: float,
    evidence_ids: Iterable[str],
) -> dict[str, Any]:
    risk = trigger - stop
    if risk <= 0:
        raise PremarketStructureResearchError(f"{name} stop is not below trigger.")
    target = target if target is not None else trigger + 2.0 * risk
    extension = _pct(ask, trigger)
    if ask < trigger:
        extension_status = "TRIGGER_NOT_REACHED_AT_DECISION"
        decision = "BLOCK"
    elif extension <= MAX_ENTRY_EXTENSION_PCT:
        extension_status = "WITHIN_0_25_PCT"
        decision = "ALLOW" if _execution_rr(ask, stop, target) >= MIN_EXECUTION_RR else "BLOCK"
    else:
        extension_status = "MISSED_ENTRY"
        decision = "BLOCK"
    return {
        "name": name,
        "family": family,
        "trigger": round(trigger, 6),
        "stop": round(stop, 6),
        "targets": [round(target, 6)],
        "extensionPct": round(extension, 6),
        "extensionStatus": extension_status,
        "executionRewardRisk": _execution_rr(ask, stop, target),
        "hypotheticalDecision": decision,
        "evidenceIds": sorted(set(evidence_ids)),
    }


def _verticality_features(
    *,
    bars: Sequence[ResearchBar],
    premarket: Sequence[ResearchBar],
    last_15: Sequence[ResearchBar],
    opening: Sequence[ResearchBar],
    prior_close: float,
    atr: float,
    ask: float,
) -> dict[str, Any]:
    recent = sorted(bars, key=lambda bar: bar.timestamp)
    running_high = recent[0].high
    max_pullback = 0.0
    meaningful_pullbacks = 0
    in_pullback = False
    consecutive_up = 0
    maximum_consecutive_up = 0
    for bar in recent:
        running_high = max(running_high, bar.high)
        depth = running_high - bar.low
        max_pullback = max(max_pullback, depth)
        if depth >= 0.25 * atr and not in_pullback:
            meaningful_pullbacks += 1
            in_pullback = True
        if bar.close >= running_high - 0.05 * atr:
            in_pullback = False
        if bar.close > bar.open:
            consecutive_up += 1
            maximum_consecutive_up = max(maximum_consecutive_up, consecutive_up)
        else:
            consecutive_up = 0
    result = {
        "moveFromPriorClosePct": round(_pct(ask, prior_close), 6),
        "moveFromPriorCloseAtr": round((ask - prior_close) / atr, 6),
        "moveFromPremarketVwapAtr": round(
            (ask - aggregate_bars(premarket)["vwapApprox"]) / atr, 6
        ),
        "maxPullbackAtr": round(max_pullback / atr, 6),
        "meaningfulPullbackCountAtExploratoryQuarterAtr": meaningful_pullbacks,
        "maximumConsecutiveUpBars": maximum_consecutive_up,
        "openingRangeAtr": round(aggregate_bars(opening)["range"] / atr, 6),
        "last15RangeAtr": round(aggregate_bars(last_15)["range"] / atr, 6),
        "returnsPct": {},
        "thresholdAuthority": "EXPLORATORY_FEATURES_ONLY_NOT_FROZEN",
    }
    for minutes in (5, 15, 30, 60):
        subset = recent[-minutes:]
        result["returnsPct"][f"{minutes}m"] = (
            round(_pct(subset[-1].close, subset[0].open), 6) if subset else None
        )
    return result


def _candidate_answers(
    *,
    original_cross_status: str,
    original_cross_time: str | None,
    original_crossed_before_decision: bool,
    original_model: Mapping[str, Any],
    last_15_model: Mapping[str, Any],
    full_model: Mapping[str, Any],
    result_class: str,
) -> dict[str, Any]:
    crossed = original_cross_status != "NOT_CROSSED_PREMARKET"
    return {
        "1_originalBreakoutBefore0930": crossed,
        "2_originalBreakoutApproximateTime": original_cross_time
        or ("BEFORE_07_00_ET_UNOBSERVED" if original_cross_status == "BEFORE_EARLIEST_TRUSTED_BAR" else None),
        "3_originalSetupGenuinelyMissed": original_crossed_before_decision,
        "4_newDefensibleStructureBy0935": bool(full_model.get("newSetup")),
        "5_bestExistingSetupFamily": full_model["family"],
        "6_freshTrigger": full_model.get("trigger") if full_model.get("newSetup") else None,
        "7_structuralStop": full_model.get("stop") if full_model.get("newSetup") else None,
        "8_executionAdjustedRewardRisk": full_model.get("executionRewardRisk"),
        "9_verticalWithoutValidNewStructure": full_model["family"] == "NO_NEW_STRUCTURE",
        "10_last15AddedUsefulInformation": True,
        "11_last15AloneMisleading": last_15_model["hypotheticalDecision"] == "ALLOW",
        "12_fullStructureImprovedDecision": (
            full_model.get("researchFinding") != original_model.get("extensionStatus")
            or full_model.get("newSetup")
        ),
        "13_currentMhRejection": result_class,
        "modelBDecision": last_15_model["hypotheticalDecision"],
    }


def _result_classification(
    *,
    original_cross_status: str,
    original_crossed_before_decision: bool,
    original_model: Mapping[str, Any],
    full_model: Mapping[str, Any],
) -> str:
    if full_model.get("newSetup"):
        return "POTENTIAL_FRESH_SETUP_NOT_RECOGNIZED"
    if (
        original_cross_status == "NOT_CROSSED_PREMARKET"
        and original_crossed_before_decision
        and original_model["extensionStatus"] != "MISSED_ENTRY"
    ):
        return "INDETERMINATE_EVIDENCE"
    if original_model["extensionStatus"] == "MISSED_ENTRY":
        return "CORRECT_ORIGINAL_SETUP_MISSED_BUT_NEW_SETUP_UNAVAILABLE"
    return "CORRECT_NO_TRADE"


def _benchmark_context(symbol: str, bars: Sequence[ResearchBar]) -> dict[str, Any]:
    premarket = _between(bars, time(4, 0), time(9, 30))
    opening = _between(bars, time(9, 30), time(9, 35))
    pm = aggregate_bars(premarket)
    op = aggregate_bars(opening)
    return {
        "symbol": symbol,
        "premarketReturnPct": round(_pct(pm["close"], pm["open"]), 6),
        "openingReturnPct": round(_pct(op["close"], op["open"]), 6),
        "premarket": pm,
        "openingRange": op,
        "source": RETROSPECTIVE_HISTORY,
    }


def _market_regime_interpretation(items: Sequence[Mapping[str, Any]]) -> str:
    positive = sum(
        item["premarketReturnPct"] > 0 and item["openingReturnPct"] > 0 for item in items
    )
    if positive == len(items):
        return "SUPPORTIVE_RISK_ON_RESEARCH_CONTEXT"
    if positive == 0:
        return "RISK_OFF_RESEARCH_CONTEXT"
    return "MIXED_RESEARCH_CONTEXT"


def _preserved_market_regime(capture: Mapping[str, Any]) -> str | None:
    for key in ("market_regime", "marketRegime"):
        value = capture.get(key)
        if value:
            return str(value)
    metadata = capture.get("metadata")
    if isinstance(metadata, Mapping):
        return str(metadata.get("market_regime") or metadata.get("marketRegime") or "UNKNOWN")
    return "UNKNOWN"


def _candidate_rows(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = report.get("candidates")
    if not isinstance(rows, list):
        raise PremarketStructureResearchError("TradePlan report has no candidate list.")
    return sorted(rows, key=lambda row: int(row["rank"]))


def _quote_receipt(row: Mapping[str, Any]) -> datetime:
    raw = row["market_tape"]["field_provenance"]["current_ask"]["local_receipt_timestamp"]
    return _parse_datetime(str(raw)).astimezone(EASTERN)


def _between(
    bars: Sequence[ResearchBar], start: time, end: time
) -> list[ResearchBar]:
    return [bar for bar in bars if start <= bar.timestamp.astimezone(EASTERN).time() < end]


def _first_cross(bars: Sequence[ResearchBar], level: float) -> ResearchBar | None:
    return next((bar for bar in bars if bar.high >= level), None)


def _reclaim_event(bars: Sequence[ResearchBar], level: float) -> bool:
    below = False
    for bar in sorted(bars, key=lambda item: item.timestamp):
        if bar.low <= level:
            below = True
        if below and bar.close > level:
            return True
    return False


def _execution_rr(entry: float, stop: float, target: float) -> float:
    risk = entry - stop
    return round((target - entry) / risk, 6) if risk > 0 else -1.0


def _pct(value: float, baseline: float) -> float:
    return ((value / baseline) - 1.0) * 100.0


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PremarketStructureResearchError(f"Naive timestamp is not allowed: {value}")
    return parsed


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PremarketStructureResearchError(f"Cannot read JSON evidence: {path}") from exc
    if not isinstance(payload, dict):
        raise PremarketStructureResearchError(f"JSON evidence is not an object: {path}")
    return payload


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest().upper()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _write_once_json(path: Path, payload: Mapping[str, Any]) -> None:
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == content:
            return
        raise PremarketStructureResearchError(f"Conflicting write-once output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    decision = subparsers.add_parser("decision")
    decision.add_argument("--trade-plan", type=Path, required=True)
    decision.add_argument("--capture", type=Path, required=True)
    decision.add_argument("--minute-store", type=Path, required=True)
    decision.add_argument("--backfill-result", type=Path, required=True)
    decision.add_argument("--output", type=Path, required=True)
    outcome = subparsers.add_parser("outcome")
    outcome.add_argument("--decision", type=Path, required=True)
    outcome.add_argument("--minute-store", type=Path, required=True)
    outcome.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "decision":
        result = build_decision_packet(
            trade_plan_path=args.trade_plan,
            capture_path=args.capture,
            minute_store_root=args.minute_store,
            backfill_result_path=args.backfill_result,
            output_path=args.output,
        )
        summary = {"status": "FROZEN", "decisionFingerprint": result["decisionFingerprint"]}
    else:
        result = build_outcome_packet(
            decision_path=args.decision,
            minute_store_root=args.minute_store,
            output_path=args.output,
        )
        summary = {"status": "COMPLETE", "outcomeFingerprint": result["outcomeFingerprint"]}
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
