"""Offline market-regime, exhaustion, and stress research specialist.

The evaluator consumes caller-supplied canonical minute bars, reuses the
CONTINUOUS-003 rolling-regime classifier, and emits the common research-only
Specialist Opinion Contract plus a versioned REGIME-specific assessment.
It has no provider, persistence, runtime, risk, broker, or order capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta, timezone
from statistics import median, pstdev
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from momentum_hunter.macro_event_context import (
    BLOCK_NEW_ENTRY,
    CAUTION,
    DATA_STALE as MACRO_DATA_STALE,
    EventRiskContext as MacroEventRiskContext,
    validate_context as validate_macro_context,
)
from momentum_hunter.rolling_market_regime import (
    CANONICAL_BAR_STATES,
    DATA_STALE as ROLLING_DATA_STALE,
    VOLATILITY_SHOCK as ROLLING_VOLATILITY_SHOCK,
    RegimeBar,
    RegimePolicy,
    RegimeSnapshot,
    RollingMarketRegimeError,
    derive_regime_snapshot,
    validate_bar,
    validate_snapshot,
)
from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    BEARISH,
    BULLISH,
    EVALUATED,
    EXECUTION_AUTHORITY_NONE,
    FAILED,
    HEURISTIC,
    NEUTRAL,
    NON_DIRECTIONAL,
    NO_DIRECTION,
    NO_OPINION,
    RESEARCH_ONLY,
    UNCALIBRATED,
    EvidenceReference,
    SpecialistOpinion,
    build_confidence,
    build_evidence_reference,
    build_specialist_opinion,
    opinion_to_wire,
    unavailable_confidence,
    validate_specialist_opinion,
)


REGIME_SPECIALIST_SCHEMA_VERSION = 1
REGIME_SPECIALIST_PROFILE = "regime-exhaustion-research-packet-v1"
REGIME_SPECIALIST_ID = "REGIME"
REGIME_SPECIALIST_VERSION = "regime-exhaustion-research-v1"
RESEARCH_HEURISTIC = "RESEARCH_HEURISTIC"

TREND_UP = "TREND_UP"
TREND_DOWN = "TREND_DOWN"
ROTATION = "ROTATION"
CHOP = "CHOP"
MIXED = "MIXED"
UNKNOWN_DIRECTION = "UNKNOWN_DIRECTION"
DIRECTION_STATES = frozenset(
    {TREND_UP, TREND_DOWN, ROTATION, CHOP, MIXED, UNKNOWN_DIRECTION}
)

NORMAL_EXTENSION = "NORMAL_EXTENSION"
LATE_TREND = "LATE_TREND"
EXHAUSTION_RISK = "EXHAUSTION_RISK"
EXTREME_EXTENSION = "EXTREME_EXTENSION"
UNKNOWN_EXTENSION = "UNKNOWN_EXTENSION"
EXTENSION_STATES = frozenset(
    {
        NORMAL_EXTENSION,
        LATE_TREND,
        EXHAUSTION_RISK,
        EXTREME_EXTENSION,
        UNKNOWN_EXTENSION,
    }
)

NORMAL = "NORMAL"
ELEVATED_VOLATILITY = "ELEVATED_VOLATILITY"
VOLATILITY_SHOCK = "VOLATILITY_SHOCK"
MARKET_STRESS = "MARKET_STRESS"
DATA_UNSAFE = "DATA_UNSAFE"
STRESS_STATES = frozenset(
    {NORMAL, ELEVATED_VOLATILITY, VOLATILITY_SHOCK, MARKET_STRESS, DATA_UNSAFE}
)

PREMARKET = "PREMARKET"
OPENING = "OPENING"
MIDDAY = "MIDDAY"
LATE_SESSION = "LATE_SESSION"
AFTER_HOURS = "AFTER_HOURS"
UNSUPPORTED_SESSION = "UNSUPPORTED_SESSION"
SESSION_STATES = frozenset(
    {PREMARKET, OPENING, MIDDAY, LATE_SESSION, AFTER_HOURS, UNSUPPORTED_SESSION}
)

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
DATA_QUALITY_STATES = frozenset({COMPLETE, PARTIAL, DATA_UNSAFE})

FULL_MARKET_EVIDENCE = "FULL_MARKET_EVIDENCE"
INCOMPLETE_MARKET_EVIDENCE = "INCOMPLETE_MARKET_EVIDENCE"
BOUNDED_CANDIDATE_UNIVERSE_PROXY = "BOUNDED_CANDIDATE_UNIVERSE_PROXY"
TRUE_04_TO_07_PATH_UNOBSERVED = "TRUE_04_TO_07_PATH_UNOBSERVED"
BAR_DERIVED_VWAP = "BAR_DERIVED_VWAP"

_EASTERN = ZoneInfo("America/New_York")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CORE_HORIZONS = (1, 5, 15, 30, 60)
_THRESHOLDED_SESSIONS = (PREMARKET, OPENING, MIDDAY, LATE_SESSION)


class RegimeResearchError(ValueError):
    """Raised when policy or packet state is malformed or contradictory."""


@dataclass(frozen=True)
class RegimeResearchPolicy:
    policy_version: str
    specialist_version: str
    research_identity: str
    required_benchmarks: tuple[str, ...]
    return_horizons_minutes: tuple[int, ...]
    stale_after_seconds: int
    maximum_cross_symbol_skew_seconds: int
    maximum_internal_gap_seconds: int
    opening_range_minutes: int
    atr_window_bars: int
    realized_volatility_window_bars: int
    direction_alignment_fraction: float
    direction_threshold_15m_pct: float
    rotation_dispersion_15m_pct: float
    chop_max_abs_return_15m_pct: float
    elevated_volatility_multiple: float
    volatility_shock_multiple: float
    market_stress_down_return_5m_pct: float
    late_trend_vwap_atr: float
    exhaustion_vwap_atr: float
    extreme_vwap_atr: float
    exhaustion_return_30m_pct: float
    extreme_return_30m_pct: float
    session_threshold_multipliers: tuple[tuple[str, float], ...]
    opinion_ttl_seconds: int
    threshold_semantics: str = RESEARCH_HEURISTIC
    allow_after_hours_evaluation: bool = False
    proposed_cadence_minutes: int = 5

    @property
    def fingerprint(self) -> str:
        return _fingerprint(asdict(self))


@dataclass(frozen=True)
class ParticipationProxy:
    observed_count: int
    advancing_count: int
    declining_count: int
    unchanged_count: int
    as_of: str
    source_identity: str
    evidence_fingerprint: str
    evidence_scope: str = BOUNDED_CANDIDATE_UNIVERSE_PROXY


@dataclass(frozen=True)
class BenchmarkFeatures:
    symbol: str
    source_identity: str
    source_state: str
    first_bar_timestamp: str
    latest_bar_timestamp: str
    bar_count: int
    current_price: float
    return_1m_pct: float
    return_5m_pct: float
    return_15m_pct: float
    return_30m_pct: float
    return_60m_pct: float
    return_since_open_pct: float | None
    return_vs_prior_close_pct: float | None
    premarket_return_pct: float | None
    session_high: float
    session_low: float
    distance_from_session_high_pct: float
    distance_from_session_low_pct: float
    consecutive_higher_highs: int
    consecutive_lower_lows: int
    opening_range_high: float | None
    opening_range_low: float | None
    opening_range_location: float | None
    vwap_kind: str
    bar_derived_vwap: float | None
    distance_from_vwap_pct: float | None
    distance_from_vwap_atr: float | None
    atr: float
    atr_pct: float
    realized_volatility_1m_pct: float
    current_range_pct: float
    range_expansion_multiple: float
    speed_5m_pct_per_minute: float
    acceleration_5m_pct_per_minute: float
    consecutive_directional_bars: int
    bars_since_material_pullback: int
    price_progress_per_million_volume_15m: float | None
    incremental_progress_ratio_5m_to_15m: float | None


@dataclass(frozen=True)
class RegimeResearchAssessment:
    assessment_id: str
    evaluated_at: str
    session_state: str
    direction_state: str
    extension_state: str
    stress_state: str
    data_quality_state: str
    evidence_scope: str
    missing_benchmarks: tuple[str, ...]
    limitations: tuple[str, ...]
    reason_codes: tuple[str, ...]
    benchmark_features: tuple[BenchmarkFeatures, ...]
    benchmark_agreement_fraction: float | None
    benchmark_return_dispersion_15m_pct: float | None
    bounded_participation_proxy: ParticipationProxy | None
    rolling_snapshot_id: str
    rolling_regime: str
    rolling_snapshot_fingerprint: str
    macro_context_id: str
    macro_context_status: str
    input_evidence_fingerprint: str
    policy_version: str
    policy_fingerprint: str
    score_authority: str = "NONE"
    trade_recommendation: bool = False
    fingerprint: str = ""


@dataclass(frozen=True)
class RegimeSpecialistPacket:
    policy: RegimeResearchPolicy
    assessment: RegimeResearchAssessment
    opinion: SpecialistOpinion
    schema_version: int = REGIME_SPECIALIST_SCHEMA_VERSION
    profile: str = REGIME_SPECIALIST_PROFILE
    fingerprint: str = ""


def default_regime_research_policy() -> RegimeResearchPolicy:
    """Return the frozen v1 policy; thresholds are provisional research heuristics."""

    policy = RegimeResearchPolicy(
        policy_version="regime-exhaustion-research-policy-v1",
        specialist_version=REGIME_SPECIALIST_VERSION,
        research_identity="regime-research-v1",
        required_benchmarks=("SPY", "QQQ", "IWM"),
        return_horizons_minutes=_CORE_HORIZONS,
        stale_after_seconds=90,
        maximum_cross_symbol_skew_seconds=5,
        maximum_internal_gap_seconds=65,
        opening_range_minutes=5,
        atr_window_bars=14,
        realized_volatility_window_bars=15,
        direction_alignment_fraction=2 / 3,
        direction_threshold_15m_pct=0.20,
        rotation_dispersion_15m_pct=0.60,
        chop_max_abs_return_15m_pct=0.12,
        elevated_volatility_multiple=1.50,
        volatility_shock_multiple=2.50,
        market_stress_down_return_5m_pct=0.75,
        late_trend_vwap_atr=1.50,
        exhaustion_vwap_atr=2.50,
        extreme_vwap_atr=3.50,
        exhaustion_return_30m_pct=1.50,
        extreme_return_30m_pct=2.50,
        session_threshold_multipliers=(
            (PREMARKET, 1.25),
            (OPENING, 1.00),
            (MIDDAY, 0.75),
            (LATE_SESSION, 1.00),
        ),
        opinion_ttl_seconds=300,
    )
    validate_policy(policy)
    return policy


def market_observation_id(*, research_identity: str, evaluated_at: datetime) -> str:
    evaluated = _aware(evaluated_at, "Evaluation timestamp")
    return _fingerprint(
        {
            "researchIdentity": _identifier(research_identity, "Research identity"),
            "evaluatedAt": _iso(evaluated),
            "target": "PERIODIC_MARKET_OBSERVATION",
        }
    )


def evaluate_regime_specialist(
    *,
    bars_by_symbol: Mapping[str, Sequence[RegimeBar]],
    evaluated_at: datetime,
    policy: RegimeResearchPolicy,
    prior_close_by_symbol: Mapping[str, float] | None = None,
    opportunity_id: str | None = None,
    candidate_id: str | None = None,
    setup_id: str | None = None,
    trade_plan_id: str | None = None,
    participation_proxy: ParticipationProxy | None = None,
    macro_context: MacroEventRiskContext | None = None,
    expected_input_evidence_fingerprint: str | None = None,
) -> RegimeSpecialistPacket:
    """Evaluate one immutable, research-only market observation."""

    validate_policy(policy)
    evaluated = _aware(evaluated_at, "Evaluation timestamp")
    session_state = classify_session(evaluated)
    target_id = opportunity_id or market_observation_id(
        research_identity=policy.research_identity,
        evaluated_at=evaluated,
    )
    prior_closes = _normalize_prior_closes(prior_close_by_symbol or {})
    if participation_proxy is not None:
        validate_participation_proxy(participation_proxy, evaluated_at=evaluated)
    if macro_context is not None:
        validate_macro_context(macro_context)
        if _parse_timestamp(macro_context.evaluated_at) > evaluated:
            return _failed_packet(
                evaluated=evaluated,
                session_state=session_state,
                policy=policy,
                target_id=target_id,
                candidate_id=candidate_id,
                setup_id=setup_id,
                trade_plan_id=trade_plan_id,
                reason="MACRO_CONTEXT_FUTURE_DATED",
            )
        if macro_context.target_opportunity_id and (
            macro_context.target_opportunity_id != target_id
        ):
            return _failed_packet(
                evaluated=evaluated,
                session_state=session_state,
                policy=policy,
                target_id=target_id,
                candidate_id=candidate_id,
                setup_id=setup_id,
                trade_plan_id=trade_plan_id,
                reason="MACRO_CONTEXT_TARGET_MISMATCH",
            )
        if macro_context.status == MACRO_DATA_STALE:
            return _abstained_packet(
                evaluated=evaluated,
                session_state=session_state,
                policy=policy,
                target_id=target_id,
                candidate_id=candidate_id,
                setup_id=setup_id,
                trade_plan_id=trade_plan_id,
                reason="DATA_BASIS_UNCERTAIN",
                machine_reason="MACRO_CONTEXT_DATA_STALE",
            )

    copied: dict[str, tuple[RegimeBar, ...]] = {}
    for raw_symbol, rows in bars_by_symbol.items():
        symbol = str(raw_symbol).strip().upper()
        if symbol in copied:
            return _failed_packet(
                evaluated=evaluated,
                session_state=session_state,
                policy=policy,
                target_id=target_id,
                candidate_id=candidate_id,
                setup_id=setup_id,
                trade_plan_id=trade_plan_id,
                reason="DUPLICATE_NORMALIZED_BENCHMARK_IDENTITY",
            )
        copied[symbol] = tuple(rows)
    missing = tuple(
        symbol for symbol in policy.required_benchmarks if symbol not in copied
    )
    if missing:
        return _abstained_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="INSUFFICIENT_EVIDENCE",
            machine_reason="MISSING_CORE_BENCHMARK:" + ",".join(missing),
            missing_benchmarks=missing,
        )
    extras = sorted(set(copied) - set(policy.required_benchmarks))
    if extras:
        return _failed_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="UNDECLARED_BENCHMARK_INPUT:" + ",".join(extras),
        )
    if session_state in {AFTER_HOURS, UNSUPPORTED_SESSION} and (
        not policy.allow_after_hours_evaluation
    ):
        return _abstained_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="UNSUPPORTED_SESSION",
            machine_reason="SESSION_THRESHOLDS_NOT_VALIDATED",
        )

    try:
        normalized = _normalize_bars(copied, evaluated=evaluated, policy=policy)
    except RegimeResearchError as exc:
        return _failed_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason=str(exc),
        )

    empty = tuple(symbol for symbol, rows in normalized.items() if not rows)
    if empty:
        return _abstained_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="INSUFFICIENT_EVIDENCE",
            machine_reason="EMPTY_CORE_BENCHMARK:" + ",".join(empty),
        )

    latest_times = {
        symbol: _parse_timestamp(rows[-1].timestamp)
        for symbol, rows in normalized.items()
    }
    if max(latest_times.values()) - min(latest_times.values()) > timedelta(
        seconds=policy.maximum_cross_symbol_skew_seconds
    ):
        return _failed_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="CROSS_BENCHMARK_TIMESTAMP_SKEW",
        )
    stale = tuple(
        symbol
        for symbol, timestamp in latest_times.items()
        if (evaluated - (timestamp + timedelta(minutes=1))).total_seconds()
        > policy.stale_after_seconds
    )
    if stale:
        return _abstained_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="STALE_EVIDENCE",
            machine_reason="STALE_CORE_BENCHMARK:" + ",".join(stale),
        )
    required_bar_count = max(policy.return_horizons_minutes) + 1
    insufficient = tuple(
        symbol
        for symbol, rows in normalized.items()
        if len(rows) < required_bar_count
    )
    if insufficient:
        return _abstained_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="INSUFFICIENT_EVIDENCE",
            machine_reason="INCOMPLETE_RETURN_HORIZON:" + ",".join(insufficient),
        )
    if session_state in {OPENING, MIDDAY, LATE_SESSION}:
        missing_opening = tuple(
            symbol
            for symbol, rows in normalized.items()
            if not _has_complete_opening_range(rows, evaluated, policy)
        )
        if missing_opening:
            return _abstained_packet(
                evaluated=evaluated,
                session_state=session_state,
                policy=policy,
                target_id=target_id,
                candidate_id=candidate_id,
                setup_id=setup_id,
                trade_plan_id=trade_plan_id,
                reason="INSUFFICIENT_EVIDENCE",
                machine_reason="MISSING_OPENING_RANGE:" + ",".join(missing_opening),
            )

    input_fingerprint = _input_evidence_fingerprint(
        normalized,
        prior_closes=prior_closes,
        participation_proxy=participation_proxy,
        macro_context=macro_context,
    )
    if expected_input_evidence_fingerprint is not None and (
        expected_input_evidence_fingerprint != input_fingerprint
    ):
        return _failed_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="INPUT_EVIDENCE_FINGERPRINT_MISMATCH",
        )

    rolling_policy = _rolling_policy(policy, session_state)
    try:
        rolling = derive_regime_snapshot(
            bars_by_symbol=normalized,
            sector_symbols=(),
            policy=rolling_policy,
            evaluated_at=evaluated,
        )
        validate_snapshot(rolling)
    except RollingMarketRegimeError as exc:
        return _failed_packet(
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            target_id=target_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            reason="ROLLING_REGIME_REJECTED_INPUT:" + str(exc),
        )

    features = tuple(
        _benchmark_features(
            symbol,
            normalized[symbol],
            evaluated=evaluated,
            session_state=session_state,
            prior_close=prior_closes.get(symbol),
            policy=policy,
        )
        for symbol in policy.required_benchmarks
    )
    direction, direction_reason, agreement, dispersion = _direction_state(
        rolling, features, policy, session_state
    )
    extension, extension_reason = _extension_state(features, policy, session_state)
    stress, stress_reason = _stress_state(
        rolling,
        features,
        macro_context,
        policy,
        session_state,
    )
    limitations: list[str] = []
    if session_state == PREMARKET:
        limitations.append(TRUE_04_TO_07_PATH_UNOBSERVED)
    if any(item.return_vs_prior_close_pct is None for item in features):
        limitations.append("PRIOR_CLOSE_UNAVAILABLE")
    elif prior_closes:
        limitations.append("PRIOR_CLOSE_PROVENANCE_CALLER_SUPPLIED")
    if any(item.bar_derived_vwap is None for item in features):
        limitations.append("BAR_DERIVED_VWAP_UNAVAILABLE")
    if participation_proxy is None:
        limitations.append("CANDIDATE_PARTICIPATION_UNAVAILABLE")
    data_quality = PARTIAL if limitations else COMPLETE
    reason_codes = [direction_reason, extension_reason, stress_reason]
    reason_codes.append(f"SESSION_THRESHOLD_PROFILE_{session_state}")
    if participation_proxy is not None:
        reason_codes.append("BOUNDED_PARTICIPATION_PROXY_PRESENT")
    if limitations:
        reason_codes.append("DATA_QUALITY_PARTIAL")
    assessment = _complete_assessment(
        evaluated=evaluated,
        session_state=session_state,
        direction_state=direction,
        extension_state=extension,
        stress_state=stress,
        data_quality_state=data_quality,
        missing_benchmarks=(),
        limitations=tuple(sorted(limitations)),
        reason_codes=tuple(sorted(set(reason_codes))),
        benchmark_features=features,
        benchmark_agreement_fraction=agreement,
        benchmark_return_dispersion_15m_pct=dispersion,
        participation_proxy=participation_proxy,
        rolling=rolling,
        macro_context=macro_context,
        input_fingerprint=input_fingerprint,
        policy=policy,
    )
    references = _evidence_references(
        normalized,
        rolling=rolling,
        macro_context=macro_context,
        participation_proxy=participation_proxy,
    )
    opinion = _evaluated_opinion(
        assessment=assessment,
        references=references,
        target_id=target_id,
        candidate_id=candidate_id,
        setup_id=setup_id,
        trade_plan_id=trade_plan_id,
        policy=policy,
    )
    return _packet(policy=policy, assessment=assessment, opinion=opinion)


def classify_session(evaluated_at: datetime) -> str:
    eastern = _aware(evaluated_at, "Evaluation timestamp").astimezone(_EASTERN)
    clock = eastern.timetz().replace(tzinfo=None)
    if time(7, 0) <= clock < time(9, 30):
        return PREMARKET
    if time(9, 30) <= clock < time(10, 0):
        return OPENING
    if time(10, 0) <= clock < time(15, 0):
        return MIDDAY
    if time(15, 0) <= clock < time(16, 0):
        return LATE_SESSION
    if time(16, 0) <= clock < time(20, 0):
        return AFTER_HOURS
    return UNSUPPORTED_SESSION


def validate_policy(policy: RegimeResearchPolicy) -> None:
    if not isinstance(policy, RegimeResearchPolicy):
        raise RegimeResearchError("Regime research policy is malformed.")
    _identifier(policy.policy_version, "Policy version")
    if policy.specialist_version != REGIME_SPECIALIST_VERSION:
        raise RegimeResearchError("Specialist version is unsupported.")
    _identifier(policy.research_identity, "Research identity")
    if policy.required_benchmarks != ("SPY", "QQQ", "IWM"):
        raise RegimeResearchError("Core benchmark policy must be SPY/QQQ/IWM.")
    if policy.return_horizons_minutes != _CORE_HORIZONS:
        raise RegimeResearchError("Return-horizon policy is unsupported.")
    if any(
        not isinstance(item, tuple)
        or len(item) != 2
        or isinstance(item[1], bool)
        or not isinstance(item[1], (int, float))
        or not math.isfinite(float(item[1]))
        or item[1] <= 0
        for item in policy.session_threshold_multipliers
    ):
        raise RegimeResearchError(
            "Session threshold multipliers must be positive finite values."
        )
    if tuple(item[0] for item in policy.session_threshold_multipliers) != (
        _THRESHOLDED_SESSIONS
    ):
        raise RegimeResearchError(
            "Session threshold multipliers must cover the supported sessions in canonical order."
        )
    integer_fields = (
        policy.stale_after_seconds,
        policy.maximum_cross_symbol_skew_seconds,
        policy.maximum_internal_gap_seconds,
        policy.opening_range_minutes,
        policy.atr_window_bars,
        policy.realized_volatility_window_bars,
        policy.opinion_ttl_seconds,
        policy.proposed_cadence_minutes,
    )
    if any(type(value) is not int or value <= 0 for value in integer_fields):
        raise RegimeResearchError("Policy integer thresholds must be positive.")
    numeric_fields = (
        policy.direction_alignment_fraction,
        policy.direction_threshold_15m_pct,
        policy.rotation_dispersion_15m_pct,
        policy.chop_max_abs_return_15m_pct,
        policy.elevated_volatility_multiple,
        policy.volatility_shock_multiple,
        policy.market_stress_down_return_5m_pct,
        policy.late_trend_vwap_atr,
        policy.exhaustion_vwap_atr,
        policy.extreme_vwap_atr,
        policy.exhaustion_return_30m_pct,
        policy.extreme_return_30m_pct,
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
        for value in numeric_fields
    ):
        raise RegimeResearchError("Policy numeric thresholds must be positive finite values.")
    if not 0.5 <= policy.direction_alignment_fraction <= 1.0:
        raise RegimeResearchError("Direction alignment must be within [0.5, 1.0].")
    if not (
        1.0 < policy.elevated_volatility_multiple
        < policy.volatility_shock_multiple
    ):
        raise RegimeResearchError("Volatility thresholds are not ordered.")
    if not (
        0 < policy.late_trend_vwap_atr
        < policy.exhaustion_vwap_atr
        < policy.extreme_vwap_atr
    ):
        raise RegimeResearchError("Extension thresholds are not ordered.")
    if policy.threshold_semantics != RESEARCH_HEURISTIC:
        raise RegimeResearchError("Policy thresholds must remain RESEARCH_HEURISTIC.")
    if type(policy.allow_after_hours_evaluation) is not bool:
        raise RegimeResearchError("After-hours policy must be boolean.")
    if policy.allow_after_hours_evaluation:
        raise RegimeResearchError(
            "After-hours evaluation is unsupported by the v1 research policy."
        )


def validate_participation_proxy(
    proxy: ParticipationProxy,
    *,
    evaluated_at: datetime,
) -> None:
    if not isinstance(proxy, ParticipationProxy):
        raise RegimeResearchError("Participation proxy is malformed.")
    counts = (
        proxy.observed_count,
        proxy.advancing_count,
        proxy.declining_count,
        proxy.unchanged_count,
    )
    if any(type(value) is not int or value < 0 for value in counts):
        raise RegimeResearchError("Participation counts must be nonnegative integers.")
    if sum(counts[1:]) != proxy.observed_count:
        raise RegimeResearchError("Participation proxy denominator is inconsistent.")
    if proxy.evidence_scope != BOUNDED_CANDIDATE_UNIVERSE_PROXY:
        raise RegimeResearchError("Participation proxy claimed full-market breadth.")
    if _parse_timestamp(proxy.as_of) > evaluated_at:
        raise RegimeResearchError("Participation proxy is future-dated.")
    _identifier(proxy.source_identity, "Participation source identity")
    _sha256(proxy.evidence_fingerprint, "Participation evidence fingerprint")


def validate_assessment(assessment: RegimeResearchAssessment) -> None:
    if not isinstance(assessment, RegimeResearchAssessment):
        raise RegimeResearchError("Regime assessment is malformed.")
    if assessment.direction_state not in DIRECTION_STATES:
        raise RegimeResearchError("Direction state is unsupported.")
    if assessment.extension_state not in EXTENSION_STATES:
        raise RegimeResearchError("Extension state is unsupported.")
    if assessment.stress_state not in STRESS_STATES:
        raise RegimeResearchError("Stress state is unsupported.")
    if assessment.session_state not in SESSION_STATES:
        raise RegimeResearchError("Session state is unsupported.")
    if assessment.data_quality_state not in DATA_QUALITY_STATES:
        raise RegimeResearchError("Data-quality state is unsupported.")
    if assessment.evidence_scope not in {
        FULL_MARKET_EVIDENCE,
        INCOMPLETE_MARKET_EVIDENCE,
    }:
        raise RegimeResearchError("Evidence scope is unsupported.")
    if assessment.score_authority != "NONE" or assessment.trade_recommendation:
        raise RegimeResearchError("Regime assessment claimed production authority.")
    evaluated = _parse_timestamp(assessment.evaluated_at)
    if assessment.evaluated_at != _iso(evaluated):
        raise RegimeResearchError("Assessment timestamp is not canonical UTC.")
    if assessment.missing_benchmarks != tuple(sorted(assessment.missing_benchmarks)) or any(
        item not in {"SPY", "QQQ", "IWM"}
        for item in assessment.missing_benchmarks
    ):
        raise RegimeResearchError("Missing-benchmark identity is invalid.")
    for token in (*assessment.limitations, *assessment.reason_codes):
        if _reason_token(token) != token:
            raise RegimeResearchError("Assessment reason metadata is not canonical.")
    symbols = tuple(item.symbol for item in assessment.benchmark_features)
    if symbols and symbols != ("SPY", "QQQ", "IWM"):
        raise RegimeResearchError("Assessment benchmark features are incomplete or unordered.")
    if symbols:
        if assessment.evidence_scope != FULL_MARKET_EVIDENCE or assessment.missing_benchmarks:
            raise RegimeResearchError("Complete benchmark features contradict evidence scope.")
        if assessment.data_quality_state == DATA_UNSAFE:
            raise RegimeResearchError("Unsafe assessment cannot carry trusted benchmark features.")
        if assessment.rolling_regime == ROLLING_DATA_STALE:
            raise RegimeResearchError("Evaluated assessment lacks rolling-regime evidence.")
        _identifier(assessment.rolling_snapshot_id, "Rolling snapshot identity")
        _sha256(assessment.rolling_snapshot_fingerprint, "Rolling snapshot fingerprint")
        if assessment.benchmark_agreement_fraction is None or not (
            0.0 <= assessment.benchmark_agreement_fraction <= 1.0
        ):
            raise RegimeResearchError("Benchmark agreement is invalid.")
        if assessment.benchmark_return_dispersion_15m_pct is None or (
            assessment.benchmark_return_dispersion_15m_pct < 0
        ):
            raise RegimeResearchError("Benchmark return dispersion is invalid.")
        for feature in assessment.benchmark_features:
            _validate_benchmark_features(feature, evaluated=evaluated)
    else:
        if assessment.evidence_scope != INCOMPLETE_MARKET_EVIDENCE:
            raise RegimeResearchError("Missing benchmark features claimed complete evidence.")
        if (
            assessment.direction_state != UNKNOWN_DIRECTION
            or assessment.extension_state != UNKNOWN_EXTENSION
            or assessment.stress_state != DATA_UNSAFE
            or assessment.data_quality_state != DATA_UNSAFE
        ):
            raise RegimeResearchError("Unsafe assessment carried a market classification.")
        if assessment.benchmark_agreement_fraction is not None or (
            assessment.benchmark_return_dispersion_15m_pct is not None
        ):
            raise RegimeResearchError("Unsafe assessment fabricated benchmark aggregates.")
    if assessment.bounded_participation_proxy is not None:
        validate_participation_proxy(
            assessment.bounded_participation_proxy,
            evaluated_at=evaluated,
        )
    if bool(assessment.macro_context_id) != bool(assessment.macro_context_status):
        raise RegimeResearchError("Macro context identity/status is incomplete.")
    if assessment.macro_context_id:
        _identifier(assessment.macro_context_id, "Macro context identity")
    _identifier(assessment.policy_version, "Policy version")
    _sha256(assessment.assessment_id, "Assessment identity")
    _sha256(assessment.input_evidence_fingerprint, "Input fingerprint")
    _sha256(assessment.policy_fingerprint, "Policy fingerprint")
    expected = _assessment_fingerprint(assessment)
    if assessment.fingerprint != expected:
        raise RegimeResearchError("Regime assessment fingerprint is invalid.")
    if assessment.assessment_id != _fingerprint(
        {
            "evaluatedAt": assessment.evaluated_at,
            "inputEvidenceFingerprint": assessment.input_evidence_fingerprint,
            "policyFingerprint": assessment.policy_fingerprint,
        }
    ):
        raise RegimeResearchError("Regime assessment identity is invalid.")


def validate_packet(packet: RegimeSpecialistPacket) -> None:
    if not isinstance(packet, RegimeSpecialistPacket):
        raise RegimeResearchError("Regime specialist packet is malformed.")
    validate_policy(packet.policy)
    validate_assessment(packet.assessment)
    validate_specialist_opinion(packet.opinion)
    if packet.schema_version != REGIME_SPECIALIST_SCHEMA_VERSION or (
        packet.profile != REGIME_SPECIALIST_PROFILE
    ):
        raise RegimeResearchError("Regime packet schema identity is unsupported.")
    if packet.assessment.policy_fingerprint != packet.policy.fingerprint or (
        packet.opinion.policy_fingerprint != packet.policy.fingerprint
    ):
        raise RegimeResearchError("Regime packet policy identity is inconsistent.")
    if packet.assessment.policy_version != packet.policy.policy_version:
        raise RegimeResearchError("Regime packet policy version is inconsistent.")
    if packet.opinion.specialist_id != REGIME_SPECIALIST_ID or (
        packet.opinion.specialist_version != packet.policy.specialist_version
    ):
        raise RegimeResearchError("Regime packet specialist identity is inconsistent.")
    if packet.opinion.authority != RESEARCH_ONLY or (
        packet.opinion.execution_authority != EXECUTION_AUTHORITY_NONE
    ):
        raise RegimeResearchError("Regime packet claimed execution authority.")
    if packet.opinion.as_of != packet.assessment.evaluated_at:
        raise RegimeResearchError("Regime packet opinion/assessment time is inconsistent.")
    if packet.assessment.data_quality_state == DATA_UNSAFE:
        if packet.opinion.evaluation_status not in {ABSTAINED, FAILED}:
            raise RegimeResearchError("Unsafe assessment was represented as evaluated opinion.")
        if packet.opinion.directional_bias != NO_DIRECTION:
            raise RegimeResearchError("Unsafe assessment was represented as directional opinion.")
    elif packet.opinion.evaluation_status != EVALUATED:
        raise RegimeResearchError("Trusted assessment did not produce evaluated opinion.")
    if packet.fingerprint != _packet_fingerprint(packet):
        raise RegimeResearchError("Regime packet fingerprint is invalid.")


def packet_to_wire(packet: RegimeSpecialistPacket) -> dict[str, object]:
    validate_packet(packet)
    return {
        "schemaVersion": packet.schema_version,
        "profile": packet.profile,
        "policy": asdict(packet.policy),
        "assessment": asdict(packet.assessment),
        "opinion": opinion_to_wire(packet.opinion),
        "fingerprint": packet.fingerprint,
    }


def packet_json_bytes(packet: RegimeSpecialistPacket) -> bytes:
    return _canonical_json_bytes(packet_to_wire(packet)) + b"\n"


def _validate_benchmark_features(
    feature: BenchmarkFeatures,
    *,
    evaluated: datetime,
) -> None:
    if not isinstance(feature, BenchmarkFeatures):
        raise RegimeResearchError("Benchmark feature row is malformed.")
    if feature.symbol not in {"SPY", "QQQ", "IWM"}:
        raise RegimeResearchError("Benchmark feature symbol is invalid.")
    _identifier(feature.source_identity, "Benchmark source identity")
    if feature.source_state not in CANONICAL_BAR_STATES:
        raise RegimeResearchError("Benchmark feature source state is not canonical.")
    first = _parse_timestamp(feature.first_bar_timestamp)
    latest = _parse_timestamp(feature.latest_bar_timestamp)
    if first > latest or latest + timedelta(minutes=1) > evaluated:
        raise RegimeResearchError("Benchmark feature chronology is invalid.")
    if type(feature.bar_count) is not int or feature.bar_count < 61:
        raise RegimeResearchError("Benchmark feature horizon is incomplete.")
    required_numeric = (
        feature.current_price,
        feature.return_1m_pct,
        feature.return_5m_pct,
        feature.return_15m_pct,
        feature.return_30m_pct,
        feature.return_60m_pct,
        feature.session_high,
        feature.session_low,
        feature.distance_from_session_high_pct,
        feature.distance_from_session_low_pct,
        feature.atr,
        feature.atr_pct,
        feature.realized_volatility_1m_pct,
        feature.current_range_pct,
        feature.range_expansion_multiple,
        feature.speed_5m_pct_per_minute,
        feature.acceleration_5m_pct_per_minute,
    )
    if any(not _is_finite_numeric(value) for value in required_numeric):
        raise RegimeResearchError("Benchmark feature contained nonfinite data.")
    if min(feature.current_price, feature.session_high, feature.session_low, feature.atr) <= 0:
        raise RegimeResearchError("Benchmark price/ATR feature must be positive.")
    if feature.session_low > feature.current_price or feature.session_high < feature.current_price:
        raise RegimeResearchError("Benchmark session range excluded current price.")
    if feature.vwap_kind != BAR_DERIVED_VWAP:
        raise RegimeResearchError("Benchmark VWAP basis is unsupported.")
    optional_numeric = (
        feature.return_since_open_pct,
        feature.return_vs_prior_close_pct,
        feature.premarket_return_pct,
        feature.opening_range_high,
        feature.opening_range_low,
        feature.opening_range_location,
        feature.bar_derived_vwap,
        feature.distance_from_vwap_pct,
        feature.distance_from_vwap_atr,
        feature.price_progress_per_million_volume_15m,
        feature.incremental_progress_ratio_5m_to_15m,
    )
    if any(value is not None and not _is_finite_numeric(value) for value in optional_numeric):
        raise RegimeResearchError("Optional benchmark feature contained nonfinite data.")
    if feature.bar_derived_vwap is None and (
        feature.distance_from_vwap_pct is not None
        or feature.distance_from_vwap_atr is not None
    ):
        raise RegimeResearchError("VWAP distances exist without a VWAP basis.")
    if feature.bar_derived_vwap is not None and feature.bar_derived_vwap <= 0:
        raise RegimeResearchError("Bar-derived VWAP must be positive.")
    if (
        feature.opening_range_high is not None
        and feature.opening_range_low is not None
        and feature.opening_range_high < feature.opening_range_low
    ):
        raise RegimeResearchError("Opening range is inverted.")
    for value in (
        feature.consecutive_higher_highs,
        feature.consecutive_lower_lows,
        feature.consecutive_directional_bars,
        feature.bars_since_material_pullback,
    ):
        if type(value) is not int or value < 0:
            raise RegimeResearchError("Benchmark persistence feature is invalid.")


def _normalize_bars(
    bars_by_symbol: Mapping[str, Sequence[RegimeBar]],
    *,
    evaluated: datetime,
    policy: RegimeResearchPolicy,
) -> dict[str, tuple[RegimeBar, ...]]:
    evaluated_date = evaluated.astimezone(_EASTERN).date()
    normalized: dict[str, tuple[RegimeBar, ...]] = {}
    for symbol in policy.required_benchmarks:
        rows = bars_by_symbol[symbol]
        parsed: list[tuple[datetime, RegimeBar]] = []
        seen: set[str] = set()
        sources: set[str] = set()
        for bar in rows:
            try:
                validate_bar(bar, expected_symbol=symbol)
            except RollingMarketRegimeError as exc:
                raise RegimeResearchError(f"INVALID_{symbol}_BAR:{exc}") from exc
            timestamp = _parse_timestamp(bar.timestamp)
            canonical = _iso(timestamp)
            if canonical in seen:
                raise RegimeResearchError(f"DUPLICATE_{symbol}_BAR_TIMESTAMP")
            if timestamp + timedelta(minutes=1) > evaluated:
                raise RegimeResearchError(f"FUTURE_OR_IN_PROGRESS_{symbol}_BAR")
            if timestamp.astimezone(_EASTERN).date() != evaluated_date:
                raise RegimeResearchError("MIXED_SESSION_DATES")
            seen.add(canonical)
            sources.add(bar.source_identity)
            parsed.append((timestamp, replace(bar, symbol=symbol, timestamp=canonical)))
        if len(sources) > 1:
            raise RegimeResearchError(f"MIXED_{symbol}_SOURCE_IDENTITY")
        parsed.sort(key=lambda item: item[0])
        for previous, current in zip(parsed, parsed[1:]):
            gap = (current[0] - previous[0]).total_seconds()
            if gap > policy.maximum_internal_gap_seconds:
                raise RegimeResearchError(f"INTERNAL_{symbol}_BAR_GAP")
        normalized[symbol] = tuple(item[1] for item in parsed)
    return normalized


def _benchmark_features(
    symbol: str,
    bars: Sequence[RegimeBar],
    *,
    evaluated: datetime,
    session_state: str,
    prior_close: float | None,
    policy: RegimeResearchPolicy,
) -> BenchmarkFeatures:
    closes = [item.close for item in bars]
    returns = {
        horizon: _return_pct(closes[-(horizon + 1)], closes[-1])
        for horizon in policy.return_horizons_minutes
    }
    eastern_rows = [(_parse_timestamp(item.timestamp).astimezone(_EASTERN), item) for item in bars]
    regular = [item for stamp, item in eastern_rows if stamp.time() >= time(9, 30)]
    premarket = [
        item for stamp, item in eastern_rows if time(7, 0) <= stamp.time() < time(9, 30)
    ]
    session_rows = premarket + regular if session_state != PREMARKET else premarket
    if not session_rows:
        session_rows = list(bars)
    current = bars[-1].close
    session_high = max(item.high for item in session_rows)
    session_low = min(item.low for item in session_rows)
    opening = regular[: policy.opening_range_minutes]
    opening_high = max((item.high for item in opening), default=None)
    opening_low = min((item.low for item in opening), default=None)
    opening_location = None
    if opening_high is not None and opening_low is not None and opening_high > opening_low:
        opening_location = (current - opening_low) / (opening_high - opening_low)
    atr = _atr(bars, policy.atr_window_bars)
    vwap = _bar_vwap(session_rows)
    distance_vwap_pct = _return_pct(vwap, current) if vwap else None
    distance_vwap_atr = (current - vwap) / atr if vwap and atr > 0 else None
    one_minute_returns = [
        _return_pct(previous.close, current_bar.close)
        for previous, current_bar in zip(bars, bars[1:])
    ]
    realized = pstdev(one_minute_returns[-policy.realized_volatility_window_bars :])
    current_range_pct = ((bars[-1].high - bars[-1].low) / bars[-1].close) * 100.0
    comparison_ranges = [
        ((item.high - item.low) / item.close) * 100.0
        for item in bars[-31:-1]
    ]
    baseline_range = median(comparison_ranges) if comparison_ranges else current_range_pct
    range_expansion = current_range_pct / baseline_range if baseline_range > 0 else 1.0
    prior_5_return = _return_pct(closes[-11], closes[-6])
    speed = returns[5] / 5.0
    acceleration = speed - (prior_5_return / 5.0)
    direction = 1 if returns[15] > 0 else -1 if returns[15] < 0 else 0
    volume_15 = sum(item.volume for item in bars[-15:])
    progress_per_volume = (
        abs(closes[-1] - closes[-16]) / (volume_15 / 1_000_000)
        if volume_15 > 0
        else None
    )
    progress_ratio = (
        abs(returns[5]) / abs(returns[15]) if abs(returns[15]) > 1e-12 else None
    )
    return BenchmarkFeatures(
        symbol=symbol,
        source_identity=bars[-1].source_identity,
        source_state=bars[-1].source_state,
        first_bar_timestamp=bars[0].timestamp,
        latest_bar_timestamp=bars[-1].timestamp,
        bar_count=len(bars),
        current_price=current,
        return_1m_pct=returns[1],
        return_5m_pct=returns[5],
        return_15m_pct=returns[15],
        return_30m_pct=returns[30],
        return_60m_pct=returns[60],
        return_since_open_pct=(
            _return_pct(regular[0].open, current) if regular else None
        ),
        return_vs_prior_close_pct=(
            _return_pct(prior_close, current) if prior_close is not None else None
        ),
        premarket_return_pct=(
            _return_pct(premarket[0].open, premarket[-1].close) if premarket else None
        ),
        session_high=session_high,
        session_low=session_low,
        distance_from_session_high_pct=_return_pct(session_high, current),
        distance_from_session_low_pct=_return_pct(session_low, current),
        consecutive_higher_highs=_consecutive(bars, lambda left, right: right.high > left.high),
        consecutive_lower_lows=_consecutive(bars, lambda left, right: right.low < left.low),
        opening_range_high=opening_high,
        opening_range_low=opening_low,
        opening_range_location=opening_location,
        vwap_kind=BAR_DERIVED_VWAP,
        bar_derived_vwap=vwap,
        distance_from_vwap_pct=distance_vwap_pct,
        distance_from_vwap_atr=distance_vwap_atr,
        atr=atr,
        atr_pct=(atr / current) * 100.0,
        realized_volatility_1m_pct=realized,
        current_range_pct=current_range_pct,
        range_expansion_multiple=range_expansion,
        speed_5m_pct_per_minute=speed,
        acceleration_5m_pct_per_minute=acceleration,
        consecutive_directional_bars=_consecutive_directional_bars(bars, direction),
        bars_since_material_pullback=_bars_since_pullback(bars, direction),
        price_progress_per_million_volume_15m=progress_per_volume,
        incremental_progress_ratio_5m_to_15m=progress_ratio,
    )


def _direction_state(
    rolling: RegimeSnapshot,
    features: Sequence[BenchmarkFeatures],
    policy: RegimeResearchPolicy,
    session_state: str,
) -> tuple[str, str, float, float]:
    multiplier = _session_threshold_multiplier(policy, session_state)
    direction_threshold = policy.direction_threshold_15m_pct * multiplier
    rotation_threshold = policy.rotation_dispersion_15m_pct * multiplier
    chop_threshold = policy.chop_max_abs_return_15m_pct * multiplier
    values = [item.return_15m_pct for item in features]
    dispersion = max(values) - min(values)
    positive = sum(value >= direction_threshold for value in values)
    negative = sum(value <= -direction_threshold for value in values)
    agreement = max(positive, negative) / len(values)
    if (
        dispersion >= rotation_threshold
        and min(values) < 0 < max(values)
    ):
        return ROTATION, "CROSS_INDEX_ROTATION", agreement, dispersion
    if positive / len(values) >= policy.direction_alignment_fraction:
        return TREND_UP, "ALIGNED_BENCHMARK_TREND_UP", agreement, dispersion
    if negative / len(values) >= policy.direction_alignment_fraction:
        return TREND_DOWN, "ALIGNED_BENCHMARK_TREND_DOWN", agreement, dispersion
    if max(abs(value) for value in values) <= chop_threshold:
        reversal_counts = sum(
            item.consecutive_higher_highs <= 1 and item.consecutive_lower_lows <= 1
            for item in features
        )
        if reversal_counts >= 2:
            return CHOP, "LOW_PERSISTENCE_CHOP", agreement, dispersion
    return MIXED, "BENCHMARK_DIRECTION_MIXED", agreement, dispersion


def _extension_state(
    features: Sequence[BenchmarkFeatures],
    policy: RegimeResearchPolicy,
    session_state: str,
) -> tuple[str, str]:
    multiplier = _session_threshold_multiplier(policy, session_state)
    late_trend_vwap_atr = policy.late_trend_vwap_atr * multiplier
    exhaustion_vwap_atr = policy.exhaustion_vwap_atr * multiplier
    extreme_vwap_atr = policy.extreme_vwap_atr * multiplier
    exhaustion_return_30m_pct = policy.exhaustion_return_30m_pct * multiplier
    extreme_return_30m_pct = policy.extreme_return_30m_pct * multiplier
    normalized = [
        abs(item.distance_from_vwap_atr)
        for item in features
        if item.distance_from_vwap_atr is not None
    ]
    median_extension = median(normalized) if normalized else 0.0
    median_return_30m = median(abs(item.return_30m_pct) for item in features)
    low_progress = sum(
        item.incremental_progress_ratio_5m_to_15m is not None
        and item.incremental_progress_ratio_5m_to_15m < 0.30
        for item in features
    ) >= 2
    if (
        median_extension >= extreme_vwap_atr
        or median_return_30m >= extreme_return_30m_pct
    ):
        return EXTREME_EXTENSION, "EXTREME_MARKET_EXTENSION"
    if (
        median_extension >= exhaustion_vwap_atr
        or median_return_30m >= exhaustion_return_30m_pct
        or (median_extension >= late_trend_vwap_atr and low_progress)
    ):
        return EXHAUSTION_RISK, "MARKET_EXTENSION_WITH_EXHAUSTION_RISK"
    if median_extension >= late_trend_vwap_atr:
        return LATE_TREND, "MARKET_TREND_MATURE"
    return NORMAL_EXTENSION, "MARKET_EXTENSION_NORMAL"


def _stress_state(
    rolling: RegimeSnapshot,
    features: Sequence[BenchmarkFeatures],
    macro_context: MacroEventRiskContext | None,
    policy: RegimeResearchPolicy,
    session_state: str,
) -> tuple[str, str]:
    multiplier = _session_threshold_multiplier(policy, session_state)
    elevated_threshold = 1.0 + (
        (policy.elevated_volatility_multiple - 1.0) * multiplier
    )
    shock_threshold = 1.0 + (
        (policy.volatility_shock_multiple - 1.0) * multiplier
    )
    downside_threshold = policy.market_stress_down_return_5m_pct * multiplier
    volatility = median(item.range_expansion_multiple for item in features)
    coordinated_down = all(
        item.return_5m_pct <= -downside_threshold
        for item in features
    )
    if macro_context is not None and macro_context.status == BLOCK_NEW_ENTRY:
        return MARKET_STRESS, "MACRO_EVENT_CONTEXT_STRESSED"
    if coordinated_down and volatility >= elevated_threshold:
        return MARKET_STRESS, "COORDINATED_DOWNSIDE_STRESS"
    if rolling.regime == ROLLING_VOLATILITY_SHOCK or (
        volatility >= shock_threshold
    ):
        return VOLATILITY_SHOCK, "BENCHMARK_VOLATILITY_SHOCK"
    if (
        volatility >= elevated_threshold
        or (macro_context is not None and macro_context.status == CAUTION)
    ):
        return ELEVATED_VOLATILITY, "ELEVATED_MARKET_VOLATILITY"
    return NORMAL, "MARKET_STRESS_NORMAL"


def _session_threshold_multiplier(
    policy: RegimeResearchPolicy,
    session_state: str,
) -> float:
    multipliers = dict(policy.session_threshold_multipliers)
    try:
        return float(multipliers[session_state])
    except KeyError as exc:
        raise RegimeResearchError(
            f"No threshold profile is defined for session {session_state}."
        ) from exc


def _evaluated_opinion(
    *,
    assessment: RegimeResearchAssessment,
    references: tuple[EvidenceReference, ...],
    target_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    trade_plan_id: str | None,
    policy: RegimeResearchPolicy,
) -> SpecialistOpinion:
    opinion_code = assessment.direction_state
    if assessment.stress_state != NORMAL:
        opinion_code = assessment.stress_state
    elif assessment.extension_state != NORMAL_EXTENSION:
        opinion_code = assessment.extension_state
    directional_bias = {
        TREND_UP: BULLISH,
        TREND_DOWN: BEARISH,
        ROTATION: NON_DIRECTIONAL,
        CHOP: NEUTRAL,
        MIXED: NON_DIRECTIONAL,
    }[assessment.direction_state]
    confidence = build_confidence(
        value=float(assessment.benchmark_agreement_fraction or 0.0),
        kind=HEURISTIC,
        calibration_status=UNCALIBRATED,
        sample_size=None,
        model_version=policy.policy_version,
    )
    return build_specialist_opinion(
        specialist_id=REGIME_SPECIALIST_ID,
        specialist_version=policy.specialist_version,
        opportunity_id=target_id,
        candidate_id=candidate_id,
        setup_id=setup_id,
        trade_plan_id=trade_plan_id,
        as_of=assessment.evaluated_at,
        expires_at=_parse_timestamp(assessment.evaluated_at)
        + timedelta(seconds=policy.opinion_ttl_seconds),
        research_identity=policy.research_identity,
        policy_fingerprint=policy.fingerprint,
        evaluation_status=EVALUATED,
        opinion_code=opinion_code,
        directional_bias=directional_bias,
        evidence_refs=references,
        feature_families=("MARKET_REGIME", "PRICE_MOMENTUM", "CANDLE_STRUCTURE", "VOLUME"),
        confidence=confidence,
        reason_codes=assessment.reason_codes,
        explanation=(
            "Research-only market environment opinion. Heuristic confidence is "
            "benchmark alignment, not a probability or trade recommendation."
        ),
        authority=RESEARCH_ONLY,
        execution_authority=EXECUTION_AUTHORITY_NONE,
    )


def _abstained_packet(
    *,
    evaluated: datetime,
    session_state: str,
    policy: RegimeResearchPolicy,
    target_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    trade_plan_id: str | None,
    reason: str,
    machine_reason: str,
    missing_benchmarks: tuple[str, ...] = (),
) -> RegimeSpecialistPacket:
    machine_reason = _reason_token(machine_reason)
    assessment = _unsafe_assessment(
        evaluated=evaluated,
        session_state=session_state,
        policy=policy,
        missing_benchmarks=missing_benchmarks,
        reason_codes=(machine_reason,),
    )
    opinion = build_specialist_opinion(
        specialist_id=REGIME_SPECIALIST_ID,
        specialist_version=policy.specialist_version,
        opportunity_id=target_id,
        candidate_id=candidate_id,
        setup_id=setup_id,
        trade_plan_id=trade_plan_id,
        as_of=evaluated,
        expires_at=evaluated + timedelta(seconds=policy.opinion_ttl_seconds),
        research_identity=policy.research_identity,
        policy_fingerprint=policy.fingerprint,
        evaluation_status=ABSTAINED,
        opinion_code=NO_OPINION,
        directional_bias=NO_DIRECTION,
        reason_codes=(machine_reason,),
        abstention_reason=reason,
        authority=RESEARCH_ONLY,
        execution_authority=EXECUTION_AUTHORITY_NONE,
    )
    return _packet(policy=policy, assessment=assessment, opinion=opinion)


def _failed_packet(
    *,
    evaluated: datetime,
    session_state: str,
    policy: RegimeResearchPolicy,
    target_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    trade_plan_id: str | None,
    reason: str,
) -> RegimeSpecialistPacket:
    machine_reason = _reason_token(reason)
    assessment = _unsafe_assessment(
        evaluated=evaluated,
        session_state=session_state,
        policy=policy,
        reason_codes=(machine_reason,),
    )
    opinion = build_specialist_opinion(
        specialist_id=REGIME_SPECIALIST_ID,
        specialist_version=policy.specialist_version,
        opportunity_id=target_id,
        candidate_id=candidate_id,
        setup_id=setup_id,
        trade_plan_id=trade_plan_id,
        as_of=evaluated,
        expires_at=evaluated + timedelta(seconds=policy.opinion_ttl_seconds),
        research_identity=policy.research_identity,
        policy_fingerprint=policy.fingerprint,
        evaluation_status=FAILED,
        opinion_code=None,
        directional_bias=NO_DIRECTION,
        reason_codes=(machine_reason,),
        failure_reason=machine_reason,
        authority=RESEARCH_ONLY,
        execution_authority=EXECUTION_AUTHORITY_NONE,
    )
    return _packet(policy=policy, assessment=assessment, opinion=opinion)


def _unsafe_assessment(
    *,
    evaluated: datetime,
    session_state: str,
    policy: RegimeResearchPolicy,
    reason_codes: tuple[str, ...],
    missing_benchmarks: tuple[str, ...] = (),
) -> RegimeResearchAssessment:
    input_fingerprint = _fingerprint(
        {
            "missingBenchmarks": missing_benchmarks,
            "reasonCodes": reason_codes,
            "sessionState": session_state,
        }
    )
    return _complete_assessment(
        evaluated=evaluated,
        session_state=session_state,
        direction_state=UNKNOWN_DIRECTION,
        extension_state=UNKNOWN_EXTENSION,
        stress_state=DATA_UNSAFE,
        data_quality_state=DATA_UNSAFE,
        missing_benchmarks=missing_benchmarks,
        limitations=("NO_FULL_MARKET_OPINION",),
        reason_codes=reason_codes,
        benchmark_features=(),
        benchmark_agreement_fraction=None,
        benchmark_return_dispersion_15m_pct=None,
        participation_proxy=None,
        rolling=None,
        macro_context=None,
        input_fingerprint=input_fingerprint,
        policy=policy,
    )


def _complete_assessment(
    *,
    evaluated: datetime,
    session_state: str,
    direction_state: str,
    extension_state: str,
    stress_state: str,
    data_quality_state: str,
    missing_benchmarks: tuple[str, ...],
    limitations: tuple[str, ...],
    reason_codes: tuple[str, ...],
    benchmark_features: tuple[BenchmarkFeatures, ...],
    benchmark_agreement_fraction: float | None,
    benchmark_return_dispersion_15m_pct: float | None,
    participation_proxy: ParticipationProxy | None,
    rolling: RegimeSnapshot | None,
    macro_context: MacroEventRiskContext | None,
    input_fingerprint: str,
    policy: RegimeResearchPolicy,
) -> RegimeResearchAssessment:
    evaluated_text = _iso(evaluated)
    assessment_id = _fingerprint(
        {
            "evaluatedAt": evaluated_text,
            "inputEvidenceFingerprint": input_fingerprint,
            "policyFingerprint": policy.fingerprint,
        }
    )
    assessment = RegimeResearchAssessment(
        assessment_id=assessment_id,
        evaluated_at=evaluated_text,
        session_state=session_state,
        direction_state=direction_state,
        extension_state=extension_state,
        stress_state=stress_state,
        data_quality_state=data_quality_state,
        evidence_scope=(
            FULL_MARKET_EVIDENCE
            if benchmark_features
            else INCOMPLETE_MARKET_EVIDENCE
        ),
        missing_benchmarks=tuple(sorted(missing_benchmarks)),
        limitations=tuple(sorted(limitations)),
        reason_codes=tuple(sorted(set(reason_codes))),
        benchmark_features=benchmark_features,
        benchmark_agreement_fraction=benchmark_agreement_fraction,
        benchmark_return_dispersion_15m_pct=benchmark_return_dispersion_15m_pct,
        bounded_participation_proxy=participation_proxy,
        rolling_snapshot_id=rolling.snapshot_id if rolling else "",
        rolling_regime=rolling.regime if rolling else ROLLING_DATA_STALE,
        rolling_snapshot_fingerprint=rolling.fingerprint if rolling else "",
        macro_context_id=macro_context.context_id if macro_context else "",
        macro_context_status=macro_context.status if macro_context else "",
        input_evidence_fingerprint=input_fingerprint,
        policy_version=policy.policy_version,
        policy_fingerprint=policy.fingerprint,
    )
    complete = replace(assessment, fingerprint=_assessment_fingerprint(assessment))
    validate_assessment(complete)
    return complete


def _packet(
    *,
    policy: RegimeResearchPolicy,
    assessment: RegimeResearchAssessment,
    opinion: SpecialistOpinion,
) -> RegimeSpecialistPacket:
    packet = RegimeSpecialistPacket(policy=policy, assessment=assessment, opinion=opinion)
    complete = replace(packet, fingerprint=_packet_fingerprint(packet))
    validate_packet(complete)
    return complete


def _evidence_references(
    bars_by_symbol: Mapping[str, Sequence[RegimeBar]],
    *,
    rolling: RegimeSnapshot,
    macro_context: MacroEventRiskContext | None,
    participation_proxy: ParticipationProxy | None = None,
) -> tuple[EvidenceReference, ...]:
    references = []
    for symbol, bars in sorted(bars_by_symbol.items()):
        fingerprint = _fingerprint([asdict(item) for item in bars])
        references.append(
            build_evidence_reference(
                evidence_id=f"{symbol}-canonical-minute-bars-{bars[-1].timestamp}",
                evidence_type="MINUTE_CANDLES",
                source=bars[-1].source_identity,
                as_of=bars[-1].timestamp,
                fingerprint=fingerprint,
            )
        )
    references.append(
        build_evidence_reference(
            evidence_id=rolling.snapshot_id,
            evidence_type="MARKET_REGIME",
            source=rolling.profile,
            as_of=rolling.evaluated_at,
            fingerprint=rolling.fingerprint,
        )
    )
    if macro_context is not None:
        references.append(
            build_evidence_reference(
                evidence_id=macro_context.context_id,
                evidence_type="MARKET_REGIME",
                source=macro_context.profile,
                as_of=macro_context.evaluated_at,
                fingerprint=macro_context.fingerprint,
            )
        )
    if participation_proxy is not None:
        references.append(
            build_evidence_reference(
                evidence_id=(
                    "bounded-participation-"
                    + participation_proxy.evidence_fingerprint[:24]
                ),
                evidence_type="MARKET_REGIME",
                source=participation_proxy.source_identity,
                as_of=participation_proxy.as_of,
                fingerprint=participation_proxy.evidence_fingerprint,
            )
        )
    return tuple(references)


def _rolling_policy(
    policy: RegimeResearchPolicy,
    session_state: str,
) -> RegimePolicy:
    multiplier = _session_threshold_multiplier(policy, session_state)
    return RegimePolicy(
        policy_version=f"{policy.policy_version}/continuous-003",
        market_symbols=policy.required_benchmarks,
        short_window_bars=15,
        long_window_bars=30,
        volatility_baseline_bars=30,
        directional_return_threshold_pct=(
            policy.direction_threshold_15m_pct * multiplier
        ),
        alignment_fraction=policy.direction_alignment_fraction,
        volatility_shock_multiple=(
            1.0 + ((policy.volatility_shock_multiple - 1.0) * multiplier)
        ),
        sector_rotation_dispersion_pct=(
            policy.rotation_dispersion_15m_pct * multiplier
        ),
        stale_after_seconds=policy.stale_after_seconds,
        maximum_cross_symbol_skew_seconds=policy.maximum_cross_symbol_skew_seconds,
        maximum_internal_gap_seconds=policy.maximum_internal_gap_seconds,
        minimum_sector_symbols=2,
        maximum_candidate_fan_out=25,
    )


def _input_evidence_fingerprint(
    bars_by_symbol: Mapping[str, Sequence[RegimeBar]],
    *,
    prior_closes: Mapping[str, float],
    participation_proxy: ParticipationProxy | None,
    macro_context: MacroEventRiskContext | None,
) -> str:
    return _fingerprint(
        {
            "bars": {
                symbol: [asdict(item) for item in bars]
                for symbol, bars in sorted(bars_by_symbol.items())
            },
            "priorCloses": dict(sorted(prior_closes.items())),
            "participationProxy": (
                asdict(participation_proxy) if participation_proxy else None
            ),
            "macroContextFingerprint": macro_context.fingerprint if macro_context else None,
        }
    )


def _assessment_fingerprint(assessment: RegimeResearchAssessment) -> str:
    payload = asdict(assessment)
    payload.pop("fingerprint", None)
    return _fingerprint(payload)


def _packet_fingerprint(packet: RegimeSpecialistPacket) -> str:
    return _fingerprint(
        {
            "schemaVersion": packet.schema_version,
            "profile": packet.profile,
            "policy": asdict(packet.policy),
            "assessmentFingerprint": packet.assessment.fingerprint,
            "opinionFingerprint": packet.opinion.fingerprint,
        }
    )


def _normalize_prior_closes(values: Mapping[str, float]) -> dict[str, float]:
    result: dict[str, float] = {}
    for symbol, raw in values.items():
        normalized = str(symbol).strip().upper()
        if normalized not in {"SPY", "QQQ", "IWM"}:
            raise RegimeResearchError("Prior-close input contained an unknown symbol.")
        if normalized in result:
            raise RegimeResearchError("Prior-close input repeated a normalized symbol.")
        value = _positive(raw, "Prior close")
        result[normalized] = value
    return result


def _has_complete_opening_range(
    bars: Sequence[RegimeBar],
    evaluated: datetime,
    policy: RegimeResearchPolicy,
) -> bool:
    session_date = evaluated.astimezone(_EASTERN).date()
    expected = {
        datetime.combine(session_date, time(9, 30), tzinfo=_EASTERN)
        + timedelta(minutes=index)
        for index in range(policy.opening_range_minutes)
    }
    observed = {
        _parse_timestamp(item.timestamp).astimezone(_EASTERN)
        for item in bars
    }
    return expected.issubset(observed)


def _bar_vwap(bars: Sequence[RegimeBar]) -> float | None:
    volume = sum(item.volume for item in bars)
    if volume <= 0:
        return None
    value = sum(
        ((item.high + item.low + item.close) / 3.0) * item.volume
        for item in bars
    )
    return value / volume


def _atr(bars: Sequence[RegimeBar], window: int) -> float:
    selected = bars[-(window + 1) :]
    ranges = []
    for previous, current in zip(selected, selected[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(ranges) / len(ranges)


def _consecutive(
    bars: Sequence[RegimeBar],
    predicate: Callable[[RegimeBar, RegimeBar], bool],
) -> int:
    count = 0
    for left, right in reversed(tuple(zip(bars, bars[1:]))):
        if not predicate(left, right):
            break
        count += 1
    return count


def _consecutive_directional_bars(bars: Sequence[RegimeBar], direction: int) -> int:
    if direction == 0:
        return 0
    count = 0
    for item in reversed(bars):
        change = item.close - item.open
        if (direction > 0 and change <= 0) or (direction < 0 and change >= 0):
            break
        count += 1
    return count


def _bars_since_pullback(bars: Sequence[RegimeBar], direction: int) -> int:
    if direction == 0:
        return 0
    for distance, item in enumerate(reversed(bars), start=0):
        change = item.close - item.open
        if (direction > 0 and change < 0) or (direction < 0 and change > 0):
            return distance
    return len(bars)


def _return_pct(start: float | None, end: float) -> float:
    if start is None or start <= 0:
        raise RegimeResearchError("Return basis must be positive.")
    return ((end / start) - 1.0) * 100.0


def _reason_token(value: str) -> str:
    token = re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")
    return (token or "REGIME_EVALUATION_FAILED")[:96]


def _positive(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise RegimeResearchError(f"{label} must be positive finite data.")
    return float(value)


def _is_finite_numeric(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or (
        value.utcoffset() is None
    ):
        raise RegimeResearchError(f"{label} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegimeResearchError("Evidence timestamp is invalid.") from exc
    return _aware(parsed, "Evidence timestamp")


def _iso(value: datetime) -> str:
    return _aware(value, "Timestamp").isoformat().replace("+00:00", "Z")


def _identifier(value: object, label: str) -> str:
    text = str(value).strip()
    if not text or len(text) > 256 or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:/-]*", text
    ):
        raise RegimeResearchError(f"{label} is invalid.")
    return text


def _sha256(value: object, label: str) -> str:
    text = str(value).strip().lower()
    if not _SHA256.fullmatch(text):
        raise RegimeResearchError(f"{label} must be SHA-256.")
    return text


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
