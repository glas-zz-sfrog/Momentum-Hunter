from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.alert_outcome_updater import AlertOutcomeUpdateReport, save_update_report
from momentum_hunter.evidence_health import (
    build_evidence_health_report,
    build_reliability_report,
    export_evidence_reports,
)
from momentum_hunter.opportunity_alerts import AlertOutcome, OpportunityAlert, save_alerts


class EvidenceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-evidence-health-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.alerts_path = self.root / "opportunity-alerts.json"
        self.minute_bars_path = self.root / "opportunity-minute-bars.json"
        self.outcome_status_path = self.root / "alert-outcome-update-status.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_evidence_health_tracks_alert_funnel_and_locks_optimization(self) -> None:
        save_alerts(
            [
                self.alert("a1", "AAA", "BREAKOUT", "EXECUTION_READY_TRADE", "SUCCESSFUL"),
                self.alert("a2", "BBB", "RVOL_CROSS", "PLANNING_SCAFFOLD", "PENDING", price=10.0),
                self.alert(
                    "a3",
                    "CCC",
                    "STATE_CHANGE",
                    "",
                    "UNSCORABLE_MISSING_ENTRY_PRICE",
                    price=None,
                    news="",
                ),
            ],
            self.alerts_path,
        )
        self.minute_bars_path.write_text(json.dumps({"bars": {"AAA": [{"timestamp": "2026-06-19T07:00:00-05:00"}]}}), encoding="utf-8")

        before = self.alerts_path.read_text(encoding="utf-8")
        report = build_evidence_health_report(
            alerts_path=self.alerts_path,
            minute_bars_path=self.minute_bars_path,
            outcome_status_path=self.outcome_status_path,
            reports_dir=self.reports_dir,
            generated_at=datetime.fromisoformat("2026-06-20T07:00:00-05:00"),
            stale_pending_hours=1,
        )
        after = self.alerts_path.read_text(encoding="utf-8")

        self.assertEqual(before, after)
        self.assertEqual(3, report.alerts_generated)
        self.assertEqual(3, report.alerts_captured)
        self.assertEqual(1, report.alerts_classified)
        self.assertEqual(1, report.completed_outcomes)
        self.assertEqual(1, report.completed_alerts)
        self.assertEqual(1, report.pending_alerts)
        self.assertEqual(1, report.unscorable_alerts)
        self.assertEqual(50.0, report.completion_rate_pct)
        self.assertEqual(1, len(report.stale_pending_alerts))
        self.assertEqual(1, len(report.unscorable_alert_issues))
        self.assertEqual({"UNSCORABLE_MISSING_ENTRY_PRICE": 1}, report.unscorable_by_reason)
        self.assertEqual(1, len(report.missing_minute_bar_alerts))
        self.assertEqual(1, len(report.missing_outcome_alerts))
        self.assertEqual(1, len(report.missing_readiness_state_alerts))
        self.assertEqual(1, len(report.missing_news_snapshot_alerts))
        self.assertEqual("COLLECTING", report.evidence_gate.evidence_status)
        self.assertEqual("LOCKED", report.evidence_gate.strategy_optimization_status)

    def test_reliability_report_counts_monitor_cycles_and_outcome_status(self) -> None:
        self.write_cycle("active-monitor-cycle-1.json", "2026-06-20T06:00:00-05:00", warnings=[])
        self.write_cycle("active-monitor-cycle-2.json", "2026-06-20T07:00:00-05:00", warnings=["TARGETS_WITHOUT_SOURCE_TRADE_ROWS"])
        save_alerts(
            [
                self.alert("a1", "AAA", "BREAKOUT", "EXECUTION_READY_TRADE", "SUCCESSFUL"),
                self.alert("a2", "BBB", "RVOL_CROSS", "PLANNING_SCAFFOLD", "PENDING"),
            ],
            self.alerts_path,
        )
        save_update_report(
            AlertOutcomeUpdateReport(
                generated_at="2026-06-20T08:00:00-05:00",
                alert_count=2,
                updated_alert_count=1,
                completed_alert_count=1,
                pending_alert_count=1,
                unscorable_alert_count=0,
                symbols_processed=["AAA", "BBB"],
                bars_loaded_count=100,
                bars_saved_path="bars.json",
                alerts_path="alerts.json",
                warnings=["NO_MINUTE_BARS_FETCHED:BBB"],
            ),
            self.outcome_status_path,
        )

        report = build_reliability_report(
            alerts_path=self.alerts_path,
            outcome_status_path=self.outcome_status_path,
            reports_dir=self.reports_dir,
            generated_at=datetime.fromisoformat("2026-06-20T09:00:00-05:00"),
        )

        self.assertEqual(2, report.monitor_cycle_count)
        self.assertEqual(2, report.successful_cycle_count)
        self.assertEqual(0, report.failed_cycle_count)
        self.assertEqual(100.0, report.cycle_reliability_pct)
        self.assertEqual(1, report.warning_cycle_count)
        self.assertEqual(2, report.alerts_generated)
        self.assertEqual(1, report.alerts_completed)
        self.assertEqual(50.0, report.alert_completion_rate_pct)
        self.assertEqual(50.0, report.outcome_processing_success_rate_pct)
        self.assertGreaterEqual(report.missing_data_incident_count, 2)

    def test_export_writes_evidence_and_reliability_reports(self) -> None:
        save_alerts([self.alert("a1", "AAA", "BREAKOUT", "EXECUTION_READY_TRADE", "SUCCESSFUL")], self.alerts_path)
        health = build_evidence_health_report(
            alerts_path=self.alerts_path,
            minute_bars_path=self.minute_bars_path,
            outcome_status_path=self.outcome_status_path,
            reports_dir=self.reports_dir,
            generated_at=datetime.fromisoformat("2026-06-20T07:00:00-05:00"),
        )
        reliability = build_reliability_report(
            alerts_path=self.alerts_path,
            outcome_status_path=self.outcome_status_path,
            reports_dir=self.reports_dir,
            generated_at=datetime.fromisoformat("2026-06-20T07:00:00-05:00"),
        )

        paths = export_evidence_reports(health, reliability, self.root / "output")

        self.assertTrue(paths["evidence_json"].name.startswith("evidence-health-report-"))
        self.assertTrue(paths["reliability_json"].name.startswith("reliability-report-"))
        self.assertIn("Evidence Status", paths["evidence_report"].read_text(encoding="utf-8"))
        self.assertIn("Cycle reliability", paths["reliability_report"].read_text(encoding="utf-8"))

    def write_cycle(self, name: str, generated_at: str, *, warnings: list[str]) -> None:
        payload = {
            "schema_version": 1,
            "monitor_cycle": {
                "generated_at": generated_at,
                "target_count": 3,
                "new_alert_count": 1,
                "active_alert_count": 1,
                "warnings": warnings,
                "uncovered_missing_symbols": [],
            },
        }
        (self.reports_dir / name).write_text(json.dumps(payload), encoding="utf-8")

    def alert(
        self,
        alert_id: str,
        symbol: str,
        alert_type: str,
        state: str,
        classification: str,
        *,
        price: float | None = 10.0,
        news: str = "news",
    ) -> OpportunityAlert:
        completed = classification in {"SUCCESSFUL", "FAILED", "NOISE", "LATE"}
        unscorable = classification.startswith("UNSCORABLE_")
        return OpportunityAlert(
            alert_id=alert_id,
            symbol=symbol,
            timestamp="2026-06-20T05:00:00-05:00",
            alert_type=alert_type,
            current_state=state,
            previous_state="PLANNING_SCAFFOLD",
            reason="test",
            price=price,
            bid=9.99 if price else None,
            ask=10.01 if price else None,
            spread_percent=0.2 if price else None,
            volume=1000000 if price else None,
            premarket_volume=500000 if price else None,
            premarket_percent=1.5 if price else None,
            rvol=1.3 if price else None,
            rvol_type="INTRADAY_RVOL",
            suggested_entry=10.1,
            stop=9.5,
            target_1=11.0,
            target_2=12.0,
            news_catalyst=news,
            market_regime="bull",
            event_mode=False,
            source_report="test.json",
            outcome=AlertOutcome(
                status="COMPLETED" if completed else ("UNSCORABLE_OUTCOME" if unscorable else "PENDING_OUTCOME"),
                five_minute_return_pct=1.0 if completed else None,
                fifteen_minute_return_pct=2.0 if completed else None,
                thirty_minute_return_pct=3.0 if completed else None,
                sixty_minute_return_pct=4.0 if completed else None,
                mfe_60m_pct=5.0 if completed else None,
                mae_60m_pct=-1.0 if completed else None,
                target_1_hit=classification == "SUCCESSFUL" if completed else None,
                target_2_hit=False if completed else None,
                stop_hit=classification == "FAILED" if completed else None,
                stop_hit_before_target=classification == "FAILED" if completed else None,
                classification=classification,
                evaluation_notes=[] if completed else (["Missing alert price."] if unscorable else ["pending"]),
            ),
        )


if __name__ == "__main__":
    unittest.main()
