from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.data_quality import build_data_quality_report, export_data_quality_report
from momentum_hunter.active_monitor import ActiveMonitorStatus, save_active_monitor_status
from momentum_hunter.evidence_autopilot import EvidenceAutopilotStatus, save_evidence_autopilot_status
from momentum_hunter.evidence_autopilot_reliability import build_evidence_autopilot_reliability_report
from momentum_hunter.evidence_health import EvidenceGate, EvidenceHealthReport
from momentum_hunter.market_tape_health import MarketTapeHealthAttempt, MarketTapeHealthReport
from momentum_hunter.storage import file_sha256
from momentum_hunter.system_readiness import (
    ReadinessSection,
    active_alert_reliability_section,
    active_monitor_section,
    changes_since_previous,
    evidence_autopilot_section,
    market_data_section,
    outcome_tracking_section,
    overall_status,
    provider_field_quality_section,
    recommended_next_action_for_issue,
    section_status_counts,
    sqlite_mirror_section,
    status_reason,
    user_state_safety_section,
    highest_priority_issue,
)


class ReliabilityReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-reliability-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_data_quality_report_detects_market_tape_and_scanner_gaps_without_mutating_captures(self) -> None:
        captures_dir = self.root / "captures"
        capture_dir = captures_dir / "2026-06-18"
        capture_dir.mkdir(parents=True)
        capture = capture_dir / "morning.json"
        capture.write_text(
            json.dumps(
                {
                    "capture_time": "2026-06-18T07:00:00-05:00",
                    "capture_session": "morning",
                    "scanner": {"name": "Basic Momentum"},
                    "candidates": [
                        {"ticker": "AAA", "price": 10.0, "volume": 1000000, "relative_volume": 0.0, "score": 80},
                        {"ticker": "AAA", "price": 10.0, "volume": 1000000, "relative_volume": 0.0, "score": 80},
                        {"ticker": "BBB", "price": 0.0, "volume": 0, "score": 70},
                    ],
                }
            ),
            encoding="utf-8",
        )
        before = file_sha256(capture)
        report = build_data_quality_report(
            ["AAA", "BBB"],
            market_tape_report=fake_market_tape_report(),
            captures_dir=captures_dir,
            minute_bars_path=self.root / "minute-bars.json",
            generated_at=datetime.fromisoformat("2026-06-18T08:00:00-05:00"),
        )
        paths = export_data_quality_report(
            report,
            json_path=self.root / "data-quality-latest.json",
            markdown_path=self.root / "data-quality-latest.md",
        )

        self.assertEqual(1, report.usable_market_tape_count)
        self.assertEqual(1, report.missing_market_tape_count)
        self.assertIn("SCANNER_RELATIVE_VOLUME_GAPS", report.warnings)
        self.assertIn("MARKET_TAPE_TIMESTAMP_UNAVAILABLE", report.warnings)
        self.assertEqual(2, report.timestamp_summary["unknown_timestamp_count"])
        self.assertIn("DUPLICATE_TICKERS_WITHIN_CAPTURE", report.warnings)
        self.assertEqual(1, len(report.duplicate_capture_anomalies))
        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["report"].exists())
        self.assertEqual(before, file_sha256(capture))

    def test_evidence_autopilot_reliability_separates_completed_pending_and_unscorable(self) -> None:
        status_path = self.root / "evidence-autopilot-status.json"
        save_evidence_autopilot_status(
            EvidenceAutopilotStatus(
                state="COMPLETED",
                started_at="2026-06-18T08:00:00-05:00",
                updated_at="2026-06-18T08:00:03-05:00",
                completed_at="2026-06-18T08:00:03-05:00",
                monitor_cycle_completed=True,
                outcome_update_completed=True,
                evidence_report_generated=True,
                daily_brief_generated=True,
                monitor_cycle_path="",
                new_alert_count=2,
                active_alert_count=1,
                tracked_alert_count=3,
                updated_outcome_count=1,
            ),
            status_path,
        )
        report = build_evidence_autopilot_reliability_report(
            status_path=status_path,
            active_monitor_status_path=self.root / "missing-active-status.json",
            outcome_status_path=self.root / "missing-outcome-status.json",
            reports_dir=self.root / "reports",
            evidence_health_report=fake_evidence_health_report(completed=1, pending=0, unscorable=1),
            generated_at=datetime.fromisoformat("2026-06-18T08:05:00-05:00"),
        )

        self.assertEqual("COMPLETED", report.latest_run_state)
        self.assertEqual(3.0, report.latest_run_duration_seconds)
        self.assertEqual(1, report.completed_alerts)
        self.assertEqual(0, report.pending_alerts)
        self.assertEqual(1, report.unscorable_alerts)
        self.assertFalse(report.latest_run_stale)
        self.assertAlmostEqual(4.95, report.latest_run_age_minutes or 0.0, places=2)
        self.assertEqual("NO_BACKGROUND_AUTOPILOT_CONFIRMED", report.background_status)
        self.assertIn("no continuous autopilot work is proven", report.app_closed_behavior)
        self.assertIn("NO_ALERT_OUTCOME_UPDATE_STATUS", report.warnings)

    def test_evidence_autopilot_reliability_warns_on_stale_latest_run(self) -> None:
        status_path = self.root / "evidence-autopilot-status.json"
        save_evidence_autopilot_status(
            EvidenceAutopilotStatus(
                state="COMPLETED",
                started_at="2026-06-18T08:00:00-05:00",
                updated_at="2026-06-18T08:00:03-05:00",
                completed_at="2026-06-18T08:00:03-05:00",
                monitor_cycle_completed=True,
                outcome_update_completed=True,
                evidence_report_generated=True,
                daily_brief_generated=True,
            ),
            status_path,
        )

        report = build_evidence_autopilot_reliability_report(
            status_path=status_path,
            active_monitor_status_path=self.root / "missing-active-status.json",
            outcome_status_path=self.root / "missing-outcome-status.json",
            reports_dir=self.root / "reports",
            evidence_health_report=fake_evidence_health_report(completed=1, pending=0, unscorable=0),
            generated_at=datetime.fromisoformat("2026-06-20T08:05:00-05:00"),
        )

        self.assertTrue(report.latest_run_stale)
        self.assertGreater(report.latest_run_age_minutes or 0.0, 24 * 60)
        self.assertIn("STALE_EVIDENCE_AUTOPILOT_RUN", report.warnings)

    def test_system_readiness_sections_surface_warnings_without_strategy_changes(self) -> None:
        data_quality = build_data_quality_report(
            ["AAA", "BBB"],
            market_tape_report=fake_market_tape_report(),
            captures_dir=self.root / "captures",
            minute_bars_path=self.root / "minute-bars.json",
            generated_at=datetime.fromisoformat("2026-06-18T08:00:00-05:00"),
        )
        market_section = market_data_section(data_quality)
        autopilot = build_evidence_autopilot_reliability_report(
            status_path=self.root / "missing-autopilot-status.json",
            active_monitor_status_path=self.root / "missing-active-status.json",
            outcome_status_path=self.root / "missing-outcome-status.json",
            reports_dir=self.root / "reports",
            evidence_health_report=fake_evidence_health_report(completed=0, pending=1, unscorable=0),
            generated_at=datetime.fromisoformat("2026-06-18T08:05:00-05:00"),
        )
        autopilot_section = evidence_autopilot_section(autopilot)
        outcome_section = outcome_tracking_section(fake_evidence_health_report(completed=0, pending=1, unscorable=0))

        self.assertEqual("WARNING", market_section.status)
        self.assertEqual("WARNING", autopilot_section.status)
        self.assertEqual("WARNING", outcome_section.status)
        self.assertEqual(
            "FAILED",
            overall_status(
                [
                    ReadinessSection("A", "READY", ""),
                    ReadinessSection("B", "FAILED", ""),
                    ReadinessSection("C", "WARNING", ""),
                ]
            ),
        )

    def test_system_readiness_executive_summary_selects_highest_priority_issue(self) -> None:
        sections = [
            ReadinessSection("Market Data", "READY", "usable", recommended_next_action="Continue."),
            ReadinessSection("Active Monitor", "WARNING", "stale cycle", recommended_next_action="Run monitor."),
            ReadinessSection("SQLite Mirror", "FAILED", "validation failed", recommended_next_action="Run validation."),
        ]

        status = overall_status(sections)
        issue = highest_priority_issue(sections)

        self.assertEqual("FAILED", status)
        self.assertEqual("SQLite Mirror: validation failed", issue)
        self.assertIn("At least one readiness section failed", status_reason(status, issue))
        self.assertEqual("Run validation.", recommended_next_action_for_issue(sections, issue))
        self.assertEqual({"READY": 1, "WARNING": 1, "FAILED": 1, "UNKNOWN": 0}, section_status_counts(sections))
        self.assertEqual(
            ["No previous report available for comparison."],
            changes_since_previous(sections, status, {}),
        )

    def test_active_monitor_section_warns_on_stale_status(self) -> None:
        status_path = self.root / "active-monitor-status.json"
        save_active_monitor_status(
            ActiveMonitorStatus(
                state="IDLE",
                started_at="2026-06-18T07:00:00-05:00",
                updated_at="2026-06-18T07:05:00-05:00",
                cycles_requested=1,
                cycles_completed=1,
                interval_seconds=300,
                fetch_missing_market_data=False,
                last_cycle_at="2026-06-18T07:05:00-05:00",
            ),
            status_path,
        )

        section = active_monitor_section(
            generated_at=datetime.fromisoformat("2026-06-20T08:05:00-05:00"),
            status_path=status_path,
        )

        self.assertEqual("WARNING", section.status)
        self.assertTrue(any("STALE_ACTIVE_MONITOR_CYCLE" in fact for fact in section.supporting_facts))

    def test_provider_field_and_active_alert_sections_handle_missing_and_warning_reports(self) -> None:
        missing_provider = provider_field_quality_section(path=self.root / "missing-provider.json")
        missing_alert = active_alert_reliability_section(path=self.root / "missing-alert.json")
        self.assertEqual("UNKNOWN", missing_provider.status)
        self.assertEqual("UNKNOWN", missing_alert.status)

        provider_path = self.root / "provider-field-quality-latest.json"
        provider_path.write_text(
            json.dumps(
                {
                    "overall_status": "WARN",
                    "source_rows": 3,
                    "audit_row_count": 36,
                    "sqlite_write_status": {"status": "SKIPPED_UNSUPPORTED_SCHEMA"},
                    "top_warnings": [{"warning": "ZERO_RELATIVE_VOLUME", "count": 2}],
                    "warnings": ["PROVIDER_FIELD_WARNINGS_PRESENT"],
                }
            ),
            encoding="utf-8",
        )
        alert_path = self.root / "active-alert-reliability-latest.json"
        alert_path.write_text(
            json.dumps(
                {
                    "report": {
                        "overall_status": "WARNING",
                        "active_monitor_state": "IDLE",
                        "active_monitor_cycle_age_minutes": 1500,
                        "alert_count": 2,
                        "completed_alert_count": 1,
                        "pending_alert_count": 0,
                        "unscorable_alert_count": 1,
                        "warnings": ["STALE_ACTIVE_MONITOR_CYCLE"],
                        "next_recommended_action": "Run a fresh active monitor cycle.",
                    }
                }
            ),
            encoding="utf-8",
        )

        provider = provider_field_quality_section(path=provider_path)
        alert = active_alert_reliability_section(path=alert_path)
        self.assertEqual("WARNING", provider.status)
        self.assertEqual("WARNING", alert.status)
        self.assertTrue(any("ZERO_RELATIVE_VOLUME" in fact for fact in provider.supporting_facts))
        self.assertTrue(any("STALE_ACTIVE_MONITOR_CYCLE" in fact for fact in alert.supporting_facts))

    def test_sqlite_mirror_section_reports_pass_and_shadow_mismatch(self) -> None:
        validation_path = self.root / "sqlite-validation-latest.json"
        shadow_path = self.root / "sqlite-shadow-compare-latest.json"
        validation_path.write_text(
            json.dumps(
                {
                    "overall_status": "PASS",
                    "sqlite_schema_version": 7,
                    "missing_slices": [],
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        shadow_path.write_text(
            json.dumps(
                {
                    "overall_status": "PASS",
                    "mismatches": 0,
                    "unavailable": 0,
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )

        ready = sqlite_mirror_section(validation_path=validation_path, shadow_compare_path=shadow_path)
        self.assertEqual("READY", ready.status)

        shadow_path.write_text(
            json.dumps(
                {
                    "overall_status": "WARN",
                    "mismatches": 1,
                    "unavailable": 0,
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        warning = sqlite_mirror_section(validation_path=validation_path, shadow_compare_path=shadow_path)
        self.assertEqual("WARNING", warning.status)
        self.assertTrue(any("Shadow mismatches: 1" in fact for fact in warning.supporting_facts))

        validation_path.write_text(
            json.dumps(
                {
                    "overall_status": "PASS",
                    "sqlite_schema_version": 7,
                    "missing_slices": [],
                    "warnings": [],
                    "import_timestamps": {
                        "captures": {"latest_imported_at": "2026-06-18T08:00:00-05:00"}
                    },
                }
            ),
            encoding="utf-8",
        )
        shadow_path.write_text(
            json.dumps({"overall_status": "PASS", "mismatches": 0, "unavailable": 0, "warnings": []}),
            encoding="utf-8",
        )
        stale = sqlite_mirror_section(
            validation_path=validation_path,
            shadow_compare_path=shadow_path,
            generated_at=datetime.fromisoformat("2026-06-20T08:00:00-05:00"),
        )
        self.assertEqual("WARNING", stale.status)
        self.assertTrue(any("STALE_SQLITE_MIRROR" in fact for fact in stale.supporting_facts))

    def test_user_state_safety_section_reports_diff_status(self) -> None:
        diff_path = self.root / "sqlite-user-state-diff-latest.json"
        diff_path.write_text(
            json.dumps(
                {
                    "overall_status": "PASS",
                    "records_in_files": 52,
                    "records_in_sqlite": 52,
                    "missing_in_sqlite": 0,
                    "extra_in_sqlite": 0,
                    "changed_values": 0,
                    "malformed_records": 0,
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )

        ready = user_state_safety_section(diff_path=diff_path)
        self.assertEqual("READY", ready.status)

        diff_path.write_text(
            json.dumps(
                {
                    "overall_status": "WARN",
                    "records_in_files": 52,
                    "records_in_sqlite": 51,
                    "missing_in_sqlite": 1,
                    "extra_in_sqlite": 0,
                    "changed_values": 0,
                    "malformed_records": 0,
                    "warnings": [],
                }
            ),
            encoding="utf-8",
        )
        warning = user_state_safety_section(diff_path=diff_path)
        self.assertEqual("WARNING", warning.status)
        self.assertTrue(any("Missing in SQLite: 1" in fact for fact in warning.supporting_facts))


def fake_market_tape_report() -> MarketTapeHealthReport:
    generated = "2026-06-18T08:00:00-05:00"
    attempts = [
        MarketTapeHealthAttempt(
            generated_at=generated,
            symbol="AAA",
            provider="combined",
            status="SUCCESS",
            success=True,
            usable_for_alerting=True,
            source="nasdaq+yahoo",
            fields_returned=[
                "last_price",
                "premarket_volume",
                "bid",
                "ask",
                "spread_percent",
                "relative_volume",
                "rvol_numerator",
                "rvol_denominator",
            ],
            last_price=10.25,
            bid=10.24,
            ask=10.26,
            spread_percent=0.2,
            relative_volume=1.2,
            rvol_numerator=1200000,
            rvol_denominator=1000000,
        ),
        MarketTapeHealthAttempt(
            generated_at=generated,
            symbol="BBB",
            provider="combined",
            status="FAIL",
            success=False,
            usable_for_alerting=False,
            source="none",
            fields_returned=[],
            error_message="QUOTE_FETCH_FAILED",
            warnings=["QUOTE_FETCH_FAILED"],
        ),
    ]
    return MarketTapeHealthReport(
        generated_at=generated,
        symbols=["AAA", "BBB"],
        attempts=attempts,
        usable_symbol_count=1,
        missing_symbol_count=1,
        provider_summary={
            "combined": {"attempts": 2, "successes": 1, "usable_for_alerting": 1, "failures": 1}
        },
        warnings=["SYMBOLS_WITHOUT_USABLE_MARKET_TAPE"],
    )


def fake_evidence_health_report(*, completed: int, pending: int, unscorable: int) -> EvidenceHealthReport:
    gate = EvidenceGate(
        completed_alerts=completed,
        required_alerts=25,
        evidence_status="COLLECTING",
        allowed_action="Collect evidence only",
        strategy_optimization_status="LOCKED",
        reason="Insufficient completed alerts.",
    )
    return EvidenceHealthReport(
        generated_at="2026-06-18T08:00:00-05:00",
        source_alerts_path="alerts.json",
        source_minute_bars_path="bars.json",
        source_outcome_status_path="status.json",
        total_alerts=completed + pending + unscorable,
        completed_alerts=completed,
        pending_alerts=pending,
        unscorable_alerts=unscorable,
        success_count=completed,
        failure_count=0,
        noise_count=0,
        late_count=0,
        completion_rate_pct=None,
        alerts_generated=completed + pending + unscorable,
        alerts_captured=completed + pending + unscorable,
        alerts_classified=completed,
        completed_outcomes=completed,
        stale_pending_alerts=[],
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
        outcome_classifications_saved=completed > 0,
        evidence_gate=gate,
        warnings=["INSUFFICIENT_COMPLETED_ALERTS"] if completed < 25 else [],
    )


if __name__ == "__main__":
    unittest.main()
