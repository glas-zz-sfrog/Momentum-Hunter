from __future__ import annotations

import ast
import copy
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.macro_event_context import (
    BLOCK_NEW_ENTRY,
    CURRENT,
    FED_DECISION,
    HIGH,
    MARKET,
    EventConsequenceRule,
    EventDefinition,
    EventRiskPolicy,
    build_event_calendar,
    evaluate_event_risk,
)
from momentum_hunter.regime_exhaustion_specialist import (
    AFTER_HOURS,
    BAR_DERIVED_VWAP,
    BOUNDED_CANDIDATE_UNIVERSE_PROXY,
    CHOP,
    DATA_UNSAFE,
    EXHAUSTION_RISK,
    EXTREME_EXTENSION,
    FULL_MARKET_EVIDENCE,
    LATE_SESSION,
    LATE_TREND,
    MARKET_STRESS,
    MIDDAY,
    MIXED,
    NORMAL,
    NORMAL_EXTENSION,
    OPENING,
    PARTIAL,
    PREMARKET,
    RESEARCH_HEURISTIC,
    REGIME_SPECIALIST_VERSION,
    ROTATION,
    TREND_DOWN,
    TREND_UP,
    TRUE_04_TO_07_PATH_UNOBSERVED,
    VOLATILITY_SHOCK,
    ParticipationProxy,
    RegimeResearchError,
    default_regime_research_policy,
    evaluate_regime_specialist,
    market_observation_id,
    packet_json_bytes,
    validate_assessment,
    validate_packet,
)
from momentum_hunter.rolling_market_regime import RegimeBar
from momentum_hunter.specialist_opinion import (
    ABSTAINED,
    BEARISH,
    BULLISH,
    EVALUATED,
    EXECUTION_AUTHORITY_NONE,
    FAILED,
    HEURISTIC,
    NO_DIRECTION,
    NO_OPINION,
    RESEARCH_ONLY,
    UNCALIBRATED,
)


EVALUATED_AT = datetime(2026, 8, 17, 13, 35, 30, tzinfo=timezone.utc)
FIRST_BAR = datetime(2026, 8, 17, 12, 30, tzinfo=timezone.utc)
CORE = ("SPY", "QQQ", "IWM")


class RegimeSpecialistFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = default_regime_research_policy()

    def evaluate(self, values=None, **kwargs):
        return evaluate_regime_specialist(
            bars_by_symbol=values or market(step=0.015),
            evaluated_at=kwargs.pop("evaluated_at", EVALUATED_AT),
            policy=kwargs.pop("policy", self.policy),
            **kwargs,
        )

    def test_normal_trend_up_is_multidimensional_research_only(self) -> None:
        packet = self.evaluate()

        self.assertEqual(TREND_UP, packet.assessment.direction_state)
        self.assertEqual(NORMAL_EXTENSION, packet.assessment.extension_state)
        self.assertEqual(NORMAL, packet.assessment.stress_state)
        self.assertEqual(EVALUATED, packet.opinion.evaluation_status)
        self.assertEqual(BULLISH, packet.opinion.directional_bias)
        self.assertEqual(RESEARCH_ONLY, packet.opinion.authority)
        self.assertEqual(EXECUTION_AUTHORITY_NONE, packet.opinion.execution_authority)
        self.assertEqual(FULL_MARKET_EVIDENCE, packet.assessment.evidence_scope)
        self.assertFalse(packet.assessment.trade_recommendation)
        self.assertTrue(packet.assessment.rolling_snapshot_id)

    def test_normal_trend_down(self) -> None:
        packet = self.evaluate(market(step=-0.015))

        self.assertEqual(TREND_DOWN, packet.assessment.direction_state)
        self.assertEqual(BEARISH, packet.opinion.directional_bias)
        self.assertEqual(NORMAL_EXTENSION, packet.assessment.extension_state)

    def test_frozen_policy_has_explicit_session_threshold_profiles(self) -> None:
        self.assertEqual(
            (
                (PREMARKET, 1.25),
                (OPENING, 1.00),
                (MIDDAY, 0.75),
                (LATE_SESSION, 1.00),
            ),
            self.policy.session_threshold_multipliers,
        )

    def test_same_marginal_move_is_session_dependent(self) -> None:
        opening = self.evaluate(market(step=0.011))
        midday_time = datetime(2026, 8, 17, 16, 0, 30, tzinfo=timezone.utc)
        midday_bars = {
            symbol: bars(
                symbol,
                step=0.011,
                first=datetime(2026, 8, 17, 13, 30, tzinfo=timezone.utc),
                count=150,
            )
            for symbol in CORE
        }
        midday = self.evaluate(midday_bars, evaluated_at=midday_time)

        self.assertEqual(OPENING, opening.assessment.session_state)
        self.assertEqual(MIDDAY, midday.assessment.session_state)
        self.assertNotEqual(TREND_UP, opening.assessment.direction_state)
        self.assertEqual(TREND_UP, midday.assessment.direction_state)
        self.assertIn(
            "SESSION_THRESHOLD_PROFILE_MIDDAY",
            midday.assessment.reason_codes,
        )

    def test_rotation_requires_cross_index_divergence(self) -> None:
        packet = self.evaluate(
            {
                "SPY": bars("SPY", step=0.03),
                "QQQ": bars("QQQ", step=0.03),
                "IWM": bars("IWM", step=-0.03),
            }
        )

        self.assertEqual(ROTATION, packet.assessment.direction_state)
        self.assertGreaterEqual(
            packet.assessment.benchmark_return_dispersion_15m_pct,
            self.policy.rotation_dispersion_15m_pct,
        )

    def test_chop_is_not_mislabeled_as_data_unsafe(self) -> None:
        packet = self.evaluate({symbol: chop_bars(symbol) for symbol in CORE})

        self.assertEqual(CHOP, packet.assessment.direction_state)
        self.assertNotEqual(DATA_UNSAFE, packet.assessment.stress_state)
        self.assertEqual(EVALUATED, packet.opinion.evaluation_status)

    def test_late_trend_is_separate_from_direction(self) -> None:
        packet = self.evaluate(market(step=0.025))

        self.assertEqual(TREND_UP, packet.assessment.direction_state)
        self.assertEqual(LATE_TREND, packet.assessment.extension_state)
        self.assertEqual(NORMAL, packet.assessment.stress_state)

    def test_extreme_extension_and_exhaustion_are_not_crash_predictions(self) -> None:
        exhaustion = self.evaluate(market(step=0.038))
        extreme = self.evaluate(market(step=0.065))

        self.assertEqual(EXHAUSTION_RISK, exhaustion.assessment.extension_state)
        self.assertEqual(EXTREME_EXTENSION, extreme.assessment.extension_state)
        self.assertEqual(BULLISH, extreme.opinion.directional_bias)
        self.assertFalse(extreme.assessment.trade_recommendation)

    def test_volatility_shock_is_distinct_from_direction(self) -> None:
        packet = self.evaluate(
            {symbol: bars(symbol, step=0.0, final_half_range=1.8) for symbol in CORE}
        )

        self.assertEqual(VOLATILITY_SHOCK, packet.assessment.stress_state)
        self.assertIn(packet.assessment.direction_state, {CHOP, MIXED})
        self.assertEqual(VOLATILITY_SHOCK, packet.opinion.opinion_code)

    def test_coordinated_downside_is_market_stress(self) -> None:
        packet = self.evaluate(
            {symbol: accelerated_selloff_bars(symbol) for symbol in CORE}
        )

        self.assertEqual(MARKET_STRESS, packet.assessment.stress_state)
        self.assertEqual(BEARISH, packet.opinion.directional_bias)

    def test_data_unsafe_is_abstention_not_neutral(self) -> None:
        values = market(step=0.015)
        del values["IWM"]

        packet = self.evaluate(values)

        self.assertEqual(DATA_UNSAFE, packet.assessment.stress_state)
        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual(NO_OPINION, packet.opinion.opinion_code)
        self.assertEqual(NO_DIRECTION, packet.opinion.directional_bias)

    def test_raw_features_include_required_horizons_structure_vwap_and_volatility(self) -> None:
        packet = self.evaluate(
            prior_close_by_symbol={symbol: 99.5 for symbol in CORE}
        )
        feature = packet.assessment.benchmark_features[0]

        for value in (
            feature.return_1m_pct,
            feature.return_5m_pct,
            feature.return_15m_pct,
            feature.return_30m_pct,
            feature.return_60m_pct,
            feature.return_since_open_pct,
            feature.return_vs_prior_close_pct,
            feature.premarket_return_pct,
            feature.session_high,
            feature.session_low,
            feature.distance_from_session_high_pct,
            feature.distance_from_session_low_pct,
            feature.opening_range_location,
            feature.bar_derived_vwap,
            feature.distance_from_vwap_pct,
            feature.distance_from_vwap_atr,
            feature.atr,
            feature.realized_volatility_1m_pct,
            feature.range_expansion_multiple,
            feature.speed_5m_pct_per_minute,
            feature.acceleration_5m_pct_per_minute,
        ):
            self.assertIsNotNone(value)
        self.assertEqual(BAR_DERIVED_VWAP, feature.vwap_kind)

    def test_bounded_participation_is_labeled_and_identity_bound(self) -> None:
        proxy = ParticipationProxy(
            observed_count=5,
            advancing_count=3,
            declining_count=1,
            unchanged_count=1,
            as_of=(EVALUATED_AT - timedelta(seconds=30)).isoformat(),
            source_identity="synthetic-candidate-universe",
            evidence_fingerprint="a" * 64,
        )

        packet = self.evaluate(participation_proxy=proxy)

        self.assertEqual(
            BOUNDED_CANDIDATE_UNIVERSE_PROXY,
            packet.assessment.bounded_participation_proxy.evidence_scope,
        )
        self.assertTrue(
            any(
                item.evidence_id.startswith("bounded-participation-")
                for item in packet.opinion.evidence_refs
            )
        )

    def test_premarket_preserves_unobserved_true_overnight_path(self) -> None:
        evaluated = datetime(2026, 8, 17, 12, 20, 30, tzinfo=timezone.utc)
        values = {
            symbol: bars(
                symbol,
                step=0.015,
                first=datetime(2026, 8, 17, 11, 0, tzinfo=timezone.utc),
                count=80,
            )
            for symbol in CORE
        }

        packet = self.evaluate(values, evaluated_at=evaluated)

        self.assertEqual(PREMARKET, packet.assessment.session_state)
        self.assertIn(TRUE_04_TO_07_PATH_UNOBSERVED, packet.assessment.limitations)
        self.assertEqual(PARTIAL, packet.assessment.data_quality_state)

    def test_heuristic_confidence_is_not_probability(self) -> None:
        packet = self.evaluate()

        self.assertEqual(HEURISTIC, packet.opinion.confidence.kind)
        self.assertEqual(UNCALIBRATED, packet.opinion.confidence.calibration_status)
        self.assertIsNone(packet.opinion.confidence.sample_size)
        self.assertIn("not a probability", packet.opinion.explanation)

    def test_macro_block_context_is_research_market_stress_only(self) -> None:
        target = market_observation_id(
            research_identity=self.policy.research_identity,
            evaluated_at=EVALUATED_AT,
        )
        context = macro_context(target)

        packet = self.evaluate(opportunity_id=target, macro_context=context)

        self.assertEqual(MARKET_STRESS, packet.assessment.stress_state)
        self.assertEqual(BLOCK_NEW_ENTRY, packet.assessment.macro_context_status)
        self.assertEqual(RESEARCH_ONLY, packet.opinion.authority)
        self.assertFalse(packet.assessment.trade_recommendation)

    def test_stale_macro_context_abstains_as_data_unsafe(self) -> None:
        target = market_observation_id(
            research_identity=self.policy.research_identity,
            evaluated_at=EVALUATED_AT,
        )
        context = macro_context(target, stale=True)

        packet = self.evaluate(opportunity_id=target, macro_context=context)

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("DATA_BASIS_UNCERTAIN", packet.opinion.abstention_reason)
        self.assertEqual(DATA_UNSAFE, packet.assessment.stress_state)


class RegimeSpecialistNegativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = default_regime_research_policy()

    def evaluate(self, values, **kwargs):
        return evaluate_regime_specialist(
            bars_by_symbol=values,
            evaluated_at=kwargs.pop("evaluated_at", EVALUATED_AT),
            policy=kwargs.pop("policy", self.policy),
            **kwargs,
        )

    def test_each_missing_core_benchmark_abstains(self) -> None:
        for missing in CORE:
            with self.subTest(missing=missing):
                values = market(step=0.015)
                del values[missing]
                packet = self.evaluate(values)
                self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
                self.assertEqual((missing,), packet.assessment.missing_benchmarks)

    def test_empty_and_incomplete_horizon_abstain(self) -> None:
        empty = market(step=0.015)
        empty["SPY"] = ()
        short = {symbol: bars(symbol, step=0.015, count=40) for symbol in CORE}

        self.assertEqual(ABSTAINED, self.evaluate(empty).opinion.evaluation_status)
        self.assertEqual(ABSTAINED, self.evaluate(short).opinion.evaluation_status)

    def test_stale_benchmark_abstains(self) -> None:
        packet = self.evaluate(
            market(step=0.015),
            evaluated_at=EVALUATED_AT + timedelta(minutes=3),
        )

        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("STALE_EVIDENCE", packet.opinion.abstention_reason)

    def test_future_or_in_progress_bar_fails(self) -> None:
        values = market(step=0.015)
        latest = values["SPY"][-1]
        values["SPY"] = (*values["SPY"], replace(
            latest,
            timestamp=datetime(2026, 8, 17, 13, 35, tzinfo=timezone.utc).isoformat(),
        ))

        packet = self.evaluate(values)

        self.assertEqual(FAILED, packet.opinion.evaluation_status)
        self.assertEqual(DATA_UNSAFE, packet.assessment.stress_state)
        self.assertEqual(NO_DIRECTION, packet.opinion.directional_bias)

    def test_mixed_session_dates_fail(self) -> None:
        values = market(step=0.015)
        values["SPY"] = (
            replace(values["SPY"][0], timestamp=(FIRST_BAR - timedelta(days=1)).isoformat()),
            *values["SPY"][1:],
        )

        self.assertEqual(FAILED, self.evaluate(values).opinion.evaluation_status)

    def test_wrong_symbol_identity_fails(self) -> None:
        values = market(step=0.015)
        values["SPY"] = (replace(values["SPY"][0], symbol="DIA"), *values["SPY"][1:])

        self.assertEqual(FAILED, self.evaluate(values).opinion.evaluation_status)

    def test_mixed_source_identity_fails(self) -> None:
        values = market(step=0.015)
        values["SPY"] = (
            replace(values["SPY"][0], source_identity="another-source"),
            *values["SPY"][1:],
        )

        self.assertEqual(FAILED, self.evaluate(values).opinion.evaluation_status)

    def test_duplicate_timestamp_and_normalized_symbol_fail(self) -> None:
        values = market(step=0.015)
        values["SPY"] = (*values["SPY"], values["SPY"][-1])
        duplicated_key = market(step=0.015)
        duplicated_key["spy"] = duplicated_key["SPY"]

        self.assertEqual(FAILED, self.evaluate(values).opinion.evaluation_status)
        self.assertEqual(FAILED, self.evaluate(duplicated_key).opinion.evaluation_status)

    def test_internal_gap_fails(self) -> None:
        values = market(step=0.015)
        rows = list(values["QQQ"])
        rows[20] = replace(
            rows[20],
            timestamp=(datetime.fromisoformat(rows[20].timestamp) + timedelta(minutes=2)).isoformat(),
        )
        values["QQQ"] = tuple(rows)

        self.assertEqual(FAILED, self.evaluate(values).opinion.evaluation_status)

    def test_missing_opening_range_abstains(self) -> None:
        evaluated = datetime(2026, 8, 17, 13, 30, 30, tzinfo=timezone.utc)
        values = {
            symbol: bars(
                symbol,
                step=0.015,
                first=datetime(2026, 8, 17, 12, 25, tzinfo=timezone.utc),
                count=65,
            )
            for symbol in CORE
        }

        packet = self.evaluate(values, evaluated_at=evaluated)

        self.assertEqual(OPENING, packet.assessment.session_state)
        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertIn("MISSING_OPENING_RANGE", packet.assessment.reason_codes[0])

    def test_timezone_naive_clock_is_rejected(self) -> None:
        with self.assertRaisesRegex(RegimeResearchError, "timezone-aware"):
            self.evaluate(
                market(step=0.015),
                evaluated_at=EVALUATED_AT.replace(tzinfo=None),
            )

    def test_after_hours_is_identified_and_abstains(self) -> None:
        packet = self.evaluate(
            market(step=0.015),
            evaluated_at=datetime(2026, 8, 17, 20, 5, tzinfo=timezone.utc),
        )

        self.assertEqual(AFTER_HOURS, packet.assessment.session_state)
        self.assertEqual(ABSTAINED, packet.opinion.evaluation_status)
        self.assertEqual("UNSUPPORTED_SESSION", packet.opinion.abstention_reason)

    def test_after_hours_cannot_be_enabled_without_a_validated_profile(self) -> None:
        policy = replace(self.policy, allow_after_hours_evaluation=True)

        with self.assertRaisesRegex(RegimeResearchError, "unsupported"):
            self.evaluate(market(step=0.015), policy=policy)

    def test_expected_input_fingerprint_detects_tampered_candle(self) -> None:
        original = self.evaluate(market(step=0.015))
        values = market(step=0.015)
        rows = list(values["IWM"])
        rows[-1] = replace(
            rows[-1],
            close=rows[-1].close + 0.01,
            high=rows[-1].high + 0.01,
        )
        values["IWM"] = tuple(rows)

        packet = self.evaluate(
            values,
            expected_input_evidence_fingerprint=(
                original.assessment.input_evidence_fingerprint
            ),
        )

        self.assertEqual(FAILED, packet.opinion.evaluation_status)
        self.assertIn("FINGERPRINT_MISMATCH", packet.opinion.failure_reason)

    def test_extreme_single_index_move_does_not_claim_aligned_trend(self) -> None:
        values = {
            "SPY": bars("SPY", step=0.08),
            "QQQ": bars("QQQ", step=0.0),
            "IWM": bars("IWM", step=0.0),
        }

        packet = self.evaluate(values)

        self.assertNotIn(packet.assessment.direction_state, {TREND_UP, TREND_DOWN})

    def test_policy_tampering_and_bad_threshold_semantics_are_rejected(self) -> None:
        bad = replace(self.policy, threshold_semantics="OPTIMIZED_BACKTEST")
        reordered = replace(self.policy, extreme_vwap_atr=1.0)
        missing_session = replace(
            self.policy,
            session_threshold_multipliers=self.policy.session_threshold_multipliers[:-1],
        )

        for policy in (bad, reordered, missing_session):
            with self.subTest(policy=policy):
                with self.assertRaises(RegimeResearchError):
                    self.evaluate(market(step=0.015), policy=policy)

    def test_assessment_tampering_is_detected(self) -> None:
        packet = self.evaluate(market(step=0.015))
        tampered = replace(packet.assessment, direction_state=TREND_DOWN)

        with self.assertRaisesRegex(RegimeResearchError, "fingerprint"):
            validate_assessment(tampered)

    def test_semantically_impossible_raw_feature_is_rejected_before_hash_trust(self) -> None:
        packet = self.evaluate(market(step=0.015))
        invalid_feature = replace(
            packet.assessment.benchmark_features[0],
            current_price=float("nan"),
        )
        tampered = replace(
            packet.assessment,
            benchmark_features=(
                invalid_feature,
                *packet.assessment.benchmark_features[1:],
            ),
        )

        with self.assertRaisesRegex(RegimeResearchError, "nonfinite"):
            validate_assessment(tampered)

    def test_common_opinion_tampering_and_authority_escalation_are_detected(self) -> None:
        packet = self.evaluate(market(step=0.015))
        tampered_opinion = replace(packet.opinion, directional_bias=BEARISH)
        elevated_opinion = replace(packet.opinion, authority="EXECUTION_VETO")

        for opinion in (tampered_opinion, elevated_opinion):
            with self.subTest(opinion=opinion):
                with self.assertRaises(Exception):
                    validate_packet(replace(packet, opinion=opinion))

    def test_participation_proxy_cannot_claim_full_market_breadth(self) -> None:
        proxy = ParticipationProxy(
            observed_count=3,
            advancing_count=2,
            declining_count=1,
            unchanged_count=0,
            as_of=EVALUATED_AT.isoformat(),
            source_identity="synthetic-proxy",
            evidence_fingerprint="a" * 64,
            evidence_scope="FULL_MARKET_EVIDENCE",
        )

        with self.assertRaisesRegex(RegimeResearchError, "full-market"):
            self.evaluate(market(step=0.015), participation_proxy=proxy)

    def test_future_macro_context_fails_and_cannot_be_neutral(self) -> None:
        target = market_observation_id(
            research_identity=self.policy.research_identity,
            evaluated_at=EVALUATED_AT,
        )
        future = macro_context(
            target,
            evaluated_at=EVALUATED_AT + timedelta(minutes=1),
        )

        packet = self.evaluate(market(step=0.015), opportunity_id=target, macro_context=future)

        self.assertEqual(FAILED, packet.opinion.evaluation_status)
        self.assertEqual(NO_DIRECTION, packet.opinion.directional_bias)


