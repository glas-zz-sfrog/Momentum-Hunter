from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.data_quality import build_data_quality_report, export_data_quality_report
from momentum_hunter.evidence_autopilot import EvidenceAutopilotStatus, save_evidence_autopilot_status
from momentum_hunter.evidence_autopilot_reliability import build_evidence_autopilot_reliability_report
from momentum_hunter.evidence_health import EvidenceGate, EvidenceHealthReport
from momentum_hunter.market_tape_health import MarketTapeHealthAttempt, MarketTapeHealthReport
from momentum_hunter.storage import file_sha256
from momentum_hunter.system_readiness import (
    ReadinessSection,
    evidence_autopilot_section,
    market_data_section,
    outcome_tracking_section,
    overall_status,
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
        self.assertIn("NO_ALERT_OUTCOME_UPDATE_STATUS", report.warnings)

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
