from __future__ import annotations

"""Broker-blind admission contract for genuine continuous TradePlans."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Mapping

from momentum_hunter.continuous_composition import (
    ContinuousCompositionCycle,
    ContinuousCompositionMemberResult,
)
from momentum_hunter.hot_universe import HotUniverseMember
from momentum_hunter.intraday_trade_plan import (
    IntradayPlanEvidence,
    intraday_plan_validation_findings,
)


CONTINUOUS_PAPER_ADMISSION_SCHEMA_VERSION = 1
CONTINUOUS_PAPER_ADMISSION_PROFILE = "continuous-paper-admission-v1"
CONTINUOUS_PAPER_PAYLOAD_TYPE = "PAPER_ADMISSION_INTENT"
RESEARCH_AUTHORITY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY_NONE = "EXECUTION_AUTHORITY_NONE"
ORDER_CAPABILITY_UNAVAILABLE = "UNAVAILABLE"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContinuousPaperContractError(ValueError):
    """Raised when a plan admission is incomplete or contradictory."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes({"domain": domain, "value": value})
    ).hexdigest()


@dataclass(frozen=True)
class ContinuousPaperAdmissionIntent:
    admission_id: str
    composition_cycle_id: str
    composition_cycle_fingerprint: str
    universe_member_id: str
    candidate_id: str
    canonical_rank: int
    symbol: str
    session_date: str
    known_at: str
    setup_id: str
    setup_family: str
    trade_plan_id: str
    trade_plan: IntradayPlanEvidence
    readiness_fingerprint: str
    minute_evidence_id: str
    minute_evidence_fingerprint: str
    daily_evidence_id: str
    daily_evidence_fingerprint: str
    rvol_evidence_id: str
    rvol_evidence_fingerprint: str
    strategy_configuration_fingerprint: str
    runtime_configuration_fingerprint: str
    product_sha: str
    source_evidence_ids: tuple[str, ...]
    fingerprint: str
    schema_version: int = CONTINUOUS_PAPER_ADMISSION_SCHEMA_VERSION
    profile: str = CONTINUOUS_PAPER_ADMISSION_PROFILE
    authority: str = RESEARCH_AUTHORITY
    execution_authority: str = EXECUTION_AUTHORITY_NONE
    order_capability: str = ORDER_CAPABILITY_UNAVAILABLE

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "profile": self.profile,
            "payloadType": CONTINUOUS_PAPER_PAYLOAD_TYPE,
            "admissionId": self.admission_id,
            "compositionCycleId": self.composition_cycle_id,
            "compositionCycleFingerprint": self.composition_cycle_fingerprint,
            "universeMemberId": self.universe_member_id,
            "candidateId": self.candidate_id,
            "canonicalRank": self.canonical_rank,
            "symbol": self.symbol,
            "sessionDate": self.session_date,
            "knownAt": self.known_at,
            "setupId": self.setup_id,
            "setupFamily": self.setup_family,
            "tradePlanId": self.trade_plan_id,
            "tradePlan": asdict(self.trade_plan),
            "readinessFingerprint": self.readiness_fingerprint,
            "minuteEvidenceId": self.minute_evidence_id,
            "minuteEvidenceFingerprint": self.minute_evidence_fingerprint,
            "dailyEvidenceId": self.daily_evidence_id,
            "dailyEvidenceFingerprint": self.daily_evidence_fingerprint,
            "rvolEvidenceId": self.rvol_evidence_id,
            "rvolEvidenceFingerprint": self.rvol_evidence_fingerprint,
            "strategyConfigurationFingerprint": self.strategy_configuration_fingerprint,
            "runtimeConfigurationFingerprint": self.runtime_configuration_fingerprint,
            "productSha": self.product_sha,
            "sourceEvidenceIds": list(self.source_evidence_ids),
            "authority": self.authority,
            "executionAuthority": self.execution_authority,
            "orderCapability": self.order_capability,
            "fingerprint": self.fingerprint,
        }


