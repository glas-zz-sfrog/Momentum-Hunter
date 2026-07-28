from __future__ import annotations

"""Read-only verification of one complete local canary worker lifecycle package."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from math import isfinite
from pathlib import Path
import re
from typing import Final

from momentum_hunter.schwab_canary_broker_worker import (
    WORKER_BUILD_MANIFEST_FILENAME,
    WORKER_IDENTITY_FILENAME,
    WORKER_PROCESS_EVIDENCE_DIRECTORY,
    WORKER_STOP_LATCH_FILENAME,
    CanaryBrokerWorkerError,
    CanaryBrokerWorkerLaunchStore,
    CanaryWorkerStopAcknowledgementStore,
)
from momentum_hunter.schwab_canary_process_evidence import (
    CanaryProcessEvidenceError,
    CanaryProcessEvidenceStore,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CanaryStopDrillPolicy,
    CanaryStopEvidenceError,
    CanaryStopLatchStore,
    evaluate_canary_stop_drill,
)
from momentum_hunter.schwab_canary_worker_identity import (
    WORKER_IDENTITY_BOUND_STOPPED,
    CanaryWorkerIdentityError,
    CanaryWorkerIdentityPolicy,
    CanaryWorkerIdentityStore,
    evaluate_canary_worker_identity_binding,
)
from momentum_hunter.schwab_canary_worker_lifecycle import (
    LIFECYCLE_REVOCATION_MISSING,
    LIFECYCLE_STOP_REASON,
    CanaryWorkerLifecycleError,
    CanaryWorkerLifecycleResultStore,
)


CANARY_WORKER_LIFECYCLE_PACKAGE_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_WORKER_LIFECYCLE_PACKAGE_V1"
)
LIFECYCLE_PACKAGE_VERIFIED: Final = "VERIFIED"
LIFECYCLE_PACKAGE_BLOCKED: Final = "BLOCK"
LIFECYCLE_PACKAGE_VERIFIED_CONCLUSION: Final = (
    "LOCAL_LIFECYCLE_PACKAGE_VERIFIED_PROVIDER_REVOCATION_MISSING"
)
LIFECYCLE_PACKAGE_BLOCKED_CONCLUSION: Final = (
    "LOCAL_LIFECYCLE_PACKAGE_INVALID"
)

_MAX_BUILD_MANIFEST_BYTES: Final = 1_048_576
_MAX_WORKER_ARTIFACT_BYTES: Final = 4_194_304
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_COMPONENTS: Final = (
    "launchContract",
    "buildManifest",
    "workerArtifact",
    "processEvidence",
    "workerIdentity",
    "stopLatch",
    "stopAcknowledgement",
    "lifecycleResult",
    "packageComposition",
)


class CanaryWorkerLifecyclePackageError(ValueError):
    pass


@dataclass(frozen=True)
class CanaryWorkerLifecyclePackagePolicy:
    expected_runtime_instance_id: str
    expected_account_binding_commitment: str
    expected_worker_build_sha256: str
    expected_worker_artifact_sha256: str
    expected_executable_path_sha256: str
    expected_lifecycle_result_sha256: str
    expected_process_observer_id: str
    expected_process_source: str
    expected_stop_controller_id: str
    expected_revocation_source: str
    max_evidence_age_seconds: float
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        for value, field in (
            (self.expected_runtime_instance_id, "runtime instance ID"),
            (self.expected_process_observer_id, "process observer ID"),
            (self.expected_process_source, "process source"),
            (self.expected_stop_controller_id, "stop controller ID"),
            (self.expected_revocation_source, "revocation source"),
        ):
            if (
                not isinstance(value, str)
                or not _IDENTIFIER.fullmatch(value.strip())
            ):
                raise CanaryWorkerLifecyclePackageError(
                    f"Expected {field} is invalid."
                )
        for value, field in (
            (
                self.expected_account_binding_commitment,
                "account binding",
            ),
            (self.expected_worker_build_sha256, "worker build"),
            (self.expected_worker_artifact_sha256, "worker artifact"),
            (
                self.expected_executable_path_sha256,
                "process executable",
            ),
            (
                self.expected_lifecycle_result_sha256,
                "lifecycle result",
            ),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise CanaryWorkerLifecyclePackageError(
                    f"Expected {field} SHA-256 is invalid."
                )
        if (
            not _is_finite_number(self.max_evidence_age_seconds)
            or self.max_evidence_age_seconds <= 0
            or self.max_evidence_age_seconds > 3_600
        ):
            raise CanaryWorkerLifecyclePackageError(
                "Maximum evidence age must be greater than zero and "
                "no more than 3600 seconds."
            )
        if (
            not _is_finite_number(self.max_future_skew_seconds)
            or self.max_future_skew_seconds < 0
            or self.max_future_skew_seconds > 60
        ):
            raise CanaryWorkerLifecyclePackageError(
                "Maximum future skew must be from zero to 60 seconds."
            )


@dataclass(frozen=True)
class CanaryWorkerLifecyclePackageFinding:
    component: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "component": self.component,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True)
class CanaryWorkerLifecyclePackageResult:
    status: str
    conclusion: str
    evaluated_at: str
    runtime_instance_id: str
    lifecycle_result_sha256: str | None
    component_statuses: tuple[tuple[str, str], ...]
    findings: tuple[CanaryWorkerLifecyclePackageFinding, ...]

    @property
    def local_package_verified(self) -> bool:
        return self.status == LIFECYCLE_PACKAGE_VERIFIED

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": (
                CANARY_WORKER_LIFECYCLE_PACKAGE_SCHEMA_VERSION
            ),
            "status": self.status,
            "conclusion": self.conclusion,
            "evaluatedAt": _canonical_timestamp(self.evaluated_at),
            "runtimeInstanceId": self.runtime_instance_id,
            "lifecycleResultSha256": self.lifecycle_result_sha256,
            "components": dict(self.component_statuses),
            "findings": [finding.to_dict() for finding in self.findings],
            "localPackageVerified": self.local_package_verified,
            "sourceProcessLaunchVerified": self.local_package_verified,
            "sourceProcessLaunchPerformed": (
                self.local_package_verified
            ),
            "sourceProcessMutationPerformed": (
                self.local_package_verified
            ),
            "sourceProcessStoppedVerified": self.local_package_verified,
            "sourceProcessTerminationPerformed": False,
            "sourceProcessSignalPerformed": False,
            "providerRevocationVerified": False,
            "providerRevocationRequired": True,
            "physicalStopDrillComplete": False,
            "verificationProcessMutationPerformed": False,
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


def verify_canary_worker_lifecycle_package(
    run_root: Path,
    *,
    evaluated_at: datetime,
    policy: CanaryWorkerLifecyclePackagePolicy,
) -> CanaryWorkerLifecyclePackageResult:
    """Revalidate a CANARY-017 package without changing any runtime state."""

    now = _require_aware_datetime(
        evaluated_at,
        field="package evaluation",
    )
    findings: list[CanaryWorkerLifecyclePackageFinding] = []

    def add(component: str, code: str, message: str) -> None:
        findings.append(
            CanaryWorkerLifecyclePackageFinding(
                component=component,
                code=code,
                message=message,
            )
        )

    root = Path(run_root)
    if root.is_symlink() or not root.is_dir():
        add(
            "packageComposition",
            "RUN_ROOT_INVALID",
            "The lifecycle package root is not a regular directory.",
        )
        return _result(
            now=now,
            policy=policy,
            lifecycle_result_sha256=None,
            findings=findings,
        )

    launch = _load(
        component="launchContract",
        missing_code="LAUNCH_CONTRACT_MISSING",
        invalid_code="LAUNCH_CONTRACT_INVALID",
        label="worker launch contract",
        loader=lambda: CanaryBrokerWorkerLaunchStore(root).load(),
        add=add,
    )
    build_manifest = _read_file(
        root / WORKER_BUILD_MANIFEST_FILENAME,
        component="buildManifest",
        invalid_code="BUILD_MANIFEST_INVALID",
        label="worker build manifest",
        maximum=_MAX_BUILD_MANIFEST_BYTES,
        add=add,
    )
    worker_artifact = _read_file(
        Path(__file__).resolve().parent
        / "schwab_canary_broker_worker.py",
        component="workerArtifact",
        invalid_code="WORKER_ARTIFACT_INVALID",
        label="worker artifact",
        maximum=_MAX_WORKER_ARTIFACT_BYTES,
        add=add,
    )
    process_store = CanaryProcessEvidenceStore(
        root / WORKER_PROCESS_EVIDENCE_DIRECTORY
    )
    target = _load(
        component="processEvidence",
        missing_code="PROCESS_TARGET_MISSING",
        invalid_code="PROCESS_EVIDENCE_INVALID",
        label="process target",
        loader=process_store.load_target,
        add=add,
    )
    records = _load_records(process_store, add=add)
    identity_store = CanaryWorkerIdentityStore(
        root / WORKER_IDENTITY_FILENAME
    )
    identity = _load(
        component="workerIdentity",
        missing_code="WORKER_IDENTITY_MISSING",
        invalid_code="WORKER_IDENTITY_INVALID",
        label="worker identity",
        loader=identity_store.load,
        add=add,
    )
    stop_request = _load(
        component="stopLatch",
        missing_code="STOP_LATCH_MISSING",
        invalid_code="STOP_LATCH_INVALID",
        label="stop latch",
        loader=lambda: CanaryStopLatchStore(
            root / WORKER_STOP_LATCH_FILENAME
        ).load(),
        add=add,
    )
    acknowledgement = _load(
        component="stopAcknowledgement",
        missing_code="STOP_ACKNOWLEDGEMENT_MISSING",
        invalid_code="STOP_ACKNOWLEDGEMENT_INVALID",
        label="stop acknowledgement",
        loader=lambda: CanaryWorkerStopAcknowledgementStore(root).load(),
        add=add,
    )
    lifecycle_result = _load(
        component="lifecycleResult",
        missing_code="LIFECYCLE_RESULT_MISSING",
        invalid_code="LIFECYCLE_RESULT_INVALID",
        label="lifecycle result",
        loader=lambda: CanaryWorkerLifecycleResultStore(root).load(),
        add=add,
    )

    if launch is not None:
        _match(
            component="launchContract",
            actual=launch.runtime_instance_id,
            expected=policy.expected_runtime_instance_id,
            code="LAUNCH_RUNTIME_MISMATCH",
            message="The launch runtime does not match policy.",
            add=add,
        )
        _match(
            component="launchContract",
            actual=launch.account_binding_commitment,
            expected=policy.expected_account_binding_commitment,
            code="LAUNCH_ACCOUNT_BINDING_MISMATCH",
            message="The launch account binding does not match policy.",
            add=add,
        )
        _match(
            component="launchContract",
            actual=launch.expected_worker_build_sha256,
            expected=policy.expected_worker_build_sha256,
            code="LAUNCH_BUILD_MISMATCH",
            message="The launch build does not match policy.",
            add=add,
        )
        _match(
            component="launchContract",
            actual=launch.expected_worker_artifact_sha256,
            expected=policy.expected_worker_artifact_sha256,
            code="LAUNCH_ARTIFACT_MISMATCH",
            message="The launch artifact does not match policy.",
            add=add,
        )

    if build_manifest is not None:
        _match(
            component="buildManifest",
            actual=hashlib.sha256(build_manifest).hexdigest(),
            expected=policy.expected_worker_build_sha256,
            code="BUILD_MANIFEST_MISMATCH",
            message="The build manifest bytes do not match policy.",
            add=add,
        )
    if worker_artifact is not None:
        _match(
            component="workerArtifact",
            actual=hashlib.sha256(worker_artifact).hexdigest(),
            expected=policy.expected_worker_artifact_sha256,
            code="WORKER_ARTIFACT_MISMATCH",
            message="The worker artifact bytes do not match policy.",
            add=add,
        )

    identity_binding = None
    if target is not None and identity is not None and records is not None:
        _match(
            component="processEvidence",
            actual=target.runtime_instance_id,
            expected=policy.expected_runtime_instance_id,
            code="PROCESS_RUNTIME_MISMATCH",
            message="The process target runtime does not match policy.",
            add=add,
        )
        _match(
            component="processEvidence",
            actual=target.executable_path_sha256,
            expected=policy.expected_executable_path_sha256,
            code="PROCESS_EXECUTABLE_MISMATCH",
            message="The process executable does not match policy.",
            add=add,
        )
        _match(
            component="processEvidence",
            actual=target.observer_id,
            expected=policy.expected_process_observer_id,
            code="PROCESS_OBSERVER_MISMATCH",
            message="The process observer does not match policy.",
            add=add,
        )
        _match(
            component="processEvidence",
            actual=target.source,
            expected=policy.expected_process_source,
            code="PROCESS_SOURCE_MISMATCH",
            message="The process source does not match policy.",
            add=add,
        )
        identity_binding = evaluate_canary_worker_identity_binding(
            identity_store=identity_store,
            process_store=process_store,
            policy=CanaryWorkerIdentityPolicy(
                expected_worker_build_sha256=(
                    policy.expected_worker_build_sha256
                ),
                expected_worker_artifact_sha256=(
                    policy.expected_worker_artifact_sha256
                ),
                expected_account_binding_commitment=(
                    policy.expected_account_binding_commitment
                ),
                expected_executable_path_sha256=(
                    policy.expected_executable_path_sha256
                ),
                expected_observer_id=(
                    policy.expected_process_observer_id
                ),
                expected_process_source=policy.expected_process_source,
                max_receipt_age_seconds=(
                    policy.max_evidence_age_seconds
                ),
                max_observation_age_seconds=(
                    policy.max_evidence_age_seconds
                ),
                max_future_skew_seconds=policy.max_future_skew_seconds,
            ),
            evaluated_at=now,
        )
        if identity_binding.status != WORKER_IDENTITY_BOUND_STOPPED:
            for finding in identity_binding.findings:
                add(
                    "workerIdentity",
                    finding.code,
                    finding.message,
                )
            if not identity_binding.findings:
                add(
                    "workerIdentity",
                    "WORKER_IDENTITY_NOT_STOPPED",
                    "The exact worker identity is not bound to a stopped lifecycle.",
                )

    if identity is not None:
        _match(
            component="workerIdentity",
            actual=identity.runtime_instance_id,
            expected=policy.expected_runtime_instance_id,
            code="IDENTITY_RUNTIME_MISMATCH",
            message="The identity runtime does not match policy.",
            add=add,
        )

    if stop_request is not None:
        _match(
            component="stopLatch",
            actual=stop_request.controller_id,
            expected=policy.expected_stop_controller_id,
            code="STOP_CONTROLLER_MISMATCH",
            message="The stop controller does not match policy.",
            add=add,
        )
        _match(
            component="stopLatch",
            actual=stop_request.account_binding_commitment,
            expected=policy.expected_account_binding_commitment,
            code="STOP_ACCOUNT_BINDING_MISMATCH",
            message="The stop account binding does not match policy.",
            add=add,
        )
        _match(
            component="stopLatch",
            actual=stop_request.reason_code,
            expected=LIFECYCLE_STOP_REASON,
            code="STOP_REASON_MISMATCH",
            message="The stop reason is not the frozen lifecycle reason.",
            add=add,
        )

    if acknowledgement is not None:
        _match(
            component="stopAcknowledgement",
            actual=acknowledgement.runtime_instance_id,
            expected=policy.expected_runtime_instance_id,
            code="ACK_RUNTIME_MISMATCH",
            message="The stop acknowledgement runtime does not match policy.",
            add=add,
        )
        _match(
            component="stopAcknowledgement",
            actual=acknowledgement.account_binding_commitment,
            expected=policy.expected_account_binding_commitment,
            code="ACK_ACCOUNT_BINDING_MISMATCH",
            message="The stop acknowledgement account binding does not match policy.",
            add=add,
        )

    lifecycle_result_sha256 = (
        lifecycle_result.result_sha256
        if lifecycle_result is not None
        else None
    )
    if lifecycle_result is not None:
        _match(
            component="lifecycleResult",
            actual=lifecycle_result.result_sha256,
            expected=policy.expected_lifecycle_result_sha256,
            code="LIFECYCLE_RESULT_MISMATCH",
            message="The lifecycle result does not match policy.",
            add=add,
        )
        _match(
            component="lifecycleResult",
            actual=lifecycle_result.runtime_instance_id,
            expected=policy.expected_runtime_instance_id,
            code="RESULT_RUNTIME_MISMATCH",
            message="The lifecycle result runtime does not match policy.",
            add=add,
        )
        _check_freshness(
            component="lifecycleResult",
            timestamp=lifecycle_result.completed_at,
            evaluated_at=now,
            policy=policy,
            label="lifecycle result",
            add=add,
        )

    if (
        lifecycle_result is not None
        and target is not None
        and identity is not None
        and stop_request is not None
        and acknowledgement is not None
        and identity_binding is not None
    ):
        expected_pairs = (
            (
                lifecycle_result.identity_receipt_id,
                identity.receipt_id,
                "RESULT_IDENTITY_MISMATCH",
                "The lifecycle result does not name the persisted identity receipt.",
            ),
            (
                lifecycle_result.process_target_sha256,
                target.target_sha256,
                "RESULT_PROCESS_TARGET_MISMATCH",
                "The lifecycle result does not name the persisted process target.",
            ),
            (
                lifecycle_result.process_evidence_chain_sha256,
                identity_binding.process_evidence_chain_sha256,
                "RESULT_PROCESS_CHAIN_MISMATCH",
                "The lifecycle result does not name the current process chain.",
            ),
            (
                lifecycle_result.stop_latch_sha256,
                stop_request.record_sha256,
                "RESULT_STOP_LATCH_MISMATCH",
                "The lifecycle result does not name the persisted stop latch.",
            ),
            (
                lifecycle_result.stop_acknowledgement_sha256,
                acknowledgement.acknowledgement_sha256,
                "RESULT_STOP_ACKNOWLEDGEMENT_MISMATCH",
                "The lifecycle result does not name the persisted "
                "stop acknowledgement.",
            ),
            (
                acknowledgement.worker_identity_receipt_sha256,
                identity.receipt_sha256,
                "ACK_IDENTITY_MISMATCH",
                "The stop acknowledgement does not name the persisted "
                "identity receipt.",
            ),
            (
                acknowledgement.process_target_sha256,
                target.target_sha256,
                "ACK_PROCESS_TARGET_MISMATCH",
                "The stop acknowledgement does not name the persisted process target.",
            ),
            (
                acknowledgement.latch_sha256,
                stop_request.record_sha256,
                "ACK_STOP_LATCH_MISMATCH",
                "The stop acknowledgement does not name the persisted stop latch.",
            ),
        )
        for actual, expected, code, message in expected_pairs:
            _match(
                component="packageComposition",
                actual=actual,
                expected=expected,
                code=code,
                message=message,
                add=add,
            )

        latest = records[-1] if records else None
        if latest is None:
            add(
                "processEvidence",
                "PROCESS_OBSERVATION_MISSING",
                "The process evidence package has no observations.",
            )
        else:
            stop_drill = evaluate_canary_stop_drill(
                stop_request=stop_request,
                runtime_acknowledgement=(
                    acknowledgement.to_stop_acknowledgement()
                ),
                process_observation=(
                    latest.evidence.to_stop_observation()
                ),
                revocation_observation=None,
                evaluated_at=now,
                policy=CanaryStopDrillPolicy(
                    expected_controller_id=(
                        policy.expected_stop_controller_id
                    ),
                    expected_process_observer_id=(
                        policy.expected_process_observer_id
                    ),
                    expected_process_source=(
                        policy.expected_process_source
                    ),
                    expected_revocation_source=(
                        policy.expected_revocation_source
                    ),
                    max_evidence_age_seconds=(
                        policy.max_evidence_age_seconds
                    ),
                    max_shutdown_latency_seconds=(
                        policy.max_evidence_age_seconds
                    ),
                    max_revocation_latency_seconds=(
                        policy.max_evidence_age_seconds
                    ),
                    max_future_skew_seconds=(
                        policy.max_future_skew_seconds
                    ),
                ),
            )
            stop_codes = tuple(
                finding.code for finding in stop_drill.findings
            )
            if (
                stop_drill.status != LIFECYCLE_PACKAGE_BLOCKED
                or stop_codes != (LIFECYCLE_REVOCATION_MISSING,)
            ):
                for finding in stop_drill.findings:
                    if finding.code != LIFECYCLE_REVOCATION_MISSING:
                        add(
                            "packageComposition",
                            finding.code,
                            finding.message,
                        )
                add(
                    "packageComposition",
                    "LOCAL_STOP_DRILL_STATE_INVALID",
                    "The local stop drill is not blocked solely on "
                    "provider revocation.",
                )
            completion = _parse_timestamp(
                lifecycle_result.completed_at,
                field="lifecycle completion",
            )
            latest_observed = _parse_timestamp(
                latest.evidence.observed_at,
                field="latest process observation",
            )
            acknowledged = _parse_timestamp(
                acknowledgement.acknowledged_at,
                field="stop acknowledgement",
            )
            requested = _parse_timestamp(
                stop_request.requested_at,
                field="stop request",
            )
            if completion < max(
                latest_observed,
                acknowledged,
                requested,
            ):
                add(
                    "packageComposition",
                    "RESULT_COMPLETION_CHRONOLOGY_INVALID",
                    "The lifecycle result predates supporting stop evidence.",
                )

    return _result(
        now=now,
        policy=policy,
        lifecycle_result_sha256=lifecycle_result_sha256,
        findings=findings,
    )


def _result(
    *,
    now: datetime,
    policy: CanaryWorkerLifecyclePackagePolicy,
    lifecycle_result_sha256: str | None,
    findings: list[CanaryWorkerLifecyclePackageFinding],
) -> CanaryWorkerLifecyclePackageResult:
    unique: list[CanaryWorkerLifecyclePackageFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.component, finding.code)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    statuses = tuple(
        (
            component,
            (
                LIFECYCLE_PACKAGE_BLOCKED
                if any(item.component == component for item in unique)
                else "PASS"
            ),
        )
        for component in _COMPONENTS
    )
    verified = not unique
    return CanaryWorkerLifecyclePackageResult(
        status=(
            LIFECYCLE_PACKAGE_VERIFIED
            if verified
            else LIFECYCLE_PACKAGE_BLOCKED
        ),
        conclusion=(
            LIFECYCLE_PACKAGE_VERIFIED_CONCLUSION
            if verified
            else LIFECYCLE_PACKAGE_BLOCKED_CONCLUSION
        ),
        evaluated_at=now.isoformat(),
        runtime_instance_id=policy.expected_runtime_instance_id,
        lifecycle_result_sha256=lifecycle_result_sha256,
        component_statuses=statuses,
        findings=tuple(unique),
    )


def _load(
    *,
    component: str,
    missing_code: str,
    invalid_code: str,
    label: str,
    loader,
    add,
):
    try:
        value = loader()
    except (
        CanaryBrokerWorkerError,
        CanaryProcessEvidenceError,
        CanaryStopEvidenceError,
        CanaryWorkerIdentityError,
        CanaryWorkerLifecycleError,
        OSError,
    ):
        add(
            component,
            invalid_code,
            f"The persisted {label} is invalid.",
        )
        return None
    if value is None:
        add(
            component,
            missing_code,
            f"The persisted {label} is missing.",
        )
    return value


def _load_records(
    store: CanaryProcessEvidenceStore,
    *,
    add,
):
    try:
        records = store.load_observations()
    except (CanaryProcessEvidenceError, OSError):
        add(
            "processEvidence",
            "PROCESS_EVIDENCE_INVALID",
            "The persisted process evidence chain is invalid.",
        )
        return None
    if not records:
        add(
            "processEvidence",
            "PROCESS_OBSERVATION_MISSING",
            "The persisted process evidence chain has no observations.",
        )
    return records


def _read_file(
    path: Path,
    *,
    component: str,
    invalid_code: str,
    label: str,
    maximum: int,
    add,
) -> bytes | None:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        size = path.stat().st_size
        if size <= 0 or size > maximum:
            raise OSError
        return path.read_bytes()
    except OSError:
        add(
            component,
            invalid_code,
            f"The {label} is missing or invalid.",
        )
        return None


def _match(
    *,
    component: str,
    actual: object,
    expected: object,
    code: str,
    message: str,
    add,
) -> None:
    if actual != expected:
        add(component, code, message)


def _check_freshness(
    *,
    component: str,
    timestamp: str,
    evaluated_at: datetime,
    policy: CanaryWorkerLifecyclePackagePolicy,
    label: str,
    add,
) -> None:
    observed = _parse_timestamp(timestamp, field=label)
    if (
        observed - evaluated_at
        > timedelta(seconds=policy.max_future_skew_seconds)
    ):
        add(
            component,
            "EVIDENCE_FROM_FUTURE",
            f"The {label} is later than policy permits.",
        )
    elif (
        evaluated_at - observed
    ).total_seconds() > policy.max_evidence_age_seconds:
        add(
            component,
            "EVIDENCE_STALE",
            f"The {label} is older than policy permits.",
        )


def _require_aware_datetime(
    value: datetime,
    *,
    field: str,
) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryWorkerLifecyclePackageError(
            f"{field} must be timezone-aware."
        )
    return value


def _parse_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CanaryWorkerLifecyclePackageError(
            f"{field} must be valid ISO-8601."
        ) from exc
    return _require_aware_datetime(parsed, field=field)


def _canonical_timestamp(value: str) -> str:
    return _parse_timestamp(value, field="timestamp").isoformat()


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )
