from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from momentum_hunter.time_utils import CENTRAL_TZ
from tools.export_news_freshness_audit import audit_freshness, update_summary_counts


class NewsFreshnessAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.captured_at = datetime(2026, 6, 4, 7, 0, tzinfo=CENTRAL_TZ)

    def test_future_timestamp_is_marked_and_excluded(self) -> None:
        age_hours, score, bucket = audit_freshness(
            ticker="LEAK",
            headline="Future headline",
            published_at=self.captured_at + timedelta(hours=2),
            captured_at=self.captured_at,
        )

        self.assertEqual(-2.0, age_hours)
        self.assertEqual(0, score)
        self.assertEqual("FUTURE_TIMESTAMP", bucket)

    def test_unknown_timestamp_is_not_hot(self) -> None:
        age_hours, score, bucket = audit_freshness(
            ticker="UNK",
            headline="Unknown headline",
            published_at=None,
            captured_at=self.captured_at,
        )

        self.assertIsNone(age_hours)
        self.assertEqual(0, score)
        self.assertEqual("UNKNOWN", bucket)

    def test_summary_counts_valid_unknown_future_and_excluded_rows(self) -> None:
        summary = {
            "valid timestamp rows": 0,
            "unknown timestamp rows": 0,
            "future timestamp rows": 0,
            "excluded-from-scoring rows": 0,
        }

        update_summary_counts(summary, "HOT")
        update_summary_counts(summary, "UNKNOWN")
        update_summary_counts(summary, "FUTURE_TIMESTAMP")

        self.assertEqual(1, summary["valid timestamp rows"])
        self.assertEqual(1, summary["unknown timestamp rows"])
        self.assertEqual(1, summary["future timestamp rows"])
        self.assertEqual(2, summary["excluded-from-scoring rows"])


if __name__ == "__main__":
    unittest.main()
