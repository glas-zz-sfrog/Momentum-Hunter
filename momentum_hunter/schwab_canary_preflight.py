from __future__ import annotations

"""Fail-closed composition of supervised Schwab plumbing-canary evidence."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
import re
from typing import Callable, Final

from momentum_hunter.schwab_canary_credential_remediation import (
    CREDENTIAL_REMEDIATION_PASS,
    CREDENTIAL_REMEDIATION_PROVEN,
    CanaryCredentialRemediationResult,
)
from momentum_hunter.schwab_canary_evidence import (
    PRE_CANARY_VERIFIED,
    CanaryPositionEvidenceError,
    CanaryPositionEvidenceStore,
)
from momentum_hunter.schwab_canary_funding import (
    RESTRICTIONS_CLEAR,
    CanaryFundingResult,
)
from momentum_hunter.schwab_canary_order_reconciliation import (
    CanaryOrderReconciliationResult,
)
from momentum_hunter.schwab_canary_positions import (
    PRE_CANARY,
    CanaryPositionInvariantResult,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CREDENTIAL_REVOKED,
    CanaryStopDrillResult,
)


CANARY_PREFLIGHT_SCHEMA_VERSION_V1: Final = "SCHWAB_CANARY_PREFLIGHT_V1"
CANARY_PREFLIGHT_SCHEMA_VERSION: Final = "SCHWAB_CANARY_PREFLIGHT_V2"
PREFLIGHT_READY: Final = "READY_FOR_DECISION"
PREFLIGHT_BLOCKED: Final = "BLOCK"
PREFLIGHT_READY_CONCLUSION: Final = (
    "PRECONDITIONS_PROVEN_AWAITING_STEVEN_REAL_ORDER_DECISION"
)
PREFLIGHT_BLOCKED_CONCLUSION: Final = "PLUMBING_CANARY_PREFLIGHT_BLOCKED"
NO_PRIOR_SUBMISSION_EVIDENCE: Final = "NO_PRIOR_SUBMISSION_EVIDENCE"
INDEPENDENT_STOP_DRILL_PROVEN: Final = "INDEPENDENT_STOP_DRILL_PROVEN"
_SIMPLE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPONENTS: Final = (
    "positionInvariant",
    "positionEvidenceChain",
    "fundingGate",
    "credentialRemediation",
    "orderReconciliation",
    "independentStopDrill",
)
_AddFinding = Callable[[str, str, str], None]


class CanaryPreflightError(ValueError):
    pass


@dataclass(frozen=True)
class CanaryPreflightPolicy:
    expected_account_ending: str
    expected_account_type: str
    expected_canary_intent_id: str
    expected_sequence_id: str
    expected_funding_requirement_id: str
    expected_credential_incident_id: str
    expected_application_commitment_sha256: str
    expected_credential_evidence_sha256: str
    expected_order_command_id: str
    expected_stop_latch_sha256: str
    max_evidence_age_seconds: float
    max_future_skew_seconds: float = 2.0

    def __post_init__(self) -> None:
        ending = str(self.expected_account_ending).strip()
        if len(ending) != 4 or not ending.isdigit():
            raise CanaryPreflightError(
                "Expected account ending must contain exactly four digits."
            )
        object.__setattr__(self, "expected_account_ending", ending)
        account_type = str(self.expected_account_type).strip().upper()
        if not account_type or not account_type.isascii():
            raise CanaryPreflightError("Expected account type is required.")
        object.__setattr__(self, "expected_account_type", account_type)
        for attribute, field in (
            ("expected_canary_intent_id", "canary intent ID"),
            ("expected_sequence_id", "sequence ID"),
            ("expected_funding_requirement_id", "funding requirement ID"),
            ("expected_credential_incident_id", "credential incident ID"),
            ("expected_order_command_id", "order command ID"),
        ):
            value = str(getattr(self, attribute)).strip()
            if not _SIMPLE_IDENTIFIER.fullmatch(value):
                raise CanaryPreflightError(f"Expected {field} is invalid.")
            object.__setattr__(self, attribute, value)
        for attribute, field in (
            (
                "expected_application_commitment_sha256",
                "application commitment",
            ),
            (
                "expected_credential_evidence_sha256",
                "credential evidence",
            ),
        ):
            value = str(getattr(self, attribute)).strip().lower()
            if not _HEX_SHA256.fullmatch(value):
                raise CanaryPreflightError(
                    f"Expected {field} must be a lowercase SHA-256 value."
                )
            object.__setattr__(self, attribute, value)
        latch_sha256 = str(self.expected_stop_latch_sha256).strip().lower()
        if not _HEX_SHA256.fullmatch(latch_sha256):
            raise CanaryPreflightError(
                "Expected stop latch SHA-256 must be 64 lowercase hexadecimal characters."
            )
        object.__setattr__(
            self,
            "expected_stop_latch_sha256",
            latch_sha256,
        )
        if (
            not _is_finite_number(self.max_evidence_age_seconds)
            or self.max_evidence_age_seconds <= 0
        ):
            raise CanaryPreflightError(
                "Maximum evidence age must be finite and greater than zero."
            )
        if (
            not _is_finite_number(self.max_future_skew_seconds)
            or self.max_future_skew_seconds < 0
        ):
            raise CanaryPreflightError(
                "Maximum future clock skew must be finite and non-negative."
            )


@dataclass(frozen=True)
class CanaryPreflightFinding:
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
class CanaryPreflightResult:
    status: str
    conclusion: str
    evaluated_at: str
    account_ending: str
    account_type: str
    canary_intent_id: str
    sequence_id: str
    funding_requirement_id: str
    credential_incident_id: str
    application_commitment_sha256: str
    credential_evidence_sha256: str
    order_command_id: str
    stop_latch_sha256: str
    component_statuses: tuple[tuple[str, str], ...]
    findings: tuple[CanaryPreflightFinding, ...]

    @property
    def ready_for_manual_decision(self) -> bool:
        return self.status == PREFLIGHT_READY

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_PREFLIGHT_SCHEMA_VERSION,
            "status": self.status,
            "conclusion": self.conclusion,
            "evaluatedAt": self.evaluated_at,
            "accountEnding": self.account_ending,
            "accountType": self.account_type,
            "canaryIntentId": self.canary_intent_id,
            "sequenceId": self.sequence_id,
            "fundingRequirementId": self.funding_requirement_id,
            "credentialIncidentId": self.credential_incident_id,
            "applicationCommitmentSha256": (
                self.application_commitment_sha256
            ),
            "credentialEvidenceSha256": self.credential_evidence_sha256,
            "orderCommandId": self.order_command_id,
            "stopLatchSha256": self.stop_latch_sha256,
            "components": dict(self.component_statuses),
            "findings": [finding.to_dict() for finding in self.findings],
            "readyForManualDecision": self.ready_for_manual_decision,
            "manualDecisionRequired": True,
            "executionPermit": False,
            "realOrderApproval": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


def evaluate_canary_preflight(
    *,
    evidence_store: CanaryPositionEvidenceStore,
    position_result: CanaryPositionInvariantResult,
    funding_result: CanaryFundingResult,
    credential_result: CanaryCredentialRemediationResult,
    order_result: CanaryOrderReconciliationResult,
    stop_result: CanaryStopDrillResult,
    evaluated_at: datetime,
    policy: CanaryPreflightPolicy,
) -> CanaryPreflightResult:
    """Compose already-collected evidence without granting execution authority."""

    normalized_evaluated_at = _require_aware_datetime(
        evaluated_at,
        field="evaluated_at",
    )
    findings: list[CanaryPreflightFinding] = []

    def add(component: str, code: str, message: str) -> None:
        findings.append(
            CanaryPreflightFinding(
                component=component,
                code=code,
                message=message,
            )
        )

    _validate_position_result(
        result=position_result,
        evaluated_at=normalized_evaluated_at,
        policy=policy,
        add=add,
    )
    chain: dict[str, object] | None = None
    try:
        chain = evidence_store.load()
    except (CanaryPositionEvidenceError, OSError) as exc:
        add(
            "positionEvidenceChain",
            "POSITION_EVIDENCE_INVALID",
            f"The immutable position evidence chain could not be validated: {exc}",
        )
    if chain is not None:
        _validate_position_chain(
            evidence_store=evidence_store,
            chain=chain,
            position_result=position_result,
            evaluated_at=normalized_evaluated_at,
            policy=policy,
            add=add,
        )
    _validate_funding_result(
        result=funding_result,
        evaluated_at=normalized_evaluated_at,
        policy=policy,
        add=add,
    )
    _validate_credential_result(
        result=credential_result,
        evaluated_at=normalized_evaluated_at,
        policy=policy,
        add=add,
    )
    _validate_order_result(
        result=order_result,
        evaluated_at=normalized_evaluated_at,
        policy=policy,
        add=add,
    )
    _validate_stop_result(
        result=stop_result,
        evaluated_at=normalized_evaluated_at,
        policy=policy,
        add=add,
    )

    component_statuses = tuple(
        (
            component,
            (
                "BLOCK"
                if any(finding.component == component for finding in findings)
                else "PASS"
            ),
        )
        for component in _COMPONENTS
    )
    ready = not findings
    return CanaryPreflightResult(
        status=PREFLIGHT_READY if ready else PREFLIGHT_BLOCKED,
        conclusion=(
            PREFLIGHT_READY_CONCLUSION
            if ready
            else PREFLIGHT_BLOCKED_CONCLUSION
        ),
        evaluated_at=normalized_evaluated_at.isoformat(),
        account_ending=policy.expected_account_ending,
        account_type=policy.expected_account_type,
        canary_intent_id=policy.expected_canary_intent_id,
        sequence_id=policy.expected_sequence_id,
        funding_requirement_id=policy.expected_funding_requirement_id,
        credential_incident_id=policy.expected_credential_incident_id,
        application_commitment_sha256=(
            policy.expected_application_commitment_sha256
        ),
        credential_evidence_sha256=(
            policy.expected_credential_evidence_sha256
        ),
        order_command_id=policy.expected_order_command_id,
        stop_latch_sha256=policy.expected_stop_latch_sha256,
        component_statuses=component_statuses,
        findings=tuple(findings),
    )


def _validate_position_result(
    *,
    result: CanaryPositionInvariantResult,
    evaluated_at: datetime,
    policy: CanaryPreflightPolicy,
    add: _AddFinding,
) -> None:
    component = "positionInvariant"
    if not result.passed or result.findings:
        add(
            component,
            "POSITION_INVARIANT_NOT_PROVEN",
            "The PRE_CANARY position invariant did not pass cleanly.",
        )
    if result.phase != PRE_CANARY:
        add(component, "POSITION_PHASE_MISMATCH", "The position result is not PRE_CANARY evidence.")
    _check_identity(
        component=component,
        actual=result.account_ending,
        expected=policy.expected_account_ending,
        code="POSITION_ACCOUNT_ENDING_MISMATCH",
        message="The position result account ending does not match policy.",
        add=add,
    )
    _check_identity(
        component=component,
        actual=result.account_type,
        expected=policy.expected_account_type,
        code="POSITION_ACCOUNT_TYPE_MISMATCH",
        message="The position result account type does not match policy.",
        add=add,
    )
    _check_identity(
        component=component,
        actual=result.canary_intent_id,
        expected=policy.expected_canary_intent_id,
        code="POSITION_INTENT_MISMATCH",
        message="The position result intent ID does not match policy.",
        add=add,
    )
    _check_freshness(
        component=component,
        timestamp=result.evaluated_at,
        evaluated_at=evaluated_at,
        policy=policy,
        label="position result",
        add=add,
    )
    payload = result.to_dict()
    _require_nontransmitting_flags(component, payload, add)


def _validate_position_chain(
    *,
    evidence_store: CanaryPositionEvidenceStore,
    chain: dict[str, object],
    position_result: CanaryPositionInvariantResult,
    evaluated_at: datetime,
    policy: CanaryPreflightPolicy,
    add: _AddFinding,
) -> None:
    component = "positionEvidenceChain"
    expected_identity = (
        ("sequenceId", policy.expected_sequence_id, "CHAIN_SEQUENCE_MISMATCH"),
        ("accountEnding", policy.expected_account_ending, "CHAIN_ACCOUNT_ENDING_MISMATCH"),
        ("accountType", policy.expected_account_type, "CHAIN_ACCOUNT_TYPE_MISMATCH"),
    )
    for key, expected, code in expected_identity:
        if chain.get(key) != expected:
            add(component, code, f"The position evidence {key} does not match policy.")
    if evidence_store.sequence_id != policy.expected_sequence_id:
        add(
            component,
            "STORE_SEQUENCE_MISMATCH",
            "The evidence store sequence ID does not match policy.",
        )
    if evidence_store.intent.intent_id != policy.expected_canary_intent_id:
        add(
            component,
            "STORE_INTENT_MISMATCH",
            "The evidence store intent ID does not match policy.",
        )
    intent = chain.get("intent")
    if (
        not isinstance(intent, dict)
        or intent.get("intentId") != policy.expected_canary_intent_id
    ):
        add(
            component,
            "CHAIN_INTENT_MISMATCH",
            "The position evidence intent does not match policy.",
        )
    if chain.get("chainState") != PRE_CANARY_VERIFIED:
        add(
            component,
            "CHAIN_STATE_INVALID",
            "The position evidence chain is not exactly PRE_CANARY_VERIFIED.",
        )
    entries = chain.get("entries")
    if not isinstance(entries, list) or len(entries) != 1:
        add(
            component,
            "CHAIN_ENTRY_COUNT_INVALID",
            "The preflight requires exactly one PRE_CANARY evidence entry.",
        )
    elif entries[0].get("result") != position_result.to_dict():
        add(
            component,
            "CHAIN_RESULT_MISMATCH",
            "The supplied position result is not the validated chain result.",
        )
    _check_freshness(
        component=component,
        timestamp=str(chain.get("updatedAt", "")),
        evaluated_at=evaluated_at,
        policy=policy,
        label="position evidence chain",
        add=add,
    )
    _require_nontransmitting_flags(component, chain, add)


def _validate_funding_result(
    *,
    result: CanaryFundingResult,
    evaluated_at: datetime,
    policy: CanaryPreflightPolicy,
    add: _AddFinding,
) -> None:
    component = "fundingGate"
    if not result.passed or result.findings:
        add(
            component,
            "FUNDING_GATE_NOT_PROVEN",
            "Settled cash and restrictions did not pass cleanly.",
        )
    if not result.settled_cash_available or result.settled_cash_sufficient is not True:
        add(
            component,
            "SETTLED_CASH_NOT_PROVEN",
            "Sufficient settled cash was not independently proven.",
        )
    if result.restriction_state != RESTRICTIONS_CLEAR or result.restriction_codes:
        add(
            component,
            "ACCOUNT_RESTRICTIONS_NOT_CLEAR",
            "Account restrictions were not proven clear.",
        )
    for actual, expected, code, message in (
        (
            result.account_ending,
            policy.expected_account_ending,
            "FUNDING_ACCOUNT_ENDING_MISMATCH",
            "Funding account ending does not match policy.",
        ),
        (
            result.account_type,
            policy.expected_account_type,
            "FUNDING_ACCOUNT_TYPE_MISMATCH",
            "Funding account type does not match policy.",
        ),
        (
            result.requirement_id,
            policy.expected_funding_requirement_id,
            "FUNDING_REQUIREMENT_MISMATCH",
            "Funding requirement ID does not match policy.",
        ),
    ):
        _check_identity(
            component=component,
            actual=actual,
            expected=expected,
            code=code,
            message=message,
            add=add,
        )
    _check_freshness(
        component=component,
        timestamp=result.evaluated_at,
        evaluated_at=evaluated_at,
        policy=policy,
        label="funding result",
        add=add,
    )
    _require_nontransmitting_flags(component, result.to_dict(), add)


def _validate_credential_result(
    *,
    result: CanaryCredentialRemediationResult,
    evaluated_at: datetime,
    policy: CanaryPreflightPolicy,
    add: _AddFinding,
) -> None:
    component = "credentialRemediation"
    if (
        result.status != CREDENTIAL_REMEDIATION_PASS
        or result.conclusion != CREDENTIAL_REMEDIATION_PROVEN
        or result.findings
        or not result.remediation_proven
        or result.old_credential_invalidated is not True
    ):
        add(
            component,
            "CREDENTIAL_REMEDIATION_NOT_PROVEN",
            "The known credential incident has not been remediated.",
        )
    for actual, expected, code, message in (
        (
            result.incident_id,
            policy.expected_credential_incident_id,
            "CREDENTIAL_INCIDENT_MISMATCH",
            "Credential incident ID does not match policy.",
        ),
        (
            result.application_commitment_sha256,
            policy.expected_application_commitment_sha256,
            "CREDENTIAL_APPLICATION_MISMATCH",
            "Credential application commitment does not match policy.",
        ),
        (
            result.evidence_artifact_sha256,
            policy.expected_credential_evidence_sha256,
            "CREDENTIAL_EVIDENCE_MISMATCH",
            "Credential-remediation evidence hash does not match policy.",
        ),
    ):
        _check_identity(
            component=component,
            actual=actual,
            expected=expected,
            code=code,
            message=message,
            add=add,
        )
    _check_freshness(
        component=component,
        timestamp=result.evaluated_at,
        evaluated_at=evaluated_at,
        policy=policy,
        label="credential-remediation result",
        add=add,
    )
    payload = result.to_dict()
    _require_nontransmitting_flags(component, payload, add)
    if (
        payload.get("credentialAccessed") is not False
        or payload.get("credentialMutationPerformed") is not False
        or payload.get("providerContactPerformed") is not False
        or payload.get("executionPermit") is not False
        or payload.get("brokerActionAllowed") is not False
        or payload.get("retryAllowed") is not False
    ):
        add(
            component,
            "CREDENTIAL_REMEDIATION_SAFETY_FLAGS_INVALID",
            "Credential-remediation evidence contains an authority-bearing flag.",
        )


def _validate_order_result(
    *,
    result: CanaryOrderReconciliationResult,
    evaluated_at: datetime,
    policy: CanaryPreflightPolicy,
    add: _AddFinding,
) -> None:
    component = "orderReconciliation"
    if (
        result.status != "BLOCK"
        or result.conclusion != NO_PRIOR_SUBMISSION_EVIDENCE
        or result.attempt_recorded
        or result.exact_match_count != 0
        or result.provider_order_id is not None
        or result.broker_status is not None
        or result.findings
    ):
        add(
            component,
            "ORDER_PREFLIGHT_STATE_INVALID",
            "Order evidence must prove no prior attempt and no broker match.",
        )
    _check_identity(
        component=component,
        actual=result.command_id,
        expected=policy.expected_order_command_id,
        code="ORDER_COMMAND_MISMATCH",
        message="Order command ID does not match policy.",
        add=add,
    )
    _check_identity(
        component=component,
        actual=result.sequence_id,
        expected=policy.expected_sequence_id,
        code="ORDER_SEQUENCE_MISMATCH",
        message="Order sequence ID does not match policy.",
        add=add,
    )
    _check_freshness(
        component=component,
        timestamp=result.evaluated_at,
        evaluated_at=evaluated_at,
        policy=policy,
        label="order reconciliation result",
        add=add,
    )
    payload = result.to_dict()
    _require_nontransmitting_flags(component, payload, add)
    if payload.get("retryAllowed") is not False:
        add(
            component,
            "ORDER_RETRY_FLAG_INVALID",
            "The order reconciliation result cannot allow retry.",
        )


def _validate_stop_result(
    *,
    result: CanaryStopDrillResult,
    evaluated_at: datetime,
    policy: CanaryPreflightPolicy,
    add: _AddFinding,
) -> None:
    component = "independentStopDrill"
    if not result.passed or result.findings:
        add(component, "STOP_DRILL_NOT_PROVEN", "The independent stop drill did not pass cleanly.")
    if result.conclusion != INDEPENDENT_STOP_DRILL_PROVEN:
        add(component, "STOP_DRILL_CONCLUSION_INVALID", "The stop drill conclusion is not proven.")
    if result.latch_sha256 != policy.expected_stop_latch_sha256:
        add(component, "STOP_LATCH_MISMATCH", "The stop drill latch does not match policy.")
    if result.process_running is not False:
        add(
            component,
            "STOP_PROCESS_STATE_INVALID",
            "Independent evidence does not prove the runtime stopped.",
        )
    if result.credential_state != CREDENTIAL_REVOKED:
        add(
            component,
            "STOP_CREDENTIAL_STATE_INVALID",
            "Provider evidence does not prove credential revocation.",
        )
    _check_freshness(
        component=component,
        timestamp=result.evaluated_at,
        evaluated_at=evaluated_at,
        policy=policy,
        label="independent stop result",
        add=add,
    )
    payload = result.to_dict()
    if (
        payload.get("executionPermit") is not False
        or payload.get("latchClearSupported") is not False
        or payload.get("credentialMutationPerformed") is not False
        or payload.get("processMutationPerformed") is not False
        or payload.get("orderTransmission") != "UNAVAILABLE"
    ):
        add(component, "STOP_SAFETY_FLAGS_INVALID", "The stop drill safety flags are invalid.")


def _require_nontransmitting_flags(
    component: str,
    payload: dict[str, object],
    add: _AddFinding,
) -> None:
    if (
        payload.get("transmitting") is not False
        or payload.get("orderTransmission") != "UNAVAILABLE"
    ):
        add(
            component,
            "NONTRANSMITTING_FLAGS_INVALID",
            "The evidence does not preserve the nontransmitting boundary.",
        )


def _check_identity(
    *,
    component: str,
    actual: object,
    expected: object,
    code: str,
    message: str,
    add: _AddFinding,
) -> None:
    if actual != expected:
        add(component, code, message)


def _check_freshness(
    *,
    component: str,
    timestamp: str,
    evaluated_at: datetime,
    policy: CanaryPreflightPolicy,
    label: str,
    add: _AddFinding,
) -> None:
    try:
        evidence_at = _parse_timestamp(timestamp, field=label)
    except CanaryPreflightError as exc:
        add(component, "EVIDENCE_TIMESTAMP_INVALID", str(exc))
        return
    age_seconds = (evaluated_at - evidence_at).total_seconds()
    if age_seconds < -policy.max_future_skew_seconds:
        add(component, "EVIDENCE_FROM_FUTURE", f"The {label} timestamp is in the future.")
    elif age_seconds > policy.max_evidence_age_seconds:
        add(component, "EVIDENCE_STALE", f"The {label} is older than policy allows.")


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryPreflightError(f"{field} must be timezone-aware.")
    return value


def _parse_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CanaryPreflightError(
            f"{field} timestamp must be valid ISO-8601."
        ) from exc
    return _require_aware_datetime(parsed, field=f"{field} timestamp")


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
    )
