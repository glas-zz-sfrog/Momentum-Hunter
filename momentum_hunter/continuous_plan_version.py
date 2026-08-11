"""Immutable continuous-intraday TradePlan version and decision bindings.

This module is an offline contract layer. It binds already-persisted evidence
to an existing DATA-004 IntradayPlanEvidence without fetching data, scoring a
candidate, running risk or allocation, or contacting an execution surface.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence

from momentum_hunter.candidate_lifecycle import (
    CANDIDATE_STATES,
    EXECUTION_ELIGIBLE as CANDIDATE_EXECUTION_ELIGIBLE,
    CandidateLifecycleSnapshot,
    expected_opportunity_id,
    expected_setup_id,
)
from momentum_hunter.catalyst_evidence import (
    AVAILABLE as CATALYST_AVAILABLE,
    CURRENT as CATALYST_CURRENT,
    RECOVERED as CATALYST_RECOVERED,
    CATALYST_EVIDENCE_STATES,
    SOURCE_AVAILABILITY_STATES,
    CatalystEvidenceSnapshot,
    validate_snapshot as validate_catalyst_snapshot,
)
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_BLOCKED,
    CATALYST_SCORE_SUPPORTED,
)
from momentum_hunter.intraday_trade_plan import (
    CATALYST_DRIVER,
    SUPPORTED_SETUP_FAMILIES,
    TECHNICAL_DRIVER,
    IntradayPlanEvidence,
    intraday_plan_decision_findings,
    intraday_plan_validation_findings,
)
from momentum_hunter.macro_event_context import (
    BLOCK_NEW_ENTRY,
    CAUTION,
    DATA_STALE as EVENT_DATA_STALE,
    EVENT_CONTEXT_STATES,
    EventRiskContext,
    validate_context as validate_event_context,
)
from momentum_hunter.rolling_market_regime import (
    DATA_STALE as REGIME_DATA_STALE,
    INSUFFICIENT,
    PARTIAL,
    REGIME_LABELS,
    STALE,
    SUFFICIENCY_STATES,
    CandidateRegimeContext,
    RegimeSnapshot,
    fingerprint_payload as regime_fingerprint_payload,
    validate_snapshot as validate_regime_snapshot,
)


CONTINUOUS_PLAN_SCHEMA_VERSION = 1
CONTINUOUS_PLAN_PROFILE = "continuous-intraday-plan-version-v1"
CONTINUOUS_DECISION_PROFILE = "continuous-intraday-decision-binding-v1"

READY_FOR_RISK_REVIEW = "READY_FOR_RISK_REVIEW"
PLAN_BLOCKED = "BLOCKED"
PLAN_STATES = frozenset({READY_FOR_RISK_REVIEW, PLAN_BLOCKED})

EXECUTION_AUTHORITY = "EXECUTION_AUTHORITY"
RESEARCH_ONLY = "RESEARCH_ONLY"
SETUP_AUTHORITIES = frozenset({EXECUTION_AUTHORITY, RESEARCH_ONLY})

RVOL_EXECUTION_ELIGIBLE = "EXECUTION_ELIGIBLE"
RVOL_BLOCKED = "BLOCKED"
RVOL_STATES = frozenset({RVOL_EXECUTION_ELIGIBLE, RVOL_BLOCKED})

RISK_AUTHORIZED = "AUTHORIZED"
RISK_BLOCKED = "BLOCKED"
ALLOCATION_AUTHORIZED = "AUTHORIZED"
ALLOCATION_BLOCKED = "BLOCKED"
DECISION_AUTHORIZED = "AUTHORIZED_FOR_CONFIGURED_MODE"
DECISION_NO_TRADE = "NO_TRADE"

NON_LIVE_MODES = frozenset({"FAKEBROKER", "SIMULATION", "ALPACA_PAPER_ENGINEERING"})
MANUAL_OVERRIDE = "MANUAL_OVERRIDE"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")


class ContinuousPlanError(ValueError):
    """Raised when plan-version evidence is contradictory or tampered."""


@dataclass(frozen=True)
class ContinuousPlanPolicy:
    policy_version: str
    configuration_fingerprint: str
    authority_profile: str = "PROSPECTIVE_EVIDENCE_ONLY"

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class SourceClockEvidence:
    source_identity: str
    provider_timestamp: str
    receipt_timestamp: str
    evidence_fingerprint: str

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class SetupRevisionEvidence:
    opportunity_id: str
    setup_id: str
    setup_family: str
    setup_sequence: int
    revision_id: str
    observed_at: str
    evidence_fingerprint: str
    authority: str

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class RvolEvidence:
    evidence_id: str
    symbol: str
    session_date: str
    evaluated_at: str
    evidence_fingerprint: str
    authority_state: str

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class ContinuousPlanVersion:
    plan_version_id: str
    version_number: int
    opportunity_id: str
    symbol: str
    session_date: str
    setup_id: str
    setup_family: str
    setup_sequence: int
    setup_revision_id: str
    setup_revision_fingerprint: str
    setup_authority: str
    setup_driver: str
    intraday_plan_id: str
    intraday_plan_fingerprint: str
    intraday_plan_execution_eligible: bool
    created_at: str
    entry_expires_at: str
    forced_flat_at: str
    candidate_state: str
    candidate_event_id: str
    candidate_evidence_fingerprint: str
    candidate_policy_fingerprint: str
    candidate_updated_at: str
    regime_snapshot_id: str
    regime_snapshot_fingerprint: str
    regime_context_fingerprint: str
    regime_policy_fingerprint: str
    regime_label: str
    regime_sufficiency: str
    event_context_id: str
    event_context_fingerprint: str
    event_calendar_fingerprint: str
    event_policy_fingerprint: str
    event_status: str
    catalyst_snapshot_id: str
    catalyst_snapshot_fingerprint: str
    catalyst_revision_id: str
    catalyst_revision_fingerprint: str
    catalyst_policy_fingerprint: str
    catalyst_authority: str
    catalyst_state: str
    catalyst_availability_status: str
    catalyst_is_duplicate: bool
    rvol_evidence_id: str
    rvol_evidence_fingerprint: str
    rvol_authority_state: str
    source_clocks: tuple[SourceClockEvidence, ...]
    source_clock_fingerprint: str
    predecessor_plan_version_id: str
    predecessor_plan_version_fingerprint: str
    supersession_reason: str
    policy_version: str
    policy_fingerprint: str
    configuration_fingerprint: str
    status: str
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    schema_version: int = CONTINUOUS_PLAN_SCHEMA_VERSION
    profile: str = CONTINUOUS_PLAN_PROFILE
    fingerprint: str = ""

    @property
    def ready_for_risk_review(self) -> bool:
        return self.status == READY_FOR_RISK_REVIEW and not self.blockers


@dataclass(frozen=True)
class RiskDecisionReference:
    risk_decision_id: str
    intraday_plan_id: str
    setup_id: str
    status: str
    policy_fingerprint: str
    evidence_fingerprint: str


@dataclass(frozen=True)
class AllocationDecisionReference:
    decision_cycle_id: str
    intraday_plan_id: str
    risk_decision_id: str
    status: str
    final_authorized_quantity: str
    policy_fingerprint: str
    account_snapshot_fingerprint: str
    capability_registry_fingerprint: str
    evidence_fingerprint: str


@dataclass(frozen=True)
class ContinuousPlanDecision:
    decision_id: str
    decided_at: str
    mode: str
    status: str
    plan_version_id: str
    plan_version_fingerprint: str
    opportunity_id: str
    setup_id: str
    intraday_plan_id: str
    risk_decision_id: str
    risk_decision_fingerprint: str
    risk_policy_fingerprint: str
    allocation_decision_cycle_id: str
    allocation_decision_fingerprint: str
    allocation_policy_fingerprint: str
    account_snapshot_fingerprint: str
    capability_registry_fingerprint: str
    final_authorized_quantity: str
    blockers: tuple[str, ...] = field(default_factory=tuple)
    schema_version: int = CONTINUOUS_PLAN_SCHEMA_VERSION
    profile: str = CONTINUOUS_DECISION_PROFILE
    fingerprint: str = ""

    @property
    def authorized(self) -> bool:
        return self.status == DECISION_AUTHORIZED and not self.blockers


@dataclass(frozen=True)
class ContinuousPlanLedger:
    plans: tuple[ContinuousPlanVersion, ...] = field(default_factory=tuple)
    schema_version: int = CONTINUOUS_PLAN_SCHEMA_VERSION
    profile: str = CONTINUOUS_PLAN_PROFILE


class ContinuousPlanStore:
    """Explicit-path append-only store for immutable plan versions."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> ContinuousPlanLedger:
        with self._lock:
            if not self.path.exists():
                return ContinuousPlanLedger()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContinuousPlanError(
                    f"Continuous plan ledger cannot be loaded: {type(exc).__name__}"
                ) from exc
            ledger = ledger_from_wire(payload)
            validate_ledger(ledger)
            return ledger

    def append(self, plan: ContinuousPlanVersion) -> ContinuousPlanVersion:
        with self._lock:
            ledger = self.load()
            existing = next(
                (item for item in ledger.plans if item.plan_version_id == plan.plan_version_id),
                None,
            )
            if existing is not None:
                if existing != plan:
                    raise ContinuousPlanError(
                        "Continuous plan identity was reused with conflicting evidence."
                    )
                return existing
            validate_plan_version(plan)
            prior_for_opportunity = tuple(
                item
                for item in ledger.plans
                if item.opportunity_id == plan.opportunity_id
            )
            if prior_for_opportunity:
                latest = prior_for_opportunity[-1]
                if plan.predecessor_plan_version_id != latest.plan_version_id:
                    raise ContinuousPlanError(
                        "Continuous plan did not extend the latest opportunity version."
                    )
            updated = ContinuousPlanLedger(plans=(*ledger.plans, plan))
            validate_ledger(updated)
            _atomic_write(self.path, canonical_json_bytes(ledger_to_wire(updated)))
            return plan