class RegimeSpecialistContractTests(unittest.TestCase):
    def test_output_is_deterministic_byte_stable_and_immutable(self) -> None:
        policy = default_regime_research_policy()
        values = market(step=0.015)
        first = evaluate_regime_specialist(
            bars_by_symbol=values,
            evaluated_at=EVALUATED_AT,
            policy=policy,
        )
        second = evaluate_regime_specialist(
            bars_by_symbol={key: values[key] for key in reversed(tuple(values))},
            evaluated_at=EVALUATED_AT,
            policy=policy,
        )

        self.assertEqual(first, second)
        self.assertEqual(packet_json_bytes(first), packet_json_bytes(second))
        self.assertTrue(packet_json_bytes(first).endswith(b"\n"))
        with self.assertRaises(FrozenInstanceError):
            first.assessment.direction_state = TREND_DOWN  # type: ignore[misc]

    def test_evaluator_does_not_mutate_source_collections(self) -> None:
        policy = default_regime_research_policy()
        values = {symbol: list(rows) for symbol, rows in market(step=0.015).items()}
        before = copy.deepcopy(values)

        evaluate_regime_specialist(
            bars_by_symbol=values,
            evaluated_at=EVALUATED_AT,
            policy=policy,
        )

        self.assertEqual(before, values)

    def test_material_policy_change_changes_policy_packet_and_opinion_identity(self) -> None:
        original_policy = default_regime_research_policy()
        changed_policy = replace(
            original_policy,
            policy_version="regime-exhaustion-research-policy-v1b",
            late_trend_vwap_atr=1.6,
        )
        original = evaluate_regime_specialist(
            bars_by_symbol=market(step=0.015),
            evaluated_at=EVALUATED_AT,
            policy=original_policy,
        )
        changed = evaluate_regime_specialist(
            bars_by_symbol=market(step=0.015),
            evaluated_at=EVALUATED_AT,
            policy=changed_policy,
        )

        self.assertNotEqual(original.policy.fingerprint, changed.policy.fingerprint)
        self.assertNotEqual(original.opinion.opinion_id, changed.opinion.opinion_id)
        self.assertNotEqual(original.fingerprint, changed.fingerprint)

    def test_policy_identity_and_future_cadence_are_dormant_metadata(self) -> None:
        policy = default_regime_research_policy()

        self.assertEqual(REGIME_SPECIALIST_VERSION, policy.specialist_version)
        self.assertEqual(RESEARCH_HEURISTIC, policy.threshold_semantics)
        self.assertEqual(5, policy.proposed_cadence_minutes)
        self.assertFalse(policy.allow_after_hours_evaluation)

    def test_module_has_no_network_provider_broker_runtime_or_execution_import(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "regime_exhaustion_specialist.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        forbidden = (
            "requests",
            "urllib",
            "httpx",
            "socket",
            "alpaca",
            "schwab_market_data",
            "account",
            "broker",
            "order",
            "execution",
            "risk_governor",
            "trade_planning",
            "intraday_trade_plan",
            "successor_setup_observer",
            "service",
            "scheduler",
            "engine_host",
            "wpf",
        )
        self.assertFalse(
            [name for name in imports if any(part in name.lower() for part in forbidden)]
        )


