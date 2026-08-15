from __future__ import annotations

import ast
import copy
import math
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from momentum_hunter.broker_capabilities import (
    BrokerCapability,
    BrokerCapabilityRegistry,
    CapabilityState,
)
from momentum_hunter.execution_quality_specialist import (
    ADEQUATE,
    AFTER_HOURS,
    CANCELLED_REMAINDER,
    COMPLETE,
    DATA_UNSAFE,
    DISLOCATED,
    EXECUTION_AUTHORITY_NONE,
    EXECUTION_QUALITY_SPECIALIST_VERSION,
    EXTREME,
    FAILED,
    FULL_FILL,
    HIGH,
    LIQUID,
    LOCKED_MARKET,
    LOW,
    MATHEMATICAL_COUNTERFACTUAL,
    MODERATE,
    NO_FILL,
    NORMAL,
    OBSERVED,
    PARTIAL,
    PARTIAL_FILL,
    PRE_DECISION_EXECUTION_QUALITY,
    REGULAR,
    RESEARCH_HEURISTIC,
    STABLE,
    THIN,
    TIGHT,
    UNKNOWN,
    UNSTABLE,
    UNSUPPORTED,
    VERY_THIN,
    WIDE,
    ExecutionQualityError,
    attach_observed_execution_result,
    build_minute_bar,
    build_observed_execution_result,
    build_quote_observation,
    default_execution_quality_policy,
    evaluate_execution_quality,
    packet_json_bytes,
    research_record_json_bytes,
    validate_packet,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    build_intraday_plan_evidence,
)
from momentum_hunter.provider_neutral_allocation import (
    AllocationStatus,
    ProviderNeutralAllocationDecision,
    QuantityMode,
)
from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    EVALUATED,
    HEURISTIC,
    NON_DIRECTIONAL,
    NO_DIRECTION,
    NO_OPINION,
    RESEARCH_ONLY,
    UNCALIBRATED,
)


EVALUATED_AT = datetime(2026, 8, 17, 14, 40, 10, tzinfo=timezone.utc)
OPPORTUNITY_ID = "1" * 64
CANDIDATE_ID = "candidate-execution-quality-1"
SETUP_ID = "2" * 64
SYMBOL = "SPY"
SOURCE = "schwab-canonical-regular-session"


class ExecutionQualityFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = default_execution_quality_policy()

    def evaluate(self, **kwargs):
        return evaluate_execution_quality(
            opportunity_id=kwargs.pop("opportunity_id", OPPORTUNITY_ID),
            candidate_id=kwargs.pop("candidate_id", CANDIDATE_ID),
            setup_id=kwargs.pop("setup_id", SETUP_ID),
            symbol=kwargs.pop("symbol", SYMBOL),
            evaluated_at=kwargs.pop("evaluated_at", EVALUATED_AT),
            quotes=kwargs.pop("quotes", quotes()),
            candles=kwargs.pop("candles", bars()),
            policy=kwargs.pop("policy", self.policy),
            trade_plan=kwargs.pop("trade_plan", plan()),
            allocation=kwargs.pop("allocation", None),
            broker_capabilities=kwargs.pop("broker_capabilities", None),
            **kwargs,
        )

    def test_a_liquid_tight_stable_fixture_is_supportive_research_only(self) -> None:
        packet = self.evaluate()

        self.assertEqual(LIQUID, packet.assessment.liquidity_state)
        self.assertEqual(TIGHT, packet.assessment.spread_state)
        self.assertEqual(STABLE, packet.assessment.quote_stability_state)
        self.assertEqual(LOW, packet.assessment.price_impact_risk_state)
        self.assertEqual(LOW, packet.assessment.fill_risk_state)
        self.assertEqual(COMPLETE, packet.assessment.data_quality_state)
        self.assertEqual(
            "EXECUTION_CONDITIONS_SUPPORT", packet.opinion.opinion_code
        )
        self.assertEqual(EVALUATED, packet.opinion.evaluation_status)
        self.assertEqual(NON_DIRECTIONAL, packet.opinion.directional_bias)
        self.assertEqual(RESEARCH_ONLY, packet.opinion.authority)
        self.assertEqual(
            EXECUTION_AUTHORITY_NONE, packet.opinion.execution_authority
        )
        self.assertFalse(packet.assessment.trade_recommendation)
        self.assertEqual(PRE_DECISION_EXECUTION_QUALITY, packet.evidence_domain)

    def test_b_wide_spread_relative_to_stop_is_fragile_or_poor(self) -> None:
        packet = self.evaluate(quotes=quotes(bids=(99.70, 99.70, 99.70), asks=(100.30, 100.30, 100.30)))

        self.assertEqual(EXTREME, packet.assessment.spread_state)
        self.assertEqual(HIGH, packet.assessment.fill_risk_state)
        self.assertEqual("EXECUTION_CONDITIONS_POOR", packet.opinion.opinion_code)
        self.assertIn("SPREAD_LARGE_RELATIVE_TO_STOP", packet.assessment.reason_codes)

    def test_c_quote_instability_and_expanding_spread_are_preserved(self) -> None:
        values = quotes(
            bids=(99.90, 100.30, 99.50, 100.50),
            asks=(99.92, 100.35, 99.65, 101.00),
        )
        packet = self.evaluate(quotes=values)

        self.assertIn(packet.assessment.quote_stability_state, {UNSTABLE, DISLOCATED})
        self.assertGreater(
            packet.assessment.quote_stability_features.spread_expansion_multiple,
            1,
        )
        self.assertIn(
            packet.opinion.opinion_code,
            {"EXECUTION_CONDITIONS_FRAGILE", "EXECUTION_CONDITIONS_DISLOCATED"},
        )

    def test_d_high_volume_without_price_progress_is_diagnostic_not_score(self) -> None:
        values = bars(prior_volume=5_000, recent_volume=100_000, recent_step=0.0)
        packet = self.evaluate(candles=values)

        self.assertTrue(packet.assessment.volume_progress_features.volume_without_progress)
        self.assertIn(
            "VOLUME_EXPANSION_WITHOUT_PRICE_PROGRESS",
            packet.assessment.reason_codes,
        )
        self.assertFalse(hasattr(packet.assessment, "execution_score"))

    def test_e_thin_volume_rapid_move_elevates_impact_and_fill_risk(self) -> None:
        values = bars(prior_volume=100, recent_volume=100, recent_step=0.35)
        packet = self.evaluate(candles=values)

        self.assertEqual(VERY_THIN, packet.assessment.liquidity_state)
        self.assertTrue(packet.assessment.volume_progress_features.thin_volume_rapid_move)
        self.assertEqual(HIGH, packet.assessment.price_impact_risk_state)
        self.assertEqual(HIGH, packet.assessment.fill_risk_state)

    def test_trade_plan_sensitivity_is_counterfactual_and_does_not_mutate_plan(self) -> None:
        original = plan()
        before = copy.deepcopy(original)

        packet = self.evaluate(trade_plan=original)

        self.assertEqual(original, before)
        self.assertIsNotNone(
            packet.assessment.spread_features.current_ask_vs_planned_entry_percent
        )
        self.assertIsNotNone(
            packet.assessment.spread_features.current_bid_distance_to_stop
        )
        self.assertEqual((0, 5, 10, 25), tuple(
            item.basis_points for item in packet.assessment.slippage_sensitivity
        ))
        self.assertTrue(all(
            item.evidence_class == MATHEMATICAL_COUNTERFACTUAL
            for item in packet.assessment.slippage_sensitivity
        ))
        self.assertLess(
            packet.assessment.slippage_sensitivity[-1].reward_risk,
            packet.assessment.slippage_sensitivity[0].reward_risk,
        )

    def test_data005b_quantity_is_used_only_for_dollar_risk_sensitivity(self) -> None:
        trade_plan = plan()
        decision = allocation(trade_plan.plan_id)
        packet = self.evaluate(trade_plan=trade_plan, allocation=decision)

        point = packet.assessment.slippage_sensitivity[0]
        self.assertAlmostEqual(
            point.risk_per_share * float(decision.final_authorized_quantity),
            point.dollar_risk_at_authorized_quantity,
            places=8,
        )
        self.assertFalse(hasattr(packet.assessment, "filled_quantity"))

    def test_capability_registry_is_referenced_without_provider_inference(self) -> None:
        registry = capabilities()
        packet = self.evaluate(broker_capabilities=registry)

        self.assertEqual(
            registry.fingerprint.lower(),
            packet.assessment.capability_registry_fingerprint,
        )
        self.assertIn("BROKER_STATE", packet.opinion.feature_families)
        self.assertNotIn("ALPACA", packet.assessment.reason_codes)
        self.assertIn(
            "CAPABILITY_REGISTRY_HAS_NO_NATIVE_AS_OF_TIMESTAMP",
            packet.assessment.limitations,
        )

    def test_displayed_size_is_unsupported_unless_observed_evidence_exists(self) -> None:
        packet = self.evaluate()

        self.assertEqual(UNSUPPORTED, packet.assessment.displayed_size_state)
        self.assertIn("DISPLAYED_SIZE_NOT_OBSERVED", packet.assessment.limitations)
        self.assertEqual(LIQUID, packet.assessment.liquidity_state)

    def test_observed_displayed_size_is_preserved_but_not_depth(self) -> None:
        packet = self.evaluate(quotes=quotes(size_state=OBSERVED))

        self.assertEqual(OBSERVED, packet.assessment.displayed_size_state)
        self.assertIn("NO_LEVEL_2_ORDER_BOOK_EVIDENCE", packet.assessment.limitations)

    def test_locked_market_is_explicitly_dislocated_not_trade_authority(self) -> None:
        packet = self.evaluate(quotes=quotes(bids=(100, 100, 100), asks=(100, 100, 100)))

        self.assertEqual(LOCKED_MARKET, packet.assessment.market_state)
        self.assertEqual(
            "EXECUTION_CONDITIONS_DISLOCATED", packet.opinion.opinion_code
        )
        self.assertEqual(EXECUTION_AUTHORITY_NONE, packet.opinion.execution_authority)

    def test_authoritative_halt_abstains_without_guessing_from_missing_data(self) -> None:
        values = tuple(replace(item, trading_state="HALTED", fingerprint="") for item in quotes())
        values = tuple(replace(item, fingerprint=fingerprint_without(item)) for item in values)

        packet = self.evaluate(quotes=values)

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("HALTED", packet.assessment.market_state)
        self.assertIn("AUTHORITATIVE_HALT_STATUS", packet.assessment.reason_codes)

    def test_regular_session_and_quote_chronology_are_preserved(self) -> None:
        packet = self.evaluate()

        self.assertEqual(REGULAR, packet.assessment.session_state)
        self.assertEqual(SOURCE, packet.assessment.source_identity)
        self.assertGreaterEqual(packet.assessment.quote_age_seconds, 0)
        self.assertLessEqual(
            packet.assessment.quote_age_seconds,
            self.policy.maximum_quote_age_seconds,
        )

    def test_extended_hours_preserves_safe_spread_then_abstains(self) -> None:
        observed = datetime(2026, 8, 17, 21, 10, 10, tzinfo=timezone.utc)
        values = quotes(evaluated_at=observed, session=AFTER_HOURS)
        packet = self.evaluate(
            evaluated_at=observed,
            quotes=values,
            candles=(),
            trade_plan=None,
            setup_id=None,
        )

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("UNSUPPORTED_SESSION", packet.opinion.abstention_reason)
        self.assertIsNotNone(packet.assessment.spread_features.spread_basis_points)
        self.assertEqual(UNKNOWN, packet.assessment.quote_stability_state)

    def test_heuristic_confidence_is_not_probability(self) -> None:
        packet = self.evaluate()

        self.assertEqual(HEURISTIC, packet.opinion.confidence.kind)
        self.assertEqual(UNCALIBRATED, packet.opinion.confidence.calibration_status)
        self.assertIsNone(packet.opinion.confidence.sample_size)
        self.assertIn("not a fill probability", packet.opinion.explanation)

    def test_packet_is_frozen_deterministic_and_byte_stable(self) -> None:
        first = self.evaluate()
        second = self.evaluate(quotes=tuple(reversed(quotes())))

        self.assertEqual(first, second)
        self.assertEqual(packet_json_bytes(first), packet_json_bytes(second))
        self.assertTrue(packet_json_bytes(first).endswith(b"\n"))
        with self.assertRaises(FrozenInstanceError):
            first.assessment.fill_risk_state = HIGH  # type: ignore[misc]


class ExecutionQualityAbstentionAndFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = default_execution_quality_policy()

    def evaluate(self, **kwargs):
        return evaluate_execution_quality(
            opportunity_id=OPPORTUNITY_ID,
            candidate_id=CANDIDATE_ID,
            setup_id=kwargs.pop("setup_id", SETUP_ID),
            symbol=SYMBOL,
            evaluated_at=kwargs.pop("evaluated_at", EVALUATED_AT),
            quotes=kwargs.pop("quotes", quotes()),
            candles=kwargs.pop("candles", bars()),
            policy=kwargs.pop("policy", self.policy),
            trade_plan=kwargs.pop("trade_plan", plan()),
            **kwargs,
        )

    def test_f_stale_quote_abstains_as_data_unsafe_not_neutral(self) -> None:
        values = quotes(evaluated_at=EVALUATED_AT - timedelta(minutes=2))
        packet = self.evaluate(quotes=values)

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("STALE_EVIDENCE", packet.opinion.abstention_reason)
        self.assertEqual(NO_OPINION, packet.opinion.opinion_code)
        self.assertEqual(NO_DIRECTION, packet.opinion.directional_bias)
        self.assertEqual(PARTIAL, packet.assessment.data_quality_state)

    def test_g_missing_bid_missing_ask_zero_bid_and_crossed_market_fail_closed(self) -> None:
        cases = (
            quotes(bids=(None, None, None)),
            quotes(asks=(None, None, None)),
            quotes(bids=(0, 0, 0)),
            quotes(bids=(101, 101, 101), asks=(100, 100, 100)),
        )
        for values in cases:
            with self.subTest(values=values[0]):
                packet = self.evaluate(quotes=values)
                self.assertEqual(FAILED, packet.opinion.evaluation_status)
                self.assertEqual(DATA_UNSAFE, packet.assessment.data_quality_state)
                self.assertIsNone(packet.opinion.opinion_code)

    def test_nonfinite_quote_is_rejected_at_input_boundary(self) -> None:
        with self.assertRaisesRegex(ExecutionQualityError, "finite"):
            quotes(bids=(math.nan, math.nan, math.nan))

    def test_future_quote_and_future_receipt_fail(self) -> None:
        future = quotes(evaluated_at=EVALUATED_AT + timedelta(seconds=20))
        packet = self.evaluate(quotes=future)

        self.assertEqual(FAILED, packet.opinion.evaluation_status)
        self.assertIn("FUTURE", packet.opinion.failure_reason)

    def test_timezone_naive_quote_is_rejected_at_input_boundary(self) -> None:
        with self.assertRaisesRegex(ExecutionQualityError, "UTC offset"):
            build_quote_observation(
                quote_id="naive-quote",
                symbol=SYMBOL,
                bid=100,
                ask=100.01,
                provider_quote_time=datetime(2026, 8, 17, 14, 40),
                provider_bid_time=EVALUATED_AT,
                provider_ask_time=EVALUATED_AT,
                receipt_time=EVALUATED_AT,
                source_identity=SOURCE,
                session=REGULAR,
            )

    def test_wrong_symbol_session_and_conflicting_source_fail(self) -> None:
        wrong_symbol = list(quotes())
        wrong_symbol[1] = replace(wrong_symbol[1], symbol="QQQ", fingerprint="")
        wrong_symbol[1] = replace(
            wrong_symbol[1], fingerprint=fingerprint_without(wrong_symbol[1])
        )
        wrong_session = quotes(session=AFTER_HOURS)
        mixed_source = list(quotes())
        mixed_kwargs = quote_kwargs(1)
        mixed_kwargs["source_identity"] = "different-source"
        mixed_source[1] = build_quote_observation(**mixed_kwargs, bid=100, ask=100.02)

        for values in (tuple(wrong_symbol), wrong_session, tuple(mixed_source)):
            with self.subTest(values=values):
                self.assertEqual(FAILED, self.evaluate(quotes=values).opinion.evaluation_status)

    def test_bid_ask_component_skew_fails(self) -> None:
        values = list(quotes())
        row = values[-1]
        values[-1] = build_quote_observation(
            quote_id=row.quote_id,
            symbol=row.symbol,
            bid=row.bid,
            ask=row.ask,
            provider_quote_time=row.provider_quote_time,
            provider_bid_time=EVALUATED_AT - timedelta(seconds=20),
            provider_ask_time=row.provider_ask_time,
            receipt_time=row.receipt_time,
            source_identity=row.source_identity,
            session=row.session,
        )

        self.assertEqual(FAILED, self.evaluate(quotes=tuple(values)).opinion.evaluation_status)

    def test_quote_sequence_unavailable_abstains_and_stability_remains_unknown(self) -> None:
        packet = self.evaluate(quotes=quotes()[:1])

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("INSUFFICIENT_EVIDENCE", packet.opinion.abstention_reason)
        self.assertIn("QUOTE_SEQUENCE_UNAVAILABLE", packet.opinion.reason_codes)
        self.assertEqual(UNKNOWN, packet.assessment.quote_stability_state)

    def test_quote_and_candle_sequences_are_bounded(self) -> None:
        many_quotes = tuple(
            build_quote_observation(
                quote_id=f"bounded-quote-{index}",
                symbol=SYMBOL,
                bid=100,
                ask=100.02,
                provider_quote_time=EVALUATED_AT - timedelta(seconds=25) + timedelta(milliseconds=index),
                provider_bid_time=EVALUATED_AT - timedelta(seconds=25) + timedelta(milliseconds=index),
                provider_ask_time=EVALUATED_AT - timedelta(seconds=25) + timedelta(milliseconds=index),
                receipt_time=EVALUATED_AT - timedelta(seconds=24) + timedelta(milliseconds=index),
                source_identity=SOURCE,
                session=REGULAR,
            )
            for index in range(self.policy.maximum_quote_observations + 1)
        )
        many_candles = tuple(
            bar(index, timestamp=EVALUATED_AT - timedelta(minutes=100 - index, seconds=10))
            for index in range(self.policy.maximum_candle_observations + 1)
        )

        self.assertEqual(FAILED, self.evaluate(quotes=many_quotes).opinion.evaluation_status)
        self.assertEqual(FAILED, self.evaluate(candles=many_candles).opinion.evaluation_status)

    def test_duplicate_quote_identity_and_timestamp_fail(self) -> None:
        values = quotes()
        duplicate_id = (values[0], values[0], values[2])
        duplicate_kwargs = quote_kwargs(0)
        duplicate_kwargs["quote_id"] = "different-id"
        duplicate_time = (
            values[0],
            build_quote_observation(**duplicate_kwargs, bid=99.99, ask=100.01),
            values[2],
        )

        self.assertEqual(FAILED, self.evaluate(quotes=duplicate_id).opinion.evaluation_status)
        self.assertEqual(FAILED, self.evaluate(quotes=duplicate_time).opinion.evaluation_status)

    def test_quote_tamper_is_detected(self) -> None:
        values = list(quotes())
        values[0] = replace(values[0], ask=999)

        packet = self.evaluate(quotes=tuple(values))

        self.assertEqual(FAILED, packet.opinion.evaluation_status)
        self.assertEqual("QUOTE_EVIDENCE_TAMPERED", packet.opinion.failure_reason)

    def test_missing_volume_and_incomplete_window_abstain(self) -> None:
        missing = list(bars())
        missing[-1] = replace(missing[-1], volume=None, fingerprint="")
        missing[-1] = replace(missing[-1], fingerprint=fingerprint_without(missing[-1]))

        for values in (tuple(missing), bars()[:10]):
            with self.subTest(count=len(values)):
                packet = self.evaluate(candles=values)
                self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)

    def test_tampered_candle_wrong_symbol_source_gap_and_future_fail(self) -> None:
        tampered = list(bars())
        tampered[-1] = replace(tampered[-1], close=999)
        wrong_symbol = rebuilt_bar_sequence(change_index=3, symbol="QQQ")
        wrong_source = rebuilt_bar_sequence(change_index=3, source_identity="other-source")
        gap = list(bars())
        original_gap = gap[5]
        gap[5] = build_minute_bar(
            evidence_id=original_gap.evidence_id,
            symbol=original_gap.symbol,
            timestamp=datetime.fromisoformat(original_gap.timestamp.replace("Z", "+00:00"))
            + timedelta(seconds=30),
            open=original_gap.open,
            high=original_gap.high,
            low=original_gap.low,
            close=original_gap.close,
            volume=original_gap.volume,
            source_identity=original_gap.source_identity,
            state=original_gap.state,
            session_date=original_gap.session_date,
        )
        future = (*bars(), bar(31, timestamp=EVALUATED_AT))

        for values in (tuple(tampered), wrong_symbol, wrong_source, tuple(gap), future):
            with self.subTest(count=len(values)):
                self.assertEqual(FAILED, self.evaluate(candles=values).opinion.evaluation_status)

    def test_malformed_trade_plan_identity_fails(self) -> None:
        malformed = replace(plan(), fingerprint="0" * 64)

        packet = self.evaluate(trade_plan=malformed)

        self.assertEqual(FAILED, packet.opinion.evaluation_status)
        self.assertEqual("TRADE_PLAN_EVIDENCE_INVALID", packet.opinion.failure_reason)

    def test_policy_drift_is_detected(self) -> None:
        packet = self.evaluate()
        tampered = replace(
            packet,
            assessment=replace(packet.assessment, policy_fingerprint="9" * 64),
        )

        with self.assertRaisesRegex(ExecutionQualityError, "Policy fingerprint"):
            validate_packet(tampered)

    def test_execution_authority_tamper_is_rejected(self) -> None:
        packet = self.evaluate()
        tampered = replace(
            packet,
            assessment=replace(packet.assessment, execution_authority="ORDER_ALLOWED"),
        )

        with self.assertRaisesRegex(ExecutionQualityError, "execution authority"):
            validate_packet(tampered)


class ObservedExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet = evaluate_execution_quality(
            opportunity_id=OPPORTUNITY_ID,
            candidate_id=CANDIDATE_ID,
            setup_id=SETUP_ID,
            symbol=SYMBOL,
            evaluated_at=EVALUATED_AT,
            quotes=quotes(),
            candles=bars(),
            policy=default_execution_quality_policy(),
            trade_plan=plan(),
        )

    def test_h_partial_fill_uses_actual_quantity_only_and_does_not_leak_backward(self) -> None:
        original_json = packet_json_bytes(self.packet)
        result = execution_result(
            fill_state=PARTIAL_FILL,
            requested_quantity=1.0,
            filled_quantity=0.4,
            confirmed_position_quantity=0.4,
            average_fill_price=100.05,
        )

        record = attach_observed_execution_result(
            self.packet, result, trade_plan=plan()
        )

        self.assertEqual(0.4, record.observed_metrics.actual_filled_quantity)
        self.assertEqual(0.4, record.observed_metrics.quantity_fill_ratio)
        self.assertEqual(self.packet.opinion.opinion_id, record.original_opinion_id)
        self.assertEqual(
            self.packet.opinion.fingerprint, record.original_opinion_fingerprint
        )
        self.assertEqual(original_json, packet_json_bytes(record.original_packet))
        self.assertNotIn("filledQuantity", packet_json_bytes(self.packet).decode("ascii"))

    def test_i_positive_slippage_and_j_negative_slippage(self) -> None:
        positive = attach_observed_execution_result(
            self.packet,
            execution_result(average_fill_price=100.05),
            trade_plan=plan(),
        )
        negative = attach_observed_execution_result(
            self.packet,
            execution_result(average_fill_price=99.99),
            trade_plan=plan(),
        )

        self.assertGreater(positive.observed_metrics.fill_slippage_basis_points, 0)
        self.assertGreater(
            positive.observed_metrics.fill_slippage_from_submitted_basis_points,
            0,
        )
        self.assertLess(negative.observed_metrics.fill_slippage_basis_points, 0)
        self.assertIsNotNone(positive.observed_metrics.realized_initial_risk)
        self.assertIsNotNone(
            positive.observed_metrics.realized_execution_reward_risk
        )

    def test_k_no_fill_has_no_slippage_or_invented_fill(self) -> None:
        result = execution_result(
            fill_state=NO_FILL,
            filled_quantity=0,
            confirmed_position_quantity=0,
            average_fill_price=None,
            filled_time=None,
        )
        record = attach_observed_execution_result(self.packet, result, trade_plan=plan())

        self.assertEqual(0, record.observed_metrics.actual_filled_quantity)
        self.assertIsNone(record.observed_metrics.fill_slippage_basis_points)
        self.assertIsNone(record.observed_metrics.realized_initial_risk)

    def test_cancelled_remainder_preserves_partial_semantics(self) -> None:
        result = execution_result(
            fill_state=CANCELLED_REMAINDER,
            requested_quantity=1,
            filled_quantity=0.25,
            confirmed_position_quantity=0.25,
            cancelled_time=EVALUATED_AT + timedelta(seconds=8),
        )
        record = attach_observed_execution_result(self.packet, result, trade_plan=plan())

        self.assertEqual(0.25, record.observed_metrics.quantity_fill_ratio)
        self.assertEqual(CANCELLED_REMAINDER, record.observed_result.fill_state)

    def test_impossible_fill_and_fill_greater_than_position_are_rejected(self) -> None:
        with self.assertRaisesRegex(ExecutionQualityError, "exceeds requested"):
            execution_result(requested_quantity=1, filled_quantity=2, confirmed_position_quantity=2)
        with self.assertRaisesRegex(ExecutionQualityError, "exceeds confirmed"):
            execution_result(requested_quantity=1, filled_quantity=1, confirmed_position_quantity=0.5)

    def test_partial_fill_cannot_masquerade_as_full(self) -> None:
        with self.assertRaisesRegex(ExecutionQualityError, "incorrectly labeled full"):
            execution_result(
                fill_state=FULL_FILL,
                requested_quantity=1,
                filled_quantity=0.5,
                confirmed_position_quantity=0.5,
            )

    def test_no_fill_cannot_carry_slippage_evidence(self) -> None:
        with self.assertRaisesRegex(ExecutionQualityError, "No-fill"):
            execution_result(
                fill_state=NO_FILL,
                filled_quantity=0,
                confirmed_position_quantity=0,
                average_fill_price=100.05,
            )

    def test_cancelled_remainder_requires_cancellation_timestamp(self) -> None:
        with self.assertRaisesRegex(ExecutionQualityError, "cancellation timestamp"):
            execution_result(
                fill_state=CANCELLED_REMAINDER,
                requested_quantity=1,
                filled_quantity=0.25,
                confirmed_position_quantity=0.25,
                cancelled_time=None,
            )

    def test_wrong_target_and_predecision_chronology_are_rejected(self) -> None:
        wrong = execution_result(opportunity_id="9" * 64)
        early = execution_result(decision_time=EVALUATED_AT - timedelta(seconds=1))

        with self.assertRaisesRegex(ExecutionQualityError, "target identity"):
            attach_observed_execution_result(self.packet, wrong, trade_plan=plan())
        with self.assertRaisesRegex(ExecutionQualityError, "predates"):
            attach_observed_execution_result(self.packet, early, trade_plan=plan())

    def test_research_record_is_deterministic_and_tamper_evident(self) -> None:
        left = attach_observed_execution_result(
            self.packet, execution_result(), trade_plan=plan()
        )
        right = attach_observed_execution_result(
            self.packet, execution_result(), trade_plan=plan()
        )

        self.assertEqual(left, right)
        self.assertEqual(research_record_json_bytes(left), research_record_json_bytes(right))
        self.assertTrue(research_record_json_bytes(left).endswith(b"\n"))


