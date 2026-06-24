from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.opportunity_alerts import (
    AlertOutcome,
    OpportunityAlert,
    calculate_alert_outcome,
    build_opportunity_alert_report,
    export_opportunity_alert_report,
    load_alerts,
    load_price_observations,
)
from momentum_hunter.storage import file_sha256


class OpportunityAlertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-opportunity-alerts-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.root / "opportunity-alerts.json"
        self.state_path = self.root / "opportunity-monitor-state.json"
        self.observations_path = self.root / "opportunity-price-observations.json"
        self.raw_capture = self.root / "morning.json"
        self.raw_capture.write_text(json.dumps({"capture_time": "2026-06-17T07:00:00-05:00", "candidates": []}), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_detects_state_rvol_breakout_and_price_expansion_alerts(self) -> None:
        first_report = self.write_trade_report(
            "report-1.json",
            generated_at="2026-06-17T13:00:00-05:00",
            candidate=trade_candidate(
                state="PLANNING_SCAFFOLD",
                price=10.00,
                rvol=0.40,
                entry=10.50,
                previous_day_high=10.50,
            ),
        )
        first = self.build_report(first_report)
        self.assertEqual([], first.new_alerts)

        second_report = self.write_trade_report(
            "report-2.json",
            generated_at="2026-06-17T13:04:00-05:00",
            candidate=trade_candidate(
                state="EXECUTION_READY_TRADE",
                price=10.60,
                rvol=1.30,
                entry=10.50,
                previous_day_high=10.50,
            ),
        )
        second = self.build_report(second_report)
        alert_types = {alert.alert_type for alert in second.new_alerts}

        self.assertIn("STATE_PLANNING_SCAFFOLD_TO_EXECUTION_READY_TRADE", alert_types)
        self.assertIn("RVOL_CROSS_0_5", alert_types)
        self.assertIn("RVOL_CROSS_1_0", alert_types)
        self.assertIn("RVOL_CROSS_1_2", alert_types)
        self.assertIn("BREAKOUT_PREVIOUS_DAY_HIGH", alert_types)
        self.assertIn("BREAKOUT_PLANNED_ENTRY", alert_types)
        self.assertIn("PRICE_EXPANSION_1PCT_5M", alert_types)
        self.assertIn("PRICE_EXPANSION_2PCT_15M", alert_types)
        self.assertTrue(all(alert.outcome.classification == "PENDING" for alert in second.new_alerts))

    def test_rerun_does_not_duplicate_persisted_alerts(self) -> None:
        first_report = self.write_trade_report(
            "report-1.json",
            generated_at="2026-06-17T13:00:00-05:00",
            candidate=trade_candidate(state="PLANNING_SCAFFOLD", price=10.0, rvol=0.4),
        )
        self.build_report(first_report)
        second_report = self.write_trade_report(
            "report-2.json",
            generated_at="2026-06-17T13:04:00-05:00",
            candidate=trade_candidate(state="EXECUTION_READY_TRADE", price=10.6, rvol=1.3),
        )
        self.build_report(second_report)
        first_count = len(load_alerts(self.alerts_path))

        self.build_report(second_report)

        self.assertEqual(first_count, len(load_alerts(self.alerts_path)))

    def test_alert_generation_does_not_mutate_raw_capture(self) -> None:
        before = file_sha256(self.raw_capture)
        trade_report = self.write_trade_report(
            "report.json",
            generated_at="2026-06-17T13:00:00-05:00",
            candidate=trade_candidate(state="EXECUTION_READY_PREMARKET", price=10.4, rvol=0.8),
        )

        self.build_report(trade_report)

        self.assertEqual(before, file_sha256(self.raw_capture))

    def test_detects_breaking_news_when_new_catalyst_appears(self) -> None:
        self.build_report(
            self.write_trade_report(
                "baseline.json",
                generated_at="2026-06-17T13:00:00-05:00",
                candidate=trade_candidate(state="PLANNING_SCAFFOLD", price=10.0, rvol=0.4, catalyst=""),
            )
        )

        report = self.build_report(
            self.write_trade_report(
                "news.json",
                generated_at="2026-06-17T13:03:00-05:00",
                candidate=trade_candidate(
                    state="PLANNING_SCAFFOLD",
                    price=10.0,
                    rvol=0.4,
                    catalyst="Company announces FDA approval",
                ),
            )
        )

        news_alert = next(alert for alert in report.new_alerts if alert.alert_type == "BREAKING_NEWS_CATALYST")
        self.assertEqual("Company announces FDA approval", news_alert.news_catalyst)
        self.assertIn("New catalyst appeared", news_alert.reason)

    def test_detects_breaking_news_when_catalyst_changes(self) -> None:
        self.build_report(
            self.write_trade_report(
                "baseline.json",
                generated_at="2026-06-17T13:00:00-05:00",
                candidate=trade_candidate(
                    state="PLANNING_SCAFFOLD",
                    price=10.0,
                    rvol=0.4,
                    catalyst="Analyst reiterates target",
                ),
            )
        )

        report = self.build_report(
            self.write_trade_report(
                "news.json",
                generated_at="2026-06-17T13:02:00-05:00",
                candidate=trade_candidate(
                    state="PLANNING_SCAFFOLD",
                    price=10.0,
                    rvol=0.4,
                    catalyst="Analyst upgrades stock after contract win",
                ),
            )
        )

        alert_types = {alert.alert_type for alert in report.new_alerts}
        self.assertIn("BREAKING_NEWS_CATALYST", alert_types)

    def test_unchanged_catalyst_does_not_create_news_alert(self) -> None:
        self.build_report(
            self.write_trade_report(
                "baseline.json",
                generated_at="2026-06-17T13:00:00-05:00",
                candidate=trade_candidate(
                    state="PLANNING_SCAFFOLD",
                    price=10.0,
                    rvol=0.4,
                    catalyst="Guidance raised after earnings beat",
                ),
            )
        )

        report = self.build_report(
            self.write_trade_report(
                "same.json",
                generated_at="2026-06-17T13:02:00-05:00",
                candidate=trade_candidate(
                    state="PLANNING_SCAFFOLD",
                    price=10.0,
                    rvol=0.4,
                    catalyst="Guidance raised after earnings beat",
                ),
            )
        )

        self.assertNotIn("BREAKING_NEWS_CATALYST", {alert.alert_type for alert in report.new_alerts})

    def test_export_report_has_active_alerts_and_pending_leaderboard_message(self) -> None:
        trade_report = self.write_trade_report(
            "report.json",
            generated_at="2026-06-17T13:00:00-05:00",
            candidate=trade_candidate(state="EXECUTION_READY_PREMARKET", price=10.4, rvol=0.8),
        )
        report = self.build_report(trade_report)
        paths = export_opportunity_alert_report(report, self.root / "reports")
        text = paths["report"].read_text(encoding="utf-8")

        self.assertTrue(paths["csv"].exists())
        self.assertTrue(paths["json"].exists())
        self.assertIn("Active Alerts", text)
        self.assertIn("Alert Outcome Tracker", text)
        self.assertIn("INITIAL_EXECUTION_READY", text)
        self.assertIn("No completed alert outcomes yet", text)

    def test_updates_alert_outcome_after_observation_window_matures(self) -> None:
        self.build_report(
            self.write_trade_report(
                "baseline.json",
                generated_at="2026-06-17T13:00:00-05:00",
                candidate=trade_candidate(state="PLANNING_SCAFFOLD", price=10.00, rvol=0.4),
            )
        )
        self.build_report(
            self.write_trade_report(
                "alert.json",
                generated_at="2026-06-17T13:04:00-05:00",
                candidate=trade_candidate(state="EXECUTION_READY_TRADE", price=10.60, rvol=1.3, entry=10.5),
            )
        )
        for minute, price in [(9, 10.85), (19, 11.0), (34, 11.95), (64, 12.05)]:
            final_report = self.build_report(
                self.write_trade_report(
                    f"obs-{minute}.json",
                    generated_at=f"2026-06-17T13:{minute:02d}:00-05:00" if minute < 60 else "2026-06-17T14:04:00-05:00",
                    candidate=trade_candidate(state="EXECUTION_READY_TRADE", price=price, rvol=1.4, entry=10.5),
                )
            )

        alerts = load_alerts(self.alerts_path)
        state_alert = next(alert for alert in alerts if alert.alert_type == "STATE_PLANNING_SCAFFOLD_TO_EXECUTION_READY_TRADE")
        observations = load_price_observations(self.observations_path)

        self.assertGreaterEqual(len(observations), 5)
        self.assertEqual("COMPLETED", state_alert.outcome.status)
        self.assertEqual("SUCCESSFUL", state_alert.outcome.classification)
        self.assertEqual(2.36, state_alert.outcome.five_minute_return_pct)
        self.assertEqual(3.77, state_alert.outcome.fifteen_minute_return_pct)
        self.assertEqual(12.74, state_alert.outcome.thirty_minute_return_pct)
        self.assertEqual(13.68, state_alert.outcome.sixty_minute_return_pct)
        self.assertTrue(state_alert.outcome.target_1_hit)
        self.assertFalse(state_alert.outcome.stop_hit)
        alert_type_summary = next(row for row in final_report.alert_type_performance if row.group == "STATE_PLANNING_SCAFFOLD_TO_EXECUTION_READY_TRADE")
        symbol_summary = next(row for row in final_report.symbol_performance if row.group == "AAA")
        readiness_summary = next(row for row in final_report.readiness_state_performance if row.group == "EXECUTION_READY_TRADE")
        regime_summary = next(row for row in final_report.market_regime_performance if row.group == "bull")

        self.assertEqual(100.0, alert_type_summary.win_rate_pct)
        self.assertEqual(100.0, alert_type_summary.target_1_hit_rate_pct)
        self.assertEqual(0.0, alert_type_summary.stop_hit_rate_pct)
        self.assertGreaterEqual(symbol_summary.completed_count, 1)
        self.assertGreaterEqual(readiness_summary.completed_count, 1)
        self.assertGreaterEqual(regime_summary.completed_count, 1)

    def test_classifies_stop_before_target_as_failed(self) -> None:
        self.build_report(
            self.write_trade_report(
                "baseline.json",
                generated_at="2026-06-17T13:00:00-05:00",
                candidate=trade_candidate(state="PLANNING_SCAFFOLD", price=10.00, rvol=0.4),
            )
        )
        self.build_report(
            self.write_trade_report(
                "alert.json",
                generated_at="2026-06-17T13:04:00-05:00",
                candidate=trade_candidate(state="EXECUTION_READY_TRADE", price=10.60, rvol=1.3, entry=10.5),
            )
        )
        self.build_report(
            self.write_trade_report(
                "stop.json",
                generated_at="2026-06-17T13:08:00-05:00",
                candidate=trade_candidate(state="PLANNING_SCAFFOLD", price=9.75, rvol=0.6, entry=10.5),
            )
        )
        final_report = self.build_report(
            self.write_trade_report(
                "done.json",
                generated_at="2026-06-17T14:05:00-05:00",
                candidate=trade_candidate(state="PLANNING_SCAFFOLD", price=9.9, rvol=0.5, entry=10.5),
            )
        )

        state_alert = next(alert for alert in load_alerts(self.alerts_path) if alert.alert_type == "STATE_PLANNING_SCAFFOLD_TO_EXECUTION_READY_TRADE")

        self.assertEqual("COMPLETED", state_alert.outcome.status)
        self.assertEqual("FAILED", state_alert.outcome.classification)
        self.assertTrue(state_alert.outcome.stop_hit)
        self.assertTrue(state_alert.outcome.stop_hit_before_target)
        alert_type_summary = next(row for row in final_report.alert_type_performance if row.group == "STATE_PLANNING_SCAFFOLD_TO_EXECUTION_READY_TRADE")
        self.assertEqual(0.0, alert_type_summary.win_rate_pct)
        self.assertEqual(100.0, alert_type_summary.stop_hit_rate_pct)

    def test_export_report_includes_learning_sections(self) -> None:
        self.build_report(
            self.write_trade_report(
                "baseline.json",
                generated_at="2026-06-17T13:00:00-05:00",
                candidate=trade_candidate(state="PLANNING_SCAFFOLD", price=10.00, rvol=0.4),
            )
        )
        for generated_at, price, state, rvol in [
            ("2026-06-17T13:04:00-05:00", 10.60, "EXECUTION_READY_TRADE", 1.3),
            ("2026-06-17T14:04:00-05:00", 12.05, "EXECUTION_READY_TRADE", 1.4),
        ]:
            report = self.build_report(
                self.write_trade_report(
                    f"{generated_at}.json".replace(":", ""),
                    generated_at=generated_at,
                    candidate=trade_candidate(state=state, price=price, rvol=rvol),
                )
            )
        paths = export_opportunity_alert_report(report, self.root / "reports-learning")
        text = paths["report"].read_text(encoding="utf-8")
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))

        self.assertIn("Alert Type Performance", text)
        self.assertIn("Symbol Performance", text)
        self.assertIn("Readiness State Performance", text)
        self.assertIn("Market Regime Performance", text)
        self.assertIn("alert_type_performance", payload)
        self.assertIn("symbol_performance", payload)
        self.assertIn("readiness_state_performance", payload)
        self.assertIn("market_regime_performance", payload)

    def test_observation_outcome_missing_price_becomes_unscorable(self) -> None:
        alert = alert_for_outcome(price=None)

        outcome = calculate_alert_outcome(alert, [])

        self.assertEqual("UNSCORABLE_OUTCOME", outcome.status)
        self.assertEqual("UNSCORABLE_MISSING_ENTRY_PRICE", outcome.classification)

    def test_observation_outcome_invalid_timestamp_becomes_unscorable(self) -> None:
        alert = alert_for_outcome(timestamp="bad-time")

        outcome = calculate_alert_outcome(alert, [])

        self.assertEqual("UNSCORABLE_OUTCOME", outcome.status)
        self.assertEqual("UNSCORABLE_INVALID_TIMESTAMP", outcome.classification)

    def test_observation_outcome_without_future_observations_stays_pending(self) -> None:
        alert = alert_for_outcome()

        outcome = calculate_alert_outcome(alert, [])

        self.assertEqual("PENDING_OUTCOME", outcome.status)
        self.assertEqual("PENDING", outcome.classification)

    def build_report(self, path: Path):
        return build_opportunity_alert_report(
            path,
            alerts_path=self.alerts_path,
            state_path=self.state_path,
            observations_path=self.observations_path,
        )

    def write_trade_report(self, name: str, *, generated_at: str, candidate: dict) -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "metadata": {
                        "generated_at": generated_at,
                        "source_capture_path": str(self.raw_capture),
                        "source_capture_time": "2026-06-17T07:00:00-05:00",
                        "event_mode": True,
                        "market_regime": "bull",
                    },
                    "candidates": [candidate],
                }
            ),
            encoding="utf-8",
        )
        return path


