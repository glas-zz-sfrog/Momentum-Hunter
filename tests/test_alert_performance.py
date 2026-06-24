from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.alert_performance import build_alert_performance_report, export_alert_performance_report
from momentum_hunter.opportunity_alerts import AlertOutcome, OpportunityAlert, save_alerts


class AlertPerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-alert-performance-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.root / "opportunity-alerts.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_alert_type_symbol_and_readiness_metrics_are_deterministic(self) -> None:
        save_alerts(
            [
                self.alert(
                    "a1",
                    symbol="AAA",
                    alert_type="BREAKOUT",
                    state="EXECUTION_READY_TRADE",
                    classification="SUCCESSFUL",
                    returns=(1.0, 2.0, 3.0, 4.0),
                    mfe=6.0,
                    mae=-1.0,
                ),
                self.alert(
                    "a2",
                    symbol="BBB",
                    alert_type="BREAKOUT",
                    state="PLANNING_SCAFFOLD",
                    classification="NOISE",
                    returns=(0.0, 0.1, 0.2, 0.3),
                    mfe=0.6,
                    mae=-0.4,
                ),
                self.alert(
                    "a3",
                    symbol="BBB",
                    alert_type="RVOL_CROSS",
                    state="PLANNING_SCAFFOLD",
                    classification="FAILED",
                    returns=(-0.5, -1.0, -1.5, -2.0),
                    mfe=0.2,
                    mae=-3.0,
                ),
                self.alert("a4", symbol="CCC", alert_type="RVOL_CROSS", state="PLANNING_SCAFFOLD", classification="PENDING"),
                self.alert(
                    "a5",
                    symbol="DDD",
                    alert_type="STATE_CHANGE",
                    state="DO_NOT_TRADE_MISSING_DATA",
                    classification="UNSCORABLE_MISSING_ENTRY_PRICE",
                ),
            ],
            self.alerts_path,
        )

        report = build_alert_performance_report(self.alerts_path, generated_at="2026-06-19T07:00:00-05:00")
        breakout = next(row for row in report.alert_type_performance if row.group == "BREAKOUT")
        bbb = next(row for row in report.symbol_performance if row.group == "BBB")
        planning = next(row for row in report.readiness_state_performance if row.group == "PLANNING_SCAFFOLD")

        self.assertEqual(5, report.total_alerts)
        self.assertEqual(3, report.completed_alerts)
        self.assertEqual(1, report.pending_alerts)
        self.assertEqual(1, report.unscorable_alerts)
        self.assertEqual("INSUFFICIENT_SAMPLE", report.measurable_edge_status)
        self.assertEqual(2, breakout.alert_count)
        self.assertEqual(2, breakout.completed_count)
        self.assertEqual(50.0, breakout.win_rate_pct)
        self.assertEqual(50.0, breakout.success_rate_pct)
        self.assertEqual(50.0, breakout.noise_rate_pct)
        self.assertEqual(0.0, breakout.failure_rate_pct)
        self.assertEqual(2.15, breakout.average_60m_return_pct)
        self.assertEqual(3.3, breakout.average_mfe_pct)
        self.assertEqual(-0.7, breakout.average_mae_pct)
        self.assertEqual(2, bbb.alert_count)
        self.assertEqual(2, bbb.completed_count)
        self.assertEqual(0, bbb.pending_count)
        self.assertEqual(3, planning.alert_count)
        self.assertEqual(2, planning.completed_count)
        state_change = next(row for row in report.alert_type_performance if row.group == "STATE_CHANGE")
        self.assertEqual(1, state_change.unscorable_count)
        self.assertEqual(0, state_change.pending_count)
        self.assertEqual(0, state_change.completed_count)

    def test_export_writes_json_and_markdown_reports(self) -> None:
        save_alerts(
            [
                self.alert(
                    "a1",
                    symbol="AAA",
                    alert_type="BREAKOUT",
                    state="EXECUTION_READY_TRADE",
                    classification="SUCCESSFUL",
                    returns=(1.0, 2.0, 3.0, 4.0),
                    mfe=6.0,
                    mae=-1.0,
                )
            ],
            self.alerts_path,
        )
        report = build_alert_performance_report(self.alerts_path, generated_at="2026-06-19T07:00:00-05:00")

        paths = export_alert_performance_report(report, self.root / "reports")
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        text = paths["report"].read_text(encoding="utf-8")

        self.assertTrue(paths["json"].name.startswith("alert-performance-report-"))
        self.assertIn("best_alert_types", payload)
        self.assertIn("unscorable_alerts", payload)
        self.assertIn("symbol_performance", payload)
        self.assertIn("Current Sample Size", text)
        self.assertIn("Best Alert Types", text)

    def alert(
        self,
        alert_id: str,
        *,
        symbol: str,
        alert_type: str,
        state: str,
        classification: str,
        returns: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        mfe: float = 0.0,
        mae: float = 0.0,
    ) -> OpportunityAlert:
        completed = classification in {"SUCCESSFUL", "FAILED", "NOISE", "LATE"}
        unscorable = classification.startswith("UNSCORABLE_")
        return OpportunityAlert(
            alert_id=alert_id,
            symbol=symbol,
            timestamp=f"2026-06-19T07:0{len(alert_id)}:00-05:00",
            alert_type=alert_type,
            current_state=state,
            previous_state="PLANNING_SCAFFOLD",
            reason="test alert",
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
                status="COMPLETED" if completed else ("UNSCORABLE_OUTCOME" if unscorable else "PENDING_OUTCOME"),
                five_minute_return_pct=returns[0] if completed else None,
                fifteen_minute_return_pct=returns[1] if completed else None,
                thirty_minute_return_pct=returns[2] if completed else None,
                sixty_minute_return_pct=returns[3] if completed else None,
                mfe_15m_pct=mfe if completed else None,
                mae_15m_pct=mae if completed else None,
                mfe_30m_pct=mfe if completed else None,
                mae_30m_pct=mae if completed else None,
                mfe_60m_pct=mfe if completed else None,
                mae_60m_pct=mae if completed else None,
                target_1_hit=classification == "SUCCESSFUL" if completed else None,
                target_2_hit=False if completed else None,
                stop_hit=classification == "FAILED" if completed else None,
                stop_hit_before_target=classification == "FAILED" if completed else None,
                classification=classification,
                evaluation_notes=["test"],
            ),
        )


if __name__ == "__main__":
    unittest.main()
