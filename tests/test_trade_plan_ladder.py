from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication

from momentum_hunter.autonomy.view_models import build_candidate_plans_from_candidates
from momentum_hunter.models import Candidate, NewsItem, NewsStack
from momentum_hunter.ui.trade_plan_ladder import TradePlanLadderWidget


class TradePlanLadderWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_render_candidate_shows_structured_tradeplan_rows(self) -> None:
        widget = TradePlanLadderWidget()
        candidate = build_candidate_plans_from_candidates([sample_candidate()])[0]

        widget.render_candidate(candidate)

        self.assertIn("Trade Plan Ladder populated for AAA", widget.empty_label.text())
        self.assertEqual("Ticker", widget.table.item(0, 0).text())
        self.assertEqual("AAA", widget.table.item(0, 1).text())
        self.assertGreater(widget.table.rowCount(), 10)
        widget.deleteLater()

    def test_clear_restores_empty_state(self) -> None:
        widget = TradePlanLadderWidget()
        candidate = build_candidate_plans_from_candidates([sample_candidate()])[0]
        widget.render_candidate(candidate)

        widget.clear()

        self.assertEqual("Select a candidate to populate the Trade Plan Ladder", widget.empty_label.text())
        self.assertEqual(0, widget.table.rowCount())
        widget.deleteLater()


def sample_candidate() -> Candidate:
    headline = "AAA rallies on AI contract momentum"
    return Candidate(
        ticker="AAA",
        company="AAA Corp",
        price=10.0,
        percent_change=5.0,
        volume=15_000_000,
        relative_volume=1.8,
        market_cap=12_000_000_000,
        sector="Technology",
        industry="Software",
        news=[NewsItem(headline=headline, source="Test")],
        score=95,
        freshness_score=90,
        news_stack=NewsStack(article_count=1, freshest_headline=headline, freshness_score=90, freshness="HOT"),
    )


if __name__ == "__main__":
    unittest.main()
