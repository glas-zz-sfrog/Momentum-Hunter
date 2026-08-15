"""Provider-neutral event-shock and market-reaction research specialist.

The evaluator consumes caller-supplied CONTINUOUS-003 catalyst/macro evidence
and canonical minute bars. It cannot fetch news or prices, persist evidence,
select a candidate, build a TradePlan, or contact an account, broker, order,
service, scheduler, Engine Host, or UI surface.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Mapping, Sequence

from momentum_hunter.catalyst_evidence import (
    CURRENT as CATALYST_CURRENT,
    CatalystEvidenceSnapshot,
    validate_snapshot as validate_catalyst_snapshot,
)
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_SUPPORTED,
    CUSTOMER_SUPPLIER,
    DIRECT_ISSUER,
    MACRO as CATALYST_MACRO,
    PEER,
    SECTOR as CATALYST_SECTOR,
    UNRESOLVED as CATALYST_UNRESOLVED,
)
from momentum_hunter.macro_event_context import (
    EventRiskContext as MacroEventRiskContext,
    validate_context as validate_macro_context,
)
from momentum_hunter.rolling_market_regime import RegimeBar, validate_bar
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
    validate_evidence_reference,
    validate_specialist_opinion,
)


EVENT_SHOCK_SCHEMA_VERSION = 1
EVENT_SHOCK_PROFILE = "event-shock-reaction-research-packet-v1"
EVENT_SHOCK_SPECIALIST_ID = "EVENT_SHOCK"
EVENT_SHOCK_SPECIALIST_VERSION = "event-shock-reaction-research-v1"
RESEARCH_HEURISTIC = "RESEARCH_HEURISTIC"

SUPPLY_DISRUPTION = "SUPPLY_DISRUPTION"
INDUSTRIAL_INCIDENT = "INDUSTRIAL_INCIDENT"
GEOPOLITICAL_ESCALATION = "GEOPOLITICAL_ESCALATION"
CYBER_INCIDENT = "CYBER_INCIDENT"
UNEXPECTED_REGULATION = "UNEXPECTED_REGULATION"
MATERIAL_CORPORATE_EVENT = "MATERIAL_CORPORATE_EVENT"
APPROVED_OTHER_SHOCK = "APPROVED_OTHER_SHOCK"
EVENT_CATEGORIES = frozenset(
    {
        SUPPLY_DISRUPTION,
        INDUSTRIAL_INCIDENT,
        GEOPOLITICAL_ESCALATION,
        CYBER_INCIDENT,
        UNEXPECTED_REGULATION,
        MATERIAL_CORPORATE_EVENT,
        APPROVED_OTHER_SHOCK,
    }
)

COMPETITOR = "COMPETITOR"
SUPPLIER_CUSTOMER = "SUPPLIER_CUSTOMER"
SECTOR = "SECTOR"
COMMODITY = "COMMODITY"
MACRO = "MACRO"
UNRESOLVED = "UNRESOLVED"
RELATIONSHIP_TYPES = frozenset(
    {
        DIRECT_ISSUER,
        COMPETITOR,
        SUPPLIER_CUSTOMER,
        SECTOR,
        COMMODITY,
        MACRO,
        UNRESOLVED,
    }
)
_CATALYST_RELATIONSHIP_MAP = {
    DIRECT_ISSUER: DIRECT_ISSUER,
    PEER: COMPETITOR,
    CUSTOMER_SUPPLIER: SUPPLIER_CUSTOMER,
    CATALYST_SECTOR: SECTOR,
    CATALYST_MACRO: MACRO,
    CATALYST_UNRESOLVED: UNRESOLVED,
}

EXPECTED_UP = "EXPECTED_UP"
EXPECTED_DOWN = "EXPECTED_DOWN"
EXPECTED_NON_DIRECTIONAL = "EXPECTED_NON_DIRECTIONAL"
EXPECTED_DIRECTIONS = frozenset(
    {EXPECTED_UP, EXPECTED_DOWN, EXPECTED_NON_DIRECTIONAL}
)

DIRECT_RELEVANCE = "DIRECT_RELEVANCE"
INDIRECT_PROVEN_RELEVANCE = "INDIRECT_PROVEN_RELEVANCE"
MARKET_WIDE_RELEVANCE = "MARKET_WIDE_RELEVANCE"
UNRESOLVED_RELEVANCE = "UNRESOLVED_RELEVANCE"
EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
RELEVANCE_STATES = frozenset(
    {
        DIRECT_RELEVANCE,
        INDIRECT_PROVEN_RELEVANCE,
        MARKET_WIDE_RELEVANCE,
        UNRESOLVED_RELEVANCE,
        EVIDENCE_UNAVAILABLE,
    }
)

MARKET_CONFIRMED_BULLISH = "MARKET_CONFIRMED_BULLISH"
MARKET_CONFIRMED_BEARISH = "MARKET_CONFIRMED_BEARISH"
VOLATILITY_REACTION_CONFIRMED = "VOLATILITY_REACTION_CONFIRMED"
NEWS_PRICE_DISAGREEMENT = "NEWS_PRICE_DISAGREEMENT"
VOLUME_WITHOUT_PROGRESS = "VOLUME_WITHOUT_PROGRESS"
RELATIVE_LAG = "RELATIVE_LAG"
IMMEDIATE_BREAKOUT_FAILURE = "IMMEDIATE_BREAKOUT_FAILURE"
NO_MATERIAL_REACTION = "NO_MATERIAL_REACTION"
MARKET_UNCONFIRMED = "MARKET_UNCONFIRMED"
NOT_EVALUATED = "NOT_EVALUATED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
DATA_FAILURE = "DATA_FAILURE"
REACTION_STATES = frozenset(
    {
        MARKET_CONFIRMED_BULLISH,
        MARKET_CONFIRMED_BEARISH,
        VOLATILITY_REACTION_CONFIRMED,
        NEWS_PRICE_DISAGREEMENT,
        VOLUME_WITHOUT_PROGRESS,
        RELATIVE_LAG,
        IMMEDIATE_BREAKOUT_FAILURE,
        NO_MATERIAL_REACTION,
        MARKET_UNCONFIRMED,
        NOT_EVALUATED,
        INSUFFICIENT_EVIDENCE,
        DATA_FAILURE,
    }
)

CANONICAL_BAR_STATES = frozenset(
    {"RECONCILED", "CORRECTED", "HISTORY_ONLY_GAP_FILL"}
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")


class EventShockResearchError(ValueError):
    """Raised when event or reaction evidence is contradictory or unsafe."""


@dataclass(frozen=True)
class EventShockPolicy:
    policy_version: str
    specialist_version: str
    research_identity: str
    supported_horizons_minutes: tuple[int, ...]
    minimum_baseline_bars: int
    baseline_window_bars: int
    minimum_confirmation_bars: int
    maximum_reference_age_seconds: int
    maximum_completed_bar_age_seconds: int
    maximum_internal_gap_seconds: int
    confirmation_move_pct: float
    disagreement_move_pct: float
    relative_lag_pct: float
    volume_expansion_multiple: float
    low_progress_pct: float
    minimum_actual_observation_fraction: float
    immediate_breakout_failure_minutes: int
    opinion_ttl_seconds: int
    threshold_semantics: str = RESEARCH_HEURISTIC

    @property
    def fingerprint(self) -> str:
        return _fingerprint(asdict(self))


@dataclass(frozen=True)
class EventShockClassification:
    classification_id: str
    event_id: str
    revision_id: str
    catalyst_snapshot_id: str
    category: str
    expected_direction: str
    relationship_type: str
    target_symbol: str
    benchmark_symbol: str
    classified_at: str
    expected_horizon_minutes: int
    breakout_level: float | None
    classification_source: str
    catalyst_fingerprint: str
    supplemental_relationship_evidence: EvidenceReference | None
    fingerprint: str


@dataclass(frozen=True)
class EventRelevanceAssessment:
    relevance_id: str
    assessed_at: str
    event_id: str
    revision_id: str
    target_symbol: str
    category: str
    relationship_type: str
    relevance_state: str
    is_relevant: bool
    catalyst_evidence_state: str
    reason_codes: tuple[str, ...]
    classification_fingerprint: str
    catalyst_fingerprint: str
    score_authority: str = "NONE"
    can_initiate_trade: bool = False
    fingerprint: str = ""


@dataclass(frozen=True)
class ExpectedReactionHypothesis:
    hypothesis_id: str
    created_at: str
    event_id: str
    revision_id: str
    classification_id: str
    relevance_id: str
    target_symbol: str
    benchmark_symbol: str
    expected_direction: str
    horizon_minutes: int
    reference_price: float
    benchmark_reference_price: float
    breakout_level: float | None
    baseline_average_volume: float
    baseline_bar_count: int
    target_source_identity: str
    benchmark_source_identity: str
    policy_version: str
    policy_fingerprint: str
    score_authority: str = "NONE"
    can_initiate_trade: bool = False
    fingerprint: str = ""


@dataclass(frozen=True)
class EventReactionMetrics:
    window_start: str
    window_end: str
    target_reference_price: float
    benchmark_reference_price: float
    target_latest_price: float
    benchmark_latest_price: float
    target_return_pct: float
    benchmark_return_pct: float
    relative_return_pct: float
    baseline_average_volume: float
    observed_average_volume: float
    volume_expansion_multiple: float
    price_progress_pct: float
    max_favorable_excursion_pct: float
    max_adverse_excursion_pct: float
    breakout_crossed: bool
    breakout_failed: bool
    immediate_breakout_failure: bool
    target_bar_count: int
    benchmark_bar_count: int
    expected_bar_count: int
    observation_fraction: float


@dataclass(frozen=True)
class MarketReactionAssessment:
    assessment_id: str
    evaluated_at: str
    hypothesis_id: str
    reaction_state: str
    reason_codes: tuple[str, ...]
    metrics: EventReactionMetrics | None
    input_evidence_fingerprint: str
    score_authority: str = "NONE"
    can_initiate_trade: bool = False
    fingerprint: str = ""


@dataclass(frozen=True)
class EventShockPacket:
    policy: EventShockPolicy
    classification: EventShockClassification
    relevance: EventRelevanceAssessment
    hypothesis: ExpectedReactionHypothesis | None
    confirmation: MarketReactionAssessment
    opinion: SpecialistOpinion
    packet_id: str
    fingerprint: str
    schema_version: int = EVENT_SHOCK_SCHEMA_VERSION
    profile: str = EVENT_SHOCK_PROFILE


@dataclass(frozen=True)
class ActualReactionOutcome:
    outcome_id: str
    observed_at: str
    hypothesis_id: str
    packet_fingerprint: str
    reaction_state: str
    reason_codes: tuple[str, ...]
    metrics: EventReactionMetrics | None
    input_evidence_fingerprint: str
    score_authority: str = "NONE"
    can_initiate_trade: bool = False
    fingerprint: str = ""


@dataclass(frozen=True)
class EventShockResearchRecord:
    packet: EventShockPacket
    actual_reaction: ActualReactionOutcome | None
    fingerprint: str


def default_event_shock_policy() -> EventShockPolicy:
    policy = EventShockPolicy(
        policy_version="event-shock-policy-v1",
        specialist_version=EVENT_SHOCK_SPECIALIST_VERSION,
        research_identity="event-shock-research-v1",
        supported_horizons_minutes=(5, 15, 30, 60),
        minimum_baseline_bars=10,
        baseline_window_bars=20,
        minimum_confirmation_bars=2,
        maximum_reference_age_seconds=120,
        maximum_completed_bar_age_seconds=120,
        maximum_internal_gap_seconds=180,
        confirmation_move_pct=0.25,
        disagreement_move_pct=0.20,
        relative_lag_pct=0.20,
        volume_expansion_multiple=1.75,
        low_progress_pct=0.10,
        minimum_actual_observation_fraction=0.80,
        immediate_breakout_failure_minutes=5,
        opinion_ttl_seconds=300,
    )
    validate_policy(policy)
    return policy


def build_event_shock_classification(
    *,
    catalyst: CatalystEvidenceSnapshot,
    category: str,
    expected_direction: str,
    benchmark_symbol: str,
    classified_at: datetime,
    expected_horizon_minutes: int,
    breakout_level: float | None = None,
    relationship_type: str | None = None,
    supplemental_relationship_evidence: EvidenceReference | None = None,
    classification_source: str = "event-shock-classifier-v1",
) -> EventShockClassification:
    validate_catalyst_snapshot(catalyst)
    classified = _aware(classified_at, "Classification timestamp")
    catalyst_as_of = _parse_timestamp(catalyst.evaluated_at, "Catalyst snapshot time")
    if catalyst_as_of > classified:
        raise EventShockResearchError(
            "Event classification cannot consume a future catalyst snapshot."
        )
    normalized_category = _token(category, "Event category")
    if normalized_category not in EVENT_CATEGORIES:
        raise EventShockResearchError("Event category is unsupported.")
    direction = _token(expected_direction, "Expected direction")
    if direction not in EXPECTED_DIRECTIONS:
        raise EventShockResearchError("Expected reaction direction is unsupported.")
    mapped_relationship = _CATALYST_RELATIONSHIP_MAP.get(catalyst.relationship_type)
    if mapped_relationship is None:
        raise EventShockResearchError("Catalyst relationship is unsupported.")
    relationship = (
        _token(relationship_type, "Event relationship")
        if relationship_type is not None
        else mapped_relationship
    )
    if relationship not in RELATIONSHIP_TYPES:
        raise EventShockResearchError("Event relationship is unsupported.")
    if relationship == COMMODITY:
        if supplemental_relationship_evidence is None:
            raise EventShockResearchError(
                "Commodity relationship requires explicit supplemental evidence."
            )
        validate_evidence_reference(supplemental_relationship_evidence)
        if _parse_timestamp(
            supplemental_relationship_evidence.as_of,
            "Supplemental relationship evidence time",
        ) > classified:
            raise EventShockResearchError(
                "Commodity relationship consumed future evidence."
            )
    elif relationship != mapped_relationship:
        raise EventShockResearchError(
            "Event relationship contradicts canonical catalyst attribution."
        )
    elif supplemental_relationship_evidence is not None:
        raise EventShockResearchError(
            "Supplemental relationship evidence is reserved for commodity exposure."
        )
    if type(expected_horizon_minutes) is not int or expected_horizon_minutes <= 0:
        raise EventShockResearchError("Expected reaction horizon is invalid.")
    normalized_breakout = (
        _positive(breakout_level, "Breakout level")
        if breakout_level is not None
        else None
    )
    payload = {
        "event_id": _sha256(catalyst.event_id, "Catalyst event identity"),
        "revision_id": _sha256(catalyst.revision_id, "Catalyst revision identity"),
        "catalyst_snapshot_id": _identifier(
            catalyst.snapshot_id, "Catalyst snapshot identity"
        ),
        "category": normalized_category,
        "expected_direction": direction,
        "relationship_type": relationship,
        "target_symbol": _symbol(catalyst.candidate_symbol, "Target symbol"),
        "benchmark_symbol": _symbol(benchmark_symbol, "Benchmark symbol"),
        "classified_at": _iso(classified),
        "expected_horizon_minutes": expected_horizon_minutes,
        "breakout_level": normalized_breakout,
        "classification_source": _identifier(
            classification_source, "Classification source"
        ),
        "catalyst_fingerprint": _sha256(
            catalyst.fingerprint, "Catalyst fingerprint"
        ),
        "supplemental_relationship_evidence": supplemental_relationship_evidence,
    }
    fingerprint = _fingerprint(_wire(payload))
    classification = EventShockClassification(
        classification_id=f"event-classification-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )
    validate_classification(classification)
    return classification


def evaluate_event_shock_specialist(
    *,
    catalyst: CatalystEvidenceSnapshot,
    classification: EventShockClassification,
    target_bars: Sequence[RegimeBar],
    benchmark_bars: Sequence[RegimeBar],
    evaluated_at: datetime,
    opportunity_id: str,
    candidate_id: str | None,
    setup_id: str | None = None,
    trade_plan_id: str | None = None,
    macro_context: MacroEventRiskContext | None = None,
    policy: EventShockPolicy | None = None,
) -> EventShockPacket:
    current_policy = policy or default_event_shock_policy()
    validate_policy(current_policy)
    validate_catalyst_snapshot(catalyst)
    validate_classification(classification)
    _validate_classification_binding(classification, catalyst, current_policy)
    evaluated = _aware(evaluated_at, "Evaluation timestamp")
    classified = _parse_timestamp(classification.classified_at, "Classification time")
    if evaluated < classified:
        raise EventShockResearchError("Evaluation precedes event classification.")
    opportunity = _sha256(opportunity_id, "Opportunity identity")
    macro_reference = _macro_reference(macro_context, opportunity, evaluated)
    relevance = _event_relevance(catalyst, classification)
    base_references = _base_evidence_references(
        catalyst, classification, macro_reference
    )

    if not relevance.is_relevant:
        stale = catalyst.evidence_state != CATALYST_CURRENT
        return _terminal_packet(
            policy=current_policy,
            classification=classification,
            relevance=relevance,
            hypothesis=None,
            confirmation=_empty_confirmation(
                evaluated=evaluated,
                state=NOT_EVALUATED,
                reasons=relevance.reason_codes,
            ),
            opportunity_id=opportunity,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            evidence_refs=base_references,
            evaluation_status=ABSTAINED,
            abstention_reason="STALE_EVIDENCE" if stale else "DATA_BASIS_UNCERTAIN",
            failure_reason=None,
        )

    if not target_bars or not benchmark_bars:
        return _terminal_packet(
            policy=current_policy,
            classification=classification,
            relevance=relevance,
            hypothesis=None,
            confirmation=_empty_confirmation(
                evaluated=evaluated,
                state=INSUFFICIENT_EVIDENCE,
                reasons=("MARKET_EVIDENCE_MISSING",),
            ),
            opportunity_id=opportunity,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            evidence_refs=base_references,
            evaluation_status=ABSTAINED,
            abstention_reason="INSUFFICIENT_EVIDENCE",
            failure_reason=None,
        )

    try:
        target = _normalized_bars(
            target_bars,
            classification.target_symbol,
            cutoff=evaluated,
            maximum_internal_gap_seconds=current_policy.maximum_internal_gap_seconds,
        )
        benchmark = _normalized_bars(
            benchmark_bars,
            classification.benchmark_symbol,
            cutoff=evaluated,
            maximum_internal_gap_seconds=current_policy.maximum_internal_gap_seconds,
        )
    except EventShockResearchError as exc:
        return _terminal_packet(
            policy=current_policy,
            classification=classification,
            relevance=relevance,
            hypothesis=None,
            confirmation=_empty_confirmation(
                evaluated=evaluated,
                state=DATA_FAILURE,
                reasons=("MARKET_EVIDENCE_INVALID",),
            ),
            opportunity_id=opportunity,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            evidence_refs=base_references,
            evaluation_status=FAILED,
            abstention_reason=None,
            failure_reason="MARKET_EVIDENCE_INVALID",
            explanation=str(exc),
        )

    target_baseline = _completed_at_or_before(target, classified)[
        -current_policy.baseline_window_bars :
    ]
    benchmark_baseline = _completed_at_or_before(benchmark, classified)[
        -current_policy.baseline_window_bars :
    ]
    if (
        len(target_baseline) < current_policy.minimum_baseline_bars
        or len(benchmark_baseline) < current_policy.minimum_baseline_bars
    ):
        references = (*base_references, *_bar_set_references(target, benchmark, evaluated))
        return _terminal_packet(
            policy=current_policy,
            classification=classification,
            relevance=relevance,
            hypothesis=None,
            confirmation=_empty_confirmation(
                evaluated=evaluated,
                state=INSUFFICIENT_EVIDENCE,
                reasons=("BASELINE_INSUFFICIENT",),
            ),
            opportunity_id=opportunity,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            evidence_refs=references,
            evaluation_status=ABSTAINED,
            abstention_reason="INSUFFICIENT_EVIDENCE",
            failure_reason=None,
        )

    reference_target = target_baseline[-1]
    reference_benchmark = benchmark_baseline[-1]
    if any(
        (classified - _bar_close_time(item)).total_seconds()
        > current_policy.maximum_reference_age_seconds
        for item in (reference_target, reference_benchmark)
    ):
        references = (*base_references, *_bar_set_references(target, benchmark, evaluated))
        return _terminal_packet(
            policy=current_policy,
            classification=classification,
            relevance=relevance,
            hypothesis=None,
            confirmation=_empty_confirmation(
                evaluated=evaluated,
                state=INSUFFICIENT_EVIDENCE,
                reasons=("REFERENCE_PRICE_STALE",),
            ),
            opportunity_id=opportunity,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            evidence_refs=references,
            evaluation_status=ABSTAINED,
            abstention_reason="STALE_EVIDENCE",
            failure_reason=None,
        )

    hypothesis = _hypothesis(
        classification,
        relevance,
        reference_target,
        reference_benchmark,
        target_baseline,
        current_policy,
    )
    target_observed = _completed_between(target, classified, evaluated)
    benchmark_observed = _completed_between(benchmark, classified, evaluated)
    references = (*base_references, *_bar_set_references(target, benchmark, evaluated))
    if (
        len(target_observed) < current_policy.minimum_confirmation_bars
        or len(benchmark_observed) < current_policy.minimum_confirmation_bars
    ):
        return _terminal_packet(
            policy=current_policy,
            classification=classification,
            relevance=relevance,
            hypothesis=hypothesis,
            confirmation=_empty_confirmation(
                evaluated=evaluated,
                state=INSUFFICIENT_EVIDENCE,
                reasons=("MARKET_CONFIRMATION_INSUFFICIENT",),
                hypothesis_id=hypothesis.hypothesis_id,
            ),
            opportunity_id=opportunity,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            evidence_refs=references,
            evaluation_status=ABSTAINED,
            abstention_reason="INSUFFICIENT_EVIDENCE",
            failure_reason=None,
        )
    latest_close = min(
        _bar_close_time(target_observed[-1]),
        _bar_close_time(benchmark_observed[-1]),
    )
    if (
        evaluated - latest_close
    ).total_seconds() > current_policy.maximum_completed_bar_age_seconds:
        return _terminal_packet(
            policy=current_policy,
            classification=classification,
            relevance=relevance,
            hypothesis=hypothesis,
            confirmation=_empty_confirmation(
                evaluated=evaluated,
                state=INSUFFICIENT_EVIDENCE,
                reasons=("MARKET_CONFIRMATION_STALE",),
                hypothesis_id=hypothesis.hypothesis_id,
            ),
            opportunity_id=opportunity,
            candidate_id=candidate_id,
            setup_id=setup_id,
            trade_plan_id=trade_plan_id,
            evidence_refs=references,
            evaluation_status=ABSTAINED,
            abstention_reason="STALE_EVIDENCE",
            failure_reason=None,
        )

    expected_count = max(
        current_policy.minimum_confirmation_bars,
        int((evaluated - classified).total_seconds() // 60),
    )
    metrics = _reaction_metrics(
        hypothesis,
        target_observed,
        benchmark_observed,
        expected_count=expected_count,
        immediate_failure_minutes=current_policy.immediate_breakout_failure_minutes,
    )
    state, reasons = _reaction_state(metrics, hypothesis, current_policy)
    confirmation = _reaction_assessment(
        evaluated=evaluated,
        hypothesis=hypothesis,
        state=state,
        reasons=reasons,
        metrics=metrics,
        target_bars=target_observed,
        benchmark_bars=benchmark_observed,
    )
    return _terminal_packet(
        policy=current_policy,
        classification=classification,
        relevance=relevance,
        hypothesis=hypothesis,
        confirmation=confirmation,
        opportunity_id=opportunity,
        candidate_id=candidate_id,
        setup_id=setup_id,
        trade_plan_id=trade_plan_id,
        evidence_refs=references,
        evaluation_status=EVALUATED,
        abstention_reason=None,
        failure_reason=None,
    )


def build_research_record(packet: EventShockPacket) -> EventShockResearchRecord:
    validate_packet(packet)
    record = EventShockResearchRecord(packet=packet, actual_reaction=None, fingerprint="")
    record = replace(record, fingerprint=_record_fingerprint(record))
    validate_research_record(record)
    return record


def attach_actual_reaction(
    record: EventShockResearchRecord,
    *,
    target_bars: Sequence[RegimeBar],
    benchmark_bars: Sequence[RegimeBar],
    observed_at: datetime,
) -> EventShockResearchRecord:
    validate_research_record(record)
    packet = record.packet
    hypothesis = packet.hypothesis
    if hypothesis is None:
        raise EventShockResearchError(
            "Actual reaction cannot attach without a prospective hypothesis."
        )
    observed = _aware(observed_at, "Actual-reaction observation time")
    horizon_end = _parse_timestamp(hypothesis.created_at, "Hypothesis time") + timedelta(
        minutes=hypothesis.horizon_minutes
    )
    if observed < horizon_end:
        raise EventShockResearchError(
            "Actual reaction cannot be finalized before its frozen horizon."
        )
    target = _normalized_bars(
        target_bars,
        hypothesis.target_symbol,
        cutoff=observed,
        maximum_internal_gap_seconds=packet.policy.maximum_internal_gap_seconds,
    )
    benchmark = _normalized_bars(
        benchmark_bars,
        hypothesis.benchmark_symbol,
        cutoff=observed,
        maximum_internal_gap_seconds=packet.policy.maximum_internal_gap_seconds,
    )
    window_start = _parse_timestamp(hypothesis.created_at, "Hypothesis time")
    target_window = _completed_between(target, window_start, horizon_end)
    benchmark_window = _completed_between(benchmark, window_start, horizon_end)
    expected_count = hypothesis.horizon_minutes
    input_fingerprint = _bar_input_fingerprint(target_window, benchmark_window)

    complete = (
        target_window
        and benchmark_window
        and len(target_window) / expected_count
        >= packet.policy.minimum_actual_observation_fraction
        and len(benchmark_window) / expected_count
        >= packet.policy.minimum_actual_observation_fraction
        and _bar_close_time(target_window[-1]) >= horizon_end
        and _bar_close_time(benchmark_window[-1]) >= horizon_end
    )
    if complete:
        metrics = _reaction_metrics(
            hypothesis,
            target_window,
            benchmark_window,
            expected_count=expected_count,
            immediate_failure_minutes=packet.policy.immediate_breakout_failure_minutes,
        )
        state, reasons = _reaction_state(metrics, hypothesis, packet.policy)
        if state == MARKET_UNCONFIRMED:
            state = NO_MATERIAL_REACTION
            reasons = ("FROZEN_HORIZON_ENDED_WITHOUT_MATERIAL_REACTION",)
    else:
        metrics = None
        state = DATA_FAILURE
        reasons = ("REACTION_WINDOW_INCOMPLETE",)
    payload = {
        "observed_at": _iso(observed),
        "hypothesis_id": hypothesis.hypothesis_id,
        "packet_fingerprint": packet.fingerprint,
        "reaction_state": state,
        "reason_codes": reasons,
        "metrics": metrics,
        "input_evidence_fingerprint": input_fingerprint,
    }
    fingerprint = _fingerprint(_wire(payload))
    outcome = ActualReactionOutcome(
        outcome_id=f"event-reaction-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )
    validate_actual_reaction(outcome, packet)
    if record.actual_reaction is not None:
        if record.actual_reaction == outcome:
            return record
        raise EventShockResearchError(
            "Actual reaction is write-once and cannot be replaced."
        )
    updated = EventShockResearchRecord(
        packet=packet,
        actual_reaction=outcome,
        fingerprint="",
    )
    updated = replace(updated, fingerprint=_record_fingerprint(updated))
    validate_research_record(updated)
    return updated


def packet_json_bytes(packet: EventShockPacket) -> bytes:
    validate_packet(packet)
    return _canonical_json_bytes(_packet_to_wire(packet))


def research_record_json_bytes(record: EventShockResearchRecord) -> bytes:
    validate_research_record(record)
    return _canonical_json_bytes(_record_to_wire(record))


def validate_policy(policy: EventShockPolicy) -> None:
    if not isinstance(policy, EventShockPolicy):
        raise EventShockResearchError("Event-shock policy is malformed.")
    _identifier(policy.policy_version, "Policy version")
    if policy.specialist_version != EVENT_SHOCK_SPECIALIST_VERSION:
        raise EventShockResearchError("Specialist version is unsupported.")
    _identifier(policy.research_identity, "Research identity")
    if policy.threshold_semantics != RESEARCH_HEURISTIC:
        raise EventShockResearchError("Threshold semantics must remain research-only.")
    horizons = policy.supported_horizons_minutes
    if (
        not horizons
        or tuple(sorted(set(horizons))) != horizons
        or any(type(value) is not int or value <= 0 for value in horizons)
    ):
        raise EventShockResearchError("Supported reaction horizons are invalid.")
    integers = (
        policy.minimum_baseline_bars,
        policy.baseline_window_bars,
        policy.minimum_confirmation_bars,
        policy.maximum_reference_age_seconds,
        policy.maximum_completed_bar_age_seconds,
        policy.maximum_internal_gap_seconds,
        policy.immediate_breakout_failure_minutes,
        policy.opinion_ttl_seconds,
    )
    if any(type(value) is not int or value <= 0 for value in integers):
        raise EventShockResearchError("Event-shock integer policy is invalid.")
    if policy.minimum_baseline_bars > policy.baseline_window_bars:
        raise EventShockResearchError("Minimum baseline exceeds its bounded window.")
    positives = (
        policy.confirmation_move_pct,
        policy.disagreement_move_pct,
        policy.relative_lag_pct,
        policy.volume_expansion_multiple,
        policy.low_progress_pct,
    )
    if any(not _finite(value) or float(value) <= 0 for value in positives):
        raise EventShockResearchError("Event-shock numeric policy is invalid.")
    if not _finite(policy.minimum_actual_observation_fraction) or not (
        0 < policy.minimum_actual_observation_fraction <= 1
    ):
        raise EventShockResearchError("Actual-reaction completeness policy is invalid.")


def validate_classification(classification: EventShockClassification) -> None:
    if not isinstance(classification, EventShockClassification):
        raise EventShockResearchError("Event classification is malformed.")
    _identifier(classification.classification_id, "Classification identity")
    _sha256(classification.event_id, "Event identity")
    _sha256(classification.revision_id, "Revision identity")
    _identifier(classification.catalyst_snapshot_id, "Catalyst snapshot identity")
    if classification.category not in EVENT_CATEGORIES:
        raise EventShockResearchError("Event category is unsupported.")
    if classification.expected_direction not in EXPECTED_DIRECTIONS:
        raise EventShockResearchError("Expected direction is unsupported.")
    if classification.relationship_type not in RELATIONSHIP_TYPES:
        raise EventShockResearchError("Relationship type is unsupported.")
    _symbol(classification.target_symbol, "Target symbol")
    _symbol(classification.benchmark_symbol, "Benchmark symbol")
    _parse_timestamp(classification.classified_at, "Classification timestamp")
    if (
        type(classification.expected_horizon_minutes) is not int
        or classification.expected_horizon_minutes <= 0
    ):
        raise EventShockResearchError("Reaction horizon is invalid.")
    if classification.breakout_level is not None:
        _positive(classification.breakout_level, "Breakout level")
    _identifier(classification.classification_source, "Classification source")
    _sha256(classification.catalyst_fingerprint, "Catalyst fingerprint")
    if classification.supplemental_relationship_evidence is not None:
        validate_evidence_reference(classification.supplemental_relationship_evidence)
    expected = _fingerprint(
        _wire(
            {
                key: value
                for key, value in asdict(classification).items()
                if key not in {"classification_id", "fingerprint"}
            }
        )
    )
    if classification.fingerprint != expected:
        raise EventShockResearchError("Event classification fingerprint is invalid.")
    if classification.classification_id != f"event-classification-{expected[:24]}":
        raise EventShockResearchError("Event classification identity is invalid.")


def validate_packet(packet: EventShockPacket) -> None:
    if not isinstance(packet, EventShockPacket):
        raise EventShockResearchError("Event-shock packet is malformed.")
    if packet.schema_version != EVENT_SHOCK_SCHEMA_VERSION or packet.profile != EVENT_SHOCK_PROFILE:
        raise EventShockResearchError("Event-shock packet schema is unsupported.")
    validate_policy(packet.policy)
    validate_classification(packet.classification)
    _validate_relevance(packet.relevance)
    if (
        packet.relevance.classification_fingerprint
        != packet.classification.fingerprint
        or packet.relevance.event_id != packet.classification.event_id
        or packet.relevance.revision_id != packet.classification.revision_id
        or packet.relevance.target_symbol != packet.classification.target_symbol
        or packet.relevance.category != packet.classification.category
        or packet.relevance.relationship_type
        != packet.classification.relationship_type
    ):
        raise EventShockResearchError(
            "Event relevance does not bind the packet classification."
        )
    if packet.hypothesis is not None:
        _validate_hypothesis(packet.hypothesis, packet.policy, packet.relevance)
        if (
            packet.hypothesis.classification_id
            != packet.classification.classification_id
            or packet.hypothesis.event_id != packet.classification.event_id
            or packet.hypothesis.revision_id != packet.classification.revision_id
            or packet.hypothesis.target_symbol != packet.classification.target_symbol
            or packet.hypothesis.benchmark_symbol
            != packet.classification.benchmark_symbol
            or packet.hypothesis.expected_direction
            != packet.classification.expected_direction
            or packet.hypothesis.horizon_minutes
            != packet.classification.expected_horizon_minutes
            or packet.hypothesis.breakout_level
            != packet.classification.breakout_level
        ):
            raise EventShockResearchError(
                "Expected reaction does not bind the packet classification."
            )
    _validate_reaction_assessment(packet.confirmation, packet.hypothesis)
    validate_specialist_opinion(packet.opinion)
    if packet.opinion.specialist_id != EVENT_SHOCK_SPECIALIST_ID:
        raise EventShockResearchError("Specialist identity is invalid.")
    if packet.opinion.specialist_version != packet.policy.specialist_version:
        raise EventShockResearchError("Specialist version contradicts policy.")
    if packet.opinion.policy_fingerprint != packet.policy.fingerprint:
        raise EventShockResearchError("Specialist opinion policy binding is invalid.")
    if packet.opinion.as_of != packet.confirmation.evaluated_at:
        raise EventShockResearchError("Specialist opinion time binding is invalid.")
    expected_fingerprint = _packet_fingerprint(packet)
    if packet.fingerprint != expected_fingerprint:
        raise EventShockResearchError("Event-shock packet fingerprint is invalid.")
    if packet.packet_id != f"event-shock-packet-{expected_fingerprint[:24]}":
        raise EventShockResearchError("Event-shock packet identity is invalid.")


def validate_actual_reaction(
    outcome: ActualReactionOutcome, packet: EventShockPacket
) -> None:
    validate_packet(packet)
    if packet.hypothesis is None:
        raise EventShockResearchError("Outcome has no prospective hypothesis.")
    _identifier(outcome.outcome_id, "Outcome identity")
    _parse_timestamp(outcome.observed_at, "Outcome observation time")
    if outcome.hypothesis_id != packet.hypothesis.hypothesis_id:
        raise EventShockResearchError("Outcome hypothesis identity is invalid.")
    if outcome.packet_fingerprint != packet.fingerprint:
        raise EventShockResearchError("Outcome packet identity is invalid.")
    if outcome.reaction_state not in REACTION_STATES:
        raise EventShockResearchError("Outcome reaction state is invalid.")
    if outcome.score_authority != "NONE" or outcome.can_initiate_trade:
        raise EventShockResearchError("Outcome claimed decision authority.")
    if outcome.reaction_state == DATA_FAILURE and outcome.metrics is not None:
        raise EventShockResearchError("Data failure cannot fabricate reaction metrics.")
    if outcome.reaction_state != DATA_FAILURE and outcome.metrics is None:
        raise EventShockResearchError("Reaction outcome requires metrics.")
    if outcome.metrics is not None:
        _validate_metrics(outcome.metrics)
    horizon_end = _parse_timestamp(
        packet.hypothesis.created_at, "Hypothesis time"
    ) + timedelta(minutes=packet.hypothesis.horizon_minutes)
    if _parse_timestamp(outcome.observed_at, "Outcome observation time") < horizon_end:
        raise EventShockResearchError("Outcome precedes the frozen reaction horizon.")
    _sha256(outcome.input_evidence_fingerprint, "Outcome input fingerprint")
    expected = _fingerprint(
        _wire(
            {
                key: value
                for key, value in asdict(outcome).items()
                if key not in {
                    "outcome_id",
                    "fingerprint",
                    "score_authority",
                    "can_initiate_trade",
                }
            }
        )
    )
    if outcome.fingerprint != expected:
        raise EventShockResearchError("Outcome fingerprint is invalid.")
    if outcome.outcome_id != f"event-reaction-{expected[:24]}":
        raise EventShockResearchError("Outcome identity is invalid.")


def validate_research_record(record: EventShockResearchRecord) -> None:
    if not isinstance(record, EventShockResearchRecord):
        raise EventShockResearchError("Event-shock research record is malformed.")
    validate_packet(record.packet)
    if record.actual_reaction is not None:
        validate_actual_reaction(record.actual_reaction, record.packet)
    if record.fingerprint != _record_fingerprint(record):
        raise EventShockResearchError("Research-record fingerprint is invalid.")


def _validate_classification_binding(
    classification: EventShockClassification,
    catalyst: CatalystEvidenceSnapshot,
    policy: EventShockPolicy,
) -> None:
    if classification.expected_horizon_minutes not in policy.supported_horizons_minutes:
        raise EventShockResearchError("Reaction horizon is not allowed by policy.")
    expected = (
        catalyst.event_id,
        catalyst.revision_id,
        catalyst.snapshot_id,
        catalyst.candidate_symbol,
        catalyst.fingerprint,
    )
    actual = (
        classification.event_id,
        classification.revision_id,
        classification.catalyst_snapshot_id,
        classification.target_symbol,
        classification.catalyst_fingerprint,
    )
    if actual != expected:
        raise EventShockResearchError(
            "Event classification does not bind the supplied catalyst snapshot."
        )


def _event_relevance(
    catalyst: CatalystEvidenceSnapshot,
    classification: EventShockClassification,
) -> EventRelevanceAssessment:
    if catalyst.evidence_state != CATALYST_CURRENT or (
        catalyst.effective_score_authority != CATALYST_SCORE_SUPPORTED
    ):
        state = EVIDENCE_UNAVAILABLE
        relevant = False
        reasons = ("CATALYST_EVIDENCE_UNAVAILABLE",)
    elif classification.relationship_type == UNRESOLVED:
        state = UNRESOLVED_RELEVANCE
        relevant = False
        reasons = ("RELATIONSHIP_UNRESOLVED",)
    elif classification.relationship_type == DIRECT_ISSUER:
        state = DIRECT_RELEVANCE
        relevant = True
        reasons = ("DIRECT_ISSUER_RELATIONSHIP",)
    elif classification.relationship_type in {COMPETITOR, SUPPLIER_CUSTOMER, SECTOR, COMMODITY}:
        state = INDIRECT_PROVEN_RELEVANCE
        relevant = True
        reasons = (f"{classification.relationship_type}_RELATIONSHIP",)
    else:
        state = MARKET_WIDE_RELEVANCE
        relevant = True
        reasons = ("MACRO_RELATIONSHIP",)
    payload = {
        "assessed_at": classification.classified_at,
        "event_id": classification.event_id,
        "revision_id": classification.revision_id,
        "target_symbol": classification.target_symbol,
        "category": classification.category,
        "relationship_type": classification.relationship_type,
        "relevance_state": state,
        "is_relevant": relevant,
        "catalyst_evidence_state": catalyst.evidence_state,
        "reason_codes": reasons,
        "classification_fingerprint": classification.fingerprint,
        "catalyst_fingerprint": catalyst.fingerprint,
    }
    fingerprint = _fingerprint(_wire(payload))
    assessment = EventRelevanceAssessment(
        relevance_id=f"event-relevance-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )
    _validate_relevance(assessment)
    return assessment


def _hypothesis(
    classification: EventShockClassification,
    relevance: EventRelevanceAssessment,
    target_reference: RegimeBar,
    benchmark_reference: RegimeBar,
    target_baseline: Sequence[RegimeBar],
    policy: EventShockPolicy,
) -> ExpectedReactionHypothesis:
    payload = {
        "created_at": classification.classified_at,
        "event_id": classification.event_id,
        "revision_id": classification.revision_id,
        "classification_id": classification.classification_id,
        "relevance_id": relevance.relevance_id,
        "target_symbol": classification.target_symbol,
        "benchmark_symbol": classification.benchmark_symbol,
        "expected_direction": classification.expected_direction,
        "horizon_minutes": classification.expected_horizon_minutes,
        "reference_price": float(target_reference.close),
        "benchmark_reference_price": float(benchmark_reference.close),
        "breakout_level": classification.breakout_level,
        "baseline_average_volume": float(mean(item.volume for item in target_baseline)),
        "baseline_bar_count": len(target_baseline),
        "target_source_identity": target_reference.source_identity,
        "benchmark_source_identity": benchmark_reference.source_identity,
        "policy_version": policy.policy_version,
        "policy_fingerprint": policy.fingerprint,
    }
    fingerprint = _fingerprint(_wire(payload))
    hypothesis = ExpectedReactionHypothesis(
        hypothesis_id=f"event-hypothesis-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )
    _validate_hypothesis(hypothesis, policy, relevance)
    return hypothesis


def _reaction_metrics(
    hypothesis: ExpectedReactionHypothesis,
    target_bars: Sequence[RegimeBar],
    benchmark_bars: Sequence[RegimeBar],
    *,
    expected_count: int,
    immediate_failure_minutes: int,
) -> EventReactionMetrics:
    target_latest = target_bars[-1].close
    benchmark_latest = benchmark_bars[-1].close
    target_return = round(
        _return_pct(hypothesis.reference_price, target_latest), 6
    )
    benchmark_return = round(
        _return_pct(hypothesis.benchmark_reference_price, benchmark_latest), 6
    )
    baseline_volume = round(hypothesis.baseline_average_volume, 6)
    observed_volume = round(float(mean(item.volume for item in target_bars)), 6)
    volume_multiple = round(observed_volume / baseline_volume, 6)
    crossed, failed, immediate = _breakout_state(
        target_bars,
        hypothesis,
        immediate_failure_minutes=immediate_failure_minutes,
    )
    favorable, adverse = _excursions(target_bars, hypothesis)
    return EventReactionMetrics(
        window_start=hypothesis.created_at,
        window_end=_iso(
            max(_bar_close_time(target_bars[-1]), _bar_close_time(benchmark_bars[-1]))
        ),
        target_reference_price=hypothesis.reference_price,
        benchmark_reference_price=hypothesis.benchmark_reference_price,
        target_latest_price=float(target_latest),
        benchmark_latest_price=float(benchmark_latest),
        target_return_pct=target_return,
        benchmark_return_pct=benchmark_return,
        relative_return_pct=round(target_return - benchmark_return, 6),
        baseline_average_volume=baseline_volume,
        observed_average_volume=observed_volume,
        volume_expansion_multiple=volume_multiple,
        price_progress_pct=round(abs(target_return), 6),
        max_favorable_excursion_pct=round(favorable, 6),
        max_adverse_excursion_pct=round(adverse, 6),
        breakout_crossed=crossed,
        breakout_failed=failed,
        immediate_breakout_failure=immediate,
        target_bar_count=len(target_bars),
        benchmark_bar_count=len(benchmark_bars),
        expected_bar_count=expected_count,
        observation_fraction=round(
            min(len(target_bars), len(benchmark_bars)) / expected_count, 6
        ),
    )


def _reaction_state(
    metrics: EventReactionMetrics,
    hypothesis: ExpectedReactionHypothesis,
    policy: EventShockPolicy,
) -> tuple[str, tuple[str, ...]]:
    expected = hypothesis.expected_direction
    target = metrics.target_return_pct
    relative = metrics.relative_return_pct
    if metrics.immediate_breakout_failure:
        return IMMEDIATE_BREAKOUT_FAILURE, ("BREAKOUT_CROSSED_THEN_FAILED",)
    if (
        expected == EXPECTED_UP and target <= -policy.disagreement_move_pct
    ) or (
        expected == EXPECTED_DOWN and target >= policy.disagreement_move_pct
    ):
        return NEWS_PRICE_DISAGREEMENT, ("ACTUAL_DIRECTION_OPPOSED_EXPECTATION",)
    if (
        metrics.volume_expansion_multiple >= policy.volume_expansion_multiple
        and metrics.price_progress_pct < policy.low_progress_pct
    ):
        return VOLUME_WITHOUT_PROGRESS, ("EXPANDED_VOLUME_WITHOUT_PRICE_PROGRESS",)
    if (
        expected == EXPECTED_UP and relative <= -policy.relative_lag_pct
    ) or (
        expected == EXPECTED_DOWN and relative >= policy.relative_lag_pct
    ):
        return RELATIVE_LAG, ("TARGET_LAGGED_BENCHMARK",)
    if expected == EXPECTED_UP and target >= policy.confirmation_move_pct and relative >= 0:
        return MARKET_CONFIRMED_BULLISH, ("EXPECTED_UP_REACTION_CONFIRMED",)
    if expected == EXPECTED_DOWN and target <= -policy.confirmation_move_pct and relative <= 0:
        return MARKET_CONFIRMED_BEARISH, ("EXPECTED_DOWN_REACTION_CONFIRMED",)
    if expected == EXPECTED_NON_DIRECTIONAL and (
        abs(target) >= policy.confirmation_move_pct
        and metrics.volume_expansion_multiple >= policy.volume_expansion_multiple
    ):
        return VOLATILITY_REACTION_CONFIRMED, ("NON_DIRECTIONAL_SHOCK_EXPANSION",)
    return MARKET_UNCONFIRMED, ("EXPECTED_REACTION_NOT_CONFIRMED",)


def _reaction_assessment(
    *,
    evaluated: datetime,
    hypothesis: ExpectedReactionHypothesis,
    state: str,
    reasons: tuple[str, ...],
    metrics: EventReactionMetrics,
    target_bars: Sequence[RegimeBar],
    benchmark_bars: Sequence[RegimeBar],
) -> MarketReactionAssessment:
    payload = {
        "evaluated_at": _iso(evaluated),
        "hypothesis_id": hypothesis.hypothesis_id,
        "reaction_state": state,
        "reason_codes": tuple(sorted(set(reasons))),
        "metrics": metrics,
        "input_evidence_fingerprint": _bar_input_fingerprint(
            target_bars, benchmark_bars
        ),
    }
    fingerprint = _fingerprint(_wire(payload))
    assessment = MarketReactionAssessment(
        assessment_id=f"event-market-reaction-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )
    _validate_reaction_assessment(assessment, hypothesis)
    return assessment


def _empty_confirmation(
    *,
    evaluated: datetime,
    state: str,
    reasons: tuple[str, ...],
    hypothesis_id: str = "",
) -> MarketReactionAssessment:
    payload = {
        "evaluated_at": _iso(evaluated),
        "hypothesis_id": hypothesis_id,
        "reaction_state": state,
        "reason_codes": tuple(sorted(set(reasons))),
        "metrics": None,
        "input_evidence_fingerprint": _fingerprint(
            {"domain": "event-shock-no-market-evidence-v1", "reasons": reasons}
        ),
    }
    fingerprint = _fingerprint(_wire(payload))
    return MarketReactionAssessment(
        assessment_id=f"event-market-reaction-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


def _terminal_packet(
    *,
    policy: EventShockPolicy,
    classification: EventShockClassification,
    relevance: EventRelevanceAssessment,
    hypothesis: ExpectedReactionHypothesis | None,
    confirmation: MarketReactionAssessment,
    opportunity_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    trade_plan_id: str | None,
    evidence_refs: Sequence[EvidenceReference],
    evaluation_status: str,
    abstention_reason: str | None,
    failure_reason: str | None,
    explanation: str = "",
) -> EventShockPacket:
    state = confirmation.reaction_state
    if evaluation_status == EVALUATED:
        direction = _directional_bias(state, hypothesis)
        opinion_code: str | None = state
        confidence = build_confidence(
            value=min(1.0, confirmation.metrics.observation_fraction),
            kind=HEURISTIC,
            calibration_status=UNCALIBRATED,
            sample_size=None,
            model_version=policy.specialist_version,
        )
        reasons = confirmation.reason_codes
        narrative = explanation or (
            f"Event relevance is {relevance.relevance_state}; observed market state is {state}."
        )
    elif evaluation_status == ABSTAINED:
        direction = NO_DIRECTION
        opinion_code = NO_OPINION
        confidence = unavailable_confidence()
        reasons = confirmation.reason_codes or relevance.reason_codes
        narrative = explanation or "Event-shock research abstained because required evidence was unavailable."
    else:
        direction = NO_DIRECTION
        opinion_code = None
        confidence = unavailable_confidence()
        reasons = confirmation.reason_codes
        narrative = explanation or "Event-shock research failed closed on contradictory evidence."
    features = {"CATALYST", "NEWS"}
    if hypothesis is not None:
        features.update({"PRICE_MOMENTUM", "CANDLE_STRUCTURE", "VOLUME"})
    if any(item.evidence_type == "MACRO_EVENT_CONTEXT" for item in evidence_refs):
        features.add("MARKET_REGIME")
    opinion = build_specialist_opinion(
        specialist_id=EVENT_SHOCK_SPECIALIST_ID,
        specialist_version=policy.specialist_version,
        opportunity_id=opportunity_id,
        candidate_id=candidate_id,
        setup_id=setup_id,
        trade_plan_id=trade_plan_id,
        as_of=confirmation.evaluated_at,
        expires_at=_parse_timestamp(confirmation.evaluated_at, "Confirmation time")
        + timedelta(seconds=policy.opinion_ttl_seconds),
        research_identity=policy.research_identity,
        policy_fingerprint=policy.fingerprint,
        evaluation_status=evaluation_status,
        opinion_code=opinion_code,
        directional_bias=direction,
        evidence_refs=evidence_refs,
        feature_families=features,
        confidence=confidence,
        reason_codes=reasons,
        explanation=narrative,
        abstention_reason=abstention_reason,
        failure_reason=failure_reason,
        authority=RESEARCH_ONLY,
        execution_authority=EXECUTION_AUTHORITY_NONE,
    )
    packet = EventShockPacket(
        policy=policy,
        classification=classification,
        relevance=relevance,
        hypothesis=hypothesis,
        confirmation=confirmation,
        opinion=opinion,
        packet_id="",
        fingerprint="",
    )
    fingerprint = _packet_fingerprint(packet)
    packet = replace(
        packet,
        packet_id=f"event-shock-packet-{fingerprint[:24]}",
        fingerprint=fingerprint,
    )
    validate_packet(packet)
    return packet


def _directional_bias(
    state: str, hypothesis: ExpectedReactionHypothesis | None
) -> str:
    if state == MARKET_CONFIRMED_BULLISH:
        return BULLISH
    if state == MARKET_CONFIRMED_BEARISH:
        return BEARISH
    if state == NEWS_PRICE_DISAGREEMENT and hypothesis is not None:
        return BEARISH if hypothesis.expected_direction == EXPECTED_UP else BULLISH
    if state == IMMEDIATE_BREAKOUT_FAILURE and hypothesis is not None:
        return BEARISH if hypothesis.expected_direction == EXPECTED_UP else BULLISH
    if state in {VOLUME_WITHOUT_PROGRESS, RELATIVE_LAG}:
        return NEUTRAL
    return NON_DIRECTIONAL


def _base_evidence_references(
    catalyst: CatalystEvidenceSnapshot,
    classification: EventShockClassification,
    macro_reference: EvidenceReference | None,
) -> tuple[EvidenceReference, ...]:
    references = [
        build_evidence_reference(
            evidence_id=catalyst.snapshot_id,
            evidence_type="CATALYST_SNAPSHOT",
            source=catalyst.source_identity,
            as_of=catalyst.evaluated_at,
            fingerprint=catalyst.fingerprint,
        ),
        build_evidence_reference(
            evidence_id=classification.classification_id,
            evidence_type="EVENT_CLASSIFICATION",
            source=classification.classification_source,
            as_of=classification.classified_at,
            fingerprint=classification.fingerprint,
        ),
    ]
    if classification.supplemental_relationship_evidence is not None:
        references.append(classification.supplemental_relationship_evidence)
    if macro_reference is not None:
        references.append(macro_reference)
    return tuple(references)


def _macro_reference(
    context: MacroEventRiskContext | None,
    opportunity_id: str,
    evaluated: datetime,
) -> EvidenceReference | None:
    if context is None:
        return None
    validate_macro_context(context)
    if _parse_timestamp(context.evaluated_at, "Macro context time") > evaluated:
        raise EventShockResearchError("Macro context is future evidence.")
    if context.target_opportunity_id and context.target_opportunity_id != opportunity_id:
        raise EventShockResearchError("Macro context targets another opportunity.")
    return build_evidence_reference(
        evidence_id=context.context_id,
        evidence_type="MACRO_EVENT_CONTEXT",
        source="continuous-003-macro-event-context",
        as_of=context.evaluated_at,
        fingerprint=context.fingerprint,
    )


def _bar_set_references(
    target: Sequence[RegimeBar],
    benchmark: Sequence[RegimeBar],
    evaluated: datetime,
) -> tuple[EvidenceReference, EvidenceReference]:
    return (
        _bar_set_reference(target, evaluated),
        _bar_set_reference(benchmark, evaluated),
    )


def _bar_set_reference(
    bars: Sequence[RegimeBar], evaluated: datetime
) -> EvidenceReference:
    eligible = [item for item in bars if _bar_close_time(item) <= evaluated]
    if not eligible:
        eligible = list(bars)
    fingerprint = _fingerprint([asdict(item) for item in eligible])
    return build_evidence_reference(
        evidence_id=f"event-bars-{eligible[0].symbol}-{fingerprint[:24]}",
        evidence_type="CANONICAL_BAR_SET",
        source=eligible[0].source_identity,
        as_of=_bar_close_time(eligible[-1]),
        fingerprint=fingerprint,
    )


def _normalized_bars(
    values: Sequence[RegimeBar],
    expected_symbol: str,
    *,
    cutoff: datetime,
    maximum_internal_gap_seconds: int,
) -> tuple[RegimeBar, ...]:
    if not values:
        raise EventShockResearchError("Canonical bar evidence is empty.")
    bars = tuple(sorted(values, key=lambda item: item.timestamp))
    if len({item.timestamp for item in bars}) != len(bars):
        raise EventShockResearchError("Canonical bar evidence repeats a timestamp.")
    if len({item.source_identity for item in bars}) != 1:
        raise EventShockResearchError("Canonical bars mix source identities.")
    previous: datetime | None = None
    for item in bars:
        try:
            validate_bar(item, expected_symbol=expected_symbol)
        except Exception as exc:
            raise EventShockResearchError(str(exc)) from exc
        if item.source_state not in CANONICAL_BAR_STATES:
            raise EventShockResearchError("Event research requires terminal canonical bars.")
        timestamp = _parse_timestamp(item.timestamp, "Bar timestamp")
        if _bar_close_time(item) > cutoff:
            raise EventShockResearchError("Canonical bar evidence contains future data.")
        if previous is not None and (
            timestamp - previous
        ).total_seconds() > maximum_internal_gap_seconds:
            raise EventShockResearchError("Canonical bar evidence contains an internal gap.")
        previous = timestamp
    return bars


def _completed_at_or_before(
    bars: Sequence[RegimeBar], cutoff: datetime
) -> tuple[RegimeBar, ...]:
    return tuple(item for item in bars if _bar_close_time(item) <= cutoff)


def _completed_between(
    bars: Sequence[RegimeBar], start: datetime, end: datetime
) -> tuple[RegimeBar, ...]:
    return tuple(
        item
        for item in bars
        if _parse_timestamp(item.timestamp, "Bar timestamp") >= start
        and _bar_close_time(item) <= end
    )


def _bar_close_time(bar: RegimeBar) -> datetime:
    return _parse_timestamp(bar.timestamp, "Bar timestamp") + timedelta(minutes=1)


def _breakout_state(
    bars: Sequence[RegimeBar],
    hypothesis: ExpectedReactionHypothesis,
    *,
    immediate_failure_minutes: int,
) -> tuple[bool, bool, bool]:
    level = hypothesis.breakout_level
    if level is None or hypothesis.expected_direction == EXPECTED_NON_DIRECTIONAL:
        return False, False, False
    crossed_at: int | None = None
    failed_at: int | None = None
    for index, item in enumerate(bars):
        if hypothesis.expected_direction == EXPECTED_UP:
            if crossed_at is None and item.high >= level:
                crossed_at = index
            if crossed_at is not None and item.close < level:
                failed_at = index
                break
        else:
            if crossed_at is None and item.low <= level:
                crossed_at = index
            if crossed_at is not None and item.close > level:
                failed_at = index
                break
    crossed = crossed_at is not None
    failed = failed_at is not None
    immediate = failed and failed_at is not None and failed_at < immediate_failure_minutes
    return crossed, failed, immediate


def _excursions(
    bars: Sequence[RegimeBar], hypothesis: ExpectedReactionHypothesis
) -> tuple[float, float]:
    reference = hypothesis.reference_price
    if hypothesis.expected_direction == EXPECTED_DOWN:
        favorable = (
            reference - min(item.low for item in bars)
        ) / reference * 100.0
        adverse = (
            max(item.high for item in bars) - reference
        ) / reference * 100.0
    else:
        favorable = (
            max(item.high for item in bars) - reference
        ) / reference * 100.0
        adverse = (
            reference - min(item.low for item in bars)
        ) / reference * 100.0
    return max(0.0, favorable), max(0.0, adverse)


def _validate_relevance(value: EventRelevanceAssessment) -> None:
    if value.relevance_state not in RELEVANCE_STATES:
        raise EventShockResearchError("Event relevance state is invalid.")
    if value.score_authority != "NONE" or value.can_initiate_trade:
        raise EventShockResearchError("Event relevance claimed decision authority.")
    if type(value.is_relevant) is not bool:
        raise EventShockResearchError("Event relevance flag is invalid.")
    if value.is_relevant != (
        value.relevance_state
        in {DIRECT_RELEVANCE, INDIRECT_PROVEN_RELEVANCE, MARKET_WIDE_RELEVANCE}
    ):
        raise EventShockResearchError("Event relevance flag contradicts its state.")
    expected = _fingerprint(
        _wire(
            {
                key: item
                for key, item in asdict(value).items()
                if key not in {
                    "relevance_id",
                    "fingerprint",
                    "score_authority",
                    "can_initiate_trade",
                }
            }
        )
    )
    if value.fingerprint != expected or value.relevance_id != f"event-relevance-{expected[:24]}":
        raise EventShockResearchError("Event relevance identity is invalid.")


def _validate_hypothesis(
    value: ExpectedReactionHypothesis,
    policy: EventShockPolicy,
    relevance: EventRelevanceAssessment,
) -> None:
    if value.relevance_id != relevance.relevance_id or not relevance.is_relevant:
        raise EventShockResearchError("Hypothesis lacks relevant event evidence.")
    if value.policy_fingerprint != policy.fingerprint:
        raise EventShockResearchError("Hypothesis policy fingerprint is invalid.")
    if value.score_authority != "NONE" or value.can_initiate_trade:
        raise EventShockResearchError("Hypothesis claimed decision authority.")
    if value.expected_direction not in EXPECTED_DIRECTIONS:
        raise EventShockResearchError("Hypothesis direction is invalid.")
    if value.horizon_minutes not in policy.supported_horizons_minutes:
        raise EventShockResearchError("Hypothesis horizon is invalid.")
    for number, label in (
        (value.reference_price, "Hypothesis reference price"),
        (value.benchmark_reference_price, "Hypothesis benchmark price"),
        (value.baseline_average_volume, "Hypothesis baseline volume"),
    ):
        _positive(number, label)
    if type(value.baseline_bar_count) is not int or (
        value.baseline_bar_count < policy.minimum_baseline_bars
        or value.baseline_bar_count > policy.baseline_window_bars
    ):
        raise EventShockResearchError("Hypothesis baseline count is invalid.")
    expected = _fingerprint(
        _wire(
            {
                key: item
                for key, item in asdict(value).items()
                if key not in {
                    "hypothesis_id",
                    "fingerprint",
                    "score_authority",
                    "can_initiate_trade",
                }
            }
        )
    )
    if value.fingerprint != expected or value.hypothesis_id != f"event-hypothesis-{expected[:24]}":
        raise EventShockResearchError("Expected-reaction hypothesis identity is invalid.")


def _validate_reaction_assessment(
    value: MarketReactionAssessment,
    hypothesis: ExpectedReactionHypothesis | None,
) -> None:
    if value.reaction_state not in REACTION_STATES:
        raise EventShockResearchError("Market-reaction state is invalid.")
    if value.score_authority != "NONE" or value.can_initiate_trade:
        raise EventShockResearchError("Market reaction claimed decision authority.")
    if hypothesis is None and value.hypothesis_id:
        raise EventShockResearchError("Market reaction references a missing hypothesis.")
    if hypothesis is not None and value.hypothesis_id not in {"", hypothesis.hypothesis_id}:
        raise EventShockResearchError("Market reaction references another hypothesis.")
    if value.metrics is None and value.reaction_state not in {
        NOT_EVALUATED,
        INSUFFICIENT_EVIDENCE,
        DATA_FAILURE,
    }:
        raise EventShockResearchError("Market reaction fabricated missing metrics.")
    if value.metrics is not None:
        _validate_metrics(value.metrics)
    expected = _fingerprint(
        _wire(
            {
                key: item
                for key, item in asdict(value).items()
                if key not in {
                    "assessment_id",
                    "fingerprint",
                    "score_authority",
                    "can_initiate_trade",
                }
            }
        )
    )
    if value.fingerprint != expected or value.assessment_id != f"event-market-reaction-{expected[:24]}":
        raise EventShockResearchError("Market-reaction identity is invalid.")


def _validate_metrics(value: EventReactionMetrics) -> None:
    if not isinstance(value, EventReactionMetrics):
        raise EventShockResearchError("Reaction metrics are malformed.")
    start = _parse_timestamp(value.window_start, "Reaction window start")
    end = _parse_timestamp(value.window_end, "Reaction window end")
    if end <= start:
        raise EventShockResearchError("Reaction window is invalid.")
    positives = (
        value.target_reference_price,
        value.benchmark_reference_price,
        value.target_latest_price,
        value.benchmark_latest_price,
        value.baseline_average_volume,
        value.observed_average_volume,
        value.volume_expansion_multiple,
    )
    if any(not _finite(item) or float(item) <= 0 for item in positives):
        raise EventShockResearchError("Reaction metrics contain invalid positive values.")
    finite = (
        value.target_return_pct,
        value.benchmark_return_pct,
        value.relative_return_pct,
        value.price_progress_pct,
        value.max_favorable_excursion_pct,
        value.max_adverse_excursion_pct,
        value.observation_fraction,
    )
    if any(not _finite(item) for item in finite):
        raise EventShockResearchError("Reaction metrics contain nonfinite values.")
    if any(
        type(item) is not int or item <= 0
        for item in (
            value.target_bar_count,
            value.benchmark_bar_count,
            value.expected_bar_count,
        )
    ):
        raise EventShockResearchError("Reaction bar counts are invalid.")
    expected_fraction = round(
        min(value.target_bar_count, value.benchmark_bar_count)
        / value.expected_bar_count,
        6,
    )
    if value.observation_fraction != expected_fraction:
        raise EventShockResearchError("Reaction observation fraction is invalid.")
    if value.relative_return_pct != round(
        value.target_return_pct - value.benchmark_return_pct, 6
    ):
        raise EventShockResearchError("Reaction relative return is invalid.")
    if value.price_progress_pct != round(abs(value.target_return_pct), 6):
        raise EventShockResearchError("Reaction price progress is invalid.")
    if value.volume_expansion_multiple != round(
        value.observed_average_volume / value.baseline_average_volume, 6
    ):
        raise EventShockResearchError("Reaction volume expansion is invalid.")
    if value.max_favorable_excursion_pct < 0 or value.max_adverse_excursion_pct < 0:
        raise EventShockResearchError("Reaction excursion is invalid.")
    if value.immediate_breakout_failure and not value.breakout_failed:
        raise EventShockResearchError("Immediate failure requires a failed breakout.")
    if value.breakout_failed and not value.breakout_crossed:
        raise EventShockResearchError("Failed breakout requires a prior cross.")


def _packet_fingerprint(packet: EventShockPacket) -> str:
    return _fingerprint(
        {
            "domain": EVENT_SHOCK_PROFILE,
            "policyFingerprint": packet.policy.fingerprint,
            "classificationFingerprint": packet.classification.fingerprint,
            "relevanceFingerprint": packet.relevance.fingerprint,
            "hypothesisFingerprint": packet.hypothesis.fingerprint if packet.hypothesis else None,
            "confirmationFingerprint": packet.confirmation.fingerprint,
            "opinionFingerprint": packet.opinion.fingerprint,
            "schemaVersion": packet.schema_version,
        }
    )


def _record_fingerprint(record: EventShockResearchRecord) -> str:
    return _fingerprint(
        {
            "domain": "event-shock-research-record-v1",
            "packetFingerprint": record.packet.fingerprint,
            "actualReactionFingerprint": (
                record.actual_reaction.fingerprint if record.actual_reaction else None
            ),
        }
    )


def _packet_to_wire(packet: EventShockPacket) -> dict[str, object]:
    payload = _wire(asdict(packet))
    payload["opinion"] = opinion_to_wire(packet.opinion)
    return payload


def _record_to_wire(record: EventShockResearchRecord) -> dict[str, object]:
    return {
        "packet": _packet_to_wire(record.packet),
        "actualReaction": _wire(asdict(record.actual_reaction)) if record.actual_reaction else None,
        "fingerprint": record.fingerprint,
    }


def _bar_input_fingerprint(
    target: Sequence[RegimeBar], benchmark: Sequence[RegimeBar]
) -> str:
    return _fingerprint(
        {
            "targetBars": [asdict(item) for item in target],
            "benchmarkBars": [asdict(item) for item in benchmark],
        }
    )


def _return_pct(start: float, end: float) -> float:
    return (float(end) / float(start) - 1.0) * 100.0


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _positive(value: object, label: str) -> float:
    if not _finite(value) or float(value) <= 0:
        raise EventShockResearchError(f"{label} must be finite and positive.")
    return float(value)


def _aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EventShockResearchError(f"{label} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventShockResearchError(f"{label} is invalid.") from exc
    return _aware(parsed, label)


def _iso(value: datetime) -> str:
    return _aware(value, "Timestamp").isoformat().replace("+00:00", "Z")


def _identifier(value: object, label: str) -> str:
    normalized = str(value).strip()
    if not _IDENTIFIER.fullmatch(normalized):
        raise EventShockResearchError(f"{label} is invalid.")
    return normalized


def _token(value: object, label: str) -> str:
    normalized = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", normalized):
        raise EventShockResearchError(f"{label} is invalid.")
    return normalized


def _symbol(value: object, label: str) -> str:
    normalized = str(value).strip().upper()
    if not _SYMBOL.fullmatch(normalized):
        raise EventShockResearchError(f"{label} is invalid.")
    return normalized


def _sha256(value: object, label: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise EventShockResearchError(f"{label} is invalid.")
    return normalized


def _wire(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _wire(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _wire(asdict(value))
    return value


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(_wire(payload))).hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
