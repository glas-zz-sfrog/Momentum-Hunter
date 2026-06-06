from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.market import MarketRegimeSnapshot
from momentum_hunter.models import BASE_MOMENTUM, Candidate, CaptureSession, MarketRegime, NewsItem, TradingMode
from momentum_hunter.news_age import apply_candidate_news_stack
from momentum_hunter.storage import candidate_from_dict, candidate_to_dict, load_latest_capture_failure, save_capture_failure, save_daily_capture
from momentum_hunter.time_utils import CENTRAL_TZ


class StorageSerializationTests(unittest.TestCase):
    def test_candidate_news_stack_round_trips_through_json_payload(self) -> None:
        now = datetime(2026, 6, 4, 12, 0, tzinfo=CENTRAL_TZ)
        candidate = Candidate(
            ticker="MDT",
            news=[
                NewsItem(
                    headline="Medtronic stock jumps on strong earnings",
                    published_at=now - timedelta(minutes=32),
                    url="https://example.com/mdt",
                ),
                NewsItem(
                    headline="Medtronic reports strongest annual revenue growth",
                    published_at=now - timedelta(hours=18),
                ),
            ],
        )
        apply_candidate_news_stack(candidate, now=now)

        payload = json.loads(json.dumps(candidate_to_dict(candidate)))
        restored = candidate_from_dict(payload)

        self.assertEqual(2, restored.news_stack.article_count)
        self.assertEqual(0.53, restored.news_stack.latest_article_age_hours)
        self.assertEqual(18.0, restored.news_stack.oldest_article_age_hours)
        self.assertEqual("Medtronic stock jumps on strong earnings", restored.news_stack.freshest_headline)
        self.assertEqual("HOT", restored.news_stack.freshness)

    def test_daily_capture_does_not_preserve_future_news_rows(self) -> None:
        capture_time = datetime(2026, 6, 4, 7, 0, tzinfo=CENTRAL_TZ)
        candidate = Candidate(
            ticker="LEAK",
            price=25.0,
            percent_change=6.0,
            volume=10_000_000,
            market_cap=5_000_000_000,
            news=[
                NewsItem(headline="Known premarket headline", published_at=capture_time - timedelta(minutes=30)),
                NewsItem(headline="Unknown timestamp headline"),
                NewsItem(headline="Later scraped headline", published_at=capture_time + timedelta(hours=5)),
            ],
            score=80,
        )

        data_dir = Path.cwd() / "MomentumHunterData" / "data"
        json_path = data_dir / "_test_future_capture.json"
        report_path = data_dir / "_test_future_capture.md"
        manifest_path = data_dir / "_test_future_capture_manifest.json"
        try:
            with (
                patch("momentum_hunter.storage.capture_json_path", return_value=json_path),
                patch("momentum_hunter.storage.capture_report_path", return_value=report_path),
                patch("momentum_hunter.storage.CAPTURE_INTEGRITY_MANIFEST", manifest_path),
                patch("momentum_hunter.storage.append_analysis_rows", lambda payload: None),
            ):
                saved_json_path, _ = save_daily_capture(
                    candidates=[candidate],
                    selected_tickers=set(),
                    reviewed_tickers=set(),
                    criteria=BASE_MOMENTUM,
                    provider="test",
                    mode=TradingMode.PAPER,
                    session=CaptureSession.MORNING,
                    market_regime=MarketRegimeSnapshot(MarketRegime.BULL, "SPY"),
                    capture_time=capture_time,
                )

            payload = json.loads(saved_json_path.read_text(encoding="utf-8"))
        finally:
            json_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)

        saved_candidate = payload["candidates"][0]
        headlines = [item["headline"] for item in saved_candidate["news"]]
        self.assertIn("Known premarket headline", headlines)
        self.assertIn("Unknown timestamp headline", headlines)
        self.assertNotIn("Later scraped headline", headlines)
        self.assertEqual(2, saved_candidate["article_count"])
        self.assertEqual(1, saved_candidate["valid_timestamp_count"])
        self.assertEqual(1, saved_candidate["unknown_timestamp_count"])
        self.assertEqual(0, saved_candidate["future_timestamp_count"])
        self.assertEqual(1, saved_candidate["excluded_from_scoring_count"])
        self.assertEqual("Known premarket headline", saved_candidate["freshest_headline"])
        self.assertIn("created_at", payload["integrity"])
        self.assertRegex(payload["integrity"]["source_hash"], r"^[0-9a-f]{64}$")
        self.assertNotIn("selected", saved_candidate)
        self.assertNotIn("reviewed", saved_candidate)
        self.assertNotIn("user_notes", saved_candidate)
        self.assertNotIn("score_reasons", saved_candidate)

    def test_capture_failure_record_round_trips_for_dashboard_health(self) -> None:
        failure_dir = Path.cwd() / "MomentumHunterData" / "data" / "_test_capture_failures"
        try:
            with patch("momentum_hunter.storage.CAPTURE_FAILURES_DIR", failure_dir):
                path = save_capture_failure(
                    session=CaptureSession.MORNING,
                    provider="finviz",
                    scanner="Base Momentum",
                    error_message="Provider unavailable / DNS failure while running finviz scan.",
                    exception_type="ProviderUnavailableError",
                    traceback_text="full traceback",
                    failure_time=datetime(2026, 6, 5, 7, 0, tzinfo=CENTRAL_TZ),
                )
                loaded = load_latest_capture_failure()

            self.assertTrue(path.exists())
            self.assertEqual("failure", loaded["status"])
            self.assertEqual("finviz", loaded["provider"])
            self.assertIn("DNS failure", loaded["error_message"])
            self.assertEqual("full traceback", loaded["traceback"])
        finally:
            for child in failure_dir.glob("*"):
                child.unlink()
            failure_dir.rmdir()


if __name__ == "__main__":
    unittest.main()
