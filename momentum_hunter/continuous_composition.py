"""Pure continuous-intraday readiness and research-plan composition.

This module deliberately has no provider, broker, account, scheduler, runtime,
or persistence capability.  A future runtime may ask for the emitted readiness
work, then supply reconciled canonical evidence back to this deterministic
composer.  Chart-pattern judgment is not derived here: successor structure is
explicit caller-supplied research evidence and remains research-only.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping

from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_FORMING,
    DATA_STALE,
    ENTRY_MISSED,
    FAILED_BREAKOUT,
    INVALIDATED,
    LEGAL_TRANSITIONS,
    PULLBACK_FORMING,
    RECLAIM_FORMING,
    SETUP_IDENTITY_CHANGED,
    SETUP_STATE_CHANGED,
    CandidateLifecycleSnapshot,
    resolve_setup_identity,
)
from momentum_hunter.canonical_candle_evidence import (
    CANONICAL_OUTCOME_STATES,
    CanonicalMinuteBar,
)
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE
from momentum_hunter.hot_universe import (
    EXPIRED,
    HOT,
    PROVIDER_BOUND as UNIVERSE_PROVIDER_BOUND,
    PROTECTED,
    TRACKED,
    WARM,
    HotUniverseMember,
    HotUniverseState,
    validate_hot_universe_state,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    EXPIRED as PLAN_EXPIRED,
    MISSED_ENTRY as PLAN_MISSED_ENTRY,
    OPENING_BREAKOUT,
    PULLBACK,
    RECLAIM,
    SUPPORTED_SETUP_FAMILIES,
    IntradayPlanEvidence,
    build_intraday_plan_evidence,
    intraday_plan_validation_findings,
    transition_intraday_plan,
)
from momentum_hunter.schwab_candle_contract import EASTERN_TZ, SCHWAB_PRICE_HISTORY_SOURCE
from momentum_hunter.time_normalized_rvol import TimeNormalizedRvolEvidence


CONTINUOUS_COMPOSITION_SCHEMA_VERSION = 1
CONTINUOUS_COMPOSITION_PROFILE = "continuous-composition-v1"
CONTINUOUS_COMPOSITION_POLICY_VERSION = "continuous-composition-policy-v1"
RESEARCH_AUTHORITY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY_NONE = "EXECUTION_AUTHORITY_NONE"

READY = "READY"
WAITING_FOR_CANONICAL_BARS = "WAITING_FOR_CANONICAL_BARS"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
INSUFFICIENT_RVOL_BASELINE = "INSUFFICIENT_RVOL_BASELINE"
STALE_EVIDENCE = "STALE_EVIDENCE"
GAPPED_EVIDENCE = "GAPPED_EVIDENCE"
DATA_UNSAFE = "DATA_UNSAFE"
READINESS_PROVIDER_BOUND = "PROVIDER_BOUND"
UNSUPPORTED_SESSION = "UNSUPPORTED_SESSION"
READINESS_STATUSES = frozenset(
    {
        READY,
        WAITING_FOR_CANONICAL_BARS,
        INSUFFICIENT_HISTORY,
        INSUFFICIENT_RVOL_BASELINE,
        STALE_EVIDENCE,
        GAPPED_EVIDENCE,
        DATA_UNSAFE,
        READINESS_PROVIDER_BOUND,
        UNSUPPORTED_SESSION,
    }
)

NOT_EVALUATED_POLICY = "NOT_EVALUATED_POLICY"
PROVIDER_BOUND = "PROVIDER_BOUND"
WAITING_READINESS = "WAITING_READINESS"
BLOCKED_DATA = "BLOCKED_DATA"
DATA_FAILURE = "DATA_FAILURE"
NO_LIFECYCLE_CHANGE = "NO_LIFECYCLE_CHANGE"
SETUP_PENDING = "SETUP_PENDING"
MISSED_ENTRY_RECORDED = "MISSED_ENTRY_RECORDED"
SUCCESSOR_SETUP_CREATED = "SUCCESSOR_SETUP_CREATED"
RESEARCH_PLAN_COMPOSED = "RESEARCH_PLAN_COMPOSED"
EXPIRED_RESULT = "EXPIRED"
UNSUPPORTED_SESSION_RESULT = "UNSUPPORTED_SESSION"
MEMBER_RESULT_STATUSES = frozenset(
    {
        NOT_EVALUATED_POLICY,
        PROVIDER_BOUND,
        WAITING_READINESS,
        BLOCKED_DATA,
        DATA_FAILURE,
        NO_LIFECYCLE_CHANGE,
        SETUP_PENDING,
        MISSED_ENTRY_RECORDED,
        SUCCESSOR_SETUP_CREATED,
        RESEARCH_PLAN_COMPOSED,
        EXPIRED_RESULT,
        UNSUPPORTED_SESSION_RESULT,
    }
)

DETERMINATE = "DETERMINATE"
AMBIGUOUS_SAME_BAR = "AMBIGUOUS_SAME_BAR"
CHRONOLOGY_STATES = frozenset({DETERMINATE, AMBIGUOUS_SAME_BAR})


class ContinuousCompositionError(ValueError):
    """Raised when composition evidence is malformed, contradictory, or unsafe."""


@dataclass(frozen=True)
class ContinuousCompositionPolicy:
    policy_version: str = CONTINUOUS_COMPOSITION_POLICY_VERSION
    required_recent_minute_bars: int = 5
    required_daily_evidence: bool = True
    minimum_history_sessions: int = 5
    maximum_completed_bar_age_seconds: int = 180
    minimum_completed_bar_lag_seconds: int = 60
    schema_version: int = CONTINUOUS_COMPOSITION_SCHEMA_VERSION
    profile: str = CONTINUOUS_COMPOSITION_PROFILE

    @property
    def fingerprint(self) -> str:
        return _fingerprint(asdict(self))


@dataclass(frozen=True)
class ContinuousReadinessRequest:
    request_id: str
    symbol: str
    universe_member_id: str
    session_date: str
    requested_at: str
    required_minute_window_start: str
    required_minute_window_end: str
    required_daily_evidence: bool
    required_baseline_sessions: int
    requested_evidence_types: tuple[str, ...]
    priority_tier: str
    source_reason: str
    predecessor_request_id: str
    policy_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class CanonicalEvidenceInput:
    """Caller-supplied, already-reconciled evidence; this type never fetches it."""

    evidence_id: str
    symbol: str
    session_date: str
    provider_timestamp: str
    receipt_timestamp: str
    bars: tuple[CanonicalMinuteBar, ...]
    daily_evidence_id: str = ""
    daily_evidence_fingerprint: str = ""
    history_depth_sessions: int = 0
    fingerprint: str = ""

    @property
    def resolved_fingerprint(self) -> str:
        return self.fingerprint or _fingerprint(
            {
                "evidenceId": self.evidence_id,
                "symbol": self.symbol,
                "sessionDate": self.session_date,
                "providerTimestamp": self.provider_timestamp,
                "receiptTimestamp": self.receipt_timestamp,
                "bars": [asdict(item) for item in self.bars],
                "dailyEvidenceId": self.daily_evidence_id,
                "dailyEvidenceFingerprint": self.daily_evidence_fingerprint,
                "historyDepthSessions": self.history_depth_sessions,
            }
        )


@dataclass(frozen=True)
class ContinuousReadinessAssessment:
    universe_member_id: str
    symbol: str
    session_date: str
    evaluated_at: str
    minute_evidence_id: str
    minute_evidence_fingerprint: str
    daily_evidence_id: str
    daily_evidence_fingerprint: str
    rvol_evidence_id: str
    rvol_evidence_fingerprint: str
    latest_completed_minute: str
    candle_canonicality: str
    history_depth_sessions: int
    baseline_sufficiency: str
    gap_state: str
    stale_state: str
    status: str
    blocker_reasons: tuple[str, ...]
    policy_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class LifecycleTransitionInput:
    """A caller-observed lifecycle fact; composition does not infer price patterns."""

    next_state: str
    reason: str
    evidence_fingerprint: str
    source_identity: str
    material_delta_kind: str = SETUP_STATE_CHANGED


@dataclass(frozen=True)
class LifecycleTransitionProposal:
    opportunity_id: str
    symbol: str
    session_date: str
    previous_state: str
    next_state: str
    setup_id: str
    setup_family: str
    setup_sequence: int
    predecessor_setup_id: str
    create_new_setup: bool
    occurred_at: str
    provider_timestamp: str
    receipt_timestamp: str
    source_identity: str
    evidence_fingerprint: str
    material_delta_kind: str
    reason: str
    fingerprint: str


@dataclass(frozen=True)
class SuccessorSetupEvidence:
    """Chronology-valid research structure supplied by a future deterministic producer."""

    evidence_id: str
    evidence_fingerprint: str
    symbol: str
    session_date: str
    setup_family: str
    known_at: str
    source_level_kind: str
    planned_entry: float
    stop_price: float
    target_prices: tuple[float, ...]
    source_evidence_ids: tuple[str, ...]
    predecessor_setup_id: str = ""
    predecessor_terminal_state: str = ""
    successor_reason: str = ""
    chronology_state: str = DETERMINATE


@dataclass(frozen=True)
class CompositionMemberInput:
    universe_member_id: str
    canonical_evidence: CanonicalEvidenceInput | None = None
    rvol_evidence: TimeNormalizedRvolEvidence | None = None
    lifecycle: CandidateLifecycleSnapshot | None = None
    lifecycle_transition: LifecycleTransitionInput | None = None
    successor_setup: SuccessorSetupEvidence | None = None
    existing_plan: IntradayPlanEvidence | None = None


@dataclass(frozen=True)
class ContinuousCompositionMemberResult:
    universe_member_id: str
    symbol: str
    session_date: str
    disposition: str
    readiness_request: ContinuousReadinessRequest | None
    readiness_assessment: ContinuousReadinessAssessment | None
    lifecycle_proposal: LifecycleTransitionProposal | None
    intraday_plan: IntradayPlanEvidence | None
    blocker_reasons: tuple[str, ...]
    authority: str
    fingerprint: str


@dataclass(frozen=True)
class ContinuousCompositionSummary:
    members_presented: int
    readiness_requests: int
    ready: int
    waiting_readiness: int
    insufficient_history: int
    insufficient_rvol: int
    provider_bound: int
    data_failures: int
    no_lifecycle_change: int
    lifecycle_transitions: int
    missed_entries: int
    successor_setups: int
    plans_composed: int


@dataclass(frozen=True)
class ContinuousCompositionCycle:
    cycle_id: str
    session_date: str
    started_at: str
    evidence_cutoff: str
    universe_policy_fingerprint: str
    composition_policy_fingerprint: str
    member_results: tuple[ContinuousCompositionMemberResult, ...]
    summary: ContinuousCompositionSummary
    shared_failure_state: str
    fingerprint: str


def build_readiness_request(
    member: HotUniverseMember,
    *,
    requested_at: datetime,
    policy: ContinuousCompositionPolicy,
    source_reason: str = "CONTINUOUS_MEMBER_REEVALUATION",
    predecessor_request_id: str = "",
) -> ContinuousReadinessRequest:
    """Describe required evidence without contacting a provider or mutating state."""

    _validate_policy(policy)
    _validate_member(member)
    requested = _aware(requested_at, "Requested timestamp")
    _require_regular_session(requested, member.session_date)
    window_end = requested - timedelta(seconds=policy.minimum_completed_bar_lag_seconds)
    window_start = window_end - timedelta(minutes=policy.required_recent_minute_bars - 1)
    source = _text(source_reason, "Readiness source reason")
    predecessor = str(predecessor_request_id).strip()
    payload = {
        "symbol": member.symbol,
        "universe_member_id": member.member_id,
        "session_date": member.session_date,
        "requested_at": requested.isoformat(),
        "required_minute_window_start": window_start.isoformat(),
        "required_minute_window_end": window_end.isoformat(),
        "required_daily_evidence": policy.required_daily_evidence,
        "required_baseline_sessions": policy.minimum_history_sessions,
        "requested_evidence_types": (
            "SCHWAB_PRICE_HISTORY_RECONCILED_MINUTE",
            "DAILY_EVIDENCE",
            "TIME_NORMALIZED_RVOL",
        ),
        "priority_tier": member.current_tier,
        "source_reason": source,
        "predecessor_request_id": predecessor,
        "policy_fingerprint": policy.fingerprint,
    }
    fingerprint = _fingerprint(payload)
    return ContinuousReadinessRequest(
        request_id=f"continuous-readiness-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


def assess_readiness(
    request: ContinuousReadinessRequest,
    *,
    evidence: CanonicalEvidenceInput | None,
    rvol_evidence: TimeNormalizedRvolEvidence | None,
    evaluated_at: datetime,
    policy: ContinuousCompositionPolicy,
) -> ContinuousReadinessAssessment:
    """Assess only caller-provided reconciled evidence at the supplied cutoff."""

    _validate_policy(policy)
    _validate_request(request, policy)
    evaluated = _aware(evaluated_at, "Readiness evaluated timestamp")
    _require_regular_session(evaluated, request.session_date)
    if evaluated < _parse_timestamp(request.requested_at):
        raise ContinuousCompositionError("Readiness assessment predates its request.")
    if evidence is None:
        return _assessment(
            request,
            evaluated,
            status=WAITING_FOR_CANONICAL_BARS,
            blockers=("CANONICAL_EVIDENCE_NOT_SUPPLIED",),
        )
    _validate_evidence_identity(evidence, request, evaluated, policy)
    current = _current_session_bars(evidence, request.session_date)
    findings = _canonical_bar_findings(evidence, request, evaluated, policy)
    if findings:
        status = _status_from_bar_findings(findings)
        return _assessment(
            request,
            evaluated,
            evidence=evidence,
            rvol_evidence=rvol_evidence,
            status=status,
            blockers=tuple(findings),
            latest=_latest_timestamp(current),
        )
    if evidence.history_depth_sessions < policy.minimum_history_sessions:
        return _assessment(
            request,
            evaluated,
            evidence=evidence,
            rvol_evidence=rvol_evidence,
            status=INSUFFICIENT_HISTORY,
            blockers=("INSUFFICIENT_DAILY_HISTORY",),
            latest=_latest_timestamp(current),
        )
    if policy.required_daily_evidence and not (
        evidence.daily_evidence_id and _sha256(evidence.daily_evidence_fingerprint)
    ):
        return _assessment(
            request,
            evaluated,
            evidence=evidence,
            rvol_evidence=rvol_evidence,
            status=INSUFFICIENT_HISTORY,
            blockers=("DAILY_EVIDENCE_IDENTITY_REQUIRED",),
            latest=_latest_timestamp(current),
        )
    rvol_findings = _rvol_findings(rvol_evidence, request, evaluated)
    if rvol_findings:
        return _assessment(
            request,
            evaluated,
            evidence=evidence,
            rvol_evidence=rvol_evidence,
            status=INSUFFICIENT_RVOL_BASELINE,
            blockers=rvol_findings,
            latest=_latest_timestamp(current),
        )
    return _assessment(
        request,
        evaluated,
        evidence=evidence,
        rvol_evidence=rvol_evidence,
        status=READY,
        blockers=(),
        latest=_latest_timestamp(current),
    )


def compose_cycle(
    *,
    universe_state: HotUniverseState,
    member_inputs: Iterable[CompositionMemberInput],
    started_at: datetime,
    evidence_cutoff: datetime,
    policy: ContinuousCompositionPolicy,
) -> ContinuousCompositionCycle:
    """Compose one all-accounted research cycle without writing or invoking anything."""

    _validate_policy(policy)
    validate_hot_universe_state(universe_state)
    started = _aware(started_at, "Cycle started timestamp")
    cutoff = _aware(evidence_cutoff, "Cycle evidence cutoff")
    if cutoff < started:
        raise ContinuousCompositionError("Composition cutoff predates cycle start.")
    session_date = cutoff.astimezone(EASTERN_TZ).date().isoformat()
    _require_regular_session(cutoff, session_date)
    if universe_state.current_session_date != session_date:
        raise ContinuousCompositionError("Universe session does not match composition cutoff.")
    inputs = _inputs_by_member(member_inputs)
    members = tuple(
        item for item in universe_state.members if item.session_date == session_date
    )
    unknown = set(inputs).difference(item.member_id for item in members)
    if unknown:
        raise ContinuousCompositionError("Composition input referenced an unknown member.")
    results = tuple(
        _compose_member(
            member,
            inputs.get(member.member_id),
            cutoff=cutoff,
            policy=policy,
        )
        for member in sorted(members, key=lambda item: item.member_id)
    )
    summary = _summary(results)
    payload = {
        "session_date": session_date,
        "started_at": started.isoformat(),
        "evidence_cutoff": cutoff.isoformat(),
        "universe_policy_fingerprint": universe_state.policy_fingerprint,
        "composition_policy_fingerprint": policy.fingerprint,
        "member_results": results,
        "summary": summary,
        "shared_failure_state": "",
    }
    fingerprint = _fingerprint(
        {**payload, "member_results": [asdict(item) for item in results], "summary": asdict(summary)}
    )
    return ContinuousCompositionCycle(
        cycle_id=f"continuous-composition-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


def _compose_member(
    member: HotUniverseMember,
    item: CompositionMemberInput | None,
    *,
    cutoff: datetime,
    policy: ContinuousCompositionPolicy,
) -> ContinuousCompositionMemberResult:
    if member.current_state != TRACKED or member.current_tier == EXPIRED:
        return _member_result(member, EXPIRED_RESULT, blockers=("UNIVERSE_MEMBER_EXPIRED",))
    if member.current_tier == UNIVERSE_PROVIDER_BOUND:
        return _member_result(member, PROVIDER_BOUND, blockers=("READINESS_CAPACITY_PROVIDER_BOUND",))
    if member.current_tier == WARM:
        return _member_result(member, NOT_EVALUATED_POLICY, blockers=("WARM_MEMBER_NOT_SCHEDULED_FOR_SCARCE_READINESS",))
    if cutoff.astimezone(EASTERN_TZ).time() >= datetime.strptime("15:55", "%H:%M").time():
        return _member_result(member, EXPIRED_RESULT, blockers=("SAME_SESSION_FORCED_FLAT_BOUNDARY",))
    if item is None:
        request = build_readiness_request(member, requested_at=cutoff, policy=policy)
        assessment = assess_readiness(request, evidence=None, rvol_evidence=None, evaluated_at=cutoff, policy=policy)
        return _member_result(member, WAITING_READINESS, request=request, assessment=assessment, blockers=assessment.blocker_reasons)
    if item.universe_member_id != member.member_id:
        raise ContinuousCompositionError("Member composition identity mismatched its universe member.")
    request = build_readiness_request(member, requested_at=cutoff, policy=policy)
    assessment = assess_readiness(
        request,
        evidence=item.canonical_evidence,
        rvol_evidence=item.rvol_evidence,
        evaluated_at=cutoff,
        policy=policy,
    )
    if assessment.status != READY:
        disposition = {
            WAITING_FOR_CANONICAL_BARS: WAITING_READINESS,
            INSUFFICIENT_HISTORY: BLOCKED_DATA,
            INSUFFICIENT_RVOL_BASELINE: BLOCKED_DATA,
            UNSUPPORTED_SESSION: UNSUPPORTED_SESSION_RESULT,
        }.get(assessment.status, DATA_FAILURE)
        return _member_result(member, disposition, request=request, assessment=assessment, blockers=assessment.blocker_reasons)
    if member.current_tier == PROTECTED:
        return _member_result(member, NOT_EVALUATED_POLICY, request=request, assessment=assessment, blockers=("PROTECTED_RESOURCE_IS_NOT_AN_ENTRY_SIGNAL",))
    lifecycle = item.lifecycle
    if lifecycle is None:
        return _member_result(member, SETUP_PENDING, request=request, assessment=assessment, blockers=("CANDIDATE_LIFECYCLE_SNAPSHOT_REQUIRED",))
    _validate_lifecycle(member, lifecycle)
    if item.lifecycle_transition is not None:
        proposal = _proposal_from_transition(lifecycle, item.lifecycle_transition, assessment, cutoff)
        if proposal.next_state == ENTRY_MISSED:
            plan = _transition_existing_plan(item.existing_plan, PLAN_MISSED_ENTRY, cutoff)
            return _member_result(member, MISSED_ENTRY_RECORDED, request=request, assessment=assessment, proposal=proposal, plan=plan)
        return _member_result(member, SUCCESSOR_SETUP_CREATED, request=request, assessment=assessment, proposal=proposal)
    if item.successor_setup is None:
        return _member_result(member, NO_LIFECYCLE_CHANGE, request=request, assessment=assessment)
    successor = item.successor_setup
    _validate_successor(successor, member, lifecycle, cutoff)
    if successor.chronology_state == AMBIGUOUS_SAME_BAR:
        return _member_result(member, SETUP_PENDING, request=request, assessment=assessment, blockers=(AMBIGUOUS_SAME_BAR,))
    proposal = _proposal_from_successor(lifecycle, successor, assessment, cutoff)
    plan = _build_research_plan(successor, assessment, item.existing_plan, proposal, cutoff)
    return _member_result(member, RESEARCH_PLAN_COMPOSED, request=request, assessment=assessment, proposal=proposal, plan=plan)


def _build_research_plan(
    successor: SuccessorSetupEvidence,
    assessment: ContinuousReadinessAssessment,
    predecessor: IntradayPlanEvidence | None,
    proposal: LifecycleTransitionProposal,
    cutoff: datetime,
) -> IntradayPlanEvidence:
    if successor.predecessor_setup_id:
        if predecessor is None:
            raise ContinuousCompositionError("Successor setup requires a predecessor DATA-004 plan.")
        if intraday_plan_validation_findings(predecessor):
            raise ContinuousCompositionError("Successor plan predecessor DATA-004 evidence is invalid.")
        if predecessor.lifecycle_status not in {PLAN_MISSED_ENTRY, PLAN_EXPIRED, "INVALIDATED"}:
            raise ContinuousCompositionError("Successor plan predecessor is not terminal.")
        if predecessor.symbol != successor.symbol or predecessor.session_date != successor.session_date:
            raise ContinuousCompositionError("Successor plan predecessor identity mismatched.")
    elif predecessor is not None:
        raise ContinuousCompositionError("Initial setup cannot inherit a predecessor plan.")
    ids = tuple(dict.fromkeys((*successor.source_evidence_ids, assessment.minute_evidence_id, assessment.daily_evidence_id, assessment.rvol_evidence_id)))
    return build_intraday_plan_evidence(
        symbol=successor.symbol,
        setup_family=successor.setup_family,
        created_at=_parse_timestamp(successor.known_at),
        planned_entry=successor.planned_entry,
        stop_price=successor.stop_price,
        target_prices=successor.target_prices,
        source_setup_fingerprint=successor.evidence_fingerprint,
        source_level_kind=successor.source_level_kind,
        source_evidence_ids=ids,
        observed_price=None,
        predecessor=predecessor,
        replacement_reason=successor.successor_reason if predecessor is not None else "",
        lifecycle_status="PENDING_ENTRY",
    )


def _transition_existing_plan(plan: IntradayPlanEvidence | None, state: str, cutoff: datetime) -> IntradayPlanEvidence | None:
    if plan is None:
        return None
    return transition_intraday_plan(plan, lifecycle_status=state, observed_at=cutoff)


def _proposal_from_transition(
    lifecycle: CandidateLifecycleSnapshot,
    transition: LifecycleTransitionInput,
    assessment: ContinuousReadinessAssessment,
    cutoff: datetime,
) -> LifecycleTransitionProposal:
    if transition.next_state != ENTRY_MISSED:
        raise ContinuousCompositionError("Composition only accepts explicit missed-entry lifecycle observations.")
    if transition.next_state not in LEGAL_TRANSITIONS.get(lifecycle.current_state, frozenset()):
        raise ContinuousCompositionError("Lifecycle observation was not a legal existing lifecycle transition.")
    setup_id, family, sequence, predecessor = resolve_setup_identity(
        lifecycle,
        next_state=transition.next_state,
        requested_family="",
    )
    return _proposal(
        lifecycle,
        next_state=transition.next_state,
        setup_id=setup_id,
        setup_family=family,
        setup_sequence=sequence,
        predecessor_setup_id=predecessor,
        create_new_setup=False,
        evidence_fingerprint=transition.evidence_fingerprint,
        source_identity=transition.source_identity,
        material_delta_kind=transition.material_delta_kind,
        reason=transition.reason,
        assessment=assessment,
        cutoff=cutoff,
    )


def _proposal_from_successor(
    lifecycle: CandidateLifecycleSnapshot,
    successor: SuccessorSetupEvidence,
    assessment: ContinuousReadinessAssessment,
    cutoff: datetime,
) -> LifecycleTransitionProposal:
    next_state = {
        CONTINUATION_BREAKOUT: BREAKOUT_FORMING,
        PULLBACK: PULLBACK_FORMING,
        RECLAIM: RECLAIM_FORMING,
    }.get(successor.setup_family)
    if next_state is None:
        raise ContinuousCompositionError("Opening setup cannot be newly composed continuously.")
    if next_state not in LEGAL_TRANSITIONS.get(lifecycle.current_state, frozenset()):
        raise ContinuousCompositionError("Successor setup was not a legal existing lifecycle transition.")
    setup_id, family, sequence, predecessor = resolve_setup_identity(
        lifecycle,
        next_state=next_state,
        requested_family=successor.setup_family,
        create_new_setup=bool(lifecycle.current_setup_id),
    )
    if successor.predecessor_setup_id and predecessor != successor.predecessor_setup_id:
        raise ContinuousCompositionError("Successor setup predecessor identity mismatched lifecycle.")
    return _proposal(
        lifecycle,
        next_state=next_state,
        setup_id=setup_id,
        setup_family=family,
        setup_sequence=sequence,
        predecessor_setup_id=predecessor,
        create_new_setup=bool(lifecycle.current_setup_id),
        evidence_fingerprint=successor.evidence_fingerprint,
        source_identity="CALLER_SUPPLIED_RESEARCH_SUCCESSOR_EVIDENCE",
        material_delta_kind=SETUP_IDENTITY_CHANGED,
        reason=successor.successor_reason or "CHRONOLOGY_VALID_RESEARCH_SUCCESSOR",
        assessment=assessment,
        cutoff=cutoff,
    )


def _proposal(
    lifecycle: CandidateLifecycleSnapshot,
    *,
    next_state: str,
    setup_id: str,
    setup_family: str,
    setup_sequence: int,
    predecessor_setup_id: str,
    create_new_setup: bool,
    evidence_fingerprint: str,
    source_identity: str,
    material_delta_kind: str,
    reason: str,
    assessment: ContinuousReadinessAssessment,
    cutoff: datetime,
) -> LifecycleTransitionProposal:
    _sha256_or_raise(evidence_fingerprint, "Lifecycle evidence fingerprint")
    payload = {
        "opportunity_id": lifecycle.opportunity_id,
        "symbol": lifecycle.symbol,
        "session_date": lifecycle.session_date,
        "previous_state": lifecycle.current_state,
        "next_state": next_state,
        "setup_id": setup_id,
        "setup_family": setup_family,
        "setup_sequence": setup_sequence,
        "predecessor_setup_id": predecessor_setup_id,
        "create_new_setup": create_new_setup,
        "occurred_at": cutoff.isoformat(),
        "provider_timestamp": assessment.latest_completed_minute,
        "receipt_timestamp": assessment.evaluated_at,
        "source_identity": _text(source_identity, "Lifecycle source identity"),
        "evidence_fingerprint": evidence_fingerprint,
        "material_delta_kind": material_delta_kind,
        "reason": _text(reason, "Lifecycle reason"),
    }
    return LifecycleTransitionProposal(fingerprint=_fingerprint(payload), **payload)


def _validate_successor(successor: SuccessorSetupEvidence, member: HotUniverseMember, lifecycle: CandidateLifecycleSnapshot, cutoff: datetime) -> None:
    if successor.symbol != member.symbol or successor.session_date != member.session_date:
        raise ContinuousCompositionError("Successor evidence identity mismatched universe member.")
    if successor.setup_family not in SUPPORTED_SETUP_FAMILIES - {OPENING_BREAKOUT}:
        raise ContinuousCompositionError("Successor setup family is unsupported.")
    if successor.chronology_state not in CHRONOLOGY_STATES:
        raise ContinuousCompositionError("Successor chronology state is unsupported.")
    known = _parse_timestamp(successor.known_at)
    if known > cutoff:
        raise ContinuousCompositionError("Successor evidence became known after composition cutoff.")
    _sha256_or_raise(successor.evidence_fingerprint, "Successor evidence fingerprint")
    if not successor.evidence_id or not successor.source_evidence_ids:
        raise ContinuousCompositionError("Successor evidence identity is incomplete.")
    if not _positive(successor.planned_entry) or not _positive(successor.stop_price) or successor.stop_price >= successor.planned_entry:
        raise ContinuousCompositionError("Successor plan levels are invalid.")
    if not successor.target_prices or any(not _positive(item) or item <= successor.planned_entry for item in successor.target_prices):
        raise ContinuousCompositionError("Successor target levels are invalid.")
    if successor.predecessor_setup_id:
        if lifecycle.current_setup_id != successor.predecessor_setup_id:
            raise ContinuousCompositionError("Successor evidence did not extend current setup identity.")
        if lifecycle.current_state not in {ENTRY_MISSED, FAILED_BREAKOUT, INVALIDATED}:
            raise ContinuousCompositionError("Successor evidence requires a terminal predecessor lifecycle state.")
        if successor.predecessor_terminal_state != lifecycle.current_state:
            raise ContinuousCompositionError("Successor terminal predecessor state mismatched lifecycle.")
    elif lifecycle.current_setup_id:
        raise ContinuousCompositionError("A replacement setup must name its predecessor setup identity.")


def _validate_lifecycle(member: HotUniverseMember, lifecycle: CandidateLifecycleSnapshot) -> None:
    if lifecycle.symbol != member.symbol or lifecycle.session_date != member.session_date:
        raise ContinuousCompositionError("Lifecycle snapshot identity mismatched universe member.")
    if not lifecycle.opportunity_id or not lifecycle.latest_event_id or not _sha256(lifecycle.latest_evidence_fingerprint):
        raise ContinuousCompositionError("Lifecycle snapshot identity is incomplete.")


def _validate_evidence_identity(evidence: CanonicalEvidenceInput, request: ContinuousReadinessRequest, evaluated: datetime, policy: ContinuousCompositionPolicy) -> None:
    if evidence.symbol != request.symbol or evidence.session_date != request.session_date:
        raise ContinuousCompositionError("Canonical evidence identity mismatched readiness request.")
    if not evidence.evidence_id or evidence.history_depth_sessions < 0:
        raise ContinuousCompositionError("Canonical evidence identity is incomplete.")
    if evidence.fingerprint and not _sha256(evidence.fingerprint):
        raise ContinuousCompositionError("Canonical evidence fingerprint was invalid.")
    provider = _parse_timestamp(evidence.provider_timestamp)
    receipt = _parse_timestamp(evidence.receipt_timestamp)
    if provider > evaluated or receipt > evaluated:
        raise ContinuousCompositionError("Canonical evidence arrived after assessment cutoff.")
    if policy.required_daily_evidence and evidence.daily_evidence_fingerprint and not _sha256(evidence.daily_evidence_fingerprint):
        raise ContinuousCompositionError("Daily evidence fingerprint was invalid.")


def _canonical_bar_findings(evidence: CanonicalEvidenceInput, request: ContinuousReadinessRequest, evaluated: datetime, policy: ContinuousCompositionPolicy) -> tuple[str, ...]:
    bars = evidence.bars
    if not bars:
        return ("CANONICAL_CURRENT_SESSION_BARS_MISSING",)
    parsed: dict[datetime, CanonicalMinuteBar] = {}
    for bar in bars:
        timestamp = _parse_timestamp(bar.timestamp)
        if bar.symbol != request.symbol or bar.session_date != request.session_date:
            return ("CANONICAL_BAR_IDENTITY_MISMATCH",)
        if bar.source != SCHWAB_PRICE_HISTORY_SOURCE or bar.state not in CANONICAL_OUTCOME_STATES:
            return ("CANONICAL_RECONCILED_SCHWAB_BAR_REQUIRED",)
        if timestamp.astimezone(EASTERN_TZ).date().isoformat() != request.session_date:
            return ("CANONICAL_BAR_SESSION_MISMATCH",)
        if not _is_regular_timestamp(timestamp) or timestamp >= evaluated:
            return ("CANONICAL_BAR_OUTSIDE_COMPLETED_CUTOFF",)
        if timestamp + timedelta(seconds=policy.minimum_completed_bar_lag_seconds) > evaluated:
            return ("CANONICAL_BAR_NOT_YET_COMPLETE",)
        if timestamp + timedelta(seconds=policy.minimum_completed_bar_lag_seconds) > _parse_timestamp(evidence.receipt_timestamp):
            return ("CANONICAL_BAR_RECEIVED_BEFORE_COMPLETION",)
        values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
        if any(not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(float(item)) for item in values):
            return ("CANONICAL_BAR_OHLCV_INVALID",)
        if min(float(bar.open), float(bar.high), float(bar.low), float(bar.close)) <= 0 or float(bar.volume) < 0:
            return ("CANONICAL_BAR_OHLCV_INVALID",)
        if float(bar.high) < max(float(bar.open), float(bar.low), float(bar.close)) or float(bar.low) > min(float(bar.open), float(bar.high), float(bar.close)):
            return ("CANONICAL_BAR_OHLC_INVALID",)
        if timestamp in parsed:
            return ("DUPLICATE_CANONICAL_BAR_IDENTITY",)
        parsed[timestamp] = bar
    latest = max(parsed)
    if (evaluated - latest).total_seconds() > policy.maximum_completed_bar_age_seconds:
        return ("CANONICAL_EVIDENCE_STALE",)
    expected_end = _parse_timestamp(request.required_minute_window_end).replace(second=0, microsecond=0)
    if latest < expected_end:
        return ("CANONICAL_RECENT_WINDOW_NOT_READY",)
    expected = tuple(expected_end - timedelta(minutes=index) for index in range(policy.required_recent_minute_bars - 1, -1, -1))
    missing = tuple(item for item in expected if item not in parsed)
    if missing:
        return ("CANONICAL_CURRENT_WINDOW_GAPPED",)
    return ()


def _rvol_findings(rvol: TimeNormalizedRvolEvidence | None, request: ContinuousReadinessRequest, evaluated: datetime) -> tuple[str, ...]:
    if rvol is None:
        return ("TIME_NORMALIZED_RVOL_NOT_SUPPLIED",)
    if rvol.symbol != request.symbol or rvol.session_date != request.session_date:
        return ("TIME_NORMALIZED_RVOL_IDENTITY_MISMATCH",)
    if not rvol.execution_eligible:
        return ("TIME_NORMALIZED_RVOL_INSUFFICIENT_OR_UNSAFE",)
    through = _parse_timestamp(rvol.through_minute)
    if through > evaluated:
        return ("TIME_NORMALIZED_RVOL_LOOKAHEAD",)
    if rvol.baseline_session_count < request.required_baseline_sessions:
        return ("TIME_NORMALIZED_RVOL_BASELINE_INSUFFICIENT",)
    return ()


def _assessment(request: ContinuousReadinessRequest, evaluated: datetime, *, status: str, blockers: tuple[str, ...], evidence: CanonicalEvidenceInput | None = None, rvol_evidence: TimeNormalizedRvolEvidence | None = None, latest: str = "") -> ContinuousReadinessAssessment:
    if status not in READINESS_STATUSES:
        raise ContinuousCompositionError("Readiness status is unsupported.")
    minute_id = evidence.evidence_id if evidence else ""
    minute_fp = evidence.resolved_fingerprint if evidence else ""
    rvol_id = _rvol_id(rvol_evidence)
    rvol_fp = _rvol_fingerprint(rvol_evidence)
    payload = {
        "universe_member_id": request.universe_member_id,
        "symbol": request.symbol,
        "session_date": request.session_date,
        "evaluated_at": evaluated.isoformat(),
        "minute_evidence_id": minute_id,
        "minute_evidence_fingerprint": minute_fp,
        "daily_evidence_id": evidence.daily_evidence_id if evidence else "",
        "daily_evidence_fingerprint": evidence.daily_evidence_fingerprint if evidence else "",
        "rvol_evidence_id": rvol_id,
        "rvol_evidence_fingerprint": rvol_fp,
        "latest_completed_minute": latest,
        "candle_canonicality": "RECONCILED_SCHWAB_PRICE_HISTORY" if evidence else "UNAVAILABLE",
        "history_depth_sessions": evidence.history_depth_sessions if evidence else 0,
        "baseline_sufficiency": "SUFFICIENT" if rvol_evidence and rvol_evidence.execution_eligible else "INSUFFICIENT",
        "gap_state": "NO_GAP_IN_REQUIRED_WINDOW" if status == READY else "UNKNOWN_OR_GAPPED",
        "stale_state": "CURRENT" if status == READY else "UNKNOWN_OR_STALE",
        "status": status,
        "blocker_reasons": tuple(dict.fromkeys(blockers)),
        "policy_fingerprint": request.policy_fingerprint,
    }
    return ContinuousReadinessAssessment(fingerprint=_fingerprint(payload), **payload)


def _member_result(member: HotUniverseMember, disposition: str, *, request: ContinuousReadinessRequest | None = None, assessment: ContinuousReadinessAssessment | None = None, proposal: LifecycleTransitionProposal | None = None, plan: IntradayPlanEvidence | None = None, blockers: tuple[str, ...] = ()) -> ContinuousCompositionMemberResult:
    if disposition not in MEMBER_RESULT_STATUSES:
        raise ContinuousCompositionError("Composition member disposition is unsupported.")
    payload = {
        "universe_member_id": member.member_id,
        "symbol": member.symbol,
        "session_date": member.session_date,
        "disposition": disposition,
        "readiness_request": request,
        "readiness_assessment": assessment,
        "lifecycle_proposal": proposal,
        "intraday_plan": plan,
        "blocker_reasons": tuple(dict.fromkeys(blockers)),
        "authority": EXECUTION_AUTHORITY_NONE,
    }
    return ContinuousCompositionMemberResult(fingerprint=_fingerprint(payload), **payload)


def _summary(results: tuple[ContinuousCompositionMemberResult, ...]) -> ContinuousCompositionSummary:
    return ContinuousCompositionSummary(
        members_presented=len(results),
        readiness_requests=sum(item.readiness_request is not None for item in results),
        ready=sum(item.readiness_assessment is not None and item.readiness_assessment.status == READY for item in results),
        waiting_readiness=sum(item.disposition == WAITING_READINESS for item in results),
        insufficient_history=sum(item.readiness_assessment is not None and item.readiness_assessment.status == INSUFFICIENT_HISTORY for item in results),
        insufficient_rvol=sum(item.readiness_assessment is not None and item.readiness_assessment.status == INSUFFICIENT_RVOL_BASELINE for item in results),
        provider_bound=sum(item.disposition == PROVIDER_BOUND for item in results),
        data_failures=sum(item.disposition == DATA_FAILURE for item in results),
        no_lifecycle_change=sum(item.disposition == NO_LIFECYCLE_CHANGE for item in results),
        lifecycle_transitions=sum(item.lifecycle_proposal is not None for item in results),
        missed_entries=sum(item.disposition == MISSED_ENTRY_RECORDED for item in results),
        successor_setups=sum(item.disposition in {SUCCESSOR_SETUP_CREATED, RESEARCH_PLAN_COMPOSED} and item.lifecycle_proposal is not None and bool(item.lifecycle_proposal.predecessor_setup_id) for item in results),
        plans_composed=sum(item.disposition == RESEARCH_PLAN_COMPOSED for item in results),
    )


def _inputs_by_member(items: Iterable[CompositionMemberInput]) -> dict[str, CompositionMemberInput]:
    result: dict[str, CompositionMemberInput] = {}
    for item in items:
        key = _text(item.universe_member_id, "Composition member identity")
        if key in result:
            raise ContinuousCompositionError("Composition member was supplied more than once.")
        result[key] = item
    return result


def _validate_policy(policy: ContinuousCompositionPolicy) -> None:
    if policy.policy_version != CONTINUOUS_COMPOSITION_POLICY_VERSION or policy.schema_version != CONTINUOUS_COMPOSITION_SCHEMA_VERSION or policy.profile != CONTINUOUS_COMPOSITION_PROFILE:
        raise ContinuousCompositionError("Composition policy contract is unsupported.")
    if policy.required_recent_minute_bars < 1 or policy.minimum_history_sessions < 1 or policy.maximum_completed_bar_age_seconds < 60 or policy.minimum_completed_bar_lag_seconds < 1:
        raise ContinuousCompositionError("Composition policy values are invalid.")


def _validate_member(member: HotUniverseMember) -> None:
    if not member.member_id or not member.symbol or not member.session_date:
        raise ContinuousCompositionError("Hot-universe member identity is incomplete.")


def _validate_request(request: ContinuousReadinessRequest, policy: ContinuousCompositionPolicy) -> None:
    if not request.request_id or request.policy_fingerprint != policy.fingerprint:
        raise ContinuousCompositionError("Readiness request policy identity mismatched.")
    expected = build_readiness_request(
        HotUniverseMember(
            member_id=request.universe_member_id,
            symbol=request.symbol,
            session_date=request.session_date,
            membership_generation=1,
            first_observed_at=request.requested_at,
            last_observed_at=request.requested_at,
            first_discovery_snapshot_id="x",
            latest_discovery_snapshot_id="x",
            first_candidate_identity="x",
            latest_candidate_identity="x",
            latest_source_row_id="x",
            admission_reason="x",
            current_tier=request.priority_tier,
            current_state=TRACKED,
            source_observation_count=1,
            consecutive_absent_observations=0,
            consecutive_rejected_observations=0,
            last_qualified_at=request.requested_at,
            last_rejected_at="",
            last_source_seen_at=request.requested_at,
            active_setup_ids=(),
            terminal_setup_count=0,
            protected_reason="",
            priority_inputs=(),
            capacity_disposition="x",
            provider_bound_since="",
            provider_bound_observation_count=0,
            expires_at="",
            predecessor_fingerprint="",
        ),
        requested_at=_parse_timestamp(request.requested_at),
        policy=policy,
        source_reason=request.source_reason,
        predecessor_request_id=request.predecessor_request_id,
    )
    if request != expected:
        raise ContinuousCompositionError("Readiness request fingerprint contradicted content.")


def _status_from_bar_findings(findings: tuple[str, ...]) -> str:
    code = findings[0]
    if code in {"CANONICAL_CURRENT_SESSION_BARS_MISSING", "CANONICAL_RECENT_WINDOW_NOT_READY"}:
        return WAITING_FOR_CANONICAL_BARS
    if code == "CANONICAL_EVIDENCE_STALE":
        return STALE_EVIDENCE
    if code == "CANONICAL_CURRENT_WINDOW_GAPPED":
        return GAPPED_EVIDENCE
    return DATA_UNSAFE


def _current_session_bars(evidence: CanonicalEvidenceInput, session_date: str) -> tuple[CanonicalMinuteBar, ...]:
    return tuple(item for item in evidence.bars if item.session_date == session_date)


def _latest_timestamp(bars: tuple[CanonicalMinuteBar, ...]) -> str:
    return max((item.timestamp for item in bars), default="")


def _rvol_id(rvol: TimeNormalizedRvolEvidence | None) -> str:
    if rvol is None:
        return ""
    return f"time-normalized-rvol:{rvol.symbol}:{rvol.session_date}:{rvol.through_minute}"


def _rvol_fingerprint(rvol: TimeNormalizedRvolEvidence | None) -> str:
    return _fingerprint(asdict(rvol)) if rvol is not None else ""


def _is_regular_timestamp(value: datetime) -> bool:
    eastern = value.astimezone(EASTERN_TZ)
    return datetime.strptime("09:30", "%H:%M").time() <= eastern.time() < datetime.strptime("16:00", "%H:%M").time()


def _require_regular_session(value: datetime, session_date: str) -> None:
    eastern = value.astimezone(EASTERN_TZ)
    if eastern.date().isoformat() != session_date or not _is_regular_timestamp(value):
        raise ContinuousCompositionError("Continuous composition supports same-session regular hours only.")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContinuousCompositionError("Timestamp was invalid.") from exc
    return _aware(parsed, "Timestamp")


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContinuousCompositionError(f"{label} must be timezone-aware.")
    return value.astimezone(EASTERN_TZ)


def _text(value: object, label: str) -> str:
    result = str(value).strip()
    if not result:
        raise ContinuousCompositionError(f"{label} is required.")
    return result


def _sha256(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(item in "0123456789abcdef" for item in text)


def _sha256_or_raise(value: object, label: str) -> None:
    if not _sha256(value):
        raise ContinuousCompositionError(f"{label} must be a lowercase SHA-256.")


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 0


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _canonical(value: object) -> object:
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value
