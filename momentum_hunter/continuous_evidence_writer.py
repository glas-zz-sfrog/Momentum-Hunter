"""Dormant dedicated-writer contract for continuous evidence.

This module proves logical topology, authenticated intent admission, immutable
record storage, and restart behavior against caller-supplied temporary roots.
It does not install a process, change ACLs, or claim same-SID isolation.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePath

from momentum_hunter.continuous_runtime import (
    ContinuousRuntimeError,
    EvidenceWriteIntent,
    WRITER_ACCEPTED,
    WRITER_DUPLICATE,
    WRITER_SLOW,
    WRITER_UNAVAILABLE,
    validate_evidence_write_intent,
)
from momentum_hunter.event_runtime_topology import (
    EventRuntimeTopology,
    PYTHON_ENGINE_HOST,
    WPF_WORKSTATION,
    validate_event_runtime_topology,
)
from momentum_hunter.event_runtime_writer_ipc import (
    ALLOWED_ARTIFACTS,
    GENESIS_FINGERPRINT,
    PROTOCOL,
    EphemeralWriterCapability,
    WriterEnvelope,
    WriterEnvelopeSender,
    verify_envelope_authentication,
)
from momentum_hunter.windows_writer_storage import (
    WriterOwnerEvidence,
    WriterOwnershipConflictError,
    WriterPhysicalStorage,
    WriterPhysicalStorageError,
    WriterStorageCrashAfterTemp,
)


TOPOLOGY_VERSION = 2
TOPOLOGY_SCHEMA_VERSION = 2
TOPOLOGY_PROFILE = "continuous-evidence-writer-topology-v2"
PRODUCTION_TOPOLOGY_PROFILE = "production-continuous-evidence-writer-topology-v1"
PRODUCTION_ACTIVATION_STATE = "RESEARCH_ONLY_ACTIVE"
WRITER_ROLE_PROFILE = "dedicated-evidence-writer-role-v1"
RECORD_SCHEMA_VERSION = 1
RECORD_PROFILE = "continuous-evidence-intent-record-v1"
ACK_PROFILE = "continuous-evidence-writer-ack-v1"
EVIDENCE_ROOT_POLICY = "writer-derived-sharded-paths-v1"
STORAGE_FORMAT = "immutable-sharded-record-per-file-v1"
AUTHORITY = "DORMANT_CONTRACT_ONLY"
WRITER_OWNER_CONFLICT = "WRITER_OWNER_CONFLICT"

DEDICATED_EVIDENCE_WRITER = "DEDICATED_EVIDENCE_WRITER"
CONTINUOUS_RUNTIME = "CONTINUOUS_RUNTIME"
WINDOWS_AUTOMATION_SERVICE = "WINDOWS_AUTOMATION_SERVICE"
OFFLINE_REVIEW = "OFFLINE_REVIEW"

READ = "READ"
APPEND = "APPEND"


def create_ephemeral_writer_capability() -> EphemeralWriterCapability:
    """Create a session capability without exposing the low-level IPC module."""

    return EphemeralWriterCapability.create()

WRITER_CAPABILITIES = ("VALIDATE", "ORDER", "PERSIST", "ACKNOWLEDGE")
FORBIDDEN_WRITER_CAPABILITIES = (
    "SCHWAB_CREDENTIALS",
    "ALPACA_CREDENTIALS",
    "FINVIZ_TRANSPORT",
    "SCORING",
    "RANKING",
    "TRADE_PLAN",
    "RISK_GOVERNOR",
    "ALLOCATION",
    "BROKER_ORDER",
    "WPF_AUTHORITY",
)

ACTIVATION_BLOCKERS = (
    "WINDOWS_PRINCIPAL_ISOLATION_UNPROVEN",
    "SAME_SID_PROCESS_ISOLATION_UNPROVEN",
    "KERNEL_HANDLE_ISOLATION_UNPROVEN",
    "ACL_AND_REPARSE_POINT_RESISTANCE_UNPROVEN",
)

CRASH_BEFORE_COMMIT = "BEFORE_COMMIT"
CRASH_AFTER_TEMP = "AFTER_TEMP_WRITE"
CRASH_AFTER_COMMIT_BEFORE_ACK = "AFTER_ATOMIC_COMMIT_BEFORE_ACK"
CRASH_AFTER_ACK_BEFORE_RETURN = "AFTER_ACK_COMMIT_BEFORE_RETURN"
CRASH_PHASES = frozenset(
    {
        CRASH_BEFORE_COMMIT,
        CRASH_AFTER_TEMP,
        CRASH_AFTER_COMMIT_BEFORE_ACK,
        CRASH_AFTER_ACK_BEFORE_RETURN,
    }
)

_PROGRAM_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SESSION_ID = re.compile(r"[0-9a-f]{32}")
_RESERVED_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)

_EVIDENCE_TYPE_TO_ARTIFACT = {
    "COMPOSITION_CYCLE": "event-decision-cycle-ledger",
    "OPPORTUNITY_DENOMINATOR": "runtime-source-admission-ledger",
    "PROVIDER_BOUND_DENOMINATOR_ROWS": "runtime-source-admission-ledger",
}

_ROOT_OWNERS_GUARD = threading.Lock()
_ROOT_OWNERS: dict[Path, str] = {}


class ContinuousEvidenceWriterError(ValueError):
    """Raised when topology or immutable evidence fails closed."""


class WriterUnavailableError(ContinuousEvidenceWriterError):
    """Raised when the logical writer cannot acknowledge an intent."""


class WriterCrashInjected(WriterUnavailableError):
    """Synthetic crash used only by temporary-root tests."""


class PhysicalWriterOwnershipConflictError(ContinuousEvidenceWriterError):
    """Raised when another process owns the exact physical evidence root."""


@dataclass(frozen=True)
class WriterRoleContract:
    role: str = DEDICATED_EVIDENCE_WRITER
    capabilities: tuple[str, ...] = WRITER_CAPABILITIES
    forbidden_capabilities: tuple[str, ...] = FORBIDDEN_WRITER_CAPABILITIES
    requires_provider_credentials: bool = False
    order_transmission: str = "UNAVAILABLE"
    profile: str = WRITER_ROLE_PROFILE


@dataclass(frozen=True)
class ContinuousWriterTopologyV2:
    topology_id: str
    root_path: str
    namespace: str
    evidence_program_id: str
    configuration_fingerprint: str
    runtime_build_hash: str
    writer_role: str
    runtime_role: str
    reader_roles: tuple[str, ...]
    supervisor_role: str
    ipc_contract_version: str
    evidence_root_policy: str
    storage_format: str
    activation_state: str
    activation_blockers: tuple[str, ...]
    topology_version: int = TOPOLOGY_VERSION
    schema_version: int = TOPOLOGY_SCHEMA_VERSION
    profile: str = TOPOLOGY_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class TopologyContradiction:
    topic: str
    topology_v1: str
    activation_prototype: str
    topology_v2_resolution: str


@dataclass(frozen=True)
class TopologyCompatibility:
    topology_v1_evidence_readable: bool
    topology_v1_historical_identity_rewritten: bool
    topology_v2_writer_role: str
    migration_required: bool
    reason: str


@dataclass(frozen=True)
class EvidenceWriterAcknowledgement:
    acknowledgement_id: str
    session_id: str
    sequence: int
    envelope_fingerprint: str
    intent_id: str
    artifact_name: str
    status: str
    relative_record_path: str
    record_sha256: str
    error_state: str | None
    fingerprint: str
    schema_version: int = RECORD_SCHEMA_VERSION
    profile: str = ACK_PROFILE


@dataclass(frozen=True)
class EvidenceRecordView:
    artifact_name: str
    record_identity: str
    record_fingerprint: str
    intent_id: str
    intent_sequence: int
    predecessor_identity: str | None
    relative_path: str
    sha256: str


@dataclass(frozen=True)
class EvidenceReadSnapshot:
    topology_id: str
    record_count: int
    records: tuple[EvidenceRecordView, ...]
    fingerprint: str


def build_continuous_writer_topology_v2(
    *,
    root_path: Path,
    evidence_program_id: str,
    configuration_fingerprint: str,
    runtime_build_hash: str,
) -> ContinuousWriterTopologyV2:
    root = _canonical_root(root_path)
    program = _program_id(evidence_program_id)
    configuration = _sha256(configuration_fingerprint, "Configuration fingerprint")
    runtime_build = _sha256(runtime_build_hash, "Runtime build hash")
    namespace = f"continuous-evidence-v2-{program}-{configuration[:12]}"
    provisional = ContinuousWriterTopologyV2(
        topology_id="",
        root_path=str(root),
        namespace=namespace,
        evidence_program_id=program,
        configuration_fingerprint=configuration,
        runtime_build_hash=runtime_build,
        writer_role=DEDICATED_EVIDENCE_WRITER,
        runtime_role=CONTINUOUS_RUNTIME,
        reader_roles=(PYTHON_ENGINE_HOST, WPF_WORKSTATION, OFFLINE_REVIEW),
        supervisor_role=WINDOWS_AUTOMATION_SERVICE,
        ipc_contract_version=PROTOCOL,
        evidence_root_policy=EVIDENCE_ROOT_POLICY,
        storage_format=STORAGE_FORMAT,
        activation_state="DORMANT_UNINSTALLED",
        activation_blockers=ACTIVATION_BLOCKERS,
    )
    identity = _fingerprint("continuous-writer-topology-v2-identity", asdict(provisional))
    with_identity = replace(
        provisional,
        topology_id=f"continuous-writer-topology-{identity[:24]}",
    )
    result = replace(with_identity, fingerprint=_topology_fingerprint(with_identity))
    validate_continuous_writer_topology_v2(result)
    return result


def build_production_continuous_writer_topology(
    *,
    root_path: Path,
    evidence_program_id: str,
    configuration_fingerprint: str,
    runtime_build_hash: str,
) -> ContinuousWriterTopologyV2:
    """Build the explicitly active research-only deployment identity.

    The historical v2 builder remains dormant by contract.  Production uses a
    separate profile and identity domain so an installed process can never
    truthfully present itself as the old uninstalled prototype.
    """

    dormant = build_continuous_writer_topology_v2(
        root_path=root_path,
        evidence_program_id=evidence_program_id,
        configuration_fingerprint=configuration_fingerprint,
        runtime_build_hash=runtime_build_hash,
    )
    provisional = replace(
        dormant,
        topology_id="",
        activation_state=PRODUCTION_ACTIVATION_STATE,
        activation_blockers=(),
        profile=PRODUCTION_TOPOLOGY_PROFILE,
        fingerprint="",
    )
    identity = _fingerprint(
        "production-continuous-writer-topology-v1-identity",
        asdict(provisional),
    )
    with_identity = replace(
        provisional,
        topology_id=f"production-continuous-writer-topology-{identity[:24]}",
    )
    result = replace(
        with_identity,
        fingerprint=_fingerprint(
            "production-continuous-writer-topology-v1",
            asdict(with_identity),
        ),
    )
    validate_production_continuous_writer_topology(result)
    return result


def validate_production_continuous_writer_topology(
    topology: ContinuousWriterTopologyV2,
) -> None:
    """Validate the immutable identity used by the installed research lane."""

    if (
        topology.topology_version != TOPOLOGY_VERSION
        or topology.schema_version != TOPOLOGY_SCHEMA_VERSION
        or topology.profile != PRODUCTION_TOPOLOGY_PROFILE
        or topology.activation_state != PRODUCTION_ACTIVATION_STATE
        or topology.activation_blockers != ()
    ):
        raise ContinuousEvidenceWriterError(
            "Production writer topology is not the active research-only profile."
        )
    dormant_shape = replace(
        topology,
        topology_id="",
        activation_state=PRODUCTION_ACTIVATION_STATE,
        activation_blockers=(),
        profile=PRODUCTION_TOPOLOGY_PROFILE,
        fingerprint="",
    )
    expected_identity = _fingerprint(
        "production-continuous-writer-topology-v1-identity",
        asdict(dormant_shape),
    )
    if topology.topology_id != f"production-continuous-writer-topology-{expected_identity[:24]}":
        raise ContinuousEvidenceWriterError("Production topology identity is invalid.")
    expected_fingerprint = _fingerprint(
        "production-continuous-writer-topology-v1",
        asdict(replace(topology, fingerprint="")),
    )
    if topology.fingerprint != expected_fingerprint:
        raise ContinuousEvidenceWriterError("Production topology fingerprint is invalid.")


def validate_continuous_writer_topology_v2(
    topology: ContinuousWriterTopologyV2,
) -> None:
    if (
        topology.topology_version != TOPOLOGY_VERSION
        or topology.schema_version != TOPOLOGY_SCHEMA_VERSION
        or topology.profile != TOPOLOGY_PROFILE
    ):
        raise ContinuousEvidenceWriterError("Writer topology version is unsupported.")
    root = _canonical_root(Path(topology.root_path))
    if str(root) != topology.root_path:
        raise ContinuousEvidenceWriterError("Writer root is not canonical.")
    program = _program_id(topology.evidence_program_id)
    configuration = _sha256(topology.configuration_fingerprint, "Configuration fingerprint")
    runtime_build = _sha256(topology.runtime_build_hash, "Runtime build hash")
    expected_namespace = f"continuous-evidence-v2-{program}-{configuration[:12]}"
    if topology.namespace != expected_namespace:
        raise ContinuousEvidenceWriterError("Writer namespace is invalid.")
    if configuration != topology.configuration_fingerprint:
        raise ContinuousEvidenceWriterError("Configuration identity is not canonical.")
    if runtime_build != topology.runtime_build_hash:
        raise ContinuousEvidenceWriterError("Runtime build identity is not canonical.")
    if (
        topology.writer_role != DEDICATED_EVIDENCE_WRITER
        or topology.runtime_role != CONTINUOUS_RUNTIME
        or topology.reader_roles != (PYTHON_ENGINE_HOST, WPF_WORKSTATION, OFFLINE_REVIEW)
        or topology.supervisor_role != WINDOWS_AUTOMATION_SERVICE
        or topology.ipc_contract_version != PROTOCOL
        or topology.evidence_root_policy != EVIDENCE_ROOT_POLICY
        or topology.storage_format != STORAGE_FORMAT
        or topology.activation_state != "DORMANT_UNINSTALLED"
        or topology.activation_blockers != ACTIVATION_BLOCKERS
    ):
        raise ContinuousEvidenceWriterError("Writer topology role contract is invalid.")
    expected_identity = _fingerprint(
        "continuous-writer-topology-v2-identity",
        asdict(replace(topology, topology_id="", fingerprint="")),
    )
    if topology.topology_id != f"continuous-writer-topology-{expected_identity[:24]}":
        raise ContinuousEvidenceWriterError("Writer topology identity is invalid.")
    if topology.fingerprint != _topology_fingerprint(topology):
        raise ContinuousEvidenceWriterError("Writer topology fingerprint is invalid.")


def topology_contradiction_inventory() -> tuple[TopologyContradiction, ...]:
    return (
        TopologyContradiction(
            "WRITER_ROLE",
            "PYTHON_ENGINE_HOST",
            "DEDICATED_EVIDENCE_WRITER",
            "Topology v2 assigns append authority only to DEDICATED_EVIDENCE_WRITER.",
        ),
        TopologyContradiction(
            "IPC",
            "DIRECT_IN_PROCESS_APPEND",
            PROTOCOL,
            "Topology v2 binds the runtime to authenticated bounded intent IPC.",
        ),
        TopologyContradiction(
            "PHYSICAL_STORAGE",
            "EVER_GROWING_ARTIFACT_LEDGER",
            "OFFLINE_FRAME_PER_FILE_PROTOTYPE",
            "Topology v2 uses sharded immutable intent records and immutable acknowledgements.",
        ),
        TopologyContradiction(
            "READER_BOUNDARY",
            "ENGINE_HOST_ONLINE_READER; WPF_VIA_HOST",
            "PROTOTYPE_DID_NOT_DEFINE_READERS",
            "Topology v2 exposes validated read-only snapshots to Engine Host and WPF.",
        ),
    )


def topology_v1_compatibility(topology_v1: EventRuntimeTopology) -> TopologyCompatibility:
    validate_event_runtime_topology(topology_v1)
    return TopologyCompatibility(
        topology_v1_evidence_readable=True,
        topology_v1_historical_identity_rewritten=False,
        topology_v2_writer_role=DEDICATED_EVIDENCE_WRITER,
        migration_required=False,
        reason="Topology v1 was dormant; its identities remain readable and unchanged.",
    )


def authorize_topology_access(
    topology: ContinuousWriterTopologyV2,
    *,
    role: str,
    operation: str,
) -> bool:
    validate_continuous_writer_topology_v2(topology)
    normalized_role = str(role).strip().upper()
    normalized_operation = str(operation).strip().upper()
    if normalized_operation == APPEND:
        return normalized_role == topology.writer_role
    if normalized_operation == READ:
        return normalized_role == topology.writer_role or normalized_role in topology.reader_roles
    return False


def artifact_record_path(
    topology: ContinuousWriterTopologyV2,
    *,
    artifact_name: str,
    record_fingerprint: str,
) -> Path:
    validate_continuous_writer_topology_v2(topology)
    artifact = _artifact_name(artifact_name)
    fingerprint = _sha256(record_fingerprint, "Record fingerprint")
    base = _evidence_root(topology)
    result = base / "records" / artifact / fingerprint[:2] / f"{fingerprint}.json"
    _require_descendant(result, base)
    return result


class DedicatedEvidenceWriter:
    """Logical v2 writer using immutable records under a temporary caller root."""

    def __init__(
        self,
        topology: ContinuousWriterTopologyV2,
        *,
        response_delay_seconds: float = 0.0,
    ) -> None:
        validate_continuous_writer_topology_v2(topology)
        if response_delay_seconds < 0:
            raise ContinuousEvidenceWriterError("Writer response delay cannot be negative.")
        self.topology = topology
        self.response_delay_seconds = float(response_delay_seconds)
        self._root = _evidence_root(topology)
        self._owner_token = uuid.uuid4().hex
        self._closed = False
        self._session_id: str | None = None
        self._key = bytearray()
        self._source_identity = ""
        self._allowed_intent_runtime_ids: frozenset[str] = frozenset()
        self._expected_sequence = 1
        self._prior_envelope_fingerprint = GENESIS_FINGERPRINT
        self._acks_by_sequence: dict[int, tuple[WriterEnvelope, EvidenceWriterAcknowledgement]] = {}
        self._records_by_identity: dict[tuple[str, str], EvidenceRecordView] = {}
        self._records_by_intent: dict[str, EvidenceRecordView] = {}
        self._records_by_sequence: dict[int, EvidenceRecordView] = {}
        self._next_intent_sequence = 1
        self._last_intent_id: str | None = None
        self._crash_phase: str | None = None
        self._storage: WriterPhysicalStorage | None = None
        _claim_root(self._root, self._owner_token)
        try:
            self._storage = WriterPhysicalStorage(
                self._root,
                writer_instance_id=self._owner_token,
                topology_fingerprint=self.topology.fingerprint,
                topology_version=self.topology.topology_version,
            )
            self._quarantine_partial_files()
            self._load_record_index()
        except WriterOwnershipConflictError as exc:
            _release_root(self._root, self._owner_token)
            raise PhysicalWriterOwnershipConflictError(
                "Another physical writer owns this evidence root."
            ) from exc
        except WriterPhysicalStorageError as exc:
            if self._storage is not None:
                self._storage.close()
            _release_root(self._root, self._owner_token)
            raise ContinuousEvidenceWriterError(
                "Writer initialization violated the physical storage boundary."
            ) from exc
        except Exception:
            if self._storage is not None:
                self._storage.close()
            _release_root(self._root, self._owner_token)
            raise

    def __enter__(self) -> "DedicatedEvidenceWriter":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def owner_evidence(self) -> WriterOwnerEvidence:
        self._require_open()
        if self._storage is None:
            raise WriterUnavailableError("Writer physical storage is unavailable.")
        return self._storage.owner_evidence

    def activate_session(
        self,
        *,
        capability: EphemeralWriterCapability,
        source_identity: str,
        replay_runtime_instance_ids: tuple[str, ...] = (),
    ) -> None:
        self._require_open()
        session_id = _session_id(capability.session_id)
        key_material = capability.key_bytes()
        normalized_source = _required_text(source_identity, "Runtime source identity")
        replay_ids = tuple(
            _required_text(item, "Replay runtime instance identity")
            for item in replay_runtime_instance_ids
        )
        if len(set(replay_ids)) != len(replay_ids) or len(replay_ids) > 1:
            raise ContinuousEvidenceWriterError(
                "At most one unique predecessor runtime may be replay-authorized."
            )
        self._zero_key()
        self._session_id = session_id
        self._key = bytearray(key_material)
        self._source_identity = normalized_source
        self._allowed_intent_runtime_ids = frozenset(
            (self._source_identity, *replay_ids)
        )
        self._load_session_acknowledgements()

    def arm_crash(self, phase: str) -> None:
        if phase not in CRASH_PHASES:
            raise ContinuousEvidenceWriterError("Crash phase is unsupported.")
        self._crash_phase = phase

    def accept(self, envelope: WriterEnvelope) -> EvidenceWriterAcknowledgement:
        self._require_open()
        if self._session_id is None:
            raise WriterUnavailableError("Writer session is unavailable.")
        verify_envelope_authentication(
            envelope,
            session_id=self._session_id,
            key_material=bytes(self._key),
            configuration_fingerprint=self.topology.configuration_fingerprint,
            source_identity=self._source_identity,
        )
        prior = self._acks_by_sequence.get(envelope.sequence)
        if prior is not None:
            old_envelope, acknowledgement = prior
            if old_envelope.fingerprint == envelope.fingerprint:
                self._revalidate_acknowledged_record(acknowledgement)
                return acknowledgement
            raise ContinuousEvidenceWriterError("Conflicting duplicate envelope sequence.")
        if envelope.sequence < self._expected_sequence:
            raise ContinuousEvidenceWriterError("Old envelope has no exact historical identity.")
        if envelope.sequence > self._expected_sequence:
            raise ContinuousEvidenceWriterError("Envelope sequence gap is forbidden.")
        if envelope.prior_envelope_fingerprint != self._prior_envelope_fingerprint:
            raise ContinuousEvidenceWriterError("Envelope predecessor continuity is invalid.")
        intent = _intent_from_envelope(
            envelope,
            topology_fingerprint=self.topology.fingerprint,
        )
        if intent.runtime_instance_id not in self._allowed_intent_runtime_ids:
            raise ContinuousEvidenceWriterError("Intent runtime identity is contradictory.")
        expected_artifact = _EVIDENCE_TYPE_TO_ARTIFACT.get(intent.evidence_type)
        if expected_artifact != envelope.artifact_name:
            raise ContinuousEvidenceWriterError("Intent evidence type maps to another artifact.")
        if self._consume_crash(CRASH_BEFORE_COMMIT):
            raise WriterCrashInjected("Writer crashed before record commit.")
        if self._storage is None:
            raise WriterUnavailableError("Writer physical storage is unavailable.")
        with self._storage.transaction():
            view, created = self._persist_record(envelope, intent)
            if self._consume_crash(CRASH_AFTER_COMMIT_BEFORE_ACK):
                raise WriterCrashInjected("Writer crashed after record commit before acknowledgement.")
            status = WRITER_ACCEPTED if created else WRITER_DUPLICATE
            acknowledgement = self._build_acknowledgement(
                envelope=envelope,
                intent=intent,
                view=view,
                status=status,
            )
            self._persist_acknowledgement(envelope, acknowledgement)
        self._acks_by_sequence[envelope.sequence] = (envelope, acknowledgement)
        self._expected_sequence += 1
        self._prior_envelope_fingerprint = envelope.fingerprint
        if self.response_delay_seconds:
            time.sleep(self.response_delay_seconds)
        if self._consume_crash(CRASH_AFTER_ACK_BEFORE_RETURN):
            raise WriterCrashInjected("Writer crashed after acknowledgement commit.")
        return acknowledgement

    def close(self) -> None:
        if self._closed:
            return
        self._zero_key()
        self._closed = True
        try:
            if self._storage is not None:
                self._storage.close()
                self._storage = None
        finally:
            _release_root(self._root, self._owner_token)

    def _persist_record(
        self,
        envelope: WriterEnvelope,
        intent: EvidenceWriteIntent,
    ) -> tuple[EvidenceRecordView, bool]:
        key = (envelope.artifact_name, intent.record_identity)
        existing = self._records_by_identity.get(key)
        if existing is not None:
            if (
                existing.record_fingerprint == intent.record_fingerprint
                and existing.intent_id == intent.intent_id
            ):
                return self._revalidate_record(existing), False
            raise ContinuousEvidenceWriterError("Conflicting duplicate record identity.")
        existing_intent = self._records_by_intent.get(intent.intent_id)
        if existing_intent is not None:
            if existing_intent.record_fingerprint == intent.record_fingerprint:
                return self._revalidate_record(existing_intent), False
            raise ContinuousEvidenceWriterError("Intent identity maps to conflicting evidence.")
        self._validate_new_intent_order(intent)
        path = _trusted_writer_record_path(
            self._root,
            artifact_name=envelope.artifact_name,
            record_fingerprint=intent.record_fingerprint,
        )
        document = _build_record_document(self.topology, envelope, intent)
        data = _canonical_bytes(document)
        created = self._atomic_create(
            path,
            data,
            crash_after_temp=self._consume_crash(CRASH_AFTER_TEMP),
        )
        if not created:
            view = _validate_record_file(self.topology, path)
            if view.record_identity != intent.record_identity or view.intent_id != intent.intent_id:
                raise ContinuousEvidenceWriterError("Record path contains conflicting evidence.")
            self._index_record(view)
            return view, False
        view = EvidenceRecordView(
            artifact_name=envelope.artifact_name,
            record_identity=intent.record_identity,
            record_fingerprint=intent.record_fingerprint,
            intent_id=intent.intent_id,
            intent_sequence=intent.sequence,
            predecessor_identity=intent.predecessor_identity,
            relative_path=path.relative_to(self._root).as_posix(),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        self._index_record(view)
        return view, True

    def _build_acknowledgement(
        self,
        *,
        envelope: WriterEnvelope,
        intent: EvidenceWriteIntent,
        view: EvidenceRecordView,
        status: str,
    ) -> EvidenceWriterAcknowledgement:
        provisional = EvidenceWriterAcknowledgement(
            acknowledgement_id="",
            session_id=envelope.session_id,
            sequence=envelope.sequence,
            envelope_fingerprint=envelope.fingerprint,
            intent_id=intent.intent_id,
            artifact_name=envelope.artifact_name,
            status=status,
            relative_record_path=view.relative_path,
            record_sha256=view.sha256,
            error_state=None,
            fingerprint="",
        )
        fingerprint = _fingerprint("continuous-writer-ack-v1", asdict(provisional))
        with_identity = replace(
            provisional,
            acknowledgement_id=f"continuous-writer-ack-{fingerprint[:24]}",
        )
        return replace(
            with_identity,
            fingerprint=_fingerprint("continuous-writer-ack-v1", asdict(with_identity)),
        )

    def _persist_acknowledgement(
        self,
        envelope: WriterEnvelope,
        acknowledgement: EvidenceWriterAcknowledgement,
    ) -> None:
        path = _trusted_writer_ack_path(
            self._root,
            envelope.session_id,
            envelope.sequence,
        )
        document = {
            "schemaVersion": RECORD_SCHEMA_VERSION,
            "profile": ACK_PROFILE,
            "topologyId": self.topology.topology_id,
            "topologyFingerprint": self.topology.fingerprint,
            "envelope": asdict(envelope),
            "acknowledgement": asdict(acknowledgement),
        }
        data = _canonical_bytes(document)
        created = self._atomic_create(path, data)
        if not created:
            old_envelope, old_ack = _validate_ack_file(self.topology, path)
            if old_envelope != envelope or old_ack != acknowledgement:
                raise ContinuousEvidenceWriterError("Acknowledgement identity conflicts.")
            return

    def _load_record_index(self) -> None:
        if self._storage is None:
            raise WriterUnavailableError("Writer physical storage is unavailable.")
        views = tuple(
            _validate_record_file(self.topology, path)
            for path in self._storage.iter_files(PurePath("records"), suffix=".json")
        )
        for view in sorted(views, key=lambda item: item.intent_sequence):
            self._index_record(view)

    def _revalidate_record(self, expected: EvidenceRecordView) -> EvidenceRecordView:
        path = self._root / PurePath(expected.relative_path)
        _require_descendant(path, self._root)
        actual = _validate_record_file(self.topology, path)
        if actual != expected:
            raise ContinuousEvidenceWriterError("Cached evidence record identity changed.")
        return actual

    def _revalidate_acknowledged_record(
        self,
        acknowledgement: EvidenceWriterAcknowledgement,
    ) -> None:
        path = self._root / PurePath(acknowledgement.relative_record_path)
        _require_descendant(path, self._root)
        view = _validate_record_file(self.topology, path)
        if view.sha256 != acknowledgement.record_sha256:
            raise ContinuousEvidenceWriterError(
                "Acknowledged evidence record changed after commit."
            )

    def _index_record(self, view: EvidenceRecordView) -> None:
        key = (view.artifact_name, view.record_identity)
        old = self._records_by_identity.get(key)
        if old is not None and old != view:
            raise ContinuousEvidenceWriterError("Stored record identities conflict.")
        old_intent = self._records_by_intent.get(view.intent_id)
        if old_intent is not None and old_intent != view:
            raise ContinuousEvidenceWriterError("Stored intent identities conflict.")
        old_sequence = self._records_by_sequence.get(view.intent_sequence)
        if old_sequence is not None and old_sequence != view:
            raise ContinuousEvidenceWriterError("Stored intent sequence identities conflict.")
        if old_sequence is None:
            if view.intent_sequence != self._next_intent_sequence:
                raise ContinuousEvidenceWriterError("Stored intent sequence has a gap.")
            if view.predecessor_identity != self._last_intent_id:
                raise ContinuousEvidenceWriterError("Stored intent predecessor chain is invalid.")
            self._records_by_sequence[view.intent_sequence] = view
            self._next_intent_sequence += 1
            self._last_intent_id = view.intent_id
        self._records_by_identity[key] = view
        self._records_by_intent[view.intent_id] = view

    def _validate_new_intent_order(self, intent: EvidenceWriteIntent) -> None:
        if intent.sequence != self._next_intent_sequence:
            raise ContinuousEvidenceWriterError("Evidence intent sequence has a gap or conflict.")
        if intent.predecessor_identity != self._last_intent_id:
            raise ContinuousEvidenceWriterError("Evidence intent predecessor chain is invalid.")

    def _load_session_acknowledgements(self) -> None:
        self._acks_by_sequence.clear()
        self._expected_sequence = 1
        self._prior_envelope_fingerprint = GENESIS_FINGERPRINT
        if self._storage is None:
            raise WriterUnavailableError("Writer physical storage is unavailable.")
        session_root = PurePath("sessions") / str(self._session_id)
        for path in self._storage.iter_files(session_root, suffix=".ack.json"):
            envelope, acknowledgement = _validate_ack_file(self.topology, path)
            verify_envelope_authentication(
                envelope,
                session_id=str(self._session_id),
                key_material=bytes(self._key),
                configuration_fingerprint=self.topology.configuration_fingerprint,
                source_identity=self._source_identity,
            )
            if envelope.sequence != self._expected_sequence:
                raise ContinuousEvidenceWriterError("Persisted acknowledgement sequence has a gap.")
            if envelope.prior_envelope_fingerprint != self._prior_envelope_fingerprint:
                raise ContinuousEvidenceWriterError("Persisted acknowledgement chain is invalid.")
            self._acks_by_sequence[envelope.sequence] = (envelope, acknowledgement)
            self._expected_sequence += 1
            self._prior_envelope_fingerprint = envelope.fingerprint

    def _quarantine_partial_files(self) -> None:
        if self._storage is None:
            raise WriterUnavailableError("Writer physical storage is unavailable.")
        try:
            self._storage.quarantine_partials()
        except WriterPhysicalStorageError as exc:
            raise ContinuousEvidenceWriterError(
                "Writer partial recovery violated the physical storage boundary."
            ) from exc

    def _atomic_create(
        self,
        path: Path,
        data: bytes,
        *,
        crash_after_temp: bool = False,
    ) -> bool:
        if self._storage is None:
            raise WriterUnavailableError("Writer physical storage is unavailable.")
        try:
            relative = path.relative_to(self._root)
        except ValueError as exc:
            raise ContinuousEvidenceWriterError(
                "Writer-derived path escaped its evidence root."
            ) from exc
        try:
            return self._storage.atomic_create(
                PurePath(relative),
                data,
                crash_after_temp=crash_after_temp,
            )
        except WriterStorageCrashAfterTemp as exc:
            raise WriterCrashInjected(
                "Writer crashed after temporary file completion."
            ) from exc
        except WriterPhysicalStorageError as exc:
            raise ContinuousEvidenceWriterError(
                "Writer commit violated the physical storage boundary."
            ) from exc

    def _consume_crash(self, phase: str) -> bool:
        if self._crash_phase != phase:
            return False
        self._crash_phase = None
        return True

    def _zero_key(self) -> None:
        for index in range(len(self._key)):
            self._key[index] = 0
        self._key = bytearray()

    def _require_open(self) -> None:
        if self._closed:
            raise WriterUnavailableError("Writer is closed.")


class AuthenticatedEvidenceWriterClient:
    """ContinuousRuntime adapter that owns no filesystem path authority."""

    def __init__(
        self,
        *,
        topology: ContinuousWriterTopologyV2,
        capability: EphemeralWriterCapability,
        runtime_instance_id: str,
        writer: DedicatedEvidenceWriter | None,
        maximum_ack_seconds: float = 1.0,
        replay_runtime_instance_ids: tuple[str, ...] = (),
    ) -> None:
        validate_continuous_writer_topology_v2(topology)
        if maximum_ack_seconds <= 0:
            raise ContinuousEvidenceWriterError("Maximum acknowledgement time must be positive.")
        self.topology = topology
        self.capability = capability
        self.runtime_instance_id = _required_text(runtime_instance_id, "Runtime instance identity")
        replay_ids = tuple(
            _required_text(item, "Replay runtime instance identity")
            for item in replay_runtime_instance_ids
        )
        if len(set(replay_ids)) != len(replay_ids) or len(replay_ids) > 1:
            raise ContinuousEvidenceWriterError(
                "At most one unique predecessor runtime may be replay-authorized."
            )
        self.allowed_intent_runtime_ids = frozenset((self.runtime_instance_id, *replay_ids))
        self.writer = writer
        self.maximum_ack_seconds = float(maximum_ack_seconds)
        self.sender = WriterEnvelopeSender(
            capability=capability,
            configuration_fingerprint=topology.configuration_fingerprint,
            source_identity=self.runtime_instance_id,
        )
        self._pending_intent: EvidenceWriteIntent | None = None
        self._pending_envelope: WriterEnvelope | None = None

    def set_writer(self, writer: DedicatedEvidenceWriter | None) -> None:
        self.writer = writer

    def write_intent(self, intent: EvidenceWriteIntent) -> str:
        validate_evidence_write_intent(intent)
        if intent.runtime_instance_id not in self.allowed_intent_runtime_ids:
            raise ContinuousEvidenceWriterError("Client received another runtime's intent.")
        if self._pending_intent is not None and self._pending_intent != intent:
            raise ContinuousEvidenceWriterError("A prior intent remains unacknowledged.")
        if self._pending_envelope is None:
            artifact = _EVIDENCE_TYPE_TO_ARTIFACT.get(intent.evidence_type)
            if artifact is None:
                raise ContinuousEvidenceWriterError("Evidence type has no canonical artifact.")
            self._pending_intent = intent
            self._pending_envelope = self.sender.build(
                artifact_name=artifact,
                payload={
                    "intent": asdict(intent),
                    "topologyFingerprint": self.topology.fingerprint,
                },
            )
        if self.writer is None or self.writer.closed:
            return WRITER_UNAVAILABLE
        started = time.perf_counter()
        try:
            acknowledgement = self.writer.accept(self._pending_envelope)
        except WriterUnavailableError:
            return WRITER_UNAVAILABLE
        elapsed = time.perf_counter() - started
        if elapsed > self.maximum_ack_seconds:
            return WRITER_SLOW
        if acknowledgement.status not in {WRITER_ACCEPTED, WRITER_DUPLICATE}:
            raise ContinuousEvidenceWriterError("Writer acknowledgement status is unsupported.")
        result = acknowledgement.status
        self._pending_intent = None
        self._pending_envelope = None
        return result


def read_evidence_snapshot(
    topology: ContinuousWriterTopologyV2,
    *,
    reader_role: str,
) -> EvidenceReadSnapshot:
    if not authorize_topology_access(topology, role=reader_role, operation=READ):
        raise ContinuousEvidenceWriterError("Role cannot read continuous evidence.")
    records_root = _evidence_root(topology) / "records"
    records = (
        tuple(_validate_record_file(topology, path) for path in sorted(records_root.rglob("*.json")))
        if records_root.exists()
        else ()
    )
    identity = {
        "topologyId": topology.topology_id,
        "records": [asdict(item) for item in records],
    }
    return EvidenceReadSnapshot(
        topology_id=topology.topology_id,
        record_count=len(records),
        records=records,
        fingerprint=_fingerprint("continuous-evidence-read-snapshot-v1", identity),
    )


def _intent_from_envelope(
    envelope: WriterEnvelope,
    *,
    topology_fingerprint: str,
) -> EvidenceWriteIntent:
    try:
        payload = json.loads(envelope.payload_json)
        if set(payload) != {"intent", "topologyFingerprint"}:
            raise ContinuousEvidenceWriterError(
                "Envelope contains unsupported payload fields."
            )
        if payload.get("topologyFingerprint") != topology_fingerprint:
            raise ContinuousEvidenceWriterError(
                "Envelope topology fingerprint is contradictory."
            )
        raw_intent = payload["intent"]
        if not isinstance(raw_intent, dict):
            raise TypeError("intent")
        intent = EvidenceWriteIntent(**raw_intent)
        validate_evidence_write_intent(intent)
    except (KeyError, TypeError, json.JSONDecodeError, ContinuousRuntimeError) as exc:
        raise ContinuousEvidenceWriterError("Envelope intent payload is malformed.") from exc
    return intent


def _build_record_document(
    topology: ContinuousWriterTopologyV2,
    envelope: WriterEnvelope,
    intent: EvidenceWriteIntent,
) -> dict[str, object]:
    base: dict[str, object] = {
        "schemaVersion": RECORD_SCHEMA_VERSION,
        "profile": RECORD_PROFILE,
        "authority": AUTHORITY,
        "topologyId": topology.topology_id,
        "topologyFingerprint": topology.fingerprint,
        "writerRole": DEDICATED_EVIDENCE_WRITER,
        "ipcProtocol": PROTOCOL,
        "artifactName": envelope.artifact_name,
        "sessionId": envelope.session_id,
        "envelopeSequence": envelope.sequence,
        "envelopeFingerprint": envelope.fingerprint,
        "intent": asdict(intent),
        "storageFingerprint": "",
    }
    base["storageFingerprint"] = _fingerprint("continuous-evidence-record-v2", base)
    return base


def _validate_record_file(
    topology: ContinuousWriterTopologyV2,
    path: Path,
) -> EvidenceRecordView:
    document, data = _read_canonical_document(path, "Evidence record")
    if (
        document.get("schemaVersion") != RECORD_SCHEMA_VERSION
        or document.get("profile") != RECORD_PROFILE
        or document.get("authority") != AUTHORITY
        or document.get("topologyId") != topology.topology_id
        or document.get("topologyFingerprint") != topology.fingerprint
        or document.get("writerRole") != DEDICATED_EVIDENCE_WRITER
        or document.get("ipcProtocol") != PROTOCOL
    ):
        raise ContinuousEvidenceWriterError("Evidence record contract is invalid.")
    artifact = _artifact_name(str(document.get("artifactName", "")))
    raw_intent = document.get("intent")
    if not isinstance(raw_intent, dict):
        raise ContinuousEvidenceWriterError("Evidence record intent is malformed.")
    try:
        intent = EvidenceWriteIntent(**raw_intent)
        validate_evidence_write_intent(intent)
    except (TypeError, ContinuousRuntimeError) as exc:
        raise ContinuousEvidenceWriterError("Evidence record intent is malformed.") from exc
    expected_storage = _fingerprint(
        "continuous-evidence-record-v2",
        {**document, "storageFingerprint": ""},
    )
    if document.get("storageFingerprint") != expected_storage:
        raise ContinuousEvidenceWriterError("Evidence record fingerprint is invalid.")
    expected_path = artifact_record_path(
        topology,
        artifact_name=artifact,
        record_fingerprint=intent.record_fingerprint,
    )
    if path.resolve() != expected_path.resolve():
        raise ContinuousEvidenceWriterError("Evidence record path is noncanonical.")
    relative = expected_path.relative_to(_evidence_root(topology)).as_posix()
    return EvidenceRecordView(
        artifact_name=artifact,
        record_identity=intent.record_identity,
        record_fingerprint=intent.record_fingerprint,
        intent_id=intent.intent_id,
        intent_sequence=intent.sequence,
        predecessor_identity=intent.predecessor_identity,
        relative_path=relative,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _validate_ack_file(
    topology: ContinuousWriterTopologyV2,
    path: Path,
) -> tuple[WriterEnvelope, EvidenceWriterAcknowledgement]:
    document, _data = _read_canonical_document(path, "Writer acknowledgement")
    if (
        document.get("schemaVersion") != RECORD_SCHEMA_VERSION
        or document.get("profile") != ACK_PROFILE
        or document.get("topologyId") != topology.topology_id
        or document.get("topologyFingerprint") != topology.fingerprint
    ):
        raise ContinuousEvidenceWriterError("Writer acknowledgement contract is invalid.")
    try:
        envelope = WriterEnvelope(**document["envelope"])
        acknowledgement = EvidenceWriterAcknowledgement(**document["acknowledgement"])
    except (KeyError, TypeError) as exc:
        raise ContinuousEvidenceWriterError("Writer acknowledgement is malformed.") from exc
    expected_path = _ack_path(topology, envelope.session_id, envelope.sequence)
    if path.resolve() != expected_path.resolve():
        raise ContinuousEvidenceWriterError("Writer acknowledgement path is noncanonical.")
    provisional = replace(acknowledgement, acknowledgement_id="", fingerprint="")
    identity = _fingerprint("continuous-writer-ack-v1", asdict(provisional))
    with_identity = replace(
        provisional,
        acknowledgement_id=f"continuous-writer-ack-{identity[:24]}",
    )
    expected_fingerprint = _fingerprint("continuous-writer-ack-v1", asdict(with_identity))
    if acknowledgement != replace(with_identity, fingerprint=expected_fingerprint):
        raise ContinuousEvidenceWriterError("Writer acknowledgement identity is invalid.")
    if (
        acknowledgement.session_id != envelope.session_id
        or acknowledgement.sequence != envelope.sequence
        or acknowledgement.envelope_fingerprint != envelope.fingerprint
        or acknowledgement.status not in {WRITER_ACCEPTED, WRITER_DUPLICATE}
        or acknowledgement.error_state is not None
    ):
        raise ContinuousEvidenceWriterError("Writer acknowledgement is contradictory.")
    record_path = _evidence_root(topology) / PurePath(acknowledgement.relative_record_path)
    _require_descendant(record_path, _evidence_root(topology))
    try:
        record_bytes = record_path.read_bytes()
    except OSError as exc:
        raise ContinuousEvidenceWriterError(
            "Writer acknowledgement references missing evidence."
        ) from exc
    if hashlib.sha256(record_bytes).hexdigest() != acknowledgement.record_sha256:
        raise ContinuousEvidenceWriterError(
            "Writer acknowledgement record hash is invalid."
        )
    return envelope, acknowledgement


def _read_canonical_document(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    try:
        data = path.read_bytes()
        document = json.loads(data)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuousEvidenceWriterError(f"{label} is unreadable.") from exc
    if not isinstance(document, dict) or data != _canonical_bytes(document):
        raise ContinuousEvidenceWriterError(f"{label} is not canonical JSON.")
    return document, data


def _ack_path(
    topology: ContinuousWriterTopologyV2,
    session_id: str,
    sequence: int,
) -> Path:
    session = _session_id(session_id)
    if not isinstance(sequence, int) or sequence < 1:
        raise ContinuousEvidenceWriterError("Acknowledgement sequence is invalid.")
    base = _evidence_root(topology)
    result = base / "sessions" / session / f"{sequence:08d}.ack.json"
    _require_descendant(result, base)
    return result


def _trusted_writer_record_path(
    root: Path,
    *,
    artifact_name: str,
    record_fingerprint: str,
) -> Path:
    """Derive a path from identities already validated at the writer boundary."""

    artifact = _artifact_name(artifact_name)
    fingerprint = _sha256(record_fingerprint, "Record fingerprint")
    return root / "records" / artifact / fingerprint[:2] / f"{fingerprint}.json"


def _trusted_writer_ack_path(root: Path, session_id: str, sequence: int) -> Path:
    """Derive an acknowledgement path under the writer's pinned topology root."""

    session = _session_id(session_id)
    if not isinstance(sequence, int) or sequence < 1:
        raise ContinuousEvidenceWriterError("Acknowledgement sequence is invalid.")
    return root / "sessions" / session / f"{sequence:08d}.ack.json"


