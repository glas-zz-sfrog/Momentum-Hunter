from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_runtime_adoption import (
    build_sqlite_runtime_adoption_dry_run,
    write_sqlite_runtime_adoption_report,
)
from momentum_hunter.sqlite_store import connect_database, import_user_state
from momentum_hunter.storage import file_sha256
from tests.test_sqlite_user_state_store import write_user_state_fixture
from tests.test_sqlite_validation import import_all_sources, write_validation_sources


class SQLiteRuntimeAdoptionDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-runtime-adoption-{uuid.uuid4().hex}"
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

    def test_dry_run_keeps_file_default_and_classifies_surfaces(self) -> None:
        payload = self.build_payload()

        self.assertEqual("file", payload["runtime_default_source"])
        self.assertFalse(payload["sqlite_authoritative"])
        self.assertEqual("PASS", payload["validation_status"])
        self.assertEqual("PASS", payload["shadow_compare_status"])
        self.assertEqual("READY_FOR_CLI_REPORTS", payload["optional_read_mode_status"])
        self.assertIn("Evidence reports", payload["safe_optional_surfaces"])
        self.assertIn("Dashboard summary cards", payload["shadow_only_surfaces"])
        self.assertIn("Research Lab", payload["deferred_surfaces"])
        self.assertIn("User-state write paths", payload["blocked_write_surfaces"])

    def test_missing_database_warns_and_uses_file_fallback(self) -> None:
        payload = build_sqlite_runtime_adoption_dry_run(db_path=self.root / "missing.sqlite3", validate_shadow_sqlite=False)

        self.assertEqual("USE_FILE_FALLBACK", payload["optional_read_mode_status"])
        self.assertIn("SQLITE_DATABASE_MISSING", " ".join(payload["warnings"]))
        self.assertIn("file mode", payload["fallback_behavior"])

    def test_stale_sqlite_shadow_compare_blocks_optional_runtime_adoption(self) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute("DELETE FROM opportunity_alerts")
            connection.commit()

        payload = self.build_payload()

        self.assertEqual("USE_FILE_FALLBACK", payload["optional_read_mode_status"])
        self.assertIn("SQLITE_SHADOW_COMPARE_NOT_PASS:WARN", payload["warnings"])
        self.assertIn("SQLITE_STALE_OR_MISMATCHED", payload["warnings"])

    def test_report_writer_creates_json_and_markdown(self) -> None:
        payload = self.build_payload()
        paths = write_sqlite_runtime_adoption_report(
            payload,
            json_path=self.reports_dir / "sqlite-runtime-adoption-dry-run-v1.json",
            markdown_path=self.reports_dir / "sqlite-runtime-adoption-dry-run-v1.md",
        )

        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())
        loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
        self.assertEqual("sqlite_runtime_adoption_dry_run_v1", loaded["engine_version"])
        self.assertIn("SQLite Runtime Adoption Dry-Run v1", paths["markdown"].read_text(encoding="utf-8"))

    def test_dry_run_does_not_mutate_file_sources(self) -> None:
        source_paths = [
            self.sources["data_quality"],
            self.sources["alerts"],
            self.sources["minute_bars"],
            self.sources["analysis_captures"],
            self.root / "review-decisions.json",
            self.root / "entry-plans.json",
        ]
        before = {path: file_sha256(path) for path in source_paths}

        self.build_payload()

        after = {path: file_sha256(path) for path in source_paths}
        self.assertEqual(before, after)

    def build_payload(self) -> dict[str, object]:
        return build_sqlite_runtime_adoption_dry_run(
            db_path=self.db_path,
            data_dir=self.root,
            data_quality_report=self.sources["data_quality"],
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            analysis_captures_path=self.sources["analysis_captures"],
            review_decisions_path=self.root / "review-decisions.json",
            entry_plans_path=self.root / "entry-plans.json",
            evidence_run_source_paths=[self.sources["evidence_run"]],
            system_status_source_paths=[self.sources["system_status"]],
            reports=["candidate-story", "evidence", "watchlist"],
            validate_shadow_sqlite=False,
        )


if __name__ == "__main__":
    unittest.main()
