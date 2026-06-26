from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.read_models import (
    build_read_model_summary,
    build_shadow_compare_read_model,
    resolve_read_model_source,
)
from momentum_hunter.sqlite_reports import main as sqlite_reports_main
from momentum_hunter.sqlite_store import connect_database, import_user_state
from momentum_hunter.storage import file_sha256
from tests.test_sqlite_user_state_store import write_user_state_fixture
from tests.test_sqlite_validation import import_all_sources, write_validation_sources


class SQLiteReadOnlyAdoptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-read-models-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.reports_dir = self.root / "reports"
        self.sources = write_validation_sources(self.root)
        import_all_sources(self.db_path, self.sources)
        write_user_state_fixture(self.root)
        import_user_state(
            review_decisions_path=self.root / "review-decisions.json",
            entry_plans_path=self.root / "entry-plans.json",
            data_dir=self.root,
            db_path=self.db_path,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_read_model_source_defaults_to_file_mode(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual("file", resolve_read_model_source())

        payload = build_read_model_summary(
            "evidence",
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
        )

        self.assertEqual("file", payload["source_mode"])
        self.assertEqual(3, payload["alert_count"])
        self.assertEqual(1, payload["completed_outcomes"])

    def test_sqlite_mode_reads_expected_summary(self) -> None:
        payload = build_read_model_summary("watchlist", source="sqlite", db_path=self.db_path)

        self.assertEqual("sqlite", payload["source_mode"])
        self.assertEqual(1, payload["review_watchlist_count"])
        self.assertEqual(1, payload["watchlist_count"])
        self.assertEqual(1, payload["complete_plans"])

    def test_missing_sqlite_database_reports_cleanly(self) -> None:
        payload = build_read_model_summary("candidate-story", source="sqlite", db_path=self.root / "missing.sqlite3")

        self.assertEqual("sqlite", payload["source_mode"])
        self.assertEqual("WARN", payload["overall_status"])
        self.assertIn("SQLITE_DATABASE_MISSING", payload["warnings"][0])

    def test_shadow_compare_detects_match_and_preserves_source_files(self) -> None:
        source_hashes = {
            "alerts": file_sha256(self.sources["alerts"]),
            "minute_bars": file_sha256(self.sources["minute_bars"]),
            "analysis": file_sha256(self.sources["analysis_captures"]),
            "review": file_sha256(self.root / "review-decisions.json"),
            "entry": file_sha256(self.root / "entry-plans.json"),
        }

        payload = build_shadow_compare_read_model(
            db_path=self.db_path,
            data_dir=self.root,
            analysis_captures_path=self.sources["analysis_captures"],
            review_decisions_path=self.root / "review-decisions.json",
            entry_plans_path=self.root / "entry-plans.json",
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            reports=["candidate-story", "evidence", "watchlist"],
            validate_sqlite=False,
        )

        self.assertEqual("PASS", payload["overall_status"])
        self.assertEqual(0, payload["mismatches"])
        self.assertFalse(payload["stale_sqlite_data"])
        self.assertEqual(source_hashes["alerts"], file_sha256(self.sources["alerts"]))
        self.assertEqual(source_hashes["minute_bars"], file_sha256(self.sources["minute_bars"]))
        self.assertEqual(source_hashes["analysis"], file_sha256(self.sources["analysis_captures"]))
        self.assertEqual(source_hashes["review"], file_sha256(self.root / "review-decisions.json"))
        self.assertEqual(source_hashes["entry"], file_sha256(self.root / "entry-plans.json"))

    def test_shadow_compare_detects_mismatch_as_stale_sqlite_data(self) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute("DELETE FROM watchlist_items")
            connection.commit()

        payload = build_shadow_compare_read_model(
            db_path=self.db_path,
            data_dir=self.root,
            analysis_captures_path=self.sources["analysis_captures"],
            review_decisions_path=self.root / "review-decisions.json",
            entry_plans_path=self.root / "entry-plans.json",
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            reports=["watchlist"],
            validate_sqlite=False,
        )

        self.assertEqual("WARN", payload["overall_status"])
        self.assertEqual(1, payload["mismatches"])
        self.assertTrue(payload["stale_sqlite_data"])
        self.assertIn("file fallback", payload["fallback_reason"].lower())

    def test_shadow_compare_cli_generates_reports(self) -> None:
        exit_code = sqlite_reports_main(
            [
                "--db",
                str(self.db_path),
                "--output-dir",
                str(self.reports_dir),
                "--shadow-compare",
            ]
        )

        self.assertEqual(0, exit_code)
        self.assertTrue((self.reports_dir / "sqlite-shadow-compare-latest.json").exists())
        self.assertTrue((self.reports_dir / "sqlite-shadow-compare-latest.md").exists())


if __name__ == "__main__":
    unittest.main()
