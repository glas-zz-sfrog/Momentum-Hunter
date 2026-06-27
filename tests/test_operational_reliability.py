from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.operational_reliability import (
    build_operational_reliability_report,
    classify_warning,
    write_operational_reliability_report,
)


class OperationalReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-operational-reliability-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.reports = self.root / "reports"
        self.reports.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_warning_classifier_uses_required_categories(self) -> None:
        self.assertEqual("STALE", classify_warning("STALE_ACTIVE_MONITOR_CYCLE")[0])
        self.assertEqual("FAILED", classify_warning("CAPTURE_FAILED")[0])
        self.assertEqual("MARKET_HOURS_REQUIRED", classify_warning("QUOTE_HTTP_401 no market tape")[0])
        self.assertEqual("LEGACY_DATA_GAP", classify_warning("LEGACY_CAPTURE_GAP")[0])
        self.assertEqual("EXPECTED", classify_warning("LOW_COMPLETED_ALERT_SAMPLE")[0])
        self.assertEqual("ACTIONABLE", classify_warning("UNSCORABLE_ALERTS:1")[0])

    def test_report_classifies_existing_artifact_warnings(self) -> None:
        self.write_json(
            self.reports / "report-index-latest.json",
            {
                "warnings": ["MISSING_REPORTS:1"],
                "entries": [
                    {"name": "Daily Evidence Brief", "latest_path": "daily.md", "warnings": ["REPORT_STALE"]},
                ],
            },
        )
        self.write_json(
            self.reports / "system-readiness-latest.json",
            {
                "report": {
                    "warnings": ["WARNING: STALE_ACTIVE_MONITOR_CYCLE"],
                    "issues_requiring_attention": ["Captures: A capture failure record exists."],
                }
            },
        )
        self.write_json(
            self.reports / "provider-field-quality-latest.json",
            {"warnings": ["PROVIDER_FIELD_WARNINGS_PRESENT"], "top_warnings": [{"warning": "MISSING_RELATIVE_VOLUME", "count": 4}]},
        )
        self.write_json(self.reports / "evidence-census-latest.json", {"overall_status": "WARN", "warnings": ["LOW_COMPLETED_ALERT_SAMPLE"]})
        self.write_json(self.root / "active-monitor-status.json", {"state": "READY", "warnings": ["STALE_ACTIVE_MONITOR_CYCLE"]})
        self.write_json(
            self.root / "opportunity-alerts.json",
            {"alerts": [{"outcome": {"classification": "UNSCORABLE_MISSING_ENTRY_PRICE"}}]},
        )

        with patch("momentum_hunter.operational_reliability.build_capture_health_snapshot") as snapshot:
            snapshot.return_value.last_failed_capture.path = None
            payload = build_operational_reliability_report(
                reports_dir=self.reports,
                data_dir=self.root,
                generated_at="2026-06-27T01:30:00-05:00",
            )

        self.assertEqual("WARN", payload["overall_status"])
        self.assertGreater(payload["category_counts"]["ACTIONABLE"], 0)
        self.assertGreater(payload["category_counts"]["STALE"], 0)
        self.assertGreater(payload["category_counts"]["EXPECTED"], 0)
        self.assertTrue(any(item["category"] == "ACTIONABLE" and "UNSCORABLE" in item["warning"] for item in payload["warnings"]))

    def test_report_writes_json_and_markdown(self) -> None:
        payload = {
            "generated_at": "2026-06-27T01:30:00-05:00",
            "overall_status": "PASS",
            "total_warnings": 0,
            "actionable_warning_count": 0,
            "category_counts": {"EXPECTED": 0},
            "warnings": [],
            "next_actions": ["No action required."],
            "safety_note": "Reporting only.",
        }

        paths = write_operational_reliability_report(
            payload,
            json_path=self.root / "operational-reliability-sprint-v1-final-report.json",
            markdown_path=self.root / "operational-reliability-sprint-v1-final-report.md",
        )

        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())
        self.assertIn("Operational Reliability Sprint v1", paths["markdown"].read_text(encoding="utf-8"))

    def write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
