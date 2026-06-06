from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.market import MarketRegimeSnapshot
from momentum_hunter.models import Candidate, CaptureSession, MarketRegime, NewsItem, ScannerCriteria, TradingMode
from momentum_hunter.review import (
    CandidateIdentity,
    ReviewStatus,
    load_review_decisions,
    make_capture_id,
    upsert_review_decision,
)
from momentum_hunter.storage import save_daily_capture
from momentum_hunter.time_utils import CENTRAL_TZ, now_central
from momentum_hunter.ui.data_view_state import DataViewState


class ReviewDecisionPersistenceTests(unittest.TestCase):
    def test_status_persistence_round_trips_by_candidate_identity(self) -> None:
        path = Path.cwd() / "MomentumHunterData" / "data" / "_test-review-decisions.json"
        if path.exists():
            path.unlink()
        identity = CandidateIdentity(
            capture_id=make_capture_id("2026-06-05", "live", "finviz", "Base Momentum"),
            capture_date="2026-06-05",
            session="live",
            provider="finviz",
            scanner="Base Momentum",
            ticker="MDT",
        )

        decisions = {}
        upsert_review_decision(
            decisions,
            identity,
            ReviewStatus.INTERESTED,
            note="Watch over high of day.",
            decision_timestamp=datetime(2026, 6, 5, 7, 15, tzinfo=CENTRAL_TZ),
            path=path,
        )

        loaded = load_review_decisions(path=path)

        self.assertEqual(ReviewStatus.INTERESTED, loaded[identity.key].review_status)
        self.assertEqual("Watch over high of day.", loaded[identity.key].decision_note)
        path.unlink()

    def test_raw_capture_does_not_receive_review_status_fields(self) -> None:
        data_dir = Path.cwd() / "MomentumHunterData" / "data"
        json_path = data_dir / "_test-review-capture.json"
        report_path = data_dir / "_test-review-capture.md"
        manifest_path = data_dir / "_test-review-capture-manifest.json"
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
                selected_tickers={"MDT"},
                reviewed_tickers={"MDT"},
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

        payload = json.loads(saved_json.read_text(encoding="utf-8"))
        candidate_payload = payload["candidates"][0]

        self.assertNotIn("review_status", candidate_payload)
        self.assertNotIn("decision_timestamp", candidate_payload)
        self.assertNotIn("decision_note", candidate_payload)
        self.assertNotIn("selected", candidate_payload)
        self.assertNotIn("reviewed", candidate_payload)
        self.assertNotIn("user_notes", candidate_payload)
        self.assertNotIn("score_reasons", candidate_payload)
        self.assertNotIn("integrity", payload)
        json_path.unlink()
        report_path.unlink()
        manifest_path.unlink()


class ReviewWorkflowGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.review_path = Path.cwd() / "MomentumHunterData" / "data" / "_test-review-gui.json"
        if self.review_path.exists():
            self.review_path.unlink()
        self.patches = [
            patch("momentum_hunter.review.REVIEW_DECISIONS_PATH", self.review_path),
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
        self.window.candidates = [make_candidate("MDT", 96), make_candidate("RXT", 73)]
        self.window.live_candidates = list(self.window.candidates)
        self.window._apply_data_view_state()
        self.window._populate_table()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        for patcher in reversed(self.patches):
            patcher.stop()
        if self.review_path.exists():
            self.review_path.unlink()

    def test_bulk_actions_persist_statuses_and_promote_interested_to_watchlist(self) -> None:
        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.window.mark_interested_candidates()

        self.assertEqual("Interested", self.window.table.item(0, 1).text())

        self.window.table.item(1, 0).setCheckState(Qt.CheckState.Checked)
        self.window.mark_rejected_candidates()
        self.assertEqual("Rejected", self.window.table.item(1, 1).text())

        self.window.add_interested_to_watchlist()

        self.assertEqual("Watchlist", self.window.table.item(0, 1).text())
        self.assertEqual("Rejected", self.window.table.item(1, 1).text())
        decisions = load_review_decisions(path=self.review_path)
        statuses = {decision.identity.ticker: decision.review_status for decision in decisions.values()}
        self.assertEqual(ReviewStatus.WATCHLIST, statuses["MDT"])
        self.assertEqual(ReviewStatus.REJECTED, statuses["RXT"])

    def test_historical_view_is_read_only_for_review_status(self) -> None:
        self.window._load_historical_capture(
            {
                "capture_time": (now_central() - timedelta(days=2)).isoformat(),
                "capture_date": (now_central() - timedelta(days=2)).strftime("%Y-%m-%d"),
                "session": "evening",
                "provider": "finviz",
                "scanner": {"name": "Base Momentum"},
                "candidates": [
                    {
                        **candidate_payload("HIST", 82),
                        "selected": False,
                        "reviewed": False,
                    }
                ],
            }
        )

        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.window.mark_interested_candidates()

        self.assertEqual("Unreviewed", self.window.table.item(0, 1).text())
        self.assertFalse(load_review_decisions(path=self.review_path))
        self.assertIn("read-only", self.window.status_label.text())

    def test_watchlist_report_defaults_to_watchlist_candidates(self) -> None:
        self.window._set_candidate_review_status(self.window.candidates[0], ReviewStatus.WATCHLIST)
        self.window._set_candidate_review_status(self.window.candidates[1], ReviewStatus.INTERESTED)

        watchlist = self.window._watchlist_candidates()

        self.assertEqual(["MDT"], [candidate.ticker for candidate in watchlist])


def make_candidate(ticker: str, score: int) -> Candidate:
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
    item = make_candidate(ticker, score)
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


if __name__ == "__main__":
    unittest.main()
