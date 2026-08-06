from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.schwab_candle_contract import (
    SCHWAB_CHART_EQUITY_SOURCE,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabDailyCandle,
    SchwabMinuteCandle,
    SchwabStreamCandleObservation,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore, minute_identity
from momentum_hunter.schwab_daily_candle_store import SchwabDailyCandleStore
from momentum_hunter.workstation_charts import (
    CHART_SNAPSHOT_SCHEMA_VERSION,
    WorkstationChartPaths,
    WorkstationChartService,
)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class WorkstationChartServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.daily_root = root / "schwab-daily-candles-v1"
        self.legacy_daily_path = root / "daily-ohlc-bars.json"
        self.candle_root = root / "schwab-candles-v1"
        self.legacy_path = root / "opportunity-minute-bars.json"
        self.paths = WorkstationChartPaths(
            schwab_candle_store_root=self.candle_root,
            schwab_daily_candle_store_root=self.daily_root,
        )
        self.store = SchwabCandleStore(self.candle_root)
        self.daily_store = SchwabDailyCandleStore(self.daily_root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_daily_snapshot_remains_separate_from_intraday_source(self) -> None:
        self.write_daily(
            [
                daily_record("AAA", "2026-08-03", 10, 12, 9, 11, 100),
                daily_record("AAA", "2026-08-04", 11, 13, 10, 12, 200),
                daily_record("AAA", "2026-08-05", 12, 14, 10, 13, 300),
                daily_record("BBB", "2026-08-04", 20, 21, 19, 20, 400),
            ]
        )

        snapshot = self.service().snapshot("aaa", "Daily", observed_at=at("2026-08-05T16:00:00Z"))

        self.assertEqual(CHART_SNAPSHOT_SCHEMA_VERSION, snapshot["schemaVersion"])
        self.assertEqual("AAA", snapshot["symbol"])
        self.assertEqual("Daily", snapshot["interval"])
        self.assertEqual("AVAILABLE", snapshot["state"])
        self.assertEqual(3, len(snapshot["candles"]))
        self.assertEqual("2026-08-03T04:00:00+00:00", snapshot["candles"][0]["timestamp"])
        self.assertEqual("Schwab price history daily OHLC", snapshot["lineage"]["sourceLabel"])
        self.assertEqual("Schwab Trader API", snapshot["quality"]["provider"])
        self.assertEqual(SCHWAB_PRICE_HISTORY_SOURCE, snapshot["candles"][0]["source"])

    def test_one_minute_snapshot_uses_history_as_canonical_and_stream_as_provisional(self) -> None:
        self.append_reconciled("AAA", "2026-08-05T14:30:00Z", 10, 11, 9, 10.5, 100)
        self.append_stream("AAA", "2026-08-05T14:31:00Z", 10.5, 12, 10, 11, 110.25, received="2026-08-05T14:31:30Z")

        snapshot = self.service().snapshot("AAA", "1m", observed_at=at("2026-08-05T14:31:45Z"))

        self.assertEqual("AVAILABLE", snapshot["state"])
        self.assertEqual(2, len(snapshot["candles"]))
        canonical, provisional = snapshot["candles"]
        self.assertTrue(canonical["isCanonical"])
        self.assertEqual(SCHWAB_PRICE_HISTORY_SOURCE, canonical["source"])
        self.assertFalse(canonical["isInProgress"])
        self.assertFalse(provisional["isCanonical"])
        self.assertTrue(provisional["isInProgress"])
        self.assertEqual(110.25, provisional["volume"])
        self.assertEqual("2026-08-05T14:31:00Z", snapshot["quality"]["latestInProgressBarAt"])
        self.assertEqual("2026-08-05T14:30:00Z", snapshot["quality"]["latestCompletedBarAt"])
        self.assertIn("No provider call", snapshot["lineage"]["summary"])

    def test_completed_unreconciled_bar_makes_snapshot_partial(self) -> None:
        self.append_reconciled("AAA", "2026-08-05T14:30:00Z", 10, 11, 9, 10.5, 100)
        self.append_stream("AAA", "2026-08-05T14:31:00Z", 10.5, 12, 10, 11, 110, received="2026-08-05T14:32:05Z")

        snapshot = self.service().snapshot("AAA", "1m", observed_at=at("2026-08-05T14:32:10Z"))

        self.assertEqual("PARTIAL", snapshot["state"])
        self.assertEqual(1, snapshot["quality"]["unreconciledCount"])
        self.assertIn("UNRECONCILED:1", snapshot["quality"]["findings"])

    def test_five_minute_aggregation_is_derived_only_from_stored_one_minute_rows(self) -> None:
        for minute, values in enumerate(
            [
                (10, 11, 9, 10.5, 100),
                (10.5, 12, 10, 11, 110),
                (11, 13, 10.5, 12.5, 120),
                (12.5, 14, 12, 13, 130),
                (13, 15, 12.5, 14, 140),
            ]
        ):
            self.append_reconciled("AAA", f"2026-08-05T14:3{minute}:00Z", *values)

        snapshot = self.service().snapshot("AAA", "5m", observed_at=at("2026-08-05T14:36:00Z"))

        self.assertEqual("INSUFFICIENT_DATA", snapshot["state"])
        self.assertEqual(1, len(snapshot["candles"]))
        candle = snapshot["candles"][0]
        self.assertEqual(10, candle["open"])
        self.assertEqual(15, candle["high"])
        self.assertEqual(9, candle["low"])
        self.assertEqual(14, candle["close"])
        self.assertEqual(600, candle["volume"])
        self.assertEqual(5, candle["presentMinuteCount"])
        self.assertEqual(5, candle["expectedMinuteCount"])
        self.assertTrue(candle["isCanonical"])

    def test_missing_minutes_remain_visible_in_aggregated_quality(self) -> None:
        self.append_reconciled("AAA", "2026-08-05T14:30:00Z", 10, 11, 9, 10.5, 100)
        self.append_reconciled("AAA", "2026-08-05T14:32:00Z", 10.5, 12, 10, 11, 110)
        self.append_reconciled("AAA", "2026-08-05T14:35:00Z", 11, 13, 10.5, 12, 120)

        one_minute = self.service().snapshot("AAA", "1m", observed_at=at("2026-08-05T14:36:00Z"))
        five_minute = self.service().snapshot("AAA", "5m", observed_at=at("2026-08-05T14:36:00Z"))

        self.assertEqual("PARTIAL", one_minute["state"])
        self.assertEqual(2, one_minute["quality"]["gapCount"])
        self.assertEqual("PARTIAL", five_minute["state"])
        self.assertEqual(2, five_minute["quality"]["gapCount"])
        self.assertEqual("GAP", five_minute["candles"][0]["state"])
        self.assertTrue(five_minute["candles"][0]["hasGapBefore"])
        self.assertEqual(2, five_minute["candles"][0]["presentMinuteCount"])

    def test_history_correction_is_canonical_and_visibly_marked(self) -> None:
        self.append_stream("AAA", "2026-08-05T14:30:00Z", 10, 11, 9, 10.4, 100, received="2026-08-05T14:30:30Z")
        self.append_history("AAA", "2026-08-05T14:30:00Z", 10, 11, 9, 10.5, 101)
        self.append_reconciled("AAA", "2026-08-05T14:31:00Z", 10.5, 12, 10, 11, 110)

        snapshot = self.service().snapshot("AAA", "1m", observed_at=at("2026-08-05T14:32:00Z"))

        corrected = snapshot["candles"][0]
        self.assertEqual("CORRECTED", corrected["state"])
        self.assertTrue(corrected["isCanonical"])
        self.assertEqual(10.5, corrected["close"])
        self.assertEqual(["close", "volume"], corrected["discrepancyFields"])
        self.assertEqual(1, snapshot["quality"]["correctionCount"])

    def test_fifteen_minute_aggregation_never_crosses_session_date_boundary(self) -> None:
        self.append_reconciled("AAA", "2026-08-04T19:59:00Z", 10, 11, 9, 10.5, 100)
        self.append_reconciled("AAA", "2026-08-05T13:30:00Z", 20, 21, 19, 20.5, 200)

        snapshot = self.service().snapshot("AAA", "15m", observed_at=at("2026-08-05T13:31:00Z"))

        self.assertEqual(2, len(snapshot["candles"]))
        self.assertNotEqual(snapshot["candles"][0]["timestamp"][:10], snapshot["candles"][1]["timestamp"][:10])
        self.assertEqual(10, snapshot["candles"][0]["open"])
        self.assertEqual(20, snapshot["candles"][1]["open"])

    def test_stale_schwab_evidence_remains_visible_and_labeled(self) -> None:
        self.append_reconciled("AAA", "2026-08-05T14:30:00Z", 10, 11, 9, 10.5, 100)
        self.append_reconciled("AAA", "2026-08-05T14:31:00Z", 10.5, 12, 10, 11, 110)

        snapshot = self.service().snapshot("AAA", "1m", observed_at=at("2026-08-05T14:40:00Z"))

        self.assertEqual("STALE", snapshot["state"])
        self.assertEqual(2, len(snapshot["candles"]))
        self.assertTrue(snapshot["quality"]["stale"])
        self.assertGreater(snapshot["quality"]["ageSeconds"], 180)

    def test_missing_store_unknown_symbol_and_tampered_partition_fail_closed(self) -> None:
        missing = self.service().snapshot("AAA", "1m", observed_at=at("2026-08-05T14:30:00Z"))
        self.append_reconciled("BBB", "2026-08-05T14:30:00Z", 10, 11, 9, 10.5, 100)
        unknown = self.service().snapshot("AAA", "1m", observed_at=at("2026-08-05T14:30:00Z"))
        partition = self.store.partition_path("BBB", "2026-08-05")
        payload = json.loads(partition.read_text(encoding="utf-8"))
        payload["bars"][0]["canonicalCandle"]["close"] = 999
        partition.write_text(json.dumps(payload), encoding="utf-8")
        tampered = self.service().snapshot("BBB", "1m", observed_at=at("2026-08-05T14:30:00Z"))

        for snapshot in (missing, unknown, tampered):
            self.assertEqual("UNAVAILABLE", snapshot["state"])
            self.assertEqual([], snapshot["candles"])
            self.assertIn("No simulated, legacy, or cross-timeframe fallback", snapshot["summary"])

    def test_daily_correction_is_canonical_and_visibly_marked(self) -> None:
        self.write_daily([daily_record("AAA", "2026-08-05", 10, 12, 9, 11, 100)])
        self.daily_store.append_history(
            (
                SchwabDailyCandle(
                    symbol="AAA",
                    timestamp=at("2026-08-05T04:00:00Z"),
                    session_date="2026-08-05",
                    open=10,
                    high=13,
                    low=9,
                    close=12,
                    volume=110,
                    source=SCHWAB_PRICE_HISTORY_SOURCE,
                ),
            ),
            received_at=at("2026-08-06T12:00:00Z"),
        )

        snapshot = self.service().snapshot(
            "AAA", "Daily", observed_at=at("2026-08-06T16:00:00Z")
        )

        self.assertEqual("INSUFFICIENT_DATA", snapshot["state"])
        self.assertEqual("CORRECTED", snapshot["candles"][0]["state"])
        self.assertEqual(12, snapshot["candles"][0]["close"])
        self.assertEqual(["high", "close", "volume"], snapshot["candles"][0]["discrepancyFields"])
        self.assertEqual(1, snapshot["quality"]["correctionCount"])

    def test_daily_tampering_fails_closed(self) -> None:
        self.write_daily([daily_record("AAA", "2026-08-05", 10, 12, 9, 11, 100)])
        path = self.daily_store.symbol_path("AAA")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["bars"][0]["canonicalCandle"]["close"] = 999
        path.write_text(json.dumps(payload), encoding="utf-8")

        snapshot = self.service().snapshot(
            "AAA", "Daily", observed_at=at("2026-08-06T16:00:00Z")
        )

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertEqual([], snapshot["candles"])
        self.assertIn("unreadable or untrusted", snapshot["summary"])

    def test_legacy_daily_file_is_never_used_as_fallback(self) -> None:
        self.legacy_daily_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "records": [daily_record("AAA", "2026-08-05", 10, 12, 9, 11, 100)],
                }
            ),
            encoding="utf-8",
        )
        before = sha256(self.legacy_daily_path)

        snapshot = self.service().snapshot(
            "AAA", "Daily", observed_at=at("2026-08-06T16:00:00Z")
        )

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertEqual([], snapshot["candles"])
        self.assertNotIn(self.legacy_daily_path.name, snapshot["lineage"]["sourceLabel"])
        self.assertEqual(before, sha256(self.legacy_daily_path))

    def test_legacy_candle_file_is_never_used_as_intraday_fallback(self) -> None:
        self.legacy_path.write_text(
            json.dumps({"schema_version": 1, "bars": {"AAA": [minute_record()]}}),
            encoding="utf-8",
        )
        before = sha256(self.legacy_path)

        snapshot = self.service().snapshot("AAA", "1m", observed_at=at("2026-08-05T14:30:00Z"))

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertEqual([], snapshot["candles"])
        self.assertNotIn(self.legacy_path.name, snapshot["lineage"]["sourceLabel"])
        self.assertEqual(before, sha256(self.legacy_path))

    def test_chart_reads_do_not_mutate_daily_or_schwab_sources(self) -> None:
        self.write_daily(
            [
                daily_record("AAA", "2026-08-03", 10, 12, 9, 11, 100),
                daily_record("AAA", "2026-08-04", 11, 13, 10, 12, 200),
            ]
        )
        self.append_reconciled("AAA", "2026-08-05T14:30:00Z", 10, 11, 9, 10.5, 100)
        self.append_reconciled("AAA", "2026-08-05T14:31:00Z", 10.5, 12, 10, 11, 110)
        partition = self.store.partition_path("AAA", "2026-08-05")
        daily_partition = self.daily_store.symbol_path("AAA")
        before = {path: sha256(path) for path in (daily_partition, partition)}

        service = self.service()
        service.snapshot("AAA", "Daily", observed_at=at("2026-08-05T16:00:00Z"))
        service.snapshot("AAA", "1m", observed_at=at("2026-08-05T14:32:00Z"))
        service.snapshot("AAA", "5m", observed_at=at("2026-08-05T14:32:00Z"))

        self.assertEqual(before, {path: sha256(path) for path in before})

    def test_symbol_and_interval_are_validated(self) -> None:
        service = self.service()
        with self.assertRaises(ValueError):
            service.snapshot("../AAA", "Daily")
        with self.assertRaises(ValueError):
            service.snapshot("AAA", "60m")

    def test_missing_history_enqueues_one_background_load_and_reports_loading(self) -> None:
        coordinator = RecordingBackfillCoordinator(status="QUEUED")
        service = WorkstationChartService(
            paths=self.paths,
            backfill_coordinator=coordinator,
        )

        snapshot = service.snapshot(
            "AAA", "1m", observed_at=at("2026-08-06T14:00:00Z")
        )

        self.assertEqual([("AAA", "No stored 1m history is available.")], coordinator.calls)
        self.assertEqual("QUEUED", snapshot["historyLoad"]["status"])
        self.assertEqual("QUEUED", snapshot["quality"]["historyLoadStatus"])
        self.assertIn("LOADING HISTORY", snapshot["summary"])
        self.assertIn("HISTORY_LOAD_QUEUED", snapshot["quality"]["findings"])

    def test_shallow_and_market_hours_stale_history_request_backfill(self) -> None:
        coordinator = RecordingBackfillCoordinator(status="RUNNING")
        self.append_reconciled("AAA", "2026-08-06T13:30:00Z", 10, 11, 9, 10.5, 100)
        service = WorkstationChartService(
            paths=self.paths,
            backfill_coordinator=coordinator,
        )

        shallow = service.snapshot(
            "AAA", "1m", observed_at=at("2026-08-06T13:31:00Z")
        )
        for minute in range(1, 31):
            self.append_reconciled(
                "BBB",
                f"2026-08-06T13:{minute:02d}:00Z",
                10,
                11,
                9,
                10.5,
                100,
            )
        stale = service.snapshot(
            "BBB", "1m", observed_at=at("2026-08-06T14:00:30Z")
        )

        self.assertEqual("RUNNING", shallow["historyLoad"]["status"])
        self.assertEqual("RUNNING", stale["historyLoad"]["status"])
        self.assertIn("at least 30", coordinator.calls[0][1])
        self.assertIn("stale during the extended market window", coordinator.calls[1][1])

    def test_stale_history_outside_market_window_does_not_poll_provider(self) -> None:
        coordinator = RecordingBackfillCoordinator(status="QUEUED")
        for minute in range(30):
            self.append_reconciled(
                "AAA",
                f"2026-08-06T13:{minute:02d}:00Z",
                10,
                11,
                9,
                10.5,
                100,
            )
        service = WorkstationChartService(
            paths=self.paths,
            backfill_coordinator=coordinator,
        )

        snapshot = service.snapshot(
            "AAA", "1m", observed_at=at("2026-08-07T02:00:00Z")
        )

        self.assertEqual([], coordinator.calls)
        self.assertEqual("NOT_REQUESTED", snapshot["historyLoad"]["status"])

    def test_untrusted_store_is_never_automatically_repaired(self) -> None:
        self.append_reconciled("AAA", "2026-08-06T13:30:00Z", 10, 11, 9, 10.5, 100)
        partition = self.store.partition_path("AAA", "2026-08-06")
        payload = json.loads(partition.read_text(encoding="utf-8"))
        payload["bars"][0]["canonicalCandle"]["close"] = 999
        partition.write_text(json.dumps(payload), encoding="utf-8")
        coordinator = RecordingBackfillCoordinator(status="QUEUED")
        service = WorkstationChartService(
            paths=self.paths,
            backfill_coordinator=coordinator,
        )

        snapshot = service.snapshot(
            "AAA", "1m", observed_at=at("2026-08-06T14:00:00Z")
        )

        self.assertEqual("UNAVAILABLE", snapshot["state"])
        self.assertEqual([], coordinator.calls)
        self.assertEqual("NOT_REQUESTED", snapshot["historyLoad"]["status"])
        self.assertIn("never repaired automatically", snapshot["historyLoad"]["detail"])

    def service(self) -> WorkstationChartService:
        return WorkstationChartService(paths=self.paths)

    def write_daily(self, records: list[dict]) -> None:
        candles = [
            SchwabDailyCandle(
                symbol=str(record["symbol"]),
                timestamp=at(f"{record['date']}T04:00:00Z"),
                session_date=str(record["date"]),
                open=float(record["open"]),
                high=float(record["high"]),
                low=float(record["low"]),
                close=float(record["close"]),
                volume=float(record["volume"]),
                source=SCHWAB_PRICE_HISTORY_SOURCE,
            )
            for record in records
        ]
        self.daily_store.append_history(
            candles,
            received_at=at("2026-08-05T12:00:00Z"),
        )

    def append_reconciled(
        self,
        symbol: str,
        timestamp: str,
        open_value: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        self.append_stream(
            symbol,
            timestamp,
            open_value,
            high,
            low,
            close,
            volume,
            received=timestamp,
        )
        self.append_history(symbol, timestamp, open_value, high, low, close, volume)

    def append_stream(
        self,
        symbol: str,
        timestamp: str,
        open_value: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        *,
        received: str,
    ) -> None:
        candle = schwab_candle(
            symbol,
            timestamp,
            open_value,
            high,
            low,
            close,
            volume,
            SCHWAB_CHART_EQUITY_SOURCE,
        )
        self.store.append_stream(
            [
                SchwabStreamCandleObservation(
                    arrival_index=0,
                    payload_index=0,
                    received_at=at(received),
                    candle=candle,
                    minute_identity=minute_identity(candle),
                    update_kind="FIRST_OBSERVATION",
                    changed_fields=(),
                    out_of_order=False,
                    sequence_delta_from_previous_arrival=None,
                )
            ]
        )

    def append_history(
        self,
        symbol: str,
        timestamp: str,
        open_value: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> None:
        self.store.append_history(
            [
                schwab_candle(
                    symbol,
                    timestamp,
                    open_value,
                    high,
                    low,
                    close,
                    volume,
                    SCHWAB_PRICE_HISTORY_SOURCE,
                )
            ],
            received_at=at(timestamp),
        )


def schwab_candle(
    symbol: str,
    timestamp: str,
    open_value: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    source: str,
) -> SchwabMinuteCandle:
    return SchwabMinuteCandle(
        symbol=symbol,
        timestamp=at(timestamp),
        open=open_value,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=source,
    )


def daily_record(
    symbol: str,
    date: str,
    open_value: float,
    high: float,
    low: float,
    close: float,
    volume: int,
) -> dict:
    return {
        "symbol": symbol,
        "date": date,
        "open": open_value,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "source": "synthetic_test_fixture",
    }


def minute_record() -> dict:
    return {
        "symbol": "AAA",
        "timestamp": "2026-08-05T14:30:00Z",
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10.5,
        "volume": 100,
        "source": "legacy_synthetic_fixture",
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordingBackfillCoordinator:
    def __init__(self, *, status: str) -> None:
        self.request_status = status
        self.calls: list[tuple[str, str]] = []

    def request(self, symbol: str, *, reason: str) -> dict[str, object]:
        self.calls.append((symbol, reason))
        return {
            "schemaVersion": 1,
            "symbol": symbol,
            "status": self.request_status,
            "detail": reason,
            "requestedAt": "2026-08-06T14:00:00Z",
            "startedAt": None,
            "completedAt": None,
            "attemptCount": 1,
            "coalesced": False,
            "networkMayRun": True,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def status(self, symbol: str) -> dict[str, object] | None:
        return None


if __name__ == "__main__":
    unittest.main()
