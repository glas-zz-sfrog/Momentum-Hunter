from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from .continuous_composition import (
    DATA_FAILURE,
    DATA_UNSAFE,
    GAPPED_EVIDENCE,
    MISSED_ENTRY_RECORDED,
    NO_LIFECYCLE_CHANGE,
    RESEARCH_PLAN_COMPOSED,
    SUCCESSOR_SETUP_CREATED,
)
from .continuous_denominator import (
    CURRENTLY_OBSERVED,
    INCOMPLETE_DISCOVERY_FAILURE,
    RETAINED_FROM_PRIOR_DISCOVERY,
    ContinuousDenominatorResult,
    summarize_continuous_denominators,
    validate_continuous_denominator_result,
)
from .opportunity_denominator import (
    EXECUTION_AUTHORITY_NONE,
    NOT_EVALUATED_PROVIDER_BOUND,
    RESEARCH_ONLY,
    SYNTHETIC_TEST,
)


CONTRACT_VERSION = 1
PROOF_PROFILE = "synthetic-whole-day-continuous-acceptance-v1"
PROOF_STATUS = "PASS"
PAPER_LANE = "SYNTHETIC_PAPER_SUPERVISION_INDEPENDENT"
ORDER_CAPABILITY_UNAVAILABLE = "UNAVAILABLE"

