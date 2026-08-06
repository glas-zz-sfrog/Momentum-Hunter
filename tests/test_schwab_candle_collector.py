from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.schwab_candle_collector import (
    CandleCollectorOptions,
    CandleSymbolUniverse,
    CandleUniverseSources,
    SchwabCandleCollectorError,
    SchwabIncrementalCandleCollector,
    build_collection_plan,
    main,
    resolve_candle_universe,
    write_result_once,
)
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_CHART_EQUITY_SOURCE,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabMinuteCandle,
    SchwabStreamCandleObservation,
)
from momentum_hunter.schwab_candle_observer import (
    GuardedStreamerAccess,
    SchwabCandleObserverNetworkError,
)
from momentum_hunter.schwab_candle_store import (
    SchwabCandleStore,
    SchwabCandleStoreError,
)


UTC = timezone.utc
MARKET_MINUTE = datetime(2026, 8, 5, 14, 0, tzinfo=UTC)


class FakeAccessGuard:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def authorize(self, expected_account_ending: str) -> GuardedStreamerAccess:
        self.calls.append(expected_account_ending)
        return GuardedStreamerAccess(
            access_token="synthetic-access-token",
            account_ending="2573",
            account_type="INDIVIDUAL_CASH",
            balances_present=True,
        )


class FakeHttpTransport:
    def __init__(
        self,
        history_by_symbol: dict[str, object],
        *,
        transient_failures: int = 0,
    ) -> None:
        self.history_by_symbol = history_by_symbol
        self.transient_failures = transient_failures
        self.history_calls: list[str] = []

    def fetch_bootstrap(self, access_token: str) -> object:
        if access_token != "synthetic-access-token":
            raise AssertionError("unexpected token")
        return bootstrap_payload()

    def fetch_price_history(
        self,
        access_token: str,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        extended_hours: bool,
    ) -> object:
        self.history_calls.append(symbol)
        if self.transient_failures:
            self.transient_failures -= 1
            raise SchwabCandleObserverNetworkError("synthetic transient")
        return self.history_by_symbol[symbol]


class FakeStream:
    def __init__(self, messages: list[object]) -> None:
        self.messages = list(messages)
        self.sent: list[dict[str, object]] = []
        self.closed = False

    def send_json(self, payload: dict[str, object]) -> None:
        self.sent.append(payload)

    def receive_json(self, timeout_seconds: float):
        if not self.messages:
            return None
        item = self.messages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class FakeStreamFactory:
    def __init__(self, stream: FakeStream) -> None:
        self.stream = stream
        self.urls: list[str] = []

    def connect(self, socket_url: str) -> FakeStream:
        self.urls.append(socket_url)
        return self.stream


class SteppingMonotonic:
    def __init__(self, step: float = 5.0) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


class SteppingClock:
    def __init__(self, start: datetime) -> None:
        self.value = start - timedelta(seconds=1)

    def __call__(self) -> datetime:
        self.value += timedelta(seconds=1)
        return self.value


class SchwabCandleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = SchwabCandleStore(self.root / "schwab-store")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_stream_versions_are_idempotent_and_revisions_are_preserved(self) -> None:
        first = observation(stream_candle(close=100.0), received_at=MARKET_MINUTE + timedelta(seconds=65))
        revised = observation(stream_candle(close=101.0), received_at=MARKET_MINUTE + timedelta(seconds=70), arrival=1)

        inserted = self.store.append_stream((first, revised))
        replayed = self.store.append_stream((first,))
        partition = self.store.load_partition("SPY", "2026-08-05")
        bar = partition["bars"][0]

        self.assertEqual(2, inserted.inserted_count)
        self.assertEqual(0, inserted.duplicate_count)
        self.assertEqual(0, replayed.inserted_count)
        self.assertEqual(1, replayed.duplicate_count)
        self.assertEqual("COMPLETED_UNRECONCILED", bar["state"])
        self.assertEqual(2, len(bar["streamVersions"]))
        self.assertIsNone(bar["canonicalCandle"])

    def test_current_minute_remains_in_progress(self) -> None:
        current = observation(
            stream_candle(close=100.0),
            received_at=MARKET_MINUTE + timedelta(seconds=30),
        )
        self.store.append_stream((current,))
        bar = self.store.load_partition("SPY", "2026-08-05")["bars"][0]
        self.assertEqual("IN_PROGRESS", bar["state"])

    def test_price_history_becomes_canonical_and_correction_is_visible(self) -> None:
        self.store.append_stream(
            (
                observation(
                    stream_candle(close=100.0, volume=1000.75),
                    received_at=MARKET_MINUTE + timedelta(seconds=65),
                ),
            )
        )
        mutation = self.store.append_history(
            (history_candle(close=100.0, volume=1000.0),),
            received_at=MARKET_MINUTE + timedelta(seconds=90),
        )
        duplicate = self.store.append_history(
            (history_candle(close=100.0, volume=1000.0),),
            received_at=MARKET_MINUTE + timedelta(seconds=120),
        )
        corrected = self.store.append_history(
            (history_candle(close=99.5, volume=1000.0),),
            received_at=MARKET_MINUTE + timedelta(seconds=150),
        )
        bar = self.store.load_partition("SPY", "2026-08-05")["bars"][0]

        self.assertEqual(1, mutation.inserted_count)
        self.assertEqual(1, duplicate.duplicate_count)
        self.assertEqual(1, corrected.inserted_count)
        self.assertEqual("CORRECTED", bar["state"])
        self.assertEqual(["close", "volume"], bar["discrepancyFields"])
        self.assertEqual(99.5, bar["canonicalCandle"]["close"])
        self.assertEqual(1000.0, bar["canonicalCandle"]["volume"])
        self.assertEqual(1, len(bar["streamVersions"]))
        self.assertEqual(2, len(bar["historyVersions"]))

    def test_matching_history_reconciles_and_history_only_fills_gap(self) -> None:
        stream = stream_candle(close=100.0)
        self.store.append_stream(
            (observation(stream, received_at=MARKET_MINUTE + timedelta(seconds=65)),)
        )
        self.store.append_history(
            (
                history_candle(close=100.0),
                history_candle(close=101.0, timestamp=MARKET_MINUTE + timedelta(minutes=1)),
            ),
            received_at=MARKET_MINUTE + timedelta(minutes=3),
        )
        bars = self.store.load_partition("SPY", "2026-08-05")["bars"]
        self.assertEqual("RECONCILED", bars[0]["state"])
        self.assertEqual("HISTORY_ONLY_GAP_FILL", bars[1]["state"])
        self.assertEqual(2, len(self.store.canonical_bars("SPY", "2026-08-05")))

    def test_history_reversion_to_prior_values_becomes_canonical(self) -> None:
        original = history_candle(close=100.0)
        self.store.append_history(
            (original,),
            received_at=MARKET_MINUTE + timedelta(seconds=60),
        )
        self.store.append_history(
            (history_candle(close=99.0),),
            received_at=MARKET_MINUTE + timedelta(seconds=90),
        )
        reverted = self.store.append_history(
            (original,),
            received_at=MARKET_MINUTE + timedelta(seconds=120),
        )
        bar = self.store.load_partition("SPY", "2026-08-05")["bars"][0]

        self.assertEqual(1, reverted.inserted_count)
        self.assertEqual(3, len(bar["historyVersions"]))
        self.assertEqual(100.0, bar["canonicalCandle"]["close"])
        self.assertIn("reassertedAfterVersionId", bar["historyVersions"][-1])

    def test_eastern_session_date_controls_partition(self) -> None:
        after_midnight_utc = datetime(2026, 8, 6, 0, 30, tzinfo=UTC)
        candle = stream_candle(timestamp=after_midnight_utc)
        self.store.append_stream(
            (observation(candle, received_at=after_midnight_utc + timedelta(seconds=65)),)
        )
        self.assertTrue(self.store.partition_path("SPY", "2026-08-05").exists())
        self.assertFalse(self.store.partition_path("SPY", "2026-08-06").exists())

    def test_health_reports_gaps_stale_and_unreconciled(self) -> None:
        observations = (
            observation(stream_candle(timestamp=MARKET_MINUTE), received_at=MARKET_MINUTE + timedelta(seconds=65)),
            observation(
                stream_candle(timestamp=MARKET_MINUTE + timedelta(minutes=2)),
                received_at=MARKET_MINUTE + timedelta(minutes=3, seconds=5),
                arrival=1,
            ),
        )
        self.store.append_stream(observations)
        health = self.store.health(
            ("SPY", "IWM"),
            evaluated_at=MARKET_MINUTE + timedelta(minutes=10),
            stale_after=timedelta(minutes=3),
        )
        self.assertEqual("STALE_WITH_GAPS_UNRECONCILED", health[0].status)
        self.assertEqual(1, health[0].gap_count)
        self.assertEqual(2, health[0].unreconciled_count)
        self.assertEqual("NO_OBSERVATIONS", health[1].status)

    def test_fresh_reconciliation_receipt_cannot_hide_stale_candle(self) -> None:
        self.store.append_history(
            (history_candle(),),
            received_at=MARKET_MINUTE + timedelta(minutes=10),
        )
        health = self.store.health(
            ("SPY",),
            evaluated_at=MARKET_MINUTE + timedelta(minutes=10, seconds=1),
            stale_after=timedelta(minutes=3),
        )[0]
        self.assertTrue(health.stale)
        self.assertEqual("STALE", health.status)

    def test_health_is_scoped_to_the_evaluated_market_session(self) -> None:
        prior_minute = MARKET_MINUTE - timedelta(days=1)
        self.store.append_stream(
            (
                observation(
                    stream_candle(timestamp=prior_minute),
                    received_at=prior_minute + timedelta(seconds=65),
                ),
            )
        )
        self.store.append_history(
            (history_candle(),),
            received_at=MARKET_MINUTE + timedelta(seconds=90),
        )

        health = self.store.health(
            ("SPY",),
            evaluated_at=MARKET_MINUTE + timedelta(minutes=2),
            stale_after=timedelta(minutes=3),
        )[0]

        self.assertEqual("CURRENT", health.status)
        self.assertEqual(1, health.canonical_count)
        self.assertEqual(0, health.unreconciled_count)

    def test_tampered_partition_fails_closed(self) -> None:
        self.store.append_stream(
            (observation(stream_candle(), received_at=MARKET_MINUTE + timedelta(seconds=65)),)
        )
        path = self.store.partition_path("SPY", "2026-08-05")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["bars"][0]["streamVersions"][0]["candle"]["close"] = 999.0
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(SchwabCandleStoreError, "hash did not match"):
            self.store.load_partition("SPY", "2026-08-05")

    def test_tampered_derived_state_fails_closed(self) -> None:
        self.store.append_stream(
            (observation(stream_candle(), received_at=MARKET_MINUTE + timedelta(seconds=65)),)
        )
        path = self.store.partition_path("SPY", "2026-08-05")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["bars"][0]["state"] = "RECONCILED"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(SchwabCandleStoreError, "derived field state"):
            self.store.load_partition("SPY", "2026-08-05")

    def test_atomic_replace_failure_preserves_absence_and_cleans_temp(self) -> None:
        with patch(
            "momentum_hunter.schwab_candle_store.os.replace",
            side_effect=PermissionError("synthetic lock"),
        ):
            with self.assertRaises(PermissionError):
                self.store.append_stream(
                    (observation(stream_candle(), received_at=MARKET_MINUTE + timedelta(seconds=65)),)
                )
        path = self.store.partition_path("SPY", "2026-08-05")
        self.assertFalse(path.exists())
        self.assertEqual([], list(path.parent.glob("*.tmp")))

    def test_single_writer_lease_fails_closed_and_releases(self) -> None:
        first = self.store.lease(acquired_at=MARKET_MINUTE).acquire()
        try:
            with self.assertRaisesRegex(SchwabCandleStoreError, "writer lease"):
                self.store.lease(acquired_at=MARKET_MINUTE).acquire()
        finally:
            first.release()
        with self.store.lease(acquired_at=MARKET_MINUTE):
            self.assertTrue((self.store.root / ".collector.lock").exists())
        with self.store.lease(acquired_at=MARKET_MINUTE):
            self.assertTrue((self.store.root / ".collector.lock").exists())

    def test_writer_lease_recovers_when_process_handle_dies(self) -> None:
        crashed = self.store.lease(acquired_at=MARKET_MINUTE).acquire()
        crashed._handle.close()  # Simulates operating-system cleanup at process exit.
        crashed._handle = None
        crashed._held = False
        with self.store.lease(acquired_at=MARKET_MINUTE + timedelta(seconds=1)):
            self.assertTrue((self.store.root / ".collector.lock").exists())

    def test_legacy_cache_path_is_rejected(self) -> None:
        from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH

        with self.assertRaisesRegex(SchwabCandleStoreError, "legacy minute-bar"):
            SchwabCandleStore(OPPORTUNITY_MINUTE_BARS_PATH.parent)


class CandleUniverseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_universe_prioritizes_active_selected_ranked_and_benchmarks(self) -> None:
        report = self.root / "report.json"
        cycles = self.root / "cycles.json"
        state = self.root / "state.json"
        report.write_text(
            json.dumps(
                {
                    "metadata": {
                        "source_session": "opening",
                        "generated_at": "2026-08-05T08:35:00-05:00",
                    },
                    "candidates": [
                        {"rank": rank, "symbol": symbol}
                        for rank, symbol in enumerate(
                            ("NVDA", "SHOP", "ZETA", "META", "MSFT", "AMZN"), 1
                        )
                    ]
                }
            ),
            encoding="utf-8",
        )
        cycles.write_text(
            json.dumps(
                {
                    "cycles": [
                        {
                            "decision_at": "2026-08-05T09:40:00-05:00",
                            "selected_symbol": "NVDA",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        state.write_text(
            json.dumps(
                {
                    "trades": [
                        {
                            "symbol": "PLTR",
                            "status": "open",
                            "position": {"quantity": 1},
                            "outcome": None,
                        },
                        {
                            "symbol": "CLOSED",
                            "status": "winner",
                            "position": {"quantity": 1},
                            "outcome": {"result": "winner"},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        universe = resolve_candle_universe(
            CandleUniverseSources(
                candidate_report=report,
                decision_cycles=cycles,
                shadow_state=state,
                explicit_selected_symbol="GOOGL",
            )
        )

        self.assertEqual(
            ("GOOGL", "NVDA", "PLTR", "SPY", "IWM", "SHOP", "ZETA", "META", "MSFT"),
            universe.symbols,
        )
        self.assertIn("LATEST_SELECTED_SYMBOL", universe.sources_by_symbol["NVDA"])
        self.assertIn("HUNTER_CANDIDATE_RANK_1", universe.sources_by_symbol["NVDA"])
        self.assertEqual(3, len(universe.input_fingerprints))

    def test_universe_cap_excludes_lower_priority_items_visibly(self) -> None:
        state = self.root / "state.json"
        state.write_text(
            json.dumps(
                {
                    "trades": [
                        {
                            "symbol": f"A{index}",
                            "status": "open",
                            "position": {"quantity": 1},
                            "outcome": None,
                        }
                        for index in range(12)
                    ]
                }
            ),
            encoding="utf-8",
        )
        universe = resolve_candle_universe(CandleUniverseSources(shadow_state=state))
        self.assertEqual(10, len(universe.symbols))
        self.assertEqual(("A8", "A9", "A10", "A11"), universe.excluded_symbols)
        self.assertIn("SPY", universe.symbols)
        self.assertIn("IWM", universe.symbols)
        self.assertIn("SYMBOL_LIMIT_EXCLUDED_LOWER_PRIORITY_ITEMS", universe.warnings)

    def test_universe_resolution_does_not_mutate_sources(self) -> None:
        report = self.root / "report.json"
        report.write_text(
            '{"metadata":{"source_session":"opening","generated_at":"2026-08-05T08:35:00-05:00"},"candidates":[{"rank":1,"symbol":"NVDA"}]}',
            encoding="utf-8",
        )
        before = sha256(report)
        resolve_candle_universe(CandleUniverseSources(candidate_report=report))
        self.assertEqual(before, sha256(report))

    def test_invalid_candidate_rank_fails_closed(self) -> None:
        report = self.root / "report.json"
        report.write_text(
            '{"metadata":{"source_session":"opening","generated_at":"2026-08-05T08:35:00-05:00"},"candidates":[{"rank":"1","symbol":"NVDA"}]}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(SchwabCandleCollectorError, "invalid rank"):
            resolve_candle_universe(CandleUniverseSources(candidate_report=report))

    def test_duplicate_candidate_identity_fails_closed(self) -> None:
        report = self.root / "report.json"
        cases = (
            (
                [{"rank": 1, "symbol": "NVDA"}, {"rank": 1, "symbol": "SHOP"}],
                "duplicate rank",
            ),
            (
                [{"rank": 1, "symbol": "NVDA"}, {"rank": 2, "symbol": "NVDA"}],
                "duplicate symbol",
            ),
        )
        for candidates, message in cases:
            with self.subTest(message=message):
                report.write_text(
                    json.dumps(
                        {
                            "metadata": {
                                "source_session": "opening",
                                "generated_at": "2026-08-05T08:35:00-05:00",
                            },
                            "candidates": candidates,
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(SchwabCandleCollectorError, message):
                    resolve_candle_universe(
                        CandleUniverseSources(candidate_report=report)
                    )

    def test_stale_candidate_report_is_rejected_for_collection_date(self) -> None:
        report = self.root / "report.json"
        report.write_text(
            '{"metadata":{"source_session":"opening","generated_at":"2026-08-04T08:35:00-05:00"},"candidates":[{"rank":1,"symbol":"NVDA"}]}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            SchwabCandleCollectorError, "did not match the collection market date"
        ):
            resolve_candle_universe(
                CandleUniverseSources(candidate_report=report),
                expected_market_date=datetime(2026, 8, 5, tzinfo=UTC).date(),
            )


class SchwabIncrementalCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = SchwabCandleStore(self.root / "store")
        self.universe = CandleSymbolUniverse(
            symbols=("SPY",),
            sources_by_symbol={"SPY": ("BENCHMARK",)},
            excluded_symbols=(),
            warnings=(),
            input_fingerprints={},
        )
        self.options = CandleCollectorOptions(
            expected_account_ending="2573",
            duration_seconds=60,
            history_attempts=2,
            stale_after_seconds=180,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_has_no_network_write_or_execution_authority(self) -> None:
        plan = build_collection_plan(
            self.universe,
            self.options,
            store_root=self.store.root,
        )
        self.assertFalse(plan["execute"])
        self.assertFalse(plan["networkCalled"])
        self.assertFalse(plan["productionDataWritten"])
        self.assertFalse(plan["positionsRequested"])
        self.assertFalse(plan["ordersRequested"])
        self.assertEqual("UNAVAILABLE", plan["orderTransmission"])

    def test_end_to_end_stream_persist_history_reconcile(self) -> None:
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_frame("SPY", MARKET_MINUTE, close=500.0),
            ]
        )
        http = FakeHttpTransport({"SPY": history_payload("SPY", MARKET_MINUTE, 500.0)})
        guard = FakeAccessGuard()
        result = collector(
            self.store,
            stream,
            http,
            guard=guard,
        ).collect(self.universe, self.options)

        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual({"SPY": 1}, result["stream"]["receivedBySymbol"])
        self.assertEqual("PASS", result["history"]["status"])
        self.assertEqual(["2573"], guard.calls)
        self.assertTrue(stream.closed)
        bar = self.store.load_partition("SPY", "2026-08-05")["bars"][0]
        self.assertEqual("RECONCILED", bar["state"])
        serialized = json.dumps(result)
        self.assertNotIn("synthetic-access-token", serialized)
        self.assertEqual("UNAVAILABLE", result["boundaries"]["orderTransmission"])

    def test_transient_history_failure_retries_once(self) -> None:
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_frame("SPY", MARKET_MINUTE, close=500.0),
            ]
        )
        http = FakeHttpTransport(
            {"SPY": history_payload("SPY", MARKET_MINUTE, 500.0)},
            transient_failures=1,
        )
        sleeps: list[float] = []
        instance = collector(self.store, stream, http, sleep=sleeps.append)
        result = instance.collect(self.universe, self.options)
        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual(2, result["history"]["symbols"][0]["attempts"])
        self.assertEqual([0.25], sleeps)

    def test_missing_symbol_is_partial_and_never_fabricated(self) -> None:
        universe = CandleSymbolUniverse(
            symbols=("SPY", "IWM"),
            sources_by_symbol={"SPY": ("BENCHMARK",), "IWM": ("BENCHMARK",)},
            excluded_symbols=(),
            warnings=(),
            input_fingerprints={},
        )
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_frame("SPY", MARKET_MINUTE, close=500.0),
            ]
        )
        http = FakeHttpTransport({"SPY": history_payload("SPY", MARKET_MINUTE, 500.0)})
        result = collector(self.store, stream, http).collect(universe, self.options)
        self.assertEqual("PARTIAL", result["status"])
        self.assertIn("NO_STREAM_CANDLES:IWM", result["findings"])
        self.assertEqual([], self.store.load_partition("IWM", "2026-08-05")["bars"])

    def test_malformed_history_is_structured_partial(self) -> None:
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_frame("SPY", MARKET_MINUTE, close=500.0),
            ]
        )
        result = collector(
            self.store,
            stream,
            FakeHttpTransport({"SPY": {"unexpected": True}}),
        ).collect(self.universe, self.options)
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual("INVALID_RESPONSE", result["history"]["symbols"][0]["status"])
        self.assertIn("HISTORY_RESPONSE_INVALID:SPY", result["findings"])
        bar = self.store.load_partition("SPY", "2026-08-05")["bars"][0]
        self.assertEqual("COMPLETED_UNRECONCILED", bar["state"])

    def test_out_of_order_stream_arrival_is_preserved(self) -> None:
        later = MARKET_MINUTE + timedelta(minutes=1)
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_frame("SPY", later, close=501.0),
                stream_frame("SPY", MARKET_MINUTE, close=500.0),
            ]
        )
        history = {
            "symbol": "SPY",
            "empty": False,
            "candles": [
                history_payload("SPY", MARKET_MINUTE, 500.0)["candles"][0],
                history_payload("SPY", later, 501.0)["candles"][0],
            ],
        }
        result = collector(
            self.store,
            stream,
            FakeHttpTransport({"SPY": history}),
        ).collect(self.universe, self.options)
        self.assertEqual("COMPLETE", result["status"])
        bars = self.store.load_partition("SPY", "2026-08-05")["bars"]
        self.assertTrue(bars[0]["streamVersions"][0]["outOfOrder"])
        self.assertFalse(bars[1]["streamVersions"][0]["outOfOrder"])

    def test_disconnect_preserves_prior_stream_evidence_and_returns_partial(self) -> None:
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_frame("SPY", MARKET_MINUTE, close=500.0),
                SchwabCandleObserverNetworkError("synthetic disconnect"),
            ]
        )
        http = FakeHttpTransport({"SPY": history_payload("SPY", MARKET_MINUTE, 500.0)})
        result = collector(self.store, stream, http).collect(self.universe, self.options)
        self.assertEqual("PARTIAL", result["status"])
        self.assertIn("STREAM_DISCONNECTED_BEFORE_DURATION", result["findings"])
        self.assertEqual(1, len(self.store.load_partition("SPY", "2026-08-05")["bars"]))

    def test_plan_only_cli_does_not_create_store(self) -> None:
        report = self.root / "report.json"
        generated_at = datetime.now(UTC).astimezone(EASTERN_TZ).isoformat()
        report.write_text(
            json.dumps(
                {
                    "metadata": {
                        "source_session": "opening",
                        "generated_at": generated_at,
                    },
                    "candidates": [{"rank": 1, "symbol": "NVDA"}],
                }
            ),
            encoding="utf-8",
        )
        store_root = self.root / "not-created"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "--expected-account-ending",
                    "2573",
                    "--candidate-report",
                    str(report),
                    "--decision-cycles",
                    str(self.root / "missing-cycles.json"),
                    "--shadow-state",
                    str(self.root / "missing-state.json"),
                    "--duration-seconds",
                    "60",
                    "--store-root",
                    str(store_root),
                ]
            )
        self.assertEqual(0, exit_code)
        self.assertFalse(store_root.exists())
        self.assertFalse(json.loads(output.getvalue())["networkCalled"])

    def test_result_is_write_once(self) -> None:
        path = self.root / "run.json"
        first = {"status": "COMPLETE"}
        self.assertEqual(path, write_result_once(first, path))
        self.assertEqual(path, write_result_once(first, path))
        with self.assertRaisesRegex(SchwabCandleCollectorError, "conflicting"):
            write_result_once({"status": "PARTIAL"}, path)

    def test_modules_have_no_trading_or_legacy_write_capability(self) -> None:
        project = Path(__file__).parents[1]
        store_source = (project / "momentum_hunter" / "schwab_candle_store.py").read_text(encoding="utf-8").lower()
        collector_source = (project / "momentum_hunter" / "schwab_candle_collector.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "submit_order",
            "cancel_order",
            "replace_order",
            "preview_order",
            "trade_planning import",
            "scoring import",
            "readiness import",
        ):
            self.assertNotIn(forbidden, collector_source)
            self.assertNotIn(forbidden, store_source)
        self.assertNotIn('"opportunity-minute-bars.json"', store_source)


def collector(
    store: SchwabCandleStore,
    stream: FakeStream,
    http: FakeHttpTransport,
    *,
    guard: FakeAccessGuard | None = None,
    sleep=lambda _: None,
) -> SchwabIncrementalCandleCollector:
    return SchwabIncrementalCandleCollector(
        store=store,
        access_guard=guard or FakeAccessGuard(),
        http_transport=http,
        stream_factory=FakeStreamFactory(stream),
        utc_clock=SteppingClock(MARKET_MINUTE + timedelta(seconds=65)),
        monotonic_clock=SteppingMonotonic(),
        sleep=sleep,
    )


def stream_candle(
    *,
    close: float = 100.0,
    volume: float = 1000.0,
    timestamp: datetime = MARKET_MINUTE,
    symbol: str = "SPY",
) -> SchwabMinuteCandle:
    return SchwabMinuteCandle(
        symbol=symbol,
        timestamp=timestamp,
        open=99.0,
        high=max(101.0, close),
        low=98.0,
        close=close,
        volume=volume,
        source=SCHWAB_CHART_EQUITY_SOURCE,
        sequence=1,
    )


def history_candle(
    *,
    close: float = 100.0,
    volume: float = 1000.0,
    timestamp: datetime = MARKET_MINUTE,
    symbol: str = "SPY",
) -> SchwabMinuteCandle:
    return SchwabMinuteCandle(
        symbol=symbol,
        timestamp=timestamp,
        open=99.0,
        high=max(101.0, close),
        low=98.0,
        close=close,
        volume=volume,
        source=SCHWAB_PRICE_HISTORY_SOURCE,
        sequence=None,
    )


def observation(
    candle: SchwabMinuteCandle,
    *,
    received_at: datetime,
    arrival: int = 0,
) -> SchwabStreamCandleObservation:
    return SchwabStreamCandleObservation(
        arrival_index=arrival,
        payload_index=0,
        received_at=received_at,
        candle=candle,
        minute_identity=f"test|{candle.symbol}|{candle.timestamp.isoformat()}",
        update_kind="FIRST_OBSERVATION",
        changed_fields=(),
        out_of_order=False,
        sequence_delta_from_previous_arrival=None,
    )


def ack(service: str, command: str, request_id: str) -> dict[str, object]:
    return {
        "response": [
            {
                "service": service,
                "command": command,
                "requestid": request_id,
                "content": {"code": 0, "msg": "OK"},
            }
        ]
    }


def stream_frame(
    symbol: str,
    timestamp: datetime,
    *,
    close: float,
) -> dict[str, object]:
    timestamp_ms = int(timestamp.timestamp() * 1000)
    return {
        "data": [
            {
                "service": "CHART_EQUITY",
                "timestamp": timestamp_ms + 65_000,
                "command": "SUBS",
                "content": [
                    {
                        "key": symbol,
                        "1": 1,
                        "2": close - 1.0,
                        "3": close + 1.0,
                        "4": close - 2.0,
                        "5": close,
                        "6": 1000.0,
                        "7": timestamp_ms,
                        "8": 20_260_805,
                    }
                ],
            }
        ]
    }


def history_payload(
    symbol: str,
    timestamp: datetime,
    close: float,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "empty": False,
        "candles": [
            {
                "datetime": int(timestamp.timestamp() * 1000),
                "open": close - 1.0,
                "high": close + 1.0,
                "low": close - 2.0,
                "close": close,
                "volume": 1000.0,
            }
        ],
    }


def bootstrap_payload() -> dict[str, object]:
    return {
        "accounts": [{"accountNumber": "REDACTED2573"}],
        "streamerInfo": [
            {
                "streamerSocketUrl": "wss://streamer-api.schwab.com/ws",
                "schwabClientCustomerId": "synthetic-customer",
                "schwabClientCorrelId": "synthetic-correlation",
                "schwabClientChannel": "synthetic-channel",
                "schwabClientFunctionId": "synthetic-function",
            }
        ],
        "offers": [{"mktDataPermission": "NP"}],
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
