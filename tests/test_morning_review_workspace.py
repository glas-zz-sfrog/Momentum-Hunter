from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.entry_plans import load_entry_plans
from momentum_hunter.market import MarketRegimeSnapshot
from momentum_hunter.models import CaptureSession, MarketRegime, ScannerCriteria, TradingMode
from momentum_hunter.review import ReviewStatus
from momentum_hunter.storage import file_sha256, save_daily_capture
from momentum_hunter.time_utils import CENTRAL_TZ, now_central
from momentum_hunter.ui.data_view_state import DataViewState
from tests.test_review_workflow import candidate_payload, make_candidate


class MorningReviewWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.review_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-morning-review-decisions.json"
        self.entry_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-morning-review-entry-plans.json"
        self.capture_json_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-morning-review-capture.json"
        self.capture_report_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-morning-review-capture.md"
        self.capture_manifest_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-morning-review-manifest.json"
        for path in [
            self.review_path,
            self.entry_path,
            self.capture_json_path,
            self.capture_report_path,
            self.capture_manifest_path,
        ]:
            if path.exists():
                path.unlink()
        self.dialogs: list[QDialog] = []
        self.patches = [
            patch("momentum_hunter.review.REVIEW_DECISIONS_PATH", self.review_path),
            patch("momentum_hunter.entry_plans.ENTRY_PLANS_PATH", self.entry_path),
            patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None),
            patch.object(MomentumHunterWindow, "_load_capture_history", lambda window: None),
            patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None),
            patch.object(MomentumHunterWindow, "refresh_market_regime", lambda window, show_status=True: None),
            patch.object(QDialog, "exec", lambda dialog: self.capture_dialog(dialog)),
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
        self.window.candidates = [make_candidate("MDT", 96), make_candidate("RXT", 73)]
        self.window.live_candidates = list(self.window.candidates)
        self.window._apply_data_view_state()
        self.window._populate_table()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        for patcher in reversed(self.patches):
            patcher.stop()
        for path in [
            self.review_path,
            self.entry_path,
            self.capture_json_path,
            self.capture_report_path,
            self.capture_manifest_path,
        ]:
            if path.exists():
                path.unlink()

    def capture_dialog(self, dialog: QDialog) -> int:
        self.dialogs.append(dialog)
        return 0

    def test_current_workspace_allows_review_and_entry_plan_edits(self) -> None:
        self.window.open_morning_review_workspace()
        dialog = self.dialogs[-1]

        self.window.morning_entry_trigger.setText("break over 105")
        self.window.morning_entry_stop.setText("99.50")
        self.window.morning_entry_invalidation.setPlainText("fails breakout")
        self.window.morning_entry_max_loss.setText("$25")
        self.window.morning_entry_thesis.setPlainText("strong morning continuation candidate")
        self.window.morning_entry_position_size.setText("starter size")
        self.window.morning_entry_hold_time.setText("1-3 days")
        self.window.morning_plan_complete.setChecked(True)
        self.click_button(dialog, "Create/Edit Entry Plan")
        self.click_button(dialog, "Add to Watchlist")

        plans = load_entry_plans(self.entry_path)
        plan = next(iter(plans.values()))

        self.assertEqual("break over 105", plan.trigger)
        self.assertEqual("99.50", plan.stop)
        self.assertEqual("fails breakout", plan.invalidation)
        self.assertTrue(plan.plan_complete)
        self.assertEqual(ReviewStatus.WATCHLIST, self.window._candidate_review_status(self.window.candidates[0]))
        self.assertTrue(self.button(dialog, "Add to Watchlist").isEnabled())

    def test_workspace_entry_plan_save_requires_selected_candidate_feedback(self) -> None:
        messages: list[str] = []
        self.window.open_morning_review_workspace()
        dialog = self.dialogs[-1]
        self.window.morning_review_table.clearSelection()

        with patch.object(self.window, "_show_action_blocked", lambda message, title="Action Not Available": messages.append(message)):
            self.click_button(dialog, "Create/Edit Entry Plan")

        self.assertTrue(messages)
        self.assertIn("No candidate selected", messages[0])

    def test_aged_workspace_warns_but_allows_actions(self) -> None:
        self.window.display_capture_time = now_central() - timedelta(days=1)
        self.window.current_capture_time = self.window.display_capture_time
        self.window._apply_data_view_state()
        self.window.open_morning_review_workspace()
        dialog = self.dialogs[-1]
        labels = [label.text() for label in dialog.findChildren(QLabel)]

        self.assertTrue(any("CURRENT MANUAL SCAN - AGED BUT REVIEWABLE" in text for text in labels))
        self.assertTrue(self.button(dialog, "Mark Interested").isEnabled())
        self.assertTrue(self.button(dialog, "Create/Edit Entry Plan").isEnabled())

    def test_historical_and_study_workspaces_block_edits(self) -> None:
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
        self.window.open_morning_review_workspace()
        historical_dialog = self.dialogs[-1]
        self.assertFalse(self.button(historical_dialog, "Add to Watchlist").isEnabled())

        self.window.data_view_state = DataViewState.STUDY
        self.window._apply_data_view_state()
        self.window.open_morning_review_workspace()
        study_dialog = self.dialogs[-1]
        self.assertFalse(self.button(study_dialog, "Create/Edit Entry Plan").isEnabled())

    def test_raw_capture_is_not_mutated_by_workspace_plan_save(self) -> None:
        data_dir = Path.cwd() / "MomentumHunterData" / "data"
        capture_time = datetime(2026, 6, 5, 7, 0, tzinfo=CENTRAL_TZ)
        with (
            patch("momentum_hunter.storage.capture_json_path", return_value=self.capture_json_path),
            patch("momentum_hunter.storage.capture_report_path", return_value=self.capture_report_path),
            patch("momentum_hunter.storage.CAPTURE_INTEGRITY_MANIFEST", self.capture_manifest_path),
            patch("momentum_hunter.storage.append_analysis_rows", lambda payload: None),
        ):
            saved_json, _ = save_daily_capture(
                candidates=[make_candidate("MDT", 96)],
                selected_tickers=set(),
                reviewed_tickers=set(),
                criteria=ScannerCriteria("Base Momentum", 1, 1.0, 1, 1.0, 1.0),
                provider="finviz",
                mode=TradingMode.PAPER,
                session=CaptureSession.MORNING,
                market_regime=MarketRegimeSnapshot(regime=MarketRegime.BULL, symbol="SPY", reason="test"),
                capture_time=capture_time,
            )
        before = file_sha256(saved_json)

        self.window.open_morning_review_workspace()
        self.window.morning_entry_trigger.setText("break over 105")
        self.click_button(self.dialogs[-1], "Create/Edit Entry Plan")

        payload = json.loads(saved_json.read_text(encoding="utf-8"))
        self.assertEqual(before, file_sha256(saved_json))
        self.assertNotIn("entry_plan", payload["candidates"][0])

    def test_decision_card_and_incomplete_plan_warnings_reflect_selected_candidate(self) -> None:
        self.window.open_morning_review_workspace()

        self.assertIn("MDT", self.window.morning_decision_card.toPlainText())
        self.assertIn("Score 96", self.window.morning_decision_card.toPlainText())
        self.assertIn("missing stop", self.window.morning_plan_warning.text())
        self.assertIn("missing invalidation", self.window.morning_plan_warning.text())

        self.window.morning_review_table.selectRow(1)
        self.assertIn("RXT", self.window.morning_decision_card.toPlainText())
        self.assertIn("Score 73", self.window.morning_decision_card.toPlainText())

    def button(self, dialog: QDialog, text: str) -> QPushButton:
        for button in dialog.findChildren(QPushButton):
            if button.text() == text:
                return button
        self.fail(f"Button not found: {text}")

    def click_button(self, dialog: QDialog, text: str) -> None:
        self.button(dialog, text).click()


if __name__ == "__main__":
    unittest.main()
