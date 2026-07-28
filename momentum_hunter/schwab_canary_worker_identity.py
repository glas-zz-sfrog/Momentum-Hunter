from __future__ import annotations

"""Immutable identity binding for a future supervised Schwab canary worker."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Final

from momentum_hunter.schwab_canary_process_evidence import (
    CanaryProcessEvidenceStore,
)
from momentum_hunter.schwab_canary_process_observer import (
    CanaryProcessTarget,
)


CANARY_WORKER_IDENTITY_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_WORKER_IDENTITY_V1"
)
CANARY_WORKER_ROLE: Final = "SUPERVISED_SCHWAB_CANARY_WORKER"
WORKER_IDENTITY_BOUND_RUNNING: Final = "BOUND_RUNNING"
WORKER_IDENTITY_BOUND_STOPPED: Final = "BOUND_STOPPED"
WORKER_IDENTITY_BLOCKED: Final = "BLOCKED"

_MAX_RECEIPT_BYTES: Final = 32_768
_MAX_BUILD_MANIFEST_BYTES: Final = 1_048_576
_MAX_WORKER_ARTIFACT_BYTES: Final = 4_194_304
_MAX_STARTUP_BINDING_DELAY = timedelta(seconds=30)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_KEYS: Final = frozenset(
    {
        "schemaVersion",
        "recordType",
        "receiptId",
        "workerRole",
        "runtimeInstanceId",
        "workerBuildSha256",
        "workerArtifactSha256",
        "accountBindingCommitment",
        "processTargetSha256",
        "executablePathSha256",
        "issuedAt",
        "receiptSha256",
        "identitySource",
        "oneWay",
        "replaceSupported",
        "clearSupported",
        "providerEvidence",
        "runtimeObserved",
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


class CanaryWorkerIdentityError(ValueError):
    pass


class CanaryWorkerIdentityConflict(CanaryWorkerIdentityError):
    pass


@dataclass(frozen=True)
class CanaryWorkerIdentityPolicy:
    expected_worker_build_sha256: str
    expected_worker_artifact_sha256: str
    expected_account_binding_commitment: str
    expected_executable_path_sha256: str
    expected_observer_id: str
    expected_process_source: str
    max_receipt_age_seconds: float = 300.0
    max_observation_age_seconds: float = 60.0
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        for value, field in (
            (self.expected_worker_build_sha256, "worker build"),
            (self.expected_worker_artifact_sha256, "worker artifact"),
            (
                self.expected_account_binding_commitment,
                "account binding",
            ),
            (
                self.expected_executable_path_sha256,
                "process executable",
            ),
        ):
            _require_sha256(value, field=field)
        _require_identifier(
            self.expected_observer_id,
            field="observer ID",
        )
        _require_identifier(
            self.expected_process_source,
            field="process source",
        )
        _require_finite_range(
            self.max_receipt_age_seconds,
            field="maximum receipt age",
            minimum=0.001,
            maximum=3_600.0,
        )
        _require_finite_range(
            self.max_observation_age_seconds,
            field="maximum observation age",
            minimum=0.001,
            maximum=3_600.0,
        )
        _require_finite_range(
            self.max_future_skew_seconds,
            field="maximum future skew",
            minimum=0.0,
            maximum=60.0,
        )


@dataclass(frozen=True, repr=False)
class CanaryWorkerIdentityReceipt:
    runtime_instance_id: str
    worker_build_sha256: str
    worker_artifact_sha256: str
    account_binding_commitment: str
    process_target_sha256: str
    executable_path_sha256: str
    issued_at: str
    worker_role: str = CANARY_WORKER_ROLE

    def __post_init__(self) -> None:
        if self.worker_role != CANARY_WORKER_ROLE:
            raise CanaryWorkerIdentityError(
                "Canary worker role is unsupported."
            )
        _require_identifier(
            self.runtime_instance_id,
            field="runtime instance ID",
        )
        for value, field in (
            (self.worker_build_sha256, "worker build"),
            (self.worker_artifact_sha256, "worker artifact"),
            (self.account_binding_commitment, "account binding"),
            (self.process_target_sha256, "process target"),
            (self.executable_path_sha256, "process executable"),
        ):
            _require_sha256(value, field=field)
        _require_timestamp(self.issued_at, field="identity receipt")

    @property
    def receipt_sha256(self) -> str:
        return _sha256(self._unsigned_payload())

    @property
    def receipt_id(self) -> str:
        return f"canary-worker-identity-{self.receipt_sha256[:24]}"

    def _unsigned_payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_WORKER_IDENTITY_SCHEMA_VERSION,
            "recordType": "CANARY_WORKER_IDENTITY_RECEIPT",
            "workerRole": self.worker_role,
            "runtimeInstanceId": self.runtime_instance_id,
            "workerBuildSha256": self.worker_build_sha256,
            "workerArtifactSha256": self.worker_artifact_sha256,
            "accountBindingCommitment": self.account_binding_commitment,
            "processTargetSha256": self.process_target_sha256,
            "executablePathSha256": self.executable_path_sha256,
            "issuedAt": _canonical_timestamp(self.issued_at),
            "identitySource": "WORKER_STARTUP_ARTIFACT_BINDING",
            "oneWay": True,
            "replaceSupported": False,
            "clearSupported": False,
            "providerEvidence": False,
            "runtimeObserved": False,
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
            "receiptId": self.receipt_id,
            "receiptSha256": self.receipt_sha256,
        }

    def __repr__(self) -> str:
        return (
            "CanaryWorkerIdentityReceipt("
            f"receipt_id={self.receipt_id!r}, "
            f"runtime_instance_id={self.runtime_instance_id!r}, "
            f"process_target_sha256={self.process_target_sha256!r})"
        )


@dataclass(frozen=True)
class CanaryWorkerIdentityFinding:
    code: str
    message: str

    def __post_init__(self) -> None:
        _require_identifier(self.code, field="finding code")
        if not isinstance(self.message, str) or not self.message.strip():
            raise CanaryWorkerIdentityError(
                "Worker identity finding message is required."
            )

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CanaryWorkerIdentityBindingResult:
    status: str
    evaluated_at: str
    receipt_id: str | None
    process_target_sha256: str | None
    process_evidence_chain_sha256: str | None
    latest_process_running: bool | None
    findings: tuple[CanaryWorkerIdentityFinding, ...]

    @property
    def identity_binding_verified(self) -> bool:
        return self.status in {
            WORKER_IDENTITY_BOUND_RUNNING,
            WORKER_IDENTITY_BOUND_STOPPED,
        }

    @property
    def stop_lifecycle_observed(self) -> bool:
        return self.status == WORKER_IDENTITY_BOUND_STOPPED

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_WORKER_IDENTITY_SCHEMA_VERSION,
            "status": self.status,
            "evaluatedAt": _canonical_timestamp(self.evaluated_at),
            "receiptId": self.receipt_id,
            "processTargetSha256": self.process_target_sha256,
            "processEvidenceChainSha256": (
                self.process_evidence_chain_sha256
            ),
            "latestProcessRunning": self.latest_process_running,
            "findings": [finding.to_dict() for finding in self.findings],
            "identityBindingVerified": self.identity_binding_verified,
            "stopLifecycleObserved": self.stop_lifecycle_observed,
            "runtimeAcknowledgementVerified": False,
            "providerRevocationVerified": False,
            "physicalStopDrillComplete": False,
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


class CanaryWorkerIdentityStore:
    """Write one worker identity receipt without replace or clear support."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def persist(
        self,
        receipt: CanaryWorkerIdentityReceipt,
    ) -> CanaryWorkerIdentityReceipt:
        encoded = _encode(receipt.to_dict())
        if len(encoded) > _MAX_RECEIPT_BYTES:
            raise CanaryWorkerIdentityError(
                "Canary worker identity receipt exceeds the size limit."
            )
        if self.path.is_symlink():
            raise CanaryWorkerIdentityError(
                "Canary worker identity receipt cannot be a symlink."
            )
        _prepare_parent(self.path.parent)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            try:
                existing = self.load()
            except CanaryWorkerIdentityError as exc:
                raise CanaryWorkerIdentityConflict(
                    "A different or invalid worker identity already exists."
                ) from exc
            if existing == receipt:
                return existing
            raise CanaryWorkerIdentityConflict(
                "A different or invalid worker identity already exists."
            ) from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # Partial evidence remains fail-closed and is never removed here.
            raise
        persisted = self.load()
        if persisted != receipt:
            raise CanaryWorkerIdentityError(
                "Persisted worker identity receipt failed validation."
            )
        return persisted

    def load(self) -> CanaryWorkerIdentityReceipt | None:
        if self.path.parent.is_symlink():
            raise CanaryWorkerIdentityError(
                "Canary worker identity parent cannot be a symlink."
            )
        if (
            self.path.parent.exists()
            and not self.path.parent.is_dir()
        ):
            raise CanaryWorkerIdentityError(
                "Canary worker identity parent must be a regular directory."
            )
        if self.path.is_symlink():
            raise CanaryWorkerIdentityError(
                "Canary worker identity receipt must be a regular file."
            )
        if not self.path.exists():
            return None
        if not self.path.is_file():
            raise CanaryWorkerIdentityError(
                "Canary worker identity receipt must be a regular file."
            )
        size = self.path.stat().st_size
        if size <= 0 or size > _MAX_RECEIPT_BYTES:
            raise CanaryWorkerIdentityError(
                "Canary worker identity receipt has an invalid size."
            )
        try:
            payload = json.loads(self.path.read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanaryWorkerIdentityError(
                "Canary worker identity receipt is unreadable or malformed."
            ) from exc
        if not isinstance(payload, dict):
            raise CanaryWorkerIdentityError(
                "Canary worker identity receipt must contain an object."
            )
        return _parse_receipt(payload)


def build_canary_worker_identity_receipt(
    target: CanaryProcessTarget,
    *,
    runtime_build_manifest: bytes,
    worker_artifact: bytes,
    account_binding_commitment: str,
    issued_at: datetime,
) -> CanaryWorkerIdentityReceipt:
    build_bytes = _require_bounded_bytes(
        runtime_build_manifest,
        field="runtime build manifest",
        maximum=_MAX_BUILD_MANIFEST_BYTES,
    )
    artifact_bytes = _require_bounded_bytes(
        worker_artifact,
        field="worker artifact",
        maximum=_MAX_WORKER_ARTIFACT_BYTES,
    )
    normalized_issued_at = _require_aware_datetime(
        issued_at,
        field="identity receipt",
    )
    process_created_at = _require_timestamp(
        target.process_created_at,
        field="target process creation",
    )
    target_captured_at = _require_timestamp(
        target.captured_at,
        field="target capture",
    )
    if normalized_issued_at < process_created_at:
        raise CanaryWorkerIdentityError(
            "Worker identity receipt predates process creation."
        )
    if normalized_issued_at - target_captured_at > _MAX_STARTUP_BINDING_DELAY:
        raise CanaryWorkerIdentityError(
            "Worker identity receipt is too late to bind startup."
        )
    return CanaryWorkerIdentityReceipt(
        runtime_instance_id=target.runtime_instance_id,
        worker_build_sha256=hashlib.sha256(build_bytes).hexdigest(),
        worker_artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        account_binding_commitment=_require_sha256(
            account_binding_commitment,
            field="account binding",
        ),
        process_target_sha256=target.target_sha256,
        executable_path_sha256=target.executable_path_sha256,
        issued_at=normalized_issued_at.isoformat(),
    )


def evaluate_canary_worker_identity_binding(
    *,
    identity_store: CanaryWorkerIdentityStore,
    process_store: CanaryProcessEvidenceStore,
    policy: CanaryWorkerIdentityPolicy,
    evaluated_at: datetime,
) -> CanaryWorkerIdentityBindingResult:
    now = _require_aware_datetime(
        evaluated_at,
        field="worker identity evaluation",
    )
    findings: list[CanaryWorkerIdentityFinding] = []
    receipt = identity_store.load()
    target = process_store.load_target()
    records = process_store.load_observations()

    if receipt is None:
        findings.append(
            CanaryWorkerIdentityFinding(
                "WORKER_IDENTITY_MISSING",
                "The broker-worker identity receipt is missing.",
            )
        )
    if target is None:
        findings.append(
            CanaryWorkerIdentityFinding(
                "PROCESS_TARGET_MISSING",
                "The persisted broker-worker process target is missing.",
            )
        )
    if receipt is not None:
        _evaluate_receipt_policy(
            receipt=receipt,
            policy=policy,
            evaluated_at=now,
            findings=findings,
        )
    if receipt is not None and target is not None:
        _evaluate_target_binding(
            receipt=receipt,
            target=target,
            policy=policy,
            findings=findings,
        )

    latest_running = (
        records[-1].evidence.process_running if records else None
    )
    if not records:
        findings.append(
            CanaryWorkerIdentityFinding(
                "PROCESS_OBSERVATION_MISSING",
                "No independent process-liveness observation is persisted.",
            )
        )
    elif latest_running is None:
        findings.append(
            CanaryWorkerIdentityFinding(
                "PROCESS_OBSERVATION_UNAVAILABLE",
                "The latest independent process observation is unavailable.",
            )
        )
    elif latest_running is False and not any(
        record.evidence.process_running is True for record in records
    ):
        findings.append(
            CanaryWorkerIdentityFinding(
                "RUNNING_OBSERVATION_MISSING",
                "A stopped lifecycle requires a prior running observation.",
            )
        )
    if records:
        latest_observed_at = _require_timestamp(
            records[-1].evidence.observed_at,
            field="latest process observation",
        )
        future_skew = timedelta(seconds=policy.max_future_skew_seconds)
        if latest_observed_at - now > future_skew:
            findings.append(
                CanaryWorkerIdentityFinding(
                    "PROCESS_OBSERVATION_FROM_FUTURE",
                    "Latest process evidence is later than the evaluation clock.",
                )
            )
        if (
            now - latest_observed_at
        ).total_seconds() > policy.max_observation_age_seconds:
            findings.append(
                CanaryWorkerIdentityFinding(
                    "PROCESS_OBSERVATION_STALE",
                    "Latest process evidence is older than policy permits.",
                )
            )
        if receipt is not None:
            issued_at = _require_timestamp(
                receipt.issued_at,
                field="identity receipt",
            )
            running_after_identity = any(
                record.evidence.process_running is True
                and _require_timestamp(
                    record.evidence.observed_at,
                    field="running process observation",
                )
                >= issued_at - future_skew
                for record in records
            )
            if not running_after_identity:
                findings.append(
                    CanaryWorkerIdentityFinding(
                        "BOUND_RUNNING_OBSERVATION_MISSING",
                        "No independent running observation binds this receipt.",
                    )
                )

    process_chain_sha256 = (
        _sha256(
            {
                "targetSha256": target.target_sha256,
                "recordSha256": [
                    record.record_sha256 for record in records
                ],
            }
        )
        if target is not None
        else None
    )
    unique_findings = _deduplicate_findings(findings)
    if unique_findings:
        status = WORKER_IDENTITY_BLOCKED
    elif latest_running is True:
        status = WORKER_IDENTITY_BOUND_RUNNING
    else:
        status = WORKER_IDENTITY_BOUND_STOPPED
    return CanaryWorkerIdentityBindingResult(
        status=status,
        evaluated_at=now.isoformat(),
        receipt_id=receipt.receipt_id if receipt else None,
        process_target_sha256=(
            target.target_sha256 if target is not None else None
        ),
        process_evidence_chain_sha256=process_chain_sha256,
        latest_process_running=latest_running,
        findings=unique_findings,
    )


def _evaluate_receipt_policy(
    *,
    receipt: CanaryWorkerIdentityReceipt,
    policy: CanaryWorkerIdentityPolicy,
    evaluated_at: datetime,
    findings: list[CanaryWorkerIdentityFinding],
) -> None:
    checks = (
        (
            receipt.worker_build_sha256,
            policy.expected_worker_build_sha256,
            "WORKER_BUILD_MISMATCH",
            "Worker build identity does not match release policy.",
        ),
        (
            receipt.worker_artifact_sha256,
            policy.expected_worker_artifact_sha256,
            "WORKER_ARTIFACT_MISMATCH",
            "Worker artifact identity does not match release policy.",
        ),
        (
            receipt.account_binding_commitment,
            policy.expected_account_binding_commitment,
            "ACCOUNT_BINDING_MISMATCH",
            "Worker identity references a different account binding.",
        ),
        (
            receipt.executable_path_sha256,
            policy.expected_executable_path_sha256,
            "EXECUTABLE_IDENTITY_MISMATCH",
            "Worker process executable does not match release policy.",
        ),
    )
    for actual, expected, code, message in checks:
        if actual != expected:
            findings.append(CanaryWorkerIdentityFinding(code, message))
    issued_at = _require_timestamp(
        receipt.issued_at,
        field="identity receipt",
    )
    future_skew = timedelta(seconds=policy.max_future_skew_seconds)
    if issued_at - evaluated_at > future_skew:
        findings.append(
            CanaryWorkerIdentityFinding(
                "IDENTITY_RECEIPT_FROM_FUTURE",
                "Worker identity receipt is later than the evaluation clock.",
            )
        )
    age = (evaluated_at - issued_at).total_seconds()
    if age > policy.max_receipt_age_seconds:
        findings.append(
            CanaryWorkerIdentityFinding(
                "IDENTITY_RECEIPT_STALE",
                "Worker identity receipt is older than release policy permits.",
            )
        )


def _evaluate_target_binding(
    *,
    receipt: CanaryWorkerIdentityReceipt,
    target: CanaryProcessTarget,
    policy: CanaryWorkerIdentityPolicy,
    findings: list[CanaryWorkerIdentityFinding],
) -> None:
    checks = (
        (
            receipt.runtime_instance_id,
            target.runtime_instance_id,
            "RUNTIME_INSTANCE_MISMATCH",
            "Worker receipt and process target use different runtime identities.",
        ),
        (
            receipt.process_target_sha256,
            target.target_sha256,
            "PROCESS_TARGET_MISMATCH",
            "Worker receipt references a different process target.",
        ),
        (
            receipt.executable_path_sha256,
            target.executable_path_sha256,
            "TARGET_EXECUTABLE_MISMATCH",
            "Worker receipt and process target use different executables.",
        ),
        (
            target.observer_id,
            policy.expected_observer_id,
            "PROCESS_OBSERVER_MISMATCH",
            "Process target came from an unexpected observer.",
        ),
        (
            target.source,
            policy.expected_process_source,
            "PROCESS_SOURCE_MISMATCH",
            "Process target came from an unexpected source.",
        ),
    )
    for actual, expected, code, message in checks:
        if actual != expected:
            findings.append(CanaryWorkerIdentityFinding(code, message))
    issued_at = _require_timestamp(
        receipt.issued_at,
        field="identity receipt",
    )
    process_created_at = _require_timestamp(
        target.process_created_at,
        field="target process creation",
    )
    captured_at = _require_timestamp(
        target.captured_at,
        field="target capture",
    )
    if issued_at < process_created_at:
        findings.append(
            CanaryWorkerIdentityFinding(
                "IDENTITY_RECEIPT_BEFORE_PROCESS",
                "Worker identity receipt predates process creation.",
            )
        )
    if issued_at - captured_at > _MAX_STARTUP_BINDING_DELAY:
        findings.append(
            CanaryWorkerIdentityFinding(
                "IDENTITY_RECEIPT_LATE",
                "Worker identity receipt is too late to bind startup.",
            )
        )


def _parse_receipt(
    payload: dict[str, object],
) -> CanaryWorkerIdentityReceipt:
    if set(payload) != _RECEIPT_KEYS:
        raise CanaryWorkerIdentityError(
            "Canary worker identity receipt fields are invalid."
        )
    if (
        payload["schemaVersion"] != CANARY_WORKER_IDENTITY_SCHEMA_VERSION
        or payload["recordType"] != "CANARY_WORKER_IDENTITY_RECEIPT"
        or payload["identitySource"] != "WORKER_STARTUP_ARTIFACT_BINDING"
        or payload["oneWay"] is not True
        or payload["replaceSupported"] is not False
        or payload["clearSupported"] is not False
        or payload["providerEvidence"] is not False
        or payload["runtimeObserved"] is not False
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
        raise CanaryWorkerIdentityError(
            "Canary worker identity safety metadata is invalid."
        )
    try:
        receipt = CanaryWorkerIdentityReceipt(
            worker_role=_require_string(
                payload["workerRole"],
                field="workerRole",
            ),
            runtime_instance_id=_require_string(
                payload["runtimeInstanceId"],
                field="runtimeInstanceId",
            ),
            worker_build_sha256=_require_string(
                payload["workerBuildSha256"],
                field="workerBuildSha256",
            ),
            worker_artifact_sha256=_require_string(
                payload["workerArtifactSha256"],
                field="workerArtifactSha256",
            ),
            account_binding_commitment=_require_string(
                payload["accountBindingCommitment"],
                field="accountBindingCommitment",
            ),
            process_target_sha256=_require_string(
                payload["processTargetSha256"],
                field="processTargetSha256",
            ),
            executable_path_sha256=_require_string(
                payload["executablePathSha256"],
                field="executablePathSha256",
            ),
            issued_at=_require_string(
                payload["issuedAt"],
                field="issuedAt",
            ),
        )
    except (TypeError, CanaryWorkerIdentityError) as exc:
        raise CanaryWorkerIdentityError(
            "Canary worker identity receipt content is invalid."
        ) from exc
    if (
        payload["receiptId"] != receipt.receipt_id
        or payload["receiptSha256"] != receipt.receipt_sha256
        or payload != receipt.to_dict()
    ):
        raise CanaryWorkerIdentityError(
            "Canary worker identity receipt hash is invalid."
        )
    return receipt


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
        raise CanaryWorkerIdentityError(
            "Canary worker identity receipt is not serializable."
        ) from exc
    return (rendered + "\n").encode("ascii")


def _prepare_parent(parent: Path) -> None:
    if parent.is_symlink():
        raise CanaryWorkerIdentityError(
            "Canary worker identity parent cannot be a symlink."
        )
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CanaryWorkerIdentityError(
            "Canary worker identity parent cannot be created safely."
        ) from exc
    if parent.is_symlink() or not parent.is_dir():
        raise CanaryWorkerIdentityError(
            "Canary worker identity parent must be a regular directory."
        )


def _require_bounded_bytes(
    value: object,
    *,
    field: str,
    maximum: int,
) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > maximum:
        raise CanaryWorkerIdentityError(
            f"{field.capitalize()} must be non-empty bounded bytes."
        )
    return value


def _require_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CanaryWorkerIdentityError(f"{field.capitalize()} is invalid.")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise CanaryWorkerIdentityError(
            f"{field.capitalize()} SHA-256 is invalid."
        )
    return value


def _require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise CanaryWorkerIdentityError(f"{field} must be a string.")
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
        raise CanaryWorkerIdentityError(f"{field.capitalize()} is invalid.")
    return float(value)


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CanaryWorkerIdentityError(
            f"{field.capitalize()} must be timezone-aware."
        )
    return value


def _require_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise CanaryWorkerIdentityError(
            f"{field.capitalize()} timestamp is invalid."
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanaryWorkerIdentityError(
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


def _deduplicate_findings(
    findings: list[CanaryWorkerIdentityFinding],
) -> tuple[CanaryWorkerIdentityFinding, ...]:
    seen: set[str] = set()
    result: list[CanaryWorkerIdentityFinding] = []
    for finding in findings:
        if finding.code not in seen:
            seen.add(finding.code)
            result.append(finding)
    return tuple(result)
