from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.alert_outcome_updater import MinutePriceBar, save_minute_bars
from momentum_hunter.sqlite_store import (
    connect_database,
    import_minute_bars,
    minute_bar_count,
    read_minute_bars,
)
from momentum_hunter.storage import file_sha256


class SQLiteMinuteBarsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-minute-bars-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.minute_bars_path = self.root / "opportunity-minute-bars.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_minute_bar_insert_read_round_trip_with_symbol_counts(self) -> None:
        save_minute_bars(
            {
                "AAA": [
                    bar("AAA", "2026-06-18T10:00:00-05:00", close=10.10),
                    bar("AAA", "2026-06-18T10:01:00-05:00", close=10.20),
                ],
                "BBB": [bar("BBB", "2026-06-18T10:00:00-05:00", close=20.10, source="provider_1m")],
            },
            self.minute_bars_path,
        )
        before_hash = file_sha256(self.minute_bars_path)

        result = import_minute_bars(self.minute_bars_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            rows = read_minute_bars(connection)
            aaa_rows = read_minute_bars(connection, symbol="aaa")

        self.assertEqual(2, result.symbols_seen)
        self.assertEqual(3, result.bars_seen)
        self.assertEqual(3, result.valid_bars)
        self.assertEqual(0, result.invalid_bars)
        self.assertEqual(3, result.bars_inserted)
        self.assertEqual(0, result.bars_updated)
        self.assertEqual(0, result.bars_skipped)
        self.assertEqual({"AAA": 2, "BBB": 1}, result.symbol_counts)
        self.assertEqual("2026-06-18T10:00:00-05:00", result.first_timestamps["AAA"])
        self.assertEqual("2026-06-18T10:01:00-05:00", result.latest_timestamps["AAA"])
        self.assertEqual(3, len(rows))
        self.assertEqual(2, len(aaa_rows))
        self.assertEqual("1m", aaa_rows[0]["granularity"])
        self.assertEqual(10.1, aaa_rows[0]["close"])
        self.assertEqual(before_hash, file_sha256(self.minute_bars_path))

    def test_repeated_minute_bar_import_is_idempotent(self) -> None:
        save_minute_bars({"AAA": [bar("AAA", "2026-06-18T10:00:00-05:00")]}, self.minute_bars_path)

        first = import_minute_bars(self.minute_bars_path, db_path=self.db_path)
        second = import_minute_bars(self.minute_bars_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            self.assertEqual(1, minute_bar_count(connection))
        self.assertEqual(1, first.bars_inserted)
        self.assertEqual(0, second.bars_inserted)
        self.assertEqual(0, second.bars_updated)
        self.assertEqual(1, second.bars_skipped)

    def test_minute_bar_import_updates_changed_existing_bar(self) -> None:
        save_minute_bars({"AAA": [bar("AAA", "2026-06-18T10:00:00-05:00", close=10.0)]}, self.minute_bars_path)
        import_minute_bars(self.minute_bars_path, db_path=self.db_path)
        save_minute_bars({"AAA": [bar("AAA", "2026-06-18T10:00:00-05:00", close=10.5)]}, self.minute_bars_path)

        result = import_minute_bars(self.minute_bars_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            rows = read_minute_bars(connection, symbol="AAA")

        self.assertEqual(0, result.bars_inserted)
        self.assertEqual(1, result.bars_updated)
        self.assertEqual(10.5, rows[0]["close"])

    def test_duplicate_source_bars_are_deduped_before_import(self) -> None:
        payload = {
            "schema_version": 1,
            "bars": {
                "AAA": [
                    raw_bar("AAA", "2026-06-18T10:00:00-05:00", close=10.0),
                    raw_bar("AAA", "2026-06-18T10:00:00-05:00", close=10.4),
                ]
            },
        }
        self.minute_bars_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        result = import_minute_bars(self.minute_bars_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            rows = read_minute_bars(connection, symbol="AAA")

        self.assertEqual(2, result.valid_bars)
        self.assertEqual(1, result.duplicate_bars)
        self.assertEqual(1, result.bars_inserted)
        self.assertEqual(1, result.source_rows_in_sqlite)
        self.assertEqual(10.4, rows[0]["close"])
        self.assertTrue(any(warning.startswith("DUPLICATE_MINUTE_BARS_IN_SOURCE") for warning in result.warnings))

    def test_invalid_minute_bar_rows_are_skipped_with_warnings_and_source_is_not_mutated(self) -> None:
        payload = {
            "schema_version": 1,
            "bars": {
                "AAA": [
                    raw_bar("AAA", "2026-06-18T10:00:00-05:00", close=10.0),
                    {"symbol": "AAA", "timestamp": "bad-time", "open": 10, "high": 10, "low": 10, "close": 10, "source": "bad_1m"},
                    {"symbol": "AAA", "timestamp": "2026-06-18T10:02:00-05:00", "open": 10, "high": 10, "low": 10},
                    "not-a-row",
                ]
            },
        }
        self.minute_bars_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        before_hash = file_sha256(self.minute_bars_path)

        result = import_minute_bars(self.minute_bars_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            rows = read_minute_bars(connection)

        self.assertEqual(4, result.bars_seen)
        self.assertEqual(1, result.valid_bars)
        self.assertEqual(3, result.invalid_bars)
        self.assertEqual(1, len(rows))
        self.assertTrue(any("INVALID_MINUTE_BAR_TIMESTAMP" in warning for warning in result.warnings))
        self.assertTrue(any("INVALID_MINUTE_BAR_ROW" in warning for warning in result.warnings))
        self.assertEqual(before_hash, file_sha256(self.minute_bars_path))


def bar(
    symbol: str,
    timestamp: str,
    *,
    close: float = 10.0,
    source: str = "yahoo_chart_1m",
) -> MinutePriceBar:
    return MinutePriceBar(
        symbol=symbol,
        timestamp=timestamp,
        open=close - 0.1,
        high=close + 0.2,
        low=close - 0.2,
        close=close,
        volume=1000,
        source=source,
    )


def raw_bar(symbol: str, timestamp: str, *, close: float = 10.0, source: str = "yahoo_chart_1m") -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": 1000,
        "source": source,
    }


if __name__ == "__main__":
    unittest.main()
