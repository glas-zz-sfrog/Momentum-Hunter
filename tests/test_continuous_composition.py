from __future__ import annotations

import ast
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.broad_discovery import (
    DiscoveryQueryIdentity,
    DiscoverySourceRow,
    build_discovery_snapshot,
)
from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_FORMING,
    BREAKOUT_CONFIRMED,
    ENTRY_MISSED,
    MONITORING_ACTIVATED,
    SETUP_IDENTITY_CHANGED,
    CandidateLifecycleCoordinator,
    CandidateLifecyclePolicy,
    CandidateLifecycleStore,
)
from momentum_hunter.canonical_candle_evidence import CanonicalMinuteBar
from momentum_hunter.continuous_composition import (
    AMBIGUOUS_SAME_BAR,
    BLOCKED_DATA,
    DATA_FAILURE,
    DETERMINATE,
    EXPIRED_RESULT,
    GAPPED_EVIDENCE,
    MISSED_ENTRY_RECORDED,
    NO_LIFECYCLE_CHANGE,
    NOT_EVALUATED_POLICY,
    PROVIDER_BOUND,
    RESEARCH_PLAN_COMPOSED,
    SETUP_PENDING,
    UNSUPPORTED_SESSION,
    WAITING_READINESS,
    CanonicalEvidenceInput,
    CompositionMemberInput,
    ContinuousCompositionError,
    ContinuousCompositionPolicy,
    LifecycleTransitionInput,
    SuccessorSetupEvidence,
    assess_readiness,
    build_readiness_request,
    compose_cycle,
)
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE
from momentum_hunter.hot_universe import (
    HOT,
    PROTECTED,
    PROVIDER_BOUND as UNIVERSE_PROVIDER_BOUND,
    WARM,
    HotUniversePolicy,
    ProtectedResourceInput,
    apply_discovery_snapshot,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    OPENING_BREAKOUT,
    PULLBACK,
    build_intraday_plan_evidence,
    transition_intraday_plan,
)
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.schwab_candle_contract import EASTERN_TZ, SCHWAB_PRICE_HISTORY_SOURCE
from momentum_hunter.time_normalized_rvol import TimeNormalizedRvolEvidence


SESSION = "2026-08-17"
SOURCE_CONTRACT = "a" * 64
SEMANTIC = "b" * 64
DAILY = "c" * 64
RVOL = "d" * 64
LIFECYCLE = "e" * 64


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, second, tzinfo=EASTERN_TZ)


def discovery_snapshot(symbols: list[str], *, minute: int = 0, rejected: tuple[str, ...] = ()):
    observed = at(11, minute)
    rows = [
        DiscoverySourceRow.from_mapping(
            source_row_ordinal=index,
            source_row_identity=f"{symbol}-{index}-{observed.isoformat()}",
            source_values={"Ticker": symbol, "No.": str(index)},
            candidate=Candidate(
                ticker=symbol,
                company=f"{symbol} Incorporated",
                price=100.0,
                percent_change=1.0 if symbol in rejected else 5.0,
                volume=5_000_000,
                relative_volume=2.0,
                market_cap=10_000_000_000,
                sector="Technology",
                industry="Software",
            ),
        )
        for index, symbol in enumerate(symbols, start=1)
    ]
    return build_discovery_snapshot(
        source="finviz",
        source_version="synthetic-continuous-discovery-v1",
        requested_at=observed - timedelta(seconds=2),
        received_at=observed - timedelta(seconds=1),
        evaluated_at=observed,
        query_identity=DiscoveryQueryIdentity.from_criteria(
            INSTITUTIONAL_MOMENTUM,
            source_query="synthetic://continuous",
            sort_order="-volume",
        ),
        source_contract_fingerprint=SOURCE_CONTRACT,
        semantic_plausibility_fingerprint=SEMANTIC,
        source_rows=rows,
    )


def universe(symbols: list[str], *, hot: int = 10, warm: int = 20, protected: tuple[str, ...] = ()):
    policy = HotUniversePolicy(
        maximum_tracked_symbols=30,
        maximum_hot_symbols=hot,
        maximum_warm_symbols=warm,
    )
    result = apply_discovery_snapshot(
        None,
        policy=policy,
        snapshot=discovery_snapshot(symbols),
        protected_inputs=tuple(
            ProtectedResourceInput(symbol, "SYNTHETIC_POSITION") for symbol in protected
        ),
    )
    return result.state


