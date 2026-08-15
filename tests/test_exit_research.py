from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from momentum_hunter.exit_research import (
    ABSTAINED_STATE,
    ACTUAL_BROKER_EXECUTION,
    ACTUAL_EXECUTABLE_RESULT,
    ACTUAL_FROZEN_CONTROL,
    ACTIVE,
    AMBIGUOUS_SAME_BAR,
    BREAK_EVEN,
    COUNTERFACTUAL_EXIT_SIGNAL,
    COUNTERFACTUAL_MARKET_PATH_RESULT,
    DATA_FAILURE,
    EXECUTION_UNKNOWN,
    EXITED,
    EXIT_SIGNALLED_EXECUTION_UNKNOWN,
    FILLED,
    MARKET_PATH_ONLY,
    MOMENTUM_FAILURE,
    OPEN,
    PARTIALLY_FILLED,
    PARTIAL_EXIT,
    REGIME_DETERIORATION,
    RESEARCH_IDENTITY,
    STRUCTURAL_STOP,
    TERMINAL,
    TIME_STOP,
    TRAILING_STOP,
    UNFILLED,
    ExitCounterfactualPath,
    ExitResearchError,
    build_actual_execution_fill,
    build_actual_trade_evidence,
    build_exit_research_bar,
    build_structural_stop_evidence,
    default_exit_research_policy,
    evaluate_exit_research,
    evaluation_json_bytes,
    prospective_sample_definition,
    validate_counterfactual_path,
    validate_exit_research_control,
    validate_exit_research_policy,
)
from momentum_hunter.specialist_opinion import (
    EVALUATED,
    NON_DIRECTIONAL,
    RESEARCH_ONLY,
    EXECUTION_AUTHORITY_NONE,
    build_evidence_reference,
    build_specialist_opinion,
    unavailable_confidence,
)


BASE = datetime(2026, 8, 14, 14, 30, tzinfo=timezone.utc)
OPPORTUNITY = "1" * 64
OPPORTUNITY_FP = "2" * 64
SETUP = "3" * 64
PLAN = "4" * 64
PLAN_FP = "5" * 64
SAMPLE_POLICY = "6" * 64


def evidence(
    identity: str,
    at: datetime,
    *,
    evidence_type: str = "MARKET_BAR",
    source: str = "test-fixture",
    seed: int = 7,
):
    return build_evidence_reference(
        evidence_id=identity,
        evidence_type=evidence_type,
        source=source,
        as_of=at,
        fingerprint=f"{seed:064x}",
    )


def bar(
    index: int,
    *,
    open_price: object = "100",
    high: object = "101",
    low: object = "99.5",
    close: object = "100.5",
    atr: object | None = "1",
    symbol: str = "TEST",
    complete: bool = True,
    started_at: datetime | None = None,
):
    start = started_at or BASE + timedelta(minutes=index)
    completed = start + timedelta(minutes=1)
    return build_exit_research_bar(
        bar_id=f"bar/{index}/{int(start.timestamp())}",
        symbol=symbol,
        started_at=start,
        completed_at=completed,
        known_at=completed,
        open_price=open_price,
        high_price=high,
        low_price=low,
        close_price=close,
        volume="1000",
        atr=atr,
        evidence=evidence(f"evidence/bar/{index}/{int(start.timestamp())}", completed, seed=100 + index),
        is_complete=complete,
    )


def actual_fill(
    identity: str,
    minutes: int,
    quantity: object,
    price: object,
    reason: str,
):
    at = BASE + timedelta(minutes=minutes)
    return build_actual_execution_fill(
        fill_id=identity,
        filled_at=at,
        quantity=quantity,
        average_price=price,
        reason_code=reason,
        evidence=evidence(
            f"evidence/{identity}",
            at,
            evidence_type="BROKER_FILL",
            source="alpaca-paper",
            seed=400 + minutes,
        ),
    )


