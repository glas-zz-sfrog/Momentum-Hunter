"""Provider-neutral, research-only execution-quality specialist.

The evaluator accepts immutable evidence supplied by a caller. It has no
provider, account, broker, order, persistence, scheduler, service, Engine Host,
or UI capability. Later execution observations are attached separately and
cannot alter the original predecision opinion.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta, timezone
from statistics import pstdev
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from momentum_hunter.broker_capabilities import BrokerCapabilityRegistry
from momentum_hunter.intraday_trade_plan import (
    IntradayPlanEvidence,
    intraday_plan_validation_findings,
)
from momentum_hunter.provider_neutral_allocation import (
    ProviderNeutralAllocationDecision,
)
from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    EVALUATED,
    EXECUTION_AUTHORITY_NONE,
    FAILED,
    HEURISTIC,
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
    input_evidence_fingerprint,
    opinion_to_wire,
    unavailable_confidence,
    validate_specialist_opinion,
)


EXECUTION_QUALITY_SCHEMA_VERSION = 1
EXECUTION_QUALITY_PROFILE = "execution-quality-research-packet-v1"
EXECUTION_QUALITY_SPECIALIST_ID = "EXECUTION_QUALITY"
EXECUTION_QUALITY_SPECIALIST_VERSION = "execution-quality-research-v1"
RESEARCH_HEURISTIC = "RESEARCH_HEURISTIC"
MATHEMATICAL_COUNTERFACTUAL = "MATHEMATICAL_COUNTERFACTUAL"
PRE_DECISION_EXECUTION_QUALITY = "PRE_DECISION_EXECUTION_QUALITY"
OBSERVED_PROVIDER_EXECUTION_RESULT = "OBSERVED_PROVIDER_EXECUTION_RESULT"

PREMARKET = "PREMARKET"
REGULAR = "REGULAR"
AFTER_HOURS = "AFTER_HOURS"
UNSUPPORTED_SESSION = "UNSUPPORTED_SESSION"
SESSIONS = frozenset({PREMARKET, REGULAR, AFTER_HOURS, UNSUPPORTED_SESSION})

LIQUID = "LIQUID"
ADEQUATE = "ADEQUATE"
THIN = "THIN"
VERY_THIN = "VERY_THIN"
UNKNOWN = "UNKNOWN"
LIQUIDITY_STATES = frozenset({LIQUID, ADEQUATE, THIN, VERY_THIN, UNKNOWN})

TIGHT = "TIGHT"
NORMAL = "NORMAL"
WIDE = "WIDE"
EXTREME = "EXTREME"
SPREAD_STATES = frozenset({TIGHT, NORMAL, WIDE, EXTREME, UNKNOWN})

STABLE = "STABLE"
MODERATELY_UNSTABLE = "MODERATELY_UNSTABLE"
UNSTABLE = "UNSTABLE"
DISLOCATED = "DISLOCATED"
STABILITY_STATES = frozenset(
    {STABLE, MODERATELY_UNSTABLE, UNSTABLE, DISLOCATED, UNKNOWN}
)

LOW = "LOW"
MODERATE = "MODERATE"
HIGH = "HIGH"
RISK_STATES = frozenset({LOW, MODERATE, HIGH, UNKNOWN})

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
DATA_UNSAFE = "DATA_UNSAFE"
DATA_QUALITY_STATES = frozenset({COMPLETE, PARTIAL, DATA_UNSAFE})

NORMAL_MARKET = "NORMAL_MARKET"
HALTED = "HALTED"
QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
ONE_SIDED_MARKET = "ONE_SIDED_MARKET"
CROSSED_MARKET = "CROSSED_MARKET"
LOCKED_MARKET = "LOCKED_MARKET"
STALE_MARKET = "STALE_MARKET"
MARKET_STATES = frozenset(
    {
        NORMAL_MARKET,
        HALTED,
        QUOTE_UNAVAILABLE,
        ONE_SIDED_MARKET,
        CROSSED_MARKET,
        LOCKED_MARKET,
        STALE_MARKET,
        DATA_UNSAFE,
    }
)

OBSERVED = "OBSERVED"
UNAVAILABLE = "UNAVAILABLE"
UNSUPPORTED = "UNSUPPORTED"
SIZE_EVIDENCE_STATES = frozenset({OBSERVED, UNAVAILABLE, UNSUPPORTED})

FULL_FILL = "FULL_FILL"
PARTIAL_FILL = "PARTIAL_FILL"
NO_FILL = "NO_FILL"
CANCELLED_REMAINDER = "CANCELLED_REMAINDER"
UNKNOWN_FILL = "UNKNOWN"
FILL_STATES = frozenset(
    {FULL_FILL, PARTIAL_FILL, NO_FILL, CANCELLED_REMAINDER, UNKNOWN_FILL}
)

CANONICAL_CANDLE_STATES = frozenset(
    {"RECONCILED", "CORRECTED", "HISTORY_ONLY_GAP_FILL"}
)

_EASTERN = ZoneInfo("America/New_York")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")


class ExecutionQualityError(ValueError):
    """Raised when research evidence is malformed or contradictory."""


@dataclass(frozen=True)
class ExecutionQualityPolicy:
    policy_version: str
    specialist_version: str
    research_identity: str
    maximum_quote_age_seconds: int
    maximum_quote_component_skew_seconds: int
    minimum_quote_observations: int
    maximum_quote_observations: int
    minimum_candle_observations: int
    maximum_candle_observations: int
    maximum_completed_bar_age_seconds: int
    spread_tight_bps: float
    spread_normal_bps: float
    spread_wide_bps: float
    stability_moderate_midpoint_range_bps: float
    stability_unstable_midpoint_range_bps: float
    stability_dislocated_midpoint_range_bps: float
    stability_moderate_spread_expansion: float
    stability_unstable_spread_expansion: float
    stability_dislocated_spread_expansion: float
    liquid_dollar_turnover_per_minute: float
    adequate_dollar_turnover_per_minute: float
    thin_dollar_turnover_per_minute: float
    thin_rapid_move_pct: float
    volume_expansion_multiple: float
    poor_progress_pct: float
    slippage_bands_bps: tuple[int, ...]
    opinion_ttl_seconds: int
    threshold_semantics: str = RESEARCH_HEURISTIC
    full_classification_session: str = REGULAR

    @property
    def fingerprint(self) -> str:
        return _fingerprint(asdict(self))


@dataclass(frozen=True)
class ExecutionQuoteObservation:
    quote_id: str
    symbol: str
    bid: float | None
    ask: float | None
    provider_quote_time: str
    provider_bid_time: str
    provider_ask_time: str
    receipt_time: str
    source_identity: str
    session: str
    realtime: bool
    trading_state: str
    security_status: str
    size_evidence_state: str
    bid_size: float | None
    ask_size: float | None
    fingerprint: str = ""


@dataclass(frozen=True)
class ExecutionMinuteBar:
    evidence_id: str
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source_identity: str
    state: str
    session_date: str
    fingerprint: str = ""


@dataclass(frozen=True)
class SpreadFeatures:
    bid: float | None
    ask: float | None
    midpoint: float | None
    absolute_spread: float | None
    spread_percent: float | None
    spread_basis_points: float | None
    spread_over_atr: float | None
    spread_over_recent_one_minute_range: float | None
    spread_over_stop_distance: float | None
    spread_over_planned_risk_per_share: float | None
    current_ask_vs_planned_entry_percent: float | None
    current_bid_distance_to_stop: float | None


@dataclass(frozen=True)
class QuoteStabilityFeatures:
    observation_count: int
    observation_window_seconds: float | None
    bid_movement: float | None
    ask_movement: float | None
    midpoint_movement: float | None
    midpoint_range_basis_points: float | None
    spread_expansion_multiple: float | None
    quote_updates_per_second: float | None
    direction_change_fraction: float | None
    realized_midpoint_volatility_basis_points: float | None


@dataclass(frozen=True)
class VolumeProgressFeatures:
    candle_count: int
    recent_window_minutes: int
    recent_volume: float | None
    prior_volume: float | None
    average_dollar_turnover_per_minute: float | None
    price_change_percent: float | None
    price_range_percent: float | None
    directional_progress_per_million_volume: float | None
    volume_expansion_multiple: float | None
    volume_without_progress: bool | None
    thin_volume_rapid_move: bool | None


@dataclass(frozen=True)
class SlippageSensitivityPoint:
    basis_points: int
    hypothetical_entry: float
    risk_per_share: float | None
    reward_per_share: float | None
    reward_risk: float | None
    extension_from_planned_entry_percent: float | None
    distance_to_stop: float | None
    distance_to_first_target: float | None
    dollar_risk_at_authorized_quantity: float | None
    evidence_class: str = MATHEMATICAL_COUNTERFACTUAL


@dataclass(frozen=True)
class ExecutionQualityAssessment:
    assessment_id: str
    opportunity_id: str
    candidate_id: str | None
    setup_id: str | None
    trade_plan_id: str | None
    symbol: str
    evaluated_at: str
    session_state: str
    market_state: str
    liquidity_state: str
    spread_state: str
    quote_stability_state: str
    price_impact_risk_state: str
    fill_risk_state: str
    data_quality_state: str
    displayed_size_state: str
    quote_age_seconds: float | None
    source_identity: str | None
    spread_features: SpreadFeatures
    quote_stability_features: QuoteStabilityFeatures
    volume_progress_features: VolumeProgressFeatures
    slippage_sensitivity: tuple[SlippageSensitivityPoint, ...]
    capability_registry_fingerprint: str | None
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...]
    input_evidence_fingerprint: str
    policy_version: str
    policy_fingerprint: str
    authority: str = RESEARCH_ONLY
    execution_authority: str = EXECUTION_AUTHORITY_NONE
    trade_recommendation: bool = False
    fingerprint: str = ""


@dataclass(frozen=True)
class ExecutionQualityPacket:
    policy: ExecutionQualityPolicy
    assessment: ExecutionQualityAssessment
    opinion: SpecialistOpinion
    schema_version: int = EXECUTION_QUALITY_SCHEMA_VERSION
    profile: str = EXECUTION_QUALITY_PROFILE
    evidence_domain: str = PRE_DECISION_EXECUTION_QUALITY
    fingerprint: str = ""


@dataclass(frozen=True)
class ObservedProviderExecutionResult:
    result_id: str
    opportunity_id: str
    candidate_id: str | None
    setup_id: str | None
    trade_plan_id: str | None
    symbol: str
    provider: str
    environment: str
    source_identity: str
    source_fingerprint: str
    decision_ask: float
    submitted_reference: float | None
    requested_quantity: float | None
    requested_notional: float | None
    fill_state: str
    filled_quantity: float
    confirmed_position_quantity: float
    average_fill_price: float | None
    decision_time: str
    submitted_time: str | None
    accepted_time: str | None
    filled_time: str | None
    cancelled_time: str | None
    fingerprint: str = ""


@dataclass(frozen=True)
class ObservedExecutionMetrics:
    fill_slippage_dollars_per_share: float | None
    fill_slippage_percent: float | None
    fill_slippage_basis_points: float | None
    fill_slippage_from_submitted_dollars_per_share: float | None
    fill_slippage_from_submitted_basis_points: float | None
    fill_delay_seconds: float | None
    quantity_fill_ratio: float | None
    realized_initial_risk: float | None
    realized_execution_reward_risk: float | None
    actual_filled_quantity: float
    evidence_domain: str = OBSERVED_PROVIDER_EXECUTION_RESULT


@dataclass(frozen=True)
class ExecutionQualityResearchRecord:
    original_packet: ExecutionQualityPacket
    observed_result: ObservedProviderExecutionResult
    observed_metrics: ObservedExecutionMetrics
    original_opinion_id: str
    original_opinion_fingerprint: str
    fingerprint: str = ""


def default_execution_quality_policy() -> ExecutionQualityPolicy:
    """Return frozen v1 thresholds; all thresholds are research heuristics."""

    policy = ExecutionQualityPolicy(
        policy_version="execution-quality-research-policy-v1",
        specialist_version=EXECUTION_QUALITY_SPECIALIST_VERSION,
        research_identity="execution-quality-research-v1",
        maximum_quote_age_seconds=30,
        maximum_quote_component_skew_seconds=5,
        minimum_quote_observations=3,
        maximum_quote_observations=20,
        minimum_candle_observations=31,
        maximum_candle_observations=90,
        maximum_completed_bar_age_seconds=90,
        spread_tight_bps=5.0,
        spread_normal_bps=20.0,
        spread_wide_bps=50.0,
        stability_moderate_midpoint_range_bps=10.0,
        stability_unstable_midpoint_range_bps=30.0,
        stability_dislocated_midpoint_range_bps=100.0,
        stability_moderate_spread_expansion=1.25,
        stability_unstable_spread_expansion=1.75,
        stability_dislocated_spread_expansion=3.0,
        liquid_dollar_turnover_per_minute=2_000_000.0,
        adequate_dollar_turnover_per_minute=500_000.0,
        thin_dollar_turnover_per_minute=100_000.0,
        thin_rapid_move_pct=1.0,
        volume_expansion_multiple=1.5,
        poor_progress_pct=0.05,
        slippage_bands_bps=(0, 5, 10, 25),
        opinion_ttl_seconds=30,
    )
    validate_policy(policy)
    return policy


def build_quote_observation(
    *,
    quote_id: str,
    symbol: str,
    bid: float | None,
    ask: float | None,
    provider_quote_time: datetime | str,
    provider_bid_time: datetime | str,
    provider_ask_time: datetime | str,
    receipt_time: datetime | str,
    source_identity: str,
    session: str,
    realtime: bool = True,
    trading_state: str = "NORMAL",
    security_status: str = "NORMAL",
    size_evidence_state: str = UNSUPPORTED,
    bid_size: float | None = None,
    ask_size: float | None = None,
) -> ExecutionQuoteObservation:
    value = ExecutionQuoteObservation(
        quote_id=_identifier(quote_id, "Quote identity"),
        symbol=_symbol(symbol),
        bid=_optional_number(bid),
        ask=_optional_number(ask),
        provider_quote_time=_iso(_aware(provider_quote_time, "Provider quote time")),
        provider_bid_time=_iso(_aware(provider_bid_time, "Provider bid time")),
        provider_ask_time=_iso(_aware(provider_ask_time, "Provider ask time")),
        receipt_time=_iso(_aware(receipt_time, "Quote receipt time")),
        source_identity=_identifier(source_identity, "Quote source identity"),
        session=_token(session, "Quote session"),
        realtime=_boolean(realtime, "Realtime flag"),
        trading_state=_token(trading_state, "Trading state"),
        security_status=_token(security_status, "Security status"),
        size_evidence_state=_token(size_evidence_state, "Size evidence state"),
        bid_size=_optional_number(bid_size),
        ask_size=_optional_number(ask_size),
        fingerprint="",
    )
    return replace(value, fingerprint=_fingerprint(asdict(value)))


def build_minute_bar(
    *,
    evidence_id: str,
    symbol: str,
    timestamp: datetime | str,
    open: float,
    high: float,
    low: float,
    close: float,
    volume: float | None,
    source_identity: str,
    state: str,
    session_date: str,
) -> ExecutionMinuteBar:
    value = ExecutionMinuteBar(
        evidence_id=_identifier(evidence_id, "Candle evidence identity"),
        symbol=_symbol(symbol),
        timestamp=_iso(_aware(timestamp, "Candle timestamp")),
        open=_number(open, "Candle open"),
        high=_number(high, "Candle high"),
        low=_number(low, "Candle low"),
        close=_number(close, "Candle close"),
        volume=_optional_number(volume),
        source_identity=_identifier(source_identity, "Candle source identity"),
        state=_token(state, "Candle state"),
        session_date=str(session_date),
        fingerprint="",
    )
    return replace(value, fingerprint=_fingerprint(asdict(value)))


def evaluate_execution_quality(
    *,
    opportunity_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    symbol: str,
    evaluated_at: datetime,
    quotes: Sequence[ExecutionQuoteObservation],
    candles: Sequence[ExecutionMinuteBar],
    policy: ExecutionQualityPolicy,
    trade_plan: IntradayPlanEvidence | None = None,
    allocation: ProviderNeutralAllocationDecision | None = None,
    broker_capabilities: BrokerCapabilityRegistry | None = None,
) -> ExecutionQualityPacket:
    """Create one immutable predecision research packet."""

    validate_policy(policy)
    evaluated = _aware(evaluated_at, "Evaluation timestamp")
    normalized_symbol = _symbol(symbol)
    target_opportunity = _sha256(opportunity_id, "Opportunity identity")
    target_setup = _optional_sha256(setup_id, "Setup identity")
    target_candidate = _optional_identifier(candidate_id, "Candidate identity")
    session_state = classify_session(evaluated)
    quote_rows = tuple(quotes)
    candle_rows = tuple(candles)

    plan_error = _plan_error(
        trade_plan,
        symbol=normalized_symbol,
        setup_id=target_setup,
        evaluated_at=evaluated,
    )
    if plan_error:
        return _terminal_packet(
            status=FAILED,
            common_reason=plan_error,
            machine_reason=plan_error,
            opportunity_id=target_opportunity,
            candidate_id=target_candidate,
            setup_id=target_setup,
            trade_plan_id=trade_plan.plan_id if trade_plan else None,
            symbol=normalized_symbol,
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
        )
    trade_plan_id = trade_plan.plan_id if trade_plan else None
    allocation_error = _allocation_error(
        allocation,
        trade_plan=trade_plan,
        symbol=normalized_symbol,
    )
    if allocation_error:
        return _terminal_packet(
            status=FAILED,
            common_reason=allocation_error,
            machine_reason=allocation_error,
            opportunity_id=target_opportunity,
            candidate_id=target_candidate,
            setup_id=target_setup,
            trade_plan_id=trade_plan_id,
            symbol=normalized_symbol,
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
        )

    quote_error, quote_abstention = _quote_findings(
        quote_rows,
        symbol=normalized_symbol,
        evaluated=evaluated,
        session_state=session_state,
        policy=policy,
    )
    if quote_error:
        return _terminal_packet(
            status=FAILED,
            common_reason=quote_error,
            machine_reason=quote_error,
            opportunity_id=target_opportunity,
            candidate_id=target_candidate,
            setup_id=target_setup,
            trade_plan_id=trade_plan_id,
            symbol=normalized_symbol,
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            quotes=quote_rows,
        )

    spread_features = _spread_features(
        quote_rows[-1] if quote_rows else None,
        candles=candle_rows,
        trade_plan=trade_plan,
    )
    if quote_abstention:
        return _terminal_packet(
            status=ABSTAINED,
            common_reason=(
                "STALE_EVIDENCE"
                if quote_abstention == "STALE_QUOTE"
                else "INSUFFICIENT_EVIDENCE"
            ),
            machine_reason=quote_abstention,
            opportunity_id=target_opportunity,
            candidate_id=target_candidate,
            setup_id=target_setup,
            trade_plan_id=trade_plan_id,
            symbol=normalized_symbol,
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            quotes=quote_rows,
            spread_features=spread_features,
        )
    if session_state != policy.full_classification_session:
        return _terminal_packet(
            status=ABSTAINED,
            common_reason="UNSUPPORTED_SESSION",
            machine_reason="SESSION_THRESHOLDS_NOT_VALIDATED",
            opportunity_id=target_opportunity,
            candidate_id=target_candidate,
            setup_id=target_setup,
            trade_plan_id=trade_plan_id,
            symbol=normalized_symbol,
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            quotes=quote_rows,
            spread_features=spread_features,
        )
    if len(quote_rows) < policy.minimum_quote_observations:
        return _terminal_packet(
            status=ABSTAINED,
            common_reason="INSUFFICIENT_EVIDENCE",
            machine_reason="QUOTE_SEQUENCE_UNAVAILABLE",
            opportunity_id=target_opportunity,
            candidate_id=target_candidate,
            setup_id=target_setup,
            trade_plan_id=trade_plan_id,
            symbol=normalized_symbol,
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            quotes=quote_rows,
            spread_features=spread_features,
        )

    candle_error, candle_abstention = _candle_findings(
        candle_rows,
        symbol=normalized_symbol,
        evaluated=evaluated,
        policy=policy,
    )
    if candle_error or candle_abstention:
        return _terminal_packet(
            status=FAILED if candle_error else ABSTAINED,
            common_reason=(candle_error or "INSUFFICIENT_EVIDENCE"),
            machine_reason=candle_error or candle_abstention or "CANDLE_DATA_UNSAFE",
            opportunity_id=target_opportunity,
            candidate_id=target_candidate,
            setup_id=target_setup,
            trade_plan_id=trade_plan_id,
            symbol=normalized_symbol,
            evaluated=evaluated,
            session_state=session_state,
            policy=policy,
            quotes=quote_rows,
            candles=candle_rows,
            spread_features=spread_features,
        )

    ordered_quotes = tuple(sorted(quote_rows, key=_effective_quote_time))
    ordered_candles = tuple(sorted(candle_rows, key=lambda item: item.timestamp))
    latest_quote = ordered_quotes[-1]
    spread_features = _spread_features(
        latest_quote,
        candles=ordered_candles,
        trade_plan=trade_plan,
    )
    stability_features = _quote_stability_features(ordered_quotes)
    volume_features = _volume_progress_features(ordered_candles, policy=policy)
    spread_state = _spread_state(spread_features, policy=policy)
    stability_state = _stability_state(stability_features, policy=policy)
    liquidity_state = _liquidity_state(volume_features, policy=policy)
    impact_state = _impact_state(
        liquidity_state=liquidity_state,
        stability_state=stability_state,
        volume_features=volume_features,
    )
    fill_state = _fill_risk_state(
        liquidity_state=liquidity_state,
        spread_state=spread_state,
        stability_state=stability_state,
        impact_state=impact_state,
    )
    market_state = _market_state(latest_quote)
    sensitivity = _slippage_sensitivity(
        ask=float(latest_quote.ask or 0),
        policy=policy,
        trade_plan=trade_plan,
        allocation=allocation,
    )
    reasons = _assessment_reasons(
        liquidity_state=liquidity_state,
        spread_state=spread_state,
        stability_state=stability_state,
        impact_state=impact_state,
        fill_state=fill_state,
        volume_features=volume_features,
        spread_features=spread_features,
        market_state=market_state,
    )
    limitations = ["NO_LEVEL_2_ORDER_BOOK_EVIDENCE"]
    if latest_quote.size_evidence_state != OBSERVED:
        limitations.append("DISPLAYED_SIZE_NOT_OBSERVED")
    if broker_capabilities is None:
        limitations.append("BROKER_CAPABILITIES_NOT_SUPPLIED")
    else:
        limitations.append("CAPABILITY_REGISTRY_HAS_NO_NATIVE_AS_OF_TIMESTAMP")
    references = _evidence_references(
        quotes=ordered_quotes,
        candles=ordered_candles,
        trade_plan=trade_plan,
        allocation=allocation,
        broker_capabilities=broker_capabilities,
    )
    evidence_fingerprint = _evidence_fingerprint(references)
    assessment = _with_assessment_fingerprint(
        ExecutionQualityAssessment(
            assessment_id=_assessment_id(
                opportunity_id=target_opportunity,
                evaluated=evaluated,
                policy=policy,
                input_evidence_fingerprint=evidence_fingerprint,
            ),
            opportunity_id=target_opportunity,
            candidate_id=target_candidate,
            setup_id=target_setup,
            trade_plan_id=trade_plan_id,
            symbol=normalized_symbol,
            evaluated_at=_iso(evaluated),
            session_state=session_state,
            market_state=market_state,
            liquidity_state=liquidity_state,
            spread_state=spread_state,
            quote_stability_state=stability_state,
            price_impact_risk_state=impact_state,
            fill_risk_state=fill_state,
            data_quality_state=COMPLETE,
            displayed_size_state=latest_quote.size_evidence_state,
            quote_age_seconds=_round(
                (evaluated - _effective_quote_time(latest_quote)).total_seconds()
            ),
            source_identity=latest_quote.source_identity,
            spread_features=spread_features,
            quote_stability_features=stability_features,
            volume_progress_features=volume_features,
            slippage_sensitivity=sensitivity,
            capability_registry_fingerprint=(
                broker_capabilities.fingerprint.lower()
                if broker_capabilities is not None
                else None
            ),
            reason_codes=tuple(sorted(set(reasons))),
            limitations=tuple(sorted(set(limitations))),
            input_evidence_fingerprint=evidence_fingerprint,
            policy_version=policy.policy_version,
            policy_fingerprint=policy.fingerprint,
        )
    )
    opinion_code = _opinion_code(
        market_state=market_state,
        liquidity_state=liquidity_state,
        spread_state=spread_state,
        stability_state=stability_state,
        fill_state=fill_state,
    )
    feature_families = {"EXECUTION_LIQUIDITY", "CANDLE_STRUCTURE", "VOLUME"}
    if broker_capabilities is not None:
        feature_families.add("BROKER_STATE")
    opinion = build_specialist_opinion(
        specialist_id=EXECUTION_QUALITY_SPECIALIST_ID,
        specialist_version=policy.specialist_version,
        opportunity_id=target_opportunity,
        candidate_id=target_candidate,
        setup_id=target_setup,
        trade_plan_id=trade_plan_id,
        as_of=evaluated,
        expires_at=evaluated + timedelta(seconds=policy.opinion_ttl_seconds),
        research_identity=policy.research_identity,
        policy_fingerprint=policy.fingerprint,
        evaluation_status=EVALUATED,
        opinion_code=opinion_code,
        directional_bias=NON_DIRECTIONAL,
        evidence_refs=references,
        feature_families=feature_families,
        confidence=build_confidence(
            value=_heuristic_confidence(assessment),
            kind=HEURISTIC,
            calibration_status=UNCALIBRATED,
            sample_size=None,
            model_version=policy.policy_version,
        ),
        reason_codes=assessment.reason_codes,
        explanation=(
            "Research-only mechanical execution assessment. Confidence is an "
            "uncalibrated evidence-completeness heuristic, not a fill probability "
            "or trade recommendation."
        ),
    )
    packet = ExecutionQualityPacket(policy=policy, assessment=assessment, opinion=opinion)
    packet = replace(packet, fingerprint=_packet_fingerprint(packet))
    validate_packet(packet)
    return packet


def build_observed_execution_result(
    *,
    opportunity_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    trade_plan_id: str | None,
    symbol: str,
    provider: str,
    environment: str,
    source_identity: str,
    source_fingerprint: str,
    decision_ask: float,
    submitted_reference: float | None,
    requested_quantity: float | None,
    requested_notional: float | None,
    fill_state: str,
    filled_quantity: float,
    confirmed_position_quantity: float,
    average_fill_price: float | None,
    decision_time: datetime | str,
    submitted_time: datetime | str | None,
    accepted_time: datetime | str | None,
    filled_time: datetime | str | None,
    cancelled_time: datetime | str | None,
) -> ObservedProviderExecutionResult:
    value = ObservedProviderExecutionResult(
        result_id="",
        opportunity_id=_sha256(opportunity_id, "Opportunity identity"),
        candidate_id=_optional_identifier(candidate_id, "Candidate identity"),
        setup_id=_optional_sha256(setup_id, "Setup identity"),
        trade_plan_id=_optional_sha256(trade_plan_id, "TradePlan identity"),
        symbol=_symbol(symbol),
        provider=_identifier(provider, "Execution provider"),
        environment=_identifier(environment, "Execution environment"),
        source_identity=_identifier(source_identity, "Execution source identity"),
        source_fingerprint=_sha256(source_fingerprint, "Execution source fingerprint"),
        decision_ask=_number(decision_ask, "Decision ask"),
        submitted_reference=_optional_number(submitted_reference),
        requested_quantity=_optional_number(requested_quantity),
        requested_notional=_optional_number(requested_notional),
        fill_state=_token(fill_state, "Fill state"),
        filled_quantity=_number(filled_quantity, "Filled quantity"),
        confirmed_position_quantity=_number(
            confirmed_position_quantity, "Confirmed position quantity"
        ),
        average_fill_price=_optional_number(average_fill_price),
        decision_time=_iso(_aware(decision_time, "Decision time")),
        submitted_time=_optional_time(submitted_time, "Submitted time"),
        accepted_time=_optional_time(accepted_time, "Accepted time"),
        filled_time=_optional_time(filled_time, "Filled time"),
        cancelled_time=_optional_time(cancelled_time, "Cancelled time"),
        fingerprint="",
    )
    value = replace(value, result_id=_fingerprint(_result_identity_payload(value)))
    value = replace(value, fingerprint=_fingerprint(asdict(value)))
    validate_observed_execution_result(value)
    return value


def attach_observed_execution_result(
    packet: ExecutionQualityPacket,
    result: ObservedProviderExecutionResult,
    *,
    trade_plan: IntradayPlanEvidence | None = None,
) -> ExecutionQualityResearchRecord:
    """Attach later provider truth without mutating the predecision packet."""

    validate_packet(packet)
    validate_observed_execution_result(result)
    expected = (
        packet.assessment.opportunity_id,
        packet.assessment.candidate_id,
        packet.assessment.setup_id,
        packet.assessment.trade_plan_id,
        packet.assessment.symbol,
    )
    actual = (
        result.opportunity_id,
        result.candidate_id,
        result.setup_id,
        result.trade_plan_id,
        result.symbol,
    )
    if actual != expected:
        raise ExecutionQualityError("Observed execution target identity mismatch.")
    if _parse_time(result.decision_time) < _parse_time(packet.assessment.evaluated_at):
        raise ExecutionQualityError("Observed execution predates the original opinion.")
    if trade_plan is not None and trade_plan.plan_id != result.trade_plan_id:
        raise ExecutionQualityError("Observed execution TradePlan identity mismatch.")
    metrics = _observed_metrics(result, trade_plan=trade_plan)
    record = ExecutionQualityResearchRecord(
        original_packet=packet,
        observed_result=result,
        observed_metrics=metrics,
        original_opinion_id=packet.opinion.opinion_id,
        original_opinion_fingerprint=packet.opinion.fingerprint,
    )
    record = replace(record, fingerprint=_fingerprint(_research_record_wire(record)))
    validate_research_record(record)
    return record


def validate_policy(policy: ExecutionQualityPolicy) -> None:
    if policy.specialist_version != EXECUTION_QUALITY_SPECIALIST_VERSION:
        raise ExecutionQualityError("Execution Quality specialist version is unsupported.")
    if policy.threshold_semantics != RESEARCH_HEURISTIC:
        raise ExecutionQualityError("Policy thresholds must be labeled research heuristics.")
    if policy.full_classification_session != REGULAR:
        raise ExecutionQualityError("V1 full classification is regular-session only.")
    if policy.maximum_quote_age_seconds != 30:
        raise ExecutionQualityError("V1 cannot weaken the 30-second quote-age ceiling.")
    if (
        policy.minimum_quote_observations < 3
        or policy.minimum_candle_observations < 2
        or policy.maximum_quote_observations < policy.minimum_quote_observations
        or policy.maximum_candle_observations < policy.minimum_candle_observations
        or policy.maximum_quote_observations + policy.maximum_candle_observations + 3
        > 128
    ):
        raise ExecutionQualityError("Policy evidence minima are unsafe.")
    if policy.slippage_bands_bps != tuple(sorted(set(policy.slippage_bands_bps))):
        raise ExecutionQualityError("Slippage bands must be canonical and unique.")
    if any(item < 0 for item in policy.slippage_bands_bps):
        raise ExecutionQualityError("Slippage bands cannot be negative.")
    numeric = (
        policy.spread_tight_bps,
        policy.spread_normal_bps,
        policy.spread_wide_bps,
        policy.stability_moderate_midpoint_range_bps,
        policy.stability_unstable_midpoint_range_bps,
        policy.stability_dislocated_midpoint_range_bps,
        policy.liquid_dollar_turnover_per_minute,
        policy.adequate_dollar_turnover_per_minute,
        policy.thin_dollar_turnover_per_minute,
    )
    if any(not math.isfinite(item) or item <= 0 for item in numeric):
        raise ExecutionQualityError("Policy thresholds must be positive finite data.")
    if not (
        policy.spread_tight_bps < policy.spread_normal_bps < policy.spread_wide_bps
        and policy.stability_moderate_midpoint_range_bps
        < policy.stability_unstable_midpoint_range_bps
        < policy.stability_dislocated_midpoint_range_bps
        and policy.liquid_dollar_turnover_per_minute
        > policy.adequate_dollar_turnover_per_minute
        > policy.thin_dollar_turnover_per_minute
    ):
        raise ExecutionQualityError("Policy threshold ordering is invalid.")


def validate_packet(packet: ExecutionQualityPacket) -> None:
    validate_policy(packet.policy)
    validate_specialist_opinion(packet.opinion)
    assessment = packet.assessment
    if packet.schema_version != EXECUTION_QUALITY_SCHEMA_VERSION:
        raise ExecutionQualityError("Execution Quality packet schema is unsupported.")
    if packet.profile != EXECUTION_QUALITY_PROFILE:
        raise ExecutionQualityError("Execution Quality packet profile is unsupported.")
    if packet.evidence_domain != PRE_DECISION_EXECUTION_QUALITY:
        raise ExecutionQualityError("Predecision evidence domain is invalid.")
    if assessment.authority != RESEARCH_ONLY or (
        assessment.execution_authority != EXECUTION_AUTHORITY_NONE
    ):
        raise ExecutionQualityError("Execution Quality cannot gain execution authority.")
    if assessment.trade_recommendation:
        raise ExecutionQualityError("Execution Quality cannot recommend a trade.")
    if assessment.liquidity_state not in LIQUIDITY_STATES:
        raise ExecutionQualityError("Liquidity state is unsupported.")
    if assessment.spread_state not in SPREAD_STATES:
        raise ExecutionQualityError("Spread state is unsupported.")
    if assessment.quote_stability_state not in STABILITY_STATES:
        raise ExecutionQualityError("Quote-stability state is unsupported.")
    if assessment.price_impact_risk_state not in RISK_STATES:
        raise ExecutionQualityError("Price-impact state is unsupported.")
    if assessment.fill_risk_state not in RISK_STATES:
        raise ExecutionQualityError("Fill-risk state is unsupported.")
    if assessment.data_quality_state not in DATA_QUALITY_STATES:
        raise ExecutionQualityError("Data-quality state is unsupported.")
    if assessment.market_state not in MARKET_STATES:
        raise ExecutionQualityError("Market state is unsupported.")
    if assessment.policy_fingerprint != packet.policy.fingerprint:
        raise ExecutionQualityError("Policy fingerprint drift detected.")
    if assessment.fingerprint != _assessment_fingerprint(assessment):
        raise ExecutionQualityError("Execution Quality assessment was tampered.")
    if packet.opinion.policy_fingerprint != packet.policy.fingerprint:
        raise ExecutionQualityError("Opinion policy fingerprint drift detected.")
    if packet.opinion.specialist_id != EXECUTION_QUALITY_SPECIALIST_ID or (
        packet.opinion.specialist_version != packet.policy.specialist_version
    ):
        raise ExecutionQualityError("Execution Quality specialist identity is invalid.")
    if packet.opinion.as_of != assessment.evaluated_at:
        raise ExecutionQualityError("Opinion and assessment timestamps contradict.")
    if (
        packet.opinion.opportunity_id,
        packet.opinion.candidate_id,
        packet.opinion.setup_id,
        packet.opinion.trade_plan_id,
    ) != (
        assessment.opportunity_id,
        assessment.candidate_id,
        assessment.setup_id,
        assessment.trade_plan_id,
    ):
        raise ExecutionQualityError("Opinion target identity is contradictory.")
    if assessment.input_evidence_fingerprint != packet.opinion.input_evidence_fingerprint:
        raise ExecutionQualityError("Opinion and assessment evidence identity contradict.")
    evaluated = _parse_time(assessment.evaluated_at)
    if assessment.session_state != classify_session(evaluated):
        raise ExecutionQualityError("Assessment session identity is contradictory.")
    if assessment.assessment_id != _assessment_id(
        opportunity_id=assessment.opportunity_id,
        evaluated=evaluated,
        policy=packet.policy,
        input_evidence_fingerprint=assessment.input_evidence_fingerprint,
    ):
        raise ExecutionQualityError("Execution Quality assessment identity is invalid.")
    if packet.fingerprint != _packet_fingerprint(packet):
        raise ExecutionQualityError("Execution Quality packet was tampered.")


def validate_observed_execution_result(result: ObservedProviderExecutionResult) -> None:
    if result.fill_state not in FILL_STATES:
        raise ExecutionQualityError("Observed fill state is unsupported.")
    if result.requested_quantity is not None and result.requested_notional is not None:
        raise ExecutionQualityError("Execution request cannot contain qty and notional together.")
    if result.requested_quantity is None and result.requested_notional is None:
        raise ExecutionQualityError("Execution request quantity or notional is required.")
    for value, label in (
        (result.decision_ask, "Decision ask"),
        (result.filled_quantity, "Filled quantity"),
        (result.confirmed_position_quantity, "Confirmed position quantity"),
    ):
        if not math.isfinite(value) or value < 0:
            raise ExecutionQualityError(f"{label} is invalid.")
    if result.decision_ask <= 0:
        raise ExecutionQualityError("Decision ask must be positive.")
    if result.filled_quantity > result.confirmed_position_quantity + 1e-9:
        raise ExecutionQualityError("Filled quantity exceeds confirmed position quantity.")
    has_fill = result.filled_quantity > 0
    if result.fill_state == NO_FILL:
        if has_fill or result.average_fill_price is not None or result.filled_time is not None:
            raise ExecutionQualityError("No-fill result cannot carry fill evidence.")
    elif result.fill_state == UNKNOWN_FILL:
        if has_fill or result.average_fill_price is not None or result.filled_time is not None:
            raise ExecutionQualityError("Unknown-fill result cannot claim fill evidence.")
    elif result.fill_state in {FULL_FILL, PARTIAL_FILL, CANCELLED_REMAINDER}:
        if not has_fill or result.average_fill_price is None or result.filled_time is None:
            raise ExecutionQualityError("Filled result requires actual provider fill evidence.")
        if result.average_fill_price <= 0:
            raise ExecutionQualityError("Average fill price must be positive.")
        if result.submitted_time is None:
            raise ExecutionQualityError("Filled result requires a submitted timestamp.")
    if result.fill_state == CANCELLED_REMAINDER and result.cancelled_time is None:
        raise ExecutionQualityError("Cancelled remainder requires a cancellation timestamp.")
    if result.requested_quantity is not None:
        if result.requested_quantity <= 0:
            raise ExecutionQualityError("Requested quantity must be positive.")
        if result.filled_quantity > result.requested_quantity + 1e-9:
            raise ExecutionQualityError("Filled quantity exceeds requested quantity.")
        if result.fill_state == FULL_FILL and not math.isclose(
            result.filled_quantity, result.requested_quantity, abs_tol=1e-9
        ):
            raise ExecutionQualityError("Partial fill was incorrectly labeled full.")
        if result.fill_state in {PARTIAL_FILL, CANCELLED_REMAINDER} and not (
            0 < result.filled_quantity < result.requested_quantity
        ):
            raise ExecutionQualityError("Partial-fill quantity semantics are invalid.")
    times = [
        _parse_time(result.decision_time),
        *(
            _parse_time(item)
            for item in (
                result.submitted_time,
                result.accepted_time,
                result.filled_time,
                result.cancelled_time,
            )
            if item is not None
        ),
    ]
    if times != sorted(times):
        raise ExecutionQualityError("Observed execution chronology is contradictory.")
    if result.result_id != _fingerprint(_result_identity_payload(result)):
        raise ExecutionQualityError("Observed execution result identity is invalid.")
    if result.fingerprint != _fingerprint(asdict(replace(result, fingerprint=""))):
        raise ExecutionQualityError("Observed execution result was tampered.")


def validate_research_record(record: ExecutionQualityResearchRecord) -> None:
    validate_packet(record.original_packet)
    validate_observed_execution_result(record.observed_result)
    if record.original_opinion_id != record.original_packet.opinion.opinion_id:
        raise ExecutionQualityError("Later evidence changed the original opinion identity.")
    if record.original_opinion_fingerprint != record.original_packet.opinion.fingerprint:
        raise ExecutionQualityError("Later evidence changed the original opinion fingerprint.")
    if record.observed_metrics.actual_filled_quantity != record.observed_result.filled_quantity:
        raise ExecutionQualityError("Observed metrics do not use actual filled quantity.")
    if record.fingerprint != _fingerprint(
        _research_record_wire(replace(record, fingerprint=""))
    ):
        raise ExecutionQualityError("Execution research record was tampered.")


def packet_json_bytes(packet: ExecutionQualityPacket) -> bytes:
    validate_packet(packet)
    return (_canonical_json(_packet_wire(packet)) + "\n").encode("ascii")


def research_record_json_bytes(record: ExecutionQualityResearchRecord) -> bytes:
    validate_research_record(record)
    return (_canonical_json(_research_record_wire(record)) + "\n").encode("ascii")


def classify_session(observed_at: datetime) -> str:
    eastern = _aware(observed_at, "Session timestamp").astimezone(_EASTERN)
    value = eastern.time().replace(tzinfo=None)
    if time(4, 0) <= value < time(9, 30):
        return PREMARKET
    if time(9, 30) <= value < time(16, 0):
        return REGULAR
    if time(16, 0) <= value < time(20, 0):
        return AFTER_HOURS
    return UNSUPPORTED_SESSION


def _quote_findings(
    quotes: tuple[ExecutionQuoteObservation, ...],
    *,
    symbol: str,
    evaluated: datetime,
    session_state: str,
    policy: ExecutionQualityPolicy,
) -> tuple[str | None, str | None]:
    if not quotes:
        return None, "QUOTE_UNAVAILABLE"
    if len(quotes) > policy.maximum_quote_observations:
        return "QUOTE_SEQUENCE_EXCEEDS_BOUND", None
    seen_ids: set[str] = set()
    seen_times: set[str] = set()
    sources: set[str] = set()
    for item in quotes:
        expected = _fingerprint(asdict(replace(item, fingerprint="")))
        if item.fingerprint != expected:
            return "QUOTE_EVIDENCE_TAMPERED", None
        if item.quote_id in seen_ids:
            return "DUPLICATE_QUOTE_IDENTITY", None
        seen_ids.add(item.quote_id)
        if item.symbol != symbol:
            return "QUOTE_SYMBOL_MISMATCH", None
        if item.session != session_state:
            return "QUOTE_SESSION_MISMATCH", None
        sources.add(item.source_identity)
        if len(sources) > 1:
            return "CONFLICTING_QUOTE_SOURCE_IDENTITY", None
        if not item.realtime:
            return "QUOTE_NOT_REALTIME", None
        if item.size_evidence_state not in SIZE_EVIDENCE_STATES:
            return "DISPLAYED_SIZE_STATE_INVALID", None
        if item.size_evidence_state == OBSERVED:
            if not _positive(item.bid_size) or not _positive(item.ask_size):
                return "DISPLAYED_SIZE_EVIDENCE_INVALID", None
        elif item.bid_size is not None or item.ask_size is not None:
            return "DISPLAYED_SIZE_WITHOUT_AUTHORITY", None
        times = tuple(
            _parse_time(value)
            for value in (
                item.provider_quote_time,
                item.provider_bid_time,
                item.provider_ask_time,
            )
        )
        receipt = _parse_time(item.receipt_time)
        if any(value > receipt or value > evaluated for value in times):
            return "FUTURE_QUOTE_OR_RECEIPT_CONTRADICTION", None
        if receipt > evaluated:
            return "FUTURE_QUOTE_RECEIPT", None
        if max(times) - min(times) > timedelta(
            seconds=policy.maximum_quote_component_skew_seconds
        ):
            return "BID_ASK_CHRONOLOGY_CONTRADICTION", None
        effective = min(times)
        key = _iso(effective)
        if key in seen_times:
            return "DUPLICATE_QUOTE_TIMESTAMP", None
        seen_times.add(key)
        if item.bid is None or item.ask is None:
            return "ONE_SIDED_MARKET", None
        if not _positive(item.bid) or not _positive(item.ask):
            return "QUOTE_PRICE_INVALID", None
        if float(item.ask) < float(item.bid):
            return "CROSSED_MARKET", None
    latest = max(quotes, key=_effective_quote_time)
    age = (evaluated - _effective_quote_time(latest)).total_seconds()
    if age < 0:
        return "FUTURE_QUOTE", None
    if age > policy.maximum_quote_age_seconds:
        return None, "STALE_QUOTE"
    if latest.trading_state == HALTED or latest.security_status == HALTED:
        return None, "AUTHORITATIVE_HALT_STATUS"
    return None, None


def _candle_findings(
    candles: tuple[ExecutionMinuteBar, ...],
    *,
    symbol: str,
    evaluated: datetime,
    policy: ExecutionQualityPolicy,
) -> tuple[str | None, str | None]:
    if len(candles) < policy.minimum_candle_observations:
        return None, "INCOMPLETE_CANDLE_WINDOW"
    if len(candles) > policy.maximum_candle_observations:
        return "CANDLE_WINDOW_EXCEEDS_BOUND", None
    ordered = sorted(candles, key=lambda item: item.timestamp)
    sources: set[str] = set()
    seen_ids: set[str] = set()
    seen_times: set[str] = set()
    expected_session_date = evaluated.astimezone(_EASTERN).date().isoformat()
    for item in ordered:
        if item.fingerprint != _fingerprint(asdict(replace(item, fingerprint=""))):
            return "CANDLE_EVIDENCE_TAMPERED", None
        if item.evidence_id in seen_ids:
            return "DUPLICATE_CANDLE_IDENTITY", None
        seen_ids.add(item.evidence_id)
        if item.symbol != symbol:
            return "CANDLE_SYMBOL_MISMATCH", None
        if item.state not in CANONICAL_CANDLE_STATES:
            return "CANDLE_STATE_NOT_CANONICAL", None
        sources.add(item.source_identity)
        if len(sources) > 1:
            return "CONFLICTING_CANDLE_SOURCE_IDENTITY", None
        if item.session_date != expected_session_date:
            return "CANDLE_SESSION_DATE_MISMATCH", None
        stamp = _parse_time(item.timestamp)
        if stamp.second or stamp.microsecond:
            return "CANDLE_TIMESTAMP_NOT_MINUTE_ALIGNED", None
        if stamp + timedelta(minutes=1) > evaluated:
            return "IN_PROGRESS_OR_FUTURE_CANDLE", None
        if item.timestamp in seen_times:
            return "DUPLICATE_CANDLE_TIMESTAMP", None
        seen_times.add(item.timestamp)
        values = (item.open, item.high, item.low, item.close)
        if any(not _positive(value) for value in values):
            return "CANDLE_OHLC_INVALID", None
        if item.high < max(item.open, item.close, item.low) or item.low > min(
            item.open, item.close, item.high
        ):
            return "CANDLE_OHLC_CONTRADICTION", None
        if item.volume is None:
            return None, "MISSING_CANDLE_VOLUME"
        if not math.isfinite(item.volume) or item.volume < 0:
            return "CANDLE_VOLUME_INVALID", None
    for previous, current in zip(ordered, ordered[1:]):
        if _parse_time(current.timestamp) - _parse_time(previous.timestamp) != timedelta(
            minutes=1
        ):
            return "CANDLE_WINDOW_GAP", None
    latest_close = _parse_time(ordered[-1].timestamp) + timedelta(minutes=1)
    if (evaluated - latest_close).total_seconds() > policy.maximum_completed_bar_age_seconds:
        return None, "STALE_CANDLE_WINDOW"
    return None, None


def _plan_error(
    plan: IntradayPlanEvidence | None,
    *,
    symbol: str,
    setup_id: str | None,
    evaluated_at: datetime,
) -> str | None:
    if plan is None:
        return None
    if intraday_plan_validation_findings(plan):
        return "TRADE_PLAN_EVIDENCE_INVALID"
    if plan.symbol != symbol:
        return "TRADE_PLAN_SYMBOL_MISMATCH"
    if setup_id is not None and plan.source_setup_fingerprint != setup_id:
        return "TRADE_PLAN_SETUP_IDENTITY_MISMATCH"
    if (
        _parse_time(plan.created_at) > evaluated_at
        or _parse_time(plan.lifecycle_updated_at) > evaluated_at
    ):
        return "TRADE_PLAN_FUTURE_DATED"
    return None


def _allocation_error(
    allocation: ProviderNeutralAllocationDecision | None,
    *,
    trade_plan: IntradayPlanEvidence | None,
    symbol: str,
) -> str | None:
    if allocation is None:
        return None
    if trade_plan is None:
        return "ALLOCATION_WITHOUT_TRADE_PLAN"
    if allocation.trade_plan_id != trade_plan.plan_id:
        return "ALLOCATION_TRADE_PLAN_IDENTITY_MISMATCH"
    if allocation.symbol != symbol:
        return "ALLOCATION_SYMBOL_MISMATCH"
    if allocation.final_authorized_quantity < 0:
        return "ALLOCATION_QUANTITY_INVALID"
    return None


def _spread_features(
    quote: ExecutionQuoteObservation | None,
    *,
    candles: Sequence[ExecutionMinuteBar],
    trade_plan: IntradayPlanEvidence | None,
) -> SpreadFeatures:
    if quote is None or not _positive(quote.bid) or not _positive(quote.ask):
        return _empty_spread_features()
    bid = float(quote.bid or 0)
    ask = float(quote.ask or 0)
    midpoint = (bid + ask) / 2
    spread = ask - bid
    true_ranges: list[float] = []
    prior_close: float | None = None
    for item in candles[-15:]:
        true_range = item.high - item.low
        if prior_close is not None:
            true_range = max(
                true_range,
                abs(item.high - prior_close),
                abs(item.low - prior_close),
            )
        true_ranges.append(true_range)
        prior_close = item.close
    atr_values = true_ranges[-14:]
    atr = sum(atr_values) / len(atr_values) if atr_values else None
    recent_range = (
        sum(item.high - item.low for item in candles[-5:]) / len(candles[-5:])
        if candles[-5:]
        else None
    )
    stop_distance = None
    bid_distance_to_stop = None
    ask_vs_planned_entry = None
    if trade_plan is not None and trade_plan.stop_price is not None:
        stop_distance = ask - float(trade_plan.stop_price)
        bid_distance_to_stop = bid - float(trade_plan.stop_price)
    if trade_plan is not None and trade_plan.planned_entry is not None:
        ask_vs_planned_entry = _ratio_pct(
            ask - float(trade_plan.planned_entry),
            float(trade_plan.planned_entry),
        )
    return SpreadFeatures(
        bid=_round(bid),
        ask=_round(ask),
        midpoint=_round(midpoint),
        absolute_spread=_round(spread),
        spread_percent=_ratio_pct(spread, midpoint),
        spread_basis_points=_round((spread / midpoint) * 10_000),
        spread_over_atr=_ratio(spread, atr),
        spread_over_recent_one_minute_range=_ratio(spread, recent_range),
        spread_over_stop_distance=_ratio(spread, stop_distance),
        spread_over_planned_risk_per_share=_ratio(spread, stop_distance),
        current_ask_vs_planned_entry_percent=ask_vs_planned_entry,
        current_bid_distance_to_stop=_round(bid_distance_to_stop),
    )


def _quote_stability_features(
    quotes: Sequence[ExecutionQuoteObservation],
) -> QuoteStabilityFeatures:
    if len(quotes) < 2:
        return _empty_stability_features(len(quotes))
    bids = [float(item.bid or 0) for item in quotes]
    asks = [float(item.ask or 0) for item in quotes]
    midpoints = [(bid + ask) / 2 for bid, ask in zip(bids, asks)]
    spreads = [ask - bid for bid, ask in zip(bids, asks)]
    window = (_effective_quote_time(quotes[-1]) - _effective_quote_time(quotes[0])).total_seconds()
    directions = [_sign(current - previous) for previous, current in zip(midpoints, midpoints[1:])]
    nonzero = [item for item in directions if item]
    changes = sum(1 for left, right in zip(nonzero, nonzero[1:]) if left != right)
    returns = [
        ((current / previous) - 1) * 10_000
        for previous, current in zip(midpoints, midpoints[1:])
        if previous > 0
    ]
    first_spread = spreads[0]
    expansion = spreads[-1] / first_spread if first_spread > 0 else None
    midpoint_reference = sum(midpoints) / len(midpoints)
    return QuoteStabilityFeatures(
        observation_count=len(quotes),
        observation_window_seconds=_round(window),
        bid_movement=_round(bids[-1] - bids[0]),
        ask_movement=_round(asks[-1] - asks[0]),
        midpoint_movement=_round(midpoints[-1] - midpoints[0]),
        midpoint_range_basis_points=_round(
            ((max(midpoints) - min(midpoints)) / midpoint_reference) * 10_000
        ),
        spread_expansion_multiple=_round(expansion),
        quote_updates_per_second=_round((len(quotes) - 1) / window) if window > 0 else None,
        direction_change_fraction=_round(changes / max(1, len(nonzero) - 1)),
        realized_midpoint_volatility_basis_points=(
            _round(pstdev(returns)) if len(returns) >= 2 else 0.0
        ),
    )


def _volume_progress_features(
    candles: Sequence[ExecutionMinuteBar],
    *,
    policy: ExecutionQualityPolicy,
) -> VolumeProgressFeatures:
    recent = tuple(candles[-5:])
    prior = tuple(candles[-15:-5])
    recent_volume = sum(float(item.volume or 0) for item in recent)
    prior_volume = sum(float(item.volume or 0) for item in prior)
    average_turnover = sum(
        float(item.volume or 0) * item.close for item in recent
    ) / max(1, len(recent))
    start = recent[0].open
    end = recent[-1].close
    change_pct = ((end / start) - 1) * 100
    range_pct = ((max(item.high for item in recent) - min(item.low for item in recent)) / start) * 100
    progress_per_million = (
        abs(end - start) / (recent_volume / 1_000_000)
        if recent_volume > 0
        else None
    )
    recent_average = recent_volume / max(1, len(recent))
    prior_average = prior_volume / max(1, len(prior)) if prior else 0
    expansion = recent_average / prior_average if prior_average > 0 else None
    return VolumeProgressFeatures(
        candle_count=len(candles),
        recent_window_minutes=len(recent),
        recent_volume=_round(recent_volume),
        prior_volume=_round(prior_volume),
        average_dollar_turnover_per_minute=_round(average_turnover),
        price_change_percent=_round(change_pct),
        price_range_percent=_round(range_pct),
        directional_progress_per_million_volume=_round(progress_per_million),
        volume_expansion_multiple=_round(expansion),
        volume_without_progress=(
            expansion is not None
            and expansion >= policy.volume_expansion_multiple
            and abs(change_pct) <= policy.poor_progress_pct
        ),
        thin_volume_rapid_move=(
            average_turnover < policy.thin_dollar_turnover_per_minute
            and abs(change_pct) >= policy.thin_rapid_move_pct
        ),
    )


def _slippage_sensitivity(
    *,
    ask: float,
    policy: ExecutionQualityPolicy,
    trade_plan: IntradayPlanEvidence | None,
    allocation: ProviderNeutralAllocationDecision | None,
) -> tuple[SlippageSensitivityPoint, ...]:
    if trade_plan is None or trade_plan.stop_price is None or not trade_plan.target_prices:
        return ()
    stop = float(trade_plan.stop_price)
    target = float(trade_plan.target_prices[0])
    planned = float(trade_plan.planned_entry or ask)
    quantity = (
        float(allocation.final_authorized_quantity)
        if allocation is not None and allocation.final_authorized_quantity > 0
        else None
    )
    rows: list[SlippageSensitivityPoint] = []
    for bps in policy.slippage_bands_bps:
        entry = ask * (1 + bps / 10_000)
        risk = entry - stop
        reward = target - entry
        valid_risk = risk if risk > 0 else None
        valid_reward = reward if reward > 0 else None
        rows.append(
            SlippageSensitivityPoint(
                basis_points=bps,
                hypothetical_entry=_round(entry),
                risk_per_share=_round(valid_risk),
                reward_per_share=_round(valid_reward),
                reward_risk=_ratio(valid_reward, valid_risk),
                extension_from_planned_entry_percent=_ratio_pct(entry - planned, planned),
                distance_to_stop=_round(valid_risk),
                distance_to_first_target=_round(valid_reward),
                dollar_risk_at_authorized_quantity=(
                    _round(valid_risk * quantity)
                    if valid_risk is not None and quantity is not None
                    else None
                ),
            )
        )
    return tuple(rows)


def _observed_metrics(
    result: ObservedProviderExecutionResult,
    *,
    trade_plan: IntradayPlanEvidence | None,
) -> ObservedExecutionMetrics:
    if result.fill_state == NO_FILL or result.filled_quantity == 0:
        return ObservedExecutionMetrics(
            fill_slippage_dollars_per_share=None,
            fill_slippage_percent=None,
            fill_slippage_basis_points=None,
            fill_slippage_from_submitted_dollars_per_share=None,
            fill_slippage_from_submitted_basis_points=None,
            fill_delay_seconds=None,
            quantity_fill_ratio=(
                0.0 if result.requested_quantity is not None else None
            ),
            realized_initial_risk=None,
            realized_execution_reward_risk=None,
            actual_filled_quantity=0.0,
        )
    fill = float(result.average_fill_price or 0)
    slippage = fill - result.decision_ask
    submitted_slippage = (
        fill - result.submitted_reference
        if result.submitted_reference is not None
        else None
    )
    delay = (
        _parse_time(result.filled_time) - _parse_time(result.submitted_time)
    ).total_seconds() if result.filled_time and result.submitted_time else None
    ratio = (
        result.filled_quantity / result.requested_quantity
        if result.requested_quantity is not None
        else None
    )
    risk = None
    reward_risk = None
    if trade_plan is not None and trade_plan.stop_price is not None and trade_plan.target_prices:
        per_share_risk = fill - float(trade_plan.stop_price)
        reward = float(trade_plan.target_prices[0]) - fill
        if per_share_risk > 0:
            risk = per_share_risk * result.filled_quantity
            reward_risk = reward / per_share_risk if reward > 0 else None
    return ObservedExecutionMetrics(
        fill_slippage_dollars_per_share=_round(slippage),
        fill_slippage_percent=_ratio_pct(slippage, result.decision_ask),
        fill_slippage_basis_points=_round((slippage / result.decision_ask) * 10_000),
        fill_slippage_from_submitted_dollars_per_share=_round(submitted_slippage),
        fill_slippage_from_submitted_basis_points=(
            _round((submitted_slippage / result.submitted_reference) * 10_000)
            if submitted_slippage is not None and result.submitted_reference
            else None
        ),
        fill_delay_seconds=_round(delay),
        quantity_fill_ratio=_round(ratio),
        realized_initial_risk=_round(risk),
        realized_execution_reward_risk=_round(reward_risk),
        actual_filled_quantity=result.filled_quantity,
    )


def _spread_state(features: SpreadFeatures, *, policy: ExecutionQualityPolicy) -> str:
    bps = features.spread_basis_points
    if bps is None:
        return UNKNOWN
    if features.spread_over_stop_distance is not None and features.spread_over_stop_distance >= 1:
        return EXTREME
    if bps <= policy.spread_tight_bps:
        return TIGHT
    if bps <= policy.spread_normal_bps:
        return NORMAL
    if bps <= policy.spread_wide_bps:
        return WIDE
    return EXTREME


def _stability_state(features: QuoteStabilityFeatures, *, policy: ExecutionQualityPolicy) -> str:
    midpoint_range = features.midpoint_range_basis_points
    expansion = features.spread_expansion_multiple
    if midpoint_range is None or expansion is None:
        return UNKNOWN
    if (
        midpoint_range >= policy.stability_dislocated_midpoint_range_bps
        or expansion >= policy.stability_dislocated_spread_expansion
    ):
        return DISLOCATED
    if (
        midpoint_range >= policy.stability_unstable_midpoint_range_bps
        or expansion >= policy.stability_unstable_spread_expansion
    ):
        return UNSTABLE
    if (
        midpoint_range >= policy.stability_moderate_midpoint_range_bps
        or expansion >= policy.stability_moderate_spread_expansion
    ):
        return MODERATELY_UNSTABLE
    return STABLE


def _liquidity_state(features: VolumeProgressFeatures, *, policy: ExecutionQualityPolicy) -> str:
    turnover = features.average_dollar_turnover_per_minute
    if turnover is None:
        return UNKNOWN
    if turnover >= policy.liquid_dollar_turnover_per_minute:
        return LIQUID
    if turnover >= policy.adequate_dollar_turnover_per_minute:
        return ADEQUATE
    if turnover >= policy.thin_dollar_turnover_per_minute:
        return THIN
    return VERY_THIN


def _impact_state(
    *,
    liquidity_state: str,
    stability_state: str,
    volume_features: VolumeProgressFeatures,
) -> str:
    if liquidity_state == UNKNOWN or stability_state == UNKNOWN:
        return UNKNOWN
    if liquidity_state == VERY_THIN or stability_state == DISLOCATED or volume_features.thin_volume_rapid_move:
        return HIGH
    if liquidity_state == THIN or stability_state in {UNSTABLE, MODERATELY_UNSTABLE}:
        return MODERATE
    return LOW


def _fill_risk_state(
    *,
    liquidity_state: str,
    spread_state: str,
    stability_state: str,
    impact_state: str,
) -> str:
    if UNKNOWN in {liquidity_state, spread_state, stability_state, impact_state}:
        return UNKNOWN
    if (
        spread_state == EXTREME
        or stability_state == DISLOCATED
        or impact_state == HIGH
        or liquidity_state == VERY_THIN
    ):
        return HIGH
    if (
        spread_state == WIDE
        or stability_state in {UNSTABLE, MODERATELY_UNSTABLE}
        or impact_state == MODERATE
        or liquidity_state == THIN
    ):
        return MODERATE
    return LOW


def _market_state(quote: ExecutionQuoteObservation) -> str:
    if quote.trading_state == HALTED or quote.security_status == HALTED:
        return HALTED
    if quote.bid is None or quote.ask is None:
        return ONE_SIDED_MARKET
    if quote.ask < quote.bid:
        return CROSSED_MARKET
    if math.isclose(quote.ask, quote.bid, abs_tol=1e-12):
        return LOCKED_MARKET
    return NORMAL_MARKET


def _opinion_code(
    *,
    market_state: str,
    liquidity_state: str,
    spread_state: str,
    stability_state: str,
    fill_state: str,
) -> str:
    if market_state != NORMAL_MARKET or stability_state == DISLOCATED:
        return "EXECUTION_CONDITIONS_DISLOCATED"
    if fill_state == HIGH or spread_state == EXTREME or liquidity_state == VERY_THIN:
        return "EXECUTION_CONDITIONS_POOR"
    if fill_state == MODERATE or stability_state in {UNSTABLE, MODERATELY_UNSTABLE}:
        return "EXECUTION_CONDITIONS_FRAGILE"
    if liquidity_state == LIQUID and spread_state == TIGHT and stability_state == STABLE:
        return "EXECUTION_CONDITIONS_SUPPORT"
    return "EXECUTION_CONDITIONS_ACCEPTABLE"


def _assessment_reasons(**values: object) -> tuple[str, ...]:
    reasons = (
        f"LIQUIDITY_{values['liquidity_state']}",
        f"SPREAD_{values['spread_state']}",
        f"QUOTE_STABILITY_{values['stability_state']}",
        f"PRICE_IMPACT_RISK_{values['impact_state']}",
        f"FILL_RISK_{values['fill_state']}",
    )
    volume = values["volume_features"]
    spread = values["spread_features"]
    extra: list[str] = []
    if isinstance(volume, VolumeProgressFeatures):
        if volume.volume_without_progress:
            extra.append("VOLUME_EXPANSION_WITHOUT_PRICE_PROGRESS")
        if volume.thin_volume_rapid_move:
            extra.append("RAPID_PRICE_MOVEMENT_ON_THIN_VOLUME")
    if isinstance(spread, SpreadFeatures) and (
        spread.spread_over_stop_distance is not None
        and spread.spread_over_stop_distance >= 0.15
    ):
        extra.append("SPREAD_LARGE_RELATIVE_TO_STOP")
    if values["market_state"] == LOCKED_MARKET:
        extra.append("LOCKED_MARKET_OBSERVED")
    return tuple((*reasons, *extra))


def _terminal_packet(
    *,
    status: str,
    common_reason: str,
    machine_reason: str,
    opportunity_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    trade_plan_id: str | None,
    symbol: str,
    evaluated: datetime,
    session_state: str,
    policy: ExecutionQualityPolicy,
    quotes: Sequence[ExecutionQuoteObservation] = (),
    candles: Sequence[ExecutionMinuteBar] = (),
    spread_features: SpreadFeatures | None = None,
) -> ExecutionQualityPacket:
    safe_quotes = _unique_by_identity(
        tuple(item for item in quotes if _safe_quote_reference(item, evaluated)),
        identity=lambda item: item.quote_id,
    )
    safe_candles = _unique_by_identity(
        tuple(item for item in candles if _safe_candle_reference(item, evaluated)),
        identity=lambda item: item.evidence_id,
    )
    references = _evidence_references(quotes=safe_quotes, candles=safe_candles)
    evidence_fingerprint = _evidence_fingerprint(references)
    assessment = _with_assessment_fingerprint(
        ExecutionQualityAssessment(
            assessment_id=_assessment_id(
                opportunity_id=opportunity_id,
                evaluated=evaluated,
                policy=policy,
                input_evidence_fingerprint=evidence_fingerprint,
            ),
            opportunity_id=opportunity_id,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            symbol=symbol,
            evaluated_at=_iso(evaluated),
            session_state=session_state,
            market_state=(
                STALE_MARKET
                if machine_reason == "STALE_QUOTE"
                else HALTED
                if machine_reason == "AUTHORITATIVE_HALT_STATUS"
                else DATA_UNSAFE
                if status == FAILED
                else QUOTE_UNAVAILABLE
            ),
            liquidity_state=UNKNOWN,
            spread_state=UNKNOWN,
            quote_stability_state=UNKNOWN,
            price_impact_risk_state=UNKNOWN,
            fill_risk_state=UNKNOWN,
            data_quality_state=DATA_UNSAFE if status == FAILED else PARTIAL,
            displayed_size_state=(quotes[-1].size_evidence_state if quotes else UNAVAILABLE),
            quote_age_seconds=(
                _round((evaluated - _effective_quote_time(quotes[-1])).total_seconds())
                if quotes and _safe_quote_time(quotes[-1])
                else None
            ),
            source_identity=(quotes[-1].source_identity if quotes else None),
            spread_features=spread_features or _empty_spread_features(),
            quote_stability_features=_empty_stability_features(len(quotes)),
            volume_progress_features=_empty_volume_features(len(candles)),
            slippage_sensitivity=(),
            capability_registry_fingerprint=None,
            reason_codes=(machine_reason,),
            limitations=("FULL_CLASSIFICATION_NOT_PRODUCED",),
            input_evidence_fingerprint=evidence_fingerprint,
            policy_version=policy.policy_version,
            policy_fingerprint=policy.fingerprint,
        )
    )
    opinion = build_specialist_opinion(
        specialist_id=EXECUTION_QUALITY_SPECIALIST_ID,
        specialist_version=policy.specialist_version,
        opportunity_id=opportunity_id,
        candidate_id=candidate_id,
        setup_id=setup_id,
        trade_plan_id=trade_plan_id,
        as_of=evaluated,
        expires_at=evaluated + timedelta(seconds=policy.opinion_ttl_seconds),
        research_identity=policy.research_identity,
        policy_fingerprint=policy.fingerprint,
        evaluation_status=status,
        opinion_code=NO_OPINION if status == ABSTAINED else None,
        directional_bias=NO_DIRECTION,
        evidence_refs=references,
        feature_families=("EXECUTION_LIQUIDITY",) if references else (),
        confidence=unavailable_confidence(),
        reason_codes=(machine_reason,),
        explanation="Execution Quality did not produce a full research classification.",
        abstention_reason=common_reason if status == ABSTAINED else None,
        failure_reason=common_reason if status == FAILED else None,
    )
    packet = ExecutionQualityPacket(policy=policy, assessment=assessment, opinion=opinion)
    packet = replace(packet, fingerprint=_packet_fingerprint(packet))
    validate_packet(packet)
    return packet


def _evidence_references(
    *,
    quotes: Sequence[ExecutionQuoteObservation] = (),
    candles: Sequence[ExecutionMinuteBar] = (),
    trade_plan: IntradayPlanEvidence | None = None,
    allocation: ProviderNeutralAllocationDecision | None = None,
    broker_capabilities: BrokerCapabilityRegistry | None = None,
) -> tuple[EvidenceReference, ...]:
    values: list[EvidenceReference] = []
    for item in quotes:
        values.append(
            build_evidence_reference(
                evidence_id=item.quote_id,
                evidence_type="EXECUTABLE_QUOTE",
                source=item.source_identity,
                as_of=_effective_quote_time(item),
                fingerprint=item.fingerprint.lower(),
            )
        )
    for item in candles:
        values.append(
            build_evidence_reference(
                evidence_id=item.evidence_id,
                evidence_type="MINUTE_CANDLE",
                source=item.source_identity,
                as_of=item.timestamp,
                fingerprint=item.fingerprint.lower(),
            )
        )
    if trade_plan is not None:
        values.append(
            build_evidence_reference(
                evidence_id=f"trade-plan-{trade_plan.plan_id[:24]}",
                evidence_type="TRADE_PLAN",
                source="data-004-intraday-trade-plan",
                as_of=trade_plan.lifecycle_updated_at,
                fingerprint=trade_plan.fingerprint.lower(),
            )
        )
    if allocation is not None:
        if trade_plan is None:
            raise ExecutionQualityError(
                "Allocation evidence requires the matching TradePlan evidence."
            )
        values.append(
            build_evidence_reference(
                evidence_id=f"allocation-{allocation.fingerprint[:24].lower()}",
                evidence_type="ALLOCATION_DECISION",
                source="data-005b-provider-neutral-allocation",
                as_of=trade_plan.lifecycle_updated_at,
                fingerprint=allocation.fingerprint.lower(),
            )
        )
    if broker_capabilities is not None:
        if not quotes:
            raise ExecutionQualityError(
                "Capability evidence requires contemporaneous quote evidence."
            )
        as_of = quotes[-1].receipt_time
        values.append(
            build_evidence_reference(
                evidence_id=f"broker-capabilities-{broker_capabilities.fingerprint[:24].lower()}",
                evidence_type="BROKER_CAPABILITIES",
                source="provider-neutral-capability-registry",
                as_of=as_of,
                fingerprint=broker_capabilities.fingerprint.lower(),
            )
        )
    return tuple(values)


def _safe_quote_reference(item: ExecutionQuoteObservation, evaluated: datetime) -> bool:
    try:
        return (
            item.fingerprint == _fingerprint(asdict(replace(item, fingerprint="")))
            and _effective_quote_time(item) <= evaluated
        )
    except (ExecutionQualityError, TypeError, ValueError):
        return False


def _unique_by_identity(values, *, identity):
    result = []
    seen = set()
    for item in values:
        key = identity(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result)


def _safe_candle_reference(item: ExecutionMinuteBar, evaluated: datetime) -> bool:
    try:
        return (
            item.fingerprint == _fingerprint(asdict(replace(item, fingerprint="")))
            and _parse_time(item.timestamp) <= evaluated
        )
    except (ExecutionQualityError, TypeError, ValueError):
        return False


def _safe_quote_time(item: ExecutionQuoteObservation) -> bool:
    try:
        _effective_quote_time(item)
        return True
    except (ExecutionQualityError, TypeError, ValueError):
        return False


def _effective_quote_time(item: ExecutionQuoteObservation) -> datetime:
    return min(
        _parse_time(item.provider_quote_time),
        _parse_time(item.provider_bid_time),
        _parse_time(item.provider_ask_time),
    )


def _heuristic_confidence(assessment: ExecutionQualityAssessment) -> float:
    known = sum(
        item != UNKNOWN
        for item in (
            assessment.liquidity_state,
            assessment.spread_state,
            assessment.quote_stability_state,
            assessment.price_impact_risk_state,
            assessment.fill_risk_state,
        )
    )
    return _round(known / 5) or 0.0


def _assessment_id(
    *,
    opportunity_id: str,
    evaluated: datetime,
    policy: ExecutionQualityPolicy,
    input_evidence_fingerprint: str,
) -> str:
    return _fingerprint(
        {
            "opportunityId": opportunity_id,
            "evaluatedAt": _iso(evaluated),
            "policyFingerprint": policy.fingerprint,
            "inputEvidenceFingerprint": input_evidence_fingerprint,
        }
    )


def _with_assessment_fingerprint(
    value: ExecutionQualityAssessment,
) -> ExecutionQualityAssessment:
    return replace(value, fingerprint=_assessment_fingerprint(value))


def _assessment_fingerprint(value: ExecutionQualityAssessment) -> str:
    return _fingerprint(asdict(replace(value, fingerprint="")))


def _packet_fingerprint(value: ExecutionQualityPacket) -> str:
    return _fingerprint(_packet_wire(replace(value, fingerprint="")))


def _packet_wire(value: ExecutionQualityPacket) -> dict[str, object]:
    return {
        "schemaVersion": value.schema_version,
        "profile": value.profile,
        "evidenceDomain": value.evidence_domain,
        "policy": asdict(value.policy),
        "assessment": asdict(value.assessment),
        "opinion": opinion_to_wire(value.opinion),
        "fingerprint": value.fingerprint,
    }


def _research_record_wire(value: ExecutionQualityResearchRecord) -> dict[str, object]:
    return {
        "originalPacket": _packet_wire(value.original_packet),
        "observedResult": asdict(value.observed_result),
        "observedMetrics": asdict(value.observed_metrics),
        "originalOpinionId": value.original_opinion_id,
        "originalOpinionFingerprint": value.original_opinion_fingerprint,
        "fingerprint": value.fingerprint,
    }


def _result_identity_payload(value: ObservedProviderExecutionResult) -> dict[str, object]:
    payload = asdict(value)
    payload.pop("result_id", None)
    payload.pop("fingerprint", None)
    return payload


def _evidence_fingerprint(references: Iterable[EvidenceReference]) -> str:
    return input_evidence_fingerprint(references)


def _empty_spread_features() -> SpreadFeatures:
    return SpreadFeatures(*(None,) * 12)


def _empty_stability_features(count: int = 0) -> QuoteStabilityFeatures:
    return QuoteStabilityFeatures(count, *(None,) * 9)


def _empty_volume_features(count: int = 0) -> VolumeProgressFeatures:
    return VolumeProgressFeatures(count, 0, *(None,) * 9)


def _parse_time(value: str) -> datetime:
    try:
        return _aware(datetime.fromisoformat(value), "Timestamp")
    except (TypeError, ValueError) as exc:
        raise ExecutionQualityError("Timestamp is malformed or timezone-naive.") from exc


def _aware(value: datetime | str, label: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ExecutionQualityError(f"{label} is malformed.") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionQualityError(f"{label} must include a UTC offset.")
    return value.astimezone(timezone.utc)


def _optional_time(value: datetime | str | None, label: str) -> str | None:
    return _iso(_aware(value, label)) if value is not None else None


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _symbol(value: object) -> str:
    text = str(value).strip().upper()
    if not text or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", text):
        raise ExecutionQualityError("Symbol identity is invalid.")
    return text


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise ExecutionQualityError(f"{label} is invalid.")
    return value.strip()


def _optional_identifier(value: object | None, label: str) -> str | None:
    return _identifier(value, label) if value is not None else None


def _token(value: object, label: str) -> str:
    text = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", text):
        raise ExecutionQualityError(f"{label} is invalid.")
    return text


def _sha256(value: object, label: str) -> str:
    text = str(value).strip().lower()
    if not _SHA256.fullmatch(text):
        raise ExecutionQualityError(f"{label} is invalid.")
    return text


def _optional_sha256(value: object | None, label: str) -> str | None:
    return _sha256(value, label) if value is not None else None


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExecutionQualityError(f"{label} must be numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise ExecutionQualityError(f"{label} must be finite.")
    return result


def _optional_number(value: object | None) -> float | None:
    return _number(value, "Optional numeric evidence") if value is not None else None


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ExecutionQualityError(f"{label} must be boolean.")
    return value


def _positive(value: object | None) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return _round(numerator / denominator)


def _ratio_pct(numerator: float | None, denominator: float | None) -> float | None:
    ratio = _ratio(numerator, denominator)
    return _round(ratio * 100) if ratio is not None else None


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 10)


def _sign(value: float) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()