def member(state, symbol: str):
    return next(item for item in state.members if item.symbol == symbol)


def canonical_bars(symbol: str, *, end: datetime = at(11, 21), missing: bool = False, source: str = SCHWAB_PRICE_HISTORY_SOURCE, state: str = "RECONCILED", session: str = SESSION):
    bars = []
    for index in range(5):
        timestamp = end - timedelta(minutes=4 - index)
        if missing and index == 2:
            continue
        bars.append(
            CanonicalMinuteBar(
                symbol=symbol,
                timestamp=timestamp.astimezone(EASTERN_TZ).isoformat(),
                open=100.0 + index,
                high=101.0 + index,
                low=99.5 + index,
                close=100.5 + index,
                volume=10_000.0 + index,
                source=source,
                state=state,
                session_date=session,
            )
        )
    return tuple(bars)


def evidence(symbol: str, *, bars=None, history: int = 7, receipt: datetime = at(11, 22), daily: bool = True):
    return CanonicalEvidenceInput(
        evidence_id=f"canonical-{symbol}-{receipt.isoformat()}",
        symbol=symbol,
        session_date=SESSION,
        provider_timestamp=receipt.isoformat(),
        receipt_timestamp=receipt.isoformat(),
        bars=canonical_bars(symbol) if bars is None else bars,
        daily_evidence_id=f"daily-{symbol}" if daily else "",
        daily_evidence_fingerprint=DAILY if daily else "",
        history_depth_sessions=history,
    )


def rvol(symbol: str, *, eligible: bool = True, through: datetime = at(11, 21), baseline: int = 7):
    return TimeNormalizedRvolEvidence(
        status=EXECUTION_ELIGIBLE if eligible else "EXECUTION_INELIGIBLE",
        symbol=symbol,
        session_date=SESSION,
        through_minute=through.isoformat(),
        baseline_session_count=baseline,
        minimum_baseline_sessions=5,
        target_baseline_sessions=20,
        observed_volume=100_000,
        expected_volume=80_000.0,
        relative_volume=1.25,
    )


