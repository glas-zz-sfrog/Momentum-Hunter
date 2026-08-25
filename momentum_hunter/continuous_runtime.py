from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


CONTRACT_VERSION = 1
RUNTIME_PROFILE = "independent-continuous-opportunity-runtime-v1"
RUNTIME_POLICY_VERSION = "continuous-runtime-policy-v1"
RESEARCH_AUTHORITY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY_NONE = "EXECUTION_AUTHORITY_NONE"
ORDER_CAPABILITY_UNAVAILABLE = "UNAVAILABLE"

STARTING = "STARTING"
READY = "READY"
RUNNING = "RUNNING"
DEGRADED = "DEGRADED"
DRAINING = "DRAINING"
STOPPED = "STOPPED"
FAILED = "FAILED"
PROCESS_STATES = frozenset(
    {STARTING, READY, RUNNING, DEGRADED, DRAINING, STOPPED, FAILED}
)

CANONICAL_BAR_COMPLETED = "CANONICAL_BAR_COMPLETED"
READINESS_CHANGED = "READINESS_CHANGED"
MEMBER_PROMOTED = "MEMBER_PROMOTED"
SETUP_STATE_CHANGED = "SETUP_STATE_CHANGED"
DATA_RECOVERED = "DATA_RECOVERED"
CATALYST_EVENT_AVAILABLE = "CATALYST_EVENT_AVAILABLE"
REGIME_EVENT_AVAILABLE = "REGIME_EVENT_AVAILABLE"
HEARTBEAT_REEVALUATION = "HEARTBEAT_REEVALUATION"
EVENT_TRIGGERS = frozenset(
    {
        CANONICAL_BAR_COMPLETED,
        READINESS_CHANGED,
        MEMBER_PROMOTED,
        SETUP_STATE_CHANGED,
        DATA_RECOVERED,
        CATALYST_EVENT_AVAILABLE,
        REGIME_EVENT_AVAILABLE,
        HEARTBEAT_REEVALUATION,
    }
)

DISCOVERY_QUEUE = "discovery"
READINESS_QUEUE = "readiness"
COMPOSITION_QUEUE = "composition"
EVIDENCE_QUEUE = "evidence"
HEALTH_QUEUE = "health"
QUEUE_NAMES = (
    DISCOVERY_QUEUE,
    READINESS_QUEUE,
    COMPOSITION_QUEUE,
    EVIDENCE_QUEUE,
    HEALTH_QUEUE,
)

ENQUEUED = "ENQUEUED"
COALESCED_DUPLICATE = "COALESCED_DUPLICATE"
REPLACED_OBSOLETE = "REPLACED_OBSOLETE"
REJECTED_CAPACITY = "REJECTED_CAPACITY"
REJECTED_STALE = "REJECTED_STALE"
EVICTED_LOWER_PRIORITY = "EVICTED_LOWER_PRIORITY"

WRITER_ACCEPTED = "ACCEPTED"
WRITER_DUPLICATE = "DUPLICATE"
WRITER_UNAVAILABLE = "WRITER_UNAVAILABLE"
WRITER_SLOW = "WRITER_SLOW"
PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
SERIALIZATION_INVALID = "SERIALIZATION_INVALID"
SCHEMA_INVALID = "SCHEMA_INVALID"
IPC_AUTH_REJECTED = "IPC_AUTH_REJECTED"
IPC_PROTOCOL_REJECTED = "IPC_PROTOCOL_REJECTED"
WRITER_OWNER_CONFLICT = "WRITER_OWNER_CONFLICT"
WRITE_FAILED = "WRITE_FAILED"
EVIDENCE_REJECTED_PERMANENT = "EVIDENCE_REJECTED_PERMANENT"
WRITER_RESULTS = frozenset(
    {
        WRITER_ACCEPTED,
        WRITER_DUPLICATE,
        WRITER_UNAVAILABLE,
        WRITER_SLOW,
        PAYLOAD_TOO_LARGE,
        SERIALIZATION_INVALID,
        SCHEMA_INVALID,
        IPC_AUTH_REJECTED,
        IPC_PROTOCOL_REJECTED,
        WRITER_OWNER_CONFLICT,
        WRITE_FAILED,
    }
)
TRANSIENT_WRITER_RESULTS = frozenset(
    {WRITER_UNAVAILABLE, WRITER_SLOW, WRITE_FAILED}
)
PERMANENT_RECORD_WRITER_RESULTS = frozenset(
    {PAYLOAD_TOO_LARGE, SERIALIZATION_INVALID, SCHEMA_INVALID, IPC_PROTOCOL_REJECTED}
)

PREMARKET_DEFERRED = "PREMARKET_DEFERRED"
REGULAR_SESSION_ROLLOVER = "REGULAR_SESSION_ROLLOVER"

PIPELINE_INITIALIZING = "INITIALIZING"
PIPELINE_FORWARD_PROGRESS = "FORWARD_PROGRESS"
PIPELINE_STALLED = "STALLED"
FAILED_FORWARD_PROGRESS = "FAILED_FORWARD_PROGRESS"

CHECKPOINT_SCHEMA_VERSION = 2

PROCESS_ALIVE = "PROCESS_ALIVE"
DISCOVERY_STALE = "DISCOVERY_STALE"
COMPOSITION_STALE = "COMPOSITION_STALE"
DENOMINATOR_DEGRADED = "DENOMINATOR_DEGRADED"


@dataclass(frozen=True)
class WriterPreflight:
    accepted: bool
    payload_bytes: int
    encoded_envelope_bytes: int
    protocol_ceiling_bytes: int
    failure_class: str | None = None

    def __post_init__(self) -> None:
        if min(
            self.payload_bytes,
            self.encoded_envelope_bytes,
            self.protocol_ceiling_bytes,
        ) < 0:
            raise ContinuousRuntimeError("Writer preflight sizes cannot be negative.")
        if self.protocol_ceiling_bytes <= 0:
            raise ContinuousRuntimeError("Writer preflight ceiling must be positive.")
        if self.accepted and self.failure_class is not None:
            raise ContinuousRuntimeError("Accepted writer preflight has a failure class.")
        if not self.accepted and self.failure_class not in WRITER_RESULTS:
            raise ContinuousRuntimeError("Writer preflight failure class is unsupported.")


@dataclass(frozen=True)
class WriterWriteResult:
    status: str
    payload_bytes: int = 0
    encoded_envelope_bytes: int = 0
    protocol_ceiling_bytes: int = 0
    detail_code: str | None = None

    def __post_init__(self) -> None:
        if self.status not in WRITER_RESULTS:
            raise ContinuousRuntimeError("Writer result status is unsupported.")
        if min(
            self.payload_bytes,
            self.encoded_envelope_bytes,
            self.protocol_ceiling_bytes,
        ) < 0:
            raise ContinuousRuntimeError("Writer result sizes cannot be negative.")


class ContinuousRuntimeError(ValueError):
    """Raised when the independent runtime contract fails closed."""


class RuntimeLeaseError(ContinuousRuntimeError):
    """Raised when another logical runtime owns the requested identity."""


class RuntimeCheckpointError(ContinuousRuntimeError):
    """Raised when an offline checkpoint is missing, corrupt, or incompatible."""


class RuntimeSequenceError(ContinuousRuntimeError):
    """Raised when evidence-intent ordering is contradictory."""


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_json({"domain": domain, "value": value})
    ).hexdigest()


