from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta

from momentum_hunter.canonical_candle_evidence import CanonicalMinuteBar
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_SUPPORTED,
    DIRECT_ISSUER,
    EXECUTION_ELIGIBLE,
    EXECUTION_INELIGIBLE,
    UNRESOLVED,
    CUSTOMER_SUPPLIER,
)
from momentum_hunter.intraday_trade_plan import (
    CATALYST_DRIVER,
    CONTINUATION_BREAKOUT,
    EXPIRED,
    INTRADAY_HORIZON,
    INVALIDATED,
    MISSED_ENTRY,
    OPENING_BREAKOUT,
    PENDING_ENTRY,
    PULLBACK,
    RECLAIM,
    TRIGGERED,
    build_intraday_plan_evidence,
    build_opening_breakout_plan_evidence,
    intraday_plan_decision_findings,
    expected_intraday_plan_id,
    intraday_plan_fingerprint,
    intraday_plan_validation_findings,
    transition_intraday_plan,
)
from momentum_hunter.schwab_candle_contract import SCHWAB_PRICE_HISTORY_SOURCE


SETUP_FINGERPRINT = "a" * 64
CATALYST_FINGERPRINT = "b" * 64


class IntradayTradePlanTests(unittest.TestCase):
    def test_opening_breakout_uses_five_bar_range_and_same_session_deadlines(self) -> None:
        evidence = build_opening_breakout_plan_evidence(
            symbol="aaa",
            created_at=at("2026-07-23T09:35:00-04:00"),
            planned_entry=10.40,
            source_setup_fingerprint=SETUP_FINGERPRINT,
            minute_bars=opening_bars(high=10.30, low=10.00),
        )

        self.assertEqual(EXECUTION_ELIGIBLE, evidence.status)
        self.assertEqual(INTRADAY_HORIZON, evidence.horizon)
        self.assertEqual(OPENING_BREAKOUT, evidence.setup_family)
        self.assertEqual(PENDING_ENTRY, evidence.lifecycle_status)
        self.assertEqual(10.40, evidence.planned_entry)
        self.assertEqual(10.00, evidence.stop_price)
        self.assertEqual((10.8, 11.2), evidence.target_prices)
        self.assertEqual("2026-07-23T10:30:00-04:00", evidence.entry_expires_at)
        self.assertEqual("2026-07-23T15:55:00-04:00", evidence.forced_flat_at)
        self.assertEqual(64, len(evidence.plan_id))
        self.assertEqual((), intraday_plan_validation_findings(evidence))

    def test_opening_breakout_crossed_before_plan_is_immutable_missed_entry(self) -> None:
        evidence = build_opening_breakout_plan_evidence(
            symbol="AAA",
            created_at=at("2026-07-23T09:35:00-04:00"),
            planned_entry=10.40,
            source_setup_fingerprint=SETUP_FINGERPRINT,
            minute_bars=opening_bars(high=10.45, low=10.00),
        )

        self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
        self.assertEqual(MISSED_ENTRY, evidence.lifecycle_status)
        self.assertEqual(10.40, evidence.planned_entry)
        self.assertIn("INTRADAY_ENTRY_MISSED_IMMUTABLY", evidence.findings)
        with self.assertRaisesRegex(ValueError, "Terminal intraday plan evidence is immutable"):
            transition_intraday_plan(
                evidence,
                lifecycle_status=PENDING_ENTRY,
                observed_at=at("2026-07-23T09:36:00-04:00"),
            )

    def test_later_session_families_have_independent_setup_aware_expiry(self) -> None:
        created = at("2026-07-23T13:00:00-04:00")
        expected_minutes = {
            CONTINUATION_BREAKOUT: 45,
            PULLBACK: 30,
        }
        expected_rule_tokens = {
            CONTINUATION_BREAKOUT: "LATER_SESSION_RANGE",
            PULLBACK: "PULLBACK_STRUCTURE",
        }
        for family, minutes in expected_minutes.items():
            with self.subTest(family=family):
                evidence = plan(family=family, created_at=created)
                self.assertEqual(PENDING_ENTRY, evidence.lifecycle_status)
                self.assertEqual(
                    created + timedelta(minutes=minutes),
                    datetime.fromisoformat(evidence.entry_expires_at),
                )
                self.assertIn(expected_rule_tokens[family], evidence.stop_rule)
                self.assertIn(family.split("_")[0], evidence.target_rule)
                self.assertEqual((), intraday_plan_validation_findings(evidence))

    def test_reclaim_is_new_identity_linked_to_terminal_missed_breakout(self) -> None:
        missed = plan(
            family=OPENING_BREAKOUT,
            created_at=at("2026-07-23T09:35:00-04:00"),
            observed_price=10.50,
        )
        reclaim = plan(
            family=RECLAIM,
            created_at=at("2026-07-23T11:00:00-04:00"),
            predecessor=missed,
            replacement_reason="PULLBACK_BELOW_TRIGGER_OBSERVED",
        )

        self.assertEqual(MISSED_ENTRY, missed.lifecycle_status)
        self.assertEqual(PENDING_ENTRY, reclaim.lifecycle_status)
        self.assertNotEqual(missed.plan_id, reclaim.plan_id)
        self.assertEqual(missed.plan_id, reclaim.predecessor_plan_id)
        self.assertEqual(missed.fingerprint, reclaim.predecessor_plan_fingerprint)
        self.assertEqual(10.40, missed.planned_entry)
        self.assertEqual(10.40, reclaim.planned_entry)
        self.assertEqual((), intraday_plan_validation_findings(reclaim))

    def test_reclaim_without_terminal_predecessor_fails_closed(self) -> None:
        reclaim = plan(
            family=RECLAIM,
            created_at=at("2026-07-23T11:00:00-04:00"),
        )

        self.assertEqual(EXECUTION_INELIGIBLE, reclaim.status)
        self.assertIn("RECLAIM_PREDECESSOR_REQUIRED", reclaim.findings)

    def test_catalyst_driver_requires_supported_attribution(self) -> None:
        supported = plan(
            family=CONTINUATION_BREAKOUT,
            created_at=at("2026-07-23T11:00:00-04:00"),
            setup_driver=CATALYST_DRIVER,
            catalyst_relationship_type=DIRECT_ISSUER,
            catalyst_score_authority=CATALYST_SCORE_SUPPORTED,
            catalyst_attribution_fingerprint=CATALYST_FINGERPRINT,
        )
        unresolved = plan(
            family=CONTINUATION_BREAKOUT,
            created_at=at("2026-07-23T11:00:00-04:00"),
            setup_driver=CATALYST_DRIVER,
            catalyst_relationship_type=UNRESOLVED,
            catalyst_score_authority="BLOCKED",
            catalyst_attribution_fingerprint=CATALYST_FINGERPRINT,
        )
        relationship_supported = plan(
            family=PULLBACK,
            created_at=at("2026-07-23T12:00:00-04:00"),
            setup_driver=CATALYST_DRIVER,
            catalyst_relationship_type=CUSTOMER_SUPPLIER,
            catalyst_score_authority=CATALYST_SCORE_SUPPORTED,
            catalyst_attribution_fingerprint=CATALYST_FINGERPRINT,
        )
        missing_identity = plan(
            family=CONTINUATION_BREAKOUT,
            created_at=at("2026-07-23T11:00:00-04:00"),
            setup_driver=CATALYST_DRIVER,
            catalyst_relationship_type=DIRECT_ISSUER,
            catalyst_score_authority=CATALYST_SCORE_SUPPORTED,
        )

        self.assertEqual(EXECUTION_ELIGIBLE, supported.status)
        self.assertEqual(EXECUTION_ELIGIBLE, relationship_supported.status)
        self.assertEqual(EXECUTION_INELIGIBLE, unresolved.status)
        self.assertIn(
            "CATALYST_DRIVEN_SETUP_ATTRIBUTION_UNSUPPORTED",
            unresolved.findings,
        )
        self.assertIn(
            "CATALYST_DRIVEN_SETUP_ATTRIBUTION_IDENTITY_MISSING",
            missing_identity.findings,
        )

    def test_plan_created_outside_regular_session_fails_closed(self) -> None:
        evidence = plan(
            family=CONTINUATION_BREAKOUT,
            created_at=at("2026-07-23T08:59:00-04:00"),
        )

        self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
        self.assertIn(
            "INTRADAY_PLAN_CREATED_OUTSIDE_REGULAR_SESSION", evidence.findings
        )

    def test_plan_created_on_non_market_day_fails_closed(self) -> None:
        evidence = plan(
            family=CONTINUATION_BREAKOUT,
            created_at=at("2026-07-25T11:00:00-04:00"),
        )

        self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
        self.assertIn("INTRADAY_PLAN_SESSION_IS_NOT_MARKET_DAY", evidence.findings)

    def test_expiry_and_invalidation_are_terminal_and_decision_gate_is_prospective(self) -> None:
        evidence = plan(
            family=CONTINUATION_BREAKOUT,
            created_at=at("2026-07-23T11:00:00-04:00"),
        )
        triggered = transition_intraday_plan(
            evidence,
            lifecycle_status=TRIGGERED,
            observed_at=at("2026-07-23T11:10:00-04:00"),
        )
        expired = transition_intraday_plan(
            triggered,
            lifecycle_status=EXPIRED,
            observed_at=at("2026-07-23T11:46:00-04:00"),
        )

        self.assertEqual(evidence.plan_id, triggered.plan_id)
        self.assertEqual(evidence.plan_id, expired.plan_id)
        self.assertEqual(
            "2026-07-23T11:46:00-04:00", expired.lifecycle_updated_at
        )
        self.assertEqual(EXECUTION_INELIGIBLE, expired.status)
        self.assertIn(
            "INTRADAY_DECISION_OUTSIDE_ENTRY_VALIDITY",
            intraday_plan_decision_findings(
                evidence,
                decision_at=at("2026-07-23T11:46:00-04:00"),
            ),
        )
        invalidated = transition_intraday_plan(
            evidence,
            lifecycle_status=INVALIDATED,
            observed_at=at("2026-07-23T11:05:00-04:00"),
        )
        self.assertEqual(INVALIDATED, invalidated.lifecycle_status)
        with self.assertRaisesRegex(ValueError, "TRIGGERED -> MISSED_ENTRY"):
            transition_intraday_plan(
                triggered,
                lifecycle_status=MISSED_ENTRY,
                observed_at=at("2026-07-23T11:15:00-04:00"),
            )
        with self.assertRaisesRegex(ValueError, "before its persisted deadline"):
            transition_intraday_plan(
                evidence,
                lifecycle_status=EXPIRED,
                observed_at=at("2026-07-23T11:10:00-04:00"),
            )

    def test_fingerprint_detects_timing_level_and_family_tampering(self) -> None:
        evidence = plan(
            family=PULLBACK,
            created_at=at("2026-07-23T13:00:00-04:00"),
        )

        for tampered in (
            replace(evidence, stop_price=9.60),
            replace(evidence, setup_family=CONTINUATION_BREAKOUT),
            replace(evidence, entry_expires_at="2026-07-23T14:00:00-04:00"),
        ):
            with self.subTest(field=tampered):
                self.assertNotEqual(tampered.fingerprint, intraday_plan_fingerprint(tampered))
                self.assertIn(
                    "INTRADAY_PLAN_FINGERPRINT_INVALID",
                    intraday_plan_validation_findings(tampered),
                )
        substituted_id = replace(evidence, plan_id="c" * 64, fingerprint="")
        substituted_id = replace(
            substituted_id,
            fingerprint=intraday_plan_fingerprint(substituted_id),
        )
        self.assertNotEqual(
            substituted_id.plan_id, expected_intraday_plan_id(substituted_id)
        )
        self.assertIn(
            "INTRADAY_PLAN_ID_CONTRADICTS_CONTENT",
            intraday_plan_validation_findings(substituted_id),
        )

    def test_replacement_claim_requires_a_terminal_predecessor_identity(self) -> None:
        evidence = plan(
            family=CONTINUATION_BREAKOUT,
            created_at=at("2026-07-23T13:00:00-04:00"),
            replacement_reason="NEW_RANGE_FORMED",
        )

        self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
        self.assertIn(
            "INTRADAY_REPLACEMENT_PREDECESSOR_REQUIRED", evidence.findings
        )

    def test_reclaim_requires_a_terminal_breakout_predecessor(self) -> None:
        pullback = transition_intraday_plan(
            plan(
                family=PULLBACK,
                created_at=at("2026-07-23T11:00:00-04:00"),
            ),
            lifecycle_status=INVALIDATED,
            observed_at=at("2026-07-23T11:10:00-04:00"),
        )
        reclaim = plan(
            family=RECLAIM,
            created_at=at("2026-07-23T12:00:00-04:00"),
            predecessor=pullback,
            replacement_reason="LEVEL_RECLAIMED",
        )

        self.assertEqual(EXECUTION_INELIGIBLE, reclaim.status)
        self.assertIn("RECLAIM_BREAKOUT_PREDECESSOR_REQUIRED", reclaim.findings)

    def test_opening_bar_gap_fails_closed_without_fabrication(self) -> None:
        bars = opening_bars(high=10.30, low=10.00)[:-1]
        evidence = build_opening_breakout_plan_evidence(
            symbol="AAA",
            created_at=at("2026-07-23T09:35:00-04:00"),
            planned_entry=10.40,
            source_setup_fingerprint=SETUP_FINGERPRINT,
            minute_bars=bars,
        )

        self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
        self.assertEqual((), evidence.target_prices)
        self.assertIn("OPENING_RANGE_FIVE_COMPLETED_BARS_REQUIRED", evidence.findings)

    def test_opening_range_rejects_noncanonical_or_duplicate_bars(self) -> None:
        valid = opening_bars(high=10.30, low=10.00)
        cases = {
            "symbol": (replace(valid[0], symbol="BBB"), *valid[1:]),
            "source": (
                replace(valid[0], source="SCHWAB_STREAMER_CHART_EQUITY"),
                *valid[1:],
            ),
            "state": (replace(valid[0], state="COMPLETED_UNRECONCILED"), *valid[1:]),
            "duplicate": (*valid, valid[-1]),
        }
        for name, bars in cases.items():
            with self.subTest(name=name):
                evidence = build_opening_breakout_plan_evidence(
                    symbol="AAA",
                    created_at=at("2026-07-23T09:35:00-04:00"),
                    planned_entry=10.40,
                    source_setup_fingerprint=SETUP_FINGERPRINT,
                    minute_bars=bars,
                )
                self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
                self.assertTrue(
                    any(
                        finding.startswith("OPENING_RANGE_")
                        for finding in evidence.findings
                    )
                )

    def test_opening_range_cannot_be_created_before_five_minutes_complete(self) -> None:
        evidence = build_opening_breakout_plan_evidence(
            symbol="AAA",
            created_at=at("2026-07-23T09:34:59-04:00"),
            planned_entry=10.40,
            source_setup_fingerprint=SETUP_FINGERPRINT,
            minute_bars=opening_bars(high=10.30, low=10.00),
        )

        self.assertEqual(EXECUTION_INELIGIBLE, evidence.status)
        self.assertIn("OPENING_RANGE_NOT_COMPLETE", evidence.findings)


