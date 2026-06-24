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

    def test_dashboard_interested_candidate_updates_watchlist_center_immediately(self) -> None:
        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.window.mark_interested_candidates()

        self.window._navigate_to_page(1)
        self.assertIn("Interested: 1", self.window.watchlist_center_summary_label.text())
        self.assertEqual("MDT", self.window.watchlist_center_table.item(0, 0).text())
        self.assertEqual("Interested", self.window.watchlist_center_table.item(0, 1).text())

        self.window.add_interested_to_watchlist()

        self.assertIn("Interested: 0", self.window.watchlist_center_summary_label.text())
        self.assertIn("Watchlist: 1", self.window.watchlist_center_summary_label.text())
        self.assertEqual("Watchlist", self.window.watchlist_center_table.item(0, 1).text())
        decisions = load_review_decisions(path=self.review_path)
        statuses = {decision.identity.ticker: decision.review_status for decision in decisions.values()}
        self.assertEqual(ReviewStatus.WATCHLIST, statuses["MDT"])

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

        blocked_messages: list[str] = []
        with patch.object(self.window, "_show_action_blocked", lambda message, title="Action Not Available": blocked_messages.append(message)):
            self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
            self.window.mark_interested_candidates()

        self.assertEqual("Unreviewed", self.window.table.item(0, 1).text())
        self.assertFalse(load_review_decisions(path=self.review_path))
        self.assertTrue(any("historical" in message.lower() for message in blocked_messages))

    def test_aged_valid_evening_snapshot_allows_review_and_stores_delayed_metadata(self) -> None:
        capture_time = datetime(2026, 6, 8, 19, 0, tzinfo=CENTRAL_TZ)
        review_time = datetime(2026, 6, 9, 0, 30, tzinfo=CENTRAL_TZ)

        with (
            patch("momentum_hunter.operator_review.now_central", return_value=review_time),
            patch("momentum_hunter.ui.data_view_state.now_central", return_value=review_time),
        ):
            self.window._load_historical_capture(
                reviewable_payload("MDT", 96, capture_time, "evening", "2026-06-09")
            )

        self.assertIn("AGING BUT REVIEWABLE", self.window.view_state_label.text())
        self.assertTrue(self.window.mark_interested_button.isEnabled())
        self.assertFalse(self.window.entry_trigger.isReadOnly())

        self.window.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        self.window.mark_interested_candidates()

        decisions = load_review_decisions(path=self.review_path)
        decision = next(iter(decisions.values()))
        self.assertEqual(ReviewStatus.INTERESTED, decision.review_status)
        self.assertTrue(decision.delayed_review)
        self.assertEqual("AGING_BUT_REVIEWABLE", decision.review_context_state)
        self.assertGreaterEqual(decision.review_delay_minutes or 0, 300)

    def test_aged_valid_preopen_snapshot_allows_entry_plan_fields(self) -> None:
        capture_time = datetime(2026, 6, 7, 19, 0, tzinfo=CENTRAL_TZ)
        review_time = datetime(2026, 6, 8, 1, 0, tzinfo=CENTRAL_TZ)

        with (
            patch("momentum_hunter.operator_review.now_central", return_value=review_time),
            patch("momentum_hunter.ui.data_view_state.now_central", return_value=review_time),
        ):
            self.window._load_historical_capture(
                reviewable_payload("GAP", 91, capture_time, "preopen", "2026-06-08")
            )

        self.assertIn("AGING BUT REVIEWABLE", self.window.view_state_label.text())
        self.assertFalse(self.window.entry_trigger.isReadOnly())
        self.assertTrue(self.window.plan_complete_checkbox.isEnabled())

    def test_aged_review_watchlist_report_requires_acknowledgement(self) -> None:
        capture_time = datetime(2026, 6, 8, 19, 0, tzinfo=CENTRAL_TZ)
        review_time = datetime(2026, 6, 9, 0, 30, tzinfo=CENTRAL_TZ)

        with (
            patch("momentum_hunter.operator_review.now_central", return_value=review_time),
            patch("momentum_hunter.ui.data_view_state.now_central", return_value=review_time),
        ):
            self.window._load_historical_capture(
                reviewable_payload("MDT", 96, capture_time, "evening", "2026-06-09")
            )
        self.window._set_candidate_review_status(self.window.candidates[0], ReviewStatus.WATCHLIST)

        with (
            patch.object(self.window, "_confirm_aging_review_watchlist", return_value=True) as confirm,
            patch("momentum_hunter.app.save_watchlist", return_value=Path("watchlist.json")) as save_watchlist_mock,
            patch("momentum_hunter.app.save_watchlist_report", return_value=Path("watchlist.md")),
            patch.object(self.window, "capture_daily_snapshot", lambda *args, **kwargs: None),
            patch("momentum_hunter.app.QMessageBox.information"),
        ):
            self.window.save_tomorrow_watchlist()

        confirm.assert_called_once()
        save_watchlist_mock.assert_called_once()

    def test_cancelled_aged_review_acknowledgement_prevents_watchlist_report(self) -> None:
        capture_time = datetime(2026, 6, 8, 19, 0, tzinfo=CENTRAL_TZ)
        review_time = datetime(2026, 6, 9, 0, 30, tzinfo=CENTRAL_TZ)

        with (
            patch("momentum_hunter.operator_review.now_central", return_value=review_time),
            patch("momentum_hunter.ui.data_view_state.now_central", return_value=review_time),
        ):
            self.window._load_historical_capture(
                reviewable_payload("MDT", 96, capture_time, "evening", "2026-06-09")
            )
        self.window._set_candidate_review_status(self.window.candidates[0], ReviewStatus.WATCHLIST)

        with (
            patch.object(self.window, "_confirm_aging_review_watchlist", return_value=False),
            patch("momentum_hunter.app.save_watchlist") as save_watchlist_mock,
        ):
            self.window.save_tomorrow_watchlist()

        save_watchlist_mock.assert_not_called()

    def test_expired_review_snapshot_blocks_trading_workflow_with_reason(self) -> None:
        capture_time = datetime(2026, 6, 8, 19, 0, tzinfo=CENTRAL_TZ)
        review_time = datetime(2026, 6, 9, 8, 31, tzinfo=CENTRAL_TZ)
        blocked_messages: list[str] = []

        with (
            patch("momentum_hunter.operator_review.now_central", return_value=review_time),
            patch("momentum_hunter.ui.data_view_state.now_central", return_value=review_time),
        ):
            self.window._load_historical_capture(
                reviewable_payload("MDT", 96, capture_time, "evening", "2026-06-09")
            )

        self.assertIn("EXPIRED REVIEW SNAPSHOT - READ ONLY", self.window.view_state_label.text())
        self.assertFalse(self.window.mark_interested_button.isEnabled())
        with patch.object(self.window, "_show_action_blocked", lambda message, title="Action Not Available": blocked_messages.append(message)):
            self.window.table.selectRow(0)
            self.window.mark_interested_candidates()

        self.assertTrue(any("expired" in message.lower() for message in blocked_messages))

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


def reviewable_payload(
    ticker: str,
    score: int,
    capture_time: datetime,
    session: str,
    next_market_session_date: str,
) -> dict:
    return {
        "schema_version": 2,
        "capture_time": capture_time.isoformat(),
        "capture_date": capture_time.strftime("%Y-%m-%d"),
        "session": session,
        "capture_session": session,
        "capture_calendar_status": "PREOPEN_GAP_REVIEW_DAY" if session == "preopen" else "MARKET_OPEN_DAY",
        "is_market_open_day": session != "preopen",
        "is_study_eligible": session == "evening",
        "next_market_session_date": next_market_session_date,
        "scheduling_policy_version": "market-calendar-v1",
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": "Base Momentum"},
        "candidates": [candidate_payload(ticker, score)],
    }


if __name__ == "__main__":
    unittest.main()
