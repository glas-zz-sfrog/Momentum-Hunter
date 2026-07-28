from __future__ import annotations

"""Read-only Windows process identity evidence for the canary stop drill."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from typing import Final, Protocol

from momentum_hunter.schwab_canary_stop_evidence import (
    CanaryIndependentProcessObservation,
)


CANARY_PROCESS_OBSERVER_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_PROCESS_OBSERVER_V1"
)
WINDOWS_PROCESS_OBSERVER_SOURCE: Final = "WINDOWS_PROCESS_OBSERVER_V1"
PROCESS_RUNNING: Final = "RUNNING"
PROCESS_NOT_FOUND: Final = "NOT_FOUND"
PROCESS_ACCESS_DENIED: Final = "ACCESS_DENIED"
PROCESS_QUERY_FAILED: Final = "QUERY_FAILED"
PROCESS_UNSUPPORTED: Final = "UNSUPPORTED"
_PROCESS_STATES: Final = frozenset(
    {
        PROCESS_RUNNING,
        PROCESS_NOT_FOUND,
        PROCESS_ACCESS_DENIED,
        PROCESS_QUERY_FAILED,
        PROCESS_UNSUPPORTED,
    }
)
_SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_CREATION_CLOCK_SKEW = timedelta(seconds=2)
_WINDOWS_EPOCH_TICKS = 116_444_736_000_000_000
_TICKS_PER_SECOND = 10_000_000


class CanaryProcessObserverError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessIdentitySnapshot:
    process_id: int
    state: str
    created_at: str | None = None
    executable_path_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_process_id(self.process_id)
        if self.state not in _PROCESS_STATES:
            raise CanaryProcessObserverError(
                "Process identity snapshot state is unsupported."
            )
        if self.state == PROCESS_RUNNING:
            if self.created_at is None:
                raise CanaryProcessObserverError(
                    "A running process snapshot requires creation time."
                )
            _require_aware_timestamp(
                self.created_at,
                field="process creation",
            )
            if (
                self.executable_path_sha256 is None
                or not _SHA256.fullmatch(self.executable_path_sha256)
            ):
                raise CanaryProcessObserverError(
                    "A running process snapshot requires an executable path "
                    "commitment."
                )
        elif (
            self.created_at is not None
            or self.executable_path_sha256 is not None
        ):
            raise CanaryProcessObserverError(
                "A non-running or unavailable snapshot cannot claim process "
                "identity."
            )


class ProcessIdentitySource(Protocol):
    source_id: str

    def inspect(self, process_id: int) -> ProcessIdentitySnapshot:
        ...


@dataclass(frozen=True)
class CanaryProcessTarget:
    observer_id: str
    source: str
    runtime_instance_id: str
    process_id: int
    process_created_at: str
    executable_path_sha256: str
    captured_at: str

    def __post_init__(self) -> None:
        _require_identifier(self.observer_id, field="observer ID")
        _require_identifier(self.source, field="process source")
        _require_identifier(
            self.runtime_instance_id,
            field="runtime instance ID",
        )
        _require_process_id(self.process_id)
        process_created = _require_aware_timestamp(
            self.process_created_at,
            field="target process creation",
        )
        captured = _require_aware_timestamp(
            self.captured_at,
            field="target capture",
        )
        if process_created - captured > _MAX_CREATION_CLOCK_SKEW:
            raise CanaryProcessObserverError(
                "Target process creation time is after target capture."
            )
        if not _SHA256.fullmatch(self.executable_path_sha256):
            raise CanaryProcessObserverError(
                "Target executable path commitment is invalid."
            )

    @property
    def target_sha256(self) -> str:
        return _sha256(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_PROCESS_OBSERVER_SCHEMA_VERSION,
            "recordType": "CANARY_PROCESS_TARGET",
            "observerId": self.observer_id,
            "source": self.source,
            "runtimeInstanceId": self.runtime_instance_id,
            "processId": self.process_id,
            "processCreatedAt": _canonical_timestamp(
                self.process_created_at
            ),
            "executablePathSha256": self.executable_path_sha256,
            "capturedAt": _canonical_timestamp(self.captured_at),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.payload(),
            "targetSha256": self.target_sha256,
            "rawExecutablePathRetained": False,
            "processMutationPerformed": False,
            "credentialMutationPerformed": False,
            "brokerActionAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


@dataclass(frozen=True)
class CanaryProcessLivenessEvidence:
    target_sha256: str
    observer_id: str
    source: str
    runtime_instance_id: str
    process_id: int
    observed_at: str
    observation_state: str
    process_running: bool | None
    pid_reused: bool
    observed_process_created_at: str | None
    observed_executable_path_sha256: str | None
    conclusion: str

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.target_sha256):
            raise CanaryProcessObserverError(
                "Process observation target commitment is invalid."
            )
        _require_identifier(self.observer_id, field="observer ID")
        _require_identifier(self.source, field="process source")
        _require_identifier(
            self.runtime_instance_id,
            field="runtime instance ID",
        )
        _require_process_id(self.process_id)
        _require_aware_timestamp(
            self.observed_at,
            field="process observation",
        )
        if self.observation_state not in _PROCESS_STATES:
            raise CanaryProcessObserverError(
                "Process observation state is unsupported."
            )
        _validate_liveness_conclusion(self)

    @property
    def record_sha256(self) -> str:
        return _sha256(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_PROCESS_OBSERVER_SCHEMA_VERSION,
            "recordType": "CANARY_PROCESS_LIVENESS_EVIDENCE",
            "targetSha256": self.target_sha256,
            "observerId": self.observer_id,
            "source": self.source,
            "runtimeInstanceId": self.runtime_instance_id,
            "processId": self.process_id,
            "observedAt": _canonical_timestamp(self.observed_at),
            "observationState": self.observation_state,
            "processRunning": self.process_running,
            "pidReused": self.pid_reused,
            "observedProcessCreatedAt": (
                _canonical_timestamp(self.observed_process_created_at)
                if self.observed_process_created_at is not None
                else None
            ),
            "observedExecutablePathSha256": (
                self.observed_executable_path_sha256
            ),
            "conclusion": self.conclusion,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.payload(),
            "recordSha256": self.record_sha256,
            "independentObservation": True,
            "rawExecutablePathRetained": False,
            "processMutationPerformed": False,
            "credentialMutationPerformed": False,
            "brokerActionAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def to_stop_observation(
        self,
    ) -> CanaryIndependentProcessObservation:
        if self.process_running is None:
            raise CanaryProcessObserverError(
                "Unavailable process evidence cannot satisfy a stop drill."
            )
        return CanaryIndependentProcessObservation(
            observer_id=self.observer_id,
            source=self.source,
            runtime_instance_id=self.runtime_instance_id,
            observed_at=_canonical_timestamp(self.observed_at),
            process_running=self.process_running,
        )


class WindowsProcessIdentitySource:
    """Query process identity with limited-information rights only."""

    source_id = WINDOWS_PROCESS_OBSERVER_SOURCE

    def inspect(self, process_id: int) -> ProcessIdentitySnapshot:
        _require_process_id(process_id)
        if os.name != "nt":
            return ProcessIdentitySnapshot(
                process_id=process_id,
                state=PROCESS_UNSUPPORTED,
            )
        return _inspect_windows_process(process_id)


def capture_canary_process_target(
    *,
    observer_id: str,
    runtime_instance_id: str,
    process_id: int,
    captured_at: datetime,
    source: ProcessIdentitySource,
) -> CanaryProcessTarget:
    normalized_observer = _require_identifier(
        observer_id,
        field="observer ID",
    )
    normalized_runtime = _require_identifier(
        runtime_instance_id,
        field="runtime instance ID",
    )
    normalized_source = _require_identifier(
        source.source_id,
        field="process source",
    )
    target_process_id = _require_process_id(process_id)
    if target_process_id == os.getpid():
        raise CanaryProcessObserverError(
            "The target runtime cannot be the independent observer process."
        )
    capture_time = _require_aware_datetime(
        captured_at,
        field="target capture",
    )
    snapshot = source.inspect(target_process_id)
    if snapshot.process_id != target_process_id:
        raise CanaryProcessObserverError(
            "Process identity source returned a different process ID."
        )
    if snapshot.state != PROCESS_RUNNING:
        raise CanaryProcessObserverError(
            "A process target can be captured only while it is running."
        )
    return CanaryProcessTarget(
        observer_id=normalized_observer,
        source=normalized_source,
        runtime_instance_id=normalized_runtime,
        process_id=target_process_id,
        process_created_at=str(snapshot.created_at),
        executable_path_sha256=str(snapshot.executable_path_sha256),
        captured_at=capture_time.isoformat(),
    )


def observe_canary_process_target(
    target: CanaryProcessTarget,
    *,
    observed_at: datetime,
    source: ProcessIdentitySource,
) -> CanaryProcessLivenessEvidence:
    observation_time = _require_aware_datetime(
        observed_at,
        field="process observation",
    )
    captured_at = _require_aware_timestamp(
        target.captured_at,
        field="target capture",
    )
    if observation_time < captured_at:
        raise CanaryProcessObserverError(
            "Process observation predates target capture."
        )
    if source.source_id != target.source:
        raise CanaryProcessObserverError(
            "Process observation source does not match the target source."
        )
    if target.process_id == os.getpid():
        raise CanaryProcessObserverError(
            "The target runtime cannot be the independent observer process."
        )
    snapshot = source.inspect(target.process_id)
    if snapshot.process_id != target.process_id:
        raise CanaryProcessObserverError(
            "Process identity source returned a different process ID."
        )
    if snapshot.state == PROCESS_RUNNING:
        same_identity = (
            _canonical_timestamp(str(snapshot.created_at))
            == _canonical_timestamp(target.process_created_at)
            and snapshot.executable_path_sha256
            == target.executable_path_sha256
        )
        process_running = same_identity
        pid_reused = not same_identity
        conclusion = (
            "TARGET_PROCESS_RUNNING"
            if same_identity
            else "TARGET_PROCESS_STOPPED_PID_REUSED"
        )
        observed_created_at = snapshot.created_at
        observed_executable = snapshot.executable_path_sha256
    elif snapshot.state == PROCESS_NOT_FOUND:
        process_running = False
        pid_reused = False
        conclusion = "TARGET_PROCESS_STOPPED"
        observed_created_at = None
        observed_executable = None
    else:
        process_running = None
        pid_reused = False
        conclusion = "PROCESS_LIVENESS_UNAVAILABLE"
        observed_created_at = None
        observed_executable = None
    return CanaryProcessLivenessEvidence(
        target_sha256=target.target_sha256,
        observer_id=target.observer_id,
        source=target.source,
        runtime_instance_id=target.runtime_instance_id,
        process_id=target.process_id,
        observed_at=observation_time.isoformat(),
        observation_state=snapshot.state,
        process_running=process_running,
        pid_reused=pid_reused,
        observed_process_created_at=observed_created_at,
        observed_executable_path_sha256=observed_executable,
        conclusion=conclusion,
    )


def _inspect_windows_process(process_id: int) -> ProcessIdentitySnapshot:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    error_invalid_parameter = 87
    error_not_found = 1168
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(
        process_query_limited_information,
        False,
        process_id,
    )
    if not handle:
        error_code = ctypes.get_last_error()
        if error_code == error_access_denied:
            state = PROCESS_ACCESS_DENIED
        elif error_code in {error_invalid_parameter, error_not_found}:
            state = PROCESS_NOT_FOUND
        else:
            state = PROCESS_QUERY_FAILED
        return ProcessIdentitySnapshot(
            process_id=process_id,
            state=state,
        )
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(
            handle,
            ctypes.byref(exit_code),
        ):
            return ProcessIdentitySnapshot(
                process_id=process_id,
                state=PROCESS_QUERY_FAILED,
            )
        if exit_code.value != still_active:
            return ProcessIdentitySnapshot(
                process_id=process_id,
                state=PROCESS_NOT_FOUND,
            )
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return ProcessIdentitySnapshot(
                process_id=process_id,
                state=PROCESS_QUERY_FAILED,
            )
        size = wintypes.DWORD(32_768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            buffer,
            ctypes.byref(size),
        ):
            return ProcessIdentitySnapshot(
                process_id=process_id,
                state=PROCESS_QUERY_FAILED,
            )
        created_at = _filetime_to_datetime(creation)
        executable_commitment = hashlib.sha256(
            buffer.value.casefold().encode("utf-8")
        ).hexdigest()
        return ProcessIdentitySnapshot(
            process_id=process_id,
            state=PROCESS_RUNNING,
            created_at=created_at.isoformat(),
            executable_path_sha256=executable_commitment,
        )
    finally:
        kernel32.CloseHandle(handle)


def _filetime_to_datetime(value: object) -> datetime:
    low = int(getattr(value, "dwLowDateTime"))
    high = int(getattr(value, "dwHighDateTime"))
    ticks = (high << 32) | low
    unix_seconds = (ticks - _WINDOWS_EPOCH_TICKS) / _TICKS_PER_SECOND
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)


def _validate_liveness_conclusion(
    evidence: CanaryProcessLivenessEvidence,
) -> None:
    running_identity = (
        evidence.observed_process_created_at is not None
        and evidence.observed_executable_path_sha256 is not None
        and _SHA256.fullmatch(
            evidence.observed_executable_path_sha256
        )
        is not None
    )
    if evidence.observation_state == PROCESS_RUNNING:
        if not running_identity:
            raise CanaryProcessObserverError(
                "A running observation requires complete process identity."
            )
        expected_conclusion = (
            "TARGET_PROCESS_RUNNING"
            if evidence.process_running is True
            and evidence.pid_reused is False
            else "TARGET_PROCESS_STOPPED_PID_REUSED"
            if evidence.process_running is False
            and evidence.pid_reused is True
            else None
        )
    elif evidence.observation_state == PROCESS_NOT_FOUND:
        if running_identity:
            raise CanaryProcessObserverError(
                "A missing process observation cannot claim process identity."
            )
        expected_conclusion = (
            "TARGET_PROCESS_STOPPED"
            if evidence.process_running is False
            and evidence.pid_reused is False
            else None
        )
    else:
        if running_identity:
            raise CanaryProcessObserverError(
                "Unavailable process evidence cannot claim process identity."
            )
        expected_conclusion = (
            "PROCESS_LIVENESS_UNAVAILABLE"
            if evidence.process_running is None
            and evidence.pid_reused is False
            else None
        )
    if evidence.conclusion != expected_conclusion:
        raise CanaryProcessObserverError(
            "Process liveness conclusion contradicts its evidence."
        )


def _require_identifier(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not _SIMPLE_IDENTIFIER.fullmatch(normalized):
        raise CanaryProcessObserverError(f"{field} is invalid.")
    return normalized


def _require_process_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CanaryProcessObserverError(
            "Process ID must be a positive integer."
        )
    return value


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CanaryProcessObserverError(
            f"{field} time must be timezone-aware."
        )
    return value.astimezone(timezone.utc)


def _require_aware_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanaryProcessObserverError(
            f"{field} time is invalid."
        ) from exc
    return _require_aware_datetime(parsed, field=field)


def _canonical_timestamp(value: str) -> str:
    return _require_aware_timestamp(
        value,
        field="evidence",
    ).isoformat()


def _sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