def market(*, step: float) -> dict[str, tuple[RegimeBar, ...]]:
    return {symbol: bars(symbol, step=step) for symbol in CORE}


def bars(
    symbol: str,
    *,
    step: float,
    count: int = 65,
    first: datetime = FIRST_BAR,
    half_range: float = 0.20,
    final_half_range: float | None = None,
) -> tuple[RegimeBar, ...]:
    result = []
    for index in range(count):
        previous = 100.0 + ((index - 1) * step) if index else 100.0
        close = 100.0 + (index * step)
        open_price = previous
        spread = final_half_range if final_half_range is not None and index == count - 1 else half_range
        result.append(
            RegimeBar(
                symbol=symbol,
                timestamp=(first + timedelta(minutes=index)).isoformat(),
                open=open_price,
                high=max(open_price, close) + spread,
                low=min(open_price, close) - spread,
                close=close,
                volume=100_000.0 + (index * 100.0),
                source_identity="schwab-price-history:synthetic-fixture",
                source_state="RECONCILED",
            )
        )
    return tuple(result)


def chop_bars(symbol: str) -> tuple[RegimeBar, ...]:
    result = []
    previous = 100.0
    for index in range(65):
        close = 100.05 if index % 2 else 99.95
        result.append(
            RegimeBar(
                symbol=symbol,
                timestamp=(FIRST_BAR + timedelta(minutes=index)).isoformat(),
                open=previous,
                high=max(previous, close) + 0.20,
                low=min(previous, close) - 0.20,
                close=close,
                volume=100_000.0,
                source_identity="schwab-price-history:synthetic-fixture",
                source_state="RECONCILED",
            )
        )
        previous = close
    return tuple(result)