def build_continuous_plan_version(
    *,
    intraday_plan: IntradayPlanEvidence,
    candidate: CandidateLifecycleSnapshot,
    setup_revision: SetupRevisionEvidence,
    regime_snapshot: RegimeSnapshot,
    regime_context: CandidateRegimeContext,
    event_context: EventRiskContext,
    rvol_evidence: RvolEvidence,
    source_clocks: Sequence[SourceClockEvidence],
    policy: ContinuousPlanPolicy,
    catalyst_snapshot: CatalystEvidenceSnapshot | None = None,
    predecessor: ContinuousPlanVersion | None = None,
    supersession_reason: str = "",
) -> ContinuousPlanVersion:
    """Bind one validated evidence set to an immutable DATA-004 plan."""

    plan_findings = intraday_plan_validation_findings(intraday_plan)
    if plan_findings:
        raise ContinuousPlanError(
            "Intraday plan evidence was invalid: " + " | ".join(plan_findings)
        )
    try:
        validate_regime_snapshot(regime_snapshot)
        validate_event_context(event_context)
        if catalyst_snapshot is not None:
            validate_catalyst_snapshot(catalyst_snapshot)
        validate_policy(policy)
        validate_setup_revision(setup_revision)
        validate_rvol_evidence(rvol_evidence)
    except ContinuousPlanError:
        raise
    except ValueError as exc:
        raise ContinuousPlanError(
            f"Referenced evidence was invalid: {type(exc).__name__}"
        ) from exc
    clocks = tuple(source_clocks)
    if not clocks:
        raise ContinuousPlanError("At least one source clock is required.")
    for clock in clocks:
        validate_source_clock(clock)
    clocked_evidence = {item.evidence_fingerprint for item in clocks}
    for required, name in (
        (setup_revision.evidence_fingerprint, "setup revision"),
        (rvol_evidence.evidence_fingerprint, "RVOL evidence"),
    ):
        if required not in clocked_evidence:
            raise ContinuousPlanError(f"Source clocks omitted {name}.")

    created_at = _timestamp(intraday_plan.created_at, "Plan creation timestamp")
    try:
        _validate_candidate(candidate)
        _validate_cross_evidence(
            intraday_plan=intraday_plan,
            candidate=candidate,
            setup_revision=setup_revision,
            regime_snapshot=regime_snapshot,
            regime_context=regime_context,
            event_context=event_context,
            rvol_evidence=rvol_evidence,
            catalyst_snapshot=catalyst_snapshot,
            created_at=created_at,
        )
    except ContinuousPlanError:
        raise
    except ValueError as exc:
        raise ContinuousPlanError(
            f"Cross-evidence identity was invalid: {type(exc).__name__}"
        ) from exc
    for clock in clocks:
        if _timestamp(clock.receipt_timestamp, "Source receipt timestamp") > created_at:
            raise ContinuousPlanError("Source evidence was received after plan creation.")

    normalized_reason = str(supersession_reason).strip().upper()
    version_number = 1
    predecessor_id = ""
    predecessor_fingerprint = ""
    if predecessor is not None:
        validate_plan_version(predecessor)
        if predecessor.opportunity_id != candidate.opportunity_id:
            raise ContinuousPlanError("Predecessor opportunity identity did not match.")
        if predecessor.symbol != intraday_plan.symbol:
            raise ContinuousPlanError("Predecessor symbol did not match.")
        if predecessor.session_date != intraday_plan.session_date:
            raise ContinuousPlanError("Predecessor session did not match.")
        if not normalized_reason:
            raise ContinuousPlanError("A supersession reason is required.")
        if predecessor.intraday_plan_fingerprint == intraday_plan.fingerprint:
            raise ContinuousPlanError(
                "A material successor must bind a new IntradayPlan evidence version."
            )
        version_number = predecessor.version_number + 1
        predecessor_id = predecessor.plan_version_id
        predecessor_fingerprint = predecessor.fingerprint
    elif normalized_reason:
        raise ContinuousPlanError("Supersession requires a predecessor plan version.")

    blockers: list[str] = []
    warnings: list[str] = []
    if candidate.current_state != CANDIDATE_EXECUTION_ELIGIBLE:
        blockers.append("CANDIDATE_NOT_EXECUTION_ELIGIBLE")
    if not intraday_plan.execution_eligible:
        blockers.append("INTRADAY_PLAN_NOT_EXECUTION_ELIGIBLE")
    if setup_revision.authority != EXECUTION_AUTHORITY:
        blockers.append("SETUP_EVIDENCE_RESEARCH_ONLY")
    if regime_snapshot.regime == REGIME_DATA_STALE or (
        regime_snapshot.input_sufficiency in {INSUFFICIENT, STALE}
    ):
        blockers.append("REGIME_EVIDENCE_UNSAFE")
    elif regime_snapshot.input_sufficiency == PARTIAL:
        warnings.append("REGIME_EVIDENCE_PARTIAL")
    if event_context.status == BLOCK_NEW_ENTRY:
        blockers.append("MACRO_EVENT_BLOCKS_NEW_ENTRY")
    elif event_context.status == EVENT_DATA_STALE:
        blockers.append("MACRO_EVENT_EVIDENCE_STALE")
    elif event_context.status == CAUTION:
        warnings.append("MACRO_EVENT_CAUTION")
    if rvol_evidence.authority_state != RVOL_EXECUTION_ELIGIBLE:
        blockers.append("RVOL_EVIDENCE_NOT_EXECUTION_ELIGIBLE")

    catalyst_fields = _catalyst_fields(catalyst_snapshot)
    if intraday_plan.setup_driver == CATALYST_DRIVER:
        if catalyst_snapshot is None:
            blockers.append("CATALYST_EVIDENCE_REQUIRED")
        elif not _supported_catalyst(catalyst_snapshot):
            blockers.append("CATALYST_EVIDENCE_NOT_AUTHORITATIVE")
    elif catalyst_snapshot is not None and not _supported_catalyst(catalyst_snapshot):
        warnings.append("CATALYST_CONTEXT_RESEARCH_ONLY")

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    clock_fingerprint = evidence_fingerprint(
        tuple(asdict(item) for item in clocks)
    )
    core = {
        "version_number": version_number,
        "opportunity_id": candidate.opportunity_id,
        "symbol": intraday_plan.symbol,
        "session_date": intraday_plan.session_date,
        "setup_id": setup_revision.setup_id,
        "setup_family": setup_revision.setup_family,
        "setup_sequence": setup_revision.setup_sequence,
        "setup_revision_id": setup_revision.revision_id,
        "setup_revision_fingerprint": setup_revision.evidence_fingerprint,
        "setup_authority": setup_revision.authority,
        "setup_driver": intraday_plan.setup_driver,
        "intraday_plan_id": intraday_plan.plan_id,
        "intraday_plan_fingerprint": intraday_plan.fingerprint,
        "intraday_plan_execution_eligible": intraday_plan.execution_eligible,
        "created_at": intraday_plan.created_at,
        "entry_expires_at": intraday_plan.entry_expires_at,
        "forced_flat_at": intraday_plan.forced_flat_at,
        "candidate_state": candidate.current_state,
        "candidate_event_id": candidate.latest_event_id,
        "candidate_evidence_fingerprint": candidate.latest_evidence_fingerprint,
        "candidate_policy_fingerprint": candidate.latest_policy_fingerprint,
        "candidate_updated_at": candidate.updated_at,
        "regime_snapshot_id": regime_snapshot.snapshot_id,
        "regime_snapshot_fingerprint": regime_snapshot.fingerprint,
        "regime_context_fingerprint": regime_context.context_fingerprint,
        "regime_policy_fingerprint": regime_snapshot.policy_fingerprint,
        "regime_label": regime_snapshot.regime,
        "regime_sufficiency": regime_snapshot.input_sufficiency,
        "event_context_id": event_context.context_id,
        "event_context_fingerprint": event_context.fingerprint,
        "event_calendar_fingerprint": event_context.calendar_fingerprint,
        "event_policy_fingerprint": event_context.policy_fingerprint,
        "event_status": event_context.status,
        **catalyst_fields,
        "rvol_evidence_id": rvol_evidence.evidence_id,
        "rvol_evidence_fingerprint": rvol_evidence.evidence_fingerprint,
        "rvol_authority_state": rvol_evidence.authority_state,
        "source_clocks": clocks,
        "source_clock_fingerprint": clock_fingerprint,
        "predecessor_plan_version_id": predecessor_id,
        "predecessor_plan_version_fingerprint": predecessor_fingerprint,
        "supersession_reason": normalized_reason,
        "policy_version": policy.policy_version,
        "policy_fingerprint": policy.fingerprint,
        "configuration_fingerprint": policy.configuration_fingerprint,
        "status": PLAN_BLOCKED if blockers else READY_FOR_RISK_REVIEW,
        "blockers": tuple(blockers),
        "warnings": tuple(warnings),
        "schema_version": CONTINUOUS_PLAN_SCHEMA_VERSION,
        "profile": CONTINUOUS_PLAN_PROFILE,
    }
    fingerprint = evidence_fingerprint(_canonical_value(core))
    result = ContinuousPlanVersion(
        plan_version_id=f"continuous-plan-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **core,
    )
    validate_plan_version(result)
    return result


