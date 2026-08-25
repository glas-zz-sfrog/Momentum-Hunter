from __future__ import annotations

import ast
import hashlib
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.automatic_candle_backfill import AutomaticCandleBackfillCoordinator
from momentum_hunter.broad_discovery import (
    DiscoveryQueryIdentity,
    DiscoverySourceRow,
    build_discovery_snapshot,
)
from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_CONFIRMED,
    ENTRY_MISSED,
    MONITORING_ACTIVATED,
    SETUP_IDENTITY_CHANGED,
    CandidateLifecycleCoordinator,
    CandidateLifecyclePolicy,
    CandidateLifecycleStore,
)
from momentum_hunter.continuous_composition import (
    CompositionMemberInput,
    ContinuousCompositionPolicy,
    SuccessorSetupEvidence,
)
from momentum_hunter.continuous_tradeplan_producer import (
    COMMON_STOCK,
    HISTORY_BACKFILL_PENDING,
    HISTORY_INSUFFICIENT,
    HISTORY_READY,
    INSTRUMENT_ADMISSION_GAP,
    LEVERAGED_ETP,
    ContinuousHistoryAdmissionCoordinator,
    ContinuousTradePlanProducer,
    ContinuousTradePlanProducerError,
    ContinuousTradePlanProducerStore,
    CurrentMarketEvidence,
    InstrumentAdmissionEvidence,
    build_current_market_evidence,
    inspect_historical_context,
    unavailable_instrument_admission,
)
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE
from momentum_hunter.hot_universe import HotUniversePolicy, apply_discovery_snapshot
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    MISSED_ENTRY as PLAN_MISSED_ENTRY,
    PULLBACK,
    transition_intraday_plan,
)
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabDailyCandle,
    SchwabMinuteCandle,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.schwab_daily_candle_store import SchwabDailyCandleStore
from momentum_hunter.time_normalized_rvol import TimeNormalizedRvolEvidence


SESSION = "2026-08-17"
CONFIGURATION = "a" * 64


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, second, tzinfo=EASTERN_TZ)


def fingerprint(value: object) -> str:
    return hashlib.sha256(repr(value).encode("ascii")).hexdigest()


def universe(symbol: str = "AAA"):
    observed = at(11, 0)
    row = DiscoverySourceRow.from_mapping(
        source_row_ordinal=1,
        source_row_identity=f"finviz:{symbol}:{observed.isoformat()}",
        source_values={"Ticker": symbol, "No.": "1"},
        candidate=Candidate(
            ticker=symbol,
            company=f"{symbol} Incorporated",
            price=100.0,
            percent_change=5.0,
            volume=5_000_000,
            relative_volume=2.0,
            market_cap=10_000_000_000,
            sector="Technology",
            industry="Software",
        ),
    )
    snapshot = build_discovery_snapshot(
        source="finviz",
        source_version="producer-test-v1",
        requested_at=observed - timedelta(seconds=2),
        received_at=observed - timedelta(seconds=1),
        evaluated_at=observed,
        query_identity=DiscoveryQueryIdentity.from_criteria(
            INSTITUTIONAL_MOMENTUM,
            source_query="synthetic://producer",
            sort_order="-volume",
        ),
        source_contract_fingerprint="b" * 64,
        semantic_plausibility_fingerprint="c" * 64,
        source_rows=(row,),
    )
    return apply_discovery_snapshot(
        None,
        policy=HotUniversePolicy(maximum_hot_symbols=1),
        snapshot=snapshot,
    ).state


def active_member(state):
    return state.members[0]