def _evidence_root(topology: ContinuousWriterTopologyV2) -> Path:
    return Path(topology.root_path) / topology.namespace


def _topology_fingerprint(topology: ContinuousWriterTopologyV2) -> str:
    return _fingerprint(
        "continuous-writer-topology-v2",
        asdict(replace(topology, fingerprint="")),
    )


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(_canonical_bytes({"domain": domain, "value": value})).hexdigest()


def _canonical_root(path: Path) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raise ContinuousEvidenceWriterError("Writer root must be absolute.")
    result = raw.resolve()
    if any(part.casefold() in _RESERVED_DEVICE_NAMES for part in result.parts):
        raise ContinuousEvidenceWriterError("Writer root contains a reserved device name.")
    return result


def _program_id(value: str) -> str:
    normalized = _required_text(value, "Evidence program identity")
    if _PROGRAM_ID.fullmatch(normalized) is None:
        raise ContinuousEvidenceWriterError("Evidence program identity is malformed.")
    if normalized.split(".", 1)[0].casefold() in _RESERVED_DEVICE_NAMES:
        raise ContinuousEvidenceWriterError("Evidence program uses a reserved device name.")
    return normalized


def _artifact_name(value: str) -> str:
    normalized = _required_text(value, "Artifact identity")
    if normalized not in ALLOWED_ARTIFACTS:
        raise ContinuousEvidenceWriterError("Artifact is outside the writer allowlist.")
    return normalized


