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
CURRENT_AUTHORIZED_RELEASE = "CURRENT_AUTHORIZED_RELEASE"
FIXED_EXPECTED_RELEASE = "FIXED_EXPECTED_RELEASE"
OBSERVER_MODES = (CURRENT_AUTHORIZED_RELEASE, FIXED_EXPECTED_RELEASE)


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
    return {
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
    return {
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
