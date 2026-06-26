from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.active_alert_reliability import (
    build_active_alert_reliability_report,
    export_active_alert_reliability_report,
)
from momentum_hunter.active_monitor import ActiveMonitorStatus, save_active_monitor_status
from momentum_hunter.alert_outcome_updater import AlertOutcomeUpdateReport, save_update_report
from momentum_hunter.opportunity_alerts import AlertOutcome, OpportunityAlert, save_alerts, stable_alert_id
from momentum_hunter.storage import file_sha256


class ActiveAlertReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-active-alert-reliability-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.status_path = self.root / "active-monitor-status.json"
        self.alerts_path = self.root / "opportunity-alerts.json"
        self.outcome_status_path = self.root / "alert-outcome-update-status.json"
        self.sqlite_validation_path = self.root / "sqlite-validation-latest.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_report_warns_on_stale_cycle_and_preserves_alert_store(self) -> None:
        write_cycle_report(self.reports_dir / "active-monitor-cycle-20260618T0800000500.json")
        save_active_monitor_status(
            ActiveMonitorStatus(
                state="IDLE",
                started_at="2026-06-18T08:00:00-05:00",
                updated_at="2026-06-18T08:00:01-05:00",
                cycles_requested=1,
                cycles_completed=1,
                interval_seconds=0,
                fetch_missing_market_data=True,
                last_cycle_at="2026-06-18T08:00:00-05:00",
                last_report_path=str(self.reports_dir / "active-monitor-cycle-20260618T0800000500.json"),
                warnings=["COVERAGE_ROWS_WITHOUT_MARKET_DATA"],
            ),
            self.status_path,
        )
        save_alerts(
            [
                alert_for("AAA", outcome=AlertOutcome(status="COMPLETED", classification="SUCCESSFUL")),
                alert_for(
                    "BBB",
                    price=None,
                    outcome=AlertOutcome(status="UNSCORABLE_OUTCOME", classification="UNSCORABLE_MISSING_ENTRY_PRICE"),
                ),
            ],
            self.alerts_path,
        )
        save_update_report(
            AlertOutcomeUpdateReport(
                generated_at="2026-06-18T08:10:00-05:00",
                alert_count=2,
                updated_alert_count=1,
                completed_alert_count=1,
                pending_alert_count=0,
                unscorable_alert_count=1,
                symbols_processed=["AAA", "BBB"],
                bars_loaded_count=10,
                bars_saved_path=str(self.root / "bars.json"),
                alerts_path=str(self.alerts_path),
            ),
            self.outcome_status_path,
        )
        write_sqlite_validation(self.sqlite_validation_path)
        before = file_sha256(self.alerts_path)

        report = build_active_alert_reliability_report(
            status_path=self.status_path,
            alerts_path=self.alerts_path,
            outcome_status_path=self.outcome_status_path,
            reports_dir=self.reports_dir,
            sqlite_validation_path=self.sqlite_validation_path,
            generated_at=datetime.fromisoformat("2026-06-20T08:05:00-05:00"),
        )

        self.assertEqual("WARNING", report.overall_status)
        self.assertEqual(2, report.alert_count)
        self.assertEqual(1, report.completed_alert_count)
        self.assertEqual(0, report.pending_alert_count)
        self.assertEqual(1, report.unscorable_alert_count)
        self.assertIn("STALE_ACTIVE_MONITOR_CYCLE", report.warnings)
        self.assertIn("ACTIVE_MONITOR_WARNINGS_PRESENT", report.warnings)
        self.assertIn("ALERTS_MISSING_PRICE", report.warnings)
        self.assertEqual(before, file_sha256(self.alerts_path))

    def test_report_detects_duplicate_and_unstable_alert_identity(self) -> None:
        write_cycle_report(self.reports_dir / "active-monitor-cycle-20260618T0800000500.json")
        write_sqlite_validation(self.sqlite_validation_path)
        first = alert_for("AAA")
        second = alert_for("AAA")
        payload = {
            "schema_version": 1,
            "engine_version": "opportunity_alert_engine_v1",
            "alerts": [
                alert_payload(first, alert_id="duplicate-id"),
                alert_payload(second, alert_id="duplicate-id"),
            ],
        }
        self.alerts_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        report = build_active_alert_reliability_report(
            status_path=self.status_path,
            alerts_path=self.alerts_path,
            outcome_status_path=self.outcome_status_path,
            reports_dir=self.reports_dir,
            sqlite_validation_path=self.sqlite_validation_path,
            generated_at=datetime.fromisoformat("2026-06-18T08:05:00-05:00"),
        )

        self.assertEqual("FAILED", report.overall_status)
        self.assertEqual(["duplicate-id"], report.duplicate_alert_ids)
        self.assertEqual(["AAA|2026-06-18T08:00:00-05:00|PRICE_EXPANSION_1PCT_5M"], report.duplicate_semantic_keys)
        self.assertEqual(["duplicate-id", "duplicate-id"], report.unstable_alert_ids)
        self.assertIn("DUPLICATE_ALERT_IDS", report.warnings)
        self.assertIn("ALERT_IDS_NOT_STABLE", report.warnings)

    def test_report_surfaces_sqlite_mirror_mismatch(self) -> None:
        save_alerts([alert_for("AAA")], self.alerts_path)
        write_sqlite_validation(self.sqlite_validation_path, alert_status="FAIL")

        report = build_active_alert_reliability_report(
            status_path=self.status_path,
            alerts_path=self.alerts_path,
            outcome_status_path=self.outcome_status_path,
            reports_dir=self.reports_dir,
            sqlite_validation_path=self.sqlite_validation_path,
            generated_at=datetime.fromisoformat("2026-06-18T08:05:00-05:00"),
        )

        self.assertEqual("FAILED", report.overall_status)
        self.assertEqual("FAIL", report.sqlite_alert_check_status)
        self.assertIn("SQLITE_ALERT_MIRROR_NOT_PASS", report.warnings)

    def test_export_writes_json_and_markdown(self) -> None:
        write_sqlite_validation(self.sqlite_validation_path)
        save_alerts([alert_for("AAA")], self.alerts_path)
        report = build_active_alert_reliability_report(
            status_path=self.status_path,
            alerts_path=self.alerts_path,
            outcome_status_path=self.outcome_status_path,
            reports_dir=self.reports_dir,
            sqlite_validation_path=self.sqlite_validation_path,
            generated_at=datetime.fromisoformat("2026-06-18T08:05:00-05:00"),
        )

        paths = export_active_alert_reliability_report(
            report,
            json_path=self.root / "active-alert-reliability-latest.json",
            markdown_path=self.root / "active-alert-reliability-latest.md",
        )

        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["report"].exists())
        self.assertIn("Active Alert Reliability", paths["report"].read_text(encoding="utf-8"))


