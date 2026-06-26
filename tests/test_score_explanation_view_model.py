from __future__ import annotations

import unittest
from datetime import timedelta

from momentum_hunter.models import Candidate, NewsItem
from momentum_hunter.score_explanation_view_model import (
    compact_score_summary_from_components,
    format_score_breakdown_html,
    format_score_rule,
    format_score_value,
)
from momentum_hunter.time_utils import now_central


class ScoreExplanationViewModelTests(unittest.TestCase):
    def test_formats_human_readable_score_values(self) -> None:
        self.assertEqual("$40.0B", format_score_value("market_cap", 40_000_000_000))
        self.assertEqual("20.0M", format_score_value("volume", 20_000_000))
        self.assertEqual("1.56x", format_score_value("relative_volume", 1.56))
        self.assertEqual("5.2%", format_score_value("percent_change", 5.234))

    def test_formats_rule_thresholds_with_units(self) -> None:
        self.assertEqual(">= $50.0B => +12; >= $5.0B => +9", format_score_rule(">= 50,000,000,000 => +12; >= 5,000,000,000 => +9", "market_cap"))
        self.assertEqual(">= 25.0M => +12; >= 3.0M => +8", format_score_rule(">= 25,000,000 => +12; >= 3,000,000 => +8", "volume"))

    def test_compact_summary_groups_component_prefixes(self) -> None:
        summary = compact_score_summary_from_components(
            [
                {"key": "volume", "points_after_adjustment": 8, "raw_inputs": {"volume": 20_000_000}},
                {"key": "positive_catalyst.earnings", "points_after_adjustment": 14, "raw_inputs": {"headline_count": 2}},
                {"key": "risk_term.low_float", "points_after_adjustment": -4, "raw_inputs": {"float": 1_000_000}},
            ]
        )

        self.assertEqual(["Volume", "Catalyst", "Risk Penalty"], [row["label"] for row in summary])
        self.assertEqual([8, 14, -4], [row["contribution"] for row in summary])

    def test_html_includes_freshness_context_and_latest_article(self) -> None:
        capture_time = now_central()
        candidate = Candidate("UNIT", score=96)
        candidate.news = [
            NewsItem(
                headline="Unit Corp posts strong earnings beat",
                source="Finviz",
                published_at=capture_time - timedelta(minutes=32),
            )
        ]
        record = {
            "ticker": "UNIT",
            "final_score": 96,
            "identity": {
                "capture_time": capture_time.isoformat(),
                "session": "live",
                "provider": "finviz",
                "scanner": "Basic Momentum",
                "mode": "PAPER",
            },
            "components": [
                {
                    "key": "market_cap",
                    "label": "Market Cap",
                    "category": "bonus",
                    "rule": ">= 50,000,000,000 => +12; >= 5,000,000,000 => +9",
                    "raw_inputs": {"market_cap": 40_000_000_000},
                    "points_before_adjustment": 9,
                    "points_after_adjustment": 9,
                    "explanation": "mid/large cap participation",
                },
                {
                    "key": "freshness_context",
                    "label": "Freshness Context",
                    "category": "context",
                    "rule": "Current engine records freshness for explainability; freshness does not add or subtract points in momentum_score_v1.",
                    "raw_inputs": {"freshness": "HOT", "freshness_score": 99, "article_count": 1},
                    "points_before_adjustment": 0,
                    "points_after_adjustment": 0,
                    "explanation": "Latest valid article freshness is HOT with score 99.",
                },
            ],
        }

        html = format_score_breakdown_html(record, candidate=candidate)

        for expected in [
            "$40.0B",
            "Base Points",
            "Applied Impact",
            "Freshness is recorded",
            "Unit Corp posts strong earnings beat",
            "Source:</b> Finviz",
        ]:
            self.assertIn(expected, html)


if __name__ == "__main__":
    unittest.main()
