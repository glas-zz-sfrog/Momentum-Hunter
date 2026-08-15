"""Deterministic, offline trade-management counterfactual research.

Actual broker evidence is an immutable control. Alternative exit paths are
research observations only and never acquire execution authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Iterable, Mapping, Sequence

from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    EVALUATED,
    FAILED,
    NO_DIRECTION,
    NO_OPINION,
    NON_DIRECTIONAL,
    EvidenceReference,
    SpecialistOpinion,
    build_evidence_reference,
    build_specialist_opinion,
    input_evidence_fingerprint,
    opinion_is_expired,
    unavailable_confidence,
    validate_opinion_target_identity,
    validate_specialist_opinion,
)


SCHEMA_VERSION = 1
SPECIALIST_ID = "EXIT_INTELLIGENCE"
SPECIALIST_VERSION = "exit-intelligence-research-v1"
RESEARCH_IDENTITY = "exit-management-research-v1"
POLICY_VERSION = "exit-management-research-v1"
RESEARCH_QUESTION = (
    "Do prospectively defined exit-management methods improve realized trade "
    "management versus the frozen actual Momentum baseline?"
)

ACTUAL_FROZEN_CONTROL = "ACTUAL_FROZEN_CONTROL"
STRUCTURAL_STOP = "STRUCTURAL_STOP"
TRAILING_STOP = "TRAILING_STOP"
TIME_STOP = "TIME_STOP"
BREAK_EVEN = "BREAK_EVEN"
PARTIAL_EXIT = "PARTIAL_EXIT"
MOMENTUM_FAILURE = "MOMENTUM_FAILURE"
REGIME_DETERIORATION = "REGIME_DETERIORATION"
COUNTERFACTUAL_METHODS = (
    STRUCTURAL_STOP,
    TRAILING_STOP,
    TIME_STOP,
    BREAK_EVEN,
    PARTIAL_EXIT,
    MOMENTUM_FAILURE,
    REGIME_DETERIORATION,
)
SUPPORTED_METHODS = (ACTUAL_FROZEN_CONTROL,) + COUNTERFACTUAL_METHODS

ACTUAL_EXECUTABLE_RESULT = "ACTUAL_EXECUTABLE_RESULT"
COUNTERFACTUAL_MARKET_PATH_RESULT = "COUNTERFACTUAL_MARKET_PATH_RESULT"
COUNTERFACTUAL_MODELED_EXECUTION_RESULT = (
    "COUNTERFACTUAL_MODELED_EXECUTION_RESULT"
)

MARKET_PATH_ONLY = "MARKET_PATH_ONLY"
EXECUTABLE_QUOTE_OBSERVED = "EXECUTABLE_QUOTE_OBSERVED"
EXISTING_FILL_MODEL_APPLIED = "EXISTING_FILL_MODEL_APPLIED"
ACTUAL_BROKER_EXECUTION = "ACTUAL_BROKER_EXECUTION"
EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
EXECUTION_EVIDENCE_STATES = frozenset(
    {
        MARKET_PATH_ONLY,
        EXECUTABLE_QUOTE_OBSERVED,
        EXISTING_FILL_MODEL_APPLIED,
        ACTUAL_BROKER_EXECUTION,
        EXECUTION_UNKNOWN,
    }
)

CREATED = "CREATED"
ACTIVE = "ACTIVE"
STOP_UPDATED = "STOP_UPDATED"
PARTIAL_SIGNAL = "PARTIAL_SIGNAL"
EXIT_SIGNAL = "EXIT_SIGNAL"
TERMINAL = "TERMINAL"
ABSTAINED_STATE = "ABSTAINED"
DATA_FAILURE = "DATA_FAILURE"
AMBIGUOUS_SAME_BAR = "AMBIGUOUS_SAME_BAR"

OPEN = "OPEN"
EXITED = "EXITED"
EXIT_SIGNALLED_EXECUTION_UNKNOWN = "EXIT_SIGNALLED_EXECUTION_UNKNOWN"
UNFILLED = "UNFILLED"
PARTIALLY_FILLED = "PARTIALLY_FILLED"
FILLED = "FILLED"

COUNTERFACTUAL_HOLD_SIGNAL = "COUNTERFACTUAL_HOLD_SIGNAL"
COUNTERFACTUAL_EXIT_SIGNAL = "COUNTERFACTUAL_EXIT_SIGNAL"
COUNTERFACTUAL_PARTIAL_EXIT_SIGNAL = "COUNTERFACTUAL_PARTIAL_EXIT_SIGNAL"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_TOKEN = re.compile(r"[A-Z][A-Z0-9_]{0,95}")
_MONEY_QUANTUM = Decimal("0.00000001")


class ExitResearchError(ValueError):
    """Raised when exit evidence is ambiguous, unsafe, or contradictory."""


@dataclass(frozen=True)
class ExitResearchPolicy:
    schema_version: int
    policy_version: str
    supported_side: str
    supported_session: str
    bar_seconds: int
    max_evidence_age_seconds: int
    trailing_reference: str
    trailing_atr_multiple: Decimal
    break_even_trigger_r: Decimal
    break_even_offset_r: Decimal
    time_stop_minutes: int
    partial_trigger: str
    partial_fraction: Decimal
    remaining_position_policy: str
    same_bar_behavior: str
    gap_behavior: str
    forced_flat_source: str
    momentum_failure_codes: tuple[str, ...]
    regime_deterioration_codes: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class ExitResearchBar:
    bar_id: str
    symbol: str
    session: str
    started_at: str
    completed_at: str
    known_at: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    atr: Decimal | None
    is_complete: bool
    evidence: EvidenceReference
    fingerprint: str


@dataclass(frozen=True)
class ActualExecutionFill:
    fill_id: str
    filled_at: str
    quantity: Decimal
    average_price: Decimal
    reason_code: str
    evidence: EvidenceReference


@dataclass(frozen=True)
class ActualTradeEvidence:
    trade_id: str
    opportunity_id: str
    opportunity_fingerprint: str
    candidate_id: str
    setup_id: str
    trade_plan_id: str
    trade_plan_fingerprint: str
    sample_identity: str
    sample_policy_fingerprint: str
    provider_environment_id: str
    symbol: str
    side: str
    session: str
    entry_order_id: str
    entry_fill_id: str | None
    entry_status: str
    actual_average_fill: Decimal | None
    actual_filled_quantity: Decimal
    actual_fill_at: str | None
    original_protective_stop: Decimal | None
    original_targets: tuple[Decimal, ...]
    forced_flat_at: str
    actual_terminal_state: str
    actual_exit_fills: tuple[ActualExecutionFill, ...]
    evidence_refs: tuple[EvidenceReference, ...]
    fingerprint: str


@dataclass(frozen=True)
class ExitResearchControl:
    control_id: str
    method: str
    trade_id: str
    actual_trade_fingerprint: str
    opportunity_id: str
    opportunity_fingerprint: str
    candidate_id: str
    setup_id: str
    trade_plan_id: str
    trade_plan_fingerprint: str
    symbol: str
    side: str
    session: str
    sample_identity: str
    sample_policy_fingerprint: str
    provider_environment_id: str
    entry_order_id: str
    entry_fill_id: str
    actual_average_fill: Decimal
    actual_filled_quantity: Decimal
    actual_fill_at: str
    original_protective_stop: Decimal
    original_targets: tuple[Decimal, ...]
    forced_flat_at: str
    original_risk_per_share: Decimal
    actual_terminal_state: str
    actual_exit_fills: tuple[ActualExecutionFill, ...]
    actual_result_domain: str
    actual_result_r: Decimal | None
    actual_result_pnl: Decimal | None
    evidence_refs: tuple[EvidenceReference, ...]
    fingerprint: str


@dataclass(frozen=True)
class StructuralStopEvidence:
    structure_id: str
    opportunity_id: str
    candidate_id: str
    setup_id: str
    trade_plan_id: str
    symbol: str
    level: Decimal
    known_at: str
    effective_at: str
    evidence: EvidenceReference
    fingerprint: str


@dataclass(frozen=True)
class ExitDecisionEvent:
    sequence: int
    event_type: str
    event_at: str
    known_at: str
    evaluated_at: str
    reference_price: Decimal | None
    quantity: Decimal | None
    reason_codes: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class ExitLeg:
    leg_id: str
    reason_code: str
    signaled_at: str
    quantity: Decimal
    reference_price: Decimal
    result_domain: str
    execution_evidence_status: str
    reference_r: Decimal | None
    reference_pnl: Decimal | None
    fingerprint: str


@dataclass(frozen=True)
class ExitCounterfactualPath:
    counterfactual_id: str
    control_id: str
    trade_id: str
    opportunity_id: str
    opportunity_fingerprint: str
    candidate_id: str
    setup_id: str
    trade_plan_id: str
    method: str
    method_version: str
    policy_fingerprint: str
    started_at: str
    evidence_cutoff: str
    entry_price: Decimal
    starting_quantity: Decimal
    evaluation_state: str
    exit_signal_state: str
    active_stop: Decimal | None
    remaining_quantity: Decimal
    terminal_state: str
    terminal_at: str | None
    market_path_outcome: str
    execution_evidence_status: str
    result_domain: str
    exit_reference_price: Decimal | None
    reference_r: Decimal | None
    reference_pnl: Decimal | None
    mfe_r: Decimal | None
    mae_r: Decimal | None
    mfe_captured_r: Decimal | None
    giveback_from_mfe_r: Decimal | None
    duration_seconds: int | None
    reason_codes: tuple[str, ...]
    events: tuple[ExitDecisionEvent, ...]
    exit_legs: tuple[ExitLeg, ...]
    evidence_refs: tuple[EvidenceReference, ...]
    fingerprint: str


@dataclass(frozen=True)
class PostExitOpportunityObservation:
    observation_id: str
    counterfactual_id: str
    observed_from: str
    observed_through: str
    max_favorable_after_exit_r: Decimal | None
    max_adverse_after_exit_r: Decimal | None
    evidence_refs: tuple[EvidenceReference, ...]
    fingerprint: str


@dataclass(frozen=True)
class ExitResearchSampleDefinition:
    sample_identity: str
    policy_fingerprint: str
    research_question: str
    comparison_methods: tuple[str, ...]
    parameter_optimization_allowed: bool
    activated: bool
    trades: int
    historical_backfill_allowed: bool
    fingerprint: str


@dataclass(frozen=True)
class ExitResearchEvaluation:
    schema_version: int
    evaluation_id: str
    research_identity: str
    specialist_id: str
    specialist_version: str
    policy_fingerprint: str
    evaluated_at: str
    evaluation_state: str
    control: ExitResearchControl | None
    paths: tuple[ExitCounterfactualPath, ...]
    opinions: tuple[SpecialistOpinion, ...]
    post_exit_observations: tuple[PostExitOpportunityObservation, ...]
    reason_codes: tuple[str, ...]
    input_evidence_fingerprint: str
    future_sample: ExitResearchSampleDefinition
    fingerprint: str


@dataclass
class _PathState:
    method: str
    control: ExitResearchControl
    policy: ExitResearchPolicy
    evaluated_at: datetime
    active_stop: Decimal | None
    remaining_quantity: Decimal
    evaluation_state: str = ACTIVE
    exit_signal_state: str = "NO_SIGNAL"
    terminal_state: str = OPEN
    terminal_at: datetime | None = None
    market_path_outcome: str = "OPEN"
    execution_status: str = MARKET_PATH_ONLY
    exit_reference_price: Decimal | None = None
    reference_r: Decimal | None = None
    reference_pnl: Decimal | None = None
    mfe: Decimal = Decimal("0")
    mae: Decimal = Decimal("0")
    reason_codes: list[str] = field(default_factory=list)
    events: list[ExitDecisionEvent] = field(default_factory=list)
    legs: list[ExitLeg] = field(default_factory=list)
    evidence: list[EvidenceReference] = field(default_factory=list)
    used_bars: list[ExitResearchBar] = field(default_factory=list)


def default_exit_research_policy() -> ExitResearchPolicy:
    policy = ExitResearchPolicy(
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        supported_side="LONG",
        supported_session="REGULAR",
        bar_seconds=60,
        max_evidence_age_seconds=180,
        trailing_reference="COMPLETED_BAR_HIGH_MINUS_ATR",
        trailing_atr_multiple=Decimal("2"),
        break_even_trigger_r=Decimal("1"),
        break_even_offset_r=Decimal("0"),
        time_stop_minutes=60,
        partial_trigger="FROZEN_TARGET_1",
        partial_fraction=Decimal("0.5"),
        remaining_position_policy="ORIGINAL_STOP_THEN_FROZEN_TARGET_2",
        same_bar_behavior=AMBIGUOUS_SAME_BAR,
        gap_behavior="EXECUTION_UNKNOWN",
        forced_flat_source="DATA004_PERSISTED_SESSION_BOUNDARY",
        momentum_failure_codes=(
            "FAILED_BREAKOUT",
            "LOWER_HIGH_BREAKDOWN",
            "MOMENTUM_FAILURE",
            "STRUCTURE_CONTRADICTS",
            "STRUCTURE_EXHAUSTED",
            "TREND_LOST",
            "VWAP_LOSS",
        ),
        regime_deterioration_codes=(
            "EXHAUSTION_RISK",
            "EXTREME_EXTENSION",
            "LATE_TREND",
            "MARKET_STRESS",
            "REGIME_DETERIORATED",
            "RISK_OFF",
            "VOLATILITY_SHOCK",
        ),
        fingerprint="",
    )
    complete = replace(policy, fingerprint=_fingerprint(policy_to_wire(policy)))
    validate_exit_research_policy(complete)
    return complete


def prospective_sample_definition(
    policy: ExitResearchPolicy | None = None,
) -> ExitResearchSampleDefinition:
    selected = policy or default_exit_research_policy()
    validate_exit_research_policy(selected)
    sample = ExitResearchSampleDefinition(
        sample_identity=RESEARCH_IDENTITY,
        policy_fingerprint=selected.fingerprint,
        research_question=RESEARCH_QUESTION,
        comparison_methods=SUPPORTED_METHODS,
        parameter_optimization_allowed=False,
        activated=False,
        trades=0,
        historical_backfill_allowed=False,
        fingerprint="",
    )
    return replace(sample, fingerprint=_fingerprint(sample_to_wire(sample)))


def build_exit_research_bar(
    *,
    bar_id: str,
    symbol: str,
    started_at: datetime | str,
    completed_at: datetime | str,
    known_at: datetime | str,
    open_price: object,
    high_price: object,
    low_price: object,
    close_price: object,
    volume: object,
    atr: object | None,
    evidence: EvidenceReference,
    session: str = "REGULAR",
    is_complete: bool = True,
) -> ExitResearchBar:
    bar = ExitResearchBar(
        bar_id=_identifier(bar_id, "Bar identity"),
        symbol=_symbol(symbol),
        session=_token(session, "Bar session"),
        started_at=_timestamp(started_at, "Bar start"),
        completed_at=_timestamp(completed_at, "Bar completion"),
        known_at=_timestamp(known_at, "Bar known-at"),
        open=_positive_decimal(open_price, "Bar open"),
        high=_positive_decimal(high_price, "Bar high"),
        low=_positive_decimal(low_price, "Bar low"),
        close=_positive_decimal(close_price, "Bar close"),
        volume=_nonnegative_decimal(volume, "Bar volume"),
        atr=(
            _positive_decimal(atr, "Bar ATR")
            if atr is not None
            else None
        ),
        is_complete=bool(is_complete),
        evidence=evidence,
        fingerprint="",
    )
    complete = replace(bar, fingerprint=_fingerprint(bar_to_wire(bar)))
    validate_exit_research_bar(complete)
    return complete


def build_actual_execution_fill(
    *,
    fill_id: str,
    filled_at: datetime | str,
    quantity: object,
    average_price: object,
    reason_code: str,
    evidence: EvidenceReference,
) -> ActualExecutionFill:
    fill = ActualExecutionFill(
        fill_id=_identifier(fill_id, "Exit fill identity"),
        filled_at=_timestamp(filled_at, "Exit fill timestamp"),
        quantity=_positive_decimal(quantity, "Exit fill quantity"),
        average_price=_positive_decimal(average_price, "Exit fill price"),
        reason_code=_token(reason_code, "Exit reason"),
        evidence=evidence,
    )
    _validate_reference(evidence)
    if _parse_time(evidence.as_of, "Exit evidence timestamp") > _parse_time(
        fill.filled_at, "Exit fill timestamp"
    ):
        raise ExitResearchError("Exit evidence cannot be known after its fill.")
    return fill


def build_actual_trade_evidence(
    *,
    trade_id: str,
    opportunity_id: str,
    opportunity_fingerprint: str,
    candidate_id: str,
    setup_id: str,
    trade_plan_id: str,
    trade_plan_fingerprint: str,
    sample_identity: str,
    sample_policy_fingerprint: str,
    provider_environment_id: str,
    symbol: str,
    entry_order_id: str,
    entry_status: str,
    actual_average_fill: object | None,
    actual_filled_quantity: object,
    actual_fill_at: datetime | str | None,
    entry_fill_id: str | None,
    original_protective_stop: object | None,
    original_targets: Iterable[object],
    forced_flat_at: datetime | str,
    actual_terminal_state: str,
    evidence_refs: Iterable[EvidenceReference],
    actual_exit_fills: Iterable[ActualExecutionFill] = (),
    side: str = "LONG",
    session: str = "REGULAR",
) -> ActualTradeEvidence:
    trade = ActualTradeEvidence(
        trade_id=_identifier(trade_id, "Trade identity"),
        opportunity_id=_sha256(opportunity_id, "Opportunity identity"),
        opportunity_fingerprint=_sha256(
            opportunity_fingerprint, "Opportunity fingerprint"
        ),
        candidate_id=_identifier(candidate_id, "Candidate identity"),
        setup_id=_sha256(setup_id, "Setup identity"),
        trade_plan_id=_sha256(trade_plan_id, "TradePlan identity"),
        trade_plan_fingerprint=_sha256(
            trade_plan_fingerprint, "TradePlan fingerprint"
        ),
        sample_identity=_identifier(sample_identity, "Sample identity"),
        sample_policy_fingerprint=_sha256(
            sample_policy_fingerprint, "Sample policy fingerprint"
        ),
        provider_environment_id=_identifier(
            provider_environment_id, "Provider environment identity"
        ),
        symbol=_symbol(symbol),
        side=_token(side, "Trade side"),
        session=_token(session, "Trade session"),
        entry_order_id=_identifier(entry_order_id, "Entry order identity"),
        entry_fill_id=(
            _identifier(entry_fill_id, "Entry fill identity")
            if entry_fill_id is not None
            else None
        ),
        entry_status=_token(entry_status, "Entry status"),
        actual_average_fill=(
            _positive_decimal(actual_average_fill, "Actual average fill")
            if actual_average_fill is not None
            else None
        ),
        actual_filled_quantity=_nonnegative_decimal(
            actual_filled_quantity, "Actual filled quantity"
        ),
        actual_fill_at=(
            _timestamp(actual_fill_at, "Actual fill timestamp")
            if actual_fill_at is not None
            else None
        ),
        original_protective_stop=(
            _positive_decimal(original_protective_stop, "Original stop")
            if original_protective_stop is not None
            else None
        ),
        original_targets=tuple(
            _positive_decimal(value, "Original target")
            for value in original_targets
        ),
        forced_flat_at=_timestamp(forced_flat_at, "Forced-flat timestamp"),
        actual_terminal_state=_token(
            actual_terminal_state, "Actual terminal state"
        ),
        actual_exit_fills=tuple(actual_exit_fills),
        evidence_refs=_canonical_references(evidence_refs),
        fingerprint="",
    )
    complete = replace(trade, fingerprint=_fingerprint(trade_to_wire(trade)))
    validate_actual_trade_evidence(complete)
    return complete


def build_structural_stop_evidence(
    *,
    structure_id: str,
    opportunity_id: str,
    candidate_id: str,
    setup_id: str,
    trade_plan_id: str,
    symbol: str,
    level: object,
    known_at: datetime | str,
    effective_at: datetime | str,
    evidence: EvidenceReference,
) -> StructuralStopEvidence:
    structure = StructuralStopEvidence(
        structure_id=_identifier(structure_id, "Structure identity"),
        opportunity_id=_sha256(opportunity_id, "Opportunity identity"),
        candidate_id=_identifier(candidate_id, "Candidate identity"),
        setup_id=_sha256(setup_id, "Setup identity"),
        trade_plan_id=_sha256(trade_plan_id, "TradePlan identity"),
        symbol=_symbol(symbol),
        level=_positive_decimal(level, "Structural stop"),
        known_at=_timestamp(known_at, "Structure known-at"),
        effective_at=_timestamp(effective_at, "Structure effective-at"),
        evidence=evidence,
        fingerprint="",
    )
    complete = replace(
        structure,
        fingerprint=_fingerprint(structural_stop_to_wire(structure)),
    )
    validate_structural_stop_evidence(complete)
    return complete


def evaluate_exit_research(
    *,
    trade: ActualTradeEvidence,
    bars: Iterable[ExitResearchBar],
    evaluated_at: datetime | str,
    structural_stop: StructuralStopEvidence | None = None,
    momentum_opinions: Iterable[SpecialistOpinion] = (),
    regime_opinions: Iterable[SpecialistOpinion] = (),
    policy: ExitResearchPolicy | None = None,
) -> ExitResearchEvaluation:
    selected_policy = policy or default_exit_research_policy()
    validate_exit_research_policy(selected_policy)
    validate_actual_trade_evidence(trade)
    cutoff = _parse_time(evaluated_at, "Evaluation timestamp")
    domain_reasons = tuple(
        reason
        for mismatch, reason in (
            (trade.side != selected_policy.supported_side, "UNSUPPORTED_SIDE"),
            (
                trade.session != selected_policy.supported_session,
                "UNSUPPORTED_SESSION",
            ),
        )
        if mismatch
    )
    if domain_reasons:
        reasons = tuple(sorted((*domain_reasons, "OUT_OF_DOMAIN")))
        opinion = _build_abstention_opinion(
            trade,
            cutoff,
            selected_policy,
            reasons=reasons,
            explanation="Actual trade is outside the frozen exit-research v1 domain.",
            abstention_reason="OUT_OF_DOMAIN",
        )
        evaluation = ExitResearchEvaluation(
            schema_version=SCHEMA_VERSION,
            evaluation_id="",
            research_identity=RESEARCH_IDENTITY,
            specialist_id=SPECIALIST_ID,
            specialist_version=SPECIALIST_VERSION,
            policy_fingerprint=selected_policy.fingerprint,
            evaluated_at=_canonical_time(cutoff),
            evaluation_state=ABSTAINED_STATE,
            control=None,
            paths=(),
            opinions=(opinion,),
            post_exit_observations=(),
            reason_codes=reasons,
            input_evidence_fingerprint=input_evidence_fingerprint(
                opinion.evidence_refs
            ),
            future_sample=prospective_sample_definition(selected_policy),
            fingerprint="",
        )
        return _complete_evaluation(evaluation)
    ordered_bars = _canonical_bars(
        bars,
        trade=trade,
        policy=selected_policy,
        evaluated_at=cutoff,
    )
    momentum = _canonical_opinions(momentum_opinions)
    regime = _canonical_opinions(regime_opinions)
    _validate_opinion_inputs(momentum, trade, cutoff, "MOMENTUM")
    _validate_opinion_inputs(regime, trade, cutoff, "REGIME")
    if structural_stop is not None:
        _validate_structure_target(structural_stop, trade, cutoff)

    input_refs = list(trade.evidence_refs)
    input_refs.extend(bar.evidence for bar in ordered_bars)
    if structural_stop is not None:
        input_refs.append(structural_stop.evidence)
    input_refs.extend(_opinion_reference(item) for item in momentum + regime)
    all_refs = _canonical_references(input_refs)
    if any(
        _parse_time(item.as_of, "Input evidence timestamp") > cutoff
        for item in all_refs
    ):
        raise ExitResearchError("Future input evidence cannot be evaluated.")

    if trade.entry_status not in {FILLED, PARTIALLY_FILLED}:
        opinion = _build_unfilled_opinion(trade, cutoff, selected_policy)
        evaluation = ExitResearchEvaluation(
            schema_version=SCHEMA_VERSION,
            evaluation_id="",
            research_identity=RESEARCH_IDENTITY,
            specialist_id=SPECIALIST_ID,
            specialist_version=SPECIALIST_VERSION,
            policy_fingerprint=selected_policy.fingerprint,
            evaluated_at=_canonical_time(cutoff),
            evaluation_state=ABSTAINED_STATE,
            control=None,
            paths=(),
            opinions=(opinion,),
            post_exit_observations=(),
            reason_codes=("ACTUAL_ENTRY_NOT_CONFIRMED", "TRADE_NOT_FILLED"),
            input_evidence_fingerprint=input_evidence_fingerprint(all_refs),
            future_sample=prospective_sample_definition(selected_policy),
            fingerprint="",
        )
        return _complete_evaluation(evaluation)

    control = _build_control(trade)
    data_failure = _bar_data_failure(
        ordered_bars, control, selected_policy, cutoff
    )
    if data_failure is not None:
        paths = tuple(
            _data_failure_path(
                method,
                control,
                selected_policy,
                cutoff,
                ordered_bars,
                data_failure,
            )
            for method in COUNTERFACTUAL_METHODS
        )
    else:
        paths = (
            _evaluate_structural(
                control, ordered_bars, selected_policy, cutoff, structural_stop
            ),
            _evaluate_trailing(control, ordered_bars, selected_policy, cutoff),
            _evaluate_time(control, ordered_bars, selected_policy, cutoff),
            _evaluate_break_even(control, ordered_bars, selected_policy, cutoff),
            _evaluate_partial(control, ordered_bars, selected_policy, cutoff),
            _evaluate_opinion_method(
                MOMENTUM_FAILURE,
                control,
                ordered_bars,
                selected_policy,
                cutoff,
                momentum,
            ),
            _evaluate_opinion_method(
                REGIME_DETERIORATION,
                control,
                ordered_bars,
                selected_policy,
                cutoff,
                regime,
            ),
        )
    opinions = tuple(
        _path_opinion(path, control, selected_policy, cutoff) for path in paths
    )
    observations = tuple(
        observation
        for path in paths
        if (
            observation := _post_exit_observation(
                path, control, ordered_bars
            )
        )
        is not None
    )
    state = (
        DATA_FAILURE
        if data_failure is not None
        else (
            TERMINAL
            if all(path.terminal_state != OPEN for path in paths)
            else ACTIVE
        )
    )
    evaluation = ExitResearchEvaluation(
        schema_version=SCHEMA_VERSION,
        evaluation_id="",
        research_identity=RESEARCH_IDENTITY,
        specialist_id=SPECIALIST_ID,
        specialist_version=SPECIALIST_VERSION,
        policy_fingerprint=selected_policy.fingerprint,
        evaluated_at=_canonical_time(cutoff),
        evaluation_state=state,
        control=control,
        paths=paths,
        opinions=opinions,
        post_exit_observations=observations,
        reason_codes=((data_failure,) if data_failure is not None else ()),
        input_evidence_fingerprint=input_evidence_fingerprint(all_refs),
        future_sample=prospective_sample_definition(selected_policy),
        fingerprint="",
    )
    return _complete_evaluation(evaluation)


def validate_exit_research_policy(policy: ExitResearchPolicy) -> None:
    if policy.schema_version != SCHEMA_VERSION:
        raise ExitResearchError("Exit research policy schema is unsupported.")
    if policy.policy_version != POLICY_VERSION:
        raise ExitResearchError("Exit research policy version is unsupported.")
    if policy.supported_side != "LONG" or policy.supported_session != "REGULAR":
        raise ExitResearchError("Exit research v1 is long regular-session only.")
    if policy.bar_seconds != 60 or policy.time_stop_minutes <= 0:
        raise ExitResearchError("Exit research cadence or time stop is invalid.")
    if policy.max_evidence_age_seconds < policy.bar_seconds:
        raise ExitResearchError("Evidence age bound is invalid.")
    if policy.trailing_atr_multiple <= 0:
        raise ExitResearchError("Trailing ATR multiple must be positive.")
    if policy.break_even_trigger_r <= 0 or policy.break_even_offset_r < 0:
        raise ExitResearchError("Break-even policy is invalid.")
    if not (Decimal("0") < policy.partial_fraction < Decimal("1")):
        raise ExitResearchError("Partial fraction must be between zero and one.")
    if tuple(sorted(set(policy.momentum_failure_codes))) != tuple(
        policy.momentum_failure_codes
    ):
        raise ExitResearchError("Momentum code vocabulary is not canonical.")
    if tuple(sorted(set(policy.regime_deterioration_codes))) != tuple(
        policy.regime_deterioration_codes
    ):
        raise ExitResearchError("Regime code vocabulary is not canonical.")
    expected = _fingerprint(policy_to_wire(replace(policy, fingerprint="")))
    if policy.fingerprint != expected:
        raise ExitResearchError("Exit research policy fingerprint is invalid.")


def validate_exit_research_bar(bar: ExitResearchBar) -> None:
    _validate_reference(bar.evidence)
    start = _parse_time(bar.started_at, "Bar start")
    completed = _parse_time(bar.completed_at, "Bar completion")
    known = _parse_time(bar.known_at, "Bar known-at")
    if completed <= start or known < completed:
        raise ExitResearchError("Bar chronology is invalid.")
    if not bar.is_complete:
        raise ExitResearchError("Forming bars cannot be used as completed evidence.")
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
        raise ExitResearchError("Bar OHLC geometry is invalid.")
    if bar.low > bar.high:
        raise ExitResearchError("Bar low exceeds bar high.")
    if _parse_time(bar.evidence.as_of, "Bar evidence time") > known:
        raise ExitResearchError("Bar evidence timestamp exceeds known-at time.")
    expected = _fingerprint(bar_to_wire(replace(bar, fingerprint="")))
    if bar.fingerprint != expected:
        raise ExitResearchError("Bar fingerprint is invalid.")


def validate_actual_trade_evidence(trade: ActualTradeEvidence) -> None:
    if trade.side not in {"LONG", "SHORT"}:
        raise ExitResearchError("Actual trade side is invalid.")
    if trade.entry_status not in {FILLED, PARTIALLY_FILLED, UNFILLED}:
        raise ExitResearchError("Actual entry status is unsupported.")
    if trade.actual_terminal_state not in {OPEN, TERMINAL}:
        raise ExitResearchError("Actual terminal state is unsupported.")
    _canonical_references(trade.evidence_refs)
    if trade.entry_status == UNFILLED:
        if (
            trade.actual_average_fill is not None
            or trade.actual_filled_quantity != 0
            or trade.actual_fill_at is not None
            or trade.entry_fill_id is not None
            or trade.actual_exit_fills
        ):
            raise ExitResearchError("Unfilled trade carries fabricated fill evidence.")
    else:
        if (
            trade.actual_average_fill is None
            or trade.actual_average_fill <= 0
            or trade.actual_filled_quantity <= 0
            or trade.actual_fill_at is None
            or trade.entry_fill_id is None
        ):
            raise ExitResearchError("Confirmed actual entry fill is incomplete.")
        entry_fill_refs = tuple(
            item
            for item in trade.evidence_refs
            if item.evidence_type == "BROKER_FILL"
            and item.evidence_id == trade.entry_fill_id
        )
        if len(entry_fill_refs) != 1:
            raise ExitResearchError(
                "Confirmed actual entry requires one exact broker-fill reference."
            )
        entry_order_refs = tuple(
            item
            for item in trade.evidence_refs
            if item.evidence_type == "BROKER_ORDER"
            and item.evidence_id == trade.entry_order_id
        )
        if len(entry_order_refs) != 1:
            raise ExitResearchError(
                "Confirmed actual entry requires one exact broker-order reference."
            )
        if trade.original_protective_stop is None:
            raise ExitResearchError("Actual trade lacks its protective stop.")
        if trade.side == "LONG":
            if trade.original_protective_stop >= trade.actual_average_fill:
                raise ExitResearchError("Long protective stop must be below actual fill.")
            if any(target <= trade.actual_average_fill for target in trade.original_targets):
                raise ExitResearchError("Long targets must be above actual fill.")
            if tuple(sorted(set(trade.original_targets))) != trade.original_targets:
                raise ExitResearchError("Original targets are not strictly ordered.")
        else:
            if trade.original_protective_stop <= trade.actual_average_fill:
                raise ExitResearchError("Short protective stop must be above actual fill.")
            if any(target >= trade.actual_average_fill for target in trade.original_targets):
                raise ExitResearchError("Short targets must be below actual fill.")
            if tuple(
                sorted(set(trade.original_targets), reverse=True)
            ) != trade.original_targets:
                raise ExitResearchError("Short targets are not strictly ordered.")
        fill_at = _parse_time(trade.actual_fill_at, "Actual fill time")
        if _parse_time(trade.forced_flat_at, "Forced-flat time") <= fill_at:
            raise ExitResearchError("Forced-flat time must follow actual fill.")
        exited = sum((fill.quantity for fill in trade.actual_exit_fills), Decimal("0"))
        if exited > trade.actual_filled_quantity:
            raise ExitResearchError("Actual exit quantity exceeds actual fill.")
        if trade.actual_terminal_state == TERMINAL and exited != trade.actual_filled_quantity:
            raise ExitResearchError("Terminal actual trade is not quantity-complete.")
        previous = fill_at
        for fill in trade.actual_exit_fills:
            current = _parse_time(fill.filled_at, "Actual exit fill time")
            if current < previous:
                raise ExitResearchError("Actual exit fills are out of order.")
            previous = current
    expected = _fingerprint(trade_to_wire(replace(trade, fingerprint="")))
    if trade.fingerprint != expected:
        raise ExitResearchError("Actual trade evidence fingerprint is invalid.")


def validate_structural_stop_evidence(structure: StructuralStopEvidence) -> None:
    _validate_reference(structure.evidence)
    known = _parse_time(structure.known_at, "Structure known-at")
    effective = _parse_time(structure.effective_at, "Structure effective-at")
    if effective < known:
        raise ExitResearchError("Structural stop cannot act before it was known.")
    if _parse_time(structure.evidence.as_of, "Structure evidence time") > known:
        raise ExitResearchError("Structural evidence timestamp exceeds known-at.")
    expected = _fingerprint(
        structural_stop_to_wire(replace(structure, fingerprint=""))
    )
    if structure.fingerprint != expected:
        raise ExitResearchError("Structural-stop fingerprint is invalid.")


def validate_counterfactual_path(path: ExitCounterfactualPath) -> None:
    if path.method not in COUNTERFACTUAL_METHODS:
        raise ExitResearchError("Counterfactual method is unsupported.")
    if path.starting_quantity <= 0 or path.remaining_quantity < 0:
        raise ExitResearchError("Counterfactual quantity is invalid.")
    if sum((leg.quantity for leg in path.exit_legs), Decimal("0")) > path.starting_quantity:
        raise ExitResearchError("Counterfactual exit quantity exceeds actual fill.")
    if path.result_domain != COUNTERFACTUAL_MARKET_PATH_RESULT:
        raise ExitResearchError("Counterfactual result domain is invalid.")
    if path.execution_evidence_status == ACTUAL_BROKER_EXECUTION:
        raise ExitResearchError("Counterfactual cannot claim actual broker execution.")
    if path.execution_evidence_status not in EXECUTION_EVIDENCE_STATES:
        raise ExitResearchError("Execution evidence status is invalid.")
    _validate_events(path.events)
    expected = _fingerprint(path_to_wire(replace(path, fingerprint="")))
    if path.fingerprint != expected:
        raise ExitResearchError("Counterfactual path fingerprint is invalid.")


def validate_exit_research_control(control: ExitResearchControl) -> None:
    if control.method != ACTUAL_FROZEN_CONTROL:
        raise ExitResearchError("Actual control method identity is invalid.")
    if control.actual_average_fill <= 0 or control.actual_filled_quantity <= 0:
        raise ExitResearchError("Actual control fill truth is invalid.")
    _sha256(control.actual_trade_fingerprint, "Actual trade fingerprint")
    _identifier(control.sample_identity, "Sample identity")
    _sha256(control.sample_policy_fingerprint, "Sample policy fingerprint")
    _identifier(control.provider_environment_id, "Provider environment identity")
    _identifier(control.entry_order_id, "Entry order identity")
    if (
        control.original_protective_stop <= 0
        or control.original_protective_stop >= control.actual_average_fill
        or control.original_risk_per_share
        != control.actual_average_fill - control.original_protective_stop
    ):
        raise ExitResearchError("Actual control 1R basis is invalid.")
    if control.actual_result_domain != ACTUAL_EXECUTABLE_RESULT:
        raise ExitResearchError("Actual control result domain is invalid.")
    expected = _fingerprint(control_to_wire(replace(control, fingerprint="")))
    if control.fingerprint != expected:
        raise ExitResearchError("Actual control fingerprint is invalid.")


def evaluation_to_wire(evaluation: ExitResearchEvaluation) -> dict[str, object]:
    return {
        "schemaVersion": evaluation.schema_version,
        "evaluationId": evaluation.evaluation_id,
        "researchIdentity": evaluation.research_identity,
        "specialistId": evaluation.specialist_id,
        "specialistVersion": evaluation.specialist_version,
        "policyFingerprint": evaluation.policy_fingerprint,
        "evaluatedAt": evaluation.evaluated_at,
        "evaluationState": evaluation.evaluation_state,
        "control": control_to_wire(evaluation.control) if evaluation.control else None,
        "paths": [path_to_wire(item) for item in evaluation.paths],
        "opinions": [
            {"opinionId": item.opinion_id, "fingerprint": item.fingerprint}
            for item in evaluation.opinions
        ],
        "postExitObservations": [
            post_exit_to_wire(item) for item in evaluation.post_exit_observations
        ],
        "reasonCodes": list(evaluation.reason_codes),
        "inputEvidenceFingerprint": evaluation.input_evidence_fingerprint,
        "futureSample": sample_to_wire(evaluation.future_sample),
        "fingerprint": evaluation.fingerprint,
    }


def evaluation_json_bytes(evaluation: ExitResearchEvaluation) -> bytes:
    return _canonical_json_bytes(evaluation_to_wire(evaluation))


def policy_to_wire(policy: ExitResearchPolicy) -> dict[str, object]:
    return {
        "schemaVersion": policy.schema_version,
        "policyVersion": policy.policy_version,
        "supportedSide": policy.supported_side,
        "supportedSession": policy.supported_session,
        "barSeconds": policy.bar_seconds,
        "maxEvidenceAgeSeconds": policy.max_evidence_age_seconds,
        "trailingReference": policy.trailing_reference,
        "trailingAtrMultiple": _decimal_wire(policy.trailing_atr_multiple),
        "breakEvenTriggerR": _decimal_wire(policy.break_even_trigger_r),
        "breakEvenOffsetR": _decimal_wire(policy.break_even_offset_r),
        "timeStopMinutes": policy.time_stop_minutes,
        "partialTrigger": policy.partial_trigger,
        "partialFraction": _decimal_wire(policy.partial_fraction),
        "remainingPositionPolicy": policy.remaining_position_policy,
        "sameBarBehavior": policy.same_bar_behavior,
        "gapBehavior": policy.gap_behavior,
        "forcedFlatSource": policy.forced_flat_source,
        "momentumFailureCodes": list(policy.momentum_failure_codes),
        "regimeDeteriorationCodes": list(policy.regime_deterioration_codes),
        "fingerprint": policy.fingerprint,
    }


def bar_to_wire(bar: ExitResearchBar) -> dict[str, object]:
    return {
        "barId": bar.bar_id,
        "symbol": bar.symbol,
        "session": bar.session,
        "startedAt": bar.started_at,
        "completedAt": bar.completed_at,
        "knownAt": bar.known_at,
        "open": _decimal_wire(bar.open),
        "high": _decimal_wire(bar.high),
        "low": _decimal_wire(bar.low),
        "close": _decimal_wire(bar.close),
        "volume": _decimal_wire(bar.volume),
        "atr": _decimal_wire(bar.atr) if bar.atr is not None else None,
        "isComplete": bar.is_complete,
        "evidence": _reference_to_wire(bar.evidence),
        "fingerprint": bar.fingerprint,
    }


def trade_to_wire(trade: ActualTradeEvidence) -> dict[str, object]:
    return {
        "tradeId": trade.trade_id,
        "opportunityId": trade.opportunity_id,
        "opportunityFingerprint": trade.opportunity_fingerprint,
        "candidateId": trade.candidate_id,
        "setupId": trade.setup_id,
        "tradePlanId": trade.trade_plan_id,
        "tradePlanFingerprint": trade.trade_plan_fingerprint,
        "sampleIdentity": trade.sample_identity,
        "samplePolicyFingerprint": trade.sample_policy_fingerprint,
        "providerEnvironmentId": trade.provider_environment_id,
        "symbol": trade.symbol,
        "side": trade.side,
        "session": trade.session,
        "entryOrderId": trade.entry_order_id,
        "entryFillId": trade.entry_fill_id,
        "entryStatus": trade.entry_status,
        "actualAverageFill": (
            _decimal_wire(trade.actual_average_fill)
            if trade.actual_average_fill is not None
            else None
        ),
        "actualFilledQuantity": _decimal_wire(trade.actual_filled_quantity),
        "actualFillAt": trade.actual_fill_at,
        "originalProtectiveStop": (
            _decimal_wire(trade.original_protective_stop)
            if trade.original_protective_stop is not None
            else None
        ),
        "originalTargets": [_decimal_wire(item) for item in trade.original_targets],
        "forcedFlatAt": trade.forced_flat_at,
        "actualTerminalState": trade.actual_terminal_state,
        "actualExitFills": [_actual_fill_to_wire(item) for item in trade.actual_exit_fills],
        "evidenceRefs": [_reference_to_wire(item) for item in trade.evidence_refs],
        "fingerprint": trade.fingerprint,
    }


def control_to_wire(control: ExitResearchControl) -> dict[str, object]:
    return {
        "controlId": control.control_id,
        "method": control.method,
        "tradeId": control.trade_id,
        "actualTradeFingerprint": control.actual_trade_fingerprint,
        "opportunityId": control.opportunity_id,
        "opportunityFingerprint": control.opportunity_fingerprint,
        "candidateId": control.candidate_id,
        "setupId": control.setup_id,
        "tradePlanId": control.trade_plan_id,
        "tradePlanFingerprint": control.trade_plan_fingerprint,
        "symbol": control.symbol,
        "side": control.side,
        "session": control.session,
        "sampleIdentity": control.sample_identity,
        "samplePolicyFingerprint": control.sample_policy_fingerprint,
        "providerEnvironmentId": control.provider_environment_id,
        "entryOrderId": control.entry_order_id,
        "entryFillId": control.entry_fill_id,
        "actualAverageFill": _decimal_wire(control.actual_average_fill),
        "actualFilledQuantity": _decimal_wire(control.actual_filled_quantity),
        "actualFillAt": control.actual_fill_at,
        "originalProtectiveStop": _decimal_wire(control.original_protective_stop),
        "originalTargets": [_decimal_wire(item) for item in control.original_targets],
        "forcedFlatAt": control.forced_flat_at,
        "originalRiskPerShare": _decimal_wire(control.original_risk_per_share),
        "actualTerminalState": control.actual_terminal_state,
        "actualExitFills": [_actual_fill_to_wire(item) for item in control.actual_exit_fills],
        "actualResultDomain": control.actual_result_domain,
        "actualResultR": _optional_decimal_wire(control.actual_result_r),
        "actualResultPnl": _optional_decimal_wire(control.actual_result_pnl),
        "evidenceRefs": [_reference_to_wire(item) for item in control.evidence_refs],
        "fingerprint": control.fingerprint,
    }


def structural_stop_to_wire(structure: StructuralStopEvidence) -> dict[str, object]:
    return {
        "structureId": structure.structure_id,
        "opportunityId": structure.opportunity_id,
        "candidateId": structure.candidate_id,
        "setupId": structure.setup_id,
        "tradePlanId": structure.trade_plan_id,
        "symbol": structure.symbol,
        "level": _decimal_wire(structure.level),
        "knownAt": structure.known_at,
        "effectiveAt": structure.effective_at,
        "evidence": _reference_to_wire(structure.evidence),
        "fingerprint": structure.fingerprint,
    }


def path_to_wire(path: ExitCounterfactualPath) -> dict[str, object]:
    return {
        "counterfactualId": path.counterfactual_id,
        "controlId": path.control_id,
        "tradeId": path.trade_id,
        "opportunityId": path.opportunity_id,
        "opportunityFingerprint": path.opportunity_fingerprint,
        "candidateId": path.candidate_id,
        "setupId": path.setup_id,
        "tradePlanId": path.trade_plan_id,
        "method": path.method,
        "methodVersion": path.method_version,
        "policyFingerprint": path.policy_fingerprint,
        "startedAt": path.started_at,
        "evidenceCutoff": path.evidence_cutoff,
        "entryPrice": _decimal_wire(path.entry_price),
        "startingQuantity": _decimal_wire(path.starting_quantity),
        "evaluationState": path.evaluation_state,
        "exitSignalState": path.exit_signal_state,
        "activeStop": _optional_decimal_wire(path.active_stop),
        "remainingQuantity": _decimal_wire(path.remaining_quantity),
        "terminalState": path.terminal_state,
        "terminalAt": path.terminal_at,
        "marketPathOutcome": path.market_path_outcome,
        "executionEvidenceStatus": path.execution_evidence_status,
        "resultDomain": path.result_domain,
        "exitReferencePrice": _optional_decimal_wire(path.exit_reference_price),
        "referenceR": _optional_decimal_wire(path.reference_r),
        "referencePnl": _optional_decimal_wire(path.reference_pnl),
        "mfeR": _optional_decimal_wire(path.mfe_r),
        "maeR": _optional_decimal_wire(path.mae_r),
        "mfeCapturedR": _optional_decimal_wire(path.mfe_captured_r),
        "givebackFromMfeR": _optional_decimal_wire(path.giveback_from_mfe_r),
        "durationSeconds": path.duration_seconds,
        "reasonCodes": list(path.reason_codes),
        "events": [_event_to_wire(item) for item in path.events],
        "exitLegs": [_leg_to_wire(item) for item in path.exit_legs],
        "evidenceRefs": [_reference_to_wire(item) for item in path.evidence_refs],
        "fingerprint": path.fingerprint,
    }


def post_exit_to_wire(observation: PostExitOpportunityObservation) -> dict[str, object]:
    return {
        "observationId": observation.observation_id,
        "counterfactualId": observation.counterfactual_id,
        "observedFrom": observation.observed_from,
        "observedThrough": observation.observed_through,
        "maxFavorableAfterExitR": _optional_decimal_wire(
            observation.max_favorable_after_exit_r
        ),
        "maxAdverseAfterExitR": _optional_decimal_wire(
            observation.max_adverse_after_exit_r
        ),
        "evidenceRefs": [_reference_to_wire(item) for item in observation.evidence_refs],
        "fingerprint": observation.fingerprint,
    }


def sample_to_wire(sample: ExitResearchSampleDefinition) -> dict[str, object]:
    return {
        "sampleIdentity": sample.sample_identity,
        "policyFingerprint": sample.policy_fingerprint,
        "researchQuestion": sample.research_question,
        "comparisonMethods": list(sample.comparison_methods),
        "parameterOptimizationAllowed": sample.parameter_optimization_allowed,
        "activated": sample.activated,
        "trades": sample.trades,
        "historicalBackfillAllowed": sample.historical_backfill_allowed,
        "fingerprint": sample.fingerprint,
    }


def _build_control(trade: ActualTradeEvidence) -> ExitResearchControl:
    validate_actual_trade_evidence(trade)
    assert trade.actual_average_fill is not None
    assert trade.actual_fill_at is not None
    assert trade.entry_fill_id is not None
    assert trade.original_protective_stop is not None
    one_r = trade.actual_average_fill - trade.original_protective_stop
    actual_pnl: Decimal | None = None
    actual_r: Decimal | None = None
    if trade.actual_terminal_state == TERMINAL:
        actual_pnl = sum(
            (
                (fill.average_price - trade.actual_average_fill) * fill.quantity
                for fill in trade.actual_exit_fills
            ),
            Decimal("0"),
        )
        actual_r = actual_pnl / (one_r * trade.actual_filled_quantity)
    control = ExitResearchControl(
        control_id="",
        method=ACTUAL_FROZEN_CONTROL,
        trade_id=trade.trade_id,
        actual_trade_fingerprint=trade.fingerprint,
        opportunity_id=trade.opportunity_id,
        opportunity_fingerprint=trade.opportunity_fingerprint,
        candidate_id=trade.candidate_id,
        setup_id=trade.setup_id,
        trade_plan_id=trade.trade_plan_id,
        trade_plan_fingerprint=trade.trade_plan_fingerprint,
        symbol=trade.symbol,
        side=trade.side,
        session=trade.session,
        sample_identity=trade.sample_identity,
        sample_policy_fingerprint=trade.sample_policy_fingerprint,
        provider_environment_id=trade.provider_environment_id,
        entry_order_id=trade.entry_order_id,
        entry_fill_id=trade.entry_fill_id,
        actual_average_fill=trade.actual_average_fill,
        actual_filled_quantity=trade.actual_filled_quantity,
        actual_fill_at=trade.actual_fill_at,
        original_protective_stop=trade.original_protective_stop,
        original_targets=trade.original_targets,
        forced_flat_at=trade.forced_flat_at,
        original_risk_per_share=one_r,
        actual_terminal_state=trade.actual_terminal_state,
        actual_exit_fills=trade.actual_exit_fills,
        actual_result_domain=ACTUAL_EXECUTABLE_RESULT,
        actual_result_r=_rounded(actual_r),
        actual_result_pnl=_rounded(actual_pnl),
        evidence_refs=trade.evidence_refs,
        fingerprint="",
    )
    identity_payload = control_to_wire(control)
    identity_payload.pop("controlId")
    identity_payload.pop("fingerprint")
    with_id = replace(control, control_id=_fingerprint(identity_payload))
    complete = replace(
        with_id,
        fingerprint=_fingerprint(control_to_wire(with_id)),
    )
    validate_exit_research_control(complete)
    return complete


def _evaluate_structural(
    control: ExitResearchControl,
    bars: tuple[ExitResearchBar, ...],
    policy: ExitResearchPolicy,
    cutoff: datetime,
    structure: StructuralStopEvidence | None,
) -> ExitCounterfactualPath:
    state = _new_state(STRUCTURAL_STOP, control, policy, cutoff)
    if structure is None:
        return _abstain_path(state, "MISSING_REQUIRED_STRUCTURE_EVIDENCE")
    state.evidence.append(structure.evidence)
    if structure.level >= control.actual_average_fill:
        return _abstain_path(state, "STRUCTURAL_STOP_NOT_BELOW_ENTRY")
    effective = _parse_time(structure.effective_at, "Structure effective-at")
    for bar in bars:
        if _parse_time(bar.started_at, "Bar start") >= effective:
            if state.active_stop != structure.level:
                state.active_stop = structure.level
                _append_event(
                    state,
                    STOP_UPDATED,
                    _parse_time(bar.started_at, "Bar start"),
                    _parse_time(structure.known_at, "Structure known-at"),
                    structure.level,
                    None,
                    ("STRUCTURAL_STOP_ACTIVATED",),
                    (structure.fingerprint,),
                )
            if _process_stop_target_bar(state, bar, final_target=_final_target(control)):
                break
        elif _process_stop_target_bar(state, bar, final_target=_final_target(control)):
            break
    return _finish_path(state)


def _evaluate_trailing(
    control: ExitResearchControl,
    bars: tuple[ExitResearchBar, ...],
    policy: ExitResearchPolicy,
    cutoff: datetime,
) -> ExitCounterfactualPath:
    state = _new_state(TRAILING_STOP, control, policy, cutoff)
    for bar in bars:
        if _process_stop_target_bar(state, bar, final_target=_final_target(control)):
            break
        if bar.atr is None:
            return _fail_path(state, "ATR_EVIDENCE_MISSING")
        proposed = bar.high - policy.trailing_atr_multiple * bar.atr
        proposed = max(control.original_protective_stop, proposed)
        if proposed > state.active_stop:
            prior = state.active_stop
            state.active_stop = proposed
            _append_event(
                state,
                STOP_UPDATED,
                _parse_time(bar.completed_at, "Bar completion"),
                _parse_time(bar.known_at, "Bar known-at"),
                proposed,
                None,
                ("TRAILING_STOP_TIGHTENED", "EFFECTIVE_NEXT_BAR"),
                (bar.fingerprint,),
            )
            if state.active_stop < prior:
                raise ExitResearchError("Trailing stop loosened unexpectedly.")
    return _finish_path(state)


def _evaluate_time(
    control: ExitResearchControl,
    bars: tuple[ExitResearchBar, ...],
    policy: ExitResearchPolicy,
    cutoff: datetime,
) -> ExitCounterfactualPath:
    state = _new_state(TIME_STOP, control, policy, cutoff)
    deadline = _parse_time(control.actual_fill_at, "Actual fill") + timedelta(
        minutes=policy.time_stop_minutes
    )
    for bar in bars:
        if _process_stop_target_bar(state, bar, final_target=_final_target(control)):
            break
        completed = _parse_time(bar.completed_at, "Bar completion")
        if completed >= deadline:
            _terminate_at_close(state, bar, "TIME_STOP_ELAPSED")
            break
    return _finish_path(state)


def _evaluate_break_even(
    control: ExitResearchControl,
    bars: tuple[ExitResearchBar, ...],
    policy: ExitResearchPolicy,
    cutoff: datetime,
) -> ExitCounterfactualPath:
    state = _new_state(BREAK_EVEN, control, policy, cutoff)
    trigger = control.actual_average_fill + (
        policy.break_even_trigger_r * control.original_risk_per_share
    )
    break_even_stop = control.actual_average_fill + (
        policy.break_even_offset_r * control.original_risk_per_share
    )
    armed = False
    for bar in bars:
        if not armed and bar.high >= trigger and bar.low <= break_even_stop:
            _mark_ambiguous(
                state,
                bar,
                ("BREAK_EVEN_TRIGGER_AND_VIOLATION_SAME_BAR",),
            )
            break
        if _process_stop_target_bar(state, bar, final_target=_final_target(control)):
            break
        if not armed and bar.high >= trigger:
            armed = True
            state.active_stop = max(state.active_stop, break_even_stop)
            _append_event(
                state,
                STOP_UPDATED,
                _parse_time(bar.completed_at, "Bar completion"),
                _parse_time(bar.known_at, "Bar known-at"),
                state.active_stop,
                None,
                ("BREAK_EVEN_ARMED", "EFFECTIVE_NEXT_BAR"),
                (bar.fingerprint,),
            )
    return _finish_path(state)


def _evaluate_partial(
    control: ExitResearchControl,
    bars: tuple[ExitResearchBar, ...],
    policy: ExitResearchPolicy,
    cutoff: datetime,
) -> ExitCounterfactualPath:
    state = _new_state(PARTIAL_EXIT, control, policy, cutoff)
    if not control.original_targets:
        return _abstain_path(state, "FROZEN_TARGET_1_MISSING")
    target_one = control.original_targets[0]
    target_two = control.original_targets[1] if len(control.original_targets) > 1 else None
    partial_done = False
    for bar in bars:
        stop_hit = state.active_stop is not None and bar.low <= state.active_stop
        target_hit = (
            (not partial_done and bar.high >= target_one)
            or (partial_done and target_two is not None and bar.high >= target_two)
        )
        if stop_hit and target_hit and bar.open > state.active_stop:
            _mark_ambiguous(state, bar, ("PARTIAL_TARGET_AND_STOP_SAME_BAR",))
            break
        if state.active_stop is not None and bar.open < state.active_stop:
            _terminate_stop(state, bar, gap=True)
            break
        if not partial_done and bar.high >= target_one:
            quantity = control.actual_filled_quantity * policy.partial_fraction
            _add_leg(state, bar, target_one, quantity, "PARTIAL_TARGET_1")
            state.remaining_quantity -= quantity
            partial_done = True
            state.exit_signal_state = PARTIAL_SIGNAL
            _append_event(
                state,
                PARTIAL_SIGNAL,
                _parse_time(bar.completed_at, "Bar completion"),
                _parse_time(bar.known_at, "Bar known-at"),
                target_one,
                quantity,
                ("COUNTERFACTUAL_PARTIAL_EXIT_SIGNAL",),
                (bar.fingerprint,),
            )
            _consume_trigger_price(state, target_one)
            state.used_bars.append(bar)
            state.evidence.append(bar.evidence)
            continue
        if partial_done and target_two is not None and bar.high >= target_two:
            _add_leg(
                state,
                bar,
                target_two,
                state.remaining_quantity,
                "REMAINING_TARGET_2",
            )
            _consume_trigger_price(state, target_two)
            state.used_bars.append(bar)
            state.evidence.append(bar.evidence)
            _terminate_from_legs(state, bar, "PARTIAL_PATH_COMPLETE")
            break
        if stop_hit:
            _terminate_stop(state, bar, gap=False)
            break
        if _forced_flat_due(control, bar):
            _add_leg(
                state,
                bar,
                bar.close,
                state.remaining_quantity,
                "FORCED_FLAT",
            )
            _consume_full_bar(state, bar)
            _terminate_from_legs(state, bar, "FORCED_FLAT")
            break
        _consume_full_bar(state, bar)
    return _finish_path(state)


def _evaluate_opinion_method(
    method: str,
    control: ExitResearchControl,
    bars: tuple[ExitResearchBar, ...],
    policy: ExitResearchPolicy,
    cutoff: datetime,
    opinions: tuple[SpecialistOpinion, ...],
) -> ExitCounterfactualPath:
    state = _new_state(method, control, policy, cutoff)
    codes = (
        policy.momentum_failure_codes
        if method == MOMENTUM_FAILURE
        else policy.regime_deterioration_codes
    )
    eligible = tuple(
        item
        for item in opinions
        if item.evaluation_status == EVALUATED and item.opinion_code in codes
    )
    if not eligible:
        reason = (
            "MISSING_REQUIRED_SPECIALIST_EVIDENCE"
            if not opinions
            else "SUPPORTED_DETERIORATION_OPINION_UNAVAILABLE"
        )
        return _abstain_path(state, reason)
    opinion_index = 0
    usable_opinion = False
    for bar in bars:
        if _process_stop_target_bar(state, bar, final_target=_final_target(control)):
            break
        completed = _parse_time(bar.completed_at, "Bar completion")
        while opinion_index < len(eligible):
            opinion = eligible[opinion_index]
            opinion_time = _parse_time(opinion.as_of, "Opinion as-of")
            if opinion_time > completed:
                break
            opinion_index += 1
            if opinion_is_expired(opinion, completed):
                continue
            usable_opinion = True
            state.evidence.append(_opinion_reference(opinion))
            _terminate_at_close(
                state,
                bar,
                (
                    "MOMENTUM_FAILURE_OPINION"
                    if method == MOMENTUM_FAILURE
                    else "REGIME_DETERIORATION_OPINION"
                ),
                extra_evidence=(opinion.fingerprint,),
            )
            break
        if state.terminal_state != OPEN:
            break
    if state.terminal_state == OPEN and not usable_opinion:
        return _abstain_path(state, "STALE_SPECIALIST_EVIDENCE")
    return _finish_path(state)


def _new_state(
    method: str,
    control: ExitResearchControl,
    policy: ExitResearchPolicy,
    cutoff: datetime,
) -> _PathState:
    state = _PathState(
        method=method,
        control=control,
        policy=policy,
        evaluated_at=cutoff,
        active_stop=control.original_protective_stop,
        remaining_quantity=control.actual_filled_quantity,
        evidence=list(control.evidence_refs),
    )
    _append_event(
        state,
        CREATED,
        _parse_time(control.actual_fill_at, "Actual fill"),
        _parse_time(control.actual_fill_at, "Actual fill"),
        control.actual_average_fill,
        control.actual_filled_quantity,
        ("ACTUAL_BROKER_FILL_BOUND",),
        (control.fingerprint,),
    )
    _append_event(
        state,
        ACTIVE,
        _parse_time(control.actual_fill_at, "Actual fill"),
        _parse_time(control.actual_fill_at, "Actual fill"),
        control.original_protective_stop,
        control.actual_filled_quantity,
        ("COUNTERFACTUAL_RESEARCH_ONLY",),
        (control.fingerprint,),
    )
    return state


def _process_stop_target_bar(
    state: _PathState,
    bar: ExitResearchBar,
    *,
    final_target: Decimal | None,
) -> bool:
    if state.active_stop is not None and bar.open < state.active_stop:
        _terminate_stop(state, bar, gap=True)
        return True
    if final_target is not None and bar.open > final_target:
        _terminate_target(state, bar, final_target)
        return True
    stop_hit = state.active_stop is not None and bar.low <= state.active_stop
    target_hit = final_target is not None and bar.high >= final_target
    if stop_hit and target_hit:
        _mark_ambiguous(state, bar, ("STOP_AND_TARGET_SAME_BAR",))
        return True
    if stop_hit:
        _terminate_stop(state, bar, gap=False)
        return True
    if target_hit and final_target is not None:
        _terminate_target(state, bar, final_target)
        return True
    if _forced_flat_due(state.control, bar):
        _terminate_at_close(state, bar, "FORCED_FLAT")
        return True
    _consume_full_bar(state, bar)
    return False


def _terminate_stop(state: _PathState, bar: ExitResearchBar, *, gap: bool) -> None:
    assert state.active_stop is not None
    exit_quantity = state.remaining_quantity
    if gap:
        state.execution_status = EXECUTION_UNKNOWN
        state.exit_reference_price = state.active_stop
        state.reference_r = None
        state.reference_pnl = None
        reason = ("STOP_LEVEL_CROSSED", "GAP_BEYOND_STOP", "EXECUTION_UNKNOWN")
        _consume_trigger_price(state, bar.open)
    else:
        reason = ("STOP_LEVEL_CROSSED", "MARKET_PATH_TRIGGER")
        _add_leg(
            state,
            bar,
            state.active_stop,
            exit_quantity,
            "STOP_LEVEL_CROSSED",
        )
        _consume_trigger_price(state, state.active_stop)
        total_pnl = sum(
            (leg.reference_pnl or Decimal("0") for leg in state.legs),
            Decimal("0"),
        )
        state.exit_reference_price = state.active_stop
        state.reference_pnl = total_pnl
        state.reference_r = total_pnl / (
            state.control.original_risk_per_share
            * state.control.actual_filled_quantity
        )
    state.used_bars.append(bar)
    state.evidence.append(bar.evidence)
    state.evaluation_state = TERMINAL
    state.exit_signal_state = EXIT_SIGNAL
    if gap:
        state.terminal_state = EXIT_SIGNALLED_EXECUTION_UNKNOWN
    else:
        state.remaining_quantity = Decimal("0")
        state.terminal_state = EXITED
    state.terminal_at = _parse_time(bar.completed_at, "Bar completion")
    state.market_path_outcome = "STOP_LEVEL_CROSSED"
    state.reason_codes.extend(reason)
    _append_event(
        state,
        EXIT_SIGNAL,
        state.terminal_at,
        _parse_time(bar.known_at, "Bar known-at"),
        state.active_stop,
        exit_quantity,
        reason,
        (bar.fingerprint,),
    )


def _terminate_target(
    state: _PathState, bar: ExitResearchBar, target: Decimal
) -> None:
    _add_leg(state, bar, target, state.remaining_quantity, "FROZEN_FINAL_TARGET")
    _consume_trigger_price(state, target)
    state.used_bars.append(bar)
    state.evidence.append(bar.evidence)
    _terminate_from_legs(state, bar, "FROZEN_FINAL_TARGET")


def _terminate_at_close(
    state: _PathState,
    bar: ExitResearchBar,
    reason: str,
    *,
    extra_evidence: tuple[str, ...] = (),
) -> None:
    _consume_full_bar(state, bar)
    _add_leg(state, bar, bar.close, state.remaining_quantity, reason)
    _terminate_from_legs(state, bar, reason, extra_evidence=extra_evidence)


def _terminate_from_legs(
    state: _PathState,
    bar: ExitResearchBar,
    reason: str,
    *,
    extra_evidence: tuple[str, ...] = (),
) -> None:
    terminal_quantity = state.legs[-1].quantity if state.legs else Decimal("0")
    state.remaining_quantity = Decimal("0")
    state.evaluation_state = TERMINAL
    state.exit_signal_state = EXIT_SIGNAL
    state.terminal_state = EXITED
    state.terminal_at = _parse_time(bar.completed_at, "Bar completion")
    state.market_path_outcome = reason
    state.reason_codes.append(reason)
    total_pnl = sum((leg.reference_pnl or Decimal("0") for leg in state.legs), Decimal("0"))
    state.reference_pnl = total_pnl
    state.reference_r = total_pnl / (
        state.control.original_risk_per_share
        * state.control.actual_filled_quantity
    )
    state.exit_reference_price = state.legs[-1].reference_price if state.legs else None
    _append_event(
        state,
        EXIT_SIGNAL,
        state.terminal_at,
        _parse_time(bar.known_at, "Bar known-at"),
        state.exit_reference_price,
        terminal_quantity,
        (reason, "MARKET_PATH_TRIGGER"),
        (bar.fingerprint,) + extra_evidence,
    )


def _mark_ambiguous(
    state: _PathState,
    bar: ExitResearchBar,
    reasons: tuple[str, ...],
) -> None:
    state.used_bars.append(bar)
    state.evidence.append(bar.evidence)
    state.evaluation_state = AMBIGUOUS_SAME_BAR
    state.exit_signal_state = AMBIGUOUS_SAME_BAR
    state.terminal_state = AMBIGUOUS_SAME_BAR
    state.terminal_at = _parse_time(bar.completed_at, "Bar completion")
    state.market_path_outcome = AMBIGUOUS_SAME_BAR
    state.execution_status = EXECUTION_UNKNOWN
    state.reason_codes.extend(reasons + (AMBIGUOUS_SAME_BAR,))
    _append_event(
        state,
        AMBIGUOUS_SAME_BAR,
        state.terminal_at,
        _parse_time(bar.known_at, "Bar known-at"),
        None,
        None,
        reasons + (AMBIGUOUS_SAME_BAR,),
        (bar.fingerprint,),
    )


def _consume_full_bar(state: _PathState, bar: ExitResearchBar) -> None:
    state.mfe = max(state.mfe, bar.high - state.control.actual_average_fill)
    state.mae = min(state.mae, bar.low - state.control.actual_average_fill)
    state.used_bars.append(bar)
    state.evidence.append(bar.evidence)


def _consume_trigger_price(state: _PathState, price: Decimal) -> None:
    move = price - state.control.actual_average_fill
    state.mfe = max(state.mfe, move)
    state.mae = min(state.mae, move)


def _add_leg(
    state: _PathState,
    bar: ExitResearchBar,
    price: Decimal,
    quantity: Decimal,
    reason: str,
) -> None:
    if quantity <= 0:
        return
    if sum((leg.quantity for leg in state.legs), Decimal("0")) + quantity > state.control.actual_filled_quantity:
        raise ExitResearchError("Counterfactual exit quantity exceeds actual fill.")
    pnl = (price - state.control.actual_average_fill) * quantity
    reference_r = (price - state.control.actual_average_fill) / state.control.original_risk_per_share
    payload = {
        "domain": "exit-counterfactual-leg-v1",
        "controlId": state.control.control_id,
        "method": state.method,
        "reason": reason,
        "at": bar.completed_at,
        "quantity": _decimal_wire(quantity),
        "price": _decimal_wire(price),
    }
    leg = ExitLeg(
        leg_id=_fingerprint(payload),
        reason_code=reason,
        signaled_at=bar.completed_at,
        quantity=quantity,
        reference_price=price,
        result_domain=COUNTERFACTUAL_MARKET_PATH_RESULT,
        execution_evidence_status=MARKET_PATH_ONLY,
        reference_r=_rounded(reference_r),
        reference_pnl=_rounded(pnl),
        fingerprint="",
    )
    state.legs.append(replace(leg, fingerprint=_fingerprint(_leg_to_wire(leg))))


def _append_event(
    state: _PathState,
    event_type: str,
    event_at: datetime,
    known_at: datetime,
    reference_price: Decimal | None,
    quantity: Decimal | None,
    reason_codes: tuple[str, ...],
    evidence_fingerprints: tuple[str, ...],
) -> None:
    if known_at > state.evaluated_at:
        raise ExitResearchError("Decision event consumes future evidence.")
    event = ExitDecisionEvent(
        sequence=len(state.events) + 1,
        event_type=_token(event_type, "Decision event type"),
        event_at=_canonical_time(event_at),
        known_at=_canonical_time(known_at),
        evaluated_at=_canonical_time(state.evaluated_at),
        reference_price=reference_price,
        quantity=quantity,
        reason_codes=tuple(sorted(set(reason_codes))),
        evidence_fingerprints=tuple(sorted(set(evidence_fingerprints))),
        fingerprint="",
    )
    state.events.append(replace(event, fingerprint=_fingerprint(_event_to_wire(event))))


def _finish_path(state: _PathState) -> ExitCounterfactualPath:
    cutoff = state.terminal_at or state.evaluated_at
    evidence = _canonical_references(state.evidence)
    mfe_r = state.mfe / state.control.original_risk_per_share
    mae_r = state.mae / state.control.original_risk_per_share
    if state.terminal_state == OPEN:
        state.market_path_outcome = "OPEN_AT_EVIDENCE_CUTOFF"
        state.reason_codes.append("NO_COUNTERFACTUAL_EXIT_YET")
    if state.terminal_state in {EXITED, EXIT_SIGNALLED_EXECUTION_UNKNOWN}:
        terminal_known = max(
            state.terminal_at or cutoff,
            _parse_time(state.events[-1].known_at, "Last event known-at"),
        )
        _append_event(
            state,
            TERMINAL,
            state.terminal_at or cutoff,
            terminal_known,
            state.exit_reference_price,
            Decimal("0"),
            ("COUNTERFACTUAL_TERMINAL",),
            tuple(item.fingerprint for item in evidence),
        )
    identity = {
        "domain": "exit-counterfactual-identity-v1",
        "controlFingerprint": state.control.fingerprint,
        "method": state.method,
        "methodVersion": POLICY_VERSION,
        "policyFingerprint": state.policy.fingerprint,
        "evidenceCutoff": _canonical_time(cutoff),
        "startingQuantity": _decimal_wire(state.control.actual_filled_quantity),
        "actualEntryBasis": _decimal_wire(state.control.actual_average_fill),
        "inputEvidenceFingerprint": input_evidence_fingerprint(evidence),
    }
    counterfactual_id = _fingerprint(identity)
    metrics_available = state.evaluation_state not in {
        ABSTAINED_STATE,
        DATA_FAILURE,
    }
    path = ExitCounterfactualPath(
        counterfactual_id=counterfactual_id,
        control_id=state.control.control_id,
        trade_id=state.control.trade_id,
        opportunity_id=state.control.opportunity_id,
        opportunity_fingerprint=state.control.opportunity_fingerprint,
        candidate_id=state.control.candidate_id,
        setup_id=state.control.setup_id,
        trade_plan_id=state.control.trade_plan_id,
        method=state.method,
        method_version=POLICY_VERSION,
        policy_fingerprint=state.policy.fingerprint,
        started_at=state.control.actual_fill_at,
        evidence_cutoff=_canonical_time(cutoff),
        entry_price=state.control.actual_average_fill,
        starting_quantity=state.control.actual_filled_quantity,
        evaluation_state=state.evaluation_state,
        exit_signal_state=state.exit_signal_state,
        active_stop=state.active_stop,
        remaining_quantity=state.remaining_quantity,
        terminal_state=state.terminal_state,
        terminal_at=(
            _canonical_time(state.terminal_at) if state.terminal_at is not None else None
        ),
        market_path_outcome=state.market_path_outcome,
        execution_evidence_status=state.execution_status,
        result_domain=COUNTERFACTUAL_MARKET_PATH_RESULT,
        exit_reference_price=state.exit_reference_price,
        reference_r=_rounded(state.reference_r),
        reference_pnl=_rounded(state.reference_pnl),
        mfe_r=_rounded(mfe_r) if metrics_available else None,
        mae_r=_rounded(mae_r) if metrics_available else None,
        mfe_captured_r=(
            _rounded(state.reference_r) if state.terminal_state == EXITED else None
        ),
        giveback_from_mfe_r=(
            _rounded(mfe_r - state.reference_r)
            if state.terminal_state == EXITED and state.reference_r is not None
            else None
        ),
        duration_seconds=(
            int((state.terminal_at - _parse_time(state.control.actual_fill_at, "Fill")).total_seconds())
            if state.terminal_at is not None
            else None
        ),
        reason_codes=tuple(sorted(set(state.reason_codes))),
        events=tuple(state.events),
        exit_legs=tuple(state.legs),
        evidence_refs=evidence,
        fingerprint="",
    )
    complete = replace(path, fingerprint=_fingerprint(path_to_wire(path)))
    validate_counterfactual_path(complete)
    return complete


def _abstain_path(state: _PathState, reason: str) -> ExitCounterfactualPath:
    state.evaluation_state = ABSTAINED_STATE
    state.exit_signal_state = "NO_OPINION"
    state.terminal_state = ABSTAINED_STATE
    state.market_path_outcome = "NOT_EVALUATED"
    state.execution_status = EXECUTION_UNKNOWN
    state.reason_codes.append(reason)
    _append_event(
        state,
        ABSTAINED_STATE,
        _parse_time(state.control.actual_fill_at, "Actual fill"),
        _parse_time(state.control.actual_fill_at, "Actual fill"),
        None,
        None,
        (reason,),
        (state.control.fingerprint,),
    )
    return _finish_path(state)


def _fail_path(state: _PathState, reason: str) -> ExitCounterfactualPath:
    state.evaluation_state = DATA_FAILURE
    state.exit_signal_state = "NO_SIGNAL"
    state.terminal_state = DATA_FAILURE
    state.market_path_outcome = DATA_FAILURE
    state.execution_status = EXECUTION_UNKNOWN
    state.reason_codes.append(reason)
    _append_event(
        state,
        DATA_FAILURE,
        state.evaluated_at,
        state.evaluated_at,
        None,
        None,
        (reason,),
        tuple(item.fingerprint for item in state.evidence),
    )
    return _finish_path(state)


def _data_failure_path(
    method: str,
    control: ExitResearchControl,
    policy: ExitResearchPolicy,
    cutoff: datetime,
    bars: tuple[ExitResearchBar, ...],
    reason: str,
) -> ExitCounterfactualPath:
    state = _new_state(method, control, policy, cutoff)
    state.evidence.extend(bar.evidence for bar in bars)
    state.used_bars.extend(bars)
    return _fail_path(state, reason)


def _path_opinion(
    path: ExitCounterfactualPath,
    control: ExitResearchControl,
    policy: ExitResearchPolicy,
    cutoff: datetime,
) -> SpecialistOpinion:
    as_of = _parse_time(path.evidence_cutoff, "Path evidence cutoff")
    expires = max(cutoff, as_of) + timedelta(seconds=policy.bar_seconds)
    if path.evaluation_state == ABSTAINED_STATE:
        return build_specialist_opinion(
            specialist_id=SPECIALIST_ID,
            specialist_version=SPECIALIST_VERSION,
            opportunity_id=control.opportunity_id,
            candidate_id=control.candidate_id,
            setup_id=control.setup_id,
            trade_plan_id=control.trade_plan_id,
            as_of=as_of,
            expires_at=expires,
            research_identity=RESEARCH_IDENTITY,
            policy_fingerprint=policy.fingerprint,
            evaluation_status=ABSTAINED,
            opinion_code=NO_OPINION,
            directional_bias=NO_DIRECTION,
            evidence_refs=(),
            feature_families=(),
            confidence=unavailable_confidence(),
            reason_codes=path.reason_codes,
            explanation=f"{path.method} abstained from exit research.",
            abstention_reason="INSUFFICIENT_EVIDENCE",
        )
    if path.evaluation_state == DATA_FAILURE:
        return build_specialist_opinion(
            specialist_id=SPECIALIST_ID,
            specialist_version=SPECIALIST_VERSION,
            opportunity_id=control.opportunity_id,
            candidate_id=control.candidate_id,
            setup_id=control.setup_id,
            trade_plan_id=control.trade_plan_id,
            as_of=as_of,
            expires_at=expires,
            research_identity=RESEARCH_IDENTITY,
            policy_fingerprint=policy.fingerprint,
            evaluation_status=FAILED,
            opinion_code=None,
            directional_bias=NO_DIRECTION,
            evidence_refs=path.evidence_refs,
            feature_families=("CANDLE_STRUCTURE",),
            confidence=unavailable_confidence(),
            reason_codes=path.reason_codes,
            explanation=f"{path.method} could not be evaluated safely.",
            failure_reason="DATA_FAILURE",
        )
    if path.evaluation_state == AMBIGUOUS_SAME_BAR:
        code = COUNTERFACTUAL_HOLD_SIGNAL
        reasons = tuple(sorted(set(path.reason_codes + ("EXIT_ORDER_AMBIGUOUS",))))
    elif path.exit_legs and len(path.exit_legs) < 2 and path.remaining_quantity > 0:
        code = COUNTERFACTUAL_PARTIAL_EXIT_SIGNAL
        reasons = path.reason_codes or ("COUNTERFACTUAL_PARTIAL_EXIT",)
    elif path.terminal_state in {EXITED, EXIT_SIGNALLED_EXECUTION_UNKNOWN}:
        code = COUNTERFACTUAL_EXIT_SIGNAL
        reasons = path.reason_codes or ("COUNTERFACTUAL_EXIT",)
    else:
        code = COUNTERFACTUAL_HOLD_SIGNAL
        reasons = path.reason_codes or ("COUNTERFACTUAL_REMAINS_OPEN",)
    families = ["CANDLE_STRUCTURE"]
    if path.method == REGIME_DETERIORATION:
        families.append("MARKET_REGIME")
    return build_specialist_opinion(
        specialist_id=SPECIALIST_ID,
        specialist_version=SPECIALIST_VERSION,
        opportunity_id=control.opportunity_id,
        candidate_id=control.candidate_id,
        setup_id=control.setup_id,
        trade_plan_id=control.trade_plan_id,
        as_of=as_of,
        expires_at=expires,
        research_identity=RESEARCH_IDENTITY,
        policy_fingerprint=policy.fingerprint,
        evaluation_status=EVALUATED,
        opinion_code=code,
        directional_bias=NON_DIRECTIONAL,
        evidence_refs=path.evidence_refs,
        feature_families=families,
        confidence=unavailable_confidence(),
        reason_codes=reasons,
        explanation=f"{path.method} produced research-only counterfactual state {path.terminal_state}.",
    )


def _build_unfilled_opinion(
    trade: ActualTradeEvidence,
    cutoff: datetime,
    policy: ExitResearchPolicy,
) -> SpecialistOpinion:
    return _build_abstention_opinion(
        trade,
        cutoff,
        policy,
        reasons=("ACTUAL_ENTRY_NOT_CONFIRMED", "TRADE_NOT_FILLED"),
        explanation="Exit research requires an actual confirmed filled entry.",
        abstention_reason="INSUFFICIENT_EVIDENCE",
    )


def _build_abstention_opinion(
    trade: ActualTradeEvidence,
    cutoff: datetime,
    policy: ExitResearchPolicy,
    *,
    reasons: tuple[str, ...],
    explanation: str,
    abstention_reason: str,
) -> SpecialistOpinion:
    refs = tuple(
        item
        for item in trade.evidence_refs
        if _parse_time(item.as_of, "Evidence timestamp") <= cutoff
    )
    return build_specialist_opinion(
        specialist_id=SPECIALIST_ID,
        specialist_version=SPECIALIST_VERSION,
        opportunity_id=trade.opportunity_id,
        candidate_id=trade.candidate_id,
        setup_id=trade.setup_id,
        trade_plan_id=trade.trade_plan_id,
        as_of=cutoff,
        expires_at=cutoff + timedelta(seconds=policy.bar_seconds),
        research_identity=RESEARCH_IDENTITY,
        policy_fingerprint=policy.fingerprint,
        evaluation_status=ABSTAINED,
        opinion_code=NO_OPINION,
        directional_bias=NO_DIRECTION,
        evidence_refs=refs,
        feature_families=("BROKER_STATE",) if refs else (),
        confidence=unavailable_confidence(),
        reason_codes=reasons,
        explanation=explanation,
        abstention_reason=abstention_reason,
    )


def _post_exit_observation(
    path: ExitCounterfactualPath,
    control: ExitResearchControl,
    bars: tuple[ExitResearchBar, ...],
) -> PostExitOpportunityObservation | None:
    if path.terminal_at is None or path.terminal_state not in {
        EXITED,
        EXIT_SIGNALLED_EXECUTION_UNKNOWN,
    }:
        return None
    terminal = _parse_time(path.terminal_at, "Path terminal time")
    later = tuple(
        bar
        for bar in bars
        if _parse_time(bar.started_at, "Bar start") >= terminal
    )
    if not later:
        return None
    favorable = max(bar.high - control.actual_average_fill for bar in later)
    adverse = min(bar.low - control.actual_average_fill for bar in later)
    refs = _canonical_references(bar.evidence for bar in later)
    observation = PostExitOpportunityObservation(
        observation_id="",
        counterfactual_id=path.counterfactual_id,
        observed_from=later[0].started_at,
        observed_through=later[-1].completed_at,
        max_favorable_after_exit_r=_rounded(
            favorable / control.original_risk_per_share
        ),
        max_adverse_after_exit_r=_rounded(adverse / control.original_risk_per_share),
        evidence_refs=refs,
        fingerprint="",
    )
    payload = post_exit_to_wire(observation)
    payload.pop("observationId")
    payload.pop("fingerprint")
    with_id = replace(observation, observation_id=_fingerprint(payload))
    return replace(with_id, fingerprint=_fingerprint(post_exit_to_wire(with_id)))


def _complete_evaluation(evaluation: ExitResearchEvaluation) -> ExitResearchEvaluation:
    identity_payload = evaluation_to_wire(evaluation)
    identity_payload.pop("evaluationId")
    identity_payload.pop("fingerprint")
    with_id = replace(evaluation, evaluation_id=_fingerprint(identity_payload))
    complete = replace(
        with_id,
        fingerprint=_fingerprint(evaluation_to_wire(with_id)),
    )
    if complete.future_sample.activated or complete.future_sample.trades != 0:
        raise ExitResearchError("Prospective sample was activated by research code.")
    for path in complete.paths:
        validate_counterfactual_path(path)
    return complete


def _canonical_bars(
    bars: Iterable[ExitResearchBar],
    *,
    trade: ActualTradeEvidence,
    policy: ExitResearchPolicy,
    evaluated_at: datetime,
) -> tuple[ExitResearchBar, ...]:
    if isinstance(bars, (str, bytes, bytearray, Mapping)):
        raise ExitResearchError("Bars are not a record sequence.")
    rows = tuple(bars)
    identities: dict[str, ExitResearchBar] = {}
    for bar in rows:
        validate_exit_research_bar(bar)
        if bar.symbol != trade.symbol or bar.session != trade.session:
            raise ExitResearchError("Bar target identity does not match actual trade.")
        if _parse_time(bar.known_at, "Bar known-at") > evaluated_at:
            raise ExitResearchError("Future bar evidence cannot be evaluated.")
        if bar.bar_id in identities and identities[bar.bar_id] != bar:
            raise ExitResearchError("Duplicate bar identity is contradictory.")
        identities[bar.bar_id] = bar
    ordered = tuple(sorted(identities.values(), key=lambda item: item.started_at))
    if trade.actual_fill_at is not None:
        fill_at = _parse_time(trade.actual_fill_at, "Actual fill")
        ordered = tuple(
            bar
            for bar in ordered
            if _parse_time(bar.completed_at, "Bar completion") > fill_at
        )
    for bar in ordered:
        duration = (
            _parse_time(bar.completed_at, "Bar completion")
            - _parse_time(bar.started_at, "Bar start")
        ).total_seconds()
        if duration != policy.bar_seconds:
            raise ExitResearchError("Bar duration does not match frozen cadence.")
    return ordered


def _bar_data_failure(
    bars: tuple[ExitResearchBar, ...],
    control: ExitResearchControl,
    policy: ExitResearchPolicy,
    cutoff: datetime,
) -> str | None:
    if not bars:
        return "COMPLETED_BAR_EVIDENCE_MISSING"
    if (cutoff - _parse_time(bars[-1].known_at, "Latest bar known-at")).total_seconds() > policy.max_evidence_age_seconds:
        return "STALE_EVIDENCE"
    previous = None
    for bar in bars:
        start = _parse_time(bar.started_at, "Bar start")
        if previous is not None and start != previous:
            return "BAR_SEQUENCE_GAP"
        previous = _parse_time(bar.completed_at, "Bar completion")
    if _parse_time(bars[0].completed_at, "First bar completion") <= _parse_time(
        control.actual_fill_at, "Actual fill"
    ):
        return "BAR_CHRONOLOGY_INVALID"
    return None


def _canonical_opinions(
    opinions: Iterable[SpecialistOpinion],
) -> tuple[SpecialistOpinion, ...]:
    if isinstance(opinions, (str, bytes, bytearray, Mapping)):
        raise ExitResearchError("Specialist opinions are not a record sequence.")
    rows = tuple(opinions)
    identities: dict[str, SpecialistOpinion] = {}
    for opinion in rows:
        validate_specialist_opinion(opinion)
        if opinion.opinion_id in identities and identities[opinion.opinion_id] != opinion:
            raise ExitResearchError("Duplicate specialist opinion is contradictory.")
        identities[opinion.opinion_id] = opinion
    return tuple(sorted(identities.values(), key=lambda item: (item.as_of, item.opinion_id)))


def _validate_opinion_inputs(
    opinions: Sequence[SpecialistOpinion],
    trade: ActualTradeEvidence,
    cutoff: datetime,
    family: str,
) -> None:
    allowed_specialists = (
        {"MOMENTUM", "TECHNICAL_STRUCTURE"}
        if family == "MOMENTUM"
        else {"REGIME"}
    )
    for opinion in opinions:
        if opinion.specialist_id not in allowed_specialists:
            raise ExitResearchError("Sibling specialist identity is unsupported.")
        validate_opinion_target_identity(
            opinion,
            opportunity_id=trade.opportunity_id,
            candidate_id=trade.candidate_id,
            setup_id=trade.setup_id,
            trade_plan_id=trade.trade_plan_id,
        )
        if _parse_time(opinion.as_of, "Opinion as-of") > cutoff:
            raise ExitResearchError("Future specialist opinion cannot be consumed.")


def _validate_structure_target(
    structure: StructuralStopEvidence,
    trade: ActualTradeEvidence,
    cutoff: datetime,
) -> None:
    validate_structural_stop_evidence(structure)
    expected = (
        trade.opportunity_id,
        trade.candidate_id,
        trade.setup_id,
        trade.trade_plan_id,
        trade.symbol,
    )
    actual = (
        structure.opportunity_id,
        structure.candidate_id,
        structure.setup_id,
        structure.trade_plan_id,
        structure.symbol,
    )
    if actual != expected:
        raise ExitResearchError("Structural-stop target identity is mismatched.")
    if _parse_time(structure.known_at, "Structure known-at") > cutoff:
        raise ExitResearchError("Future structure evidence cannot be consumed.")


def _opinion_reference(opinion: SpecialistOpinion) -> EvidenceReference:
    return build_evidence_reference(
        evidence_id=opinion.opinion_id,
        evidence_type="SPECIALIST_OPINION",
        source=opinion.specialist_id,
        as_of=opinion.as_of,
        fingerprint=opinion.fingerprint,
    )


def _forced_flat_due(control: ExitResearchControl, bar: ExitResearchBar) -> bool:
    return _parse_time(bar.completed_at, "Bar completion") >= _parse_time(
        control.forced_flat_at, "Forced-flat time"
    )


def _final_target(control: ExitResearchControl) -> Decimal | None:
    return control.original_targets[-1] if control.original_targets else None


def _validate_events(events: tuple[ExitDecisionEvent, ...]) -> None:
    expected_sequence = 1
    seen: dict[int, ExitDecisionEvent] = {}
    previous_known: datetime | None = None
    for event in events:
        if event.sequence != expected_sequence:
            raise ExitResearchError("Decision event sequence is not contiguous.")
        if event.sequence in seen and seen[event.sequence] != event:
            raise ExitResearchError("Decision event history is contradictory.")
        known = _parse_time(event.known_at, "Event known-at")
        if previous_known is not None and known < previous_known:
            raise ExitResearchError("Decision event knowledge moved backward.")
        previous_known = known
        expected = _fingerprint(_event_to_wire(replace(event, fingerprint="")))
        if event.fingerprint != expected:
            raise ExitResearchError("Decision event fingerprint is invalid.")
        seen[event.sequence] = event
        expected_sequence += 1


def _actual_fill_to_wire(fill: ActualExecutionFill) -> dict[str, object]:
    return {
        "fillId": fill.fill_id,
        "filledAt": fill.filled_at,
        "quantity": _decimal_wire(fill.quantity),
        "averagePrice": _decimal_wire(fill.average_price),
        "reasonCode": fill.reason_code,
        "evidence": _reference_to_wire(fill.evidence),
    }


def _event_to_wire(event: ExitDecisionEvent) -> dict[str, object]:
    return {
        "sequence": event.sequence,
        "eventType": event.event_type,
        "eventAt": event.event_at,
        "knownAt": event.known_at,
        "evaluatedAt": event.evaluated_at,
        "referencePrice": _optional_decimal_wire(event.reference_price),
        "quantity": _optional_decimal_wire(event.quantity),
        "reasonCodes": list(event.reason_codes),
        "evidenceFingerprints": list(event.evidence_fingerprints),
        "fingerprint": event.fingerprint,
    }


def _leg_to_wire(leg: ExitLeg) -> dict[str, object]:
    return {
        "legId": leg.leg_id,
        "reasonCode": leg.reason_code,
        "signaledAt": leg.signaled_at,
        "quantity": _decimal_wire(leg.quantity),
        "referencePrice": _decimal_wire(leg.reference_price),
        "resultDomain": leg.result_domain,
        "executionEvidenceStatus": leg.execution_evidence_status,
        "referenceR": _optional_decimal_wire(leg.reference_r),
        "referencePnl": _optional_decimal_wire(leg.reference_pnl),
        "fingerprint": leg.fingerprint,
    }


def _reference_to_wire(reference: EvidenceReference) -> dict[str, object]:
    return {
        "evidenceId": reference.evidence_id,
        "evidenceType": reference.evidence_type,
        "source": reference.source,
        "asOf": reference.as_of,
        "fingerprint": reference.fingerprint,
    }


def _validate_reference(reference: EvidenceReference) -> None:
    if not isinstance(reference, EvidenceReference):
        raise ExitResearchError("Evidence reference is malformed.")
    if not _SHA256.fullmatch(reference.fingerprint):
        raise ExitResearchError("Evidence fingerprint is malformed.")


def _canonical_references(
    references: Iterable[EvidenceReference],
) -> tuple[EvidenceReference, ...]:
    if isinstance(references, (str, bytes, bytearray, Mapping)):
        raise ExitResearchError("Evidence references are not a record sequence.")
    rows = tuple(references)
    identities: dict[str, EvidenceReference] = {}
    for item in rows:
        _validate_reference(item)
        if item.evidence_id in identities:
            if identities[item.evidence_id] != item:
                raise ExitResearchError("Evidence identity is contradictory.")
            continue
        identities[item.evidence_id] = item
    return tuple(
        sorted(
            identities.values(),
            key=lambda item: (
                item.evidence_type,
                item.evidence_id,
                item.source,
                item.as_of,
                item.fingerprint,
            ),
        )
    )


def _timestamp(value: datetime | str, label: str) -> str:
    return _canonical_time(_parse_time(value, label))


def _parse_time(value: datetime | str, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ExitResearchError(f"{label} is invalid.") from exc
    else:
        raise ExitResearchError(f"{label} is invalid.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExitResearchError(f"{label} must include a UTC offset.")
    return parsed.astimezone(timezone.utc)


def _canonical_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_decimal(value: object, label: str) -> Decimal:
    result = _decimal(value, label)
    if result <= 0:
        raise ExitResearchError(f"{label} must be positive.")
    return result


def _nonnegative_decimal(value: object, label: str) -> Decimal:
    result = _decimal(value, label)
    if result < 0:
        raise ExitResearchError(f"{label} cannot be negative.")
    return result


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ExitResearchError(f"{label} must be finite numeric data.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ExitResearchError(f"{label} must be finite numeric data.") from exc
    if not result.is_finite():
        raise ExitResearchError(f"{label} must be finite numeric data.")
    return result.normalize()


def _rounded(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_EVEN).normalize()


def _decimal_wire(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _optional_decimal_wire(value: Decimal | None) -> str | None:
    return _decimal_wire(value) if value is not None else None


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise ExitResearchError(f"{label} is invalid.")
    return value.strip()


def _symbol(value: object) -> str:
    if not isinstance(value, str):
        raise ExitResearchError("Symbol is invalid.")
    text = value.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", text):
        raise ExitResearchError("Symbol is invalid.")
    return text


def _token(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ExitResearchError(f"{label} is invalid.")
    text = value.strip().upper()
    if not _TOKEN.fullmatch(text):
        raise ExitResearchError(f"{label} is invalid.")
    return text


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value.strip().lower()):
        raise ExitResearchError(f"{label} is invalid.")
    return value.strip().lower()


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload).rstrip(b"\n")).hexdigest()
