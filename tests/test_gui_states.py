from __future__ import annotations

import unittest
import time
from datetime import timedelta
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QDialog, QTableWidget, QWidget

from momentum_hunter.app import MomentumHunterWindow, format_score_breakdown_html
from momentum_hunter.models import Candidate, NewsItem
from momentum_hunter.providers import ProviderUnavailableError
from momentum_hunter.study import RegimeSummary, ScoreBucketSummary, StudySummary
from momentum_hunter.time_utils import now_central
from momentum_hunter.ui.data_view_state import DataViewState


class GuiStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.patches = [
            patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None),
            patch.object(MomentumHunterWindow, "_load_capture_history", lambda window: None),
            patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None),
            patch.object(MomentumHunterWindow, "refresh_market_regime", lambda window, show_status=True: None),
            patch("momentum_hunter.app.upsert_score_breakdowns_for_candidates", lambda *args, **kwargs: []),
            patch("momentum_hunter.app.upsert_score_breakdowns_for_capture_payload", lambda *args, **kwargs: []),
        ]
        for patcher in self.patches:
            patcher.start()
        self.window = MomentumHunterWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
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

    def test_command_center_navigation_pages_exist(self) -> None:
        self.assertEqual(6, self.window.page_stack.count())
        self.assertEqual(
            ["Dashboard", "Watchlist", "Evidence", "Research", "Replay", "Health"],
            [button.text() for button in self.window.nav_buttons],
        )
        self.assertEqual(0, self.window.page_stack.currentIndex())

        self.window._navigate_to_page(2)

        self.assertEqual(2, self.window.page_stack.currentIndex())
        self.assertTrue(self.window.nav_buttons[2].isChecked())
        self.assertFalse(self.window.nav_buttons[0].isChecked())
        self.assertTrue(hasattr(self.window, "execution_ready_table"))
        self.assertTrue(hasattr(self.window, "provider_status_label"))

    def test_selecting_candidate_does_not_mark_it_reviewed(self) -> None:
        self.window.data_view_state = DataViewState.CURRENT
        self.window.display_capture_time = now_central() - timedelta(seconds=30)
        self.window.display_session_label = "live"
        self.window.candidates = [candidate("LOOK", score=88)]

        self.window._apply_data_view_state()
        self.window._populate_table()

        self.assertEqual("LOOK", self.window.selected_ticker)
        self.assertNotIn("LOOK", self.window.reviewed_tickers)
        self.assertNotIn("LOOK", self.window.live_reviewed_tickers)
        self.assertEqual("Unreviewed", self.window.table.item(0, 1).text())

    def test_checked_rows_survive_row_selection_and_detail_refresh(self) -> None:
        self.window.data_view_state = DataViewState.CURRENT
        self.window.display_capture_time = now_central() - timedelta(seconds=30)
        self.window.display_session_label = "live"
        self.window.candidates = [candidate("KEEP", score=88), candidate("VIEW", score=84)]

        self.window._apply_data_view_state()
        self.window._populate_table()
        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.window.table.selectRow(1)
        self.window._show_candidate_details(self.window.candidates[1])

        self.assertEqual(Qt.CheckState.Checked, self.window.table.item(0, 0).checkState())
        self.assertEqual("VIEW", self.window.selected_ticker)

    def test_readiness_gate_failure_shows_visible_feedback(self) -> None:
        messages: list[tuple[str, str]] = []

        def blocked(message: str, title: str = "Action Not Available") -> None:
            messages.append((title, message))

        with (
            patch("momentum_hunter.app.build_outcome_maturity_report", side_effect=RuntimeError("boom")),
            patch.object(self.window, "_show_action_blocked", blocked),
        ):
            self.window.open_readiness_gate()

        self.assertTrue(self.wait_until(lambda: bool(messages)))
        self.assertEqual("Readiness Gate Error", messages[0][0])
        self.assertIn("RuntimeError", messages[0][1])
        self.assertIn("boom", messages[0][1])

    def test_research_lab_failure_shows_visible_feedback(self) -> None:
        messages: list[tuple[str, str]] = []

        def blocked(message: str, title: str = "Action Not Available") -> None:
            messages.append((title, message))

        with (
            patch("momentum_hunter.app.build_capture_study", side_effect=RuntimeError("boom")),
            patch.object(self.window, "_show_action_blocked", blocked),
        ):
            self.window.open_study_engine()

        self.assertTrue(self.wait_until(lambda: bool(messages)))
        self.assertEqual("Research Lab Error", messages[0][0])
        self.assertIn("RuntimeError", messages[0][1])
        self.assertIn("boom", messages[0][1])

    def test_research_lab_open_returns_control_before_slow_report_finishes(self) -> None:
        opened: list[object] = []

        def slow_study():
            time.sleep(0.25)
            return study_summary()

        with (
            patch("momentum_hunter.app.build_capture_study", slow_study),
            patch.object(self.window, "_show_study_dialog", lambda summary: opened.append(summary)),
        ):
            started = time.perf_counter()
            self.window.open_study_engine()
            elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.15)
        self.assertTrue(self.wait_until(lambda: bool(opened), timeout=3.0))

    def test_score_breakdown_html_uses_readable_units_and_freshness_note(self) -> None:
        capture_time = now_central()
        candidate_with_news = candidate("UNIT", score=96)
        candidate_with_news.news = [
            NewsItem(
                headline="Unit Corp posts strong earnings beat",
                source="Finviz",
                published_at=capture_time - timedelta(minutes=32),
            )
        ]
        record = {
            "ticker": "UNIT",
            "final_score": 96,
            "identity": {"capture_time": capture_time.isoformat(), "session": "live", "provider": "finviz", "scanner": "Base Momentum", "mode": "PAPER"},
            "components": [
                {
                    "key": "market_cap",
                    "label": "Market Cap",
                    "category": "bonus",
                    "rule": ">= 50,000,000,000 => +12; >= 5,000,000,000 => +9",
                    "raw_inputs": {"market_cap": 40_000_000_000},
                    "points_before_adjustment": 9,
                    "points_after_adjustment": 9,
                    "explanation": "mid/large cap participation",
                },
                {
                    "key": "volume",
                    "label": "Volume",
                    "category": "bonus",
                    "rule": ">= 25,000,000 => +12; >= 3,000,000 => +8",
                    "raw_inputs": {"volume": 20_000_000},
                    "points_before_adjustment": 8,
                    "points_after_adjustment": 8,
                    "explanation": "20,000,000 volume",
                },
                {
                    "key": "freshness_context",
                    "label": "Freshness Context",
                    "category": "context",
                    "rule": "Current engine records freshness for explainability; freshness does not add or subtract points in momentum_score_v1.",
                    "raw_inputs": {"freshness": "HOT", "freshness_score": 99, "article_count": 1},
                    "points_before_adjustment": 0,
                    "points_after_adjustment": 0,
                    "explanation": "Latest valid article freshness is HOT with score 99.",
                },
            ],
        }

        html = format_score_breakdown_html(record, candidate=candidate_with_news)

        self.assertIn("$40.0B", html)
        self.assertIn("20.0M", html)
        self.assertIn("Base Points", html)
        self.assertIn("Applied Impact", html)
        self.assertIn("Freshness is recorded", html)
        self.assertIn("Unit Corp posts strong earnings beat", html)

    def test_fresh_current_dashboard_allows_decisions(self) -> None:
        self.window.data_view_state = DataViewState.CURRENT
        self.window.display_capture_time = now_central() - timedelta(seconds=30)
        self.window.display_session_label = "live"
        self.window.candidates = [candidate("LIVE", score=91)]

        self.window._apply_data_view_state()
        self.window._populate_table()

        self.assertIn("CURRENT DASHBOARD - LIVE REVIEW", self.window.view_state_label.text())
        self.assertEqual("LIVE REVIEW CANDIDATE", self.window.detail_state_label.text())
        self.assertEqual("LIVE - Top Momentum Candidates", self.window.chart_state_label.text())
        self.assertEqual("Why 91?", self.window.why_score_button.text())
        self.assertTrue(self.window.why_score_button.isEnabled())
        self.assertTrue(self.window.mark_interested_button.isEnabled())
        self.assertFalse(self.window.notes_edit.isReadOnly())
        self.assertTrue(self.window.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)

    def test_aged_current_dashboard_warns_but_allows_staging_actions(self) -> None:
        self.window.data_view_state = DataViewState.CURRENT
        self.window.display_capture_time = now_central() - timedelta(days=1)
        self.window.display_session_label = "live"
        self.window.candidates = [candidate("OLD", score=75)]

        self.window._apply_data_view_state()
        self.window._populate_table()

        self.assertIn("CURRENT MANUAL SCAN - AGED BUT REVIEWABLE", self.window.view_state_label.text())
        self.assertEqual("AGED - Top Momentum Candidates", self.window.chart_state_label.text())
        self.assertTrue(self.window.mark_interested_button.isEnabled())
        self.assertFalse(self.window.notes_edit.isReadOnly())
        self.assertTrue(self.window.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)

    def test_run_scan_replaces_stale_candidate_detail_panel(self) -> None:
        self.window.candidates = [candidate("OLD", score=72)]
        self.window.display_capture_time = now_central() - timedelta(seconds=30)
        self.window._apply_data_view_state()
        self.window._populate_table()
        self.assertEqual("OLD", self.window.ticker_label.text())

        with patch.object(self.window, "_scan_current_candidates", lambda: setattr(self.window, "candidates", [candidate("NEW", score=94)])):
            self.window.run_scan()

        self.assertEqual("NEW", self.window.ticker_label.text())
        self.assertEqual("Momentum: 94 | Freshness: 0 UNKNOWN", self.window.score_label.text())
        self.assertEqual("NEW", self.window.table.item(0, 4).text())
        self.assertNotEqual("OLD", self.window.selected_ticker)

    def test_empty_scan_clears_candidate_detail_panel(self) -> None:
        self.window.candidates = [candidate("OLD", score=72)]
        self.window.display_capture_time = now_central() - timedelta(seconds=30)
        self.window._apply_data_view_state()
        self.window._populate_table()
        self.assertEqual("OLD", self.window.ticker_label.text())

        with patch.object(self.window, "_scan_current_candidates", lambda: setattr(self.window, "candidates", [])):
            self.window.run_scan()

        self.assertEqual("No candidate selected", self.window.ticker_label.text())
        self.assertEqual("", self.window.score_label.text())
        self.assertEqual("", self.window.news_text.toPlainText())
        self.assertIsNone(self.window.selected_ticker)

    def test_provider_failure_preserves_existing_table_and_shows_retry(self) -> None:
        self.window.data_view_state = DataViewState.CURRENT
        self.window.display_capture_time = now_central() - timedelta(days=1)
        self.window.current_capture_time = self.window.display_capture_time
        self.window.display_session_label = "live"
        self.window.candidates = [candidate("OLD", score=72)]
        self.window._apply_data_view_state()
        self.window._populate_table()

        def fail_scan():
            raise ProviderUnavailableError("finviz", "Provider unavailable / DNS failure while running finviz scan.", "dns_failure")

        with (
            patch.object(self.window, "_scan_current_candidates", fail_scan),
            patch("momentum_hunter.app.QMessageBox.warning"),
        ):
            self.window.run_scan()

        self.assertEqual("OLD", self.window.table.item(0, 4).text())
        self.assertIn("CURRENT MANUAL SCAN - AGED BUT REVIEWABLE", self.window.view_state_label.text())
        self.assertFalse(self.window.retry_scan_button.isHidden())
        self.assertIn("DNS failure", self.window.provider_status_label.text())

    def test_historical_capture_is_read_only_and_restores_current_dashboard(self) -> None:
        self.window.live_candidates = [candidate("CURR", score=88)]
        self.window.live_saved_candidates = {}
        self.window.live_reviewed_tickers = set()
        self.window.current_capture_time = now_central() - timedelta(seconds=45)

        self.window._load_historical_capture(
            {
                "capture_time": (now_central() - timedelta(days=2)).isoformat(),
                "session": "evening",
                "candidates": [
                    {
                        **candidate_payload("HIST", score=82),
                        "selected": True,
                        "reviewed": True,
                    }
                ],
            }
        )

        self.assertIn("HISTORICAL SNAPSHOT - READ ONLY", self.window.view_state_label.text())
        self.assertEqual("HISTORICAL - Top Momentum Candidates", self.window.chart_state_label.text())
        self.assertFalse(self.window.mark_interested_button.isEnabled())
        self.assertTrue(self.window.notes_edit.isReadOnly())
        self.assertEqual("Watchlist", self.window.table.item(0, 1).text())
        self.assertFalse(self.window.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)

        self.window.return_to_current_dashboard()

        self.assertIn("CURRENT DASHBOARD - LIVE REVIEW", self.window.view_state_label.text())
        self.assertEqual("CURR", self.window.table.item(0, 4).text())
        self.assertTrue(self.window.mark_interested_button.isEnabled())
        self.assertFalse(self.window.notes_edit.isReadOnly())

    def test_study_dialog_shows_simulated_read_only_context(self) -> None:
        dialogs: list[QDialog] = []

        def capture_dialog(dialog: QDialog) -> int:
            dialogs.append(dialog)
            return 0

        with (
            patch.object(QDialog, "exec", capture_dialog),
            patch("momentum_hunter.app.build_capture_study", return_value=study_summary()),
            patch("momentum_hunter.app.build_study_chart", return_value=QWidget()),
            patch("momentum_hunter.app.build_outcome_chart", return_value=QWidget()),
            patch("momentum_hunter.app.build_historical_cluster_report"),
            patch("momentum_hunter.app.build_historical_recurrence_report"),
            patch("momentum_hunter.app.build_catalyst_cluster_report"),
            patch("momentum_hunter.app.build_catalyst_age_audit_report"),
            patch("momentum_hunter.app.build_headline_dedup_report"),
            patch("momentum_hunter.app.build_outcome_explorer_report"),
            patch("momentum_hunter.app.build_outcome_maturity_report"),
            patch("momentum_hunter.app.build_opportunity_research_report"),
            patch("momentum_hunter.app.build_historical_cluster_panel", return_value=QWidget()),
            patch("momentum_hunter.app.build_catalyst_cluster_panel", return_value=QWidget()),
            patch("momentum_hunter.app.build_catalyst_age_panel", return_value=QWidget()),
            patch("momentum_hunter.app.build_headline_dedup_panel", return_value=QWidget()),
            patch("momentum_hunter.app.build_outcome_explorer_panel", return_value=QWidget()),
            patch("momentum_hunter.app.build_outcome_maturity_panel", return_value=QWidget()),
            patch("momentum_hunter.app.build_opportunity_research_panel", return_value=QWidget()),
            patch("momentum_hunter.app.build_recommendation_panel", return_value=QWidget()),
            patch("momentum_hunter.app.build_weight_recommendations"),
        ):
            self.window._show_study_dialog(study_summary())

        labels = [label.text() for label in dialogs[0].findChildren(QLabel)]
        tables = dialogs[0].findChildren(QTableWidget)

        self.assertTrue(any("STUDY RESULTS - SIMULATED HISTORICAL DATA" in text for text in labels))
        self.assertTrue(any("Research only. These results are not live market data." in text for text in labels))
        self.assertGreaterEqual(len(tables), 2)
        self.assertTrue(any(table.columnCount() == 6 and table.rowCount() == 4 for table in tables))
        self.assertTrue(any(table.columnCount() == 2 and table.rowCount() == 1 for table in tables))


