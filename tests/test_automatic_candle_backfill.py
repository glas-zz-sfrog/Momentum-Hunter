from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.automatic_candle_backfill import (
    AutomaticCandleBackfillCoordinator,
    AutomaticCandleBackfillError,
    expected_account_ending_from_manifest,
)
from momentum_hunter.schwab_candle_contract import (
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabDailyCandle,
    SchwabMinuteCandle,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.schwab_daily_candle_store import SchwabDailyCandleStore
from momentum_hunter.workstation_charts import (
    WorkstationChartPaths,
    WorkstationChartService,
)


class AutomaticCandleBackfillCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_path = self.root / "state" / "automatic.json"
        self.now = datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def coordinator(self, runner, **kwargs) -> AutomaticCandleBackfillCoordinator:
        return AutomaticCandleBackfillCoordinator(
            state_path=self.state_path,
            run_backfill=runner,
            utc_clock=lambda: self.now,
            **kwargs,
        )

    def test_duplicate_requests_coalesce_behind_one_background_load(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls: list[tuple[str, ...]] = []

        def runner(symbols: tuple[str, ...]) -> dict[str, object]:
            calls.append(symbols)
            started.set()
            self.assertTrue(release.wait(2))
            return {"status": "COMPLETE", "symbols": [{"symbol": symbols[0]}]}

        coordinator = self.coordinator(runner)
        first = coordinator.request("nvda", reason="missing")
        self.assertTrue(started.wait(2))
        duplicate = coordinator.request("NVDA", reason="still missing")

        self.assertEqual("QUEUED", first["status"])
        self.assertIn(duplicate["status"], {"QUEUED", "RUNNING"})
        self.assertTrue(duplicate["coalesced"])
        self.assertEqual([("NVDA",)], calls)

        release.set()
        self.assertTrue(coordinator.wait_until_idle())
        completed = coordinator.status("NVDA")
        self.assertIsNotNone(completed)
        self.assertEqual("COMPLETE", completed["status"])
        self.assertEqual("UNAVAILABLE", completed["orderTransmission"])

    def test_worker_failure_is_terminal_and_does_not_loop_on_chart_refresh(self) -> None:
        calls = 0

        def runner(_symbols: tuple[str, ...]) -> dict[str, object]:
            nonlocal calls
            calls += 1
            raise RuntimeError("synthetic secret-bearing provider detail")

        coordinator = self.coordinator(runner)
        coordinator.request("AAA", reason="missing")
        self.assertTrue(coordinator.wait_until_idle())
        repeated = coordinator.request("AAA", reason="missing again")

        self.assertEqual(1, calls)
        self.assertEqual("FAILED", repeated["status"])
        self.assertTrue(repeated["coalesced"])
        self.assertNotIn("secret-bearing", repeated["detail"])

    def test_queue_limit_rejects_an_eleventh_active_symbol_without_running_it(self) -> None:
        started = threading.Event()
        release = threading.Event()
        calls: list[tuple[str, ...]] = []

        def runner(symbols: tuple[str, ...]) -> dict[str, object]:
            calls.append(symbols)
            started.set()
            self.assertTrue(release.wait(2))
            return {"status": "COMPLETE"}

        coordinator = self.coordinator(runner, max_symbols=2)
        coordinator.request("AAA", reason="missing")
        self.assertTrue(started.wait(2))
        coordinator.request("BBB", reason="missing")
        rejected = coordinator.request("CCC", reason="missing")

        self.assertEqual("FAILED", rejected["status"])
        self.assertIn("safety limit", rejected["detail"])
        release.set()
        self.assertTrue(coordinator.wait_until_idle())
        self.assertEqual([("AAA",), ("BBB",)], calls)

    def test_completed_load_obeys_five_minute_cooldown_then_can_refresh(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(symbols: tuple[str, ...]) -> dict[str, object]:
            calls.append(symbols)
            return {"status": "COMPLETE"}

        coordinator = self.coordinator(
            runner,
            refresh_cooldown=timedelta(minutes=5),
        )
        coordinator.request("AAA", reason="stale")
        self.assertTrue(coordinator.wait_until_idle())
        within_cooldown = coordinator.request("AAA", reason="still stale")
        self.now += timedelta(minutes=5, seconds=1)
        after_cooldown = coordinator.request("AAA", reason="still stale")
        self.assertTrue(coordinator.wait_until_idle())

        self.assertEqual("COMPLETE", within_cooldown["status"])
        self.assertTrue(within_cooldown["coalesced"])
        self.assertEqual("QUEUED", after_cooldown["status"])
        self.assertEqual(2, len(calls))

    def test_interrupted_load_is_recovered_once_after_restart(self) -> None:
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "records": {
                        "AAA": {
                            "symbol": "AAA",
                            "status": "RUNNING",
                            "detail": "interrupted",
                            "requestedAt": "2026-08-06T13:59:00Z",
                            "startedAt": "2026-08-06T13:59:01Z",
                            "completedAt": None,
                            "attemptCount": 1,
                            "recoveryCount": 0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        calls: list[tuple[str, ...]] = []
        coordinator = self.coordinator(
            lambda symbols: calls.append(symbols) or {"status": "COMPLETE"}
        )

        self.assertTrue(coordinator.wait_until_idle())
        status = coordinator.status("AAA")
        self.assertEqual([("AAA",)], calls)
        self.assertEqual("COMPLETE", status["status"])

    def test_tampered_state_fails_closed_without_network_work(self) -> None:
        self.state_path.parent.mkdir(parents=True)
        self.state_path.write_text('{"schemaVersion":999,"records":{}}', encoding="utf-8")
        calls: list[tuple[str, ...]] = []
        coordinator = self.coordinator(
            lambda symbols: calls.append(symbols) or {"status": "COMPLETE"}
        )

        result = coordinator.request("AAA", reason="missing")

        self.assertEqual("FAILED", result["status"])
        self.assertIn("unreadable or untrusted", result["detail"])
        self.assertEqual([], calls)

    def test_state_contains_no_account_or_broker_capability(self) -> None:
        coordinator = self.coordinator(lambda _symbols: {"status": "COMPLETE"})
        coordinator.request("AAA", reason="missing")
        self.assertTrue(coordinator.wait_until_idle())
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        serialized = json.dumps(payload).lower()

        self.assertNotIn("account", serialized)
        self.assertNotIn("token", serialized)
        self.assertFalse(payload["positionsRequested"])
        self.assertFalse(payload["ordersRequested"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def test_chart_transitions_from_loading_to_populated_cache_without_blocking(self) -> None:
        minute_root = self.root / "minute"
        daily_root = self.root / "daily"
        minute_store = SchwabCandleStore(minute_root)
        daily_store = SchwabDailyCandleStore(daily_root)
        started = threading.Event()
        release = threading.Event()

        def runner(symbols: tuple[str, ...]) -> dict[str, object]:
            started.set()
            self.assertTrue(release.wait(2))
            minute_candles = tuple(
                SchwabMinuteCandle(
                    symbol=symbols[0],
                    timestamp=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
                    + timedelta(minutes=index),
                    open=100 + index,
                    high=101 + index,
                    low=99 + index,
                    close=100.5 + index,
                    volume=1000 + index,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                )
                for index in range(120)
            )
            session_dates: list[datetime] = []
            cursor = datetime(2026, 8, 6, tzinfo=timezone.utc)
            while len(session_dates) < 20:
                if cursor.weekday() < 5:
                    session_dates.append(cursor)
                cursor -= timedelta(days=1)
            daily_candles = tuple(
                SchwabDailyCandle(
                    symbol=symbols[0],
                    timestamp=session.replace(hour=4),
                    session_date=session.date().isoformat(),
                    open=90 + index,
                    high=92 + index,
                    low=89 + index,
                    close=91 + index,
                    volume=100_000 + index,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                )
                for index, session in enumerate(reversed(session_dates))
            )
            minute_store.append_history(minute_candles, received_at=self.now)
            daily_store.append_history(daily_candles, received_at=self.now)
            return {"status": "COMPLETE", "symbols": [{"symbol": symbols[0]}]}

        coordinator = AutomaticCandleBackfillCoordinator(
            state_path=self.state_path,
            minute_store_root=minute_root,
            daily_store_root=daily_root,
            run_backfill=runner,
            utc_clock=lambda: self.now,
        )
        service = WorkstationChartService(
            paths=WorkstationChartPaths(
                schwab_candle_store_root=minute_root,
                schwab_daily_candle_store_root=daily_root,
            ),
            backfill_coordinator=coordinator,
        )

        first = service.snapshot("AAA", "1m", observed_at=self.now)
        self.assertTrue(started.wait(2))
        self.assertEqual("UNAVAILABLE", first["state"])
        self.assertEqual("QUEUED", first["historyLoad"]["status"])
        release.set()
        self.assertTrue(coordinator.wait_until_idle())
        expected_counts = {"1m": 120, "5m": 24, "15m": 8, "Daily": 20}
        for interval, expected_count in expected_counts.items():
            populated = service.snapshot("AAA", interval, observed_at=self.now)
            self.assertEqual("AVAILABLE", populated["state"], interval)
            self.assertEqual(expected_count, len(populated["candles"]), interval)
            self.assertEqual("COMPLETE", populated["historyLoad"]["status"], interval)
            self.assertEqual(
                "UNAVAILABLE",
                populated["historyLoad"]["orderTransmission"],
                interval,
            )


class AutomaticCandleBackfillManifestTests(unittest.TestCase):
    def test_manifest_must_match_current_checkout_and_cash_account_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "repositoryRoot": str(Path(__file__).resolve().parents[1]),
                        "expectedAccountEnding": "2573",
                        "expectedAccountType": "INDIVIDUAL_CASH",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual("2573", expected_account_ending_from_manifest(path))

            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["repositoryRoot"] = str(Path(temporary) / "other-checkout")
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(AutomaticCandleBackfillError):
                expected_account_ending_from_manifest(path)


if __name__ == "__main__":
    unittest.main()
