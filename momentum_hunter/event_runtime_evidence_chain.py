"""Dormant topology-bound persistence for one continuous evidence chain.

The chain session routes candidate, plan, source-admission, and decision-cycle
writes through one current Engine Host writer session. It provides ordering and
cross-ledger identity checks, but it does not select an installed root, start a
host, discover evidence, contact a provider, or execute an order.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from momentum_hunter.candidate_lifecycle import (
    CandidateLifecycleEvent,
    CandidateLifecycleLedger,
    CandidateLifecycleStore,
    RuntimeAvailabilityEvent,
)
from momentum_hunter.continuous_plan_version import (
    ContinuousPlanDecision,
    ContinuousPlanLedger,
    ContinuousPlanStore,
    ContinuousPlanVersion,
    validate_plan_version,
)
from momentum_hunter.event_driven_decision_cycle import (
    EventDecisionCycleCoordinator,
    EventDecisionCycleLedger,
    EventDecisionCyclePolicy,
    EventDecisionCycleResult,
    EventDecisionCycleStore,
    validate_policy as validate_event_cycle_policy,
)
from momentum_hunter.event_runtime_topology import (
    CANDIDATE_LIFECYCLE_LEDGER,
    CONTINUOUS_PLAN_LEDGER,
    EVENT_DECISION_CYCLE_LEDGER,
    RUNTIME_SOURCE_ADMISSION_LEDGER,
    EventRuntimeTopology,
    RuntimeWriterClaim,
    artifact_path,
)
from momentum_hunter.event_runtime_writer_session import (
    RuntimeSourceAdmissionWriterSession,
)
from momentum_hunter.event_source_admission import (
    CANDIDATE_LIFECYCLE_SOURCE,
    RuntimeSourceAdmission,
    validate_runtime_source_admission,
)


class RuntimeEvidenceChainError(ValueError):
    """Raised when cross-ledger runtime evidence is missing or contradictory."""


class RuntimeEvidenceChainWriterSession:
    """Persist one ordered evidence chain under a sole writer lifetime lease."""

    def __init__(
        self,
        *,
        topology: EventRuntimeTopology,
        writer_claim: RuntimeWriterClaim,
        current_host_instance_id: str,
        lease_timeout_seconds: float = 5.0,
    ) -> None:
        self.topology = topology
        self._writer_session = RuntimeSourceAdmissionWriterSession(
            topology=topology,
            writer_claim=writer_claim,
            current_host_instance_id=current_host_instance_id,
            lease_timeout_seconds=lease_timeout_seconds,
        )
        self.candidate_path = artifact_path(topology, CANDIDATE_LIFECYCLE_LEDGER)
        self.plan_path = artifact_path(topology, CONTINUOUS_PLAN_LEDGER)
        self.source_admission_path = artifact_path(
            topology,
            RUNTIME_SOURCE_ADMISSION_LEDGER,
        )
        self.cycle_path = artifact_path(topology, EVENT_DECISION_CYCLE_LEDGER)
        self._candidate_store = CandidateLifecycleStore(self.candidate_path)
        self._plan_store = ContinuousPlanStore(self.plan_path)
        self._cycle_store = EventDecisionCycleStore(
            self.cycle_path,
            lease_timeout_seconds=lease_timeout_seconds,
        )
        self._operation_lock = threading.RLock()

    @property
    def state(self) -> str:
        return self._writer_session.state

    @contextmanager
    def activate(self) -> Iterator[RuntimeEvidenceChainWriterSession]:
        with self._writer_session.activate():
            yield self

    def append_candidate_event(
        self,
        event: CandidateLifecycleEvent,
    ) -> CandidateLifecycleEvent:
        with self._authorized_store(
            CANDIDATE_LIFECYCLE_LEDGER,
            self._candidate_store.path,
        ):
            return self._candidate_store.append_event(event)

    def append_availability_event(
        self,
        event: RuntimeAvailabilityEvent,
    ) -> RuntimeAvailabilityEvent:
        with self._authorized_store(
            CANDIDATE_LIFECYCLE_LEDGER,
            self._candidate_store.path,
        ):
            return self._candidate_store.append_availability_event(event)

    def append_plan_version(
        self,
        plan: ContinuousPlanVersion,
    ) -> ContinuousPlanVersion:
        validate_plan_version(plan)
        if plan.configuration_fingerprint != self.topology.configuration_fingerprint:
            raise RuntimeEvidenceChainError(
                "Continuous plan belongs to a different runtime configuration."
            )
        with self._authorized_store(CONTINUOUS_PLAN_LEDGER, self._plan_store.path):
            candidate_ledger = self._candidate_store.load()
            _require_candidate_binding(candidate_ledger, plan)
            _require_plan_ledger_configuration(
                self._plan_store.load(),
                self.topology.configuration_fingerprint,
            )
            return self._plan_store.append(plan)

    def append_source_admission(
        self,
        admission: RuntimeSourceAdmission,
    ) -> RuntimeSourceAdmission:
        validate_runtime_source_admission(admission)
        with self._authorized_store(
            RUNTIME_SOURCE_ADMISSION_LEDGER,
            self.source_admission_path,
        ):
            plan_ledger = self._plan_store.load()
            _require_plan_ledger_configuration(
                plan_ledger,
                self.topology.configuration_fingerprint,
            )
            plan = _require_persisted_plan(plan_ledger, admission)
            candidate_ledger = self._candidate_store.load()
            _require_candidate_binding(candidate_ledger, plan)
            _require_admission_source_binding(
                admission,
                plan=plan,
                candidate_ledger=candidate_ledger,
            )
            return self._writer_session.append_source_admission(admission)

    def process_decision_cycle(
        self,
        admission: RuntimeSourceAdmission,
        *,
        policy: EventDecisionCyclePolicy,
        recorded_at: datetime,
        cycle_started_at: datetime | None = None,
        plan_version: ContinuousPlanVersion | None = None,
        decision: ContinuousPlanDecision | None = None,
    ) -> EventDecisionCycleResult:
        validate_runtime_source_admission(admission)
        validate_event_cycle_policy(policy)
        if (
            policy.configuration_fingerprint
            != self.topology.configuration_fingerprint
            or policy.fingerprint != admission.event_cycle_policy_fingerprint
        ):
            raise RuntimeEvidenceChainError(
                "Decision-cycle policy does not match the admitted runtime source."
            )
        with self._authorized_store(
            EVENT_DECISION_CYCLE_LEDGER,
            self._cycle_store.path,
        ):
            plan_ledger = self._plan_store.load()
            _require_plan_ledger_configuration(
                plan_ledger,
                self.topology.configuration_fingerprint,
            )
            plan = _require_persisted_plan(plan_ledger, admission)
            _require_candidate_binding(self._candidate_store.load(), plan)
            self._writer_session.require_source_admission(admission)
            _require_cycle_ledger_configuration(
                self._cycle_store.load(),
                self.topology.configuration_fingerprint,
            )
            if plan_version is not None and plan_version != plan:
                raise RuntimeEvidenceChainError(
                    "Decision cycle supplied a different persisted plan version."
                )
            coordinator = EventDecisionCycleCoordinator(
                self._cycle_store,
                policy=policy,
            )
            return coordinator.process(
                admission.trigger,
                recorded_at=recorded_at,
                cycle_started_at=cycle_started_at,
                plan_version=plan_version,
                decision=decision,
            )

    @contextmanager
    def _authorized_store(
        self,
        artifact_name: str,
        actual_path: Path,
    ) -> Iterator[None]:
        with self._operation_lock:
            with self._writer_session.authorized_artifact_append(
                artifact_name
            ) as expected_path:
                if actual_path.resolve() != expected_path.resolve():
                    raise RuntimeEvidenceChainError(
                        "Runtime evidence store escaped its topology path."
                    )
                yield


def _require_candidate_binding(
    ledger: CandidateLifecycleLedger,
    plan: ContinuousPlanVersion,
) -> CandidateLifecycleEvent:
    event = next(
        (item for item in ledger.events if item.event_id == plan.candidate_event_id),
        None,
    )
    if event is None:
        raise RuntimeEvidenceChainError(
            "Continuous plan requires its exact persisted candidate event."
        )
    if (
        event.evidence_fingerprint != plan.candidate_evidence_fingerprint
        or event.policy_fingerprint != plan.candidate_policy_fingerprint
        or event.opportunity_id != plan.opportunity_id
        or event.symbol != plan.symbol
        or event.session_date != plan.session_date
        or event.next_state != plan.candidate_state
        or event.receipt_timestamp != plan.candidate_updated_at
        or event.setup_id != plan.setup_id
        or event.setup_family != plan.setup_family
        or event.setup_sequence != plan.setup_sequence
    ):
        raise RuntimeEvidenceChainError(
            "Persisted candidate event contradicts the continuous plan."
        )
    return event


def _require_persisted_plan(
    ledger: ContinuousPlanLedger,
    admission: RuntimeSourceAdmission,
) -> ContinuousPlanVersion:
    plan = next(
        (
            item
            for item in ledger.plans
            if item.plan_version_id == admission.plan_version_id
        ),
        None,
    )
    if plan is None:
        raise RuntimeEvidenceChainError(
            "Runtime source admission requires its exact persisted plan."
        )
    if (
        plan.fingerprint != admission.plan_version_fingerprint
        or plan.configuration_fingerprint != admission.configuration_fingerprint
    ):
        raise RuntimeEvidenceChainError(
            "Persisted plan contradicts the runtime source admission."
        )
    return plan


def _require_plan_ledger_configuration(
    ledger: ContinuousPlanLedger,
    configuration_fingerprint: str,
) -> None:
    if any(
        plan.configuration_fingerprint != configuration_fingerprint
        for plan in ledger.plans
    ):
        raise RuntimeEvidenceChainError(
            "Continuous plan ledger contains a different runtime configuration."
        )


def _require_cycle_ledger_configuration(
    ledger: EventDecisionCycleLedger,
    configuration_fingerprint: str,
) -> None:
    if any(
        receipt.policy.configuration_fingerprint != configuration_fingerprint
        for receipt in ledger.receipts
    ) or any(
        cycle.configuration_fingerprint != configuration_fingerprint
        for cycle in ledger.cycles
    ):
        raise RuntimeEvidenceChainError(
            "Decision-cycle ledger contains a different runtime configuration."
        )


def _require_admission_source_binding(
    admission: RuntimeSourceAdmission,
    *,
    plan: ContinuousPlanVersion,
    candidate_ledger: CandidateLifecycleLedger,
) -> None:
    if admission.source_kind != CANDIDATE_LIFECYCLE_SOURCE:
        return
    event = _require_candidate_binding(candidate_ledger, plan)
    if (
        admission.source_record_id != event.event_id
        or admission.source_record_fingerprint != event.fingerprint
        or admission.source_authority_fingerprint != event.evidence_fingerprint
    ):
        raise RuntimeEvidenceChainError(
            "Runtime source admission contradicts its persisted candidate event."
        )
