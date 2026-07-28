from __future__ import annotations

"""Bounded, nontransmitting lifecycle shell for a future canary worker."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Final, Protocol, Sequence

from momentum_hunter.schwab_canary_process_evidence import (
    CanaryProcessEvidenceStore,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    RUNTIME_STOPPED,
    CanaryRuntimeStopAcknowledgement,
    CanaryStopRequest,
    CanaryStopLatchStore,
)
from momentum_hunter.schwab_canary_worker_identity import (
    CanaryWorkerIdentityReceipt,
    CanaryWorkerIdentityStore,
    build_canary_worker_identity_receipt,
)


CANARY_BROKER_WORKER_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_BROKER_WORKER_V1"
)
WORKER_LAUNCH_FILENAME: Final = "worker-launch.json"
WORKER_BUILD_MANIFEST_FILENAME: Final = "worker-build-manifest.json"
WORKER_IDENTITY_FILENAME: Final = "worker-identity.json"
WORKER_STOP_LATCH_FILENAME: Final = "stop-latch.json"
WORKER_STOP_ACK_FILENAME: Final = "stop-acknowledgement.json"
WORKER_PROCESS_EVIDENCE_DIRECTORY: Final = "process-evidence"

WORKER_STOPPED_ACKNOWLEDGED: Final = "STOPPED_ACKNOWLEDGED"
WORKER_PRESTART_STOPPED: Final = "PRESTART_STOPPED_ACKNOWLEDGED"
WORKER_STARTUP_TIMEOUT: Final = "STARTUP_TIMEOUT"
WORKER_RUNTIME_TIMEOUT: Final = "RUNTIME_TIMEOUT"

_MAX_LAUNCH_BYTES: Final = 32_768
_MAX_ACK_BYTES: Final = 32_768
_MAX_BUILD_MANIFEST_BYTES: Final = 1_048_576
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LAUNCH_KEYS: Final = frozenset(
    {
        "schemaVersion",
        "recordType",
        "runtimeInstanceId",
        "accountBindingCommitment",
        "expectedWorkerBuildSha256",
        "expectedWorkerArtifactSha256",
        "pollIntervalMilliseconds",
        "startupTimeoutSeconds",
        "maximumRuntimeSeconds",
        "executionEnabled",
        "providerAccessAllowed",
        "credentialAccessAllowed",
        "brokerActionAllowed",
        "retryAllowed",
        "transmitting",
        "orderTransmission",
    }
)
_ACK_KEYS: Final = frozenset(
    {
        "schemaVersion",
        "recordType",
        "latchSha256",
        "runtimeInstanceId",
        "accountBindingCommitment",
        "acknowledgedAt",
        "state",
        "executionDisabled",
        "outstandingCommandCount",
        "workerIdentityReceiptSha256",
        "processTargetSha256",
        "acknowledgementSha256",
        "oneWay",
        "replaceSupported",
        "clearSupported",
        "providerEvidence",
        "processMutationPerformed",
        "credentialAccessed",
        "credentialMutationPerformed",
        "brokerActionAllowed",
        "executionPermit",
        "realOrderApproval",
        "retryAllowed",
        "transmitting",
        "orderTransmission",
    }
)


class CanaryBrokerWorkerError(RuntimeError):
    pass


class CanaryBrokerWorkerConflict(CanaryBrokerWorkerError):
    pass


class WorkerClock(Protocol):
    def now(self) -> datetime:
        ...

    def monotonic(self) -> float:
        ...

    def sleep(self, seconds: float) -> None:
        ...


class SystemWorkerClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class CanaryBrokerWorkerLaunchContract:
    runtime_instance_id: str
    account_binding_commitment: str
    expected_worker_build_sha256: str
    expected_worker_artifact_sha256: str
    poll_interval_milliseconds: int = 50
    startup_timeout_seconds: float = 30.0
    maximum_runtime_seconds: float = 300.0

    def __post_init__(self) -> None:
        _require_identifier(
            self.runtime_instance_id,
            field="runtime instance ID",
        )
        _require_sha256(
            self.account_binding_commitment,
            field="account binding",
        )
        _require_sha256(
            self.expected_worker_build_sha256,
            field="worker build",
        )
        _require_sha256(
            self.expected_worker_artifact_sha256,
            field="worker artifact",
        )
        if (
            isinstance(self.poll_interval_milliseconds, bool)
            or not isinstance(self.poll_interval_milliseconds, int)
            or self.poll_interval_milliseconds < 10
            or self.poll_interval_milliseconds > 1_000
        ):
            raise CanaryBrokerWorkerError(
                "Worker poll interval must be from 10 to 1000 milliseconds."
            )
        _require_finite_range(
            self.startup_timeout_seconds,
            field="startup timeout",
            minimum=0.1,
            maximum=300.0,
        )
        _require_finite_range(
            self.maximum_runtime_seconds,
            field="maximum runtime",
            minimum=0.1,
            maximum=3_600.0,
        )
        if self.maximum_runtime_seconds < self.startup_timeout_seconds:
            raise CanaryBrokerWorkerError(
                "Maximum runtime cannot be shorter than startup timeout."
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_BROKER_WORKER_SCHEMA_VERSION,
            "recordType": "CANARY_BROKER_WORKER_LAUNCH",
            "runtimeInstanceId": self.runtime_instance_id,
            "accountBindingCommitment": (
                self.account_binding_commitment
            ),
            "expectedWorkerBuildSha256": (
                self.expected_worker_build_sha256
            ),
            "expectedWorkerArtifactSha256": (
                self.expected_worker_artifact_sha256
            ),
            "pollIntervalMilliseconds": (
                self.poll_interval_milliseconds
            ),
            "startupTimeoutSeconds": self.startup_timeout_seconds,
            "maximumRuntimeSeconds": self.maximum_runtime_seconds,
            "executionEnabled": False,
            "providerAccessAllowed": False,
            "credentialAccessAllowed": False,
            "brokerActionAllowed": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


class CanaryBrokerWorkerLaunchStore:
    """Write one immutable local launch contract."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = Path(run_root)
        self.path = self.run_root / WORKER_LAUNCH_FILENAME

    def persist(
        self,
        contract: CanaryBrokerWorkerLaunchContract,
    ) -> CanaryBrokerWorkerLaunchContract:
        _prepare_run_root(self.run_root, create=True)
        return _persist_one_way(
            path=self.path,
            value=contract,
            payload=contract.to_dict(),
            maximum=_MAX_LAUNCH_BYTES,
            loader=self.load,
            conflict_message=(
                "A different or invalid worker launch contract exists."
            ),
        )

    def load(self) -> CanaryBrokerWorkerLaunchContract | None:
        _prepare_run_root(self.run_root, create=False)
        payload = _load_json_object(
            self.path,
            label="Worker launch contract",
            maximum=_MAX_LAUNCH_BYTES,
        )
        if payload is None:
            return None
        if set(payload) != _LAUNCH_KEYS:
            raise CanaryBrokerWorkerError(
                "Worker launch contract fields are invalid."
            )
        if (
            payload["schemaVersion"]
            != CANARY_BROKER_WORKER_SCHEMA_VERSION
            or payload["recordType"]
            != "CANARY_BROKER_WORKER_LAUNCH"
            or payload["executionEnabled"] is not False
            or payload["providerAccessAllowed"] is not False
            or payload["credentialAccessAllowed"] is not False
            or payload["brokerActionAllowed"] is not False
            or payload["retryAllowed"] is not False
            or payload["transmitting"] is not False
            or payload["orderTransmission"] != "UNAVAILABLE"
        ):
            raise CanaryBrokerWorkerError(
                "Worker launch contract safety metadata is invalid."
            )
        try:
            contract = CanaryBrokerWorkerLaunchContract(
                runtime_instance_id=_require_string(
                    payload["runtimeInstanceId"],
                    field="runtimeInstanceId",
                ),
                account_binding_commitment=_require_string(
                    payload["accountBindingCommitment"],
                    field="accountBindingCommitment",
                ),
                expected_worker_build_sha256=_require_string(
                    payload["expectedWorkerBuildSha256"],
                    field="expectedWorkerBuildSha256",
                ),
                expected_worker_artifact_sha256=_require_string(
                    payload["expectedWorkerArtifactSha256"],
                    field="expectedWorkerArtifactSha256",
                ),
                poll_interval_milliseconds=_require_int(
                    payload["pollIntervalMilliseconds"],
                    field="pollIntervalMilliseconds",
                ),
                startup_timeout_seconds=_require_number(
                    payload["startupTimeoutSeconds"],
                    field="startupTimeoutSeconds",
                ),
                maximum_runtime_seconds=_require_number(
                    payload["maximumRuntimeSeconds"],
                    field="maximumRuntimeSeconds",
                ),
            )
        except CanaryBrokerWorkerError:
            raise
        except (TypeError, ValueError) as exc:
            raise CanaryBrokerWorkerError(
                "Worker launch contract content is invalid."
            ) from exc
        if payload != contract.to_dict():
            raise CanaryBrokerWorkerError(
                "Worker launch contract is not canonical."
            )
        return contract