def trade(
    *,
    entry_status: str = FILLED,
    entry: object = "100",
    quantity: object = "1",
    stop: object = "98",
    targets: tuple[object, ...] = ("102", "104"),
    forced_minutes: int = 360,
    terminal_state: str = OPEN,
    exits=(),
    symbol: str = "TEST",
    side: str = "LONG",
    session: str = "REGULAR",
    sample_identity: str = "paper-engineering-v2",
    sample_policy_fingerprint: str = SAMPLE_POLICY,
    provider_environment_id: str = "alpaca-paper",
    entry_order_id: str = "order/entry-1",
):
    filled = entry_status in {FILLED, PARTIALLY_FILLED}
    refs = (
        evidence(
            "evidence/trade-plan",
            BASE,
            evidence_type="TRADE_PLAN",
            source="data004",
            seed=11,
        ),
        evidence(
            entry_order_id,
            BASE,
            evidence_type="BROKER_ORDER",
            source="alpaca-paper",
            seed=12,
        ),
    ) + (
        (
            evidence(
                "fill/entry-1",
                BASE,
                evidence_type="BROKER_FILL",
                source="alpaca-paper",
                seed=13,
            ),
        )
        if filled
        else ()
    )
    return build_actual_trade_evidence(
        trade_id="trade/test-1",
        opportunity_id=OPPORTUNITY,
        opportunity_fingerprint=OPPORTUNITY_FP,
        candidate_id="candidate/test-1",
        setup_id=SETUP,
        trade_plan_id=PLAN,
        trade_plan_fingerprint=PLAN_FP,
        sample_identity=sample_identity,
        sample_policy_fingerprint=sample_policy_fingerprint,
        provider_environment_id=provider_environment_id,
        symbol=symbol,
        entry_order_id=entry_order_id,
        entry_status=entry_status,
        actual_average_fill=entry if filled else None,
        actual_filled_quantity=quantity if filled else "0",
        actual_fill_at=BASE if filled else None,
        entry_fill_id="fill/entry-1" if filled else None,
        original_protective_stop=stop if filled else None,
        original_targets=targets if filled else (),
        forced_flat_at=BASE + timedelta(minutes=forced_minutes),
        actual_terminal_state=terminal_state,
        actual_exit_fills=exits,
        evidence_refs=refs,
        side=side,
        session=session,
    )


def structure(level: object = "99", *, known_at: datetime = BASE, effective_at: datetime = BASE):
    return build_structural_stop_evidence(
        structure_id="structure/test-1",
        opportunity_id=OPPORTUNITY,
        candidate_id="candidate/test-1",
        setup_id=SETUP,
        trade_plan_id=PLAN,
        symbol="TEST",
        level=level,
        known_at=known_at,
        effective_at=effective_at,
        evidence=evidence(
            "evidence/structure-1",
            known_at,
            evidence_type="TECHNICAL_STRUCTURE",
            source="technical-structure",
            seed=15,
        ),
    )


def specialist_opinion(
    specialist: str,
    code: str,
    at: datetime,
    *,
    candidate: str = "candidate/test-1",
    setup_id: str = SETUP,
    plan_id: str = PLAN,
):
    ref = evidence(
        f"evidence/opinion/{specialist}/{int(at.timestamp())}",
        at,
        evidence_type="SPECIALIST_INPUT",
        source="specialist-fixture",
        seed=20 + int(at.timestamp()) % 100,
    )
    family = "MARKET_REGIME" if specialist == "REGIME" else "CANDLE_STRUCTURE"
    return build_specialist_opinion(
        specialist_id=specialist,
        specialist_version=f"{specialist.lower()}-research-v1",
        opportunity_id=OPPORTUNITY,
        candidate_id=candidate,
        setup_id=setup_id,
        trade_plan_id=plan_id,
        as_of=at,
        expires_at=at + timedelta(minutes=30),
        research_identity="sibling-research-v1",
        policy_fingerprint="9" * 64,
        evaluation_status=EVALUATED,
        opinion_code=code,
        directional_bias=NON_DIRECTIONAL,
        evidence_refs=(ref,),
        feature_families=(family,),
        confidence=unavailable_confidence(),
        reason_codes=(code,),
        explanation="Synthetic sibling opinion for contract testing.",
    )


def evaluate(
    bars,
    *,
    actual=None,
    structural=None,
    momentum=(),
    regime=(),
    evaluated_at=None,
):
    rows = tuple(bars)
    cutoff = evaluated_at or (BASE + timedelta(minutes=max(1, len(rows))))
    return evaluate_exit_research(
        trade=actual or trade(),
        bars=rows,
        evaluated_at=cutoff,
        structural_stop=structural,
        momentum_opinions=momentum,
        regime_opinions=regime,
    )


def path(result, method: str) -> ExitCounterfactualPath:
    return next(item for item in result.paths if item.method == method)


