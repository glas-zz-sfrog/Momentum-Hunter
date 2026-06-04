from __future__ import annotations

import unittest
from datetime import timedelta
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QDialog, QTableWidget

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.models import Candidate, NewsItem
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
        ]
        for patcher in self.patches:
            patcher.start()
        self.window = MomentumHunterWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        for patcher in reversed(self.patches):
            patcher.stop()

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
        self.assertTrue(self.window.save_button.isEnabled())
        self.assertFalse(self.window.notes_edit.isReadOnly())
        self.assertTrue(self.window.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)

    def test_stale_current_dashboard_blocks_staging_actions(self) -> None:
        self.window.data_view_state = DataViewState.CURRENT
        self.window.display_capture_time = now_central() - timedelta(days=1)
        self.window.display_session_label = "live"
        self.window.candidates = [candidate("OLD", score=75)]

        self.window._apply_data_view_state()
        self.window._populate_table()
        self.window.save_selected_candidates()

        self.assertIn("STALE DATA - REFRESH REQUIRED", self.window.view_state_label.text())
        self.assertEqual("STALE - Top Momentum Candidates", self.window.chart_state_label.text())
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertTrue(self.window.notes_edit.isReadOnly())
        self.assertFalse(self.window.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertIn("read-only", self.window.status_label.text())

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
        self.assertEqual("NEW", self.window.table.item(0, 3).text())
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
        self.assertFalse(self.window.save_button.isEnabled())
        self.assertTrue(self.window.notes_edit.isReadOnly())
        self.assertEqual(Qt.CheckState.Checked, self.window.table.item(0, 0).checkState())
        self.assertFalse(self.window.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)

        self.window.return_to_current_dashboard()

        self.assertIn("CURRENT DASHBOARD - LIVE REVIEW", self.window.view_state_label.text())
        self.assertEqual("CURR", self.window.table.item(0, 3).text())
        self.assertTrue(self.window.save_button.isEnabled())
        self.assertFalse(self.window.notes_edit.isReadOnly())

    def test_study_dialog_shows_simulated_read_only_context(self) -> None:
        dialogs: list[QDialog] = []

        def capture_dialog(dialog: QDialog) -> int:
            dialogs.append(dialog)
            return 0

        with (
            patch.object(QDialog, "exec", capture_dialog),
            patch("momentum_hunter.app.build_capture_study", return_value=study_summary()),
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