CHECK_OPENING_MISS_AND_SUCCESSOR = "OPENING_MISS_AND_DISTINCT_SUCCESSOR"
CHECK_MIDDAY_DISCOVERY = "MIDDAY_FIRST_DISCOVERY"
CHECK_RETAINED_MEMBER = "SOURCE_DISAPPEARANCE_RETAINS_MEMBER"
CHECK_LATER_PAGE = "LATER_PAGE_CANDIDATE_ADMITTED"
CHECK_CAPACITY = "THIRTY_FOR_TEN_PRESERVES_TWENTY_PROVIDER_BOUND"
CHECK_DISCOVERY_FAILURE = "DISCOVERY_FAILURE_ISOLATED"
CHECK_READINESS_FAILURE = "SCHWAB_READINESS_FAILURE_EXPLICIT"
CHECK_CORRUPT_DATA = "CORRUPT_CANDIDATE_DATA_EXPLICIT"
CHECK_RESTART = "NOON_RESTART_IDEMPOTENT"
CHECK_IDENTITY = "NO_DUPLICATE_CREATED_IDENTITIES"
CHECK_DENOMINATOR = "ALL_DENOMINATOR_COUNTS_RECONCILE"
CHECK_PAPER_LANE = "PAPER_SUPERVISION_INDEPENDENT_OF_DISCOVERY"
REQUIRED_CHECKS = (
    CHECK_OPENING_MISS_AND_SUCCESSOR,
    CHECK_MIDDAY_DISCOVERY,
    CHECK_RETAINED_MEMBER,
    CHECK_LATER_PAGE,
    CHECK_CAPACITY,
    CHECK_DISCOVERY_FAILURE,
    CHECK_READINESS_FAILURE,
    CHECK_CORRUPT_DATA,
    CHECK_RESTART,
    CHECK_IDENTITY,
    CHECK_DENOMINATOR,
    CHECK_PAPER_LANE,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_MARKET_TZ = ZoneInfo("America/New_York")


class ContinuousDayProofError(ValueError):
    """Raised when the composed synthetic day violates an acceptance invariant."""


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(_canonical_json({"domain": domain, "value": value})).hexdigest()


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContinuousDayProofError(f"{label} is malformed.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContinuousDayProofError(f"{label} must be timezone-aware.")
    return parsed


def _require_sha256(value: str, label: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ContinuousDayProofError(f"{label} must be SHA-256 evidence.")


@dataclass(frozen=True)
class ContinuousDayScenario:
    opening_symbol: str = "AAA"
    midday_symbol: str = "BBB"
    retained_symbol: str = "CCC"
    later_page_symbol: str = "DDD"
    readiness_failure_symbol: str = "EEE"
    corrupt_data_symbol: str = "FFF"
    readiness_capacity: int = 10
    expected_provider_bound: int = 20
    midday_hour: int = 12
    restart_hour: int = 12


@dataclass(frozen=True)
class RestartReceipt:
    restarted_at: str
    preceding_cycle_id: str
    universe_fingerprint_before: str
    universe_fingerprint_after: str
    denominator_cycle_id: str
    denominator_fingerprint_before: str
    denominator_fingerprint_after: str
    duplicate_persist_byte_identical: bool
    fingerprint: str


@dataclass(frozen=True)
class SyntheticPaperSupervisionObservation:
    observation_id: str
    observed_at: str
    symbol: str
    lifecycle_state: str
    position_evidence_fingerprint: str
    protection_evidence_fingerprint: str
    lane: str
    discovery_dependency: str
    authority: str
    execution_authority: str
    order_capability: str
    fingerprint: str


@dataclass(frozen=True)
class ContinuousDayCycleReference:
    sequence: int
    cycle_id: str
    cycle_fingerprint: str
    discovery_snapshot_id: str
    discovery_fingerprint: str
    universe_state_fingerprint: str
    composition_cycle_id: str
    composition_fingerprint: str
    observed_at: str
    decision_cutoff: str
    complete_denominator: bool
    opportunity_count: int
    fingerprint: str


@dataclass(frozen=True)
class ContinuousDayMetrics:
    cycles: int
    complete_cycles: int
    incomplete_cycles: int
    opportunities: int
    unique_opportunities: int
    unique_members: int
    unique_setups: int
    unique_trade_plans: int
    created_setups: int
    created_trade_plans: int
    thirty_for_ten_provider_bound: int
    maximum_provider_bound: int
    discovery_failures: int
    readiness_data_failures: int
    paper_supervision_observations: int


@dataclass(frozen=True)
class ContinuousDayProof:
    contract_version: int
    profile: str
    proof_id: str
    session_date: str
    started_at: str
    ended_at: str
    cycle_references: tuple[ContinuousDayCycleReference, ...]
    restart_receipt: RestartReceipt
    paper_supervision_observations: tuple[SyntheticPaperSupervisionObservation, ...]
    scenario_checks: tuple[str, ...]
    metrics: ContinuousDayMetrics
    status: str
    observation_mode: str
    authority: str
    execution_authority: str
    order_capability: str
    fingerprint: str


def build_restart_receipt(
    *,
    restarted_at: str,
    preceding_cycle_id: str,
    universe_fingerprint_before: str,
    universe_fingerprint_after: str,
    denominator_cycle_id: str,
    denominator_fingerprint_before: str,
    denominator_fingerprint_after: str,
    duplicate_persist_byte_identical: bool,
) -> RestartReceipt:
    _parse_timestamp(restarted_at, "Restart timestamp")
    for label, value in (
        ("Preceding cycle identity", preceding_cycle_id),
        ("Universe fingerprint before restart", universe_fingerprint_before),
        ("Universe fingerprint after restart", universe_fingerprint_after),
        ("Denominator cycle identity", denominator_cycle_id),
        ("Denominator fingerprint before restart", denominator_fingerprint_before),
        ("Denominator fingerprint after restart", denominator_fingerprint_after),
    ):
        _require_sha256(value, label)
    payload = {
        "restarted_at": restarted_at,
        "preceding_cycle_id": preceding_cycle_id,
        "universe_fingerprint_before": universe_fingerprint_before,
        "universe_fingerprint_after": universe_fingerprint_after,
        "denominator_cycle_id": denominator_cycle_id,
        "denominator_fingerprint_before": denominator_fingerprint_before,
        "denominator_fingerprint_after": denominator_fingerprint_after,
        "duplicate_persist_byte_identical": duplicate_persist_byte_identical,
    }
    return RestartReceipt(
        **payload,
        fingerprint=_fingerprint("continuous-day-restart-receipt-v1", payload),
    )


def build_synthetic_paper_supervision_observation(
    *,
    observed_at: str,
    symbol: str,
    lifecycle_state: str,
    position_evidence_fingerprint: str,
    protection_evidence_fingerprint: str,
) -> SyntheticPaperSupervisionObservation:
    _parse_timestamp(observed_at, "Paper supervision timestamp")
    normalized_symbol = symbol.strip().upper()
    normalized_state = lifecycle_state.strip().upper()
    if not normalized_symbol or not normalized_state:
        raise ContinuousDayProofError("Paper supervision identity is incomplete.")
    _require_sha256(position_evidence_fingerprint, "Paper position evidence")
    _require_sha256(protection_evidence_fingerprint, "Paper protection evidence")
    payload = {
        "observed_at": observed_at,
        "symbol": normalized_symbol,
        "lifecycle_state": normalized_state,
        "position_evidence_fingerprint": position_evidence_fingerprint,
        "protection_evidence_fingerprint": protection_evidence_fingerprint,
        "lane": PAPER_LANE,
        "discovery_dependency": "NONE",
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
        "order_capability": ORDER_CAPABILITY_UNAVAILABLE,
    }
    fingerprint = _fingerprint("synthetic-paper-supervision-v1", payload)
    return SyntheticPaperSupervisionObservation(
        observation_id=f"synthetic-paper-supervision-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


def build_continuous_day_proof(
    *,
    results: Iterable[ContinuousDenominatorResult],
    restart_receipt: RestartReceipt,
    paper_supervision_observations: Iterable[SyntheticPaperSupervisionObservation],
    scenario: ContinuousDayScenario | None = None,
) -> ContinuousDayProof:
    """Validate one synthetic day assembled from the real continuous contracts."""

    scenario = scenario or ContinuousDayScenario()
    items = tuple(results)
    papers = tuple(paper_supervision_observations)
    if len(items) < 4:
        raise ContinuousDayProofError("Whole-day proof requires at least four cycles.")
    for item in items:
        validate_continuous_denominator_result(item)
        if item.cycle.observation_mode != SYNTHETIC_TEST:
            raise ContinuousDayProofError("Whole-day proof accepts synthetic cycles only.")
        if item.cycle.execution_authority != EXECUTION_AUTHORITY_NONE:
            raise ContinuousDayProofError("A proof cycle acquired execution authority.")
    ordered = tuple(sorted(items, key=lambda item: _parse_timestamp(item.cycle.observed_at, "Cycle timestamp")))
    if ordered != items:
        raise ContinuousDayProofError("Whole-day cycles must be supplied chronologically.")
    session_dates = {item.cycle.session_date for item in items}
    if len(session_dates) != 1:
        raise ContinuousDayProofError("Whole-day cycles must share one session date.")
    session_date = next(iter(session_dates))
    cycle_ids = [item.cycle.cycle_id for item in items]
    if len(cycle_ids) != len(set(cycle_ids)):
        raise ContinuousDayProofError("Duplicate continuous cycle identity was created.")

    opportunity_ids = [
        opportunity.opportunity_id
        for item in items
        for opportunity in item.opportunities
    ]
    if len(opportunity_ids) != len(set(opportunity_ids)):
        raise ContinuousDayProofError("Duplicate opportunity identity was created.")

    created_setups: dict[str, str] = {}
    created_plans: dict[str, str] = {}
    setup_lineage: dict[str, tuple[str | None, str]] = {}
    plan_lineage: dict[str, tuple[str | None, str]] = {}
    member_symbols: dict[str, str] = {}
    symbol_members: dict[str, str] = {}
    for item in items:
        members_by_id = {member.universe_member_id: member for member in item.linkage.members}
        for member in item.linkage.members:
            prior_symbol = member_symbols.setdefault(member.universe_member_id, member.symbol)
            if prior_symbol != member.symbol:
                raise ContinuousDayProofError("Universe member identity changed symbols.")
            prior_member = symbol_members.setdefault(member.symbol, member.universe_member_id)
            if prior_member != member.universe_member_id:
                raise ContinuousDayProofError("A symbol acquired duplicate membership identity.")
            if member.setup_id:
                lineage = (member.predecessor_setup_id, member.symbol)
                prior = setup_lineage.setdefault(member.setup_id, lineage)
                if prior != lineage:
                    raise ContinuousDayProofError("Setup identity changed lineage.")
            if member.trade_plan_id:
                lineage = (member.setup_id, member.symbol)
                prior = plan_lineage.setdefault(member.trade_plan_id, lineage)
                if prior != lineage:
                    raise ContinuousDayProofError("TradePlan identity changed setup lineage.")
            if member.composition_disposition in {
                RESEARCH_PLAN_COMPOSED,
                SUCCESSOR_SETUP_CREATED,
            }:
                if not member.setup_id:
                    raise ContinuousDayProofError("Created setup omitted setup identity.")
                if member.setup_id in created_setups:
                    raise ContinuousDayProofError("A setup was created more than once.")
                created_setups[member.setup_id] = item.cycle.cycle_id
            if member.composition_disposition == RESEARCH_PLAN_COMPOSED:
                if not member.setup_id or not member.trade_plan_id:
                    raise ContinuousDayProofError("Composed plan omitted setup or plan identity.")
                if member.trade_plan_id in created_plans:
                    raise ContinuousDayProofError("A TradePlan was created more than once.")
                created_plans[member.trade_plan_id] = item.cycle.cycle_id
        if len(members_by_id) != len(item.linkage.members):
            raise ContinuousDayProofError("A cycle duplicated a universe member.")

    checks: list[str] = []
    missed = _first_member(items, scenario.opening_symbol, MISSED_ENTRY_RECORDED)
    successor = _first_member(items, scenario.opening_symbol, RESEARCH_PLAN_COMPOSED)
    if not missed.setup_id or not missed.trade_plan_id:
        raise ContinuousDayProofError("Opening miss omitted its immutable setup or plan.")
    if (
        not successor.setup_id
        or successor.setup_id == missed.setup_id
        or successor.predecessor_setup_id != missed.setup_id
        or not successor.trade_plan_id
        or successor.trade_plan_id == missed.trade_plan_id
    ):
        raise ContinuousDayProofError("Opening miss did not produce a distinct linked successor.")
    checks.append(CHECK_OPENING_MISS_AND_SUCCESSOR)

    midday_rows = _rows_for_symbol(items, scenario.midday_symbol)
    if not midday_rows:
        raise ContinuousDayProofError("Midday candidate never entered discovery.")
    first_midday_cycle, _ = midday_rows[0]
    if (
        _parse_timestamp(first_midday_cycle.cycle.observed_at, "Midday cycle")
        .astimezone(_MARKET_TZ)
        .hour
        < scenario.midday_hour
    ):
        raise ContinuousDayProofError("Midday candidate existed before its expected window.")
    midday_member = _member(first_midday_cycle, scenario.midday_symbol)
    if midday_member.predecessor_setup_id is not None:
        raise ContinuousDayProofError("Midday candidate inherited opening ancestry.")
    checks.append(CHECK_MIDDAY_DISCOVERY)

    retained_rows = [
        member
        for item in items[1:]
        for member in item.linkage.members
        if member.symbol == scenario.retained_symbol
        and member.source_relationship == RETAINED_FROM_PRIOR_DISCOVERY
        and not member.current_source_row_ids
    ]
    if not retained_rows:
        raise ContinuousDayProofError("Source disappearance did not retain the expected member.")
    checks.append(CHECK_RETAINED_MEMBER)

    later_rows = _rows_for_symbol(items, scenario.later_page_symbol)
    if not later_rows or not any((row.source_page_number or 0) > 1 for _, row in later_rows):
        raise ContinuousDayProofError("Later-page candidate provenance was not preserved.")
    later_member = _member(later_rows[0][0], scenario.later_page_symbol)
    if later_member.composition_disposition != RESEARCH_PLAN_COMPOSED:
        raise ContinuousDayProofError("Later-page candidate did not enter composition.")
    checks.append(CHECK_LATER_PAGE)

    capacity_cycles = [
        item
        for item in items
        if item.linkage.counts.discovery_qualified == 30
        and item.linkage.counts.composition_presented == 30
        and item.linkage.counts.universe_provider_bound == scenario.expected_provider_bound
        and sum(
            opportunity.disposition == NOT_EVALUATED_PROVIDER_BOUND
            for opportunity in item.opportunities
        )
        == scenario.expected_provider_bound
    ]
    if not capacity_cycles or scenario.readiness_capacity + scenario.expected_provider_bound != 30:
        raise ContinuousDayProofError("Thirty-for-ten capacity accounting did not reconcile.")
    checks.append(CHECK_CAPACITY)

    failure_cycles = [
        item for item in items if INCOMPLETE_DISCOVERY_FAILURE in item.linkage.incomplete_reasons
    ]
    if not failure_cycles or any(item.cycle.complete_denominator for item in failure_cycles):
        raise ContinuousDayProofError("Discovery failure was not preserved as incomplete.")
    if not any(
        member.source_relationship == RETAINED_FROM_PRIOR_DISCOVERY
        and member.composition_disposition == NO_LIFECYCLE_CHANGE
        for item in failure_cycles
        for member in item.linkage.members
    ):
        raise ContinuousDayProofError(
            "Discovery failure blocked every retained-member evaluation."
        )
    checks.append(CHECK_DISCOVERY_FAILURE)

    readiness_failure = _member_any(items, scenario.readiness_failure_symbol)
    if not any(
        member.composition_disposition == DATA_FAILURE
        and member.readiness_status == GAPPED_EVIDENCE
        for member in readiness_failure
    ):
        raise ContinuousDayProofError("Schwab/readiness failure was not explicit.")
    checks.append(CHECK_READINESS_FAILURE)

    corrupt_failure = _member_any(items, scenario.corrupt_data_symbol)
    if not any(
        member.composition_disposition == DATA_FAILURE
        and member.readiness_status == DATA_UNSAFE
        for member in corrupt_failure
    ):
        raise ContinuousDayProofError("Corrupt candidate evidence was not explicit.")
    checks.append(CHECK_CORRUPT_DATA)

    _validate_restart(restart_receipt, items, scenario)
    checks.append(CHECK_RESTART)
    checks.append(CHECK_IDENTITY)

    aggregate = summarize_continuous_denominators(items)
    if aggregate.cycles_produced != len(items) or sum(len(item.opportunities) for item in items) != len(opportunity_ids):
        raise ContinuousDayProofError("Day-level denominator totals did not reconcile.")
    checks.append(CHECK_DENOMINATOR)

    _validate_paper_lane(papers, failure_cycles)
    checks.append(CHECK_PAPER_LANE)
    if tuple(checks) != REQUIRED_CHECKS:
        raise ContinuousDayProofError("Whole-day proof checks are incomplete.")

    cycle_references = tuple(
        _cycle_reference(sequence, item) for sequence, item in enumerate(items, start=1)
    )
    setup_ids = {
        member.setup_id
        for item in items
        for member in item.linkage.members
        if member.setup_id
    }
    plan_ids = {
        member.trade_plan_id
        for item in items
        for member in item.linkage.members
        if member.trade_plan_id
    }
    metrics = ContinuousDayMetrics(
        cycles=len(items),
        complete_cycles=aggregate.complete_cycles,
        incomplete_cycles=aggregate.incomplete_cycles,
        opportunities=len(opportunity_ids),
        unique_opportunities=len(set(opportunity_ids)),
        unique_members=len(member_symbols),
        unique_setups=len(setup_ids),
        unique_trade_plans=len(plan_ids),
        created_setups=len(created_setups),
        created_trade_plans=len(created_plans),
        thirty_for_ten_provider_bound=scenario.expected_provider_bound,
        maximum_provider_bound=max(
            item.linkage.counts.universe_provider_bound for item in items
        ),
        discovery_failures=aggregate.discovery_failures,
        readiness_data_failures=aggregate.opportunities_blocked_data,
        paper_supervision_observations=len(papers),
    )
    payload = {
        "contract_version": CONTRACT_VERSION,
        "profile": PROOF_PROFILE,
        "session_date": session_date,
        "started_at": items[0].cycle.observed_at,
        "ended_at": items[-1].cycle.decision_cutoff,
        "cycle_references": cycle_references,
        "restart_receipt": restart_receipt,
        "paper_supervision_observations": papers,
        "scenario_checks": tuple(checks),
        "metrics": metrics,
        "status": PROOF_STATUS,
        "observation_mode": SYNTHETIC_TEST,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
        "order_capability": ORDER_CAPABILITY_UNAVAILABLE,
    }
    identity_payload = {
        **payload,
        "cycle_references": [asdict(item) for item in cycle_references],
        "restart_receipt": asdict(restart_receipt),
        "paper_supervision_observations": [asdict(item) for item in papers],
        "metrics": asdict(metrics),
    }
    fingerprint = _fingerprint("continuous-day-proof-v1", identity_payload)
    return ContinuousDayProof(
        proof_id=f"continuous-day-proof-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


def _cycle_reference(sequence: int, item: ContinuousDenominatorResult) -> ContinuousDayCycleReference:
    payload = {
        "sequence": sequence,
        "cycle_id": item.cycle.cycle_id,
        "cycle_fingerprint": item.cycle.fingerprint,
        "discovery_snapshot_id": item.linkage.discovery_snapshot_id,
        "discovery_fingerprint": item.linkage.discovery_fingerprint,
        "universe_state_fingerprint": item.linkage.universe_state_fingerprint,
        "composition_cycle_id": item.linkage.composition_cycle_id,
        "composition_fingerprint": item.linkage.composition_fingerprint,
        "observed_at": item.cycle.observed_at,
        "decision_cutoff": item.cycle.decision_cutoff,
        "complete_denominator": item.cycle.complete_denominator,
        "opportunity_count": len(item.opportunities),
    }
    return ContinuousDayCycleReference(
        **payload,
        fingerprint=_fingerprint("continuous-day-cycle-reference-v1", payload),
    )


def _rows_for_symbol(results: tuple[ContinuousDenominatorResult, ...], symbol: str):
    return [
        (item, row)
        for item in results
        for row in item.linkage.source_rows
        if row.symbol == symbol
    ]


def _member(result: ContinuousDenominatorResult, symbol: str):
    matches = [item for item in result.linkage.members if item.symbol == symbol]
    if len(matches) != 1:
        raise ContinuousDayProofError(f"Expected one member record for {symbol}.")
    return matches[0]


def _member_any(results: tuple[ContinuousDenominatorResult, ...], symbol: str):
    matches = [
        member
        for item in results
        for member in item.linkage.members
        if member.symbol == symbol
    ]
    if not matches:
        raise ContinuousDayProofError(f"Expected member evidence for {symbol}.")
    return matches


def _first_member(results: tuple[ContinuousDenominatorResult, ...], symbol: str, disposition: str):
    matches = [
        member
        for item in results
        for member in item.linkage.members
        if member.symbol == symbol and member.composition_disposition == disposition
    ]
    if not matches:
        raise ContinuousDayProofError(f"Expected {disposition} evidence for {symbol}.")
    return matches[0]


def _validate_restart(
    receipt: RestartReceipt,
    results: tuple[ContinuousDenominatorResult, ...],
    scenario: ContinuousDayScenario,
) -> None:
    expected = build_restart_receipt(
        restarted_at=receipt.restarted_at,
        preceding_cycle_id=receipt.preceding_cycle_id,
        universe_fingerprint_before=receipt.universe_fingerprint_before,
        universe_fingerprint_after=receipt.universe_fingerprint_after,
        denominator_cycle_id=receipt.denominator_cycle_id,
        denominator_fingerprint_before=receipt.denominator_fingerprint_before,
        denominator_fingerprint_after=receipt.denominator_fingerprint_after,
        duplicate_persist_byte_identical=receipt.duplicate_persist_byte_identical,
    )
    if receipt != expected:
        raise ContinuousDayProofError("Restart receipt fingerprint is invalid.")
    restart_time = _parse_timestamp(receipt.restarted_at, "Restart timestamp")
    if restart_time.astimezone(_MARKET_TZ).hour != scenario.restart_hour:
        raise ContinuousDayProofError("Restart did not occur in the noon proof window.")
    if not (
        receipt.universe_fingerprint_before == receipt.universe_fingerprint_after
        and receipt.denominator_fingerprint_before == receipt.denominator_fingerprint_after
        and receipt.duplicate_persist_byte_identical
    ):
        raise ContinuousDayProofError("Restart changed persisted proof state.")
    cycle_map = {item.cycle.cycle_id: item for item in results}
    preceding = cycle_map.get(receipt.preceding_cycle_id)
    denominator = cycle_map.get(receipt.denominator_cycle_id)
    if preceding is None or denominator is None:
        raise ContinuousDayProofError("Restart receipt references an unknown cycle.")
    if denominator.cycle.fingerprint != receipt.denominator_fingerprint_before:
        raise ContinuousDayProofError("Restart denominator fingerprint drifted.")
    if restart_time <= _parse_timestamp(preceding.cycle.decision_cutoff, "Pre-restart cutoff"):
        raise ContinuousDayProofError("Restart did not follow its preceding cycle.")


def _validate_paper_lane(
    papers: tuple[SyntheticPaperSupervisionObservation, ...],
    failure_cycles: list[ContinuousDenominatorResult],
) -> None:
    if len(papers) < 3:
        raise ContinuousDayProofError("Paper supervision needs before/during/after observations.")
    expected = tuple(
        build_synthetic_paper_supervision_observation(
            observed_at=item.observed_at,
            symbol=item.symbol,
            lifecycle_state=item.lifecycle_state,
            position_evidence_fingerprint=item.position_evidence_fingerprint,
            protection_evidence_fingerprint=item.protection_evidence_fingerprint,
        )
        for item in papers
    )
    if papers != expected:
        raise ContinuousDayProofError("Paper supervision evidence is invalid or tampered.")
    ordered = sorted(papers, key=lambda item: _parse_timestamp(item.observed_at, "Paper timestamp"))
    if tuple(ordered) != papers or len({item.observation_id for item in papers}) != len(papers):
        raise ContinuousDayProofError("Paper supervision chronology or identity is duplicated.")
    if any(
        item.discovery_dependency != "NONE"
        or item.order_capability != ORDER_CAPABILITY_UNAVAILABLE
        or item.execution_authority != EXECUTION_AUTHORITY_NONE
        for item in papers
    ):
        raise ContinuousDayProofError("Paper supervision acquired discovery or order authority.")
    if len({item.symbol for item in papers}) != 1:
        raise ContinuousDayProofError("Paper supervision changed position identity.")
    paper_times = [
        _parse_timestamp(item.observed_at, "Paper timestamp") for item in papers
    ]
    failure_windows = [
        (
            _parse_timestamp(item.cycle.observed_at, "Discovery-failure start"),
            _parse_timestamp(item.cycle.decision_cutoff, "Discovery-failure cutoff"),
        )
        for item in failure_cycles
    ]
    if not any(
        min(paper_times) < start
        and max(paper_times) > cutoff
        and any(start <= observed <= cutoff for observed in paper_times)
        for start, cutoff in failure_windows
    ):
        raise ContinuousDayProofError("Paper supervision did not survive discovery failure.")


def validate_continuous_day_proof(proof: ContinuousDayProof) -> None:
    if not isinstance(proof, ContinuousDayProof):
        raise ContinuousDayProofError("Continuous day proof is malformed.")
    payload = asdict(proof)
    fingerprint = payload.pop("fingerprint")
    proof_id = payload.pop("proof_id")
    expected = _fingerprint("continuous-day-proof-v1", payload)
    if fingerprint != expected or proof_id != f"continuous-day-proof-{expected[:24]}":
        raise ContinuousDayProofError("Continuous day proof fingerprint is invalid.")
    if tuple(proof.scenario_checks) != REQUIRED_CHECKS or proof.status != PROOF_STATUS:
        raise ContinuousDayProofError("Continuous day proof is not terminal PASS evidence.")
    if (
        proof.observation_mode != SYNTHETIC_TEST
        or proof.authority != RESEARCH_ONLY
        or proof.execution_authority != EXECUTION_AUTHORITY_NONE
        or proof.order_capability != ORDER_CAPABILITY_UNAVAILABLE
    ):
        raise ContinuousDayProofError("Continuous day proof authority boundary drifted.")