def build_continuous_paper_admission_intent(
    *,
    cycle: ContinuousCompositionCycle,
    member: ContinuousCompositionMemberResult,
    universe_member: HotUniverseMember,
    runtime_configuration_fingerprint: str,
    product_sha: str,
) -> ContinuousPaperAdmissionIntent | None:
    plan = member.intraday_plan
    proposal = member.lifecycle_proposal
    assessment = member.readiness_assessment
    if plan is None or not plan.execution_eligible:
        return None
    if proposal is None or assessment is None:
        raise ContinuousPaperContractError(
            "An execution-eligible plan lacks lifecycle or readiness identity."
        )
    if intraday_plan_validation_findings(plan):
        raise ContinuousPaperContractError("The continuous TradePlan is invalid.")
    if not _SHA256.fullmatch(runtime_configuration_fingerprint):
        raise ContinuousPaperContractError("Runtime configuration identity is invalid.")
    if not re.fullmatch(r"[0-9a-f]{40}", product_sha):
        raise ContinuousPaperContractError("Product Git identity is invalid.")
    rank = _canonical_rank(universe_member)
    known_at = plan.lifecycle_updated_at or plan.created_at
    source_ids = tuple(dict.fromkeys(plan.source_evidence_ids))
    # A later composition cycle may carry the same immutable TradePlan again.
    # Admission identity follows the plan, while the full record retains the
    # cycle lineage that delivered it.
    identity = {
        "symbol": member.symbol,
        "sessionDate": member.session_date,
        "knownAt": known_at,
        "setupId": proposal.setup_id,
        "tradePlanId": plan.plan_id,
        "strategyConfigurationFingerprint": cycle.composition_policy_fingerprint,
        "runtimeConfigurationFingerprint": runtime_configuration_fingerprint,
        "productSha": product_sha,
    }
    admission_id = "continuous-paper-admission-" + _fingerprint(
        "continuous-paper-admission-identity-v1", identity
    )[:24]
    values = {
        "admission_id": admission_id,
        "composition_cycle_id": cycle.cycle_id,
        "composition_cycle_fingerprint": cycle.fingerprint,
        "universe_member_id": member.universe_member_id,
        "candidate_id": universe_member.latest_candidate_identity,
        "canonical_rank": rank,
        "symbol": member.symbol,
        "session_date": member.session_date,
        "known_at": known_at,
        "setup_id": proposal.setup_id,
        "setup_family": plan.setup_family,
        "trade_plan_id": plan.plan_id,
        "trade_plan": plan,
        "readiness_fingerprint": assessment.fingerprint,
        "minute_evidence_id": assessment.minute_evidence_id,
        "minute_evidence_fingerprint": assessment.minute_evidence_fingerprint,
        "daily_evidence_id": assessment.daily_evidence_id,
        "daily_evidence_fingerprint": assessment.daily_evidence_fingerprint,
        "rvol_evidence_id": assessment.rvol_evidence_id,
        "rvol_evidence_fingerprint": assessment.rvol_evidence_fingerprint,
        "strategy_configuration_fingerprint": cycle.composition_policy_fingerprint,
        "runtime_configuration_fingerprint": runtime_configuration_fingerprint,
        "product_sha": product_sha,
        "source_evidence_ids": source_ids,
    }
    unsigned_intent = ContinuousPaperAdmissionIntent(
        **values,
        fingerprint="0" * 64,
    )
    fingerprint = _intent_fingerprint(unsigned_intent)
    intent = replace(unsigned_intent, fingerprint=fingerprint)
    validate_continuous_paper_admission_intent(intent)
    return intent


def parse_continuous_paper_admission_intent(
    payload: Mapping[str, object],
) -> ContinuousPaperAdmissionIntent:
    raw_plan = payload.get("tradePlan")
    if not isinstance(raw_plan, Mapping):
        raise ContinuousPaperContractError("TradePlan payload is missing.")
    plan_values = dict(raw_plan)
    for field_name in ("target_prices", "source_evidence_ids", "findings"):
        if isinstance(plan_values.get(field_name), list):
            plan_values[field_name] = tuple(plan_values[field_name])
    try:
        intent = ContinuousPaperAdmissionIntent(
            admission_id=str(payload["admissionId"]),
            composition_cycle_id=str(payload["compositionCycleId"]),
            composition_cycle_fingerprint=str(payload["compositionCycleFingerprint"]),
            universe_member_id=str(payload["universeMemberId"]),
            candidate_id=str(payload["candidateId"]),
            canonical_rank=int(payload["canonicalRank"]),
            symbol=str(payload["symbol"]),
            session_date=str(payload["sessionDate"]),
            known_at=str(payload["knownAt"]),
            setup_id=str(payload["setupId"]),
            setup_family=str(payload["setupFamily"]),
            trade_plan_id=str(payload["tradePlanId"]),
            trade_plan=IntradayPlanEvidence(**plan_values),
            readiness_fingerprint=str(payload["readinessFingerprint"]),
            minute_evidence_id=str(payload["minuteEvidenceId"]),
            minute_evidence_fingerprint=str(payload["minuteEvidenceFingerprint"]),
            daily_evidence_id=str(payload["dailyEvidenceId"]),
            daily_evidence_fingerprint=str(payload["dailyEvidenceFingerprint"]),
            rvol_evidence_id=str(payload["rvolEvidenceId"]),
            rvol_evidence_fingerprint=str(payload["rvolEvidenceFingerprint"]),
            strategy_configuration_fingerprint=str(payload["strategyConfigurationFingerprint"]),
            runtime_configuration_fingerprint=str(payload["runtimeConfigurationFingerprint"]),
            product_sha=str(payload["productSha"]),
            source_evidence_ids=tuple(str(item) for item in payload["sourceEvidenceIds"]),
            fingerprint=str(payload["fingerprint"]),
            schema_version=int(payload["schemaVersion"]),
            profile=str(payload["profile"]),
            authority=str(payload["authority"]),
            execution_authority=str(payload["executionAuthority"]),
            order_capability=str(payload["orderCapability"]),
        )
    except (KeyError, TypeError, ValueError):
        raise ContinuousPaperContractError("Admission payload fields are invalid.") from None
    validate_continuous_paper_admission_intent(intent)
    return intent