def _session_id(value: str) -> str:
    normalized = _required_text(value, "Writer session identity")
    if _SESSION_ID.fullmatch(normalized) is None:
        raise ContinuousEvidenceWriterError("Writer session identity is malformed.")
    return normalized


def _sha256(value: str, label: str) -> str:
    normalized = _required_text(value, label)
    if _SHA256.fullmatch(normalized) is None:
        raise ContinuousEvidenceWriterError(f"{label} must be lowercase SHA-256.")
    return normalized


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContinuousEvidenceWriterError(f"{label} is required in canonical form.")
    return value


def _require_descendant(path: Path, parent: Path) -> None:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError as exc:
        raise ContinuousEvidenceWriterError("Writer-derived path escaped its evidence root.") from exc


def _claim_root(root: Path, token: str) -> None:
    resolved = root.resolve()
    with _ROOT_OWNERS_GUARD:
        if resolved in _ROOT_OWNERS:
            raise ContinuousEvidenceWriterError("A logical writer already owns this evidence root.")
        _ROOT_OWNERS[resolved] = token


def _release_root(root: Path, token: str) -> None:
    resolved = root.resolve()
    with _ROOT_OWNERS_GUARD:
        if _ROOT_OWNERS.get(resolved) == token:
            _ROOT_OWNERS.pop(resolved, None)