def build_continuous_plan_decision(
    *,
    plan_version: ContinuousPlanVersion,
    intraday_plan: IntradayPlanEvidence,
    risk: RiskDecisionReference,
    allocation: AllocationDecisionReference,
    decided_at: datetime,
    mode: str,
    predecessor_decision: ContinuousPlanDecision | None = None,
) -> ContinuousPlanDecision:
    """Bind completed risk/allocation evidence without running either decision."""

    validate_plan_version(plan_version)
    validate_risk_reference(risk)
    validate_allocation_reference(allocation)
    normalized_mode = _required_text(mode, "Decision mode").upper()
    if normalized_mode not in NON_LIVE_MODES:
        raise ContinuousPlanError("Continuous plan decisions cannot target a live mode.")
    decision_time = _aware(decided_at, "Decision timestamp")
    if intraday_plan.plan_id != plan_version.intraday_plan_id or (
        intraday_plan.fingerprint != plan_version.intraday_plan_fingerprint
    ):
        raise ContinuousPlanError("Decision IntradayPlan identity did not match the version.")
    if risk.intraday_plan_id != plan_version.intraday_plan_id:
        raise ContinuousPlanError("Risk decision did not bind the versioned IntradayPlan.")
    if risk.setup_id != plan_version.setup_id:
        raise ContinuousPlanError("Risk decision setup identity did not match.")
    if allocation.intraday_plan_id != plan_version.intraday_plan_id:
        raise ContinuousPlanError("Allocation did not bind the versioned IntradayPlan.")
    if allocation.risk_decision_id != risk.risk_decision_id:
        raise ContinuousPlanError("Allocation did not bind the supplied risk decision.")
    if plan_version.supersession_reason == MANUAL_OVERRIDE:
        if predecessor_decision is None:
            raise ContinuousPlanError("Manual override requires the predecessor decision.")
        validate_decision(predecessor_decision)
        if predecessor_decision.plan_version_id != plan_version.predecessor_plan_version_id:
            raise ContinuousPlanError("Manual override predecessor decision did not match.")
        if predecessor_decision.risk_decision_id == risk.risk_decision_id:
            raise ContinuousPlanError("Manual override must create a new risk decision.")
        if (
            predecessor_decision.allocation_decision_fingerprint
            == allocation.evidence_fingerprint
        ):
            raise ContinuousPlanError("Manual override must create a new allocation decision.")

    blockers = list(
        intraday_plan_decision_findings(intraday_plan, decision_at=decision_time)
    )
    blockers.extend(plan_version.blockers)
    if risk.status != RISK_AUTHORIZED:
        blockers.append("RISK_DECISION_BLOCKED")
    if allocation.status != ALLOCATION_AUTHORIZED:
        blockers.append("ALLOCATION_DECISION_BLOCKED")
    quantity = _decimal(allocation.final_authorized_quantity)
    if quantity is None or quantity <= 0:
        blockers.append("ALLOCATION_QUANTITY_NOT_POSITIVE")
    blockers = list(dict.fromkeys(blockers))
    status = DECISION_NO_TRADE if blockers else DECISION_AUTHORIZED
    decided_text = decision_time.isoformat()
    core = {
        "decided_at": decided_text,
        "mode": normalized_mode,
        "status": status,
        "plan_version_id": plan_version.plan_version_id,
        "plan_version_fingerprint": plan_version.fingerprint,
        "opportunity_id": plan_version.opportunity_id,
        "setup_id": plan_version.setup_id,
        "intraday_plan_id": plan_version.intraday_plan_id,
        "risk_decision_id": risk.risk_decision_id,
        "risk_decision_fingerprint": risk.evidence_fingerprint,
        "risk_policy_fingerprint": risk.policy_fingerprint,
        "allocation_decision_cycle_id": allocation.decision_cycle_id,
        "allocation_decision_fingerprint": allocation.evidence_fingerprint,
        "allocation_policy_fingerprint": allocation.policy_fingerprint,
        "account_snapshot_fingerprint": allocation.account_snapshot_fingerprint,
        "capability_registry_fingerprint": allocation.capability_registry_fingerprint,
        "final_authorized_quantity": allocation.final_authorized_quantity,
        "blockers": tuple(blockers),
        "schema_version": CONTINUOUS_PLAN_SCHEMA_VERSION,
        "profile": CONTINUOUS_DECISION_PROFILE,
    }
    decision_identity = evidence_fingerprint(
        {
            "plan_version_id": plan_version.plan_version_id,
            "risk_decision_fingerprint": risk.evidence_fingerprint,
            "allocation_decision_fingerprint": allocation.evidence_fingerprint,
            "decided_at": decided_text,
        }
    )
    fingerprint = evidence_fingerprint(_canonical_value(core))
    result = ContinuousPlanDecision(
        decision_id=f"continuous-decision-{decision_identity[:24]}",
        fingerprint=fingerprint,
        **core,
    )
    validate_decision(result)
    return result