def plan(
    *,
    family: str,
    created_at: datetime,
    observed_price: float | None = None,
    predecessor=None,
    replacement_reason: str = "",
    setup_driver: str = "TECHNICAL",
    catalyst_relationship_type: str = "",
    catalyst_score_authority: str = "",
    catalyst_attribution_fingerprint: str = "",
):
    return build_intraday_plan_evidence(
        symbol="AAA",
        setup_family=family,
        created_at=created_at,
        planned_entry=10.40,
        stop_price=10.00,
        target_prices=(10.80, 11.20),
        source_setup_fingerprint=SETUP_FINGERPRINT,
        source_level_kind="SYNTHETIC_INTRADAY_STRUCTURE",
        source_evidence_ids=("bar-1", "bar-2"),
        observed_price=observed_price,
        predecessor=predecessor,
        replacement_reason=replacement_reason,
        setup_driver=setup_driver,
        catalyst_relationship_type=catalyst_relationship_type,
        catalyst_score_authority=catalyst_score_authority,
        catalyst_attribution_fingerprint=catalyst_attribution_fingerprint,
    )


def opening_bars(*, high: float, low: float) -> tuple[CanonicalMinuteBar, ...]:
    start = at("2026-07-23T09:30:00-04:00")
    return tuple(
        CanonicalMinuteBar(
            symbol="AAA",
            timestamp=(start + timedelta(minutes=index)).isoformat(),
            open=10.10,
            high=high,
            low=low,
            close=10.20,
            volume=10_000 + index,
            source=SCHWAB_PRICE_HISTORY_SOURCE,
            state="RECONCILED",
            session_date="2026-07-23",
        )
        for index in range(5)
    )


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