def accelerated_selloff_bars(symbol: str) -> tuple[RegimeBar, ...]:
    result = list(bars(symbol, step=-0.005))
    for offset in range(6):
        index = len(result) - 6 + offset
        previous_close = result[index - 1].close
        close = previous_close - 0.30
        result[index] = replace(
            result[index],
            open=previous_close,
            high=previous_close + 0.55,
            low=close - 0.55,
            close=close,
        )
    return tuple(result)


def macro_context(
    target: str,
    *,
    evaluated_at: datetime = EVALUATED_AT,
    stale: bool = False,
):
    definition = EventDefinition(
        source_event_id="fed-event-1",
        revision_identity="revision-1",
        category=FED_DECISION,
        title="Synthetic Fed event",
        importance=HIGH,
        evidence_state=CURRENT,
        scheduled_start=(evaluated_at - timedelta(minutes=5)).isoformat(),
        scheduled_end=(evaluated_at + timedelta(minutes=5)).isoformat(),
        risk_window_start=(evaluated_at - timedelta(minutes=15)).isoformat(),
        risk_window_end=(evaluated_at + timedelta(minutes=15)).isoformat(),
        observation_window_start=(evaluated_at - timedelta(minutes=30)).isoformat(),
        observation_window_end=(evaluated_at + timedelta(minutes=30)).isoformat(),
        scope=MARKET,
        source_identity="synthetic-approved-calendar",
        provider_timestamp=(evaluated_at - timedelta(hours=1)).isoformat(),
        receipt_timestamp=(evaluated_at - timedelta(minutes=59)).isoformat(),
    )
    calendar = build_event_calendar(
        definitions=(definition,),
        generated_at=evaluated_at - timedelta(minutes=50),
        valid_through=(
            evaluated_at - timedelta(minutes=1)
            if stale
            else evaluated_at + timedelta(hours=1)
        ),
    )
    policy = EventRiskPolicy(
        policy_version="synthetic-regime-macro-policy-v1",
        rules=(EventConsequenceRule(FED_DECISION, HIGH, BLOCK_NEW_ENTRY),),
        maximum_candidate_fan_out=3,
    )
    from momentum_hunter.macro_event_context import EventRiskTarget

    return evaluate_event_risk(
        calendar=calendar,
        policy=policy,
        evaluated_at=evaluated_at,
        target=EventRiskTarget(target, "SPY"),
    )


if __name__ == "__main__":
    unittest.main()
