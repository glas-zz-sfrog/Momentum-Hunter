from __future__ import annotations

import unittest

from momentum_hunter.study import FILTER_SELECTED, StudyFilter, bucket_for_score, summarize_capture_rows


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

    def test_summarizes_outcome_returns(self) -> None:
        summary = summarize_capture_rows(
            [
                {
                    "capture_date": "2026-06-01",
                    "capture_time": "2026-06-01T07:00:00-05:00",
                    "session": "morning",
                    "market_regime": "bull",
                    "score": "90",
                    "selected": "false",
                    "reviewed": "false",
                    "next_day_return_pct": "2.0",
                    "five_day_return_pct": "4.0",
                },
                {
                    "capture_date": "2026-06-01",
                    "capture_time": "2026-06-01T07:00:00-05:00",
                    "session": "morning",
                    "market_regime": "bull",
                    "score": "88",
                    "selected": "false",
                    "reviewed": "false",
                    "next_day_return_pct": "-1.0",
                    "five_day_return_pct": "2.0",
                },
            ]
        )

        self.assertEqual(2, summary.outcome_count)
        self.assertEqual(2, summary.complete_outcome_count)
        self.assertEqual(0.5, summary.avg_next_day_return_pct)
        self.assertEqual(3.0, summary.avg_five_day_return_pct)
        self.assertEqual(100.0, summary.five_day_win_rate_pct)

    def test_combines_date_session_and_regime_filters(self) -> None:
        rows = [
            {
                "capture_date": "2026-06-01",
                "capture_time": "2026-06-01T07:00:00-05:00",
                "session": "morning",
                "market_regime": "bull",
                "score": "90",
                "selected": "false",
                "reviewed": "false",
            },
            {
                "capture_date": "2026-06-02",
                "capture_time": "2026-06-02T19:00:00-05:00",
                "session": "evening",
                "market_regime": "bear",
                "score": "90",
                "selected": "false",
                "reviewed": "false",
            },
            {
                "capture_date": "2026-06-03",
                "capture_time": "2026-06-03T19:00:00-05:00",
                "session": "evening",
                "market_regime": "bull",
                "score": "90",
                "selected": "false",
                "reviewed": "false",
            },
        ]

        summary = summarize_capture_rows(
            rows,
            study_filter=StudyFilter(start_date="2026-06-02", end_date="2026-06-03", session="evening", regime="bull"),
        )

        self.assertEqual(1, summary.candidate_count)
        self.assertIn("2026-06-02 to 2026-06-03", summary.source_range)
        self.assertIn("evening", summary.source_range)
        self.assertIn("bull", summary.source_range)


if __name__ == "__main__":
    unittest.main()
