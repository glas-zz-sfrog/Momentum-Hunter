from __future__ import annotations

import unittest

from momentum_hunter.models import Candidate, MarketRegime, NewsItem
from momentum_hunter.scoring import score_candidate


class ScoringTests(unittest.TestCase):
    def test_regime_adjustments_change_score(self) -> None:
        candidate = Candidate(
            ticker="TEST",
            company="Test Corp",
            price=50,
            percent_change=9,
            volume=30_000_000,
            relative_volume=2.2,
            market_cap=60_000_000_000,
            news=[NewsItem(headline="Test beats earnings on AI guidance")],
        )

        bull = score_candidate(clone_candidate(candidate), regime=MarketRegime.BULL)
        bear = score_candidate(clone_candidate(candidate), regime=MarketRegime.BEAR)

        self.assertGreaterEqual(bull.score, bear.score)
        self.assertIn("score profile: regime-aware-v1", bull.score_reasons)
        self.assertIn("score regime: bull", bull.score_reasons)
        self.assertEqual("regime-aware-v1", bull.score_profile)
        self.assertEqual("bull", bull.score_regime)


def clone_candidate(candidate: Candidate) -> Candidate:
    return Candidate(
        ticker=candidate.ticker,
        company=candidate.company,
        price=candidate.price,
        percent_change=candidate.percent_change,
        volume=candidate.volume,
        relative_volume=candidate.relative_volume,
        market_cap=candidate.market_cap,
        sector=candidate.sector,
        industry=candidate.industry,
        news=list(candidate.news),
    )


if __name__ == "__main__":
    unittest.main()