def alert_for(
    symbol: str,
    *,
    price: float | None = 10.0,
    outcome: AlertOutcome | None = None,
) -> OpportunityAlert:
    timestamp = "2026-06-18T08:00:00-05:00"
    alert_type = "PRICE_EXPANSION_1PCT_5M"
    return OpportunityAlert(
        alert_id=stable_alert_id(symbol, timestamp, alert_type),
        symbol=symbol,
        timestamp=timestamp,
        alert_type=alert_type,
        current_state="PLANNING_SCAFFOLD",
        previous_state="PLANNING_SCAFFOLD",
        reason="test alert",
        price=price,
        bid=9.99,
        ask=10.01,
        spread_percent=0.2,
        volume=1_000_000,
        premarket_volume=100_000,
        premarket_percent=1.2,
        rvol=1.3,
        rvol_type="INTRADAY_RVOL",
        suggested_entry=10.1,
        stop=9.6,
        target_1=10.8,
        target_2=11.4,
        news_catalyst="",
        market_regime="bull",
        event_mode=False,
        source_report=str(Path.cwd() / "test-trade-report.json"),
        outcome=outcome or AlertOutcome(),
    )


def alert_payload(alert: OpportunityAlert, *, alert_id: str) -> dict[str, object]:
    return {
        "alert_id": alert_id,
        "symbol": alert.symbol,
        "timestamp": alert.timestamp,
        "alert_type": alert.alert_type,
        "current_state": alert.current_state,
        "previous_state": alert.previous_state,
        "reason": alert.reason,
        "price": alert.price,
        "bid": alert.bid,
        "ask": alert.ask,
        "spread_percent": alert.spread_percent,
        "volume": alert.volume,
        "premarket_volume": alert.premarket_volume,
        "premarket_percent": alert.premarket_percent,
        "rvol": alert.rvol,
        "rvol_type": alert.rvol_type,
        "suggested_entry": alert.suggested_entry,
        "stop": alert.stop,
        "target_1": alert.target_1,
        "target_2": alert.target_2,
        "news_catalyst": alert.news_catalyst,
        "market_regime": alert.market_regime,
        "event_mode": alert.event_mode,
        "source_report": alert.source_report,
        "engine_version": alert.engine_version,
        "outcome": {
            "status": alert.outcome.status,
            "classification": alert.outcome.classification,
        },
    }


def write_cycle_report(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "monitor_cycle": {
            "generated_at": "2026-06-18T08:00:00-05:00",
            "target_count": 2,
            "new_alert_count": 1,
            "active_alert_count": 1,
            "tracked_alert_count": 2,
            "state_transition_count": 0,
            "coverage_row_count": 1,
            "warnings": ["COVERAGE_ROWS_WITHOUT_MARKET_DATA"],
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_sqlite_validation(path: Path, *, alert_status: str = "PASS", outcome_status: str = "PASS") -> None:
    payload = {
        "overall_status": "PASS" if alert_status == "PASS" and outcome_status == "PASS" else "FAIL",
        "warnings": [],
        "checks": [
            {"name": "opportunity_alerts", "status": alert_status},
            {"name": "alert_outcomes", "status": outcome_status},
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
