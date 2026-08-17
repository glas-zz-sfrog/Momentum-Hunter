"""Provider-neutral, prospective opportunity-denominator research contract.

The module records immutable facts supplied by callers. It has no provider,
account, broker, order, scheduler, service, UI, or production-root capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from momentum_hunter.specialist_opinion import (
    EvidenceReference,
    SpecialistOpinion,
    SpecialistOpinionError,
    validate_opinion_target_identity,
    validate_specialist_opinion,
)


CONTRACT_VERSION = 1
SAMPLE_IDENTITY = "opportunity-denominator-research-v1"
POLICY_VERSION = "opportunity-denominator-policy-v1"
SAMPLE_STATUS = "INACTIVE_NOT_ACTIVATED"
RESEARCH_ONLY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY_NONE = "EXECUTION_AUTHORITY_NONE"

PROSPECTIVE = "PROSPECTIVE"
RETROSPECTIVE_RESEARCH_EXAMPLE = "RETROSPECTIVE_RESEARCH_EXAMPLE"
SYNTHETIC_TEST = "SYNTHETIC_TEST"
LIVE_READ_ONLY_QUALIFICATION = "LIVE_READ_ONLY_QUALIFICATION"
OBSERVATION_MODES = frozenset(
    {
        PROSPECTIVE,
        RETROSPECTIVE_RESEARCH_EXAMPLE,
        SYNTHETIC_TEST,
        LIVE_READ_ONLY_QUALIFICATION,
    }
)

RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"
SECURITY_IDENTITY_STATUSES = frozenset({RESOLVED, UNRESOLVED})

MOMENTUM_CANDIDATE = "MOMENTUM_CANDIDATE"
RANK_ALTERNATIVE = "RANK_ALTERNATIVE"
CONTINUOUS_INTRADAY_OPPORTUNITY = "CONTINUOUS_INTRADAY_OPPORTUNITY"
SPECIALIST_NOMINATION = "SPECIALIST_NOMINATION"
STRATEGY_REJECT = "STRATEGY_REJECT"
PROVIDER_BOUND_ROW = "PROVIDER_BOUND_ROW"
ORIGIN_KINDS = frozenset(
    {
        MOMENTUM_CANDIDATE,
        RANK_ALTERNATIVE,
        CONTINUOUS_INTRADAY_OPPORTUNITY,
        SPECIALIST_NOMINATION,
        STRATEGY_REJECT,
        PROVIDER_BOUND_ROW,
    }
)

ELIGIBLE_SELECTED = "ELIGIBLE_SELECTED"
ELIGIBLE_NOT_SELECTED = "ELIGIBLE_NOT_SELECTED"
REJECTED_STRATEGY = "REJECTED_STRATEGY"
BLOCKED_DATA = "BLOCKED_DATA"
BLOCKED_RISK = "BLOCKED_RISK"
BLOCKED_PROVIDER_CAPABILITY = "BLOCKED_PROVIDER_CAPABILITY"
NOT_EVALUATED_PROVIDER_BOUND = "NOT_EVALUATED_PROVIDER_BOUND"
SYSTEM_FAILURE = "SYSTEM_FAILURE"
NO_ACTION_RESEARCH_ONLY = "NO_ACTION_RESEARCH_ONLY"
VETOED_BY_AUTHORIZED_REGIME_POLICY = "VETOED_BY_AUTHORIZED_REGIME_POLICY"
DISPOSITIONS = frozenset(
    {
        ELIGIBLE_SELECTED,
        ELIGIBLE_NOT_SELECTED,
        REJECTED_STRATEGY,
        BLOCKED_DATA,
        BLOCKED_RISK,
        BLOCKED_PROVIDER_CAPABILITY,
        NOT_EVALUATED_PROVIDER_BOUND,
        SYSTEM_FAILURE,
        NO_ACTION_RESEARCH_ONLY,
        VETOED_BY_AUTHORIZED_REGIME_POLICY,
    }
)

ACTUAL_SYSTEM_DECISION = "ACTUAL_SYSTEM_DECISION"
COUNTERFACTUAL_RESEARCH_OBSERVATION = "COUNTERFACTUAL_RESEARCH_OBSERVATION"
DECISION_CLASSES = frozenset(
    {ACTUAL_SYSTEM_DECISION, COUNTERFACTUAL_RESEARCH_OBSERVATION}
)

PRE_DECISION = "PRE_DECISION"
AT_DECISION = "AT_DECISION"
POST_DECISION_RESEARCH = "POST_DECISION_RESEARCH"
TIMING_RELATIONSHIPS = frozenset(
    {PRE_DECISION, AT_DECISION, POST_DECISION_RESEARCH}
)

MARKET_PATH = "MARKET_PATH"
BROKER_EXECUTION = "BROKER_EXECUTION"
DATA_QUALITY = "DATA_QUALITY"

TARGET_FIRST = "TARGET_FIRST"
STOP_FIRST = "STOP_FIRST"
TIMEOUT = "TIMEOUT"
INVALIDATED = "INVALIDATED"
AMBIGUOUS_SAME_BAR = "AMBIGUOUS_SAME_BAR"
DATA_FAILURE = "DATA_FAILURE"
UNTRIGGERED = "UNTRIGGERED"
MARKET_PATH_STATES = frozenset(
    {
        TARGET_FIRST,
        STOP_FIRST,
        TIMEOUT,
        INVALIDATED,
        AMBIGUOUS_SAME_BAR,
        DATA_FAILURE,
        UNTRIGGERED,
    }
)

FULL_FILL = "FULL_FILL"
PARTIAL_FILL = "PARTIAL_FILL"
UNFILLED = "UNFILLED"
CANCELLED = "CANCELLED"
REJECTED = "REJECTED"
EXECUTION_DATA_FAILURE = "EXECUTION_DATA_FAILURE"
BROKER_EXECUTION_STATES = frozenset(
    {FULL_FILL, PARTIAL_FILL, UNFILLED, CANCELLED, REJECTED, EXECUTION_DATA_FAILURE}
)

DENOMINATOR_INCOMPLETE = "DENOMINATOR_INCOMPLETE"
DATA_CONTRACT_FAILURE = "DATA_CONTRACT_FAILURE"
SYSTEM_DATA_FAILURE = "SYSTEM_DATA_FAILURE"
DATA_QUALITY_STATES = frozenset(
    {DATA_FAILURE, SYSTEM_FAILURE, DENOMINATOR_INCOMPLETE, DATA_CONTRACT_FAILURE, SYSTEM_DATA_FAILURE}
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[A-Z][A-Z0-9_]{0,95}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")


class OpportunityDenominatorError(RuntimeError):
    """Raised when denominator evidence is incomplete or contradictory."""


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: Any) -> str:
    return hashlib.sha256(
        _canonical_json({"domain": domain, "value": value})
    ).hexdigest()


def _record_fingerprint(payload: Mapping[str, Any]) -> str:
    value = dict(payload)
    value.pop("fingerprint", None)
    return _fingerprint("opportunity-denominator-record-v1", value)


FROZEN_POLICY: dict[str, Any] = {
    "contractVersion": CONTRACT_VERSION,
    "sampleIdentity": SAMPLE_IDENTITY,
    "sampleStatus": SAMPLE_STATUS,
    "admission": "COMPLETE_BOUNDED_SOURCE_ROWS_OR_EXPLICIT_INCOMPLETE_CYCLE",
    "baseRecords": "IMMUTABLE",
    "laterEvidence": "SEPARATE_WRITE_ONCE_ATTACHMENTS_AND_OUTCOMES",
    "securityIdentity": "TICKER_IS_NOT_DURABLE_SECURITY_ID",
    "counterfactual": "NEVER_RECLASSIFY_AS_ACTUAL_DECISION_OR_EXECUTION",
    "marketPath": "CANONICAL_CALLER_SUPPLIED_BARS_NO_POST_TERMINAL_LEAKAGE",
    "brokerExecution": "ACTUAL_PROVIDER_SUBMISSION_AND_FILL_EVIDENCE_ONLY",
    "historicalBackfill": "PROHIBITED",
    "executionAuthority": EXECUTION_AUTHORITY_NONE,
}
POLICY_FINGERPRINT = _fingerprint("opportunity-denominator-policy-v1", FROZEN_POLICY)


@dataclass(frozen=True)
class DenominatorPolicy:
    contract_version: int = CONTRACT_VERSION
    sample_identity: str = SAMPLE_IDENTITY
    policy_version: str = POLICY_VERSION
    policy_fingerprint: str = POLICY_FINGERPRINT
    status: str = SAMPLE_STATUS
    activated_at: str | None = None
    first_eligible_session_date: str | None = None
    historical_backfill_allowed: bool = False
    authority: str = RESEARCH_ONLY
    execution_authority: str = EXECUTION_AUTHORITY_NONE


@dataclass(frozen=True)
class OpportunitySeed:
    origin_kinds: tuple[str, ...]
    origin_record_id: str
    origin_fingerprint: str
    symbol: str
    security_identity_status: str
    security_id: str | None
    observed_at: str
    decision_cutoff: str
    candidate_id: str | None
    setup_id: str | None
    trade_plan_id: str | None
    rank: int | None
    evidence_refs: tuple[EvidenceReference, ...]
    disposition: str
    decision_class: str = ACTUAL_SYSTEM_DECISION
    blocker_reasons: tuple[str, ...] = field(default_factory=tuple)
    nominating_specialist_id: str | None = None
    nomination_opinion_fingerprint: str | None = None


@dataclass(frozen=True)
class OpportunityReference:
    opportunity_id: str
    opportunity_fingerprint: str


@dataclass(frozen=True)
class OpportunityRecord:
    contract_version: int
    sample_identity: str
    policy_fingerprint: str
    observation_mode: str
    cycle_id: str
    opportunity_id: str
    cycle_type: str
    session_date: str
    session_type: str
    origin_kinds: tuple[str, ...]
    origin_record_id: str
    origin_fingerprint: str
    symbol: str
    security_identity_status: str
    security_id: str | None
    observed_at: str
    decision_cutoff: str
    candidate_id: str | None
    setup_id: str | None
    trade_plan_id: str | None
    rank: int | None
    evidence_refs: tuple[EvidenceReference, ...]
    disposition: str
    decision_class: str
    blocker_reasons: tuple[str, ...]
    nominating_specialist_id: str | None
    nomination_opinion_fingerprint: str | None
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class OpportunityCycleRecord:
    contract_version: int
    sample_identity: str
    policy_fingerprint: str
    observation_mode: str
    cycle_id: str
    cycle_type: str
    session_date: str
    session_type: str
    observed_at: str
    decision_cutoff: str
    source_identity: str
    source_evidence_fingerprint: str
    raw_count: int
    parsed_count: int
    eligible_count: int
    rejected_count: int
    blocked_count: int
    not_evaluated_count: int
    complete_denominator: bool
    failure_reason: str | None
    opportunity_refs: tuple[OpportunityReference, ...]
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class SpecialistOpinionAttachment:
    contract_version: int
    sample_identity: str
    policy_fingerprint: str
    attachment_id: str
    opportunity_id: str
    opportunity_fingerprint: str
    specialist_opinion_id: str
    specialist_id: str
    specialist_version: str
    opinion_as_of: str
    attached_at: str
    timing_relationship: str
    opinion_fingerprint: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class MarketPathBar:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    evidence_id: str
    fingerprint: str


@dataclass(frozen=True)
class MarketPathOutcomeRecord:
    contract_version: int
    sample_identity: str
    policy_fingerprint: str
    outcome_id: str
    outcome_domain: str
    outcome_state: str
    opportunity_id: str
    opportunity_fingerprint: str
    observation_class: str
    entry_price: float
    stop_price: float
    target_price: float
    horizon_end: str
    triggered_at: str | None
    terminal_timestamp: str
    mfe: float | None
    mae: float | None
    time_to_target_minutes: float | None
    time_to_stop_minutes: float | None
    time_to_mfe_minutes: float | None
    time_to_mae_minutes: float | None
    observation_duration_minutes: float
    data_completeness: str
    bar_evidence_fingerprint: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class BrokerExecutionOutcomeRecord:
    contract_version: int
    sample_identity: str
    policy_fingerprint: str
    outcome_id: str
    outcome_domain: str
    outcome_state: str
    opportunity_id: str
    opportunity_fingerprint: str
    submission_id: str
    submission_fingerprint: str
    provider_evidence_id: str
    provider_evidence_fingerprint: str
    provider_order_status: str
    requested_quantity: float | None
    requested_notional: float | None
    filled_quantity: float
    average_fill_price: float | None
    fill_time: str | None
    remaining_quantity: float | None
    observed_at: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class DataQualityOutcomeRecord:
    contract_version: int
    sample_identity: str
    policy_fingerprint: str
    outcome_id: str
    outcome_domain: str
    outcome_state: str
    cycle_id: str
    cycle_fingerprint: str
    opportunity_id: str | None
    opportunity_fingerprint: str | None
    observed_at: str
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[EvidenceReference, ...]
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class DenominatorSummary:
    sample_identity: str
    policy_fingerprint: str
    sample_status: str
    prospective_sessions: int
    retrospective_cycles: int
    synthetic_cycles: int
    complete_cycles: int
    incomplete_cycles: int
    total_opportunities: int
    selected: int
    eligible_not_selected: int
    strategy_rejects: int
    risk_blocks: int
    data_blocks: int
    provider_bound: int
    system_failures: int
    specialist_attachments_by_type: Mapping[str, int]
    actual_executions: int
    unfilled: int
    counterfactual_observations: int


def current_policy() -> DenominatorPolicy:
    """Return the inactive, zero-observation prospective sample contract."""

    return DenominatorPolicy()


def build_cycle_bundle(
    *,
    cycle_type: str,
    session_date: str,
    session_type: str,
    observed_at: str,
    decision_cutoff: str,
    source_identity: str,
    source_evidence_fingerprint: str,
    raw_count: int,
    parsed_count: int,
    seeds: Iterable[OpportunitySeed],
    observation_mode: str,
    failure_reason: str | None = None,
    policy: DenominatorPolicy | None = None,
) -> tuple[OpportunityCycleRecord, tuple[OpportunityRecord, ...]]:
    """Freeze one bounded source cycle and every represented opportunity."""

    policy = policy or current_policy()
    _validate_policy(policy)
    mode = _mode(observation_mode)
    session = _session_date(session_date)
    observed = _timestamp(observed_at, "Observed timestamp")
    cutoff = _timestamp(decision_cutoff, "Decision cutoff")
    if _parse_timestamp(cutoff) < _parse_timestamp(observed):
        raise OpportunityDenominatorError("Decision cutoff precedes cycle observation.")
    if mode == PROSPECTIVE:
        _validate_prospective_admission(policy, session, observed)
    if type(raw_count) is not int or raw_count < 0:
        raise OpportunityDenominatorError("Raw count must be a non-negative integer.")
    if type(parsed_count) is not int or parsed_count < 0 or parsed_count > raw_count:
        raise OpportunityDenominatorError("Parsed count is inconsistent with raw count.")
    normalized_cycle_type = _token(cycle_type, "Cycle type")
    normalized_session_type = _token(session_type, "Session type")
    normalized_source = _identifier(source_identity, "Source identity")
    source_fp = _sha256(source_evidence_fingerprint, "Source fingerprint")
    cycle_identity_payload = {
        "sampleIdentity": policy.sample_identity,
        "policyFingerprint": policy.policy_fingerprint,
        "observationMode": mode,
        "cycleType": normalized_cycle_type,
        "sessionDate": session,
        "sessionType": normalized_session_type,
        "observedAt": observed,
        "decisionCutoff": cutoff,
        "sourceIdentity": normalized_source,
        "sourceEvidenceFingerprint": source_fp,
    }
    cycle_id = _fingerprint("opportunity-cycle-identity-v1", cycle_identity_payload)
    records = tuple(
        _build_opportunity(
            seed,
            policy=policy,
            observation_mode=mode,
            cycle_id=cycle_id,
            cycle_type=normalized_cycle_type,
            session_date=session,
            session_type=normalized_session_type,
        )
        for seed in seeds
    )
    if len({record.opportunity_id for record in records}) != len(records):
        raise OpportunityDenominatorError("Duplicate opportunity identity in cycle.")

    represented_count = len(records)
    complete = raw_count == parsed_count == represented_count and failure_reason is None
    normalized_failure = _optional_token(failure_reason, "Failure reason")
    if not complete:
        normalized_failure = normalized_failure or DENOMINATOR_INCOMPLETE
    elif normalized_failure is not None:
        raise OpportunityDenominatorError("A complete cycle cannot carry failure state.")
    dispositions = [record.disposition for record in records]
    refs = tuple(
        OpportunityReference(record.opportunity_id, record.fingerprint)
        for record in records
    )
    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "sample_identity": policy.sample_identity,
        "policy_fingerprint": policy.policy_fingerprint,
        "observation_mode": mode,
        "cycle_id": cycle_id,
        "cycle_type": normalized_cycle_type,
        "session_date": session,
        "session_type": normalized_session_type,
        "observed_at": observed,
        "decision_cutoff": cutoff,
        "source_identity": normalized_source,
        "source_evidence_fingerprint": source_fp,
        "raw_count": raw_count,
        "parsed_count": parsed_count,
        "eligible_count": sum(
            value in {ELIGIBLE_SELECTED, ELIGIBLE_NOT_SELECTED} for value in dispositions
        ),
        "rejected_count": dispositions.count(REJECTED_STRATEGY),
        "blocked_count": sum(
            value in {BLOCKED_DATA, BLOCKED_RISK, BLOCKED_PROVIDER_CAPABILITY, SYSTEM_FAILURE}
            for value in dispositions
        ),
        "not_evaluated_count": dispositions.count(NOT_EVALUATED_PROVIDER_BOUND),
        "complete_denominator": complete,
        "failure_reason": normalized_failure,
        "opportunity_refs": refs,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(_to_wire_value(payload))
    cycle = OpportunityCycleRecord(**payload)
    validate_cycle(cycle)
    return cycle, records


def _build_opportunity(
    seed: OpportunitySeed,
    *,
    policy: DenominatorPolicy,
    observation_mode: str,
    cycle_id: str,
    cycle_type: str,
    session_date: str,
    session_type: str,
) -> OpportunityRecord:
    if not isinstance(seed, OpportunitySeed):
        raise OpportunityDenominatorError("Opportunity seed is malformed.")
    origins = _tokens(seed.origin_kinds, "Origin kind")
    if not origins or any(value not in ORIGIN_KINDS for value in origins):
        raise OpportunityDenominatorError("Opportunity origin is missing or unsupported.")
    security_status = _token(seed.security_identity_status, "Security identity status")
    if security_status not in SECURITY_IDENTITY_STATUSES:
        raise OpportunityDenominatorError("Security identity status is unsupported.")
    security_id = _optional_identifier(seed.security_id, "Security identity")
    if security_status == RESOLVED and security_id is None:
        raise OpportunityDenominatorError("Resolved security identity requires proof identity.")
    if security_status == UNRESOLVED and security_id is not None:
        raise OpportunityDenominatorError(
            "Unresolved security identity cannot promote ticker to durable identity."
        )
    symbol = _symbol(seed.symbol)
    if security_status == RESOLVED and security_id is not None and security_id.upper() == symbol:
        raise OpportunityDenominatorError(
            "Ticker alone cannot be used as durable security identity."
        )
    observed = _timestamp(seed.observed_at, "Opportunity observed timestamp")
    cutoff = _timestamp(seed.decision_cutoff, "Opportunity decision cutoff")
    if _parse_timestamp(cutoff) < _parse_timestamp(observed):
        raise OpportunityDenominatorError("Opportunity cutoff precedes observation.")
    disposition = _token(seed.disposition, "Disposition")
    if disposition not in DISPOSITIONS:
        raise OpportunityDenominatorError("Opportunity disposition is unsupported.")
    decision_class = _token(seed.decision_class, "Decision class")
    if decision_class not in DECISION_CLASSES:
        raise OpportunityDenominatorError("Decision class is unsupported.")
    if decision_class == COUNTERFACTUAL_RESEARCH_OBSERVATION and disposition == ELIGIBLE_SELECTED:
        raise OpportunityDenominatorError("Counterfactual evidence cannot be selected as actual.")
    if disposition == VETOED_BY_AUTHORIZED_REGIME_POLICY:
        raise OpportunityDenominatorError(
            "No current regime specialist has authoritative veto capability."
        )
    candidate_id = _optional_identifier(seed.candidate_id, "Candidate identity")
    setup_id = _optional_sha256(seed.setup_id, "Setup identity")
    trade_plan_id = _optional_sha256(seed.trade_plan_id, "TradePlan identity")
    if trade_plan_id is not None and setup_id is None:
        raise OpportunityDenominatorError("TradePlan identity requires setup identity.")
    rank = seed.rank
    if rank is not None and (type(rank) is not int or rank < 1):
        raise OpportunityDenominatorError("Rank must be a positive integer.")
    references = _evidence_refs(seed.evidence_refs, cutoff=cutoff)
    blockers = _tokens(seed.blocker_reasons, "Blocker reason")
    nominator = _optional_token(seed.nominating_specialist_id, "Nominating specialist")
    nomination_fp = _optional_sha256(
        seed.nomination_opinion_fingerprint, "Nomination opinion fingerprint"
    )
    if SPECIALIST_NOMINATION in origins and (nominator is None or nomination_fp is None):
        raise OpportunityDenominatorError(
            "Specialist nomination requires specialist and opinion identity."
        )
    if SPECIALIST_NOMINATION not in origins and (nominator is not None or nomination_fp is not None):
        raise OpportunityDenominatorError("Nomination lineage requires specialist origin.")
    evidence_fp = _fingerprint(
        "opportunity-source-evidence-v1", [_evidence_to_wire(item) for item in references]
    )
    identity_payload = {
        "cycleId": cycle_id,
        "originKinds": list(origins),
        "originRecordId": _identifier(seed.origin_record_id, "Origin record identity"),
        "originFingerprint": _sha256(seed.origin_fingerprint, "Origin fingerprint"),
        "symbol": symbol,
        "observedAt": observed,
        "decisionCutoff": cutoff,
        "candidateId": candidate_id,
        "setupId": setup_id,
        "tradePlanId": trade_plan_id,
        "rank": rank,
        "evidenceFingerprint": evidence_fp,
    }
    opportunity_id = _fingerprint("opportunity-identity-v1", identity_payload)
    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "sample_identity": policy.sample_identity,
        "policy_fingerprint": policy.policy_fingerprint,
        "observation_mode": observation_mode,
        "cycle_id": cycle_id,
        "opportunity_id": opportunity_id,
        "cycle_type": cycle_type,
        "session_date": session_date,
        "session_type": session_type,
        "origin_kinds": origins,
        "origin_record_id": identity_payload["originRecordId"],
        "origin_fingerprint": identity_payload["originFingerprint"],
        "symbol": symbol,
        "security_identity_status": security_status,
        "security_id": security_id,
        "observed_at": observed,
        "decision_cutoff": cutoff,
        "candidate_id": candidate_id,
        "setup_id": setup_id,
        "trade_plan_id": trade_plan_id,
        "rank": rank,
        "evidence_refs": references,
        "disposition": disposition,
        "decision_class": decision_class,
        "blocker_reasons": blockers,
        "nominating_specialist_id": nominator,
        "nomination_opinion_fingerprint": nomination_fp,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(_to_wire_value(payload))
    record = OpportunityRecord(**payload)
    validate_opportunity(record)
    return record


def build_specialist_attachment(
    *,
    opportunity: OpportunityRecord,
    opinion: SpecialistOpinion,
    opinion_symbol: str,
    attached_at: str,
) -> SpecialistOpinionAttachment:
    """Attach one immutable common-contract opinion to an exact opportunity chain."""

    validate_opportunity(opportunity)
    try:
        validate_specialist_opinion(opinion)
        validate_opinion_target_identity(
            opinion,
            opportunity_id=opportunity.opportunity_id,
            candidate_id=opportunity.candidate_id,
            setup_id=opportunity.setup_id,
            trade_plan_id=opportunity.trade_plan_id,
        )
    except SpecialistOpinionError as exc:
        raise OpportunityDenominatorError(str(exc)) from exc
    if _symbol(opinion_symbol) != opportunity.symbol:
        raise OpportunityDenominatorError("Specialist opinion symbol does not match opportunity.")
    attached = _timestamp(attached_at, "Attachment timestamp")
    opinion_time = _timestamp(opinion.as_of, "Opinion timestamp")
    if _parse_timestamp(opinion_time) > _parse_timestamp(attached):
        raise OpportunityDenominatorError("Future-dated specialist opinion cannot be attached.")
    if _parse_timestamp(opinion_time) < _parse_timestamp(opportunity.decision_cutoff):
        relationship = PRE_DECISION
    elif opinion_time == opportunity.decision_cutoff:
        relationship = AT_DECISION
    else:
        relationship = POST_DECISION_RESEARCH
    identity = _fingerprint(
        "specialist-opinion-attachment-identity-v1",
        {
            "opportunityId": opportunity.opportunity_id,
            "opinionId": opinion.opinion_id,
            "opinionFingerprint": opinion.fingerprint,
            "attachedAt": attached,
            "timingRelationship": relationship,
        },
    )
    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "sample_identity": opportunity.sample_identity,
        "policy_fingerprint": opportunity.policy_fingerprint,
        "attachment_id": identity,
        "opportunity_id": opportunity.opportunity_id,
        "opportunity_fingerprint": opportunity.fingerprint,
        "specialist_opinion_id": opinion.opinion_id,
        "specialist_id": opinion.specialist_id,
        "specialist_version": opinion.specialist_version,
        "opinion_as_of": opinion_time,
        "attached_at": attached,
        "timing_relationship": relationship,
        "opinion_fingerprint": opinion.fingerprint,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(payload)
    return SpecialistOpinionAttachment(**payload)


def build_market_path_outcome(
    *,
    opportunity: OpportunityRecord,
    bars: Sequence[MarketPathBar],
    entry_price: float,
    stop_price: float,
    target_price: float,
    horizon_end: str,
    observation_class: str,
) -> MarketPathOutcomeRecord:
    """Adjudicate a long market path without inferring a broker execution."""

    validate_opportunity(opportunity)
    classification = _token(observation_class, "Observation class")
    if classification not in DECISION_CLASSES:
        raise OpportunityDenominatorError("Market-path observation class is unsupported.")
    if opportunity.disposition != ELIGIBLE_SELECTED and classification != COUNTERFACTUAL_RESEARCH_OBSERVATION:
        raise OpportunityDenominatorError("A nonselected opportunity path must remain counterfactual.")
    entry = _positive(entry_price, "Entry price")
    stop = _positive(stop_price, "Stop price")
    target = _positive(target_price, "Target price")
    if not stop < entry < target:
        raise OpportunityDenominatorError("Long market-path levels are contradictory.")
    horizon = _timestamp(horizon_end, "Market-path horizon")
    if _parse_timestamp(horizon) < _parse_timestamp(opportunity.decision_cutoff):
        raise OpportunityDenominatorError("Market-path horizon precedes opportunity cutoff.")
    ordered = tuple(sorted((_validate_bar(item) for item in bars), key=lambda item: item.timestamp))
    if any(
        _parse_timestamp(item.timestamp) < _parse_timestamp(opportunity.observed_at)
        for item in ordered
    ):
        raise OpportunityDenominatorError("Market-path evidence predates opportunity.")
    if len({item.timestamp for item in ordered}) != len(ordered):
        raise OpportunityDenominatorError("Duplicate market-path bar timestamp.")
    in_horizon = tuple(
        item for item in ordered if _parse_timestamp(item.timestamp) <= _parse_timestamp(horizon)
    )
    complete = bool(in_horizon) and _parse_timestamp(in_horizon[-1].timestamp) >= _parse_timestamp(horizon)
    triggered_index: int | None = None
    terminal_index: int | None = None
    state: str | None = None
    for index, bar in enumerate(in_horizon):
        if triggered_index is None:
            if bar.low <= stop and bar.high < entry:
                state, terminal_index = INVALIDATED, index
                break
            if bar.high >= entry:
                triggered_index = index
                if bar.low <= stop:
                    state, terminal_index = AMBIGUOUS_SAME_BAR, index
                    break
        if triggered_index is not None:
            hit_target = bar.high >= target
            hit_stop = bar.low <= stop
            if hit_target and hit_stop:
                state, terminal_index = AMBIGUOUS_SAME_BAR, index
                break
            if hit_target:
                state, terminal_index = TARGET_FIRST, index
                break
            if hit_stop:
                state, terminal_index = STOP_FIRST, index
                break
    if state is None:
        if not complete:
            state = DATA_FAILURE
            terminal_index = len(in_horizon) - 1 if in_horizon else None
        elif triggered_index is None:
            state, terminal_index = UNTRIGGERED, len(in_horizon) - 1
        else:
            state, terminal_index = TIMEOUT, len(in_horizon) - 1
    terminal_timestamp = (
        in_horizon[terminal_index].timestamp
        if terminal_index is not None
        else opportunity.decision_cutoff
    )
    triggered_at = (
        in_horizon[triggered_index].timestamp if triggered_index is not None else None
    )
    metric_bars: tuple[MarketPathBar, ...] = ()
    if triggered_index is not None and terminal_index is not None:
        metric_bars = in_horizon[triggered_index : terminal_index + 1]
    mfe = mae = None
    time_to_mfe = time_to_mae = None
    time_to_target = time_to_stop = None
    if metric_bars:
        highest = max(metric_bars, key=lambda item: item.high)
        lowest = min(metric_bars, key=lambda item: item.low)
        mfe = round(highest.high - entry, 8)
        mae = round(entry - lowest.low, 8)
        time_to_mfe = _minutes(triggered_at, highest.timestamp)
        time_to_mae = _minutes(triggered_at, lowest.timestamp)
        if state == TARGET_FIRST:
            time_to_target = _minutes(triggered_at, terminal_timestamp)
        elif state == STOP_FIRST:
            time_to_stop = _minutes(triggered_at, terminal_timestamp)
    terminal_bars = (
        in_horizon[: terminal_index + 1] if terminal_index is not None else ()
    )
    bar_fp = _fingerprint(
        "market-path-bars-v1", [_to_wire_value(asdict(item)) for item in terminal_bars]
    )
    identity = _fingerprint(
        "market-path-outcome-identity-v1",
        {
            "opportunityId": opportunity.opportunity_id,
            "entry": entry,
            "stop": stop,
            "target": target,
            "horizon": horizon,
            "barEvidenceFingerprint": bar_fp,
            "observationClass": classification,
        },
    )
    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "sample_identity": opportunity.sample_identity,
        "policy_fingerprint": opportunity.policy_fingerprint,
        "outcome_id": identity,
        "outcome_domain": MARKET_PATH,
        "outcome_state": state,
        "opportunity_id": opportunity.opportunity_id,
        "opportunity_fingerprint": opportunity.fingerprint,
        "observation_class": classification,
        "entry_price": entry,
        "stop_price": stop,
        "target_price": target,
        "horizon_end": horizon,
        "triggered_at": triggered_at,
        "terminal_timestamp": terminal_timestamp,
        "mfe": mfe,
        "mae": mae,
        "time_to_target_minutes": time_to_target,
        "time_to_stop_minutes": time_to_stop,
        "time_to_mfe_minutes": time_to_mfe,
        "time_to_mae_minutes": time_to_mae,
        "observation_duration_minutes": _minutes(opportunity.decision_cutoff, terminal_timestamp),
        "data_completeness": "COMPLETE" if complete else "INCOMPLETE",
        "bar_evidence_fingerprint": bar_fp,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(payload)
    return MarketPathOutcomeRecord(**payload)


def build_broker_execution_outcome(
    *,
    opportunity: OpportunityRecord,
    outcome_state: str,
    submission_id: str,
    submission_fingerprint: str,
    provider_evidence_id: str,
    provider_evidence_fingerprint: str,
    provider_order_status: str,
    requested_quantity: float | None,
    requested_notional: float | None,
    filled_quantity: float,
    average_fill_price: float | None,
    fill_time: str | None,
    remaining_quantity: float | None,
    observed_at: str,
) -> BrokerExecutionOutcomeRecord:
    """Freeze actual provider execution truth; never derive fills from prices."""

    validate_opportunity(opportunity)
    if opportunity.decision_class != ACTUAL_SYSTEM_DECISION or opportunity.disposition != ELIGIBLE_SELECTED:
        raise OpportunityDenominatorError("Broker execution requires an actual selected opportunity.")
    state = _token(outcome_state, "Broker outcome state")
    if state not in BROKER_EXECUTION_STATES:
        raise OpportunityDenominatorError("Broker outcome state is unsupported.")
    status = _token(provider_order_status, "Provider order status")
    requested_qty = _optional_positive(requested_quantity, "Requested quantity")
    requested_cash = _optional_positive(requested_notional, "Requested notional")
    if (requested_qty is None) == (requested_cash is None):
        raise OpportunityDenominatorError("Exactly one requested quantity or notional is required.")
    filled = _nonnegative(filled_quantity, "Filled quantity")
    remaining = (
        None if remaining_quantity is None else _nonnegative(remaining_quantity, "Remaining quantity")
    )
    average = _optional_positive(average_fill_price, "Average fill price")
    filled_at = None if fill_time is None else _timestamp(fill_time, "Fill timestamp")
    observed = _timestamp(observed_at, "Broker outcome timestamp")
    if filled_at is not None and _parse_timestamp(filled_at) > _parse_timestamp(observed):
        raise OpportunityDenominatorError("Broker fill is future-dated.")
    if state == FULL_FILL:
        if filled <= 0 or average is None or filled_at is None or remaining not in {0, 0.0} or status != "FILLED":
            raise OpportunityDenominatorError("Full fill contradicts provider execution truth.")
        if requested_qty is not None and not math.isclose(filled, requested_qty, rel_tol=0, abs_tol=1e-9):
            raise OpportunityDenominatorError("Partial fill cannot be labeled full fill.")
    elif state == PARTIAL_FILL:
        if filled <= 0 or average is None or filled_at is None or remaining is None or remaining <= 0 or status != "PARTIALLY_FILLED":
            raise OpportunityDenominatorError("Partial fill requires actual partial provider truth.")
        if requested_qty is not None and filled >= requested_qty:
            raise OpportunityDenominatorError("Partial fill must remain below requested quantity.")
    elif state in {UNFILLED, CANCELLED, REJECTED}:
        if filled != 0 or average is not None or filled_at is not None:
            raise OpportunityDenominatorError("Unexecuted broker state cannot contain a fill.")
    identity = _fingerprint(
        "broker-execution-outcome-identity-v1",
        {
            "opportunityId": opportunity.opportunity_id,
            "submissionId": _identifier(submission_id, "Submission identity"),
            "submissionFingerprint": _sha256(submission_fingerprint, "Submission fingerprint"),
            "providerEvidenceId": _identifier(provider_evidence_id, "Provider evidence identity"),
            "providerEvidenceFingerprint": _sha256(provider_evidence_fingerprint, "Provider evidence fingerprint"),
            "observedAt": observed,
        },
    )
    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "sample_identity": opportunity.sample_identity,
        "policy_fingerprint": opportunity.policy_fingerprint,
        "outcome_id": identity,
        "outcome_domain": BROKER_EXECUTION,
        "outcome_state": state,
        "opportunity_id": opportunity.opportunity_id,
        "opportunity_fingerprint": opportunity.fingerprint,
        "submission_id": _identifier(submission_id, "Submission identity"),
        "submission_fingerprint": _sha256(submission_fingerprint, "Submission fingerprint"),
        "provider_evidence_id": _identifier(provider_evidence_id, "Provider evidence identity"),
        "provider_evidence_fingerprint": _sha256(provider_evidence_fingerprint, "Provider evidence fingerprint"),
        "provider_order_status": status,
        "requested_quantity": requested_qty,
        "requested_notional": requested_cash,
        "filled_quantity": filled,
        "average_fill_price": average,
        "fill_time": filled_at,
        "remaining_quantity": remaining,
        "observed_at": observed,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(payload)
    return BrokerExecutionOutcomeRecord(**payload)


def build_data_quality_outcome(
    *,
    cycle: OpportunityCycleRecord,
    outcome_state: str,
    observed_at: str,
    reason_codes: Iterable[str],
    evidence_refs: Iterable[EvidenceReference] = (),
    opportunity: OpportunityRecord | None = None,
) -> DataQualityOutcomeRecord:
    validate_cycle(cycle)
    state = _token(outcome_state, "Data quality state")
    if state not in DATA_QUALITY_STATES:
        raise OpportunityDenominatorError("Data quality state is unsupported.")
    if state == SYSTEM_FAILURE and opportunity is not None and opportunity.disposition == REJECTED_STRATEGY:
        raise OpportunityDenominatorError("System failure cannot be mislabeled strategy rejection.")
    observed = _timestamp(observed_at, "Data quality timestamp")
    reasons = _tokens(reason_codes, "Data quality reason")
    if not reasons:
        raise OpportunityDenominatorError("Data quality outcome requires reason codes.")
    references = _evidence_refs(tuple(evidence_refs), cutoff=observed)
    if opportunity is not None:
        validate_opportunity(opportunity)
        if opportunity.cycle_id != cycle.cycle_id:
            raise OpportunityDenominatorError("Data quality opportunity belongs to another cycle.")
    identity = _fingerprint(
        "data-quality-outcome-identity-v1",
        {
            "cycleId": cycle.cycle_id,
            "opportunityId": opportunity.opportunity_id if opportunity else None,
            "state": state,
            "observedAt": observed,
            "reasonCodes": list(reasons),
        },
    )
    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "sample_identity": cycle.sample_identity,
        "policy_fingerprint": cycle.policy_fingerprint,
        "outcome_id": identity,
        "outcome_domain": DATA_QUALITY,
        "outcome_state": state,
        "cycle_id": cycle.cycle_id,
        "cycle_fingerprint": cycle.fingerprint,
        "opportunity_id": opportunity.opportunity_id if opportunity else None,
        "opportunity_fingerprint": opportunity.fingerprint if opportunity else None,
        "observed_at": observed,
        "reason_codes": reasons,
        "evidence_refs": references,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(_to_wire_value(payload))
    return DataQualityOutcomeRecord(**payload)


def adapt_opening_report(
    *,
    report: Mapping[str, Any],
    source_identity: str,
    source_evidence_fingerprint: str,
    raw_count: int,
    parsed_count: int,
    observation_mode: str = RETROSPECTIVE_RESEARCH_EXAMPLE,
    policy: DenominatorPolicy | None = None,
) -> tuple[OpportunityCycleRecord, tuple[OpportunityRecord, ...]]:
    """Adapt caller-supplied opening evidence without providers, decisions, or writes."""

    if not isinstance(report, Mapping):
        raise OpportunityDenominatorError("Opening report is malformed.")
    metadata = report.get("metadata")
    rows = report.get("candidates")
    if not isinstance(metadata, Mapping) or not isinstance(rows, list):
        raise OpportunityDenominatorError("Opening report metadata or candidates are malformed.")
    generated_at = metadata.get("generated_at")
    if not isinstance(generated_at, str):
        raise OpportunityDenominatorError("Opening report generated timestamp is missing.")
    source_session = str(metadata.get("source_session") or "OPENING").upper()
    session = _parse_timestamp(_timestamp(generated_at, "Opening report timestamp")).date().isoformat()
    seeds: list[OpportunitySeed] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise OpportunityDenominatorError("Opening candidate row is malformed.")
        symbol = _symbol(row.get("symbol"))
        rank = row.get("rank", index)
        trade_plan = row.get("trade_plan")
        trade_plan = trade_plan if isinstance(trade_plan, Mapping) else {}
        setup = trade_plan.get("setup_evidence")
        setup = setup if isinstance(setup, Mapping) else {}
        intraday = trade_plan.get("intraday_evidence")
        intraday = intraday if isinstance(intraday, Mapping) else {}
        setup_fp = setup.get("fingerprint")
        setup_id = setup_fp if isinstance(setup_fp, str) and _SHA256.fullmatch(setup_fp.lower()) else None
        plan_id = intraday.get("plan_id") if setup_id is not None else None
        if not isinstance(plan_id, str) or not _SHA256.fullmatch(plan_id.lower()):
            plan_id = None
        row_fp = _fingerprint("opening-report-row-v1", row)
        origins = (MOMENTUM_CANDIDATE,) if int(rank) == 1 else (MOMENTUM_CANDIDATE, RANK_ALTERNATIVE)
        blockers = trade_plan.get("blocking_reasons")
        blockers = tuple(str(value).upper() for value in blockers) if isinstance(blockers, list) else ()
        evidence = EvidenceReference(
            evidence_id=f"opening-row:{session}:{int(rank)}:{symbol}",
            evidence_type="OPENING_TRADE_PLAN_ROW",
            source=_identifier(source_identity, "Source identity"),
            as_of=_timestamp(generated_at, "Opening report timestamp"),
            fingerprint=row_fp,
        )
        seeds.append(
            OpportunitySeed(
                origin_kinds=origins,
                origin_record_id=f"opening-row:{session}:{int(rank)}:{symbol}",
                origin_fingerprint=row_fp,
                symbol=symbol,
                security_identity_status=UNRESOLVED,
                security_id=None,
                observed_at=generated_at,
                decision_cutoff=generated_at,
                candidate_id=None,
                setup_id=setup_id.lower() if setup_id else None,
                trade_plan_id=plan_id.lower() if plan_id else None,
                rank=int(rank),
                evidence_refs=(evidence,),
                disposition=NO_ACTION_RESEARCH_ONLY,
                decision_class=COUNTERFACTUAL_RESEARCH_OBSERVATION,
                blocker_reasons=blockers,
            )
        )
    return build_cycle_bundle(
        cycle_type="OPENING_MOMENTUM",
        session_date=session,
        session_type=source_session,
        observed_at=generated_at,
        decision_cutoff=generated_at,
        source_identity=source_identity,
        source_evidence_fingerprint=source_evidence_fingerprint,
        raw_count=raw_count,
        parsed_count=parsed_count,
        seeds=seeds,
        observation_mode=observation_mode,
        policy=policy,
    )


class OpportunityDenominatorStore:
    """Explicit-root, atomic, write-once research persistence."""

    def __init__(self, root: Path, *, policy: DenominatorPolicy | None = None) -> None:
        if not isinstance(root, Path):
            raise OpportunityDenominatorError("Persistence root must be an explicit Path.")
        self.policy = policy or current_policy()
        _validate_policy(self.policy)
        self.root = root.resolve()
        self.sample_root = self.root / self.policy.sample_identity

    def persist_cycle(
        self,
        cycle: OpportunityCycleRecord,
        opportunities: Sequence[OpportunityRecord],
    ) -> None:
        validate_cycle(cycle)
        if cycle.sample_identity != self.policy.sample_identity or cycle.policy_fingerprint != self.policy.policy_fingerprint:
            raise OpportunityDenominatorError("Cycle policy or sample identity drift.")
        by_id = {record.opportunity_id: record for record in opportunities}
        if len(by_id) != len(opportunities):
            raise OpportunityDenominatorError("Duplicate opportunity identity supplied to store.")
        expected = {item.opportunity_id: item.opportunity_fingerprint for item in cycle.opportunity_refs}
        if set(by_id) != set(expected):
            raise OpportunityDenominatorError("Cycle opportunity set is incomplete or conflicting.")
        targets: list[tuple[Path, bytes]] = []
        for identity, record in sorted(by_id.items()):
            validate_opportunity(record)
            if record.cycle_id != cycle.cycle_id or record.fingerprint != expected[identity]:
                raise OpportunityDenominatorError("Opportunity does not match terminal cycle reference.")
            targets.append((self._path("opportunities", identity), _record_bytes("OPPORTUNITY", record)))
        targets.append((self._path("cycles", cycle.cycle_id), _record_bytes("CYCLE", cycle)))
        self._write_many(targets)

    def persist_attachment(self, attachment: SpecialistOpinionAttachment) -> None:
        validate_attachment(attachment)
        self._require_opportunity(
            attachment.opportunity_id, attachment.opportunity_fingerprint
        )
        self._persist_one("specialist-attachments", attachment.attachment_id, "SPECIALIST_ATTACHMENT", attachment)

    def persist_outcome(
        self,
        outcome: MarketPathOutcomeRecord | BrokerExecutionOutcomeRecord | DataQualityOutcomeRecord,
    ) -> None:
        if not isinstance(outcome, (MarketPathOutcomeRecord, BrokerExecutionOutcomeRecord, DataQualityOutcomeRecord)):
            raise OpportunityDenominatorError("Outcome record is unsupported.")
        validate_outcome(outcome)
        if isinstance(outcome, (MarketPathOutcomeRecord, BrokerExecutionOutcomeRecord)):
            self._require_opportunity(
                outcome.opportunity_id, outcome.opportunity_fingerprint
            )
        else:
            self._require_cycle(outcome.cycle_id, outcome.cycle_fingerprint)
            if outcome.opportunity_id is not None:
                self._require_opportunity(
                    outcome.opportunity_id,
                    outcome.opportunity_fingerprint or "",
                )
        self._persist_one("outcomes", outcome.outcome_id, "OUTCOME", outcome)

    def summary(self) -> DenominatorSummary:
        cycles = [self._read_record(path, "CYCLE") for path in self._json_files("cycles")]
        opportunities: list[dict[str, Any]] = []
        for cycle in cycles:
            for reference in cycle["payload"]["opportunity_refs"]:
                record = self._read_record(self._path("opportunities", reference["opportunity_id"]), "OPPORTUNITY")
                payload = record["payload"]
                if payload["fingerprint"] != reference["opportunity_fingerprint"]:
                    raise OpportunityDenominatorError("Persisted opportunity reference was tampered.")
                opportunities.append(payload)
        attachments = [
            self._read_record(path, "SPECIALIST_ATTACHMENT")["payload"]
            for path in self._json_files("specialist-attachments")
        ]
        outcomes = [
            self._read_record(path, "OUTCOME")["payload"] for path in self._json_files("outcomes")
        ]
        for item in attachments:
            self._require_opportunity(
                item["opportunity_id"], item["opportunity_fingerprint"]
            )
        for item in outcomes:
            if item["outcome_domain"] in {MARKET_PATH, BROKER_EXECUTION}:
                self._require_opportunity(
                    item["opportunity_id"], item["opportunity_fingerprint"]
                )
            else:
                self._require_cycle(item["cycle_id"], item["cycle_fingerprint"])
                if item["opportunity_id"] is not None:
                    self._require_opportunity(
                        item["opportunity_id"], item["opportunity_fingerprint"]
                    )
        prospective = [cycle["payload"] for cycle in cycles if cycle["payload"]["observation_mode"] == PROSPECTIVE]
        prospective_ids = {cycle["cycle_id"] for cycle in prospective}
        counted = [item for item in opportunities if item["cycle_id"] in prospective_ids]
        attachment_counts: dict[str, int] = {}
        for item in attachments:
            attachment_counts[item["specialist_id"]] = attachment_counts.get(item["specialist_id"], 0) + 1
        return DenominatorSummary(
            sample_identity=self.policy.sample_identity,
            policy_fingerprint=self.policy.policy_fingerprint,
            sample_status=self.policy.status,
            prospective_sessions=len({item["session_date"] for item in prospective}),
            retrospective_cycles=sum(item["payload"]["observation_mode"] == RETROSPECTIVE_RESEARCH_EXAMPLE for item in cycles),
            synthetic_cycles=sum(item["payload"]["observation_mode"] == SYNTHETIC_TEST for item in cycles),
            complete_cycles=sum(item["payload"]["complete_denominator"] for item in cycles),
            incomplete_cycles=sum(not item["payload"]["complete_denominator"] for item in cycles),
            total_opportunities=len(counted),
            selected=sum(item["disposition"] == ELIGIBLE_SELECTED for item in counted),
            eligible_not_selected=sum(item["disposition"] == ELIGIBLE_NOT_SELECTED for item in counted),
            strategy_rejects=sum(item["disposition"] == REJECTED_STRATEGY for item in counted),
            risk_blocks=sum(item["disposition"] == BLOCKED_RISK for item in counted),
            data_blocks=sum(item["disposition"] == BLOCKED_DATA for item in counted),
            provider_bound=sum(item["disposition"] in {BLOCKED_PROVIDER_CAPABILITY, NOT_EVALUATED_PROVIDER_BOUND} for item in counted),
            system_failures=sum(item["disposition"] == SYSTEM_FAILURE for item in counted)
            + sum(item["failure_reason"] in {SYSTEM_FAILURE, SYSTEM_DATA_FAILURE} for item in prospective),
            specialist_attachments_by_type=dict(sorted(attachment_counts.items())),
            actual_executions=sum(
                item.get("outcome_domain") == BROKER_EXECUTION and item.get("filled_quantity", 0) > 0
                for item in outcomes
            ),
            unfilled=sum(item.get("outcome_domain") == BROKER_EXECUTION and item.get("outcome_state") == UNFILLED for item in outcomes),
            counterfactual_observations=sum(item["decision_class"] == COUNTERFACTUAL_RESEARCH_OBSERVATION for item in counted),
        )

    def _persist_one(self, folder: str, identity: str, record_type: str, record: Any) -> None:
        if getattr(record, "sample_identity", None) != self.policy.sample_identity or getattr(record, "policy_fingerprint", None) != self.policy.policy_fingerprint:
            raise OpportunityDenominatorError("Record policy or sample identity drift.")
        self._write_many([(self._path(folder, identity), _record_bytes(record_type, record))])

    def _require_opportunity(self, identity: str, fingerprint: str) -> None:
        record = self._read_record(
            self._path("opportunities", identity), "OPPORTUNITY"
        )["payload"]
        if record["opportunity_id"] != identity or record["fingerprint"] != fingerprint:
            raise OpportunityDenominatorError(
                "Attachment or outcome opportunity reference is unavailable or conflicting."
            )

    def _require_cycle(self, identity: str, fingerprint: str) -> None:
        record = self._read_record(self._path("cycles", identity), "CYCLE")["payload"]
        if record["cycle_id"] != identity or record["fingerprint"] != fingerprint:
            raise OpportunityDenominatorError(
                "Outcome cycle reference is unavailable or conflicting."
            )

    def _path(self, folder: str, identity: str) -> Path:
        return self.sample_root / folder / f"{_sha256(identity, 'Record identity')}.json"

    def _json_files(self, folder: str) -> list[Path]:
        path = self.sample_root / folder
        return sorted(path.glob("*.json")) if path.exists() else []

    def _write_many(self, targets: Sequence[tuple[Path, bytes]]) -> None:
        for path, content in targets:
            if path.exists():
                existing = path.read_bytes()
                self._read_record(path, None)
                if existing != content:
                    raise OpportunityDenominatorError(f"Conflicting write-once record exists: {path.name}")
        for path, content in targets:
            if not path.exists():
                _atomic_write(path, content)

    def _read_record(self, path: Path, expected_type: str | None) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="ascii"), object_pairs_hook=_reject_duplicate_keys)
        except (OSError, UnicodeError, json.JSONDecodeError, OpportunityDenominatorError) as exc:
            raise OpportunityDenominatorError(f"Malformed persisted record: {path.name}") from exc
        if not isinstance(payload, dict) or set(payload) != {"recordType", "payload"} or not isinstance(payload["payload"], dict):
            raise OpportunityDenominatorError(f"Unsupported persisted record: {path.name}")
        if expected_type is not None and payload["recordType"] != expected_type:
            raise OpportunityDenominatorError(f"Persisted record type mismatch: {path.name}")
        record = payload["payload"]
        if record.get("sample_identity") != self.policy.sample_identity or record.get("policy_fingerprint") != self.policy.policy_fingerprint:
            raise OpportunityDenominatorError("Persisted record policy or sample identity drift.")
        if record.get("execution_authority") != EXECUTION_AUTHORITY_NONE or record.get("authority") != RESEARCH_ONLY:
            raise OpportunityDenominatorError("Persisted record attempted execution authority.")
        if record.get("fingerprint") != _record_fingerprint(record):
            raise OpportunityDenominatorError(f"Persisted record fingerprint is invalid: {path.name}")
        return payload


def validate_cycle(cycle: OpportunityCycleRecord) -> None:
    if not isinstance(cycle, OpportunityCycleRecord):
        raise OpportunityDenominatorError("Cycle record is malformed.")
    _validate_common_record(cycle)
    if cycle.complete_denominator != (cycle.raw_count == cycle.parsed_count == len(cycle.opportunity_refs) and cycle.failure_reason is None):
        raise OpportunityDenominatorError("Cycle denominator completeness is contradictory.")
    if not cycle.complete_denominator and cycle.failure_reason is None:
        raise OpportunityDenominatorError("Incomplete cycle requires failure reason.")
    if cycle.fingerprint != _record_fingerprint(_to_wire_value({key: value for key, value in asdict(cycle).items()})):
        raise OpportunityDenominatorError("Cycle fingerprint is invalid.")


def validate_opportunity(opportunity: OpportunityRecord) -> None:
    if not isinstance(opportunity, OpportunityRecord):
        raise OpportunityDenominatorError("Opportunity record is malformed.")
    _validate_common_record(opportunity)
    if opportunity.security_identity_status == UNRESOLVED and opportunity.security_id is not None:
        raise OpportunityDenominatorError("Unresolved security identity contains durable identity.")
    if opportunity.disposition == VETOED_BY_AUTHORIZED_REGIME_POLICY:
        raise OpportunityDenominatorError("Current research specialists cannot veto opportunities.")
    if opportunity.fingerprint != _record_fingerprint(_to_wire_value(asdict(opportunity))):
        raise OpportunityDenominatorError("Opportunity fingerprint is invalid.")


def validate_attachment(attachment: SpecialistOpinionAttachment) -> None:
    if not isinstance(attachment, SpecialistOpinionAttachment):
        raise OpportunityDenominatorError("Specialist attachment is malformed.")
    _validate_common_record(attachment)
    if attachment.timing_relationship not in TIMING_RELATIONSHIPS:
        raise OpportunityDenominatorError("Specialist timing relationship is unsupported.")
    if _parse_timestamp(attachment.opinion_as_of) > _parse_timestamp(attachment.attached_at):
        raise OpportunityDenominatorError("Specialist attachment is future-dated.")
    if attachment.fingerprint != _record_fingerprint(_to_wire_value(asdict(attachment))):
        raise OpportunityDenominatorError("Specialist attachment fingerprint is invalid.")


def validate_outcome(
    outcome: MarketPathOutcomeRecord | BrokerExecutionOutcomeRecord | DataQualityOutcomeRecord,
) -> None:
    _validate_common_record(outcome)
    if isinstance(outcome, MarketPathOutcomeRecord):
        if outcome.outcome_domain != MARKET_PATH or outcome.outcome_state not in MARKET_PATH_STATES:
            raise OpportunityDenominatorError("Market-path outcome domain or state is invalid.")
        if _parse_timestamp(outcome.terminal_timestamp) > _parse_timestamp(outcome.horizon_end):
            raise OpportunityDenominatorError("Market-path terminal state is outside its horizon.")
    elif isinstance(outcome, BrokerExecutionOutcomeRecord):
        if outcome.outcome_domain != BROKER_EXECUTION or outcome.outcome_state not in BROKER_EXECUTION_STATES:
            raise OpportunityDenominatorError("Broker outcome domain or state is invalid.")
    elif isinstance(outcome, DataQualityOutcomeRecord):
        if outcome.outcome_domain != DATA_QUALITY or outcome.outcome_state not in DATA_QUALITY_STATES:
            raise OpportunityDenominatorError("Data-quality outcome domain or state is invalid.")
    else:
        raise OpportunityDenominatorError("Outcome record is unsupported.")
    if outcome.fingerprint != _record_fingerprint(_to_wire_value(asdict(outcome))):
        raise OpportunityDenominatorError("Outcome fingerprint is invalid.")


def _validate_common_record(record: Any) -> None:
    if record.contract_version != CONTRACT_VERSION:
        raise OpportunityDenominatorError("Record contract version is unsupported.")
    if record.sample_identity != SAMPLE_IDENTITY or record.policy_fingerprint != POLICY_FINGERPRINT:
        raise OpportunityDenominatorError("Record sample or policy identity drift.")
    if record.authority != RESEARCH_ONLY or record.execution_authority != EXECUTION_AUTHORITY_NONE:
        raise OpportunityDenominatorError("Research record attempted execution authority.")


def _validate_policy(policy: DenominatorPolicy) -> None:
    if not isinstance(policy, DenominatorPolicy):
        raise OpportunityDenominatorError("Denominator policy is malformed.")
    if policy.contract_version != CONTRACT_VERSION or policy.sample_identity != SAMPLE_IDENTITY:
        raise OpportunityDenominatorError("Sample identity or contract version drift.")
    if policy.policy_fingerprint != POLICY_FINGERPRINT:
        raise OpportunityDenominatorError("Policy fingerprint drift.")
    if policy.authority != RESEARCH_ONLY or policy.execution_authority != EXECUTION_AUTHORITY_NONE:
        raise OpportunityDenominatorError("Policy attempted execution authority.")
    if policy.historical_backfill_allowed:
        raise OpportunityDenominatorError("Historical backfill is prohibited.")


def _validate_prospective_admission(policy: DenominatorPolicy, session: str, observed_at: str) -> None:
    if policy.status != "ACTIVE_PROSPECTIVE" or policy.activated_at is None or policy.first_eligible_session_date is None:
        raise OpportunityDenominatorError("Prospective sample is not activated.")
    if _parse_timestamp(observed_at) < _parse_timestamp(_timestamp(policy.activated_at, "Activation timestamp")):
        raise OpportunityDenominatorError("Prospective observation predates activation.")
    if date.fromisoformat(session) < date.fromisoformat(policy.first_eligible_session_date):
        raise OpportunityDenominatorError("Historical session cannot enter activated prospective sample.")


def _record_bytes(record_type: str, record: Any) -> bytes:
    payload = _to_wire_value(asdict(record))
    if payload.get("fingerprint") != _record_fingerprint(payload):
        raise OpportunityDenominatorError("Record fingerprint is malformed.")
    return _canonical_json({"recordType": record_type, "payload": payload})


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OpportunityDenominatorError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_bar(bar: MarketPathBar) -> MarketPathBar:
    if not isinstance(bar, MarketPathBar):
        raise OpportunityDenominatorError("Market-path bar is malformed.")
    timestamp = _timestamp(bar.timestamp, "Bar timestamp")
    values = [
        _positive(bar.open, "Bar open"),
        _positive(bar.high, "Bar high"),
        _positive(bar.low, "Bar low"),
        _positive(bar.close, "Bar close"),
    ]
    if values[1] < max(values[0], values[2], values[3]) or values[2] > min(values[0], values[1], values[3]):
        raise OpportunityDenominatorError("Market-path OHLC is contradictory.")
    _nonnegative(bar.volume, "Bar volume")
    _identifier(bar.evidence_id, "Bar evidence identity")
    _sha256(bar.fingerprint, "Bar fingerprint")
    return MarketPathBar(timestamp, *values, float(bar.volume), bar.evidence_id, bar.fingerprint.lower())


def _evidence_refs(values: Iterable[EvidenceReference], *, cutoff: str) -> tuple[EvidenceReference, ...]:
    normalized: list[EvidenceReference] = []
    for item in values:
        if not isinstance(item, EvidenceReference):
            raise OpportunityDenominatorError("Evidence reference is malformed.")
        as_of = _timestamp(item.as_of, "Evidence timestamp")
        if _parse_timestamp(as_of) > _parse_timestamp(cutoff):
            raise OpportunityDenominatorError("Opportunity consumed evidence after its cutoff.")
        normalized.append(
            EvidenceReference(
                evidence_id=_identifier(item.evidence_id, "Evidence identity"),
                evidence_type=_token(item.evidence_type, "Evidence type"),
                source=_identifier(item.source, "Evidence source"),
                as_of=as_of,
                fingerprint=_sha256(item.fingerprint, "Evidence fingerprint"),
            )
        )
    references = tuple(
        sorted(normalized, key=lambda item: (item.as_of, item.evidence_id, item.fingerprint))
    )
    if len({(item.evidence_id, item.fingerprint) for item in references}) != len(references):
        raise OpportunityDenominatorError("Duplicate evidence reference.")
    return references


def _evidence_to_wire(value: EvidenceReference) -> dict[str, Any]:
    return {
        "evidence_id": value.evidence_id,
        "evidence_type": value.evidence_type,
        "source": value.source,
        "as_of": value.as_of,
        "fingerprint": value.fingerprint,
    }


def _to_wire_value(value: Any) -> Any:
    if isinstance(value, EvidenceReference):
        return _evidence_to_wire(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _to_wire_value(asdict(value))
    if isinstance(value, tuple):
        return [_to_wire_value(item) for item in value]
    if isinstance(value, list):
        return [_to_wire_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _to_wire_value(item) for key, item in value.items()}
    return value


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise OpportunityDenominatorError("Naive timestamp is not allowed.")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise OpportunityDenominatorError(f"{label} must be an ISO timestamp.")
    try:
        return _parse_timestamp(value).isoformat().replace("+00:00", "Z")
    except ValueError as exc:
        raise OpportunityDenominatorError(f"{label} is invalid.") from exc


def _session_date(value: Any) -> str:
    if not isinstance(value, str):
        raise OpportunityDenominatorError("Session date is invalid.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise OpportunityDenominatorError("Session date must use YYYY-MM-DD.") from exc


def _mode(value: Any) -> str:
    normalized = _token(value, "Observation mode")
    if normalized not in OBSERVATION_MODES:
        raise OpportunityDenominatorError("Observation mode is unsupported.")
    return normalized


def _symbol(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", value.strip().upper()):
        raise OpportunityDenominatorError("Symbol is invalid.")
    return value.strip().upper()


def _token(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise OpportunityDenominatorError(f"{label} is invalid.")
    normalized = value.strip().upper()
    if not _TOKEN.fullmatch(normalized):
        raise OpportunityDenominatorError(f"{label} is invalid.")
    return normalized


def _optional_token(value: Any, label: str) -> str | None:
    return None if value is None else _token(value, label)


def _tokens(values: Iterable[Any], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted({_token(value, label) for value in values}))
    return normalized


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise OpportunityDenominatorError(f"{label} is invalid.")
    return value.strip()


def _optional_identifier(value: Any, label: str) -> str | None:
    return None if value is None else _identifier(value, label)


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value.strip().lower()):
        raise OpportunityDenominatorError(f"{label} must be SHA-256.")
    return value.strip().lower()


def _optional_sha256(value: Any, label: str) -> str | None:
    return None if value is None else _sha256(value, label)


def _positive(value: Any, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise OpportunityDenominatorError(f"{label} must be positive.")
    return number


def _optional_positive(value: Any, label: str) -> float | None:
    return None if value is None else _positive(value, label)


def _nonnegative(value: Any, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise OpportunityDenominatorError(f"{label} must be non-negative.")
    return number


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise OpportunityDenominatorError(f"{label} must be finite numeric data.")
    return float(value)


def _minutes(start: str | None, end: str) -> float:
    if start is None:
        return 0.0
    return round((_parse_timestamp(end) - _parse_timestamp(start)).total_seconds() / 60.0, 6)
