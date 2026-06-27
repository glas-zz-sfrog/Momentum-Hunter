from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.evidence_analytics_maturity import (
    build_evidence_analytics_maturity_report,
    write_evidence_analytics_maturity_report,
)
from momentum_hunter.opportunity_alerts import AlertOutcome, OpportunityAlert, save_alerts


class EvidenceAnalyticsMaturityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-evidence-analytics-maturity-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.root / "opportunity-alerts.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_small_sample_keeps_strategy_changes_locked(self) -> None:
        save_alerts(
            [
                alert("a1", classification="SUCCESSFUL"),
                alert("a2", classification="PENDING"),
                alert("a3", classification="UNSCORABLE_MISSING_ENTRY_PRICE"),
            ],
            self.alerts_path,
        )

        report = build_evidence_analytics_maturity_report(
            alerts_path=self.alerts_path,
            generated_at="2026-06-27T07:00:00-05:00",
        )

        self.assertEqual(1, report["completed_alerts"])
        self.assertEqual(1, report["pending_alerts"])
        self.assertEqual(1, report["unscorable_alerts"])
        self.assertEqual("COLLECTING_ONLY", report["sample_confidence"])
        self.assertEqual("LOCKED", report["strategy_optimization_status"])
        self.assertFalse(report["strategy_change_recommendations_allowed"])
        self.assertIn("INSUFFICIENT_COMPLETED_ALERTS_FOR_PATTERN_REVIEW", report["warnings"])

    def test_group_maturity_marks_sufficient_group_samples(self) -> None:
        save_alerts(
            [alert(f"a{index}", classification="SUCCESSFUL", symbol="AAA", alert_type="BREAKOUT") for index in range(10)],
            self.alerts_path,
        )

        report = build_evidence_analytics_maturity_report(
            alerts_path=self.alerts_path,
            generated_at="2026-06-27T07:00:00-05:00",
        )
        breakout = next(row for row in report["alert_type_maturity"] if row["group"] == "BREAKOUT")
        symbol = next(row for row in report["symbol_maturity"] if row["group"] == "AAA")

        self.assertEqual("SUFFICIENT_FOR_PATTERN_REVIEW", breakout["sample_status"])
        self.assertEqual("SUFFICIENT_FOR_PATTERN_REVIEW", symbol["sample_status"])
        self.assertEqual(0, breakout["completed_needed"])

    def test_writer_creates_latest_json_and_markdown(self) -> None:
        save_alerts([alert("a1", classification="SUCCESSFUL")], self.alerts_path)
        payload = build_evidence_analytics_maturity_report(alerts_path=self.alerts_path)

        paths = write_evidence_analytics_maturity_report(
            payload,
            json_path=self.root / "reports" / "evidence-analytics-maturity-latest.json",
            markdown_path=self.root / "reports" / "evidence-analytics-maturity-latest.md",
        )

        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())
        loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
        self.assertEqual("evidence_analytics_maturity_v1", loaded["engine_version"])
        self.assertIn("Evidence Analytics Maturity v1", paths["markdown"].read_text(encoding="utf-8"))


def alert(
    alert_id: str,
    *,
    classification: str,
    symbol: str = "AAA",
    alert_type: str = "BREAKOUT",
    state: str = "PLANNING_SCAFFOLD",
) -> OpportunityAlert:
    completed = classification in {"SUCCESSFUL", "FAILED", "NOISE", "LATE"}
    unscorable = classification.startswith("UNSCORABLE_")
    return OpportunityAlert(
        alert_id=alert_id,
        symbol=symbol,
        timestamp=f"2026-06-27T07:{len(alert_id):02d}:00-05:00",
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
            five_minute_return_pct=1.0 if completed else None,
            fifteen_minute_return_pct=1.5 if completed else None,
            thirty_minute_return_pct=2.0 if completed else None,
            sixty_minute_return_pct=2.5 if completed else None,
            mfe_15m_pct=3.0 if completed else None,
            mae_15m_pct=-0.5 if completed else None,
            mfe_30m_pct=3.0 if completed else None,
            mae_30m_pct=-0.5 if completed else None,
            mfe_60m_pct=3.0 if completed else None,
            mae_60m_pct=-0.5 if completed else None,
            target_1_hit=True if completed else None,
            target_2_hit=False if completed else None,
            stop_hit=False if completed else None,
            stop_hit_before_target=False if completed else None,
            classification=classification,
            evaluation_notes=["test"],
        ),
    )


if __name__ == "__main__":
    unittest.main()
