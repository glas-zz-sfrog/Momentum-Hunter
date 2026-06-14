from __future__ import annotations

import unittest
from datetime import datetime

from momentum_hunter.operator_review import (
    OperatorReviewState,
    classify_scheduled_snapshot,
)
from momentum_hunter.time_utils import CENTRAL_TZ


class OperatorReviewStateTests(unittest.TestCase):
    def test_aged_evening_snapshot_before_next_open_is_reviewable(self) -> None:
        context = classify_scheduled_snapshot(
            capture_time=datetime(2026, 6, 8, 19, 0, tzinfo=CENTRAL_TZ),
            session="evening",
            next_market_session_date="2026-06-09",
            freshness_threshold_minutes=20,
            now=datetime(2026, 6, 9, 0, 30, tzinfo=CENTRAL_TZ),
        )

        self.assertEqual(OperatorReviewState.AGING_BUT_REVIEWABLE, context.state)
        self.assertTrue(context.can_review)
        self.assertTrue(context.can_generate_watchlist)
        self.assertTrue(context.acknowledgement_required)

    def test_aged_preopen_snapshot_before_next_open_is_reviewable(self) -> None:
        context = classify_scheduled_snapshot(
            capture_time=datetime(2026, 6, 7, 19, 0, tzinfo=CENTRAL_TZ),
            session="preopen",
            next_market_session_date="2026-06-08",
            freshness_threshold_minutes=20,
            now=datetime(2026, 6, 8, 1, 0, tzinfo=CENTRAL_TZ),
        )

        self.assertEqual(OperatorReviewState.AGING_BUT_REVIEWABLE, context.state)
        self.assertTrue(context.can_review)

    def test_snapshot_expires_at_market_open_cutoff(self) -> None:
        context = classify_scheduled_snapshot(
            capture_time=datetime(2026, 6, 8, 19, 0, tzinfo=CENTRAL_TZ),
            session="evening",
            next_market_session_date="2026-06-09",
            freshness_threshold_minutes=20,
            now=datetime(2026, 6, 9, 8, 30, tzinfo=CENTRAL_TZ),
        )

        self.assertEqual(OperatorReviewState.EXPIRED_REVIEW_SNAPSHOT, context.state)
        self.assertFalse(context.can_review)
        self.assertFalse(context.can_generate_watchlist)

    def test_quarantined_snapshot_blocks_workflow(self) -> None:
        context = classify_scheduled_snapshot(
            capture_time=datetime(2026, 6, 8, 19, 0, tzinfo=CENTRAL_TZ),
            session="evening",
            next_market_session_date="2026-06-09",
            freshness_threshold_minutes=20,
            now=datetime(2026, 6, 9, 0, 30, tzinfo=CENTRAL_TZ),
            quarantined=True,
        )

        self.assertEqual(OperatorReviewState.QUARANTINED_BLOCKED, context.state)
        self.assertFalse(context.can_review)


if __name__ == "__main__":
    unittest.main()
