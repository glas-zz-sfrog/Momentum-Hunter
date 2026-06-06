from __future__ import annotations

import csv
import json
import shutil
import unittest
from datetime import datetime
from pathlib import Path

from momentum_hunter.capture_health import build_capture_health_snapshot
from momentum_hunter.time_utils import CENTRAL_TZ


class CaptureHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_capture_health"
        self.captures_dir = self.root / "captures"
        self.failures_dir = self.root / "failures"
        self.analysis_csv = self.root / "analysis-captures.csv"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_builds_scheduled_capture_health_snapshot(self) -> None:
        self.write_capture("2026-06-05", "morning", "2026-06-05T07:00:12-05:00", 3)
        self.write_capture("2026-06-04", "evening", "2026-06-04T19:00:12-05:00", 2)
        self.write_failure("2026-06-05T07:01:00-05:00")
        self.write_csv(self.analysis_csv, 4)
        self.write_csv(self.outcomes_csv, 2)

        snapshot = build_capture_health_snapshot(
            now=datetime(2026, 6, 5, 8, 30, tzinfo=CENTRAL_TZ),
            captures_dir=self.captures_dir,
            failures_dir=self.failures_dir,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual("2026-06-05T07:00:12-05:00", snapshot.last_morning_capture.capture_time.isoformat())
        self.assertEqual(3, snapshot.last_morning_capture.candidate_count)
        self.assertEqual("finviz", snapshot.last_morning_capture.provider)
        self.assertEqual("2026-06-04T19:00:12-05:00", snapshot.last_evening_capture.capture_time.isoformat())
        self.assertEqual("Provider unavailable / DNS failure", snapshot.last_failed_capture.error_message)
        self.assertEqual("2026-06-06T07:00:00-05:00", snapshot.next_morning_run.isoformat())
        self.assertEqual("2026-06-05T19:00:00-05:00", snapshot.next_evening_run.isoformat())
        self.assertTrue(snapshot.csv_append_status.exists)
        self.assertEqual(4, snapshot.csv_append_status.row_count)
        self.assertTrue(snapshot.outcome_update_status.exists)
        self.assertEqual(2, snapshot.outcome_update_status.row_count)

    def write_capture(self, date_text: str, session: str, capture_time: str, candidate_count: int) -> None:
        path = self.captures_dir / date_text
        path.mkdir(parents=True, exist_ok=True)
        payload = {
            "capture_time": capture_time,
            "provider": "finviz",
            "scanner": {"name": "Base Momentum"},
            "candidates": [{"ticker": f"T{index}"} for index in range(candidate_count)],
        }
        (path / f"{session}.json").write_text(json.dumps(payload), encoding="utf-8")

    def write_failure(self, failure_time: str) -> None:
        self.failures_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "failure_time": failure_time,
            "session": "morning",
            "provider": "finviz",
            "scanner": "Base Momentum",
            "error_message": "Provider unavailable / DNS failure",
        }
        (self.failures_dir / "2026-06-05-070100-morning.json").write_text(json.dumps(payload), encoding="utf-8")

    def write_csv(self, path: Path, rows: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=["ticker"])
            writer.writeheader()
            for index in range(rows):
                writer.writerow({"ticker": f"T{index}"})


if __name__ == "__main__":
    unittest.main()
