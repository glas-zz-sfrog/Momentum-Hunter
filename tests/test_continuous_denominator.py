from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

from momentum_hunter.broad_discovery import (
    CROSS_PAGE_ATOMICITY_NOT_GUARANTEED,
    SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE,
    build_paginated_discovery_snapshot,
)
from momentum_hunter.candidate_lifecycle import ENTRY_MISSED
from momentum_hunter.continuous_composition import (
    BLOCKED_DATA as COMPOSITION_BLOCKED_DATA,
    DATA_FAILURE as COMPOSITION_DATA_FAILURE,
    MISSED_ENTRY_RECORDED,
    NO_LIFECYCLE_CHANGE,
    PROVIDER_BOUND,
    RESEARCH_PLAN_COMPOSED,
    WAITING_READINESS,
    CompositionMemberInput,
    ContinuousCompositionCycle,
    ContinuousCompositionPolicy,
    LifecycleTransitionInput,
    SuccessorSetupEvidence,
    _fingerprint as composition_fingerprint,
    _summary as composition_summary,
    compose_cycle,
)
from momentum_hunter.continuous_denominator import (
    CURRENTLY_OBSERVED,
    INCOMPLETE_COMPOSITION_SYSTEM_FAILURE,
    INCOMPLETE_DISCOVERY_FAILURE,
    INCOMPLETE_MISSING_COMPOSITION_RESULT,
    RETAINED_FROM_PRIOR_DISCOVERY,
    SOURCE_ROW_BLOCKED_DATA,
    ContinuousDenominatorError,
    ContinuousDenominatorStore,
    _fingerprint as denominator_fingerprint,
    produce_continuous_denominator,
    reference_continuous_denominator_policy,
    summarize_continuous_denominators,
    validate_continuous_denominator_result,
)
from momentum_hunter.hot_universe import (
    FAILURE_RECORDED,
    HotUniversePolicy,
    apply_discovery_snapshot,
    build_discovery_failure_observation,
    record_discovery_failure,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    PULLBACK,
    build_intraday_plan_evidence,
)
from momentum_hunter.opportunity_denominator import (
    BLOCKED_DATA,
    DATA_CONTRACT_FAILURE,
    EXECUTION_AUTHORITY_NONE,
    NO_ACTION_RESEARCH_ONLY,
    NOT_EVALUATED_PROVIDER_BOUND,
    OpportunityDenominatorError,
    REJECTED_STRATEGY,
    SAMPLE_IDENTITY,
    SAMPLE_STATUS,
    SYNTHETIC_TEST,
    LIVE_READ_ONLY_QUALIFICATION,
    SYSTEM_FAILURE,
)
from tests import test_continuous_composition as composition_fixture
from tests import test_discovery_pagination as discovery_fixture


