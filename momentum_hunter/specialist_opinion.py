"""Provider-neutral, research-only specialist opinion contract.

This module defines immutable analysis packets. It has no provider, account,
broker, order, scheduler, service, Engine Host, WPF, or persistence capability.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


CONTRACT_VERSION = 1
RESEARCH_ONLY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY_NONE = "EXECUTION_AUTHORITY_NONE"

EVALUATED = "EVALUATED"
ABSTAINED = "ABSTAINED"
FAILED = "FAILED"
EVALUATION_STATUSES = frozenset({EVALUATED, ABSTAINED, FAILED})

BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"
NON_DIRECTIONAL = "NON_DIRECTIONAL"
NO_DIRECTION = "NONE"
DIRECTIONAL_BIASES = frozenset(
    {BULLISH, BEARISH, NEUTRAL, NON_DIRECTIONAL, NO_DIRECTION}
)

NO_OPINION = "NO_OPINION"
ABSTENTION_REASONS = frozenset(
    {
        NO_OPINION,
        "INSUFFICIENT_EVIDENCE",
        "OUT_OF_DOMAIN",
        "STALE_EVIDENCE",
        "CONTRADICTORY_EVIDENCE",
        "DATA_BASIS_UNCERTAIN",
        "UNSUPPORTED_SESSION",
    }
)

CONFIDENCE_UNAVAILABLE = "UNAVAILABLE"
HEURISTIC = "HEURISTIC"
CALIBRATED_PROBABILITY = "CALIBRATED_PROBABILITY"
EMPIRICAL_FREQUENCY = "EMPIRICAL_FREQUENCY"
MODEL_SCORE = "MODEL_SCORE"
CONFIDENCE_KINDS = frozenset(
    {
        CONFIDENCE_UNAVAILABLE,
        HEURISTIC,
        CALIBRATED_PROBABILITY,
        EMPIRICAL_FREQUENCY,
        MODEL_SCORE,
    }
)

CALIBRATION_UNAVAILABLE = "UNAVAILABLE"
UNCALIBRATED = "UNCALIBRATED"
PROVISIONAL = "PROVISIONAL"
CALIBRATED = "CALIBRATED"
CALIBRATION_STATUSES = frozenset(
    {CALIBRATION_UNAVAILABLE, UNCALIBRATED, PROVISIONAL, CALIBRATED}
)

REFERENCE_SPECIALISTS = frozenset(
    {
        "MOMENTUM",
        "REGIME",
        "TECHNICAL_STRUCTURE",
        "EVENT_SHOCK",
        "STATISTICAL_OUTCOME",
        "EXECUTION_QUALITY",
        "EXIT_INTELLIGENCE",
        "BEARISH_EQUITY",
    }
)

REFERENCE_FEATURE_FAMILIES = frozenset(
    {
        "PRICE_MOMENTUM",
        "CANDLE_STRUCTURE",
        "VOLUME",
        "MARKET_REGIME",
        "SECTOR",
        "CATALYST",
        "NEWS",
        "EXECUTION_LIQUIDITY",
        "BROKER_STATE",
        "HISTORICAL_ANALOGS",
        "CORPORATE_ACTION",
    }
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_TOKEN = re.compile(r"[A-Z][A-Z0-9_]{0,95}")
_MAX_EVIDENCE_REFS = 128
_MAX_FEATURE_FAMILIES = 32
_MAX_REASON_CODES = 64
_MAX_EXPLANATION_CHARS = 2_000


class SpecialistOpinionError(ValueError):
    """Raised when a specialist opinion is ambiguous or contradictory."""


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: str
    evidence_type: str
    source: str
    as_of: str
    fingerprint: str


@dataclass(frozen=True)
class ConfidenceMetadata:
    available: bool
    value: float | None
    kind: str
    calibration_status: str
    sample_size: int | None
    model_version: str | None


@dataclass(frozen=True)
class SpecialistOpinion:
    contract_version: int
    specialist_id: str
    specialist_version: str
    opinion_id: str
    opportunity_id: str
    candidate_id: str | None
    setup_id: str | None
    trade_plan_id: str | None
    as_of: str
    expires_at: str
    research_identity: str
    policy_fingerprint: str
    input_evidence_fingerprint: str
    evaluation_status: str
    opinion_code: str | None
    directional_bias: str
    authority: str
    execution_authority: str
    abstention_reason: str | None
    failure_reason: str | None
    evidence_refs: tuple[EvidenceReference, ...] = field(default_factory=tuple)
    feature_families: tuple[str, ...] = field(default_factory=tuple)
    confidence: ConfidenceMetadata = field(
        default_factory=lambda: unavailable_confidence()
    )
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    explanation: str = ""
    fingerprint: str = ""


def build_evidence_reference(
    *,
    evidence_id: str,
    evidence_type: str,
    source: str,
    as_of: datetime | str,
    fingerprint: str,
) -> EvidenceReference:
    reference = EvidenceReference(
        evidence_id=_identifier(evidence_id, "Evidence identity"),
        evidence_type=_token(evidence_type, "Evidence type"),
        source=_identifier(source, "Evidence source"),
        as_of=_timestamp(as_of, "Evidence timestamp"),
        fingerprint=_sha256(fingerprint, "Evidence fingerprint"),
    )
    validate_evidence_reference(reference)
    return reference


def unavailable_confidence() -> ConfidenceMetadata:
    return ConfidenceMetadata(
        available=False,
        value=None,
        kind=CONFIDENCE_UNAVAILABLE,
        calibration_status=CALIBRATION_UNAVAILABLE,
        sample_size=None,
        model_version=None,
    )


def build_confidence(
    *,
    value: float,
    kind: str,
    calibration_status: str,
    sample_size: int | None,
    model_version: str,
) -> ConfidenceMetadata:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise SpecialistOpinionError("Confidence value must be finite numeric data.")
    confidence = ConfidenceMetadata(
        available=True,
        value=float(value),
        kind=str(kind).strip().upper(),
        calibration_status=str(calibration_status).strip().upper(),
        sample_size=sample_size,
        model_version=_identifier(model_version, "Confidence model version"),
    )
    validate_confidence(confidence)
    return confidence


def build_specialist_opinion(
    *,
    specialist_id: str,
    specialist_version: str,
    opportunity_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    trade_plan_id: str | None,
    as_of: datetime | str,
    expires_at: datetime | str,
    research_identity: str,
    policy_fingerprint: str,
    evaluation_status: str,
    opinion_code: str | None,
    directional_bias: str,
    evidence_refs: Iterable[EvidenceReference] = (),
    feature_families: Iterable[str] = (),
    confidence: ConfidenceMetadata | None = None,
    reason_codes: Iterable[str] = (),
    explanation: str = "",
    abstention_reason: str | None = None,
    failure_reason: str | None = None,
    authority: str = RESEARCH_ONLY,
    execution_authority: str = EXECUTION_AUTHORITY_NONE,
    contract_version: int = CONTRACT_VERSION,
) -> SpecialistOpinion:
    references = _canonical_references(evidence_refs)
    families = _canonical_tokens(
        feature_families,
        "Feature family",
        maximum=_MAX_FEATURE_FAMILIES,
    )
    reasons = _canonical_tokens(
        reason_codes,
        "Reason code",
        maximum=_MAX_REASON_CODES,
    )
    normalized = SpecialistOpinion(
        contract_version=contract_version,
        specialist_id=_token(specialist_id, "Specialist identity"),
        specialist_version=_identifier(
            specialist_version, "Specialist version"
        ),
        opinion_id="",
        opportunity_id=_sha256(opportunity_id, "Opportunity identity"),
        candidate_id=_optional_identifier(candidate_id, "Candidate identity"),
        setup_id=_optional_sha256(setup_id, "Setup identity"),
        trade_plan_id=_optional_sha256(trade_plan_id, "TradePlan identity"),
        as_of=_timestamp(as_of, "Opinion as-of timestamp"),
        expires_at=_timestamp(expires_at, "Opinion expiration timestamp"),
        research_identity=_identifier(research_identity, "Research identity"),
        policy_fingerprint=_sha256(policy_fingerprint, "Policy fingerprint"),
        input_evidence_fingerprint=input_evidence_fingerprint(references),
        evaluation_status=_token(evaluation_status, "Evaluation status"),
        opinion_code=(
            _token(opinion_code, "Opinion code")
            if opinion_code is not None
            else None
        ),
        directional_bias=_token(directional_bias, "Directional bias"),
        authority=_token(authority, "Authority"),
        execution_authority=_token(
            execution_authority, "Execution authority"
        ),
        abstention_reason=(
            _token(abstention_reason, "Abstention reason")
            if abstention_reason is not None
            else None
        ),
        failure_reason=(
            _token(failure_reason, "Failure reason")
            if failure_reason is not None
            else None
        ),
        evidence_refs=references,
        feature_families=families,
        confidence=confidence if confidence is not None else unavailable_confidence(),
        reason_codes=reasons,
        explanation=_explanation(explanation),
        fingerprint="",
    )
    with_identity = replace(normalized, opinion_id=expected_opinion_id(normalized))
    complete = replace(
        with_identity,
        fingerprint=specialist_opinion_fingerprint(with_identity),
    )
    validate_specialist_opinion(complete)
    return complete


def validate_evidence_reference(reference: EvidenceReference) -> None:
    if not isinstance(reference, EvidenceReference):
        raise SpecialistOpinionError("Evidence reference is malformed.")
    if reference.evidence_id != _identifier(
        reference.evidence_id, "Evidence identity"
    ):
        raise SpecialistOpinionError("Evidence identity is not canonical.")
    if reference.evidence_type != _token(reference.evidence_type, "Evidence type"):
        raise SpecialistOpinionError("Evidence type is not canonical.")
    if reference.source != _identifier(reference.source, "Evidence source"):
        raise SpecialistOpinionError("Evidence source is not canonical.")
    if reference.as_of != _timestamp(reference.as_of, "Evidence timestamp"):
        raise SpecialistOpinionError("Evidence timestamp is not canonical UTC.")
    if reference.fingerprint != _sha256(
        reference.fingerprint, "Evidence fingerprint"
    ):
        raise SpecialistOpinionError("Evidence fingerprint is not canonical.")


def validate_confidence(confidence: ConfidenceMetadata) -> None:
    if not isinstance(confidence, ConfidenceMetadata):
        raise SpecialistOpinionError("Confidence metadata is malformed.")
    if type(confidence.available) is not bool:
        raise SpecialistOpinionError("Confidence availability must be boolean.")
    if confidence.kind != _token(confidence.kind, "Confidence kind"):
        raise SpecialistOpinionError("Confidence kind is not canonical.")
    if confidence.calibration_status != _token(
        confidence.calibration_status, "Confidence calibration status"
    ):
        raise SpecialistOpinionError(
            "Confidence calibration status is not canonical."
        )
    if confidence.kind not in CONFIDENCE_KINDS:
        raise SpecialistOpinionError("Confidence kind is unsupported.")
    if confidence.calibration_status not in CALIBRATION_STATUSES:
        raise SpecialistOpinionError("Confidence calibration status is unsupported.")
    if not confidence.available:
        if confidence != unavailable_confidence():
            raise SpecialistOpinionError(
                "Unavailable confidence cannot carry numeric semantics."
            )
        return
    if type(confidence.value) is not float or not math.isfinite(confidence.value):
        raise SpecialistOpinionError("Confidence value must be finite numeric data.")
    if confidence.kind == CONFIDENCE_UNAVAILABLE:
        raise SpecialistOpinionError(
            "Confidence value is missing confidence semantics."
        )
    if confidence.model_version != _identifier(
        confidence.model_version, "Confidence model version"
    ):
        raise SpecialistOpinionError("Confidence model version is not canonical.")
    if confidence.sample_size is not None and (
        type(confidence.sample_size) is not int or confidence.sample_size <= 0
    ):
        raise SpecialistOpinionError("Confidence sample size must be positive.")
    if confidence.kind == CALIBRATED_PROBABILITY:
        if not 0.0 <= float(confidence.value) <= 1.0:
            raise SpecialistOpinionError("Probability confidence is outside [0, 1].")
        if confidence.calibration_status != CALIBRATED:
            raise SpecialistOpinionError(
                "Probability confidence must identify calibrated semantics."
            )
        if confidence.sample_size is None:
            raise SpecialistOpinionError(
                "Probability confidence requires a calibration sample size."
            )
    elif confidence.kind == EMPIRICAL_FREQUENCY:
        if not 0.0 <= float(confidence.value) <= 1.0:
            raise SpecialistOpinionError("Empirical frequency is outside [0, 1].")
        if confidence.sample_size is None:
            raise SpecialistOpinionError(
                "Empirical frequency requires an observed sample size."
            )
        if confidence.calibration_status not in {PROVISIONAL, CALIBRATED}:
            raise SpecialistOpinionError(
                "Empirical frequency has contradictory calibration semantics."
            )
    elif confidence.kind == HEURISTIC and confidence.calibration_status != UNCALIBRATED:
        raise SpecialistOpinionError(
            "A heuristic confidence cannot be presented as calibrated probability."
        )
    elif confidence.kind == MODEL_SCORE and confidence.calibration_status == CALIBRATED:
        raise SpecialistOpinionError(
            "A model score cannot be labeled calibrated without probability semantics."
        )


def validate_specialist_opinion(opinion: SpecialistOpinion) -> None:
    if not isinstance(opinion, SpecialistOpinion):
        raise SpecialistOpinionError("Specialist opinion is malformed.")
    if type(opinion.contract_version) is not int or (
        opinion.contract_version != CONTRACT_VERSION
    ):
        raise SpecialistOpinionError("Specialist contract version is unsupported.")
    canonical_fields = (
        (
            opinion.specialist_id,
            _token(opinion.specialist_id, "Specialist identity"),
            "Specialist identity",
        ),
        (
            opinion.specialist_version,
            _identifier(opinion.specialist_version, "Specialist version"),
            "Specialist version",
        ),
        (
            opinion.opinion_id,
            _sha256(opinion.opinion_id, "Opinion identity"),
            "Opinion identity",
        ),
        (
            opinion.opportunity_id,
            _sha256(opinion.opportunity_id, "Opportunity identity"),
            "Opportunity identity",
        ),
        (
            opinion.candidate_id,
            _optional_identifier(opinion.candidate_id, "Candidate identity"),
            "Candidate identity",
        ),
        (
            opinion.setup_id,
            _optional_sha256(opinion.setup_id, "Setup identity"),
            "Setup identity",
        ),
        (
            opinion.trade_plan_id,
            _optional_sha256(opinion.trade_plan_id, "TradePlan identity"),
            "TradePlan identity",
        ),
    )
    for actual, canonical, label in canonical_fields:
        if actual != canonical:
            raise SpecialistOpinionError(f"{label} is not canonical.")
    if opinion.setup_id is not None and opinion.candidate_id is None:
        raise SpecialistOpinionError("Setup identity requires candidate identity.")
    if opinion.trade_plan_id is not None and opinion.setup_id is None:
        raise SpecialistOpinionError("TradePlan identity requires setup identity.")

    as_of = _parsed_timestamp(opinion.as_of, "Opinion as-of timestamp")
    expires = _parsed_timestamp(opinion.expires_at, "Opinion expiration timestamp")
    if opinion.as_of != _canonical_timestamp(as_of) or (
        opinion.expires_at != _canonical_timestamp(expires)
    ):
        raise SpecialistOpinionError("Opinion timestamps are not canonical UTC.")
    if expires <= as_of:
        raise SpecialistOpinionError("Opinion expires at or before its as-of time.")

    if opinion.research_identity != _identifier(
        opinion.research_identity, "Research identity"
    ):
        raise SpecialistOpinionError("Research identity is not canonical.")
    if opinion.policy_fingerprint != _sha256(
        opinion.policy_fingerprint, "Policy fingerprint"
    ):
        raise SpecialistOpinionError("Policy fingerprint is not canonical.")
    if opinion.input_evidence_fingerprint != _sha256(
        opinion.input_evidence_fingerprint, "Input evidence fingerprint"
    ):
        raise SpecialistOpinionError(
            "Input evidence fingerprint is not canonical."
        )
    token_fields = (
        (opinion.evaluation_status, "Evaluation status"),
        (opinion.directional_bias, "Directional bias"),
        (opinion.authority, "Authority"),
        (opinion.execution_authority, "Execution authority"),
    )
    for actual, label in token_fields:
        if actual != _token(actual, label):
            raise SpecialistOpinionError(f"{label} is not canonical.")
    if opinion.evaluation_status not in EVALUATION_STATUSES:
        raise SpecialistOpinionError("Specialist evaluation status is unsupported.")
    if opinion.directional_bias not in DIRECTIONAL_BIASES:
        raise SpecialistOpinionError("Specialist directional bias is unsupported.")
    if opinion.authority != RESEARCH_ONLY:
        raise SpecialistOpinionError("Specialist authority must remain RESEARCH_ONLY.")
    if opinion.execution_authority != EXECUTION_AUTHORITY_NONE:
        raise SpecialistOpinionError("Specialist execution authority must remain NONE.")

    references = _canonical_references(opinion.evidence_refs)
    if references != opinion.evidence_refs:
        raise SpecialistOpinionError("Evidence references are not canonical.")
    if input_evidence_fingerprint(references) != opinion.input_evidence_fingerprint:
        raise SpecialistOpinionError("Input evidence fingerprint is invalid.")
    if any(
        _parsed_timestamp(item.as_of, "Evidence timestamp") > as_of
        for item in references
    ):
        raise SpecialistOpinionError("Specialist opinion consumed future evidence.")
    families = _canonical_tokens(
        opinion.feature_families,
        "Feature family",
        maximum=_MAX_FEATURE_FAMILIES,
    )
    if families != opinion.feature_families:
        raise SpecialistOpinionError("Feature-family disclosure is not canonical.")
    if references and not families:
        raise SpecialistOpinionError(
            "Evidence-family disclosure is required when evidence is used."
        )
    reasons = _canonical_tokens(
        opinion.reason_codes,
        "Reason code",
        maximum=_MAX_REASON_CODES,
    )
    if reasons != opinion.reason_codes:
        raise SpecialistOpinionError("Reason codes are not canonical.")
    if _explanation(opinion.explanation) != opinion.explanation:
        raise SpecialistOpinionError("Specialist explanation is invalid.")
    validate_confidence(opinion.confidence)
    _validate_evaluation_semantics(opinion)

    if opinion.opinion_id != expected_opinion_id(opinion):
        raise SpecialistOpinionError("Specialist opinion identity is invalid.")
    if opinion.fingerprint != specialist_opinion_fingerprint(opinion):
        raise SpecialistOpinionError("Specialist opinion fingerprint is invalid.")


def validate_opinion_target_identity(
    opinion: SpecialistOpinion,
    *,
    opportunity_id: str,
    candidate_id: str | None,
    setup_id: str | None,
    trade_plan_id: str | None,
) -> None:
    """Fail closed unless an opinion addresses the exact requested target chain."""

    validate_specialist_opinion(opinion)
    expected = (
        _sha256(opportunity_id, "Expected opportunity identity"),
        _optional_identifier(candidate_id, "Expected candidate identity"),
        _optional_sha256(setup_id, "Expected setup identity"),
        _optional_sha256(trade_plan_id, "Expected TradePlan identity"),
    )
    actual = (
        opinion.opportunity_id,
        opinion.candidate_id,
        opinion.setup_id,
        opinion.trade_plan_id,
    )
    if actual != expected:
        raise SpecialistOpinionError(
            "Specialist opinion target identity does not match the requested chain."
        )


def _validate_evaluation_semantics(opinion: SpecialistOpinion) -> None:
    if opinion.evaluation_status == EVALUATED:
        if opinion.opinion_code in {None, NO_OPINION}:
            raise SpecialistOpinionError("Evaluated opinion requires an opinion code.")
        _token(opinion.opinion_code, "Opinion code")
        if opinion.abstention_reason is not None or opinion.failure_reason is not None:
            raise SpecialistOpinionError(
                "Evaluated opinion cannot carry abstention or failure state."
            )
        if not opinion.evidence_refs or not opinion.reason_codes:
            raise SpecialistOpinionError(
                "Evaluated opinion requires evidence and machine reason codes."
            )
        return
    if opinion.evaluation_status == ABSTAINED:
        if opinion.opinion_code != NO_OPINION:
            raise SpecialistOpinionError("Abstention must be explicit NO_OPINION.")
        if opinion.abstention_reason not in ABSTENTION_REASONS:
            raise SpecialistOpinionError("Abstention reason is missing or unsupported.")
        if (
            opinion.failure_reason is not None
            or opinion.directional_bias != NO_DIRECTION
        ):
            raise SpecialistOpinionError(
                "Abstention cannot carry failed or directional opinion semantics."
            )
        if opinion.confidence.available:
            raise SpecialistOpinionError("Abstention cannot claim confidence.")
        return
    if opinion.opinion_code is not None or opinion.abstention_reason is not None:
        raise SpecialistOpinionError(
            "Failed evaluation cannot be presented as opinion or abstention."
        )
    if opinion.failure_reason is None:
        raise SpecialistOpinionError("Failed evaluation requires a failure reason.")
    _token(opinion.failure_reason, "Failure reason")
    if opinion.directional_bias != NO_DIRECTION or opinion.confidence.available:
        raise SpecialistOpinionError(
            "Failed evaluation cannot be neutral, directional, or confident."
        )


def input_evidence_fingerprint(
    references: Iterable[EvidenceReference],
) -> str:
    canonical = _canonical_references(references)
    return _fingerprint(
        {
            "domain": "specialist-input-evidence-v1",
            "evidenceRefs": [_evidence_to_wire(item) for item in canonical],
        }
    )


def expected_opinion_id(opinion: SpecialistOpinion) -> str:
    payload = _opinion_to_wire_unchecked(opinion)
    payload.pop("opinionId", None)
    payload.pop("fingerprint", None)
    return _fingerprint(
        {"domain": "specialist-opinion-identity-v1", "opinion": payload}
    )


def specialist_opinion_fingerprint(opinion: SpecialistOpinion) -> str:
    payload = _opinion_to_wire_unchecked(opinion)
    payload.pop("fingerprint", None)
    return _fingerprint(
        {"domain": "specialist-opinion-record-v1", "opinion": payload}
    )


def opinion_to_wire(opinion: SpecialistOpinion) -> dict[str, Any]:
    validate_specialist_opinion(opinion)
    return _opinion_to_wire_unchecked(opinion)


def opinion_from_wire(payload: object) -> SpecialistOpinion:
    if not isinstance(payload, Mapping) or set(payload) != _OPINION_WIRE_FIELDS:
        raise SpecialistOpinionError("Specialist opinion wire fields are unsupported.")
    raw_refs = payload.get("evidenceRefs")
    raw_confidence = payload.get("confidence")
    raw_families = payload.get("featureFamilies")
    raw_reasons = payload.get("reasonCodes")
    if not isinstance(raw_refs, list) or any(
        not isinstance(item, Mapping) or set(item) != _EVIDENCE_WIRE_FIELDS
        for item in raw_refs
    ):
        raise SpecialistOpinionError("Specialist evidence references are malformed.")
    if not isinstance(raw_confidence, Mapping) or (
        set(raw_confidence) != _CONFIDENCE_WIRE_FIELDS
    ):
        raise SpecialistOpinionError("Specialist confidence metadata is malformed.")
    if not isinstance(raw_families, list) or not isinstance(raw_reasons, list):
        raise SpecialistOpinionError("Specialist list fields are malformed.")
    try:
        opinion = SpecialistOpinion(
            contract_version=payload["contractVersion"],
            specialist_id=payload["specialistId"],
            specialist_version=payload["specialistVersion"],
            opinion_id=payload["opinionId"],
            opportunity_id=payload["opportunityId"],
            candidate_id=payload["candidateId"],
            setup_id=payload["setupId"],
            trade_plan_id=payload["tradePlanId"],
            as_of=payload["asOf"],
            expires_at=payload["expiresAt"],
            research_identity=payload["researchIdentity"],
            policy_fingerprint=payload["policyFingerprint"],
            input_evidence_fingerprint=payload["inputEvidenceFingerprint"],
            evaluation_status=payload["evaluationStatus"],
            opinion_code=payload["opinionCode"],
            directional_bias=payload["directionalBias"],
            authority=payload["authority"],
            execution_authority=payload["executionAuthority"],
            abstention_reason=payload["abstentionReason"],
            failure_reason=payload["failureReason"],
            evidence_refs=tuple(_evidence_from_wire(item) for item in raw_refs),
            feature_families=tuple(raw_families),
            confidence=_confidence_from_wire(raw_confidence),
            reason_codes=tuple(raw_reasons),
            explanation=payload["explanation"],
            fingerprint=payload["fingerprint"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SpecialistOpinionError(
            "Specialist opinion wire data is malformed."
        ) from exc
    validate_specialist_opinion(opinion)
    return opinion


def opinion_json_bytes(opinion: SpecialistOpinion) -> bytes:
    return _canonical_json_bytes(opinion_to_wire(opinion))


def opinion_from_json(value: bytes | str) -> SpecialistOpinion:
    try:
        payload = json.loads(value, object_pairs_hook=_strict_json_object)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise SpecialistOpinionError("Specialist opinion JSON is malformed.") from exc
    return opinion_from_wire(payload)


def opinion_is_expired(
    opinion: SpecialistOpinion,
    at: datetime | str,
) -> bool:
    validate_specialist_opinion(opinion)
    return _parsed_timestamp(at, "Expiration check timestamp") >= _parsed_timestamp(
        opinion.expires_at,
        "Opinion expiration timestamp",
    )


def _opinion_to_wire_unchecked(opinion: SpecialistOpinion) -> dict[str, Any]:
    return {
        "contractVersion": opinion.contract_version,
        "specialistId": opinion.specialist_id,
        "specialistVersion": opinion.specialist_version,
        "opinionId": opinion.opinion_id,
        "opportunityId": opinion.opportunity_id,
        "candidateId": opinion.candidate_id,
        "setupId": opinion.setup_id,
        "tradePlanId": opinion.trade_plan_id,
        "asOf": opinion.as_of,
        "expiresAt": opinion.expires_at,
        "researchIdentity": opinion.research_identity,
        "policyFingerprint": opinion.policy_fingerprint,
        "inputEvidenceFingerprint": opinion.input_evidence_fingerprint,
        "evaluationStatus": opinion.evaluation_status,
        "opinionCode": opinion.opinion_code,
        "directionalBias": opinion.directional_bias,
        "authority": opinion.authority,
        "executionAuthority": opinion.execution_authority,
        "abstentionReason": opinion.abstention_reason,
        "failureReason": opinion.failure_reason,
        "evidenceRefs": [_evidence_to_wire(item) for item in opinion.evidence_refs],
        "featureFamilies": list(opinion.feature_families),
        "confidence": _confidence_to_wire(opinion.confidence),
        "reasonCodes": list(opinion.reason_codes),
        "explanation": opinion.explanation,
        "fingerprint": opinion.fingerprint,
    }


def _evidence_to_wire(reference: EvidenceReference) -> dict[str, Any]:
    return {
        "evidenceId": reference.evidence_id,
        "evidenceType": reference.evidence_type,
        "source": reference.source,
        "asOf": reference.as_of,
        "fingerprint": reference.fingerprint,
    }


def _evidence_from_wire(payload: Mapping[str, Any]) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=payload["evidenceId"],
        evidence_type=payload["evidenceType"],
        source=payload["source"],
        as_of=payload["asOf"],
        fingerprint=payload["fingerprint"],
    )


def _confidence_to_wire(confidence: ConfidenceMetadata) -> dict[str, Any]:
    return {
        "available": confidence.available,
        "value": confidence.value,
        "kind": confidence.kind,
        "calibrationStatus": confidence.calibration_status,
        "sampleSize": confidence.sample_size,
        "modelVersion": confidence.model_version,
    }


def _confidence_from_wire(payload: Mapping[str, Any]) -> ConfidenceMetadata:
    return ConfidenceMetadata(
        available=payload["available"],
        value=payload["value"],
        kind=payload["kind"],
        calibration_status=payload["calibrationStatus"],
        sample_size=payload["sampleSize"],
        model_version=payload["modelVersion"],
    )


def _canonical_references(
    references: Iterable[EvidenceReference],
) -> tuple[EvidenceReference, ...]:
    if isinstance(references, (str, bytes, bytearray, Mapping)):
        raise SpecialistOpinionError("Evidence references are not a record sequence.")
    try:
        rows = tuple(references)
    except TypeError as exc:
        raise SpecialistOpinionError("Evidence references are not iterable.") from exc
    if len(rows) > _MAX_EVIDENCE_REFS:
        raise SpecialistOpinionError(
            "Specialist opinion has too many evidence references."
        )
    for item in rows:
        validate_evidence_reference(item)
    identities: dict[str, EvidenceReference] = {}
    for item in rows:
        if item.evidence_id in identities:
            if identities[item.evidence_id] == item:
                raise SpecialistOpinionError("Evidence identity is duplicated.")
            raise SpecialistOpinionError("Evidence identity is contradictory.")
        identities[item.evidence_id] = item
    return tuple(
        sorted(
            rows,
            key=lambda item: (
                item.evidence_type,
                item.evidence_id,
                item.source,
                item.as_of,
                item.fingerprint,
            ),
        )
    )


def _canonical_tokens(
    values: Iterable[str],
    label: str,
    *,
    maximum: int,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray, Mapping)):
        raise SpecialistOpinionError(f"{label} values are not a token sequence.")
    try:
        normalized = tuple(_token(item, label) for item in values)
    except TypeError as exc:
        raise SpecialistOpinionError(f"{label} values are not iterable.") from exc
    if len(normalized) > maximum:
        raise SpecialistOpinionError(f"{label} count exceeds the contract bound.")
    if len(set(normalized)) != len(normalized):
        raise SpecialistOpinionError(f"{label} values contain duplicates.")
    return tuple(sorted(normalized))


def _timestamp(value: datetime | str, label: str) -> str:
    return _canonical_timestamp(_parsed_timestamp(value, label))


def _parsed_timestamp(value: datetime | str, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SpecialistOpinionError(f"{label} is invalid.") from exc
    else:
        raise SpecialistOpinionError(f"{label} is invalid.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SpecialistOpinionError(f"{label} must include a UTC offset.")
    return parsed.astimezone(timezone.utc)


def _canonical_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise SpecialistOpinionError(f"{label} is invalid.")
    text = value.strip()
    if not _IDENTIFIER.fullmatch(text):
        raise SpecialistOpinionError(f"{label} is invalid.")
    return text


def _optional_identifier(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, label)


def _token(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise SpecialistOpinionError(f"{label} is invalid.")
    text = value.strip().upper()
    if not _TOKEN.fullmatch(text):
        raise SpecialistOpinionError(f"{label} is invalid.")
    return text


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise SpecialistOpinionError(f"{label} is invalid.")
    text = value.strip().lower()
    if not _SHA256.fullmatch(text):
        raise SpecialistOpinionError(f"{label} is invalid.")
    return text


def _optional_sha256(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, label)


def _explanation(value: object) -> str:
    if not isinstance(value, str):
        raise SpecialistOpinionError("Specialist explanation must be text.")
    text = value.strip()
    if len(text) > _MAX_EXPLANATION_CHARS:
        raise SpecialistOpinionError(
            "Specialist explanation exceeds the contract bound."
        )
    if any(
        ord(character) < 32 and character not in "\n\t" for character in text
    ):
        raise SpecialistOpinionError(
            "Specialist explanation contains control characters."
        )
    return text


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SpecialistOpinionError(
                "Specialist opinion JSON contains duplicate object keys."
            )
        result[key] = value
    return result


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(payload).rstrip(b"\n")).hexdigest()


_EVIDENCE_WIRE_FIELDS = frozenset(
    {"evidenceId", "evidenceType", "source", "asOf", "fingerprint"}
)
_CONFIDENCE_WIRE_FIELDS = frozenset(
    {
        "available",
        "value",
        "kind",
        "calibrationStatus",
        "sampleSize",
        "modelVersion",
    }
)
_OPINION_WIRE_FIELDS = frozenset(
    {
        "contractVersion",
        "specialistId",
        "specialistVersion",
        "opinionId",
        "opportunityId",
        "candidateId",
        "setupId",
        "tradePlanId",
        "asOf",
        "expiresAt",
        "researchIdentity",
        "policyFingerprint",
        "inputEvidenceFingerprint",
        "evaluationStatus",
        "opinionCode",
        "directionalBias",
        "authority",
        "executionAuthority",
        "abstentionReason",
        "failureReason",
        "evidenceRefs",
        "featureFamilies",
        "confidence",
        "reasonCodes",
        "explanation",
        "fingerprint",
    }
)
