from __future__ import annotations

import csv
import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_migration import run_sqlite_migration
from momentum_hunter.sqlite_store import (
    capture_candidate_index_count,
    capture_index_count,
    connect_database,
    import_capture_candidate_index,
    read_capture_candidates,
    read_captures,
)
from momentum_hunter.storage import file_sha256


class SQLiteCaptureIndexStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-capture-index-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.captures_dir = self.root / "captures"
        self.analysis_path = self.root / "analysis-captures.csv"
        self.raw_path = self.captures_dir / "2026-06-25" / "morning.json"
        write_raw_capture(self.raw_path)
        write_analysis_capture_csv(
            self.analysis_path,
            [
                analysis_row("2026-06-25T07:00:00-05:00", "morning", 1, "AAA", 91, 10.25),
                analysis_row("2026-06-25T07:00:00-05:00", "morning", 2, "BBB", 84, 20.5),
            ],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_capture_index_import_round_trips_without_mutating_sources(self) -> None:
        csv_hash = file_sha256(self.analysis_path)
        raw_hash = file_sha256(self.raw_path)

        result = import_capture_candidate_index(
            self.analysis_path,
            db_path=self.db_path,
            captures_dir=self.captures_dir,
        )

        with connect_database(self.db_path) as connection:
            captures = read_captures(connection)
            candidates = read_capture_candidates(connection)
            aaa = read_capture_candidates(connection, ticker="AAA")

        self.assertEqual(2, result.analysis_rows_seen)
        self.assertEqual(1, result.captures_seen)
        self.assertEqual(1, result.captures_inserted)
        self.assertEqual(2, result.candidates_seen)
        self.assertEqual(2, result.candidates_inserted)
        self.assertEqual(1, len(captures))
        self.assertEqual(2, len(candidates))
        self.assertEqual("morning", captures[0]["session"])
        self.assertEqual(1, captures[0]["is_market_open_day"])
        self.assertEqual(raw_hash, captures[0]["source_hash"])
        self.assertEqual("AAA", aaa[0]["ticker"])
        self.assertEqual(91, aaa[0]["score"])
        self.assertEqual(10.25, aaa[0]["price"])
        self.assertEqual(csv_hash, file_sha256(self.analysis_path))
        self.assertEqual(raw_hash, file_sha256(self.raw_path))

    def test_capture_index_import_is_idempotent(self) -> None:
        first = import_capture_candidate_index(self.analysis_path, db_path=self.db_path, captures_dir=self.captures_dir)
        second = import_capture_candidate_index(self.analysis_path, db_path=self.db_path, captures_dir=self.captures_dir)

        with connect_database(self.db_path) as connection:
            capture_count = capture_index_count(connection)
            candidate_count = capture_candidate_index_count(connection)

        self.assertEqual(1, first.captures_inserted)
        self.assertEqual(0, second.captures_inserted)
        self.assertEqual(1, second.captures_skipped)
        self.assertEqual(0, second.candidates_inserted)
        self.assertEqual(2, second.candidates_skipped)
        self.assertEqual(1, capture_count)
        self.assertEqual(2, candidate_count)

    def test_capture_index_updates_when_candidate_row_matures(self) -> None:
        import_capture_candidate_index(self.analysis_path, db_path=self.db_path, captures_dir=self.captures_dir)
        write_analysis_capture_csv(
            self.analysis_path,
            [
                analysis_row("2026-06-25T07:00:00-05:00", "morning", 1, "AAA", 95, 10.25),
                analysis_row("2026-06-25T07:00:00-05:00", "morning", 2, "BBB", 84, 20.5),
            ],
        )

        result = import_capture_candidate_index(self.analysis_path, db_path=self.db_path, captures_dir=self.captures_dir)

        with connect_database(self.db_path) as connection:
            aaa = read_capture_candidates(connection, ticker="AAA")

        self.assertEqual(1, result.captures_updated)
        self.assertEqual(2, result.candidates_updated)
        self.assertEqual(95, aaa[0]["score"])

    def test_missing_raw_capture_is_warned_but_indexed_from_csv(self) -> None:
        missing_root = self.root / "missing-captures"

        result = import_capture_candidate_index(self.analysis_path, db_path=self.db_path, captures_dir=missing_root)

        with connect_database(self.db_path) as connection:
            captures = read_captures(connection)

        self.assertEqual(1, result.captures_inserted)
        self.assertEqual("", captures[0]["source_hash"])
        self.assertTrue(any("RAW_CAPTURE_JSON_MISSING" in warning for warning in result.warnings))

    def test_sqlite_migration_writes_capture_index_report(self) -> None:
        payload = run_sqlite_migration(
            db_path=self.db_path,
            analysis_captures_path=self.analysis_path,
            import_provider_quality=False,
            import_capture_index_slice=True,
            capture_index_report_json=self.root / "sqlite-capture-index-import-latest.json",
            capture_index_report_md=self.root / "sqlite-capture-index-import-latest.md",
        )

        self.assertEqual(7, payload["schema_version"])
        self.assertIsNotNone(payload["capture_index_import"])
        self.assertTrue((self.root / "sqlite-capture-index-import-latest.json").exists())
        self.assertTrue((self.root / "sqlite-capture-index-import-latest.md").exists())


def analysis_row(capture_time: str, session: str, rank: int, ticker: str, score: int, price: float) -> dict[str, object]:
    return {
        "capture_date": "2026-06-25",
        "capture_time": capture_time,
        "session": session,
        "capture_session": session,
        "capture_calendar_status": "MARKET_OPEN_DAY",
        "is_market_open_day": "True",
        "is_study_eligible": "True",
        "next_market_session_date": "2026-06-25",
        "scheduling_policy_version": "market-calendar-v1",
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": "Base Momentum",
        "market_regime": "bull",
        "rank": rank,
        "ticker": ticker,
        "company": f"{ticker} Corp",
        "score": score,
        "freshness": "HOT",
        "freshness_score": 99,
        "article_count": 3,
        "price": price,
        "percent_change": 5.5,
        "volume": 1234567,
        "relative_volume": 1.8,
        "market_cap": 5000000000,
        "sector": "Technology",
        "industry": "Software",
    }


def write_analysis_capture_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_raw_capture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "capture_date": "2026-06-25",
                "capture_time": "2026-06-25T07:00:00-05:00",
                "session": "morning",
                "provider": "finviz",
                "scanner": {"name": "Base Momentum"},
                "candidates": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