def paginated_snapshot(
    count: int,
    qualified_ordinals: set[int],
    *,
    minute: int = 1,
    symbols: dict[int, str] | None = None,
    fail_page: int | None = None,
):
    symbols = symbols or {}
    page_count = max(1, (count + 19) // 20)
    policy = discovery_fixture.policy(
        max_pages=max(page_count, fail_page or 0),
        max_rows=max(20, count),
    )
    pages = []
    for page_number in range(1, page_count + 1):
        if fail_page == page_number:
            pages.append(
                discovery_fixture.page(
                    page_number,
                    [],
                    total=None,
                    failure=f"PAGE_{page_number}_PROVIDER_FAILURE",
                )
            )
            break
        start = 1 + ((page_number - 1) * 20)
        stop = min(count, start + 19)
        source_rows = [
            discovery_fixture.source_row(
                ordinal,
                symbols.get(ordinal, f"S{ordinal:04d}"),
                qualified=ordinal in qualified_ordinals,
            )
            for ordinal in range(start, stop + 1)
        ]
        pages.append(
            discovery_fixture.page(
                page_number,
                source_rows,
                total=count,
                terminal=page_number == page_count,
            )
        )
    return build_paginated_discovery_snapshot(
        source="finviz",
        source_version="synthetic-stat-data-002-v1",
        evaluated_at=discovery_fixture.BASE + timedelta(minutes=minute),
        query_identity=discovery_fixture.query(policy),
        pagination_policy=policy,
        page_inputs=pages,
    )


def universe_result(snapshot, *, state=None, policy=None):
    policy = policy or HotUniversePolicy()
    return apply_discovery_snapshot(state, policy=policy, snapshot=snapshot)


def composition_cycle(result, *, inputs=(), started=None, cutoff=None):
    return compose_cycle(
        universe_state=result.state,
        member_inputs=inputs,
        started_at=started or composition_fixture.at(11, 21, 50),
        evidence_cutoff=cutoff or composition_fixture.at(11, 22),
        policy=ContinuousCompositionPolicy(),
    )


def active_member(state, symbol: str):
    return next(
        item
        for item in state.members
        if item.symbol == symbol and item.current_state == "TRACKED"
    )


def member_input(state, symbol: str, *, lifecycle=None, evidence=None, volume=None, transition=None, successor=None, plan=None):
    return CompositionMemberInput(
        universe_member_id=active_member(state, symbol).member_id,
        lifecycle=lifecycle,
        canonical_evidence=evidence,
        rvol_evidence=volume,
        lifecycle_transition=transition,
        successor_setup=successor,
        existing_plan=plan,
    )


def ready_member_input(state, symbol: str, lifecycle):
    return member_input(
        state,
        symbol,
        lifecycle=lifecycle,
        evidence=composition_fixture.evidence(symbol),
        volume=composition_fixture.rvol(symbol),
    )


def successor(symbol: str, *, predecessor: str = "", terminal: str = "", known=None):
    return SuccessorSetupEvidence(
        evidence_id=f"successor-{symbol}-pullback",
        evidence_fingerprint="2" * 64,
        symbol=symbol,
        session_date="2026-08-17",
        setup_family=PULLBACK if predecessor else CONTINUATION_BREAKOUT,
        known_at=(known or composition_fixture.at(11, 21)).isoformat(),
        source_level_kind="TEST_ONLY_CHRONOLOGY_VALID_STRUCTURE",
        planned_entry=105.0,
        stop_price=103.0,
        target_prices=(107.0, 109.0),
        source_evidence_ids=(f"structure-{symbol}",),
        predecessor_setup_id=predecessor,
        predecessor_terminal_state=terminal,
        successor_reason="TEST_ONLY_SUCCESSOR_STRUCTURE",
    )


def incomplete_composition(cycle: ContinuousCompositionCycle, *, remove_member_id: str):
    results = tuple(
        item for item in cycle.member_results if item.universe_member_id != remove_member_id
    )
    summary = composition_summary(results)
    payload = {
        "session_date": cycle.session_date,
        "started_at": cycle.started_at,
        "evidence_cutoff": cycle.evidence_cutoff,
        "universe_policy_fingerprint": cycle.universe_policy_fingerprint,
        "composition_policy_fingerprint": cycle.composition_policy_fingerprint,
        "member_results": results,
        "summary": summary,
        "shared_failure_state": "COMPOSITION_INTERRUPTED",
    }
    fingerprint = composition_fingerprint(
        {
            **payload,
            "member_results": [asdict(item) for item in results],
            "summary": asdict(summary),
        }
    )
    return ContinuousCompositionCycle(
        cycle_id=f"continuous-composition-{fingerprint[:24]}",
        fingerprint=fingerprint,
        **payload,
    )


class ContinuousDenominatorWholeCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_twenty_rows_two_qualified_are_fully_reconciled(self) -> None:
        snapshot = paginated_snapshot(20, {1, 2}, symbols={1: "AAA", 2: "BBB"})
        universe = universe_result(snapshot)
        life = composition_fixture.LifecycleFixture(self.root, "AAA")
        cycle = composition_cycle(
            universe,
            inputs=(ready_member_input(universe.state, "AAA", life.snapshot),),
        )

        result = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=cycle,
        )

        counts = result.linkage.counts
        self.assertTrue(result.cycle.complete_denominator)
        self.assertEqual((20, 20, 20), (
            counts.discovery_raw_rows,
            counts.discovery_parsed_rows,
            counts.discovery_represented_rows,
        ))
        self.assertEqual((2, 18), (counts.discovery_qualified, counts.discovery_rejected))
        self.assertEqual(20, len(result.opportunities))
        self.assertEqual(18, sum(item.disposition == REJECTED_STRATEGY for item in result.opportunities))
        self.assertEqual(1, counts.composition_waiting)
        self.assertEqual(1, counts.composition_no_change)
        self.assertEqual({WAITING_READINESS, NO_LIFECYCLE_CHANGE}, {
            item.composition_disposition for item in result.linkage.members
        })

    def test_hundred_rows_over_five_pages_preserve_every_coordinate(self) -> None:
        snapshot = paginated_snapshot(100, {1, 17, 34, 51, 68, 85, 100})
        universe = universe_result(snapshot)
        result = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=composition_cycle(universe),
        )

        self.assertTrue(result.cycle.complete_denominator)
        self.assertEqual(100, len(result.linkage.source_rows))
        self.assertEqual({1, 2, 3, 4, 5}, {
            item.source_page_number for item in result.linkage.source_rows
        })
        self.assertEqual(CROSS_PAGE_ATOMICITY_NOT_GUARANTEED, result.linkage.cross_page_atomicity)
        self.assertEqual(snapshot.coverage_state, result.linkage.coverage_state)
        self.assertEqual(snapshot.query_fingerprint, result.linkage.discovery_query_fingerprint)

    def test_page_four_midday_candidate_has_no_opening_parent(self) -> None:
        snapshot = paginated_snapshot(
            100,
            {65},
            minute=15,
            symbols={65: "BBB"},
        )
        universe = universe_result(snapshot)
        life = composition_fixture.LifecycleFixture(self.root, "BBB")
        item = ready_member_input(universe.state, "BBB", life.snapshot)
        item = replace(item, successor_setup=successor("BBB"))
        cycle = composition_cycle(universe, inputs=(item,))
        result = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=cycle,
        )

        bbb_row = next(item for item in result.linkage.source_rows if item.symbol == "BBB")
        bbb_member = next(item for item in result.linkage.members if item.symbol == "BBB")
        bbb_opportunity = next(
            item for item in result.opportunities if item.symbol == "BBB"
        )
        self.assertEqual(4, bbb_row.source_page_number)
        self.assertEqual(65, bbb_row.global_observation_ordinal)
        self.assertEqual(RESEARCH_PLAN_COMPOSED, bbb_member.composition_disposition)
        self.assertIsNone(bbb_member.predecessor_setup_id)
        self.assertTrue(bbb_member.setup_id)
        self.assertEqual(bbb_member.setup_id, bbb_opportunity.setup_id)
        self.assertNotIn("08:35", json.dumps(asdict(result.linkage)))

    def test_scanner_disappearance_retains_member_without_current_row(self) -> None:
        policy = HotUniversePolicy()
        first_snapshot = composition_fixture.discovery_snapshot(["CCC"], minute=0)
        first = universe_result(first_snapshot, policy=policy)
        current_snapshot = composition_fixture.discovery_snapshot(["AAA"], minute=5)
        current = universe_result(current_snapshot, state=first.state, policy=policy)
        cycle = composition_cycle(current)

        result = produce_continuous_denominator(
            discovery_snapshot=current_snapshot,
            universe_result=current,
            composition_cycle=cycle,
        )

        ccc = next(item for item in result.linkage.members if item.symbol == "CCC")
        self.assertEqual(RETAINED_FROM_PRIOR_DISCOVERY, ccc.source_relationship)
        self.assertEqual((), ccc.current_source_row_ids)
        self.assertEqual(first_snapshot.snapshot_id, ccc.first_discovery_snapshot_id)
        self.assertEqual(1, result.linkage.counts.retained_prior_members_presented)
        self.assertEqual(2, len(result.opportunities))

    def test_thirty_for_ten_keeps_twenty_provider_bound_members(self) -> None:
        snapshot = paginated_snapshot(30, set(range(1, 31)))
        policy = HotUniversePolicy(
            maximum_tracked_symbols=30,
            maximum_hot_symbols=10,
            maximum_warm_symbols=0,
        )
        universe = universe_result(snapshot, policy=policy)
        cycle = composition_cycle(universe)
        result = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=cycle,
        )

        self.assertEqual(30, len(result.opportunities))
        self.assertEqual(20, result.linkage.counts.universe_provider_bound)
        self.assertEqual(20, sum(
            item.disposition == NOT_EVALUATED_PROVIDER_BOUND
            for item in result.opportunities
        ))
        self.assertEqual(20, sum(
            item.composition_disposition == PROVIDER_BOUND
            for item in result.linkage.members
        ))

    def test_discovery_failure_preserves_partial_rows_and_retained_evaluations(self) -> None:
        policy = HotUniversePolicy()
        prior_snapshot = composition_fixture.discovery_snapshot(["AAA", "BBB"], minute=0)
        prior = universe_result(prior_snapshot, policy=policy)
        partial = paginated_snapshot(100, {1, 2}, minute=6, fail_page=2)
        self.assertEqual(SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE, partial.status)
        failure = build_discovery_failure_observation(
            source=partial.source,
            observed_at=partial.evaluated_at,
            session_date=partial.session_date,
            reason=partial.failure_reason or "",
            source_contract_fingerprint=partial.source_contract_fingerprint,
        )
        failed = record_discovery_failure(prior.state, policy=policy, failure=failure)
        self.assertEqual(FAILURE_RECORDED, failed.status)
        lives = {
            symbol: composition_fixture.LifecycleFixture(self.root, symbol)
            for symbol in ("AAA", "BBB")
        }
        inputs = tuple(
            ready_member_input(failed.state, symbol, lives[symbol].snapshot)
            for symbol in ("AAA", "BBB")
        )
        cycle = composition_cycle(failed, inputs=inputs)

        result = produce_continuous_denominator(
            discovery_snapshot=partial,
            universe_result=failed,
            composition_cycle=cycle,
        )

        self.assertFalse(result.cycle.complete_denominator)
        self.assertEqual(DATA_CONTRACT_FAILURE, result.cycle.failure_reason)
        self.assertIn(INCOMPLETE_DISCOVERY_FAILURE, result.linkage.incomplete_reasons)
        self.assertEqual(20, len(result.linkage.source_rows))
        self.assertTrue(all(item.treatment == SOURCE_ROW_BLOCKED_DATA for item in result.linkage.source_rows))
        self.assertEqual(2, result.linkage.counts.retained_prior_members_presented)
        self.assertEqual(22, len(result.opportunities))
        self.assertEqual(0, sum(
            item.consecutive_absent_observations
            for item in failed.state.members
        ))

    def test_gapped_readiness_is_data_block_not_strategy_reject(self) -> None:
        snapshot = paginated_snapshot(20, {1}, symbols={1: "AAA"})
        universe = universe_result(snapshot)
        life = composition_fixture.LifecycleFixture(self.root, "AAA")
        item = member_input(
            universe.state,
            "AAA",
            lifecycle=life.snapshot,
            evidence=composition_fixture.evidence(
                "AAA",
                bars=composition_fixture.canonical_bars("AAA", missing=True),
            ),
            volume=composition_fixture.rvol("AAA"),
        )
        cycle = composition_cycle(universe, inputs=(item,))
        self.assertEqual(COMPOSITION_DATA_FAILURE, cycle.member_results[0].disposition)

        result = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=cycle,
        )
        aaa = next(item for item in result.opportunities if item.symbol == "AAA")
        self.assertEqual(BLOCKED_DATA, aaa.disposition)
        self.assertNotEqual(REJECTED_STRATEGY, aaa.disposition)
        self.assertNotIn("NO_TRADE", json.dumps(asdict(aaa)))

    def test_missed_entry_and_successor_keep_distinct_immutable_identity(self) -> None:
        snapshot = paginated_snapshot(20, {1}, symbols={1: "AAA"})
        universe = universe_result(snapshot)
        life = composition_fixture.LifecycleFixture(self.root, "AAA")
        life.opening_breakout()
        original = life.snapshot
        original_plan = build_intraday_plan_evidence(
            symbol="AAA",
            setup_family=CONTINUATION_BREAKOUT,
            created_at=composition_fixture.at(11, 3),
            planned_entry=100.0,
            stop_price=98.0,
            target_prices=(102.0, 104.0),
            source_setup_fingerprint="3" * 64,
            source_level_kind="TEST_ONLY_OPENING_STRUCTURE",
            source_evidence_ids=("opening-bars",),
            lifecycle_status="PENDING_ENTRY",
        )
        missed_input = ready_member_input(universe.state, "AAA", original)
        missed_input = replace(
            missed_input,
            existing_plan=original_plan,
            lifecycle_transition=LifecycleTransitionInput(
                next_state=ENTRY_MISSED,
                reason="TRIGGER_CROSSED_OUTSIDE_ENTRY_WINDOW",
                evidence_fingerprint="4" * 64,
                source_identity="test-only-canonical-bar",
            ),
        )
        missed_cycle = composition_cycle(universe, inputs=(missed_input,))
        missed_result = missed_cycle.member_results[0]
        self.assertEqual(MISSED_ENTRY_RECORDED, missed_result.disposition)
        first = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=missed_cycle,
        )
        life.apply_proposal(missed_result.lifecycle_proposal)

        later_evidence = composition_fixture.evidence(
            "AAA",
            bars=composition_fixture.canonical_bars(
                "AAA", end=composition_fixture.at(11, 24)
            ),
            receipt=composition_fixture.at(11, 25),
        )
        next_input = member_input(
            universe.state,
            "AAA",
            lifecycle=life.snapshot,
            evidence=later_evidence,
            volume=composition_fixture.rvol(
                "AAA", through=composition_fixture.at(11, 24)
            ),
            successor=successor(
                "AAA",
                predecessor=original.current_setup_id,
                terminal=ENTRY_MISSED,
                known=composition_fixture.at(11, 24),
            ),
            plan=missed_result.intraday_plan,
        )
        next_cycle = composition_cycle(
            universe,
            inputs=(next_input,),
            started=composition_fixture.at(11, 24, 50),
            cutoff=composition_fixture.at(11, 25),
        )
        self.assertEqual(RESEARCH_PLAN_COMPOSED, next_cycle.member_results[0].disposition)
        second = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=next_cycle,
        )

        old = next(item for item in first.opportunities if item.symbol == "AAA")
        new = next(item for item in second.opportunities if item.symbol == "AAA")
        member = next(item for item in second.linkage.members if item.symbol == "AAA")
        self.assertNotEqual(old.opportunity_id, new.opportunity_id)
        self.assertNotEqual(old.setup_id, new.setup_id)
        self.assertEqual(original.current_setup_id, member.predecessor_setup_id)
        self.assertEqual(missed_result.intraday_plan.plan_id, next_cycle.member_results[0].intraday_plan.predecessor_plan_id)

    def test_partial_pagination_cannot_be_complete_or_normal(self) -> None:
        prior_snapshot = composition_fixture.discovery_snapshot(["AAA"], minute=0)
        policy = HotUniversePolicy()
        prior = universe_result(prior_snapshot, policy=policy)
        partial = paginated_snapshot(100, {1}, minute=7, fail_page=3)
        failure = build_discovery_failure_observation(
            source=partial.source,
            observed_at=partial.evaluated_at,
            session_date=partial.session_date,
            reason=partial.failure_reason or "",
            source_contract_fingerprint=partial.source_contract_fingerprint,
        )
        failed = record_discovery_failure(prior.state, policy=policy, failure=failure)
        result = produce_continuous_denominator(
            discovery_snapshot=partial,
            universe_result=failed,
            composition_cycle=composition_cycle(failed),
        )

        self.assertFalse(result.linkage.complete_denominator)
        self.assertIn(INCOMPLETE_DISCOVERY_FAILURE, result.linkage.incomplete_reasons)
        self.assertEqual(partial.coverage_state, result.linkage.coverage_state)
        self.assertTrue(all(
            item.disposition == BLOCKED_DATA
            for item in result.opportunities
            if item.origin_record_id in {row.row_id for row in partial.rows}
        ))

    def test_partial_composition_is_system_failure_and_incomplete(self) -> None:
        snapshot = paginated_snapshot(20, {1, 2}, symbols={1: "AAA", 2: "BBB"})
        universe = universe_result(snapshot)
        complete = composition_cycle(universe)
        missing_id = active_member(universe.state, "BBB").member_id
        partial = incomplete_composition(complete, remove_member_id=missing_id)

        result = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=partial,
        )

        self.assertFalse(result.cycle.complete_denominator)
        self.assertEqual(SYSTEM_FAILURE, result.cycle.failure_reason)
        self.assertIn(INCOMPLETE_MISSING_COMPOSITION_RESULT, result.linkage.incomplete_reasons)
        self.assertIn(INCOMPLETE_COMPOSITION_SYSTEM_FAILURE, result.linkage.incomplete_reasons)
        bbb = next(item for item in result.opportunities if item.symbol == "BBB")
        self.assertEqual(SYSTEM_FAILURE, bbb.disposition)

    def test_zero_qualified_is_complete_not_system_failure(self) -> None:
        snapshot = paginated_snapshot(20, set())
        universe = universe_result(snapshot)
        result = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=composition_cycle(universe),
        )

        self.assertTrue(result.cycle.complete_denominator)
        self.assertIsNone(result.cycle.failure_reason)
        self.assertEqual(0, result.linkage.counts.universe_admitted)
        self.assertEqual(20, len(result.opportunities))
        self.assertTrue(all(item.disposition == REJECTED_STRATEGY for item in result.opportunities))


class ContinuousDenominatorPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        snapshot = paginated_snapshot(20, {1}, symbols={1: "AAA"})
        universe = universe_result(snapshot)
        self.result = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=composition_cycle(universe),
        )

    def test_duplicate_persist_is_idempotent_and_restart_is_terminal(self) -> None:
        store = ContinuousDenominatorStore(self.root)
        store.persist(self.result)
        before = {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*.json")
        }
        store.persist(self.result)
        restarted = ContinuousDenominatorStore(self.root)
        self.assertTrue(restarted.is_terminal(self.result.cycle.cycle_id))
        after = {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*.json")
        }
        self.assertEqual(before, after)

    def test_authoritative_cycle_without_linkage_is_not_terminal_then_recovers(self) -> None:
        store = ContinuousDenominatorStore(self.root)
        store.denominator.persist_cycle(self.result.cycle, self.result.opportunities)
        self.assertFalse(store.is_terminal(self.result.cycle.cycle_id))
        ContinuousDenominatorStore(self.root).persist(self.result)
        self.assertTrue(ContinuousDenominatorStore(self.root).is_terminal(self.result.cycle.cycle_id))

    def test_tampered_linkage_fails_closed(self) -> None:
        store = ContinuousDenominatorStore(self.root)
        store.persist(self.result)
        path = store._path(self.result.cycle.cycle_id)
        payload = json.loads(path.read_text(encoding="ascii"))
        payload["payload"]["coverage_state"] = "TAMPERED"
        path.write_text(json.dumps(payload), encoding="ascii")
        with self.assertRaisesRegex(ContinuousDenominatorError, "fingerprint"):
            ContinuousDenominatorStore(self.root).read_linkage(self.result.cycle.cycle_id)

    def test_linkage_without_authoritative_opportunity_is_not_terminal(self) -> None:
        store = ContinuousDenominatorStore(self.root)
        store.persist(self.result)
        missing = self.result.opportunities[0]
        store.denominator._path("opportunities", missing.opportunity_id).unlink()
        with self.assertRaises(OpportunityDenominatorError):
            ContinuousDenominatorStore(self.root).is_terminal(self.result.cycle.cycle_id)

    def test_conflicting_same_cycle_linkage_fails_closed(self) -> None:
        store = ContinuousDenominatorStore(self.root)
        store.persist(self.result)
        payload = asdict(self.result.linkage)
        payload["coverage_state"] = "CONFLICTING_TEST_VALUE"
        payload.pop("fingerprint")
        changed = replace(
            self.result.linkage,
            coverage_state="CONFLICTING_TEST_VALUE",
            fingerprint=denominator_fingerprint(
                "continuous-denominator-linkage-v1", payload
            ),
        )
        with self.assertRaisesRegex(ContinuousDenominatorError, "Conflicting"):
            store.persist(replace(self.result, linkage=changed))

    def test_two_cycles_and_replay_preserve_prior_identities(self) -> None:
        store = ContinuousDenominatorStore(self.root)
        store.persist(self.result)
        first_files = {
            path.relative_to(self.root): path.read_bytes()
            for path in self.root.rglob("*.json")
        }
        snapshot = paginated_snapshot(20, {1}, minute=10, symbols={1: "AAA"})
        universe = universe_result(snapshot)
        later = produce_continuous_denominator(
            discovery_snapshot=snapshot,
            universe_result=universe,
            composition_cycle=composition_cycle(universe),
        )
        self.assertNotEqual(self.result.cycle.cycle_id, later.cycle.cycle_id)
        store.persist(later)
        ContinuousDenominatorStore(self.root).persist(later)
        for relative, content in first_files.items():
            self.assertEqual(content, (self.root / relative).read_bytes())


class ContinuousDenominatorNegativeAndIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.snapshot = paginated_snapshot(20, {1}, symbols={1: "AAA"})
        self.universe = universe_result(self.snapshot)
        self.cycle = composition_cycle(self.universe)

    def produce(self, **changes):
        values = {
            "discovery_snapshot": self.snapshot,
            "universe_result": self.universe,
            "composition_cycle": self.cycle,
        }
        values.update(changes)
        return produce_continuous_denominator(**values)

    def test_source_inputs_are_not_mutated_and_result_is_deterministic(self) -> None:
        before_snapshot = self.snapshot.to_dict()
        before_state = asdict(self.universe.state)
        before_cycle = asdict(self.cycle)
        first = self.produce()
        second = self.produce()
        self.assertEqual(first, second)
        self.assertEqual(before_snapshot, self.snapshot.to_dict())
        self.assertEqual(before_state, asdict(self.universe.state))
        self.assertEqual(before_cycle, asdict(self.cycle))

    def test_wrong_discovery_fingerprint_and_query_identity_fail_closed(self) -> None:
        with self.assertRaisesRegex(ContinuousDenominatorError, "invalid or tampered"):
            self.produce(discovery_snapshot=replace(self.snapshot, fingerprint="0" * 64))
        with self.assertRaisesRegex(ContinuousDenominatorError, "invalid or tampered"):
            self.produce(discovery_snapshot=replace(self.snapshot, query_fingerprint="0" * 64))

    def test_wrong_universe_policy_fingerprint_fails_closed(self) -> None:
        different = universe_result(
            self.snapshot,
            policy=HotUniversePolicy(maximum_hot_symbols=9, maximum_warm_symbols=21),
        )
        with self.assertRaisesRegex(ContinuousDenominatorError, "Universe policy fingerprint mismatch"):
            self.produce(universe_result=different)

    def test_universe_latest_receipt_must_match_exact_discovery_pulse(self) -> None:
        later_snapshot = paginated_snapshot(20, {1}, minute=10, symbols={1: "AAA"})
        later_universe = universe_result(later_snapshot, state=self.universe.state)
        later_cycle = composition_cycle(later_universe)
        with self.assertRaisesRegex(ContinuousDenominatorError, "latest receipt"):
            produce_continuous_denominator(
                discovery_snapshot=self.snapshot,
                universe_result=later_universe,
                composition_cycle=later_cycle,
            )

    def test_unknown_or_tampered_composition_member_fails_closed(self) -> None:
        item = self.cycle.member_results[0]
        tampered_item = replace(item, universe_member_id="unknown-member")
        tampered_cycle = replace(self.cycle, member_results=(tampered_item,))
        with self.assertRaisesRegex(ContinuousDenominatorError, "fingerprint"):
            self.produce(composition_cycle=tampered_cycle)

    def test_missing_member_result_is_never_silently_complete(self) -> None:
        missing = incomplete_composition(
            self.cycle,
            remove_member_id=self.cycle.member_results[0].universe_member_id,
        )
        result = self.produce(composition_cycle=missing)
        self.assertFalse(result.cycle.complete_denominator)
        self.assertEqual(SYSTEM_FAILURE, result.cycle.failure_reason)

    def test_omitted_reject_cannot_be_hidden_by_rewriting_counts(self) -> None:
        result = self.produce()
        omitted = result.linkage.source_rows[-1]
        source_rows = result.linkage.source_rows[:-1]
        counts = replace(
            result.linkage.counts,
            discovery_represented_rows=result.linkage.counts.discovery_represented_rows - 1,
            discovery_rejected=result.linkage.counts.discovery_rejected - 1,
            denominator_source_row_dispositions=(
                result.linkage.counts.denominator_source_row_dispositions - 1
            ),
        )
        values = asdict(result.linkage)
        values["source_rows"] = source_rows
        values["counts"] = counts
        values.pop("fingerprint")
        changed = replace(
            result.linkage,
            source_rows=source_rows,
            counts=counts,
            fingerprint=denominator_fingerprint(
                "continuous-denominator-linkage-v1", values
            ),
        )
        self.assertTrue(omitted.opportunity_id)
        with self.assertRaisesRegex(ContinuousDenominatorError, "every opportunity"):
            validate_continuous_denominator_result(replace(result, linkage=changed))

    def test_failed_discovery_requires_exact_failure_receipt(self) -> None:
        partial = paginated_snapshot(100, {1}, minute=7, fail_page=2)
        failure = build_discovery_failure_observation(
            source=partial.source,
            observed_at=partial.evaluated_at + timedelta(seconds=1),
            session_date=partial.session_date,
            reason=partial.failure_reason or "",
            source_contract_fingerprint=partial.source_contract_fingerprint,
        )
        failed = record_discovery_failure(
            self.universe.state,
            policy=HotUniversePolicy(),
            failure=failure,
        )
        with self.assertRaisesRegex(ContinuousDenominatorError, "explicit"):
            produce_continuous_denominator(
                discovery_snapshot=partial,
                universe_result=failed,
                composition_cycle=composition_cycle(failed),
            )

    def test_chronology_reversal_and_future_member_fail_closed(self) -> None:
        early_cycle = composition_cycle(
            self.universe,
            started=composition_fixture.at(10, 59),
            cutoff=composition_fixture.at(11, 0),
        )
        with self.assertRaisesRegex(ContinuousDenominatorError, "before discovery"):
            self.produce(composition_cycle=early_cycle)

    def test_only_nonprospective_inactive_modes_are_admitted(self) -> None:
        with self.assertRaisesRegex(ContinuousDenominatorError, "synthetic or isolated"):
            produce_continuous_denominator(
                discovery_snapshot=self.snapshot,
                universe_result=self.universe,
                composition_cycle=self.cycle,
                observation_mode="PROSPECTIVE",
            )
        policy = reference_continuous_denominator_policy()
        result = self.produce()
        self.assertEqual(SAMPLE_IDENTITY, result.cycle.sample_identity)
        self.assertEqual(SAMPLE_STATUS, result.linkage.sample_status)
        self.assertEqual(SYNTHETIC_TEST, result.cycle.observation_mode)
        self.assertEqual(EXECUTION_AUTHORITY_NONE, result.linkage.execution_authority)
        self.assertEqual(policy.fingerprint, result.linkage.producer_policy_fingerprint)

        qualification = produce_continuous_denominator(
            discovery_snapshot=self.snapshot,
            universe_result=self.universe,
            composition_cycle=self.cycle,
            observation_mode=LIVE_READ_ONLY_QUALIFICATION,
        )
        self.assertEqual(
            LIVE_READ_ONLY_QUALIFICATION,
            qualification.cycle.observation_mode,
        )
        self.assertEqual(
            EXECUTION_AUTHORITY_NONE,
            qualification.cycle.execution_authority,
        )

    def test_no_specialist_attachment_outcome_or_profitability_is_generated(self) -> None:
        result = self.produce()
        wire = json.dumps(asdict(result), sort_keys=True)
        self.assertTrue(all(
            item.nominating_specialist_id is None
            and item.nomination_opinion_fingerprint is None
            for item in result.opportunities
        ))
        for forbidden in ("mfe", "mae", "profit", "target_first", "stop_first", "filled_quantity"):
            self.assertNotIn(forbidden, wire.lower())
        store = ContinuousDenominatorStore(self.root)
        store.persist(result)
        folders = {path.parent.name for path in self.root.rglob("*.json")}
        self.assertNotIn("specialist-attachments", folders)
        self.assertNotIn("outcomes", folders)

    def test_summary_metrics_exclude_profitability_and_reconcile(self) -> None:
        complete = self.produce()
        partial_cycle = incomplete_composition(
            self.cycle,
            remove_member_id=self.cycle.member_results[0].universe_member_id,
        )
        incomplete = self.produce(composition_cycle=partial_cycle)
        summary = summarize_continuous_denominators((complete, incomplete))
        self.assertEqual((2, 1, 1), (
            summary.cycles_produced,
            summary.complete_cycles,
            summary.incomplete_cycles,
        ))
        self.assertEqual(40, summary.source_rows_represented)
        self.assertEqual(38, summary.source_rows_rejected)
        self.assertEqual(1, summary.system_failures)
        self.assertFalse(any(
            token in name.lower()
            for name in summary.__dataclass_fields__
            for token in ("profit", "win", "mfe", "mae")
        ))

    def test_module_has_no_runtime_provider_broker_service_or_ui_capability(self) -> None:
        source_path = Path(__file__).parents[1] / "momentum_hunter" / "continuous_denominator.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
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
        forbidden_import_tokens = (
            "providers",
            "schwab",
            "alpaca",
            "broker",
            "account",
            "automation",
            "service",
            "scheduler",
            "wpf",
            "requests",
            "urllib",
            "httpx",
        )
        self.assertFalse(any(
            token in module.lower()
            for module in imports
            for token in forbidden_import_tokens
        ), imports)


if __name__ == "__main__":
    unittest.main()
