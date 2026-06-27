from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.evidence_console_view_model import (
    active_monitor_summary_text,
    evidence_next_action_text,
    load_active_alert_rows,
    load_alert_outcome_rows,
    load_user_monitor_symbol_rows,
)


class EvidenceConsoleViewModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-evidence-console-view-model-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_evidence_next_action_prioritizes_execution_ready(self) -> None:
        text = evidence_next_action_text(
            execution_ready_count=2,
            active_alert_count=5,
            outcome_count=0,
            performance_count=0,
            monitor_summary="ACTIVE MONITOR: 5 active alert(s)",
            evidence_summary="EVIDENCE HEALTH: COLLECTING",
        )

        self.assertIn("2 execution-ready", text)

    def test_load_active_alert_rows_filters_terminal_outcomes(self) -> None:
        path = self.root / "opportunity-alerts.json"
        write_json(
            path,
            {
                "alerts": [
                    {"alert_id": "old", "timestamp": "2026-06-25T09:00:00-05:00", "outcome": {"status": "COMPLETED"}},
                    {"alert_id": "new", "timestamp": "2026-06-25T09:05:00-05:00", "outcome": {"status": "ACTIVE"}},
                    {"alert_id": "pending", "timestamp": "2026-06-25T09:03:00-05:00", "outcome": {"status": "PENDING_OUTCOME"}},
                ]
            },
        )

        rows = load_active_alert_rows(path)

        self.assertEqual(["new", "pending"], [row["alert_id"] for row in rows])
        self.assertEqual(["new", "pending"], [row["alert_id"] for row in load_alert_outcome_rows(path, limit=2)])

    def test_active_monitor_summary_reports_missing_tape(self) -> None:
        path = self.root / "active-monitor-cycle-test.json"
        write_json(
            path,
            {
                "monitor_cycle": {
                    "target_count": 6,
                    "active_alert_count": 0,
                    "new_alert_count": 0,
                    "coverage_row_count": 5,
                    "warnings": ["COVERAGE_ROWS_WITHOUT_MARKET_DATA"],
                }
            },
        )

        self.assertEqual("ACTIVE MONITOR: 6 target(s), 5 coverage row(s) need market tape", active_monitor_summary_text(path))

    def test_load_user_monitor_symbol_rows_handles_malformed_file(self) -> None:
        path = self.root / "monitor-symbols.json"
        path.write_text("{bad json", encoding="utf-8")

        self.assertEqual([], load_user_monitor_symbol_rows(path))


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