def _parse_timestamp(value: str, label: str = "timestamp") -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContinuousRuntimeError(f"{label} is malformed.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContinuousRuntimeError(f"{label} must be timezone-aware.")
    return parsed


def _timestamp(value: datetime, label: str = "timestamp") -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContinuousRuntimeError(f"{label} must be timezone-aware.")
    return value.isoformat()


def _optional_checkpoint_timestamp(
    payload: Mapping[str, object], key: str
) -> datetime | None:
    value = payload.get(key)
    return _parse_timestamp(str(value), key) if value else None


def _require_fingerprint(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ContinuousRuntimeError(f"{label} must be lowercase SHA-256 evidence.")


def _positive(value: int | float, label: str) -> None:
    if value <= 0:
        raise ContinuousRuntimeError(f"{label} must be positive.")


@dataclass(frozen=True)
class RuntimeCadence:
    broad_discovery_seconds: float
    housekeeping_seconds: float
    discovery_stale_seconds: float
    composition_stale_seconds: float

    def __post_init__(self) -> None:
        for label, value in (
            ("Broad-discovery cadence", self.broad_discovery_seconds),
            ("Housekeeping cadence", self.housekeeping_seconds),
            ("Discovery stale threshold", self.discovery_stale_seconds),
            ("Composition stale threshold", self.composition_stale_seconds),
        ):
            _positive(value, label)


@dataclass(frozen=True)
class QueueCapacities:
    discovery: int = 2
    readiness: int = 64
    composition: int = 64
    evidence: int = 128
    health: int = 16

    def __post_init__(self) -> None:
        for name in QUEUE_NAMES:
            _positive(getattr(self, name), f"{name} queue capacity")

    def as_mapping(self) -> dict[str, int]:
        return {name: int(getattr(self, name)) for name in QUEUE_NAMES}


@dataclass(frozen=True)
class ContinuousRuntimeConfig:
    runtime_identity: str
    session_date: str
    cadence: RuntimeCadence
    queues: QueueCapacities = field(default_factory=QueueCapacities)
    lease_ttl_seconds: float = 30.0
    shutdown_timeout_seconds: float = 10.0
    processed_event_capacity: int = 4096
    evidence_history_capacity: int = 65536
    diagnostic_capacity: int = 256
    maximum_tracked_symbols: int = 128
    policy_version: str = RUNTIME_POLICY_VERSION

    def __post_init__(self) -> None:
        if not self.runtime_identity.strip():
            raise ContinuousRuntimeError("Runtime identity is required.")
        try:
            datetime.fromisoformat(self.session_date)
        except ValueError as exc:
            raise ContinuousRuntimeError("Session date is malformed.") from exc
        for label, value in (
            ("Lease TTL", self.lease_ttl_seconds),
            ("Shutdown timeout", self.shutdown_timeout_seconds),
            ("Processed-event capacity", self.processed_event_capacity),
            ("Evidence-history capacity", self.evidence_history_capacity),
            ("Diagnostic capacity", self.diagnostic_capacity),
            ("Maximum tracked symbols", self.maximum_tracked_symbols),
        ):
            _positive(value, label)

    @property
    def fingerprint(self) -> str:
        return _fingerprint("continuous-runtime-config-v1", asdict(self))


@dataclass(frozen=True)
class DiscoveryRequest:
    request_id: str
    requested_at: str
    reason: str


@dataclass(frozen=True)
class DiscoveryPulse:
    pulse_id: str
    fingerprint: str
    source_rows_represented: int
    symbols_for_readiness: tuple[str, ...]
    new_symbols: tuple[str, ...] = ()
    retained_symbols: tuple[str, ...] = ()
    provider_bound_symbols: tuple[str, ...] = ()
    evidence_payload_json: str | None = None

    def __post_init__(self) -> None:
        _require_fingerprint(self.fingerprint, "Discovery pulse fingerprint")
        if self.source_rows_represented < 0:
            raise ContinuousRuntimeError("Discovery source-row count cannot be negative.")
        if self.evidence_payload_json is not None:
            try:
                evidence = json.loads(self.evidence_payload_json)
            except json.JSONDecodeError as exc:
                raise ContinuousRuntimeError(
                    "Discovery evidence payload is malformed."
                ) from exc
            if not isinstance(evidence, dict):
                raise ContinuousRuntimeError(
                    "Discovery evidence payload must be an object."
                )


@dataclass(frozen=True)
class RuntimeTriggerEvent:
    event_id: str
    trigger: str
    occurred_at: str
    symbol: str | None = None
    source_fingerprint: str | None = None
    priority: int = 50

    def __post_init__(self) -> None:
        if self.trigger not in EVENT_TRIGGERS:
            raise ContinuousRuntimeError("Runtime trigger is unsupported.")
        _parse_timestamp(self.occurred_at, "Event timestamp")
        if self.source_fingerprint is not None:
            _require_fingerprint(self.source_fingerprint, "Event source fingerprint")
        if self.trigger != HEARTBEAT_REEVALUATION and not (self.symbol or "").strip():
            raise ContinuousRuntimeError("Symbol event omitted its symbol.")


@dataclass(frozen=True)
class ReadinessRequest:
    request_id: str
    symbol: str
    trigger: str
    requested_at: str
    source_fingerprint: str


@dataclass(frozen=True)
class ReadinessResult:
    request_id: str
    symbol: str
    status: str
    fingerprint: str
    ready: bool
    failure_reason: str | None = None
    deferred: bool = False

    def __post_init__(self) -> None:
        _require_fingerprint(self.fingerprint, "Readiness fingerprint")
        if self.ready and self.failure_reason:
            raise ContinuousRuntimeError("Ready evidence cannot carry a failure reason.")
        if self.deferred and (self.ready or self.failure_reason):
            raise ContinuousRuntimeError(
                "Deferred readiness is neither ready nor failed."
            )
        if self.deferred and self.status != PREMARKET_DEFERRED:
            raise ContinuousRuntimeError("Deferred readiness status is inconsistent.")


@dataclass(frozen=True)
class CompositionRequest:
    request_id: str
    symbol: str
    trigger: str
    requested_at: str
    readiness_fingerprint: str


@dataclass(frozen=True)
class CompositionResult:
    request_id: str
    symbol: str
    cycle_id: str
    fingerprint: str
    lifecycle_transitions: int = 0
    setup_id: str | None = None
    plan_id: str | None = None
    evidence_payload_json: str | None = None

    def __post_init__(self) -> None:
        _require_fingerprint(self.fingerprint, "Composition fingerprint")
        if self.lifecycle_transitions < 0:
            raise ContinuousRuntimeError("Lifecycle transition count cannot be negative.")
        if self.evidence_payload_json is not None:
            try:
                evidence = json.loads(self.evidence_payload_json)
            except json.JSONDecodeError as exc:
                raise ContinuousRuntimeError(
                    "Composition evidence payload is malformed."
                ) from exc
            if not isinstance(evidence, dict):
                raise ContinuousRuntimeError(
                    "Composition evidence payload must be an object."
                )


@dataclass(frozen=True)
class DenominatorRequest:
    request_id: str
    symbol: str
    requested_at: str
    composition_cycle_id: str
    composition_fingerprint: str
    provider_bound_symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class DenominatorResult:
    cycle_id: str
    fingerprint: str
    complete: bool
    opportunity_count: int
    incomplete_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_fingerprint(self.fingerprint, "Denominator fingerprint")
        if self.opportunity_count < 0:
            raise ContinuousRuntimeError("Opportunity count cannot be negative.")
        if self.complete and self.incomplete_reasons:
            raise ContinuousRuntimeError("Complete denominator carries incomplete reasons.")
        if not self.complete and not self.incomplete_reasons:
            raise ContinuousRuntimeError("Incomplete denominator omitted its reasons.")


class DiscoverySource(Protocol):
    def discover(self, request: DiscoveryRequest) -> DiscoveryPulse: ...


class CanonicalMarketDataSource(Protocol):
    def evaluate(self, request: ReadinessRequest) -> ReadinessResult: ...


class EventSource(Protocol):
    def poll(self, now: datetime) -> Iterable[RuntimeTriggerEvent]: ...


class CompositionSource(Protocol):
    def compose(self, request: CompositionRequest) -> CompositionResult: ...


class DenominatorSource(Protocol):
    def produce(self, request: DenominatorRequest) -> DenominatorResult: ...


class EvidenceIntentWriter(Protocol):
    def write_intent(
        self, intent: "EvidenceWriteIntent"
    ) -> str | WriterWriteResult: ...

    def preflight_intent(self, intent: "EvidenceWriteIntent") -> WriterPreflight: ...


@dataclass(frozen=True)
class EvidenceWriteIntent:
    intent_id: str
    runtime_instance_id: str
    sequence: int
    evidence_type: str
    record_identity: str
    record_fingerprint: str
    predecessor_identity: str | None
    requested_at: str
    payload_fingerprint: str
    fingerprint: str
    payload_json: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("Intent identity", self.intent_id),
            ("Runtime instance identity", self.runtime_instance_id),
            ("Evidence type", self.evidence_type),
            ("Record identity", self.record_identity),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ContinuousRuntimeError(f"{label} is required.")
        for label, value in (
            ("Record fingerprint", self.record_fingerprint),
            ("Payload fingerprint", self.payload_fingerprint),
            ("Intent fingerprint", self.fingerprint),
        ):
            _require_fingerprint(value, label)
        if self.sequence <= 0:
            raise ContinuousRuntimeError("Intent sequence must be positive.")
        if self.predecessor_identity is not None and not self.predecessor_identity.strip():
            raise ContinuousRuntimeError("Intent predecessor identity is malformed.")
        _parse_timestamp(self.requested_at, "Intent timestamp")


@dataclass(frozen=True)
class EvidenceRejection:
    failed_intent_id: str
    failed_record_identity: str
    failed_record_fingerprint: str
    payload_fingerprint: str
    payload_bytes: int
    encoded_envelope_bytes: int
    protocol_ceiling_bytes: int
    retry_count: int
    failure_class: str
    source_cycle: str
    known_at: str
    compact_intent_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        for label, value in (
            ("Failed intent identity", self.failed_intent_id),
            ("Failed record identity", self.failed_record_identity),
            ("Source cycle", self.source_cycle),
            ("Compact intent identity", self.compact_intent_id),
        ):
            if not value.strip():
                raise ContinuousRuntimeError(f"{label} is required.")
        for label, value in (
            ("Failed record fingerprint", self.failed_record_fingerprint),
            ("Payload fingerprint", self.payload_fingerprint),
            ("Evidence rejection fingerprint", self.fingerprint),
        ):
            _require_fingerprint(value, label)
        if self.failure_class not in PERMANENT_RECORD_WRITER_RESULTS:
            raise ContinuousRuntimeError("Evidence rejection is not record-terminal.")
        if min(
            self.payload_bytes,
            self.encoded_envelope_bytes,
            self.protocol_ceiling_bytes,
            self.retry_count,
        ) < 0:
            raise ContinuousRuntimeError("Evidence rejection sizes cannot be negative.")
        _parse_timestamp(self.known_at, "Evidence rejection timestamp")


def validate_evidence_write_intent(intent: EvidenceWriteIntent) -> None:
    """Recompute the complete immutable identity of a write intent."""

    payload = {
        "runtime_instance_id": intent.runtime_instance_id,
        "sequence": intent.sequence,
        "evidence_type": intent.evidence_type,
        "record_identity": intent.record_identity,
        "record_fingerprint": intent.record_fingerprint,
        "predecessor_identity": intent.predecessor_identity,
        "requested_at": intent.requested_at,
        "payload_fingerprint": intent.payload_fingerprint,
    }
    if intent.payload_json is not None:
        try:
            decoded = json.loads(intent.payload_json)
        except (TypeError, ValueError) as exc:
            raise ContinuousRuntimeError("Evidence payload JSON is malformed.") from exc
        if not isinstance(decoded, dict):
            raise ContinuousRuntimeError("Evidence payload must be an object.")
        if _fingerprint("continuous-evidence-payload-v1", decoded) != intent.payload_fingerprint:
            raise ContinuousRuntimeError("Evidence payload fingerprint is invalid.")
        payload["payload_json"] = intent.payload_json
    fingerprint = _fingerprint("continuous-evidence-write-intent-v1", payload)
    if intent.fingerprint != fingerprint:
        raise ContinuousRuntimeError("Evidence write intent fingerprint is invalid.")
    if intent.intent_id != f"continuous-intent-{fingerprint[:24]}":
        raise ContinuousRuntimeError("Evidence write intent identity is invalid.")


def build_evidence_write_intent(
    *,
    runtime_instance_id: str,
    sequence: int,
    evidence_type: str,
    record_identity: str,
    record_fingerprint: str,
    predecessor_identity: str | None,
    requested_at: str,
    payload_fingerprint: str,
    payload: Mapping[str, Any] | None = None,
) -> EvidenceWriteIntent:
    intent_payload = {
        "runtime_instance_id": runtime_instance_id,
        "sequence": sequence,
        "evidence_type": evidence_type,
        "record_identity": record_identity,
        "record_fingerprint": record_fingerprint,
        "predecessor_identity": predecessor_identity,
        "requested_at": requested_at,
        "payload_fingerprint": payload_fingerprint,
    }
    payload_json = None
    if payload is not None:
        payload_json = _canonical_json(dict(payload)).decode("ascii").strip()
        expected_payload = _fingerprint("continuous-evidence-payload-v1", dict(payload))
        if expected_payload != payload_fingerprint:
            raise ContinuousRuntimeError("Evidence payload fingerprint does not match payload.")
        intent_payload["payload_json"] = payload_json
    fingerprint = _fingerprint("continuous-evidence-write-intent-v1", intent_payload)
    result = EvidenceWriteIntent(
        intent_id=f"continuous-intent-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **intent_payload,
    )
    validate_evidence_write_intent(result)
    return result


@dataclass(frozen=True)
class QueuedWork:
    kind: str
    key: str
    requested_at: str
    priority: int
    payload_json: str
    fingerprint: str

    @property
    def payload(self) -> Mapping[str, object]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ContinuousRuntimeError("Queued payload is not an object.")
        return value


def build_work(
    *, kind: str, key: str, requested_at: str, priority: int, payload: Mapping[str, object]
) -> QueuedWork:
    _parse_timestamp(requested_at, "Work timestamp")
    payload_json = _canonical_json(payload).decode("ascii").strip()
    values = {
        "kind": kind,
        "key": key,
        "requested_at": requested_at,
        "priority": priority,
        "payload_json": payload_json,
    }
    return QueuedWork(
        **values,
        fingerprint=_fingerprint("continuous-runtime-work-v1", values),
    )


@dataclass(frozen=True)
class BackpressureDecision:
    queue_name: str
    work_key: str
    decision: str
    decided_at: str
    displaced_key: str | None
    source_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class QueueMetrics:
    configured_capacity: int
    current_depth: int
    high_water_mark: int
    dropped_count: int
    rejected_count: int
    coalesced_count: int
    replaced_count: int
    oldest_age_seconds: float


class BoundedWorkQueue:
    def __init__(self, name: str, capacity: int) -> None:
        if name not in QUEUE_NAMES:
            raise ContinuousRuntimeError("Unknown runtime queue.")
        _positive(capacity, f"{name} queue capacity")
        self.name = name
        self.capacity = capacity
        self._items: OrderedDict[str, QueuedWork] = OrderedDict()
        self.high_water_mark = 0
        self.dropped_count = 0
        self.rejected_count = 0
        self.coalesced_count = 0
        self.replaced_count = 0

    def enqueue(self, work: QueuedWork, now: datetime) -> tuple[str, QueuedWork | None]:
        if work.key in self._items:
            existing = self._items[work.key]
            if existing.fingerprint == work.fingerprint:
                self.coalesced_count += 1
                return COALESCED_DUPLICATE, None
            if _parse_timestamp(work.requested_at) < _parse_timestamp(existing.requested_at):
                self.rejected_count += 1
                return REJECTED_STALE, None
            self._items[work.key] = work
            self.replaced_count += 1
            return REPLACED_OBSOLETE, existing

        if len(self._items) >= self.capacity:
            lowest = min(self._items.values(), key=lambda item: (item.priority, item.requested_at))
            if work.priority > lowest.priority:
                del self._items[lowest.key]
                self._items[work.key] = work
                self.replaced_count += 1
                self.high_water_mark = max(self.high_water_mark, len(self._items))
                return EVICTED_LOWER_PRIORITY, lowest
            self.rejected_count += 1
            return REJECTED_CAPACITY, None

        self._items[work.key] = work
        self.high_water_mark = max(self.high_water_mark, len(self._items))
        return ENQUEUED, None

    def peek(self) -> QueuedWork | None:
        return next(iter(self._items.values()), None)

    def pop(self) -> QueuedWork | None:
        if not self._items:
            return None
        _, value = self._items.popitem(last=False)
        return value

    def restore(self, work: QueuedWork) -> None:
        if len(self._items) >= self.capacity and work.key not in self._items:
            raise RuntimeCheckpointError("Checkpoint queue exceeds configured capacity.")
        self._items[work.key] = work
        self.high_water_mark = max(self.high_water_mark, len(self._items))

    def metrics(self, now: datetime) -> QueueMetrics:
        oldest = 0.0
        if self._items:
            oldest_at = min(_parse_timestamp(item.requested_at) for item in self._items.values())
            oldest = max(0.0, (now - oldest_at).total_seconds())
        return QueueMetrics(
            configured_capacity=self.capacity,
            current_depth=len(self._items),
            high_water_mark=self.high_water_mark,
            dropped_count=self.dropped_count,
            rejected_count=self.rejected_count,
            coalesced_count=self.coalesced_count,
            replaced_count=self.replaced_count,
            oldest_age_seconds=oldest,
        )

    def snapshot(self) -> list[dict[str, object]]:
        return [asdict(item) for item in self._items.values()]

    def __len__(self) -> int:
        return len(self._items)


@dataclass(frozen=True)
class RuntimeLease:
    runtime_identity: str
    runtime_instance_id: str
    runtime_lease_id: str
    generation: int
    acquired_at: str
    heartbeat_at: str
    expires_at: str


class LogicalRuntimeLeaseRegistry:
    """In-process logical lease contract; physical Windows enforcement is later."""

    def __init__(self) -> None:
        self._leases: dict[str, RuntimeLease] = {}
        self._generations: dict[str, int] = {}

    def acquire(
        self, runtime_identity: str, runtime_instance_id: str, now: datetime, ttl: float
    ) -> tuple[RuntimeLease, bool]:
        current = self._leases.get(runtime_identity)
        stale_takeover = False
        if current is not None:
            if current.runtime_instance_id == runtime_instance_id:
                return self.heartbeat(current, now, ttl), False
            if _parse_timestamp(current.expires_at) > now:
                raise RuntimeLeaseError("Logical runtime identity is already owned.")
            stale_takeover = True
        generation = self._generations.get(runtime_identity, 0) + 1
        self._generations[runtime_identity] = generation
        values = {
            "runtime_identity": runtime_identity,
            "runtime_instance_id": runtime_instance_id,
            "generation": generation,
            "acquired_at": _timestamp(now),
        }
        lease_id = _fingerprint("continuous-runtime-lease-v1", values)
        lease = RuntimeLease(
            runtime_lease_id=lease_id,
            heartbeat_at=_timestamp(now),
            expires_at=_timestamp(now + timedelta(seconds=ttl)),
            **values,
        )
        self._leases[runtime_identity] = lease
        return lease, stale_takeover

    def heartbeat(self, lease: RuntimeLease, now: datetime, ttl: float) -> RuntimeLease:
        current = self._leases.get(lease.runtime_identity)
        if current is None or current.runtime_lease_id != lease.runtime_lease_id:
            raise RuntimeLeaseError("Logical runtime lease is no longer authoritative.")
        updated = RuntimeLease(
            **{
                **asdict(current),
                "heartbeat_at": _timestamp(now),
                "expires_at": _timestamp(now + timedelta(seconds=ttl)),
            }
        )
        self._leases[lease.runtime_identity] = updated
        return updated

    def release(self, lease: RuntimeLease) -> None:
        current = self._leases.get(lease.runtime_identity)
        if current is not None and current.runtime_lease_id == lease.runtime_lease_id:
            del self._leases[lease.runtime_identity]

    def current(self, runtime_identity: str) -> RuntimeLease | None:
        return self._leases.get(runtime_identity)


@dataclass(frozen=True)
class SymbolFailure:
    symbol: str
    stage: str
    reason: str
    observed_at: str
    source_fingerprint: str


@dataclass(frozen=True)
class RuntimeHealth:
    contract_version: int
    runtime_profile: str
    runtime_instance_id: str
    runtime_lease_id: str
    process_state: str
    health_flags: tuple[str, ...]
    started_at: str
    last_heartbeat_at: str
    uptime_seconds: float
    discovery_pulses_attempted: int
    discovery_pulses_completed: int
    discovery_failures: int
    source_rows_represented: int
    new_symbols: int
    retained_symbols: int
    provider_bound_symbols: int
    provider_bound_denominator_cycles: int
    readiness_requests: int
    readiness_completed: int
    readiness_deferred: int
    ready_members: int
    readiness_failures: int
    composition_cycles: int
    lifecycle_transitions: int
    setups_created: int
    plans_created: int
    denominator_cycles: int
    incomplete_denominator_cycles: int
    queue_depths: tuple[tuple[str, int], ...]
    queue_high_water_marks: tuple[tuple[str, int], ...]
    backpressure_events: int
    last_successful_discovery_at: str | None
    last_successful_composition_at: str | None
    checkpoint_writes: int
    restart_count: int
    writer_unavailable_events: int
    writer_slow_events: int
    evidence_accepted_count: int
    evidence_permanent_rejections: int
    payload_too_large_events: int
    heartbeat_count: int
    last_evidence_payload_bytes: int
    last_evidence_encoded_envelope_bytes: int
    maximum_evidence_encoded_envelope_bytes: int
    evidence_protocol_ceiling_bytes: int
    last_tick_at: str | None
    last_discovery_started_at: str | None
    last_discovery_completed_at: str | None
    last_readiness_completed_at: str | None
    last_composition_completed_at: str | None
    last_denominator_completed_at: str | None
    last_evidence_accepted_at: str | None
    active_queue: str | None
    queue_head_age_seconds: float
    queue_head_retry_count: int
    queue_head_failure_class: str | None
    last_forward_progress_at: str | None
    stalled_since: str | None
    pipeline_state: str
    stall_blocker: str | None
    stall_threshold_seconds: float
    fingerprint: str


class RuntimeCheckpointStore:
    """Atomic checkpoint store with an explicit opt-in for production persistence."""

    def __init__(self, root: Path, *, allow_persistent: bool = False) -> None:
        resolved = root.resolve()
        lowered = str(resolved).lower()
        if allow_persistent:
            if "one drive" in lowered or "\\.git" in lowered or ".git\\" in lowered:
                raise RuntimeCheckpointError("Production checkpoint root is not deployable.")
        else:
            temp_root = Path(tempfile.gettempdir()).resolve()
            try:
                resolved.relative_to(temp_root)
            except ValueError as exc:
                raise RuntimeCheckpointError(
                    "Runtime checkpoint root must remain under the temporary directory."
                ) from exc
            if "momentumhunterdata" in lowered or "programdata" in lowered:
                raise RuntimeCheckpointError("Production checkpoint roots are prohibited.")
        self.root = resolved
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, runtime_identity: str) -> Path:
        safe = "".join(character for character in runtime_identity if character.isalnum() or character in "-_")
        if safe != runtime_identity or not safe:
            raise RuntimeCheckpointError("Runtime identity is unsafe for checkpoint naming.")
        return self.root / f"{safe}.json"

    def save(self, runtime_identity: str, payload: Mapping[str, object]) -> Path:
        body = dict(payload)
        body.pop("checkpoint_fingerprint", None)
        body["checkpoint_fingerprint"] = _fingerprint(
            "continuous-runtime-checkpoint-v1", body
        )
        content = _canonical_json(body)
        destination = self.path_for(runtime_identity)
        temporary = destination.with_suffix(".tmp")
        with temporary.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return destination

    def load(self, runtime_identity: str) -> dict[str, object]:
        path = self.path_for(runtime_identity)
        try:
            payload = json.loads(path.read_text(encoding="ascii"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeCheckpointError("Runtime checkpoint is unreadable.") from exc
        if not isinstance(payload, dict):
            raise RuntimeCheckpointError("Runtime checkpoint is not an object.")
        fingerprint = payload.pop("checkpoint_fingerprint", None)
        expected = _fingerprint("continuous-runtime-checkpoint-v1", payload)
        if fingerprint != expected:
            raise RuntimeCheckpointError("Runtime checkpoint fingerprint is invalid.")
        payload["checkpoint_fingerprint"] = fingerprint
        return payload


class ManualClock:
    def __init__(self, now: datetime) -> None:
        _timestamp(now)
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        if seconds < 0:
            raise ContinuousRuntimeError("Manual clock cannot move backward.")
        self._now += timedelta(seconds=seconds)
        return self._now


class ContinuousOpportunityRuntime:
    """Deterministic owner for a future independent, research-only process lane."""

    def __init__(
        self,
        *,
        config: ContinuousRuntimeConfig,
        runtime_instance_id: str,
        discovery_source: DiscoverySource,
        market_data_source: CanonicalMarketDataSource,
        event_source: EventSource,
        composition_source: CompositionSource,
        denominator_source: DenominatorSource,
        writer: EvidenceIntentWriter,
        lease_registry: LogicalRuntimeLeaseRegistry,
        checkpoint_store: RuntimeCheckpointStore,
    ) -> None:
        if not runtime_instance_id.strip():
            raise ContinuousRuntimeError("Runtime instance identity is required.")
        self.config = config
        self.runtime_instance_id = runtime_instance_id
        self.discovery_source = discovery_source
        self.market_data_source = market_data_source
        self.event_source = event_source
        self.composition_source = composition_source
        self.denominator_source = denominator_source
        self.writer = writer
        self.lease_registry = lease_registry
        self.checkpoint_store = checkpoint_store
        self.lease: RuntimeLease | None = None
        self.process_state = STOPPED
        self.started_at: datetime | None = None
        self.last_heartbeat_at: datetime | None = None
        self.next_discovery_at: datetime | None = None
        self.next_housekeeping_at: datetime | None = None
        self.last_successful_discovery_at: datetime | None = None
        self.last_successful_composition_at: datetime | None = None
        self.last_tick_at: datetime | None = None
        self.last_discovery_started_at: datetime | None = None
        self.last_discovery_completed_at: datetime | None = None
        self.last_readiness_completed_at: datetime | None = None
        self.last_composition_completed_at: datetime | None = None
        self.last_denominator_completed_at: datetime | None = None
        self.last_evidence_accepted_at: datetime | None = None
        self.last_forward_progress_at: datetime | None = None
        self.stalled_since: datetime | None = None
        self.pipeline_state = PIPELINE_INITIALIZING
        self.stall_blocker: str | None = None
        self._resolved_discovery_cadence_seconds = (
            config.cadence.broad_discovery_seconds
        )
        self._session_work_eligible = False
        self._queues = {
            name: BoundedWorkQueue(name, capacity)
            for name, capacity in config.queues.as_mapping().items()
        }
        self._counters = {
            name: 0
            for name in (
                "discovery_pulses_attempted",
                "discovery_pulses_completed",
                "discovery_failures",
                "source_rows_represented",
                "new_symbols",
                "retained_symbols",
                "provider_bound_symbols",
                "provider_bound_denominator_cycles",
                "readiness_requests",
                "readiness_completed",
                "readiness_deferred",
                "ready_members",
                "readiness_failures",
                "composition_cycles",
                "lifecycle_transitions",
                "setups_created",
                "plans_created",
                "denominator_cycles",
                "incomplete_denominator_cycles",
                "backpressure_events",
                "checkpoint_writes",
                "restart_count",
                "writer_unavailable_events",
                "writer_slow_events",
                "evidence_accepted_count",
                "evidence_permanent_rejections",
                "payload_too_large_events",
                "heartbeat_count",
            )
        }
        self._backpressure: deque[BackpressureDecision] = deque(
            maxlen=config.diagnostic_capacity
        )
        self._symbol_failures: OrderedDict[str, SymbolFailure] = OrderedDict()
        self._seen_events: OrderedDict[str, str] = OrderedDict()
        self._intents: OrderedDict[int, EvidenceWriteIntent] = OrderedDict()
        self._last_intent_id: str | None = None
        self._sequence = 0
        self._in_flight: QueuedWork | None = None
        self._in_flight_queue: str | None = None
        self._setup_identities: dict[str, str] = {}
        self._plan_identities: dict[str, str] = {}
        self._membership_generations: dict[str, int] = {}
        self._terminal_cycle_ids: OrderedDict[str, str] = OrderedDict()
        self._provider_bound_events: OrderedDict[str, QueuedWork] = OrderedDict()
        self._deferred_readiness: OrderedDict[str, QueuedWork] = OrderedDict()
        self._evidence_rejections: OrderedDict[str, EvidenceRejection] = OrderedDict()
        self._evidence_retry_counts: dict[str, int] = {}
        self._evidence_retry_failure_class: dict[str, str] = {}
        self._evidence_retry_not_before: dict[str, datetime] = {}
        self._last_evidence_payload_bytes = 0
        self._last_evidence_encoded_envelope_bytes = 0
        self._maximum_evidence_encoded_envelope_bytes = 0
        self._evidence_protocol_ceiling_bytes = 0
        self._active_degradations: set[str] = set()
        self._accepting_work = False
        self._stale_lease_takeovers = 0

    def start(self, now: datetime) -> RuntimeHealth:
        if self.process_state not in {STOPPED, FAILED}:
            raise ContinuousRuntimeError("Runtime is already started.")
        lease, stale = self.lease_registry.acquire(
            self.config.runtime_identity,
            self.runtime_instance_id,
            now,
            self.config.lease_ttl_seconds,
        )
        self.process_state = STARTING
        self.lease = lease
        self._stale_lease_takeovers += int(stale)
        self.started_at = now
        self.last_heartbeat_at = now
        self.last_tick_at = now
        self.next_discovery_at = now
        self.next_housekeeping_at = now
        self._accepting_work = True
        self.process_state = READY
        self._checkpoint(now)
        return self.health(now)

    def submit_event(self, event: RuntimeTriggerEvent, now: datetime) -> str:
        if not self._accepting_work or self.process_state in {DRAINING, STOPPED, FAILED}:
            return self._record_backpressure(
                HEALTH_QUEUE,
                event.event_id,
                REJECTED_STALE,
                now,
                event.source_fingerprint or _fingerprint("event", asdict(event)),
            )
        event_fingerprint = _fingerprint("continuous-runtime-event-v1", asdict(event))
        previous = self._seen_events.get(event.event_id)
        if previous is not None:
            if previous != event_fingerprint:
                self._degrade("EVENT_IDENTITY_CONFLICT")
                raise ContinuousRuntimeError("Conflicting duplicate runtime event.")
            return COALESCED_DUPLICATE
        self._remember_event(event.event_id, event_fingerprint)
        if event.trigger == HEARTBEAT_REEVALUATION:
            return self._enqueue(
                HEALTH_QUEUE,
                build_work(
                    kind="HEARTBEAT",
                    key="heartbeat",
                    requested_at=event.occurred_at,
                    priority=event.priority,
                    payload=asdict(event),
                ),
                now,
            )
        symbol = (event.symbol or "").strip().upper()
        return self._enqueue_readiness(
            symbol=symbol,
            trigger=event.trigger,
            requested_at=event.occurred_at,
            source_fingerprint=event.source_fingerprint or event_fingerprint,
            priority=event.priority,
            now=now,
        )

    def request_discovery(self, now: datetime, reason: str = "CADENCE") -> str:
        if not self._accepting_work:
            return self._record_backpressure(
                DISCOVERY_QUEUE,
                "broad-discovery",
                REJECTED_STALE,
                now,
                _fingerprint("discovery-rejected", reason),
            )
        request_id = _fingerprint(
            "continuous-discovery-request-v1",
            {"runtime": self.config.runtime_identity, "requested_at": _timestamp(now), "reason": reason},
        )
        work = build_work(
            kind="DISCOVERY",
            key="broad-discovery",
            requested_at=_timestamp(now),
            priority=100,
            payload={"request_id": request_id, "reason": reason},
        )
        return self._enqueue(DISCOVERY_QUEUE, work, now)

    def set_session_eligibility(self, eligible: bool, now: datetime) -> None:
        """Expose session eligibility to health without inventing strategy state."""

        _timestamp(now)
        self._session_work_eligible = bool(eligible)
        if not eligible:
            self.stalled_since = None
            self.stall_blocker = None
            self._active_degradations.discard(FAILED_FORWARD_PROGRESS)
            if self.pipeline_state == PIPELINE_STALLED:
                self.pipeline_state = (
                    PIPELINE_FORWARD_PROGRESS
                    if self.last_forward_progress_at is not None
                    else PIPELINE_INITIALIZING
                )

    def release_deferred_readiness(self, now: datetime) -> int:
        """Prospectively requeue retained premarket candidates at regular open."""

        _timestamp(now)
        released = 0
        for symbol, deferred in tuple(self._deferred_readiness.items()):
            rollover_fingerprint = _fingerprint(
                "continuous-regular-session-rollover-v1",
                {
                    "symbol": symbol,
                    "deferred_work": deferred.fingerprint,
                    "released_at": _timestamp(now),
                },
            )
            decision = self._enqueue_readiness(
                symbol=symbol,
                trigger=REGULAR_SESSION_ROLLOVER,
                requested_at=_timestamp(now),
                source_fingerprint=rollover_fingerprint,
                priority=deferred.priority,
                now=now,
            )
            if decision not in {REJECTED_CAPACITY, REJECTED_STALE}:
                del self._deferred_readiness[symbol]
                released += 1
        return released

    def tick(
        self,
        now: datetime,
        *,
        work_budget: int = 256,
        discovery_cadence_seconds: float | None = None,
    ) -> RuntimeHealth:
        if self.process_state not in {READY, RUNNING, DEGRADED}:
            raise ContinuousRuntimeError("Runtime is not available for ticking.")
        _positive(work_budget, "Work budget")
        if self.lease is None:
            raise RuntimeLeaseError("Runtime has no logical lease.")
        self.last_tick_at = now
        self._session_work_eligible = True
        self._resolved_discovery_cadence_seconds = (
            self.config.cadence.broad_discovery_seconds
            if discovery_cadence_seconds is None
            else discovery_cadence_seconds
        )
        self.lease = self.lease_registry.heartbeat(
            self.lease, now, self.config.lease_ttl_seconds
        )
        self._schedule_due_work(
            now,
            discovery_cadence_seconds=discovery_cadence_seconds,
        )
        for event in self.event_source.poll(now):
            self.submit_event(event, now)
        self._flush_provider_bound_cycle(now)

        processed = 0
        while processed < work_budget:
            queue_name = self._next_queue_with_work()
            if queue_name is None:
                break
            if queue_name == EVIDENCE_QUEUE:
                made_progress = self._process_evidence(now)
            else:
                made_progress = self._process_one(queue_name, now)
            processed += 1
            if not made_progress and queue_name == EVIDENCE_QUEUE:
                break
        self._apply_forward_progress_watchdog(now)
        if self.process_state != FAILED:
            self.process_state = DEGRADED if self._active_degradations else RUNNING
        self._checkpoint(now)
        return self.health(now)

    def crash_with_in_flight(self, queue_name: str, now: datetime) -> None:
        if queue_name not in {DISCOVERY_QUEUE, READINESS_QUEUE, COMPOSITION_QUEUE, HEALTH_QUEUE}:
            raise ContinuousRuntimeError("Crash injection queue is unsupported.")
        work = self._queues[queue_name].pop()
        if work is None:
            raise ContinuousRuntimeError("Crash injection requires queued work.")
        self._in_flight = work
        self._in_flight_queue = queue_name
        self.process_state = FAILED
        self._accepting_work = False
        self._checkpoint(now)
        # Abrupt termination intentionally does not release the logical lease.

    def shutdown(self, now: datetime, *, work_budget: int = 4096) -> RuntimeHealth:
        if self.process_state in {STOPPED, FAILED}:
            return self.health(now)
        self.process_state = DRAINING
        self._accepting_work = False
        deadline = now + timedelta(seconds=self.config.shutdown_timeout_seconds)
        processed = 0
        while self.pending_work and processed < work_budget and now <= deadline:
            queue_name = self._next_queue_with_work()
            if queue_name is None:
                break
            if queue_name == EVIDENCE_QUEUE:
                progress = self._process_evidence(now)
                if not progress:
                    break
            else:
                self._process_one(queue_name, now)
            processed += 1
        if self.pending_work:
            self._degrade("DRAIN_TIMEOUT")
        self.process_state = STOPPED
        self.last_heartbeat_at = now
        self._checkpoint(now)
        if self.lease is not None:
            self.lease_registry.release(self.lease)
        return self.health(now)

    @classmethod
    def restore(
        cls,
        *,
        config: ContinuousRuntimeConfig,
        runtime_instance_id: str,
        now: datetime,
        discovery_source: DiscoverySource,
        market_data_source: CanonicalMarketDataSource,
        event_source: EventSource,
        composition_source: CompositionSource,
        denominator_source: DenominatorSource,
        writer: EvidenceIntentWriter,
        lease_registry: LogicalRuntimeLeaseRegistry,
        checkpoint_store: RuntimeCheckpointStore,
    ) -> "ContinuousOpportunityRuntime":
        payload = checkpoint_store.load(config.runtime_identity)
        if payload.get("contract_version") != CONTRACT_VERSION:
            raise RuntimeCheckpointError("Checkpoint contract version is incompatible.")
        checkpoint_schema = int(payload.get("checkpoint_schema_version", 1))
        if checkpoint_schema not in {1, CHECKPOINT_SCHEMA_VERSION}:
            raise RuntimeCheckpointError("Checkpoint schema version is incompatible.")
        if payload.get("config_fingerprint") != config.fingerprint:
            raise RuntimeCheckpointError("Checkpoint configuration identity changed.")
        runtime = cls(
            config=config,
            runtime_instance_id=runtime_instance_id,
            discovery_source=discovery_source,
            market_data_source=market_data_source,
            event_source=event_source,
            composition_source=composition_source,
            denominator_source=denominator_source,
            writer=writer,
            lease_registry=lease_registry,
            checkpoint_store=checkpoint_store,
        )
        runtime.lease, stale = lease_registry.acquire(
            config.runtime_identity,
            runtime_instance_id,
            now,
            config.lease_ttl_seconds,
        )
        runtime._stale_lease_takeovers = int(stale)
        runtime.started_at = _parse_timestamp(str(payload["started_at"]))
        runtime.last_heartbeat_at = _parse_timestamp(str(payload["last_heartbeat_at"]))
        runtime.last_tick_at = _optional_checkpoint_timestamp(payload, "last_tick_at")
        runtime.last_discovery_started_at = _optional_checkpoint_timestamp(
            payload, "last_discovery_started_at"
        )
        runtime.last_discovery_completed_at = _optional_checkpoint_timestamp(
            payload, "last_discovery_completed_at"
        )
        runtime.last_readiness_completed_at = _optional_checkpoint_timestamp(
            payload, "last_readiness_completed_at"
        )
        runtime.last_composition_completed_at = _optional_checkpoint_timestamp(
            payload, "last_composition_completed_at"
        )
        runtime.last_denominator_completed_at = _optional_checkpoint_timestamp(
            payload, "last_denominator_completed_at"
        )
        runtime.last_evidence_accepted_at = _optional_checkpoint_timestamp(
            payload, "last_evidence_accepted_at"
        )
        runtime.last_forward_progress_at = _optional_checkpoint_timestamp(
            payload, "last_forward_progress_at"
        )
        runtime.stalled_since = _optional_checkpoint_timestamp(payload, "stalled_since")
        runtime.pipeline_state = str(
            payload.get("pipeline_state", PIPELINE_INITIALIZING)
        )
        runtime.stall_blocker = (
            str(payload["stall_blocker"])
            if payload.get("stall_blocker") is not None
            else None
        )
        runtime._resolved_discovery_cadence_seconds = float(
            payload.get(
                "resolved_discovery_cadence_seconds",
                config.cadence.broad_discovery_seconds,
            )
        )
        runtime._session_work_eligible = bool(
            payload.get("session_work_eligible", False)
        )
        runtime.next_discovery_at = _parse_timestamp(str(payload["next_discovery_at"]))
        runtime.next_housekeeping_at = _parse_timestamp(str(payload["next_housekeeping_at"]))
        if payload.get("last_successful_discovery_at"):
            runtime.last_successful_discovery_at = _parse_timestamp(
                str(payload["last_successful_discovery_at"])
            )
        if payload.get("last_successful_composition_at"):
            runtime.last_successful_composition_at = _parse_timestamp(
                str(payload["last_successful_composition_at"])
            )
        for key, value in dict(payload["counters"]).items():
            if key in runtime._counters:
                runtime._counters[key] = int(value)
        runtime._counters["restart_count"] += 1
        for item in payload.get("backpressure", []):
            runtime._backpressure.append(BackpressureDecision(**item))
        runtime._symbol_failures = OrderedDict(
            (item["symbol"], SymbolFailure(**item)) for item in payload.get("symbol_failures", [])
        )
        runtime._seen_events = OrderedDict(payload.get("seen_events", []))
        runtime._intents = OrderedDict(
            (int(item["sequence"]), EvidenceWriteIntent(**item))
            for item in payload.get("intents", [])
        )
        runtime._sequence = int(payload.get("sequence", 0))
        runtime._last_intent_id = payload.get("last_intent_id")
        runtime._evidence_rejections = OrderedDict(
            (item["failed_intent_id"], EvidenceRejection(**item))
            for item in payload.get("evidence_rejections", [])
        )
        runtime._evidence_retry_counts = {
            str(key): int(value)
            for key, value in dict(payload.get("evidence_retry_counts", {})).items()
        }
        runtime._evidence_retry_failure_class = {
            str(key): str(value)
            for key, value in dict(
                payload.get("evidence_retry_failure_class", {})
            ).items()
        }
        runtime._evidence_retry_not_before = {
            str(key): _parse_timestamp(str(value), "Evidence retry timestamp")
            for key, value in dict(
                payload.get("evidence_retry_not_before", {})
            ).items()
        }
        runtime._last_evidence_payload_bytes = int(
            payload.get("last_evidence_payload_bytes", 0)
        )
        runtime._last_evidence_encoded_envelope_bytes = int(
            payload.get("last_evidence_encoded_envelope_bytes", 0)
        )
        runtime._maximum_evidence_encoded_envelope_bytes = int(
            payload.get("maximum_evidence_encoded_envelope_bytes", 0)
        )
        runtime._evidence_protocol_ceiling_bytes = int(
            payload.get("evidence_protocol_ceiling_bytes", 0)
        )
        runtime._deferred_readiness = OrderedDict(
            (item["key"], QueuedWork(**item))
            for item in payload.get("deferred_readiness", [])
        )
        runtime._setup_identities = {
            str(key): str(value) for key, value in dict(payload.get("setup_identities", {})).items()
        }
        runtime._plan_identities = {
            str(key): str(value) for key, value in dict(payload.get("plan_identities", {})).items()
        }
        runtime._membership_generations = {
            str(key): int(value)
            for key, value in dict(payload.get("membership_generations", {})).items()
        }
        runtime._terminal_cycle_ids = OrderedDict(payload.get("terminal_cycle_ids", []))
        runtime._provider_bound_events = OrderedDict(
            (item["key"], QueuedWork(**item))
            for item in payload.get("provider_bound_events", [])
        )
        if len(runtime._provider_bound_events) > config.maximum_tracked_symbols:
            raise RuntimeCheckpointError("Provider-bound checkpoint state exceeds its bound.")
        runtime._active_degradations = set(payload.get("active_degradations", []))
        for name, items in dict(payload["queues"]).items():
            if name not in runtime._queues or not isinstance(items, list):
                raise RuntimeCheckpointError("Checkpoint queue topology changed.")
            for item in items:
                work = QueuedWork(**item)
                if name == EVIDENCE_QUEUE:
                    runtime._restore_evidence_work(
                        work,
                        now,
                        legacy_envelope=checkpoint_schema == 1,
                    )
                else:
                    runtime._queues[name].restore(work)
        in_flight = payload.get("in_flight")
        if isinstance(in_flight, dict):
            queue_name = str(payload.get("in_flight_queue"))
            if queue_name not in runtime._queues:
                raise RuntimeCheckpointError("Checkpoint in-flight queue is invalid.")
            work = QueuedWork(**in_flight)
            if queue_name == EVIDENCE_QUEUE:
                runtime._restore_evidence_work(
                    work,
                    now,
                    legacy_envelope=checkpoint_schema == 1,
                )
            else:
                runtime._queues[queue_name].restore(work)
        runtime._in_flight = None
        runtime._in_flight_queue = None
        runtime._accepting_work = True
        runtime.process_state = DEGRADED if runtime._active_degradations else READY
        runtime._checkpoint(now)
        return runtime

    def admit_evidence_intent(self, intent: EvidenceWriteIntent, now: datetime) -> str:
        existing = self._intents.get(intent.sequence)
        if existing is not None:
            if existing == intent:
                return WRITER_DUPLICATE
            self._degrade("EVIDENCE_SEQUENCE_CONFLICT")
            raise RuntimeSequenceError("Conflicting duplicate evidence sequence.")
        validate_evidence_write_intent(intent)
        expected = self._sequence + 1
        if intent.sequence != expected:
            self._record_backpressure(
                EVIDENCE_QUEUE,
                intent.intent_id,
                REJECTED_STALE,
                now,
                intent.fingerprint,
            )
            self._degrade("EVIDENCE_SEQUENCE_GAP")
            raise RuntimeSequenceError("Evidence sequence gap is explicit; no event was invented.")
        if expected > 1 and intent.predecessor_identity != self._last_intent_id:
            self._degrade("EVIDENCE_PREDECESSOR_CONFLICT")
            raise RuntimeSequenceError("Evidence predecessor identity is missing or contradictory.")
        if expected == 1 and intent.predecessor_identity is not None:
            raise RuntimeSequenceError("First evidence intent cannot have a predecessor.")
        if len(self._intents) >= self.config.evidence_history_capacity:
            self._record_backpressure(
                EVIDENCE_QUEUE,
                intent.intent_id,
                REJECTED_CAPACITY,
                now,
                intent.fingerprint,
            )
            self._counters["incomplete_denominator_cycles"] += 1
            self._degrade("EVIDENCE_HISTORY_CAPACITY")
            return REJECTED_CAPACITY
        preflight = self._writer_preflight(intent)
        self._record_preflight(preflight)
        if not preflight.accepted:
            if preflight.failure_class not in PERMANENT_RECORD_WRITER_RESULTS:
                self._degrade(preflight.failure_class or WRITER_UNAVAILABLE)
                return preflight.failure_class or WRITER_UNAVAILABLE
            return self._replace_with_compact_rejection(
                intent,
                preflight,
                now,
                replace_existing=False,
            )
        return self._admit_preflighted_intent(intent, now)

    def _admit_preflighted_intent(
        self, intent: EvidenceWriteIntent, now: datetime
    ) -> str:
        work = build_work(
            kind="EVIDENCE",
            key=str(intent.sequence),
            requested_at=intent.requested_at,
            priority=100,
            payload=asdict(intent),
        )
        decision = self._enqueue(EVIDENCE_QUEUE, work, now)
        if decision in {REJECTED_CAPACITY, REJECTED_STALE}:
            self._counters["incomplete_denominator_cycles"] += 1
            self._degrade("EVIDENCE_QUEUE_CAPACITY")
            return decision
        self._intents[intent.sequence] = intent
        self._sequence = intent.sequence
        self._last_intent_id = intent.intent_id
        return decision

    def _writer_preflight(self, intent: EvidenceWriteIntent) -> WriterPreflight:
        callback = getattr(self.writer, "preflight_intent", None)
        if callback is None:
            payload_bytes = len((intent.payload_json or "").encode("utf-8"))
            return WriterPreflight(
                accepted=True,
                payload_bytes=payload_bytes,
                encoded_envelope_bytes=payload_bytes,
                protocol_ceiling_bytes=2**31 - 1,
            )
        result = callback(intent)
        if not isinstance(result, WriterPreflight):
            raise ContinuousRuntimeError("Writer preflight returned an invalid result.")
        return result

    def _record_preflight(self, preflight: WriterPreflight) -> None:
        self._last_evidence_payload_bytes = preflight.payload_bytes
        self._last_evidence_encoded_envelope_bytes = preflight.encoded_envelope_bytes
        self._maximum_evidence_encoded_envelope_bytes = max(
            self._maximum_evidence_encoded_envelope_bytes,
            preflight.encoded_envelope_bytes,
        )
        self._evidence_protocol_ceiling_bytes = preflight.protocol_ceiling_bytes

    def _replace_with_compact_rejection(
        self,
        intent: EvidenceWriteIntent,
        preflight: WriterPreflight,
        now: datetime,
        *,
        replace_existing: bool,
    ) -> str:
        if preflight.failure_class not in PERMANENT_RECORD_WRITER_RESULTS:
            raise ContinuousRuntimeError("Writer failure is not record-terminal.")
        failure_payload = {
            "payloadType": "EVIDENCE_REJECTED_PERMANENT",
            "failedIntentId": intent.intent_id,
            "failedRecordIdentity": intent.record_identity,
            "failedRecordFingerprint": intent.record_fingerprint,
            "payloadFingerprint": intent.payload_fingerprint,
            "payloadBytes": preflight.payload_bytes,
            "encodedEnvelopeBytes": preflight.encoded_envelope_bytes,
            "protocolCeilingBytes": preflight.protocol_ceiling_bytes,
            "retryCount": self._evidence_retry_counts.get(
                intent.intent_id,
                int(self._counters["writer_unavailable_events"]),
            ),
            "failureClass": preflight.failure_class,
            "sourceCycle": intent.record_identity,
            "knownAt": intent.requested_at,
            "authority": RESEARCH_AUTHORITY,
            "executionAuthority": EXECUTION_AUTHORITY_NONE,
            "orderCapability": ORDER_CAPABILITY_UNAVAILABLE,
        }
        failure_fingerprint = _fingerprint(
            "continuous-evidence-rejection-record-v1", failure_payload
        )
        compact = build_evidence_write_intent(
            runtime_instance_id=intent.runtime_instance_id,
            sequence=intent.sequence,
            evidence_type="SYSTEM_FAILURE",
            record_identity=f"evidence-rejection-{failure_fingerprint[:24]}",
            record_fingerprint=failure_fingerprint,
            predecessor_identity=intent.predecessor_identity,
            requested_at=intent.requested_at,
            payload_fingerprint=_fingerprint(
                "continuous-evidence-payload-v1", failure_payload
            ),
            payload=failure_payload,
        )
        compact_preflight = self._writer_preflight(compact)
        self._record_preflight(compact_preflight)
        if not compact_preflight.accepted:
            raise ContinuousRuntimeError(
                "Compact evidence-rejection record failed writer preflight."
            )
        rejection_values = {
            "failed_intent_id": intent.intent_id,
            "failed_record_identity": intent.record_identity,
            "failed_record_fingerprint": intent.record_fingerprint,
            "payload_fingerprint": intent.payload_fingerprint,
            "payload_bytes": preflight.payload_bytes,
            "encoded_envelope_bytes": preflight.encoded_envelope_bytes,
            "protocol_ceiling_bytes": preflight.protocol_ceiling_bytes,
            "retry_count": self._evidence_retry_counts.get(
                intent.intent_id,
                int(self._counters["writer_unavailable_events"]),
            ),
            "failure_class": preflight.failure_class,
            "source_cycle": intent.record_identity,
            "known_at": intent.requested_at,
            "compact_intent_id": compact.intent_id,
        }
        rejection = EvidenceRejection(
            **rejection_values,
            fingerprint=_fingerprint(
                "continuous-evidence-rejection-v1", rejection_values
            ),
        )
        if replace_existing:
            if intent.sequence != self._sequence or self._last_intent_id != intent.intent_id:
                raise RuntimeCheckpointError(
                    "A terminal poison record is not the checkpoint lineage head."
                )
            self._intents[intent.sequence] = compact
            self._last_intent_id = compact.intent_id
        else:
            self._intents[intent.sequence] = compact
            self._sequence = intent.sequence
            self._last_intent_id = compact.intent_id
        self._evidence_rejections[intent.intent_id] = rejection
        self._trim_ordered(
            self._evidence_rejections, self.config.evidence_history_capacity
        )
        self._counters["evidence_permanent_rejections"] += 1
        if preflight.failure_class == PAYLOAD_TOO_LARGE:
            self._counters["payload_too_large_events"] += 1
        self._evidence_retry_counts.pop(intent.intent_id, None)
        self._evidence_retry_failure_class.pop(intent.intent_id, None)
        self._evidence_retry_not_before.pop(intent.intent_id, None)
        work = build_work(
            kind="EVIDENCE",
            key=str(compact.sequence),
            requested_at=compact.requested_at,
            priority=100,
            payload=asdict(compact),
        )
        decision = self._enqueue(EVIDENCE_QUEUE, work, now)
        if decision in {REJECTED_CAPACITY, REJECTED_STALE}:
            raise ContinuousRuntimeError(
                "Compact evidence-rejection record could not enter the queue."
            )
        self._degrade("EVIDENCE_REJECTED_PERMANENT")
        return EVIDENCE_REJECTED_PERMANENT

    def _restore_evidence_work(
        self,
        work: QueuedWork,
        now: datetime,
        *,
        legacy_envelope: bool,
    ) -> None:
        intent = EvidenceWriteIntent(**work.payload)
        legacy_callback = getattr(self.writer, "preflight_legacy_intent", None)
        preflight = (
            legacy_callback(intent)
            if legacy_envelope and legacy_callback is not None
            else self._writer_preflight(intent)
        )
        if not isinstance(preflight, WriterPreflight):
            raise RuntimeCheckpointError(
                "Legacy evidence preflight returned an invalid result."
            )
        self._record_preflight(preflight)
        if preflight.accepted:
            self._queues[EVIDENCE_QUEUE].restore(work)
            return
        if preflight.failure_class not in PERMANENT_RECORD_WRITER_RESULTS:
            self._queues[EVIDENCE_QUEUE].restore(work)
            return
        self._replace_with_compact_rejection(
            intent,
            preflight,
            now,
            replace_existing=True,
        )
        self._active_degradations.discard("WRITER_UNAVAILABLE")
        self._active_degradations.discard("WRITER_SLOW")

    @property
    def pending_work(self) -> int:
        return sum(len(queue) for queue in self._queues.values()) + int(self._in_flight is not None)

    @property
    def backpressure_decisions(self) -> tuple[BackpressureDecision, ...]:
        return tuple(self._backpressure)

    @property
    def symbol_failures(self) -> tuple[SymbolFailure, ...]:
        return tuple(self._symbol_failures.values())

    @property
    def evidence_intents(self) -> tuple[EvidenceWriteIntent, ...]:
        return tuple(self._intents.values())

    @property
    def evidence_rejections(self) -> tuple[EvidenceRejection, ...]:
        return tuple(self._evidence_rejections.values())

    @property
    def deferred_readiness_symbols(self) -> tuple[str, ...]:
        return tuple(self._deferred_readiness)

    def queue_metrics(self, now: datetime) -> dict[str, QueueMetrics]:
        return {name: queue.metrics(now) for name, queue in self._queues.items()}

    def health(self, now: datetime) -> RuntimeHealth:
        started = self.started_at or now
        heartbeat = self.last_heartbeat_at or started
        flags = []
        if self.process_state in {STARTING, READY, RUNNING, DEGRADED, DRAINING}:
            flags.append(PROCESS_ALIVE)
        if self.last_successful_discovery_at is None or (
            now - self.last_successful_discovery_at
        ).total_seconds() > self.config.cadence.discovery_stale_seconds:
            flags.append(DISCOVERY_STALE)
        if self.last_successful_composition_at is None or (
            now - self.last_successful_composition_at
        ).total_seconds() > self.config.cadence.composition_stale_seconds:
            flags.append(COMPOSITION_STALE)
        if any(reason.startswith("DENOMINATOR_") for reason in self._active_degradations):
            flags.append(DENOMINATOR_DEGRADED)
        if FAILED_FORWARD_PROGRESS in self._active_degradations:
            flags.append(FAILED_FORWARD_PROGRESS)
        metrics = self.queue_metrics(now)
        active_queue = self._next_queue_with_work()
        queue_head = (
            self._queues[active_queue].peek() if active_queue is not None else None
        )
        queue_head_failure_class = None
        queue_head_retry_count = 0
        if active_queue == EVIDENCE_QUEUE and queue_head is not None:
            queued_intent = EvidenceWriteIntent(**queue_head.payload)
            queue_head_failure_class = self._evidence_retry_failure_class.get(
                queued_intent.intent_id
            )
            queue_head_retry_count = self._evidence_retry_counts.get(
                queued_intent.intent_id, 0
            )
        stall_threshold = self._stall_threshold_seconds()
        lease_id = self.lease.runtime_lease_id if self.lease else "NONE"
        payload = {
            "contract_version": CONTRACT_VERSION,
            "runtime_profile": RUNTIME_PROFILE,
            "runtime_instance_id": self.runtime_instance_id,
            "runtime_lease_id": lease_id,
            "process_state": self.process_state,
            "health_flags": tuple(flags),
            "started_at": _timestamp(started),
            "last_heartbeat_at": _timestamp(heartbeat),
            "uptime_seconds": max(0.0, (now - started).total_seconds()),
            **self._counters,
            "queue_depths": tuple((name, metrics[name].current_depth) for name in QUEUE_NAMES),
            "queue_high_water_marks": tuple(
                (name, metrics[name].high_water_mark) for name in QUEUE_NAMES
            ),
            "last_successful_discovery_at": (
                _timestamp(self.last_successful_discovery_at)
                if self.last_successful_discovery_at
                else None
            ),
            "last_successful_composition_at": (
                _timestamp(self.last_successful_composition_at)
                if self.last_successful_composition_at
                else None
            ),
            "last_tick_at": (
                _timestamp(self.last_tick_at) if self.last_tick_at else None
            ),
            "last_discovery_started_at": (
                _timestamp(self.last_discovery_started_at)
                if self.last_discovery_started_at
                else None
            ),
            "last_discovery_completed_at": (
                _timestamp(self.last_discovery_completed_at)
                if self.last_discovery_completed_at
                else None
            ),
            "last_readiness_completed_at": (
                _timestamp(self.last_readiness_completed_at)
                if self.last_readiness_completed_at
                else None
            ),
            "last_composition_completed_at": (
                _timestamp(self.last_composition_completed_at)
                if self.last_composition_completed_at
                else None
            ),
            "last_denominator_completed_at": (
                _timestamp(self.last_denominator_completed_at)
                if self.last_denominator_completed_at
                else None
            ),
            "last_evidence_accepted_at": (
                _timestamp(self.last_evidence_accepted_at)
                if self.last_evidence_accepted_at
                else None
            ),
            "active_queue": active_queue,
            "queue_head_age_seconds": (
                metrics[active_queue].oldest_age_seconds
                if active_queue is not None
                else 0.0
            ),
            "queue_head_retry_count": queue_head_retry_count,
            "queue_head_failure_class": queue_head_failure_class,
            "last_forward_progress_at": (
                _timestamp(self.last_forward_progress_at)
                if self.last_forward_progress_at
                else None
            ),
            "stalled_since": (
                _timestamp(self.stalled_since) if self.stalled_since else None
            ),
            "pipeline_state": self.pipeline_state,
            "stall_blocker": self.stall_blocker,
            "stall_threshold_seconds": stall_threshold,
            "last_evidence_payload_bytes": self._last_evidence_payload_bytes,
            "last_evidence_encoded_envelope_bytes": (
                self._last_evidence_encoded_envelope_bytes
            ),
            "maximum_evidence_encoded_envelope_bytes": (
                self._maximum_evidence_encoded_envelope_bytes
            ),
            "evidence_protocol_ceiling_bytes": (
                self._evidence_protocol_ceiling_bytes
            ),
        }
        return RuntimeHealth(
            **payload,
            fingerprint=_fingerprint("continuous-runtime-health-v1", payload),
        )

    def _schedule_due_work(
        self,
        now: datetime,
        *,
        discovery_cadence_seconds: float | None = None,
    ) -> None:
        discovery_cadence = (
            self.config.cadence.broad_discovery_seconds
            if discovery_cadence_seconds is None
            else discovery_cadence_seconds
        )
        _positive(discovery_cadence, "Resolved broad-discovery cadence")
        if self.next_discovery_at is not None and now >= self.next_discovery_at:
            self.request_discovery(now)
            while self.next_discovery_at <= now:
                self.next_discovery_at += timedelta(
                    seconds=discovery_cadence
                )
        if self.next_housekeeping_at is not None and now >= self.next_housekeeping_at:
            heartbeat = RuntimeTriggerEvent(
                event_id=_fingerprint(
                    "continuous-heartbeat-event-v1",
                    {"runtime": self.config.runtime_identity, "at": _timestamp(now)},
                ),
                trigger=HEARTBEAT_REEVALUATION,
                occurred_at=_timestamp(now),
                priority=100,
            )
            self.submit_event(heartbeat, now)
            while self.next_housekeeping_at <= now:
                self.next_housekeeping_at += timedelta(
                    seconds=self.config.cadence.housekeeping_seconds
                )

    def _next_queue_with_work(self) -> str | None:
        for name in (
            HEALTH_QUEUE,
            EVIDENCE_QUEUE,
            DISCOVERY_QUEUE,
            READINESS_QUEUE,
            COMPOSITION_QUEUE,
        ):
            if len(self._queues[name]):
                return name
        return None

    def _process_one(self, queue_name: str, now: datetime) -> bool:
        work = self._queues[queue_name].pop()
        if work is None:
            return False
        self._in_flight = work
        self._in_flight_queue = queue_name
        try:
            if queue_name == DISCOVERY_QUEUE:
                self._process_discovery(work, now)
            elif queue_name == READINESS_QUEUE:
                self._process_readiness(work, now)
            elif queue_name == COMPOSITION_QUEUE:
                self._process_composition(work, now)
            elif queue_name == HEALTH_QUEUE:
                self.last_heartbeat_at = now
                self._counters["heartbeat_count"] += 1
        finally:
            self._in_flight = None
            self._in_flight_queue = None
        return True

    def _process_discovery(self, work: QueuedWork, now: datetime) -> None:
        payload = work.payload
        request = DiscoveryRequest(
            request_id=str(payload["request_id"]),
            requested_at=work.requested_at,
            reason=str(payload["reason"]),
        )
        self._counters["discovery_pulses_attempted"] += 1
        self.last_discovery_started_at = now
        try:
            pulse = self.discovery_source.discover(request)
        except Exception as exc:
            self._counters["discovery_failures"] += 1
            self.last_discovery_completed_at = now
            self._degrade("DISCOVERY_FAILURE")
            self._record_system_failure("DISCOVERY", type(exc).__name__, now, work.fingerprint)
            return
        if len(set(pulse.symbols_for_readiness)) > self.config.maximum_tracked_symbols:
            self._counters["discovery_failures"] += 1
            self.last_discovery_completed_at = now
            self._degrade("DISCOVERY_MAXIMUM_TRACKED_SYMBOLS")
            self._record_system_failure("DISCOVERY", "MAXIMUM_TRACKED_SYMBOLS_EXCEEDED", now, pulse.fingerprint)
            return
        self._counters["discovery_pulses_completed"] += 1
        self._active_degradations.discard("DISCOVERY_FAILURE")
        self._active_degradations.discard("DISCOVERY_MAXIMUM_TRACKED_SYMBOLS")
        self._counters["source_rows_represented"] = pulse.source_rows_represented
        self._counters["new_symbols"] = len(pulse.new_symbols)
        self._counters["retained_symbols"] = len(pulse.retained_symbols)
        self._counters["provider_bound_symbols"] = len(pulse.provider_bound_symbols)
        self.last_successful_discovery_at = now
        self.last_discovery_completed_at = now
        self._mark_forward_progress(now)
        source_evidence = (
            json.loads(pulse.evidence_payload_json)
            if pulse.evidence_payload_json is not None
            else None
        )
        discovery_payload = {
            "payloadType": "DISCOVERY_CYCLE",
            "request": asdict(request),
            "pulse": {
                key: value
                for key, value in asdict(pulse).items()
                if key != "evidence_payload_json"
            },
            "sourceEvidence": source_evidence,
            "knownAt": _timestamp(now),
            "authority": RESEARCH_AUTHORITY,
            "executionAuthority": EXECUTION_AUTHORITY_NONE,
        }
        evidence_decision = self._emit_intent(
            evidence_type="DISCOVERY_CYCLE",
            record_identity=pulse.pulse_id,
            record_fingerprint=_fingerprint(
                "continuous-discovery-cycle-record-v1", discovery_payload
            ),
            payload_fingerprint=pulse.fingerprint,
            payload=discovery_payload,
            now=now,
        )
        if evidence_decision == EVIDENCE_REJECTED_PERMANENT:
            return
        for symbol in pulse.symbols_for_readiness:
            normalized = symbol.strip().upper()
            self._membership_generations.setdefault(normalized, 1)
            self._enqueue_readiness(
                symbol=normalized,
                trigger=MEMBER_PROMOTED,
                requested_at=_timestamp(now),
                source_fingerprint=pulse.fingerprint,
                priority=60,
                now=now,
            )

    def _process_readiness(self, work: QueuedWork, now: datetime) -> None:
        payload = work.payload
        request = ReadinessRequest(
            request_id=str(payload["request_id"]),
            symbol=str(payload["symbol"]),
            trigger=str(payload["trigger"]),
            requested_at=work.requested_at,
            source_fingerprint=str(payload["source_fingerprint"]),
        )
        self._counters["readiness_requests"] += 1
        try:
            result = self.market_data_source.evaluate(request)
        except Exception as exc:
            self._record_symbol_failure(request.symbol, "READINESS", type(exc).__name__, now, work.fingerprint)
            self._counters["readiness_failures"] += 1
            self._counters["readiness_completed"] += 1
            self.last_readiness_completed_at = now
            self._mark_forward_progress(now)
            return
        self._counters["readiness_completed"] += 1
        self.last_readiness_completed_at = now
        self._mark_forward_progress(now)
        if result.request_id != request.request_id or result.symbol != request.symbol:
            self._record_symbol_failure(
                request.symbol,
                "READINESS",
                "ADAPTER_IDENTITY_MISMATCH",
                now,
                result.fingerprint,
            )
            self._counters["readiness_failures"] += 1
            return
        if result.deferred:
            self._deferred_readiness[request.symbol] = work
            self._deferred_readiness.move_to_end(request.symbol)
            self._trim_ordered(
                self._deferred_readiness, self.config.maximum_tracked_symbols
            )
            self._counters["readiness_deferred"] += 1
            self._emit_intent(
                evidence_type="READINESS_DEFERRED",
                record_identity=(
                    f"readiness-deferred-{result.fingerprint[:24]}"
                ),
                record_fingerprint=result.fingerprint,
                payload_fingerprint=result.fingerprint,
                payload={
                    "payloadType": "READINESS_DEFERRED",
                    "request": asdict(request),
                    "result": asdict(result),
                    "knownAt": _timestamp(now),
                    "authority": RESEARCH_AUTHORITY,
                    "executionAuthority": EXECUTION_AUTHORITY_NONE,
                    "orderCapability": ORDER_CAPABILITY_UNAVAILABLE,
                },
                now=now,
            )
            return
        if not result.ready:
            self._record_symbol_failure(
                request.symbol,
                "READINESS",
                result.failure_reason or result.status,
                now,
                result.fingerprint,
            )
            self._counters["readiness_failures"] += 1
            return
        self._counters["ready_members"] += 1
        self._deferred_readiness.pop(request.symbol, None)
        composition_id = _fingerprint(
            "continuous-composition-request-v1",
            {"readiness": result.fingerprint, "trigger": request.trigger},
        )
        self._enqueue(
            COMPOSITION_QUEUE,
            build_work(
                kind="COMPOSITION",
                key=request.symbol,
                requested_at=_timestamp(now),
                priority=work.priority,
                payload={
                    "request_id": composition_id,
                    "symbol": request.symbol,
                    "trigger": request.trigger,
                    "readiness_fingerprint": result.fingerprint,
                },
            ),
            now,
        )

    def _process_composition(self, work: QueuedWork, now: datetime) -> None:
        payload = work.payload
        request = CompositionRequest(
            request_id=str(payload["request_id"]),
            symbol=str(payload["symbol"]),
            trigger=str(payload["trigger"]),
            requested_at=work.requested_at,
            readiness_fingerprint=str(payload["readiness_fingerprint"]),
        )
        try:
            result = self.composition_source.compose(request)
        except Exception as exc:
            self._record_symbol_failure(request.symbol, "COMPOSITION", type(exc).__name__, now, work.fingerprint)
            return
        if result.request_id != request.request_id or result.symbol != request.symbol:
            self._record_symbol_failure(
                request.symbol,
                "COMPOSITION",
                "ADAPTER_IDENTITY_MISMATCH",
                now,
                result.fingerprint,
            )
            return
        prior_cycle = self._terminal_cycle_ids.get(result.cycle_id)
        if prior_cycle is not None:
            if prior_cycle != result.fingerprint:
                self._degrade("COMPOSITION_CYCLE_CONFLICT")
                raise ContinuousRuntimeError("Composition cycle identity changed fingerprint.")
            return
        self._terminal_cycle_ids[result.cycle_id] = result.fingerprint
        self._trim_ordered(self._terminal_cycle_ids, self.config.processed_event_capacity)
        self._counters["composition_cycles"] += 1
        self._counters["lifecycle_transitions"] += result.lifecycle_transitions
        if result.setup_id:
            is_new_setup = result.setup_id not in self._setup_identities
            if is_new_setup and len(self._setup_identities) >= self.config.processed_event_capacity:
                self._degrade("SETUP_IDENTITY_CAPACITY")
                raise ContinuousRuntimeError("Setup identity history reached its configured bound.")
            prior = self._setup_identities.setdefault(result.setup_id, request.symbol)
            if prior != request.symbol:
                raise ContinuousRuntimeError("Setup identity changed symbols.")
            self._counters["setups_created"] += int(is_new_setup)
        if result.plan_id:
            is_new_plan = result.plan_id not in self._plan_identities
            if is_new_plan and len(self._plan_identities) >= self.config.processed_event_capacity:
                self._degrade("PLAN_IDENTITY_CAPACITY")
                raise ContinuousRuntimeError("Plan identity history reached its configured bound.")
            prior = self._plan_identities.setdefault(result.plan_id, request.symbol)
            if prior != request.symbol:
                raise ContinuousRuntimeError("Plan identity changed symbols.")
            self._counters["plans_created"] += int(is_new_plan)
        self.last_successful_composition_at = now
        self.last_composition_completed_at = now
        self._mark_forward_progress(now)
        if result.evidence_payload_json is not None:
            evidence_payload = json.loads(result.evidence_payload_json)
        else:
            result_payload = asdict(result)
            result_payload.pop("evidence_payload_json", None)
            evidence_payload = {
                "payloadType": "COMPOSITION_CYCLE",
                "request": asdict(request),
                "result": result_payload,
                "knownAt": _timestamp(now),
                "authority": RESEARCH_AUTHORITY,
                "executionAuthority": EXECUTION_AUTHORITY_NONE,
            }
        evidence_decision = self._emit_intent(
            evidence_type="COMPOSITION_CYCLE",
            record_identity=result.cycle_id,
            record_fingerprint=result.fingerprint,
            payload_fingerprint=result.fingerprint,
            payload=evidence_payload,
            now=now,
        )
        if evidence_decision == EVIDENCE_REJECTED_PERMANENT:
            return
        denominator_request = DenominatorRequest(
            request_id=_fingerprint("denominator-request", asdict(result)),
            symbol=result.symbol,
            requested_at=_timestamp(now),
            composition_cycle_id=result.cycle_id,
            composition_fingerprint=result.fingerprint,
        )
        try:
            denominator = self.denominator_source.produce(denominator_request)
        except Exception as exc:
            self._counters["incomplete_denominator_cycles"] += 1
            self._degrade("DENOMINATOR_FAILURE")
            self._record_system_failure("DENOMINATOR", type(exc).__name__, now, result.fingerprint)
            return
        self._counters["denominator_cycles"] += 1
        self.last_denominator_completed_at = now
        self._mark_forward_progress(now)
        if not denominator.complete:
            self._counters["incomplete_denominator_cycles"] += 1
            self._degrade("DENOMINATOR_INCOMPLETE")
        self._emit_intent(
            evidence_type="OPPORTUNITY_DENOMINATOR",
            record_identity=denominator.cycle_id,
            record_fingerprint=denominator.fingerprint,
            payload_fingerprint=denominator.fingerprint,
            payload={
                "payloadType": "OPPORTUNITY_DENOMINATOR",
                "request": asdict(denominator_request),
                "result": asdict(denominator),
                "knownAt": _timestamp(now),
                "authority": RESEARCH_AUTHORITY,
                "executionAuthority": EXECUTION_AUTHORITY_NONE,
            },
            now=now,
        )

    def _emit_intent(
        self,
        *,
        evidence_type: str,
        record_identity: str,
        record_fingerprint: str,
        payload_fingerprint: str,
        payload: Mapping[str, Any] | None = None,
        now: datetime,
    ) -> str:
        if payload is not None:
            payload_fingerprint = _fingerprint("continuous-evidence-payload-v1", dict(payload))
        intent = build_evidence_write_intent(
            runtime_instance_id=self.runtime_instance_id,
            sequence=self._sequence + 1,
            evidence_type=evidence_type,
            record_identity=record_identity,
            record_fingerprint=record_fingerprint,
            predecessor_identity=self._last_intent_id,
            requested_at=_timestamp(now),
            payload_fingerprint=payload_fingerprint,
            payload=payload,
        )
        return self.admit_evidence_intent(intent, now)

    def _flush_provider_bound_cycle(self, now: datetime) -> None:
        if not self._provider_bound_events:
            return
        works = tuple(self._provider_bound_events.values())
        symbols = tuple(sorted(self._provider_bound_events))
        source_fingerprint = _fingerprint(
            "provider-bound-runtime-batch-v1",
            {"symbols": symbols, "work": [item.fingerprint for item in works]},
        )
        cycle_id = f"provider-bound-{source_fingerprint[:24]}"
        request = DenominatorRequest(
            request_id=_fingerprint("provider-bound-denominator-request-v1", source_fingerprint),
            symbol="__PROVIDER_BOUND_BATCH__",
            requested_at=_timestamp(now),
            composition_cycle_id=cycle_id,
            composition_fingerprint=source_fingerprint,
            provider_bound_symbols=symbols,
        )
        try:
            denominator = self.denominator_source.produce(request)
        except Exception as exc:
            self._counters["incomplete_denominator_cycles"] += 1
            self._degrade("DENOMINATOR_PROVIDER_BOUND_FAILURE")
            self._record_system_failure(
                "DENOMINATOR_PROVIDER_BOUND", type(exc).__name__, now, source_fingerprint
            )
            return
        if denominator.opportunity_count != len(symbols):
            self._counters["incomplete_denominator_cycles"] += 1
            self._degrade("DENOMINATOR_PROVIDER_BOUND_COUNT_MISMATCH")
            self._record_system_failure(
                "DENOMINATOR_PROVIDER_BOUND",
                "OPPORTUNITY_COUNT_MISMATCH",
                now,
                denominator.fingerprint,
            )
            return
        self._counters["denominator_cycles"] += 1
        self._counters["provider_bound_denominator_cycles"] += 1
        if not denominator.complete:
            self._counters["incomplete_denominator_cycles"] += 1
            self._degrade("DENOMINATOR_PROVIDER_BOUND_INCOMPLETE")
        decision = self._emit_intent(
            evidence_type="PROVIDER_BOUND_DENOMINATOR_ROWS",
            record_identity=denominator.cycle_id,
            record_fingerprint=denominator.fingerprint,
            payload_fingerprint=source_fingerprint,
            payload={
                "payloadType": "PROVIDER_BOUND_DENOMINATOR_ROWS",
                "request": asdict(request),
                "result": asdict(denominator),
                "knownAt": _timestamp(now),
                "authority": RESEARCH_AUTHORITY,
                "executionAuthority": EXECUTION_AUTHORITY_NONE,
            },
            now=now,
        )
        if decision not in {REJECTED_CAPACITY, REJECTED_STALE}:
            self._provider_bound_events.clear()

    def _process_evidence(self, now: datetime) -> bool:
        work = self._queues[EVIDENCE_QUEUE].peek()
        if work is None:
            return False
        intent = EvidenceWriteIntent(**work.payload)
        retry_at = self._evidence_retry_not_before.get(intent.intent_id)
        if retry_at is not None and now < retry_at:
            return False
        raw_result = self.writer.write_intent(intent)
        if isinstance(raw_result, WriterWriteResult):
            result = raw_result
        else:
            legacy_status = {
                "UNAVAILABLE": WRITER_UNAVAILABLE,
                "SLOW": WRITER_SLOW,
            }.get(str(raw_result), str(raw_result))
            result = WriterWriteResult(status=legacy_status)
        if result.status not in WRITER_RESULTS:
            raise ContinuousRuntimeError("Writer returned an unsupported result.")
        if result.status in TRANSIENT_WRITER_RESULTS:
            retries = self._evidence_retry_counts.get(intent.intent_id, 0) + 1
            self._evidence_retry_counts[intent.intent_id] = retries
            self._evidence_retry_failure_class[intent.intent_id] = result.status
            delay_seconds = min(60.0, 5.0 * (2 ** min(retries - 1, 4)))
            self._evidence_retry_not_before[intent.intent_id] = now + timedelta(
                seconds=delay_seconds
            )
        if result.status == WRITER_UNAVAILABLE:
            self._counters["writer_unavailable_events"] += 1
            self._degrade(WRITER_UNAVAILABLE)
            return False
        if result.status == WRITER_SLOW:
            self._counters["writer_slow_events"] += 1
            self._degrade(WRITER_SLOW)
            return False
        if result.status == WRITE_FAILED:
            self._degrade(WRITE_FAILED)
            return False
        if result.status in PERMANENT_RECORD_WRITER_RESULTS:
            preflight = WriterPreflight(
                accepted=False,
                payload_bytes=result.payload_bytes,
                encoded_envelope_bytes=result.encoded_envelope_bytes,
                protocol_ceiling_bytes=(
                    result.protocol_ceiling_bytes or 524_288
                ),
                failure_class=result.status,
            )
            self._replace_with_compact_rejection(
                intent,
                preflight,
                now,
                replace_existing=True,
            )
            return True
        if result.status in {IPC_AUTH_REJECTED, WRITER_OWNER_CONFLICT}:
            retries = self._evidence_retry_counts.get(intent.intent_id, 0) + 1
            self._evidence_retry_counts[intent.intent_id] = retries
            self._evidence_retry_failure_class[intent.intent_id] = result.status
            self._evidence_retry_not_before[intent.intent_id] = now + timedelta(
                seconds=60
            )
            self._degrade(result.status)
            return False
        self._queues[EVIDENCE_QUEUE].pop()
        self._evidence_retry_counts.pop(intent.intent_id, None)
        self._evidence_retry_failure_class.pop(intent.intent_id, None)
        self._evidence_retry_not_before.pop(intent.intent_id, None)
        for recovered in (
            WRITER_UNAVAILABLE,
            WRITER_SLOW,
            WRITE_FAILED,
            EVIDENCE_REJECTED_PERMANENT,
        ):
            self._active_degradations.discard(recovered)
        self._counters["evidence_accepted_count"] += 1
        self.last_evidence_accepted_at = now
        self._mark_forward_progress(now)
        return True

    def _enqueue_readiness(
        self,
        *,
        symbol: str,
        trigger: str,
        requested_at: str,
        source_fingerprint: str,
        priority: int,
        now: datetime,
    ) -> str:
        request_id = _fingerprint(
            "continuous-readiness-request-v1",
            {
                "symbol": symbol,
                "trigger": trigger,
                "requested_at": requested_at,
                "source_fingerprint": source_fingerprint,
            },
        )
        return self._enqueue(
            READINESS_QUEUE,
            build_work(
                kind="READINESS",
                key=symbol,
                requested_at=requested_at,
                priority=priority,
                payload={
                    "request_id": request_id,
                    "symbol": symbol,
                    "trigger": trigger,
                    "source_fingerprint": source_fingerprint,
                },
            ),
            now,
        )

    def _enqueue(self, queue_name: str, work: QueuedWork, now: datetime) -> str:
        decision, displaced = self._queues[queue_name].enqueue(work, now)
        if queue_name == READINESS_QUEUE:
            if decision == REJECTED_CAPACITY:
                self._provider_bound_events[work.key] = work
            elif decision == EVICTED_LOWER_PRIORITY and displaced is not None:
                self._provider_bound_events[displaced.key] = displaced
            self._trim_ordered(
                self._provider_bound_events, self.config.maximum_tracked_symbols
            )
        if decision != ENQUEUED:
            self._record_backpressure(
                queue_name,
                work.key,
                decision,
                now,
                work.fingerprint,
                displaced.key if displaced else None,
            )
        return decision

    def _record_backpressure(
        self,
        queue_name: str,
        work_key: str,
        decision: str,
        now: datetime,
        source_fingerprint: str,
        displaced_key: str | None = None,
    ) -> str:
        payload = {
            "queue_name": queue_name,
            "work_key": work_key,
            "decision": decision,
            "decided_at": _timestamp(now),
            "displaced_key": displaced_key,
            "source_fingerprint": source_fingerprint,
        }
        self._backpressure.append(
            BackpressureDecision(
                **payload,
                fingerprint=_fingerprint("continuous-backpressure-v1", payload),
            )
        )
        self._counters["backpressure_events"] += 1
        if decision in {REJECTED_CAPACITY, EVICTED_LOWER_PRIORITY} and queue_name != READINESS_QUEUE:
            self._degrade("QUEUE_SATURATION")
        return decision

    def _record_symbol_failure(
        self,
        symbol: str,
        stage: str,
        reason: str,
        now: datetime,
        source_fingerprint: str,
    ) -> None:
        self._symbol_failures[symbol] = SymbolFailure(
            symbol=symbol,
            stage=stage,
            reason=reason,
            observed_at=_timestamp(now),
            source_fingerprint=source_fingerprint,
        )
        self._symbol_failures.move_to_end(symbol)
        self._trim_ordered(self._symbol_failures, self.config.maximum_tracked_symbols)

    def _record_system_failure(
        self, stage: str, reason: str, now: datetime, source_fingerprint: str
    ) -> None:
        self._record_symbol_failure(
            "__SYSTEM__", stage, reason, now, source_fingerprint
        )
        payload = {
            "payloadType": "SYSTEM_FAILURE",
            "stage": stage,
            "reason": reason,
            "sourceFingerprint": source_fingerprint,
            "knownAt": _timestamp(now),
            "authority": RESEARCH_AUTHORITY,
            "executionAuthority": EXECUTION_AUTHORITY_NONE,
        }
        failure_fingerprint = _fingerprint(
            "continuous-system-failure-record-v1", payload
        )
        self._emit_intent(
            evidence_type="SYSTEM_FAILURE",
            record_identity=f"system-failure-{failure_fingerprint[:24]}",
            record_fingerprint=failure_fingerprint,
            payload_fingerprint=source_fingerprint,
            payload=payload,
            now=now,
        )

    def _remember_event(self, event_id: str, fingerprint: str) -> None:
        self._seen_events[event_id] = fingerprint
        self._trim_ordered(self._seen_events, self.config.processed_event_capacity)

    @staticmethod
    def _trim_ordered(values: OrderedDict, capacity: int) -> None:
        while len(values) > capacity:
            values.popitem(last=False)

    def _degrade(self, reason: str) -> None:
        self._active_degradations.add(reason)
        if self.process_state not in {DRAINING, STOPPED, FAILED}:
            self.process_state = DEGRADED

    def _mark_forward_progress(self, now: datetime) -> None:
        self.last_forward_progress_at = now
        self.stalled_since = None
        self.stall_blocker = None
        self.pipeline_state = PIPELINE_FORWARD_PROGRESS
        self._active_degradations.discard(FAILED_FORWARD_PROGRESS)

    def _stall_threshold_seconds(self) -> float:
        return (
            2.0 * self._resolved_discovery_cadence_seconds
            + self.config.cadence.housekeeping_seconds
        )

    def _stall_blocker(self) -> str:
        evidence = self._queues[EVIDENCE_QUEUE].peek()
        if evidence is not None:
            intent = EvidenceWriteIntent(**evidence.payload)
            failure = self._evidence_retry_failure_class.get(intent.intent_id)
            if failure in PERMANENT_RECORD_WRITER_RESULTS:
                return "POISON_EVIDENCE_RECORD"
            if failure in {
                WRITER_UNAVAILABLE,
                WRITER_SLOW,
                WRITE_FAILED,
                IPC_AUTH_REJECTED,
                WRITER_OWNER_CONFLICT,
            }:
                return "WRITER_UNAVAILABLE"
        if any(
            reason.startswith("DISCOVERY_")
            for reason in self._active_degradations
        ):
            return "PROVIDER_UNAVAILABLE"
        if len(self._queues[READINESS_QUEUE]) or self._deferred_readiness:
            return "READINESS_BLOCKED"
        if self.pending_work:
            return "QUEUE_BACKLOG"
        return "UNKNOWN_FORWARD_PROGRESS_FAILURE"

    def _apply_forward_progress_watchdog(self, now: datetime) -> None:
        if not self._session_work_eligible:
            return
        anchor = self.last_forward_progress_at or self.started_at or now
        threshold = self._stall_threshold_seconds()
        if (now - anchor).total_seconds() < threshold:
            return
        if self.stalled_since is None:
            self.stalled_since = now
        self.pipeline_state = PIPELINE_STALLED
        self.stall_blocker = self._stall_blocker()
        self._degrade(FAILED_FORWARD_PROGRESS)

    def _checkpoint(self, now: datetime) -> Path:
        if self.started_at is None or self.last_heartbeat_at is None:
            raise RuntimeCheckpointError("Runtime cannot checkpoint before start.")
        payload = {
            "contract_version": CONTRACT_VERSION,
            "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
            "runtime_profile": RUNTIME_PROFILE,
            "config_fingerprint": self.config.fingerprint,
            "runtime_identity": self.config.runtime_identity,
            "runtime_instance_id": self.runtime_instance_id,
            "process_state": self.process_state,
            "started_at": _timestamp(self.started_at),
            "last_heartbeat_at": _timestamp(self.last_heartbeat_at),
            "last_tick_at": _timestamp(self.last_tick_at) if self.last_tick_at else None,
            "last_discovery_started_at": (
                _timestamp(self.last_discovery_started_at)
                if self.last_discovery_started_at
                else None
            ),
            "last_discovery_completed_at": (
                _timestamp(self.last_discovery_completed_at)
                if self.last_discovery_completed_at
                else None
            ),
            "last_readiness_completed_at": (
                _timestamp(self.last_readiness_completed_at)
                if self.last_readiness_completed_at
                else None
            ),
            "last_composition_completed_at": (
                _timestamp(self.last_composition_completed_at)
                if self.last_composition_completed_at
                else None
            ),
            "last_denominator_completed_at": (
                _timestamp(self.last_denominator_completed_at)
                if self.last_denominator_completed_at
                else None
            ),
            "last_evidence_accepted_at": (
                _timestamp(self.last_evidence_accepted_at)
                if self.last_evidence_accepted_at
                else None
            ),
            "last_forward_progress_at": (
                _timestamp(self.last_forward_progress_at)
                if self.last_forward_progress_at
                else None
            ),
            "stalled_since": _timestamp(self.stalled_since) if self.stalled_since else None,
            "pipeline_state": self.pipeline_state,
            "stall_blocker": self.stall_blocker,
            "resolved_discovery_cadence_seconds": self._resolved_discovery_cadence_seconds,
            "session_work_eligible": self._session_work_eligible,
            "next_discovery_at": _timestamp(self.next_discovery_at or now),
            "next_housekeeping_at": _timestamp(self.next_housekeeping_at or now),
            "last_successful_discovery_at": (
                _timestamp(self.last_successful_discovery_at)
                if self.last_successful_discovery_at
                else None
            ),
            "last_successful_composition_at": (
                _timestamp(self.last_successful_composition_at)
                if self.last_successful_composition_at
                else None
            ),
            "counters": self._counters,
            "queues": {name: queue.snapshot() for name, queue in self._queues.items()},
            "backpressure": [asdict(item) for item in self._backpressure],
            "symbol_failures": [asdict(item) for item in self._symbol_failures.values()],
            "seen_events": list(self._seen_events.items()),
            "intents": [asdict(item) for item in self._intents.values()],
            "sequence": self._sequence,
            "last_intent_id": self._last_intent_id,
            "evidence_rejections": [
                asdict(item) for item in self._evidence_rejections.values()
            ],
            "evidence_retry_counts": self._evidence_retry_counts,
            "evidence_retry_failure_class": self._evidence_retry_failure_class,
            "evidence_retry_not_before": {
                key: _timestamp(value)
                for key, value in self._evidence_retry_not_before.items()
            },
            "last_evidence_payload_bytes": self._last_evidence_payload_bytes,
            "last_evidence_encoded_envelope_bytes": (
                self._last_evidence_encoded_envelope_bytes
            ),
            "maximum_evidence_encoded_envelope_bytes": (
                self._maximum_evidence_encoded_envelope_bytes
            ),
            "evidence_protocol_ceiling_bytes": (
                self._evidence_protocol_ceiling_bytes
            ),
            "deferred_readiness": [
                {"key": key, **asdict(item)}
                for key, item in self._deferred_readiness.items()
            ],
            "setup_identities": self._setup_identities,
            "plan_identities": self._plan_identities,
            "membership_generations": self._membership_generations,
            "terminal_cycle_ids": list(self._terminal_cycle_ids.items()),
            "provider_bound_events": [
                asdict(item) for item in self._provider_bound_events.values()
            ],
            "active_degradations": sorted(self._active_degradations),
            "in_flight": asdict(self._in_flight) if self._in_flight else None,
            "in_flight_queue": self._in_flight_queue,
            "authority": RESEARCH_AUTHORITY,
            "execution_authority": EXECUTION_AUTHORITY_NONE,
            "order_capability": ORDER_CAPABILITY_UNAVAILABLE,
        }
        path = self.checkpoint_store.save(self.config.runtime_identity, payload)
        self._counters["checkpoint_writes"] += 1
        return path


@dataclass(frozen=True)
class RuntimePerformanceObservation:
    simulated_minutes: int
    tracked_symbols: int
    readiness_slots: int
    ticks: int
    elapsed_milliseconds: float
    composition_throughput_per_second: float
    checkpoint_restart_milliseconds: float
    maximum_queue_depth: int
    all_queues_drained: bool
    evidence_intents_reconciled: bool
    denominator_cycles_reconciled: bool
    heartbeat_continuous: bool
    bounded_state: bool


def measure_runtime_operation(
    runtime: ContinuousOpportunityRuntime,
    clock: ManualClock,
    *,
    simulated_minutes: int,
    symbols: Iterable[str],
    work_budget: int = 4096,
) -> RuntimePerformanceObservation:
    """Accelerate a caller-supplied synthetic runtime; never sleeps or contacts a provider."""

    normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
    if not normalized:
        raise ContinuousRuntimeError("Performance proof requires symbols.")
    started = time.perf_counter()
    heartbeats: list[str] = []
    starting_compositions = runtime._counters["composition_cycles"]
    starting_denominators = runtime._counters["denominator_cycles"]
    starting_provider_bound_denominators = runtime._counters[
        "provider_bound_denominator_cycles"
    ]
    for minute in range(simulated_minutes):
        now = clock.now()
        for symbol in normalized:
            source = _fingerprint(
                "synthetic-completed-bar",
                {"symbol": symbol, "minute": minute, "at": _timestamp(now)},
            )
            runtime.submit_event(
                RuntimeTriggerEvent(
                    event_id=_fingerprint("synthetic-bar-event", {"source": source}),
                    trigger=CANONICAL_BAR_COMPLETED,
                    occurred_at=_timestamp(now),
                    symbol=symbol,
                    source_fingerprint=source,
                ),
                now,
            )
        health = runtime.tick(now, work_budget=work_budget)
        heartbeats.append(health.last_heartbeat_at)
        clock.advance(60)
    runtime.tick(clock.now(), work_budget=work_budget)
    elapsed = (time.perf_counter() - started) * 1000.0
    compositions = runtime._counters["composition_cycles"] - starting_compositions
    denominators = runtime._counters["denominator_cycles"] - starting_denominators
    provider_bound_denominators = (
        runtime._counters["provider_bound_denominator_cycles"]
        - starting_provider_bound_denominators
    )
    metrics = runtime.queue_metrics(clock.now())
    checkpoint_started = time.perf_counter()
    runtime.checkpoint_store.load(runtime.config.runtime_identity)
    checkpoint_elapsed = (time.perf_counter() - checkpoint_started) * 1000.0
    return RuntimePerformanceObservation(
        simulated_minutes=simulated_minutes,
        tracked_symbols=len(normalized),
        readiness_slots=min(len(normalized), runtime.config.queues.readiness),
        ticks=simulated_minutes + 1,
        elapsed_milliseconds=elapsed,
        composition_throughput_per_second=(
            compositions / max(elapsed / 1000.0, 0.000001)
        ),
        checkpoint_restart_milliseconds=checkpoint_elapsed,
        maximum_queue_depth=max(item.high_water_mark for item in metrics.values()),
        all_queues_drained=runtime.pending_work == 0,
        evidence_intents_reconciled=all(
            intent.sequence == index
            for index, intent in enumerate(runtime.evidence_intents, start=1)
        ),
        denominator_cycles_reconciled=(
            denominators == compositions + provider_bound_denominators
            and not runtime._provider_bound_events
        ),
        heartbeat_continuous=all(
            _parse_timestamp(right) >= _parse_timestamp(left)
            for left, right in zip(heartbeats, heartbeats[1:])
        ),
        bounded_state=(
            len(runtime._seen_events) <= runtime.config.processed_event_capacity
            and len(runtime._intents) <= runtime.config.evidence_history_capacity
            and len(runtime._backpressure) <= runtime.config.diagnostic_capacity
            and len(runtime._symbol_failures) <= runtime.config.maximum_tracked_symbols
        ),
    )


__all__ = [
    "BackpressureDecision",
    "BoundedWorkQueue",
    "CanonicalMarketDataSource",
    "CompositionRequest",
    "CompositionResult",
    "CompositionSource",
    "ContinuousOpportunityRuntime",
    "ContinuousRuntimeConfig",
    "ContinuousRuntimeError",
    "DenominatorRequest",
    "DenominatorResult",
    "DenominatorSource",
    "DiscoveryPulse",
    "DiscoveryRequest",
    "DiscoverySource",
    "EvidenceIntentWriter",
    "EvidenceWriteIntent",
    "EventSource",
    "LogicalRuntimeLeaseRegistry",
    "ManualClock",
    "QueueCapacities",
    "QueueMetrics",
    "ReadinessRequest",
    "ReadinessResult",
    "RuntimeCadence",
    "RuntimeCheckpointStore",
    "RuntimeHealth",
    "RuntimeLease",
    "RuntimePerformanceObservation",
    "RuntimeTriggerEvent",
    "build_evidence_write_intent",
    "measure_runtime_operation",
    "validate_evidence_write_intent",
]
