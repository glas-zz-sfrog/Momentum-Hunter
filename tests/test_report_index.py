from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.report_index import build_report_index, write_report_index


class ReportIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-report-index-{uuid.uuid4().hex}"
        self.reports = self.root / "reports"
        self.reports.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_latest_report_discovery_and_status_extraction(self) -> None:
        write_json(self.reports / "sqlite-validation-latest.json", {"overall_status": "PASS"})
        write_json(self.reports / "system-readiness-latest.json", {"report": {"overall_status": "WARNING"}})
        older_market = self.reports / "market-tape-health-20260618T100000.json"
        newer_market = self.reports / "market-tape-health-20260619T100000.json"
        write_json(older_market, {"overall_status": "PASS"})
        write_json(newer_market, {"overall_status": "WARN"})
        old_ts = datetime.fromisoformat("2026-06-18T10:00:00-05:00").timestamp()
        new_ts = datetime.fromisoformat("2026-06-19T10:00:00-05:00").timestamp()
        os.utime(older_market, (old_ts, old_ts))
        os.utime(newer_market, (new_ts, new_ts))

        payload = build_report_index(
            reports_dir=self.reports,
            generated_at=datetime.fromisoformat("2026-06-19T12:00:00-05:00"),
            stale_after_hours=24 * 365,
        )

        entries = {entry["name"]: entry for entry in payload["entries"]}
        self.assertEqual("PASS", entries["SQLite Validation"]["status"])
        self.assertEqual("WARNING", entries["System Readiness"]["status"])
        self.assertTrue(entries["Market Tape Health"]["latest_path"].endswith("market-tape-health-20260619T100000.json"))
        self.assertEqual("WARN", entries["Market Tape Health"]["status"])

    def test_missing_and_stale_reports_are_flagged(self) -> None:
        stale_path = self.reports / "sqlite-validation-latest.json"
        write_json(stale_path, {"overall_status": "PASS"})
        old_timestamp = datetime.fromisoformat("2026-06-18T08:00:00-05:00").timestamp()
        stale_path.touch()
        os.utime(stale_path, (old_timestamp, old_timestamp))

        payload = build_report_index(
            reports_dir=self.reports,
            generated_at=datetime.fromisoformat("2026-06-20T08:00:00-05:00"),
            stale_after_hours=24,
        )

        entries = {entry["name"]: entry for entry in payload["entries"]}
        self.assertEqual("STALE", entries["SQLite Validation"]["freshness"])
        self.assertGreater(payload["missing_report_count"], 0)
        self.assertIn("STALE_REPORTS:1", payload["warnings"])

    def test_report_index_writes_json_and_markdown(self) -> None:
        write_json(self.reports / "sqlite-validation-latest.json", {"overall_status": "PASS"})
        payload = build_report_index(
            reports_dir=self.reports,
            generated_at=datetime.fromisoformat("2026-06-19T12:00:00-05:00"),
        )

        json_path, markdown_path = write_report_index(payload, output_dir=self.reports)

        self.assertTrue(json_path.exists())
        self.assertTrue(markdown_path.exists())
        self.assertIn("Momentum Hunter Report Index", markdown_path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