def validate_plan_version(plan: ContinuousPlanVersion) -> None:
    if plan.schema_version != CONTINUOUS_PLAN_SCHEMA_VERSION or (
        plan.profile != CONTINUOUS_PLAN_PROFILE
    ):
        raise ContinuousPlanError("Continuous plan schema identity is unsupported.")
    if plan.status not in PLAN_STATES:
        raise ContinuousPlanError("Continuous plan status is unsupported.")
    expected_blockers = _authority_blockers_from_record(plan)
    if not expected_blockers.issubset(set(plan.blockers)):
        raise ContinuousPlanError(
            "Continuous plan omitted a required authority blocker."
        )
    if (plan.status == READY_FOR_RISK_REVIEW) != (not plan.blockers):
        raise ContinuousPlanError("Continuous plan authority contradicts its blockers.")
    if plan.version_number <= 0 or plan.setup_sequence <= 0:
        raise ContinuousPlanError("Continuous plan sequence is invalid.")
    for value, name in (
        (plan.symbol, "Plan symbol"),
        (plan.session_date, "Plan session"),
        (plan.setup_revision_id, "Setup revision identity"),
        (plan.regime_snapshot_id, "Regime snapshot identity"),
        (plan.event_context_id, "Event context identity"),
        (plan.rvol_evidence_id, "RVOL evidence identity"),
        (plan.policy_version, "Continuous plan policy version"),
    ):
        _required_text(value, name)
    for value, name in (
        (plan.opportunity_id, "Opportunity identity"),
        (plan.setup_id, "Setup identity"),
        (plan.intraday_plan_id, "IntradayPlan identity"),
        (plan.intraday_plan_fingerprint, "IntradayPlan fingerprint"),
        (plan.setup_revision_fingerprint, "Setup revision fingerprint"),
        (plan.candidate_event_id, "Candidate event identity"),
        (plan.candidate_evidence_fingerprint, "Candidate evidence fingerprint"),
        (plan.candidate_policy_fingerprint, "Candidate policy fingerprint"),
        (plan.regime_snapshot_fingerprint, "Regime snapshot fingerprint"),
        (plan.regime_context_fingerprint, "Regime context fingerprint"),
        (plan.regime_policy_fingerprint, "Regime policy fingerprint"),
        (plan.event_context_fingerprint, "Event context fingerprint"),
        (plan.event_calendar_fingerprint, "Event calendar fingerprint"),
        (plan.event_policy_fingerprint, "Event policy fingerprint"),
        (plan.rvol_evidence_fingerprint, "RVOL evidence fingerprint"),
        (plan.source_clock_fingerprint, "Source clock fingerprint"),
        (plan.policy_fingerprint, "Continuous plan policy fingerprint"),
        (plan.configuration_fingerprint, "Configuration fingerprint"),
    ):
        _sha256(value, name)
    for value, name in (
        (plan.created_at, "Plan creation timestamp"),
        (plan.entry_expires_at, "Entry expiry timestamp"),
        (plan.forced_flat_at, "Forced-flat timestamp"),
        (plan.candidate_updated_at, "Candidate update timestamp"),
    ):
        _timestamp(value, name)
    if plan.setup_authority not in SETUP_AUTHORITIES:
        raise ContinuousPlanError("Setup authority is unsupported.")
    if plan.setup_family not in SUPPORTED_SETUP_FAMILIES:
        raise ContinuousPlanError("Setup family is unsupported.")
    if plan.setup_driver not in {TECHNICAL_DRIVER, CATALYST_DRIVER}:
        raise ContinuousPlanError("Setup driver is unsupported.")
    if type(plan.intraday_plan_execution_eligible) is not bool:
        raise ContinuousPlanError("IntradayPlan authority flag is invalid.")
    if plan.candidate_state not in CANDIDATE_STATES:
        raise ContinuousPlanError("Candidate state is unsupported.")
    if plan.regime_label not in REGIME_LABELS or (
        plan.regime_sufficiency not in SUFFICIENCY_STATES
    ):
        raise ContinuousPlanError("Regime record state is unsupported.")
    if plan.event_status not in EVENT_CONTEXT_STATES:
        raise ContinuousPlanError("Event context state is unsupported.")
    if plan.rvol_authority_state not in RVOL_STATES:
        raise ContinuousPlanError("RVOL authority is unsupported.")
    catalyst_values = (
        plan.catalyst_snapshot_id,
        plan.catalyst_snapshot_fingerprint,
        plan.catalyst_revision_id,
        plan.catalyst_revision_fingerprint,
        plan.catalyst_policy_fingerprint,
        plan.catalyst_authority,
        plan.catalyst_state,
        plan.catalyst_availability_status,
    )
    if any(catalyst_values):
        for value, name in (
            (plan.catalyst_snapshot_id, "Catalyst snapshot identity"),
            (plan.catalyst_revision_id, "Catalyst revision identity"),
        ):
            _required_text(value, name)
        for value, name in (
            (plan.catalyst_snapshot_fingerprint, "Catalyst snapshot fingerprint"),
            (plan.catalyst_revision_fingerprint, "Catalyst revision fingerprint"),
            (plan.catalyst_policy_fingerprint, "Catalyst policy fingerprint"),
        ):
            _sha256(value, name)
        if plan.catalyst_authority not in {
            CATALYST_SCORE_SUPPORTED,
            CATALYST_SCORE_BLOCKED,
        }:
            raise ContinuousPlanError("Catalyst authority is unsupported.")
        if plan.catalyst_state not in CATALYST_EVIDENCE_STATES:
            raise ContinuousPlanError("Catalyst evidence state is unsupported.")
        if plan.catalyst_availability_status not in (
            SOURCE_AVAILABILITY_STATES | {CATALYST_AVAILABLE}
        ):
            raise ContinuousPlanError("Catalyst availability state is unsupported.")
    elif type(plan.catalyst_is_duplicate) is not bool or plan.catalyst_is_duplicate:
        raise ContinuousPlanError("Absent catalyst evidence has contradictory state.")
    if type(plan.catalyst_is_duplicate) is not bool:
        raise ContinuousPlanError("Catalyst duplicate state is invalid.")
    if plan.predecessor_plan_version_id:
        _required_text(plan.predecessor_plan_version_id, "Predecessor plan version")
        _required_text(plan.supersession_reason, "Supersession reason")
        _sha256(plan.predecessor_plan_version_fingerprint, "Predecessor fingerprint")
        if plan.version_number <= 1:
            raise ContinuousPlanError("A successor plan must advance its version.")
    elif plan.version_number != 1 or plan.supersession_reason:
        raise ContinuousPlanError("Initial plan version has invalid predecessor state.")
    for clock in plan.source_clocks:
        validate_source_clock(clock)
        if _timestamp(clock.receipt_timestamp, "Source receipt timestamp") > _timestamp(
            plan.created_at, "Plan creation timestamp"
        ):
            raise ContinuousPlanError("Source evidence was received after plan creation.")
    clocked_evidence = {item.evidence_fingerprint for item in plan.source_clocks}
    if not {
        plan.setup_revision_fingerprint,
        plan.rvol_evidence_fingerprint,
    }.issubset(clocked_evidence):
        raise ContinuousPlanError("Continuous plan omitted required source clocks.")
    expected_clock = evidence_fingerprint(
        tuple(asdict(item) for item in plan.source_clocks)
    )
    if expected_clock != plan.source_clock_fingerprint:
        raise ContinuousPlanError("Source clock fingerprint did not verify.")
    created = _timestamp(plan.created_at, "Plan creation timestamp")
    if _timestamp(plan.candidate_updated_at, "Candidate update timestamp") > created:
        raise ContinuousPlanError("Candidate state was updated after plan creation.")
    if not created < _timestamp(plan.entry_expires_at, "Entry expiry timestamp") < (
        _timestamp(plan.forced_flat_at, "Forced-flat timestamp")
    ):
        raise ContinuousPlanError("Continuous plan timing is contradictory.")
    if len(set(plan.blockers)) != len(plan.blockers) or len(set(plan.warnings)) != len(
        plan.warnings
    ):
        raise ContinuousPlanError("Continuous plan findings contain duplicates.")
    payload = plan_fingerprint_payload(plan)
    expected = evidence_fingerprint(payload)
    if plan.fingerprint != expected or plan.plan_version_id != (
        f"continuous-plan-{expected[:24]}"
    ):
        raise ContinuousPlanError("Continuous plan fingerprint did not verify.")


