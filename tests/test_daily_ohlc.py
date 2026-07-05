from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import unittest
import uuid
from pathlib import Path

from momentum_hunter.daily_ohlc import (
    QUALITY_INVALID,
    QUALITY_VALID,
    DailyOhlcRecord,
    build_daily_ohlc_coverage_report,
    load_daily_ohlc_records,
    mirror_daily_ohlc_to_sqlite,
    parse_yahoo_chart_daily_ohlc,
    write_daily_ohlc_cache,
    write_daily_ohlc_coverage_report,
)


class DailyOhlcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-daily-ohlc-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_valid_daily_ohlc_load(self) -> None:
        source = self.root / "daily-ohlc-bars.json"
        source.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "symbol": "AAA",
                            "date": "2026-01-02",
                            "open": 10.0,
                            "high": 11.0,
                            "low": 9.5,
                            "close": 10.8,
                            "volume": 1000,
                            "source": "test_daily",
                            "adjusted": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = load_daily_ohlc_records(source, requested_symbols=["AAA"], generated_at="2026-01-03T00:00:00-05:00")

        self.assertEqual(1, len(result.valid_records))
        self.assertEqual(0, len(result.invalid_records))
        self.assertEqual([], result.missing_symbols)
        self.assertEqual(QUALITY_VALID, result.valid_records[0].quality_status)

    def test_invalid_daily_ohlc_is_flagged(self) -> None:
        source = self.root / "daily-ohlc-bars.json"
        source.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "symbol": "AAA",
                            "date": "2026-01-02",
                            "open": 10.0,
                            "high": 9.0,
                            "low": 9.5,
                            "close": 10.8,
                            "volume": 1000,
                            "source": "test_daily",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        result = load_daily_ohlc_records(source, requested_symbols=["AAA"])

        self.assertEqual(0, len(result.valid_records))
        self.assertEqual(1, len(result.invalid_records))
        self.assertEqual(QUALITY_INVALID, result.invalid_records[0].quality_status)
        self.assertIn("IMPOSSIBLE_HIGH", result.invalid_records[0].warnings)

    def test_coverage_report_flags_missing_and_insufficient_history(self) -> None:
        record = valid_record("AAA", "2026-01-02")
        load_result = load_daily_ohlc_records(write_source(self.root, [record]), requested_symbols=["AAA", "BBB"])

        report = build_daily_ohlc_coverage_report(load_result, requested_symbols=["AAA", "BBB"], minimum_history_bars=50)

        self.assertEqual(1, report["summary"]["covered_symbols"])
        self.assertEqual(1, report["summary"]["missing_symbols"])
        self.assertEqual(1, report["summary"]["insufficient_history_symbols"])
        self.assertEqual(["BBB"], report["missing_symbols"])
        self.assertIn("INSUFFICIENT_HISTORY:1/50", report["symbols"][0]["warnings"])

    def test_write_cache_preserves_only_valid_records(self) -> None:
        path = self.root / "daily-ohlc-bars.json"
        valid = valid_record("AAA", "2026-01-02")
        invalid = DailyOhlcRecord(
            symbol="BBB",
            date="2026-01-02",
            open=10.0,
            high=9.0,
            low=10.0,
            close=10.0,
            volume=100,
            source="test",
            adjusted=True,
            imported_at="2026-01-03T00:00:00-05:00",
            quality_status=QUALITY_INVALID,
            warnings=["IMPOSSIBLE_HIGH"],
        )

        write_daily_ohlc_cache([valid, invalid], path=path, generated_at="2026-01-03T00:00:00-05:00")
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(1, len(payload["records"]))
        self.assertEqual("AAA", payload["records"][0]["symbol"])

    def test_coverage_report_writes_json_and_markdown_without_mutating_source(self) -> None:
        source = write_source(self.root, [valid_record("AAA", "2026-01-02")])
        before = sha256(source)
        load_result = load_daily_ohlc_records(source, requested_symbols=["AAA"])
        report = build_daily_ohlc_coverage_report(load_result, requested_symbols=["AAA"])

        paths = write_daily_ohlc_coverage_report(
            report,
            json_path=self.root / "daily-ohlc-coverage-latest.json",
            markdown_path=self.root / "daily-ohlc-coverage-latest.md",
        )

        self.assertEqual(before, sha256(source))
        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())

    def test_sqlite_mirror_is_additive_and_non_authoritative(self) -> None:
        db_path = self.root / "research.sqlite3"

        inserted = mirror_daily_ohlc_to_sqlite([valid_record("AAA", "2026-01-02")], db_path=db_path)

        self.assertEqual(1, inserted)
        with sqlite3.connect(db_path) as connection:
            count = connection.execute("SELECT COUNT(*) FROM research_daily_ohlc").fetchone()[0]
            source = connection.execute("SELECT source FROM research_daily_ohlc").fetchone()[0]
        self.assertEqual(1, count)
        self.assertEqual("test_daily", source)

    def test_yahoo_chart_payload_normalizes_adjusted_ohlc(self) -> None:
        records = parse_yahoo_chart_daily_ohlc(
            {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1767225600],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [100.0],
                                        "high": [110.0],
                                        "low": [90.0],
                                        "close": [100.0],
                                        "volume": [1234],
                                    }
                                ],
                                "adjclose": [{"adjclose": [50.0]}],
                            },
                        }
                    ]
                }
            },
            symbol="AAA",
            imported_at="2026-01-03T00:00:00-05:00",
        )

        self.assertEqual(1, len(records))
        self.assertEqual(50.0, records[0].open)
        self.assertEqual(55.0, records[0].high)
        self.assertEqual(45.0, records[0].low)
        self.assertEqual(50.0, records[0].close)
        self.assertTrue(records[0].adjusted)


def valid_record(symbol: str, date: str) -> DailyOhlcRecord:
    return DailyOhlcRecord(
        symbol=symbol,
        date=date,
        open=10.0,
        high=11.0,
        low=9.5,
        close=10.5,
        volume=1000,
        source="test_daily",
        adjusted=True,
        imported_at="2026-01-03T00:00:00-05:00",
        quality_status=QUALITY_VALID,
        warnings=[],
    )


def write_source(root: Path, records: list[DailyOhlcRecord]) -> Path:
    path = root / "daily-ohlc-bars.json"
    path.write_text(json.dumps({"records": [record.__dict__ for record in records]}, indent=2), encoding="utf-8")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