@dataclass(frozen=True, repr=False)
class CanaryWorkerStopAcknowledgementRecord:
    latch_sha256: str
    runtime_instance_id: str
    account_binding_commitment: str
    acknowledged_at: str
    worker_identity_receipt_sha256: str | None
    process_target_sha256: str | None
    state: str = RUNTIME_STOPPED
    execution_disabled: bool = True
    outstanding_command_count: int = 0

    def __post_init__(self) -> None:
        _require_sha256(self.latch_sha256, field="stop latch")
        _require_identifier(
            self.runtime_instance_id,
            field="runtime instance ID",
        )
        _require_sha256(
            self.account_binding_commitment,
            field="account binding",
        )
        _require_timestamp(
            self.acknowledged_at,
            field="stop acknowledgement",
        )
        for value, field in (
            (
                self.worker_identity_receipt_sha256,
                "worker identity receipt",
            ),
            (self.process_target_sha256, "process target"),
        ):
            if value is not None:
                _require_sha256(value, field=field)
        if (
            (self.worker_identity_receipt_sha256 is None)
            != (self.process_target_sha256 is None)
        ):
            raise CanaryBrokerWorkerError(
                "Worker identity and process target must be present together."
            )
        if (
            self.state != RUNTIME_STOPPED
            or self.execution_disabled is not True
            or isinstance(self.outstanding_command_count, bool)
            or not isinstance(self.outstanding_command_count, int)
            or self.outstanding_command_count != 0
        ):
            raise CanaryBrokerWorkerError(
                "Worker stop acknowledgement is not fail-closed."
            )

    @property
    def acknowledgement_sha256(self) -> str:
        return _sha256(self._unsigned_payload())

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_BROKER_WORKER_SCHEMA_VERSION,
            "recordType": "CANARY_BROKER_WORKER_STOP_ACKNOWLEDGEMENT",
            "latchSha256": self.latch_sha256,
            "runtimeInstanceId": self.runtime_instance_id,
            "accountBindingCommitment": (
                self.account_binding_commitment
            ),
            "acknowledgedAt": _canonical_timestamp(self.acknowledged_at),
            "state": self.state,
            "executionDisabled": self.execution_disabled,
            "outstandingCommandCount": self.outstanding_command_count,
            "workerIdentityReceiptSha256": (
                self.worker_identity_receipt_sha256
            ),
            "processTargetSha256": self.process_target_sha256,
            "oneWay": True,
            "replaceSupported": False,
            "clearSupported": False,
            "providerEvidence": False,
            "processMutationPerformed": False,
            "credentialAccessed": False,
            "credentialMutationPerformed": False,
            "brokerActionAllowed": False,
            "executionPermit": False,
            "realOrderApproval": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._unsigned_payload(),
            "acknowledgementSha256": self.acknowledgement_sha256,
        }

    def to_stop_acknowledgement(
        self,
    ) -> CanaryRuntimeStopAcknowledgement:
        return CanaryRuntimeStopAcknowledgement(
            latch_sha256=self.latch_sha256,
            runtime_instance_id=self.runtime_instance_id,
            account_binding_commitment=self.account_binding_commitment,
            acknowledged_at=_canonical_timestamp(self.acknowledged_at),
            state=self.state,
            execution_disabled=self.execution_disabled,
            outstanding_command_count=self.outstanding_command_count,
        )

    def __repr__(self) -> str:
        return (
            "CanaryWorkerStopAcknowledgementRecord("
            f"acknowledgement_sha256={self.acknowledgement_sha256!r}, "
            f"runtime_instance_id={self.runtime_instance_id!r}, "
            f"identity_bound={self.worker_identity_receipt_sha256 is not None})"
        )


