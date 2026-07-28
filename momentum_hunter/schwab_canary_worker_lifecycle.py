from __future__ import annotations

"""Bounded local lifecycle proof for the nontransmitting canary worker."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Final, Protocol, Sequence

from momentum_hunter.schwab_canary_broker_worker import (
    WORKER_BUILD_MANIFEST_FILENAME,
    WORKER_IDENTITY_FILENAME,
    WORKER_PROCESS_EVIDENCE_DIRECTORY,
    WORKER_STOPPED_ACKNOWLEDGED,
    WORKER_STOP_ACK_FILENAME,
    WORKER_STOP_LATCH_FILENAME,
    CanaryBrokerWorkerLaunchStore,
    CanaryWorkerStopAcknowledgementStore,
)
from momentum_hunter.schwab_canary_process_evidence import (
    CanaryProcessEvidenceStore,
)
from momentum_hunter.schwab_canary_process_observer import (
    WINDOWS_PROCESS_OBSERVER_SOURCE,
    CanaryProcessLivenessEvidence,
    CanaryProcessTarget,
    ProcessIdentitySource,
    WindowsProcessIdentitySource,
    capture_canary_process_target,
    observe_canary_process_target,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CanaryStopDrillPolicy,
    CanaryStopLatchStore,
    CanaryStopRequest,
    evaluate_canary_stop_drill,
)
from momentum_hunter.schwab_canary_worker_identity import (
    WORKER_IDENTITY_BOUND_STOPPED,
    CanaryWorkerIdentityPolicy,
    CanaryWorkerIdentityStore,
    evaluate_canary_worker_identity_binding,
)


CANARY_WORKER_LIFECYCLE_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_WORKER_LIFECYCLE_V1"
)
CANARY_WORKER_LIFECYCLE_STATUS: Final = (
    "LOCAL_LIFECYCLE_PROVEN_PROVIDER_REVOCATION_MISSING"
)
WORKER_LIFECYCLE_RESULT_FILENAME: Final = (
    "worker-lifecycle-result.json"
)
LIFECYCLE_OBSERVER_ID: Final = "canary-lifecycle-observer"
LIFECYCLE_CONTROLLER_ID: Final = "canary-lifecycle-controller"
LIFECYCLE_REVOCATION_SOURCE: Final = (
    "schwab-provider-revocation-observer"
)
LIFECYCLE_STOP_REASON: Final = "LOCAL_LIFECYCLE_PROOF_COMPLETE"
LIFECYCLE_REVOCATION_MISSING: Final = (
    "REVOCATION_OBSERVATION_MISSING"
)

_MAX_RESULT_BYTES: Final = 65_536
_MAX_BUILD_MANIFEST_BYTES: Final = 1_048_576
_MAX_WORKER_ARTIFACT_BYTES: Final = 4_194_304
_MAX_CAPTURE_WAIT_SECONDS: Final = 10.0
_MAX_EXIT_GRACE_SECONDS: Final = 5.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RESULT_KEYS: Final = frozenset(
    {
        "schemaVersion",
        "status",
        "conclusion",
        "completedAt",
        "runtimeInstanceId",
        "workerExitCode",
        "identityReceiptId",
        "processTargetSha256",
        "processEvidenceChainSha256",
        "stopLatchSha256",
        "stopAcknowledgementSha256",
        "stopDrillStatus",
        "stopDrillFindingCodes",
        "localWorkerLifecycleVerified",
        "identityBindingVerified",
        "runtimeAcknowledgementVerified",
        "processStoppedVerified",
        "providerRevocationVerified",
        "providerRevocationRequired",
        "physicalStopDrillComplete",
        "workerProcessExited",
        "processLaunchPerformed",
        "processMutationPerformed",
        "processTerminationPerformed",
        "processSignalPerformed",
        "providerEvidence",
        "credentialAccessed",
        "credentialMutationPerformed",
        "brokerActionAllowed",
        "executionPermit",
        "realOrderApproval",
        "retryAllowed",
        "transmitting",
        "orderTransmission",
        "resultSha256",
    }
)


class CanaryWorkerLifecycleError(RuntimeError):
    pass


class CanaryWorkerLifecycleConflict(CanaryWorkerLifecycleError):
    pass


class LifecycleClock(Protocol):
    def now(self) -> datetime:
        ...

    def monotonic(self) -> float:
        ...

    def sleep(self, seconds: float) -> None:
        ...


class SystemLifecycleClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class WorkerChildProcess(Protocol):
    pid: int
    returncode: int | None

    def poll(self) -> int | None:
        ...

    def communicate(
        self,
        input: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str, str]:
        ...


class WorkerProcessLauncher(Protocol):
    def launch(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
    ) -> WorkerChildProcess:
        ...


class SubprocessWorkerLauncher:
    """Start exactly one child without a shell or termination capability."""

    def launch(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
    ) -> WorkerChildProcess:
        creation_flags = (
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        return subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            creationflags=creation_flags,
        )


@dataclass(frozen=True, repr=False)
class CanaryWorkerLifecycleResult:
    completed_at: str
    runtime_instance_id: str
    worker_exit_code: int
    identity_receipt_id: str
    process_target_sha256: str
    process_evidence_chain_sha256: str
    stop_latch_sha256: str
    stop_acknowledgement_sha256: str
    stop_drill_finding_codes: tuple[str, ...] = (
        LIFECYCLE_REVOCATION_MISSING,
    )

    def __post_init__(self) -> None:
        _require_timestamp(self.completed_at, field="completion")
        _require_identifier(
            self.runtime_instance_id,
            field="runtime instance ID",
        )
        _require_identifier(
            self.identity_receipt_id,
            field="identity receipt ID",
        )
        if (
            isinstance(self.worker_exit_code, bool)
            or not isinstance(self.worker_exit_code, int)
            or self.worker_exit_code != 0
        ):
            raise CanaryWorkerLifecycleError(
                "Worker exit code must prove a successful cooperative exit."
            )
        for value, field in (
            (self.process_target_sha256, "process target"),
            (
                self.process_evidence_chain_sha256,
                "process evidence chain",
            ),
            (self.stop_latch_sha256, "stop latch"),
            (
                self.stop_acknowledgement_sha256,
                "stop acknowledgement",
            ),
        ):
            _require_sha256(value, field=field)
        if self.stop_drill_finding_codes != (
            LIFECYCLE_REVOCATION_MISSING,
        ):
            raise CanaryWorkerLifecycleError(
                "Local lifecycle proof must remain blocked on revocation."
            )

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_WORKER_LIFECYCLE_SCHEMA_VERSION,
            "status": CANARY_WORKER_LIFECYCLE_STATUS,
            "conclusion": (
                "LOCAL_PROCESS_LIFECYCLE_VERIFIED_"
                "PROVIDER_REVOCATION_UNAVAILABLE"
            ),
            "completedAt": _canonical_timestamp(self.completed_at),
            "runtimeInstanceId": self.runtime_instance_id,
            "workerExitCode": self.worker_exit_code,
            "identityReceiptId": self.identity_receipt_id,
            "processTargetSha256": self.process_target_sha256,
            "processEvidenceChainSha256": (
                self.process_evidence_chain_sha256
            ),
            "stopLatchSha256": self.stop_latch_sha256,
            "stopAcknowledgementSha256": (
                self.stop_acknowledgement_sha256
            ),
            "stopDrillStatus": "BLOCK",
            "stopDrillFindingCodes": list(
                self.stop_drill_finding_codes
            ),
            "localWorkerLifecycleVerified": True,
            "identityBindingVerified": True,
            "runtimeAcknowledgementVerified": True,
            "processStoppedVerified": True,
            "providerRevocationVerified": False,
            "providerRevocationRequired": True,
            "physicalStopDrillComplete": False,
            "workerProcessExited": True,
            "processLaunchPerformed": True,
            "processMutationPerformed": True,
            "processTerminationPerformed": False,
            "processSignalPerformed": False,
            "providerEvidence": False,
            "credentialAccessed": False,
            "credentialMutationPerformed": False,
            "brokerActionAllowed": False,
            "executionPermit": False,
            "realOrderApproval": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }

    @property
    def result_sha256(self) -> str:
        return _sha256(self._unsigned_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self._unsigned_payload(),
            "resultSha256": self.result_sha256,
        }

    def __repr__(self) -> str:
        return (
            "CanaryWorkerLifecycleResult("
            f"result_sha256={self.result_sha256!r}, "
            f"runtime_instance_id={self.runtime_instance_id!r}, "
            f"status={CANARY_WORKER_LIFECYCLE_STATUS!r})"
        )

class CanaryWorkerLifecycleResultStore:
    """Persist one immutable sanitized lifecycle result."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = Path(run_root)
        self.path = self.run_root / WORKER_LIFECYCLE_RESULT_FILENAME

    def persist(
        self,
        result: CanaryWorkerLifecycleResult,
    ) -> CanaryWorkerLifecycleResult:
        _validate_run_root(self.run_root)
        encoded = _encode(result.to_dict())
        if len(encoded) > _MAX_RESULT_BYTES:
            raise CanaryWorkerLifecycleError(
                "Worker lifecycle result exceeds the size limit."
            )
        if self.path.is_symlink():
            raise CanaryWorkerLifecycleError(
                "Worker lifecycle result cannot be a symlink."
            )
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            try:
                existing = self.load()
            except CanaryWorkerLifecycleError as exc:
                raise CanaryWorkerLifecycleConflict(
                    "A different or invalid lifecycle result exists."
                ) from exc
            if existing == result:
                return existing
            raise CanaryWorkerLifecycleConflict(
                "A different or invalid lifecycle result exists."
            ) from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # Partial evidence remains fail-closed and is not removed.
            raise
        persisted = self.load()
        if persisted != result:
            raise CanaryWorkerLifecycleError(
                "Persisted lifecycle result failed validation."
            )
        return persisted

    def load(self) -> CanaryWorkerLifecycleResult | None:
        _validate_run_root(self.run_root)
        payload = _load_json_object(
            self.path,
            label="Worker lifecycle result",
            maximum=_MAX_RESULT_BYTES,
        )
        if payload is None:
            return None
        return _parse_result(payload)


