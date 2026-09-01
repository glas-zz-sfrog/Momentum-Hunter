from __future__ import annotations

"""Fail-closed observer binding for the authorized opening-runtime channel."""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from momentum_hunter.opening_runtime_identity import (
    DEFAULT_CHANNEL,
    DEFAULT_RELEASE_ROOT,
    GIT_SHA_PATTERN,
    RELEASE_ID_PATTERN,
    SHA256_PATTERN,
    OpeningRuntimeIdentityError,
    OpeningRuntimeReleaseStore,
)


OBSERVER_RESULT_SCHEMA = "OpeningAuthorizedReleaseObserverResultV1"
OBSERVATION_SCHEMA = "OpeningRuntimeObservationV1"
HEARTBEAT_SAFETY_SCHEMA = "OpeningObserverHeartbeatSafetyV1"
HEARTBEAT_POLICY_RESULT_SCHEMA = "OpeningObserverHeartbeatPolicyResultV1"
CURRENT_AUTHORIZED_RELEASE = "CURRENT_AUTHORIZED_RELEASE"
FIXED_EXPECTED_RELEASE = "FIXED_EXPECTED_RELEASE"
OBSERVER_MODES = (CURRENT_AUTHORIZED_RELEASE, FIXED_EXPECTED_RELEASE)
AUTHORIZED_OBSERVER_RUNTIME_IDENTITY = "argus-opening-authorized-release-observer"
SOURCE_GIT_EQUAL = "CURRENT_CANONICAL_EQUALS_AUTHORIZED_RELEASE_SOURCE"
SOURCE_GIT_DIFFERENT = "CURRENT_CANONICAL_DIFFERS_FROM_AUTHORIZED_RELEASE_SOURCE"
SOURCE_GIT_UNAVAILABLE = "SOURCE_GIT_RELATIONSHIP_UNAVAILABLE"


@dataclass(frozen=True)
class AuthorizedOpeningExpectation:
    mode: str
    channel: str
    release_id: str
    runtime_fingerprint: str
    release_fingerprint: str
    release_source_git_sha: str
    promotion_receipt_fingerprint: str
    authority_source: str


@dataclass(frozen=True)
class OpeningRuntimeObservation:
    actual_release_id: str
    actual_runtime_fingerprint: str
    actual_canonical_git_sha: str
    canonical_worktree_clean: bool

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
    ) -> "OpeningRuntimeObservation":
        if payload.get("schemaVersion") != OBSERVATION_SCHEMA:
            raise OpeningRuntimeIdentityError(
                "OBSERVER_EVIDENCE_SCHEMA_UNSUPPORTED",
                "Opening observer evidence uses an unsupported schema.",
            )
        release_id = str(payload.get("actualReleaseId", ""))
        runtime_fingerprint = str(payload.get("actualRuntimeFingerprint", ""))
        canonical_git_sha = str(payload.get("actualCanonicalGitSha", ""))
        worktree_clean = payload.get("canonicalWorktreeClean")
        if not RELEASE_ID_PATTERN.fullmatch(release_id):
            raise OpeningRuntimeIdentityError(
                "ACTUAL_RELEASE_ID_INVALID",
                "Observed opening release identity is missing or malformed.",
            )
        if not SHA256_PATTERN.fullmatch(runtime_fingerprint):
            raise OpeningRuntimeIdentityError(
                "ACTUAL_RUNTIME_FINGERPRINT_INVALID",
                "Observed opening runtime fingerprint is missing or malformed.",
            )
        if not GIT_SHA_PATTERN.fullmatch(canonical_git_sha):
            raise OpeningRuntimeIdentityError(
                "ACTUAL_CANONICAL_IDENTITY_INVALID",
                "Observed canonical Git identity is missing or malformed.",
            )
        if not isinstance(worktree_clean, bool):
            raise OpeningRuntimeIdentityError(
                "ACTUAL_CANONICAL_CLEANLINESS_INVALID",
                "Observed canonical worktree cleanliness must be explicit.",
            )
        return cls(
            actual_release_id=release_id,
            actual_runtime_fingerprint=runtime_fingerprint,
            actual_canonical_git_sha=canonical_git_sha,
            canonical_worktree_clean=worktree_clean,
        )