class ExitResearchReferenceFixtureTests(unittest.TestCase):
    def test_actual_control_preserves_target_one_then_target_two(self):
        exits = (
            actual_fill("fill/exit-1", 5, "0.5", "102", "TARGET_1"),
            actual_fill("fill/exit-2", 10, "0.5", "104", "TARGET_2"),
        )
        result = evaluate(
            [bar(0)],
            actual=trade(terminal_state=TERMINAL, exits=exits),
        )
        control = result.control
        self.assertIsNotNone(control)
        assert control is not None
        self.assertEqual(ACTUAL_FROZEN_CONTROL, control.method)
        self.assertEqual(ACTUAL_EXECUTABLE_RESULT, control.actual_result_domain)
        self.assertEqual(Decimal("1.5"), control.actual_result_r)
        self.assertEqual(("TARGET_1", "TARGET_2"), tuple(item.reason_code for item in control.actual_exit_fills))

    def test_structural_stop_exits_before_original_stop(self):
        result = evaluate(
            [bar(0, high="100.5", low="98.8", close="99")],
            structural=structure("99"),
        )
        item = path(result, STRUCTURAL_STOP)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertEqual(Decimal("99"), item.exit_reference_price)
        self.assertEqual(Decimal("-0.5"), item.reference_r)

    def test_missing_structure_abstains(self):
        item = path(evaluate([bar(0)]), STRUCTURAL_STOP)
        self.assertEqual(ABSTAINED_STATE, item.evaluation_state)
        self.assertIn("MISSING_REQUIRED_STRUCTURE_EVIDENCE", item.reason_codes)

    def test_trailing_stop_ratchets_then_triggers(self):
        rows = (
            bar(0, high="103", low="100", close="102", atr="1"),
            bar(1, open_price="102", high="102.5", low="100.5", close="101", atr="1"),
        )
        item = path(evaluate(rows), TRAILING_STOP)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertEqual(Decimal("101"), item.exit_reference_price)
        updates = [event.reference_price for event in item.events if event.event_type == "STOP_UPDATED"]
        self.assertEqual([Decimal("101")], updates)

    def test_trailing_same_bar_does_not_invent_favorable_order(self):
        item = path(
            evaluate([bar(0, high="103", low="99.5", close="102", atr="1")]),
            TRAILING_STOP,
        )
        self.assertEqual(OPEN, item.terminal_state)
        self.assertEqual(Decimal("101"), item.active_stop)
        self.assertNotIn("STOP_LEVEL_CROSSED", item.reason_codes)

    def test_time_stop_exits_stagnant_trade(self):
        rows = tuple(
            bar(i, high="100.3", low="99.7", close="100") for i in range(60)
        )
        item = path(evaluate(rows), TIME_STOP)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertIn("TIME_STOP_ELAPSED", item.reason_codes)
        self.assertEqual(3600, item.duration_seconds)

    def test_break_even_arms_then_later_triggers(self):
        rows = (
            bar(0, open_price="100.5", high="102.2", low="100.2", close="102"),
            bar(1, open_price="101.5", high="101.7", low="99.9", close="100"),
        )
        item = path(evaluate(rows), BREAK_EVEN)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertEqual(Decimal("100"), item.exit_reference_price)
        self.assertEqual(Decimal("0"), item.reference_r)

    def test_break_even_same_bar_is_ambiguous(self):
        item = path(
            evaluate([bar(0, high="102.2", low="99.9", close="101")]),
            BREAK_EVEN,
        )
        self.assertEqual(AMBIGUOUS_SAME_BAR, item.terminal_state)
        self.assertIsNone(item.reference_r)

    def test_partial_exit_uses_target_one_and_runner(self):
        rows = (
            bar(0, high="102.2", low="99", close="102"),
            bar(1, open_price="102", high="104.2", low="101", close="104"),
        )
        item = path(evaluate(rows), PARTIAL_EXIT)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertEqual(2, len(item.exit_legs))
        self.assertEqual(Decimal("1"), sum((leg.quantity for leg in item.exit_legs), Decimal("0")))
        self.assertEqual(Decimal("1.5"), item.reference_r)
        exit_event = next(
            event for event in reversed(item.events) if event.event_type == "EXIT_SIGNAL"
        )
        self.assertEqual(Decimal("0.5"), exit_event.quantity)

    def test_partial_runner_stop_uses_only_remaining_quantity(self):
        rows = (
            bar(0, high="102.2", low="99", close="102"),
            bar(1, open_price="101", high="101.5", low="97.5", close="98"),
        )
        item = path(evaluate(rows), PARTIAL_EXIT)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertEqual(
            (Decimal("0.5"), Decimal("0.5")),
            tuple(leg.quantity for leg in item.exit_legs),
        )
        exit_event = next(
            event for event in reversed(item.events) if event.event_type == "EXIT_SIGNAL"
        )
        self.assertEqual(Decimal("0.5"), exit_event.quantity)

    def test_partial_target_and_stop_same_bar_is_ambiguous(self):
        item = path(
            evaluate([bar(0, high="102.2", low="97.8", close="100")]),
            PARTIAL_EXIT,
        )
        self.assertEqual(AMBIGUOUS_SAME_BAR, item.terminal_state)
        self.assertEqual(0, len(item.exit_legs))

    def test_prospective_momentum_failure_opinion_triggers(self):
        opinion = specialist_opinion("MOMENTUM", "MOMENTUM_FAILURE", BASE + timedelta(minutes=1))
        item = path(evaluate([bar(0)], momentum=(opinion,)), MOMENTUM_FAILURE)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertIn("MOMENTUM_FAILURE_OPINION", item.reason_codes)

    def test_pushed_tech_v2_opinion_vocabulary_is_compatible(self):
        opinion = specialist_opinion(
            "TECHNICAL_STRUCTURE",
            "STRUCTURE_CONTRADICTS",
            BASE + timedelta(minutes=1),
        )
        item = path(evaluate([bar(0)], momentum=(opinion,)), MOMENTUM_FAILURE)
        self.assertEqual(EXITED, item.terminal_state)

    def test_future_momentum_opinion_is_rejected(self):
        opinion = specialist_opinion("MOMENTUM", "MOMENTUM_FAILURE", BASE + timedelta(minutes=5))
        with self.assertRaisesRegex(ExitResearchError, "Future specialist"):
            evaluate([bar(0)], momentum=(opinion,), evaluated_at=BASE + timedelta(minutes=1))

    def test_prospective_regime_deterioration_opinion_triggers(self):
        opinion = specialist_opinion("REGIME", "MARKET_STRESS", BASE + timedelta(minutes=1))
        item = path(evaluate([bar(0)], regime=(opinion,)), REGIME_DETERIORATION)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertIn("REGIME_DETERIORATION_OPINION", item.reason_codes)

    def test_pushed_regime_v2_opinion_vocabulary_is_compatible(self):
        opinion = specialist_opinion(
            "REGIME", "EXHAUSTION_RISK", BASE + timedelta(minutes=1)
        )
        item = path(evaluate([bar(0)], regime=(opinion,)), REGIME_DETERIORATION)
        self.assertEqual(EXITED, item.terminal_state)

    def test_later_regime_opinion_cannot_change_earlier_stop(self):
        rows = (
            bar(0, high="100.5", low="99.5", close="100"),
            bar(1, open_price="100", high="101", low="99", close="100"),
            bar(2, open_price="100", high="101", low="99", close="100"),
        )
        early = specialist_opinion("REGIME", "MARKET_STRESS", BASE + timedelta(minutes=1))
        late = specialist_opinion("REGIME", "RISK_OFF", BASE + timedelta(minutes=2))
        without = path(evaluate(rows, regime=(early,)), REGIME_DETERIORATION)
        with_late = path(evaluate(rows, regime=(early, late)), REGIME_DETERIORATION)
        self.assertEqual(without.fingerprint, with_late.fingerprint)

    def test_gap_through_stop_does_not_fabricate_fill(self):
        item = path(
            evaluate([bar(0, open_price="97", high="97.5", low="96", close="97")]),
            TIME_STOP,
        )
        self.assertEqual(EXIT_SIGNALLED_EXECUTION_UNKNOWN, item.terminal_state)
        self.assertEqual(EXECUTION_UNKNOWN, item.execution_evidence_status)
        self.assertIsNone(item.reference_r)
        self.assertEqual(0, len(item.exit_legs))
        self.assertEqual(Decimal("1"), item.remaining_quantity)

    def test_missing_and_stale_bars_are_data_failure(self):
        missing = evaluate([], evaluated_at=BASE + timedelta(minutes=1))
        self.assertEqual(DATA_FAILURE, missing.evaluation_state)
        stale = evaluate([bar(0)], evaluated_at=BASE + timedelta(minutes=10))
        self.assertEqual(DATA_FAILURE, stale.evaluation_state)
        self.assertIn("STALE_EVIDENCE", stale.reason_codes)

    def test_unfilled_actual_entry_abstains(self):
        result = evaluate([], actual=trade(entry_status=UNFILLED), evaluated_at=BASE + timedelta(minutes=1))
        self.assertEqual(ABSTAINED_STATE, result.evaluation_state)
        self.assertIsNone(result.control)
        self.assertEqual(0, len(result.paths))

    def test_unsupported_side_abstains_out_of_domain(self):
        result = evaluate(
            [],
            actual=trade(side="SHORT", stop="102", targets=("98", "96")),
        )
        self.assertEqual(ABSTAINED_STATE, result.evaluation_state)
        self.assertIsNone(result.control)
        self.assertEqual((), result.paths)
        self.assertIn("OUT_OF_DOMAIN", result.reason_codes)
        self.assertIn("UNSUPPORTED_SIDE", result.reason_codes)
        self.assertEqual("OUT_OF_DOMAIN", result.opinions[0].abstention_reason)

    def test_unsupported_session_abstains_out_of_domain(self):
        result = evaluate([], actual=trade(session="PREMARKET"))
        self.assertEqual(ABSTAINED_STATE, result.evaluation_state)
        self.assertIsNone(result.control)
        self.assertEqual((), result.paths)
        self.assertIn("OUT_OF_DOMAIN", result.reason_codes)
        self.assertIn("UNSUPPORTED_SESSION", result.reason_codes)
        self.assertEqual("OUT_OF_DOMAIN", result.opinions[0].abstention_reason)

    def test_actual_partial_entry_fill_is_starting_quantity(self):
        result = evaluate(
            [bar(0)],
            actual=trade(entry_status=PARTIALLY_FILLED, quantity="0.37"),
        )
        self.assertTrue(all(item.starting_quantity == Decimal("0.37") for item in result.paths))

    def test_mfe_and_mae_terminate_at_counterfactual_exit(self):
        rows = (
            bar(0, high="103", low="100", close="102"),
            bar(1, open_price="102", high="102.5", low="98.8", close="99"),
            bar(2, open_price="99", high="110", low="98.5", close="109"),
        )
        item = path(evaluate(rows, structural=structure("99")), STRUCTURAL_STOP)
        self.assertEqual(Decimal("1.5"), item.mfe_r)
        self.assertEqual(Decimal("-0.5"), item.mae_r)

    def test_post_exit_move_is_separate_observation(self):
        rows = (
            bar(0, high="100.5", low="98.8", close="99"),
            bar(1, open_price="99", high="110", low="99", close="109"),
        )
        result = evaluate(rows, structural=structure("99"))
        item = path(result, STRUCTURAL_STOP)
        observation = next(
            row for row in result.post_exit_observations if row.counterfactual_id == item.counterfactual_id
        )
        self.assertEqual(Decimal("5"), observation.max_favorable_after_exit_r)
        self.assertEqual(Decimal("0"), item.mfe_r)

    def test_forced_flat_uses_frozen_session_boundary(self):
        rows = tuple(bar(i, high="100.2", low="99.8", close="100.1") for i in range(3))
        result = evaluate(rows, actual=trade(forced_minutes=3))
        item = path(result, TIME_STOP)
        self.assertEqual(EXITED, item.terminal_state)
        self.assertIn("FORCED_FLAT", item.reason_codes)
        self.assertEqual(180, item.duration_seconds)

    def test_price_scale_is_equivalent_in_r(self):
        low_result = evaluate(
            [bar(0, open_price="10", high="10.1", low="9.89", close="9.9")],
            actual=trade(entry="10", stop="9.8", targets=("10.2", "10.4")),
            structural=structure("9.9"),
        )
        high_structure = build_structural_stop_evidence(
            structure_id="structure/high",
            opportunity_id=OPPORTUNITY,
            candidate_id="candidate/test-1",
            setup_id=SETUP,
            trade_plan_id=PLAN,
            symbol="TEST",
            level="990",
            known_at=BASE,
            effective_at=BASE,
            evidence=evidence("evidence/structure-high", BASE, evidence_type="TECHNICAL_STRUCTURE", seed=88),
        )
        high_result = evaluate(
            [bar(0, open_price="1000", high="1010", low="989", close="990")],
            actual=trade(entry="1000", stop="980", targets=("1020", "1040")),
            structural=high_structure,
        )
        self.assertEqual(
            path(low_result, STRUCTURAL_STOP).reference_r,
            path(high_result, STRUCTURAL_STOP).reference_r,
        )


