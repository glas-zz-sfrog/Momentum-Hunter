from __future__ import annotations

import json
import shutil
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from momentum_hunter.alert_outcome_updater import (
    MinutePriceBar,
    load_update_report,
    load_minute_bars,
    update_alert_store_from_minute_bars,
)
from momentum_hunter.opportunity_alerts import AlertOutcome, OpportunityAlert, load_alerts, save_alerts
from momentum_hunter.storage import file_sha256


class AlertOutcomeUpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-alert-outcome-updater-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.root / "opportunity-alerts.json"
        self.minute_bars_path = self.root / "opportunity-minute-bars.json"
        self.status_path = self.root / "alert-outcome-update-status.json"
        self.raw_capture = self.root / "morning.json"
        self.raw_capture.write_text(json.dumps({"capture_time": "2026-06-17T07:00:00-05:00"}), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_updates_completed_alert_outcome_from_minute_bars(self) -> None:
        save_alerts([alert_for("AAA")], self.alerts_path)
        before = file_sha256(self.raw_capture)

        report = update_alert_store_from_minute_bars(
            alerts_path=self.alerts_path,
            minute_bars_path=self.minute_bars_path,
            bars_by_symbol={"AAA": success_bars("AAA")},
            status_path=self.status_path,
        )
        loaded_report = load_update_report(self.status_path)

        updated = load_alerts(self.alerts_path)[0]
        self.assertEqual(1, report.updated_alert_count)
        self.assertEqual(1, report.completed_alert_count)
        self.assertEqual("COMPLETED", updated.outcome.status)
        self.assertEqual("SUCCESSFUL", updated.outcome.classification)
        self.assertEqual(5.0, updated.outcome.five_minute_return_pct)
        self.assertEqual(8.0, updated.outcome.fifteen_minute_return_pct)
        self.assertEqual(10.0, updated.outcome.thirty_minute_return_pct)
        self.assertEqual(11.0, updated.outcome.sixty_minute_return_pct)
        self.assertEqual(12.0, updated.outcome.mfe_30m_pct)
        self.assertEqual(-2.0, updated.outcome.mae_30m_pct)
        self.assertTrue(updated.outcome.target_1_hit)
        self.assertFalse(updated.outcome.target_2_hit)
        self.assertFalse(updated.outcome.stop_hit)
        self.assertFalse(updated.outcome.stop_hit_before_target)
        self.assertIn("Minute-bar outcome updater v1.", updated.outcome.evaluation_notes)
        self.assertEqual(before, file_sha256(self.raw_capture))
        self.assertEqual(4, len(load_minute_bars(self.minute_bars_path)["AAA"]))
        self.assertIsNotNone(loaded_report)
        self.assertEqual(1, loaded_report.completed_alert_count)

    def test_stop_before_target_is_failed_from_minute_bar_sequence(self) -> None:
        save_alerts([alert_for("AAA")], self.alerts_path)

        update_alert_store_from_minute_bars(
            alerts_path=self.alerts_path,
            minute_bars_path=self.minute_bars_path,
            bars_by_symbol={"AAA": stop_before_target_bars("AAA")},
        )

        updated = load_alerts(self.alerts_path)[0]
        self.assertEqual("COMPLETED", updated.outcome.status)
        self.assertEqual("FAILED", updated.outcome.classification)
        self.assertTrue(updated.outcome.stop_hit)
        self.assertTrue(updated.outcome.target_1_hit)
        self.assertTrue(updated.outcome.stop_hit_before_target)

    def test_completed_alert_is_not_overwritten_by_default(self) -> None:
        completed = replace(
            alert_for("AAA"),
            outcome=AlertOutcome(status="COMPLETED", classification="SUCCESSFUL", sixty_minute_return_pct=9.9),
        )
        save_alerts([completed], self.alerts_path)

        update_alert_store_from_minute_bars(
            alerts_path=self.alerts_path,
            minute_bars_path=self.minute_bars_path,
            bars_by_symbol={"AAA": stop_before_target_bars("AAA")},
        )

        updated = load_alerts(self.alerts_path)[0]
        self.assertEqual("SUCCESSFUL", updated.outcome.classification)
        self.assertEqual(9.9, updated.outcome.sixty_minute_return_pct)

    def test_missing_alert_price_becomes_unscorable_not_pending(self) -> None:
        broken = replace(alert_for("AAA"), price=None)
        save_alerts([broken], self.alerts_path)
        before = file_sha256(self.raw_capture)

        report = update_alert_store_from_minute_bars(
            alerts_path=self.alerts_path,
            minute_bars_path=self.minute_bars_path,
            bars_by_symbol={"AAA": success_bars("AAA")},
            status_path=self.status_path,
        )

        updated = load_alerts(self.alerts_path)[0]
        self.assertEqual("UNSCORABLE_OUTCOME", updated.outcome.status)
        self.assertEqual("UNSCORABLE_MISSING_ENTRY_PRICE", updated.outcome.classification)
        self.assertEqual(0, report.pending_alert_count)
        self.assertEqual(1, report.unscorable_alert_count)
        self.assertEqual(before, file_sha256(self.raw_capture))

    def test_invalid_alert_timestamp_becomes_unscorable(self) -> None:
        broken = replace(alert_for("AAA"), timestamp="not-a-date")
        save_alerts([broken], self.alerts_path)

        report = update_alert_store_from_minute_bars(
            alerts_path=self.alerts_path,
            minute_bars_path=self.minute_bars_path,
            bars_by_symbol={"AAA": success_bars("AAA")},
        )

        updated = load_alerts(self.alerts_path)[0]
        self.assertEqual("UNSCORABLE_OUTCOME", updated.outcome.status)
        self.assertEqual("UNSCORABLE_INVALID_TIMESTAMP", updated.outcome.classification)
        self.assertEqual(0, report.pending_alert_count)
        self.assertEqual(1, report.unscorable_alert_count)

    def test_missing_minute_bars_remains_pending_when_alert_is_scorable(self) -> None:
        save_alerts([alert_for("AAA")], self.alerts_path)

        report = update_alert_store_from_minute_bars(
            alerts_path=self.alerts_path,
            minute_bars_path=self.minute_bars_path,
            bars_by_symbol={},
        )

        updated = load_alerts(self.alerts_path)[0]
        self.assertEqual("PENDING_OUTCOME", updated.outcome.status)
        self.assertEqual("PENDING", updated.outcome.classification)
        self.assertEqual(1, report.pending_alert_count)
        self.assertEqual(0, report.unscorable_alert_count)


def alert_for(symbol: str) -> OpportunityAlert:
    return OpportunityAlert(
        alert_id=f"{symbol}-alert",
        symbol=symbol,
        timestamp="2026-06-17T10:00:00-05:00",
        alert_type="STATE_PLANNING_SCAFFOLD_TO_EXECUTION_READY_TRADE",
        current_state="EXECUTION_READY_TRADE",
        previous_state="PLANNING_SCAFFOLD",
        reason="state changed",
        price=10.0,
        bid=9.99,
        ask=10.01,
        spread_percent=0.1,
        volume=1_000_000,
        premarket_volume=500_000,
        premarket_percent=2.0,
        rvol=1.3,
        rvol_type="INTRADAY_RVOL",
        suggested_entry=10.0,
        stop=9.5,
        target_1=10.8,
        target_2=11.5,
        news_catalyst="test catalyst",
        market_regime="bull",
        event_mode=False,
        source_report="test-report.json",
    )


def success_bars(symbol: str) -> list[MinutePriceBar]:
    return [
        bar(symbol, "2026-06-17T10:05:00-05:00", high=10.6, low=10.1, close=10.5),
        bar(symbol, "2026-06-17T10:15:00-05:00", high=10.85, low=10.2, close=10.8),
        bar(symbol, "2026-06-17T10:30:00-05:00", high=11.2, low=9.8, close=11.0),
        bar(symbol, "2026-06-17T11:00:00-05:00", high=11.1, low=10.9, close=11.1),
    ]


def stop_before_target_bars(symbol: str) -> list[MinutePriceBar]:
    return [
        bar(symbol, "2026-06-17T10:01:00-05:00", high=10.2, low=9.4, close=9.6),
        bar(symbol, "2026-06-17T10:15:00-05:00", high=10.9, low=9.9, close=10.6),
        bar(symbol, "2026-06-17T10:30:00-05:00", high=10.7, low=10.1, close=10.4),
        bar(symbol, "2026-06-17T11:00:00-05:00", high=10.6, low=10.2, close=10.3),
    ]


def bar(symbol: str, timestamp: str, *, high: float, low: float, close: float) -> MinutePriceBar:
    return MinutePriceBar(
        symbol=symbol,
        timestamp=timestamp,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=10_000,
        source="test_1m",
    )
