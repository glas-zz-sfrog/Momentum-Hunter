from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

from momentum_hunter.candidate_lifecycle import ENTRY_MISSED
from momentum_hunter.continuous_composition import (
    LifecycleTransitionInput,
)
from momentum_hunter.continuous_denominator import (
    produce_continuous_denominator,
    reference_continuous_denominator_policy,
)
from momentum_hunter.continuous_live_qualification import (
    LiveDenominatorSource,
    QualificationState,
)
from momentum_hunter.continuous_runtime import DenominatorRequest
from momentum_hunter.hot_universe import HotUniversePolicy
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    build_intraday_plan_evidence,
)
from momentum_hunter.opportunity_denominator import (
    COUNTERFACTUAL_RESEARCH_OBSERVATION,
    PROSPECTIVE,
    MarketPathBar,
    OpportunityDenominatorError,
    build_market_path_outcome,
)
from momentum_hunter.prospective_denominator import (
    COMPOSITION,
    DISCOVERED,
    HISTORICAL_CONTEXT_ONLY,
    HOT_UNIVERSE,
    NO_PLAN,
    PROVIDER_BOUND,
    READY,
    SUCCESSOR_SETUP,
    TRADEPLAN,
    ProspectiveDenominatorError,
    ProspectiveDenominatorStore,
    build_activation_record,
)
from tests import test_continuous_composition as composition_fixture
from tests.test_continuous_denominator import (
    composition_cycle,
    member_input,
    paginated_snapshot,
    ready_member_input,
    successor,
    universe_result,
)


def active_result(snapshot, universe, cycle, activation):
    return produce_continuous_denominator(
        discovery_snapshot=snapshot,
        universe_result=universe,
        composition_cycle=cycle,
        observation_mode=PROSPECTIVE,
        policy=activation.producer_policy,
        denominator_policy=activation.policy,
    )


class ProspectiveDenominatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.activation = build_activation_record(
            activated_at="2026-08-17T09:00:00-04:00",
            first_eligible_session_date="2026-08-17",
            source_git_sha="1" * 40,
            configuration_fingerprint="2" * 64,
        )

    def basic_result(self, *, minute: int = 1):
        snapshot = paginated_snapshot(
            20,
            {1, 2},
            minute=minute,
            symbols={1: "AAA", 2: "BBB"},
        )
        universe = universe_result(snapshot)
        life = composition_fixture.LifecycleFixture(self.root / f"life-{minute}", "AAA")
        cycle = composition_cycle(
            universe,
            inputs=(ready_member_input(universe.state, "AAA", life.snapshot),),
            started=composition_fixture.at(11, 20 + minute, 50),
            cutoff=composition_fixture.at(11, 21 + minute),
        )
        return active_result(snapshot, universe, cycle, self.activation)

    def planned_result(self):
        snapshot = paginated_snapshot(1, {1}, symbols={1: "AAA"})
        universe = universe_result(snapshot)
        life = composition_fixture.LifecycleFixture(self.root / "planned", "AAA")
        item = ready_member_input(universe.state, "AAA", life.snapshot)
        item = replace(item, successor_setup=successor("AAA"))
        cycle = composition_cycle(universe, inputs=(item,))
        return active_result(snapshot, universe, cycle, self.activation)

    def test_activation_precedes_membership_and_historical_session_is_rejected(self) -> None:
        self.assertEqual(
            "b6e5c76734c3219212e8e74e437e6a49fa84ad494e991994631df11f8f4f258a",
            reference_continuous_denominator_policy().fingerprint,
        )
        result = self.basic_result()
        store = ProspectiveDenominatorStore(self.root / "store", activation=self.activation)
        store.persist_result(result, completed_at="2026-08-17T11:23:00-04:00")
        self.assertEqual(20, store.summary().unique_prospective_members)

        late = build_activation_record(
            activated_at="2026-08-18T09:00:00-04:00",
            first_eligible_session_date="2026-08-18",
            source_git_sha="1" * 40,
            configuration_fingerprint="2" * 64,
        )
        with self.assertRaises((OpportunityDenominatorError, ProspectiveDenominatorError)):
            active_result(
                paginated_snapshot(1, {1}, symbols={1: "AAA"}),
                universe_result(paginated_snapshot(1, {1}, symbols={1: "AAA"})),
                composition_cycle(
                    universe_result(paginated_snapshot(1, {1}, symbols={1: "AAA"}))
                ),
                late,
            )

    def test_nested_populations_and_unknown_instrument_boundary_are_truthful(self) -> None:
        result = self.basic_result()
        store = ProspectiveDenominatorStore(self.root / "store", activation=self.activation)
        store.persist_result(result, completed_at="2026-08-17T11:23:00-04:00")
        summary = store.summary()
        self.assertEqual(20, summary.prospective_observations_seen)
        self.assertEqual(20, summary.unique_prospective_members)
        self.assertEqual(0, summary.duplicate_observations_suppressed)
        self.assertEqual(20, summary.population_counts[DISCOVERED])
        self.assertEqual(2, summary.population_counts[HOT_UNIVERSE])
        self.assertEqual(1, summary.population_counts[READY])
        self.assertEqual(2, summary.population_counts[COMPOSITION])
        self.assertEqual(2, summary.population_counts[NO_PLAN])
        self.assertEqual(0, summary.population_counts[TRADEPLAN])
        members = store._records(
            "prospective-members",
            "PROSPECTIVE_MEMBERSHIP",
            __import__(
                "momentum_hunter.prospective_denominator",
                fromlist=["ProspectiveMembershipRecord"],
            ).ProspectiveMembershipRecord,
        )
        self.assertTrue(all(item.statistical_eligibility.endswith("ELIGIBLE") for item in members))
        self.assertTrue(all(item.execution_eligibility.endswith("BLOCKED") for item in members))

    def test_provider_bound_members_remain_in_prospective_population(self) -> None:
        snapshot = paginated_snapshot(30, set(range(1, 31)))
        policy = HotUniversePolicy(
            maximum_tracked_symbols=30,
            maximum_hot_symbols=10,
            maximum_warm_symbols=0,
        )
        universe = universe_result(snapshot, policy=policy)
        result = active_result(
            snapshot,
            universe,
            composition_cycle(universe),
            self.activation,
        )
        store = ProspectiveDenominatorStore(
            self.root / "provider-bound",
            activation=self.activation,
        )

        store.persist_result(result, completed_at="2026-08-17T11:23:00-04:00")

        self.assertEqual(20, store.summary().population_counts[PROVIDER_BOUND])

    def test_existing_natural_denominator_source_persists_prospective_result(self) -> None:
        snapshot = paginated_snapshot(1, {1}, symbols={1: "AAA"})
        universe = universe_result(snapshot)
        life = composition_fixture.LifecycleFixture(self.root / "natural-source", "AAA")
        cycle = composition_cycle(
            universe,
            inputs=(ready_member_input(universe.state, "AAA", life.snapshot),),
        )
        state = QualificationState(
            root=self.root / "qualification",
            launch_at=composition_fixture.at(11, 20),
        )
        state.snapshot = snapshot
        state.universe = universe
        state.cycles[cycle.cycle_id] = cycle
        store = ProspectiveDenominatorStore(
            self.root / "prospective", activation=self.activation
        )
        source = LiveDenominatorSource(state, prospective_store=store)
        result = source.produce(
            DenominatorRequest(
                request_id="natural-denominator-request",
                symbol="AAA",
                requested_at=composition_fixture.at(11, 23).isoformat(),
                composition_cycle_id=cycle.cycle_id,
                composition_fingerprint=cycle.fingerprint,
            )
        )
        self.assertTrue(result.complete)
        self.assertEqual(1, store.summary().unique_prospective_members)
        self.assertIn(result.cycle_id, state.denominator_results)

    def test_repeated_cycle_suppresses_membership_but_preserves_attempts_and_restart(self) -> None:
        first = self.basic_result(minute=1)
        second = self.basic_result(minute=2)
        store = ProspectiveDenominatorStore(self.root / "store", activation=self.activation)
        store.persist_result(first, completed_at="2026-08-17T11:23:00-04:00")
        store.persist_result(first, completed_at="2026-08-17T11:23:00-04:00")
        store.persist_result(second, completed_at="2026-08-17T11:24:00-04:00")
        restarted = ProspectiveDenominatorStore(
            self.root / "store", activation=self.activation
        )
        summary = restarted.summary()
        self.assertEqual(40, summary.prospective_observations_seen)
        self.assertEqual(20, summary.unique_prospective_members)
        self.assertEqual(20, summary.duplicate_observations_suppressed)

    def test_historical_context_never_creates_membership(self) -> None:
        store = ProspectiveDenominatorStore(self.root / "store", activation=self.activation)
        context = store.persist_historical_context(
            source_context_id="schwab-history:AAA",
            symbol="AAA",
            observed_at="2026-08-17T11:20:00-04:00",
            evidence_fingerprint="3" * 64,
        )
        summary = store.summary()
        self.assertEqual(HISTORICAL_CONTEXT_ONLY, context.observation_class)
        self.assertFalse(context.creates_prospective_membership)
        self.assertEqual(1, summary.historical_context_only_records)
        self.assertEqual(0, summary.unique_prospective_members)

    def test_winner_and_loser_cannot_change_original_membership(self) -> None:
        result = self.planned_result()
        opportunity = result.opportunities[0]
        stores = []
        membership_payloads = []
        for name in ("winner", "loser"):
            store = ProspectiveDenominatorStore(
                self.root / name, activation=self.activation
            )
            receipt = store.persist_result(
                result, completed_at="2026-08-17T11:23:00-04:00"
            )
            membership_id = receipt.membership_ids[0]
            membership_path = store._path("prospective-members", membership_id)
            membership_payloads.append(membership_path.read_bytes())
            stores.append((store, membership_id))
        self.assertEqual(membership_payloads[0], membership_payloads[1])

        def bar(minute: int, *, high: float, low: float) -> MarketPathBar:
            return MarketPathBar(
                timestamp=composition_fixture.at(11, minute).isoformat(),
                open=101.0,
                high=high,
                low=low,
                close=101.0,
                volume=1000.0,
                evidence_id=f"bar:{minute}:{high}:{low}",
                fingerprint=("4" if high > 103 else "5") * 64,
            )

        winner = build_market_path_outcome(
            opportunity=opportunity,
            bars=(bar(23, high=104.0, low=100.0),),
            entry_price=101.0,
            stop_price=99.0,
            target_price=103.0,
            horizon_end=composition_fixture.at(11, 30).isoformat(),
            observation_class=COUNTERFACTUAL_RESEARCH_OBSERVATION,
        )
        loser = build_market_path_outcome(
            opportunity=opportunity,
            bars=(bar(23, high=102.0, low=98.0),),
            entry_price=101.0,
            stop_price=99.0,
            target_price=103.0,
            horizon_end=composition_fixture.at(11, 30).isoformat(),
            observation_class=COUNTERFACTUAL_RESEARCH_OBSERVATION,
        )
        stores[0][0].persist_market_outcome(
            membership_id=stores[0][1],
            outcome=winner,
            attached_at=composition_fixture.at(11, 31).isoformat(),
        )
        stores[1][0].persist_market_outcome(
            membership_id=stores[1][1],
            outcome=loser,
            attached_at=composition_fixture.at(11, 31).isoformat(),
        )
        self.assertEqual(membership_payloads[0], stores[0][0]._path("prospective-members", stores[0][1]).read_bytes())
        self.assertEqual(membership_payloads[1], stores[1][0]._path("prospective-members", stores[1][1]).read_bytes())
        self.assertEqual(1, stores[0][0].summary().outcome_complete_members)
        self.assertEqual(0, stores[0][0].summary().outcome_pending_members)

    def test_successor_setup_is_a_new_member_and_predecessor_stays_immutable(self) -> None:
        snapshot = paginated_snapshot(20, {1}, symbols={1: "AAA"})
        universe = universe_result(snapshot)
        life = composition_fixture.LifecycleFixture(self.root / "successor", "AAA")
        life.opening_breakout()
        original = life.snapshot
        original_plan = build_intraday_plan_evidence(
            symbol="AAA",
            setup_family=CONTINUATION_BREAKOUT,
            created_at=composition_fixture.at(11, 3),
            planned_entry=100.0,
            stop_price=98.0,
            target_prices=(102.0, 104.0),
            source_setup_fingerprint="6" * 64,
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
                evidence_fingerprint="7" * 64,
                source_identity="test-only-canonical-bar",
            ),
        )
        missed_cycle = composition_cycle(universe, inputs=(missed_input,))
        first = active_result(snapshot, universe, missed_cycle, self.activation)
        missed_result = missed_cycle.member_results[0]
        life.apply_proposal(missed_result.lifecycle_proposal)
        next_input = member_input(
            universe.state,
            "AAA",
            lifecycle=life.snapshot,
            evidence=composition_fixture.evidence(
                "AAA",
                bars=composition_fixture.canonical_bars(
                    "AAA", end=composition_fixture.at(11, 24)
                ),
                receipt=composition_fixture.at(11, 25),
            ),
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
        second = active_result(snapshot, universe, next_cycle, self.activation)
        store = ProspectiveDenominatorStore(self.root / "store", activation=self.activation)
        first_receipt = store.persist_result(
            first, completed_at=composition_fixture.at(11, 23).isoformat()
        )
        first_bytes = {
            identity: store._path("prospective-members", identity).read_bytes()
            for identity in first_receipt.membership_ids
        }
        store.persist_result(
            second, completed_at=composition_fixture.at(11, 26).isoformat()
        )
        self.assertGreater(store.summary().population_counts[SUCCESSOR_SETUP], 0)
        self.assertTrue(all(
            store._path("prospective-members", identity).read_bytes() == content
            for identity, content in first_bytes.items()
        ))
        setup_members = [
            item
            for item in store._records(
                "prospective-members",
                "PROSPECTIVE_MEMBERSHIP",
                __import__(
                    "momentum_hunter.prospective_denominator",
                    fromlist=["ProspectiveMembershipRecord"],
                ).ProspectiveMembershipRecord,
            )
            if item.unit_kind == "SETUP"
        ]
        self.assertEqual(2, len(setup_members))

    def test_tamper_and_conflicting_activation_fail_closed(self) -> None:
        store = ProspectiveDenominatorStore(self.root / "store", activation=self.activation)
        store.persist_result(
            self.basic_result(), completed_at="2026-08-17T11:23:00-04:00"
        )
        member = next((store.sample_root / "prospective-members").glob("*.json"))
        payload = json.loads(member.read_text(encoding="ascii"))
        payload["payload"]["symbol"] = "ZZZ"
        member.write_text(json.dumps(payload), encoding="ascii")
        with self.assertRaises(ProspectiveDenominatorError):
            store.summary()

    def test_module_has_no_provider_broker_service_scheduler_or_ui_capability(self) -> None:
        source = Path(__import__(
            "momentum_hunter.prospective_denominator", fromlist=["__file__"]
        ).__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        forbidden = ("providers", "schwab", "alpaca", "broker", "order", "service", "scheduler", "ui")
        self.assertFalse(any(any(part in item.lower() for part in forbidden) for item in imports))


if __name__ == "__main__":
    unittest.main()
