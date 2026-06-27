from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog, QPushButton

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.capture_health import CaptureFailureInfo, CaptureHealthSnapshot, CaptureSuccessInfo, CsvStatus
from momentum_hunter.daily_workflow import build_daily_workflow_report
from momentum_hunter.entry_plans import load_entry_plans, upsert_entry_plan
from momentum_hunter.market import MarketRegimeSnapshot
from momentum_hunter.models import CaptureSession, MarketRegime, ScannerCriteria, TradingMode
from momentum_hunter.outcome_maturity import OutcomeMaturityReport, ReadinessGate
from momentum_hunter.review import ReviewStatus
from momentum_hunter.storage import file_sha256, save_daily_capture
from momentum_hunter.time_utils import CENTRAL_TZ, now_central
from momentum_hunter.ui.data_view_state import DataViewState
from tests.test_review_workflow import candidate_payload, make_candidate


class DailyWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.review_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-daily-workflow-decisions.json"
        self.entry_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-daily-workflow-entry-plans.json"
        self.capture_json_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-daily-workflow-capture.json"
        self.capture_report_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-daily-workflow-capture.md"
        self.capture_manifest_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-daily-workflow-manifest.json"
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
        self.current_time = now_central()
        self.health = self.capture_health()
        self.maturity = self.outcome_maturity()
        self.patches = [
            patch("momentum_hunter.review.REVIEW_DECISIONS_PATH", self.review_path),
            patch("momentum_hunter.entry_plans.ENTRY_PLANS_PATH", self.entry_path),
            patch("momentum_hunter.app.build_capture_health_snapshot", return_value=self.health),
            patch("momentum_hunter.app.build_outcome_maturity_report", return_value=self.maturity),
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
        self.window.display_capture_time = self.current_time - timedelta(seconds=30)
        self.window.current_capture_time = self.window.display_capture_time
        self.window.display_session_label = "live"
        self.window.display_provider_label = "finviz"
        self.window.display_scanner_label = "Base Momentum"
        self.window.candidates = [make_candidate("MDT", 96), make_candidate("RXT", 73), make_candidate("PATH", 88)]
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

    def test_report_counts_score_and_warnings_are_deterministic(self) -> None:
        identities = {candidate.ticker: self.window._candidate_identity(candidate) for candidate in self.window.candidates}
        review_statuses = {
            identities["MDT"].key: ReviewStatus.WATCHLIST,
            identities["RXT"].key: ReviewStatus.REJECTED,
            identities["PATH"].key: ReviewStatus.UNREVIEWED,
        }
        upsert_entry_plan(
            {},
            identities["MDT"],
            trigger="break over 82",
            stop="79",
            invalidation="fails open",
            max_loss="$25",
            path=self.entry_path,
        )
        report = build_daily_workflow_report(
            candidates=self.window.candidates,
            identities=identities,
            review_statuses=review_statuses,
            entry_plans=load_entry_plans(self.entry_path),
            capture_health=self.health,
            outcome_maturity=self.maturity,
        )

        self.assertEqual(3, report.review.total_candidates)
        self.assertEqual(2, report.review.reviewed_candidates)
        self.assertEqual(1, report.review.unreviewed_candidates)
        self.assertEqual(1, report.review.rejected_candidates)
        self.assertEqual(1, report.entry_plans.complete_plans)
        self.assertEqual(84, report.workflow_score)
        self.assertEqual(["REVIEWS INCOMPLETE", "READINESS GATE LOCKED"], report.warnings)

    def test_warnings_trigger_for_missing_plan_failure_and_locked_gate(self) -> None:
        identities = {candidate.ticker: self.window._candidate_identity(candidate) for candidate in self.window.candidates}
        report = build_daily_workflow_report(
            candidates=self.window.candidates[:1],
            identities=identities,
            review_statuses={identities["MDT"].key: ReviewStatus.WATCHLIST},
            entry_plans={},
            capture_health=self.capture_health(failed=True),
            outcome_maturity=self.maturity,
        )

        self.assertIn("WATCHLIST HAS NO ENTRY PLAN", report.warnings)
        self.assertIn("INCOMPLETE ENTRY PLAN", report.warnings)
        self.assertIn("CAPTURE FAILURE DETECTED", report.warnings)
        self.assertIn("READINESS GATE LOCKED", report.warnings)
        self.assertLess(report.workflow_score, 100)

    def test_dialog_current_view_allows_workflow_quick_actions(self) -> None:
        self.window.daily_checklist_button.click()
        dialog = self.dialogs[-1]

        self.assertIn("Today's Workflow Score:", self.window.daily_workflow_score_label.text())
        self.assertTrue(self.button(dialog, "Open Morning Review").isEnabled())
        self.assertTrue(self.button(dialog, "Generate Watchlist Report").isEnabled())
        self.assertTrue(self.button(dialog, "Open Capture Health").isEnabled())
        self.assertTrue(self.button(dialog, "Open Readiness Gate").isEnabled())

    def test_operator_navigation_labels_are_clear(self) -> None:
        self.assertFalse(hasattr(self.window, "save_button"))
        self.assertEqual("Daily Checklist", self.window.daily_checklist_button.text())
        self.assertIsNotNone(self.window.daily_checklist_button.parentWidget())
        self.assertEqual("Morning Review", self.window.morning_review_button.text())
        self.assertEqual("Capture Health", self.window.capture_health_button.text())
        self.assertEqual("Generate Watchlist Report", self.window.watchlist_button.text())
        self.assertEqual("Open Latest Watchlist", self.window.view_button.text())
        self.assertEqual("Open Historical Snapshot", self.window.open_capture_button.text())
        self.assertEqual("Current Dashboard", self.window.current_button.text())
        self.assertEqual("Research Lab", self.window.study_button.text())
        self.assertIn("checked rows", self.window.mark_interested_button.toolTip())
        self.assertIn("No orders", self.window.watchlist_button.toolTip())
        self.assertIn("Research-only", self.window.study_button.toolTip())

    def test_historical_and_study_dialogs_are_read_only_for_edit_actions(self) -> None:
        self.window._load_historical_capture(
            {
                "capture_time": (self.current_time - timedelta(days=2)).isoformat(),
                "capture_date": (self.current_time - timedelta(days=2)).strftime("%Y-%m-%d"),
                "session": "evening",
                "provider": "finviz",
                "scanner": {"name": "Base Momentum"},
                "candidates": [{**candidate_payload("HIST", 82), "selected": False, "reviewed": False}],
            }
        )
        self.window.open_daily_workflow_checklist()
        historical_dialog = self.dialogs[-1]
        self.assertFalse(self.button(historical_dialog, "Open Morning Review").isEnabled())
        self.assertFalse(self.button(historical_dialog, "Generate Watchlist Report").isEnabled())

        self.window.data_view_state = DataViewState.STUDY
        self.window._apply_data_view_state()
        self.window.open_daily_workflow_checklist()
        study_dialog = self.dialogs[-1]
        self.assertFalse(self.button(study_dialog, "Open Morning Review").isEnabled())
        self.assertFalse(self.button(study_dialog, "Generate Watchlist Report").isEnabled())

    def test_raw_capture_is_not_mutated_by_daily_checklist(self) -> None:
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

        self.window.open_daily_workflow_checklist()

        self.assertEqual(before, file_sha256(saved_json))

    def button(self, dialog: QDialog, text: str) -> QPushButton:
        for button in dialog.findChildren(QPushButton):
            if button.text() == text:
                return button
        self.fail(f"Button not found: {text}")

    def capture_health(self, *, failed: bool = False) -> CaptureHealthSnapshot:
        current = self.current_time if hasattr(self, "current_time") else now_central()
        return CaptureHealthSnapshot(
            last_morning_capture=CaptureSuccessInfo(
                session=CaptureSession.MORNING,
                capture_time=current.replace(hour=7, minute=0, second=0, microsecond=0),
                candidate_count=10,
                provider="finviz",
                scanner="Base Momentum",
            ),
            last_evening_capture=CaptureSuccessInfo(
                session=CaptureSession.EVENING,
                capture_time=current.replace(hour=19, minute=0, second=0, microsecond=0) - timedelta(days=1),
                candidate_count=12,
                provider="finviz",
                scanner="Base Momentum",
            ),
            last_preopen_capture=CaptureSuccessInfo(session=CaptureSession.PREOPEN),
            last_failed_capture=CaptureFailureInfo(
                failure_time=current - timedelta(hours=1),
                session="morning",
                provider="finviz",
                scanner="Base Momentum",
                error_message="DNS failure",
            )
            if failed
            else CaptureFailureInfo(),
            next_morning_run=current + timedelta(days=1),
            next_evening_run=current.replace(hour=19, minute=0, second=0, microsecond=0),
            next_preopen_run=current + timedelta(days=3),
            csv_append_status=CsvStatus(path=Path("analysis-captures.csv"), exists=True, row_count=10),
            outcome_update_status=CsvStatus(path=Path("analysis-outcomes.csv"), exists=True, row_count=10),
        )

    def outcome_maturity(self) -> OutcomeMaturityReport:
        gates = [
            ReadinessGate("Outcome Explorer", "LOCKED", 0, 20, "0 completed next-day outcomes", "unknown"),
            ReadinessGate("Opportunity Research", "LOCKED", 0, 50, "0 completed five-day outcomes", "unknown"),
            ReadinessGate("Opportunity Score design", "LOCKED", 0, 100, "0 completed five-day outcomes", "unknown"),
            ReadinessGate("Weight optimization", "LOCKED", 0, 300, "0 completed five-day outcomes", "unknown"),
        ]
        return OutcomeMaturityReport(
            label="test",
            source="test",
            filters=None,
            total_candidates=10,
            study_eligible_candidates=10,
            completed_next_day_outcomes=2,
            completed_five_day_outcomes=1,
            pending_next_day_outcomes=8,
            pending_five_day_outcomes=9,
            completed_outcome_pct=10.0,
            pending_outcome_pct=90.0,
            earliest_capture_date="2026-06-01",
            latest_capture_date="2026-06-05",
            earliest_date_with_usable_five_day_outcomes="2026-06-01",
            latest_date_with_pending_five_day_outcomes="2026-06-05",
            gates=gates,
            warnings=["INSUFFICIENT COMPLETED OUTCOMES"],
        )


if __name__ == "__main__":
    unittest.main()
