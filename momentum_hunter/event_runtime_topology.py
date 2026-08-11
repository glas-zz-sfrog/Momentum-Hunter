"""Dormant process-ownership and path contract for continuous decisions.

The Python Engine Host is the sole logical writer and online reader. The
Windows Automation Service may supervise and invoke the host but cannot access
the evidence files. WPF must consume versioned Engine Host snapshots rather
than read files directly. Offline review may read evidence only. This module
derives and validates a relative layout beneath an explicit caller-provided
root; it never creates, reads, or writes any artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path, PurePath


RUNTIME_TOPOLOGY_SCHEMA_VERSION = 1
RUNTIME_TOPOLOGY_PROFILE = "continuous-decision-runtime-topology-v1"
RUNTIME_WRITER_CLAIM_PROFILE = "continuous-decision-writer-claim-v1"

PYTHON_ENGINE_HOST = "PYTHON_ENGINE_HOST"
WINDOWS_AUTOMATION_SERVICE = "WINDOWS_AUTOMATION_SERVICE"
WPF_WORKSTATION = "WPF_WORKSTATION"
OFFLINE_REVIEW = "OFFLINE_REVIEW"

PROCESS_ROLES = frozenset(
    {
        PYTHON_ENGINE_HOST,
        WINDOWS_AUTOMATION_SERVICE,
        WPF_WORKSTATION,
        OFFLINE_REVIEW,
    }
)

READ = "READ"
APPEND = "APPEND"
ARTIFACT_OPERATIONS = frozenset({READ, APPEND})

DORMANT_UNINSTALLED = "DORMANT_UNINSTALLED"
ORDER_TRANSMISSION_UNAVAILABLE = "UNAVAILABLE"
PROSPECTIVE_EVIDENCE_ONLY = "PROSPECTIVE_EVIDENCE_ONLY"

CANDIDATE_LIFECYCLE_LEDGER = "CANDIDATE_LIFECYCLE_LEDGER"
CONTINUOUS_PLAN_LEDGER = "CONTINUOUS_PLAN_LEDGER"
RUNTIME_SOURCE_ADMISSION_LEDGER = "RUNTIME_SOURCE_ADMISSION_LEDGER"
EVENT_DECISION_CYCLE_LEDGER = "EVENT_DECISION_CYCLE_LEDGER"

_ARTIFACT_LAYOUT = (
    (CANDIDATE_LIFECYCLE_LEDGER, "evidence/candidate-lifecycle.json"),
    (CONTINUOUS_PLAN_LEDGER, "evidence/continuous-plans.json"),
    (RUNTIME_SOURCE_ADMISSION_LEDGER, "evidence/runtime-source-admissions.json"),
    (EVENT_DECISION_CYCLE_LEDGER, "evidence/event-decision-cycles.json"),
)
REQUIRED_ARTIFACTS = frozenset(name for name, _ in _ARTIFACT_LAYOUT)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PROGRAM_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_FORBIDDEN_ROOT_PARTS = frozenset({".git", ".venv", "tests", "momentum_hunter"})


class EventRuntimeTopologyError(ValueError):
    """Raised when path or process authority is incomplete or contradictory."""


@dataclass(frozen=True)
class RuntimeArtifactBinding:
    artifact_name: str
    relative_path: str
    writer_role: str
    reader_roles: tuple[str, ...]
    append_only: bool = True


@dataclass(frozen=True)
class EventRuntimeTopology:
    topology_id: str
    root_path: str
    namespace: str
    evidence_program_id: str
    configuration_fingerprint: str
    runtime_build_hash: str
    writer_role: str
    supervisor_role: str
    reader_roles: tuple[str, ...]
    artifacts: tuple[RuntimeArtifactBinding, ...]
    activation_state: str = DORMANT_UNINSTALLED
    observation_mode: str = PROSPECTIVE_EVIDENCE_ONLY
    order_transmission: str = ORDER_TRANSMISSION_UNAVAILABLE
    schema_version: int = RUNTIME_TOPOLOGY_SCHEMA_VERSION
    profile: str = RUNTIME_TOPOLOGY_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RuntimeWriterClaim:
    claim_id: str
    topology_id: str
    topology_fingerprint: str
    process_role: str
    host_instance_id: str
    process_id: int
    runtime_build_hash: str
    configuration_fingerprint: str
    claimed_at: str
    schema_version: int = RUNTIME_TOPOLOGY_SCHEMA_VERSION
    profile: str = RUNTIME_WRITER_CLAIM_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RuntimeArtifactAccessDecision:
    allowed: bool
    artifact_name: str
    operation: str
    process_role: str
    reason: str


def build_event_runtime_topology(
    *,
    root_path: Path,
    evidence_program_id: str,
    configuration_fingerprint: str,
    runtime_build_hash: str,
) -> EventRuntimeTopology:
    """Derive a dormant topology without creating or inspecting the root."""

    root = _absolute_root(root_path)
    program = _program_id(evidence_program_id)
    configuration = _sha256(
        configuration_fingerprint, "Topology configuration fingerprint"
    )
    runtime_build = _sha256(runtime_build_hash, "Topology runtime build hash")
    namespace = f"continuous-decision-v1-{program}-{configuration[:12]}"
    readers = (OFFLINE_REVIEW,)
    artifacts = tuple(
        RuntimeArtifactBinding(
            artifact_name=name,
            relative_path=f"{namespace}/{relative}",
            writer_role=PYTHON_ENGINE_HOST,
            reader_roles=readers,
        )
        for name, relative in _ARTIFACT_LAYOUT
    )
    provisional = EventRuntimeTopology(
        topology_id="",
        root_path=str(root),
        namespace=namespace,
        evidence_program_id=program,
        configuration_fingerprint=configuration,
        runtime_build_hash=runtime_build,
        writer_role=PYTHON_ENGINE_HOST,
        supervisor_role=WINDOWS_AUTOMATION_SERVICE,
        reader_roles=readers,
        artifacts=artifacts,
    )
    identity = _fingerprint(asdict(provisional))
    with_identity = replace(
        provisional,
        topology_id=f"event-runtime-topology-{identity[:24]}",
    )
    result = replace(
        with_identity,
        fingerprint=topology_fingerprint(with_identity),
    )
    validate_event_runtime_topology(result)
    return result


def validate_event_runtime_topology(topology: EventRuntimeTopology) -> None:
    if (
        topology.schema_version != RUNTIME_TOPOLOGY_SCHEMA_VERSION
        or topology.profile != RUNTIME_TOPOLOGY_PROFILE
    ):
        raise EventRuntimeTopologyError("Runtime topology schema is unsupported.")
    root = _absolute_root(Path(topology.root_path))
    if str(root) != topology.root_path:
        raise EventRuntimeTopologyError(
            "Runtime topology root must use its canonical absolute form."
        )
    configuration = _sha256(
        topology.configuration_fingerprint, "Topology configuration fingerprint"
    )
    if configuration != topology.configuration_fingerprint:
        raise EventRuntimeTopologyError(
            "Topology configuration fingerprint must use canonical lowercase form."
        )
    runtime_build = _sha256(topology.runtime_build_hash, "Topology runtime build hash")
    if runtime_build != topology.runtime_build_hash:
        raise EventRuntimeTopologyError(
            "Topology runtime build hash must use canonical lowercase form."
        )
    program = _program_id(topology.evidence_program_id)
    if program != topology.evidence_program_id:
        raise EventRuntimeTopologyError(
            "Runtime evidence program identity must use canonical form."
        )
    expected_namespace = f"continuous-decision-v1-{program}-{configuration[:12]}"
    if topology.namespace != expected_namespace:
        raise EventRuntimeTopologyError("Runtime topology namespace is invalid.")
    if topology.writer_role != PYTHON_ENGINE_HOST:
        raise EventRuntimeTopologyError(
            "Only the Python Engine Host may own continuous evidence writes."
        )
    if topology.supervisor_role != WINDOWS_AUTOMATION_SERVICE:
        raise EventRuntimeTopologyError(
            "The Windows Automation Service must remain the supervisor only."
        )
    expected_readers = (OFFLINE_REVIEW,)
    if topology.reader_roles != expected_readers:
        raise EventRuntimeTopologyError("Runtime topology reader roles are invalid.")
    if (
        topology.activation_state != DORMANT_UNINSTALLED
        or topology.observation_mode != PROSPECTIVE_EVIDENCE_ONLY
        or topology.order_transmission != ORDER_TRANSMISSION_UNAVAILABLE
    ):
        raise EventRuntimeTopologyError(
            "The dormant topology cannot activate runtime or order transmission."
        )
    if len(topology.artifacts) != len(REQUIRED_ARTIFACTS):
        raise EventRuntimeTopologyError("Runtime topology artifact set is incomplete.")

    expected_layout = dict(_ARTIFACT_LAYOUT)
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    for binding in topology.artifacts:
        if binding.artifact_name in seen_names:
            raise EventRuntimeTopologyError("Runtime artifact identity is duplicated.")
        seen_names.add(binding.artifact_name)
        expected_relative = expected_layout.get(binding.artifact_name)
        if expected_relative is None:
            raise EventRuntimeTopologyError("Runtime artifact identity is unsupported.")
        expected_path = f"{expected_namespace}/{expected_relative}"
        if binding.relative_path != expected_path:
            raise EventRuntimeTopologyError("Runtime artifact path layout is invalid.")
        normalized_path = _relative_artifact_path(binding.relative_path)
        collision_key = str(normalized_path).replace("\\", "/").lower()
        if collision_key in seen_paths:
            raise EventRuntimeTopologyError("Runtime artifact paths collide.")
        seen_paths.add(collision_key)
        if (
            binding.writer_role != PYTHON_ENGINE_HOST
            or binding.reader_roles != expected_readers
            or binding.append_only is not True
        ):
            raise EventRuntimeTopologyError(
                "Runtime artifact ownership or append-only authority is invalid."
            )
        absolute = root.joinpath(*normalized_path.parts)
        if not _is_descendant(absolute, root / expected_namespace):
            raise EventRuntimeTopologyError(
                "Runtime artifact escaped its configuration namespace."
            )
    if seen_names != REQUIRED_ARTIFACTS:
        raise EventRuntimeTopologyError("Runtime topology artifact set is incomplete.")

    expected_id = _expected_topology_id(topology)
    if topology.topology_id != expected_id:
        raise EventRuntimeTopologyError("Runtime topology identity is invalid.")
    if topology.fingerprint != topology_fingerprint(topology):
        raise EventRuntimeTopologyError("Runtime topology fingerprint is invalid.")


def topology_fingerprint(topology: EventRuntimeTopology) -> str:
    return _fingerprint(asdict(replace(topology, fingerprint="")))


def artifact_path(topology: EventRuntimeTopology, artifact_name: str) -> Path:
    validate_event_runtime_topology(topology)
    binding = _binding(topology, artifact_name)
    relative = _relative_artifact_path(binding.relative_path)
    root = Path(topology.root_path)
    path = root.joinpath(*relative.parts)
    if not _is_descendant(path, root / topology.namespace):
        raise EventRuntimeTopologyError(
            "Runtime artifact escaped its configuration namespace."
        )
    return path


def build_runtime_writer_claim(
    topology: EventRuntimeTopology,
    *,
    process_role: str,
    host_instance_id: str,
    process_id: int,
    runtime_build_hash: str,
    configuration_fingerprint: str,
    claimed_at: datetime,
) -> RuntimeWriterClaim:
    validate_event_runtime_topology(topology)
    if process_role != topology.writer_role:
        raise EventRuntimeTopologyError(
            "Only the topology writer role may create a writer claim."
        )
    host = _required_text(host_instance_id, "Writer host instance identity")
    pid = _positive_process_id(process_id)
    runtime_build = _sha256(runtime_build_hash, "Writer runtime build hash")
    configuration = _sha256(
        configuration_fingerprint, "Writer configuration fingerprint"
    )
    if runtime_build != topology.runtime_build_hash:
        raise EventRuntimeTopologyError(
            "Writer runtime build does not match the topology."
        )
    if configuration != topology.configuration_fingerprint:
        raise EventRuntimeTopologyError(
            "Writer configuration does not match the topology."
        )
    claimed = _aware(claimed_at, "Writer claim timestamp").isoformat()
    provisional = RuntimeWriterClaim(
        claim_id="",
        topology_id=topology.topology_id,
        topology_fingerprint=topology.fingerprint,
        process_role=process_role,
        host_instance_id=host,
        process_id=pid,
        runtime_build_hash=runtime_build,
        configuration_fingerprint=configuration,
        claimed_at=claimed,
    )
    identity = _fingerprint(asdict(provisional))
    with_identity = replace(
        provisional,
        claim_id=f"runtime-writer-claim-{identity[:24]}",
    )
    result = replace(
        with_identity,
        fingerprint=writer_claim_fingerprint(with_identity),
    )
    validate_runtime_writer_claim(result, topology)
    return result


def validate_runtime_writer_claim(
    claim: RuntimeWriterClaim,
    topology: EventRuntimeTopology,
) -> None:
    validate_event_runtime_topology(topology)
    if (
        claim.schema_version != RUNTIME_TOPOLOGY_SCHEMA_VERSION
        or claim.profile != RUNTIME_WRITER_CLAIM_PROFILE
    ):
        raise EventRuntimeTopologyError("Runtime writer claim schema is unsupported.")
    if (
        claim.topology_id != topology.topology_id
        or claim.topology_fingerprint != topology.fingerprint
    ):
        raise EventRuntimeTopologyError(
            "Runtime writer claim does not match the topology."
        )
    if claim.process_role != topology.writer_role:
        raise EventRuntimeTopologyError("Runtime writer claim role is invalid.")
    if _required_text(
        claim.host_instance_id, "Writer host instance identity"
    ) != claim.host_instance_id:
        raise EventRuntimeTopologyError(
            "Writer host instance identity must use canonical form."
        )
    _positive_process_id(claim.process_id)
    runtime_build = _sha256(claim.runtime_build_hash, "Writer runtime build hash")
    if (
        runtime_build != claim.runtime_build_hash
        or runtime_build != topology.runtime_build_hash
    ):
        raise EventRuntimeTopologyError(
            "Runtime writer claim build does not match the topology."
        )
    configuration = _sha256(
        claim.configuration_fingerprint, "Writer configuration fingerprint"
    )
    if (
        configuration != claim.configuration_fingerprint
        or configuration != topology.configuration_fingerprint
    ):
        raise EventRuntimeTopologyError(
            "Runtime writer claim configuration does not match the topology."
        )
    claimed = _timestamp(claim.claimed_at, "Writer claim timestamp")
    if claimed.isoformat() != claim.claimed_at:
        raise EventRuntimeTopologyError(
            "Runtime writer claim timestamp must use canonical ISO form."
        )
    expected_id = _expected_claim_id(claim)
    if claim.claim_id != expected_id:
        raise EventRuntimeTopologyError("Runtime writer claim identity is invalid.")
    if claim.fingerprint != writer_claim_fingerprint(claim):
        raise EventRuntimeTopologyError(
            "Runtime writer claim fingerprint is invalid."
        )


def writer_claim_fingerprint(claim: RuntimeWriterClaim) -> str:
    return _fingerprint(asdict(replace(claim, fingerprint="")))


def authorize_runtime_artifact_access(
    topology: EventRuntimeTopology,
    *,
    artifact_name: str,
    operation: str,
    process_role: str,
    writer_claim: RuntimeWriterClaim | None = None,
    current_host_instance_id: str = "",
    current_process_id: int = 0,
) -> RuntimeArtifactAccessDecision:
    """Return a fail-closed logical access decision; perform no filesystem work."""

    validate_event_runtime_topology(topology)
    artifact = str(artifact_name).strip().upper()
    normalized_operation = str(operation).strip().upper()
    role = str(process_role).strip().upper()
    if artifact not in REQUIRED_ARTIFACTS:
        return RuntimeArtifactAccessDecision(
            False, artifact, normalized_operation, role, "UNKNOWN_ARTIFACT"
        )
    if normalized_operation not in ARTIFACT_OPERATIONS:
        return RuntimeArtifactAccessDecision(
            False, artifact, normalized_operation, role, "UNKNOWN_OPERATION"
        )
    if role not in PROCESS_ROLES:
        return RuntimeArtifactAccessDecision(
            False, artifact, normalized_operation, role, "UNKNOWN_PROCESS_ROLE"
        )
    binding = _binding(topology, artifact)
    if normalized_operation == READ:
        allowed = role == binding.writer_role or role in binding.reader_roles
        return RuntimeArtifactAccessDecision(
            allowed,
            artifact,
            normalized_operation,
            role,
            "READ_AUTHORIZED" if allowed else "ROLE_NOT_A_READER",
        )
    if role != binding.writer_role:
        return RuntimeArtifactAccessDecision(
            False, artifact, normalized_operation, role, "SOLE_WRITER_ROLE_REQUIRED"
        )
    if writer_claim is None:
        return RuntimeArtifactAccessDecision(
            False, artifact, normalized_operation, role, "WRITER_CLAIM_REQUIRED"
        )
    try:
        validate_runtime_writer_claim(writer_claim, topology)
    except (EventRuntimeTopologyError, TypeError, ValueError):
        return RuntimeArtifactAccessDecision(
            False, artifact, normalized_operation, role, "WRITER_CLAIM_INVALID"
        )
    current_host = str(current_host_instance_id).strip()
    try:
        current_pid = _positive_process_id(current_process_id)
    except EventRuntimeTopologyError:
        return RuntimeArtifactAccessDecision(
            False,
            artifact,
            normalized_operation,
            role,
            "CURRENT_WRITER_IDENTITY_REQUIRED",
        )
    if (
        not current_host
        or current_host != writer_claim.host_instance_id
        or current_pid != writer_claim.process_id
    ):
        return RuntimeArtifactAccessDecision(
            False,
            artifact,
            normalized_operation,
            role,
            "CURRENT_WRITER_IDENTITY_MISMATCH",
        )
    return RuntimeArtifactAccessDecision(
        True, artifact, normalized_operation, role, "APPEND_AUTHORIZED"
    )


def _binding(
    topology: EventRuntimeTopology, artifact_name: str
) -> RuntimeArtifactBinding:
    artifact = str(artifact_name).strip().upper()
    binding = next(
        (item for item in topology.artifacts if item.artifact_name == artifact),
        None,
    )
    if binding is None:
        raise EventRuntimeTopologyError("Runtime artifact identity is unsupported.")
    return binding


def _expected_topology_id(topology: EventRuntimeTopology) -> str:
    payload = asdict(replace(topology, topology_id="", fingerprint=""))
    return f"event-runtime-topology-{_fingerprint(payload)[:24]}"


def _expected_claim_id(claim: RuntimeWriterClaim) -> str:
    payload = asdict(replace(claim, claim_id="", fingerprint=""))
    return f"runtime-writer-claim-{_fingerprint(payload)[:24]}"


def _absolute_root(value: Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise EventRuntimeTopologyError(
            "Runtime topology root must be an explicit absolute path."
        )
    if ".." in root.parts:
        raise EventRuntimeTopologyError(
            "Runtime topology root cannot contain parent traversal."
        )
    normalized = root.resolve(strict=False)
    lowered_parts = {part.lower() for part in normalized.parts}
    if lowered_parts & _FORBIDDEN_ROOT_PARTS:
        raise EventRuntimeTopologyError(
            "Runtime topology root cannot be a source, test, Git, or environment path."
        )
    return normalized


def _relative_artifact_path(value: str) -> PurePath:
    normalized = str(value).strip().replace("\\", "/")
    path = PurePath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise EventRuntimeTopologyError("Runtime artifact path must be relative and safe.")
    return path


def _is_descendant(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _positive_process_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventRuntimeTopologyError("Writer process identity must be positive.")
    if value <= 0:
        raise EventRuntimeTopologyError("Writer process identity must be positive.")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EventRuntimeTopologyError(f"{name} must be timezone-aware.")
    return value


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise EventRuntimeTopologyError(f"{name} is invalid.") from exc
    return _aware(parsed, name)


def _required_text(value: object, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise EventRuntimeTopologyError(f"{name} is required.")
    return normalized


def _sha256(value: object, name: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise EventRuntimeTopologyError(f"{name} must be SHA-256.")
    return normalized


def _program_id(value: object) -> str:
    normalized = str(value).strip().lower()
    if not _PROGRAM_ID.fullmatch(normalized):
        raise EventRuntimeTopologyError(
            "Runtime evidence program identity is invalid."
        )
    return normalized


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
