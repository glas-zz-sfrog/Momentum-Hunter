from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from momentum_hunter.models import Candidate, NewsItem
from momentum_hunter.news_age import (
    FRESHNESS_ACTIVE,
    FRESHNESS_HOT,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    apply_candidate_news_freshness,
    evaluate_news_freshness,
    format_news_age,
    freshness_badge,
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
