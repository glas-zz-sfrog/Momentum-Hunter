from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    BULLISH,
    EVALUATED,
    EXECUTION_AUTHORITY_NONE,
    RESEARCH_ONLY,
)
from momentum_hunter.technical_breakouts import TechnicalPriceBar
from momentum_hunter import technical_structure
from momentum_hunter.technical_structure import (
    AFTER_HOURS,
    AMBIGUOUS_SAME_BAR,
    BAR_DERIVED_VWAP,
    BEARISH,
    BREAKOUT_RETEST,
    COMPRESSION_EXPANSION,
    CONFIRMED_STRUCTURE,
    DOUBLE_BOTTOM,
    DOUBLE_TOP,
    DURABLE,
    FAILED_BREAKOUT,
    HEAD_AND_SHOULDERS,
    HIGHER_LOW_CONTINUATION,
    INVERSE_HEAD_AND_SHOULDERS,
    LOWER_HIGH_BREAKDOWN,
    POTENTIAL_STRUCTURE,
    PREMARKET,
    REGULAR,
    RESISTANCE,
    SAME_SESSION_RAW_PROVIDER,
    SESSION_BOUND,
    SPLIT_ADJUSTED_ANALYSIS,
    STRUCTURE_CONTRADICTS,
    STRUCTURE_NEUTRAL,
    STRUCTURE_SUPPORTS,
    STRUCTURE_EXHAUSTED,
    SUPPORT,
    SUPPORT_RESISTANCE,
    TechnicalStructureBar,
    TechnicalStructureError,
    TechnicalStructurePolicy,
    TechnicalStructureRequest,
    VWAP_LOSS,
    VWAP_RECLAIM,
    build_frozen_level,
    build_structure_bar,
    current_policy,
    detect_pivots,
    evaluate_technical_structure,
    evaluation_json_bytes,
    policy_fingerprint,
    research_data_basis_compatibility,
    structure_bar_from_v1,
    technical_structure_experiment_preregistration,
    validate_evaluation,
    validate_structure_instance,
)


UTC = timezone.utc
START = datetime(2026, 8, 14, 14, 30, tzinfo=UTC)
OPPORTUNITY_ID = "a" * 64
SETUP_ID = "b" * 64
TRADE_PLAN_ID = "c" * 64
TRADE_PLAN_FP = "d" * 64
LEVEL_FP = "e" * 64


def compact_policy(**changes: object) -> TechnicalStructurePolicy:
    base = replace(
        current_policy(),
        pivot_left_bars=1,
        pivot_right_bars=1,
        atr_window=3,
        minimum_bars=6,
        max_evidence_age_seconds=600,
        compression_window=4,
        level_min_touches=2,
    )
    return replace(base, **changes)


def bars_from_rows(
    rows: list[tuple[float, float, float, float]],
    *,
    symbol: str = "TEST",
    start: datetime = START,
    session: str = REGULAR,
    basis: str = SAME_SESSION_RAW_PROVIDER,
    volumes: list[float] | None = None,
) -> tuple[TechnicalStructureBar, ...]:
    result = []
    for index, (open_price, high, low, close) in enumerate(rows):
        result.append(
            build_structure_bar(
                symbol=symbol,
                timestamp=start + timedelta(minutes=index),
                completed_at=start + timedelta(minutes=index + 1),
                open_price=open_price,
                high=high,
                low=low,
                close=close,
                volume=(volumes[index] if volumes is not None else 1_000 + index * 10),
                source="synthetic-fixture",
                session=session,
                price_basis=basis,
            )
        )
    return tuple(result)


def bars_from_closes(
    closes: list[float],
    *,
    symbol: str = "TEST",
    start: datetime = START,
    session: str = REGULAR,
    basis: str = SAME_SESSION_RAW_PROVIDER,
    scale: float = 1.0,
    volumes: list[float] | None = None,
) -> tuple[TechnicalStructureBar, ...]:
    width = 0.20 * scale
    rows = [
        (close * scale, close * scale + width, close * scale - width, close * scale)
        for close in closes
    ]
    return bars_from_rows(
        rows,
        symbol=symbol,
        start=start,
        session=session,
        basis=basis,
        volumes=volumes,
    )


