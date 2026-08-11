"""Dormant writer-session composition for continuous runtime evidence.

The session binds one validated Engine Host claim to one process-lifetime OS
lease and composes that authority with source-admission persistence. It does not
select a root, start a host, discover data, call a provider, or create an order.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from momentum_hunter.event_runtime_topology import (
    APPEND,
    PYTHON_ENGINE_HOST,
    RUNTIME_SOURCE_ADMISSION_LEDGER,
    EventRuntimeTopology,
    EventRuntimeTopologyError,
    RuntimeWriterClaim,
    artifact_path,
    authorize_runtime_artifact_access,
    validate_event_runtime_topology,
    validate_runtime_writer_claim,
)
from momentum_hunter.event_source_admission import (
    RuntimeSourceAdmission,
    RuntimeSourceAdmissionError,
    RuntimeSourceAdmissionStore,
)
from momentum_hunter.path_transaction import (
    PathTransactionLease,
    PathTransactionLeaseError,
    PathTransactionLeaseTimeoutError,
)


SESSION_NEW = "NEW"
SESSION_ACTIVE = "ACTIVE"
SESSION_CLOSED = "CLOSED"
WRITER_SESSION_TARGET_NAME = "runtime-writer-session"

_ACTIVE_SESSIONS_GUARD = threading.Lock()
_ACTIVE_SESSIONS: dict[Path, str] = {}


class RuntimeWriterSessionError(RuntimeError):
    """Raised when runtime writer ownership is absent or contradictory."""


class RuntimeSourceAdmissionWriterSession:
    """Hold sole writer ownership while appending admitted runtime sources."""

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
        self.writer_claim = writer_claim
        self.current_host_instance_id = str(current_host_instance_id).strip()
        self.source_admission_path = artifact_path(
            topology,
            RUNTIME_SOURCE_ADMISSION_LEDGER,
        )
        target = writer_session_target_path(topology)
        try:
            self._writer_lease = PathTransactionLease(
                target,
                timeout_seconds=lease_timeout_seconds,
            )
        except PathTransactionLeaseError as exc:
            raise RuntimeWriterSessionError(
                "Runtime writer-session lease timeout must be positive and finite."
            ) from exc
        try:
            self._source_store = RuntimeSourceAdmissionStore(
                self.source_admission_path,
                evidence_program_id=topology.evidence_program_id,
                configuration_fingerprint=topology.configuration_fingerprint,
                lease_timeout_seconds=lease_timeout_seconds,
            )
        except RuntimeSourceAdmissionError as exc:
            raise RuntimeWriterSessionError(
                "Runtime source-admission store could not be configured."
            ) from exc
        self.writer_lease_path = self._writer_lease.lease_path
        self._state = SESSION_NEW
        self._owner_process_id = 0
        self._state_lock = threading.RLock()

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @contextmanager
    def activate(self) -> Iterator[RuntimeSourceAdmissionWriterSession]:
        """Hold sole writer ownership until the Engine Host session closes."""

        self._validate_current_identity()
        with self._state_lock:
            if self._state != SESSION_NEW:
                raise RuntimeWriterSessionError(
                    "A runtime writer session is single-use and already started."
                )
        try:
            with self._writer_lease.transaction():
                with self._state_lock:
                    if self._state != SESSION_NEW:
                        raise RuntimeWriterSessionError(
                            "A runtime writer session is single-use and already started."
                        )
                registry_key = self._writer_lease.resolved_target_path
                registered = False
                with _ACTIVE_SESSIONS_GUARD:
                    if registry_key in _ACTIVE_SESSIONS:
                        raise RuntimeWriterSessionError(
                            "Another local runtime writer session is already active."
                        )
                    _ACTIVE_SESSIONS[registry_key] = self.writer_claim.fingerprint
                    registered = True
                with self._state_lock:
                    self._state = SESSION_ACTIVE
                    self._owner_process_id = os.getpid()
                try:
                    yield self
                finally:
                    with self._state_lock:
                        self._state = SESSION_CLOSED
                        self._owner_process_id = 0
                    if registered:
                        with _ACTIVE_SESSIONS_GUARD:
                            if (
                                _ACTIVE_SESSIONS.get(registry_key)
                                == self.writer_claim.fingerprint
                            ):
                                _ACTIVE_SESSIONS.pop(registry_key, None)
        except PathTransactionLeaseTimeoutError as exc:
            raise RuntimeWriterSessionError(
                "Runtime writer-session lease timed out."
            ) from exc

    def append_source_admission(
        self,
        admission: RuntimeSourceAdmission,
    ) -> RuntimeSourceAdmission:
        """Append under the same current claim and lifetime writer lease."""

        with self._state_lock:
            if self._state != SESSION_ACTIVE:
                raise RuntimeWriterSessionError(
                    "Runtime source admission requires an active writer session."
                )
            if self._owner_process_id != os.getpid():
                raise RuntimeWriterSessionError(
                    "Runtime writer session belongs to a different process."
                )
            self._validate_current_identity()
            if (
                admission.configuration_fingerprint
                != self.topology.configuration_fingerprint
            ):
                raise RuntimeWriterSessionError(
                    "Runtime source admission belongs to a different configuration."
                )
            registry_key = self._writer_lease.resolved_target_path
            with _ACTIVE_SESSIONS_GUARD:
                if (
                    _ACTIVE_SESSIONS.get(registry_key)
                    != self.writer_claim.fingerprint
                ):
                    raise RuntimeWriterSessionError(
                        "Runtime writer-session ownership is no longer current."
                    )
            access = authorize_runtime_artifact_access(
                self.topology,
                artifact_name=RUNTIME_SOURCE_ADMISSION_LEDGER,
                operation=APPEND,
                process_role=PYTHON_ENGINE_HOST,
                writer_claim=self.writer_claim,
                current_host_instance_id=self.current_host_instance_id,
                current_process_id=os.getpid(),
            )
            if not access.allowed:
                raise RuntimeWriterSessionError(
                    f"Runtime source-admission append was denied: {access.reason}."
                )
            expected_path = artifact_path(
                self.topology,
                RUNTIME_SOURCE_ADMISSION_LEDGER,
            )
            if self.source_admission_path.resolve() != expected_path.resolve():
                raise RuntimeWriterSessionError(
                    "Runtime source-admission store escaped the topology path."
                )
            return self._source_store.append(admission)

    def _validate_current_identity(self) -> None:
        try:
            validate_event_runtime_topology(self.topology)
            validate_runtime_writer_claim(self.writer_claim, self.topology)
        except (EventRuntimeTopologyError, TypeError, ValueError) as exc:
            raise RuntimeWriterSessionError(
                "Runtime writer claim or topology is invalid."
            ) from exc
        if self.writer_claim.process_role != PYTHON_ENGINE_HOST:
            raise RuntimeWriterSessionError(
                "Runtime writer session requires the Python Engine Host role."
            )
        if self.writer_claim.process_id != os.getpid():
            raise RuntimeWriterSessionError(
                "Runtime writer claim does not match the current process."
            )
        if (
            not self.current_host_instance_id
            or self.current_host_instance_id != self.writer_claim.host_instance_id
        ):
            raise RuntimeWriterSessionError(
                "Runtime writer claim does not match the current host instance."
            )


def writer_session_target_path(topology: EventRuntimeTopology) -> Path:
    """Return the non-artifact lease target without creating it."""

    validate_event_runtime_topology(topology)
    namespace_root = Path(topology.root_path) / topology.namespace
    target = namespace_root / WRITER_SESSION_TARGET_NAME
    if not target.is_relative_to(namespace_root):
        raise RuntimeWriterSessionError(
            "Runtime writer-session target escaped the topology namespace."
        )
    return target
