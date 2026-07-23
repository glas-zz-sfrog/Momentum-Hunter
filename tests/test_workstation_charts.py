from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.workstation_charts import (
    WorkstationChartPaths,
    WorkstationChartService,
)


def at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class WorkstationChartServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.daily_path = root / "daily-ohlc-bars.json"
        self.minute_path = root / "opportunity-minute-bars.json"
        self.paths = WorkstationChartPaths(
            minute_bars_path=self.minute_path,
            daily_ohlc_path=self.daily_path,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_daily_snapshot_maps_only_valid_stored_bars(self) -> None:
        self.write_daily(
            [
                daily_record("AAA", "2026-01-02", 10, 12, 9, 11, 100),
                daily_record("AAA", "2026-01-05", 11, 13, 10, 12, 200),
                daily_record("AAA", "2026-01-06", 12, 11, 10, 12, 300),
                daily_record("BBB", "2026-01-05", 20, 21, 19, 20, 400),
            ]
        )

        snapshot = self.service().snapshot("aaa", "Daily", observed_at=at("2026-01-07T12:00:00Z"))

        self.assertEqual("AAA", snapshot["symbol"])
        self.assertEqual("Daily", snapshot["interval"])
        self.assertEqual("AVAILABLE", snapshot["state"])
        self.assertEqual(2, len(snapshot["candles"]))
        self.assertEqual("2026-01-02T00:00:00Z", snapshot["candles"][0]["timestamp"])
        self.assertEqual(12.0, snapshot["candles"][-1]["close"])
        self.assertIn("daily-ohlc-bars.json", snapshot["summary"])
        self.assertIn("no provider fetch", snapshot["summary"])

    def test_one_minute_and_five_minute_snapshots_preserve_ohlcv(self) -> None:
        self.write_minutes(
            "AAA",
            [
                minute_record("2026-01-05T09:30:00-05:00", 10, 11, 9, 10.5, 100),
                minute_record("2026-01-05T09:31:00-05:00", 10.5, 12, 10, 11, 110),
                minute_record("2026-01-05T09:34:00-05:00", 11, 13, 10.5, 12.5, 120),
                minute_record("2026-01-05T09:35:00-05:00", 12.5, 14, 12, 13, 130),
            ],
        )

        one_minute = self.service().snapshot("AAA", "1m", observed_at=at("2026-01-05T16:00:00Z"))
        five_minute = self.service().snapshot("AAA", "5m", observed_at=at("2026-01-05T16:00:00Z"))

        self.assertEqual(4, len(one_minute["candles"]))
        self.assertEqual(2, len(five_minute["candles"]))
        first = five_minute["candles"][0]
        self.assertEqual(10.0, first["open"])
        self.assertEqual(13.0, first["high"])
        self.assertEqual(9.0, first["low"])
        self.assertEqual(12.5, first["close"])
        self.assertEqual(330, first["volume"])

    def test_fifteen_minute_aggregation_never_crosses_a_day_boundary(self) -> None:
        self.write_minutes(
            "AAA",
            [
                minute_record("2026-01-05T15:59:00-05:00", 10, 11, 9, 10.5, 100),
                minute_record("2026-01-06T09:30:00-05:00", 20, 21, 19, 20.5, 200),
            ],
        )

        snapshot = self.service().snapshot("AAA", "15m", observed_at=at("2026-01-06T16:00:00Z"))

        self.assertEqual(2, len(snapshot["candles"]))
        self.assertNotEqual(snapshot["candles"][0]["timestamp"][:10], snapshot["candles"][1]["timestamp"][:10])
        self.assertEqual(10.0, snapshot["candles"][0]["open"])
        self.assertEqual(20.0, snapshot["candles"][1]["open"])

    def test_stale_evidence_remains_visible_and_is_labeled(self) -> None:
        self.write_daily([daily_record("AAA", "2026-01-02", 10, 12, 9, 11, 100), daily_record("AAA", "2026-01-05", 11, 13, 10, 12, 200)])

        snapshot = self.service().snapshot("AAA", "Daily", observed_at=at("2026-01-20T12:00:00Z"))

        self.assertEqual("STALE", snapshot["state"])
        self.assertEqual(2, len(snapshot["candles"]))
        self.assertTrue(snapshot["summary"].startswith("STALE |"))

    def test_single_old_candle_remains_insufficient_instead_of_appearing_stale_but_usable(self) -> None:
        self.write_daily([daily_record("AAA", "2026-01-02", 10, 12, 9, 11, 100)])

        snapshot = self.service().snapshot("AAA", "Daily", observed_at=at("2026-01-20T12:00:00Z"))

        self.assertEqual("INSUFFICIENT_DATA", snapshot["state"])
        self.assertEqual(1, len(snapshot["candles"]))
        self.assertTrue(snapshot["summary"].startswith("INSUFFICIENT DATA |"))

    def test_missing_malformed_and_unknown_symbol_are_unavailable_without_fallback(self) -> None:
        missing = self.service().snapshot("AAA", "Daily", observed_at=at("2026-01-06T12:00:00Z"))
        self.daily_path.write_text("{not-json", encoding="utf-8")
        malformed = self.service().snapshot("AAA", "Daily", observed_at=at("2026-01-06T12:00:00Z"))
        self.write_minutes("BBB", [minute_record("2026-01-05T09:30:00-05:00", 10, 11, 9, 10.5, 100)])
        unknown = self.service().snapshot("AAA", "1m", observed_at=at("2026-01-05T16:00:00Z"))

        for snapshot in (missing, malformed, unknown):
            self.assertEqual("UNAVAILABLE", snapshot["state"])
            self.assertEqual([], snapshot["candles"])
            self.assertIn("No simulated or cross-timeframe fallback", snapshot["summary"])

    def test_chart_reads_do_not_mutate_source_files(self) -> None:
        self.write_daily([daily_record("AAA", "2026-01-02", 10, 12, 9, 11, 100), daily_record("AAA", "2026-01-05", 11, 13, 10, 12, 200)])
        self.write_minutes("AAA", [minute_record("2026-01-05T09:30:00-05:00", 10, 11, 9, 10.5, 100)])
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.daily_path, self.minute_path)}

        service = self.service()
        service.snapshot("AAA", "Daily", observed_at=at("2026-01-06T12:00:00Z"))
        service.snapshot("AAA", "1m", observed_at=at("2026-01-05T16:00:00Z"))

        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (self.daily_path, self.minute_path)}
        self.assertEqual(before, after)

    def test_symbol_and_interval_are_validated(self) -> None:
        service = self.service()

        with self.assertRaises(ValueError):
            service.snapshot("../AAA", "Daily")
        with self.assertRaises(ValueError):
            service.snapshot("AAA", "60m")

    def service(self) -> WorkstationChartService:
        return WorkstationChartService(paths=self.paths)

    def write_daily(self, records: list[dict]) -> None:
        self.daily_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_at": "2026-01-06T12:00:00Z",
                    "records": records,
                }
            ),
            encoding="utf-8",
        )

    def write_minutes(self, symbol: str, records: list[dict]) -> None:
        self.minute_path.write_text(
            json.dumps({"schema_version": 1, "bars": {symbol: records}}),
            encoding="utf-8",
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


def minute_record(
    timestamp: str,
    open_value: float,
    high: float,
    low: float,
    close: float,
    volume: int,
) -> dict:
    return {
        "symbol": "AAA",
        "timestamp": timestamp,
        "open": open_value,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "source": "synthetic_test_fixture",
    }


if __name__ == "__main__":
    unittest.main()
