from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.active_monitor import MonitorCycleReport
from momentum_hunter.alert_outcome_updater import AlertOutcomeUpdateReport
from momentum_hunter.app import evidence_autopilot_summary_text, load_evidence_autopilot_dashboard_rows
from momentum_hunter.evidence_autopilot import load_evidence_autopilot_status, run_evidence_autopilot
from momentum_hunter.evidence_health import AlertIssue, EvidenceGate, EvidenceHealthReport


class EvidenceAutopilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-evidence-autopilot-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.output_dir = self.root / "reports"
        self.status_path = self.root / "evidence-autopilot-status.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_autopilot_runs_monitor_outcomes_evidence_and_brief(self) -> None:
        calls: list[str] = []

        def monitor_runner(**kwargs) -> MonitorCycleReport:
            calls.append("monitor")
            self.assertTrue(kwargs["fetch_missing_market_data"])
            self.assertTrue(kwargs["refresh_target_market_data"])
            return fake_monitor_report()

        def outcome_updater(**kwargs) -> AlertOutcomeUpdateReport:
            calls.append("outcome")
            self.assertTrue(kwargs["fetch_missing_bars"])
            self.assertIsNotNone(kwargs["status_path"])
            return fake_outcome_report()

        def evidence_builder(**kwargs) -> EvidenceHealthReport:
            calls.append("evidence")
            return fake_evidence_report()

        status = run_evidence_autopilot(
            output_dir=self.output_dir,
            status_path=self.status_path,
            monitor_cycle_runner=monitor_runner,
            outcome_updater=outcome_updater,
            evidence_builder=evidence_builder,
        )
        loaded = load_evidence_autopilot_status(self.status_path)

        self.assertEqual(["monitor", "outcome", "evidence"], calls)
        self.assertEqual("COMPLETED", status.state)
        self.assertIsNotNone(loaded)
        self.assertEqual("COMPLETED", loaded.state)
        self.assertTrue(status.monitor_cycle_completed)
        self.assertTrue(status.outcome_update_completed)
        self.assertTrue(status.evidence_report_generated)
        self.assertTrue(status.daily_brief_generated)
        self.assertEqual(2, status.new_alert_count)
        self.assertEqual(1, status.completed_outcome_count)
        self.assertEqual(1, status.pending_alert_count)
        self.assertEqual(1, status.stale_pending_alert_count)
        self.assertTrue(Path(status.daily_brief_path).exists())
        self.assertIn("Daily Evidence Brief", Path(status.daily_brief_path).read_text(encoding="utf-8"))
        self.assertTrue(Path(status.evidence_report_path).exists())

    def test_autopilot_records_failure_status(self) -> None:
        def failing_monitor(**kwargs) -> MonitorCycleReport:
            raise RuntimeError("monitor failed")

        with self.assertRaises(RuntimeError):
            run_evidence_autopilot(
                output_dir=self.output_dir,
                status_path=self.status_path,
                monitor_cycle_runner=failing_monitor,
                outcome_updater=lambda **kwargs: fake_outcome_report(),
                evidence_builder=lambda **kwargs: fake_evidence_report(),
            )
        loaded = load_evidence_autopilot_status(self.status_path)

        self.assertIsNotNone(loaded)
        self.assertEqual("FAILED", loaded.state)
        self.assertIn("monitor failed", loaded.last_error)

    def test_dashboard_helpers_show_autopilot_status(self) -> None:
        status = run_evidence_autopilot(
            output_dir=self.output_dir,
            status_path=self.status_path,
            monitor_cycle_runner=lambda **kwargs: fake_monitor_report(),
            outcome_updater=lambda **kwargs: fake_outcome_report(),
            evidence_builder=lambda **kwargs: fake_evidence_report(),
        )

        text = evidence_autopilot_summary_text(self.status_path)
        rows = load_evidence_autopilot_dashboard_rows(self.status_path)
        by_metric = {row["metric"]: row for row in rows}

        self.assertIn("EVIDENCE AUTOPILOT: COMPLETED", text)
        self.assertIn("2 new alert(s)", text)
        self.assertEqual("COMPLETED", by_metric["State"]["value"])
        self.assertIn("M:yes", by_metric["Pipeline"]["value"])
        self.assertEqual(Path(status.daily_brief_path).name, by_metric["Daily Brief"]["value"])


def fake_monitor_report() -> MonitorCycleReport:
    return MonitorCycleReport(
        generated_at="2026-06-20T10:00:00-05:00",
        trade_report_path="trade-report.json",
        target_symbols=["AAA"],
        target_count=1,
        trade_report_symbol_count=1,
        matched_target_count=1,
        missing_target_symbols=[],
        new_alert_count=2,
        active_alert_count=2,
        tracked_alert_count=3,
        state_transition_count=1,
        coverage_row_count=0,
        covered_missing_symbols=[],
        uncovered_missing_symbols=[],
        coverage_report_path="",
        target_report_paths={},
        alert_report_paths={},
        warnings=["TEST_MONITOR_WARNING"],
    )


def fake_outcome_report() -> AlertOutcomeUpdateReport:
    return AlertOutcomeUpdateReport(
        generated_at="2026-06-20T10:05:00-05:00",
        alert_count=3,
        updated_alert_count=1,
        completed_alert_count=1,
        pending_alert_count=1,
        unscorable_alert_count=0,
        symbols_processed=["AAA"],
        bars_loaded_count=60,
        bars_saved_path="bars.json",
        alerts_path="alerts.json",
        warnings=["TEST_OUTCOME_WARNING"],
    )


def fake_evidence_report() -> EvidenceHealthReport:
    return EvidenceHealthReport(
        generated_at="2026-06-20T10:06:00-05:00",
        source_alerts_path="alerts.json",
        source_minute_bars_path="bars.json",
        source_outcome_status_path="status.json",
        total_alerts=3,
        completed_alerts=1,
        pending_alerts=1,
        unscorable_alerts=0,
        success_count=0,
        failure_count=0,
        noise_count=1,
        late_count=0,
        completion_rate_pct=33.33,
        alerts_generated=3,
        alerts_captured=3,
        alerts_classified=1,
        completed_outcomes=1,
        stale_pending_alerts=[
            AlertIssue(
                alert_id="a1",
                symbol="AAA",
                alert_type="BREAKOUT",
                timestamp="2026-06-20T09:00:00-05:00",
                issue="STALE_PENDING_ALERT",
                detail="test",
            )
        ],
        unscorable_alert_issues=[],
        unscorable_by_reason={},
        missing_minute_bar_alerts=[],
        missing_outcome_alerts=[],
        incomplete_outcome_alerts=[],
        missing_readiness_state_alerts=[],
        missing_news_snapshot_alerts=[],
        monitor_started=True,
        monitor_completed=True,
        alerts_written=True,
        outcome_jobs_executed=True,
        outcome_classifications_saved=True,
        evidence_gate=EvidenceGate(
            completed_alerts=1,
            required_alerts=25,
            evidence_status="COLLECTING",
            allowed_action="Collect evidence only",
            strategy_optimization_status="LOCKED",
            reason="1 completed alert(s); minimum 25 required.",
        ),
        warnings=["TEST_EVIDENCE_WARNING"],
    )


if __name__ == "__main__":
    unittest.main()
