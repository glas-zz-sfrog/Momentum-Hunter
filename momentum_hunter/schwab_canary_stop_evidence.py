from __future__ import annotations

"""One-way stop latch and nonmutating canary shutdown drill evidence."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
from typing import Final


CANARY_STOP_SCHEMA_VERSION: Final = "SCHWAB_CANARY_STOP_EVIDENCE_V1"
STOP_REQUESTED: Final = "STOP_REQUESTED"
RUNTIME_STOPPED: Final = "STOPPED"
CREDENTIAL_REVOKED: Final = "REVOKED"
_SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_LATCH_BYTES = 16_384


class CanaryStopEvidenceError(ValueError):
    pass


class CanaryStopLatchConflict(CanaryStopEvidenceError):
    pass


@dataclass(frozen=True, repr=False)
class CanaryStopRequest:
    latch_id: str
    controller_id: str
    account_binding_commitment: str
    requested_at: str
    reason_code: str
    state: str = STOP_REQUESTED

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "latch_id",
            _normalize_identifier(self.latch_id, field="latch ID"),
        )
        object.__setattr__(
            self,
            "controller_id",
            _normalize_identifier(self.controller_id, field="controller ID"),
        )
        object.__setattr__(
            self,
            "reason_code",
            _normalize_identifier(self.reason_code, field="reason code"),
        )
        object.__setattr__(
            self,
            "account_binding_commitment",
            _normalize_commitment(self.account_binding_commitment),
        )
        if self.state != STOP_REQUESTED:
            raise CanaryStopEvidenceError(
                "A canary stop request must remain STOP_REQUESTED."
            )
        _require_timestamp(self.requested_at, field="stop request")

    @property
    def record_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.payload()).encode("utf-8")).hexdigest()

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_STOP_SCHEMA_VERSION,
            "latchId": self.latch_id,
            "controllerId": self.controller_id,
            "accountBindingCommitment": self.account_binding_commitment,
            "requestedAt": _canonical_timestamp(self.requested_at),
            "reasonCode": self.reason_code,
            "state": self.state,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.payload(),
            "recordSha256": self.record_sha256,
            "oneWay": True,
            "clearSupported": False,
            "transmitting": False,
        }

    def redacted_dict(self) -> dict[str, object]:
        payload = self.to_dict()
        payload["accountBindingCommitment"] = _commitment_tag(
            self.account_binding_commitment
        )
        return payload

    def __repr__(self) -> str:
        return (
            "CanaryStopRequest("
            f"latch_id={self.latch_id!r}, controller_id={self.controller_id!r}, "
            f"account_binding={_commitment_tag(self.account_binding_commitment)!r}, "
            f"requested_at={self.requested_at!r}, "
            f"reason_code={self.reason_code!r}, state={self.state!r})"
        )


class CanaryStopLatchStore:
    """Write-once stop request store with intentionally no clear operation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def engage(self, request: CanaryStopRequest) -> CanaryStopRequest:
        encoded = (
            json.dumps(
                request.to_dict(),
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if len(encoded) > _MAX_LATCH_BYTES:
            raise CanaryStopEvidenceError("Canary stop request exceeds the size limit.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            try:
                existing = self.load()
            except CanaryStopEvidenceError as exc:
                raise CanaryStopLatchConflict(
                    "A different or invalid canary stop latch already exists."
                ) from exc
            if existing == request:
                return existing
            raise CanaryStopLatchConflict(
                "A different or invalid canary stop latch already exists."
            ) from None
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            # A partial latch remains fail-closed and must not be silently removed.
            raise
        persisted = self.load()
        if persisted != request:
            raise CanaryStopEvidenceError(
                "Persisted canary stop request failed byte-level validation."
            )
        return persisted

    def load(self) -> CanaryStopRequest | None:
        if not self.path.exists():
            return None
        if not self.path.is_file() or self.path.is_symlink():
            raise CanaryStopEvidenceError(
                "Canary stop latch must be a regular non-symlink file."
            )
        size = self.path.stat().st_size
        if size <= 0 or size > _MAX_LATCH_BYTES:
            raise CanaryStopEvidenceError(
                "Canary stop latch has an invalid file size."
            )
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CanaryStopEvidenceError(
                "Canary stop latch is unreadable or malformed."
            ) from exc
        if not isinstance(payload, dict):
            raise CanaryStopEvidenceError(
                "Canary stop latch must contain a JSON object."
            )
        expected_keys = {
            "schemaVersion",
            "latchId",
            "controllerId",
            "accountBindingCommitment",
            "requestedAt",
            "reasonCode",
            "state",
            "recordSha256",
            "oneWay",
            "clearSupported",
            "transmitting",
        }
        if set(payload) != expected_keys:
            raise CanaryStopEvidenceError(
                "Canary stop latch fields do not match the frozen schema."
            )
        if payload["schemaVersion"] != CANARY_STOP_SCHEMA_VERSION:
            raise CanaryStopEvidenceError(
                "Canary stop latch schema version is unsupported."
            )
        if (
            payload["oneWay"] is not True
            or payload["clearSupported"] is not False
            or payload["transmitting"] is not False
        ):
            raise CanaryStopEvidenceError(
                "Canary stop latch safety flags are invalid."
            )
        request = CanaryStopRequest(
            latch_id=str(payload["latchId"]),
            controller_id=str(payload["controllerId"]),
            account_binding_commitment=str(
                payload["accountBindingCommitment"]
            ),
            requested_at=str(payload["requestedAt"]),
            reason_code=str(payload["reasonCode"]),
            state=str(payload["state"]),
        )
        if payload["recordSha256"] != request.record_sha256:
            raise CanaryStopEvidenceError(
                "Canary stop latch hash does not match its content."
            )
        return request


@dataclass(frozen=True, repr=False)
class CanaryRuntimeStopAcknowledgement:
    latch_sha256: str
    runtime_instance_id: str
    account_binding_commitment: str
    acknowledged_at: str
    state: str
    execution_disabled: bool
    outstanding_command_count: int

    def __repr__(self) -> str:
        return (
            "CanaryRuntimeStopAcknowledgement("
            f"latch_sha256={self.latch_sha256!r}, "
            f"runtime_instance_id={self.runtime_instance_id!r}, "
            f"account_binding={_commitment_tag(self.account_binding_commitment)!r}, "
            f"acknowledged_at={self.acknowledged_at!r}, state={self.state!r}, "
            f"execution_disabled={self.execution_disabled!r}, "
            f"outstanding_command_count={self.outstanding_command_count!r})"
        )


@dataclass(frozen=True)
class CanaryIndependentProcessObservation:
    observer_id: str
    source: str
    runtime_instance_id: str
    observed_at: str
    process_running: bool


@dataclass(frozen=True, repr=False)
class CanaryCredentialRevocationObservation:
    source: str
    account_binding_commitment: str
    observed_at: str
    credential_state: str

    def __repr__(self) -> str:
        return (
            "CanaryCredentialRevocationObservation("
            f"source={self.source!r}, "
            f"account_binding={_commitment_tag(self.account_binding_commitment)!r}, "
            f"observed_at={self.observed_at!r}, "
            f"credential_state={self.credential_state!r})"
        )


@dataclass(frozen=True)
class CanaryStopDrillPolicy:
    expected_controller_id: str
    expected_process_observer_id: str
    expected_process_source: str
    expected_revocation_source: str
    max_evidence_age_seconds: float
    max_shutdown_latency_seconds: float
    max_revocation_latency_seconds: float
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        for attribute, field in (
            ("expected_controller_id", "controller ID"),
            ("expected_process_observer_id", "process observer ID"),
            ("expected_process_source", "process evidence source"),
            ("expected_revocation_source", "revocation evidence source"),
        ):
            object.__setattr__(
                self,
                attribute,
                _normalize_identifier(getattr(self, attribute), field=field),
            )
        for value, field in (
            (self.max_evidence_age_seconds, "Maximum evidence age"),
            (self.max_shutdown_latency_seconds, "Maximum shutdown latency"),
            (self.max_revocation_latency_seconds, "Maximum revocation latency"),
        ):
            if not _is_positive_number(value):
                raise CanaryStopEvidenceError(
                    f"{field} must be finite and greater than zero."
                )
        if (
            not _is_finite_number(self.max_future_skew_seconds)
            or self.max_future_skew_seconds < 0
        ):
            raise CanaryStopEvidenceError(
                "Maximum future clock skew must be finite and non-negative."
            )


@dataclass(frozen=True)
class CanaryStopFinding:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CanaryStopDrillResult:
    status: str
    conclusion: str
    evaluated_at: str
    latch_id: str | None
    latch_sha256: str | None
    runtime_instance_id: str | None
    process_running: bool | None
    credential_state: str | None
    findings: tuple[CanaryStopFinding, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_STOP_SCHEMA_VERSION,
            "status": self.status,
            "conclusion": self.conclusion,
            "evaluatedAt": self.evaluated_at,
            "latchId": self.latch_id,
            "latchSha256": self.latch_sha256,
            "runtimeInstanceId": self.runtime_instance_id,
            "processRunning": self.process_running,
            "credentialState": self.credential_state,
            "findings": [finding.to_dict() for finding in self.findings],
            "executionPermit": False,
            "latchClearSupported": False,
            "credentialMutationPerformed": False,
            "processMutationPerformed": False,
            "orderTransmission": "UNAVAILABLE",
        }


def evaluate_canary_stop_drill(
    *,
    stop_request: CanaryStopRequest | None,
    runtime_acknowledgement: CanaryRuntimeStopAcknowledgement | None,
    process_observation: CanaryIndependentProcessObservation | None,
    revocation_observation: CanaryCredentialRevocationObservation | None,
    evaluated_at: datetime,
    policy: CanaryStopDrillPolicy,
) -> CanaryStopDrillResult:
    evaluation_time = _require_aware_datetime(
        evaluated_at,
        field="evaluation",
    )
    findings: list[CanaryStopFinding] = []
    request_time = _validate_stop_request(
        stop_request,
        evaluation_time=evaluation_time,
        policy=policy,
        findings=findings,
    )
    acknowledgement_time = _validate_acknowledgement(
        stop_request=stop_request,
        acknowledgement=runtime_acknowledgement,
        request_time=request_time,
        evaluation_time=evaluation_time,
        policy=policy,
        findings=findings,
    )
    _validate_process_observation(
        acknowledgement=runtime_acknowledgement,
        process_observation=process_observation,
        request_time=request_time,
        acknowledgement_time=acknowledgement_time,
        evaluation_time=evaluation_time,
        policy=policy,
        findings=findings,
    )
    _validate_revocation_observation(
        stop_request=stop_request,
        revocation=revocation_observation,
        request_time=request_time,
        evaluation_time=evaluation_time,
        policy=policy,
        findings=findings,
    )
    unique_findings = _deduplicate_findings(findings)
    passed = not unique_findings
    return CanaryStopDrillResult(
        status="PASS" if passed else "BLOCK",
        conclusion=(
            "INDEPENDENT_STOP_DRILL_PROVEN"
            if passed
            else "INDEPENDENT_STOP_DRILL_BLOCKED"
        ),
        evaluated_at=evaluation_time.isoformat(),
        latch_id=stop_request.latch_id if stop_request else None,
        latch_sha256=stop_request.record_sha256 if stop_request else None,
        runtime_instance_id=(
            runtime_acknowledgement.runtime_instance_id
            if runtime_acknowledgement
            else None
        ),
        process_running=(
            process_observation.process_running
            if process_observation
            else None
        ),
        credential_state=(
            revocation_observation.credential_state
            if revocation_observation
            else None
        ),
        findings=unique_findings,
    )


def _validate_stop_request(
    request: CanaryStopRequest | None,
    *,
    evaluation_time: datetime,
    policy: CanaryStopDrillPolicy,
    findings: list[CanaryStopFinding],
) -> datetime | None:
    if request is None:
        findings.append(
            CanaryStopFinding(
                code="STOP_REQUEST_MISSING",
                message="The independent stop request is missing.",
            )
        )
        return None
    if request.controller_id != policy.expected_controller_id:
        findings.append(
            CanaryStopFinding(
                code="STOP_CONTROLLER_MISMATCH",
                message="The stop request came from an unexpected controller.",
            )
        )
    requested_at = _parse_timestamp(
        request.requested_at,
        field="stop request",
        code_prefix="STOP_REQUEST_TIME",
        findings=findings,
    )
    _check_age(
        requested_at,
        evaluated_at=evaluation_time,
        max_age=policy.max_evidence_age_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        stale_code="STOP_REQUEST_STALE",
        future_code="STOP_REQUEST_FROM_FUTURE",
        label="Stop request",
        findings=findings,
    )
    return requested_at


def _validate_acknowledgement(
    *,
    stop_request: CanaryStopRequest | None,
    acknowledgement: CanaryRuntimeStopAcknowledgement | None,
    request_time: datetime | None,
    evaluation_time: datetime,
    policy: CanaryStopDrillPolicy,
    findings: list[CanaryStopFinding],
) -> datetime | None:
    if acknowledgement is None:
        findings.append(
            CanaryStopFinding(
                code="RUNTIME_ACKNOWLEDGEMENT_MISSING",
                message="Runtime stop acknowledgement is missing.",
            )
        )
        return None
    if (
        stop_request is not None
        and stop_request.controller_id == acknowledgement.runtime_instance_id
    ):
        findings.append(
            CanaryStopFinding(
                code="STOP_CONTROLLER_NOT_INDEPENDENT",
                message="The runtime cannot act as its own independent stop controller.",
            )
        )
    if stop_request is not None:
        if acknowledgement.latch_sha256 != stop_request.record_sha256:
            findings.append(
                CanaryStopFinding(
                    code="RUNTIME_LATCH_MISMATCH",
                    message="Runtime acknowledgement references a different stop latch.",
                )
            )
        if (
            acknowledgement.account_binding_commitment
            != stop_request.account_binding_commitment
        ):
            findings.append(
                CanaryStopFinding(
                    code="RUNTIME_ACCOUNT_MISMATCH",
                    message="Runtime acknowledgement is bound to a different account.",
                )
            )
    if not _SIMPLE_IDENTIFIER.fullmatch(
        str(acknowledgement.runtime_instance_id).strip()
    ):
        findings.append(
            CanaryStopFinding(
                code="RUNTIME_INSTANCE_INVALID",
                message="Runtime acknowledgement has an invalid instance identity.",
            )
        )
    if acknowledgement.state != RUNTIME_STOPPED:
        findings.append(
            CanaryStopFinding(
                code="RUNTIME_NOT_STOPPED",
                message="Runtime did not report the required STOPPED state.",
            )
        )
    if acknowledgement.execution_disabled is not True:
        findings.append(
            CanaryStopFinding(
                code="EXECUTION_NOT_DISABLED",
                message="Runtime did not report execution disabled.",
            )
        )
    if (
        isinstance(acknowledgement.outstanding_command_count, bool)
        or not isinstance(acknowledgement.outstanding_command_count, int)
        or acknowledgement.outstanding_command_count < 0
    ):
        findings.append(
            CanaryStopFinding(
                code="OUTSTANDING_COMMAND_COUNT_INVALID",
                message="Outstanding command count is invalid.",
            )
        )
    elif acknowledgement.outstanding_command_count != 0:
        findings.append(
            CanaryStopFinding(
                code="OUTSTANDING_COMMANDS_REMAIN",
                message="Runtime still reports outstanding execution commands.",
            )
        )
    acknowledged_at = _parse_timestamp(
        acknowledgement.acknowledged_at,
        field="runtime acknowledgement",
        code_prefix="RUNTIME_ACK_TIME",
        findings=findings,
    )
    _check_age(
        acknowledged_at,
        evaluated_at=evaluation_time,
        max_age=policy.max_evidence_age_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        stale_code="RUNTIME_ACK_STALE",
        future_code="RUNTIME_ACK_FROM_FUTURE",
        label="Runtime acknowledgement",
        findings=findings,
    )
    _check_after_request(
        value=acknowledged_at,
        request_time=request_time,
        max_latency=policy.max_shutdown_latency_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        before_code="RUNTIME_ACK_BEFORE_REQUEST",
        late_code="RUNTIME_ACK_TOO_SLOW",
        label="Runtime acknowledgement",
        findings=findings,
    )
    return acknowledged_at


def _validate_process_observation(
    *,
    acknowledgement: CanaryRuntimeStopAcknowledgement | None,
    process_observation: CanaryIndependentProcessObservation | None,
    request_time: datetime | None,
    acknowledgement_time: datetime | None,
    evaluation_time: datetime,
    policy: CanaryStopDrillPolicy,
    findings: list[CanaryStopFinding],
) -> None:
    if process_observation is None:
        findings.append(
            CanaryStopFinding(
                code="PROCESS_OBSERVATION_MISSING",
                message="Independent process observation is missing.",
            )
        )
        return
    if process_observation.observer_id != policy.expected_process_observer_id:
        findings.append(
            CanaryStopFinding(
                code="PROCESS_OBSERVER_MISMATCH",
                message="Process evidence came from an unexpected observer.",
            )
        )
    if process_observation.source != policy.expected_process_source:
        findings.append(
            CanaryStopFinding(
                code="PROCESS_SOURCE_MISMATCH",
                message="Process evidence came from an unexpected source.",
            )
        )
    if acknowledgement is not None:
        if process_observation.runtime_instance_id != acknowledgement.runtime_instance_id:
            findings.append(
                CanaryStopFinding(
                    code="PROCESS_RUNTIME_MISMATCH",
                    message="Process evidence references a different runtime instance.",
                )
            )
        if process_observation.observer_id == acknowledgement.runtime_instance_id:
            findings.append(
                CanaryStopFinding(
                    code="PROCESS_OBSERVER_NOT_INDEPENDENT",
                    message="The runtime cannot independently attest to its own shutdown.",
                )
            )
    if process_observation.process_running is not False:
        findings.append(
            CanaryStopFinding(
                code="PROCESS_STILL_RUNNING",
                message="Independent evidence still reports the runtime process running.",
            )
        )
    observed_at = _parse_timestamp(
        process_observation.observed_at,
        field="process observation",
        code_prefix="PROCESS_OBSERVATION_TIME",
        findings=findings,
    )
    _check_age(
        observed_at,
        evaluated_at=evaluation_time,
        max_age=policy.max_evidence_age_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        stale_code="PROCESS_OBSERVATION_STALE",
        future_code="PROCESS_OBSERVATION_FROM_FUTURE",
        label="Process observation",
        findings=findings,
    )
    _check_after_request(
        value=observed_at,
        request_time=request_time,
        max_latency=policy.max_shutdown_latency_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        before_code="PROCESS_OBSERVATION_BEFORE_REQUEST",
        late_code="PROCESS_STOP_TOO_SLOW",
        label="Process stop observation",
        findings=findings,
    )
    if observed_at is not None and acknowledgement_time is not None:
        if (
            acknowledgement_time - observed_at
        ).total_seconds() > policy.max_future_skew_seconds:
            findings.append(
                CanaryStopFinding(
                    code="PROCESS_OBSERVED_BEFORE_ACKNOWLEDGEMENT",
                    message=(
                        "Independent process stop evidence predates runtime acknowledgement."
                    ),
                )
            )


def _validate_revocation_observation(
    *,
    stop_request: CanaryStopRequest | None,
    revocation: CanaryCredentialRevocationObservation | None,
    request_time: datetime | None,
    evaluation_time: datetime,
    policy: CanaryStopDrillPolicy,
    findings: list[CanaryStopFinding],
) -> None:
    if revocation is None:
        findings.append(
            CanaryStopFinding(
                code="REVOCATION_OBSERVATION_MISSING",
                message="Credential revocation evidence is missing.",
            )
        )
        return
    if revocation.source != policy.expected_revocation_source:
        findings.append(
            CanaryStopFinding(
                code="REVOCATION_SOURCE_MISMATCH",
                message="Credential evidence came from an unexpected source.",
            )
        )
    if stop_request is not None and (
        revocation.account_binding_commitment
        != stop_request.account_binding_commitment
    ):
        findings.append(
            CanaryStopFinding(
                code="REVOCATION_ACCOUNT_MISMATCH",
                message="Credential evidence is bound to a different account.",
            )
        )
    if revocation.credential_state != CREDENTIAL_REVOKED:
        findings.append(
            CanaryStopFinding(
                code="CREDENTIAL_NOT_REVOKED",
                message="Credential evidence does not report REVOKED.",
            )
        )
    observed_at = _parse_timestamp(
        revocation.observed_at,
        field="revocation observation",
        code_prefix="REVOCATION_TIME",
        findings=findings,
    )
    _check_age(
        observed_at,
        evaluated_at=evaluation_time,
        max_age=policy.max_evidence_age_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        stale_code="REVOCATION_OBSERVATION_STALE",
        future_code="REVOCATION_OBSERVATION_FROM_FUTURE",
        label="Revocation observation",
        findings=findings,
    )
    _check_after_request(
        value=observed_at,
        request_time=request_time,
        max_latency=policy.max_revocation_latency_seconds,
        max_future_skew=policy.max_future_skew_seconds,
        before_code="REVOCATION_BEFORE_REQUEST",
        late_code="REVOCATION_TOO_SLOW",
        label="Credential revocation",
        findings=findings,
    )


def _check_after_request(
    *,
    value: datetime | None,
    request_time: datetime | None,
    max_latency: float,
    max_future_skew: float,
    before_code: str,
    late_code: str,
    label: str,
    findings: list[CanaryStopFinding],
) -> None:
    if value is None or request_time is None:
        return
    latency = (value - request_time).total_seconds()
    if latency < -max_future_skew:
        findings.append(
            CanaryStopFinding(
                code=before_code,
                message=f"{label} predates the stop request.",
            )
        )
    elif latency > max_latency:
        findings.append(
            CanaryStopFinding(
                code=late_code,
                message=f"{label} exceeded the configured latency limit.",
            )
        )


def _check_age(
    value: datetime | None,
    *,
    evaluated_at: datetime,
    max_age: float,
    max_future_skew: float,
    stale_code: str,
    future_code: str,
    label: str,
    findings: list[CanaryStopFinding],
) -> None:
    if value is None:
        return
    age = (evaluated_at - value).total_seconds()
    if age < -max_future_skew:
        findings.append(
            CanaryStopFinding(
                code=future_code,
                message=f"{label} is later than the permitted clock skew.",
            )
        )
    elif age > max_age:
        findings.append(
            CanaryStopFinding(
                code=stale_code,
                message=f"{label} is older than the configured evidence window.",
            )
        )


def _parse_timestamp(
    value: str,
    *,
    field: str,
    code_prefix: str,
    findings: list[CanaryStopFinding],
) -> datetime | None:
    try:
        return _require_timestamp(value, field=field)
    except CanaryStopEvidenceError as exc:
        code = (
            f"{code_prefix}_NAIVE"
            if "UTC offset" in str(exc)
            else f"{code_prefix}_INVALID"
        )
        findings.append(CanaryStopFinding(code=code, message=str(exc)))
        return None


def _require_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CanaryStopEvidenceError(
            f"{field.capitalize()} timestamp is not valid ISO 8601."
        ) from exc
    return _require_aware_datetime(parsed, field=field)


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryStopEvidenceError(
            f"{field.capitalize()} timestamp must include a UTC offset."
        )
    return value


def _canonical_timestamp(value: str) -> str:
    return _require_timestamp(value, field="timestamp").isoformat()


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _normalize_identifier(value: str, *, field: str) -> str:
    normalized = str(value).strip()
    if not _SIMPLE_IDENTIFIER.fullmatch(normalized):
        raise CanaryStopEvidenceError(
            f"{field.capitalize()} must be a simple ASCII identifier."
        )
    return normalized


def _normalize_commitment(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _HEX_SHA256.fullmatch(normalized):
        raise CanaryStopEvidenceError(
            "Account binding commitment must be a lowercase SHA-256 digest."
        )
    return normalized


def _commitment_tag(value: str) -> str:
    clean = str(value).strip()
    return f"{clean[:12]}..." if clean else "[missing]"


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )


def _is_positive_number(value: object) -> bool:
    return _is_finite_number(value) and float(value) > 0


def _deduplicate_findings(
    findings: list[CanaryStopFinding],
) -> tuple[CanaryStopFinding, ...]:
    unique: list[CanaryStopFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (finding.code, finding.message)
        if key not in seen:
            unique.append(finding)
            seen.add(key)
    return tuple(unique)