def worker_lifecycle_command(
    *,
    run_root: Path,
) -> tuple[str, ...]:
    root = Path(run_root)
    _validate_run_root(root)
    interpreter = _resolve_interpreter()
    repository_root = Path(__file__).resolve().parents[1]
    worker_artifact = (
        repository_root
        / "momentum_hunter"
        / "schwab_canary_broker_worker.py"
    )
    _read_regular_file(
        worker_artifact,
        label="Worker artifact",
        maximum=_MAX_WORKER_ARTIFACT_BYTES,
    )
    return (
        str(interpreter),
        "-B",
        "-m",
        "momentum_hunter.schwab_canary_broker_worker",
        "--run-root",
        str(root.resolve()),
    )


def run_canary_worker_lifecycle(
    run_root: Path,
    *,
    clock: LifecycleClock | None = None,
    process_source: ProcessIdentitySource | None = None,
    launcher: WorkerProcessLauncher | None = None,
) -> CanaryWorkerLifecycleResult:
    if os.name != "nt" and process_source is None:
        raise CanaryWorkerLifecycleError(
            "Local lifecycle proof requires an explicit process source."
        )
    root = Path(run_root)
    _validate_run_root(root)
    launch = CanaryBrokerWorkerLaunchStore(root).load()
    if launch is None:
        raise CanaryWorkerLifecycleError(
            "Worker launch contract is missing."
        )
    _validate_pristine_evidence(root)
    build_manifest = _read_regular_file(
        root / WORKER_BUILD_MANIFEST_FILENAME,
        label="Worker build manifest",
        maximum=_MAX_BUILD_MANIFEST_BYTES,
    )
    worker_artifact_path = (
        Path(__file__).resolve().parent
        / "schwab_canary_broker_worker.py"
    )
    worker_artifact = _read_regular_file(
        worker_artifact_path,
        label="Worker artifact",
        maximum=_MAX_WORKER_ARTIFACT_BYTES,
    )
    if (
        hashlib.sha256(build_manifest).hexdigest()
        != launch.expected_worker_build_sha256
    ):
        raise CanaryWorkerLifecycleError(
            "Worker build manifest does not match launch policy."
        )
    if (
        hashlib.sha256(worker_artifact).hexdigest()
        != launch.expected_worker_artifact_sha256
    ):
        raise CanaryWorkerLifecycleError(
            "Worker artifact does not match launch policy."
        )

    active_clock = clock or SystemLifecycleClock()
    active_source = process_source or WindowsProcessIdentitySource()
    active_launcher = launcher or SubprocessWorkerLauncher()
    command = worker_lifecycle_command(
        run_root=root,
    )
    if launch.account_binding_commitment in " ".join(command):
        raise CanaryWorkerLifecycleError(
            "Account binding cannot appear in the worker command."
        )
    repository_root = Path(__file__).resolve().parents[1]
    child: WorkerChildProcess | None = None
    stop_store = CanaryStopLatchStore(
        root / WORKER_STOP_LATCH_FILENAME
    )
    try:
        child = active_launcher.launch(command, cwd=repository_root)
        target = _capture_target(
            child=child,
            launch_runtime_id=launch.runtime_instance_id,
            process_source=active_source,
            clock=active_clock,
            timeout_seconds=min(
                launch.startup_timeout_seconds,
                _MAX_CAPTURE_WAIT_SECONDS,
            ),
        )
        process_store = CanaryProcessEvidenceStore(
            root / WORKER_PROCESS_EVIDENCE_DIRECTORY
        )
        process_store.persist_target(target)
        identity_store = CanaryWorkerIdentityStore(
            root / WORKER_IDENTITY_FILENAME
        )
        identity = _wait_for_identity(
            child=child,
            identity_store=identity_store,
            clock=active_clock,
            timeout_seconds=launch.startup_timeout_seconds,
        )
        running = observe_canary_process_target(
            target,
            observed_at=active_clock.now(),
            source=active_source,
        )
        if running.process_running is not True:
            raise CanaryWorkerLifecycleError(
                "Worker was not independently observed running."
            )
        process_store.append_observation(running)
        stop_request = _engage_stop(
            stop_store=stop_store,
            launch_runtime_id=launch.runtime_instance_id,
            account_binding_commitment=(
                launch.account_binding_commitment
            ),
            requested_at=active_clock.now(),
            reason_code=LIFECYCLE_STOP_REASON,
        )
        stdout, stderr = _wait_for_cooperative_exit(
            child=child,
            timeout_seconds=(
                launch.maximum_runtime_seconds
                + _MAX_EXIT_GRACE_SECONDS
            ),
        )
        worker_exit_code = child.poll()
        if worker_exit_code != 0:
            raise CanaryWorkerLifecycleError(
                "Worker did not complete a cooperative zero-code exit."
            )
        worker_result = _parse_worker_output(stdout, stderr=stderr)
        stopped = _observe_stopped(
            child=child,
            target=target,
            process_source=active_source,
            clock=active_clock,
            timeout_seconds=_MAX_EXIT_GRACE_SECONDS,
        )
        process_store.append_observation(stopped)
        acknowledgement = CanaryWorkerStopAcknowledgementStore(
            root
        ).load()
        if acknowledgement is None:
            raise CanaryWorkerLifecycleError(
                "Worker stop acknowledgement is missing."
            )
        if (
            worker_result["stopAcknowledgementSha256"]
            != acknowledgement.acknowledgement_sha256
            or acknowledgement.latch_sha256
            != stop_request.record_sha256
            or acknowledgement.worker_identity_receipt_sha256
            != identity.receipt_sha256
            or acknowledgement.process_target_sha256
            != target.target_sha256
        ):
            raise CanaryWorkerLifecycleError(
                "Worker lifecycle evidence identity is inconsistent."
            )
        evaluated_at = active_clock.now()
        identity_binding = evaluate_canary_worker_identity_binding(
            identity_store=identity_store,
            process_store=process_store,
            policy=CanaryWorkerIdentityPolicy(
                expected_worker_build_sha256=(
                    launch.expected_worker_build_sha256
                ),
                expected_worker_artifact_sha256=(
                    launch.expected_worker_artifact_sha256
                ),
                expected_account_binding_commitment=(
                    launch.account_binding_commitment
                ),
                expected_executable_path_sha256=(
                    target.executable_path_sha256
                ),
                expected_observer_id=target.observer_id,
                expected_process_source=target.source,
                max_receipt_age_seconds=(
                    launch.maximum_runtime_seconds
                    + _MAX_EXIT_GRACE_SECONDS
                ),
                max_observation_age_seconds=(
                    launch.maximum_runtime_seconds
                    + _MAX_EXIT_GRACE_SECONDS
                ),
            ),
            evaluated_at=evaluated_at,
        )
        if identity_binding.status != WORKER_IDENTITY_BOUND_STOPPED:
            raise CanaryWorkerLifecycleError(
                "Worker identity and stopped lifecycle are not proven."
            )
        stop_drill = evaluate_canary_stop_drill(
            stop_request=stop_request,
            runtime_acknowledgement=(
                acknowledgement.to_stop_acknowledgement()
            ),
            process_observation=stopped.to_stop_observation(),
            revocation_observation=None,
            evaluated_at=evaluated_at,
            policy=CanaryStopDrillPolicy(
                expected_controller_id=LIFECYCLE_CONTROLLER_ID,
                expected_process_observer_id=LIFECYCLE_OBSERVER_ID,
                expected_process_source=active_source.source_id,
                expected_revocation_source=(
                    LIFECYCLE_REVOCATION_SOURCE
                ),
                max_evidence_age_seconds=(
                    launch.maximum_runtime_seconds
                    + _MAX_EXIT_GRACE_SECONDS
                ),
                max_shutdown_latency_seconds=(
                    launch.maximum_runtime_seconds
                    + _MAX_EXIT_GRACE_SECONDS
                ),
                max_revocation_latency_seconds=(
                    launch.maximum_runtime_seconds
                    + _MAX_EXIT_GRACE_SECONDS
                ),
            ),
        )
        finding_codes = tuple(
            finding.code for finding in stop_drill.findings
        )
        if (
            stop_drill.status != "BLOCK"
            or finding_codes != (LIFECYCLE_REVOCATION_MISSING,)
        ):
            raise CanaryWorkerLifecycleError(
                "Local lifecycle proof has unexpected stop-drill findings."
            )
        process_chain_sha256 = (
            identity_binding.process_evidence_chain_sha256
        )
        if process_chain_sha256 is None:
            raise CanaryWorkerLifecycleError(
                "Process evidence chain identity is missing."
            )
        result = CanaryWorkerLifecycleResult(
            completed_at=evaluated_at.isoformat(),
            runtime_instance_id=launch.runtime_instance_id,
            worker_exit_code=worker_exit_code,
            identity_receipt_id=identity.receipt_id,
            process_target_sha256=target.target_sha256,
            process_evidence_chain_sha256=process_chain_sha256,
            stop_latch_sha256=stop_request.record_sha256,
            stop_acknowledgement_sha256=(
                acknowledgement.acknowledgement_sha256
            ),
            stop_drill_finding_codes=finding_codes,
        )
        return CanaryWorkerLifecycleResultStore(root).persist(result)
    except Exception as exc:
        if child is not None and child.poll() is None:
            _request_fail_closed_stop(
                stop_store=stop_store,
                launch_runtime_id=launch.runtime_instance_id,
                account_binding_commitment=(
                    launch.account_binding_commitment
                ),
                requested_at=active_clock.now(),
            )
            _bounded_cleanup_wait(
                child,
                timeout_seconds=(
                    launch.maximum_runtime_seconds
                    + _MAX_EXIT_GRACE_SECONDS
                ),
            )
        if isinstance(exc, CanaryWorkerLifecycleError):
            raise
        raise CanaryWorkerLifecycleError(
            "Worker lifecycle proof failed closed."
        ) from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description=(
            "Run a local nontransmitting canary worker lifecycle proof."
        )
    )
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args(argv)
    try:
        result = run_canary_worker_lifecycle(Path(args.run_root))
    except (
        OSError,
        ValueError,
        CanaryWorkerLifecycleError,
        subprocess.SubprocessError,
    ):
        print(
            json.dumps(
                {
                    "schemaVersion": (
                        CANARY_WORKER_LIFECYCLE_SCHEMA_VERSION
                    ),
                    "status": "BLOCKED",
                    "reason": "Worker lifecycle proof failed closed.",
                    "localWorkerLifecycleVerified": False,
                    "providerRevocationVerified": False,
                    "physicalStopDrillComplete": False,
                    "processLaunchPerformed": None,
                    "processMutationPerformed": None,
                    "processTerminationPerformed": False,
                    "processSignalPerformed": False,
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
    return 0


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


def _capture_target(
    *,
    child: WorkerChildProcess,
    launch_runtime_id: str,
    process_source: ProcessIdentitySource,
    clock: LifecycleClock,
    timeout_seconds: float,
) -> CanaryProcessTarget:
    deadline = clock.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while clock.monotonic() <= deadline:
        if child.poll() is not None:
            raise CanaryWorkerLifecycleError(
                "Worker exited before process identity capture."
            )
        try:
            return capture_canary_process_target(
                observer_id=LIFECYCLE_OBSERVER_ID,
                runtime_instance_id=launch_runtime_id,
                process_id=child.pid,
                captured_at=clock.now(),
                source=process_source,
            )
        except ValueError as exc:
            last_error = exc
            clock.sleep(0.02)
    raise CanaryWorkerLifecycleError(
        "Worker process identity was not captured in time."
    ) from last_error


def _wait_for_identity(
    *,
    child: WorkerChildProcess,
    identity_store: CanaryWorkerIdentityStore,
    clock: LifecycleClock,
    timeout_seconds: float,
):
    deadline = clock.monotonic() + timeout_seconds
    while clock.monotonic() <= deadline:
        identity = identity_store.load()
        if identity is not None:
            return identity
        if child.poll() is not None:
            raise CanaryWorkerLifecycleError(
                "Worker exited before identity binding."
            )
        clock.sleep(0.02)
    raise CanaryWorkerLifecycleError(
        "Worker identity was not persisted in time."
    )


def _engage_stop(
    *,
    stop_store: CanaryStopLatchStore,
    launch_runtime_id: str,
    account_binding_commitment: str,
    requested_at: datetime,
    reason_code: str,
) -> CanaryStopRequest:
    request = CanaryStopRequest(
        latch_id=_latch_id(launch_runtime_id),
        controller_id=LIFECYCLE_CONTROLLER_ID,
        account_binding_commitment=account_binding_commitment,
        requested_at=_require_aware_datetime(
            requested_at,
            field="stop request",
        ).isoformat(),
        reason_code=reason_code,
    )
    return stop_store.engage(request)


def _request_fail_closed_stop(
    *,
    stop_store: CanaryStopLatchStore,
    launch_runtime_id: str,
    account_binding_commitment: str,
    requested_at: datetime,
) -> None:
    try:
        _engage_stop(
            stop_store=stop_store,
            launch_runtime_id=launch_runtime_id,
            account_binding_commitment=account_binding_commitment,
            requested_at=requested_at,
            reason_code="SUPERVISOR_FAIL_CLOSED",
        )
    except (OSError, ValueError):
        # Existing or invalid immutable evidence is preserved for review.
        return


def _wait_for_cooperative_exit(
    *,
    child: WorkerChildProcess,
    timeout_seconds: float,
) -> tuple[str, str]:
    try:
        return child.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise CanaryWorkerLifecycleError(
            "Worker did not exit within the bounded lifecycle window."
        ) from exc


def _bounded_cleanup_wait(
    child: WorkerChildProcess,
    *,
    timeout_seconds: float,
) -> None:
    try:
        child.communicate(timeout=timeout_seconds)
    except (OSError, subprocess.SubprocessError):
        return


def _observe_stopped(
    *,
    child: WorkerChildProcess,
    target: CanaryProcessTarget,
    process_source: ProcessIdentitySource,
    clock: LifecycleClock,
    timeout_seconds: float,
) -> CanaryProcessLivenessEvidence:
    deadline = clock.monotonic() + timeout_seconds
    latest: CanaryProcessLivenessEvidence | None = None
    while clock.monotonic() <= deadline:
        if child.poll() is None:
            clock.sleep(0.02)
            continue
        latest = observe_canary_process_target(
            target,
            observed_at=clock.now(),
            source=process_source,
        )
        if latest.process_running is False:
            return latest
        clock.sleep(0.02)
    raise CanaryWorkerLifecycleError(
        "Independent observer did not prove the worker stopped."
    )


def _parse_worker_output(
    stdout: str,
    *,
    stderr: str,
) -> dict[str, object]:
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        raise CanaryWorkerLifecycleError(
            "Worker output channels are invalid."
        )
    if stderr:
        raise CanaryWorkerLifecycleError(
            "Worker emitted an error during lifecycle proof."
        )
    if len(stdout.encode("utf-8")) > 65_536:
        raise CanaryWorkerLifecycleError(
            "Worker output exceeds the size limit."
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CanaryWorkerLifecycleError(
            "Worker output is malformed."
        ) from exc
    if not isinstance(payload, dict):
        raise CanaryWorkerLifecycleError(
            "Worker output must contain one JSON object."
        )
    if (
        payload.get("status") != WORKER_STOPPED_ACKNOWLEDGED
        or payload.get("workerProcessExited") is not False
        or payload.get("workerProcessExitPending") is not True
        or payload.get("providerEvidence") is not False
        or payload.get("credentialAccessed") is not False
        or payload.get("credentialMutationPerformed") is not False
        or payload.get("brokerActionAllowed") is not False
        or payload.get("executionPermit") is not False
        or payload.get("realOrderApproval") is not False
        or payload.get("retryAllowed") is not False
        or payload.get("transmitting") is not False
        or payload.get("orderTransmission") != "UNAVAILABLE"
    ):
        raise CanaryWorkerLifecycleError(
            "Worker output safety state is invalid."
        )
    acknowledgement = payload.get("stopAcknowledgementSha256")
    if not isinstance(acknowledgement, str):
        raise CanaryWorkerLifecycleError(
            "Worker output acknowledgement identity is missing."
        )
    _require_sha256(
        acknowledgement,
        field="worker output acknowledgement",
    )
    return payload


def _validate_pristine_evidence(root: Path) -> None:
    evidence_paths = (
        root / WORKER_PROCESS_EVIDENCE_DIRECTORY,
        root / WORKER_IDENTITY_FILENAME,
        root / WORKER_STOP_LATCH_FILENAME,
        root / WORKER_STOP_ACK_FILENAME,
        root / WORKER_LIFECYCLE_RESULT_FILENAME,
    )
    if any(path.exists() or path.is_symlink() for path in evidence_paths):
        raise CanaryWorkerLifecycleError(
            "Worker lifecycle evidence already exists."
        )


def _resolve_interpreter() -> Path:
    selected = Path(
        getattr(sys, "_base_executable", sys.executable)
    )
    if (
        not selected.is_absolute()
        or selected.is_symlink()
        or not selected.is_file()
    ):
        raise CanaryWorkerLifecycleError(
            "Worker interpreter must be an absolute regular file."
        )
    return selected.resolve()


def _validate_run_root(root: Path) -> None:
    if (
        root.is_symlink()
        or not root.exists()
        or not root.is_dir()
    ):
        raise CanaryWorkerLifecycleError(
            "Worker run root must be a regular directory."
        )


def _read_regular_file(
    path: Path,
    *,
    label: str,
    maximum: int,
) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CanaryWorkerLifecycleError(
            f"{label} must be a regular non-symlink file."
        )
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise CanaryWorkerLifecycleError(
            f"{label} has an invalid size."
        )
    return path.read_bytes()


def _load_json_object(
    path: Path,
    *,
    label: str,
    maximum: int,
) -> dict[str, object] | None:
    if path.is_symlink():
        raise CanaryWorkerLifecycleError(
            f"{label} must be a regular file."
        )
    if not path.exists():
        return None
    if not path.is_file():
        raise CanaryWorkerLifecycleError(
            f"{label} must be a regular file."
        )
    size = path.stat().st_size
    if size <= 0 or size > maximum:
        raise CanaryWorkerLifecycleError(
            f"{label} has an invalid size."
        )
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryWorkerLifecycleError(
            f"{label} is unreadable or malformed."
        ) from exc
    if not isinstance(payload, dict):
        raise CanaryWorkerLifecycleError(
            f"{label} must contain one JSON object."
        )
    return payload


def _parse_result(
    payload: dict[str, object],
) -> CanaryWorkerLifecycleResult:
    if set(payload) != _RESULT_KEYS:
        raise CanaryWorkerLifecycleError(
            "Worker lifecycle result fields are invalid."
        )
    if (
        payload["schemaVersion"]
        != CANARY_WORKER_LIFECYCLE_SCHEMA_VERSION
        or payload["status"] != CANARY_WORKER_LIFECYCLE_STATUS
        or payload["conclusion"]
        != (
            "LOCAL_PROCESS_LIFECYCLE_VERIFIED_"
            "PROVIDER_REVOCATION_UNAVAILABLE"
        )
        or payload["stopDrillStatus"] != "BLOCK"
        or payload["localWorkerLifecycleVerified"] is not True
        or payload["identityBindingVerified"] is not True
        or payload["runtimeAcknowledgementVerified"] is not True
        or payload["processStoppedVerified"] is not True
        or payload["providerRevocationVerified"] is not False
        or payload["providerRevocationRequired"] is not True
        or payload["physicalStopDrillComplete"] is not False
        or payload["workerProcessExited"] is not True
        or payload["processLaunchPerformed"] is not True
        or payload["processMutationPerformed"] is not True
        or payload["processTerminationPerformed"] is not False
        or payload["processSignalPerformed"] is not False
        or payload["providerEvidence"] is not False
        or payload["credentialAccessed"] is not False
        or payload["credentialMutationPerformed"] is not False
        or payload["brokerActionAllowed"] is not False
        or payload["executionPermit"] is not False
        or payload["realOrderApproval"] is not False
        or payload["retryAllowed"] is not False
        or payload["transmitting"] is not False
        or payload["orderTransmission"] != "UNAVAILABLE"
    ):
        raise CanaryWorkerLifecycleError(
            "Worker lifecycle result safety state is invalid."
        )
    finding_codes = payload["stopDrillFindingCodes"]
    if not isinstance(finding_codes, list) or not all(
        isinstance(value, str) for value in finding_codes
    ):
        raise CanaryWorkerLifecycleError(
            "Worker lifecycle finding codes are invalid."
        )
    result = CanaryWorkerLifecycleResult(
        completed_at=_require_string(
            payload["completedAt"],
            field="completedAt",
        ),
        runtime_instance_id=_require_string(
            payload["runtimeInstanceId"],
            field="runtimeInstanceId",
        ),
        worker_exit_code=_require_int(
            payload["workerExitCode"],
            field="workerExitCode",
        ),
        identity_receipt_id=_require_string(
            payload["identityReceiptId"],
            field="identityReceiptId",
        ),
        process_target_sha256=_require_string(
            payload["processTargetSha256"],
            field="processTargetSha256",
        ),
        process_evidence_chain_sha256=_require_string(
            payload["processEvidenceChainSha256"],
            field="processEvidenceChainSha256",
        ),
        stop_latch_sha256=_require_string(
            payload["stopLatchSha256"],
            field="stopLatchSha256",
        ),
        stop_acknowledgement_sha256=_require_string(
            payload["stopAcknowledgementSha256"],
            field="stopAcknowledgementSha256",
        ),
        stop_drill_finding_codes=tuple(finding_codes),
    )
    if (
        payload["resultSha256"] != result.result_sha256
        or payload != result.to_dict()
    ):
        raise CanaryWorkerLifecycleError(
            "Worker lifecycle result hash is invalid."
        )
    return result


def _latch_id(runtime_instance_id: str) -> str:
    digest = hashlib.sha256(
        runtime_instance_id.encode("ascii")
    ).hexdigest()[:24]
    return f"local-lifecycle-stop-{digest}"


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
        raise CanaryWorkerLifecycleError(
            "Worker lifecycle evidence is not serializable."
        ) from exc
    return (rendered + "\n").encode("ascii")


def _require_identifier(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
            value,
        )
    ):
        raise CanaryWorkerLifecycleError(
            f"{field.capitalize()} is invalid."
        )
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CanaryWorkerLifecycleError(
            f"{field.capitalize()} SHA-256 is invalid."
        )
    return value


def _require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise CanaryWorkerLifecycleError(
            f"{field} must be a string."
        )
    return value


def _require_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanaryWorkerLifecycleError(
            f"{field} must be an integer."
        )
    return value


def _require_aware_datetime(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CanaryWorkerLifecycleError(
            f"{field.capitalize()} must be timezone-aware."
        )
    return value


def _require_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise CanaryWorkerLifecycleError(
            f"{field.capitalize()} timestamp is invalid."
        )
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise CanaryWorkerLifecycleError(
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