def validate_decision(decision: ContinuousPlanDecision) -> None:
    if decision.schema_version != CONTINUOUS_PLAN_SCHEMA_VERSION or (
        decision.profile != CONTINUOUS_DECISION_PROFILE
    ):
        raise ContinuousPlanError("Continuous decision schema identity is unsupported.")
    if decision.mode not in NON_LIVE_MODES:
        raise ContinuousPlanError("Continuous decision mode is not non-live.")
    if decision.status not in {DECISION_AUTHORIZED, DECISION_NO_TRADE}:
        raise ContinuousPlanError("Continuous decision status is unsupported.")
    if (decision.status == DECISION_AUTHORIZED) != (not decision.blockers):
        raise ContinuousPlanError("Continuous decision authority contradicts blockers.")
    _timestamp(decision.decided_at, "Decision timestamp")
    quantity = _decimal(decision.final_authorized_quantity)
    if quantity is None:
        raise ContinuousPlanError("Continuous decision quantity is invalid.")
    if decision.status == DECISION_AUTHORIZED and quantity <= 0:
        raise ContinuousPlanError("Authorized decision quantity must be positive.")
    for value, name in (
        (decision.plan_version_fingerprint, "Plan version fingerprint"),
        (decision.opportunity_id, "Opportunity identity"),
        (decision.setup_id, "Setup identity"),
        (decision.intraday_plan_id, "IntradayPlan identity"),
        (decision.risk_decision_fingerprint, "Risk decision fingerprint"),
        (decision.risk_policy_fingerprint, "Risk policy fingerprint"),
        (decision.allocation_decision_fingerprint, "Allocation fingerprint"),
        (decision.allocation_policy_fingerprint, "Allocation policy fingerprint"),
        (decision.account_snapshot_fingerprint, "Account snapshot fingerprint"),
        (decision.capability_registry_fingerprint, "Capability fingerprint"),
    ):
        _sha256(value, name)
    expected = evidence_fingerprint(decision_fingerprint_payload(decision))
    if decision.fingerprint != expected:
        raise ContinuousPlanError("Continuous decision fingerprint did not verify.")
    identity = evidence_fingerprint(
        {
            "plan_version_id": decision.plan_version_id,
            "risk_decision_fingerprint": decision.risk_decision_fingerprint,
            "allocation_decision_fingerprint": decision.allocation_decision_fingerprint,
            "decided_at": decision.decided_at,
        }
    )
    if decision.decision_id != f"continuous-decision-{identity[:24]}":
        raise ContinuousPlanError("Continuous decision identity did not verify.")