@dataclass(frozen=True)
class OpeningObserverHeartbeatSafety:
    observer_runtime_identity: str
    observer_instance_count: int
    read_only: bool
    protected_production_hashes_unchanged: bool
    services_unchanged: bool
    scheduler_unchanged: bool
    canonical_local_origin_synchronized: bool
    external_provider_or_authentication_contacted: bool
    broker_or_account_contacted: bool
    paper_authority_used: bool
    execution_authority_used: bool

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, object],
    ) -> "OpeningObserverHeartbeatSafety":
        if payload.get("schemaVersion") != HEARTBEAT_SAFETY_SCHEMA:
            raise OpeningRuntimeIdentityError(
                "OBSERVER_SAFETY_EVIDENCE_SCHEMA_UNSUPPORTED",
                "Opening Observer safety evidence uses an unsupported schema.",
            )
        observer_identity = payload.get("observerRuntimeIdentity")
        instance_count = payload.get("observerInstanceCount")
        if not isinstance(observer_identity, str) or not observer_identity:
            raise OpeningRuntimeIdentityError(
                "OBSERVER_RUNTIME_IDENTITY_INVALID",
                "Opening Observer runtime identity must be explicit.",
            )
        if isinstance(instance_count, bool) or not isinstance(instance_count, int):
            raise OpeningRuntimeIdentityError(
                "OBSERVER_INSTANCE_COUNT_INVALID",
                "Opening Observer instance count must be an integer.",
            )
        boolean_fields = {
            "readOnly": "read_only",
            "protectedProductionHashesUnchanged": (
                "protected_production_hashes_unchanged"
            ),
            "servicesUnchanged": "services_unchanged",
            "schedulerUnchanged": "scheduler_unchanged",
            "canonicalLocalOriginSynchronized": (
                "canonical_local_origin_synchronized"
            ),
            "externalProviderOrAuthenticationContacted": (
                "external_provider_or_authentication_contacted"
            ),
            "brokerOrAccountContacted": "broker_or_account_contacted",
            "paperAuthorityUsed": "paper_authority_used",
            "executionAuthorityUsed": "execution_authority_used",
        }
        values: dict[str, bool] = {}
        for payload_name, attribute_name in boolean_fields.items():
            value = payload.get(payload_name)
            if not isinstance(value, bool):
                raise OpeningRuntimeIdentityError(
                    "OBSERVER_SAFETY_EVIDENCE_INVALID",
                    f"Opening Observer safety field must be boolean: {payload_name}",
                )
            values[attribute_name] = value
        return cls(
            observer_runtime_identity=observer_identity,
            observer_instance_count=instance_count,
            **values,
        )


def _source_git_diagnostics(
    expectation: AuthorizedOpeningExpectation | None,
    observation: OpeningRuntimeObservation | None,
) -> dict[str, object]:
    if expectation is None or observation is None:
        return {
            "authorizedReleaseSourceProvenanceVerified": expectation is not None,
            "currentSourceEqualsReleaseSource": None,
            "sourceGitRelationship": SOURCE_GIT_UNAVAILABLE,
        }
    source_equal = (
        observation.actual_canonical_git_sha == expectation.release_source_git_sha
    )
    return {
        "authorizedReleaseSourceProvenanceVerified": True,
        "currentSourceEqualsReleaseSource": source_equal,
        "sourceGitRelationship": (
            SOURCE_GIT_EQUAL if source_equal else SOURCE_GIT_DIFFERENT
        ),
    }


def _require_existing_release_store(release_root: Path) -> Path:
    root = release_root.absolute()
    required_directories = (
        root,
        root / "releases",
        root / "promotions",
        root / "channels",
    )
    missing = [str(path) for path in required_directories if not path.is_dir()]
    if missing:
        raise OpeningRuntimeIdentityError(
            "RELEASE_AUTHORITY_ROOT_MISSING",
            "Approved opening release authority is missing or incomplete.",
            details={"missingDirectories": missing},
        )
    return root


