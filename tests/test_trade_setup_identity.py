from __future__ import annotations

import unittest
from dataclasses import replace

from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE, EXECUTION_INELIGIBLE
from momentum_hunter.trade_setup_identity import (
    BREAKOUT_CONFIRMATION_RULE,
    BREAKOUT_SETUP,
    DAILY_LEVEL_SOURCE,
    PENDING_BREAKOUT,
    RECLAIM_CONFIRMATION_REQUIRED,
    RECLAIM_CONFIRMATION_RULE,
    RECLAIM_NOT_CONFIRMED,
    RECLAIM_REQUIRED_SETUP,
    SETUP_UNAVAILABLE,
    build_trade_setup_evidence,
    trade_setup_fingerprint,
)


class TradeSetupIdentityTests(unittest.TestCase):
    def test_breakout_ahead_uses_original_daily_level(self) -> None:
        evidence = build_trade_setup_evidence(
            symbol="aaa",
            observed_price=10.15,
            breakout_level=10.40,
            invalidation_level=9.80,
            source=DAILY_LEVEL_SOURCE,
        )

        self.assertEqual(EXECUTION_ELIGIBLE, evidence.status)
        self.assertEqual("AAA", evidence.symbol)
        self.assertEqual(BREAKOUT_SETUP, evidence.setup_type)
        self.assertEqual(10.40, evidence.breakout_level)
        self.assertEqual(10.40, evidence.planned_entry)
        self.assertEqual(PENDING_BREAKOUT, evidence.confirmation_status)
        self.assertEqual(BREAKOUT_CONFIRMATION_RULE, evidence.confirmation_rule)
        self.assertFalse(evidence.requires_pullback)
        self.assertEqual(64, len(evidence.fingerprint))
        self.assertEqual(evidence.fingerprint, trade_setup_fingerprint(evidence))

    def test_price_above_level_requires_reclaim_without_chasing(self) -> None:
        evidence = build_trade_setup_evidence(
            symbol="AAA",
            observed_price=10.70,
            breakout_level=10.40,
            invalidation_level=9.80,
            source=DAILY_LEVEL_SOURCE,
        )

        self.assertEqual(EXECUTION_ELIGIBLE, evidence.status)
        self.assertEqual(RECLAIM_REQUIRED_SETUP, evidence.setup_type)
        self.assertEqual(10.40, evidence.planned_entry)
        self.assertLess(evidence.planned_entry or 0, evidence.observed_price or 0)
        self.assertEqual(RECLAIM_NOT_CONFIRMED, evidence.confirmation_status)
        self.assertEqual(RECLAIM_CONFIRMATION_RULE, evidence.confirmation_rule)
        self.assertTrue(evidence.requires_pullback)
        self.assertIn(RECLAIM_CONFIRMATION_REQUIRED, evidence.findings)

    def test_missing_daily_authority_fails_closed_without_guessing(self) -> None:
        evidence = build_trade_setup_evidence(
            symbol="AAA",
            observed_price=10.0,
            breakout_level=10.1,
            invalidation_level=9.5,
            source="estimated_from_capture_price",
        )

        self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
        self.assertEqual(SETUP_UNAVAILABLE, evidence.setup_type)
        self.assertIn("AUTHORITATIVE_DAILY_LEVELS_UNAVAILABLE", evidence.findings)

    def test_invalid_level_order_fails_closed(self) -> None:
        evidence = build_trade_setup_evidence(
            symbol="AAA",
            observed_price=10.0,
            breakout_level=10.1,
            invalidation_level=10.1,
            source=DAILY_LEVEL_SOURCE,
        )

        self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
        self.assertIn("SETUP_LEVEL_ORDER_INVALID", evidence.findings)

    def test_fingerprint_is_deterministic_and_detects_tampering(self) -> None:
        first = build_trade_setup_evidence(
            symbol="AAA",
            observed_price=10.0,
            breakout_level=10.1,
            invalidation_level=9.5,
            source=DAILY_LEVEL_SOURCE,
        )
        second = build_trade_setup_evidence(
            symbol="AAA",
            observed_price=10.0,
            breakout_level=10.1,
            invalidation_level=9.5,
            source=DAILY_LEVEL_SOURCE,
        )

        self.assertEqual(first, second)
        tampered = replace(first, observed_price=10.2)
        self.assertNotEqual(tampered.fingerprint, trade_setup_fingerprint(tampered))

    def test_subcent_values_are_classified_from_persisted_precision(self) -> None:
        evidence = build_trade_setup_evidence(
            symbol="AAA",
            observed_price=10.404,
            breakout_level=10.400,
            invalidation_level=9.801,
            source=DAILY_LEVEL_SOURCE,
        )

        self.assertEqual(10.40, evidence.observed_price)
        self.assertEqual(10.40, evidence.breakout_level)
        self.assertEqual(BREAKOUT_SETUP, evidence.setup_type)
        self.assertEqual(evidence.fingerprint, trade_setup_fingerprint(evidence))


if __name__ == "__main__":
    unittest.main()
