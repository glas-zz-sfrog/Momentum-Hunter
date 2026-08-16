from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from momentum_hunter.broad_discovery import (
    DiscoveryPageInput,
    DiscoveryPaginationPolicy,
    DiscoveryQueryIdentity,
    DiscoverySourceRow,
    build_paginated_discovery_snapshot,
    pagination_page_bound,
)
from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_FORMING,
    ENTRY_MISSED,
    MONITORING_ACTIVATED,
    SETUP_IDENTITY_CHANGED,
    CandidateLifecycleCoordinator,
    CandidateLifecyclePolicy,
    CandidateLifecycleStore,
)
from momentum_hunter.canonical_candle_evidence import CanonicalMinuteBar
from momentum_hunter.continuous_composition import (
    DATA_FAILURE,
    DATA_UNSAFE,
    GAPPED_EVIDENCE,
    RESEARCH_PLAN_COMPOSED,
    CanonicalEvidenceInput,
    CompositionMemberInput,
    ContinuousCompositionPolicy,
    LifecycleTransitionInput,
    SuccessorSetupEvidence,
    compose_cycle,
)
from momentum_hunter.continuous_day_proof import (
    CHECK_CAPACITY,
    CHECK_DISCOVERY_FAILURE,
    CHECK_PAPER_LANE,
    ORDER_CAPABILITY_UNAVAILABLE,
    PAPER_LANE,
    PROOF_STATUS,
    REQUIRED_CHECKS,
    ContinuousDayProofError,
    build_continuous_day_proof,
    build_restart_receipt,
    build_synthetic_paper_supervision_observation,
    validate_continuous_day_proof,
)
from momentum_hunter.continuous_denominator import (
    INCOMPLETE_DISCOVERY_FAILURE,
    ContinuousDenominatorStore,
    produce_continuous_denominator,
)
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE
from momentum_hunter.hot_universe import (
    HotUniversePolicy,
    HotUniverseStore,
    apply_discovery_snapshot,
    build_discovery_failure_observation,
    record_discovery_failure,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    OPENING_BREAKOUT,
    PULLBACK,
    build_intraday_plan_evidence,
)
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.opportunity_denominator import (
    EXECUTION_AUTHORITY_NONE,
    NOT_EVALUATED_PROVIDER_BOUND,
    SYNTHETIC_TEST,
)
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
)
from momentum_hunter.time_normalized_rvol import TimeNormalizedRvolEvidence


SESSION = "2026-08-17"
CENTRAL = ZoneInfo("America/Chicago")
SOURCE_CONTRACT = "a" * 64
SEMANTIC = "b" * 64
DAILY = "c" * 64
LIFECYCLE = "d" * 64


def et(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, second, tzinfo=EASTERN_TZ)


def ct(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, second, tzinfo=CENTRAL)


def source_row(
    ordinal: int,
    symbol: str,
    *,
    qualified: bool,
    observed_at: datetime,
) -> DiscoverySourceRow:
    percent_change = 10.0 - (ordinal / 100.0) if qualified else 1.0
    volume = 10_000_000 - ordinal if qualified else 1_000_000 + ordinal
    return DiscoverySourceRow.from_mapping(
        source_row_ordinal=ordinal,
        source_row_identity=f"{observed_at.isoformat()}:{ordinal}:{symbol}",
        source_values={
            "No.": str(ordinal),
            "Ticker": symbol,
            "Price": f"{100 + ordinal / 10:.2f}",
            "Change %": f"{percent_change:.2f}%",
        },
        candidate=Candidate(
            ticker=symbol,
            company=f"{symbol} Incorporated",
            price=100 + ordinal / 10,
            percent_change=percent_change,
            volume=volume,
            relative_volume=2.0,
            market_cap=10_000_000_000,
            sector="Technology",
            industry="Software",
            float_shares=400_000_000,
            atr=2.0,
        ),
    )


