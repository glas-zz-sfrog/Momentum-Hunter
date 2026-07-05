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
    DailyOhlcUniverseRow,
    build_daily_ohlc_coverage_report,
    build_daily_ohlc_universe,
    expand_daily_ohlc_cache,
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

    def test_universe_builder_classifies_and_prioritizes_symbols(self) -> None:
        captures = self.root / "analysis-captures.csv"
        captures.write_text(
            "\n".join(
                [
                    "capture_date,ticker,score",
                    "2026-06-20,AAA,90",
                    "2026-06-21,AAA,91",
                    "2026-06-21,BBB,70",
                ]
            ),
            encoding="utf-8",
        )
        outcomes = self.root / "analysis-outcomes.csv"
        outcomes.write_text("capture_date,ticker\n2026-06-21,CCC\n", encoding="utf-8")
        alerts = self.root / "opportunity-alerts.json"
        alerts.write_text(json.dumps({"alerts": [{"symbol": "DDD", "timestamp": "2026-06-21T10:00:00-05:00"}]}), encoding="utf-8")
        reviews = self.root / "review-decisions.json"
        reviews.write_text(
            json.dumps(
                {
                    "decisions": {
                        "one": {
                            "identity": {"ticker": "EEE"},
                            "review_status": "watchlist",
                            "decision_timestamp": "2026-06-21T11:00:00-05:00",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        plans = self.root / "entry-plans.json"
        plans.write_text(json.dumps({"plans": {"one": {"identity": {"ticker": "FFF"}, "updated_at": "2026-06-21"}}}), encoding="utf-8")
        reports = self.root / "reports"
        reports.mkdir()
        (reports / "opportunity-monitor-targets-20260621.json").write_text(
            json.dumps({"targets": [{"symbol": "GGG"}]}),
            encoding="utf-8",
        )

        rows = build_daily_ohlc_universe(
            captures_path=captures,
            outcomes_path=outcomes,
            alerts_path=alerts,
            review_decisions_path=reviews,
            entry_plans_path=plans,
            score_breakdowns_path=self.root / "missing-score-breakdowns.json",
            reports_dir=reports,
            watchlist_dir=self.root,
        )
        by_symbol = {row.symbol: row for row in rows}

        self.assertEqual(0, by_symbol["QQQ"].priority)
        self.assertEqual(1, by_symbol["DDD"].priority)
        self.assertEqual(1, by_symbol["EEE"].priority)
        self.assertEqual(1, by_symbol["FFF"].priority)
        self.assertEqual(1, by_symbol["GGG"].priority)
        self.assertEqual(2, by_symbol["AAA"].priority)
        self.assertIn("repeated_capture_candidates", by_symbol["AAA"].categories)
        self.assertIn("recent_high_score_capture_symbols", by_symbol["AAA"].categories)

    def test_expand_cache_preserves_existing_and_records_failed_symbol(self) -> None:
        cache = self.root / "daily-ohlc-bars.json"
        existing = valid_record("AAA", "2026-01-02")
        write_daily_ohlc_cache([existing], path=cache, generated_at="2026-01-03T00:00:00-05:00")
        before = json.loads(cache.read_text(encoding="utf-8"))
        rows = [
            DailyOhlcUniverseRow(symbol="AAA", priority=1, categories=["alert_symbols"], source_counts={}),
            DailyOhlcUniverseRow(symbol="BBB", priority=1, categories=["alert_symbols"], source_counts={}),
            DailyOhlcUniverseRow(symbol="FAIL", priority=1, categories=["alert_symbols"], source_counts={}),
        ]

        result = expand_daily_ohlc_cache(
            rows,
            cache_path=cache,
            generated_at="2026-01-04T00:00:00-05:00",
            session=FakeSession(),
            retry_limit=0,
            delay_seconds=0,
        )
        payload = json.loads(cache.read_text(encoding="utf-8"))
        loaded = load_daily_ohlc_records(cache, requested_symbols=["AAA", "BBB", "FAIL"])

        self.assertEqual(1, len(before["records"]))
        self.assertIn("BBB", result.fetched_symbols)
        self.assertIn("FAIL", result.failed_symbols)
        self.assertIn("AAA", result.skipped_symbols)
        self.assertEqual({"AAA", "BBB"}, {record.symbol for record in loaded.valid_records})
        self.assertEqual(["FAIL"], loaded.missing_symbols)

    def test_coverage_report_includes_category_coverage_and_failed_symbols(self) -> None:
        source = write_source(self.root, [valid_record("AAA", "2026-01-02"), valid_record("ZZZ", "2026-01-02")])
        result = load_daily_ohlc_records(source, requested_symbols=["AAA", "BBB"])
        rows = [
            DailyOhlcUniverseRow(symbol="AAA", priority=1, categories=["alert_symbols"], source_counts={}),
            DailyOhlcUniverseRow(symbol="BBB", priority=1, categories=["alert_symbols"], source_counts={}),
        ]

        report = build_daily_ohlc_coverage_report(
            result,
            requested_symbols=["AAA", "BBB"],
            universe_rows=rows,
            failed_symbols=["BBB"],
        )

        self.assertEqual(50.0, report["summary"]["coverage_pct"])
        self.assertEqual(1, report["summary"]["covered_symbols"])
        self.assertEqual(1, report["summary"]["failed_symbols"])
        self.assertEqual(50.0, report["coverage_by_category"][0]["coverage_pct"])
        self.assertEqual(["BBB"], report["failed_symbols"])


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


class FakeSession:
    def get(self, url: str, timeout: int):
        if "FAIL" in url:
            return FakeResponse(503, {})
        return FakeResponse(
            200,
            {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1767225600],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [10.0],
                                        "high": [11.0],
                                        "low": [9.0],
                                        "close": [10.0],
                                        "volume": [1000],
                                    }
                                ],
                                "adjclose": [{"adjclose": [10.0]}],
                            },
                        }
                    ]
                }
            },
        )


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


if __name__ == "__main__":
    unittest.main()