def validate_continuous_paper_admission_intent(
    intent: ContinuousPaperAdmissionIntent,
) -> None:
    if (
        intent.schema_version != CONTINUOUS_PAPER_ADMISSION_SCHEMA_VERSION
        or intent.profile != CONTINUOUS_PAPER_ADMISSION_PROFILE
        or intent.authority != RESEARCH_AUTHORITY
        or intent.execution_authority != EXECUTION_AUTHORITY_NONE
        or intent.order_capability != ORDER_CAPABILITY_UNAVAILABLE
    ):
        raise ContinuousPaperContractError("Admission authority boundary is invalid.")
    if not intent.admission_id.startswith("continuous-paper-admission-"):
        raise ContinuousPaperContractError("Admission identity is invalid.")
    for value in (
        intent.composition_cycle_fingerprint,
        intent.setup_id,
        intent.trade_plan_id,
        intent.readiness_fingerprint,
        intent.minute_evidence_fingerprint,
        intent.daily_evidence_fingerprint,
        intent.rvol_evidence_fingerprint,
        intent.strategy_configuration_fingerprint,
        intent.runtime_configuration_fingerprint,
        intent.fingerprint,
    ):
        if not _SHA256.fullmatch(value):
            raise ContinuousPaperContractError("Admission fingerprint field is invalid.")
    if not re.fullmatch(r"[0-9a-f]{40}", intent.product_sha):
        raise ContinuousPaperContractError("Admission product identity is invalid.")
    if intent.canonical_rank <= 0 or intent.symbol != intent.symbol.strip().upper():
        raise ContinuousPaperContractError("Admission candidate identity is invalid.")
    try:
        known = datetime.fromisoformat(intent.known_at.replace("Z", "+00:00"))
    except ValueError:
        raise ContinuousPaperContractError("Admission timestamp is invalid.") from None
    if known.tzinfo is None or known.utcoffset() is None:
        raise ContinuousPaperContractError("Admission timestamp lacks an offset.")
    if (
        intent.trade_plan.plan_id != intent.trade_plan_id
        or intent.trade_plan.symbol != intent.symbol
        or intent.trade_plan.session_date != intent.session_date
        or intent.trade_plan.setup_family != intent.setup_family
        or intraday_plan_validation_findings(intent.trade_plan)
        or not intent.trade_plan.execution_eligible
    ):
        raise ContinuousPaperContractError("Admission TradePlan identity is invalid.")
    if not intent.source_evidence_ids or tuple(intent.trade_plan.source_evidence_ids) != intent.source_evidence_ids:
        raise ContinuousPaperContractError("Admission source evidence is inconsistent.")
    expected = _intent_fingerprint(intent)
    if intent.fingerprint != expected:
        raise ContinuousPaperContractError("Admission fingerprint is invalid.")


def _unsigned_dict(values: Mapping[str, object]) -> dict[str, object]:
    result = dict(values)
    plan = result.get("trade_plan")
    if isinstance(plan, IntradayPlanEvidence):
        result["trade_plan"] = asdict(plan)
    sources = result.get("source_evidence_ids")
    if isinstance(sources, tuple):
        result["source_evidence_ids"] = list(sources)
    return result


def _intent_fingerprint(intent: ContinuousPaperAdmissionIntent) -> str:
    values = {
        key: value
        for key, value in intent.__dict__.items()
        if key != "fingerprint"
    }
    return _fingerprint(
        "continuous-paper-admission-record-v1",
        _unsigned_dict(values),
    )


def _canonical_rank(member: HotUniverseMember) -> int:
    values = dict(member.priority_inputs)
    try:
        rank = int(values.get("canonicalRank", "0"))
    except ValueError:
        rank = 0
    if rank <= 0:
        raise ContinuousPaperContractError("Universe member canonical rank is missing.")
    return rank


__all__ = [
    "CONTINUOUS_PAPER_ADMISSION_PROFILE",
    "CONTINUOUS_PAPER_PAYLOAD_TYPE",
    "ContinuousPaperAdmissionIntent",
    "ContinuousPaperContractError",
    "build_continuous_paper_admission_intent",
    "parse_continuous_paper_admission_intent",
    "validate_continuous_paper_admission_intent",
]
