from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from momentum_hunter.models import Candidate, NewsItem
from momentum_hunter.news_age import (
    FRESHNESS_ACTIVE,
    FRESHNESS_FUTURE,
    FRESHNESS_HOT,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    apply_candidate_news_freshness,
    build_news_stack,
    evaluate_news_freshness,
    format_news_age,
    format_news_range,
    freshness_badge,
    news_stack_badge,
)
from momentum_hunter.providers import parse_finviz_news_time
from momentum_hunter.time_utils import CENTRAL_TZ


class NewsAgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 6, 4, 12, 0, tzinfo=CENTRAL_TZ)

    def test_hot_headline_scores_near_top(self) -> None:
        result = evaluate_news_freshness(
            ticker="MDT",
            headline="MDT beats earnings and raises guidance",
            publish_time=self.now - timedelta(hours=11),
            now=self.now,
        )

        self.assertEqual(11, int(result.hours_old or 0))
        self.assertEqual(FRESHNESS_HOT, result.freshness)
        self.assertEqual(98, result.score)

    def test_old_headline_is_stale(self) -> None:
        result = evaluate_news_freshness(
            ticker="RXT",
            headline="RXT announces AMD partnership",
            publish_time=self.now - timedelta(days=28),
            now=self.now,
        )

        self.assertEqual(FRESHNESS_STALE, result.freshness)
        self.assertEqual(10, result.score)
        self.assertEqual("28d", format_news_age(result.hours_old))

    def test_unknown_publish_time_is_not_treated_as_fresh(self) -> None:
        result = evaluate_news_freshness(
            ticker="UNK",
            headline="No timestamp headline",
            publish_time=None,
            now=self.now,
        )

        self.assertIsNone(result.hours_old)
        self.assertEqual(FRESHNESS_UNKNOWN, result.freshness)
        self.assertEqual(0, result.score)

    def test_future_publish_time_is_excluded_from_scoring(self) -> None:
        result = evaluate_news_freshness(
            ticker="LEAK",
            headline="Future headline",
            publish_time=self.now + timedelta(hours=2),
            now=self.now,
        )

        self.assertEqual(FRESHNESS_FUTURE, result.freshness)
        self.assertEqual(0, result.score)
        self.assertTrue(result.excluded_from_scoring)

    def test_candidate_uses_freshest_known_headline(self) -> None:
        candidate = Candidate(
            ticker="TEST",
            news=[
                NewsItem(headline="Old partnership story", published_at=self.now - timedelta(days=20)),
                NewsItem(headline="Fresh earnings beat", published_at=self.now - timedelta(hours=9)),
            ],
        )

        apply_candidate_news_freshness(candidate, now=self.now)

        self.assertEqual(FRESHNESS_HOT, candidate.freshness)
        self.assertGreaterEqual(candidate.freshness_score, 98)
        self.assertIn("HOT", freshness_badge(candidate))

    def test_news_stack_tracks_count_range_and_freshest_headline(self) -> None:
        candidate = Candidate(
            ticker="MDT",
            news=[
                NewsItem(headline="Medtronic reports strongest annual revenue growth", published_at=self.now - timedelta(hours=18)),
                NewsItem(headline="Medtronic stock jumps on strong earnings", published_at=self.now - timedelta(minutes=32)),
                NewsItem(headline="Headline without timestamp"),
            ],
        )

        stack = build_news_stack(candidate, now=self.now)

        self.assertEqual(3, stack.article_count)
        self.assertEqual(2, stack.known_timestamp_count)
        self.assertEqual(1, stack.unknown_timestamp_count)
        self.assertEqual("Medtronic stock jumps on strong earnings", stack.freshest_headline)
        self.assertEqual("32m-18h", format_news_range(stack))

    def test_news_stack_badge_summarizes_latest_count_and_range(self) -> None:
        candidate = Candidate(
            ticker="MDT",
            news=[
                NewsItem(headline="Older headline", published_at=self.now - timedelta(hours=18)),
                NewsItem(headline="Fresh headline", published_at=self.now - timedelta(minutes=32)),
            ],
        )

        apply_candidate_news_freshness(candidate, now=self.now)

        self.assertEqual("HOT 32m | 2 | 32m-18h", news_stack_badge(candidate))

    def test_news_stack_ignores_future_and_unknown_rows_for_candidate_freshness(self) -> None:
        candidate = Candidate(
            ticker="SAFE",
            news=[
                NewsItem(headline="Future headline", published_at=self.now + timedelta(hours=4)),
                NewsItem(headline="Valid headline", published_at=self.now - timedelta(hours=5)),
                NewsItem(headline="Unknown timestamp headline"),
            ],
        )

        stack = build_news_stack(candidate, now=self.now)

        self.assertEqual("Valid headline", stack.freshest_headline)
        self.assertEqual(1, stack.valid_timestamp_count)
        self.assertEqual(1, stack.future_timestamp_count)
        self.assertEqual(1, stack.unknown_timestamp_count)
        self.assertEqual(2, stack.excluded_from_scoring_count)
        self.assertEqual(FRESHNESS_HOT, stack.freshness)

    def test_active_window_between_one_and_seven_days(self) -> None:
        result = evaluate_news_freshness(
            ticker="ACT",
            headline="Three day old catalyst",
            publish_time=self.now - timedelta(days=3),
            now=self.now,
        )

        self.assertEqual(FRESHNESS_ACTIVE, result.freshness)

    def test_parse_finviz_news_time(self) -> None:
        today = parse_finviz_news_time("Today 08:15AM", now=self.now)
        dated = parse_finviz_news_time("Jun-03-26 07:30PM", now=self.now)

        self.assertEqual(datetime(2026, 6, 4, 8, 15, tzinfo=CENTRAL_TZ), today)
        self.assertEqual(datetime(2026, 6, 3, 19, 30, tzinfo=CENTRAL_TZ), dated)


if __name__ == "__main__":
    unittest.main()