def validate_source_clock(clock: SourceClockEvidence) -> None:
    _required_text(clock.source_identity, "Source identity")
    provider = _timestamp(clock.provider_timestamp, "Provider timestamp")
    receipt = _timestamp(clock.receipt_timestamp, "Receipt timestamp")
    if receipt < provider:
        raise ContinuousPlanError("Source receipt timestamp predates provider time.")
    _sha256(clock.evidence_fingerprint, "Source evidence fingerprint")


def validate_setup_revision(evidence: SetupRevisionEvidence) -> None:
    _sha256(evidence.opportunity_id, "Setup opportunity identity")
    _sha256(evidence.setup_id, "Setup identity")
    _required_text(evidence.revision_id, "Setup revision identity")
    _timestamp(evidence.observed_at, "Setup observation timestamp")
    _sha256(evidence.evidence_fingerprint, "Setup evidence fingerprint")
    if evidence.authority not in SETUP_AUTHORITIES:
        raise ContinuousPlanError("Setup evidence authority is unsupported.")
    if evidence.setup_sequence <= 0:
        raise ContinuousPlanError("Setup sequence must be positive.")


def validate_rvol_evidence(evidence: RvolEvidence) -> None:
    _required_text(evidence.evidence_id, "RVOL evidence identity")
    _required_text(evidence.symbol, "RVOL symbol")
    _required_text(evidence.session_date, "RVOL session")
    _timestamp(evidence.evaluated_at, "RVOL evaluation timestamp")
    _sha256(evidence.evidence_fingerprint, "RVOL evidence fingerprint")
    if evidence.authority_state not in RVOL_STATES:
        raise ContinuousPlanError("RVOL evidence authority is unsupported.")


def validate_risk_reference(reference: RiskDecisionReference) -> None:
    _required_text(reference.risk_decision_id, "Risk decision identity")
    _sha256(reference.intraday_plan_id, "Risk IntradayPlan identity")
    _sha256(reference.setup_id, "Risk setup identity")
    _sha256(reference.policy_fingerprint, "Risk policy fingerprint")
    _sha256(reference.evidence_fingerprint, "Risk evidence fingerprint")
    if reference.status not in {RISK_AUTHORIZED, RISK_BLOCKED}:
        raise ContinuousPlanError("Risk decision status is unsupported.")


def validate_allocation_reference(reference: AllocationDecisionReference) -> None:
    _required_text(reference.decision_cycle_id, "Allocation cycle identity")
    _sha256(reference.intraday_plan_id, "Allocation IntradayPlan identity")
    _required_text(reference.risk_decision_id, "Allocation risk identity")
    for value, name in (
        (reference.policy_fingerprint, "Allocation policy fingerprint"),
        (reference.account_snapshot_fingerprint, "Account snapshot fingerprint"),
        (reference.capability_registry_fingerprint, "Capability fingerprint"),
        (reference.evidence_fingerprint, "Allocation evidence fingerprint"),
    ):
        _sha256(value, name)
    if reference.status not in {ALLOCATION_AUTHORIZED, ALLOCATION_BLOCKED}:
        raise ContinuousPlanError("Allocation decision status is unsupported.")
    if _decimal(reference.final_authorized_quantity) is None:
        raise ContinuousPlanError("Allocation quantity is invalid.")


def validate_policy(policy: ContinuousPlanPolicy) -> None:
    _required_text(policy.policy_version, "Continuous plan policy version")
    _required_text(policy.authority_profile, "Continuous plan authority profile")
    _sha256(policy.configuration_fingerprint, "Configuration fingerprint")


