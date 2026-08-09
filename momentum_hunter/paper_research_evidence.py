from __future__ import annotations

"""Prospective, nonactivating Paper research and dual-result evidence."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import re

from momentum_hunter.provider_neutral_allocation import (
    ProviderNeutralAllocationDecision,
    decimal_text,
    evidence_fingerprint,
)


PAPER_RESEARCH_SCHEMA_VERSION = 1


class CandidateDisposition(str, Enum):
    WOULD_ADMIT = "WOULD_ADMIT"
    WITHHELD_CONCURRENCY = "WITHHELD_CONCURRENCY"
    INELIGIBLE = "INELIGIBLE"
    RANK_NOT_PARTICIPATING = "RANK_NOT_PARTICIPATING"


class ExecutionResultType(str, Enum):
    ALPACA_PAPER_EXECUTION_RESULT = "ALPACA_PAPER_EXECUTION_RESULT"
    MH_CONSERVATIVE_EXECUTABLE_RESULT = "MH_CONSERVATIVE_EXECUTABLE_RESULT"


@dataclass(frozen=True)
class PaperResearchPolicy:
    policy_id: str
    lane: str
    participating_ranks: tuple[int, ...]
    max_concurrent_positions: int
    schema_version: int = PAPER_RESEARCH_SCHEMA_VERSION

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class ProspectiveResearchCandidate:
    candidate_id: str
    decision_cycle_id: str
    canonical_rank: int
    symbol: str
    setup_id: str
    trade_plan_id: str
    risk_decision_id: str
    source_evidence_fingerprint: str
    allocation: ProviderNeutralAllocationDecision
    independently_eligible: bool
    eligibility_blockers: tuple[str, ...]


@dataclass(frozen=True)
class ProspectiveCandidateRecord:
    candidate_id: str
    canonical_rank: int
    symbol: str
    setup_id: str
    trade_plan_id: str
    risk_decision_id: str
    source_evidence_fingerprint: str
    independently_eligible: bool
    eligibility_blockers: tuple[str, ...]
    disposition: CandidateDisposition
    allocation_status: str
    final_authorized_quantity: Decimal
    allocation_fingerprint: str
    allocation_blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "candidateId": self.candidate_id,
            "canonicalRank": self.canonical_rank,
            "symbol": self.symbol,
            "setupId": self.setup_id,
            "tradePlanId": self.trade_plan_id,
            "riskDecisionId": self.risk_decision_id,
            "sourceEvidenceFingerprint": self.source_evidence_fingerprint,
            "independentlyEligible": self.independently_eligible,
            "eligibilityBlockers": list(self.eligibility_blockers),
            "disposition": self.disposition.value,
            "allocationStatus": self.allocation_status,
            "finalAuthorizedQuantity": decimal_text(
                self.final_authorized_quantity
            ),
            "allocationFingerprint": self.allocation_fingerprint,
            "allocationBlockers": list(self.allocation_blockers),
        }


@dataclass(frozen=True)
class PaperResearchPortfolioEvidence:
    decision_cycle_id: str
    policy_fingerprint: str
    existing_open_positions: int
    records: tuple[ProspectiveCandidateRecord, ...]
    activated: bool = field(default=False, init=False)
    orders_created: bool = field(default=False, init=False)
    counts_toward_official_sample: bool = field(default=False, init=False)
    schema_version: int = PAPER_RESEARCH_SCHEMA_VERSION

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schemaVersion": self.schema_version,
            "decisionCycleId": self.decision_cycle_id,
            "policyFingerprint": self.policy_fingerprint,
            "existingOpenPositions": self.existing_open_positions,
            "records": [item.to_dict() for item in self.records],
            "activated": self.activated,
            "ordersCreated": self.orders_created,
            "countsTowardOfficialSample": self.counts_toward_official_sample,
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


def build_paper_research_portfolio_evidence(
    *,
    policy: PaperResearchPolicy,
    candidates: tuple[ProspectiveResearchCandidate, ...],
    existing_open_positions: int,
) -> PaperResearchPortfolioEvidence:
    _validate_research_policy(policy)
    if (
        not isinstance(existing_open_positions, int)
        or isinstance(existing_open_positions, bool)
        or existing_open_positions < 0
    ):
        raise ValueError("Existing open-position count is invalid.")
    if not candidates:
        raise ValueError("Prospective research candidates are required.")
    cycle_ids = {item.decision_cycle_id for item in candidates}
    candidate_ids = {item.candidate_id for item in candidates}
    ranks = [item.canonical_rank for item in candidates]
    if len(cycle_ids) != 1 or "" in cycle_ids:
        raise ValueError("Candidates must share one decision-cycle identity.")
    if len(candidate_ids) != len(candidates) or "" in candidate_ids:
        raise ValueError("Candidate identities must be unique and nonempty.")
    if len(set(ranks)) != len(ranks) or any(
        isinstance(rank, bool) or rank <= 0 for rank in ranks
    ):
        raise ValueError("Canonical candidate ranks must be unique and positive.")
    for candidate in candidates:
        _validate_candidate(candidate)

    available_slots = max(
        0, policy.max_concurrent_positions - existing_open_positions
    )
    records: list[ProspectiveCandidateRecord] = []
    for candidate in sorted(candidates, key=lambda item: item.canonical_rank):
        if not candidate.independently_eligible or not candidate.allocation.authorized:
            disposition = CandidateDisposition.INELIGIBLE
        elif candidate.canonical_rank not in policy.participating_ranks:
            disposition = CandidateDisposition.RANK_NOT_PARTICIPATING
        elif available_slots <= 0:
            disposition = CandidateDisposition.WITHHELD_CONCURRENCY
        else:
            disposition = CandidateDisposition.WOULD_ADMIT
            available_slots -= 1
        records.append(
            ProspectiveCandidateRecord(
                candidate_id=candidate.candidate_id,
                canonical_rank=candidate.canonical_rank,
                symbol=candidate.symbol,
                setup_id=candidate.setup_id,
                trade_plan_id=candidate.trade_plan_id,
                risk_decision_id=candidate.risk_decision_id,
                source_evidence_fingerprint=candidate.source_evidence_fingerprint,
                independently_eligible=candidate.independently_eligible,
                eligibility_blockers=candidate.eligibility_blockers,
                disposition=disposition,
                allocation_status=candidate.allocation.status.value,
                final_authorized_quantity=(
                    candidate.allocation.final_authorized_quantity
                ),
                allocation_fingerprint=candidate.allocation.fingerprint,
                allocation_blockers=candidate.allocation.blockers,
            )
        )
    return PaperResearchPortfolioEvidence(
        decision_cycle_id=next(iter(cycle_ids)),
        policy_fingerprint=policy.fingerprint,
        existing_open_positions=existing_open_positions,
        records=tuple(records),
    )


@dataclass(frozen=True)
class ExecutionResultEvidence:
    result_type: ExecutionResultType
    result_id: str
    decision_cycle_id: str
    candidate_id: str
    trade_plan_id: str
    symbol: str
    requested_quantity: Decimal
    filled_quantity: Decimal
    entry_price: Decimal | None
    exit_price: Decimal | None
    realized_pnl: Decimal | None
    terminal_status: str
    evidence_fingerprint: str
    observed_at: str

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class ExecutionResultComparison:
    decision_cycle_id: str
    candidate_id: str
    trade_plan_id: str
    symbol: str
    alpaca_paper_execution_result: ExecutionResultEvidence
    mh_conservative_executable_result: ExecutionResultEvidence
    statistics_combined: bool = field(default=False, init=False)
    schema_version: int = PAPER_RESEARCH_SCHEMA_VERSION

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


def pair_execution_results(
    paper: ExecutionResultEvidence,
    conservative: ExecutionResultEvidence,
) -> ExecutionResultComparison:
    _validate_execution_result(paper)
    _validate_execution_result(conservative)
    if paper.result_type is not ExecutionResultType.ALPACA_PAPER_EXECUTION_RESULT:
        raise ValueError("Paper result has the wrong evidence domain.")
    if (
        conservative.result_type
        is not ExecutionResultType.MH_CONSERVATIVE_EXECUTABLE_RESULT
    ):
        raise ValueError("Conservative result has the wrong evidence domain.")
    identity = (
        paper.decision_cycle_id,
        paper.candidate_id,
        paper.trade_plan_id,
        paper.symbol,
        paper.requested_quantity,
    )
    if identity != (
        conservative.decision_cycle_id,
        conservative.candidate_id,
        conservative.trade_plan_id,
        conservative.symbol,
        conservative.requested_quantity,
    ):
        raise ValueError("Execution results do not share one prospective identity.")
    if not paper.result_id or not conservative.result_id:
        raise ValueError("Execution result identities are required.")
    if not paper.evidence_fingerprint or not conservative.evidence_fingerprint:
        raise ValueError("Execution source evidence fingerprints are required.")
    return ExecutionResultComparison(
        decision_cycle_id=paper.decision_cycle_id,
        candidate_id=paper.candidate_id,
        trade_plan_id=paper.trade_plan_id,
        symbol=paper.symbol,
        alpaca_paper_execution_result=paper,
        mh_conservative_executable_result=conservative,
    )


def _validate_research_policy(policy: PaperResearchPolicy) -> None:
    if not _nonempty_text(policy.policy_id) or not _nonempty_text(policy.lane):
        raise ValueError("Paper research policy identity is required.")
    if (
        not isinstance(policy.max_concurrent_positions, int)
        or isinstance(policy.max_concurrent_positions, bool)
        or policy.max_concurrent_positions <= 0
    ):
        raise ValueError("Paper research concurrency must be positive.")
    if not policy.participating_ranks or len(set(policy.participating_ranks)) != len(
        policy.participating_ranks
    ):
        raise ValueError("Paper research ranks must be unique and nonempty.")
    if any(
        not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0
        for rank in policy.participating_ranks
    ):
        raise ValueError("Paper research ranks must be positive integers.")


def _validate_candidate(candidate: ProspectiveResearchCandidate) -> None:
    for value in (
        candidate.candidate_id,
        candidate.decision_cycle_id,
        candidate.symbol,
        candidate.setup_id,
        candidate.trade_plan_id,
        candidate.risk_decision_id,
    ):
        if not _nonempty_text(value):
            raise ValueError("Candidate evidence identities must be nonempty.")
    if not _sha256_text(candidate.source_evidence_fingerprint):
        raise ValueError("Candidate source-evidence fingerprint must be SHA-256 text.")
    if not isinstance(candidate.independently_eligible, bool):
        raise ValueError("Candidate independent eligibility must be explicit.")
    if candidate.independently_eligible and candidate.eligibility_blockers:
        raise ValueError("Eligible candidate cannot carry eligibility blockers.")
    if not candidate.independently_eligible and not candidate.eligibility_blockers:
        raise ValueError("Ineligible candidate must preserve at least one blocker.")
    if any(not _nonempty_text(item) for item in candidate.eligibility_blockers):
        raise ValueError("Candidate eligibility blockers must be nonempty.")


def _validate_execution_result(result: ExecutionResultEvidence) -> None:
    for value in (
        result.result_id,
        result.decision_cycle_id,
        result.candidate_id,
        result.trade_plan_id,
        result.symbol,
        result.terminal_status,
    ):
        if not _nonempty_text(value):
            raise ValueError("Execution result identities and status are required.")
    if not _sha256_text(result.evidence_fingerprint):
        raise ValueError("Execution result source fingerprint must be SHA-256 text.")
    if _aware_datetime(result.observed_at) is None:
        raise ValueError("Execution result observation timestamp must include an offset.")
    requested_quantity = _nonnegative_decimal(result.requested_quantity)
    filled_quantity = _nonnegative_decimal(result.filled_quantity)
    if requested_quantity is None or filled_quantity is None:
        raise ValueError("Execution result quantities cannot be negative.")
    if filled_quantity > requested_quantity:
        raise ValueError("Filled quantity cannot exceed requested quantity.")
    for value in (result.entry_price, result.exit_price):
        if value is not None and _positive_decimal(value) is None:
            raise ValueError("Execution prices must be finite and positive when present.")
    if result.realized_pnl is not None and _finite_decimal(result.realized_pnl) is None:
        raise ValueError("Execution realized P&L must be finite when present.")


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256_text(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f]{64}", value) is not None


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _finite_decimal(value: object) -> Decimal | None:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _nonnegative_decimal(value: object) -> Decimal | None:
    parsed = _finite_decimal(value)
    return parsed if parsed is not None and parsed >= 0 else None


def _positive_decimal(value: object) -> Decimal | None:
    parsed = _finite_decimal(value)
    return parsed if parsed is not None and parsed > 0 else None