class ExecutionQualityIsolationTests(unittest.TestCase):
    def test_module_has_no_provider_network_broker_order_persistence_or_runtime_imports(self) -> None:
        path = Path(__file__).parents[1] / "momentum_hunter" / "execution_quality_specialist.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        forbidden_fragments = (
            "requests",
            "urllib",
            "socket",
            "httpx",
            "alpaca_paper_broker",
            "schwab_market_data",
            "canonical_candle_store",
            "automation",
            "service",
            "wpf",
            "regime_exhaustion_specialist",
        )
        for fragment in forbidden_fragments:
            self.assertFalse(any(fragment in item for item in imports), fragment)

        call_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        call_names |= {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        forbidden_calls = {
            "submit_order",
            "preview_order",
            "replace_order",
            "cancel_order",
            "open",
            "write_text",
            "write_bytes",
        }
        self.assertFalse(call_names & forbidden_calls)

    def test_no_production_modules_import_execution_quality(self) -> None:
        root = Path(__file__).parents[1] / "momentum_hunter"
        consumers = []
        for path in root.rglob("*.py"):
            if path.name == "execution_quality_specialist.py":
                continue
            if "execution_quality_specialist" in path.read_text(encoding="utf-8"):
                consumers.append(path)
        self.assertEqual([], consumers)

    def test_policy_contains_no_fixed_dollar_account_or_position_law(self) -> None:
        policy = default_execution_quality_policy()
        keys = set(policy.__dict__)
        forbidden = {
            "minimum_stock_price",
            "maximum_notional",
            "account_balance",
            "risk_dollars",
            "maximum_positions",
        }
        self.assertFalse(keys & forbidden)
        self.assertEqual(RESEARCH_HEURISTIC, policy.threshold_semantics)
        self.assertEqual(
            EXECUTION_QUALITY_SPECIALIST_VERSION, policy.specialist_version
        )


def quotes(
    *,
    bids=(99.99, 100.00, 100.01),
    asks=(100.01, 100.02, 100.03),
    evaluated_at=EVALUATED_AT,
    session=REGULAR,
    size_state=UNSUPPORTED,
):
    rows = []
    for index, (bid, ask) in enumerate(zip(bids, asks)):
        kwargs = quote_kwargs(index, evaluated_at=evaluated_at, session=session)
        rows.append(
            build_quote_observation(
                **kwargs,
                bid=bid,
                ask=ask,
                size_evidence_state=size_state,
                bid_size=10_000 if size_state == OBSERVED else None,
                ask_size=12_000 if size_state == OBSERVED else None,
            )
        )
    return tuple(rows)


def quote_kwargs(index, *, evaluated_at=EVALUATED_AT, session=REGULAR):
    stamp = evaluated_at - timedelta(seconds=9 - index * 2)
    return {
        "quote_id": f"quote-{index}",
        "symbol": SYMBOL,
        "provider_quote_time": stamp,
        "provider_bid_time": stamp,
        "provider_ask_time": stamp,
        "receipt_time": stamp + timedelta(milliseconds=100),
        "source_identity": SOURCE,
        "session": session,
    }


def bars(*, prior_volume=30_000, recent_volume=30_000, recent_step=0.01):
    values = []
    price = 100.0
    for index in range(31):
        step = 0.01 if index < 26 else recent_step
        volume = prior_volume if index < 26 else recent_volume
        values.append(bar(index, price=price, close=price + step, volume=volume))
        price += step
    return tuple(values)


def bar(
    index,
    *,
    price=100.0,
    close=None,
    volume=30_000,
    timestamp=None,
    symbol=SYMBOL,
    source_identity=SOURCE,
):
    stamp = timestamp or (EVALUATED_AT - timedelta(minutes=31 - index, seconds=10))
    closing = price + 0.01 if close is None else close
    return build_minute_bar(
        evidence_id=f"bar-{index}",
        symbol=symbol,
        timestamp=stamp,
        open=price,
        high=max(price, closing) + 0.05,
        low=min(price, closing) - 0.05,
        close=closing,
        volume=volume,
        source_identity=source_identity,
        state="RECONCILED",
        session_date="2026-08-17",
    )


def rebuilt_bar_sequence(*, change_index, symbol=SYMBOL, source_identity=SOURCE):
    values = list(bars())
    original = values[change_index]
    values[change_index] = build_minute_bar(
        evidence_id=original.evidence_id,
        symbol=symbol,
        timestamp=original.timestamp,
        open=original.open,
        high=original.high,
        low=original.low,
        close=original.close,
        volume=original.volume,
        source_identity=source_identity,
        state=original.state,
        session_date=original.session_date,
    )
    return tuple(values)


def plan():
    return build_intraday_plan_evidence(
        symbol=SYMBOL,
        setup_family=CONTINUATION_BREAKOUT,
        created_at=datetime(2026, 8, 17, 14, 36, tzinfo=timezone.utc),
        planned_entry=100.03,
        stop_price=99.50,
        target_prices=(101.09,),
        source_setup_fingerprint=SETUP_ID,
        source_level_kind="CONTINUATION_RANGE_HIGH",
        source_evidence_ids=("source-candle-window",),
    )


def allocation(trade_plan_id):
    return ProviderNeutralAllocationDecision(
        decision_cycle_id="cycle-execution-quality-1",
        candidate_id=CANDIDATE_ID,
        canonical_rank=1,
        symbol=SYMBOL,
        trade_plan_id=trade_plan_id,
        risk_decision_id="risk-decision-1",
        account_lane="SYNTHETIC_RESEARCH",
        provider="PROVIDER_NEUTRAL",
        environment="TEST_ONLY",
        request_fingerprint="3" * 64,
        policy_fingerprint="4" * 64,
        account_snapshot_fingerprint="5" * 64,
        capability_registry_fingerprint="6" * 64,
        status=AllocationStatus.AUTHORIZED,
        quantity_mode=QuantityMode.FRACTIONAL,
        quantity_increment=Decimal("0.00000001"),
        ideal_risk_quantity=Decimal("2"),
        provider_executable_quantity=Decimal("0.75"),
        final_authorized_quantity=Decimal("0.75"),
        risk_per_share=Decimal("0.53"),
        effective_cash_available=Decimal("100"),
        effective_open_risk_available=Decimal("2"),
        position_notional=Decimal("75.0225"),
        total_risk=Decimal("0.3975"),
        target_reward=Decimal("0.795"),
    )


def capabilities():
    return BrokerCapabilityRegistry.build(
        provider="PROVIDER_NEUTRAL",
        environment="TEST_ONLY",
        capabilities=(
            BrokerCapability(
                name="supportsMarketOrder",
                state=CapabilityState.PROVEN,
                value="true",
                evidence=("synthetic capability fixture",),
            ),
        ),
    )


def execution_result(**overrides):
    values = {
        "opportunity_id": OPPORTUNITY_ID,
        "candidate_id": CANDIDATE_ID,
        "setup_id": SETUP_ID,
        "trade_plan_id": plan().plan_id,
        "symbol": SYMBOL,
        "provider": "ALPACA_PAPER",
        "environment": "PAPER_ONLY",
        "source_identity": "paper-005-confirmed-provider-order",
        "source_fingerprint": "7" * 64,
        "decision_ask": 100.03,
        "submitted_reference": 100.03,
        "requested_quantity": 1.0,
        "requested_notional": None,
        "fill_state": FULL_FILL,
        "filled_quantity": 1.0,
        "confirmed_position_quantity": 1.0,
        "average_fill_price": 100.05,
        "decision_time": EVALUATED_AT,
        "submitted_time": EVALUATED_AT + timedelta(seconds=1),
        "accepted_time": EVALUATED_AT + timedelta(seconds=2),
        "filled_time": EVALUATED_AT + timedelta(seconds=3),
        "cancelled_time": None,
    }
    values.update(overrides)
    return build_observed_execution_result(**values)


def fingerprint_without(value):
    from dataclasses import asdict
    import hashlib
    import json

    payload = asdict(replace(value, fingerprint=""))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


if __name__ == "__main__":
    unittest.main()
