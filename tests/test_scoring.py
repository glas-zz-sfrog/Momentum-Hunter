from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from momentum_hunter.models import Candidate, MarketRegime, NewsItem
from momentum_hunter.scoring import build_score_breakdown, score_candidate, score_candidates
from momentum_hunter.time_utils import CENTRAL_TZ


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

    def test_future_news_does_not_contribute_catalyst_score(self) -> None:
        now = datetime(2026, 6, 4, 7, 0, tzinfo=CENTRAL_TZ)
        base = Candidate(
            ticker="SAFE",
            company="Safe Corp",
            price=50,
            percent_change=6,
            volume=12_000_000,
            relative_volume=1.4,
            market_cap=20_000_000_000,
            news=[NewsItem(headline="Routine company update", published_at=now - timedelta(hours=1))],
        )
        leaked = clone_candidate(base)
        leaked.news.append(
            NewsItem(
                headline="Safe beats earnings on AI guidance",
                published_at=now + timedelta(hours=3),
            )
        )

        base_scored = score_candidate(base, regime=MarketRegime.BULL, now=now)
        leaked_scored = score_candidate(leaked, regime=MarketRegime.BULL, now=now)

        self.assertEqual(base_scored.score, leaked_scored.score)
        self.assertNotIn("AI catalyst", leaked_scored.score_reasons)

    def test_direct_issuer_news_can_contribute_catalyst_score(self) -> None:
        now = datetime(2026, 8, 24, 8, 35, tzinfo=CENTRAL_TZ)
        candidate = scoring_candidate(
            "BMNR",
            "BitMine Immersion Technologies Inc",
            "BMNR expands AI infrastructure program",
            now,
        )

        breakdown = build_score_breakdown(candidate, regime=MarketRegime.BULL, now=now)

        self.assertTrue(component(breakdown, "positive_catalyst.ai")["points_after_adjustment"] > 0)
        authority = component(breakdown, "catalyst_authority_context")["raw_inputs"]
        self.assertEqual(1, authority["authorized_headline_count"])
        self.assertEqual(["DIRECT_ISSUER"], authority["authorized_relationship_types"])

    def test_unrelated_news_cannot_change_score_or_add_derived_bonus(self) -> None:
        now = datetime(2026, 8, 24, 8, 35, tzinfo=CENTRAL_TZ)
        base = scoring_candidate("BMNR", "BitMine Immersion Technologies Inc", "Routine market update", now)
        unrelated = scoring_candidate(
            "BMNR",
            "BitMine Immersion Technologies Inc",
            "Eightco announces OpenAI initiative for AI infrastructure",
            now,
        )

        base_breakdown = build_score_breakdown(base, regime=MarketRegime.BULL, now=now)
        unrelated_breakdown = build_score_breakdown(unrelated, regime=MarketRegime.BULL, now=now)

        self.assertEqual(base_breakdown["computed_final_score"], unrelated_breakdown["computed_final_score"])
        self.assertNotIn("positive_catalyst.ai", unrelated_breakdown["bonuses"])
        authority = component(unrelated_breakdown, "catalyst_authority_context")["raw_inputs"]
        self.assertEqual(0, authority["authorized_headline_count"])
        self.assertEqual(1, authority["blocked_headline_count"])
        self.assertEqual(["UNRESOLVED"], authority["blocked_relationship_types"])

    def test_unrelated_risk_term_cannot_penalize_candidate(self) -> None:
        now = datetime(2026, 8, 24, 8, 35, tzinfo=CENTRAL_TZ)
        base = scoring_candidate("BMNR", "BitMine Immersion Technologies Inc", "Routine market update", now)
        unrelated = scoring_candidate(
            "BMNR",
            "BitMine Immersion Technologies Inc",
            "Eightco faces bankruptcy investigation",
            now,
        )

        base_score = score_candidate(base, regime=MarketRegime.BULL, now=now).score
        unrelated_score = score_candidate(unrelated, regime=MarketRegime.BULL, now=now).score

        self.assertEqual(base_score, unrelated_score)

    def test_ambiguous_ticker_and_unresolved_relationship_remain_blocked(self) -> None:
        now = datetime(2026, 8, 24, 8, 35, tzinfo=CENTRAL_TZ)
        candidate = scoring_candidate("AI", "C3.ai Inc", "AI infrastructure demand accelerates", now)

        breakdown = build_score_breakdown(candidate, regime=MarketRegime.BULL, now=now)

        self.assertNotIn("positive_catalyst.ai", breakdown["bonuses"])
        authority = component(breakdown, "catalyst_authority_context")["raw_inputs"]
        self.assertEqual(0, authority["authorized_headline_count"])
        self.assertEqual(["UNRESOLVED"], authority["blocked_relationship_types"])

    def test_explicit_macro_relationship_can_contribute(self) -> None:
        now = datetime(2026, 8, 24, 8, 35, tzinfo=CENTRAL_TZ)
        candidate = scoring_candidate(
            "NVDA",
            "NVIDIA Corp",
            "Federal Reserve report highlights AI investment",
            now,
        )

        breakdown = build_score_breakdown(candidate, regime=MarketRegime.BULL, now=now)

        self.assertIn("positive_catalyst.ai", breakdown["bonuses"])
        authority = component(breakdown, "catalyst_authority_context")["raw_inputs"]
        self.assertEqual(["MACRO"], authority["authorized_relationship_types"])

    def test_authority_changes_ranking_for_otherwise_equal_candidates(self) -> None:
        now = datetime(2026, 8, 24, 8, 35, tzinfo=CENTRAL_TZ)
        authorized = scoring_candidate("NVDA", "NVIDIA Corp", "NVDA expands AI platform", now)
        blocked = scoring_candidate("BMNR", "BitMine Immersion Technologies Inc", "Eightco expands AI platform", now)

        ranked = score_candidates([blocked, authorized], regime=MarketRegime.BULL, now=now)

        self.assertEqual(["NVDA", "BMNR"], [candidate.ticker for candidate in ranked])
        self.assertGreater(ranked[0].score, ranked[1].score)

    def test_august_24_bmnr_unrelated_openai_story_is_blocked_prospectively(self) -> None:
        now = datetime(2026, 8, 24, 8, 35, tzinfo=CENTRAL_TZ)
        candidate = Candidate(
            ticker="BMNR",
            company="BitMine Immersion Technologies Inc",
            price=50,
            percent_change=6,
            volume=12_000_000,
            relative_volume=1.4,
            market_cap=20_000_000_000,
            news=[
                NewsItem(
                    headline=(
                        "Bitmine Immersion Technologies (BMNR) Announces ETH Holdings Reach "
                        "5.85 Million Tokens, and Total Crypto and Total Cash Holdings of $14.9 Billion"
                    ),
                    published_at=now - timedelta(minutes=5),
                ),
                NewsItem(
                    headline=(
                        "Eightco Holdings (NASDAQ: ORBS) Reports Total Holdings of Approximately "
                        "$389 Million, Includes OpenAI, Beast Industries, More Than 16,000 ETH and "
                        "Nearly 302 Million WLD Tokens"
                    ),
                    summary="Potential AI infrastructure or automation theme.",
                    published_at=now - timedelta(days=4),
                ),
                NewsItem(
                    headline=(
                        "MSTR, BMNR, COIN, CRCL Stock Extend Rally After Bitcoin Blasts Past $71K, "
                        "Triggering $3B Liquidation Wave"
                    ),
                    published_at=now - timedelta(hours=2),
                ),
            ],
        )

        breakdown = build_score_breakdown(candidate, regime=MarketRegime.BULL, now=now)

        self.assertNotIn("positive_catalyst.ai", breakdown["bonuses"])
        self.assertNotIn("AI catalyst", breakdown["score_reasons"])
        self.assertEqual(1, component(breakdown, "catalyst_authority_context")["raw_inputs"]["blocked_headline_count"])
        self.assertEqual(2, component(breakdown, "catalyst_authority_context")["raw_inputs"]["authorized_headline_count"])


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


def scoring_candidate(ticker: str, company: str, headline: str, now: datetime) -> Candidate:
    return Candidate(
        ticker=ticker,
        company=company,
        price=50,
        percent_change=6,
        volume=12_000_000,
        relative_volume=1.4,
        market_cap=20_000_000_000,
        news=[NewsItem(headline=headline, published_at=now - timedelta(minutes=5))],
    )


def component(breakdown: dict, key: str) -> dict:
    return next(item for item in breakdown["components"] if item["key"] == key)


if __name__ == "__main__":
    unittest.main()