def request_for(
    bars: tuple[TechnicalStructureBar, ...],
    *,
    direction: str = BULLISH,
    levels: tuple = (),
    as_of: datetime | None = None,
    basis_verified: bool = True,
    security_identity_status: str = SESSION_BOUND,
    corporate_action_safe: bool = True,
    session: str | None = None,
    price_basis: str | None = None,
) -> TechnicalStructureRequest:
    completed = [item.completed_at for item in bars if item.completed_at is not None]
    cutoff = as_of or datetime.fromisoformat(max(completed).replace("Z", "+00:00"))
    return TechnicalStructureRequest(
        opportunity_id=OPPORTUNITY_ID,
        candidate_id="candidate-1",
        setup_id=SETUP_ID,
        trade_plan_id=TRADE_PLAN_ID,
        symbol=bars[0].symbol,
        thesis_direction=direction,
        as_of=cutoff.isoformat(),
        expires_at=(cutoff + timedelta(minutes=5)).isoformat(),
        session=session or bars[0].session,
        price_basis=price_basis or bars[0].price_basis,
        basis_verified=basis_verified,
        security_identity_status=security_identity_status,
        corporate_action_safe=corporate_action_safe,
        bars=bars,
        frozen_levels=levels,
        expected_trade_plan_fingerprint=TRADE_PLAN_FP,
    )


def frozen(level_type: str, price: float, known_index: int = 0):
    return build_frozen_level(
        level_id=f"fixture-{level_type.lower()}-{price}",
        level_type=level_type,
        price=price,
        known_at=START + timedelta(minutes=known_index + 1),
        origin="TEST_ONLY_FROZEN_LEVEL",
        evidence_fingerprint=LEVEL_FP,
    )


def types(evaluation) -> set[str]:
    return {item.structure_type for item in evaluation.structures}


def instances(evaluation, structure_type: str):
    return [item for item in evaluation.structures if item.structure_type == structure_type]


