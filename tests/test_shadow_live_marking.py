from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.engine_host import EngineHostRuntime
from momentum_hunter.schwab_market_data import SCHWAB_QUOTE_SOURCE
from momentum_hunter.shadow_market_validity import ShadowMarketValidityPolicy
from momentum_hunter.shadow_trading import (
    ShadowExecutionPolicy,
    ShadowQuote,
    ShadowStateError,
    ShadowStateStore,
    ShadowTradingService,
    build_executable_mark,
    build_shadow_sample_metadata,
    shadow_executable_mark_to_dict,
)
from momentum_hunter.workstation_shadow import (
    ShadowWorkspacePaths,
    ShadowWorkspaceService,
)
from tests.test_shadow_trading import at, quote, report_payload


class RecordingQuoteSource:
    def __init__(self, quotes: dict[str, dict]) -> None:
        self.values = quotes
        self.calls: list[tuple[tuple[str, ...], datetime]] = []

    def quotes(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime,
    ) -> dict[str, dict]:
        self.calls.append((tuple(symbols), decision_at))
        return {
            symbol: dict(self.values[symbol])
            for symbol in symbols
            if symbol in self.values
        }


class BlockingQuoteSource(RecordingQuoteSource):
    def __init__(self, quotes: dict[str, dict]) -> None:
        super().__init__(quotes)
        self.entered = threading.Event()
        self.release = threading.Event()

    def quotes(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime,
    ) -> dict[str, dict]:
        self.calls.append((tuple(symbols), decision_at))
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("Synthetic quote source was not released.")
        return {
            symbol: dict(self.values[symbol])
            for symbol in symbols
            if symbol in self.values
        }


class ShadowLiveMarkingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report = self.root / "trade-plan.json"
        self.state = self.root / "shadow-state.json"
        self.report.write_text(
            json.dumps(report_payload()),
            encoding="utf-8",
        )
        self.service = ShadowTradingService(
            store=ShadowStateStore(self.state),
            policy=ShadowExecutionPolicy(
                slippage_bps=0,
                minimum_fill_delay_seconds=1,
            ),
        )
        self.service.start_trade(
            self.report,
            symbol="TEST",
            simulation_command_id="shadow-live-mark",
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fill(self) -> None:
        self.service.process_quote(
            quote(
                "2026-07-23T10:00:05-05:00",
                bid=9.94,
                ask=9.95,
            ),
            received_at=at("2026-07-23T10:00:05-05:00"),
        )

    def review_mark(self, observed_at: str) -> dict:
        trade = self.service.store.load().trades[0]
        return shadow_executable_mark_to_dict(
            trade,
            observed_at=at(observed_at),
        )

    def host_runtime(
        self,
        *,
        mark_runner,
        cycle_runner=lambda: None,
        collection_interval_seconds: int = 60,
        active_mark_interval_seconds: int = 1,
    ) -> EngineHostRuntime:
        return EngineHostRuntime(
            collection_interval_seconds=collection_interval_seconds,
            active_mark_interval_seconds=active_mark_interval_seconds,
            cycle_runner=cycle_runner,
            external_monitor_running=lambda: False,
            workspace_snapshot_loader=lambda: {},
            simulation_workspace_loader=lambda: {},
            simulation_runner=lambda _symbol: {},
            chart_snapshot_loader=lambda _symbol, _interval: {},
            shadow_workspace_loader=lambda: {},
            shadow_starter=lambda _symbol, _command: {},
            shadow_observation_runner=lambda: {},
            shadow_active_mark_runner=mark_runner,
            technical_research_snapshot_loader=lambda _symbol: {},
            saved_watchlist_snapshot_loader=lambda: {},
            daily_workflow_snapshot_loader=lambda: {},
            candidate_story_loader=lambda _symbol: {},
            research_maturity_loader=lambda: {},
        )

    def test_long_mark_uses_bid_for_pnl_r_mfe_mae_and_distances(self) -> None:
        self.fill()
        self.service.process_quote(
            quote(
                "2026-07-23T10:00:10-05:00",
                bid=10.20,
                ask=10.21,
                high=99.0,
                low=1.0,
            ),
            received_at=at("2026-07-23T10:00:10-05:00"),
        )

        mark = self.review_mark("2026-07-23T10:00:10-05:00")

        self.assertEqual("AHEAD", mark["displayState"])
        self.assertEqual(10.20, mark["currentExecutableMark"])
        self.assertEqual(0.50, mark["unrealizedPnl"])
        self.assertEqual(0.5556, mark["unrealizedR"])
        self.assertEqual(0.50, mark["mfeDollars"])
        self.assertEqual(-0.02, mark["maeDollars"])
        self.assertEqual(0.70, mark["distanceToStop"])
        self.assertEqual(0.30, mark["distanceToNextTarget"])

    def test_short_mark_helper_uses_ask_and_never_last_or_midpoint(self) -> None:
        self.fill()
        long_trade = self.service.store.load().trades[0]
        short_position = replace(
            long_trade.position,
            direction="SHORT",
            average_entry_price=10.00,
            stop_price=10.50,
            target_price=9.50,
            highest_price=10.00,
            lowest_price=9.80,
        )
        short_trade = replace(long_trade, position=short_position)
        supplied = ShadowQuote(
            symbol="TEST",
            timestamp="2026-07-23T10:00:10-05:00",
            bid=9.00,
            ask=9.80,
            last=1.00,
            session="regular",
            trading_state="tradable",
            source="synthetic-test",
        )

        mark = build_executable_mark(
            short_trade,
            supplied,
            received_at=at("2026-07-23T10:00:10-05:00"),
        )

        self.assertEqual("SHORT", mark.direction)
        self.assertEqual(9.80, mark.executable_mark)
        self.assertEqual(0.40, mark.unrealized_pnl)
        self.assertEqual(0.40, mark.unrealized_r)

    def test_working_order_has_no_pnl_and_open_labels_are_not_final(self) -> None:
        self.service.process_quote(
            quote(
                "2026-07-23T10:00:05-05:00",
                bid=10.04,
                ask=10.05,
            ),
            received_at=at("2026-07-23T10:00:05-05:00"),
        )

        mark = self.review_mark("2026-07-23T10:00:05-05:00")

        self.assertEqual("WORKING", mark["displayState"])
        self.assertIsNone(mark["simulatedFill"])
        self.assertIsNone(mark["currentExecutableMark"])
        self.assertIsNone(mark["unrealizedPnl"])
        self.assertIsNone(mark["unrealizedR"])
        self.assertNotIn(mark["displayState"], {"WINNER", "LOSER"})

    def test_ahead_behind_flat_stale_and_halted_states_fail_closed(self) -> None:
        self.fill()
        fill_price = self.service.store.load().trades[0].position.average_entry_price
        cases = (
            ("2026-07-23T10:00:06-05:00", fill_price + 0.10, "AHEAD"),
            ("2026-07-23T10:00:07-05:00", fill_price - 0.10, "BEHIND"),
            ("2026-07-23T10:00:08-05:00", fill_price, "FLAT"),
        )
        for timestamp, bid, expected in cases:
            self.service.process_quote(
                quote(timestamp, bid=bid, ask=bid + 0.01),
                received_at=at(timestamp),
            )
            self.assertEqual(expected, self.review_mark(timestamp)["displayState"])

        stale = self.review_mark("2026-07-23T10:00:19-05:00")
        self.assertEqual("STALE", stale["displayState"])
        self.assertIsNone(stale["unrealizedPnl"])
        self.assertIsNone(stale["unrealizedR"])
        preserved = stale["currentExecutableMark"]

        self.service.process_quote(
            quote(
                "2026-07-23T10:00:20-05:00",
                bid=fill_price + 0.20,
                ask=fill_price + 0.21,
                trading_state="halted",
            ),
            received_at=at("2026-07-23T10:00:20-05:00"),
        )
        halted = self.review_mark("2026-07-23T10:00:20-05:00")
        self.assertEqual("HALTED", halted["displayState"])
        self.assertEqual(preserved, halted["currentExecutableMark"])
        self.assertIsNone(halted["unrealizedPnl"])
        self.assertIsNone(halted["unrealizedR"])

    def test_duplicate_restart_and_completed_trade_are_immutable(self) -> None:
        self.fill()
        mark_quote = quote(
            "2026-07-23T10:00:10-05:00",
            bid=10.20,
            ask=10.21,
        )
        self.service.process_quote(
            mark_quote,
            received_at=at("2026-07-23T10:00:10-05:00"),
        )
        before = self.service.store.load().trades[0]
        self.service.process_quote(
            mark_quote,
            received_at=at("2026-07-23T10:00:11-05:00"),
        )
        duplicate = self.service.store.load().trades[0]
        self.assertEqual(before, duplicate)

        restarted = ShadowTradingService(
            store=ShadowStateStore(self.state),
            policy=self.service.policy,
        )
        reloaded = restarted.store.load().trades[0]
        self.assertEqual(before.position.highest_price, reloaded.position.highest_price)
        self.assertEqual(before.position.lowest_price, reloaded.position.lowest_price)
        self.assertEqual(before.executable_mark, reloaded.executable_mark)

        persisted = json.loads(self.state.read_text(encoding="utf-8"))
        for field_name, bad_value, expected_message in (
            (
                "direction",
                "SHORT",
                "executable mark direction does not match",
            ),
            (
                "executable_mark",
                999.0,
                "executable mark does not match the persisted bid/ask side",
            ),
        ):
            with self.subTest(tampered_field=field_name):
                tampered = json.loads(json.dumps(persisted))
                tampered["trades"][0]["executable_mark"][field_name] = bad_value
                self.state.write_text(
                    json.dumps(tampered),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ShadowStateError, expected_message):
                    restarted.store.load()
        self.state.write_text(json.dumps(persisted), encoding="utf-8")

        restarted.process_quote(
            quote(
                "2026-07-23T10:00:15-05:00",
                bid=10.50,
                ask=10.51,
            ),
            received_at=at("2026-07-23T10:00:15-05:00"),
        )
        completed = restarted.store.load().trades[0]
        restarted.process_quote(
            quote(
                "2026-07-23T10:00:16-05:00",
                bid=9.00,
                ask=9.01,
            ),
            received_at=at("2026-07-23T10:00:16-05:00"),
        )
        self.assertEqual(completed, restarted.store.load().trades[0])

    def test_active_workspace_does_not_poll_without_official_work(self) -> None:
        source = RecordingQuoteSource({})
        empty_service = ShadowTradingService(
            store=ShadowStateStore(self.root / "empty-state.json"),
        )
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                self.root,
                self.root / "observations.json",
                self.root / "empty-state.json",
            ),
            service=empty_service,
            quote_source=source,
        )

        result = workspace.advance_active_marks(
            received_at=at("2026-07-23T10:00:05-05:00"),
        )

        self.assertFalse(result["polled"])
        self.assertEqual(0, result["providerRequestCount"])
        self.assertEqual([], source.calls)

    def test_active_workspace_requests_only_official_symbol_from_schwab_boundary(self) -> None:
        definition = build_shadow_sample_metadata(
            self.service.policy,
            sample_version="synthetic-live-mark-v2",
            official_sample_authorized=True,
        )
        state = self.service.store.load()
        trade = state.trades[0]
        official_ticket = replace(
            trade.ticket,
            sample_version=definition.sample_version,
            strategy_configuration_fingerprint=(
                definition.strategy_configuration_fingerprint
            ),
            fill_model_version=definition.fill_model_version,
            evidence_schema_version=definition.evidence_schema_version,
        )
        official_trade = replace(
            trade,
            sample_metadata=definition,
            ticket=official_ticket,
        )
        self.service.store.save(replace(state, trades=(official_trade,)))
        self.service.sample_definition = definition
        request_at = at("2026-07-23T10:00:05-05:00")
        receipt_at = at("2026-07-23T10:00:07-05:00")
        source = RecordingQuoteSource(
            {
                "TEST": {
                    "symbol": "TEST",
                    "timestamp": request_at.isoformat(),
                    "provider_quote_timestamp": request_at.isoformat(),
                    "provider_bid_timestamp": request_at.isoformat(),
                    "provider_ask_timestamp": request_at.isoformat(),
                    "bid": 9.94,
                    "ask": 9.95,
                    "last": 99.00,
                    "volume": 1_000,
                    "session": "regular",
                    "trading_state": "tradable",
                    "realtime": True,
                    "security_status": "Normal",
                    "source": SCHWAB_QUOTE_SOURCE,
                }
            }
        )
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                self.root,
                self.root / "observations.json",
                self.state,
            ),
            service=self.service,
            quote_source=source,
        )

        with patch(
            "momentum_hunter.workstation_shadow.now_central",
            side_effect=(request_at, receipt_at),
        ):
            result = workspace.advance_active_marks()

        self.assertTrue(result["polled"])
        self.assertEqual(1, result["providerRequestCount"])
        self.assertEqual([(("TEST",), request_at)], source.calls)
        self.assertEqual(["TEST"], result["requestedSymbols"])
        persisted = self.service.store.load().trades[0]
        self.assertEqual(
            receipt_at.isoformat(),
            persisted.executable_mark.receipt_timestamp,
        )
        self.assertEqual("open", result["snapshot"]["trades"][0]["status"])
        self.assertFalse(result["snapshot"]["transmitting"])

    def test_active_workspace_rejects_noncanonical_quote_source_without_fill(self) -> None:
        definition = build_shadow_sample_metadata(
            self.service.policy,
            sample_version="synthetic-live-mark-v2",
            official_sample_authorized=True,
        )
        state = self.service.store.load()
        trade = state.trades[0]
        official_trade = replace(
            trade,
            sample_metadata=definition,
            ticket=replace(
                trade.ticket,
                sample_version=definition.sample_version,
                strategy_configuration_fingerprint=(
                    definition.strategy_configuration_fingerprint
                ),
                fill_model_version=definition.fill_model_version,
                evidence_schema_version=definition.evidence_schema_version,
            ),
        )
        self.service.store.save(replace(state, trades=(official_trade,)))
        self.service.sample_definition = definition
        received_at = at("2026-07-23T10:00:05-05:00")
        source = RecordingQuoteSource(
            {
                "TEST": {
                    "symbol": "TEST",
                    "timestamp": received_at.isoformat(),
                    "bid": 9.94,
                    "ask": 9.95,
                    "session": "regular",
                    "trading_state": "tradable",
                    "source": "unapproved-provider",
                }
            }
        )
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                self.root,
                self.root / "observations.json",
                self.state,
            ),
            service=self.service,
            quote_source=source,
        )

        result = workspace.advance_active_marks(received_at=received_at)
        rejected = self.service.store.load().trades[0]

        self.assertEqual(["TEST"], result["invalidQuoteSymbols"])
        self.assertEqual(["TEST"], result["missingQuoteSymbols"])
        self.assertEqual("pending_entry", rejected.status)
        self.assertIsNone(rejected.position)
        self.assertEqual("UNAVAILABLE", rejected.executable_mark.condition)
        self.assertEqual("quote_rejected", rejected.ledger_events[-1].event_type)
        self.assertFalse(result["snapshot"]["transmitting"])

    def test_read_only_snapshot_remains_available_during_slow_active_quote(self) -> None:
        definition = build_shadow_sample_metadata(
            self.service.policy,
            sample_version="synthetic-live-mark-v2",
            official_sample_authorized=True,
        )
        state = self.service.store.load()
        trade = state.trades[0]
        official_trade = replace(
            trade,
            sample_metadata=definition,
            ticket=replace(
                trade.ticket,
                sample_version=definition.sample_version,
                strategy_configuration_fingerprint=(
                    definition.strategy_configuration_fingerprint
                ),
                fill_model_version=definition.fill_model_version,
                evidence_schema_version=definition.evidence_schema_version,
            ),
        )
        self.service.store.save(replace(state, trades=(official_trade,)))
        self.service.sample_definition = definition
        observed_at = at("2026-07-23T10:00:05-05:00")
        source = BlockingQuoteSource(
            {
                "TEST": {
                    "symbol": "TEST",
                    "timestamp": observed_at.isoformat(),
                    "provider_quote_timestamp": observed_at.isoformat(),
                    "provider_bid_timestamp": observed_at.isoformat(),
                    "provider_ask_timestamp": observed_at.isoformat(),
                    "bid": 9.94,
                    "ask": 9.95,
                    "last": 9.95,
                    "volume": 1_000,
                    "session": "regular",
                    "trading_state": "tradable",
                    "realtime": True,
                    "security_status": "Normal",
                    "source": SCHWAB_QUOTE_SOURCE,
                }
            }
        )
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                self.root,
                self.root / "observations.json",
                self.state,
            ),
            service=self.service,
            quote_source=source,
        )
        marking = threading.Thread(
            target=workspace.advance_active_marks,
            kwargs={"received_at": observed_at},
        )
        marking.start()
        self.assertTrue(source.entered.wait(timeout=1))

        snapshot_done = threading.Event()
        snapshot_result: list[dict] = []

        def read_snapshot() -> None:
            snapshot_result.append(workspace.snapshot())
            snapshot_done.set()

        snapshot_reader = threading.Thread(target=read_snapshot)
        snapshot_reader.start()
        try:
            self.assertTrue(snapshot_done.wait(timeout=1))
            self.assertEqual(
                "PAPER SHADOW / NONTRANSMITTING",
                snapshot_result[0]["mode"],
            )
        finally:
            source.release.set()
            marking.join(timeout=2)
            snapshot_reader.join(timeout=2)
        self.assertFalse(marking.is_alive())
        self.assertFalse(snapshot_reader.is_alive())

    def test_official_quote_age_uses_frozen_sample_threshold(self) -> None:
        self.service.policy = replace(
            self.service.policy,
            active_position_quote_max_age_seconds=3,
        )
        definition = build_shadow_sample_metadata(
            self.service.policy,
            sample_version="synthetic-frozen-age-v2",
            official_sample_authorized=True,
        )
        state = self.service.store.load()
        trade = state.trades[0]
        official_trade = replace(
            trade,
            sample_metadata=definition,
            ticket=replace(
                trade.ticket,
                sample_version=definition.sample_version,
                strategy_configuration_fingerprint=(
                    definition.strategy_configuration_fingerprint
                ),
                fill_model_version=definition.fill_model_version,
                evidence_schema_version=definition.evidence_schema_version,
            ),
        )
        self.service.store.save(replace(state, trades=(official_trade,)))
        self.service.sample_definition = definition
        self.service.policy = replace(
            self.service.policy,
            active_position_quote_max_age_seconds=10,
        )

        self.service.process_quote(
            quote(
                "2026-07-23T10:00:05-05:00",
                bid=9.94,
                ask=9.95,
            ),
            received_at=at("2026-07-23T10:00:09-05:00"),
        )
        rejected = self.service.store.load().trades[0]
        mark = shadow_executable_mark_to_dict(
            rejected,
            observed_at=at("2026-07-23T10:00:09-05:00"),
        )

        self.assertEqual("pending_entry", rejected.status)
        self.assertIsNone(rejected.position)
        self.assertIn("frozen 3-second", rejected.last_reason)
        self.assertEqual("STALE", mark["displayState"])
        self.assertIsNone(mark["unrealizedPnl"])

    def test_engine_host_active_loop_is_separate_and_read_only(self) -> None:
        calls: list[str] = []
        called = threading.Event()

        def mark_runner() -> dict:
            calls.append("mark")
            called.set()
            return {
                "polled": False,
                "providerRequestCount": 0,
                "reason": "No active official Shadow work.",
            }

        runtime = self.host_runtime(mark_runner=mark_runner)
        runtime.start_collection_loop()
        try:
            self.assertTrue(called.wait(6.5))
            snapshot = runtime.snapshot()["activePositionMarking"]
            self.assertEqual(5, snapshot["cadenceSeconds"])
            self.assertEqual(0, snapshot["providerRequestCount"])
            self.assertEqual("UNAVAILABLE", snapshot["orderTransmission"])
            self.assertNotIn("submit_order", runtime.snapshot()["capabilities"])
        finally:
            runtime.close()

    def test_engine_host_provider_failure_is_visible_and_creates_no_order_capability(self) -> None:
        attempted = threading.Event()

        def failing_runner() -> dict:
            attempted.set()
            raise RuntimeError("synthetic provider outage")

        runtime = self.host_runtime(mark_runner=failing_runner)
        runtime.start_collection_loop()
        try:
            self.assertTrue(attempted.wait(6.5))
            deadline = time.monotonic() + 1
            snapshot = runtime.snapshot()
            while (
                snapshot["activePositionMarking"]["state"] != "Blocked"
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
                snapshot = runtime.snapshot()

            marking = snapshot["activePositionMarking"]
            self.assertEqual("Blocked", marking["state"])
            self.assertIn("synthetic provider outage", marking["detail"])
            self.assertEqual(0, marking["providerRequestCount"])
            self.assertEqual("UNAVAILABLE", marking["orderTransmission"])
            self.assertNotIn("submit_order", snapshot["capabilities"])
        finally:
            runtime.close()

    def test_slow_collection_does_not_block_active_marking_or_read_only_snapshot(self) -> None:
        collection_started = threading.Event()
        release_collection = threading.Event()
        mark_during_collection = threading.Event()

        def slow_collection():
            collection_started.set()
            release_collection.wait(8)
            return None

        def mark_runner() -> dict:
            if collection_started.wait(2) and not release_collection.is_set():
                mark_during_collection.set()
            return {
                "polled": False,
                "providerRequestCount": 0,
                "reason": "Synthetic independent marking cycle.",
            }

        runtime = self.host_runtime(
            mark_runner=mark_runner,
            cycle_runner=slow_collection,
            collection_interval_seconds=1,
        )
        runtime.start_collection_loop()
        try:
            self.assertTrue(collection_started.wait(2.5))
            self.assertTrue(mark_during_collection.wait(6.5))
            snapshot = runtime.snapshot()
            self.assertTrue(snapshot["collection"]["cycleInProgress"])
            self.assertGreaterEqual(
                snapshot["activePositionMarking"]["cycleCount"],
                1,
            )
            self.assertEqual(
                "UNAVAILABLE",
                snapshot["activePositionMarking"]["orderTransmission"],
            )
        finally:
            release_collection.set()
            runtime.close()

    def test_production_marking_cadence_cannot_be_configured_below_constitution(self) -> None:
        runtime = self.host_runtime(
            mark_runner=lambda: {},
            active_mark_interval_seconds=1,
        )

        self.assertEqual(
            ShadowMarketValidityPolicy().active_position_poll_interval_seconds,
            runtime.active_mark_interval_seconds,
        )


if __name__ == "__main__":
    unittest.main()
