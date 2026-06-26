from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from momentum_hunter.app import MomentumHunterWindow


class ReportLoaderHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.patches = [
            patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None),
            patch.object(MomentumHunterWindow, "_load_capture_history", lambda window: None),
            patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None),
            patch.object(MomentumHunterWindow, "refresh_market_regime", lambda window, show_status=True: None),
        ]
        for patcher in self.patches:
            patcher.start()
        self.window = MomentumHunterWindow()

    def tearDown(self) -> None:
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline and self.window._report_loader_refs:
            self.app.processEvents()
            time.sleep(0.01)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        for patcher in reversed(self.patches):
            patcher.stop()

    def wait_until(self, condition, timeout: float = 2.0) -> bool:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.01)
        return False

    def test_duplicate_report_loader_request_is_ignored_while_active(self) -> None:
        results: list[object] = []

        def slow_loader() -> dict[str, str]:
            time.sleep(0.15)
            return {"status": "ok"}

        self.window._run_report_loader(
            title="Research Lab",
            loading_message="Loading Research Lab without blocking the dashboard...",
            loader=slow_loader,
            on_success=lambda result, elapsed: results.append(result),
            error_title="Research Lab Error",
        )
        self.window._run_report_loader(
            title="Research Lab",
            loading_message="Loading Research Lab without blocking the dashboard...",
            loader=slow_loader,
            on_success=lambda result, elapsed: results.append(result),
            error_title="Research Lab Error",
        )

        self.assertEqual(1, len(self.window._report_loader_refs))
        self.assertIn("Research Lab", self.window._active_report_loader_titles)
        self.assertTrue(self.wait_until(lambda: len(results) == 1, timeout=3.0))
        self.assertEqual([{"status": "ok"}], results)
        self.assertEqual([], self.window._report_loader_refs)
        self.assertNotIn("Research Lab", self.window._active_report_loader_titles)

    def test_failed_report_loader_clears_active_title_and_reports_error(self) -> None:
        messages: list[tuple[str, str]] = []

        def fail_loader() -> object:
            raise RuntimeError("boom")

        with patch.object(self.window, "_show_action_blocked", lambda message, title="Action Not Available": messages.append((title, message))):
            self.window._run_report_loader(
                title="Readiness Gate",
                loading_message="Loading Readiness Gate without blocking the dashboard...",
                loader=fail_loader,
                on_success=lambda result, elapsed: None,
                error_title="Readiness Gate Error",
            )

            self.assertTrue(self.wait_until(lambda: bool(messages), timeout=3.0))

        self.assertEqual("Readiness Gate Error", messages[0][0])
        self.assertIn("RuntimeError", messages[0][1])
        self.assertIn("boom", messages[0][1])
        self.assertEqual([], self.window._report_loader_refs)
        self.assertNotIn("Readiness Gate", self.window._active_report_loader_titles)


if __name__ == "__main__":
    unittest.main()
