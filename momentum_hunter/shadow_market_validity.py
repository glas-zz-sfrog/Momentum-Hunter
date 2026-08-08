"""Frozen market-validity policy and evidence stores for official Shadow v1."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from momentum_hunter.opportunity_alerts import (
    PriceObservation,
    load_price_observations,
)
from momentum_hunter.scheduling import is_market_open_day, is_nyse_early_close
from momentum_hunter.shadow_opening import clock_skew_findings
from momentum_hunter.trade_planning import parse_datetime


EASTERN_TZ = ZoneInfo("America/New_York")
SHADOW_MARKET_POLICY_VERSION = "official-shadow-market-validity-v1"
SHADOW_CONSTITUTION_VERSION = "official-shadow-constitution-v2"
SHADOW_SELECTOR_ARM_SCHEMA_VERSION = 3
SHADOW_DECISION_CYCLE_SCHEMA_VERSION = 1
SHADOW_SELECTOR_ARM_CONFIRMATION = "ARM OFFICIAL SHADOW SELECTOR"
SELECTOR_PROOF_ARTIFACT_SCHEMA_VERSION = 1
MAX_SELECTOR_PROOF_ARTIFACT_BYTES = 4 * 1024 * 1024
MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_SELECTOR_EVIDENCE_FILES_PER_PROOF = 16
SHADOW_SELECTOR_ARM_REQUIRED_PROOFS = (
    "canonical_merge_backup",
    "counterfactuals",
    "cycle_accounting",
    "fresh_quote_boundary",
    "freshness_matrix",
    "opportunity_deduplication",
    "portfolio_policy",
    "ranking_and_tie_breaks",
    "secret_transmission_block",
    "session_and_forced_exit",
    "visual_acceptance",
    "warning_severity",
)

FATAL_WARNING_CODES = frozenset(
    {
        "DATA_REQUIRED_DAILY_BARS",
        "INVALID_RISK",
        "MISSING_MARKET_TAPE",
        "MISSING_TECHNICAL_LEVELS",
        "MONITOR_COVERAGE_ONLY",
        "TECHNICAL_LEVELS_ESTIMATED",
    }
)
INFORMATIONAL_WARNING_CODES = frozenset(
    {
        "MISSING_BID_ASK",
        "MISSING_PREMARKET_PERCENT",
        "MISSING_PREMARKET_PRICE",
        "MISSING_PREMARKET_VOLUME",
        "MISSING_RELATIVE_VOLUME",
        "MISSING_SPREAD",
        "PRICE_ALREADY_ABOVE_ENTRY",
        "STOP_ADJUSTED_BELOW_ENTRY",
        "WIDE_SPREAD",
    }
)
INFORMATIONAL_WARNING_PREFIXES = (
    "CHART_",
    "QUOTE_",
)


@dataclass(frozen=True)
class ShadowMarketValidityPolicy:
    version: str = SHADOW_MARKET_POLICY_VERSION
    quote_max_age_seconds: int = 30
    active_position_quote_max_age_seconds: int = 10
    active_position_poll_interval_seconds: int = 5
    capture_max_age_seconds: int = 600
    report_max_age_seconds: int = 300
    report_to_selection_max_seconds: int = 60
    entry_start_eastern: str = "09:35:00"
    entry_end_eastern: str = "15:30:00"
    forced_exit_eastern: str = "15:55:00"
    early_close_entry_end_eastern: str = "12:30:00"
    early_close_forced_exit_eastern: str = "12:55:00"
    allow_extended_hours: bool = False
    allow_overnight: bool = False
    maximum_active_positions: int = 1
    maximum_symbol_trades_per_day: int = 1
    maximum_new_trades_per_report: int = 1
    required_distinct_sessions_for_strategy_review: int = 10
    expected_cycle_interval_seconds: int = 300
    benchmark_symbols: tuple[str, ...] = ("SPY", "IWM")
    primary_performance_metric: str = "R_MULTIPLE"


@dataclass(frozen=True)
class WarningAssessment:
    fatal: tuple[str, ...]
    informational: tuple[str, ...]


@dataclass(frozen=True)
class SelectorArmRecord:
    schema_version: int
    arm_id: str
    armed_at: str
    sample_version: str
    strategy_configuration_fingerprint: str
    selection_policy_fingerprint: str
    constitution_version: str
    constitution_hash: str
    build_hash: str
    opening_configuration: dict[str, Any]
    clock_skew_proof: dict[str, Any]
    prerequisite_proofs: dict[str, str]
    prerequisite_proof_paths: dict[str, str]


@dataclass(frozen=True)
class VerifiedSelectorProofArtifacts:
    hashes: dict[str, str]
    paths: dict[str, str]
    opening_configuration: dict[str, Any]
    clock_skew_proof: dict[str, Any]


@dataclass(frozen=True)
class DecisionCycleState:
    schema_version: int = SHADOW_DECISION_CYCLE_SCHEMA_VERSION
    updated_at: str = ""
    cycles: tuple[dict[str, Any], ...] = ()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def shadow_market_policy_definition(
    policy: ShadowMarketValidityPolicy | None = None,
) -> dict[str, Any]:
    active = policy or ShadowMarketValidityPolicy()
    payload = asdict(active)
    payload["benchmark_symbols"] = list(active.benchmark_symbols)
    return payload


def shadow_constitution_definition(
    policy: ShadowMarketValidityPolicy | None = None,
) -> dict[str, Any]:
    active = policy or ShadowMarketValidityPolicy()
    return {
        "constitution_version": SHADOW_CONSTITUTION_VERSION,
        "selection": {
            "automatic_only": True,
            "order": [
                "canonical_rank_ascending",
                "composite_score_descending",
                "candidate_id_or_symbol_ascending",
            ],
            "risk_governor_role": "eligibility_gate_not_ranker",
        },
        "market_validity": shadow_market_policy_definition(active),
        "eligibility": {
            "fatal_warning_codes": sorted(FATAL_WARNING_CODES),
            "informational_warning_codes": sorted(INFORMATIONAL_WARNING_CODES),
            "informational_warning_prefixes": list(
                INFORMATIONAL_WARNING_PREFIXES
            ),
            "unknown_warning": "fatal",
            "requires_fresh_executable_bid_ask": True,
        },
        "portfolio": {
            "one_active_position_globally": True,
            "one_symbol_trade_per_trading_day": True,
            "same_day_reentry": False,
            "primary_metric": active.primary_performance_metric,
        },
        "active_position_marking": {
            "transport": "schwab_marketdata_v1_quotes",
            "cadence_seconds": active.active_position_poll_interval_seconds,
            "maximum_quote_age_seconds": (
                active.active_position_quote_max_age_seconds
            ),
            "long_executable_side": "bid",
            "short_executable_side": "ask",
            "stale_behavior": "preserve_last_reliable_mark_and_block_exit",
            "display_refresh_may_not_fetch_provider": True,
        },
        "accounting": {
            "record_every_attempted_cycle": True,
            "preserve_all_candidate_reasons": True,
            "counterfactuals": [
                "all_eligible_candidates",
                "deterministic_random_eligible",
                *active.benchmark_symbols,
            ],
        },
        "execution_boundary": "ProspectiveFakeBroker",
        "order_transmission": "UNAVAILABLE",
    }


def shadow_constitution_hash(
    policy: ShadowMarketValidityPolicy | None = None,
) -> str:
    return hashlib.sha256(
        canonical_json(shadow_constitution_definition(policy)).encode("utf-8")
    ).hexdigest()


def runtime_build_hash(paths: Iterable[Path] | None = None) -> str:
    if paths is None:
        root = Path(__file__).resolve().parent
        project_root = root.parent
        paths = (
            root / "engine_host.py",
            root / "engine_host_client.py",
            root / "models.py",
            root / "intraday_trade_plan.py",
            root / "scheduling.py",
            root / "schwab_market_data.py",
            root / "shadow_arm_ceremony.py",
            root / "shadow_market_validity.py",
            root / "shadow_opening.py",
            root / "shadow_selection.py",
            root / "shadow_trading.py",
            root / "storage.py",
            root / "trade_planning.py",
            root / "trade_setup_identity.py",
            root / "workstation_shadow.py",
            project_root / "tools" / "capture_job.py",
            project_root / "tools" / "install_capture_tasks.ps1",
            project_root / "tools" / "run_capture_job.ps1",
        )
    evidence: list[str] = []
    for path in sorted((Path(item) for item in paths), key=lambda item: item.name):
        source = path.read_bytes()
        evidence.append(f"{path.name}:{hashlib.sha256(source).hexdigest()}")
    return stable_hash(*evidence)


def classify_warnings(
    warnings: Iterable[str],
    blocking_reasons: Iterable[str] = (),
) -> WarningAssessment:
    fatal = [str(item).strip() for item in blocking_reasons if str(item).strip()]
    informational: list[str] = []
    for raw_warning in warnings:
        warning = str(raw_warning).strip()
        if not warning:
            continue
        code = warning.split(":", 1)[0]
        if (
            code in INFORMATIONAL_WARNING_CODES
            or code.startswith(INFORMATIONAL_WARNING_PREFIXES)
        ):
            informational.append(warning)
        elif code in FATAL_WARNING_CODES:
            fatal.append(warning)
        else:
            fatal.append(warning)
    return WarningAssessment(
        fatal=tuple(dict.fromkeys(fatal)),
        informational=tuple(dict.fromkeys(informational)),
    )


def canonical_candidate_rows(rows: Iterable[Any]) -> list[tuple[int, dict[str, Any]]]:
    normalized: list[tuple[int, float, str, int, dict[str, Any]]] = []
    seen_keys: set[str] = set()
    seen_symbols: set[str] = set()
    for persisted_index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        rank_value = row.get("rank")
        if not isinstance(rank_value, int) or isinstance(rank_value, bool) or rank_value <= 0:
            raise ValueError(
                f"Candidate at persisted index {persisted_index} lacks a positive canonical rank."
            )
        scoring = row.get("scoring") if isinstance(row.get("scoring"), dict) else {}
        score_value = scoring.get("composite_score")
        if not isinstance(score_value, (int, float)) or isinstance(score_value, bool):
            raise ValueError(
                f"Candidate rank {rank_value} lacks a numeric canonical score."
            )
        if not math.isfinite(float(score_value)):
            raise ValueError(
                f"Candidate rank {rank_value} lacks a finite canonical score."
            )
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError(f"Candidate rank {rank_value} lacks a symbol.")
        candidate_key = str(row.get("candidate_id") or symbol).strip().upper()
        if candidate_key in seen_keys or symbol in seen_symbols:
            raise ValueError(
                f"Candidate identity is duplicated in the report: {candidate_key}."
            )
        seen_keys.add(candidate_key)
        seen_symbols.add(symbol)
        normalized.append(
            (
                rank_value,
                -float(score_value),
                candidate_key,
                persisted_index,
                row,
            )
        )
    ordered = sorted(normalized, key=lambda item: item[:4])
    return [(persisted_index, row) for *_, persisted_index, row in ordered]


def validate_report_clocks(
    metadata: dict[str, Any],
    *,
    decision_at: datetime,
    policy: ShadowMarketValidityPolicy | None = None,
) -> tuple[str, ...]:
    active = policy or ShadowMarketValidityPolicy()
    if not is_offset_aware(decision_at):
        return ("Selection timestamp is missing a UTC offset.",)
    capture_at = parse_datetime(str(metadata.get("source_capture_time", "")))
    report_at = parse_datetime(str(metadata.get("generated_at", "")))
    reasons: list[str] = []
    if not is_offset_aware(capture_at):
        reasons.append("Source capture timestamp is missing, invalid, or ambiguous.")
    if not is_offset_aware(report_at):
        reasons.append("Report timestamp is missing, invalid, or ambiguous.")
    if reasons:
        return tuple(reasons)
    assert capture_at is not None
    assert report_at is not None
    if capture_at > decision_at:
        reasons.append("Source capture timestamp is in the future.")
    if report_at > decision_at:
        reasons.append("Report timestamp is in the future.")
    if report_at < capture_at:
        reasons.append("Report timestamp predates its source capture.")
    capture_age = (decision_at - capture_at).total_seconds()
    report_age = (decision_at - report_at).total_seconds()
    if capture_age > active.capture_max_age_seconds:
        reasons.append(
            f"Source capture is stale by {int(capture_age)} seconds."
        )
    if report_age > active.report_max_age_seconds:
        reasons.append(f"Generated report is stale by {int(report_age)} seconds.")
    if report_age > active.report_to_selection_max_seconds:
        reasons.append(
            f"Report-to-selection delay is {int(report_age)} seconds."
        )
    return tuple(reasons)


def validate_selection_quote(
    quote: dict[str, Any] | None,
    *,
    decision_at: datetime,
    entry: float,
    stop: float,
    target: float,
    quantity: int,
    maximum_spread_percent: float,
    buying_power: float,
    expected_symbol: str,
    policy: ShadowMarketValidityPolicy | None = None,
) -> tuple[str, ...]:
    active = policy or ShadowMarketValidityPolicy()
    if quote is None:
        return ("Fresh executable quote is unavailable.",)
    reasons: list[str] = []
    quote_at = parse_datetime(str(quote.get("timestamp", "")))
    if not is_offset_aware(quote_at):
        reasons.append("Quote timestamp is missing, invalid, or ambiguous.")
        return tuple(reasons)
    assert quote_at is not None
    quote_symbol = str(quote.get("symbol", "")).strip().upper()
    if quote_symbol != expected_symbol.strip().upper():
        reasons.append("Executable quote symbol does not match the candidate.")
    if not str(quote.get("source", "")).strip():
        reasons.append("Executable quote source identity is missing.")
    if quote_at > decision_at:
        reasons.append("Quote timestamp is in the future.")
    quote_age = (decision_at - quote_at).total_seconds()
    if quote_age > active.quote_max_age_seconds:
        reasons.append(f"Executable quote is stale by {int(quote_age)} seconds.")
    bid = optional_float(quote.get("bid"))
    ask = optional_float(quote.get("ask"))
    last = optional_float(quote.get("last"))
    if bid is None or ask is None:
        reasons.append("Executable quote is missing bid or ask.")
    elif bid <= 0 or ask <= 0 or ask < bid:
        reasons.append("Executable bid/ask is invalid or crossed.")
    else:
        spread = (ask - bid) / ask * 100
        if spread > maximum_spread_percent:
            reasons.append(
                f"Quote spread {spread:.2f}% exceeds {maximum_spread_percent:.2f}%."
            )
        if ask >= target or (last is not None and last >= target):
            reasons.append("Current price is at or beyond the primary target.")
        if bid <= stop or (last is not None and last <= stop):
            reasons.append("Current price is at or below the frozen stop.")
        if quantity <= 0 or quantity * ask > buying_power:
            reasons.append("Current entry notional exceeds frozen buying power.")
    trading_state = str(quote.get("trading_state", "")).lower()
    if trading_state not in {"open", "tradable"}:
        reasons.append(
            f"Symbol trading state is not tradable: {trading_state or 'unknown'}."
        )
    session = str(quote.get("session", "")).lower()
    if session != "regular":
        reasons.append(f"Quote session is not permitted: {session or 'unknown'}.")
    reasons.extend(entry_window_findings(decision_at, active))
    if not (stop < entry < target):
        reasons.append("Frozen TradePlan entry/stop/target ordering is invalid.")
    return tuple(dict.fromkeys(reasons))


def report_clock_evidence(
    metadata: dict[str, Any],
    *,
    decision_at: datetime,
) -> dict[str, float | None]:
    capture_at = parse_datetime(str(metadata.get("source_capture_time", "")))
    report_at = parse_datetime(str(metadata.get("generated_at", "")))
    if not (
        is_offset_aware(capture_at)
        and is_offset_aware(report_at)
        and is_offset_aware(decision_at)
    ):
        return {
            "capture_to_report_seconds": None,
            "report_to_selection_seconds": None,
            "capture_to_selection_seconds": None,
        }
    assert capture_at is not None and report_at is not None
    return {
        "capture_to_report_seconds": (
            report_at - capture_at
        ).total_seconds(),
        "report_to_selection_seconds": (
            decision_at - report_at
        ).total_seconds(),
        "capture_to_selection_seconds": (
            decision_at - capture_at
        ).total_seconds(),
    }


def entry_window_findings(
    value: datetime,
    policy: ShadowMarketValidityPolicy | None = None,
) -> tuple[str, ...]:
    active = policy or ShadowMarketValidityPolicy()
    if not is_offset_aware(value):
        return ("Selection timestamp is missing a UTC offset.",)
    eastern = value.astimezone(EASTERN_TZ)
    if not is_market_open_day(eastern.date()):
        return ("Selection date is not an open NYSE trading day.",)
    start = time.fromisoformat(active.entry_start_eastern)
    try:
        early_close = is_nyse_early_close(eastern.date())
    except ValueError as exc:
        return (str(exc),)
    end = time.fromisoformat(
        active.early_close_entry_end_eastern
        if early_close
        else active.entry_end_eastern
    )
    if not (start <= eastern.time().replace(tzinfo=None) <= end):
        return (
            f"Selection time is outside the {start.isoformat()}-{end.isoformat()} ET entry window.",
        )
    return ()


def forced_exit_deadline(
    value: datetime,
    policy: ShadowMarketValidityPolicy | None = None,
) -> datetime:
    active = policy or ShadowMarketValidityPolicy()
    eastern = value.astimezone(EASTERN_TZ)
    deadline = time.fromisoformat(
        active.early_close_forced_exit_eastern
        if is_nyse_early_close(eastern.date())
        else active.forced_exit_eastern
    )
    return datetime.combine(eastern.date(), deadline, tzinfo=EASTERN_TZ)


def opportunity_identity(
    row: dict[str, Any],
    *,
    plan_fingerprint: str,
    decision_at: datetime,
) -> str:
    scoring = row.get("scoring") if isinstance(row.get("scoring"), dict) else {}
    symbol = str(row.get("symbol", "")).strip().upper()
    setup = str(scoring.get("catalyst_cluster", "")).strip().lower()
    catalyst = str(scoring.get("catalyst_summary", "")).strip().lower()
    session_date = decision_at.astimezone(EASTERN_TZ).date().isoformat()
    return stable_hash(
        "shadow-opportunity-v1",
        symbol,
        "LONG",
        setup,
        catalyst,
        session_date,
        plan_fingerprint,
    )


def portfolio_findings(
    trades: Iterable[Any],
    *,
    symbol: str,
    opportunity_id: str,
    decision_at: datetime,
    daily_loss_limit: float,
) -> tuple[str, ...]:
    reasons: list[str] = []
    active_states = {"pending_entry", "partially_filled", "open"}
    trades = tuple(trades)
    if any(getattr(item, "status", "") in active_states for item in trades):
        reasons.append("An official Shadow order or position is already active.")
    decision_date = decision_at.astimezone(EASTERN_TZ).date()
    if any(
        getattr(item, "symbol", "").upper() == symbol.upper()
        and same_eastern_date(getattr(item, "decision_timestamp", ""), decision_date)
        for item in trades
    ):
        reasons.append("The symbol already has an official Shadow trade this trading day.")
    if any(
        getattr(item, "opportunity_id", "") == opportunity_id
        for item in trades
    ):
        reasons.append("The deterministic opportunity has already been traded.")
    realized = sum(
        float(getattr(getattr(item, "outcome", None), "executable_pnl", 0.0) or 0.0)
        for item in trades
        if same_eastern_date(getattr(item, "decision_timestamp", ""), decision_date)
    )
    if realized <= -abs(daily_loss_limit):
        reasons.append("The frozen daily-loss ceiling has been reached.")
    return tuple(dict.fromkeys(reasons))


class PersistedObservationQuoteSource:
    """Read-only latest executable quote boundary over persisted monitor evidence."""

    def __init__(self, observations_path: Path) -> None:
        self.observations_path = observations_path

    def quote(self, symbol: str, *, decision_at: datetime) -> dict[str, Any] | None:
        normalized = symbol.strip().upper()
        candidates: list[tuple[datetime, PriceObservation]] = []
        for observation in load_price_observations(self.observations_path):
            observed_at = parse_datetime(observation.quote_timestamp)
            if (
                observation.symbol.upper() != normalized
                or not is_offset_aware(observed_at)
                or observed_at > decision_at
                or not observation.quote_source.strip()
            ):
                continue
            assert observed_at is not None
            candidates.append((observed_at, observation))
        if not candidates:
            return None
        _, latest = max(candidates, key=lambda item: item[0])
        observed_at = parse_datetime(latest.quote_timestamp)
        assert observed_at is not None
        eastern = observed_at.astimezone(EASTERN_TZ)
        raw_state = latest.state.strip().lower()
        return {
            "symbol": normalized,
            "timestamp": latest.quote_timestamp,
            "bid": latest.bid,
            "ask": latest.ask,
            "last": latest.price,
            "volume": latest.volume,
            "session": (
                "regular"
                if time(9, 30) <= eastern.time().replace(tzinfo=None) < time(16, 0)
                else "extended"
            ),
            "trading_state": (
                raw_state
                if raw_state in {"halted", "open", "tradable"}
                else "tradable"
            ),
            "source": latest.quote_source,
        }


class SelectorArmStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> SelectorArmRecord | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Selector arm record cannot be loaded: {type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError("Selector arm record must contain an object.")
        record = SelectorArmRecord(
            schema_version=int(payload.get("schema_version", 0)),
            arm_id=str(payload.get("arm_id", "")),
            armed_at=str(payload.get("armed_at", "")),
            sample_version=str(payload.get("sample_version", "")),
            strategy_configuration_fingerprint=str(
                payload.get("strategy_configuration_fingerprint", "")
            ),
            selection_policy_fingerprint=str(
                payload.get("selection_policy_fingerprint", "")
            ),
            constitution_version=str(payload.get("constitution_version", "")),
            constitution_hash=str(payload.get("constitution_hash", "")),
            build_hash=str(payload.get("build_hash", "")),
            opening_configuration=dict(
                payload.get("opening_configuration", {})
            ),
            clock_skew_proof=dict(payload.get("clock_skew_proof", {})),
            prerequisite_proofs={
                str(key): str(value)
                for key, value in dict(payload.get("prerequisite_proofs", {})).items()
            },
            prerequisite_proof_paths={
                str(key): str(value)
                for key, value in dict(
                    payload.get("prerequisite_proof_paths", {})
                ).items()
            },
        )
        validate_arm_record(record)
        return record

    def save_once(self, record: SelectorArmRecord) -> SelectorArmRecord:
        validate_arm_record(record)
        existing = self.load()
        if existing is not None:
            if existing == record:
                return existing
            raise ValueError("Selector arm record is immutable and already exists.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(asdict(record), indent=2, sort_keys=True))
                stream.write("\n")
        except FileExistsError as exc:
            existing = self.load()
            if existing == record:
                return record
            raise ValueError("Selector arm record is immutable and already exists.") from exc
        return record


class DecisionCycleStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> DecisionCycleState:
        if not self.path.exists():
            return DecisionCycleState()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"Shadow decision-cycle evidence cannot be loaded: {type(exc).__name__}"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != SHADOW_DECISION_CYCLE_SCHEMA_VERSION
            or not isinstance(payload.get("cycles"), list)
        ):
            raise ValueError("Shadow decision-cycle evidence has an invalid schema.")
        return DecisionCycleState(
            schema_version=SHADOW_DECISION_CYCLE_SCHEMA_VERSION,
            updated_at=str(payload.get("updated_at", "")),
            cycles=tuple(
                item for item in payload["cycles"] if isinstance(item, dict)
            ),
        )

    def get(self, cycle_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.load().cycles if item.get("cycle_id") == cycle_id),
            None,
        )

    def find_report(self, report_sha256: str) -> dict[str, Any] | None:
        return next(
            (
                item
                for item in self.load().cycles
                if item.get("report_sha256") == report_sha256
            ),
            None,
        )

    def save_cycle(self, cycle: dict[str, Any]) -> dict[str, Any]:
        cycle_id = str(cycle.get("cycle_id", ""))
        if not cycle_id:
            raise ValueError("Decision cycle requires a stable cycle ID.")
        state = self.load()
        existing = self.get(cycle_id)
        if existing is not None and existing == cycle:
            return existing
        cycles = [
            item for item in state.cycles if item.get("cycle_id") != cycle_id
        ]
        cycles.append(cycle)
        self._save(
            DecisionCycleState(
                updated_at=str(cycle.get("updated_at") or cycle.get("decision_at") or ""),
                cycles=tuple(sorted(cycles, key=lambda item: (str(item.get("decision_at", "")), str(item.get("cycle_id", ""))))),
            )
        )
        return cycle

    def append_observations(
        self,
        observations: Iterable[dict[str, Any]],
    ) -> int:
        state = self.load()
        normalized = [item for item in observations if isinstance(item, dict)]
        if not normalized or not state.cycles:
            return 0
        changed = 0
        updated_cycles: list[dict[str, Any]] = []
        for cycle in state.cycles:
            tracked = {
                str(item.get("symbol", "")).upper()
                for item in cycle.get("candidate_assessments", [])
                if isinstance(item, dict)
            }
            tracked.update(
                str(item).upper() for item in cycle.get("benchmark_symbols", [])
            )
            existing = list(cycle.get("market_observations", []))
            keys = {
                (
                    str(item.get("symbol", "")).upper(),
                    str(item.get("timestamp", "")),
                    str(item.get("source", "")),
                )
                for item in existing
                if isinstance(item, dict)
            }
            additions = []
            for item in normalized:
                key = (
                    str(item.get("symbol", "")).upper(),
                    str(item.get("timestamp", "")),
                    str(item.get("source", "")),
                )
                if key[0] in tracked and key not in keys:
                    additions.append(item)
                    keys.add(key)
            if additions:
                cycle = {
                    **cycle,
                    "market_observations": [*existing, *additions],
                    "updated_at": max(
                        [str(cycle.get("updated_at", ""))]
                        + [str(item.get("timestamp", "")) for item in additions]
                    ),
                }
                changed += len(additions)
            cycle = {
                **cycle,
                "counterfactual_marks": build_counterfactual_marks(cycle),
            }
            updated_cycles.append(cycle)
        if changed:
            self._save(
                DecisionCycleState(
                    updated_at=max(
                        str(item.get("updated_at", "")) for item in updated_cycles
                    ),
                    cycles=tuple(updated_cycles),
                )
            )
        return changed

    def finalize_counterfactuals(
        self,
        cycle_id: str,
        *,
        horizon_at: str,
    ) -> dict[str, Any] | None:
        cycle = self.get(cycle_id)
        horizon = parse_datetime(horizon_at)
        if cycle is None or not is_offset_aware(horizon):
            return None
        existing_horizon = str(cycle.get("counterfactual_horizon_at", ""))
        if existing_horizon and existing_horizon != horizon_at:
            raise ValueError(
                "Counterfactual holding-window horizon is immutable."
            )
        updated = {
            **cycle,
            "counterfactual_horizon_at": horizon_at,
            "counterfactual_status": "FINALIZED_TO_SELECTED_TRADE_EXIT",
        }
        updated["counterfactual_marks"] = build_counterfactual_marks(updated)
        self.save_cycle(updated)
        return updated

    def _save(self, state: DecisionCycleState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SHADOW_DECISION_CYCLE_SCHEMA_VERSION,
            "updated_at": state.updated_at,
            "cycles": list(state.cycles),
        }
        temporary = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def validate_arm_record(record: SelectorArmRecord) -> None:
    armed_at = parse_datetime(record.armed_at)
    if (
        record.schema_version != SHADOW_SELECTOR_ARM_SCHEMA_VERSION
        or not is_offset_aware(armed_at)
    ):
        raise ValueError("Selector arm record has an invalid schema or timestamp.")
    for name, value in {
        "arm_id": record.arm_id,
        "strategy_configuration_fingerprint": record.strategy_configuration_fingerprint,
        "selection_policy_fingerprint": record.selection_policy_fingerprint,
        "constitution_hash": record.constitution_hash,
        "build_hash": record.build_hash,
    }.items():
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"Selector arm record {name} is not a SHA-256 value.")
    if record.constitution_version != SHADOW_CONSTITUTION_VERSION:
        raise ValueError("Selector arm record constitution version is unsupported.")
    if set(record.prerequisite_proofs) != set(SHADOW_SELECTOR_ARM_REQUIRED_PROOFS):
        raise ValueError("Selector arm record prerequisite proof set is incomplete.")
    if set(record.prerequisite_proof_paths) != set(
        SHADOW_SELECTOR_ARM_REQUIRED_PROOFS
    ):
        raise ValueError(
            "Selector arm record prerequisite proof path set is incomplete."
        )
    for name, proof in record.prerequisite_proofs.items():
        digest = proof.removeprefix("PASS:")
        if (
            not proof.startswith("PASS:")
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError(f"Selector arm prerequisite proof is invalid: {name}.")
    for name, raw_path in record.prerequisite_proof_paths.items():
        if not raw_path or not Path(raw_path).is_absolute():
            raise ValueError(
                f"Selector arm prerequisite proof path is invalid: {name}."
            )
    validate_opening_configuration_identity(
        record.opening_configuration,
        expected_build_hash=record.build_hash,
        expected_constitution_hash=record.constitution_hash,
        expected_selection_policy_fingerprint=(
            record.selection_policy_fingerprint
        ),
    )
    findings = clock_skew_findings(
        record.clock_skew_proof,
        evaluated_at=armed_at,
    )
    if findings:
        raise ValueError(
            "Selector arm clock-skew proof is invalid: "
            + " | ".join(findings)
        )


def hash_prerequisite_proof_artifacts(
    artifact_paths: Mapping[str, str | Path],
    *,
    sample_version: str,
    activation_hash: str,
    activated_at: datetime,
    constitution_hash: str,
    build_hash: str,
    armed_at: datetime,
) -> VerifiedSelectorProofArtifacts:
    frozen_paths = dict(artifact_paths)
    if set(frozen_paths) != set(SHADOW_SELECTOR_ARM_REQUIRED_PROOFS):
        raise ValueError(
            "Selector arm prerequisite proof artifact set is incomplete."
        )
    if not is_offset_aware(armed_at) or not is_offset_aware(activated_at):
        raise ValueError(
            "Selector arm prerequisite verification time requires a UTC offset."
        )
    if (
        len(activation_hash) != 64
        or any(char not in "0123456789abcdef" for char in activation_hash)
    ):
        raise ValueError("Selector arm activation hash is invalid.")
    resolved_paths: set[Path] = set()
    proofs: dict[str, str] = {}
    canonical_paths: dict[str, str] = {}
    opening_configuration: dict[str, Any] = {}
    clock_skew_proof: dict[str, Any] = {}
    for name in SHADOW_SELECTOR_ARM_REQUIRED_PROOFS:
        raw_path = frozen_paths[name]
        if not isinstance(raw_path, (str, Path)):
            raise ValueError(
                f"Selector arm prerequisite artifact path is invalid: {name}."
            )
        path, payload = read_stable_selector_artifact(
            Path(raw_path),
            proof_name=name,
            artifact_role="proof",
            maximum_bytes=MAX_SELECTOR_PROOF_ARTIFACT_BYTES,
        )
        if path in resolved_paths:
            raise ValueError(
                f"Selector arm prerequisite artifacts must be distinct: {name}."
            )
        resolved_paths.add(path)
        validate_selector_proof_artifact(
            name,
            path,
            payload,
            sample_version=sample_version,
            activation_hash=activation_hash,
            activated_at=activated_at,
            constitution_hash=constitution_hash,
            build_hash=build_hash,
            armed_at=armed_at,
        )
        proofs[name] = f"PASS:{hashlib.sha256(payload).hexdigest()}"
        canonical_paths[name] = str(path)
        if name == "fresh_quote_boundary":
            opening_configuration, clock_skew_proof = (
                read_opening_gate_evidence(
                    path,
                    evaluated_at=armed_at,
                )
            )
    return VerifiedSelectorProofArtifacts(
        hashes=proofs,
        paths=canonical_paths,
        opening_configuration=opening_configuration,
        clock_skew_proof=clock_skew_proof,
    )


def read_stable_selector_artifact(
    supplied_path: Path,
    *,
    proof_name: str,
    artifact_role: str,
    maximum_bytes: int,
) -> tuple[Path, bytes]:
    if supplied_path.is_symlink():
        raise ValueError(
            f"Selector arm {artifact_role} artifact cannot be a symlink: {proof_name}."
        )
    try:
        path = supplied_path.resolve(strict=True)
        if not path.is_file():
            raise ValueError(
                f"Selector arm {artifact_role} artifact is not a file: {proof_name}."
            )
        before = path.stat()
        if before.st_size <= 0:
            raise ValueError(
                f"Selector arm {artifact_role} artifact is empty: {proof_name}."
            )
        if before.st_size > maximum_bytes:
            raise ValueError(
                f"Selector arm {artifact_role} artifact is too large: {proof_name}."
            )
        payload = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise ValueError(
            f"Selector arm {artifact_role} artifact is unavailable: {proof_name}."
        ) from exc
    if (
        len(payload) != before.st_size
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ValueError(
            f"Selector arm {artifact_role} artifact changed while reading: {proof_name}."
        )
    return path, payload


def validate_selector_proof_artifact(
    proof_name: str,
    path: Path,
    payload: bytes,
    *,
    sample_version: str,
    activation_hash: str,
    activated_at: datetime,
    constitution_hash: str,
    build_hash: str,
    armed_at: datetime,
) -> None:
    try:
        artifact = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(
            f"Selector arm proof artifact is not valid UTF-8 JSON: {proof_name}."
        ) from None
    if not isinstance(artifact, dict):
        raise ValueError(
            f"Selector arm proof artifact has an invalid shape: {proof_name}."
        )
    verified_at = parse_datetime(str(artifact.get("verified_at", "")))
    if (
        artifact.get("schema_version")
        != SELECTOR_PROOF_ARTIFACT_SCHEMA_VERSION
        or artifact.get("proof_name") != proof_name
        or artifact.get("status") != "PASS"
        or artifact.get("sample_version") != sample_version
        or artifact.get("activation_hash") != activation_hash
        or artifact.get("constitution_hash") != constitution_hash
        or artifact.get("build_hash") != build_hash
        or not is_offset_aware(verified_at)
        or (verified_at is not None and verified_at < activated_at)
        or (verified_at is not None and verified_at > armed_at)
        or not str(artifact.get("summary", "")).strip()
    ):
        raise ValueError(
            f"Selector arm proof artifact context is invalid: {proof_name}."
        )
    evidence = artifact.get("evidence")
    if (
        not isinstance(evidence, list)
        or not evidence
        or len(evidence) > MAX_SELECTOR_EVIDENCE_FILES_PER_PROOF
    ):
        raise ValueError(
            f"Selector arm proof artifact lacks evidence: {proof_name}."
        )
    bundle_root = path.parent.resolve()
    seen_evidence: set[Path] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError(
                f"Selector arm proof evidence has an invalid shape: {proof_name}."
            )
        relative_value = str(item.get("path", "")).strip()
        expected_digest = str(item.get("sha256", "")).strip()
        relative_path = Path(relative_value)
        if (
            not relative_value
            or relative_path.is_absolute()
            or relative_path.drive
            or ".." in relative_path.parts
            or len(expected_digest) != 64
            or any(
                char not in "0123456789abcdef"
                for char in expected_digest
            )
        ):
            raise ValueError(
                f"Selector arm proof evidence reference is invalid: {proof_name}."
            )
        evidence_path, evidence_payload = read_stable_selector_artifact(
            path.parent / relative_path,
            proof_name=proof_name,
            artifact_role="evidence",
            maximum_bytes=MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
        )
        if (
            not evidence_path.is_relative_to(bundle_root)
            or evidence_path == path
            or evidence_path in seen_evidence
        ):
            raise ValueError(
                f"Selector arm proof evidence path is invalid: {proof_name}."
            )
        seen_evidence.add(evidence_path)
        if hashlib.sha256(evidence_payload).hexdigest() != expected_digest:
            raise ValueError(
                f"Selector arm proof evidence hash does not match: {proof_name}."
            )


def read_opening_gate_evidence(
    fresh_proof_path: Path,
    *,
    evaluated_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, proof_bytes = read_stable_selector_artifact(
        fresh_proof_path,
        proof_name="fresh_quote_boundary",
        artifact_role="proof",
        maximum_bytes=MAX_SELECTOR_PROOF_ARTIFACT_BYTES,
    )
    try:
        artifact = json.loads(proof_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(
            "Fresh quote proof is not valid UTF-8 JSON."
        ) from None
    evidence = artifact.get("evidence") if isinstance(artifact, dict) else None
    if not isinstance(evidence, list):
        raise ValueError("Fresh quote proof evidence is missing.")

    opening_configuration: dict[str, Any] | None = None
    clock_proof: dict[str, Any] | None = None
    task_definition_sha256 = ""
    for item in evidence:
        if not isinstance(item, dict):
            continue
        relative_path = Path(str(item.get("path", "")))
        evidence_path, evidence_bytes = read_stable_selector_artifact(
            fresh_proof_path.parent / relative_path,
            proof_name="fresh_quote_boundary",
            artifact_role="evidence",
            maximum_bytes=MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
        )
        if evidence_path.name == "scheduled_task_definition.xml":
            task_definition_sha256 = hashlib.sha256(
                evidence_bytes
            ).hexdigest()
            continue
        try:
            payload = json.loads(evidence_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if (
            payload.get("proofType")
            == "SHADOW_OPENING_CONFIGURATION_IDENTITY"
        ):
            if opening_configuration is not None:
                raise ValueError(
                    "Fresh quote proof has duplicate opening configuration evidence."
                )
            opening_configuration = dict(payload)
        if (
            payload.get("proofType")
            == "SCHWAB_REGULAR_MARKET_QUOTE_BOUNDARY"
        ):
            raw_clock = payload.get("clockSkewProof")
            if not isinstance(raw_clock, dict):
                raise ValueError(
                    "Fresh quote proof lacks clock-skew evidence."
                )
            if clock_proof is not None:
                raise ValueError(
                    "Fresh quote proof has duplicate clock-skew evidence."
                )
            clock_proof = dict(raw_clock)

    if opening_configuration is None:
        raise ValueError(
            "Fresh quote proof lacks frozen opening configuration evidence."
        )
    if clock_proof is None:
        raise ValueError(
            "Fresh quote proof lacks pre-arm clock-skew evidence."
        )
    if (
        not task_definition_sha256
        or opening_configuration.get("scheduledTaskDefinitionSha256")
        != task_definition_sha256
    ):
        raise ValueError(
            "Frozen scheduled-task definition hash does not match its evidence."
        )
    validate_opening_configuration_identity(opening_configuration)
    findings = clock_skew_findings(
        clock_proof,
        evaluated_at=evaluated_at,
    )
    if findings:
        raise ValueError(
            "Fresh quote clock-skew gate failed: " + " | ".join(findings)
        )
    return opening_configuration, clock_proof


def validate_opening_configuration_identity(
    identity: object,
    *,
    expected_build_hash: str = "",
    expected_constitution_hash: str = "",
    expected_selection_policy_fingerprint: str = "",
) -> None:
    if not isinstance(identity, Mapping):
        raise ValueError("Opening configuration identity is missing.")
    frozen = dict(identity)
    supplied_hash = str(
        frozen.pop("configurationIdentitySha256", "")
    ).strip()
    calculated_hash = hashlib.sha256(
        canonical_json(frozen).encode("utf-8")
    ).hexdigest()
    required = (
        "provider",
        "scanner",
        "reportSchemaVersion",
        "constitutionHash",
        "selectionPolicyVersion",
        "selectionPolicyFingerprint",
        "fillModelVersion",
        "evidenceSchemaVersion",
        "runtimeBuildHash",
        "scheduledTaskDefinitionSha256",
        "quoteSource",
    )
    if (
        identity.get("schemaVersion") != 1
        or identity.get("proofType")
        != "SHADOW_OPENING_CONFIGURATION_IDENTITY"
        or supplied_hash != calculated_hash
        or any(not str(identity.get(name, "")).strip() for name in required)
        or identity.get("transmitting") is not False
        or identity.get("orderTransmission") != "UNAVAILABLE"
    ):
        raise ValueError("Opening configuration identity is invalid.")
    for field_name in (
        "constitutionHash",
        "selectionPolicyFingerprint",
        "runtimeBuildHash",
        "scheduledTaskDefinitionSha256",
    ):
        value = str(identity.get(field_name, ""))
        if (
            len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)
        ):
            raise ValueError(
                f"Opening configuration {field_name} is not SHA-256."
            )
    if (
        expected_build_hash
        and identity.get("runtimeBuildHash") != expected_build_hash
    ):
        raise ValueError(
            "Opening configuration runtime build hash does not match."
        )
    if (
        expected_constitution_hash
        and identity.get("constitutionHash")
        != expected_constitution_hash
    ):
        raise ValueError(
            "Opening configuration constitution hash does not match."
        )
    if (
        expected_selection_policy_fingerprint
        and identity.get("selectionPolicyFingerprint")
        != expected_selection_policy_fingerprint
    ):
        raise ValueError(
            "Opening configuration selection policy hash does not match."
        )


def selector_arm_id(
    *,
    sample_version: str,
    strategy_configuration_fingerprint: str,
    selection_policy_fingerprint: str,
    constitution_hash: str,
    build_hash: str,
    prerequisite_proofs: dict[str, str],
) -> str:
    return stable_hash(
        "shadow-selector-arm-v2",
        sample_version,
        strategy_configuration_fingerprint,
        selection_policy_fingerprint,
        constitution_hash,
        build_hash,
        canonical_json(prerequisite_proofs),
    )

def build_counterfactual_marks(cycle: dict[str, Any]) -> list[dict[str, Any]]:
    baselines: dict[str, dict[str, Any]] = {}
    roles: dict[str, set[str]] = {}
    for assessment in cycle.get("candidate_assessments", []):
        if not isinstance(assessment, dict) or not assessment.get("eligible"):
            continue
        symbol = str(assessment.get("symbol", "")).upper()
        quote = assessment.get("quote")
        if symbol and isinstance(quote, dict):
            baselines[symbol] = quote
            roles.setdefault(symbol, set()).add(
                "SELECTED"
                if symbol == str(cycle.get("selected_symbol", "")).upper()
                else "OTHER_ELIGIBLE"
            )
    random_candidate = cycle.get("deterministic_random_eligible")
    if isinstance(random_candidate, dict):
        random_symbol = str(random_candidate.get("symbol", "")).upper()
        if random_symbol:
            roles.setdefault(random_symbol, set()).add(
                "DETERMINISTIC_RANDOM_ELIGIBLE"
            )
    for symbol, quote in dict(cycle.get("benchmark_baselines", {})).items():
        normalized = str(symbol).upper()
        if normalized:
            baselines[normalized] = quote if isinstance(quote, dict) else {}
            roles.setdefault(normalized, set()).add("BENCHMARK")

    observations_by_symbol: dict[str, list[dict[str, Any]]] = {}
    decision_at = parse_datetime(str(cycle.get("decision_at", "")))
    horizon_at = parse_datetime(
        str(cycle.get("counterfactual_horizon_at", ""))
    )
    for observation in cycle.get("market_observations", []):
        if not isinstance(observation, dict):
            continue
        symbol = str(observation.get("symbol", "")).upper()
        observed_at = parse_datetime(str(observation.get("timestamp", "")))
        if (
            symbol not in baselines
            or not is_offset_aware(observed_at)
            or not is_offset_aware(decision_at)
            or observed_at <= decision_at
            or (
                is_offset_aware(horizon_at)
                and horizon_at is not None
                and observed_at > horizon_at
            )
        ):
            continue
        observations_by_symbol.setdefault(symbol, []).append(observation)

    marks: list[dict[str, Any]] = []
    for symbol in sorted(baselines):
        baseline = baselines[symbol]
        baseline_price = quote_reference_price(baseline)
        baseline_at = parse_datetime(str(baseline.get("timestamp", "")))
        baseline_age = (
            (decision_at - baseline_at).total_seconds()
            if is_offset_aware(decision_at) and is_offset_aware(baseline_at)
            else None
        )
        baseline_available = (
            baseline_price is not None
            and baseline_price > 0
            and baseline_age is not None
            and 0 <= baseline_age <= ShadowMarketValidityPolicy().quote_max_age_seconds
        )
        observations = observations_by_symbol.get(symbol, [])
        latest = max(
            observations,
            key=lambda item: str(item.get("timestamp", "")),
            default=None,
        )
        latest_price = quote_reference_price(latest)
        available = (
            baseline_available
            and latest_price is not None
        )
        marks.append(
            {
                "symbol": symbol,
                "roles": sorted(roles.get(symbol, ())),
                "baseline_timestamp": str(baseline.get("timestamp", "")),
                "baseline_price": baseline_price,
                "baseline_available": baseline_available,
                "latest_timestamp": (
                    str(latest.get("timestamp", "")) if latest else None
                ),
                "latest_price": latest_price,
                "return_percent": (
                    round(
                        (latest_price - baseline_price)
                        / baseline_price
                        * 100,
                        6,
                    )
                    if available
                    else None
                ),
                "observation_count": len(observations),
                "available": available,
                "measurement": (
                    "SELECTED_TRADE_HOLDING_WINDOW"
                    if is_offset_aware(horizon_at)
                    else "MARK_TO_LATEST_NOT_A_TRADED_OUTCOME"
                ),
            }
        )
    return marks


def decision_cycle_summary(
    cycles: Iterable[dict[str, Any]],
    trades: Iterable[Any] = (),
) -> dict[str, Any]:
    cycles = tuple(cycles)
    trades = tuple(trades)
    attempts = tuple(
        item for item in cycles if item.get("cycle_kind") == "COLLECTION_ATTEMPT"
    )
    decisions = tuple(
        item for item in cycles if item.get("cycle_kind") != "COLLECTION_ATTEMPT"
    )
    denominator = attempts or decisions
    status_counts: dict[str, int] = {}
    for cycle in cycles:
        status = str(cycle.get("status", "UNKNOWN"))
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "expectedCycles": len(denominator),
        "successfulCaptures": sum(
            bool(item.get("capture_succeeded")) for item in denominator
        ),
        "reportsCreated": sum(
            bool(item.get("report_sha256")) for item in decisions
        ),
        "reportsRejectedStale": sum(
            item.get("status") == "INVALID_REPORT"
            and "stale" in str(item.get("reason", "")).lower()
            for item in decisions
        ),
        "reportsRejectedDataQuality": sum(
            item.get("status") == "NO_ELIGIBLE_CANDIDATE"
            and any(
                bool(assessment.get("fatal_warnings"))
                for assessment in item.get("candidate_assessments", [])
                if isinstance(assessment, dict)
            )
            for item in decisions
        ),
        "reportsWithNoEligibleCandidates": sum(
            item.get("status") == "NO_ELIGIBLE_CANDIDATE"
            for item in decisions
        ),
        "selectionsAttempted": sum(
            item.get("status")
            not in {"COLLECTION_FAILED", "NO_REPORT", "CONSTITUTION_NOT_ARMED"}
            for item in decisions
        ),
        "tradesStarted": sum(
            item.get("status") == "TRADE_STARTED" for item in decisions
        ),
        "ordersUnfilled": sum(
            getattr(item, "status", "") in {"pending_entry", "cancelled"}
            and getattr(item, "position", None) is None
            for item in trades
        ),
        "tradesCompleted": sum(
            getattr(item, "status", "") == "completed" for item in trades
        ),
        "collectionFailures": sum(
            item.get("status") == "COLLECTION_FAILED" for item in attempts
        ),
        "systemDowntimeCycles": sum(
            item.get("status") == "SYSTEM_DOWNTIME" for item in attempts
        ),
        "counterfactualMarksAvailable": sum(
            bool(mark.get("available"))
            for item in decisions
            for mark in item.get("counterfactual_marks", [])
            if isinstance(mark, dict)
        ),
        "denominatorScope": (
            "EXPECTED_IN_WINDOW_ENGINE_HOST_CYCLES"
            if attempts
            else "RECORDED_DECISION_CYCLES"
        ),
        "statusCounts": status_counts,
    }


def is_offset_aware(value: datetime | None) -> bool:
    return (
        value is not None
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def optional_float(value: Any) -> float | None:
    try:
        parsed = float(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed is not None and math.isfinite(parsed) else None


def quote_reference_price(quote: dict[str, Any] | None) -> float | None:
    if not isinstance(quote, dict):
        return None
    bid = optional_float(quote.get("bid"))
    ask = optional_float(quote.get("ask"))
    if bid is not None and ask is not None and bid > 0 and ask >= bid:
        return round((bid + ask) / 2, 8)
    value = optional_float(quote.get("last"))
    return value if value is not None and value > 0 else None


def same_eastern_date(value: str, expected: date) -> bool:
    parsed = parse_datetime(value)
    return bool(
        is_offset_aware(parsed)
        and parsed is not None
        and parsed.astimezone(EASTERN_TZ).date() == expected
    )


def nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    value = date(year, month, 1)
    while value.weekday() != weekday:
        value = value.replace(day=value.day + 1)
    return value.replace(day=value.day + 7 * (occurrence - 1))