class CanaryWorkerStopAcknowledgementStore:
    """Write one runtime acknowledgement without replacement or clearing."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = Path(run_root)
        self.path = self.run_root / WORKER_STOP_ACK_FILENAME

    def persist(
        self,
        record: CanaryWorkerStopAcknowledgementRecord,
    ) -> CanaryWorkerStopAcknowledgementRecord:
        _prepare_run_root(self.run_root, create=False)
        return _persist_one_way(
            path=self.path,
            value=record,
            payload=record.to_dict(),
            maximum=_MAX_ACK_BYTES,
            loader=self.load,
            conflict_message=(
                "A different or invalid worker acknowledgement exists."
            ),
        )

    def load(self) -> CanaryWorkerStopAcknowledgementRecord | None:
        _prepare_run_root(self.run_root, create=False)
        payload = _load_json_object(
            self.path,
            label="Worker stop acknowledgement",
            maximum=_MAX_ACK_BYTES,
        )
        if payload is None:
            return None
        return _parse_stop_acknowledgement(payload)


@dataclass(frozen=True)
class CanaryBrokerWorkerResult:
    status: str
    runtime_instance_id: str
    observed_at: str
    identity_receipt_id: str | None
    stop_acknowledgement_sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_BROKER_WORKER_SCHEMA_VERSION,
            "status": self.status,
            "runtimeInstanceId": self.runtime_instance_id,
            "observedAt": _canonical_timestamp(self.observed_at),
            "identityReceiptId": self.identity_receipt_id,
            "stopAcknowledgementSha256": (
                self.stop_acknowledgement_sha256
            ),
            "workerProcessExited": False,
            "workerProcessExitPending": True,
            "providerEvidence": False,
            "processMutationPerformed": False,
            "credentialAccessed": False,
            "credentialMutationPerformed": False,
            "brokerActionAllowed": False,
            "executionPermit": False,
            "realOrderApproval": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


def run_canary_broker_worker(
    run_root: Path,
    *,
    clock: WorkerClock | None = None,
    worker_artifact_path: Path | None = None,
) -> CanaryBrokerWorkerResult:
    root = Path(run_root)
    _prepare_run_root(root, create=False)
    launch = CanaryBrokerWorkerLaunchStore(root).load()
    if launch is None:
        raise CanaryBrokerWorkerError(
            "Worker launch contract is missing."
        )
    worker_clock = clock or SystemWorkerClock()
    build_manifest = _read_regular_file(
        root / WORKER_BUILD_MANIFEST_FILENAME,
        label="Worker build manifest",
        maximum=_MAX_BUILD_MANIFEST_BYTES,
    )
    artifact_path = (
        Path(worker_artifact_path)
        if worker_artifact_path is not None
        else Path(__file__)
    )
    worker_artifact = _read_regular_file(
        artifact_path,
        label="Worker artifact",
        maximum=4_194_304,
    )
    if (
        hashlib.sha256(build_manifest).hexdigest()
        != launch.expected_worker_build_sha256
    ):
        raise CanaryBrokerWorkerError(
            "Worker build manifest does not match launch policy."
        )
    if (
        hashlib.sha256(worker_artifact).hexdigest()
        != launch.expected_worker_artifact_sha256
    ):
        raise CanaryBrokerWorkerError(
            "Worker artifact does not match launch policy."
        )

    process_store = CanaryProcessEvidenceStore(
        root / WORKER_PROCESS_EVIDENCE_DIRECTORY
    )
    identity_store = CanaryWorkerIdentityStore(
        root / WORKER_IDENTITY_FILENAME
    )
    stop_store = CanaryStopLatchStore(root / WORKER_STOP_LATCH_FILENAME)
    acknowledgement_store = CanaryWorkerStopAcknowledgementStore(root)
    started_monotonic = worker_clock.monotonic()
    startup_deadline = (
        started_monotonic + launch.startup_timeout_seconds
    )
    runtime_deadline = (
        started_monotonic + launch.maximum_runtime_seconds
    )
    poll_seconds = launch.poll_interval_milliseconds / 1000.0
    identity_receipt: CanaryWorkerIdentityReceipt | None = None

    while worker_clock.monotonic() <= startup_deadline:
        stop_request = stop_store.load()
        if stop_request is not None:
            acknowledgement = _acknowledge_stop(
                launch=launch,
                stop_request=stop_request,
                identity_receipt=None,
                process_target_sha256=None,
                acknowledged_at=worker_clock.now(),
                store=acknowledgement_store,
            )
            return _result(
                status=WORKER_PRESTART_STOPPED,
                launch=launch,
                clock=worker_clock,
                identity_receipt=None,
                acknowledgement=acknowledgement,
            )
        target = process_store.load_target()
        if target is None:
            worker_clock.sleep(poll_seconds)
            continue
        if (
            target.process_id != os.getpid()
            or target.runtime_instance_id != launch.runtime_instance_id
        ):
            raise CanaryBrokerWorkerError(
                "Persisted process target does not match this worker."
            )
        identity_receipt = build_canary_worker_identity_receipt(
            target,
            runtime_build_manifest=build_manifest,
            worker_artifact=worker_artifact,
            account_binding_commitment=(
                launch.account_binding_commitment
            ),
            issued_at=worker_clock.now(),
        )
        identity_store.persist(identity_receipt)
        break
    if identity_receipt is None:
        return _result(
            status=WORKER_STARTUP_TIMEOUT,
            launch=launch,
            clock=worker_clock,
            identity_receipt=None,
            acknowledgement=None,
        )

    while worker_clock.monotonic() <= runtime_deadline:
        stop_request = stop_store.load()
        if stop_request is None:
            worker_clock.sleep(poll_seconds)
            continue
        target = process_store.load_target()
        if target is None or target.target_sha256 != (
            identity_receipt.process_target_sha256
        ):
            raise CanaryBrokerWorkerError(
                "Persisted process target changed after identity binding."
            )
        acknowledgement = _acknowledge_stop(
            launch=launch,
            stop_request=stop_request,
            identity_receipt=identity_receipt,
            process_target_sha256=target.target_sha256,
            acknowledged_at=worker_clock.now(),
            store=acknowledgement_store,
        )
        return _result(
            status=WORKER_STOPPED_ACKNOWLEDGED,
            launch=launch,
            clock=worker_clock,
            identity_receipt=identity_receipt,
            acknowledgement=acknowledgement,
        )
    return _result(
        status=WORKER_RUNTIME_TIMEOUT,
        launch=launch,
        clock=worker_clock,
        identity_receipt=identity_receipt,
        acknowledgement=None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Run the local nontransmitting canary worker shell."
    )
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_canary_broker_worker(Path(args.run_root))
    except (OSError, CanaryBrokerWorkerError, ValueError):
        print(
            json.dumps(
                {
                    "schemaVersion": (
                        CANARY_BROKER_WORKER_SCHEMA_VERSION
                    ),
                    "status": "BLOCKED",
                    "reason": "Worker lifecycle failed closed.",
                    "providerEvidence": False,
                    "credentialAccessed": False,
                    "brokerActionAllowed": False,
                    "executionPermit": False,
                    "retryAllowed": False,
                    "transmitting": False,
                    "orderTransmission": "UNAVAILABLE",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result.to_dict(), sort_keys=True))
    return (
        0
        if result.status
        in {WORKER_STOPPED_ACKNOWLEDGED, WORKER_PRESTART_STOPPED}
        else 3
    )


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


def _acknowledge_stop(
    *,
    launch: CanaryBrokerWorkerLaunchContract,
    stop_request: CanaryStopRequest,
    identity_receipt: CanaryWorkerIdentityReceipt | None,
    process_target_sha256: str | None,
    acknowledged_at: datetime,
    store: CanaryWorkerStopAcknowledgementStore,
) -> CanaryWorkerStopAcknowledgementRecord:
    if (
        stop_request.account_binding_commitment
        != launch.account_binding_commitment
    ):
        raise CanaryBrokerWorkerError(
            "Stop request references a different account binding."
        )
    if stop_request.controller_id == launch.runtime_instance_id:
        raise CanaryBrokerWorkerError(
            "Worker cannot act as its own independent stop controller."
        )
    normalized_acknowledged_at = _require_aware_datetime(
        acknowledged_at,
        field="stop acknowledgement",
    )
    requested_at = _require_timestamp(
        stop_request.requested_at,
        field="stop request",
    )
    if normalized_acknowledged_at < requested_at:
        raise CanaryBrokerWorkerError(
            "Stop acknowledgement cannot predate the stop request."
        )
    acknowledgement = CanaryWorkerStopAcknowledgementRecord(
        latch_sha256=stop_request.record_sha256,
        runtime_instance_id=launch.runtime_instance_id,
        account_binding_commitment=(
            launch.account_binding_commitment
        ),
        acknowledged_at=normalized_acknowledged_at.isoformat(),
        worker_identity_receipt_sha256=(
            identity_receipt.receipt_sha256
            if identity_receipt is not None
            else None
        ),
        process_target_sha256=process_target_sha256,
    )
    return store.persist(acknowledgement)


def _result(
    *,
    status: str,
    launch: CanaryBrokerWorkerLaunchContract,
    clock: WorkerClock,
    identity_receipt: CanaryWorkerIdentityReceipt | None,
    acknowledgement: CanaryWorkerStopAcknowledgementRecord | None,
) -> CanaryBrokerWorkerResult:
    return CanaryBrokerWorkerResult(
        status=status,
        runtime_instance_id=launch.runtime_instance_id,
        observed_at=_require_aware_datetime(
            clock.now(),
            field="worker result",
        ).isoformat(),
        identity_receipt_id=(
            identity_receipt.receipt_id
            if identity_receipt is not None
            else None
        ),
        stop_acknowledgement_sha256=(
            acknowledgement.acknowledgement_sha256
            if acknowledgement is not None
            else None
        ),
    )


def _parse_stop_acknowledgement(
    payload: dict[str, object],
) -> CanaryWorkerStopAcknowledgementRecord:
    if set(payload) != _ACK_KEYS:
        raise CanaryBrokerWorkerError(
            "Worker stop acknowledgement fields are invalid."
        )
    if (
        payload["schemaVersion"] != CANARY_BROKER_WORKER_SCHEMA_VERSION
        or payload["recordType"]
        != "CANARY_BROKER_WORKER_STOP_ACKNOWLEDGEMENT"
        or payload["oneWay"] is not True
        or payload["replaceSupported"] is not False
        or payload["clearSupported"] is not False
        or payload["providerEvidence"] is not False
        or payload["processMutationPerformed"] is not False
        or payload["credentialAccessed"] is not False
        or payload["credentialMutationPerformed"] is not False
        or payload["brokerActionAllowed"] is not False
        or payload["executionPermit"] is not False
        or payload["realOrderApproval"] is not False
        or payload["retryAllowed"] is not False
        or payload["transmitting"] is not False
        or payload["orderTransmission"] != "UNAVAILABLE"
    ):
        raise CanaryBrokerWorkerError(
            "Worker stop acknowledgement safety metadata is invalid."
        )
    record = CanaryWorkerStopAcknowledgementRecord(
        latch_sha256=_require_string(
            payload["latchSha256"],
            field="latchSha256",
        ),
        runtime_instance_id=_require_string(
            payload["runtimeInstanceId"],
            field="runtimeInstanceId",
        ),
        account_binding_commitment=_require_string(
            payload["accountBindingCommitment"],
            field="accountBindingCommitment",
        ),
        acknowledged_at=_require_string(
            payload["acknowledgedAt"],
            field="acknowledgedAt",
        ),
        state=_require_string(payload["state"], field="state"),
        execution_disabled=_require_bool(
            payload["executionDisabled"],
            field="executionDisabled",
        ),
        outstanding_command_count=_require_int(
            payload["outstandingCommandCount"],
            field="outstandingCommandCount",
        ),
        worker_identity_receipt_sha256=_optional_string(
            payload["workerIdentityReceiptSha256"],
            field="workerIdentityReceiptSha256",
        ),
        process_target_sha256=_optional_string(
            payload["processTargetSha256"],
            field="processTargetSha256",
        ),
    )
    if (
        payload["acknowledgementSha256"]
        != record.acknowledgement_sha256
        or payload != record.to_dict()
    ):
        raise CanaryBrokerWorkerError(
            "Worker stop acknowledgement hash is invalid."
        )
    return record


def _persist_one_way(
    *,
    path: Path,
    value,
    payload: dict[str, object],
    maximum: int,
    loader,
    conflict_message: str,
):
    encoded = _encode(payload)
    if len(encoded) > maximum:
        raise CanaryBrokerWorkerError(
            "Worker evidence exceeds the size limit."
        )
    if path.is_symlink():
        raise CanaryBrokerWorkerError(
            "Worker evidence path cannot be a symlink."
        )
    try:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError:
        try:
            existing = loader()
        except CanaryBrokerWorkerError as exc:
            raise CanaryBrokerWorkerConflict(
                conflict_message
            ) from exc
        if existing == value:
            return existing
        raise CanaryBrokerWorkerConflict(conflict_message) from None
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        # Partial evidence remains fail-closed and is not removed here.
        raise
    persisted = loader()
    if persisted != value:
        raise CanaryBrokerWorkerError(
            "Persisted worker evidence failed validation."
        )
    return persisted


def _load_json_object(
    path: Path,
    *,
    label: str,
    maximum: int,
) -> dict[str, object] | None:
    if path.is_symlink():
        raise CanaryBrokerWorkerError(
            f"{label} must be a regular file."
        )
    if not path.exists():
        return None
    if not path.is_file():
        raise CanaryBrokerWorkerError(
            f"{label} must be a regular file."
        )
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise CanaryBrokerWorkerError(f"{label} has an invalid size.")
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryBrokerWorkerError(
            f"{label} is unreadable or malformed."
        ) from exc
    if not isinstance(payload, dict):
        raise CanaryBrokerWorkerError(
            f"{label} must contain a JSON object."
        )
    return payload


def _read_regular_file(
    path: Path,
    *,
    label: str,
    maximum: int,
) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CanaryBrokerWorkerError(
            f"{label} must be a regular non-symlink file."
        )
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise CanaryBrokerWorkerError(f"{label} has an invalid size.")
    return path.read_bytes()


def _prepare_run_root(root: Path, *, create: bool) -> None:
    if root.is_symlink():
        raise CanaryBrokerWorkerError(
            "Worker run root cannot be a symlink."
        )
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CanaryBrokerWorkerError(
                "Worker run root cannot be created safely."
            ) from exc
    if not root.exists():
        raise CanaryBrokerWorkerError("Worker run root is missing.")
    if not root.is_dir() or root.is_symlink():
        raise CanaryBrokerWorkerError(
            "Worker run root must be a regular directory."
        )


def _encode(payload: dict[str, object]) -> bytes:
    try:
        rendered = json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanaryBrokerWorkerError(
            "Worker evidence is not serializable."
        ) from exc
    return (rendered + "\n").encode("ascii")


def _require_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CanaryBrokerWorkerError(f"{field.capitalize()} is invalid.")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CanaryBrokerWorkerError(
            f"{field.capitalize()} SHA-256 is invalid."
        )
    return value


def _require_finite_range(
    value: object,
    *,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value != value
        or value in (float("inf"), float("-inf"))
        or float(value) < minimum
        or float(value) > maximum
    ):
        raise CanaryBrokerWorkerError(f"{field.capitalize()} is invalid.")
    return float(value)


def _require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise CanaryBrokerWorkerError(f"{field} must be a string.")
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field=field)


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanaryBrokerWorkerError(f"{field} must be an integer.")
    return value


def _require_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanaryBrokerWorkerError(f"{field} must be numeric.")
    return float(value)


def _require_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise CanaryBrokerWorkerError(f"{field} must be boolean.")
    return value


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CanaryBrokerWorkerError(
            f"{field.capitalize()} must be timezone-aware."
        )
    return value


def _require_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise CanaryBrokerWorkerError(
            f"{field.capitalize()} timestamp is invalid."
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanaryBrokerWorkerError(
            f"{field.capitalize()} timestamp is invalid."
        ) from exc
    return _require_aware_datetime(parsed, field=field)


def _canonical_timestamp(value: str) -> str:
    return _require_timestamp(value, field="timestamp").isoformat()


def _sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