def trade_candidate(
    *,
    state: str,
    price: float,
    rvol: float,
    entry: float = 10.5,
    previous_day_high: float = 10.5,
    catalyst: str = "AAA alert catalyst",
) -> dict:
    return {
        "symbol": "AAA",
        "market_data": {
            "last_price": price,
            "current_bid": price - 0.01,
            "current_ask": price + 0.01,
            "spread_percent": 0.19,
            "intraday_volume": 1_300_000,
            "premarket_volume": 600_000,
            "premarket_percent": 2.5,
            "relative_volume": rvol,
            "rvol_type": "INTRADAY_RVOL",
        },
        "technical_levels": {
            "previous_day_high": previous_day_high,
            "support_level": 9.8,
        },
        "trade_plan": {
            "readiness": state,
            "bullish_entry": entry,
            "bullish_stop": 9.8,
            "bullish_target_1": 11.9,
            "bullish_target_2": 12.6,
        },
        "scoring": {
            "catalyst_summary": catalyst,
        },
    }


def alert_for_outcome(*, price: float | None = 10.0, timestamp: str = "2026-06-17T13:00:00-05:00") -> OpportunityAlert:
    return OpportunityAlert(
        alert_id="outcome-alert",
        symbol="AAA",
        timestamp=timestamp,
        alert_type="BREAKOUT_PLANNED_ENTRY",
        current_state="EXECUTION_READY_TRADE",
        previous_state="PLANNING_SCAFFOLD",
        reason="test",
        price=price,
        bid=9.99 if price else None,
        ask=10.01 if price else None,
        spread_percent=0.2 if price else None,
        volume=1_000_000 if price else None,
        premarket_volume=500_000 if price else None,
        premarket_percent=2.0 if price else None,
        rvol=1.4 if price else None,
        rvol_type="INTRADAY_RVOL",
        suggested_entry=10.0,
        stop=9.5,
        target_1=11.0,
        target_2=12.0,
        news_catalyst="test catalyst",
        market_regime="bull",
        event_mode=False,
        source_report="test-report.json",
        outcome=AlertOutcome(),
    )


if __name__ == "__main__":
    unittest.main()