def resolve_authorized_opening_expectation(
    release_root: Path = DEFAULT_RELEASE_ROOT,
    *,
    channel: str = DEFAULT_CHANNEL,
    mode: str = CURRENT_AUTHORIZED_RELEASE,
    fixed_expected_release_id: str | None = None,
    fixed_expected_runtime_fingerprint: str | None = None,
) -> AuthorizedOpeningExpectation:
    if mode not in OBSERVER_MODES:
        raise OpeningRuntimeIdentityError(
            "OBSERVER_MODE_UNSUPPORTED",
            f"Opening observer mode is unsupported: {mode}",
        )
    store = OpeningRuntimeReleaseStore(_require_existing_release_store(release_root))
    if mode == CURRENT_AUTHORIZED_RELEASE:
        release, _, receipt = store.verify_channel(channel)
        receipt_fingerprint = str(receipt.get("receiptFingerprint", ""))
        source = (
            f"{store.pointer_path(channel)}"
            "+verified-promotion-chain+immutable-release"
        )
    else:
        release_id = str(fixed_expected_release_id or "")
        runtime_fingerprint = str(fixed_expected_runtime_fingerprint or "")
        if not RELEASE_ID_PATTERN.fullmatch(release_id) or not SHA256_PATTERN.fullmatch(
            runtime_fingerprint
        ):
            raise OpeningRuntimeIdentityError(
                "FIXED_EXPECTATION_INVALID",
                "Fixed observer mode requires an explicit valid release and fingerprint.",
            )
        release = store.verify_release(release_id)
        if release.get("approvedRuntimeFingerprint") != runtime_fingerprint:
            raise OpeningRuntimeIdentityError(
                "FIXED_EXPECTATION_CONTRADICTS_RELEASE",
                "Fixed observer expectation does not match its immutable release.",
            )
        receipt_fingerprint = ""
        source = f"{store.release_path(release_id)}+explicit-fixed-mode"

    return AuthorizedOpeningExpectation(
        mode=mode,
        channel=channel,
        release_id=str(release["releaseId"]),
        runtime_fingerprint=str(release["approvedRuntimeFingerprint"]),
        release_fingerprint=str(release["releaseFingerprint"]),
        release_source_git_sha=str(release["sourceGitSha"]),
        promotion_receipt_fingerprint=receipt_fingerprint,
        authority_source=source,
    )


