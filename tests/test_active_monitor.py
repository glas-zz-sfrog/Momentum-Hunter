from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.active_monitor import (
    MonitorCycleReport,
    load_active_monitor_status,
    run_monitor_cycle,
    run_monitor_loop,
)
from momentum_hunter.monitor_targets import UserDefinedMonitorSymbol, save_user_defined_symbols
from momentum_hunter.opportunity_alerts import load_alerts
from momentum_hunter.review import CandidateIdentity, ReviewDecision, ReviewStatus, save_review_decisions
from momentum_hunter.storage import file_sha256
from momentum_hunter.trade_planning import MarketTape


class ActiveMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-active-monitor-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.review_path = self.root / "review-decisions.json"
        self.entry_plan_path = self.root / "entry-plans.json"
        self.user_symbols_path = self.root / "opportunity-monitor-symbols.json"
        self.alerts_path = self.root / "opportunity-alerts.json"
        self.state_path = self.root / "opportunity-monitor-state.json"
        self.observations_path = self.root / "opportunity-price-observations.json"
        self.status_path = self.root / "active-monitor-status.json"
        self.trade_report_path = self.root / "trade-plan.json"
        self.raw_capture = self.root / "morning.json"
        self.raw_capture.write_text(
            json.dumps({"capture_time": "2026-06-17T07:00:00-05:00", "candidates": []}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cycle_filters_alerts_to_active_monitor_targets(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_trade_report(
            [
                trade_candidate("AAA", "EXECUTION_READY_TRADE", price=10.5),
                trade_candidate("BBB", "PLANNING_SCAFFOLD", price=20.5),
            ]
        )

        report = self.run_cycle()
        alerts = load_alerts(self.alerts_path)

        self.assertEqual(["AAA"], [alert.symbol for alert in alerts])
        self.assertEqual(1, report.target_count)
        self.assertEqual(1, report.matched_target_count)
        self.assertEqual(1, report.new_alert_count)
        self.assertEqual(1, report.active_alert_count)

    def test_cycle_reports_user_target_missing_from_trade_report(self) -> None:
        save_user_defined_symbols(
            {
                "ZZZ": UserDefinedMonitorSymbol(symbol="ZZZ", notes="manual radar", enabled=True),
            },
            self.user_symbols_path,
        )
        self.write_trade_report([trade_candidate("AAA", "PLANNING_SCAFFOLD", price=10.0)])

        report = self.run_cycle()

        self.assertEqual(["ZZZ"], report.target_symbols)
        self.assertEqual(["ZZZ"], report.missing_target_symbols)
        self.assertEqual(["ZZZ"], report.covered_missing_symbols)
        self.assertEqual([], report.uncovered_missing_symbols)
        self.assertEqual(1, report.coverage_row_count)
        self.assertIn("TARGETS_WITHOUT_SOURCE_TRADE_ROWS", report.warnings)
        self.assertIn("COVERAGE_ROWS_ADDED_FOR_MISSING_TARGETS", report.warnings)
        self.assertIn("COVERAGE_ROWS_WITHOUT_MARKET_DATA", report.warnings)

    def test_missing_target_with_market_tape_can_generate_price_expansion_alert(self) -> None:
        save_user_defined_symbols(
            {
                "ZZZ": UserDefinedMonitorSymbol(symbol="ZZZ", notes="manual radar", enabled=True),
            },
            self.user_symbols_path,
        )
        self.write_trade_report([])
        self.run_cycle(
            generated_at=datetime.fromisoformat("2026-06-17T10:00:00-05:00"),
            market_tape_by_symbol={"ZZZ": market_tape(price=10.0, volume=1_000_000)},
        )

        self.run_cycle(
            generated_at=datetime.fromisoformat("2026-06-17T10:04:00-05:00"),
            market_tape_by_symbol={"ZZZ": market_tape(price=10.22, volume=1_250_000)},
        )

        alert_types = {alert.alert_type for alert in load_alerts(self.alerts_path)}
        self.assertIn("PRICE_EXPANSION_1PCT_5M", alert_types)
        self.assertIn("PRICE_EXPANSION_2PCT_15M", alert_types)

    def test_refresh_target_market_data_updates_existing_target_rows_for_alerts(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_trade_report([trade_candidate("AAA", "PLANNING_SCAFFOLD", price=10.0)])
        before = file_sha256(self.raw_capture)
        self.run_cycle(generated_at=datetime.fromisoformat("2026-06-17T10:00:00-05:00"))

        report = self.run_cycle(
            generated_at=datetime.fromisoformat("2026-06-17T10:04:00-05:00"),
            refresh_target_market_data=True,
            market_tape_by_symbol={"AAA": market_tape(price=10.25, volume=1_400_000)},
        )

        self.assertEqual(1, report.refreshed_target_count)
        self.assertEqual(1, report.readiness_recalculated_count)
        self.assertEqual(1, report.readiness_changed_count)
        self.assertIn("TARGET_MARKET_DATA_REFRESHED", report.warnings)
        self.assertIn("TARGET_READINESS_RECALCULATED_FROM_REFRESHED_TAPE", report.warnings)
        self.assertTrue(report.market_data_refresh_report_path.endswith(".json"))
        refreshed = json.loads(Path(report.market_data_refresh_report_path).read_text(encoding="utf-8"))
        row = refreshed["candidates"][0]
        self.assertEqual(10.25, row["market_data"]["last_price"])
        self.assertEqual("test_tape", row["monitor_market_data_refresh"]["source"])
        self.assertEqual("PLANNING_SCAFFOLD", row["monitor_market_data_refresh"]["previous_readiness"])
        self.assertEqual("EXECUTION_READY_TRADE", row["monitor_market_data_refresh"]["recalculated_readiness"])
        self.assertEqual("EXECUTION_READY_TRADE", row["trade_plan"]["readiness"])
        self.assertIn("readiness was recalculated", refreshed["metadata"]["monitor_market_data_refresh_warning"])
        self.assertEqual(before, file_sha256(self.raw_capture))
        alert_types = {alert.alert_type for alert in load_alerts(self.alerts_path)}
        self.assertIn("STATE_PLANNING_SCAFFOLD_TO_EXECUTION_READY_TRADE", alert_types)
        self.assertIn("PRICE_EXPANSION_1PCT_5M", alert_types)
        self.assertIn("PRICE_EXPANSION_2PCT_15M", alert_types)

    def test_cycle_exports_reports(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_trade_report([trade_candidate("AAA", "EXECUTION_READY_PREMARKET", price=10.2)])

        report = self.run_cycle()
        cycle_reports = list((self.root / "reports").glob("active-monitor-cycle-*.md"))
        target_reports = list((self.root / "reports").glob("opportunity-monitor-targets-*.json"))
        alert_reports = list((self.root / "reports").glob("opportunity-alerts-*.json"))

        self.assertTrue(cycle_reports)
        self.assertTrue(target_reports)
        self.assertTrue(alert_reports)
        text = cycle_reports[0].read_text(encoding="utf-8")
        self.assertIn("Active Monitor Cycle", text)
        self.assertIn("AAA", text)
        self.assertEqual(1, report.new_alert_count)

    def test_cycle_does_not_mutate_raw_capture(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_trade_report([trade_candidate("AAA", "EXECUTION_READY_TRADE", price=10.5)])
        before = file_sha256(self.raw_capture)

        self.run_cycle()

        self.assertEqual(before, file_sha256(self.raw_capture))

    def test_one_shot_cycle_writes_fresh_status(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_trade_report([trade_candidate("AAA", "EXECUTION_READY_TRADE", price=10.5)])

        report = self.run_cycle(
            fetch_missing_market_data=True,
            refresh_target_market_data=True,
            market_tape_by_symbol={"AAA": market_tape(price=10.5, volume=1_000_000)},
        )
        status = load_active_monitor_status(self.status_path)

        self.assertIsNotNone(status)
        self.assertEqual("IDLE", status.state)
        self.assertEqual(1, status.cycles_requested)
        self.assertEqual(1, status.cycles_completed)
        self.assertEqual(0, status.interval_seconds)
        self.assertTrue(status.fetch_missing_market_data)
        self.assertTrue(status.refresh_target_market_data)
        self.assertEqual(report.generated_at, status.last_cycle_at)
        self.assertTrue(status.last_report_path.endswith(".json"))
        self.assertEqual(report.warnings, status.warnings)

    def test_monitor_loop_writes_idle_status_after_success(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_trade_report([trade_candidate("AAA", "EXECUTION_READY_TRADE", price=10.5)])
        status_path = self.root / "active-monitor-status.json"

        report = run_monitor_loop(
            cycles=1,
            interval_seconds=3,
            status_path=status_path,
            trade_report_path=self.trade_report_path,
            output_dir=self.root / "reports",
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_plan_path,
            user_symbols_path=self.user_symbols_path,
            alerts_path=self.alerts_path,
            state_path=self.state_path,
            observations_path=self.observations_path,
        )
        status = load_active_monitor_status(status_path)

        self.assertIsNotNone(report)
        self.assertIsNotNone(status)
        self.assertEqual("IDLE", status.state)
        self.assertEqual(1, status.cycles_completed)
        self.assertEqual(1, status.cycles_requested)
        self.assertTrue(status.last_report_path.endswith(".json"))
        self.assertFalse(status.last_error)

    def test_monitor_loop_runs_multiple_cycles_without_real_sleep(self) -> None:
        status_path = self.root / "active-monitor-status.json"
        sleep_calls = []

        run_monitor_loop(
            cycles=2,
            interval_seconds=7,
            status_path=status_path,
            sleep_fn=lambda seconds: sleep_calls.append(seconds),
            cycle_runner=lambda **kwargs: fake_cycle_report(),
        )
        status = load_active_monitor_status(status_path)

        self.assertEqual([7], sleep_calls)
        self.assertIsNotNone(status)
        self.assertEqual("IDLE", status.state)
        self.assertEqual(2, status.cycles_completed)
        self.assertEqual(2, status.cycles_requested)

    def test_monitor_loop_writes_failed_status_on_exception(self) -> None:
        status_path = self.root / "active-monitor-status.json"

        with self.assertRaises(RuntimeError):
            run_monitor_loop(
                cycles=1,
                interval_seconds=1,
                status_path=status_path,
                cycle_runner=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("provider down")),
            )
        status = load_active_monitor_status(status_path)

        self.assertIsNotNone(status)
        self.assertEqual("FAILED", status.state)
        self.assertEqual(0, status.cycles_completed)
        self.assertIn("provider down", status.last_error)

    def run_cycle(self, **kwargs):
        return run_monitor_cycle(
            trade_report_path=self.trade_report_path,
            output_dir=self.root / "reports",
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_plan_path,
            user_symbols_path=self.user_symbols_path,
            alerts_path=self.alerts_path,
            state_path=self.state_path,
            observations_path=self.observations_path,
            status_path=self.status_path,
            **kwargs,
        )

    def write_review_decisions(self, rows: list[tuple[str, ReviewStatus]]) -> None:
        decisions = {}
        for ticker, status in rows:
            identity = identity_for(ticker)
            decisions[identity.key] = ReviewDecision(identity=identity, review_status=status)
        save_review_decisions(decisions, self.review_path)

    def write_trade_report(self, candidates: list[dict]) -> None:
        self.trade_report_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "metadata": {
                        "generated_at": "2026-06-17T10:00:00-05:00",
                        "source_capture_path": str(self.raw_capture),
                        "event_mode": True,
                        "market_regime": "bull",
                    },
                    "candidates": candidates,
                }
            ),
            encoding="utf-8",
        )


def identity_for(ticker: str) -> CandidateIdentity:
    return CandidateIdentity(
        capture_id="2026-06-17|morning|finviz|Basic Momentum",
        capture_date="2026-06-17",
        session="morning",
        provider="finviz",
        scanner="Basic Momentum",
        ticker=ticker,
    )


def trade_candidate(symbol: str, readiness: str, *, price: float) -> dict:
    return {
        "symbol": symbol,
        "market_data": {
            "last_price": price,
            "current_bid": price - 0.01,
            "current_ask": price + 0.01,
            "spread_percent": 0.1,
            "intraday_volume": 2_000_000,
            "premarket_volume": 800_000,
            "premarket_percent": 2.0,
            "relative_volume": 1.5,
            "rvol_type": "INTRADAY_RVOL",
        },
        "technical_levels": {
            "previous_day_high": price - 0.2,
            "support_level": price - 0.5,
        },
        "trade_plan": {
            "readiness": readiness,
            "bullish_entry": price - 0.1,
            "bullish_stop": price - 0.4,
            "bullish_target_1": price + 0.6,
            "bullish_target_2": price + 1.2,
        },
        "scoring": {
            "catalyst_summary": "test catalyst",
        },
    }


def market_tape(*, price: float, volume: int) -> MarketTape:
    return MarketTape(
        last_price=price,
        intraday_volume=volume,
        average_daily_volume_20=1_000_000,
        current_bid=price - 0.01,
        current_ask=price + 0.01,
        spread_percent=0.1,
        source="test_tape",
    )


def fake_cycle_report() -> MonitorCycleReport:
    return MonitorCycleReport(
        generated_at="2026-06-17T10:00:00-05:00",
        trade_report_path="fake-trade-report.json",
        target_symbols=["AAA"],
        target_count=1,
        trade_report_symbol_count=1,
        matched_target_count=1,
        missing_target_symbols=[],
        new_alert_count=0,
        active_alert_count=0,
        tracked_alert_count=0,
        state_transition_count=0,
        coverage_row_count=0,
        covered_missing_symbols=[],
        uncovered_missing_symbols=[],
        coverage_report_path="",
        target_report_paths={},
        alert_report_paths={},
        warnings=[],
    )
