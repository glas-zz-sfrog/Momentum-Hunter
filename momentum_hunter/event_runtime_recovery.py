"""Read-only recovery planning for a dormant continuous evidence chain.

The planner inspects persisted chain prefixes and identifies the next safe
orchestration stage. It never repairs evidence, writes a ledger, starts a host,
contacts a provider, or advances a decision cycle.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from momentum_hunter.candidate_lifecycle import (
    CandidateLifecycleError,
    CandidateLifecycleStore,
)
from momentum_hunter.continuous_plan_version import (
    ContinuousPlanError,
    ContinuousPlanStore,
)
from momentum_hunter.event_driven_decision_cycle import (
    EventDecisionCycleError,
    EventDecisionCycleStore,
)
from momentum_hunter.event_runtime_evidence_chain import (
    RuntimeEvidenceChainError,
    validate_runtime_evidence_chain_prefix,
)
from momentum_hunter.event_runtime_topology import (
    CANDIDATE_LIFECYCLE_LEDGER,
    CONTINUOUS_PLAN_LEDGER,
    EVENT_DECISION_CYCLE_LEDGER,
    OFFLINE_REVIEW,
    READ,
    RUNTIME_SOURCE_ADMISSION_LEDGER,
    EventRuntimeTopology,
    artifact_path,
    authorize_runtime_artifact_access,
    validate_event_runtime_topology,
)
from momentum_hunter.event_source_admission import (
    RuntimeSourceAdmissionError,
    RuntimeSourceAdmissionStore,
)


EMPTY = "EMPTY"
WAITING_FOR_PLAN = "WAITING_FOR_PLAN"
RESUME_SOURCE_ADMISSION = "RESUME_SOURCE_ADMISSION"
RESUME_DECISION_CYCLE = "RESUME_DECISION_CYCLE"
RESUME_MULTIPLE_STAGES = "RESUME_MULTIPLE_STAGES"
COMPLETE = "COMPLETE"

NO_ACTION = "NO_ACTION"
WAIT_FOR_PLAN = "WAIT_FOR_PLAN"
APPEND_SOURCE_ADMISSION = "APPEND_SOURCE_ADMISSION"
PROCESS_DECISION_CYCLE = "PROCESS_DECISION_CYCLE"
RESUME_IN_STAGE_ORDER = "RESUME_IN_STAGE_ORDER"

RECOVERY_STATUSES = frozenset(
    {
        EMPTY,
        WAITING_FOR_PLAN,
        RESUME_SOURCE_ADMISSION,
        RESUME_DECISION_CYCLE,
        RESUME_MULTIPLE_STAGES,
        COMPLETE,
    }
)
RECOVERY_ACTIONS = frozenset(
    {
        NO_ACTION,
        WAIT_FOR_PLAN,
        APPEND_SOURCE_ADMISSION,
        PROCESS_DECISION_CYCLE,
        RESUME_IN_STAGE_ORDER,
    }
)

RUNTIME_RECOVERY_SCHEMA_VERSION = 1
RUNTIME_RECOVERY_PROFILE = "runtime-evidence-recovery-v1"

_ARTIFACT_ORDER = (
    CANDIDATE_LIFECYCLE_LEDGER,
    CONTINUOUS_PLAN_LEDGER,
    RUNTIME_SOURCE_ADMISSION_LEDGER,
    EVENT_DECISION_CYCLE_LEDGER,
)


class RuntimeEvidenceRecoveryError(ValueError):
    """Raised when recovery inspection cannot trust the persisted prefix."""


@dataclass(frozen=True)
class RuntimeEvidenceRecoverySnapshot:
    topology_id: str
    topology_fingerprint: str
    evidence_program_id: str
    configuration_fingerprint: str
    process_role: str
    status: str
    next_action: str
    candidate_event_count: int
    availability_event_count: int
    plan_count: int
    admission_count: int
    receipt_count: int
    cycle_count: int
    pending_plan_version_ids: tuple[str, ...]
    pending_admission_ids: tuple[str, ...]
    completed_admission_ids: tuple[str, ...]
    artifact_hashes: tuple[tuple[str, str], ...]
    schema_version: int = RUNTIME_RECOVERY_SCHEMA_VERSION
    profile: str = RUNTIME_RECOVERY_PROFILE
    fingerprint: str = ""


class RuntimeEvidenceRecoveryPlanner:
    """Inspect one topology namespace without mutating its evidence."""

    def __init__(
        self,
        *,
        topology: EventRuntimeTopology,
        process_role: str = OFFLINE_REVIEW,
        lease_timeout_seconds: float = 5.0,
    ) -> None:
        validate_event_runtime_topology(topology)
        self.topology = topology
        self.process_role = str(process_role).strip().upper()
        self.paths = tuple(
            (artifact, artifact_path(topology, artifact))
            for artifact in _ARTIFACT_ORDER
        )
        for artifact, _ in self.paths:
            access = authorize_runtime_artifact_access(
                topology,
                artifact_name=artifact,
                operation=READ,
                process_role=self.process_role,
            )
            if not access.allowed:
                raise RuntimeEvidenceRecoveryError(
                    f"Runtime recovery read was denied: {access.reason}."
                )

        paths = dict(self.paths)
        self._candidate_store = CandidateLifecycleStore(
            paths[CANDIDATE_LIFECYCLE_LEDGER]
        )
        self._plan_store = ContinuousPlanStore(paths[CONTINUOUS_PLAN_LEDGER])
        self._admission_store = RuntimeSourceAdmissionStore(
            paths[RUNTIME_SOURCE_ADMISSION_LEDGER],
            evidence_program_id=topology.evidence_program_id,
            configuration_fingerprint=topology.configuration_fingerprint,
            lease_timeout_seconds=lease_timeout_seconds,
        )
        self._cycle_store = EventDecisionCycleStore(
            paths[EVENT_DECISION_CYCLE_LEDGER],
            lease_timeout_seconds=lease_timeout_seconds,
        )

    def inspect(self) -> RuntimeEvidenceRecoverySnapshot:
        try:
            hashes_before = _artifact_hashes(self.paths)
            candidate_ledger = self._candidate_store.load()
            plan_ledger = self._plan_store.load()
            admission_ledger = self._admission_store.load()
            cycle_ledger = self._cycle_store.load()
            validate_runtime_evidence_chain_prefix(
                self.topology,
                candidate_ledger=candidate_ledger,
                plan_ledger=plan_ledger,
                admission_ledger=admission_ledger,
                cycle_ledger=cycle_ledger,
            )
            hashes_after = _artifact_hashes(self.paths)
            if hashes_before != hashes_after:
                raise RuntimeEvidenceRecoveryError(
                    "Runtime evidence changed during recovery inspection."
                )
        except (
            CandidateLifecycleError,
            ContinuousPlanError,
            EventDecisionCycleError,
            RuntimeEvidenceChainError,
            RuntimeSourceAdmissionError,
            RuntimeEvidenceRecoveryError,
            OSError,
        ) as exc:
            if isinstance(exc, RuntimeEvidenceRecoveryError):
                raise
            raise RuntimeEvidenceRecoveryError(
                "Runtime evidence recovery inspection rejected persisted evidence: "
                f"{type(exc).__name__}."
            ) from exc

        admitted_plan_ids = {
            admission.plan_version_id for admission in admission_ledger.admissions
        }
        receipts_by_trigger = {
            receipt.trigger.trigger_id: receipt for receipt in cycle_ledger.receipts
        }
        pending_plan_ids = tuple(
            plan.plan_version_id
            for plan in plan_ledger.plans
            if plan.plan_version_id not in admitted_plan_ids
        )
        pending_admission_ids = tuple(
            admission.admission_id
            for admission in admission_ledger.admissions
            if admission.trigger.trigger_id not in receipts_by_trigger
        )
        completed_admission_ids = tuple(
            admission.admission_id
            for admission in admission_ledger.admissions
            if admission.trigger.trigger_id in receipts_by_trigger
        )
        status, next_action = _classify_recovery(
            candidate_count=len(candidate_ledger.events),
            availability_count=len(candidate_ledger.availability_events),
            plan_count=len(plan_ledger.plans),
            pending_plan_ids=pending_plan_ids,
            pending_admission_ids=pending_admission_ids,
        )
        provisional = RuntimeEvidenceRecoverySnapshot(
            topology_id=self.topology.topology_id,
            topology_fingerprint=self.topology.fingerprint,
            evidence_program_id=self.topology.evidence_program_id,
            configuration_fingerprint=self.topology.configuration_fingerprint,
            process_role=self.process_role,
            status=status,
            next_action=next_action,
            candidate_event_count=len(candidate_ledger.events),
            availability_event_count=len(candidate_ledger.availability_events),
            plan_count=len(plan_ledger.plans),
            admission_count=len(admission_ledger.admissions),
            receipt_count=len(cycle_ledger.receipts),
            cycle_count=len(cycle_ledger.cycles),
            pending_plan_version_ids=pending_plan_ids,
            pending_admission_ids=pending_admission_ids,
            completed_admission_ids=completed_admission_ids,
            artifact_hashes=hashes_after,
        )
        snapshot = replace(
            provisional,
            fingerprint=runtime_recovery_snapshot_fingerprint(provisional),
        )
        validate_runtime_recovery_snapshot(snapshot)
        return snapshot


def runtime_recovery_snapshot_fingerprint(
    snapshot: RuntimeEvidenceRecoverySnapshot,
) -> str:
    payload = asdict(replace(snapshot, fingerprint=""))
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_runtime_recovery_snapshot(
    snapshot: RuntimeEvidenceRecoverySnapshot,
) -> None:
    if (
        snapshot.schema_version != RUNTIME_RECOVERY_SCHEMA_VERSION
        or snapshot.profile != RUNTIME_RECOVERY_PROFILE
    ):
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot schema identity is unsupported."
        )
    if snapshot.status not in RECOVERY_STATUSES:
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot status is unsupported."
        )
    if snapshot.next_action not in RECOVERY_ACTIONS:
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot action is unsupported."
        )
    counts = (
        snapshot.candidate_event_count,
        snapshot.availability_event_count,
        snapshot.plan_count,
        snapshot.admission_count,
        snapshot.receipt_count,
        snapshot.cycle_count,
    )
    if any(value < 0 for value in counts):
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot count is invalid."
        )
    if (
        len(snapshot.pending_plan_version_ids)
        + snapshot.admission_count
        != snapshot.plan_count
        or len(snapshot.pending_admission_ids)
        + len(snapshot.completed_admission_ids)
        != snapshot.admission_count
        or snapshot.receipt_count != len(snapshot.completed_admission_ids)
        or snapshot.cycle_count > snapshot.receipt_count
    ):
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot stage counts are contradictory."
        )
    identity_groups = (
        snapshot.pending_plan_version_ids,
        snapshot.pending_admission_ids,
        snapshot.completed_admission_ids,
    )
    if any(len(values) != len(set(values)) for values in identity_groups) or (
        set(snapshot.pending_admission_ids)
        & set(snapshot.completed_admission_ids)
    ):
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot identities are contradictory."
        )
    expected_status, expected_action = _classify_recovery(
        candidate_count=snapshot.candidate_event_count,
        availability_count=snapshot.availability_event_count,
        plan_count=snapshot.plan_count,
        pending_plan_ids=snapshot.pending_plan_version_ids,
        pending_admission_ids=snapshot.pending_admission_ids,
    )
    if (snapshot.status, snapshot.next_action) != (
        expected_status,
        expected_action,
    ):
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot classification is contradictory."
        )
    if tuple(name for name, _ in snapshot.artifact_hashes) != _ARTIFACT_ORDER:
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot artifact order is invalid."
        )
    for _, fingerprint in snapshot.artifact_hashes:
        if fingerprint and (
            len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise RuntimeEvidenceRecoveryError(
                "Runtime recovery artifact fingerprint is invalid."
            )
    if snapshot.fingerprint != runtime_recovery_snapshot_fingerprint(snapshot):
        raise RuntimeEvidenceRecoveryError(
            "Runtime recovery snapshot fingerprint is invalid."
        )


def _classify_recovery(
    *,
    candidate_count: int,
    availability_count: int,
    plan_count: int,
    pending_plan_ids: tuple[str, ...],
    pending_admission_ids: tuple[str, ...],
) -> tuple[str, str]:
    if not any((candidate_count, availability_count, plan_count)):
        return EMPTY, NO_ACTION
    if plan_count == 0:
        return WAITING_FOR_PLAN, WAIT_FOR_PLAN
    if pending_plan_ids and pending_admission_ids:
        return RESUME_MULTIPLE_STAGES, RESUME_IN_STAGE_ORDER
    if pending_plan_ids:
        return RESUME_SOURCE_ADMISSION, APPEND_SOURCE_ADMISSION
    if pending_admission_ids:
        return RESUME_DECISION_CYCLE, PROCESS_DECISION_CYCLE
    return COMPLETE, NO_ACTION


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_hashes(
    paths: tuple[tuple[str, Path], ...],
) -> tuple[tuple[str, str], ...]:
    return tuple((artifact, _file_sha256(path)) for artifact, path in paths)
