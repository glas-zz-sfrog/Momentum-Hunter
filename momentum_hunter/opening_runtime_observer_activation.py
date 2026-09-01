from __future__ import annotations

"""Creation-time guardrails for operational opening-runtime observers."""

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Mapping

from momentum_hunter.opening_runtime_identity import (
    DEFAULT_CHANNEL,
    DEFAULT_RELEASE_ROOT,
    RELEASE_ID_PATTERN,
    SHA256_PATTERN,
    payload_fingerprint,
)
from momentum_hunter.opening_runtime_observer import (
    CURRENT_AUTHORIZED_RELEASE,
    FIXED_EXPECTED_RELEASE,
    OBSERVER_MODES,
    observe_opening_runtime,
)


ACTIVATION_SCHEMA = "OpeningAuthorizedReleaseObserverActivationV1"
RECEIPT_SCHEMA = "OpeningAuthorizedReleaseOperationalReceiptV1"
AUTHORITY_RESOLUTION_AT_OBSERVATION = "AT_OBSERVATION_TIME"
VERIFIER_ENTRYPOINT = (
    "momentum_hunter.opening_runtime_observer.observe_opening_runtime"
)

_BASE_ACTIVATION_FIELDS = {
    "schemaVersion",
    "mode",
    "channel",
    "authorityResolution",
    "verifierEntrypoint",
    "createdAt",
    "readOnly",
    "providerContactAllowed",
    "mutationAllowed",
    "orderTransmission",
    "activationFingerprint",
}
_FIXED_IDENTITY_FIELD = "fixedExpectedIdentity"


class OpeningObserverActivationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OpeningObserverActivation:
    payload: dict[str, object]

    @property
    def mode(self) -> str:
        return str(self.payload["mode"])

    @property
    def channel(self) -> str:
        return str(self.payload["channel"])

    @property
    def fixed_release_id(self) -> str | None:
        identity = self.payload.get(_FIXED_IDENTITY_FIELD)
        if not isinstance(identity, Mapping):
            return None
        return str(identity.get("releaseId", ""))

    @property
    def fixed_runtime_fingerprint(self) -> str | None:
        identity = self.payload.get(_FIXED_IDENTITY_FIELD)
        if not isinstance(identity, Mapping):
            return None
        return str(identity.get("runtimeFingerprint", ""))