class LifecycleFixture:
    def __init__(self, root: Path, symbol: str) -> None:
        self.symbol = symbol
        self.coordinator = CandidateLifecycleCoordinator(
            CandidateLifecycleStore(root / f"{symbol}.json"),
            policy=CandidateLifecyclePolicy(
                policy_version="synthetic-lifecycle-v1",
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
            source_identity="synthetic-discovery",
            occurred_at=at(11, 0),
            provider_timestamp=at(10, 59, 59),
            receipt_timestamp=at(11, 0),
            reason="Synthetic bounded discovery.",
        )
        self.opportunity_id = discovered.snapshot.opportunity_id
        self.coordinator.transition(
            opportunity_id=self.opportunity_id,
            next_state="WATCHING",
            evidence_fingerprint="f" * 64,
            source_identity="synthetic-canonical",
            occurred_at=at(11, 1),
            provider_timestamp=at(11, 0, 59),
            receipt_timestamp=at(11, 1),
            reason="Synthetic monitoring admission.",
            material_delta_kind=MONITORING_ACTIVATED,
        )

    @property
    def snapshot(self):
        return self.coordinator.snapshot(self.opportunity_id)

    def opening_breakout(self):
        return self.coordinator.transition(
            opportunity_id=self.opportunity_id,
            next_state=BREAKOUT_FORMING,
            evidence_fingerprint="1" * 64,
            source_identity="synthetic-canonical",
            occurred_at=at(11, 2),
            provider_timestamp=at(11, 1, 59),
            receipt_timestamp=at(11, 2),
            reason="Synthetic opening breakout.",
            material_delta_kind=SETUP_IDENTITY_CHANGED,
            setup_family=OPENING_BREAKOUT,
        )

    def apply_proposal(self, proposal):
        return self.coordinator.transition(
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


class ContinuousCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.policy = ContinuousCompositionPolicy()
        self.cutoff = at(11, 22)

    def compose(self, state, inputs):
        return compose_cycle(
            universe_state=state,
            member_inputs=inputs,
            started_at=at(11, 21, 50),
            evidence_cutoff=self.cutoff,
            policy=self.policy,
        )

    def input(self, state, symbol: str, *, lifecycle=None, canonical=None, volume=None, transition=None, successor=None, existing_plan=None):
        return CompositionMemberInput(
            universe_member_id=member(state, symbol).member_id,
            lifecycle=lifecycle,
            canonical_evidence=evidence(symbol) if canonical is None else canonical,
            rvol_evidence=rvol(symbol) if volume is None else volume,
            lifecycle_transition=transition,
            successor_setup=successor,
            existing_plan=existing_plan,
        )

    def result(self, cycle, symbol: str):
        return next(item for item in cycle.member_results if item.symbol == symbol)

    def successor(self, symbol: str, *, family: str = CONTINUATION_BREAKOUT, predecessor="", terminal="", known: datetime = at(11, 21), ambiguity: str = DETERMINATE):
        return SuccessorSetupEvidence(
            evidence_id=f"successor-{symbol}-{family}",
            evidence_fingerprint="2" * 64,
            symbol=symbol,
            session_date=SESSION,
            setup_family=family,
            known_at=known.isoformat(),
            source_level_kind="CALLER_SUPPLIED_CHRONOLOGY_VALID_RESEARCH_STRUCTURE",
            planned_entry=105.0,
            stop_price=103.0,
            target_prices=(107.0, 109.0),
            source_evidence_ids=(f"structure-{symbol}",),
            predecessor_setup_id=predecessor,
            predecessor_terminal_state=terminal,
            successor_reason="TEST_ONLY_SUCCESSOR_STRUCTURE",
            chronology_state=ambiguity,
        )

    def test_midday_new_bbb_composes_without_opening_ancestry(self) -> None:
        state = universe(["BBB"])
        life = LifecycleFixture(self.root, "BBB")

        cycle = self.compose(state, [self.input(state, "BBB", lifecycle=life.snapshot, successor=self.successor("BBB"))])

        result = self.result(cycle, "BBB")
        self.assertEqual(RESEARCH_PLAN_COMPOSED, result.disposition)
        self.assertEqual(CONTINUATION_BREAKOUT, result.lifecycle_proposal.setup_family)
        self.assertEqual(1, result.lifecycle_proposal.setup_sequence)
        self.assertEqual("", result.lifecycle_proposal.predecessor_setup_id)
        self.assertEqual("EXECUTION_AUTHORITY_NONE", result.authority)
        self.assertTrue(result.intraday_plan.plan_id)
        self.assertEqual(1, cycle.summary.plans_composed)

    def test_readiness_waits_then_becomes_ready(self) -> None:
        state = universe(["BBB"])
        life = LifecycleFixture(self.root, "BBB")
        waiting = self.compose(state, [self.input(state, "BBB", lifecycle=life.snapshot, canonical=None, volume=None)])
        self.assertEqual(NO_LIFECYCLE_CHANGE, self.result(waiting, "BBB").disposition)

        pending = self.compose(state, [replace(self.input(state, "BBB", lifecycle=life.snapshot), canonical_evidence=None)])
        self.assertEqual(WAITING_READINESS, self.result(pending, "BBB").disposition)
        self.assertEqual("CANONICAL_EVIDENCE_NOT_SUPPLIED", self.result(pending, "BBB").blocker_reasons[0])

    def test_provisional_only_bars_cannot_confirm_setup(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        provisional = evidence("AAA", bars=canonical_bars("AAA", state="PROVISIONAL"))

        cycle = self.compose(state, [self.input(state, "AAA", lifecycle=life.snapshot, canonical=provisional, successor=self.successor("AAA"))])

        self.assertEqual(DATA_FAILURE, self.result(cycle, "AAA").disposition)
        self.assertIn("CANONICAL_RECONCILED_SCHWAB_BAR_REQUIRED", self.result(cycle, "AAA").blocker_reasons)

    def test_rvol_insufficient_is_explicit_blocker(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        cycle = self.compose(state, [self.input(state, "AAA", lifecycle=life.snapshot, volume=rvol("AAA", eligible=False, baseline=2))])

        self.assertEqual(BLOCKED_DATA, self.result(cycle, "AAA").disposition)
        self.assertEqual("TIME_NORMALIZED_RVOL_INSUFFICIENT_OR_UNSAFE", self.result(cycle, "AAA").blocker_reasons[0])

    def test_opening_setup_continues_without_duplicate_identity(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        life.opening_breakout()
        first = self.compose(state, [self.input(state, "AAA", lifecycle=life.snapshot)])
        second = self.compose(state, [self.input(state, "AAA", lifecycle=life.snapshot)])

        self.assertEqual(NO_LIFECYCLE_CHANGE, self.result(first, "AAA").disposition)
        self.assertEqual(first, second)
        self.assertEqual(0, first.summary.plans_composed)

    def test_missed_opening_then_distinct_pullback_successor(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        life.opening_breakout()
        original = life.snapshot
        original_plan = build_intraday_plan_evidence(
            symbol="AAA", setup_family=CONTINUATION_BREAKOUT, created_at=at(11, 3), planned_entry=100.0,
            stop_price=98.0, target_prices=(102.0, 104.0), source_setup_fingerprint="3" * 64,
            source_level_kind="TEST_ONLY_OPENING_STRUCTURE", source_evidence_ids=("opening-bars",), lifecycle_status="PENDING_ENTRY",
        )
        missed = self.compose(state, [self.input(state, "AAA", lifecycle=original, existing_plan=original_plan, transition=LifecycleTransitionInput(
            next_state=ENTRY_MISSED, reason="TRIGGER_CROSSED_OUTSIDE_ENTRY_WINDOW", evidence_fingerprint="4" * 64,
            source_identity="caller-canonical-completed-bar",
        ))])
        missed_result = self.result(missed, "AAA")
        self.assertEqual(MISSED_ENTRY_RECORDED, missed_result.disposition)
        self.assertEqual(ENTRY_MISSED, missed_result.lifecycle_proposal.next_state)
        self.assertEqual("MISSED_ENTRY", missed_result.intraday_plan.lifecycle_status)
        self.assertEqual(100.0, missed_result.intraday_plan.planned_entry)
        life.apply_proposal(missed_result.lifecycle_proposal)
        terminal = life.snapshot
        successor = self.successor("AAA", family=PULLBACK, predecessor=original.current_setup_id, terminal=ENTRY_MISSED)
        next_cycle = self.compose(state, [self.input(state, "AAA", lifecycle=terminal, successor=successor, existing_plan=missed_result.intraday_plan)])
        result = self.result(next_cycle, "AAA")

        self.assertEqual(RESEARCH_PLAN_COMPOSED, result.disposition)
        self.assertNotEqual(original.current_setup_id, result.lifecycle_proposal.setup_id)
        self.assertEqual(original.current_setup_id, result.lifecycle_proposal.predecessor_setup_id)
        self.assertNotEqual(original_plan.plan_id, result.intraday_plan.plan_id)
        self.assertEqual(missed_result.intraday_plan.plan_id, result.intraday_plan.predecessor_plan_id)
        self.assertEqual(105.0, result.intraday_plan.planned_entry)

    def test_same_bar_ambiguity_is_never_promoted(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        cycle = self.compose(state, [self.input(state, "AAA", lifecycle=life.snapshot, successor=self.successor("AAA", ambiguity=AMBIGUOUS_SAME_BAR))])

        result = self.result(cycle, "AAA")
        self.assertEqual(SETUP_PENDING, result.disposition)
        self.assertIn(AMBIGUOUS_SAME_BAR, result.blocker_reasons)
        self.assertIsNone(result.intraday_plan)

    def test_missed_setup_cannot_reopen_or_create_unlinked_successor(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        life.opening_breakout()
        original = life.snapshot
        missed = self.compose(state, [self.input(state, "AAA", lifecycle=original, transition=LifecycleTransitionInput(
            next_state=ENTRY_MISSED, reason="MISSED", evidence_fingerprint="6" * 64, source_identity="canonical",
        ))])
        life.apply_proposal(self.result(missed, "AAA").lifecycle_proposal)
        with self.assertRaisesRegex(ContinuousCompositionError, "replacement setup must name"):
            self.compose(state, [self.input(state, "AAA", lifecycle=life.snapshot, successor=self.successor("AAA", family=PULLBACK))])

    def test_duplicate_member_input_and_nonregular_cutoff_fail_closed(self) -> None:
        state = universe(["AAA"])
        item = self.input(state, "AAA")
        with self.assertRaisesRegex(ContinuousCompositionError, "more than once"):
            self.compose(state, [item, item])
        with self.assertRaisesRegex(ContinuousCompositionError, "same-session regular hours"):
            compose_cycle(
                universe_state=state,
                member_inputs=(),
                started_at=at(8, 29),
                evidence_cutoff=at(8, 30),
                policy=self.policy,
            )

    def test_scanner_disappearance_and_discovery_failure_do_not_block_hot_member(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        cycle = self.compose(state, [self.input(state, "AAA", lifecycle=life.snapshot, successor=self.successor("AAA"))])
        self.assertEqual(RESEARCH_PLAN_COMPOSED, self.result(cycle, "AAA").disposition)

    def test_provider_bound_warm_and_protected_have_explicit_non_entry_dispositions(self) -> None:
        protected_state = universe(["AAA"], protected=("AAA",))
        policy = HotUniversePolicy(maximum_tracked_symbols=30, maximum_hot_symbols=1, maximum_warm_symbols=1)
        first = apply_discovery_snapshot(None, policy=policy, snapshot=discovery_snapshot(["BBB", "CCC"]))
        warm_state = apply_discovery_snapshot(first.state, policy=policy, snapshot=discovery_snapshot(["BBB", "CCC"], minute=1, rejected=("CCC",))).state
        bound_state = universe(["DDD", "EEE"], hot=1, warm=0)
        self.assertEqual(PROTECTED, member(protected_state, "AAA").current_tier)
        self.assertEqual(WARM, member(warm_state, "CCC").current_tier)
        self.assertEqual(UNIVERSE_PROVIDER_BOUND, member(bound_state, "EEE").current_tier)
        life = LifecycleFixture(self.root, "AAA")
        protected_cycle = self.compose(protected_state, [self.input(protected_state, "AAA", lifecycle=life.snapshot)])
        warm_cycle = self.compose(warm_state, [])
        bound_cycle = self.compose(bound_state, [])

        self.assertEqual(NOT_EVALUATED_POLICY, self.result(protected_cycle, "AAA").disposition)
        self.assertEqual(NOT_EVALUATED_POLICY, self.result(warm_cycle, "CCC").disposition)
        self.assertEqual(PROVIDER_BOUND, self.result(bound_cycle, "EEE").disposition)

    def test_one_bad_symbol_does_not_abort_other_ready_members(self) -> None:
        state = universe(["AAA", "BBB", "CCC", "DDD", "EEE"], hot=3, warm=1)
        lives = {symbol: LifecycleFixture(self.root, symbol) for symbol in ("AAA", "BBB", "CCC", "EEE")}
        corrupted = evidence("CCC", bars=canonical_bars("CCC", missing=True))
        inputs = [
            self.input(state, "AAA", lifecycle=lives["AAA"].snapshot, successor=self.successor("AAA")),
            replace(self.input(state, "BBB", lifecycle=lives["BBB"].snapshot), canonical_evidence=None),
            self.input(state, "CCC", lifecycle=lives["CCC"].snapshot, canonical=corrupted),
            self.input(state, "EEE", lifecycle=lives["EEE"].snapshot, successor=self.successor("EEE")),
        ]
        cycle = self.compose(state, inputs)

        self.assertEqual(RESEARCH_PLAN_COMPOSED, self.result(cycle, "AAA").disposition)
        self.assertEqual(WAITING_READINESS, self.result(cycle, "BBB").disposition)
        self.assertEqual(DATA_FAILURE, self.result(cycle, "CCC").disposition)
        self.assertEqual(PROVIDER_BOUND, self.result(cycle, "DDD").disposition)
        self.assertEqual(PROVIDER_BOUND, self.result(cycle, "EEE").disposition)
        self.assertEqual(5, cycle.summary.members_presented)

    def test_gapped_stale_and_history_data_are_honest(self) -> None:
        state = universe(["AAA"])
        request = build_readiness_request(member(state, "AAA"), requested_at=self.cutoff, policy=self.policy)
        gapped = assess_readiness(request, evidence=evidence("AAA", bars=canonical_bars("AAA", missing=True)), rvol_evidence=rvol("AAA"), evaluated_at=self.cutoff, policy=self.policy)
        stale = assess_readiness(request, evidence=evidence("AAA", bars=canonical_bars("AAA", end=at(11, 15))), rvol_evidence=rvol("AAA"), evaluated_at=self.cutoff, policy=self.policy)
        shallow = assess_readiness(request, evidence=evidence("AAA", history=2), rvol_evidence=rvol("AAA"), evaluated_at=self.cutoff, policy=self.policy)

        self.assertEqual(GAPPED_EVIDENCE, gapped.status)
        self.assertEqual("STALE_EVIDENCE", stale.status)
        self.assertEqual("INSUFFICIENT_HISTORY", shallow.status)

    def test_future_naive_or_foreign_evidence_rejected(self) -> None:
        state = universe(["AAA"])
        request = build_readiness_request(member(state, "AAA"), requested_at=self.cutoff, policy=self.policy)
        with self.assertRaisesRegex(ContinuousCompositionError, "after assessment cutoff"):
            assess_readiness(request, evidence=evidence("AAA", receipt=at(11, 23)), rvol_evidence=rvol("AAA"), evaluated_at=self.cutoff, policy=self.policy)
        foreign = evidence("AAA", bars=canonical_bars("BBB"))
        foreign_assessment = assess_readiness(request, evidence=foreign, rvol_evidence=rvol("AAA"), evaluated_at=self.cutoff, policy=self.policy)
        self.assertEqual("DATA_UNSAFE", foreign_assessment.status)
        with self.assertRaisesRegex(ContinuousCompositionError, "timezone-aware"):
            compose_cycle(universe_state=state, member_inputs=(), started_at=datetime(2026, 8, 17, 11, 20), evidence_cutoff=self.cutoff, policy=self.policy)

    def test_restart_replay_is_idempotent_and_correction_does_not_rewrite_old_cycle(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        item = self.input(state, "AAA", lifecycle=life.snapshot, successor=self.successor("AAA"))
        first = self.compose(state, [item])
        second = self.compose(state, [item])
        corrected_bars = list(canonical_bars("AAA"))
        corrected_bars[-1] = replace(corrected_bars[-1], close=111.0)
        later_item = self.input(state, "AAA", lifecycle=life.snapshot, canonical=evidence("AAA", bars=tuple(corrected_bars), receipt=at(11, 22)), successor=self.successor("AAA"))
        later = self.compose(state, [later_item])

        self.assertEqual(first, second)
        self.assertNotEqual(first.fingerprint, later.fingerprint)
        self.assertEqual(100.5, item.canonical_evidence.bars[0].close)
        self.assertEqual(104.5, item.canonical_evidence.bars[-1].close)

    def test_session_end_is_terminal_not_overnight_continuation(self) -> None:
        state = universe(["AAA"])
        life = LifecycleFixture(self.root, "AAA")
        ending = at(15, 55)
        cycle = compose_cycle(
            universe_state=state,
            member_inputs=(self.input(state, "AAA", lifecycle=life.snapshot),),
            started_at=at(15, 54, 30), evidence_cutoff=ending, policy=self.policy,
        )
        self.assertEqual(EXPIRED_RESULT, self.result(cycle, "AAA").disposition)

    def test_research_only_module_has_no_runtime_provider_or_broker_imports(self) -> None:
        path = Path(__file__).parents[1] / "momentum_hunter" / "continuous_composition.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[1] if alias.name.startswith("momentum_hunter.") else alias.name
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[1] if node.module and node.module.startswith("momentum_hunter.") else node.module
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
        }
        forbidden = {"alpaca", "broker", "risk_governor", "allocation", "schwab_market_data", "automation", "scheduler", "service"}
        self.assertTrue(forbidden.isdisjoint(imported), imported)


if __name__ == "__main__":
    unittest.main()