def validate_ledger(ledger: ContinuousPlanLedger) -> None:
    if ledger.schema_version != CONTINUOUS_PLAN_SCHEMA_VERSION or (
        ledger.profile != CONTINUOUS_PLAN_PROFILE
    ):
        raise ContinuousPlanError("Continuous plan ledger schema is unsupported.")
    seen: dict[str, ContinuousPlanVersion] = {}
    for plan in ledger.plans:
        validate_plan_version(plan)
        if plan.plan_version_id in seen:
            raise ContinuousPlanError("Continuous plan ledger repeated an identity.")
        if plan.predecessor_plan_version_id:
            predecessor = seen.get(plan.predecessor_plan_version_id)
            if predecessor is None:
                raise ContinuousPlanError("Continuous plan predecessor was not append-only.")
            if predecessor.fingerprint != plan.predecessor_plan_version_fingerprint:
                raise ContinuousPlanError("Continuous plan predecessor fingerprint changed.")
            if plan.version_number != predecessor.version_number + 1:
                raise ContinuousPlanError("Continuous plan version sequence was invalid.")
            if plan.opportunity_id != predecessor.opportunity_id:
                raise ContinuousPlanError("Continuous plan chain changed opportunity identity.")
        seen[plan.plan_version_id] = plan


def plan_fingerprint_payload(plan: ContinuousPlanVersion) -> dict[str, object]:
    payload = asdict(plan)
    payload.pop("plan_version_id", None)
    payload.pop("fingerprint", None)
    return _canonical_value(payload)


def decision_fingerprint_payload(decision: ContinuousPlanDecision) -> dict[str, object]:
    payload = asdict(decision)
    payload.pop("decision_id", None)
    payload.pop("fingerprint", None)
    return _canonical_value(payload)


def ledger_to_wire(ledger: ContinuousPlanLedger) -> dict[str, object]:
    return {
        "schema_version": ledger.schema_version,
        "profile": ledger.profile,
        "plans": [_canonical_value(asdict(item)) for item in ledger.plans],
    }


def ledger_from_wire(payload: object) -> ContinuousPlanLedger:
    if not isinstance(payload, Mapping):
        raise ContinuousPlanError("Continuous plan ledger root is invalid.")
    if set(payload) != {"schema_version", "profile", "plans"}:
        raise ContinuousPlanError("Continuous plan ledger fields are unsupported.")
    rows = payload.get("plans")
    if not isinstance(rows, list):
        raise ContinuousPlanError("Continuous plan ledger plans are invalid.")
    allowed = {item.name for item in fields(ContinuousPlanVersion)}
    plans: list[ContinuousPlanVersion] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != allowed:
            raise ContinuousPlanError("Continuous plan ledger row is malformed.")
        body = dict(row)
        clocks = body.get("source_clocks")
        if not isinstance(clocks, list):
            raise ContinuousPlanError("Continuous plan source clocks are malformed.")
        try:
            body["source_clocks"] = tuple(SourceClockEvidence(**dict(item)) for item in clocks)
            body["blockers"] = tuple(body["blockers"])
            body["warnings"] = tuple(body["warnings"])
            plans.append(ContinuousPlanVersion(**body))
        except (TypeError, ValueError) as exc:
            raise ContinuousPlanError("Continuous plan ledger row is malformed.") from exc
    try:
        return ContinuousPlanLedger(
            plans=tuple(plans),
            schema_version=int(payload["schema_version"]),
            profile=str(payload["profile"]),
        )
    except (TypeError, ValueError) as exc:
        raise ContinuousPlanError("Continuous plan ledger header is malformed.") from exc


def canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            _canonical_value(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def evidence_fingerprint(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload).rstrip(b"\n")).hexdigest()


def _validate_candidate(candidate: CandidateLifecycleSnapshot) -> None:
    expected_opportunity = expected_opportunity_id(
        candidate.symbol,
        candidate.session_date,
        candidate.originating_evidence_family,
    )
    if candidate.opportunity_id != expected_opportunity:
        raise ContinuousPlanError("Candidate opportunity identity did not verify.")
    expected_setup = expected_setup_id(
        candidate.opportunity_id,
        candidate.current_setup_family,
        candidate.current_setup_sequence,
    )
    if candidate.current_setup_id != expected_setup:
        raise ContinuousPlanError("Candidate setup identity did not verify.")
    _sha256(candidate.latest_event_id, "Candidate event identity")
    _sha256(candidate.latest_evidence_fingerprint, "Candidate evidence fingerprint")
    _sha256(candidate.latest_policy_fingerprint, "Candidate policy fingerprint")
    _timestamp(candidate.updated_at, "Candidate update timestamp")


