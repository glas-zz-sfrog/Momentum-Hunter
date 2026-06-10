from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.entry_plans import (
    EntryPlan,
    entry_plan_warnings,
    load_entry_plans,
    upsert_entry_plan,
)
from momentum_hunter.market import MarketRegimeSnapshot
from momentum_hunter.models import CaptureSession, MarketRegime, ScannerCriteria, TradingMode
from momentum_hunter.review import CandidateIdentity, ReviewStatus, make_capture_id
from momentum_hunter.storage import file_sha256, save_daily_capture, save_watchlist_report
from momentum_hunter.time_utils import CENTRAL_TZ, now_central
from momentum_hunter.ui.data_view_state import DataViewState
from tests.test_review_workflow import candidate_payload, make_candidate


class EntryPlanPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path.cwd() / "MomentumHunterData" / "data" / "_test-entry-plans.json"
        if self.path.exists():
            self.path.unlink()
        self.identity = CandidateIdentity(
            capture_id=make_capture_id("2026-06-05", "live", "finviz", "Base Momentum"),
            capture_date="2026-06-05",
            session="live",
            provider="finviz",
            scanner="Base Momentum",
            ticker="MDT",
        )

    def tearDown(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def test_entry_plan_persists_and_computes_complete_status(self) -> None:
        plans = {}
        upsert_entry_plan(
            plans,
            self.identity,
            trigger="break over 105",
            stop="99.50",
            thesis="earnings continuation",
            invalidation="fails breakout and loses VWAP",
            max_loss="$25",
            position_size="25 shares",
            planned_hold_time="1-3 days",
            notes="Only take if volume confirms.",
            plan_complete=True,
            updated_at=datetime(2026, 6, 5, 7, 30, tzinfo=CENTRAL_TZ),
            path=self.path,
        )

        loaded = load_entry_plans(self.path)
        plan = loaded[self.identity.key]

        self.assertEqual("break over 105", plan.trigger)
        self.assertEqual("99.50", plan.stop)
        self.assertTrue(plan.plan_complete)
        self.assertEqual([], plan.warnings)

    def test_incomplete_plan_shows_warnings_and_cannot_be_marked_complete(self) -> None:
        plans = {}
        plan = upsert_entry_plan(
            plans,
            self.identity,
            trigger="breakout over prior high",
            plan_complete=True,
            path=self.path,
        )

        self.assertFalse(plan.plan_complete)
        self.assertEqual(["missing stop", "missing invalidation", "missing max loss"], plan.warnings)
        self.assertEqual(plan.warnings, entry_plan_warnings(plan))

    def test_entry_plan_updates_do_not_mutate_raw_capture(self) -> None:
        data_dir = Path.cwd() / "MomentumHunterData" / "data"
        json_path = data_dir / "_test-entry-plan-capture.json"
        report_path = data_dir / "_test-entry-plan-capture.md"
        manifest_path = data_dir / "_test-entry-plan-capture-manifest.json"
        candidate = make_candidate("MDT", 96)
        capture_time = datetime(2026, 6, 5, 7, 0, tzinfo=CENTRAL_TZ)

        with (
            patch("momentum_hunter.storage.capture_json_path", return_value=json_path),
            patch("momentum_hunter.storage.capture_report_path", return_value=report_path),
            patch("momentum_hunter.storage.CAPTURE_INTEGRITY_MANIFEST", manifest_path),
            patch("momentum_hunter.storage.append_analysis_rows", lambda payload: None),
        ):
            saved_json, _ = save_daily_capture(
                candidates=[candidate],
                selected_tickers=set(),
                reviewed_tickers=set(),
                criteria=ScannerCriteria("Base Momentum", 1, 1.0, 1, 1.0, 1.0),
                provider="finviz",
                mode=TradingMode.PAPER,
                session=CaptureSession.MORNING,
                market_regime=MarketRegimeSnapshot(
                    regime=MarketRegime.BULL,
                    symbol="SPY",
                    reason="test",
                ),
                capture_time=capture_time,
            )
        before = file_sha256(saved_json)

        upsert_entry_plan({}, self.identity, trigger="breakout", path=self.path)

        payload = json.loads(saved_json.read_text(encoding="utf-8"))
        self.assertEqual(before, file_sha256(saved_json))
        self.assertNotIn("entry_plan", payload["candidates"][0])
        self.assertNotIn("trigger", payload["candidates"][0])
        json_path.unlink()
        report_path.unlink()
        manifest_path.unlink()

    def test_watchlist_report_includes_entry_plan_fields(self) -> None:
        candidate = make_candidate("MDT", 96)
        plan = EntryPlan(
            identity=self.identity,
            trigger="break over 105",
            stop="99.50",
            thesis="earnings continuation",
            invalidation="fails breakout",
            max_loss="$25",
            position_size="25 shares",
            planned_hold_time="1-3 days",
            notes="Only if volume confirms.",
            plan_complete=True,
            warnings=[],
        )

        report_path = self.path.with_name("_test-watchlist-report.md")
        with patch("momentum_hunter.storage.report_path", return_value=report_path):
            report_path = save_watchlist_report(
                [candidate],
                datetime(2026, 6, 8, tzinfo=CENTRAL_TZ),
                entry_plans={"MDT": plan},
            )
        text = report_path.read_text(encoding="utf-8")

        self.assertIn("### Entry Plan", text)
        self.assertIn("- Trigger: break over 105", text)
        self.assertIn("- Stop: 99.50", text)
        self.assertIn("- Plan Complete: True", text)
        self.assertIn("- Plan Warnings: none", text)
        report_path.unlink()


class EntryPlanGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.review_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-entry-review.json"
        self.entry_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-entry-gui.json"
        for path in [self.review_path, self.entry_path]:
            if path.exists():
                path.unlink()
        self.patches = [
            patch("momentum_hunter.review.REVIEW_DECISIONS_PATH", self.review_path),
            patch("momentum_hunter.entry_plans.ENTRY_PLANS_PATH", self.entry_path),
            patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None),
            patch.object(MomentumHunterWindow, "_load_capture_history", lambda window: None),
            patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None),
            patch.object(MomentumHunterWindow, "refresh_market_regime", lambda window, show_status=True: None),
        ]
        for patcher in self.patches:
            patcher.start()
        self.window = MomentumHunterWindow()
        self.window.data_view_state = DataViewState.CURRENT
        self.window.display_capture_time = now_central() - timedelta(seconds=30)
        self.window.current_capture_time = self.window.display_capture_time
        self.window.display_session_label = "live"
        self.window.display_provider_label = "finviz"
        self.window.display_scanner_label = "Base Momentum"
        self.window.candidates = [make_candidate("MDT", 96)]
        self.window.live_candidates = list(self.window.candidates)
        self.window._apply_data_view_state()
        self.window._populate_table()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        for patcher in reversed(self.patches):
            patcher.stop()
        for path in [self.review_path, self.entry_path]:
            if path.exists():
                path.unlink()

    def test_current_view_can_edit_entry_plan_and_watchlist_status_creates_plan(self) -> None:
        self.window.entry_trigger.setText("break over 105")
        self.window.stop_level.setText("99.50")
        self.window.entry_invalidation.setPlainText("fails breakout")
        self.window.entry_max_loss.setText("$25")
        self.window.plan_complete_checkbox.setChecked(True)
        self.window._set_candidate_review_status(self.window.candidates[0], ReviewStatus.WATCHLIST)

        plans = load_entry_plans(self.entry_path)
        plan = next(iter(plans.values()))

        self.assertEqual("break over 105", plan.trigger)
        self.assertEqual("99.50", plan.stop)
        self.assertTrue(plan.plan_complete)
        self.assertEqual(ReviewStatus.WATCHLIST, self.window._candidate_review_status(self.window.candidates[0]))

    def test_historical_view_cannot_edit_entry_plan(self) -> None:
        self.window._load_historical_capture(
            {
                "capture_time": (now_central() - timedelta(days=2)).isoformat(),
                "capture_date": (now_central() - timedelta(days=2)).strftime("%Y-%m-%d"),
                "session": "evening",
                "provider": "finviz",
                "scanner": {"name": "Base Momentum"},
                "candidates": [{**candidate_payload("HIST", 82), "selected": False, "reviewed": False}],
            }
        )

        self.window.entry_trigger.setText("should not save")
        self.window._entry_plan_changed()

        self.assertFalse(load_entry_plans(self.entry_path))
        self.assertIn("read-only", self.window.status_label.text())

    def test_study_view_cannot_edit_entry_plan(self) -> None:
        self.window.data_view_state = DataViewState.STUDY
        self.window._apply_data_view_state()

        self.window.entry_trigger.setText("should not save")
        self.window._entry_plan_changed()

        self.assertFalse(load_entry_plans(self.entry_path))
        self.assertIn("read-only", self.window.status_label.text())


if __name__ == "__main__":
    unittest.main()
