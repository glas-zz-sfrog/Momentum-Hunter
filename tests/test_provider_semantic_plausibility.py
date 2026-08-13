from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.provider_semantic_plausibility import (
    ProviderSemanticBaseline,
    ProviderSemanticReference,
    evaluate_provider_semantics,
)


EVALUATION_TIME = datetime(2026, 8, 13, 14, 35, tzinfo=timezone.utc)


def candidate(
    ticker: str,
    *,
    price: float = 100.0,
    percent_change: float = 5.0,
    volume: int = 5_000_000,
    relative_volume: float = 2.0,
    market_cap: int = 10_000_000_000,
    float_shares: int | None = 80_000_000,
    atr: float | None = 4.0,
) -> Candidate:
    return Candidate(
        ticker=ticker,
        company=f"{ticker} Incorporated",
        price=price,
        percent_change=percent_change,
        volume=volume,
        relative_volume=relative_volume,
        market_cap=market_cap,
        float_shares=float_shares,
        atr=atr,
    )


class ProviderSemanticPlausibilityTests(unittest.TestCase):
    def test_valid_candidates_pass_with_deterministic_fingerprint(self) -> None:
        candidates = [candidate("NVDA"), candidate("AMD", price=180.0, volume=8_000_000)]

        first = evaluate_provider_semantics(
            candidates,
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            input_row_count=2,
        )
        second = evaluate_provider_semantics(
            candidates,
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            input_row_count=2,
        )

        self.assertEqual("PASS", first.status)
        self.assertEqual(2, first.qualifying_candidate_count)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_legitimate_all_rows_rejected_is_explained_not_failed(self) -> None:
        candidates = [
            candidate("LOWV", volume=50_000),
            candidate("FLAT", percent_change=0.2),
        ]

        diagnostics = evaluate_provider_semantics(
            candidates,
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            input_row_count=2,
        )

        self.assertEqual("PASS", diagnostics.status)
        self.assertEqual(0, diagnostics.qualifying_candidate_count)
        self.assertEqual(2, diagnostics.rejected_candidate_count)
        self.assertEqual(
            {
                "BELOW_MIN_PERCENT_CHANGE": 1,
                "BELOW_MIN_VOLUME": 1,
            },
            dict(diagnostics.rejection_reason_counts),
        )

    def test_unexplained_raw_to_parsed_collapse_fails(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NVDA")],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            input_row_count=20,
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("UNEXPLAINED_ROW_COUNT_COLLAPSE", diagnostics.issue_codes)

    def test_impossible_price_change_relationship_fails(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("BROKEN", percent_change=-100.0)],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("IMPOSSIBLE_PRICE_CHANGE_RELATIONSHIP", diagnostics.issue_codes)

    def test_extreme_change_scale_fails(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("SCALE", percent_change=1_434.0)],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("ECONOMIC_VALUE_OUT_OF_BOUNDS", diagnostics.issue_codes)

    def test_nonfinite_value_fails_with_serializable_diagnostics(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NAN", price=float("nan"))],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("NONFINITE_VALUE", diagnostics.issue_codes)
        self.assertEqual(64, len(diagnostics.fingerprint))
        self.assertEqual("FAIL", diagnostics.to_dict()["status"])

    def test_repeated_cross_symbol_economic_signature_fails(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate(ticker) for ticker in ("AAAA", "BBBB", "CCCC", "DDDD")],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("SUSPICIOUS_REPEATED_ECONOMIC_SIGNATURE", diagnostics.issue_codes)

    def test_duplicate_symbol_rows_fail(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NVDA"), candidate("nvda", price=101.0)],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("DUPLICATE_SYMBOL_ROWS", diagnostics.issue_codes)

    def test_authoritative_schwab_price_can_confirm_candidate(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NVDA", price=180.0, volume=10_000_000)],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            evaluation_time=EVALUATION_TIME,
            expected_session="REGULAR",
            references=[
                ProviderSemanticReference(
                    symbol="NVDA",
                    source="Schwab Trader API",
                    observed_at=EVALUATION_TIME - timedelta(seconds=3),
                    session="REGULAR",
                    price=181.0,
                    cumulative_volume=9_900_000,
                    cumulative_volume_comparable=True,
                )
            ],
        )

        self.assertEqual("PASS", diagnostics.status)
        self.assertEqual(1, diagnostics.compared_reference_count)

    def test_severe_schwab_price_disagreement_fails_without_substitution(self) -> None:
        source_candidate = candidate("NVDA", price=180.0)
        diagnostics = evaluate_provider_semantics(
            [source_candidate],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            evaluation_time=EVALUATION_TIME,
            expected_session="REGULAR",
            references=[
                ProviderSemanticReference(
                    symbol="NVDA",
                    source="Schwab Trader API",
                    observed_at=EVALUATION_TIME,
                    session="REGULAR",
                    price=100.0,
                )
            ],
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("AUTHORITATIVE_PRICE_DISAGREEMENT", diagnostics.issue_codes)
        self.assertEqual(180.0, source_candidate.price)
        payload = diagnostics.to_dict()
        self.assertEqual(180.0, payload["evaluatedCandidates"][0]["price"])
        self.assertEqual(100.0, payload["evaluatedReferences"][0]["price"])
        self.assertEqual("Schwab Trader API", payload["evaluatedReferences"][0]["source"])

    def test_authoritative_cumulative_volume_contradiction_fails(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NVDA", volume=5_000_000)],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            evaluation_time=EVALUATION_TIME,
            expected_session="REGULAR",
            references=[
                ProviderSemanticReference(
                    symbol="NVDA",
                    source="Schwab canonical completed candles",
                    observed_at=EVALUATION_TIME,
                    session="REGULAR",
                    price=100.0,
                    cumulative_volume=8_000_000,
                    cumulative_volume_comparable=True,
                )
            ],
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("AUTHORITATIVE_VOLUME_CONTRADICTION", diagnostics.issue_codes)

    def test_stale_reference_fails_instead_of_becoming_authority(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NVDA")],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            evaluation_time=EVALUATION_TIME,
            expected_session="REGULAR",
            references=[
                ProviderSemanticReference(
                    symbol="NVDA",
                    source="Schwab Trader API",
                    observed_at=EVALUATION_TIME - timedelta(minutes=5),
                    session="REGULAR",
                    price=100.0,
                )
            ],
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("REFERENCE_STALE", diagnostics.issue_codes)
        self.assertEqual(0, diagnostics.compared_reference_count)

    def test_volume_is_not_compared_without_explicit_comparability(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NVDA", volume=5_000_000)],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            evaluation_time=EVALUATION_TIME,
            expected_session="REGULAR",
            references=[
                ProviderSemanticReference(
                    symbol="NVDA",
                    source="Schwab Trader API",
                    observed_at=EVALUATION_TIME,
                    session="REGULAR",
                    price=100.0,
                    cumulative_volume=8_000_000,
                    cumulative_volume_comparable=False,
                )
            ],
        )

        self.assertEqual("PASS", diagnostics.status)
        self.assertNotIn("AUTHORITATIVE_VOLUME_CONTRADICTION", diagnostics.issue_codes)

    def test_wrong_session_reference_fails(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NVDA")],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            evaluation_time=EVALUATION_TIME,
            expected_session="REGULAR",
            references=[
                ProviderSemanticReference(
                    symbol="NVDA",
                    source="Schwab Trader API",
                    observed_at=EVALUATION_TIME,
                    session="AFTER_HOURS",
                    price=100.0,
                )
            ],
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("REFERENCE_SESSION_MISMATCH", diagnostics.issue_codes)

    def test_non_schwab_reference_cannot_be_promoted_to_authority(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [candidate("NVDA")],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            evaluation_time=EVALUATION_TIME,
            expected_session="REGULAR",
            references=[
                ProviderSemanticReference(
                    symbol="NVDA",
                    source="Yahoo",
                    observed_at=EVALUATION_TIME,
                    session="REGULAR",
                    price=100.0,
                    authoritative=True,
                )
            ],
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("REFERENCE_SOURCE_NOT_AUTHORIZED", diagnostics.issue_codes)

    def test_extreme_distribution_shift_fails_against_explicit_baseline(self) -> None:
        diagnostics = evaluate_provider_semantics(
            [
                candidate(
                    f"S{index}",
                    price=10_000.0 + index,
                    market_cap=20_000_000_000,
                    float_shares=1_000_000,
                )
                for index in range(5)
            ],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
            baseline=ProviderSemanticBaseline(
                source="prior verified Finviz scanner distributions",
                sample_size=50,
                median_price=50.0,
                median_absolute_change_percent=5.0,
                median_volume=5_000_000,
                median_relative_volume=2.0,
            ),
        )

        self.assertEqual("FAIL", diagnostics.status)
        self.assertIn("EXTREME_DISTRIBUTION_SHIFT", diagnostics.issue_codes)

    def test_evaluation_does_not_mutate_source_candidates(self) -> None:
        source_candidate = candidate("NVDA")
        before = source_candidate.__dict__.copy()

        evaluate_provider_semantics(
            [source_candidate],
            INSTITUTIONAL_MOMENTUM,
            provider="finviz",
        )

        self.assertEqual(before, source_candidate.__dict__)

    def test_semantic_layer_has_no_network_scoring_or_broker_dependency(self) -> None:
        source = Path(
            "momentum_hunter/provider_semantic_plausibility.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "import requests",
            "import urllib",
            "momentum_hunter.scoring",
            "momentum_hunter.trade_planning",
            "momentum_hunter.execution",
            "alpaca",
            "schwab_market_data",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
