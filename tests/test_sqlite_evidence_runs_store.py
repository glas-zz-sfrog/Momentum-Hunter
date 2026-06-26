from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_store import (
    connect_database,
    evidence_metric_count,
    evidence_run_count,
    import_evidence_runs,
    read_evidence_metrics,
    read_evidence_runs,
)
from momentum_hunter.storage import file_sha256


class SQLiteEvidenceRunsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-evidence-runs-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.status_path = self.root / "evidence-autopilot-status.json"
        self.health_path = self.root / "evidence-health-report-test.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_evidence_run_and_metric_insert_read_round_trip_does_not_mutate_source(self) -> None:
        write_autopilot_status(self.status_path)
        before_hash = file_sha256(self.status_path)

        result = import_evidence_runs(db_path=self.db_path, source_paths=[self.status_path])

        with connect_database(self.db_path) as connection:
            runs = read_evidence_runs(connection)
            metrics = read_evidence_metrics(connection, run_id=runs[0]["run_id"])

        self.assertEqual(1, result.runs_seen)
        self.assertEqual(1, result.runs_inserted)
        self.assertEqual(0, result.runs_updated)
        self.assertEqual(0, result.runs_skipped)
        self.assertGreater(result.metrics_inserted, 0)
        self.assertEqual("evidence_autopilot_status", runs[0]["run_type"])
        self.assertEqual("COMPLETED", runs[0]["status"])
        self.assertEqual("2026-06-22T10:58:02-05:00", runs[0]["started_at"])
        self.assertEqual("2026-06-22T10:58:04-05:00", runs[0]["ended_at"])
        self.assertEqual(2, runs[0]["alert_count"])
        self.assertEqual(1, runs[0]["completed_count"])
        metric_names = {metric["metric_name"] for metric in metrics}
        self.assertIn("new_alert_count", metric_names)
        self.assertIn("monitor_cycle_completed", metric_names)
        self.assertEqual(before_hash, file_sha256(self.status_path))

    def test_evidence_runs_import_is_idempotent(self) -> None:
        write_autopilot_status(self.status_path)

        first = import_evidence_runs(db_path=self.db_path, source_paths=[self.status_path])
        second = import_evidence_runs(db_path=self.db_path, source_paths=[self.status_path])

        with connect_database(self.db_path) as connection:
            self.assertEqual(1, evidence_run_count(connection))
            self.assertEqual(first.metrics_inserted, evidence_metric_count(connection))

        self.assertEqual(1, first.runs_inserted)
        self.assertEqual(0, second.runs_inserted)
        self.assertEqual(0, second.runs_updated)
        self.assertEqual(1, second.runs_skipped)
        self.assertEqual(0, second.metrics_inserted)
        self.assertEqual(0, second.metrics_updated)
        self.assertEqual(first.metrics_inserted, second.metrics_skipped)

    def test_evidence_run_updates_when_same_source_run_changes(self) -> None:
        write_autopilot_status(self.status_path, pending=1, warning_count=1)
        import_evidence_runs(db_path=self.db_path, source_paths=[self.status_path])
        write_autopilot_status(self.status_path, pending=0, warning_count=0)

        result = import_evidence_runs(db_path=self.db_path, source_paths=[self.status_path])

        with connect_database(self.db_path) as connection:
            runs = read_evidence_runs(connection)

        self.assertEqual(0, result.runs_inserted)
        self.assertEqual(1, result.runs_updated)
        self.assertEqual(1, len(runs))
        self.assertEqual(0, runs[0]["pending_count"])
        self.assertEqual(0, runs[0]["warning_count"])

    def test_evidence_run_import_removes_stale_rows_for_mutable_latest_source(self) -> None:
        write_autopilot_status(self.status_path)
        first = import_evidence_runs(db_path=self.db_path, source_paths=[self.status_path])
        write_autopilot_status(
            self.status_path,
            timestamp="2026-06-22T11:08:02-05:00",
            end_timestamp="2026-06-22T11:08:04-05:00",
        )

        second = import_evidence_runs(db_path=self.db_path, source_paths=[self.status_path])

        with connect_database(self.db_path) as connection:
            runs = read_evidence_runs(connection)
            metrics = read_evidence_metrics(connection)

        self.assertEqual(1, first.runs_inserted)
        self.assertEqual(1, second.runs_inserted)
        self.assertEqual(1, second.runs_removed_stale)
        self.assertGreater(second.metrics_removed_stale, 0)
        self.assertEqual(1, len(runs))
        self.assertEqual("2026-06-22T11:08:02-05:00", runs[0]["started_at"])
        self.assertTrue(metrics)
        self.assertEqual({runs[0]["run_id"]}, {metric["run_id"] for metric in metrics})

    def test_evidence_health_report_import_handles_nested_gate_and_lists(self) -> None:
        write_evidence_health_report(self.health_path)

        result = import_evidence_runs(db_path=self.db_path, source_paths=[self.health_path])

        with connect_database(self.db_path) as connection:
            runs = read_evidence_runs(connection)
            metrics = read_evidence_metrics(connection, run_id=runs[0]["run_id"])

        self.assertEqual(1, result.runs_inserted)
        self.assertEqual("evidence_health", runs[0]["run_type"])
        self.assertEqual("COLLECTING", runs[0]["status"])
        self.assertEqual(2, runs[0]["alert_count"])
        self.assertEqual(1, runs[0]["completed_count"])
        self.assertEqual(1, runs[0]["unscorable_count"])
        by_name = {metric["metric_name"]: metric for metric in metrics}
        self.assertEqual(1.0, by_name["evidence_gate.completed_alerts"]["metric_value"])
        self.assertEqual("LOCKED", by_name["evidence_gate.strategy_optimization_status"]["metric_text"])
        self.assertEqual(1.0, by_name["unscorable_alert_issues"]["metric_value"])

    def test_missing_or_invalid_sources_warn_without_crashing(self) -> None:
        missing = self.root / "missing.json"
        invalid = self.root / "invalid.json"
        invalid.write_text("{not json", encoding="utf-8")

        result = import_evidence_runs(db_path=self.db_path, source_paths=[missing, invalid])

        with connect_database(self.db_path) as connection:
            self.assertEqual(0, evidence_run_count(connection))
            self.assertEqual(0, evidence_metric_count(connection))
        self.assertEqual(0, result.runs_seen)
        self.assertEqual(2, len(result.warnings))