class ExitResearchSafetyTests(unittest.TestCase):
    def test_policy_is_frozen_and_fingerprint_bound(self):
        policy = default_exit_research_policy()
        with self.assertRaises(FrozenInstanceError):
            policy.time_stop_minutes = 30  # type: ignore[misc]
        with self.assertRaisesRegex(ExitResearchError, "fingerprint"):
            validate_exit_research_policy(replace(policy, time_stop_minutes=30))

    def test_invalid_actual_fill_values_fail_closed(self):
        with self.assertRaises(ExitResearchError):
            trade(quantity="0")
        with self.assertRaises(ExitResearchError):
            trade(entry=math.inf)
        with self.assertRaises(ExitResearchError):
            trade(stop="100")

    def test_terminal_exit_quantity_must_equal_actual_fill(self):
        exits = (actual_fill("fill/short", 2, "0.5", "101", "EXIT"),)
        with self.assertRaisesRegex(ExitResearchError, "quantity-complete"):
            trade(terminal_state=TERMINAL, exits=exits)

    def test_wrong_symbol_bar_fails_closed(self):
        with self.assertRaisesRegex(ExitResearchError, "target identity"):
            evaluate([bar(0, symbol="OTHER")])

    def test_wrong_structure_identity_fails_closed(self):
        wrong = build_structural_stop_evidence(
            structure_id="structure/wrong",
            opportunity_id="a" * 64,
            candidate_id="candidate/test-1",
            setup_id=SETUP,
            trade_plan_id=PLAN,
            symbol="TEST",
            level="99",
            known_at=BASE,
            effective_at=BASE,
            evidence=evidence("evidence/wrong", BASE, evidence_type="TECHNICAL_STRUCTURE", seed=77),
        )
        with self.assertRaisesRegex(ExitResearchError, "target identity"):
            evaluate([bar(0)], structural=wrong)

    def test_wrong_sibling_target_fails_closed(self):
        wrong = specialist_opinion(
            "REGIME", "MARKET_STRESS", BASE + timedelta(minutes=1), candidate="candidate/other"
        )
        with self.assertRaises(Exception):
            evaluate([bar(0)], regime=(wrong,))

    def test_forming_and_future_bars_fail_closed(self):
        with self.assertRaisesRegex(ExitResearchError, "Forming"):
            bar(0, complete=False)
        future = bar(2)
        with self.assertRaisesRegex(ExitResearchError, "Future bar"):
            evaluate([future], evaluated_at=BASE + timedelta(minutes=1))

    def test_duplicate_conflicting_bar_fails_closed(self):
        first = bar(0)
        changed = replace(first, close=Decimal("100.6"))
        with self.assertRaises(ExitResearchError):
            evaluate([first, changed])

    def test_bar_gap_is_explicit_data_failure(self):
        result = evaluate([bar(0), bar(2)], evaluated_at=BASE + timedelta(minutes=3))
        self.assertEqual(DATA_FAILURE, result.evaluation_state)
        self.assertIn("BAR_SEQUENCE_GAP", result.reason_codes)

    def test_missing_atr_fails_trailing_only(self):
        result = evaluate([bar(0, atr=None)])
        self.assertEqual(DATA_FAILURE, path(result, TRAILING_STOP).evaluation_state)
        self.assertNotEqual(DATA_FAILURE, path(result, TIME_STOP).evaluation_state)

    def test_stale_specialist_opinion_does_not_trigger(self):
        old = specialist_opinion("REGIME", "MARKET_STRESS", BASE - timedelta(minutes=31))
        rows = (bar(0, high="100.2", low="99.8", close="100"),)
        item = path(evaluate(rows, regime=(old,)), REGIME_DETERIORATION)
        self.assertNotIn("REGIME_DETERIORATION_OPINION", item.reason_codes)
        self.assertEqual(ABSTAINED_STATE, item.evaluation_state)

    def test_confirmed_entry_requires_exact_fill_reference(self):
        actual = trade()
        without_fill = tuple(
            item for item in actual.evidence_refs if item.evidence_type != "BROKER_FILL"
        )
        with self.assertRaisesRegex(ExitResearchError, "broker-fill reference"):
            build_actual_trade_evidence(
                trade_id=actual.trade_id,
                opportunity_id=actual.opportunity_id,
                opportunity_fingerprint=actual.opportunity_fingerprint,
                candidate_id=actual.candidate_id,
                setup_id=actual.setup_id,
                trade_plan_id=actual.trade_plan_id,
                trade_plan_fingerprint=actual.trade_plan_fingerprint,
                sample_identity=actual.sample_identity,
                sample_policy_fingerprint=actual.sample_policy_fingerprint,
                provider_environment_id=actual.provider_environment_id,
                symbol=actual.symbol,
                entry_order_id=actual.entry_order_id,
                entry_status=actual.entry_status,
                actual_average_fill=actual.actual_average_fill,
                actual_filled_quantity=actual.actual_filled_quantity,
                actual_fill_at=actual.actual_fill_at,
                entry_fill_id=actual.entry_fill_id,
                original_protective_stop=actual.original_protective_stop,
                original_targets=actual.original_targets,
                forced_flat_at=actual.forced_flat_at,
                actual_terminal_state=actual.actual_terminal_state,
                evidence_refs=without_fill,
            )

    def test_confirmed_entry_requires_exact_order_reference(self):
        actual = trade()
        without_order = tuple(
            item
            for item in actual.evidence_refs
            if item.evidence_type != "BROKER_ORDER"
        )
        with self.assertRaisesRegex(ExitResearchError, "broker-order"):
            build_actual_trade_evidence(
                trade_id=actual.trade_id,
                opportunity_id=actual.opportunity_id,
                opportunity_fingerprint=actual.opportunity_fingerprint,
                candidate_id=actual.candidate_id,
                setup_id=actual.setup_id,
                trade_plan_id=actual.trade_plan_id,
                trade_plan_fingerprint=actual.trade_plan_fingerprint,
                sample_identity=actual.sample_identity,
                sample_policy_fingerprint=actual.sample_policy_fingerprint,
                provider_environment_id=actual.provider_environment_id,
                symbol=actual.symbol,
                entry_order_id=actual.entry_order_id,
                entry_status=actual.entry_status,
                actual_average_fill=actual.actual_average_fill,
                actual_filled_quantity=actual.actual_filled_quantity,
                actual_fill_at=actual.actual_fill_at,
                entry_fill_id=actual.entry_fill_id,
                original_protective_stop=actual.original_protective_stop,
                original_targets=actual.original_targets,
                forced_flat_at=actual.forced_flat_at,
                actual_terminal_state=actual.actual_terminal_state,
                evidence_refs=without_order,
            )

    def test_actual_control_tampering_is_rejected(self):
        control = evaluate([bar(0)]).control
        assert control is not None
        with self.assertRaisesRegex(ExitResearchError, "fingerprint"):
            validate_exit_research_control(replace(control, actual_filled_quantity=Decimal("2")))

    def test_counterfactual_entry_quantity_and_plan_are_identity_bound(self):
        item = path(evaluate([bar(0)]), TIME_STOP)
        for changed in (
            replace(item, entry_price=Decimal("101")),
            replace(item, starting_quantity=Decimal("2")),
            replace(item, trade_plan_id="a" * 64),
        ):
            with self.assertRaises(ExitResearchError):
                validate_counterfactual_path(changed)

    def test_actual_sample_provider_and_order_identity_bind_every_path(self):
        first = evaluate([bar(0)], actual=trade())
        assert first.control is not None
        variants = (
            {"sample_identity": "paper-engineering-v3"},
            {"sample_policy_fingerprint": "a" * 64},
            {"provider_environment_id": "alpaca-paper-canary-v2"},
            {"entry_order_id": "order/entry-2"},
        )
        for changed in variants:
            second = evaluate([bar(0)], actual=trade(**changed))
            assert second.control is not None
            self.assertNotEqual(first.control.fingerprint, second.control.fingerprint)
            self.assertNotEqual(
                tuple(item.counterfactual_id for item in first.paths),
                tuple(item.counterfactual_id for item in second.paths),
            )

    def test_partial_quantity_overrun_and_negative_remaining_are_rejected(self):
        item = path(
            evaluate(
                [
                    bar(0, high="102.2", low="99", close="102"),
                    bar(1, open_price="102", high="104.2", low="101", close="104"),
                ]
            ),
            PARTIAL_EXIT,
        )
        oversized = replace(item.exit_legs[0], quantity=Decimal("2"))
        with self.assertRaisesRegex(ExitResearchError, "exceeds"):
            validate_counterfactual_path(replace(item, exit_legs=(oversized,) + item.exit_legs[1:]))
        with self.assertRaisesRegex(ExitResearchError, "quantity"):
            validate_counterfactual_path(replace(item, remaining_quantity=Decimal("-1")))

    def test_counterfactual_cannot_claim_actual_execution(self):
        item = path(evaluate([bar(0)]), TIME_STOP)
        with self.assertRaisesRegex(ExitResearchError, "actual broker"):
            validate_counterfactual_path(
                replace(item, execution_evidence_status=ACTUAL_BROKER_EXECUTION)
            )

    def test_duplicate_conflicting_decision_event_is_rejected(self):
        item = path(evaluate([bar(0)]), TIME_STOP)
        duplicate = replace(item.events[0], event_type="EXIT_SIGNAL")
        with self.assertRaises(ExitResearchError):
            validate_counterfactual_path(replace(item, events=item.events + (duplicate,)))

    def test_structural_stop_cannot_act_before_known(self):
        with self.assertRaisesRegex(ExitResearchError, "before"):
            structure(
                "99",
                known_at=BASE + timedelta(minutes=2),
                effective_at=BASE + timedelta(minutes=1),
            )

    def test_source_inputs_remain_immutable(self):
        actual = trade()
        rows = (bar(0), bar(1))
        before = (actual.fingerprint, tuple(item.fingerprint for item in rows))
        evaluate(rows, actual=actual)
        after = (actual.fingerprint, tuple(item.fingerprint for item in rows))
        self.assertEqual(before, after)

    def test_deterministic_serialization_and_material_change_identity(self):
        rows = (bar(0), bar(1))
        first = evaluate(rows)
        second = evaluate(reversed(rows))
        self.assertEqual(evaluation_json_bytes(first), evaluation_json_bytes(second))
        changed = evaluate((bar(0, close="100.6"), bar(1)))
        self.assertNotEqual(first.evaluation_id, changed.evaluation_id)

    def test_future_sample_is_inactive_empty_and_no_backfill(self):
        sample = prospective_sample_definition()
        self.assertEqual(RESEARCH_IDENTITY, sample.sample_identity)
        self.assertFalse(sample.activated)
        self.assertEqual(0, sample.trades)
        self.assertFalse(sample.historical_backfill_allowed)
        self.assertFalse(sample.parameter_optimization_allowed)
        self.assertEqual(
            (
                ACTUAL_FROZEN_CONTROL,
                STRUCTURAL_STOP,
                TRAILING_STOP,
                TIME_STOP,
                BREAK_EVEN,
                PARTIAL_EXIT,
                MOMENTUM_FAILURE,
                REGIME_DETERIORATION,
            ),
            sample.comparison_methods,
        )
        self.assertIn("frozen actual Momentum baseline", sample.research_question)

    def test_opinions_are_research_only_without_fake_confidence(self):
        result = evaluate([bar(0)])
        for opinion in result.opinions:
            self.assertEqual(RESEARCH_ONLY, opinion.authority)
            self.assertEqual(EXECUTION_AUTHORITY_NONE, opinion.execution_authority)
            self.assertFalse(opinion.confidence.available)

    def test_module_has_no_runtime_or_capability_imports(self):
        source = Path("momentum_hunter/exit_research.py").read_text(encoding="utf-8")
        forbidden = (
            "alpaca_paper",
            "fakebroker",
            "shadow_trading",
            "requests",
            "urllib",
            "socket",
            "subprocess",
            "pathlib",
            "sqlite3",
            "open(",
            "finalAuthorizedQuantity",
            "momentum_hunter.regime",
            "momentum_hunter.technical",
            "momentum_hunter.event",
            "momentum_hunter.execution_quality",
        )
        lowered = source.lower()
        for token in forbidden:
            self.assertNotIn(token.lower(), lowered, token)


if __name__ == "__main__":
    unittest.main()