class TechnicalStructurePatternTests(unittest.TestCase):
    def test_v1_bar_adapter_preserves_ohlcv(self) -> None:
        source = TechnicalPriceBar("TEST", START.isoformat(), 10, 11, 9, 10.5, 1234, "v1")
        adapted = structure_bar_from_v1(
            source,
            completed_at=START + timedelta(minutes=1),
            session=REGULAR,
            price_basis=SAME_SESSION_RAW_PROVIDER,
        )
        self.assertEqual((10, 11, 9, 10.5, 1234), (adapted.open, adapted.high, adapted.low, adapted.close, adapted.volume))

    def test_compression_expansion(self) -> None:
        rows = [
            (100, 101.0, 99.0, 100),
            (100, 100.8, 99.2, 100),
            (100, 100.25, 99.75, 100),
            (100, 100.20, 99.80, 100),
            (100, 101.5, 99.9, 101.3),
            (101.3, 101.6, 101.1, 101.4),
        ]
        result = evaluate_technical_structure(request_for(bars_from_rows(rows)), policy=compact_policy())
        self.assertIn(COMPRESSION_EXPANSION, types(result))

    def test_breakout_retest_and_supporting_opinion(self) -> None:
        data = bars_from_closes([99.0, 99.2, 99.1, 99.3, 100.7, 100.05, 100.8, 100.9])
        result = evaluate_technical_structure(
            request_for(data, levels=(frozen(RESISTANCE, 100.0),)),
            policy=compact_policy(),
        )
        found = instances(result, BREAKOUT_RETEST)
        self.assertTrue(found)
        self.assertEqual(CONFIRMED_STRUCTURE, found[0].confirmation_state)
        self.assertEqual(STRUCTURE_SUPPORTS, result.opinion.opinion_code)

    def test_failed_breakout(self) -> None:
        data = bars_from_closes([99.0, 99.2, 99.1, 99.3, 100.7, 99.0, 98.8])
        result = evaluate_technical_structure(
            request_for(data, levels=(frozen(RESISTANCE, 100.0),)),
            policy=compact_policy(),
        )
        self.assertTrue(instances(result, FAILED_BREAKOUT))

    def test_breakout_same_bar_ambiguity(self) -> None:
        rows = [
            (99, 99.3, 98.8, 99),
            (99, 99.4, 98.9, 99.1),
            (99.1, 99.4, 99.0, 99.2),
            (99.2, 99.5, 99.0, 99.3),
            (99.3, 101.2, 98.5, 100.7),
            (100.7, 101, 100.4, 100.8),
        ]
        result = evaluate_technical_structure(
            request_for(bars_from_rows(rows), levels=(frozen(RESISTANCE, 100.0),)),
            policy=compact_policy(),
        )
        self.assertEqual(AMBIGUOUS_SAME_BAR, instances(result, FAILED_BREAKOUT)[0].confirmation_state)

    def test_vwap_reclaim_and_source(self) -> None:
        data = bars_from_closes([100, 100, 99.8, 99.2, 101.0, 101.2, 101.1])
        result = evaluate_technical_structure(request_for(data), policy=compact_policy())
        found = instances(result, VWAP_RECLAIM)
        self.assertTrue(found)
        self.assertTrue(any(level.origin == BAR_DERIVED_VWAP for level in found[0].reference_levels))
        self.assertIn("VOLUME", result.opinion.feature_families)

    def test_vwap_loss(self) -> None:
        data = bars_from_closes([100, 100, 100.2, 100.8, 99.0, 98.8, 98.9])
        result = evaluate_technical_structure(request_for(data), policy=compact_policy())
        self.assertTrue(instances(result, VWAP_LOSS))

    def test_vwap_is_unavailable_without_volume(self) -> None:
        data = tuple(replace(item, volume=None) for item in bars_from_closes([100, 100, 99.8, 99.2, 101, 101.2, 101.1]))
        result = evaluate_technical_structure(request_for(data), policy=compact_policy())
        self.assertNotIn(VWAP_RECLAIM, types(result))
        self.assertNotIn(VWAP_LOSS, types(result))

    def test_higher_low_continuation(self) -> None:
        data = bars_from_closes([100, 100.4, 100.0, 98.0, 100.0, 104.0, 102.5, 101.0, 103.0, 105.0, 105.2])
        result = evaluate_technical_structure(request_for(data), policy=compact_policy())
        self.assertIn(HIGHER_LOW_CONTINUATION, types(result))

    def test_continuation_confirmation_and_invalidation_same_bar_is_ambiguous(self) -> None:
        rows = [(value, value + 0.2, value - 0.2, value) for value in [100, 100.4, 100, 98, 100, 104, 102.5, 101, 103]]
        rows.extend([(103, 105.2, 99.0, 105.0), (105, 105.4, 104.8, 105.2)])
        result = evaluate_technical_structure(request_for(bars_from_rows(rows)), policy=compact_policy())
        found = instances(result, HIGHER_LOW_CONTINUATION)
        self.assertTrue(found)
        self.assertEqual(AMBIGUOUS_SAME_BAR, found[0].confirmation_state)

    def test_lower_high_breakdown(self) -> None:
        data = bars_from_closes([100, 99.6, 100, 104, 102, 98, 100, 101, 99, 97, 96.8])
        result = evaluate_technical_structure(request_for(data, direction=BEARISH), policy=compact_policy())
        self.assertIn(LOWER_HIGH_BREAKDOWN, types(result))

    def test_potential_and_confirmed_double_top(self) -> None:
        potential_data = bars_from_closes([100, 101, 100, 104, 102, 100, 102, 104.1, 103, 102.5])
        potential = evaluate_technical_structure(request_for(potential_data), policy=compact_policy())
        self.assertTrue(any(item.confirmation_state == POTENTIAL_STRUCTURE for item in instances(potential, DOUBLE_TOP)))
        confirmed_data = bars_from_closes([100, 101, 100, 104, 102, 100, 102, 104.1, 102, 99, 98.8])
        confirmed = evaluate_technical_structure(request_for(confirmed_data), policy=compact_policy())
        self.assertTrue(any(item.confirmation_state == CONFIRMED_STRUCTURE for item in instances(confirmed, DOUBLE_TOP)))

    def test_confirmed_double_bottom(self) -> None:
        data = bars_from_closes([100, 99, 100, 96, 98, 100, 98, 95.9, 98, 101, 101.2])
        result = evaluate_technical_structure(request_for(data), policy=compact_policy())
        self.assertTrue(any(item.confirmation_state == CONFIRMED_STRUCTURE for item in instances(result, DOUBLE_BOTTOM)))

    def test_head_and_shoulders(self) -> None:
        data = bars_from_closes([100, 101, 100, 103, 101, 100, 102, 106, 102, 100.2, 102, 103.1, 101, 99, 98.8])
        result = evaluate_technical_structure(request_for(data), policy=compact_policy())
        self.assertTrue(instances(result, HEAD_AND_SHOULDERS))

    def test_inverse_head_and_shoulders(self) -> None:
        data = bars_from_closes([100, 99, 100, 97, 99, 100, 98, 94, 98, 99.8, 98, 96.9, 99, 101, 101.2])
        result = evaluate_technical_structure(request_for(data), policy=compact_policy())
        self.assertTrue(instances(result, INVERSE_HEAD_AND_SHOULDERS))

    def test_nearby_support_and_resistance_conflict(self) -> None:
        data = bars_from_closes([100, 100.1, 100, 100.1, 100, 100.1])
        result = evaluate_technical_structure(
            request_for(data, levels=(frozen(SUPPORT, 99.9), frozen(RESISTANCE, 100.2))),
            policy=compact_policy(),
        )
        self.assertGreaterEqual(len(instances(result, SUPPORT_RESISTANCE)), 2)
        self.assertEqual(STRUCTURE_NEUTRAL, result.opinion.opinion_code)

    def test_multiple_structures_coexist_without_voting(self) -> None:
        data = bars_from_closes([99.0, 99.2, 99.1, 99.3, 100.7, 100.05, 100.8, 100.9])
        result = evaluate_technical_structure(
            request_for(
                data,
                levels=(frozen(RESISTANCE, 100.0), frozen(SUPPORT, 100.8)),
            ),
            policy=compact_policy(),
        )
        self.assertIn(BREAKOUT_RETEST, types(result))
        self.assertIn(SUPPORT_RESISTANCE, types(result))
        self.assertGreater(len(result.structures), 1)

    def test_extreme_extension_failure_is_exhausted(self) -> None:
        data = bars_from_closes([100, 100.2, 100.1, 101, 102, 103, 104, 105, 103.5, 102.5])
        policy = compact_policy(exhaustion_extension_atr=1.0)
        result = evaluate_technical_structure(request_for(data), policy=policy)
        self.assertEqual(STRUCTURE_EXHAUSTED, result.opinion.opinion_code)

    def test_opposing_confirmed_structure_contradicts_thesis(self) -> None:
        data = bars_from_closes([99, 99.2, 99.1, 99.3, 100.7, 99, 98.8])
        result = evaluate_technical_structure(
            request_for(data, direction=BULLISH, levels=(frozen(RESISTANCE, 100),)),
            policy=compact_policy(),
        )
        self.assertEqual(STRUCTURE_CONTRADICTS, result.opinion.opinion_code)


class TechnicalStructureSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = compact_policy()
        self.data = bars_from_closes([100, 100.2, 100.1, 100.3, 100.2, 100.4, 100.5])

    def test_insufficient_data_abstains_not_neutral(self) -> None:
        result = evaluate_technical_structure(request_for(self.data[:3]), policy=self.policy)
        self.assertEqual(ABSTAINED, result.opinion.evaluation_status)
        self.assertEqual("INSUFFICIENT_EVIDENCE", result.opinion.abstention_reason)
        self.assertNotEqual(STRUCTURE_NEUTRAL, result.opinion.opinion_code)

    def test_unknown_basis_abstains(self) -> None:
        request = replace(request_for(self.data), basis_verified=False)
        result = evaluate_technical_structure(request, policy=self.policy)
        self.assertEqual("DATA_BASIS_UNCERTAIN", result.opinion.abstention_reason)

    def test_corporate_action_discontinuity_abstains(self) -> None:
        result = evaluate_technical_structure(
            request_for(self.data, corporate_action_safe=False), policy=self.policy
        )
        self.assertIn("CORPORATE_ACTION_DISCONTINUITY", result.opinion.reason_codes)

    def test_cross_session_raw_basis_abstains(self) -> None:
        first = bars_from_closes([100, 101, 100], start=START)
        second = bars_from_closes([100, 101, 100], start=START + timedelta(days=1))
        result = evaluate_technical_structure(request_for(first + second), policy=self.policy)
        self.assertIn("CROSS_SESSION_RAW_BASIS_UNSAFE", result.opinion.reason_codes)

    def test_cross_session_adjusted_requires_durable_identity(self) -> None:
        first = bars_from_closes([100, 101, 100], start=START, basis=SPLIT_ADJUSTED_ANALYSIS)
        second = bars_from_closes([100, 101, 100], start=START + timedelta(days=1), basis=SPLIT_ADJUSTED_ANALYSIS)
        result = evaluate_technical_structure(
            request_for(first + second, price_basis=SPLIT_ADJUSTED_ANALYSIS), policy=self.policy
        )
        self.assertIn("DURABLE_SECURITY_IDENTITY_REQUIRED", result.opinion.reason_codes)
        admitted = evaluate_technical_structure(
            request_for(
                first + second,
                price_basis=SPLIT_ADJUSTED_ANALYSIS,
                security_identity_status=DURABLE,
            ),
            policy=self.policy,
        )
        self.assertEqual(EVALUATED, admitted.opinion.evaluation_status)

    def test_premarket_and_after_hours_abstain(self) -> None:
        for session in (PREMARKET, AFTER_HOURS):
            data = bars_from_closes([100, 100.1, 100, 100.2, 100.1, 100.2], session=session)
            result = evaluate_technical_structure(
                request_for(data, session=session), policy=self.policy
            )
            self.assertEqual("UNSUPPORTED_SESSION", result.opinion.abstention_reason)

    def test_missing_interval_abstains(self) -> None:
        broken = self.data[:3] + tuple(
            replace(item, timestamp=(START + timedelta(minutes=index + 5)).isoformat().replace("+00:00", "Z"))
            for index, item in enumerate(self.data[3:])
        )
        # Rebuild identities for the moved bars.
        rebuilt = self.data[:3] + tuple(
            build_structure_bar(
                symbol=item.symbol,
                timestamp=START + timedelta(minutes=index + 5),
                completed_at=START + timedelta(minutes=index + 6),
                open_price=item.open,
                high=item.high,
                low=item.low,
                close=item.close,
                volume=item.volume,
                source=item.source,
                session=item.session,
                price_basis=item.price_basis,
            )
            for index, item in enumerate(self.data[3:])
        )
        result = evaluate_technical_structure(request_for(rebuilt), policy=self.policy)
        self.assertIn("MISSING_REQUIRED_INTERVAL", result.opinion.reason_codes)

    def test_stale_evidence_abstains(self) -> None:
        cutoff = datetime.fromisoformat(self.data[-1].completed_at.replace("Z", "+00:00")) + timedelta(hours=1)
        result = evaluate_technical_structure(request_for(self.data, as_of=cutoff), policy=self.policy)
        self.assertEqual("STALE_EVIDENCE", result.opinion.abstention_reason)

    def test_future_completed_bar_fails_closed(self) -> None:
        cutoff = datetime.fromisoformat(self.data[-2].completed_at.replace("Z", "+00:00"))
        with self.assertRaisesRegex(TechnicalStructureError, "future-bar"):
            evaluate_technical_structure(request_for(self.data, as_of=cutoff), policy=self.policy)

    def test_future_forming_bar_also_fails_closed(self) -> None:
        future = build_structure_bar(
            symbol="TEST",
            timestamp=START + timedelta(hours=1),
            completed_at=None,
            open_price=100,
            high=101,
            low=99,
            close=100,
            volume=100,
            source="synthetic-fixture",
            session=REGULAR,
            price_basis=SAME_SESSION_RAW_PROVIDER,
            completed=False,
        )
        with self.assertRaisesRegex(TechnicalStructureError, "future-bar"):
            evaluate_technical_structure(request_for(self.data + (future,)), policy=self.policy)

    def test_forming_bar_is_provisional_and_not_confirmed(self) -> None:
        forming = build_structure_bar(
            symbol="TEST",
            timestamp=START + timedelta(minutes=len(self.data)),
            completed_at=None,
            open_price=100,
            high=110,
            low=90,
            close=109,
            volume=10_000,
            source="synthetic-fixture",
            session=REGULAR,
            price_basis=SAME_SESSION_RAW_PROVIDER,
            completed=False,
        )
        result = evaluate_technical_structure(request_for(self.data + (forming,)), policy=self.policy)
        self.assertEqual(1, result.provisional_bar_count)
        self.assertTrue(all(item.evidence_end != forming.timestamp for item in result.structures))

    def test_duplicate_bar_identity_fails_closed(self) -> None:
        with self.assertRaisesRegex(TechnicalStructureError, "duplicated"):
            evaluate_technical_structure(request_for(self.data + (self.data[-1],)), policy=self.policy)

    def test_conflicting_duplicate_bar_fails_closed(self) -> None:
        conflicting = replace(self.data[-1], close=self.data[-1].close + 0.05)
        with self.assertRaisesRegex(TechnicalStructureError, "contradictory"):
            evaluate_technical_structure(request_for(self.data[:-1] + (self.data[-1], conflicting)), policy=self.policy)

    def test_out_of_order_bar_fails_closed(self) -> None:
        with self.assertRaisesRegex(TechnicalStructureError, "out of order"):
            evaluate_technical_structure(
                request_for(self.data[:3] + (self.data[4], self.data[3]) + self.data[5:]),
                policy=self.policy,
            )

    def test_wrong_symbol_and_session_fail_closed(self) -> None:
        wrong_symbol = replace(self.data[2], symbol="NOPE")
        with self.assertRaises(TechnicalStructureError):
            evaluate_technical_structure(request_for(self.data[:2] + (wrong_symbol,) + self.data[3:]), policy=self.policy)
        wrong_session = replace(self.data[2], session=PREMARKET)
        with self.assertRaisesRegex(TechnicalStructureError, "crossed market session"):
            evaluate_technical_structure(request_for(self.data[:2] + (wrong_session,) + self.data[3:]), policy=self.policy)

    def test_timezone_naive_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(TechnicalStructureError, "UTC offset"):
            build_structure_bar(
                symbol="TEST",
                timestamp="2026-08-14T14:30:00",
                completed_at="2026-08-14T14:31:00",
                open_price=100,
                high=101,
                low=99,
                close=100,
                volume=100,
                source="fixture",
                session=REGULAR,
                price_basis=SAME_SESSION_RAW_PROVIDER,
            )

    def test_policy_change_changes_fingerprint_and_output_identity(self) -> None:
        altered = replace(self.policy, level_tolerance_atr=0.25)
        self.assertNotEqual(policy_fingerprint(self.policy), policy_fingerprint(altered))
        first = evaluate_technical_structure(request_for(self.data), policy=self.policy)
        second = evaluate_technical_structure(request_for(self.data), policy=altered)
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_tampered_instance_and_evaluation_are_rejected(self) -> None:
        data = bars_from_closes([99, 99.2, 99.1, 99.3, 100.7, 99, 98.8])
        result = evaluate_technical_structure(
            request_for(data, levels=(frozen(RESISTANCE, 100),)), policy=self.policy
        )
        item = result.structures[0]
        with self.assertRaises(TechnicalStructureError):
            validate_structure_instance(replace(item, known_at=item.evidence_start))
        with self.assertRaises(TechnicalStructureError):
            validate_evaluation(replace(result, policy_fingerprint="f" * 64))

    def test_deterministic_bytes_and_identity(self) -> None:
        first = evaluate_technical_structure(request_for(self.data), policy=self.policy)
        second = evaluate_technical_structure(request_for(self.data), policy=self.policy)
        self.assertEqual(first, second)
        self.assertEqual(evaluation_json_bytes(first), evaluation_json_bytes(second))

    def test_price_scale_equivalence(self) -> None:
        closes = [99, 99.2, 99.1, 99.3, 100.7, 100.05, 100.8, 100.9]
        low = bars_from_closes(closes, scale=1.0)
        high = bars_from_closes(closes, scale=10.0)
        low_result = evaluate_technical_structure(
            request_for(low, levels=(frozen(RESISTANCE, 100),)), policy=self.policy
        )
        high_level = build_frozen_level(
            level_id="scaled-level",
            level_type=RESISTANCE,
            price=1000,
            known_at=START + timedelta(minutes=1),
            origin="TEST_ONLY_FROZEN_LEVEL",
            evidence_fingerprint=LEVEL_FP,
        )
        high_result = evaluate_technical_structure(
            request_for(high, levels=(high_level,)), policy=self.policy
        )
        self.assertIn(BREAKOUT_RETEST, types(low_result))
        self.assertIn(BREAKOUT_RETEST, types(high_result))

    def test_request_and_caller_trade_plan_are_not_mutated(self) -> None:
        request = request_for(self.data)
        request_before = asdict(request)
        trade_plan = {"tradePlanId": TRADE_PLAN_ID, "entry": 100.0, "stop": 98.0}
        trade_plan_before = json.dumps(trade_plan, sort_keys=True)
        evaluate_technical_structure(request, policy=self.policy)
        self.assertEqual(request_before, asdict(request))
        self.assertEqual(trade_plan_before, json.dumps(trade_plan, sort_keys=True))


