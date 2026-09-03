from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QDialog

from momentum_hunter.app import MomentumHunterWindow, ReportLoaderUiRelay


class ThreadTrackingDialog(QDialog):
    def __init__(self, parent: MomentumHunterWindow) -> None:
        super().__init__(parent)
        self.close_calls = 0
        self.close_threads: list[QThread] = []

    def close(self) -> bool:
        self.close_calls += 1
        self.close_threads.append(QThread.currentThread())
        return super().close()


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

    def test_worker_completion_closes_progress_once_on_gui_thread(self) -> None:
        dialog = ThreadTrackingDialog(self.window)
        loader_threads: list[QThread] = []
        callback_threads: list[QThread] = []
        results: list[object] = []

        def loader() -> dict[str, str]:
            loader_threads.append(QThread.currentThread())
            return {"status": "ok"}

        def on_success(result: object, elapsed_seconds: float) -> None:
            del elapsed_seconds
            callback_threads.append(QThread.currentThread())
            results.append(result)

        with patch.object(self.window, "_show_loading_dialog", return_value=dialog):
            self.window._run_report_loader(
                title="Thread Affinity",
                loading_message="Loading on a worker thread...",
                loader=loader,
                on_success=on_success,
                error_title="Thread Affinity Error",
            )
            loader_thread, _worker, _progress, relay = self.window._report_loader_refs[0]
            thread_finished: list[bool] = []
            loader_thread.finished.connect(lambda: thread_finished.append(True))
            self.assertIs(relay.thread(), self.window.thread())
            self.assertTrue(self.wait_until(lambda: bool(results), timeout=3.0))
            self.assertTrue(self.wait_until(lambda: bool(thread_finished), timeout=3.0))

        self.assertEqual([{"status": "ok"}], results)
        self.assertEqual(1, dialog.close_calls)
        self.assertEqual([self.window.thread()], dialog.close_threads)
        self.assertEqual([self.window.thread()], callback_threads)
        self.assertNotEqual(self.window.thread(), loader_threads[0])
        self.assertEqual([True], thread_finished)
        self.assertEqual([], self.window._report_loader_refs)
        self.assertNotIn("Thread Affinity", self.window._active_report_loader_titles)

    def test_worker_failure_closes_progress_once_on_gui_thread(self) -> None:
        dialog = ThreadTrackingDialog(self.window)
        messages: list[tuple[str, str, QThread]] = []

        def fail_loader() -> object:
            raise RuntimeError("affinity failure")

        def show_blocked(message: str, title: str = "Action Not Available") -> None:
            messages.append((title, message, QThread.currentThread()))

        with (
            patch.object(self.window, "_show_loading_dialog", return_value=dialog),
            patch.object(self.window, "_show_action_blocked", show_blocked),
        ):
            self.window._run_report_loader(
                title="Failure Affinity",
                loading_message="Loading on a worker thread...",
                loader=fail_loader,
                on_success=lambda result, elapsed: None,
                error_title="Failure Affinity Error",
            )
            loader_thread = self.window._report_loader_refs[0][0]
            thread_finished: list[bool] = []
            loader_thread.finished.connect(lambda: thread_finished.append(True))
            self.assertTrue(self.wait_until(lambda: bool(messages), timeout=3.0))
            self.assertTrue(self.wait_until(lambda: bool(thread_finished), timeout=3.0))

        self.assertEqual(1, dialog.close_calls)
        self.assertEqual([self.window.thread()], dialog.close_threads)
        self.assertEqual(self.window.thread(), messages[0][2])
        self.assertEqual([True], thread_finished)
        self.assertEqual([], self.window._report_loader_refs)
        self.assertNotIn("Failure Affinity", self.window._active_report_loader_titles)

    def test_repeated_sequential_loads_release_every_thread_and_title(self) -> None:
        dialogs: list[ThreadTrackingDialog] = []
        thread_finished_flags: list[list[bool]] = []
        results: list[int] = []

        for cycle in range(8):
            dialog = ThreadTrackingDialog(self.window)
            dialogs.append(dialog)
            with patch.object(self.window, "_show_loading_dialog", return_value=dialog):
                self.window._run_report_loader(
                    title="Sequential Report",
                    loading_message="Loading sequential report...",
                    loader=lambda value=cycle: value,
                    on_success=lambda result, elapsed: results.append(result),
                    error_title="Sequential Report Error",
                )
                thread = self.window._report_loader_refs[0][0]
                finished: list[bool] = []
                thread.finished.connect(lambda target=finished: target.append(True))
                thread_finished_flags.append(finished)
                self.assertTrue(self.wait_until(lambda: len(results) == cycle + 1, timeout=3.0))
                self.assertTrue(self.wait_until(lambda: bool(finished), timeout=3.0))

        self.assertEqual(list(range(8)), results)
        self.assertTrue(all(dialog.close_calls == 1 for dialog in dialogs))
        self.assertTrue(all(dialog.close_threads == [self.window.thread()] for dialog in dialogs))
        self.assertTrue(all(finished == [True] for finished in thread_finished_flags))
        self.assertEqual([], self.window._report_loader_refs)
        self.assertNotIn("Sequential Report", self.window._active_report_loader_titles)

    def test_relay_ignores_duplicate_terminal_delivery(self) -> None:
        deliveries: list[str] = []
        relay = ReportLoaderUiRelay(
            on_finished=lambda result, elapsed: deliveries.append("finished"),
            on_failed=lambda error_type, message, elapsed: deliveries.append("failed"),
            parent=self.window,
        )

        relay.finish({"status": "ok"}, 0.01)
        relay.fail("RuntimeError", "late duplicate", 0.02)

        self.assertEqual(["finished"], deliveries)


if __name__ == "__main__":
    unittest.main()
