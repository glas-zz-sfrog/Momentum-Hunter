from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.broad_discovery import (
    DiscoveryQueryIdentity,
    DiscoverySourceRow,
    build_discovery_snapshot,
)
from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_CONFIRMED,
    ENTRY_MISSED,
    PULLBACK_FORMING,
    WATCHING,
)
from momentum_hunter.continuous_composition import (
    CompositionMemberInput,
    ContinuousCompositionPolicy,
)
from momentum_hunter.continuous_live_qualification import (
    LiveCompositionSource,
    LiveDenominatorSource,
    LiveDiscoverySource,
    LiveMaterialEvents,
    QualificationState,
)
from momentum_hunter.continuous_runtime import (
    CANONICAL_BAR_COMPLETED,
    WRITER_ACCEPTED,
    CompositionRequest,
    ContinuousOpportunityRuntime,
    ContinuousRuntimeConfig,
    DiscoveryPulse,
    LogicalRuntimeLeaseRegistry,
    QueueCapacities,
    ReadinessResult,
    RuntimeCadence,
    RuntimeCheckpointStore,
)
from momentum_hunter.continuous_tradeplan_producer import (
    build_current_market_evidence,
    inspect_historical_context,
    unavailable_instrument_admission,
)
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE
from momentum_hunter.hot_universe import (
    HotUniversePolicy,
    HotUniverseStore,
    apply_discovery_snapshot,
)
from momentum_hunter.intraday_trade_plan import PULLBACK
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


class ContinuousNaturalSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.minute_root = self.root / "market-data" / "minute"
        self.daily_root = self.root / "market-data" / "daily"
        self.snapshot, self.universe = self._universe()
        self.member = self.universe.state.members[0]
        self.state = QualificationState(
            root=self.root,
            launch_at=at(11, 0),
            configuration_fingerprint=CONFIGURATION,
        )
        self.state.snapshot = self.snapshot
        self.state.universe = HotUniverseStore(
            self.root / "state" / "hot-universe.json",
            allow_persistent=True,
        ).apply_snapshot(
            policy=HotUniversePolicy(maximum_hot_symbols=1),
            snapshot=self.snapshot,
            recorded_at=at(11, 0),
        )
        self.universe = self.state.universe
        self.member = self.universe.state.members[0]
        discovery_path = (
            self.root
            / "source-evidence"
            / "finviz"
            / f"{self.snapshot.snapshot_id}.json"
        )
        discovery_path.parent.mkdir(parents=True, exist_ok=True)
        discovery_path.write_text(self.snapshot.canonical_json(), encoding="ascii")
        self._seed_prior_history()
        self._append_initial_sequence()

    def _universe(self):
        observed = at(11, 0)
        row = DiscoverySourceRow.from_mapping(
            source_row_ordinal=1,
            source_row_identity=f"finviz:AAA:{observed.isoformat()}",
            source_values={"Ticker": "AAA", "No.": "1"},
            candidate=Candidate(
                ticker="AAA",
                company="AAA Incorporated",
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
            source_version="natural-producer-test-v1",
            requested_at=observed - timedelta(seconds=2),
            received_at=observed - timedelta(seconds=1),
            evaluated_at=observed,
            query_identity=DiscoveryQueryIdentity.from_criteria(
                INSTITUTIONAL_MOMENTUM,
                source_query="synthetic://natural-producer",
                sort_order="-volume",
            ),
            source_contract_fingerprint="b" * 64,
            semantic_plausibility_fingerprint="c" * 64,
            source_rows=(row,),
        )
        universe = apply_discovery_snapshot(
            None,
            policy=HotUniversePolicy(maximum_hot_symbols=1),
            snapshot=snapshot,
        )
        return snapshot, universe

    def _seed_prior_history(self) -> None:
        prior = tuple(
            datetime(2026, 8, day, 11, 0, tzinfo=EASTERN_TZ)
            for day in (11, 12, 13, 14)
        )
        minute_store = SchwabCandleStore(self.minute_root)
        minute_store.append_history(
            tuple(
                SchwabMinuteCandle(
                    symbol="AAA",
                    timestamp=timestamp,
                    open=95.0,
                    high=95.2,
                    low=94.8,
                    close=95.0,
                    volume=100.0,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                )
                for timestamp in prior
            ),
            received_at=at(11, 0),
        )
        SchwabDailyCandleStore(self.daily_root).append_history(
            tuple(
                SchwabDailyCandle(
                    symbol="AAA",
                    timestamp=timestamp.replace(hour=16),
                    session_date=timestamp.date().isoformat(),
                    open=94.0,
                    high=96.0,
                    low=93.0,
                    close=95.0,
                    volume=1_000_000,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                )
                for timestamp in prior
            ),
            received_at=at(11, 0),
        )

    def _append_initial_sequence(self) -> None:
        bars = [
            SchwabMinuteCandle(
                symbol="AAA",
                timestamp=at(11, minute),
                open=99.9,
                high=100.0,
                low=99.8,
                close=99.9,
                volume=100.0,
                source=SCHWAB_PRICE_HISTORY_SOURCE,
            )
            for minute in range(20)
        ]
        bars.append(
            SchwabMinuteCandle(
                symbol="AAA",
                timestamp=at(11, 20),
                open=100.15,
                high=100.3,
                low=100.11,
                close=100.2,
                volume=200.0,
                source=SCHWAB_PRICE_HISTORY_SOURCE,
            )
        )
        SchwabCandleStore(self.minute_root).append_history(
            tuple(bars), received_at=at(11, 21)
        )

    def _rvol(self, cutoff: datetime) -> TimeNormalizedRvolEvidence:
        return TimeNormalizedRvolEvidence(
            status=EXECUTION_ELIGIBLE,
            symbol="AAA",
            session_date=SESSION,
            through_minute=(cutoff - timedelta(minutes=1)).isoformat(),
            baseline_session_count=5,
            minimum_baseline_sessions=5,
            target_baseline_sessions=20,
            observed_volume=2_200,
            expected_volume=1_800.0,
            relative_volume=1.22,
        )

    def _prepare(self, cutoff: datetime, *, generation: int) -> None:
        context, canonical = inspect_historical_context(
            minute_store_root=self.minute_root,
            daily_store_root=self.daily_root,
            symbol="AAA",
            session_date=SESSION,
            cutoff=cutoff,
            policy=ContinuousCompositionPolicy(required_recent_minute_bars=1),
        )
        self.state.historical_contexts["AAA"] = context
        self.state.current_market_evidence["AAA"] = build_current_market_evidence(
            symbol="AAA",
            provider_timestamp=(cutoff - timedelta(seconds=5)).isoformat(),
            receipt_timestamp=cutoff.isoformat(),
            source_identity="synthetic-read-only-current-market",
            market_payload={"symbol": "AAA", "generation": generation},
        )
        self.state.instrument_admissions["AAA"] = unavailable_instrument_admission(
            "AAA", observed_at=cutoff
        )
        self.state.readiness_inputs["AAA"] = CompositionMemberInput(
            universe_member_id=self.member.member_id,
            canonical_evidence=canonical,
            rvol_evidence=self._rvol(cutoff),
        )

    def _request(self, cutoff: datetime, *, generation: int) -> CompositionRequest:
        material = fingerprint(("material", generation))
        self.state.material_event_fingerprints["AAA"] = material
        return CompositionRequest(
            request_id=f"natural-request-{generation}",
            symbol="AAA",
            trigger=CANONICAL_BAR_COMPLETED,
            requested_at=cutoff.isoformat(),
            readiness_fingerprint=fingerprint(("readiness", generation)),
        )

    def test_natural_runtime_owns_missed_entry_and_distinct_pullback_successor(self) -> None:
        first_cutoff = at(11, 21)
        source = LiveCompositionSource(self.state)
        self._prepare(first_cutoff, generation=1)
        first = source.compose(self._request(first_cutoff, generation=1))
        first_payload = json.loads(first.evidence_payload_json)
        first_types = [item["eventType"] for item in first_payload["naturalSteps"]]
        self.assertIn("BREAKOUT_CONFIRMED", first_types)
        self.assertIn("ENTRY_MISSED", first_types)
        lifecycle_states = [
            item.next_state for item in source.natural_setup.lifecycle.store.load().events
        ]
        self.assertIn(BREAKOUT_CONFIRMED, lifecycle_states)
        first_plans = [
            item["producerRecord"]["compositionCycle"]["member_results"][0][
                "intraday_plan"
            ]
            for item in first_payload["naturalSteps"]
            if item["producerRecord"]["compositionCycle"]["member_results"][0][
                "intraday_plan"
            ]
            is not None
        ]
        missed = next(item for item in first_plans if item["lifecycle_status"] == "MISSED_ENTRY")
        missed_setup_id = next(
            item["producerRecord"]["compositionCycle"]["member_results"][0][
                "lifecycle_proposal"
            ]["setup_id"]
            for item in first_payload["naturalSteps"]
            if item["producerRecord"]["compositionCycle"]["member_results"][0][
                "intraday_plan"
            ]
            and item["producerRecord"]["compositionCycle"]["member_results"][0][
                "intraday_plan"
            ]["plan_id"]
            == missed["plan_id"]
        )
        self.assertIn(
            "INSTRUMENT_CLASSIFICATION_UNAVAILABLE",
            next(
                item["producerRecord"]["blockers"]
                for item in first_payload["naturalSteps"]
                if item["producerRecord"]["compositionCycle"]["member_results"][0][
                    "intraday_plan"
                ]
                and item["producerRecord"]["compositionCycle"]["member_results"][0][
                    "intraday_plan"
                ]["plan_id"]
                == missed["plan_id"]
            ),
        )

        SchwabCandleStore(self.minute_root).append_history(
            (
                SchwabMinuteCandle(
                    symbol="AAA",
                    timestamp=at(11, 21),
                    open=100.1,
                    high=100.15,
                    low=100.03,
                    close=100.05,
                    volume=100.0,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                ),
            ),
            received_at=at(11, 22),
        )
        second_cutoff = at(11, 22)
        self._prepare(second_cutoff, generation=2)
        second = source.compose(self._request(second_cutoff, generation=2))
        second_payload = json.loads(second.evidence_payload_json)
        pullback_step = next(
            item
            for item in second_payload["naturalSteps"]
            if item["eventType"] == "PULLBACK_FORMING"
        )
        result = pullback_step["producerRecord"]["compositionCycle"]["member_results"][0]
        successor = result["intraday_plan"]
        proposal = result["lifecycle_proposal"]
        self.assertEqual(PULLBACK, successor["setup_family"])
        self.assertEqual(missed["plan_id"], successor["predecessor_plan_id"])
        self.assertNotEqual(missed["plan_id"], successor["plan_id"])
        self.assertEqual(proposal["predecessor_setup_id"], missed_setup_id)
        lifecycle = source.natural_setup.lifecycle.snapshot(proposal["opportunity_id"])
        self.assertEqual(PULLBACK_FORMING, lifecycle.current_state)
        self.assertNotEqual(proposal["setup_id"], proposal["predecessor_setup_id"])

    def test_completed_bar_dispatch_and_restart_are_idempotent(self) -> None:
        cutoff = at(11, 21)
        source = LiveCompositionSource(self.state)
        self._prepare(cutoff, generation=1)
        request = self._request(cutoff, generation=1)
        first = source.compose(request)
        before = source.producer_store.load()

        class Backfill:
            def request(self, symbol: str, *, reason: str):
                return {"symbol": symbol, "status": "COMPLETE", "reason": reason}

            def status(self, symbol: str):
                return None

        events = LiveMaterialEvents(
            self.state,
            Backfill(),
            natural_setup=source.natural_setup,
        )
        self.assertEqual((), events.poll(cutoff))
        SchwabCandleStore(self.minute_root).append_history(
            (
                SchwabMinuteCandle(
                    symbol="AAA",
                    timestamp=at(11, 21),
                    open=100.1,
                    high=100.15,
                    low=100.03,
                    close=100.05,
                    volume=100.0,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                ),
            ),
            received_at=at(11, 22),
        )
        emitted = events.poll(at(11, 22))
        self.assertEqual(1, len(emitted))
        self.assertEqual(CANONICAL_BAR_COMPLETED, emitted[0].trigger)
        self.assertEqual(at(11, 22).isoformat(), emitted[0].occurred_at)

        restarted = LiveCompositionSource(self.state)
        duplicate = restarted.compose(request)
        self.assertEqual(first.cycle_id, duplicate.cycle_id)
        self.assertEqual(before, restarted.producer_store.load())
        lifecycle = restarted.natural_setup.lifecycle.snapshot(
            restarted.natural_setup.lifecycle.store.load().events[0].opportunity_id
        )
        self.assertEqual(ENTRY_MISSED, lifecycle.current_state)

    def test_late_process_start_does_not_replay_earlier_intraday_setups(self) -> None:
        flat_bars = []
        timestamp = at(11, 21)
        while timestamp <= at(12, 16):
            flat_bars.append(
                SchwabMinuteCandle(
                    symbol="AAA",
                    timestamp=timestamp,
                    open=100.0,
                    high=100.05,
                    low=99.95,
                    close=100.0,
                    volume=100.0,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                )
            )
            timestamp += timedelta(minutes=1)
        SchwabCandleStore(self.minute_root).append_history(
            tuple(flat_bars),
            received_at=at(12, 17),
        )
        self.state.launch_at = at(12, 17)
        cutoff = at(12, 17)
        self._prepare(cutoff, generation=9)
        source = LiveCompositionSource(self.state)

        result = source.compose(self._request(cutoff, generation=9))
        payload = json.loads(result.evidence_payload_json)

        self.assertFalse(
            [item for item in payload["naturalSteps"] if item["eventId"]]
        )
        lifecycle = source.natural_setup.lifecycle.snapshots()[
            source.natural_setup.lifecycle.store.load().events[0].opportunity_id
        ]
        self.assertEqual(WATCHING, lifecycle.current_state)
        self.assertIsNone(result.plan_id)

    def test_future_receipt_is_not_dispatched_before_it_is_known(self) -> None:
        cutoff = at(11, 21)
        source = LiveCompositionSource(self.state)
        self._prepare(cutoff, generation=1)
        source.compose(self._request(cutoff, generation=1))
        SchwabCandleStore(self.minute_root).append_history(
            (
                SchwabMinuteCandle(
                    symbol="AAA",
                    timestamp=at(11, 21),
                    open=100.1,
                    high=100.15,
                    low=100.03,
                    close=100.05,
                    volume=100.0,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                ),
            ),
            received_at=at(11, 23),
        )

        class Backfill:
            def request(self, symbol: str, *, reason: str):
                return {"symbol": symbol, "status": "COMPLETE", "reason": reason}

            def status(self, symbol: str):
                return None

        events = LiveMaterialEvents(
            self.state,
            Backfill(),
            natural_setup=source.natural_setup,
        )
        self.assertEqual((), events.poll(at(11, 22)))
        emitted = events.poll(at(11, 23))
        self.assertEqual(1, len(emitted))
        self.assertEqual(at(11, 23).isoformat(), emitted[0].occurred_at)

    def test_fresh_process_restores_universe_and_preserves_predecessor_chain(self) -> None:
        first_cutoff = at(11, 21)
        first_source = LiveCompositionSource(self.state)
        self._prepare(first_cutoff, generation=1)
        first_source.compose(self._request(first_cutoff, generation=1))
        missed_plan = first_source.natural_setup.latest_plan(self.member.member_id)
        self.assertIsNotNone(missed_plan)
        self.assertEqual("MISSED_ENTRY", missed_plan.lifecycle_status)

        SchwabCandleStore(self.minute_root).append_history(
            (
                SchwabMinuteCandle(
                    symbol="AAA",
                    timestamp=at(11, 21),
                    open=100.1,
                    high=100.15,
                    low=100.03,
                    close=100.05,
                    volume=100.0,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                ),
            ),
            received_at=at(11, 22),
        )
        restarted_state = QualificationState(
            root=self.root,
            launch_at=at(11, 22),
            allow_persistent=True,
            configuration_fingerprint=CONFIGURATION,
        )
        LiveDiscoverySource(restarted_state)
        self.assertIsNotNone(restarted_state.universe)
        self.assertEqual(self.member.member_id, restarted_state.universe.state.members[0].member_id)
        self.state = restarted_state
        self.universe = restarted_state.universe
        self.member = restarted_state.universe.state.members[0]
        self._prepare(at(11, 22), generation=2)
        restarted_source = LiveCompositionSource(restarted_state)

        result = restarted_source.compose(self._request(at(11, 22), generation=2))
        payload = json.loads(result.evidence_payload_json)
        pullback = next(
            item["producerRecord"]["compositionCycle"]["member_results"][0]
            for item in payload["naturalSteps"]
            if item["eventType"] == "PULLBACK_FORMING"
        )
        self.assertEqual(missed_plan.plan_id, pullback["intraday_plan"]["predecessor_plan_id"])
        records = restarted_source.producer_store.load()
        self.assertEqual(len(records), len({item.record_id for item in records}))
        self.assertEqual(
            ENTRY_MISSED,
            next(
                event.previous_state
                for event in restarted_source.natural_setup.lifecycle.store.load().events
                if event.next_state == PULLBACK_FORMING
            ),
        )

    def test_natural_setup_owner_has_no_broker_account_or_order_capability(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "continuous_natural_setup.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(
            imports.intersection(
                {
                    "momentum_hunter.alpaca_paper_broker",
                    "momentum_hunter.alpaca_paper_engineering",
                    "momentum_hunter.shadow_selection",
                    "momentum_hunter.shadow_opening",
                }
            )
        )
        calls = {
            node.func.attr.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(
            calls.intersection(
                {"submit_order", "cancel_order", "replace_order", "get_account"}
            )
        )

    def test_continuous_runtime_naturally_reaches_tradeplan_evidence(self) -> None:
        cutoff = at(11, 21)
        test = self

        class Discovery:
            def discover(self, request):
                return DiscoveryPulse(
                    pulse_id=test.snapshot.snapshot_id,
                    fingerprint=test.snapshot.fingerprint,
                    source_rows_represented=1,
                    symbols_for_readiness=("AAA",),
                    new_symbols=("AAA",),
                    retained_symbols=(),
                    provider_bound_symbols=(),
                    evidence_payload_json=test.snapshot.canonical_json(),
                )

        class Market:
            def evaluate(self, request):
                test._prepare(cutoff, generation=1)
                source = fingerprint(("runtime-readiness", request.request_id))
                test.state.material_event_fingerprints[request.symbol] = source
                return ReadinessResult(
                    request_id=request.request_id,
                    symbol=request.symbol,
                    status="READY",
                    fingerprint=source,
                    ready=True,
                )

        class Events:
            def poll(self, now):
                return ()

        class Writer:
            def __init__(self):
                self.intents = []

            def write_intent(self, intent):
                self.intents.append(intent)
                return WRITER_ACCEPTED

        writer = Writer()
        runtime = ContinuousOpportunityRuntime(
            config=ContinuousRuntimeConfig(
                runtime_identity="natural-runtime-acceptance",
                session_date=SESSION,
                cadence=RuntimeCadence(
                    broad_discovery_seconds=300,
                    housekeeping_seconds=30,
                    discovery_stale_seconds=600,
                    composition_stale_seconds=180,
                ),
                queues=QueueCapacities(),
                lease_ttl_seconds=30,
                shutdown_timeout_seconds=2,
            ),
            runtime_instance_id="natural-runtime-instance",
            discovery_source=Discovery(),
            market_data_source=Market(),
            event_source=Events(),
            composition_source=LiveCompositionSource(self.state),
            denominator_source=LiveDenominatorSource(self.state),
            writer=writer,
            lease_registry=LogicalRuntimeLeaseRegistry(),
            checkpoint_store=RuntimeCheckpointStore(self.root / "runtime-checkpoint"),
        )

        runtime.start(cutoff)
        health = runtime.tick(cutoff, work_budget=512)
        runtime.shutdown(cutoff)

        self.assertGreater(health.composition_cycles, 0)
        composition_payloads = [
            json.loads(item.payload_json)
            for item in writer.intents
            if item.evidence_type == "COMPOSITION_CYCLE"
        ]
        self.assertTrue(composition_payloads)
        self.assertTrue(
            any(
                payload.get("profile") == "continuous-natural-composition-chain-v1"
                and any(
                    step["producerRecord"]["compositionCycle"]["member_results"][0][
                        "intraday_plan"
                    ]
                    for step in payload["naturalSteps"]
                )
                for payload in composition_payloads
            )
        )


if __name__ == "__main__":
    unittest.main()
