from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.alert_outcome_updater import AlertOutcomeUpdateReport, save_update_report
from momentum_hunter.app import (
    active_monitor_summary_text,
    evidence_health_summary_text,
    alert_performance_summary_text,
    alert_outcome_update_status_text,
    load_active_monitor_dashboard_rows,
    load_evidence_health_dashboard_rows,
    load_alert_performance_dashboard_rows,
    load_user_monitor_symbol_rows,
)
from momentum_hunter.monitor_targets import UserDefinedMonitorSymbol, save_user_defined_symbols
from momentum_hunter.opportunity_alerts import AlertOutcome, OpportunityAlert, save_alerts


class ActiveMonitorDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-active-monitor-dashboard-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_summary_highlights_market_tape_gap(self) -> None:
        path = self.write_cycle(
            {
                "target_count": 6,
                "coverage_row_count": 5,
                "active_alert_count": 0,
                "new_alert_count": 0,
                "warnings": ["COVERAGE_ROWS_WITHOUT_MARKET_DATA"],
            }
        )

        self.assertEqual(
            "ACTIVE MONITOR: 6 target(s), 5 coverage row(s) need market tape",
            active_monitor_summary_text(path),
        )

    def test_summary_highlights_active_alerts(self) -> None:
        path = self.write_cycle(
            {
                "target_count": 4,
                "coverage_row_count": 0,
                "active_alert_count": 2,
                "new_alert_count": 1,
                "warnings": [],
            }
        )

        self.assertEqual(
            "ACTIVE MONITOR: 2 active alert(s), 1 new alert(s), 4 target(s)",
            active_monitor_summary_text(path),
        )

    def test_dashboard_rows_show_coverage_and_warnings(self) -> None:
        path = self.write_cycle(
            {
                "generated_at": "2026-06-17T16:37:59-05:00",
                "trade_report_path": "C:/x/active-monitor-coverage.json",
                "target_count": 6,
                "target_symbols": ["CRWV", "MDT"],
                "matched_target_count": 6,
                "missing_target_symbols": ["MDT"],
                "covered_missing_symbols": ["MDT"],
                "uncovered_missing_symbols": [],
                "coverage_row_count": 1,
                "refreshed_target_count": 3,
                "readiness_changed_count": 2,
                "market_data_refresh_report_path": "C:/x/active-monitor-refresh-20260617T1000000500.json",
                "active_alert_count": 0,
                "new_alert_count": 0,
                "tracked_alert_count": 0,
                "state_transition_count": 0,
                "warnings": ["TARGETS_WITHOUT_SOURCE_TRADE_ROWS", "COVERAGE_ROWS_ADDED_FOR_MISSING_TARGETS"],
            }
        )

        rows = load_active_monitor_dashboard_rows(path)
        by_metric = {row["metric"]: row for row in rows}

        self.assertEqual("6", by_metric["Targets"]["value"])
        self.assertEqual("6 / 6", by_metric["Matched / Covered"]["value"])
        self.assertEqual("1", by_metric["Missing Source Rows"]["value"])
        self.assertEqual("MDT", by_metric["Covered Missing"]["note"])
        self.assertEqual("3", by_metric["Refreshed Targets"]["value"])
        self.assertEqual(
            "readiness changed: 2; active-monitor-refresh-20260617T1000000500.json",
            by_metric["Refreshed Targets"]["note"],
        )
        self.assertEqual("2", by_metric["Warnings"]["value"])

    def test_bad_or_missing_report_returns_empty_state(self) -> None:
        bad = self.root / "bad.json"
        bad.write_text("{not json", encoding="utf-8")

        self.assertEqual("ACTIVE MONITOR: NO CYCLE REPORT YET", active_monitor_summary_text(bad))
        self.assertEqual([], load_active_monitor_dashboard_rows(bad))
        self.assertEqual([], load_active_monitor_dashboard_rows(self.root / "missing.json"))

    def test_user_monitor_symbol_rows_are_sorted(self) -> None:
        path = self.root / "opportunity-monitor-symbols.json"
        save_user_defined_symbols(
            {
                "TSLA": UserDefinedMonitorSymbol(symbol="TSLA", notes="EV watch", enabled=True),
                "AMD": UserDefinedMonitorSymbol(symbol="AMD", notes="AI chips", enabled=True),
            },
            path,
        )

        rows = load_user_monitor_symbol_rows(path)

        self.assertEqual(["AMD", "TSLA"], [row["symbol"] for row in rows])
        self.assertEqual("yes", rows[0]["enabled"])
        self.assertEqual("AI chips", rows[0]["notes"])

    def test_bad_user_monitor_symbol_store_returns_empty_rows(self) -> None:
        path = self.root / "opportunity-monitor-symbols.json"
        path.write_text("{bad json", encoding="utf-8")

        self.assertEqual([], load_user_monitor_symbol_rows(path))

    def test_alert_outcome_update_status_text(self) -> None:
        path = self.root / "alert-outcome-update-status.json"
        save_update_report(
            AlertOutcomeUpdateReport(
                generated_at="2026-06-17T11:00:00-05:00",
                alert_count=4,
                updated_alert_count=2,
                completed_alert_count=3,
                pending_alert_count=1,
                unscorable_alert_count=0,
                symbols_processed=["AAA", "BBB"],
                bars_loaded_count=120,
                bars_saved_path="minute-bars.json",
                alerts_path="alerts.json",
                warnings=["NO_MINUTE_BARS_FETCHED:BBB"],
            ),
            path,
        )

        self.assertEqual(
            "OUTCOME UPDATE: 2 changed, 3 completed, 1 pending, 0 unscorable, 120 minute bar(s), 1 warning(s)",
            alert_outcome_update_status_text(path),
        )

    def test_alert_performance_dashboard_rows_show_sample_size(self) -> None:
        path = self.root / "opportunity-alerts.json"
        save_alerts(
            [
                OpportunityAlert(
                    alert_id="a1",
                    symbol="AAA",
                    timestamp="2026-06-19T07:00:00-05:00",
                    alert_type="BREAKOUT",
                    current_state="EXECUTION_READY_TRADE",
                    previous_state="PLANNING_SCAFFOLD",
                    reason="test",
                    price=10.0,
                    bid=9.99,
                    ask=10.01,
                    spread_percent=0.2,
                    volume=1000000,
                    premarket_volume=500000,
                    premarket_percent=2.0,
                    rvol=1.4,
                    rvol_type="INTRADAY_RVOL",
                    suggested_entry=10.1,
                    stop=9.5,
                    target_1=11.0,
                    target_2=12.0,
                    news_catalyst="test",
                    market_regime="bull",
                    event_mode=False,
                    source_report="test.json",
                    outcome=AlertOutcome(
                        status="COMPLETED",
                        five_minute_return_pct=1.0,
                        fifteen_minute_return_pct=2.0,
                        thirty_minute_return_pct=3.0,
                        sixty_minute_return_pct=4.0,
                        mfe_60m_pct=5.0,
                        mae_60m_pct=-1.0,
                        target_1_hit=True,
                        target_2_hit=False,
                        stop_hit=False,
                        stop_hit_before_target=False,
                        classification="SUCCESSFUL",
                    ),
                )
            ],
            path,
        )

        text = alert_performance_summary_text(path)
        rows = load_alert_performance_dashboard_rows(path)

        self.assertIn("1 alert(s), 1 completed, 0 pending", text)
        self.assertIn("Sample size: 1", text)
        self.assertEqual("Best Alert Types", rows[0]["section"])
        self.assertEqual("BREAKOUT", rows[0]["group"])

    def test_evidence_health_dashboard_rows_show_locked_gate(self) -> None:
        path = self.root / "opportunity-alerts.json"
        save_alerts(
            [
                OpportunityAlert(
                    alert_id="a1",
                    symbol="AAA",
                    timestamp="2026-06-19T07:00:00-05:00",
                    alert_type="BREAKOUT",
                    current_state="EXECUTION_READY_TRADE",
                    previous_state="PLANNING_SCAFFOLD",
                    reason="test",
                    price=10.0,
                    bid=9.99,
                    ask=10.01,
                    spread_percent=0.2,
                    volume=1000000,
                    premarket_volume=500000,
                    premarket_percent=2.0,
                    rvol=1.4,
                    rvol_type="INTRADAY_RVOL",
                    suggested_entry=10.1,
                    stop=9.5,
                    target_1=11.0,
                    target_2=12.0,
                    news_catalyst="test",
                    market_regime="bull",
                    event_mode=False,
                    source_report="test.json",
                    outcome=AlertOutcome(
                        status="COMPLETED",
                        five_minute_return_pct=1.0,
                        fifteen_minute_return_pct=2.0,
                        thirty_minute_return_pct=3.0,
                        sixty_minute_return_pct=4.0,
                        mfe_60m_pct=5.0,
                        mae_60m_pct=-1.0,
                        target_1_hit=True,
                        target_2_hit=False,
                        stop_hit=False,
                        stop_hit_before_target=False,
                        classification="SUCCESSFUL",
                    ),
                )
            ],
            path,
        )

        text = evidence_health_summary_text(path)
        rows = load_evidence_health_dashboard_rows(path)
        by_metric = {row["metric"]: row for row in rows}

        self.assertIn("1/25 completed alert(s)", text)
        self.assertIn("Optimization: LOCKED", text)
        self.assertEqual("1 / 25", by_metric["Completed Alerts"]["value"])
        self.assertEqual("LOCKED", by_metric["Optimization Gate"]["value"])

    def write_cycle(self, cycle: dict) -> Path:
        path = self.root / "active-monitor-cycle.json"
        payload = {"schema_version": 1, "monitor_cycle": cycle}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path