class LifecycleFixture:
    def __init__(self, root: Path, symbol: str = "AAA") -> None:
        self.coordinator = CandidateLifecycleCoordinator(
            CandidateLifecycleStore(root / f"{symbol}-lifecycle.json"),
            policy=CandidateLifecyclePolicy(
                policy_version="producer-test-lifecycle-v1",
                cooldown_seconds=0,
                hysteresis_profile="producer-test",
                minimum_delta_profile="producer-test",
            ),
        )
        discovered = self.coordinator.discover(
            symbol=symbol,
            session_date=SESSION,
            originating_evidence_family="CONTINUOUS_MONITOR",
            evidence_fingerprint="d" * 64,
            source_identity="producer-test-discovery",
            occurred_at=at(11, 0),
            provider_timestamp=at(10, 59, 59),
            receipt_timestamp=at(11, 0),
            reason="Prospective producer test discovery.",
        )
        self.opportunity_id = discovered.snapshot.opportunity_id
        self.coordinator.transition(
            opportunity_id=self.opportunity_id,
            next_state="WATCHING",
            evidence_fingerprint="e" * 64,
            source_identity="producer-test-canonical",
            occurred_at=at(11, 1),
            provider_timestamp=at(11, 0, 59),
            receipt_timestamp=at(11, 1),
            reason="Prospective monitoring admitted.",
            material_delta_kind=MONITORING_ACTIVATED,
        )

    @property
    def snapshot(self):
        return self.coordinator.snapshot(self.opportunity_id)

    def apply(self, proposal) -> None:
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

    def miss_current(self, *, occurred_at: datetime) -> None:
        current = self.snapshot
        self.coordinator.transition(
            opportunity_id=self.opportunity_id,
            next_state=BREAKOUT_CONFIRMED,
            evidence_fingerprint="f" * 64,
            source_identity="producer-test-confirmation",
            occurred_at=occurred_at - timedelta(minutes=1),
            provider_timestamp=occurred_at - timedelta(minutes=1, seconds=1),
            receipt_timestamp=occurred_at - timedelta(minutes=1),
            reason="Breakout confirmation preserved.",
            material_delta_kind="SETUP_STATE_CHANGED",
            setup_family=current.current_setup_family,
        )
        self.coordinator.transition(
            opportunity_id=self.opportunity_id,
            next_state=ENTRY_MISSED,
            evidence_fingerprint="1" * 64,
            source_identity="producer-test-miss",
            occurred_at=occurred_at,
            provider_timestamp=occurred_at - timedelta(seconds=1),
            receipt_timestamp=occurred_at,
            reason="Original entry was prospectively missed.",
            material_delta_kind="SETUP_STATE_CHANGED",
            setup_family=current.current_setup_family,
        )


class ContinuousTradePlanProducerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.minute_root = self.root / "minute"
        self.daily_root = self.root / "daily"
        self.policy = ContinuousCompositionPolicy(
            required_recent_minute_bars=1,
        )
        self.state = universe()
        self.member = active_member(self.state)
        self.lifecycle = LifecycleFixture(self.root)
        self.store_path = self.root / "producer-state.json"

    def producer(self) -> ContinuousTradePlanProducer:
        return ContinuousTradePlanProducer(
            store=ContinuousTradePlanProducerStore(self.store_path),
            configuration_fingerprint=CONFIGURATION,
            policy=self.policy,
        )

    def current(self, cutoff: datetime, *, generation: int = 1) -> CurrentMarketEvidence:
        return build_current_market_evidence(
            symbol="AAA",
            provider_timestamp=(cutoff - timedelta(seconds=5)).isoformat(),
            receipt_timestamp=cutoff.isoformat(),
            source_identity="schwab_marketdata_v1_quotes:min_bid_ask_quote_time_v1",
            market_payload={
                "symbol": "AAA",
                "bid": 104.95 + generation,
                "ask": 105.0 + generation,
                "timestamp": (cutoff - timedelta(seconds=5)).isoformat(),
            },
        )

    def instrument(self, instrument_class: str = COMMON_STOCK) -> InstrumentAdmissionEvidence:
        return InstrumentAdmissionEvidence(
            evidence_id=f"instrument-aaa-{instrument_class.lower()}",
            symbol="AAA",
            observed_at=at(11, 22).isoformat(),
            source_identity="SYNTHETIC_AUTHORITATIVE_INSTRUMENT_MASTER",
            instrument_class=instrument_class,
            authoritative=True,
            evidence_fingerprint=(
                "2" if instrument_class == COMMON_STOCK else "5"
            ) * 64,
        )

    def rvol(self, cutoff: datetime) -> TimeNormalizedRvolEvidence:
        return TimeNormalizedRvolEvidence(
            status=EXECUTION_ELIGIBLE,
            symbol="AAA",
            session_date=SESSION,
            through_minute=(cutoff - timedelta(minutes=1)).isoformat(),
            baseline_session_count=5,
            minimum_baseline_sessions=5,
            target_baseline_sessions=20,
            observed_volume=100_000,
            expected_volume=80_000.0,
            relative_volume=1.25,
        )

    def successor(
        self,
        *,
        known_at: datetime,
        family: str = CONTINUATION_BREAKOUT,
        predecessor: str = "",
        terminal: str = "",
        generation: int = 1,
    ) -> SuccessorSetupEvidence:
        return SuccessorSetupEvidence(
            evidence_id=f"successor-aaa-{generation}",
            evidence_fingerprint=("3" if generation == 1 else "4") * 64,
            symbol="AAA",
            session_date=SESSION,
            setup_family=family,
            known_at=known_at.isoformat(),
            source_level_kind="CALLER_SUPPLIED_CHRONOLOGY_VALID_RESEARCH_STRUCTURE",
            planned_entry=105.0 + generation,
            stop_price=103.0,
            target_prices=(109.0 + generation, 111.0 + generation),
            source_evidence_ids=(f"canonical-structure-{generation}",),
            predecessor_setup_id=predecessor,
            predecessor_terminal_state=terminal,
            successor_reason="PROSPECTIVE_DISTINCT_SUCCESSOR",
        )

    def seed_history(self, *, latest: datetime = at(11, 21)) -> None:
        minute_store = SchwabCandleStore(self.minute_root)
        prior_sessions = (
            datetime(2026, 8, 11, 11, 0, tzinfo=EASTERN_TZ),
            datetime(2026, 8, 12, 11, 0, tzinfo=EASTERN_TZ),
            datetime(2026, 8, 13, 11, 0, tzinfo=EASTERN_TZ),
            datetime(2026, 8, 14, 11, 0, tzinfo=EASTERN_TZ),
        )
        minute_store.append_history(
            tuple(self.minute_candle(item, index) for index, item in enumerate(prior_sessions))
            + (self.minute_candle(latest, 10),),
            received_at=latest + timedelta(minutes=1),
        )
        daily_store = SchwabDailyCandleStore(self.daily_root)
        daily_store.append_history(
            tuple(
                SchwabDailyCandle(
                    symbol="AAA",
                    timestamp=item.replace(hour=16),
                    session_date=item.date().isoformat(),
                    open=90.0 + index,
                    high=92.0 + index,
                    low=89.0 + index,
                    close=91.0 + index,
                    volume=1_000_000 + index,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                )
                for index, item in enumerate(prior_sessions)
            ),
            received_at=latest + timedelta(minutes=1),
        )

    @staticmethod
    def minute_candle(timestamp: datetime, index: int) -> SchwabMinuteCandle:
        return SchwabMinuteCandle(
            symbol="AAA",
            timestamp=timestamp,
            open=100.0 + index,
            high=101.0 + index,
            low=99.0 + index,
            close=100.5 + index,
            volume=10_000 + index,
            source=SCHWAB_PRICE_HISTORY_SOURCE,
        )

    def context(self, cutoff: datetime):
        return inspect_historical_context(
            minute_store_root=self.minute_root,
            daily_store_root=self.daily_root,
            symbol="AAA",
            session_date=SESSION,
            cutoff=cutoff,
            policy=self.policy,
        )

    def member_input(
        self,
        canonical,
        *,
        cutoff: datetime,
        lifecycle=None,
        successor=None,
        existing_plan=None,
    ) -> CompositionMemberInput:
        return CompositionMemberInput(
            universe_member_id=self.member.member_id,
            canonical_evidence=canonical,
            rvol_evidence=self.rvol(cutoff),
            lifecycle=lifecycle or self.lifecycle.snapshot,
            successor_setup=successor,
            existing_plan=existing_plan,
        )

    def test_cold_symbol_backfill_runs_while_current_evidence_is_collected(self) -> None:
        cutoff = at(11, 22)
        runner_started = threading.Event()
        release_runner = threading.Event()
        current_started = threading.Event()

        def runner(_symbols: tuple[str, ...]) -> dict[str, object]:
            runner_started.set()
            self.assertTrue(release_runner.wait(2))
            self.seed_history()
            return {"status": "COMPLETE", "symbols": [{"symbol": "AAA"}]}

        def current_loader(_symbol: str, observed: datetime) -> CurrentMarketEvidence:
            current_started.set()
            return self.current(observed)

        backfill = AutomaticCandleBackfillCoordinator(
            state_path=self.root / "backfill-state.json",
            minute_store_root=self.minute_root,
            daily_store_root=self.daily_root,
            run_backfill=runner,
            utc_clock=lambda: cutoff,
        )
        admission = ContinuousHistoryAdmissionCoordinator(
            minute_store_root=self.minute_root,
            daily_store_root=self.daily_root,
            backfill=backfill,
            policy=self.policy,
        )
        first = admission.admit(
            member=self.member,
            cutoff=cutoff,
            current_evidence_loader=current_loader,
        )
        self.assertTrue(current_started.is_set())
        self.assertTrue(runner_started.wait(1))
        self.assertEqual(HISTORY_BACKFILL_PENDING, first.context.status)
        self.assertTrue(first.current_collection_started_before_backfill_admission)
        release_runner.set()
        self.assertTrue(backfill.wait_until_idle(2))
        second = admission.admit(
            member=self.member,
            cutoff=cutoff,
            current_evidence_loader=current_loader,
        )
        self.assertEqual(HISTORY_READY, second.context.status)
        self.assertEqual(1, second.context.current_session_bar_count)
        self.assertIsNotNone(second.canonical_evidence)
        evaluated = self.producer().evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                second.canonical_evidence,
                cutoff=cutoff,
                successor=self.successor(known_at=at(11, 21)),
            ),
            history_context=second.context,
            current_market_evidence=second.current_market_evidence,
            instrument_admission=self.instrument(),
            evidence_cutoff=cutoff,
            trigger="DATA_RECOVERED",
        )
        self.assertIsNotNone(evaluated.member_result.intraday_plan)

    def test_arbitrary_midday_start_uses_backfilled_context_immediately(self) -> None:
        cutoff = at(12, 17)
        self.seed_history(latest=at(12, 16))
        context, canonical = self.context(cutoff)
        result = self.producer().evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical,
                cutoff=cutoff,
                successor=self.successor(known_at=at(12, 16)),
            ),
            history_context=context,
            current_market_evidence=self.current(cutoff),
            instrument_admission=self.instrument(),
            evidence_cutoff=cutoff,
            trigger="MEMBER_PROMOTED",
        )
        self.assertEqual(HISTORY_READY, context.status)
        self.assertEqual(1, context.current_session_bar_count)
        self.assertIsNotNone(result.member_result.intraday_plan)

    def test_one_backfilled_current_bar_is_enough_without_five_new_bars(self) -> None:
        cutoff = at(11, 22)
        self.seed_history()
        context, canonical = self.context(cutoff)
        self.assertEqual(1, context.current_session_bar_count)
        result = self.producer().evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical,
                cutoff=cutoff,
                successor=self.successor(known_at=at(11, 21)),
            ),
            history_context=context,
            current_market_evidence=self.current(cutoff),
            instrument_admission=self.instrument(),
            evidence_cutoff=cutoff,
            trigger="CANONICAL_BAR_COMPLETED",
        )
        self.assertFalse(result.duplicate)
        self.assertIsNotNone(result.member_result.intraday_plan)
        self.assertTrue(result.record.execution_eligible)
        self.assertEqual(1, result.cycle.summary.plans_composed)

    def test_stale_current_session_history_is_not_ready_for_composition(self) -> None:
        self.seed_history(latest=at(11, 20))
        context, canonical = self.context(at(11, 22))
        self.assertEqual(HISTORY_INSUFFICIENT, context.status)
        self.assertIn("CANONICAL_RECENT_WINDOW_NOT_READY", context.blockers)
        self.assertIsNotNone(canonical)

    def test_future_or_tampered_current_evidence_fails_closed(self) -> None:
        cutoff = at(11, 22)
        self.seed_history()
        context, canonical = self.context(cutoff)
        future = replace(
            self.current(cutoff),
            receipt_timestamp=(cutoff + timedelta(seconds=1)).isoformat(),
        )
        with self.assertRaisesRegex(
            ContinuousTradePlanProducerError, "after the producer cutoff"
        ):
            self.producer().evaluate(
                universe_state=self.state,
                member_input=self.member_input(
                    canonical,
                    cutoff=cutoff,
                    successor=self.successor(known_at=at(11, 21)),
                ),
                history_context=context,
                current_market_evidence=future,
                instrument_admission=self.instrument(),
                evidence_cutoff=cutoff,
                trigger="SETUP_STATE_CHANGED",
            )
        tampered = replace(
            self.current(cutoff),
            market_payload_json='{"symbol":"AAA","bid":1}',
        )
        with self.assertRaisesRegex(
            ContinuousTradePlanProducerError, "payload fingerprint"
        ):
            self.producer().evaluate(
                universe_state=self.state,
                member_input=self.member_input(
                    canonical,
                    cutoff=cutoff,
                    successor=self.successor(known_at=at(11, 21)),
                ),
                history_context=context,
                current_market_evidence=tampered,
                instrument_admission=self.instrument(),
                evidence_cutoff=cutoff,
                trigger="SETUP_STATE_CHANGED",
            )

    def test_missing_instrument_authority_withholds_paper_consumable_plan(self) -> None:
        cutoff = at(11, 22)
        self.seed_history()
        context, canonical = self.context(cutoff)
        result = self.producer().evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical,
                cutoff=cutoff,
                successor=self.successor(known_at=at(11, 21)),
            ),
            history_context=context,
            current_market_evidence=self.current(cutoff),
            instrument_admission=unavailable_instrument_admission(
                "AAA", observed_at=cutoff
            ),
            evidence_cutoff=cutoff,
            trigger="CANONICAL_BAR_COMPLETED",
        )
        self.assertIsNone(result.member_result.intraday_plan)
        self.assertFalse(result.record.execution_eligible)
        self.assertIn("INSTRUMENT_CLASSIFICATION_NOT_AUTHORITATIVE", result.record.blockers)
        self.assertEqual(
            "AUTHORITATIVE_SUBTYPE_AND_LEVERAGE_CLASSIFICATION_UNAVAILABLE",
            INSTRUMENT_ADMISSION_GAP,
        )

    def test_authoritative_leveraged_product_is_explicitly_blocked(self) -> None:
        cutoff = at(11, 22)
        self.seed_history()
        context, canonical = self.context(cutoff)
        result = self.producer().evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical,
                cutoff=cutoff,
                successor=self.successor(known_at=at(11, 21)),
            ),
            history_context=context,
            current_market_evidence=self.current(cutoff),
            instrument_admission=self.instrument(LEVERAGED_ETP),
            evidence_cutoff=cutoff,
            trigger="SETUP_STATE_CHANGED",
        )
        self.assertIsNone(result.member_result.intraday_plan)
        self.assertIn(
            "INSTRUMENT_CLASS_BLOCKED:LEVERAGED_ETP", result.record.blockers
        )

    def test_completed_bar_materially_reevaluates_and_restart_is_idempotent(self) -> None:
        cutoff = at(11, 22)
        self.seed_history()
        context1, canonical1 = self.context(cutoff)
        producer = self.producer()
        first = producer.evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical1,
                cutoff=cutoff,
                successor=self.successor(known_at=at(11, 21)),
            ),
            history_context=context1,
            current_market_evidence=self.current(cutoff),
            instrument_admission=self.instrument(),
            evidence_cutoff=cutoff,
            trigger="CANONICAL_BAR_COMPLETED",
        )
        state_before = self.store_path.read_bytes()
        restarted = self.producer().evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical1,
                cutoff=cutoff,
                successor=self.successor(known_at=at(11, 21)),
            ),
            history_context=context1,
            current_market_evidence=self.current(cutoff),
            instrument_admission=self.instrument(),
            evidence_cutoff=cutoff,
            trigger="HEARTBEAT_REEVALUATION",
        )
        self.assertTrue(restarted.duplicate)
        self.assertEqual(first.record, restarted.record)
        self.assertEqual(state_before, self.store_path.read_bytes())

        next_cutoff = at(11, 23)
        SchwabCandleStore(self.minute_root).append_history(
            (self.minute_candle(at(11, 22), 11),),
            received_at=at(11, 23),
        )
        context2, canonical2 = self.context(next_cutoff)
        second = producer.evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical2,
                cutoff=next_cutoff,
                successor=self.successor(known_at=at(11, 22), generation=2),
            ),
            history_context=context2,
            current_market_evidence=self.current(next_cutoff, generation=2),
            instrument_admission=self.instrument(),
            evidence_cutoff=next_cutoff,
            trigger="CANONICAL_BAR_COMPLETED",
        )
        self.assertNotEqual(first.record.record_id, second.record.record_id)
        self.assertNotEqual(
            first.record.historical_context_fingerprint,
            second.record.historical_context_fingerprint,
        )
        self.assertEqual(context1.minute_bar_count + 1, context2.minute_bar_count)
        self.assertEqual(0, context2.provisional_bar_count)
        timestamps = tuple(item.timestamp for item in canonical2.bars)
        self.assertEqual(len(timestamps), len(set(timestamps)))

    def test_missed_plan_remains_immutable_and_successor_is_distinct(self) -> None:
        cutoff = at(11, 22)
        self.seed_history()
        context1, canonical1 = self.context(cutoff)
        producer = self.producer()
        first = producer.evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical1,
                cutoff=cutoff,
                successor=self.successor(known_at=at(11, 21)),
            ),
            history_context=context1,
            current_market_evidence=self.current(cutoff),
            instrument_admission=self.instrument(),
            evidence_cutoff=cutoff,
            trigger="SETUP_STATE_CHANGED",
        )
        original_plan = first.member_result.intraday_plan
        original_proposal = first.member_result.lifecycle_proposal
        self.lifecycle.apply(original_proposal)
        self.lifecycle.miss_current(occurred_at=at(11, 23))
        missed_plan = transition_intraday_plan(
            original_plan,
            lifecycle_status=PLAN_MISSED_ENTRY,
            observed_at=at(11, 23),
        )
        SchwabCandleStore(self.minute_root).append_history(
            (self.minute_candle(at(11, 23), 12),),
            received_at=at(11, 24),
        )
        successor_cutoff = at(11, 24)
        context2, canonical2 = self.context(successor_cutoff)
        successor = producer.evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical2,
                cutoff=successor_cutoff,
                lifecycle=self.lifecycle.snapshot,
                successor=self.successor(
                    known_at=at(11, 23),
                    family=PULLBACK,
                    predecessor=original_proposal.setup_id,
                    terminal=ENTRY_MISSED,
                    generation=2,
                ),
                existing_plan=missed_plan,
            ),
            history_context=context2,
            current_market_evidence=self.current(successor_cutoff, generation=2),
            instrument_admission=self.instrument(),
            evidence_cutoff=successor_cutoff,
            trigger="SETUP_STATE_CHANGED",
        )
        successor_plan = successor.member_result.intraday_plan
        self.assertEqual(original_proposal.setup_id, successor.record.predecessor_setup_id)
        self.assertNotEqual(first.record.setup_id, successor.record.setup_id)
        self.assertNotEqual(original_plan.plan_id, successor_plan.plan_id)
        self.assertEqual(original_plan.plan_id, successor_plan.predecessor_plan_id)
        preserved = ContinuousTradePlanProducerStore(self.store_path).load()[0]
        self.assertEqual(first.record, preserved)

    def test_missing_context_and_tampered_restart_state_fail_closed(self) -> None:
        cutoff = at(11, 22)
        context, canonical = self.context(cutoff)
        self.assertNotEqual(HISTORY_READY, context.status)
        with self.assertRaisesRegex(ContinuousTradePlanProducerError, "not ready"):
            self.producer().evaluate(
                universe_state=self.state,
                member_input=self.member_input(
                    canonical,
                    cutoff=cutoff,
                    successor=self.successor(known_at=at(11, 21)),
                ),
                history_context=context,
                current_market_evidence=self.current(cutoff),
                instrument_admission=self.instrument(),
                evidence_cutoff=cutoff,
                trigger="DATA_RECOVERED",
            )
        self.store_path.write_text('{"schemaVersion":1,"profile":"bad","records":[]}', encoding="ascii")
        with self.assertRaisesRegex(ContinuousTradePlanProducerError, "unsupported"):
            ContinuousTradePlanProducerStore(self.store_path).load()

    def test_conflicting_duplicate_record_fails_closed(self) -> None:
        cutoff = at(11, 22)
        self.seed_history()
        context, canonical = self.context(cutoff)
        result = self.producer().evaluate(
            universe_state=self.state,
            member_input=self.member_input(
                canonical,
                cutoff=cutoff,
                successor=self.successor(known_at=at(11, 21)),
            ),
            history_context=context,
            current_market_evidence=self.current(cutoff),
            instrument_admission=self.instrument(),
            evidence_cutoff=cutoff,
            trigger="CANONICAL_BAR_COMPLETED",
        )
        forged = replace(result.record, blockers=("FORGED",))
        with self.assertRaises(ContinuousTradePlanProducerError):
            ContinuousTradePlanProducerStore(self.store_path).append(forged)

    def test_producer_module_has_no_broker_account_or_order_capability(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "continuous_tradeplan_producer.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(
            any(
                token in name.lower()
                for name in imports
                for token in ("broker", "account", "paper", "shadow", "order")
            )
        )
        calls = {
            node.func.attr.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(
            calls.intersection(
                {
                    "submit_order",
                    "cancel_order",
                    "replace_order",
                    "get_account",
                    "get_positions",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