def write_autopilot_status(
    path: Path,
    *,
    pending: int = 0,
    warning_count: int = 1,
    timestamp: str = "2026-06-22T10:58:02-05:00",
    end_timestamp: str = "2026-06-22T10:58:04-05:00",
) -> None:
    payload = {
        "schema_version": 1,
        "engine_version": "evidence_autopilot_v1",
        "status": {
            "state": "COMPLETED",
            "started_at": timestamp,
            "updated_at": end_timestamp,
            "completed_at": end_timestamp,
            "monitor_cycle_completed": True,
            "outcome_update_completed": True,
            "evidence_report_generated": True,
            "daily_brief_generated": True,
            "monitor_cycle_path": "reports/active-monitor-cycle-test.json",
            "outcome_status_path": "alert-outcome-update-status.json",
            "evidence_report_path": "reports/evidence-health-test.md",
            "daily_brief_path": "reports/daily-evidence-brief-test.md",
            "new_alert_count": 0,
            "active_alert_count": 0,
            "tracked_alert_count": 2,
            "updated_outcome_count": 0,
            "completed_outcome_count": 1,
            "pending_alert_count": pending,
            "unscorable_alert_count": 1,
            "warning_count": warning_count,
            "warnings": ["TEST_WARNING"] if warning_count else [],
            "last_error": "",
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_evidence_health_report(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "engine_version": "evidence_health_v1",
        "report": {
            "generated_at": "2026-06-22T10:58:02-05:00",
            "source_alerts_path": "opportunity-alerts.json",
            "source_minute_bars_path": "opportunity-minute-bars.json",
            "source_outcome_status_path": "alert-outcome-update-status.json",
            "total_alerts": 2,
            "completed_alerts": 1,
            "pending_alerts": 0,
            "unscorable_alerts": 1,
            "completion_rate_pct": 100.0,
            "alerts_generated": 2,
            "alerts_captured": 2,
            "alerts_classified": 1,
            "completed_outcomes": 1,
            "stale_pending_alerts": [],
            "unscorable_alert_issues": [{"alert_id": "a1", "issue": "UNSCORABLE_MISSING_ENTRY_PRICE"}],
            "evidence_gate": {
                "completed_alerts": 1,
                "required_alerts": 25,
                "evidence_status": "COLLECTING",
                "allowed_action": "Collect evidence only",
                "strategy_optimization_status": "LOCKED",
                "reason": "Insufficient sample.",
            },
            "warnings": ["EVIDENCE_THRESHOLD_LOCKED"],
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
