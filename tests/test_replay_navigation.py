from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QGroupBox

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.models import Candidate, CaptureSession


class ReplayNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        patches = [
            patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None),
            patch.object(MomentumHunterWindow, "_load_capture_history", lambda window: None),
            patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None),
            patch.object(MomentumHunterWindow, "refresh_market_regime", lambda window, show_status=True: None),
        ]
        self.patchers = patches
        for patcher in patches:
            patcher.start()
        self.window = MomentumHunterWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        for patcher in reversed(self.patchers):
            patcher.stop()

    def test_open_historical_snapshot_populates_replay_page(self) -> None:
        self.window.capture_date_combo.addItem("2026-06-18")
        self.window.capture_date_combo.setCurrentText("2026-06-18")
        self.window.capture_session_combo.addItem("evening")
        self.window.capture_session_combo.setCurrentText("evening")
        self.window._navigate_to_page(4)

        with patch("momentum_hunter.app.load_capture_json", return_value=historical_payload()) as load_capture:
            self.window.open_selected_capture()

        load_capture.assert_called_once()
        self.assertEqual("2026-06-18", load_capture.call_args.args[0])
        self.assertEqual("evening", load_capture.call_args.args[1].value)
        self.assertEqual(4, self.window.page_stack.currentIndex())
        self.assertEqual("evening", self.window.display_session_label)
        self.assertEqual(["COO"], [candidate.ticker for candidate in self.window.candidates])
        self.assertEqual(1, self.window.replay_snapshot_table.rowCount())
        self.assertEqual("COO", self.window.replay_snapshot_table.item(0, 0).text())
        self.assertIn("COO Historical Snapshot Candidate", self.window.replay_snapshot_detail.toPlainText())
        self.assertIn("Snapshot Audit Identity", self.window.replay_snapshot_detail.toPlainText())

    def test_open_historical_snapshot_with_empty_capture_shows_no_candidate_reason_without_fallback(self) -> None:
        self.window.capture_date_combo.addItem("2026-06-17")
        self.window.capture_date_combo.setCurrentText("2026-06-17")
        self.window.capture_session_combo.addItem("morning")
        self.window.capture_session_combo.setCurrentText("morning")
        self.window._navigate_to_page(4)
        payload = historical_payload()
        payload["capture_date"] = "2026-06-17"
        payload["capture_time"] = "2026-06-17T07:00:00-05:00"
        payload["session"] = "morning"
        payload["candidates"] = []

        with (
            patch("momentum_hunter.app.load_capture_json", return_value=payload) as load_capture,
            patch("momentum_hunter.app.load_capture_report") as load_report,
        ):
            self.window.open_selected_capture()

        load_capture.assert_called_once()
        load_report.assert_not_called()
        self.assertEqual(4, self.window.page_stack.currentIndex())
        self.assertEqual([], self.window.candidates)
        self.assertEqual(0, self.window.replay_snapshot_table.rowCount())
        self.assertIn("No candidates found in this capture.", self.window.status_label.text())
        self.assertIn("has no candidates", self.window.replay_snapshot_status_label.text())
        self.assertIn("Selected capture has no candidates.", self.window.replay_snapshot_detail.toPlainText())

    def test_replay_page_autoloads_latest_capture_with_candidates(self) -> None:
        self.window.capture_date_combo.addItem("2026-06-19")
        self.window.capture_date_combo.setCurrentText("2026-06-19")
        self.window.capture_session_combo.addItem("morning")
        self.window.capture_session_combo.setCurrentText("morning")
        self.window._navigate_to_page(4)
        empty_payload = historical_payload()
        empty_payload["capture_date"] = "2026-06-19"
        empty_payload["capture_time"] = "2026-06-19T07:00:00-05:00"
        empty_payload["session"] = "morning"
        empty_payload["candidates"] = []
        usable_payload = historical_payload()
        usable_payload["capture_date"] = "2026-06-18"
        usable_payload["session"] = "evening"

        def fake_load(date_text: str, session: CaptureSession) -> dict:
            if date_text == "2026-06-19":
                return empty_payload
            if date_text == "2026-06-18" and session == CaptureSession.EVENING:
                return usable_payload
            return {}

        def fake_sessions(date_text: str) -> list[CaptureSession]:
            if date_text == "2026-06-18":
                return [CaptureSession.MORNING, CaptureSession.EVENING]
            return [CaptureSession.MORNING]

        with (
            patch("momentum_hunter.app.load_capture_json", side_effect=fake_load),
            patch("momentum_hunter.app.list_capture_dates", return_value=["2026-06-19", "2026-06-18"]),
            patch("momentum_hunter.app.list_capture_sessions", side_effect=fake_sessions),
        ):
            self.window._autoload_replay_snapshot()

        self.assertEqual("2026-06-18", self.window.capture_date_combo.currentText())
        self.assertEqual("evening", self.window.capture_session_combo.currentText())
        self.assertEqual(1, self.window.replay_snapshot_table.rowCount())
        self.assertEqual("COO", self.window.replay_snapshot_table.item(0, 0).text())
        self.assertIn("Loaded 1 candidate", self.window.replay_snapshot_status_label.text())

    def test_current_dashboard_returns_to_dashboard_page(self) -> None:
        self.window.live_candidates = [Candidate("LIVE", score=88)]
        self.window.candidates = [Candidate("OLD", score=1)]
        self.window.selected_ticker = "OLD"
        self.window._navigate_to_page(4)

        self.window.return_to_current_dashboard()

        self.assertEqual(0, self.window.page_stack.currentIndex())
        self.assertEqual(["LIVE"], [candidate.ticker for candidate in self.window.candidates])
        self.assertEqual("LIVE", self.window.selected_ticker)

    def test_timeline_button_uses_selected_replay_snapshot_candidate(self) -> None:
        payload = historical_payload()
        payload["candidates"].append({"ticker": "FROG", "price": 42, "score": 77})
        self.window._navigate_to_page(4)
        self.window._load_historical_capture(payload)
        self.window._load_replay_snapshot(payload)
        self.window.replay_snapshot_table.selectRow(1)
        opened = []

        with patch.object(self.window, "_show_timeline_dialog", lambda ticker: opened.append(ticker)):
            self.window.view_candidate_timeline()

        self.assertEqual(["FROG"], opened)

    def test_back_button_returns_to_previous_pages_without_looping(self) -> None:
        self.assertEqual(0, self.window.page_stack.currentIndex())
        self.assertFalse(self.window.back_button.isEnabled())

        self.window._navigate_to_page(1)
        self.window._navigate_to_page(4)

        self.assertEqual(4, self.window.page_stack.currentIndex())
        self.assertTrue(self.window.back_button.isEnabled())
        self.assertIn("Watchlist", self.window.back_button.toolTip())

        self.window._go_back_page()

        self.assertEqual(1, self.window.page_stack.currentIndex())
        self.assertTrue(self.window.back_button.isEnabled())
        self.assertIn("Dashboard", self.window.back_button.toolTip())

        self.window._go_back_page()

        self.assertEqual(0, self.window.page_stack.currentIndex())
        self.assertFalse(self.window.back_button.isEnabled())

    def test_candidate_story_dialog_defaults_to_trail_and_preserves_audit(self) -> None:
        opened: list[QDialog] = []

        def capture_exec(dialog: QDialog) -> int:
            opened.append(dialog)
            return 0

        with (
            patch("momentum_hunter.app.build_candidate_timeline", return_value=[]),
            patch.object(QDialog, "exec", capture_exec),
        ):
            self.window._show_timeline_dialog("COO")

        self.assertEqual(1, len(opened))
        dialog = opened[0]
        self.assertEqual("Candidate Story - COO", dialog.windowTitle())
        combo_items = [
            [combo.itemText(index) for index in range(combo.count())]
            for combo in dialog.findChildren(QComboBox)
        ]
        self.assertIn(["Trail", "Intraday", "5D", "Audit"], combo_items)
        audit_boxes = [
            group
            for group in dialog.findChildren(QGroupBox)
            if group.title() == "Advanced Capture Audit"
        ]
        self.assertEqual(1, len(audit_boxes))
        self.assertTrue(audit_boxes[0].isHidden())


def historical_payload() -> dict:
    return {
        "schema_version": 2,
        "capture_time": "2026-06-18T19:00:00-05:00",
        "capture_date": "2026-06-18",
        "session": "evening",
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": "Base Momentum"},
        "capture_calendar_status": "MARKET_OPEN_DAY",
        "next_market_session_date": "2026-06-22",
        "candidates": [{"ticker": "COO", "price": 100, "score": 90}],
    }


if __name__ == "__main__":
    unittest.main()