def _failure(
    *,
    classification: str,
    diagnostic_code: str,
    diagnostic_message: str,
    expected_canonical_git_sha: str,
    expectation: AuthorizedOpeningExpectation | None = None,
    observation: OpeningRuntimeObservation | None = None,
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result = {
        "schemaVersion": OBSERVER_RESULT_SCHEMA,
        "observerResult": "FAIL",
        "classification": classification,
        "diagnosticCode": diagnostic_code,
        "diagnosticMessage": diagnostic_message,
        "diagnosticDetails": dict(details or {}),
        "failClosed": True,
        "mode": expectation.mode if expectation else "",
        "channel": expectation.channel if expectation else DEFAULT_CHANNEL,
        "authoritySource": expectation.authority_source if expectation else "",
        "authorizedReleaseResolved": expectation is not None,
        "expectedReleaseId": expectation.release_id if expectation else "",
        "expectedRuntimeFingerprint": (
            expectation.runtime_fingerprint if expectation else ""
        ),
        "expectedReleaseFingerprint": (
            expectation.release_fingerprint if expectation else ""
        ),
        "expectedReleaseSourceGitSha": (
            expectation.release_source_git_sha if expectation else ""
        ),
        "promotionReceiptFingerprint": (
            expectation.promotion_receipt_fingerprint if expectation else ""
        ),
        "actualReleaseId": observation.actual_release_id if observation else "",
        "actualRuntimeFingerprint": (
            observation.actual_runtime_fingerprint if observation else ""
        ),
        "expectedCanonicalGitSha": expected_canonical_git_sha,
        "actualCanonicalGitSha": (
            observation.actual_canonical_git_sha if observation else ""
        ),
        "canonicalWorktreeClean": (
            observation.canonical_worktree_clean if observation else False
        ),
        "runtimeDrift": classification == "RUNTIME_DRIFT",
        "canonicalDrift": classification == "CANONICAL_DRIFT",
        "mutationPerformed": False,
        "orderTransmission": "UNAVAILABLE",
    }
    result.update(_source_git_diagnostics(expectation, observation))
    return result


def evaluate_opening_runtime_observation(
    expectation: AuthorizedOpeningExpectation,
    observation: OpeningRuntimeObservation,
    *,
    expected_canonical_git_sha: str,
) -> dict[str, object]:
    if not GIT_SHA_PATTERN.fullmatch(expected_canonical_git_sha):
        return _failure(
            classification="FAIL_CLOSED",
            diagnostic_code="EXPECTED_CANONICAL_IDENTITY_INVALID",
            diagnostic_message="Expected canonical Git identity is missing or malformed.",
            expected_canonical_git_sha=expected_canonical_git_sha,
            expectation=expectation,
            observation=observation,
        )
    if (
        not observation.canonical_worktree_clean
        or observation.actual_canonical_git_sha != expected_canonical_git_sha
    ):
        return _failure(
            classification="CANONICAL_DRIFT",
            diagnostic_code="CANONICAL_DRIFT",
            diagnostic_message="Observed canonical state differs from observer policy.",
            expected_canonical_git_sha=expected_canonical_git_sha,
            expectation=expectation,
            observation=observation,
        )
    if (
        observation.actual_release_id != expectation.release_id
        or observation.actual_runtime_fingerprint != expectation.runtime_fingerprint
    ):
        return _failure(
            classification="RUNTIME_DRIFT",
            diagnostic_code="RUNTIME_DRIFT",
            diagnostic_message=(
                "Observed opening runtime differs from the selected observer expectation."
            ),
            expected_canonical_git_sha=expected_canonical_git_sha,
            expectation=expectation,
            observation=observation,
        )
    result = {
        "schemaVersion": OBSERVER_RESULT_SCHEMA,
        "observerResult": "PASS",
        "classification": "AUTHORIZED_RUNTIME_MATCH",
        "diagnosticCode": "AUTHORIZED_RUNTIME_MATCH",
        "diagnosticMessage": "Observed opening runtime matches current authority.",
        "diagnosticDetails": {},
        "failClosed": False,
        "mode": expectation.mode,
        "channel": expectation.channel,
        "authoritySource": expectation.authority_source,
        "authorizedReleaseResolved": True,
        "expectedReleaseId": expectation.release_id,
        "expectedRuntimeFingerprint": expectation.runtime_fingerprint,
        "expectedReleaseFingerprint": expectation.release_fingerprint,
        "expectedReleaseSourceGitSha": expectation.release_source_git_sha,
        "promotionReceiptFingerprint": expectation.promotion_receipt_fingerprint,
        "actualReleaseId": observation.actual_release_id,
        "actualRuntimeFingerprint": observation.actual_runtime_fingerprint,
        "expectedCanonicalGitSha": expected_canonical_git_sha,
        "actualCanonicalGitSha": observation.actual_canonical_git_sha,
        "canonicalWorktreeClean": observation.canonical_worktree_clean,
        "runtimeDrift": False,
        "canonicalDrift": False,
        "mutationPerformed": False,
        "orderTransmission": "UNAVAILABLE",
    }
    result.update(_source_git_diagnostics(expectation, observation))
    return result


def _heartbeat_policy_failure(
    *,
    diagnostic_code: str,
    diagnostic_message: str,
    observer_result: Mapping[str, object],
    safety: OpeningObserverHeartbeatSafety | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": HEARTBEAT_POLICY_RESULT_SCHEMA,
        "heartbeatResult": "FAIL",
        "classification": "FAIL_CLOSED",
        "diagnosticCode": diagnostic_code,
        "diagnosticMessage": diagnostic_message,
        "failClosed": True,
        "observerRuntimeIdentity": (
            safety.observer_runtime_identity if safety else ""
        ),
        "observerInstanceCount": safety.observer_instance_count if safety else 0,
        "authorizedReleaseBindingResult": observer_result.get("observerResult", ""),
        "authorizedReleaseBindingDiagnostic": observer_result.get(
            "diagnosticCode", ""
        ),
        "expectedReleaseId": observer_result.get("expectedReleaseId", ""),
        "expectedRuntimeFingerprint": observer_result.get(
            "expectedRuntimeFingerprint", ""
        ),
        "expectedReleaseSourceGitSha": observer_result.get(
            "expectedReleaseSourceGitSha", ""
        ),
        "actualCanonicalGitSha": observer_result.get("actualCanonicalGitSha", ""),
        "authorizedReleaseSourceProvenanceVerified": observer_result.get(
            "authorizedReleaseSourceProvenanceVerified", False
        ),
        "currentSourceEqualsReleaseSource": observer_result.get(
            "currentSourceEqualsReleaseSource"
        ),
        "sourceGitRelationship": observer_result.get(
            "sourceGitRelationship", SOURCE_GIT_UNAVAILABLE
        ),
        "readOnly": safety.read_only if safety else None,
        "protectedProductionHashesUnchanged": (
            safety.protected_production_hashes_unchanged if safety else None
        ),
        "servicesUnchanged": safety.services_unchanged if safety else None,
        "schedulerUnchanged": safety.scheduler_unchanged if safety else None,
        "canonicalLocalOriginSynchronized": (
            safety.canonical_local_origin_synchronized if safety else None
        ),
        "externalProviderOrAuthenticationContacted": (
            safety.external_provider_or_authentication_contacted if safety else None
        ),
        "brokerOrAccountContacted": (
            safety.broker_or_account_contacted if safety else None
        ),
        "paperAuthorityUsed": safety.paper_authority_used if safety else None,
        "executionAuthorityUsed": (
            safety.execution_authority_used if safety else None
        ),
        "mutationPerformed": observer_result.get("mutationPerformed"),
        "orderTransmission": observer_result.get("orderTransmission", ""),
    }


def evaluate_opening_observer_heartbeat(
    observer_result: Mapping[str, object],
    safety_payload: Mapping[str, object],
    *,
    expected_observer_runtime_identity: str = AUTHORIZED_OBSERVER_RUNTIME_IDENTITY,
) -> dict[str, object]:
    """Apply fail-closed heartbeat safety without equating canonical and release Git."""

    try:
        safety = OpeningObserverHeartbeatSafety.from_mapping(safety_payload)
    except OpeningRuntimeIdentityError as exc:
        return _heartbeat_policy_failure(
            diagnostic_code=exc.code,
            diagnostic_message=str(exc),
            observer_result=observer_result,
        )

    def fail(code: str, message: str) -> dict[str, object]:
        return _heartbeat_policy_failure(
            diagnostic_code=code,
            diagnostic_message=message,
            observer_result=observer_result,
            safety=safety,
        )

    if observer_result.get("schemaVersion") != OBSERVER_RESULT_SCHEMA:
        return fail(
            "AUTHORIZED_RELEASE_BINDING_SCHEMA_INVALID",
            "Authorized release-binding result uses an unsupported schema.",
        )
    if observer_result.get("observerResult") != "PASS":
        return fail(
            "AUTHORIZED_RELEASE_BINDING_FAILED",
            "Authorized release-binding verifier did not pass.",
        )
    if (
        observer_result.get("authorizedReleaseResolved") is not True
        or not RELEASE_ID_PATTERN.fullmatch(
            str(observer_result.get("expectedReleaseId", ""))
        )
        or not SHA256_PATTERN.fullmatch(
            str(observer_result.get("expectedRuntimeFingerprint", ""))
        )
        or not SHA256_PATTERN.fullmatch(
            str(observer_result.get("expectedReleaseFingerprint", ""))
        )
    ):
        return fail(
            "AUTHORIZED_RELEASE_IDENTITY_UNVERIFIED",
            "Authorized release identity or immutable fingerprint is unverified.",
        )
    if (
        observer_result.get("authorizedReleaseSourceProvenanceVerified") is not True
        or not GIT_SHA_PATTERN.fullmatch(
            str(observer_result.get("expectedReleaseSourceGitSha", ""))
        )
    ):
        return fail(
            "AUTHORIZED_RELEASE_SOURCE_PROVENANCE_UNVERIFIED",
            "Authorized release source provenance is unverified.",
        )
    if (
        observer_result.get("mode") != CURRENT_AUTHORIZED_RELEASE
        or observer_result.get("channel") != DEFAULT_CHANNEL
        or not SHA256_PATTERN.fullmatch(
            str(observer_result.get("promotionReceiptFingerprint", ""))
        )
        or not str(observer_result.get("authoritySource", ""))
    ):
        return fail(
            "AUTHORIZED_RELEASE_PROMOTION_CHAIN_UNVERIFIED",
            "Authorized channel or promotion-chain evidence is incomplete.",
        )
    if (
        observer_result.get("runtimeDrift") is not False
        or observer_result.get("actualReleaseId")
        != observer_result.get("expectedReleaseId")
        or observer_result.get("actualRuntimeFingerprint")
        != observer_result.get("expectedRuntimeFingerprint")
    ):
        return fail(
            "AUTHORIZED_RUNTIME_IDENTITY_UNVERIFIED",
            "Observed runtime identity does not match authorized release authority.",
        )
    expected_canonical = str(observer_result.get("expectedCanonicalGitSha", ""))
    actual_canonical = str(observer_result.get("actualCanonicalGitSha", ""))
    if (
        not GIT_SHA_PATTERN.fullmatch(expected_canonical)
        or actual_canonical != expected_canonical
        or observer_result.get("canonicalWorktreeClean") is not True
        or observer_result.get("canonicalDrift") is not False
        or not safety.canonical_local_origin_synchronized
    ):
        return fail(
            "CURRENT_CANONICAL_INTEGRITY_UNVERIFIED",
            "Current canonical integrity is unverified.",
        )
    release_source = str(observer_result.get("expectedReleaseSourceGitSha", ""))
    source_equal = actual_canonical == release_source
    expected_relationship = SOURCE_GIT_EQUAL if source_equal else SOURCE_GIT_DIFFERENT
    if (
        observer_result.get("currentSourceEqualsReleaseSource") is not source_equal
        or observer_result.get("sourceGitRelationship") != expected_relationship
    ):
        return fail(
            "SOURCE_GIT_DIAGNOSTIC_INCONSISTENT",
            "Source Git relationship diagnostic contradicts verified identities.",
        )
    if safety.observer_runtime_identity != expected_observer_runtime_identity:
        return fail(
            "OBSERVER_RUNTIME_IDENTITY_UNAUTHORIZED",
            "Observer runtime identity is not authorized.",
        )
    if safety.observer_instance_count != 1:
        return fail(
            "OBSERVER_SINGLETON_VIOLATION",
            "Exactly one Observer instance is required.",
        )
    if not safety.read_only or observer_result.get("mutationPerformed") is not False:
        return fail(
            "OBSERVER_READ_ONLY_VIOLATION",
            "Observer read-only behavior is unverified.",
        )
    if not safety.protected_production_hashes_unchanged:
        return fail(
            "PROTECTED_PRODUCTION_MUTATION",
            "Protected production hashes changed during observation.",
        )
    if not safety.services_unchanged or not safety.scheduler_unchanged:
        return fail(
            "PRODUCTION_CONTROL_STATE_CHANGED",
            "Production service or scheduler state changed during observation.",
        )
    if safety.external_provider_or_authentication_contacted:
        return fail(
            "OBSERVER_EXTERNAL_CONTACT_VIOLATION",
            "Observer contacted an external provider or authentication endpoint.",
        )
    if safety.broker_or_account_contacted:
        return fail(
            "OBSERVER_BROKER_ACCOUNT_CONTACT_VIOLATION",
            "Observer contacted a broker or account endpoint.",
        )
    if (
        safety.paper_authority_used
        or safety.execution_authority_used
        or observer_result.get("orderTransmission") != "UNAVAILABLE"
    ):
        return fail(
            "EXECUTION_AUTHORITY_PRESENT",
            "Observer evidence indicates Paper or execution authority.",
        )

    return {
        "schemaVersion": HEARTBEAT_POLICY_RESULT_SCHEMA,
        "heartbeatResult": "PASS",
        "classification": "AUTHORIZED_OBSERVER_CAPTURE_VALID",
        "diagnosticCode": "AUTHORIZED_OBSERVER_CAPTURE_VALID",
        "diagnosticMessage": (
            "Observer safety and authorized release binding are verified."
        ),
        "failClosed": False,
        "observerRuntimeIdentity": safety.observer_runtime_identity,
        "observerInstanceCount": safety.observer_instance_count,
        "authorizedReleaseBindingResult": observer_result["observerResult"],
        "authorizedReleaseBindingDiagnostic": observer_result["diagnosticCode"],
        "expectedReleaseId": observer_result["expectedReleaseId"],
        "expectedRuntimeFingerprint": observer_result["expectedRuntimeFingerprint"],
        "expectedReleaseSourceGitSha": observer_result[
            "expectedReleaseSourceGitSha"
        ],
        "actualCanonicalGitSha": observer_result["actualCanonicalGitSha"],
        "authorizedReleaseSourceProvenanceVerified": observer_result[
            "authorizedReleaseSourceProvenanceVerified"
        ],
        "currentSourceEqualsReleaseSource": observer_result[
            "currentSourceEqualsReleaseSource"
        ],
        "sourceGitRelationship": observer_result["sourceGitRelationship"],
        "readOnly": True,
        "protectedProductionHashesUnchanged": True,
        "servicesUnchanged": True,
        "schedulerUnchanged": True,
        "canonicalLocalOriginSynchronized": True,
        "externalProviderOrAuthenticationContacted": False,
        "brokerOrAccountContacted": False,
        "paperAuthorityUsed": False,
        "executionAuthorityUsed": False,
        "mutationPerformed": False,
        "orderTransmission": "UNAVAILABLE",
    }


def observe_opening_runtime(
    observation_payload: Mapping[str, object],
    *,
    expected_canonical_git_sha: str,
    release_root: Path = DEFAULT_RELEASE_ROOT,
    channel: str = DEFAULT_CHANNEL,
    mode: str = CURRENT_AUTHORIZED_RELEASE,
    fixed_expected_release_id: str | None = None,
    fixed_expected_runtime_fingerprint: str | None = None,
) -> dict[str, object]:
    try:
        expectation = resolve_authorized_opening_expectation(
            release_root,
            channel=channel,
            mode=mode,
            fixed_expected_release_id=fixed_expected_release_id,
            fixed_expected_runtime_fingerprint=fixed_expected_runtime_fingerprint,
        )
    except OpeningRuntimeIdentityError as exc:
        return _failure(
            classification="UNKNOWN_AUTHORIZED_RELEASE",
            diagnostic_code=exc.code,
            diagnostic_message=str(exc),
            expected_canonical_git_sha=expected_canonical_git_sha,
            details=exc.details,
        )
    try:
        observation = OpeningRuntimeObservation.from_mapping(observation_payload)
    except OpeningRuntimeIdentityError as exc:
        return _failure(
            classification="RUNTIME_EVIDENCE_INVALID",
            diagnostic_code=exc.code,
            diagnostic_message=str(exc),
            expected_canonical_git_sha=expected_canonical_git_sha,
            expectation=expectation,
            details=exc.details,
        )
    return evaluate_opening_runtime_observation(
        expectation,
        observation,
        expected_canonical_git_sha=expected_canonical_git_sha,
    )
