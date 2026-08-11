"""Dormant orchestration for one prebuilt continuous evidence transaction.

The orchestrator validates an explicit candidate/plan/admission/decision bundle,
previews it against the persisted prefix, and then replays every stage under one
topology-bound sole-writer lease. It does not build evidence, start a host,
contact a provider or account, or invoke broker/order behavior.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Iterator

from momentum_hunter.candidate_lifecycle import (
    CandidateLifecycleEvent,
    CandidateLifecycleLedger,
    CandidateLifecycleStore,
    validate_lifecycle_event,
)
from momentum_hunter.continuous_plan_version import (
    ContinuousPlanDecision,
    ContinuousPlanLedger,
    ContinuousPlanStore,
    ContinuousPlanVersion,
    validate_decision,
    validate_plan_version,
)
from momentum_hunter.event_driven_decision_cycle import (
    DUPLICATE,
    EventDecisionCycleCoordinator,
    EventDecisionCycleLedger,
    EventDecisionCyclePolicy,
    EventDecisionCycleResult,
    EventDecisionCycleStore,
    validate_ledger as validate_cycle_ledger,
    validate_policy as validate_event_cycle_policy,
)
from momentum_hunter.event_runtime_evidence_chain import (
    RuntimeEvidenceChainWriterSession,
    validate_runtime_evidence_chain_prefix,
)
from momentum_hunter.event_runtime_recovery import (
    RuntimeEvidenceRecoveryPlanner,
    RuntimeEvidenceRecoverySnapshot,
)
from momentum_hunter.event_runtime_topology import (
    PYTHON_ENGINE_HOST,
    EventRuntimeTopology,
    RuntimeWriterClaim,
    validate_event_runtime_topology,
)
from momentum_hunter.event_source_admission import (
    RuntimeSourceAdmission,
    RuntimeSourceAdmissionStore,
    build_runtime_source_admission_ledger,
    validate_runtime_source_admission,
)


CREATED = "CREATED"
RECOVERED = "RECOVERED"
DUPLICATE_REPLAY = "DUPLICATE_REPLAY"
ORCHESTRATION_STATUSES = frozenset({CREATED, RECOVERED, DUPLICATE_REPLAY})

RUNTIME_ORCHESTRATION_SCHEMA_VERSION = 1
RUNTIME_ORCHESTRATION_PROFILE = "runtime-evidence-orchestration-v1"

_CANDIDATE_STAGE = "CANDIDATE"
_PLAN_STAGE = "PLAN"
_ADMISSION_STAGE = "SOURCE_ADMISSION"
_DECISION_STAGE = "DECISION_CYCLE"
_STAGE_ORDER = (
    _CANDIDATE_STAGE,
    _PLAN_STAGE,
    _ADMISSION_STAGE,
    _DECISION_STAGE,
)


class RuntimeEvidenceOrchestrationError(ValueError):
    """Raised when an orchestration request or result cannot be trusted."""


@dataclass(frozen=True)
class RuntimeEvidenceOrchestrationRequest:
    candidate_events: tuple[CandidateLifecycleEvent, ...]
    plan_version: ContinuousPlanVersion
    source_admission: RuntimeSourceAdmission
    policy: EventDecisionCyclePolicy
    decision: ContinuousPlanDecision
    cycle_started_at: datetime
    recorded_at: datetime


@dataclass(frozen=True)
class RuntimeEvidenceOrchestrationResult:
    status: str
    target_plan_version_id: str
    target_admission_id: str
    target_trigger_id: str
    stages_present_before: tuple[str, ...]
    before_snapshot: RuntimeEvidenceRecoverySnapshot
    after_snapshot: RuntimeEvidenceRecoverySnapshot
    decision_result: EventDecisionCycleResult
    schema_version: int = RUNTIME_ORCHESTRATION_SCHEMA_VERSION
    profile: str = RUNTIME_ORCHESTRATION_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class _Preview:
    result: EventDecisionCycleResult
    stages_present_before: tuple[str, ...]


class _InMemoryCycleStore:
    def __init__(self, ledger: EventDecisionCycleLedger) -> None:
        validate_cycle_ledger(ledger)
        self._ledger = ledger

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def load(self) -> EventDecisionCycleLedger:
        return self._ledger

    def save(self, ledger: EventDecisionCycleLedger) -> None:
        validate_cycle_ledger(ledger)
        self._ledger = ledger


class RuntimeEvidenceOrchestrator:
    """Replay one already-built evidence request under current writer authority."""

    def __init__(
        self,
        *,
        topology: EventRuntimeTopology,
        writer_claim: RuntimeWriterClaim,
        current_host_instance_id: str,
        lease_timeout_seconds: float = 5.0,
    ) -> None:
        validate_event_runtime_topology(topology)
        self.topology = topology
        self._chain = RuntimeEvidenceChainWriterSession(
            topology=topology,
            writer_claim=writer_claim,
            current_host_instance_id=current_host_instance_id,
            lease_timeout_seconds=lease_timeout_seconds,
        )
        self._planner = RuntimeEvidenceRecoveryPlanner(
            topology=topology,
            process_role=PYTHON_ENGINE_HOST,
            lease_timeout_seconds=lease_timeout_seconds,
        )
        self._candidate_store = CandidateLifecycleStore(self._chain.candidate_path)
        self._plan_store = ContinuousPlanStore(self._chain.plan_path)
        self._admission_store = RuntimeSourceAdmissionStore(
            self._chain.source_admission_path,
            evidence_program_id=topology.evidence_program_id,
            configuration_fingerprint=topology.configuration_fingerprint,
            lease_timeout_seconds=lease_timeout_seconds,
        )
        self._cycle_store = EventDecisionCycleStore(
            self._chain.cycle_path,
            lease_timeout_seconds=lease_timeout_seconds,
        )

    def execute(
        self,
        request: RuntimeEvidenceOrchestrationRequest,
    ) -> RuntimeEvidenceOrchestrationResult:
        validate_runtime_orchestration_request(request, topology=self.topology)
        with self._chain.activate():
            before = self._planner.inspect()
            preview = self._preview(request)
            for event in request.candidate_events:
                self._chain.append_candidate_event(event)
            self._chain.append_plan_version(request.plan_version)
            self._chain.append_source_admission(request.source_admission)
            actual = self._chain.process_decision_cycle(
                request.source_admission,
                policy=request.policy,
                cycle_started_at=request.cycle_started_at,
                plan_version=request.plan_version,
                decision=request.decision,
                recorded_at=request.recorded_at,
            )
            if actual != preview.result:
                raise RuntimeEvidenceOrchestrationError(
                    "Persisted decision result differed from its in-memory preview."
                )
            after = self._planner.inspect()

        status = _orchestration_status(preview)
        provisional = RuntimeEvidenceOrchestrationResult(
            status=status,
            target_plan_version_id=request.plan_version.plan_version_id,
            target_admission_id=request.source_admission.admission_id,
            target_trigger_id=request.source_admission.trigger.trigger_id,
            stages_present_before=preview.stages_present_before,
            before_snapshot=before,
            after_snapshot=after,
            decision_result=actual,
        )
        result = replace(
            provisional,
            fingerprint=runtime_orchestration_result_fingerprint(provisional),
        )
        validate_runtime_orchestration_result(result)
        return result

    def _preview(self, request: RuntimeEvidenceOrchestrationRequest) -> _Preview:
        candidate_ledger = self._candidate_store.load()
        plan_ledger = self._plan_store.load()
        admission_ledger = self._admission_store.load()
        cycle_ledger = self._cycle_store.load()

        candidate_events = _merge_exact(
            candidate_ledger.events,
            request.candidate_events,
            identity_name="event_id",
            evidence_name="candidate event",
        )
        plans = _merge_exact(
            plan_ledger.plans,
            (request.plan_version,),
            identity_name="plan_version_id",
            evidence_name="continuous plan",
        )
        admissions = _merge_exact(
            admission_ledger.admissions,
            (request.source_admission,),
            identity_name="admission_id",
            evidence_name="runtime source admission",
        )
        proposed_candidates = CandidateLifecycleLedger(
            events=candidate_events,
            availability_events=candidate_ledger.availability_events,
        )
        proposed_plans = ContinuousPlanLedger(plans=plans)
        proposed_admissions = build_runtime_source_admission_ledger(
            evidence_program_id=self.topology.evidence_program_id,
            configuration_fingerprint=self.topology.configuration_fingerprint,
            admissions=admissions,
        )
        validate_runtime_evidence_chain_prefix(
            self.topology,
            candidate_ledger=proposed_candidates,
            plan_ledger=proposed_plans,
            admission_ledger=proposed_admissions,
            cycle_ledger=cycle_ledger,
        )

        memory_store = _InMemoryCycleStore(cycle_ledger)
        decision_result = EventDecisionCycleCoordinator(
            memory_store,
            policy=request.policy,
        ).process(
            request.source_admission.trigger,
            cycle_started_at=request.cycle_started_at,
            plan_version=request.plan_version,
            decision=request.decision,
            recorded_at=request.recorded_at,
        )
        validate_runtime_evidence_chain_prefix(
            self.topology,
            candidate_ledger=proposed_candidates,
            plan_ledger=proposed_plans,
            admission_ledger=proposed_admissions,
            cycle_ledger=memory_store.load(),
        )

        existing_event_ids = {item.event_id for item in candidate_ledger.events}
        stages = []
        if any(
            item.event_id in existing_event_ids for item in request.candidate_events
        ):
            stages.append(_CANDIDATE_STAGE)
        if any(
            item.plan_version_id == request.plan_version.plan_version_id
            for item in plan_ledger.plans
        ):
            stages.append(_PLAN_STAGE)
        if any(
            item.admission_id == request.source_admission.admission_id
            for item in admission_ledger.admissions
        ):
            stages.append(_ADMISSION_STAGE)
        if any(
            item.trigger.trigger_id == request.source_admission.trigger.trigger_id
            for item in cycle_ledger.receipts
        ):
            stages.append(_DECISION_STAGE)
        return _Preview(
            result=decision_result,
            stages_present_before=tuple(stages),
        )


def validate_runtime_orchestration_request(
    request: RuntimeEvidenceOrchestrationRequest,
    *,
    topology: EventRuntimeTopology,
) -> None:
    validate_event_runtime_topology(topology)
    for event in request.candidate_events:
        validate_lifecycle_event(event)
    validate_plan_version(request.plan_version)
    validate_runtime_source_admission(request.source_admission)
    validate_event_cycle_policy(request.policy)
    validate_decision(request.decision)
    _aware(request.cycle_started_at, "Decision-cycle start timestamp")
    _aware(request.recorded_at, "Decision recording timestamp")
    configuration = topology.configuration_fingerprint
    if any(
        value != configuration
        for value in (
            request.plan_version.configuration_fingerprint,
            request.source_admission.configuration_fingerprint,
            request.policy.configuration_fingerprint,
        )
    ):
        raise RuntimeEvidenceOrchestrationError(
            "Orchestration request belongs to a different runtime configuration."
        )
    if (
        request.source_admission.plan_version_id
        != request.plan_version.plan_version_id
        or request.source_admission.plan_version_fingerprint
        != request.plan_version.fingerprint
        or request.source_admission.event_cycle_policy_fingerprint
        != request.policy.fingerprint
    ):
        raise RuntimeEvidenceOrchestrationError(
            "Orchestration request does not bind one exact plan and policy."
        )


def runtime_orchestration_result_fingerprint(
    result: RuntimeEvidenceOrchestrationResult,
) -> str:
    payload = asdict(replace(result, fingerprint=""))
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def validate_runtime_orchestration_result(
    result: RuntimeEvidenceOrchestrationResult,
) -> None:
    if (
        result.schema_version != RUNTIME_ORCHESTRATION_SCHEMA_VERSION
        or result.profile != RUNTIME_ORCHESTRATION_PROFILE
    ):
        raise RuntimeEvidenceOrchestrationError(
            "Runtime orchestration result schema identity is unsupported."
        )
    if result.status not in ORCHESTRATION_STATUSES:
        raise RuntimeEvidenceOrchestrationError(
            "Runtime orchestration result status is unsupported."
        )
    if tuple(stage for stage in _STAGE_ORDER if stage in result.stages_present_before) != (
        result.stages_present_before
    ) or len(set(result.stages_present_before)) != len(
        result.stages_present_before
    ):
        raise RuntimeEvidenceOrchestrationError(
            "Runtime orchestration prior stages are invalid."
        )
    if (
        result.target_plan_version_id
        in result.after_snapshot.pending_plan_version_ids
        or result.target_admission_id
        in result.after_snapshot.pending_admission_ids
        or result.target_admission_id
        not in result.after_snapshot.completed_admission_ids
        or result.decision_result.receipt.trigger.trigger_id
        != result.target_trigger_id
        or result.decision_result.receipt.plan_version_id
        != result.target_plan_version_id
    ):
        raise RuntimeEvidenceOrchestrationError(
            "Runtime orchestration did not complete its exact target evidence."
        )
    expected_status = _orchestration_status(
        _Preview(
            result=result.decision_result,
            stages_present_before=result.stages_present_before,
        )
    )
    if result.status != expected_status:
        raise RuntimeEvidenceOrchestrationError(
            "Runtime orchestration status contradicts its persisted result."
        )
    if result.fingerprint != runtime_orchestration_result_fingerprint(result):
        raise RuntimeEvidenceOrchestrationError(
            "Runtime orchestration result fingerprint is invalid."
        )


def _merge_exact(existing, incoming, *, identity_name: str, evidence_name: str):
    merged = list(existing)
    by_identity = {getattr(item, identity_name): item for item in existing}
    for item in incoming:
        identity = getattr(item, identity_name)
        prior = by_identity.get(identity)
        if prior is None:
            merged.append(item)
            by_identity[identity] = item
        elif prior != item:
            raise RuntimeEvidenceOrchestrationError(
                f"Persisted {evidence_name} identity is contradictory."
            )
    return tuple(merged)


def _orchestration_status(preview: _Preview) -> str:
    if preview.result.status == DUPLICATE:
        return DUPLICATE_REPLAY
    if preview.stages_present_before:
        return RECOVERED
    return CREATED


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeEvidenceOrchestrationError(f"{name} must be timezone-aware.")
    return value
