from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.entry_plans import EntryPlan, save_entry_plans
from momentum_hunter.monitor_targets import (
    UserDefinedMonitorSymbol,
    build_monitor_target_report,
    export_monitor_target_report,
    load_user_defined_symbols,
    remove_user_defined_symbol,
    save_user_defined_symbols,
    upsert_user_defined_symbol,
)
from momentum_hunter.review import CandidateIdentity, ReviewDecision, ReviewStatus, save_review_decisions
from momentum_hunter.storage import file_sha256


class MonitorTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-monitor-targets-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.review_path = self.root / "review-decisions.json"
        self.entry_plan_path = self.root / "entry-plans.json"
        self.user_symbols_path = self.root / "opportunity-monitor-symbols.json"
        self.trade_report_path = self.root / "trade-plan.json"
        self.raw_capture = self.root / "morning.json"
        self.raw_capture.write_text(
            json.dumps({"capture_time": "2026-06-17T07:00:00-05:00", "candidates": []}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_builds_targets_from_review_plans_user_symbols_and_execution_ready(self) -> None:
        self.write_review_decisions(
            [
                ("AAA", ReviewStatus.WATCHLIST),
                ("BBB", ReviewStatus.INTERESTED),
                ("CCC", ReviewStatus.REJECTED),
            ]
        )
        self.write_entry_plans(["AAA"])
        save_user_defined_symbols(
            {
                "DDD": UserDefinedMonitorSymbol(symbol="DDD", notes="User radar", enabled=True),
                "ZZZ": UserDefinedMonitorSymbol(symbol="ZZZ", notes="Disabled", enabled=False),
            },
            self.user_symbols_path,
        )
        self.write_trade_report(
            [
                trade_candidate("EEE", "EXECUTION_READY_TRADE"),
                trade_candidate("BBB", "PLANNING_SCAFFOLD"),
            ]
        )

        report = self.build_report()
        by_symbol = {target.symbol: target for target in report.targets}

        self.assertEqual(["EEE", "AAA", "BBB", "DDD"], [target.symbol for target in report.targets])
        self.assertEqual(["watchlist", "entry_plan"], by_symbol["AAA"].sources)
        self.assertEqual("complete", by_symbol["AAA"].entry_plan_status)
        self.assertEqual(["interested"], by_symbol["BBB"].review_statuses)
        self.assertEqual("EXECUTION_READY_TRADE", by_symbol["EEE"].execution_state)
        self.assertNotIn("CCC", by_symbol)
        self.assertNotIn("ZZZ", by_symbol)

    def test_dedupes_symbol_sources_and_uses_highest_priority(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_entry_plans(["AAA"])
        save_user_defined_symbols({"AAA": UserDefinedMonitorSymbol(symbol="AAA", notes="Manual add")}, self.user_symbols_path)
        self.write_trade_report([trade_candidate("AAA", "EXECUTION_READY_PREMARKET")])

        report = self.build_report()

        self.assertEqual(1, len(report.targets))
        target = report.targets[0]
        self.assertEqual("AAA", target.symbol)
        self.assertEqual(100, target.priority)
        self.assertEqual(["execution_ready", "watchlist", "entry_plan", "user_defined"], target.sources)
        self.assertEqual("EXECUTION_READY_PREMARKET", target.execution_state)

    def test_include_flags_can_exclude_interested_and_execution_ready(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.INTERESTED), ("BBB", ReviewStatus.WATCHLIST)])
        self.write_trade_report([trade_candidate("CCC", "EXECUTION_READY_TRADE")])

        report = build_monitor_target_report(
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_plan_path,
            user_symbols_path=self.user_symbols_path,
            trade_report_path=self.trade_report_path,
            include_interested=False,
            include_execution_ready=False,
        )

        self.assertEqual(["BBB"], [target.symbol for target in report.targets])

    def test_user_symbol_store_round_trips(self) -> None:
        upsert_user_defined_symbol("sofi", notes="User-defined radar", path=self.user_symbols_path)

        loaded = load_user_defined_symbols(self.user_symbols_path)

        self.assertEqual(["SOFI"], list(loaded))
        self.assertEqual("User-defined radar", loaded["SOFI"].notes)
        self.assertTrue(loaded["SOFI"].enabled)

    def test_remove_user_symbol_updates_store(self) -> None:
        upsert_user_defined_symbol("sofi", notes="User-defined radar", path=self.user_symbols_path)
        upsert_user_defined_symbol("pltr", notes="Second radar", path=self.user_symbols_path)

        removed = remove_user_defined_symbol("SOFI", path=self.user_symbols_path)
        missing = remove_user_defined_symbol("MSFT", path=self.user_symbols_path)
        loaded = load_user_defined_symbols(self.user_symbols_path)

        self.assertTrue(removed)
        self.assertFalse(missing)
        self.assertEqual(["PLTR"], list(loaded))

    def test_exports_csv_json_and_markdown(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_trade_report([])
        report = self.build_report()

        paths = export_monitor_target_report(report, self.root / "reports")
        text = paths["report"].read_text(encoding="utf-8")
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))

        self.assertTrue(paths["csv"].exists())
        self.assertIn("Opportunity Monitor Targets", text)
        self.assertIn("AAA", text)
        self.assertEqual("AAA", payload["targets"][0]["symbol"])

    def test_report_generation_does_not_mutate_raw_capture(self) -> None:
        self.write_review_decisions([("AAA", ReviewStatus.WATCHLIST)])
        self.write_trade_report([trade_candidate("BBB", "EXECUTION_READY_TRADE")])
        before = file_sha256(self.raw_capture)

        self.build_report()

        self.assertEqual(before, file_sha256(self.raw_capture))

    def build_report(self):
        return build_monitor_target_report(
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_plan_path,
            user_symbols_path=self.user_symbols_path,
            trade_report_path=self.trade_report_path,
            generated_at=None,
        )

    def write_review_decisions(self, rows: list[tuple[str, ReviewStatus]]) -> None:
        decisions = {}
        for ticker, status in rows:
            identity = identity_for(ticker)
            decisions[identity.key] = ReviewDecision(identity=identity, review_status=status)
        save_review_decisions(decisions, self.review_path)

    def write_entry_plans(self, tickers: list[str]) -> None:
        plans = {}
        for ticker in tickers:
            identity = identity_for(ticker)
            plans[identity.key] = EntryPlan(
                identity=identity,
                trigger="breakout over high",
                stop="below VWAP",
                thesis="test thesis",
                invalidation="fails entry",
                max_loss="$20",
                plan_complete=True,
            )
        save_entry_plans(plans, self.entry_plan_path)

    def write_trade_report(self, candidates: list[dict]) -> None:
        self.trade_report_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "metadata": {
                        "generated_at": "2026-06-17T08:00:00-05:00",
                        "source_capture_path": str(self.raw_capture),
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


def trade_candidate(symbol: str, readiness: str) -> dict:
    return {
        "symbol": symbol,
        "trade_plan": {"readiness": readiness},
    }