def _require_aware_timestamp(value: object, *, field_name: str) -> str:
    raw = str(value or "")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise OpeningObserverActivationError(
            "OBSERVER_ACTIVATION_TIMESTAMP_INVALID",
            f"{field_name} must be a valid ISO-8601 timestamp.",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OpeningObserverActivationError(
            "OBSERVER_ACTIVATION_TIMESTAMP_INVALID",
            f"{field_name} must include timezone identity.",
        )
    return parsed.isoformat()


def create_observer_activation(
    *,
    created_at: datetime,
    mode: str = CURRENT_AUTHORIZED_RELEASE,
    channel: str = DEFAULT_CHANNEL,
    fixed_expected_release_id: str | None = None,
    fixed_expected_runtime_fingerprint: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": ACTIVATION_SCHEMA,
        "mode": mode,
        "channel": channel,
        "authorityResolution": AUTHORITY_RESOLUTION_AT_OBSERVATION,
        "verifierEntrypoint": VERIFIER_ENTRYPOINT,
        "createdAt": _require_aware_timestamp(
            created_at.isoformat(), field_name="createdAt"
        ),
        "readOnly": True,
        "providerContactAllowed": False,
        "mutationAllowed": False,
        "orderTransmission": "UNAVAILABLE",
    }
    if (
        fixed_expected_release_id is not None
        or fixed_expected_runtime_fingerprint is not None
    ):
        payload[_FIXED_IDENTITY_FIELD] = {
            "releaseId": str(fixed_expected_release_id or ""),
            "runtimeFingerprint": str(fixed_expected_runtime_fingerprint or ""),
        }
    payload["activationFingerprint"] = payload_fingerprint(
        payload, "activationFingerprint"
    )
    return validate_observer_activation(payload).payload


def validate_observer_activation(
    payload: Mapping[str, object],
) -> OpeningObserverActivation:
    candidate = dict(payload)
    if candidate.get("schemaVersion") != ACTIVATION_SCHEMA:
        raise OpeningObserverActivationError(
            "OBSERVER_ACTIVATION_SCHEMA_UNSUPPORTED",
            "Observer activation uses an unsupported schema.",
        )
    mode = str(candidate.get("mode", ""))
    if mode not in OBSERVER_MODES:
        raise OpeningObserverActivationError(
            "OBSERVER_ACTIVATION_MODE_UNSUPPORTED",
            f"Observer activation mode is unsupported: {mode}",
        )
    expected_fields = set(_BASE_ACTIVATION_FIELDS)
    if mode == FIXED_EXPECTED_RELEASE:
        expected_fields.add(_FIXED_IDENTITY_FIELD)
    actual_fields = set(candidate)
    if actual_fields != expected_fields:
        extra = sorted(actual_fields - expected_fields)
        missing = sorted(expected_fields - actual_fields)
        if mode == CURRENT_AUTHORIZED_RELEASE and _FIXED_IDENTITY_FIELD in actual_fields:
            code = "CURRENT_MODE_FIXED_IDENTITY_AMBIGUOUS"
        elif mode == FIXED_EXPECTED_RELEASE and _FIXED_IDENTITY_FIELD in missing:
            code = "FIXED_EXPECTATION_INVALID"
        else:
            code = "OBSERVER_ACTIVATION_FIELDS_INVALID"
        raise OpeningObserverActivationError(
            code,
            f"Observer activation fields are invalid; extra={extra}, missing={missing}.",
        )
    if candidate.get("channel") != DEFAULT_CHANNEL:
        raise OpeningObserverActivationError(
            "OBSERVER_ACTIVATION_CHANNEL_INVALID",
            "Operational opening observers must use the opening-capture channel.",
        )
    if candidate.get("authorityResolution") != AUTHORITY_RESOLUTION_AT_OBSERVATION:
        raise OpeningObserverActivationError(
            "OBSERVER_ACTIVATION_AUTHORITY_TIMING_INVALID",
            "Operational authority must be resolved at observation time.",
        )
    if candidate.get("verifierEntrypoint") != VERIFIER_ENTRYPOINT:
        raise OpeningObserverActivationError(
            "OBSERVER_ACTIVATION_VERIFIER_INVALID",
            "Observer activation must delegate to the accepted verifier.",
        )
    _require_aware_timestamp(candidate.get("createdAt"), field_name="createdAt")
    safety_fields = {
        "readOnly": True,
        "providerContactAllowed": False,
        "mutationAllowed": False,
        "orderTransmission": "UNAVAILABLE",
    }
    for field_name, expected in safety_fields.items():
        if candidate.get(field_name) != expected:
            raise OpeningObserverActivationError(
                "OBSERVER_ACTIVATION_AUTHORITY_INVALID",
                f"Observer activation safety field {field_name} is invalid.",
            )
    if mode == FIXED_EXPECTED_RELEASE:
        identity = candidate.get(_FIXED_IDENTITY_FIELD)
        if not isinstance(identity, Mapping) or set(identity) != {
            "releaseId",
            "runtimeFingerprint",
        }:
            raise OpeningObserverActivationError(
                "FIXED_EXPECTATION_INVALID",
                "Fixed observer mode requires one explicit release/fingerprint pair.",
            )
        release_id = str(identity.get("releaseId", ""))
        runtime_fingerprint = str(identity.get("runtimeFingerprint", ""))
        if not RELEASE_ID_PATTERN.fullmatch(release_id) or not SHA256_PATTERN.fullmatch(
            runtime_fingerprint
        ):
            raise OpeningObserverActivationError(
                "FIXED_EXPECTATION_INVALID",
                "Fixed observer mode requires a valid release and runtime fingerprint.",
            )
    fingerprint = str(candidate.get("activationFingerprint", ""))
    if not SHA256_PATTERN.fullmatch(fingerprint) or fingerprint != payload_fingerprint(
        candidate, "activationFingerprint"
    ):
        raise OpeningObserverActivationError(
            "OBSERVER_ACTIVATION_FINGERPRINT_INVALID",
            "Observer activation fingerprint does not verify.",
        )
    return OpeningObserverActivation(candidate)


def build_operational_automation_prompt(payload: Mapping[str, object]) -> str:
    activation = validate_observer_activation(payload)
    encoded = json.dumps(activation.payload, sort_keys=True, separators=(",", ":"))
    return (
        "Run the production Argus Opening authorized-release Observer as a strictly "
        "read-only verification heartbeat. Use the integrated stable observer "
        "activation entrypoint and the accepted opening-runtime verifier; do not "
        "reimplement release authority resolution. Build independent observation "
        "evidence only from terminal persisted Opening state. Resolve authority at "
        "observation time, freeze that authority in a write-once receipt, and compare "
        "the actual runtime against it. Never contact a provider, broker, account, "
        "position, order, or authentication endpoint, and never launch, retry, repair, "
        "restart, promote, repoint, schedule, or mutate production state. Treat any "
        "missing, malformed, inconsistent, dirty, divergent, ambiguous, or mismatched "
        "state as fail-closed. The durable activation payload is: "
        f"{encoded} Operational entrypoint: python -m "
        "tools.prepare_opening_runtime_observer observe."
    )


def build_observer_receipt(
    activation_payload: Mapping[str, object],
    observation_payload: Mapping[str, object],
    *,
    expected_canonical_git_sha: str,
    observed_at: datetime,
    release_root: Path = DEFAULT_RELEASE_ROOT,
) -> dict[str, object]:
    activation = validate_observer_activation(activation_payload)
    result = observe_opening_runtime(
        observation_payload,
        expected_canonical_git_sha=expected_canonical_git_sha,
        release_root=release_root,
        channel=activation.channel,
        mode=activation.mode,
        fixed_expected_release_id=activation.fixed_release_id,
        fixed_expected_runtime_fingerprint=activation.fixed_runtime_fingerprint,
    )
    receipt: dict[str, object] = {
        "schemaVersion": RECEIPT_SCHEMA,
        "activationFingerprint": activation.payload["activationFingerprint"],
        "observerMode": activation.mode,
        "observationTimestamp": _require_aware_timestamp(
            observed_at.isoformat(), field_name="observationTimestamp"
        ),
        "authoritySnapshot": {
            "channel": result.get("channel", activation.channel),
            "authoritySource": result.get("authoritySource", ""),
            "authorizedReleaseResolved": result.get(
                "authorizedReleaseResolved", False
            ),
            "authorizedReleaseId": result.get("expectedReleaseId", ""),
            "authorizedRuntimeFingerprint": result.get(
                "expectedRuntimeFingerprint", ""
            ),
            "authorizedReleaseFingerprint": result.get(
                "expectedReleaseFingerprint", ""
            ),
            "authorizedReleaseSourceGitSha": result.get(
                "expectedReleaseSourceGitSha", ""
            ),
            "promotionReceiptFingerprint": result.get(
                "promotionReceiptFingerprint", ""
            ),
        },
        "actualObservation": {
            "releaseId": result.get("actualReleaseId", ""),
            "runtimeFingerprint": result.get("actualRuntimeFingerprint", ""),
            "canonicalGitSha": result.get("actualCanonicalGitSha", ""),
            "canonicalWorktreeClean": result.get("canonicalWorktreeClean", False),
        },
        "observerResult": result.get("observerResult", "FAIL"),
        "classification": result.get("classification", "FAIL_CLOSED"),
        "diagnosticCode": result.get("diagnosticCode", "OBSERVER_RESULT_INVALID"),
        "diagnosticMessage": result.get("diagnosticMessage", ""),
        "diagnosticDetails": result.get("diagnosticDetails", {}),
        "failClosed": result.get("failClosed", True),
        "runtimeDrift": result.get("runtimeDrift", False),
        "canonicalDrift": result.get("canonicalDrift", False),
        "authorizedReleaseVerified": bool(
            result.get("authorizedReleaseResolved")
        ),
        "promotionChainVerified": bool(
            result.get("authorizedReleaseResolved")
            and result.get("promotionReceiptFingerprint")
        ),
        "mutationPerformed": False,
        "providerContact": False,
        "orderTransmission": "UNAVAILABLE",
        "verifierResult": result,
    }
    receipt["receiptFingerprint"] = payload_fingerprint(
        receipt, "receiptFingerprint"
    )
    return receipt


def _write_new(path: Path, content: bytes) -> None:
    target = path.absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        raise


def write_new_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_new(path, encoded)


def write_new_text(path: Path, value: str) -> None:
    _write_new(path, value.encode("utf-8"))