def discovery_snapshot(
    *,
    evaluated_at: datetime,
    count: int,
    qualified_ordinals: set[int],
    symbols: dict[int, str] | None = None,
    fail_page: int | None = None,
):
    symbols = symbols or {}
    page_count = max(1, (count + 19) // 20)
    policy = DiscoveryPaginationPolicy(
        max_pages=page_count,
        max_rows=max(20, count),
        maximum_elapsed_time_seconds=30.0,
        per_page_timeout_seconds=5.0,
    )
    pages = []
    requested = evaluated_at - timedelta(seconds=10)
    for page_number in range(1, page_count + 1):
        page_requested = requested + timedelta(seconds=page_number - 1)
        if page_number == fail_page:
            pages.append(
                DiscoveryPageInput(
                    page_number=page_number,
                    page_offset=1 + ((page_number - 1) * 20),
                    requested_at=page_requested,
                    received_at=page_requested + timedelta(milliseconds=25),
                    request_duration_milliseconds=25,
                    failure_reason=f"PAGE_{page_number}_PROVIDER_FAILURE",
                )
            )
            break
        start = 1 + ((page_number - 1) * 20)
        stop = min(count, start + 19)
        rows = tuple(
            source_row(
                ordinal,
                symbols.get(ordinal, f"S{ordinal:04d}"),
                qualified=ordinal in qualified_ordinals,
                observed_at=evaluated_at,
            )
            for ordinal in range(start, stop + 1)
        )
        pages.append(
            DiscoveryPageInput(
                page_number=page_number,
                page_offset=start,
                requested_at=page_requested,
                received_at=page_requested + timedelta(milliseconds=25),
                request_duration_milliseconds=25,
                source_rows=rows,
                raw_row_count=len(rows),
                source_contract_fingerprint=SOURCE_CONTRACT,
                semantic_plausibility_fingerprint=SEMANTIC,
                provider_total_results=count,
                provider_page_size=20,
                terminal_page=page_number == page_count,
            )
        )
    query = DiscoveryQueryIdentity.from_criteria(
        INSTITUTIONAL_MOMENTUM,
        source_query="synthetic://whole-day-finviz",
        sort_order="-volume",
        page_bound=pagination_page_bound(policy),
    )
    return build_paginated_discovery_snapshot(
        source="finviz",
        source_version="synthetic-whole-day-finviz-v1",
        evaluated_at=evaluated_at,
        query_identity=query,
        pagination_policy=policy,
        page_inputs=pages,
    )


def active_member(state, symbol: str):
    return next(
        item for item in state.members if item.symbol == symbol and item.current_state == "TRACKED"
    )


def canonical_bars(
    symbol: str,
    *,
    end: datetime,
    missing: bool = False,
    state: str = "RECONCILED",
):
    bars = []
    for index in range(5):
        timestamp = end - timedelta(minutes=4 - index)
        if missing and index == 2:
            continue
        bars.append(
            CanonicalMinuteBar(
                symbol=symbol,
                timestamp=timestamp.isoformat(),
                open=100.0 + index,
                high=101.0 + index,
                low=99.5 + index,
                close=100.5 + index,
                volume=10_000.0 + index,
                source=SCHWAB_PRICE_HISTORY_SOURCE,
                state=state,
                session_date=SESSION,
            )
        )
    return tuple(bars)


def evidence(
    symbol: str,
    *,
    cutoff: datetime,
    missing: bool = False,
    state: str = "RECONCILED",
    corrupt: bool = False,
):
    end = cutoff - timedelta(minutes=1)
    bars = canonical_bars(symbol, end=end, missing=missing, state=state)
    if corrupt:
        bars = tuple(
            replace(bar, high=bar.low - 1.0) if index == 2 else bar
            for index, bar in enumerate(bars)
        )
    return CanonicalEvidenceInput(
        evidence_id=(
            f"canonical:{symbol}:{cutoff.isoformat()}:{missing}:{state}:{corrupt}"
        ),
        symbol=symbol,
        session_date=SESSION,
        provider_timestamp=cutoff.isoformat(),
        receipt_timestamp=cutoff.isoformat(),
        bars=bars,
        daily_evidence_id=f"daily:{symbol}",
        daily_evidence_fingerprint=DAILY,
        history_depth_sessions=7,
    )


def rvol(symbol: str, *, cutoff: datetime):
    return TimeNormalizedRvolEvidence(
        status=EXECUTION_ELIGIBLE,
        symbol=symbol,
        session_date=SESSION,
        through_minute=(cutoff - timedelta(minutes=1)).isoformat(),
        baseline_session_count=7,
        minimum_baseline_sessions=5,
        target_baseline_sessions=20,
        observed_volume=100_000,
        expected_volume=80_000.0,
        relative_volume=1.25,
    )


class Lifecycle:
    def __init__(self, root: Path, symbol: str, *, discovered_at: datetime) -> None:
        self.coordinator = CandidateLifecycleCoordinator(
            CandidateLifecycleStore(root / f"{symbol}.json"),
            policy=CandidateLifecyclePolicy(
                policy_version="synthetic-whole-day-lifecycle-v1",
                cooldown_seconds=0,
                hysteresis_profile="synthetic",
                minimum_delta_profile="synthetic",
            ),
        )
        discovered = self.coordinator.discover(
            symbol=symbol,
            session_date=SESSION,
            originating_evidence_family="CONTINUOUS_MONITOR",
            evidence_fingerprint=LIFECYCLE,
            source_identity="synthetic-whole-day-discovery",
            occurred_at=discovered_at,
            provider_timestamp=discovered_at - timedelta(seconds=1),
            receipt_timestamp=discovered_at,
            reason="Synthetic whole-day discovery.",
        )
        self.opportunity_id = discovered.snapshot.opportunity_id
        self.coordinator.transition(
            opportunity_id=self.opportunity_id,
            next_state="WATCHING",
            evidence_fingerprint="e" * 64,
            source_identity="synthetic-whole-day-canonical",
            occurred_at=discovered_at + timedelta(minutes=1),
            provider_timestamp=discovered_at + timedelta(minutes=1) - timedelta(seconds=1),
            receipt_timestamp=discovered_at + timedelta(minutes=1),
            reason="Synthetic monitoring admission.",
            material_delta_kind=MONITORING_ACTIVATED,
        )

    @property
    def snapshot(self):
        return self.coordinator.snapshot(self.opportunity_id)

    def opening_breakout(self, occurred_at: datetime) -> None:
        self.coordinator.transition(
            opportunity_id=self.opportunity_id,
            next_state=BREAKOUT_FORMING,
            evidence_fingerprint="f" * 64,
            source_identity="synthetic-whole-day-canonical",
            occurred_at=occurred_at,
            provider_timestamp=occurred_at - timedelta(seconds=1),
            receipt_timestamp=occurred_at,
            reason="Synthetic opening breakout.",
            material_delta_kind=SETUP_IDENTITY_CHANGED,
            setup_family=OPENING_BREAKOUT,
        )

    def apply_proposal(self, proposal) -> None:
        self.coordinator.transition(
            opportunity_id=proposal.opportunity_id,
            next_state=proposal.next_state,
            evidence_fingerprint=proposal.evidence_fingerprint,
            source_identity=proposal.source_identity,
            occurred_at=datetime.fromisoformat(proposal.occurred_at),
            provider_timestamp=datetime.fromisoformat(proposal.provider_timestamp),
            receipt_timestamp=datetime.fromisoformat(proposal.receipt_timestamp),
            reason=proposal.reason,
            material_delta_kind=proposal.material_delta_kind,
            setup_family=proposal.setup_family,
            create_new_setup=proposal.create_new_setup,
        )


def member_input(
    state,
    symbol: str,
    *,
    cutoff: datetime,
    lifecycle=None,
    missing: bool = False,
    bar_state: str = "RECONCILED",
    corrupt: bool = False,
    transition=None,
    successor=None,
    existing_plan=None,
):
    return CompositionMemberInput(
        universe_member_id=active_member(state, symbol).member_id,
        canonical_evidence=evidence(
            symbol,
            cutoff=cutoff,
            missing=missing,
            state=bar_state,
            corrupt=corrupt,
        ),
        rvol_evidence=rvol(symbol, cutoff=cutoff),
        lifecycle=lifecycle,
        lifecycle_transition=transition,
        successor_setup=successor,
        existing_plan=existing_plan,
    )


def successor(
    symbol: str,
    *,
    known_at: datetime,
    predecessor_setup_id: str = "",
    predecessor_terminal_state: str = "",
    family: str = CONTINUATION_BREAKOUT,
):
    return SuccessorSetupEvidence(
        evidence_id=f"successor:{symbol}:{known_at.isoformat()}",
        evidence_fingerprint=hashlib.sha256(
            f"successor:{symbol}:{known_at.isoformat()}".encode("ascii")
        ).hexdigest(),
        symbol=symbol,
        session_date=SESSION,
        setup_family=family,
        known_at=known_at.isoformat(),
        source_level_kind="SYNTHETIC_CHRONOLOGY_VALID_STRUCTURE",
        planned_entry=105.0,
        stop_price=103.0,
        target_prices=(107.0, 109.0),
        source_evidence_ids=(f"structure:{symbol}:{known_at.isoformat()}",),
        predecessor_setup_id=predecessor_setup_id,
        predecessor_terminal_state=predecessor_terminal_state,
        successor_reason="SYNTHETIC_WHOLE_DAY_SUCCESSOR",
    )


def compose(universe_result, *, cutoff: datetime, inputs=()):
    return compose_cycle(
        universe_state=universe_result.state,
        member_inputs=inputs,
        started_at=cutoff - timedelta(seconds=10),
        evidence_cutoff=cutoff,
        policy=ContinuousCompositionPolicy(),
    )


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("ascii"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class WholeDayFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.policy = HotUniversePolicy(
            maximum_tracked_symbols=40,
            maximum_hot_symbols=10,
            maximum_warm_symbols=0,
        )
        self.universe_path = root / "restart" / "hot-universe.json"
        self.denominator_root = root / "restart" / "denominator"
        self.results = []
        self.papers = []

    def build(self):
        universe_store = HotUniverseStore(self.universe_path)

        opening = discovery_snapshot(
            evaluated_at=ct(8, 35),
            count=30,
            qualified_ordinals=set(range(1, 31)),
            symbols={1: "AAA", 2: "CCC", 3: "EEE", 4: "FFF"},
        )
        opening_universe = universe_store.apply_snapshot(
            policy=self.policy, snapshot=opening
        )
        self.aaa = Lifecycle(self.root / "lifecycle", "AAA", discovered_at=et(9, 35))
        self.aaa.opening_breakout(et(9, 37))
        opening_setup_id = self.aaa.snapshot.current_setup_id
        opening_plan = build_intraday_plan_evidence(
            symbol="AAA",
            setup_family=OPENING_BREAKOUT,
            created_at=et(9, 37),
            planned_entry=100.0,
            stop_price=98.0,
            target_prices=(102.0, 104.0),
            source_setup_fingerprint="1" * 64,
            source_level_kind="SYNTHETIC_OPENING_STRUCTURE",
            source_evidence_ids=("synthetic-opening-bars",),
            lifecycle_status="PENDING_ENTRY",
        )
        ccc = Lifecycle(self.root / "lifecycle", "CCC", discovered_at=et(9, 35))
        eee = Lifecycle(self.root / "lifecycle", "EEE", discovered_at=et(9, 35))
        fff = Lifecycle(self.root / "lifecycle", "FFF", discovered_at=et(9, 35))
        opening_cutoff = et(9, 40)
        opening_cycle = compose(
            opening_universe,
            cutoff=opening_cutoff,
            inputs=(
                member_input(
                    opening_universe.state,
                    "AAA",
                    cutoff=opening_cutoff,
                    lifecycle=self.aaa.snapshot,
                    transition=LifecycleTransitionInput(
                        next_state=ENTRY_MISSED,
                        reason="TRIGGER_CROSSED_OUTSIDE_ENTRY_WINDOW",
                        evidence_fingerprint="2" * 64,
                        source_identity="synthetic-completed-opening-bar",
                    ),
                    existing_plan=opening_plan,
                ),
                member_input(
                    opening_universe.state,
                    "CCC",
                    cutoff=opening_cutoff,
                    lifecycle=ccc.snapshot,
                ),
                member_input(
                    opening_universe.state,
                    "EEE",
                    cutoff=opening_cutoff,
                    lifecycle=eee.snapshot,
                    missing=True,
                ),
                member_input(
                    opening_universe.state,
                    "FFF",
                    cutoff=opening_cutoff,
                    lifecycle=fff.snapshot,
                    corrupt=True,
                ),
            ),
        )
        opening_result = produce_continuous_denominator(
            discovery_snapshot=opening,
            universe_result=opening_universe,
            composition_cycle=opening_cycle,
        )
        self.results.append(opening_result)
        missed = next(
            item for item in opening_cycle.member_results if item.symbol == "AAA"
        )
        self.aaa.apply_proposal(missed.lifecycle_proposal)
        self.missed_plan = missed.intraday_plan
        self.opening_setup_id = opening_setup_id
        self.papers.append(
            build_synthetic_paper_supervision_observation(
                observed_at=et(9, 41).isoformat(),
                symbol="POS",
                lifecycle_state="POSITION_PROTECTED",
                position_evidence_fingerprint="3" * 64,
                protection_evidence_fingerprint="4" * 64,
            )
        )

        continuation = discovery_snapshot(
            evaluated_at=ct(9, 30),
            count=20,
            qualified_ordinals={1},
            symbols={1: "AAA"},
        )
        continuation_universe = universe_store.apply_snapshot(
            policy=self.policy, snapshot=continuation
        )
        continuation_cutoff = et(10, 35)
        continuation_cycle = compose(
            continuation_universe,
            cutoff=continuation_cutoff,
            inputs=(
                member_input(
                    continuation_universe.state,
                    "AAA",
                    cutoff=continuation_cutoff,
                    lifecycle=self.aaa.snapshot,
                    successor=successor(
                        "AAA",
                        known_at=et(10, 34),
                        predecessor_setup_id=opening_setup_id,
                        predecessor_terminal_state=ENTRY_MISSED,
                        family=PULLBACK,
                    ),
                    existing_plan=self.missed_plan,
                ),
            ),
        )
        continuation_result = produce_continuous_denominator(
            discovery_snapshot=continuation,
            universe_result=continuation_universe,
            composition_cycle=continuation_cycle,
        )
        self.results.append(continuation_result)

        denominator = ContinuousDenominatorStore(self.denominator_root)
        denominator.persist(continuation_result)
        before_tree = tree_hash(self.denominator_root)
        before_universe = continuation_universe.state.fingerprint
        restarted_universe = HotUniverseStore(self.universe_path).load()
        restarted_denominator = ContinuousDenominatorStore(self.denominator_root)
        self.assert_terminal = restarted_denominator.is_terminal(
            continuation_result.cycle.cycle_id
        )
        restarted_denominator.persist(continuation_result)
        after_tree = tree_hash(self.denominator_root)
        self.restart = build_restart_receipt(
            restarted_at=et(12, 0).isoformat(),
            preceding_cycle_id=continuation_result.cycle.cycle_id,
            universe_fingerprint_before=before_universe,
            universe_fingerprint_after=restarted_universe.fingerprint,
            denominator_cycle_id=continuation_result.cycle.cycle_id,
            denominator_fingerprint_before=continuation_result.cycle.fingerprint,
            denominator_fingerprint_after=continuation_result.cycle.fingerprint,
            duplicate_persist_byte_identical=before_tree == after_tree,
        )
        self.papers.append(
            build_synthetic_paper_supervision_observation(
                observed_at=et(12, 1).isoformat(),
                symbol="POS",
                lifecycle_state="POSITION_PROTECTED",
                position_evidence_fingerprint="5" * 64,
                protection_evidence_fingerprint="6" * 64,
            )
        )

        midday = discovery_snapshot(
            evaluated_at=ct(11, 5),
            count=65,
            qualified_ordinals={1, 45, 65},
            symbols={1: "AAA", 45: "DDD", 65: "BBB"},
        )
        midday_universe = HotUniverseStore(self.universe_path).apply_snapshot(
            policy=self.policy, snapshot=midday
        )
        bbb = Lifecycle(self.root / "lifecycle", "BBB", discovered_at=et(12, 6))
        ddd = Lifecycle(self.root / "lifecycle", "DDD", discovered_at=et(12, 6))
        midday_cutoff = et(12, 10)
        midday_cycle = compose(
            midday_universe,
            cutoff=midday_cutoff,
            inputs=(
                member_input(
                    midday_universe.state,
                    "BBB",
                    cutoff=midday_cutoff,
                    lifecycle=bbb.snapshot,
                    successor=successor("BBB", known_at=et(12, 9)),
                ),
                member_input(
                    midday_universe.state,
                    "DDD",
                    cutoff=midday_cutoff,
                    lifecycle=ddd.snapshot,
                    successor=successor("DDD", known_at=et(12, 9)),
                ),
            ),
        )
        midday_result = produce_continuous_denominator(
            discovery_snapshot=midday,
            universe_result=midday_universe,
            composition_cycle=midday_cycle,
        )
        self.results.append(midday_result)

        partial = discovery_snapshot(
            evaluated_at=ct(12, 5),
            count=100,
            qualified_ordinals={1},
            symbols={1: "ZZZ"},
            fail_page=2,
        )
        failure = build_discovery_failure_observation(
            source=partial.source,
            observed_at=partial.evaluated_at,
            session_date=partial.session_date,
            reason=partial.failure_reason or "",
            source_contract_fingerprint=partial.source_contract_fingerprint,
        )
        failed_universe = HotUniverseStore(self.universe_path).record_failure(
            policy=self.policy,
            failure=failure,
        )
        failed_cutoff = et(13, 10)
        failed_cycle = compose(
            failed_universe,
            cutoff=failed_cutoff,
            inputs=(
                member_input(
                    failed_universe.state,
                    "AAA",
                    cutoff=failed_cutoff,
                    lifecycle=self.aaa.snapshot,
                ),
            ),
        )
        failed_result = produce_continuous_denominator(
            discovery_snapshot=partial,
            universe_result=failed_universe,
            composition_cycle=failed_cycle,
        )
        self.results.append(failed_result)
        self.papers.append(
            build_synthetic_paper_supervision_observation(
                observed_at=et(13, 10).isoformat(),
                symbol="POS",
                lifecycle_state="POSITION_PROTECTED",
                position_evidence_fingerprint="7" * 64,
                protection_evidence_fingerprint="8" * 64,
            )
        )

        close = discovery_snapshot(
            evaluated_at=ct(14, 45),
            count=20,
            qualified_ordinals={1, 2, 3},
            symbols={1: "AAA", 2: "CCC", 3: "BBB"},
        )
        close_universe = HotUniverseStore(self.universe_path).apply_snapshot(
            policy=self.policy, snapshot=close
        )
        close_cutoff = et(15, 50)
        close_cycle = compose(close_universe, cutoff=close_cutoff)
        close_result = produce_continuous_denominator(
            discovery_snapshot=close,
            universe_result=close_universe,
            composition_cycle=close_cycle,
        )
        self.results.append(close_result)
        self.papers.append(
            build_synthetic_paper_supervision_observation(
                observed_at=et(15, 51).isoformat(),
                symbol="POS",
                lifecycle_state="POSITION_PROTECTED",
                position_evidence_fingerprint="9" * 64,
                protection_evidence_fingerprint="a" * 64,
            )
        )
        self.proof = build_continuous_day_proof(
            results=self.results,
            restart_receipt=self.restart,
            paper_supervision_observations=self.papers,
        )
        return self.proof


class ContinuousWholeDayAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = WholeDayFixture(self.root)
        self.proof = self.fixture.build()

    def test_complete_ugly_day_passes_all_twelve_checks(self) -> None:
        validate_continuous_day_proof(self.proof)
        self.assertEqual(PROOF_STATUS, self.proof.status)
        self.assertEqual(REQUIRED_CHECKS, self.proof.scenario_checks)
        self.assertIn(CHECK_CAPACITY, self.proof.scenario_checks)
        self.assertIn(CHECK_DISCOVERY_FAILURE, self.proof.scenario_checks)
        self.assertIn(CHECK_PAPER_LANE, self.proof.scenario_checks)

    def test_capacity_and_failure_counts_reconcile(self) -> None:
        opening = self.fixture.results[0]
        failure = self.fixture.results[3]
        self.assertEqual(20, opening.linkage.counts.universe_provider_bound)
        self.assertEqual(
            20,
            sum(
                item.disposition == NOT_EVALUATED_PROVIDER_BOUND
                for item in opening.opportunities
            ),
        )
        self.assertIn(INCOMPLETE_DISCOVERY_FAILURE, failure.linkage.incomplete_reasons)
        self.assertEqual(
            self.proof.metrics.opportunities,
            self.proof.metrics.unique_opportunities,
        )

    def test_readiness_and_corrupt_data_fail_independently(self) -> None:
        opening = self.fixture.results[0]
        eee = next(item for item in opening.linkage.members if item.symbol == "EEE")
        fff = next(item for item in opening.linkage.members if item.symbol == "FFF")
        self.assertEqual((DATA_FAILURE, GAPPED_EVIDENCE), (
            eee.composition_disposition,
            eee.readiness_status,
        ))
        self.assertEqual((DATA_FAILURE, DATA_UNSAFE), (
            fff.composition_disposition,
            fff.readiness_status,
        ))
        self.assertIn("CANONICAL_BAR_OHLC_INVALID", fff.blocker_reasons)

    def test_midday_and_later_page_candidates_have_no_opening_parent(self) -> None:
        midday = self.fixture.results[2]
        bbb = next(item for item in midday.linkage.members if item.symbol == "BBB")
        ddd = next(item for item in midday.linkage.members if item.symbol == "DDD")
        ddd_row = next(item for item in midday.linkage.source_rows if item.symbol == "DDD")
        self.assertEqual(RESEARCH_PLAN_COMPOSED, bbb.composition_disposition)
        self.assertIsNone(bbb.predecessor_setup_id)
        self.assertEqual(RESEARCH_PLAN_COMPOSED, ddd.composition_disposition)
        self.assertEqual(3, ddd_row.source_page_number)

    def test_restart_is_byte_identical_and_terminal(self) -> None:
        self.assertTrue(self.fixture.assert_terminal)
        self.assertTrue(self.fixture.restart.duplicate_persist_byte_identical)
        self.assertEqual(
            self.fixture.restart.universe_fingerprint_before,
            self.fixture.restart.universe_fingerprint_after,
        )

    def test_paper_supervision_is_synthetic_and_has_no_order_capability(self) -> None:
        self.assertEqual(4, len(self.proof.paper_supervision_observations))
        for item in self.proof.paper_supervision_observations:
            self.assertEqual(PAPER_LANE, item.lane)
            self.assertEqual("NONE", item.discovery_dependency)
            self.assertEqual(ORDER_CAPABILITY_UNAVAILABLE, item.order_capability)
            self.assertEqual(EXECUTION_AUTHORITY_NONE, item.execution_authority)

    def test_proof_is_deterministic_and_does_not_mutate_sources(self) -> None:
        before = json.dumps(
            [asdict(item) for item in self.fixture.results], sort_keys=True
        )
        duplicate = build_continuous_day_proof(
            results=self.fixture.results,
            restart_receipt=self.fixture.restart,
            paper_supervision_observations=self.fixture.papers,
        )
        after = json.dumps(
            [asdict(item) for item in self.fixture.results], sort_keys=True
        )
        self.assertEqual(self.proof, duplicate)
        self.assertEqual(before, after)

    def test_duplicate_cycle_fails_closed(self) -> None:
        with self.assertRaisesRegex(ContinuousDayProofError, "Duplicate continuous cycle"):
            build_continuous_day_proof(
                results=(*self.fixture.results, self.fixture.results[-1]),
                restart_receipt=self.fixture.restart,
                paper_supervision_observations=self.fixture.papers,
            )

    def test_changed_restart_or_proof_fingerprint_fails_closed(self) -> None:
        changed_restart = replace(
            self.fixture.restart,
            universe_fingerprint_after="0" * 64,
        )
        with self.assertRaisesRegex(ContinuousDayProofError, "fingerprint"):
            build_continuous_day_proof(
                results=self.fixture.results,
                restart_receipt=changed_restart,
                paper_supervision_observations=self.fixture.papers,
            )
        with self.assertRaisesRegex(ContinuousDayProofError, "fingerprint"):
            validate_continuous_day_proof(replace(self.proof, fingerprint="0" * 64))

    def test_module_has_no_network_broker_service_or_scheduler_import(self) -> None:
        source = Path("momentum_hunter/continuous_day_proof.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        forbidden = (
            "requests",
            "urllib",
            "httpx",
            "socket",
            "alpaca",
            "broker",
            "automation_service",
            "automation_supervisor",
            "subprocess",
        )
        self.assertFalse(any(any(token in item for token in forbidden) for item in imports))
        lowered = source.lower()
        for token in ("submit_order", "cancel_order", "replace_order", "query_account"):
            self.assertNotIn(token, lowered)


if __name__ == "__main__":
    unittest.main()
