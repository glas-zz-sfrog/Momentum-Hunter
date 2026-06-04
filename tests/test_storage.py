from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta

from momentum_hunter.models import Candidate, NewsItem
from momentum_hunter.news_age import apply_candidate_news_stack
from momentum_hunter.storage import candidate_from_dict, candidate_to_dict
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


if __name__ == "__main__":
    unittest.main()