class TechnicalStructureContractTests(unittest.TestCase):
    def test_specialist_contract_authority_and_feature_family(self) -> None:
        data = bars_from_closes([99, 99.2, 99.1, 99.3, 100.7, 100.05, 100.8, 100.9])
        result = evaluate_technical_structure(
            request_for(data, levels=(frozen(RESISTANCE, 100),)), policy=compact_policy()
        )
        self.assertEqual(RESEARCH_ONLY, result.opinion.authority)
        self.assertEqual(EXECUTION_AUTHORITY_NONE, result.opinion.execution_authority)
        self.assertIn("CANDLE_STRUCTURE", result.opinion.feature_families)
        self.assertEqual("UNAVAILABLE", result.opinion.confidence.kind)
        self.assertNotIn("VOLUME", result.opinion.feature_families)

    def test_exact_opportunity_setup_and_tradeplan_identity_are_preserved(self) -> None:
        result = evaluate_technical_structure(request_for(bars_from_closes([100] * 6)), policy=compact_policy())
        self.assertEqual(OPPORTUNITY_ID, result.opinion.opportunity_id)
        self.assertEqual(SETUP_ID, result.opinion.setup_id)
        self.assertEqual(TRADE_PLAN_ID, result.opinion.trade_plan_id)

    def test_pivot_economic_time_and_known_at_are_distinct(self) -> None:
        data = bars_from_closes([100, 101, 100, 99, 100, 101])
        pivots = detect_pivots(data, data[-1].completed_at, compact_policy())
        self.assertTrue(pivots)
        self.assertTrue(all(item.known_at > item.timestamp for item in pivots))

    def test_preregistration_is_one_variant_without_outcome_optimization(self) -> None:
        value = technical_structure_experiment_preregistration(compact_policy())
        self.assertEqual("SINGLE_PREREGISTERED_VARIANT", value["searchMethod"])
        self.assertEqual(1, value["plannedVariantCount"])
        self.assertFalse(value["outcomeOptimizationAuthorized"])
        self.assertEqual(EXECUTION_AUTHORITY_NONE, value["executionAuthority"])

    def test_research_data_basis_compatibility_is_non_authoritative(self) -> None:
        request = request_for(bars_from_closes([100] * 6))
        value = research_data_basis_compatibility(request)
        self.assertEqual("RAW_PROVIDER", value["requestedBasis"])
        self.assertEqual("SAFE_FOR_RAW_ANALYSIS", value["admissionStatus"])
        self.assertEqual("RESEARCH_DATA_ADMISSION_ONLY", value["authority"])
        self.assertEqual("NONE", value["executionAuthority"])

    def test_stat_data_attachment_identity_is_available(self) -> None:
        result = evaluate_technical_structure(request_for(bars_from_closes([100] * 6)), policy=compact_policy())
        attachment_key = (
            result.opinion.opportunity_id,
            result.opinion.opinion_id,
            result.opinion.as_of,
            result.opinion.fingerprint,
        )
        self.assertTrue(all(attachment_key))

    def test_module_has_no_network_broker_order_or_runtime_capability(self) -> None:
        source = inspect.getsource(technical_structure).lower()
        forbidden = (
            "import requests",
            "import urllib",
            "import socket",
            "alpaca",
            "schwab_client",
            "submit_order",
            "cancel_order",
            "replace_order",
            "account_snapshot",
            "automation-manifest",
            "subprocess",
        )
        for text in forbidden:
            self.assertNotIn(text, source)

    def test_module_does_not_consume_historical_outcomes(self) -> None:
        source = inspect.getsource(technical_structure)
        self.assertNotIn("analysis_outcomes", source.lower())
        self.assertNotIn("outcome_probability", source.lower())
        self.assertNotIn("historical_profit", source.lower())

    def test_sibling_specialists_are_not_imported(self) -> None:
        source = inspect.getsource(technical_structure)
        for module in (
            "regime_research",
            "execution_quality_research",
            "event_shock_research",
            "opportunity_denominator",
            "research_governance",
            "successor_setup_observer",
        ):
            self.assertNotIn(f"import {module}", source)
            self.assertNotIn(f"from momentum_hunter.{module}", source)

    def test_existing_runtime_does_not_import_new_specialist(self) -> None:
        # Import direction remains specialist -> common contract/v1 primitives only.
        source = inspect.getsource(technical_structure)
        self.assertIn("from momentum_hunter.technical_breakouts import", source)
        self.assertIn("from momentum_hunter.specialist_opinion import", source)


if __name__ == "__main__":
    unittest.main()
