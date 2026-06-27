from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_benchmarks import build_sqlite_benchmark_report, write_sqlite_benchmark_report
from momentum_hunter.sqlite_store import connect_database, initialize_schema
from tests.test_sqlite_analytics import seed_database


class SQLiteBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-benchmarks-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "benchmarks.sqlite3"
        with connect_database(self.db_path) as connection:
            initialize_schema(connection)
            seed_database(connection)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_benchmark_report_runs_read_only_queries(self) -> None:
        payload = build_sqlite_benchmark_report(db_path=self.db_path, slow_query_ms=1000.0)

        self.assertEqual("PASS", payload["overall_status"])
        names = {item["name"] for item in payload["benchmarks"]}
        self.assertIn("candidate_history_by_symbol", names)
        self.assertIn("alert_outcome_counts", names)
        self.assertTrue(all(item["elapsed_ms"] >= 0 for item in payload["benchmarks"]))

    def test_missing_database_warns_without_creating_database(self) -> None:
        missing = self.root / "missing.sqlite3"

        payload = build_sqlite_benchmark_report(db_path=missing)

        self.assertEqual("WARN", payload["overall_status"])
        self.assertIn("SQLITE_DATABASE_MISSING", payload["warnings"])
        self.assertFalse(missing.exists())

    def test_benchmark_report_writes_json_and_markdown(self) -> None:
        payload = build_sqlite_benchmark_report(db_path=self.db_path)
        paths = write_sqlite_benchmark_report(
            payload,
            json_path=self.root / "sqlite-query-benchmark-latest.json",
            markdown_path=self.root / "sqlite-query-benchmark-latest.md",
        )

        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())
        self.assertIn("SQLite Query Benchmark", paths["markdown"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
