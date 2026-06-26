from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_reports import (
    build_candidate_story_read_model,
    build_evidence_read_model,
    build_sqlite_read_model_comparison,
    build_system_readiness_read_model,
    build_watchlist_read_model,
    main as sqlite_reports_main,
    write_report,
)
from momentum_hunter.sqlite_store import connect_database, import_user_state
from momentum_hunter.storage import file_sha256
from tests.test_sqlite_user_state_store import write_user_state_fixture
from tests.test_sqlite_validation import import_all_sources, write_validation_sources


class SQLiteReadModelReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-reports-{uuid.uuid4().hex}"
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

    def test_candidate_story_read_model_uses_sqlite_history_and_user_state(self) -> None:
        payload = build_candidate_story_read_model(db_path=self.db_path)

        story = payload["stories"][0]
        self.assertEqual("sqlite_candidate_story_read_model_v1", payload["engine_version"])
        self.assertEqual(1, payload["candidate_count"])
        self.assertEqual("AAA", story["ticker"])
        self.assertEqual("watchlist", story["candidate_status"])
        self.assertEqual("complete", story["entry_plan_status"])
        self.assertEqual(1, story["trusted_capture_count"])

    def test_evidence_read_model_summarizes_alerts_outcomes_and_bars(self) -> None:
        payload = build_evidence_read_model(db_path=self.db_path)

        self.assertEqual(3, payload["alert_count"])
        self.assertEqual(1, payload["completed_outcomes"])
        self.assertEqual(1, payload["pending_outcomes"])
        self.assertEqual(1, payload["unscorable_outcomes"])
        self.assertEqual(1, payload["available_minute_bars"])
        self.assertIn("AAA", payload["symbols_with_evidence"])
        self.assertIn("COLLECTING", payload["evidence_sample_size_status"])

    def test_watchlist_read_model_summarizes_plans_and_gaps(self) -> None:
        payload = build_watchlist_read_model(db_path=self.db_path)

        self.assertEqual(0, payload["interested_count"])
        self.assertEqual(1, payload["rejected_count"])
        self.assertEqual(1, payload["review_watchlist_count"])
        self.assertEqual(1, payload["watchlist_count"])
        self.assertEqual(1, payload["complete_plans"])
        self.assertEqual(1, payload["incomplete_plans"])
        self.assertIn("BBB", payload["candidates_with_plans_but_no_watchlist"])

    def test_system_readiness_read_model_accepts_validation_payload(self) -> None:
        payload = build_system_readiness_read_model(
            db_path=self.db_path,
            validation_payload={"overall_status": "PASS", "missing_slices": [], "warnings": []},
        )

        self.assertEqual("PASS", payload["validation_status"])
        self.assertEqual([], payload["missing_slices"])
        self.assertEqual("No action required. SQLite read models are consistent with current validation inputs.", payload["recommended_next_action"])

    def test_cli_generates_json_and_markdown_reports(self) -> None:
        exit_code = sqlite_reports_main(
            [
                "--db",
                str(self.db_path),
                "--output-dir",
                str(self.reports_dir),
                "--report",
                "candidate-story",
                "--report",
                "evidence",
                "--report",
                "watchlist",
            ]
        )

        self.assertEqual(0, exit_code)
        self.assertTrue((self.reports_dir / "sqlite-candidate-story-read-model-latest.json").exists())
        self.assertTrue((self.reports_dir / "sqlite-candidate-story-read-model-latest.md").exists())
        self.assertTrue((self.reports_dir / "sqlite-evidence-read-model-latest.json").exists())
        self.assertTrue((self.reports_dir / "sqlite-watchlist-read-model-latest.md").exists())

    def test_comparison_report_detects_matching_counts_and_does_not_mutate_sources(self) -> None:
        source_hashes = {
            name: file_sha256(path)
            for name, path in {
                "alerts": self.sources["alerts"],
                "minute_bars": self.sources["minute_bars"],
                "analysis_captures": self.sources["analysis_captures"],
                "review": self.root / "review-decisions.json",
                "entry": self.root / "entry-plans.json",
            }.items()
        }

        payload = build_sqlite_read_model_comparison(
            db_path=self.db_path,
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            analysis_captures_path=self.sources["analysis_captures"],
            review_decisions_path=self.root / "review-decisions.json",
            entry_plans_path=self.root / "entry-plans.json",
            data_dir=self.root,
        )
        paths = write_report("comparison", payload, output_dir=self.reports_dir)

        self.assertEqual("PASS", payload["overall_status"])
        self.assertEqual(0, payload["mismatches"])
        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())
        self.assertEqual(source_hashes["alerts"], file_sha256(self.sources["alerts"]))
        self.assertEqual(source_hashes["minute_bars"], file_sha256(self.sources["minute_bars"]))
        self.assertEqual(source_hashes["analysis_captures"], file_sha256(self.sources["analysis_captures"]))
        self.assertEqual(source_hashes["review"], file_sha256(self.root / "review-decisions.json"))
        self.assertEqual(source_hashes["entry"], file_sha256(self.root / "entry-plans.json"))

    def test_comparison_report_reports_mismatches_clearly(self) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute("DELETE FROM watchlist_items")
            connection.commit()

        payload = build_sqlite_read_model_comparison(
            db_path=self.db_path,
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            analysis_captures_path=self.sources["analysis_captures"],
            review_decisions_path=self.root / "review-decisions.json",
            entry_plans_path=self.root / "entry-plans.json",
            data_dir=self.root,
        )
        mismatches = [item for item in payload["comparisons"] if item["status"] == "MISMATCH"]

        self.assertEqual("WARN", payload["overall_status"])
        self.assertTrue(any(item["name"] == "watchlist_items" for item in mismatches))

    def test_missing_database_is_reported_without_crash(self) -> None:
        payload = build_candidate_story_read_model(db_path=self.root / "missing.sqlite3")

        self.assertEqual("WARN", payload["overall_status"])
        self.assertIn("SQLITE_DATABASE_MISSING", payload["warnings"][0])


if __name__ == "__main__":
    unittest.main()