def _validate_cross_evidence(
    *,
    intraday_plan: IntradayPlanEvidence,
    candidate: CandidateLifecycleSnapshot,
    setup_revision: SetupRevisionEvidence,
    regime_snapshot: RegimeSnapshot,
    regime_context: CandidateRegimeContext,
    event_context: EventRiskContext,
    rvol_evidence: RvolEvidence,
    catalyst_snapshot: CatalystEvidenceSnapshot | None,
    created_at: datetime,
) -> None:
    if candidate.symbol != intraday_plan.symbol or (
        candidate.session_date != intraday_plan.session_date
    ):
        raise ContinuousPlanError("Candidate symbol or session did not match the plan.")
    if setup_revision.opportunity_id != candidate.opportunity_id or (
        setup_revision.setup_id != candidate.current_setup_id
    ):
        raise ContinuousPlanError("Setup revision did not match the candidate identity.")
    if setup_revision.setup_family != candidate.current_setup_family or (
        setup_revision.setup_sequence != candidate.current_setup_sequence
    ):
        raise ContinuousPlanError("Setup revision sequence or family did not match.")
    if setup_revision.setup_family != intraday_plan.setup_family:
        raise ContinuousPlanError("Setup revision family did not match the IntradayPlan.")
    if setup_revision.evidence_fingerprint != intraday_plan.source_setup_fingerprint:
        raise ContinuousPlanError("IntradayPlan did not bind the setup revision fingerprint.")
    if setup_revision.evidence_fingerprint != candidate.latest_evidence_fingerprint:
        raise ContinuousPlanError("Candidate did not bind the current setup revision.")
    if setup_revision.revision_id not in intraday_plan.source_evidence_ids:
        raise ContinuousPlanError("IntradayPlan source IDs omitted the setup revision.")
    if _timestamp(setup_revision.observed_at, "Setup observation timestamp") > created_at:
        raise ContinuousPlanError("Setup revision was observed after plan creation.")
    if _timestamp(candidate.updated_at, "Candidate update timestamp") > created_at:
        raise ContinuousPlanError("Candidate state was updated after plan creation.")

    context_payload = asdict(regime_context)
    context_fingerprint = context_payload.pop("context_fingerprint")
    if regime_fingerprint_payload(context_payload) != context_fingerprint:
        raise ContinuousPlanError("Candidate regime context fingerprint did not verify.")
    if regime_context.opportunity_id != candidate.opportunity_id or (
        regime_context.symbol != candidate.symbol
    ):
        raise ContinuousPlanError("Regime context target did not match the candidate.")
    if regime_context.snapshot_id != regime_snapshot.snapshot_id or (
        regime_context.market_regime != regime_snapshot.regime
    ):
        raise ContinuousPlanError("Regime context did not bind the supplied snapshot.")
    if _timestamp(regime_snapshot.evaluated_at, "Regime evaluation timestamp") > created_at:
        raise ContinuousPlanError("Regime snapshot was evaluated after plan creation.")

    if event_context.target_opportunity_id != candidate.opportunity_id or (
        event_context.target_symbol != candidate.symbol
    ):
        raise ContinuousPlanError("Event context target did not match the candidate.")
    if _timestamp(event_context.evaluated_at, "Event evaluation timestamp") > created_at:
        raise ContinuousPlanError("Event context was evaluated after plan creation.")

    if rvol_evidence.symbol != candidate.symbol or (
        rvol_evidence.session_date != candidate.session_date
    ):
        raise ContinuousPlanError("RVOL evidence symbol or session did not match.")
    if _timestamp(rvol_evidence.evaluated_at, "RVOL evaluation timestamp") > created_at:
        raise ContinuousPlanError("RVOL evidence was evaluated after plan creation.")

    if catalyst_snapshot is not None:
        if catalyst_snapshot.candidate_symbol != candidate.symbol:
            raise ContinuousPlanError("Catalyst evidence symbol did not match.")
        if _timestamp(catalyst_snapshot.evaluated_at, "Catalyst evaluation timestamp") > created_at:
            raise ContinuousPlanError("Catalyst evidence was evaluated after plan creation.")
        if intraday_plan.setup_driver == CATALYST_DRIVER and (
            intraday_plan.catalyst_attribution_fingerprint
            != catalyst_snapshot.fingerprint
        ):
            raise ContinuousPlanError("Catalyst-driven plan did not bind the catalyst snapshot.")


def _catalyst_fields(snapshot: CatalystEvidenceSnapshot | None) -> dict[str, str]:
    if snapshot is None:
        return {
            "catalyst_snapshot_id": "",
            "catalyst_snapshot_fingerprint": "",
            "catalyst_revision_id": "",
            "catalyst_revision_fingerprint": "",
            "catalyst_policy_fingerprint": "",
            "catalyst_authority": "",
            "catalyst_state": "",
            "catalyst_availability_status": "",
            "catalyst_is_duplicate": False,
        }
    return {
        "catalyst_snapshot_id": snapshot.snapshot_id,
        "catalyst_snapshot_fingerprint": snapshot.fingerprint,
        "catalyst_revision_id": snapshot.revision_id,
        "catalyst_revision_fingerprint": snapshot.revision_fingerprint,
        "catalyst_policy_fingerprint": snapshot.policy_fingerprint,
        "catalyst_authority": snapshot.effective_score_authority,
        "catalyst_state": snapshot.evidence_state,
        "catalyst_availability_status": snapshot.availability_status,
        "catalyst_is_duplicate": snapshot.is_duplicate,
    }


def _supported_catalyst(snapshot: CatalystEvidenceSnapshot) -> bool:
    return (
        snapshot.evidence_state == CATALYST_CURRENT
        and snapshot.availability_status in {
            CATALYST_AVAILABLE,
            CATALYST_RECOVERED,
        }
        and snapshot.effective_score_authority == CATALYST_SCORE_SUPPORTED
        and not snapshot.is_duplicate
    )


def _authority_blockers_from_record(plan: ContinuousPlanVersion) -> set[str]:
    blockers: set[str] = set()
    if plan.candidate_state != CANDIDATE_EXECUTION_ELIGIBLE:
        blockers.add("CANDIDATE_NOT_EXECUTION_ELIGIBLE")
    if not plan.intraday_plan_execution_eligible:
        blockers.add("INTRADAY_PLAN_NOT_EXECUTION_ELIGIBLE")
    if plan.setup_authority != EXECUTION_AUTHORITY:
        blockers.add("SETUP_EVIDENCE_RESEARCH_ONLY")
    if plan.regime_label == REGIME_DATA_STALE or plan.regime_sufficiency in {
        INSUFFICIENT,
        STALE,
    }:
        blockers.add("REGIME_EVIDENCE_UNSAFE")
    if plan.event_status == BLOCK_NEW_ENTRY:
        blockers.add("MACRO_EVENT_BLOCKS_NEW_ENTRY")
    elif plan.event_status == EVENT_DATA_STALE:
        blockers.add("MACRO_EVENT_EVIDENCE_STALE")
    if plan.rvol_authority_state != RVOL_EXECUTION_ELIGIBLE:
        blockers.add("RVOL_EVIDENCE_NOT_EXECUTION_ELIGIBLE")
    if plan.setup_driver == CATALYST_DRIVER:
        if not plan.catalyst_snapshot_fingerprint:
            blockers.add("CATALYST_EVIDENCE_REQUIRED")
        elif (
            plan.catalyst_authority != CATALYST_SCORE_SUPPORTED
            or plan.catalyst_state != CATALYST_CURRENT
            or plan.catalyst_availability_status
            not in {CATALYST_AVAILABLE, CATALYST_RECOVERED}
            or plan.catalyst_is_duplicate
        ):
            blockers.add("CATALYST_EVIDENCE_NOT_AUTHORITATIVE")
    return blockers


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _canonical_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ContinuousPlanError(f"{name} is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContinuousPlanError(f"{name} requires a UTC offset.")
    return parsed


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContinuousPlanError(f"{name} requires a UTC offset.")
    return value


def _sha256(value: object, name: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise ContinuousPlanError(f"{name} is invalid.")
    return normalized


def _required_text(value: object, name: str) -> str:
    normalized = str(value).strip()
    if not normalized or not _IDENTITY.fullmatch(normalized):
        raise ContinuousPlanError(f"{name} is invalid.")
    return normalized


def _decimal(value: object) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None
