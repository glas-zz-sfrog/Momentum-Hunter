from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_mirror_freshness import (
    build_sqlite_mirror_freshness_report,
    write_sqlite_mirror_freshness_report,
)
from momentum_hunter.sqlite_store import import_system_status_events
from tests.test_sqlite_validation import import_all_sources, write_validation_sources


class SQLiteMirrorFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-freshness-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.sources = write_validation_sources(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_mirror_freshness_passes_after_matching_import(self) -> None:
        before_hash = self.sources["alerts"].read_bytes()
        import_all_sources(self.db_path, self.sources)
        import_system_status_events(
            db_path=self.db_path,
            source_paths=[self.sources["system_status"], self.sources["data_quality"]],
        )

        payload = build_sqlite_mirror_freshness_report(
            db_path=self.db_path,
            data_dir=self.root,
            reports_dir=self.root,
            data_quality_report=self.sources["data_quality"],
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            analysis_captures_path=self.sources["analysis_captures"],
            review_decisions_path=self.root / "review-decisions.json",
            entry_plans_path=self.root / "entry-plans.json",
        )
        paths = write_sqlite_mirror_freshness_report(
            payload,
            json_path=self.root / "sqlite-mirror-freshness-latest.json",
            markdown_path=self.root / "sqlite-mirror-freshness-latest.md",
        )

        self.assertEqual("PASS", payload["overall_status"])
        checks = {check["name"]: check for check in payload["checks"]}
        self.assertEqual("PASS", checks["opportunity_alerts"]["status"])
        self.assertEqual(3, checks["opportunity_alerts"]["source_count"])
        self.assertEqual(3, checks["opportunity_alerts"]["sqlite_current_count"])
        self.assertEqual("PASS", checks["capture_candidates"]["status"])
        self.assertEqual(before_hash, self.sources["alerts"].read_bytes())
        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())

    def test_mirror_freshness_detects_stale_current_hash_rows(self) -> None:
        import_all_sources(self.db_path, self.sources)
        import_system_status_events(
            db_path=self.db_path,
            source_paths=[self.sources["system_status"], self.sources["data_quality"]],
        )
        payload = json.loads(self.sources["alerts"].read_text(encoding="utf-8"))
        payload["alerts"].append(
            {
                "alert_id": "alert-new",
                "symbol": "DDD",
                "timestamp": "2026-06-25T09:04:00-05:00",
                "alert_type": "TEST_NEW",
                "current_state": "PLANNING_SCAFFOLD",
                "price": 12.0,
                "outcome": {"status": "PENDING_OUTCOME", "classification": "PENDING"},
            }
        )
        self.sources["alerts"].write_text(json.dumps(payload, indent=2), encoding="utf-8")

        report = build_sqlite_mirror_freshness_report(
            db_path=self.db_path,
            data_dir=self.root,
            reports_dir=self.root,
            data_quality_report=self.sources["data_quality"],
            alerts_path=self.sources["alerts"],
            minute_bars_path=self.sources["minute_bars"],
            analysis_captures_path=self.sources["analysis_captures"],
            review_decisions_path=self.root / "review-decisions.json",
            entry_plans_path=self.root / "entry-plans.json",
        )

        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual("FAIL", report["overall_status"])
        self.assertEqual("FAIL", checks["opportunity_alerts"]["status"])
        self.assertEqual(4, checks["opportunity_alerts"]["source_count"])
        self.assertEqual(0, checks["opportunity_alerts"]["sqlite_current_count"])
        self.assertIn("MIRROR_COUNT_MISMATCH:4!=0", checks["opportunity_alerts"]["warnings"])


if __name__ == "__main__":
    unittest.main()