__all__ = [
    "ACTIVATION_BLOCKERS",
    "APPEND",
    "AuthenticatedEvidenceWriterClient",
    "CRASH_AFTER_ACK_BEFORE_RETURN",
    "CRASH_AFTER_COMMIT_BEFORE_ACK",
    "CRASH_AFTER_TEMP",
    "CRASH_BEFORE_COMMIT",
    "CONTINUOUS_RUNTIME",
    "ContinuousEvidenceWriterError",
    "ContinuousWriterTopologyV2",
    "DEDICATED_EVIDENCE_WRITER",
    "DedicatedEvidenceWriter",
    "EvidenceReadSnapshot",
    "EvidenceRecordView",
    "EvidenceWriterAcknowledgement",
    "PhysicalWriterOwnershipConflictError",
    "READ",
    "STORAGE_FORMAT",
    "TOPOLOGY_VERSION",
    "TopologyCompatibility",
    "TopologyContradiction",
    "WriterCrashInjected",
    "WRITER_OWNER_CONFLICT",
    "WriterRoleContract",
    "artifact_record_path",
    "authorize_topology_access",
    "build_continuous_writer_topology_v2",
    "build_production_continuous_writer_topology",
    "create_ephemeral_writer_capability",
    "read_evidence_snapshot",
    "topology_contradiction_inventory",
    "topology_v1_compatibility",
    "validate_continuous_writer_topology_v2",
    "validate_production_continuous_writer_topology",
    "PRODUCTION_ACTIVATION_STATE",
    "PRODUCTION_TOPOLOGY_PROFILE",
]
