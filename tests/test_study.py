from __future__ import annotations

import unittest

from momentum_hunter.study import FILTER_SELECTED, bucket_for_score, summarize_capture_rows


class StudySummaryTests(unittest.TestCase):
    def test_score_bucket_boundaries(self) -> None:
        self.assertEqual("0-49", bucket_for_score(49))
        self.assertEqual("50-69", bucket_for_score(50))
        self.assertEqual("70-84", bucket_for_score(84))
        self.assertEqual("85-100", bucket_for_score(100))

    def test_summarizes_capture_rows(self) -> None:
        summary = summarize_capture_rows(
            [
                {
                    "capture_date": "2026-06-01",
                    "capture_time": "2026-06-01T07:00:00-05:00",
                    "session": "morning",
                    "market_regime": "bull",
                    "score": "96",
                    "selected": "true",
                    "reviewed": "true",
                },
                {
                    "capture_date": "2026-06-02",
                    "capture_time": "2026-06-02T19:00:00-05:00",
                    "session": "evening",
                    "market_regime": "bear",
                    "score": "72",
                    "selected": "false",
                    "reviewed": "true",
                },
            ]
        )

        self.assertTrue(summary.has_data)
        self.assertEqual(2, summary.capture_count)
        self.assertEqual(2, summary.candidate_count)
        self.assertEqual(1, summary.selected_count)
        self.assertEqual("2026-06-01 to 2026-06-02 | Filter: all candidates", summary.source_range)
        self.assertEqual({"bear": 1, "bull": 1}, {item.regime: item.count for item in summary.regimes})

    def test_filters_to_selected_rows(self) -> None:
        summary = summarize_capture_rows(
            [
                {
                    "capture_date": "2026-06-01",
                    "capture_time": "2026-06-01T07:00:00-05:00",
                    "session": "morning",
                    "market_regime": "bull",
                    "score": "96",
                    "selected": "true",
                    "reviewed": "true",
                },
                {
                    "capture_date": "2026-06-01",
                    "capture_time": "2026-06-01T07:00:00-05:00",
                    "session": "morning",
                    "market_regime": "bull",
                    "score": "72",
                    "selected": "false",
                    "reviewed": "true",
                },
            ],
            row_filter=FILTER_SELECTED,
        )

        self.assertEqual(1, summary.candidate_count)
        self.assertEqual(1, summary.selected_count)
        self.assertIn("selected only", summary.source_range)


if __name__ == "__main__":
    unittest.main()