def candidate(ticker: str, score: int) -> Candidate:
    return Candidate(
        ticker=ticker,
        company=f"{ticker} Corp",
        price=42.0,
        percent_change=6.5,
        volume=12_000_000,
        relative_volume=1.8,
        market_cap=20_000_000_000,
        sector="Technology",
        industry="Software",
        news=[NewsItem(headline=f"{ticker} announces AI expansion", url="https://example.com/news")],
        score=score,
        score_reasons=["test catalyst"],
    )


def candidate_payload(ticker: str, score: int) -> dict:
    item = candidate(ticker, score)
    return {
        "ticker": item.ticker,
        "company": item.company,
        "price": item.price,
        "percent_change": item.percent_change,
        "volume": item.volume,
        "relative_volume": item.relative_volume,
        "market_cap": item.market_cap,
        "sector": item.sector,
        "industry": item.industry,
        "news": [
            {
                "headline": news.headline,
                "source": news.source,
                "published_at": None,
                "url": news.url,
                "summary": news.summary,
            }
            for news in item.news
        ],
        "score": item.score,
        "score_reasons": item.score_reasons,
        "score_profile": "regime-aware-v1",
        "score_regime": "bull",
        "user_notes": "",
        "saved_at": None,
    }


def study_summary() -> StudySummary:
    return StudySummary(
        run_id="2026-06-03_study_v1",
        source_range="2026-06-01 to 2026-06-03",
        capture_count=2,
        candidate_count=5,
        selected_count=1,
        reviewed_count=2,
        scoring_profiles=["regime-aware-v1"],
        outcome_count=1,
        complete_outcome_count=1,
        avg_next_day_return_pct=1.25,
        avg_five_day_return_pct=3.5,
        next_day_win_rate_pct=100.0,
        five_day_win_rate_pct=100.0,
        score_buckets=[
            ScoreBucketSummary(label="0-49", count=0),
            ScoreBucketSummary(label="50-69", count=1),
            ScoreBucketSummary(label="70-84", count=2, selected_count=1),
            ScoreBucketSummary(label="85-100", count=2, reviewed_count=2),
        ],
        regimes=[RegimeSummary(regime="bull", count=5)],
        has_data=True,
    )


if __name__ == "__main__":
    unittest.main()
