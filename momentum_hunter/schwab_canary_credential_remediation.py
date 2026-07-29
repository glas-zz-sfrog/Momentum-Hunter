from __future__ import annotations

"""Fail-closed evidence gate for the known Schwab credential incident."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
import re
from typing import Final


CANARY_CREDENTIAL_REMEDIATION_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_CREDENTIAL_REMEDIATION_V1"
)
CREDENTIAL_REMEDIATION_PASS: Final = "PASS"
CREDENTIAL_REMEDIATION_BLOCK: Final = "BLOCK"
CREDENTIAL_REMEDIATION_PROVEN: Final = "CREDENTIAL_REMEDIATION_PROVEN"
CREDENTIAL_REMEDIATION_REQUIRED: Final = "CREDENTIAL_REMEDIATION_REQUIRED"
SECRET_ROTATED: Final = "SECRET_ROTATED"
APPLICATION_REPLACED: Final = "APPLICATION_REPLACED"
VENDOR_REMEDIATED: Final = "VENDOR_REMEDIATED"
UNREMEDIATED: Final = "UNREMEDIATED"
ACCEPTED_REMEDIATION_STATES: Final = frozenset(
    {
        SECRET_ROTATED,
        APPLICATION_REPLACED,
        VENDOR_REMEDIATED,
    }
)
DEFAULT_EVIDENCE_SOURCES: Final = (
    "SCHWAB_DEVELOPER_PORTAL",
    "SCHWAB_SUPPORT",
)
_SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CanaryCredentialRemediationError(ValueError):
    pass


@dataclass(frozen=True)
class CanaryCredentialRemediationPolicy:
    expected_incident_id: str
    expected_application_commitment_sha256: str
    expected_evidence_artifact_sha256: str
    incident_recorded_at: datetime
    accepted_evidence_sources: tuple[str, ...] = DEFAULT_EVIDENCE_SOURCES
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        incident_id = _require_identifier(
            self.expected_incident_id,
            field="expected credential incident ID",
        )
        application = _require_sha256(
            self.expected_application_commitment_sha256,
            field="expected application commitment",
        )
        evidence = _require_sha256(
            self.expected_evidence_artifact_sha256,
            field="expected remediation evidence",
        )
        incident_at = _require_aware_datetime(
            self.incident_recorded_at,
            field="credential incident time",
        )
        sources = tuple(
            _require_identifier(source, field="accepted evidence source")
            for source in self.accepted_evidence_sources
        )
        if not sources or len(set(sources)) != len(sources):
            raise CanaryCredentialRemediationError(
                "Accepted evidence sources must be unique and non-empty."
            )
        if (
            not _is_finite_number(self.max_future_skew_seconds)
            or self.max_future_skew_seconds < 0
        ):
            raise CanaryCredentialRemediationError(
                "Maximum future clock skew must be finite and non-negative."
            )
        object.__setattr__(self, "expected_incident_id", incident_id)
        object.__setattr__(
            self,
            "expected_application_commitment_sha256",
            application,
        )
        object.__setattr__(
            self,
            "expected_evidence_artifact_sha256",
            evidence,
        )
        object.__setattr__(self, "incident_recorded_at", incident_at)
        object.__setattr__(self, "accepted_evidence_sources", sources)


@dataclass(frozen=True, repr=False)
class CanaryCredentialRemediationObservation:
    incident_id: str
    application_commitment_sha256: str
    remediation_state: str
    evidence_source: str
    evidence_artifact_sha256: str
    observed_at: str
    old_credential_invalidated: bool

    def __repr__(self) -> str:
        return (
            "CanaryCredentialRemediationObservation("
            f"incident_id={self.incident_id!r}, "
            f"remediation_state={self.remediation_state!r}, "
            f"evidence_source={self.evidence_source!r}, "
            f"old_credential_invalidated={self.old_credential_invalidated!r})"
        )


@dataclass(frozen=True)
class CanaryCredentialRemediationFinding:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, repr=False)
class CanaryCredentialRemediationResult:
    status: str
    conclusion: str
    evaluated_at: str
    incident_id: str
    application_commitment_sha256: str
    remediation_state: str
    evidence_source: str | None
    evidence_artifact_sha256: str
    observed_at: str | None
    old_credential_invalidated: bool
    findings: tuple[CanaryCredentialRemediationFinding, ...]

    @property
    def remediation_proven(self) -> bool:
        return self.status == CREDENTIAL_REMEDIATION_PASS

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_CREDENTIAL_REMEDIATION_SCHEMA_VERSION,
            "status": self.status,
            "conclusion": self.conclusion,
            "evaluatedAt": self.evaluated_at,
            "incidentId": self.incident_id,
            "applicationCommitmentSha256": (
                self.application_commitment_sha256
            ),
            "remediationState": self.remediation_state,
            "evidenceSource": self.evidence_source,
            "evidenceArtifactSha256": self.evidence_artifact_sha256,
            "observedAt": self.observed_at,
            "oldCredentialInvalidated": self.old_credential_invalidated,
            "findings": [finding.to_dict() for finding in self.findings],
            "remediationProven": self.remediation_proven,
            "credentialAccessed": False,
            "credentialMutationPerformed": False,
            "providerContactPerformed": False,
            "executionPermit": False,
            "brokerActionAllowed": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def __repr__(self) -> str:
        return (
            "CanaryCredentialRemediationResult("
            f"status={self.status!r}, conclusion={self.conclusion!r}, "
            f"incident_id={self.incident_id!r}, "
            f"remediation_state={self.remediation_state!r}, "
            f"finding_count={len(self.findings)})"
        )


def evaluate_canary_credential_remediation(
    *,
    observation: CanaryCredentialRemediationObservation | None,
    evaluated_at: datetime,
    policy: CanaryCredentialRemediationPolicy,
) -> CanaryCredentialRemediationResult:
    """Evaluate sanitized evidence without accessing or changing credentials."""

    evaluated = _require_aware_datetime(
        evaluated_at,
        field="credential remediation evaluation time",
    )
    findings: list[CanaryCredentialRemediationFinding] = []

    def add(code: str, message: str) -> None:
        findings.append(
            CanaryCredentialRemediationFinding(code=code, message=message)
        )

    if observation is None:
        add(
            "REMEDIATION_EVIDENCE_MISSING",
            "No reviewed credential-remediation evidence was supplied.",
        )
        remediation_state = UNREMEDIATED
        evidence_source = None
        observed_at = None
        invalidated = False
    else:
        remediation_state = str(observation.remediation_state).strip().upper()
        evidence_source = str(observation.evidence_source).strip().upper()
        observed_at = str(observation.observed_at).strip()
        invalidated = observation.old_credential_invalidated is True
        if observation.incident_id != policy.expected_incident_id:
            add(
                "INCIDENT_ID_MISMATCH",
                "Credential-remediation evidence targets a different incident.",
            )
        if (
            str(observation.application_commitment_sha256).strip().lower()
            != policy.expected_application_commitment_sha256
        ):
            add(
                "APPLICATION_COMMITMENT_MISMATCH",
                "Credential-remediation evidence targets a different application.",
            )
        if (
            str(observation.evidence_artifact_sha256).strip().lower()
            != policy.expected_evidence_artifact_sha256
        ):
            add(
                "EVIDENCE_ARTIFACT_MISMATCH",
                "Credential-remediation evidence does not match the reviewed artifact.",
            )
        if remediation_state not in ACCEPTED_REMEDIATION_STATES:
            add(
                "REMEDIATION_STATE_NOT_ACCEPTED",
                "Rotation, application replacement, or explicit vendor remediation "
                "has not been proven.",
            )
        if evidence_source not in policy.accepted_evidence_sources:
            add(
                "EVIDENCE_SOURCE_NOT_ACCEPTED",
                "Credential-remediation evidence has an unsupported source.",
            )
        if not invalidated:
            add(
                "OLD_CREDENTIAL_NOT_INVALIDATED",
                "The previously surfaced credential is not proven invalidated.",
            )
        observed = _parse_timestamp(observed_at)
        if observed is None:
            add(
                "OBSERVATION_TIME_INVALID",
                "Credential-remediation evidence time is invalid or timezone-naive.",
            )
        else:
            if observed < policy.incident_recorded_at:
                add(
                    "REMEDIATION_PREDATES_INCIDENT",
                    "Credential-remediation evidence predates the recorded incident.",
                )
            if (
                (observed - evaluated).total_seconds()
                > policy.max_future_skew_seconds
            ):
                add(
                    "REMEDIATION_TIME_IN_FUTURE",
                    "Credential-remediation evidence is later than permitted clock skew.",
                )
            observed_at = observed.isoformat()

    normalized = tuple(_deduplicate_findings(findings))
    passed = not normalized
    return CanaryCredentialRemediationResult(
        status=(
            CREDENTIAL_REMEDIATION_PASS
            if passed
            else CREDENTIAL_REMEDIATION_BLOCK
        ),
        conclusion=(
            CREDENTIAL_REMEDIATION_PROVEN
            if passed
            else CREDENTIAL_REMEDIATION_REQUIRED
        ),
        evaluated_at=evaluated.isoformat(),
        incident_id=policy.expected_incident_id,
        application_commitment_sha256=(
            policy.expected_application_commitment_sha256
        ),
        remediation_state=remediation_state,
        evidence_source=evidence_source,
        evidence_artifact_sha256=policy.expected_evidence_artifact_sha256,
        observed_at=observed_at,
        old_credential_invalidated=invalidated,
        findings=normalized,
    )


def _parse_timestamp(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _deduplicate_findings(
    findings: list[CanaryCredentialRemediationFinding],
) -> list[CanaryCredentialRemediationFinding]:
    seen: set[tuple[str, str]] = set()
    result: list[CanaryCredentialRemediationFinding] = []
    for finding in findings:
        identity = (finding.code, finding.message)
        if identity not in seen:
            seen.add(identity)
            result.append(finding)
    return result


def _require_identifier(value: object, *, field: str) -> str:
    normalized = str(value).strip().upper()
    if not _SIMPLE_IDENTIFIER.fullmatch(normalized):
        raise CanaryCredentialRemediationError(f"{field} is invalid.")
    return normalized


def _require_sha256(value: object, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if not _HEX_SHA256.fullmatch(normalized):
        raise CanaryCredentialRemediationError(
            f"{field} must be a lowercase SHA-256 value."
        )
    return normalized


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise CanaryCredentialRemediationError(
            f"{field} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryCredentialRemediationError(
            f"{field} must be timezone-aware."
        )
    return value


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )
