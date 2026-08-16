"""Pure continuous-cycle adapter for the inactive opportunity denominator.

The producer consumes caller-supplied discovery, hot-universe, and composition
records. It has no provider, account, broker, scheduler, service, UI, or
production-root capability.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from momentum_hunter.broad_discovery import (
    CROSS_PAGE_ATOMICITY_NOT_GUARANTEED,
    PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED,
    ROW_DISPOSITION_QUALIFIED,
    ROW_DISPOSITION_REJECTED_FILTER,
    SNAPSHOT_STATUS_COMPLETE,
    DiscoveryRow,
    DiscoverySnapshot,
)
from momentum_hunter.continuous_composition import (
    BLOCKED_DATA as COMPOSITION_BLOCKED_DATA,
    DATA_FAILURE as COMPOSITION_DATA_FAILURE,
    EXPIRED_RESULT,
    MISSED_ENTRY_RECORDED,
    NO_LIFECYCLE_CHANGE,
    NOT_EVALUATED_POLICY,
    PROVIDER_BOUND as COMPOSITION_PROVIDER_BOUND,
    READY,
    RESEARCH_PLAN_COMPOSED,
    SETUP_PENDING,
    SUCCESSOR_SETUP_CREATED,
    UNSUPPORTED_SESSION_RESULT,
    WAITING_READINESS,
    ContinuousCompositionCycle,
    ContinuousCompositionMemberResult,
    _fingerprint as _composition_fingerprint,
    _summary as _composition_summary,
)
from momentum_hunter.hot_universe import (
    ADMITTED,
    DISCOVERY_FAILURE,
    EXPIRED_TRANSITION,
    FAILURE_RECORDED,
    PROVIDER_BOUND as UNIVERSE_PROVIDER_BOUND,
    READMITTED_NEW_GENERATION,
    TRACKED,
    HotUniverseMember,
    HotUniverseResult,
    _summary as _universe_summary,
    validate_hot_universe_state,
)
from momentum_hunter.opportunity_denominator import (
    ACTUAL_SYSTEM_DECISION,
    BLOCKED_DATA,
    CONTINUOUS_INTRADAY_OPPORTUNITY,
    DATA_CONTRACT_FAILURE,
    DENOMINATOR_INCOMPLETE,
    EXECUTION_AUTHORITY_NONE,
    NO_ACTION_RESEARCH_ONLY,
    NOT_EVALUATED_PROVIDER_BOUND,
    POLICY_FINGERPRINT,
    PROVIDER_BOUND_ROW,
    REJECTED_STRATEGY,
    RESEARCH_ONLY,
    SAMPLE_IDENTITY,
    SAMPLE_STATUS,
    STRATEGY_REJECT,
    SYNTHETIC_TEST,
    SYSTEM_FAILURE,
    OpportunityCycleRecord,
    OpportunityDenominatorError,
    OpportunityDenominatorStore,
    OpportunityRecord,
    OpportunityReference,
    OpportunitySeed,
    build_cycle_bundle,
    current_policy,
    validate_cycle,
    validate_opportunity,
)
from momentum_hunter.specialist_opinion import EvidenceReference


CONTRACT_VERSION = 1
PRODUCER_POLICY_VERSION = "continuous-denominator-producer-policy-v1"
PRODUCER_PROFILE = "continuous-opportunity-denominator-wiring-v1"
CYCLE_TYPE = "CONTINUOUS_INTRADAY"
SESSION_TYPE = "CONTINUOUS_INTRADAY"

CURRENTLY_OBSERVED = "CURRENTLY_OBSERVED"
RETAINED_FROM_PRIOR_DISCOVERY = "RETAINED_FROM_PRIOR_DISCOVERY"
SOURCE_RELATIONSHIPS = frozenset(
    {CURRENTLY_OBSERVED, RETAINED_FROM_PRIOR_DISCOVERY}
)

SOURCE_ROW_QUALIFIED = "QUALIFIED"
SOURCE_ROW_REJECTED = "REJECTED_FILTER"
SOURCE_ROW_BLOCKED_DATA = "BLOCKED_DATA"
SOURCE_ROW_SYSTEM_FAILURE = "SYSTEM_FAILURE"
SOURCE_ROW_TREATMENTS = frozenset(
    {
        SOURCE_ROW_QUALIFIED,
        SOURCE_ROW_REJECTED,
        SOURCE_ROW_BLOCKED_DATA,
        SOURCE_ROW_SYSTEM_FAILURE,
    }
)

INCOMPLETE_DISCOVERY_FAILURE = "DISCOVERY_SOURCE_FAILURE"
INCOMPLETE_MISSING_UNIVERSE_MEMBER = "MISSING_UNIVERSE_MEMBER"
INCOMPLETE_MISSING_COMPOSITION_RESULT = "MISSING_COMPOSITION_MEMBER_RESULT"
INCOMPLETE_COMPOSITION_SYSTEM_FAILURE = "COMPOSITION_SYSTEM_FAILURE"

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ContinuousDenominatorError(OpportunityDenominatorError):
    """Raised when upstream cycle lineage cannot be reconciled safely."""


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            _to_wire(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def _to_wire(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item: _to_wire(field_value)
            for item, field_value in asdict(value).items()
        }
    if isinstance(value, Mapping):
        return {
            str(key): _to_wire(item)
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_to_wire(item) for item in value]
    return value


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_json({"domain": domain, "value": value})
    ).hexdigest()


@dataclass(frozen=True)
class ContinuousDenominatorPolicy:
    contract_version: int = CONTRACT_VERSION
    policy_version: str = PRODUCER_POLICY_VERSION
    profile: str = PRODUCER_PROFILE
    cycle_type: str = CYCLE_TYPE
    sample_identity: str = SAMPLE_IDENTITY
    denominator_policy_fingerprint: str = POLICY_FINGERPRINT
    source_unit_rule: str = "DISCOVERY_ROWS_PLUS_RETAINED_MEMBER_OBSERVATIONS"
    discovery_failure_rule: str = "PRESERVE_PARTIAL_ROWS_AND_RETAINED_EVALUATIONS"
    authority: str = RESEARCH_ONLY
    execution_authority: str = EXECUTION_AUTHORITY_NONE

    @property
    def fingerprint(self) -> str:
        return _fingerprint("continuous-denominator-policy-v1", asdict(self))


@dataclass(frozen=True)
class SourceRowDispositionRecord:
    row_id: str
    row_fingerprint: str
    symbol: str
    source_row_ordinal: int
    source_row_identity: str
    source_page_number: int | None
    source_page_offset: int | None
    source_page_ordinal: int | None
    global_observation_ordinal: int | None
    source_relationship: str | None
    discovery_disposition: str
    discovery_reasons: tuple[str, ...]
    treatment: str
    universe_member_id: str | None
    opportunity_id: str
    opportunity_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class MemberDispositionRecord:
    universe_member_id: str
    member_fingerprint: str
    symbol: str
    source_relationship: str
    current_source_row_ids: tuple[str, ...]
    first_discovery_snapshot_id: str
    latest_discovery_snapshot_id: str
    latest_source_row_id: str
    current_tier: str
    current_state: str
    provider_bound_since: str
    composition_disposition: str
    readiness_status: str
    blocker_reasons: tuple[str, ...]
    setup_id: str | None
    predecessor_setup_id: str | None
    trade_plan_id: str | None
    opportunity_refs: tuple[OpportunityReference, ...]
    fingerprint: str


@dataclass(frozen=True)
class ContinuousDenominatorCounts:
    discovery_raw_rows: int
    discovery_parsed_rows: int
    discovery_represented_rows: int
    discovery_qualified: int
    discovery_rejected: int
    retained_prior_members_presented: int
    universe_admitted: int
    universe_retained: int
    universe_provider_bound: int
    universe_expired: int
    composition_presented: int
    composition_ready: int
    composition_waiting: int
    composition_blocked_data: int
    composition_data_failure: int
    composition_no_change: int
    composition_missed_entry: int
    composition_successor_created: int
    composition_plan_composed: int
    denominator_opportunity_records: int
    denominator_source_row_dispositions: int


@dataclass(frozen=True)
class ContinuousDenominatorLinkageRecord:
    contract_version: int
    producer_policy_version: str
    producer_policy_fingerprint: str
    sample_identity: str
    sample_status: str
    denominator_policy_fingerprint: str
    cycle_id: str
    cycle_fingerprint: str
    cycle_type: str
    session_date: str
    observed_at: str
    decision_cutoff: str
    discovery_snapshot_id: str
    discovery_fingerprint: str
    discovery_query_fingerprint: str
    discovery_pagination_policy_fingerprint: str
    coverage_scope: str
    coverage_state: str
    pagination_state: str
    cross_page_atomicity: str
    universe_policy_fingerprint: str
    universe_state_fingerprint: str
    composition_cycle_id: str
    composition_fingerprint: str
    composition_policy_fingerprint: str
    source_identity: str
    source_evidence_fingerprint: str
    source_rows: tuple[SourceRowDispositionRecord, ...]
    members: tuple[MemberDispositionRecord, ...]
    counts: ContinuousDenominatorCounts
    complete_denominator: bool
    incomplete_reasons: tuple[str, ...]
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class ContinuousDenominatorResult:
    cycle: OpportunityCycleRecord
    opportunities: tuple[OpportunityRecord, ...]
    linkage: ContinuousDenominatorLinkageRecord


@dataclass(frozen=True)
class ContinuousDenominatorMetrics:
    cycles_produced: int = 0
    complete_cycles: int = 0
    incomplete_cycles: int = 0
    source_rows_represented: int = 0
    source_rows_qualified: int = 0
    source_rows_rejected: int = 0
    opportunities_new: int = 0
    opportunities_retained: int = 0
    opportunities_provider_bound: int = 0
    opportunities_blocked_data: int = 0
    opportunities_waiting: int = 0
    opportunities_no_change: int = 0
    opportunities_missed_entry: int = 0
    opportunities_successor_created: int = 0
    opportunities_plan_composed: int = 0
    discovery_failures: int = 0
    system_failures: int = 0


@dataclass(frozen=True)
class _SeedContext:
    seed: OpportunitySeed
    row: DiscoveryRow | None
    member: HotUniverseMember | None
    composition: ContinuousCompositionMemberResult | None
    source_relationship: str
    treatment: str


def reference_continuous_denominator_policy() -> ContinuousDenominatorPolicy:
    """Return the inactive research-only producer policy."""

    return ContinuousDenominatorPolicy()


def produce_continuous_denominator(
    *,
    discovery_snapshot: DiscoverySnapshot,
    universe_result: HotUniverseResult,
    composition_cycle: ContinuousCompositionCycle,
    observation_mode: str = SYNTHETIC_TEST,
    policy: ContinuousDenominatorPolicy | None = None,
) -> ContinuousDenominatorResult:
    """Map one immutable upstream pulse into STAT-DATA-001 records."""

    policy = policy or reference_continuous_denominator_policy()
    _validate_policy(policy)
    if observation_mode != SYNTHETIC_TEST:
        raise ContinuousDenominatorError(
            "The inactive STAT-DATA-002 producer accepts synthetic evidence only."
        )
    denominator_policy = current_policy()
    if denominator_policy.status != SAMPLE_STATUS:
        raise ContinuousDenominatorError("Opportunity denominator activation drifted.")

    snapshot = _validated_snapshot(discovery_snapshot)
    _validate_universe_result(universe_result)
    _validate_composition_cycle(composition_cycle)
    _validate_lineage(snapshot, universe_result, composition_cycle)

    rows_by_symbol: dict[str, list[DiscoveryRow]] = {}
    for row in snapshot.rows:
        rows_by_symbol.setdefault(row.symbol, []).append(row)
    members = {
        member.member_id: member
        for member in universe_result.state.members
        if member.session_date == composition_cycle.session_date
    }
    if len(members) != sum(
        member.session_date == composition_cycle.session_date
        for member in universe_result.state.members
    ):
        raise ContinuousDenominatorError("Universe contains duplicate member identity.")
    members_by_symbol = {
        member.symbol: member for member in members.values() if member.current_state == TRACKED
    }
    if len(members_by_symbol) != sum(
        member.current_state == TRACKED for member in members.values()
    ):
        raise ContinuousDenominatorError("Universe contains duplicate tracked symbol.")
    composition_by_member = {
        result.universe_member_id: result
        for result in composition_cycle.member_results
    }
    if len(composition_by_member) != len(composition_cycle.member_results):
        raise ContinuousDenominatorError("Composition member result is duplicated.")
    if set(composition_by_member).difference(members):
        raise ContinuousDenominatorError(
            "Composition result references an unknown universe member."
        )

    incomplete: list[str] = []
    if snapshot.status != SNAPSHOT_STATUS_COMPLETE:
        incomplete.append(INCOMPLETE_DISCOVERY_FAILURE)
    if composition_cycle.shared_failure_state:
        incomplete.append(INCOMPLETE_COMPOSITION_SYSTEM_FAILURE)

    contexts: list[_SeedContext] = []
    qualified_member_ids: set[str] = set()
    for row in snapshot.rows:
        if snapshot.status != SNAPSHOT_STATUS_COMPLETE:
            contexts.append(
                _context_for_failed_discovery_row(row, snapshot, composition_cycle)
            )
            continue
        if row.disposition == ROW_DISPOSITION_REJECTED_FILTER:
            contexts.append(_context_for_rejected_row(row, snapshot, composition_cycle))
            continue
        member = members_by_symbol.get(row.symbol)
        if member is None:
            incomplete.append(INCOMPLETE_MISSING_UNIVERSE_MEMBER)
            contexts.append(
                _context_for_missing_row(row, snapshot, composition_cycle)
            )
            continue
        qualified_member_ids.add(member.member_id)
        result = composition_by_member.get(member.member_id)
        if result is None:
            incomplete.append(INCOMPLETE_MISSING_COMPOSITION_RESULT)
            contexts.append(
                _context_for_missing_result(row, member, snapshot, composition_cycle)
            )
            continue
        contexts.append(
            _context_for_member(
                row=row,
                member=member,
                result=result,
                snapshot=snapshot,
                composition_cycle=composition_cycle,
                source_relationship=CURRENTLY_OBSERVED,
            )
        )

    for member_id, result in sorted(composition_by_member.items()):
        if member_id in qualified_member_ids:
            continue
        member = members[member_id]
        contexts.append(
            _context_for_member(
                row=None,
                member=member,
                result=result,
                snapshot=snapshot,
                composition_cycle=composition_cycle,
                source_relationship=(
                    CURRENTLY_OBSERVED
                    if member.symbol in rows_by_symbol
                    else RETAINED_FROM_PRIOR_DISCOVERY
                ),
            )
        )

    for member_id, member in sorted(members.items()):
        if member_id in composition_by_member:
            continue
        incomplete.append(INCOMPLETE_MISSING_COMPOSITION_RESULT)
        contexts.append(
            _context_for_unreported_member(member, snapshot, composition_cycle)
        )

    incomplete_reasons = tuple(dict.fromkeys(incomplete))
    source_identity, source_fingerprint = _source_identity(
        snapshot, universe_result, composition_cycle, policy
    )
    failure_reason = None
    if incomplete_reasons:
        failure_reason = (
            SYSTEM_FAILURE
            if any(
                item
                in {
                    INCOMPLETE_MISSING_UNIVERSE_MEMBER,
                    INCOMPLETE_MISSING_COMPOSITION_RESULT,
                    INCOMPLETE_COMPOSITION_SYSTEM_FAILURE,
                }
                for item in incomplete_reasons
            )
            else DATA_CONTRACT_FAILURE
        )
    cycle, opportunities = build_cycle_bundle(
        cycle_type=CYCLE_TYPE,
        session_date=composition_cycle.session_date,
        session_type=SESSION_TYPE,
        observed_at=composition_cycle.started_at,
        decision_cutoff=composition_cycle.evidence_cutoff,
        source_identity=source_identity,
        source_evidence_fingerprint=source_fingerprint,
        raw_count=len(contexts),
        parsed_count=len(contexts),
        seeds=(context.seed for context in contexts),
        observation_mode=observation_mode,
        failure_reason=failure_reason,
        policy=denominator_policy,
    )
    source_rows = _source_row_records(contexts, opportunities)
    member_records = _member_records(
        contexts,
        opportunities,
        universe_result=universe_result,
        composition_cycle=composition_cycle,
        rows_by_symbol=rows_by_symbol,
    )
    counts = _counts(
        snapshot=snapshot,
        universe_result=universe_result,
        composition_cycle=composition_cycle,
        source_rows=source_rows,
        member_records=member_records,
        opportunities=opportunities,
    )
    _reconcile_counts(snapshot, composition_cycle, counts)
    linkage = _build_linkage(
        policy=policy,
        cycle=cycle,
        snapshot=snapshot,
        universe_result=universe_result,
        composition_cycle=composition_cycle,
        source_identity=source_identity,
        source_fingerprint=source_fingerprint,
        source_rows=source_rows,
        members=member_records,
        counts=counts,
        incomplete_reasons=incomplete_reasons,
    )
    result = ContinuousDenominatorResult(cycle, opportunities, linkage)
    validate_continuous_denominator_result(result)
    return result


def summarize_continuous_denominators(
    results: Iterable[ContinuousDenominatorResult],
) -> ContinuousDenominatorMetrics:
    """Aggregate health counters without adding profitability semantics."""

    items = tuple(results)
    for item in items:
        validate_continuous_denominator_result(item)
    links = [item.linkage for item in items]
    return ContinuousDenominatorMetrics(
        cycles_produced=len(items),
        complete_cycles=sum(item.complete_denominator for item in links),
        incomplete_cycles=sum(not item.complete_denominator for item in links),
        source_rows_represented=sum(
            item.counts.discovery_represented_rows for item in links
        ),
        source_rows_qualified=sum(item.counts.discovery_qualified for item in links),
        source_rows_rejected=sum(item.counts.discovery_rejected for item in links),
        opportunities_new=sum(item.counts.discovery_qualified for item in links),
        opportunities_retained=sum(
            item.counts.retained_prior_members_presented for item in links
        ),
        opportunities_provider_bound=sum(
            item.counts.universe_provider_bound for item in links
        ),
        opportunities_blocked_data=sum(
            item.counts.composition_blocked_data
            + item.counts.composition_data_failure
            for item in links
        ),
        opportunities_waiting=sum(item.counts.composition_waiting for item in links),
        opportunities_no_change=sum(
            item.counts.composition_no_change for item in links
        ),
        opportunities_missed_entry=sum(
            item.counts.composition_missed_entry for item in links
        ),
        opportunities_successor_created=sum(
            item.counts.composition_successor_created for item in links
        ),
        opportunities_plan_composed=sum(
            item.counts.composition_plan_composed for item in links
        ),
        discovery_failures=sum(
            INCOMPLETE_DISCOVERY_FAILURE in item.incomplete_reasons for item in links
        ),
        system_failures=sum(
            any(
                reason != INCOMPLETE_DISCOVERY_FAILURE
                for reason in item.incomplete_reasons
            )
            for item in links
        ),
    )


class ContinuousDenominatorStore:
    """Write the authoritative cycle first and linkage as its terminal receipt."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise ContinuousDenominatorError("Persistence root must be an explicit Path.")
        self.root = root.resolve()
        self.denominator = OpportunityDenominatorStore(self.root)
        self.linkage_root = (
            self.root / SAMPLE_IDENTITY / "continuous-cycle-linkage"
        )

    def persist(self, result: ContinuousDenominatorResult) -> None:
        validate_continuous_denominator_result(result)
        path = self._path(result.cycle.cycle_id)
        content = _linkage_bytes(result.linkage)
        if path.exists():
            existing = path.read_bytes()
            self._read(path, expected_cycle_id=result.cycle.cycle_id)
            if existing != content:
                raise ContinuousDenominatorError(
                    "Conflicting continuous linkage record exists."
                )
        self.denominator.persist_cycle(result.cycle, result.opportunities)
        if not path.exists():
            _atomic_write(path, content)

    def is_terminal(self, cycle_id: str) -> bool:
        path = self._path(cycle_id)
        if not path.exists():
            return False
        payload = self._read(path, expected_cycle_id=cycle_id)
        self.denominator._require_cycle(
            cycle_id, str(payload["cycle_fingerprint"])
        )
        self.denominator.summary()
        return True

    def read_linkage(self, cycle_id: str) -> Mapping[str, object]:
        return self._read(self._path(cycle_id), expected_cycle_id=cycle_id)

    def _path(self, cycle_id: str) -> Path:
        if not _SHA256.fullmatch(cycle_id):
            raise ContinuousDenominatorError("Cycle identity is malformed.")
        return self.linkage_root / f"{cycle_id}.json"

    def _read(self, path: Path, *, expected_cycle_id: str) -> Mapping[str, object]:
        try:
            value = json.loads(path.read_text(encoding="ascii"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ContinuousDenominatorError(
                "Continuous linkage record is malformed."
            ) from exc
        if not isinstance(value, dict) or set(value) != {"recordType", "payload"}:
            raise ContinuousDenominatorError("Continuous linkage envelope is invalid.")
        if value["recordType"] != "CONTINUOUS_DENOMINATOR_LINKAGE":
            raise ContinuousDenominatorError("Continuous linkage type is invalid.")
        payload = value["payload"]
        if not isinstance(payload, dict):
            raise ContinuousDenominatorError("Continuous linkage payload is invalid.")
        _validate_linkage_payload(payload)
        if payload.get("cycle_id") != expected_cycle_id:
            raise ContinuousDenominatorError("Continuous linkage cycle identity drifted.")
        return payload


def validate_continuous_denominator_result(
    result: ContinuousDenominatorResult,
) -> None:
    if not isinstance(result, ContinuousDenominatorResult):
        raise ContinuousDenominatorError("Continuous denominator result is malformed.")
    validate_cycle(result.cycle)
    for opportunity in result.opportunities:
        validate_opportunity(opportunity)
        if opportunity.cycle_id != result.cycle.cycle_id:
            raise ContinuousDenominatorError("Opportunity cycle identity drifted.")
    expected = {
        item.opportunity_id: item.opportunity_fingerprint
        for item in result.cycle.opportunity_refs
    }
    actual = {item.opportunity_id: item.fingerprint for item in result.opportunities}
    if expected != actual:
        raise ContinuousDenominatorError("Opportunity references are incomplete.")
    linkage = result.linkage
    if linkage.cycle_id != result.cycle.cycle_id or linkage.cycle_fingerprint != result.cycle.fingerprint:
        raise ContinuousDenominatorError("Linkage cycle identity drifted.")
    if linkage.complete_denominator != result.cycle.complete_denominator:
        raise ContinuousDenominatorError("Linkage completeness contradicts its cycle.")
    if linkage.counts.denominator_opportunity_records != len(result.opportunities):
        raise ContinuousDenominatorError("Linkage opportunity count is inconsistent.")
    if linkage.counts.denominator_source_row_dispositions != len(linkage.source_rows):
        raise ContinuousDenominatorError("Linkage source-row count is inconsistent.")
    if len({item.row_id for item in linkage.source_rows}) != len(linkage.source_rows):
        raise ContinuousDenominatorError("Linkage source-row identity is duplicated.")
    if len({item.universe_member_id for item in linkage.members}) != len(linkage.members):
        raise ContinuousDenominatorError("Linkage member identity is duplicated.")
    if any(item.treatment not in SOURCE_ROW_TREATMENTS for item in linkage.source_rows):
        raise ContinuousDenominatorError("Linkage source-row treatment is unsupported.")
    if any(item.source_relationship not in SOURCE_RELATIONSHIPS for item in linkage.members):
        raise ContinuousDenominatorError("Linkage member relationship is unsupported.")
    counts = linkage.counts
    if not (
        counts.discovery_represented_rows
        == counts.discovery_qualified + counts.discovery_rejected
        == counts.denominator_source_row_dispositions
    ):
        raise ContinuousDenominatorError("Linkage discovery counts do not reconcile.")
    linked_opportunities = {
        item.opportunity_id for item in linkage.source_rows
    } | {
        reference.opportunity_id
        for member in linkage.members
        for reference in member.opportunity_refs
    }
    if linked_opportunities != set(actual):
        raise ContinuousDenominatorError(
            "Linkage does not account for every opportunity identity."
        )
    payload = asdict(linkage)
    fingerprint = payload.pop("fingerprint")
    if fingerprint != _fingerprint("continuous-denominator-linkage-v1", payload):
        raise ContinuousDenominatorError("Continuous linkage fingerprint is invalid.")
    if linkage.authority != RESEARCH_ONLY or linkage.execution_authority != EXECUTION_AUTHORITY_NONE:
        raise ContinuousDenominatorError("Continuous linkage attempted execution authority.")


def _validated_snapshot(snapshot: DiscoverySnapshot) -> DiscoverySnapshot:
    if not isinstance(snapshot, DiscoverySnapshot):
        raise ContinuousDenominatorError("Discovery snapshot is malformed.")
    try:
        return DiscoverySnapshot.from_dict(snapshot.to_dict())
    except (KeyError, TypeError, ValueError) as exc:
        raise ContinuousDenominatorError("Discovery snapshot is invalid or tampered.") from exc


def _validate_universe_result(result: HotUniverseResult) -> None:
    if not isinstance(result, HotUniverseResult):
        raise ContinuousDenominatorError("Hot-universe result is malformed.")
    validate_hot_universe_state(result.state)
    stored = {item.transition_id: item.fingerprint for item in result.state.transitions}
    for transition in result.transitions:
        if stored.get(transition.transition_id) != transition.fingerprint:
            raise ContinuousDenominatorError("Pulse transition is absent or conflicting.")
    if result.summary != _universe_summary(result.state, result.transitions):
        raise ContinuousDenominatorError("Hot-universe summary is inconsistent.")


def _validate_composition_cycle(cycle: ContinuousCompositionCycle) -> None:
    if not isinstance(cycle, ContinuousCompositionCycle):
        raise ContinuousDenominatorError("Composition cycle is malformed.")
    for result in cycle.member_results:
        payload = {
            "universe_member_id": result.universe_member_id,
            "symbol": result.symbol,
            "session_date": result.session_date,
            "disposition": result.disposition,
            "readiness_request": result.readiness_request,
            "readiness_assessment": result.readiness_assessment,
            "lifecycle_proposal": result.lifecycle_proposal,
            "intraday_plan": result.intraday_plan,
            "blocker_reasons": result.blocker_reasons,
            "authority": result.authority,
        }
        if result.fingerprint != _composition_fingerprint(payload):
            raise ContinuousDenominatorError("Composition member fingerprint is invalid.")
    if cycle.summary != _composition_summary(cycle.member_results):
        raise ContinuousDenominatorError("Composition summary is inconsistent.")
    payload = {
        "session_date": cycle.session_date,
        "started_at": cycle.started_at,
        "evidence_cutoff": cycle.evidence_cutoff,
        "universe_policy_fingerprint": cycle.universe_policy_fingerprint,
        "composition_policy_fingerprint": cycle.composition_policy_fingerprint,
        "member_results": cycle.member_results,
        "summary": cycle.summary,
        "shared_failure_state": cycle.shared_failure_state,
    }
    expected = _composition_fingerprint(
        {
            **payload,
            "member_results": [asdict(item) for item in cycle.member_results],
            "summary": asdict(cycle.summary),
        }
    )
    if cycle.fingerprint != expected or cycle.cycle_id != f"continuous-composition-{expected[:24]}":
        raise ContinuousDenominatorError("Composition cycle fingerprint is invalid.")


def _validate_lineage(
    snapshot: DiscoverySnapshot,
    universe_result: HotUniverseResult,
    composition_cycle: ContinuousCompositionCycle,
) -> None:
    if snapshot.session_date != composition_cycle.session_date:
        raise ContinuousDenominatorError("Discovery and composition session mismatch.")
    if universe_result.state.current_session_date != composition_cycle.session_date:
        raise ContinuousDenominatorError("Universe and composition session mismatch.")
    if universe_result.state.policy_fingerprint != composition_cycle.universe_policy_fingerprint:
        raise ContinuousDenominatorError("Universe policy fingerprint mismatch.")
    if _parse_timestamp(composition_cycle.started_at) < snapshot.evaluated_at:
        raise ContinuousDenominatorError("Composition started before discovery was evaluated.")
    if _parse_timestamp(composition_cycle.evidence_cutoff) < _parse_timestamp(composition_cycle.started_at):
        raise ContinuousDenominatorError("Composition cutoff precedes cycle start.")
    if snapshot.status == SNAPSHOT_STATUS_COMPLETE:
        if not universe_result.state.snapshot_receipts or (
            universe_result.state.snapshot_receipts[-1].snapshot_id
            != snapshot.snapshot_id
        ):
            raise ContinuousDenominatorError(
                "Universe latest receipt does not match the discovery pulse."
            )
        receipt = next(
            (
                item
                for item in universe_result.state.snapshot_receipts
                if item.snapshot_id == snapshot.snapshot_id
            ),
            None,
        )
        if receipt is None or receipt.snapshot_fingerprint != snapshot.fingerprint:
            raise ContinuousDenominatorError("Universe lacks the exact discovery receipt.")
    else:
        matching_failure = next(
            (
                item
                for item in universe_result.transitions
                if item.transition_type == DISCOVERY_FAILURE
                and item.source_observed_at == snapshot.evaluated_at.isoformat()
                and item.reason == (snapshot.failure_reason or "")
            ),
            None,
        )
        if universe_result.status != FAILURE_RECORDED or matching_failure is None:
            raise ContinuousDenominatorError(
                "Failed discovery pulse lacks an explicit universe failure receipt."
            )
    cutoff = _parse_timestamp(composition_cycle.evidence_cutoff)
    for member in universe_result.state.members:
        if member.session_date == composition_cycle.session_date and _parse_timestamp(member.last_observed_at) > cutoff:
            raise ContinuousDenominatorError("Universe member is future-dated beyond cutoff.")


def _context_for_rejected_row(
    row: DiscoveryRow,
    snapshot: DiscoverySnapshot,
    cycle: ContinuousCompositionCycle,
) -> _SeedContext:
    evidence = _row_evidence(row, snapshot)
    return _SeedContext(
        seed=OpportunitySeed(
            origin_kinds=(STRATEGY_REJECT,),
            origin_record_id=row.row_id,
            origin_fingerprint=row.fingerprint,
            symbol=row.symbol,
            security_identity_status="UNRESOLVED",
            security_id=None,
            observed_at=snapshot.evaluated_at.isoformat(),
            decision_cutoff=cycle.evidence_cutoff,
            candidate_id=row.candidate_identity,
            setup_id=None,
            trade_plan_id=None,
            rank=_row_rank(row),
            evidence_refs=(evidence,),
            disposition=REJECTED_STRATEGY,
            decision_class=ACTUAL_SYSTEM_DECISION,
            blocker_reasons=tuple(_reason(item) for item in row.disposition_reasons),
        ),
        row=row,
        member=None,
        composition=None,
        source_relationship=CURRENTLY_OBSERVED,
        treatment=SOURCE_ROW_REJECTED,
    )


def _context_for_missing_row(
    row: DiscoveryRow,
    snapshot: DiscoverySnapshot,
    cycle: ContinuousCompositionCycle,
) -> _SeedContext:
    return _SeedContext(
        seed=OpportunitySeed(
            origin_kinds=(CONTINUOUS_INTRADAY_OPPORTUNITY,),
            origin_record_id=row.row_id,
            origin_fingerprint=row.fingerprint,
            symbol=row.symbol,
            security_identity_status="UNRESOLVED",
            security_id=None,
            observed_at=snapshot.evaluated_at.isoformat(),
            decision_cutoff=cycle.evidence_cutoff,
            candidate_id=row.candidate_identity,
            setup_id=None,
            trade_plan_id=None,
            rank=_row_rank(row),
            evidence_refs=(_row_evidence(row, snapshot),),
            disposition=SYSTEM_FAILURE,
            decision_class=ACTUAL_SYSTEM_DECISION,
            blocker_reasons=(INCOMPLETE_MISSING_UNIVERSE_MEMBER,),
        ),
        row=row,
        member=None,
        composition=None,
        source_relationship=CURRENTLY_OBSERVED,
        treatment=SOURCE_ROW_SYSTEM_FAILURE,
    )


def _context_for_failed_discovery_row(
    row: DiscoveryRow,
    snapshot: DiscoverySnapshot,
    cycle: ContinuousCompositionCycle,
) -> _SeedContext:
    return _SeedContext(
        seed=OpportunitySeed(
            origin_kinds=(CONTINUOUS_INTRADAY_OPPORTUNITY,),
            origin_record_id=row.row_id,
            origin_fingerprint=row.fingerprint,
            symbol=row.symbol,
            security_identity_status="UNRESOLVED",
            security_id=None,
            observed_at=snapshot.evaluated_at.isoformat(),
            decision_cutoff=cycle.evidence_cutoff,
            candidate_id=row.candidate_identity,
            setup_id=None,
            trade_plan_id=None,
            rank=_row_rank(row),
            evidence_refs=(_row_evidence(row, snapshot),),
            disposition=BLOCKED_DATA,
            decision_class=ACTUAL_SYSTEM_DECISION,
            blocker_reasons=(INCOMPLETE_DISCOVERY_FAILURE,),
        ),
        row=row,
        member=None,
        composition=None,
        source_relationship=CURRENTLY_OBSERVED,
        treatment=SOURCE_ROW_BLOCKED_DATA,
    )


def _context_for_missing_result(
    row: DiscoveryRow,
    member: HotUniverseMember,
    snapshot: DiscoverySnapshot,
    cycle: ContinuousCompositionCycle,
) -> _SeedContext:
    return _SeedContext(
        seed=_member_seed(
            row=row,
            member=member,
            result=None,
            snapshot=snapshot,
            cycle=cycle,
            disposition=SYSTEM_FAILURE,
            blockers=(INCOMPLETE_MISSING_COMPOSITION_RESULT,),
        ),
        row=row,
        member=member,
        composition=None,
        source_relationship=CURRENTLY_OBSERVED,
        treatment=SOURCE_ROW_SYSTEM_FAILURE,
    )


def _context_for_unreported_member(
    member: HotUniverseMember,
    snapshot: DiscoverySnapshot,
    cycle: ContinuousCompositionCycle,
) -> _SeedContext:
    return _SeedContext(
        seed=_member_seed(
            row=None,
            member=member,
            result=None,
            snapshot=snapshot,
            cycle=cycle,
            disposition=SYSTEM_FAILURE,
            blockers=(INCOMPLETE_MISSING_COMPOSITION_RESULT,),
        ),
        row=None,
        member=member,
        composition=None,
        source_relationship=RETAINED_FROM_PRIOR_DISCOVERY,
        treatment=SOURCE_ROW_SYSTEM_FAILURE,
    )


def _context_for_member(
    *,
    row: DiscoveryRow | None,
    member: HotUniverseMember,
    result: ContinuousCompositionMemberResult,
    snapshot: DiscoverySnapshot,
    composition_cycle: ContinuousCompositionCycle,
    source_relationship: str,
) -> _SeedContext:
    disposition = _denominator_disposition(result)
    blockers = tuple(_reason(item) for item in result.blocker_reasons)
    return _SeedContext(
        seed=_member_seed(
            row=row,
            member=member,
            result=result,
            snapshot=snapshot,
            cycle=composition_cycle,
            disposition=disposition,
            blockers=blockers,
        ),
        row=row,
        member=member,
        composition=result,
        source_relationship=source_relationship,
        treatment=SOURCE_ROW_QUALIFIED if row is not None else result.disposition,
    )


def _member_seed(
    *,
    row: DiscoveryRow | None,
    member: HotUniverseMember,
    result: ContinuousCompositionMemberResult | None,
    snapshot: DiscoverySnapshot,
    cycle: ContinuousCompositionCycle,
    disposition: str,
    blockers: tuple[str, ...],
) -> OpportunitySeed:
    references: list[EvidenceReference] = []
    if row is not None:
        references.append(_row_evidence(row, snapshot))
    references.append(
        EvidenceReference(
            evidence_id=member.member_id,
            evidence_type="HOT_UNIVERSE_MEMBER",
            source="hot-universe",
            as_of=member.last_observed_at,
            fingerprint=member.fingerprint,
        )
    )
    if result is not None:
        references.append(
            EvidenceReference(
                evidence_id=f"{cycle.cycle_id}:{member.member_id}",
                evidence_type="CONTINUOUS_COMPOSITION_RESULT",
                source="continuous-composition",
                as_of=cycle.evidence_cutoff,
                fingerprint=result.fingerprint,
            )
        )
    proposal = result.lifecycle_proposal if result is not None else None
    plan = result.intraday_plan if result is not None else None
    origin_kind = (
        PROVIDER_BOUND_ROW
        if disposition == NOT_EVALUATED_PROVIDER_BOUND
        else CONTINUOUS_INTRADAY_OPPORTUNITY
    )
    return OpportunitySeed(
        origin_kinds=(origin_kind,),
        origin_record_id=row.row_id if row is not None else member.member_id,
        origin_fingerprint=row.fingerprint if row is not None else member.fingerprint,
        symbol=member.symbol,
        security_identity_status="UNRESOLVED",
        security_id=None,
        observed_at=(
            snapshot.evaluated_at.isoformat()
            if row is not None
            else member.first_observed_at
        ),
        decision_cutoff=cycle.evidence_cutoff,
        candidate_id=row.candidate_identity if row is not None else member.latest_candidate_identity,
        setup_id=proposal.setup_id if proposal is not None and proposal.setup_id else None,
        trade_plan_id=plan.plan_id if plan is not None and plan.plan_id else None,
        rank=_row_rank(row) if row is not None else None,
        evidence_refs=tuple(references),
        disposition=disposition,
        decision_class=ACTUAL_SYSTEM_DECISION,
        blocker_reasons=blockers,
    )


def _denominator_disposition(result: ContinuousCompositionMemberResult) -> str:
    if result.disposition == COMPOSITION_PROVIDER_BOUND:
        return NOT_EVALUATED_PROVIDER_BOUND
    if result.disposition in {
        COMPOSITION_BLOCKED_DATA,
        COMPOSITION_DATA_FAILURE,
        UNSUPPORTED_SESSION_RESULT,
    }:
        return BLOCKED_DATA
    return NO_ACTION_RESEARCH_ONLY


def _row_evidence(row: DiscoveryRow, snapshot: DiscoverySnapshot) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=row.row_id,
        evidence_type="DISCOVERY_ROW",
        source=snapshot.source,
        as_of=snapshot.evaluated_at.isoformat(),
        fingerprint=row.fingerprint,
    )


def _source_row_records(
    contexts: Sequence[_SeedContext],
    opportunities: Sequence[OpportunityRecord],
) -> tuple[SourceRowDispositionRecord, ...]:
    records: list[SourceRowDispositionRecord] = []
    for context, opportunity in zip(contexts, opportunities, strict=True):
        row = context.row
        if row is None:
            continue
        payload = {
            "row_id": row.row_id,
            "row_fingerprint": row.fingerprint,
            "symbol": row.symbol,
            "source_row_ordinal": row.source_row_ordinal,
            "source_row_identity": row.source_row_identity,
            "source_page_number": row.source_page_number,
            "source_page_offset": row.source_page_offset,
            "source_page_ordinal": row.source_page_ordinal,
            "global_observation_ordinal": row.global_observation_ordinal,
            "source_relationship": row.source_relationship,
            "discovery_disposition": row.disposition,
            "discovery_reasons": row.disposition_reasons,
            "treatment": context.treatment,
            "universe_member_id": context.member.member_id if context.member else None,
            "opportunity_id": opportunity.opportunity_id,
            "opportunity_fingerprint": opportunity.fingerprint,
        }
        payload["fingerprint"] = _fingerprint(
            "continuous-source-row-disposition-v1", payload
        )
        records.append(SourceRowDispositionRecord(**payload))
    return tuple(records)


def _member_records(
    contexts: Sequence[_SeedContext],
    opportunities: Sequence[OpportunityRecord],
    *,
    universe_result: HotUniverseResult,
    composition_cycle: ContinuousCompositionCycle,
    rows_by_symbol: Mapping[str, list[DiscoveryRow]],
) -> tuple[MemberDispositionRecord, ...]:
    refs_by_member: dict[str, list[OpportunityReference]] = {}
    for context, opportunity in zip(contexts, opportunities, strict=True):
        if context.member is None:
            continue
        refs_by_member.setdefault(context.member.member_id, []).append(
            OpportunityReference(opportunity.opportunity_id, opportunity.fingerprint)
        )
    results = {
        item.universe_member_id: item for item in composition_cycle.member_results
    }
    records: list[MemberDispositionRecord] = []
    for member in sorted(
        (
            item
            for item in universe_result.state.members
            if item.session_date == composition_cycle.session_date
        ),
        key=lambda item: item.member_id,
    ):
        result = results.get(member.member_id)
        proposal = result.lifecycle_proposal if result is not None else None
        plan = result.intraday_plan if result is not None else None
        current_rows = tuple(row.row_id for row in rows_by_symbol.get(member.symbol, ()))
        readiness = (
            result.readiness_assessment.status
            if result is not None and result.readiness_assessment is not None
            else "UNAVAILABLE"
        )
        blockers = (
            tuple(_reason(item) for item in result.blocker_reasons)
            if result is not None
            else (INCOMPLETE_MISSING_COMPOSITION_RESULT,)
        )
        payload = {
            "universe_member_id": member.member_id,
            "member_fingerprint": member.fingerprint,
            "symbol": member.symbol,
            "source_relationship": (
                CURRENTLY_OBSERVED
                if current_rows
                else RETAINED_FROM_PRIOR_DISCOVERY
            ),
            "current_source_row_ids": current_rows,
            "first_discovery_snapshot_id": member.first_discovery_snapshot_id,
            "latest_discovery_snapshot_id": member.latest_discovery_snapshot_id,
            "latest_source_row_id": member.latest_source_row_id,
            "current_tier": member.current_tier,
            "current_state": member.current_state,
            "provider_bound_since": member.provider_bound_since,
            "composition_disposition": (
                result.disposition if result is not None else SYSTEM_FAILURE
            ),
            "readiness_status": readiness,
            "blocker_reasons": blockers,
            "setup_id": proposal.setup_id if proposal is not None and proposal.setup_id else None,
            "predecessor_setup_id": (
                proposal.predecessor_setup_id
                if proposal is not None and proposal.predecessor_setup_id
                else None
            ),
            "trade_plan_id": plan.plan_id if plan is not None and plan.plan_id else None,
            "opportunity_refs": tuple(refs_by_member.get(member.member_id, ())),
        }
        payload["fingerprint"] = _fingerprint(
            "continuous-member-disposition-v1", payload
        )
        records.append(MemberDispositionRecord(**payload))
    return tuple(records)


def _counts(
    *,
    snapshot: DiscoverySnapshot,
    universe_result: HotUniverseResult,
    composition_cycle: ContinuousCompositionCycle,
    source_rows: Sequence[SourceRowDispositionRecord],
    member_records: Sequence[MemberDispositionRecord],
    opportunities: Sequence[OpportunityRecord],
) -> ContinuousDenominatorCounts:
    transitions = universe_result.transitions
    results = composition_cycle.member_results
    return ContinuousDenominatorCounts(
        discovery_raw_rows=snapshot.raw_row_count,
        discovery_parsed_rows=snapshot.parsed_row_count,
        discovery_represented_rows=snapshot.represented_row_count,
        discovery_qualified=snapshot.qualified_count,
        discovery_rejected=snapshot.rejected_count,
        retained_prior_members_presented=sum(
            item.source_relationship == RETAINED_FROM_PRIOR_DISCOVERY
            and item.composition_disposition != SYSTEM_FAILURE
            for item in member_records
        ),
        universe_admitted=sum(
            item.transition_type in {ADMITTED, READMITTED_NEW_GENERATION}
            for item in transitions
        ),
        universe_retained=sum(
            item.source_relationship == RETAINED_FROM_PRIOR_DISCOVERY
            for item in member_records
        ),
        universe_provider_bound=sum(
            item.current_tier == UNIVERSE_PROVIDER_BOUND for item in member_records
        ),
        universe_expired=sum(
            item.transition_type == EXPIRED_TRANSITION for item in transitions
        ),
        composition_presented=len(results),
        composition_ready=sum(
            item.readiness_assessment is not None
            and item.readiness_assessment.status == READY
            for item in results
        ),
        composition_waiting=sum(
            item.disposition in {WAITING_READINESS, SETUP_PENDING} for item in results
        ),
        composition_blocked_data=sum(
            item.disposition in {COMPOSITION_BLOCKED_DATA, UNSUPPORTED_SESSION_RESULT}
            for item in results
        ),
        composition_data_failure=sum(
            item.disposition == COMPOSITION_DATA_FAILURE for item in results
        ),
        composition_no_change=sum(
            item.disposition == NO_LIFECYCLE_CHANGE for item in results
        ),
        composition_missed_entry=sum(
            item.disposition == MISSED_ENTRY_RECORDED for item in results
        ),
        composition_successor_created=sum(
            item.disposition in {SUCCESSOR_SETUP_CREATED, RESEARCH_PLAN_COMPOSED}
            and item.lifecycle_proposal is not None
            and bool(item.lifecycle_proposal.predecessor_setup_id)
            for item in results
        ),
        composition_plan_composed=sum(
            item.disposition == RESEARCH_PLAN_COMPOSED for item in results
        ),
        denominator_opportunity_records=len(opportunities),
        denominator_source_row_dispositions=len(source_rows),
    )


def _reconcile_counts(
    snapshot: DiscoverySnapshot,
    composition_cycle: ContinuousCompositionCycle,
    counts: ContinuousDenominatorCounts,
) -> None:
    if not (
        counts.discovery_represented_rows
        == counts.discovery_qualified + counts.discovery_rejected
        == counts.denominator_source_row_dispositions
        == len(snapshot.rows)
    ):
        raise ContinuousDenominatorError("Discovery source-row equation failed.")
    if counts.discovery_raw_rows != counts.discovery_parsed_rows:
        raise ContinuousDenominatorError("Discovery raw/parsed equation failed.")
    if counts.discovery_parsed_rows != counts.discovery_represented_rows:
        raise ContinuousDenominatorError("Discovery parsed/represented equation failed.")
    if counts.composition_presented != len(composition_cycle.member_results):
        raise ContinuousDenominatorError("Composition presented equation failed.")


def _build_linkage(
    *,
    policy: ContinuousDenominatorPolicy,
    cycle: OpportunityCycleRecord,
    snapshot: DiscoverySnapshot,
    universe_result: HotUniverseResult,
    composition_cycle: ContinuousCompositionCycle,
    source_identity: str,
    source_fingerprint: str,
    source_rows: tuple[SourceRowDispositionRecord, ...],
    members: tuple[MemberDispositionRecord, ...],
    counts: ContinuousDenominatorCounts,
    incomplete_reasons: tuple[str, ...],
) -> ContinuousDenominatorLinkageRecord:
    payload = {
        "contract_version": CONTRACT_VERSION,
        "producer_policy_version": policy.policy_version,
        "producer_policy_fingerprint": policy.fingerprint,
        "sample_identity": SAMPLE_IDENTITY,
        "sample_status": SAMPLE_STATUS,
        "denominator_policy_fingerprint": POLICY_FINGERPRINT,
        "cycle_id": cycle.cycle_id,
        "cycle_fingerprint": cycle.fingerprint,
        "cycle_type": CYCLE_TYPE,
        "session_date": cycle.session_date,
        "observed_at": cycle.observed_at,
        "decision_cutoff": cycle.decision_cutoff,
        "discovery_snapshot_id": snapshot.snapshot_id,
        "discovery_fingerprint": snapshot.fingerprint,
        "discovery_query_fingerprint": snapshot.query_fingerprint,
        "discovery_pagination_policy_fingerprint": snapshot.pagination_policy_fingerprint,
        "coverage_scope": snapshot.coverage_scope,
        "coverage_state": snapshot.coverage_state or PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED,
        "pagination_state": snapshot.pagination_state,
        "cross_page_atomicity": (
            snapshot.cross_page_atomicity
            or (
                CROSS_PAGE_ATOMICITY_NOT_GUARANTEED
                if snapshot.pages_requested > 1
                else "SINGLE_RESPONSE_NOT_APPLICABLE"
            )
        ),
        "universe_policy_fingerprint": universe_result.state.policy_fingerprint,
        "universe_state_fingerprint": universe_result.state.fingerprint,
        "composition_cycle_id": composition_cycle.cycle_id,
        "composition_fingerprint": composition_cycle.fingerprint,
        "composition_policy_fingerprint": composition_cycle.composition_policy_fingerprint,
        "source_identity": source_identity,
        "source_evidence_fingerprint": source_fingerprint,
        "source_rows": source_rows,
        "members": members,
        "counts": counts,
        "complete_denominator": cycle.complete_denominator,
        "incomplete_reasons": incomplete_reasons,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _fingerprint(
        "continuous-denominator-linkage-v1", asdict(_LinkagePayload(**payload))
    )
    return ContinuousDenominatorLinkageRecord(**payload)


@dataclass(frozen=True)
class _LinkagePayload:
    contract_version: int
    producer_policy_version: str
    producer_policy_fingerprint: str
    sample_identity: str
    sample_status: str
    denominator_policy_fingerprint: str
    cycle_id: str
    cycle_fingerprint: str
    cycle_type: str
    session_date: str
    observed_at: str
    decision_cutoff: str
    discovery_snapshot_id: str
    discovery_fingerprint: str
    discovery_query_fingerprint: str
    discovery_pagination_policy_fingerprint: str
    coverage_scope: str
    coverage_state: str
    pagination_state: str
    cross_page_atomicity: str
    universe_policy_fingerprint: str
    universe_state_fingerprint: str
    composition_cycle_id: str
    composition_fingerprint: str
    composition_policy_fingerprint: str
    source_identity: str
    source_evidence_fingerprint: str
    source_rows: tuple[SourceRowDispositionRecord, ...]
    members: tuple[MemberDispositionRecord, ...]
    counts: ContinuousDenominatorCounts
    complete_denominator: bool
    incomplete_reasons: tuple[str, ...]
    authority: str
    execution_authority: str


def _source_identity(
    snapshot: DiscoverySnapshot,
    universe_result: HotUniverseResult,
    cycle: ContinuousCompositionCycle,
    policy: ContinuousDenominatorPolicy,
) -> tuple[str, str]:
    payload = {
        "discoverySnapshotId": snapshot.snapshot_id,
        "discoveryFingerprint": snapshot.fingerprint,
        "discoveryQueryFingerprint": snapshot.query_fingerprint,
        "discoveryPaginationPolicyFingerprint": snapshot.pagination_policy_fingerprint,
        "coverageScope": snapshot.coverage_scope,
        "coverageState": snapshot.coverage_state,
        "paginationState": snapshot.pagination_state,
        "crossPageAtomicity": snapshot.cross_page_atomicity,
        "universePolicyFingerprint": universe_result.state.policy_fingerprint,
        "universeStateFingerprint": universe_result.state.fingerprint,
        "compositionCycleId": cycle.cycle_id,
        "compositionFingerprint": cycle.fingerprint,
        "compositionPolicyFingerprint": cycle.composition_policy_fingerprint,
        "evidenceCutoff": cycle.evidence_cutoff,
        "producerPolicyFingerprint": policy.fingerprint,
    }
    fingerprint = _fingerprint("continuous-denominator-source-v1", payload)
    return f"continuous-denominator:{snapshot.snapshot_id}:{cycle.cycle_id}", fingerprint


def _validate_policy(policy: ContinuousDenominatorPolicy) -> None:
    if not isinstance(policy, ContinuousDenominatorPolicy):
        raise ContinuousDenominatorError("Producer policy is malformed.")
    if policy.contract_version != CONTRACT_VERSION or policy.policy_version != PRODUCER_POLICY_VERSION:
        raise ContinuousDenominatorError("Producer policy version drifted.")
    if policy.sample_identity != SAMPLE_IDENTITY or policy.denominator_policy_fingerprint != POLICY_FINGERPRINT:
        raise ContinuousDenominatorError("Producer sample or denominator policy drifted.")
    if policy.authority != RESEARCH_ONLY or policy.execution_authority != EXECUTION_AUTHORITY_NONE:
        raise ContinuousDenominatorError("Producer policy attempted execution authority.")


def _row_rank(row: DiscoveryRow) -> int:
    return row.global_observation_ordinal or row.source_row_ordinal


def _reason(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", str(value).strip().upper()).strip("_")
    return normalized[:96] or "UNSPECIFIED"


def _parse_timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContinuousDenominatorError("Timestamp is malformed.") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ContinuousDenominatorError("Timestamp must include timezone evidence.")
    return result


def _linkage_bytes(linkage: ContinuousDenominatorLinkageRecord) -> bytes:
    payload = asdict(linkage)
    fingerprint = payload.pop("fingerprint")
    if fingerprint != _fingerprint("continuous-denominator-linkage-v1", payload):
        raise ContinuousDenominatorError("Continuous linkage fingerprint is malformed.")
    payload["fingerprint"] = fingerprint
    return _canonical_json(
        {"recordType": "CONTINUOUS_DENOMINATOR_LINKAGE", "payload": payload}
    )


def _validate_linkage_payload(payload: Mapping[str, object]) -> None:
    fingerprint = payload.get("fingerprint")
    values = dict(payload)
    values.pop("fingerprint", None)
    if fingerprint != _fingerprint("continuous-denominator-linkage-v1", values):
        raise ContinuousDenominatorError("Persisted linkage fingerprint is invalid.")
    if payload.get("sample_identity") != SAMPLE_IDENTITY or payload.get("sample_status") != SAMPLE_STATUS:
        raise ContinuousDenominatorError("Persisted linkage sample identity drifted.")
    if payload.get("denominator_policy_fingerprint") != POLICY_FINGERPRINT:
        raise ContinuousDenominatorError("Persisted linkage denominator policy drifted.")
    if payload.get("authority") != RESEARCH_ONLY or payload.get("execution_authority") != EXECUTION_AUTHORITY_NONE:
        raise ContinuousDenominatorError("Persisted linkage attempted execution authority.")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
