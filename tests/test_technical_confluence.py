from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta

from momentum_hunter import technical_confluence
from momentum_hunter.technical_breakouts import (
    BREAKOUT_FAILED,
    BREAKOUT_PRESENT,
    BreakoutEvent,
    TechnicalPriceBar,
    study_breakout_events,
)
from momentum_hunter.technical_confluence import (
    BLOCKED,
    CAUTION,
    CLEAR,
    FAMILY_BREAKOUT,
    FAMILY_MARKET_REGIME,
    FAMILY_MOMENTUM,
    FAMILY_RELATIVE_STRENGTH,
    FAMILY_TREND,
    FAMILY_VOLUME,
    GREEN,
    HOSTILE,
    INSUFFICIENT_DATA,
    MIXED,
    RED,
    STRONG_CONFLUENCE,
    SUPPORTIVE,
    TEMPORAL_STABILITY_RELEASED,
    TEMPORAL_STABILITY_WITHHELD,
    TechnicalConfluenceOptions,
    TechnicalConfluenceError,
    accumulation_distribution_state,
    adx_trend_strength_state,
    anchored_vwap_state,
    atr_extension_risk_state,
    atr_expansion_state,
    average_daily_range_expansion_state,
    benchmark_sma_regime_state,
    bollinger_bandwidth_state,
    breakout_context_state,
    build_technical_confluence_report_payload,
    build_technical_confluence_study_payload,
    chaikin_money_flow_state,
    ema_stack_state,
    evaluate_wave1_confluence,
    macd_momentum_state,
    money_flow_index_state,
    obv_new_high_state,
    ppo_momentum_state,
    rate_of_change_state,
    relative_strength_long_slope_state,
    relative_strength_new_high_state,
    relative_strength_short_slope_state,
    relative_strength_state,
    render_technical_confluence_markdown,
    render_technical_confluence_study_markdown,
    rsi_regime_state,
    sma_position_state,
    squeeze_release_state,
    supertrend_state,
    up_down_volume_state,
    volume_confirmation_state,
    write_technical_confluence_reports,
    write_technical_confluence_study_reports,
)


class TechnicalConfluenceTests(unittest.TestCase):
    def test_ema_stack_marks_green_without_mutating_source_bars(self) -> None:
        bars = daily_bars("AAA", [10 + offset * 0.2 for offset in range(70)])
        before = fingerprint_bars(bars)

        state = ema_stack_state(bars, len(bars) - 1)

        self.assertEqual(GREEN, state.state)
        self.assertEqual(before, fingerprint_bars(bars))

    def test_sma_position_preserves_partial_20_50_and_full_200_state(self) -> None:
        partial = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(70)],
        )
        full = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(220)],
        )
        bearish = daily_bars(
            "AAA",
            [300.0 - offset for offset in range(220)],
        )

        partial_state = sma_position_state(partial, 69)
        full_state = sma_position_state(full, 219)
        bearish_state = sma_position_state(bearish, 219)

        self.assertEqual(GREEN, partial_state.state)
        self.assertFalse(partial_state.details["long_window_available"])
        self.assertFalse(partial_state.details["full_bullish"])
        self.assertEqual(GREEN, full_state.state)
        self.assertTrue(full_state.details["long_window_available"])
        self.assertTrue(full_state.details["full_bullish"])
        self.assertEqual(RED, bearish_state.state)

    def test_supertrend_marks_sustained_uptrend_green(self) -> None:
        state = supertrend_state(
            daily_bars("AAA", [10.0 + offset for offset in range(30)]),
            29,
        )

        self.assertEqual(GREEN, state.state)
        self.assertEqual("BULLISH", state.details["direction"])
        self.assertGreater(
            state.details["close"],
            state.details["active_line"],
        )
        self.assertEqual(10, state.details["atr_window"])
        self.assertEqual(3.0, state.details["atr_multiple"])
        self.assertEqual("UPPER_BAND", state.details["initialization"])

    def test_supertrend_marks_sustained_downtrend_red(self) -> None:
        state = supertrend_state(
            daily_bars("AAA", [40.0 - offset for offset in range(30)]),
            29,
        )

        self.assertEqual(RED, state.state)
        self.assertEqual("BEARISH", state.details["direction"])
        self.assertLess(
            state.details["close"],
            state.details["active_line"],
        )

    def test_supertrend_flips_after_price_crosses_active_band(self) -> None:
        closes = (
            [10.0 + offset for offset in range(40)]
            + [49.0 - 2.0 * offset for offset in range(20)]
        )
        bars = daily_bars("AAA", closes)

        before_reversal = supertrend_state(bars, 39)
        after_reversal = supertrend_state(bars, 59)

        self.assertEqual(GREEN, before_reversal.state)
        self.assertEqual(RED, after_reversal.state)
        self.assertEqual("BEARISH", after_reversal.details["direction"])

    def test_supertrend_requires_registry_minimum_history(self) -> None:
        state = supertrend_state(
            daily_bars("AAA", [10.0 + offset for offset in range(29)]),
            28,
        )

        self.assertEqual(INSUFFICIENT_DATA, state.state)
        self.assertEqual(30, state.details["minimum_bars"])

    def test_supertrend_ignores_future_bars_without_source_mutation(
        self,
    ) -> None:
        bars = daily_bars(
            "AAA",
            [10.0 + offset for offset in range(60)],
        )
        source_before = fingerprint_bars(bars)
        state_before = asdict(supertrend_state(bars, 29))
        self.assertEqual(source_before, fingerprint_bars(bars))

        bars[59] = replace(
            bars[59],
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
        )
        manually_mutated = fingerprint_bars(bars)
        state_after = asdict(supertrend_state(bars, 29))

        self.assertEqual(state_before, state_after)
        self.assertEqual(manually_mutated, fingerprint_bars(bars))
        self.assertNotEqual(source_before, fingerprint_bars(bars))

    def test_benchmark_sma_regime_preserves_partial_qqq_context(self) -> None:
        stock = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(70)],
        )
        benchmark = daily_bars(
            "QQQ",
            [100.0 + offset * 0.2 for offset in range(70)],
        )

        state = benchmark_sma_regime_state(
            benchmark,
            as_of=benchmark[-1].timestamp,
        )
        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=stock,
            benchmark_bars=benchmark,
        )

        self.assertEqual(GREEN, state.state)
        self.assertEqual("QQQ", state.details["benchmark_symbol"])
        self.assertFalse(state.details["long_window_available"])
        self.assertEqual(
            SUPPORTIVE,
            summary.family_states[FAMILY_MARKET_REGIME].state,
        )

    def test_benchmark_sma_regime_projects_mixed_and_hostile_context(self) -> None:
        mixed_benchmark = daily_bars("QQQ", [100.0] * 70)
        hostile_benchmark = daily_bars(
            "QQQ",
            [300.0 - offset for offset in range(220)],
        )
        partial_stock = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(70)],
        )
        full_stock = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(220)],
        )

        mixed = evaluate_wave1_confluence(
            symbol="AAA",
            bars=partial_stock,
            benchmark_bars=mixed_benchmark,
        )
        hostile = evaluate_wave1_confluence(
            symbol="AAA",
            bars=full_stock,
            benchmark_bars=hostile_benchmark,
        )

        self.assertEqual(
            MIXED,
            mixed.family_states[FAMILY_MARKET_REGIME].state,
        )
        self.assertEqual(
            HOSTILE,
            hostile.family_states[FAMILY_MARKET_REGIME].state,
        )
        self.assertLessEqual(hostile.independent_total_families, 6)
        self.assertEqual(
            hostile.major_red_flags,
            sum(
                1
                for family, state in hostile.family_states.items()
                if family != FAMILY_MARKET_REGIME
                and state.state
                in {
                    RED,
                    BLOCKED,
                    technical_confluence.FAIL,
                }
            ),
        )

    def test_benchmark_sma_regime_aligns_as_of_and_ignores_future_bars(self) -> None:
        benchmark = daily_bars(
            "QQQ",
            [100.0 + offset * 0.2 for offset in range(220)],
        )
        source_before = fingerprint_bars(benchmark)
        as_of = benchmark[69].timestamp
        before = asdict(
            benchmark_sma_regime_state(
                benchmark,
                as_of=as_of,
            )
        )

        benchmark[219] = replace(
            benchmark[219],
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
        )
        mutated_source = fingerprint_bars(benchmark)
        after = asdict(
            benchmark_sma_regime_state(
                benchmark,
                as_of=as_of,
            )
        )
        missing_date = benchmark_sma_regime_state(
            benchmark,
            as_of="2027-12-31",
        )

        self.assertEqual(before, after)
        self.assertEqual(INSUFFICIENT_DATA, missing_date.state)
        self.assertEqual(mutated_source, fingerprint_bars(benchmark))
        self.assertNotEqual(source_before, fingerprint_bars(benchmark))

    def test_adx_marks_directional_trend_strength_green(self) -> None:
        bars = [
            daily_bar("AAA", offset, close=10 + offset, high=10.5 + offset, low=9.8 + offset, volume=100)
            for offset in range(35)
        ]

        state = adx_trend_strength_state(bars, len(bars) - 1)

        self.assertEqual(GREEN, state.state)
        self.assertGreaterEqual(float(state.value or 0), 20.0)

    def test_squeeze_release_marks_green_after_prior_compression(self) -> None:
        bars = [
            daily_bar("AAA", offset, close=10.0, high=11.0, low=9.0, volume=100)
            for offset in range(22)
        ]
        bars.append(
            daily_bar(
                "AAA",
                22,
                close=13.2,
                high=13.3,
                low=13.0,
                volume=250,
            )
        )

        state = squeeze_release_state(bars, len(bars) - 1)

        self.assertEqual(GREEN, state.state)
        self.assertTrue(state.details["was_compressed"])
        self.assertTrue(state.details["released"])

    def test_bollinger_bandwidth_detects_lowest_percentile_squeeze(self) -> None:
        bars = daily_bars(
            "AAA",
            [
                8.0 if offset % 2 == 0 else 12.0
                for offset in range(120)
            ]
            + [10.0] * 20,
        )

        state = bollinger_bandwidth_state(bars, 139)

        self.assertEqual(GREEN, state.state)
        self.assertLessEqual(
            state.details["percentile_rank"],
            state.details["squeeze_percentile"],
        )
        self.assertEqual(120, state.details["prior_readings"])
        self.assertEqual("midrank", state.details["tie_method"])

    def test_bollinger_bandwidth_rejects_high_percentile_expansion(self) -> None:
        bars = daily_bars(
            "AAA",
            [10.0] * 120
            + [
                8.0 if offset % 2 == 0 else 12.0
                for offset in range(20)
            ],
        )

        state = bollinger_bandwidth_state(bars, 139)

        self.assertEqual(RED, state.state)
        self.assertGreater(
            state.details["percentile_rank"],
            state.details["squeeze_percentile"],
        )

    def test_bollinger_bandwidth_midrank_avoids_false_tied_squeeze(self) -> None:
        state = bollinger_bandwidth_state(
            daily_bars("AAA", [10.0] * 140),
            139,
        )

        self.assertEqual(RED, state.state)
        self.assertEqual(50.0, state.details["percentile_rank"])

    def test_bollinger_bandwidth_requires_full_percentile_history(self) -> None:
        state = bollinger_bandwidth_state(
            daily_bars("AAA", [10.0] * 139),
            138,
        )

        self.assertEqual(INSUFFICIENT_DATA, state.state)
        self.assertEqual(140, state.details["minimum_bars"])
        self.assertEqual(
            "NOT_CONFIGURED",
            state.details["short_history_fallback"],
        )

    def test_bollinger_bandwidth_ignores_future_bars_without_mutation(
        self,
    ) -> None:
        bars = daily_bars(
            "AAA",
            [
                8.0 if offset % 2 == 0 else 12.0
                for offset in range(120)
            ]
            + [10.0] * 50,
        )
        source_before = fingerprint_bars(bars)
        state_before = asdict(bollinger_bandwidth_state(bars, 139))
        self.assertEqual(source_before, fingerprint_bars(bars))

        bars[169] = replace(
            bars[169],
            open=25.0,
            high=25.0,
            low=25.0,
            close=25.0,
        )
        manually_mutated = fingerprint_bars(bars)
        state_after = asdict(bollinger_bandwidth_state(bars, 139))

        self.assertEqual(state_before, state_after)
        self.assertEqual(manually_mutated, fingerprint_bars(bars))
        self.assertNotEqual(source_before, fingerprint_bars(bars))

    def test_atr_expansion_requires_upside_direction_for_green(self) -> None:
        rising = [
            daily_bar(
                "AAA",
                offset,
                close=10.0 + offset * 0.1,
                high=10.1 + offset * 0.1,
                low=9.9 + offset * 0.1,
                volume=100,
            )
            for offset in range(34)
        ]
        falling = list(rising)
        rising.append(
            daily_bar(
                "AAA",
                34,
                close=16.0,
                high=18.0,
                low=15.0,
                volume=100,
            )
        )
        falling.append(
            daily_bar(
                "AAA",
                34,
                close=10.0,
                high=13.5,
                low=9.0,
                volume=100,
            )
        )

        confirming = atr_expansion_state(rising, 34)
        unconfirmed = atr_expansion_state(falling, 34)

        self.assertEqual(GREEN, confirming.state)
        self.assertGreaterEqual(
            confirming.details["expansion_ratio"],
            confirming.details["expansion_threshold"],
        )
        self.assertTrue(confirming.details["upside_direction"])
        self.assertEqual("YELLOW", unconfirmed.state)
        self.assertFalse(unconfirmed.details["upside_direction"])

    def test_average_daily_range_expansion_uses_prior_adr20(self) -> None:
        confirming = [
            daily_bar(
                "AAA",
                offset,
                close=10.0 + offset * 0.1,
                high=10.1 + offset * 0.1,
                low=9.9 + offset * 0.1,
                volume=100,
            )
            for offset in range(24)
        ]
        unconfirmed = list(confirming)
        confirming.append(
            daily_bar(
                "AAA",
                24,
                close=14.0,
                high=15.0,
                low=12.0,
                volume=100,
            )
        )
        unconfirmed.append(
            daily_bar(
                "AAA",
                24,
                close=9.0,
                high=12.5,
                low=8.0,
                volume=100,
            )
        )

        expansion = average_daily_range_expansion_state(confirming, 24)
        downside = average_daily_range_expansion_state(unconfirmed, 24)

        self.assertEqual(GREEN, expansion.state)
        self.assertEqual("absolute_high_low", expansion.details["range_basis"])
        self.assertEqual(20, expansion.details["window"])
        self.assertEqual(1.5, expansion.details["expansion_threshold"])
        self.assertEqual("YELLOW", downside.state)
        self.assertFalse(downside.details["upside_direction"])

    def test_volatility_expansion_marks_short_history_insufficient(self) -> None:
        bars = [
            daily_bar(
                "AAA",
                offset,
                close=10.0,
                high=10.1,
                low=9.9,
                volume=100,
            )
            for offset in range(24)
        ]

        self.assertEqual(
            INSUFFICIENT_DATA,
            atr_expansion_state(bars, 23).state,
        )
        self.assertEqual(
            INSUFFICIENT_DATA,
            average_daily_range_expansion_state(bars, 23).state,
        )

    def test_volatility_expansion_ignores_future_bars_and_source_mutation(
        self,
    ) -> None:
        bars = [
            daily_bar(
                "AAA",
                offset,
                close=10.0 + offset * 0.1,
                high=10.1 + offset * 0.1,
                low=9.9 + offset * 0.1,
                volume=100,
            )
            for offset in range(60)
        ]
        source_before = fingerprint_bars(bars)
        states_before = [
            asdict(atr_expansion_state(bars, 34)),
            asdict(average_daily_range_expansion_state(bars, 34)),
        ]
        self.assertEqual(source_before, fingerprint_bars(bars))

        bars[59] = replace(
            bars[59],
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.0,
        )
        manually_mutated = fingerprint_bars(bars)
        states_after = [
            asdict(atr_expansion_state(bars, 34)),
            asdict(average_daily_range_expansion_state(bars, 34)),
        ]

        self.assertEqual(states_before, states_after)
        self.assertEqual(manually_mutated, fingerprint_bars(bars))
        self.assertNotEqual(source_before, fingerprint_bars(bars))

    def test_volatility_expansion_checks_remain_one_family(self) -> None:
        bars = [
            daily_bar(
                "AAA",
                offset,
                close=10.0 + offset * 0.1,
                high=10.1 + offset * 0.1,
                low=9.9 + offset * 0.1,
                volume=100,
            )
            for offset in range(60)
        ]

        summary = evaluate_wave1_confluence(symbol="AAA", bars=bars)
        volatility_names = {
            state.name
            for state in summary.indicator_states
            if state.family == technical_confluence.FAMILY_VOLATILITY
        }

        self.assertEqual(
            {
                "bollinger_bandwidth_percentile",
                "bollinger_keltner_squeeze_release",
                "atr_expansion",
                "average_daily_range_expansion",
            },
            volatility_names,
        )
        self.assertLessEqual(summary.independent_total_families, 6)

    def test_volume_confirmation_uses_prior_average(self) -> None:
        bars = daily_bars("AAA", [10.0] * 21, volume=100)
        bars.append(daily_bar("AAA", 21, close=10.5, high=10.6, low=10.2, volume=200))

        state = volume_confirmation_state(bars, 21)

        self.assertEqual(GREEN, state.state)
        self.assertEqual(2.0, state.value)

    def test_rsi_regime_requires_sustained_strength(self) -> None:
        constructive = daily_bars(
            "AAA",
            [10.0 + offset * 0.1 for offset in range(30)],
        )
        one_bar_spike = daily_bars("AAA", [10.0] * 29 + [12.0])

        constructive_state = rsi_regime_state(
            constructive,
            len(constructive) - 1,
        )
        spike_state = rsi_regime_state(
            one_bar_spike,
            len(one_bar_spike) - 1,
        )

        self.assertEqual(GREEN, constructive_state.state)
        self.assertTrue(constructive_state.details["held_above_floor"])
        self.assertEqual(RED, spike_state.state)
        self.assertFalse(spike_state.details["held_above_floor"])

    def test_macd_and_ppo_detect_bullish_inflection(self) -> None:
        bars = daily_bars("AAA", [10.0] * 34 + [12.0])

        macd = macd_momentum_state(bars, len(bars) - 1)
        ppo = ppo_momentum_state(bars, len(bars) - 1)

        self.assertEqual(GREEN, macd.state)
        self.assertTrue(macd.details["crossed_above"])
        self.assertEqual(GREEN, ppo.state)
        self.assertTrue(ppo.details["percentage_based"])

    def test_obv_new_high_uses_prior_completed_windows(self) -> None:
        bars = daily_bars(
            "AAA",
            [10.0 + offset * 0.1 for offset in range(51)],
            volume=100,
        )

        state = obv_new_high_state(bars, len(bars) - 1)

        self.assertEqual(GREEN, state.state)
        self.assertTrue(state.details["short_window_new_high"])
        self.assertTrue(state.details["long_window_new_high"])

    def test_money_flow_index_requires_improvement_above_midpoint(self) -> None:
        closes = [
            10.0 + (offset % 3) * 0.1 + offset * 0.01
            for offset in range(60)
        ]
        bars = daily_bars("AAA", closes, volume=100)

        state = money_flow_index_state(bars, len(bars) - 1)

        self.assertEqual(GREEN, state.state)
        self.assertGreater(float(state.value or 0), 50.0)
        self.assertTrue(state.details["improving"])

    def test_chaikin_money_flow_handles_positive_negative_and_flat_ranges(self) -> None:
        positive = [
            daily_bar(
                "AAA",
                offset,
                close=10.0 + offset * 0.1,
                high=10.0 + offset * 0.1,
                low=9.0 + offset * 0.1,
                volume=100,
            )
            for offset in range(21)
        ]
        negative = [
            daily_bar(
                "AAA",
                offset,
                close=9.0 + offset * 0.1,
                high=10.0 + offset * 0.1,
                low=9.0 + offset * 0.1,
                volume=100,
            )
            for offset in range(21)
        ]
        flat = daily_bars("AAA", [10.0] * 21, volume=100)

        self.assertEqual(
            GREEN,
            chaikin_money_flow_state(positive, 20).state,
        )
        self.assertEqual(
            RED,
            chaikin_money_flow_state(negative, 20).state,
        )
        self.assertEqual(
            "YELLOW",
            chaikin_money_flow_state(flat, 20).state,
        )

    def test_rate_of_change_reports_fixed_10_20_60_window_values(self) -> None:
        bars = daily_bars(
            "AAA",
            [10.0 + offset for offset in range(61)],
        )

        state = rate_of_change_state(bars, 60)

        self.assertEqual(GREEN, state.state)
        self.assertEqual([10, 20, 60], state.details["windows"])
        self.assertAlmostEqual(
            (70.0 / 50.0 - 1.0) * 100.0,
            state.details["returns_pct"]["20"],
            places=4,
        )
        self.assertEqual(state.details["returns_pct"]["20"], state.value)

    def test_rate_of_change_distinguishes_negative_and_mixed_windows(self) -> None:
        negative = daily_bars(
            "AAA",
            [100.0 - offset for offset in range(61)],
        )
        mixed_closes = [10.0] * 61
        mixed_closes[0] = 8.0
        mixed_closes[40] = 12.0
        mixed_closes[50] = 9.0
        mixed_closes[60] = 10.0
        mixed = daily_bars("AAA", mixed_closes)

        self.assertEqual(RED, rate_of_change_state(negative, 60).state)
        self.assertEqual(
            "YELLOW",
            rate_of_change_state(mixed, 60).state,
        )

    def test_accumulation_distribution_tracks_positive_and_negative_flow(self) -> None:
        positive = [
            daily_bar(
                "AAA",
                offset,
                close=10.9 + offset * 0.1,
                high=11.0 + offset * 0.1,
                low=10.0 + offset * 0.1,
                volume=100,
            )
            for offset in range(55)
        ]
        negative = [
            daily_bar(
                "AAA",
                offset,
                close=10.1 + offset * 0.1,
                high=11.0 + offset * 0.1,
                low=10.0 + offset * 0.1,
                volume=100,
            )
            for offset in range(55)
        ]
        neutral = daily_bars("AAA", [10.0] * 55, volume=100)

        positive_state = accumulation_distribution_state(positive, 54)
        negative_state = accumulation_distribution_state(negative, 54)
        neutral_state = accumulation_distribution_state(neutral, 54)

        self.assertEqual(GREEN, positive_state.state)
        self.assertGreater(float(positive_state.details["delta"]), 0.0)
        self.assertEqual(RED, negative_state.state)
        self.assertLess(float(negative_state.details["delta"]), 0.0)
        self.assertEqual("YELLOW", neutral_state.state)
        self.assertEqual(0.0, neutral_state.details["delta"])

    def test_up_down_volume_uses_both_10_and_20_bar_windows(self) -> None:
        bars = [
            daily_bar(
                "AAA",
                0,
                close=10.0,
                high=10.0,
                low=10.0,
                volume=100,
            )
        ]
        close = 10.0
        for offset in range(1, 25):
            advancing = offset % 2 == 1
            close += 1.0 if advancing else -0.5
            volume = 200 if advancing else 50
            bars.append(
                daily_bar(
                    "AAA",
                    offset,
                    close=close,
                    high=close,
                    low=close,
                    volume=volume,
                )
            )

        state = up_down_volume_state(bars, 24)

        self.assertEqual(GREEN, state.state)
        self.assertEqual([10, 20], state.details["windows"])
        self.assertEqual(4.0, state.details["totals"]["10"]["ratio"])
        self.assertEqual(4.0, state.details["totals"]["20"]["ratio"])

    def test_up_down_volume_reports_no_directional_volume_without_division(self) -> None:
        bars = daily_bars("AAA", [10.0] * 21, volume=100)

        state = up_down_volume_state(bars, 20)

        self.assertEqual("YELLOW", state.state)
        self.assertEqual("NO_DIRECTIONAL_VOLUME", state.value)
        self.assertIsNone(state.details["totals"]["20"]["ratio"])

    def test_wave2_indicators_mark_missing_history_or_volume_honestly(self) -> None:
        short = daily_bars("AAA", [10.0] * 10)
        missing_volume = daily_bars(
            "AAA",
            [10.0 + offset * 0.1 for offset in range(55)],
        )
        missing_volume[-1] = replace(missing_volume[-1], volume=None)

        for state in (
            rsi_regime_state(short, 9),
            macd_momentum_state(short, 9),
            ppo_momentum_state(short, 9),
            obv_new_high_state(short, 9),
            money_flow_index_state(short, 9),
            chaikin_money_flow_state(short, 9),
            rate_of_change_state(short, 9),
            accumulation_distribution_state(short, 9),
            up_down_volume_state(short, 9),
            obv_new_high_state(missing_volume, 54),
            money_flow_index_state(missing_volume, 54),
            chaikin_money_flow_state(missing_volume, 54),
            accumulation_distribution_state(missing_volume, 54),
            up_down_volume_state(missing_volume, 54),
        ):
            with self.subTest(indicator=state.name):
                self.assertEqual(INSUFFICIENT_DATA, state.state)

    def test_wave2_indicators_do_not_read_future_bars_or_mutate_sources(self) -> None:
        bars = daily_bars(
            "AAA",
            [
                10.0 + (offset % 3) * 0.1 + offset * 0.01
                for offset in range(70)
            ],
            volume=100,
        )
        before_hash = fingerprint_bars(bars)
        states_before = [
            asdict(state)
            for state in (
                rsi_regime_state(bars, 61),
                macd_momentum_state(bars, 61),
                ppo_momentum_state(bars, 61),
                rate_of_change_state(bars, 61),
                obv_new_high_state(bars, 61),
                money_flow_index_state(bars, 61),
                chaikin_money_flow_state(bars, 61),
                accumulation_distribution_state(bars, 61),
                up_down_volume_state(bars, 61),
            )
        ]
        after_evaluation_hash = fingerprint_bars(bars)
        bars[69] = replace(
            bars[69],
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=10000,
        )
        states_after = [
            asdict(state)
            for state in (
                rsi_regime_state(bars, 61),
                macd_momentum_state(bars, 61),
                ppo_momentum_state(bars, 61),
                rate_of_change_state(bars, 61),
                obv_new_high_state(bars, 61),
                money_flow_index_state(bars, 61),
                chaikin_money_flow_state(bars, 61),
                accumulation_distribution_state(bars, 61),
                up_down_volume_state(bars, 61),
            )
        ]

        self.assertEqual(states_before, states_after)
        self.assertEqual(before_hash, after_evaluation_hash)
        self.assertNotEqual(before_hash, fingerprint_bars(bars))

    def test_redundant_momentum_checks_count_as_one_family(self) -> None:
        bars = daily_bars(
            "AAA",
            [
                10.0 + (offset % 3) * 0.1 + offset * 0.01
                for offset in range(70)
            ],
            volume=100,
        )

        summary = evaluate_wave1_confluence(symbol="AAA", bars=bars)
        momentum_indicators = [
            state
            for state in summary.indicator_states
            if state.family == FAMILY_MOMENTUM
        ]

        self.assertEqual(4, len(momentum_indicators))
        self.assertIn(
            "rate_of_change",
            {state.name for state in momentum_indicators},
        )
        self.assertIn(FAMILY_MOMENTUM, summary.family_states)
        self.assertLessEqual(summary.independent_total_families, 6)

    def test_redundant_volume_checks_count_as_one_family(self) -> None:
        bars = [
            daily_bar(
                "AAA",
                offset,
                close=10.9 + offset * 0.1,
                high=11.0 + offset * 0.1,
                low=10.0 + offset * 0.1,
                volume=100 + offset,
            )
            for offset in range(70)
        ]

        summary = evaluate_wave1_confluence(symbol="AAA", bars=bars)
        volume_indicators = [
            state
            for state in summary.indicator_states
            if state.family == FAMILY_VOLUME
        ]

        self.assertEqual(6, len(volume_indicators))
        self.assertIn(
            "accumulation_distribution_trend",
            {state.name for state in volume_indicators},
        )
        self.assertIn(
            "up_down_volume",
            {state.name for state in volume_indicators},
        )
        self.assertLessEqual(summary.independent_total_families, 6)

    def test_redundant_sma_and_relative_strength_checks_stay_family_capped(self) -> None:
        stock = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(220)],
        )
        benchmark = daily_bars("QQQ", [100.0] * 220)

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=stock,
            benchmark_bars=benchmark,
        )
        trend_names = {
            state.name
            for state in summary.indicator_states
            if state.family == FAMILY_TREND
        }
        relative_names = {
            state.name
            for state in summary.indicator_states
            if state.family == FAMILY_RELATIVE_STRENGTH
        }

        self.assertIn("sma_position", trend_names)
        self.assertIn("supertrend", trend_names)
        self.assertEqual(
            {
                "relative_strength_vs_benchmark",
                "relative_strength_short_slope",
                "relative_strength_long_slope",
                "relative_strength_new_high",
            },
            relative_names,
        )
        self.assertLessEqual(summary.independent_total_families, 6)

    def test_green_plus_yellow_family_is_confirming_but_red_conflict_is_not(self) -> None:
        green = technical_confluence.indicator(
            "green",
            FAMILY_MOMENTUM,
            GREEN,
            "confirmation signal",
            1.0,
            "green",
        )
        yellow = technical_confluence.indicator(
            "yellow",
            FAMILY_MOMENTUM,
            "YELLOW",
            "confirmation signal",
            0.0,
            "yellow",
        )
        red = technical_confluence.indicator(
            "red",
            FAMILY_MOMENTUM,
            RED,
            "confirmation signal",
            -1.0,
            "red",
        )

        confirming = technical_confluence.summarize_signal_family(
            FAMILY_MOMENTUM,
            [green, yellow],
        )
        conflicted = technical_confluence.summarize_signal_family(
            FAMILY_MOMENTUM,
            [green, red],
        )

        self.assertEqual(GREEN, confirming.state)
        self.assertEqual("YELLOW", conflicted.state)

    def test_relative_strength_outperforms_benchmark(self) -> None:
        stock = daily_bars("AAA", [10.0] * 20 + [12.0])
        benchmark = daily_bars("QQQ", [100.0] * 20 + [105.0])

        state = relative_strength_state(stock, benchmark, 20)

        self.assertEqual(GREEN, state.state)
        self.assertEqual(15.0, state.value)

    def test_relative_strength_slopes_and_new_high_use_aligned_ratios(self) -> None:
        stock = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(70)],
        )
        benchmark = daily_bars("QQQ", [100.0] * 70)

        short = relative_strength_short_slope_state(
            stock,
            benchmark,
            69,
        )
        long = relative_strength_long_slope_state(
            stock,
            benchmark,
            69,
        )
        new_high = relative_strength_new_high_state(
            stock,
            benchmark,
            69,
        )

        self.assertEqual(GREEN, short.state)
        self.assertEqual(20, short.details["window"])
        self.assertEqual(25, short.details["aligned_bars"])
        self.assertEqual(GREEN, long.state)
        self.assertEqual(60, long.details["window"])
        self.assertEqual(65, long.details["aligned_bars"])
        self.assertEqual(GREEN, new_high.state)
        self.assertEqual(
            {"20": True, "50": True, "60": True},
            new_high.details["new_highs"],
        )

    def test_relative_strength_partial_history_keeps_short_evidence_only(self) -> None:
        stock = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(25)],
        )
        benchmark = daily_bars("QQQ", [100.0] * 25)

        short = relative_strength_short_slope_state(
            stock,
            benchmark,
            24,
        )
        long = relative_strength_long_slope_state(
            stock,
            benchmark,
            24,
        )
        new_high = relative_strength_new_high_state(
            stock,
            benchmark,
            24,
        )

        self.assertEqual(GREEN, short.state)
        self.assertEqual(INSUFFICIENT_DATA, long.state)
        self.assertEqual(GREEN, new_high.state)
        self.assertEqual(
            {"20": True, "50": None, "60": None},
            new_high.details["new_highs"],
        )

    def test_relative_strength_alignment_gap_fails_closed(self) -> None:
        stock = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(30)],
        )
        benchmark = daily_bars("QQQ", [100.0] * 30)
        benchmark.pop(15)

        self.assertEqual(
            INSUFFICIENT_DATA,
            relative_strength_short_slope_state(
                stock,
                benchmark,
                29,
            ).state,
        )
        self.assertEqual(
            INSUFFICIENT_DATA,
            relative_strength_new_high_state(
                stock,
                benchmark,
                29,
            ).state,
        )

    def test_sma_and_relative_strength_ignore_future_bars_without_mutation(self) -> None:
        stock = daily_bars(
            "AAA",
            [10.0 + offset * 0.2 for offset in range(220)],
        )
        benchmark = daily_bars("QQQ", [100.0] * 220)
        stock_before = fingerprint_bars(stock)
        benchmark_before = fingerprint_bars(benchmark)
        states_before = [
            asdict(sma_position_state(stock, 69)),
            asdict(
                relative_strength_short_slope_state(
                    stock,
                    benchmark,
                    69,
                )
            ),
            asdict(
                relative_strength_long_slope_state(
                    stock,
                    benchmark,
                    69,
                )
            ),
            asdict(
                relative_strength_new_high_state(
                    stock,
                    benchmark,
                    69,
                )
            ),
        ]
        self.assertEqual(stock_before, fingerprint_bars(stock))
        self.assertEqual(benchmark_before, fingerprint_bars(benchmark))
        stock[219] = replace(
            stock[219],
            open=500.0,
            high=501.0,
            low=499.0,
            close=500.0,
        )
        benchmark[219] = replace(
            benchmark[219],
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
        )
        states_after = [
            asdict(sma_position_state(stock, 69)),
            asdict(
                relative_strength_short_slope_state(
                    stock,
                    benchmark,
                    69,
                )
            ),
            asdict(
                relative_strength_long_slope_state(
                    stock,
                    benchmark,
                    69,
                )
            ),
            asdict(
                relative_strength_new_high_state(
                    stock,
                    benchmark,
                    69,
                )
            ),
        ]

        self.assertEqual(states_before, states_after)
        self.assertNotEqual(stock_before, fingerprint_bars(stock))
        self.assertNotEqual(benchmark_before, fingerprint_bars(benchmark))

    def test_relative_strength_unavailable_without_benchmark(self) -> None:
        stock = daily_bars("AAA", [10.0] * 21)

        state = relative_strength_state(stock, [], 20)

        self.assertEqual("UNAVAILABLE", state.state)
        self.assertEqual("UNAVAILABLE", state.data_sufficiency)

    def test_relative_strength_rejects_nonpositive_starting_price(self) -> None:
        stock = daily_bars("AAA", [0.0] + [10.0] * 20)
        benchmark = daily_bars("QQQ", [100.0] * 21)

        state = relative_strength_state(stock, benchmark, 20)

        self.assertEqual(INSUFFICIENT_DATA, state.state)
        self.assertIn("must be positive", state.reason)

    def test_anchored_vwap_marks_price_above_anchor_green(self) -> None:
        bars = [
            daily_bar("AAA", 0, close=10.0, high=10.2, low=9.8, volume=100),
            daily_bar("AAA", 1, close=11.0, high=11.2, low=10.8, volume=200),
        ]

        state = anchored_vwap_state(
            bars,
            1,
            options=TechnicalConfluenceOptions(
                anchored_vwap_anchor_index=0
            ),
        )

        self.assertEqual(GREEN, state.state)
        self.assertLess(float(state.value or 0), 11.0)
        self.assertEqual("2026-01-01", state.details["anchor_timestamp"])
        self.assertIn("2026-01-01", state.reason)

    def test_anchored_vwap_is_unavailable_without_explicit_anchor(self) -> None:
        state = anchored_vwap_state(
            daily_bars("AAA", [10.0, 11.0]),
            1,
        )

        self.assertEqual("UNAVAILABLE", state.state)
        self.assertIn("no anchor event", state.reason)

    def test_atr_extension_marks_caution_when_price_is_stretched(self) -> None:
        bars = [
            daily_bar("AAA", offset, close=10.0, high=10.2, low=9.8, volume=100)
            for offset in range(25)
        ]
        bars.append(daily_bar("AAA", 25, close=14.0, high=14.1, low=13.9, volume=100))

        state = atr_extension_risk_state(bars, 25, options=TechnicalConfluenceOptions(atr_extension_multiple=2.0))

        self.assertEqual(CAUTION, state.state)

    def test_failed_breakout_blocks_confluence_risk_family(self) -> None:
        bars = daily_bars("AAA", [10 + offset * 0.2 for offset in range(70)], volume=200)
        event = breakout_event("AAA", BREAKOUT_FAILED)

        summary = evaluate_wave1_confluence(symbol="AAA", bars=bars, breakout_events=[event])

        self.assertEqual(BLOCKED, summary.family_states["Overextension / Risk"].state)
        self.assertEqual(RED, summary.family_states[FAMILY_BREAKOUT].state)
        self.assertGreaterEqual(summary.major_red_flags, 1)

    def test_latest_breakout_context_replaces_older_failure(self) -> None:
        bars = daily_bars("AAA", [10 + offset * 0.2 for offset in range(70)], volume=200)
        older_failure = breakout_event(
            "AAA",
            BREAKOUT_FAILED,
            event_timestamp="2026-02-01",
        )
        latest_present = breakout_event(
            "AAA",
            BREAKOUT_PRESENT,
            event_timestamp="2026-03-01",
        )

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=bars,
            breakout_events=[older_failure, latest_present],
        )

        self.assertNotEqual(
            BLOCKED,
            summary.family_states["Overextension / Risk"].state,
        )
        self.assertEqual(
            GREEN,
            summary.family_states[FAMILY_BREAKOUT].state,
        )

    def test_future_failed_breakout_does_not_block_current_context(self) -> None:
        bars = daily_bars("AAA", [10 + offset * 0.2 for offset in range(70)], volume=200)
        present = breakout_event(
            "AAA",
            BREAKOUT_PRESENT,
            event_timestamp="2026-03-01",
        )
        future_failure = breakout_event(
            "AAA",
            BREAKOUT_FAILED,
            event_timestamp="2026-12-01",
        )

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=bars,
            breakout_events=[present, future_failure],
        )

        self.assertNotEqual(
            BLOCKED,
            summary.family_states["Overextension / Risk"].state,
        )
        self.assertEqual(
            GREEN,
            summary.family_states[FAMILY_BREAKOUT].state,
        )

    def test_offset_aware_breakout_context_is_compared_without_clock_error(self) -> None:
        bars = [
            replace(
                bar,
                timestamp=f"{bar.timestamp}T21:00:00+00:00",
            )
            for bar in daily_bars(
                "AAA",
                [10 + offset * 0.2 for offset in range(70)],
                volume=200,
            )
        ]
        future_failure = breakout_event(
            "AAA",
            BREAKOUT_FAILED,
            event_timestamp="2026-12-01T09:30:00-05:00",
        )

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=bars,
            breakout_events=[future_failure],
        )

        self.assertNotEqual(
            BLOCKED,
            summary.family_states["Overextension / Risk"].state,
        )

    def test_conflicting_latest_breakout_records_are_unavailable(self) -> None:
        events = [
            breakout_event(
                "AAA",
                BREAKOUT_PRESENT,
                event_timestamp="2026-03-01",
            ),
            breakout_event(
                "AAA",
                BREAKOUT_FAILED,
                event_timestamp="2026-03-01",
            ),
        ]

        state = technical_confluence.failed_breakout_state(
            symbol="AAA",
            breakout_events=events,
            as_of="2026-03-02",
        )

        self.assertEqual("UNAVAILABLE", state.state)
        self.assertIn("conflicting", state.reason)
        breakout_state = breakout_context_state(
            symbol="AAA",
            breakout_events=events,
            as_of="2026-03-02",
        )
        self.assertEqual("UNAVAILABLE", breakout_state.state)
        self.assertIn("conflicting", breakout_state.reason)

    def test_breakout_context_is_an_independent_green_family(self) -> None:
        bars = daily_bars(
            "AAA",
            [10 + offset * 0.2 for offset in range(70)],
            volume=200,
        )

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=bars,
            breakout_events=[breakout_event("AAA", BREAKOUT_PRESENT)],
        )

        state = next(
            item
            for item in summary.indicator_states
            if item.name == "breakout_context"
        )
        self.assertEqual(GREEN, state.state)
        self.assertEqual(FAMILY_BREAKOUT, state.family)
        self.assertEqual(GREEN, summary.family_states[FAMILY_BREAKOUT].state)

    def test_latest_breakout_failure_replaces_older_present_context(self) -> None:
        bars = daily_bars(
            "AAA",
            [10 + offset * 0.2 for offset in range(70)],
            volume=200,
        )
        events = [
            breakout_event(
                "AAA",
                BREAKOUT_PRESENT,
                event_timestamp="2026-02-01",
            ),
            breakout_event(
                "AAA",
                BREAKOUT_FAILED,
                event_timestamp="2026-03-01",
            ),
        ]

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=bars,
            breakout_events=events,
        )

        self.assertEqual(RED, summary.family_states[FAMILY_BREAKOUT].state)
        self.assertEqual(
            BLOCKED,
            summary.family_states["Overextension / Risk"].state,
        )

    def test_duplicate_present_breakout_types_count_as_one_family(self) -> None:
        bars = daily_bars(
            "AAA",
            [10 + offset * 0.2 for offset in range(70)],
            volume=200,
        )
        events = [
            breakout_event(
                "AAA",
                BREAKOUT_PRESENT,
                event_type="donchian_20_day_breakout",
            ),
            breakout_event(
                "AAA",
                BREAKOUT_PRESENT,
                event_type="bollinger_upper_band_breakout",
            ),
        ]

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=bars,
            breakout_events=events,
        )

        breakout_states = [
            item
            for item in summary.indicator_states
            if item.family == FAMILY_BREAKOUT
        ]
        self.assertEqual(1, len(breakout_states))
        self.assertEqual(GREEN, summary.family_states[FAMILY_BREAKOUT].state)
        self.assertEqual(6, summary.independent_total_families)

    def test_one_green_does_not_override_reds_in_same_family(self) -> None:
        states = [
            technical_confluence.indicator(
                "one",
                technical_confluence.FAMILY_TREND,
                GREEN,
                "primary signal",
                1.0,
                "green",
            ),
            technical_confluence.indicator(
                "two",
                technical_confluence.FAMILY_TREND,
                RED,
                "primary signal",
                0.0,
                "red",
            ),
        ]

        family = technical_confluence.summarize_signal_family(
            technical_confluence.FAMILY_TREND,
            states,
        )

        self.assertEqual("YELLOW", family.state)

    def test_missing_risk_data_is_not_reported_clear(self) -> None:
        states = [
            technical_confluence.indicator(
                "risk",
                technical_confluence.FAMILY_RISK,
                "UNAVAILABLE",
                "warning signal",
                None,
                "missing",
            )
        ]

        family = technical_confluence.summarize_risk_family(states)

        self.assertEqual("UNAVAILABLE", family.state)

    def test_partial_risk_data_is_not_reported_fully_clear(self) -> None:
        states = [
            technical_confluence.indicator(
                "available",
                technical_confluence.FAMILY_RISK,
                CLEAR,
                "warning signal",
                False,
                "clear",
            ),
            technical_confluence.indicator(
                "missing",
                technical_confluence.FAMILY_RISK,
                "UNAVAILABLE",
                "blocker / gate",
                None,
                "missing",
            ),
        ]

        family = technical_confluence.summarize_risk_family(states)

        self.assertEqual("PARTIAL", family.state)

    def test_wave1_summary_counts_independent_families(self) -> None:
        bars = [
            daily_bar(
                "AAA",
                offset,
                close=10.0 + offset * 0.01,
                high=10.5 + offset * 0.01,
                low=9.5 + offset * 0.01,
                volume=100,
            )
            for offset in range(60)
        ]
        bars.append(
            daily_bar(
                "AAA",
                60,
                close=12.2,
                high=12.3,
                low=12.0,
                volume=250,
            )
        )
        benchmark = daily_bars("QQQ", [100.0] * 61)
        event = breakout_event("AAA", BREAKOUT_PRESENT)
        options = TechnicalConfluenceOptions(
            atr_extension_multiple=10.0,
            anchored_vwap_anchor_index=0,
        )

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=bars,
            benchmark_bars=benchmark,
            breakout_events=[event],
            options=options,
        )

        self.assertTrue(summary.research_only)
        self.assertEqual(
            technical_confluence.MODERATE_CONFLUENCE,
            summary.conclusion,
        )
        self.assertEqual(
            "YELLOW",
            summary.family_states[
                technical_confluence.FAMILY_VOLATILITY
            ].state,
        )
        self.assertGreaterEqual(summary.independent_green_families, 3)
        self.assertEqual(CLEAR, summary.family_states["Overextension / Risk"].state)

    def test_raw_denominator_preserves_every_configured_check(self) -> None:
        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=daily_bars("AAA", [10.0] * 5),
        )

        self.assertEqual(10, summary.schema_version)
        self.assertEqual(
            len(summary.indicator_states),
            summary.raw_total_checks,
        )
        self.assertEqual(27, summary.raw_total_checks)
        self.assertEqual(
            summary.raw_total_checks,
            (
                summary.raw_available_checks
                + summary.raw_unavailable_checks
                + summary.raw_insufficient_data_checks
            ),
        )
        self.assertEqual(
            summary.raw_total_checks,
            sum(summary.raw_state_counts.values()),
        )
        self.assertEqual(6, summary.independent_total_families)
        self.assertEqual(
            summary.independent_total_families,
            (
                summary.independent_available_families
                + summary.independent_unavailable_families
                + summary.independent_insufficient_data_families
            ),
        )
        self.assertEqual(
            summary.raw_green_checks,
            summary.raw_state_counts.get(GREEN, 0),
        )
        self.assertGreater(
            (
                summary.raw_unavailable_checks
                + summary.raw_insufficient_data_checks
            ),
            0,
        )

    def test_raw_state_counts_match_explicit_state_fields(self) -> None:
        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=daily_bars(
                "AAA",
                [10.0 + offset * 0.2 for offset in range(70)],
            ),
        )
        expected = {
            GREEN: summary.raw_green_checks,
            "YELLOW": summary.raw_yellow_checks,
            RED: summary.raw_red_checks,
            CAUTION: summary.raw_caution_checks,
            BLOCKED: summary.raw_blocked_checks,
            CLEAR: summary.raw_clear_checks,
            "UNAVAILABLE": summary.raw_unavailable_checks,
            INSUFFICIENT_DATA: summary.raw_insufficient_data_checks,
        }

        for state, count in expected.items():
            self.assertEqual(
                count,
                summary.raw_state_counts.get(state, 0),
            )
        self.assertGreater(
            summary.raw_total_checks,
            summary.raw_available_checks,
        )

    def test_insufficient_data_is_explicit(self) -> None:
        bars = daily_bars("AAA", [10.0] * 5)

        summary = evaluate_wave1_confluence(symbol="AAA", bars=bars)

        self.assertEqual(INSUFFICIENT_DATA, summary.conclusion)
        self.assertEqual("FAIL", summary.family_states["Data Quality"].state)

    def test_invalid_options_fail_closed(self) -> None:
        invalid_options = (
            {"ema_fast_window": 0},
            {"ema_fast_window": 20, "ema_mid_window": 8},
            {"sma_short_window": 50, "sma_mid_window": 20},
            {"supertrend_atr_window": 0},
            {
                "supertrend_atr_window": 30,
                "supertrend_minimum_bars": 30,
            },
            {"supertrend_atr_multiple": float("nan")},
            {"adx_green_threshold": 10.0, "adx_yellow_threshold": 15.0},
            {"volume_confirmation_multiple": float("nan")},
            {"bollinger_bandwidth_percentile_window": 0},
            {"bollinger_bandwidth_squeeze_percentile": 0.0},
            {"bollinger_bandwidth_squeeze_percentile": 101.0},
            {"bollinger_bandwidth_squeeze_percentile": float("nan")},
            {"anchored_vwap_anchor_index": -1},
            {"rsi_window": 0},
            {"rsi_floor": 60.0, "rsi_reach": 60.0},
            {"rsi_reach": 101.0},
            {"macd_fast_window": 26, "macd_slow_window": 12},
            {"obv_short_window": 50, "obv_long_window": 20},
            {"mfi_window": 0},
            {"cmf_window": 0},
            {
                "relative_strength_window": 60,
                "relative_strength_mid_window": 50,
            },
            {"roc_short_window": 20, "roc_mid_window": 10},
            {
                "accumulation_distribution_minimum_bars": 20,
                "accumulation_distribution_slope_window": 20,
            },
            {
                "up_down_volume_short_window": 20,
                "up_down_volume_long_window": 10,
            },
            {"atr_expansion_baseline_window": 0},
            {"atr_expansion_multiple": float("nan")},
            {
                "average_daily_range_window": 25,
                "average_daily_range_minimum_bars": 25,
            },
            {
                "average_daily_range_expansion_multiple": 0.0,
            },
        )

        for values in invalid_options:
            with self.subTest(values=values):
                with self.assertRaises(TechnicalConfluenceError):
                    TechnicalConfluenceOptions(**values)

    def test_mixed_symbols_duplicate_timestamps_and_invalid_bars_fail_closed(self) -> None:
        valid = daily_bars("AAA", [10.0] * 60)
        invalid_sets = (
            valid + [daily_bar("BBB", 60, close=10.0, high=10.0, low=10.0)],
            valid + [replace(valid[-1])],
            valid
            + [
                replace(
                    valid[-1],
                    timestamp=f"{valid[-1].timestamp}T00:00:00",
                )
            ],
            valid[:-1] + [replace(valid[-1], high=9.0)],
            valid[:-1] + [replace(valid[-1], volume=-1)],
        )

        for bars in invalid_sets:
            with self.subTest(last_bar=bars[-1]):
                with self.assertRaises(TechnicalConfluenceError):
                    evaluate_wave1_confluence(symbol="AAA", bars=bars)

    def test_squeeze_release_requires_break_above_outer_upper_band(self) -> None:
        bars = [
            daily_bar("AAA", offset, close=10.0, high=11.0, low=9.0, volume=100)
            for offset in range(23)
        ]
        options = TechnicalConfluenceOptions()
        outer_upper = technical_confluence.prior_keltner_upper_confluence(
            bars,
            22,
            options,
        )
        inner_upper = technical_confluence.prior_bollinger_upper_confluence(
            bars,
            22,
            options,
        )
        assert outer_upper is not None and inner_upper is not None
        self.assertGreater(outer_upper, inner_upper)
        bars[22] = replace(
            bars[22],
            close=(outer_upper + inner_upper) / 2,
            high=(outer_upper + inner_upper) / 2,
            low=(outer_upper + inner_upper) / 2,
            open=(outer_upper + inner_upper) / 2,
        )

        state = squeeze_release_state(bars, 22, options=options)

        self.assertEqual("YELLOW", state.state)

    def test_module_stays_research_only_by_import_boundary(self) -> None:
        source = inspect.getsource(technical_confluence)

        forbidden_imports = [
            "from momentum_hunter.scoring",
            "import momentum_hunter.scoring",
            "from momentum_hunter.trade_planning",
            "import momentum_hunter.trade_planning",
            "from momentum_hunter.opportunity_alerts",
            "import momentum_hunter.opportunity_alerts",
            "from momentum_hunter.autonomy",
            "import momentum_hunter.autonomy",
        ]
        for forbidden in forbidden_imports:
            self.assertNotIn(forbidden, source)

    def test_report_payload_evaluates_symbols_and_uses_qqq_benchmark(self) -> None:
        bars = {
            "BBB": daily_bars("BBB", [20 + offset * 0.1 for offset in range(60)]),
            "QQQ": daily_bars("QQQ", [100 + offset * 0.05 for offset in range(60)]),
            "AAA": daily_bars("AAA", [10 + offset * 0.2 for offset in range(60)]),
        }

        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol=bars,
            breakout_events=[],
            source_paths={"daily_ohlc_path": "daily.json"},
        )

        self.assertTrue(payload["research_only"])
        self.assertFalse(payload["trade_recommendation"])
        self.assertEqual("QQQ", payload["benchmark_symbol"])
        self.assertEqual(["AAA", "BBB"], [row["symbol"] for row in payload["symbols"]])
        self.assertEqual(2, payload["summary"]["symbols_evaluated"])
        self.assertNotIn("BENCHMARK_BARS_UNAVAILABLE:QQQ", payload["warnings"])

    def test_report_payload_preserves_spy_benchmark_regime_identity(self) -> None:
        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-15T16:00:00-05:00",
            daily_bars_by_symbol={
                "AAA": daily_bars(
                    "AAA",
                    [10.0 + offset * 0.2 for offset in range(70)],
                ),
                "SPY": daily_bars(
                    "SPY",
                    [100.0 + offset * 0.2 for offset in range(70)],
                ),
            },
            breakout_events=[],
            source_paths={"daily_ohlc_path": "daily.json"},
            benchmark_symbol="SPY",
        )

        market_regime = next(
            indicator
            for indicator in payload["symbols"][0]["indicator_states"]
            if indicator["name"] == "benchmark_sma_regime"
        )

        self.assertEqual("SPY", payload["benchmark_symbol"])
        self.assertEqual(["AAA"], [row["symbol"] for row in payload["symbols"]])
        self.assertEqual("SPY", market_regime["details"]["benchmark_symbol"])
        self.assertEqual(GREEN, market_regime["state"])

    def test_report_payload_marks_event_symbol_without_daily_bars_unavailable(self) -> None:
        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol={},
            breakout_events=[breakout_event("AAA", BREAKOUT_PRESENT)],
            source_paths={},
        )

        self.assertEqual(
            [{"symbol": "AAA", "reason": "DAILY_BARS_UNAVAILABLE"}],
            payload["unavailable_symbols"],
        )
        self.assertEqual(0, payload["summary"]["symbols_evaluated"])

    def test_case_duplicate_symbol_groups_are_not_selected_by_input_order(self) -> None:
        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol={
                "AAA": daily_bars("AAA", [10.0] * 60),
                "aaa": daily_bars("AAA", [20.0] * 60),
            },
            breakout_events=[breakout_event("AAA", BREAKOUT_PRESENT)],
            source_paths={},
        )

        self.assertEqual([], payload["symbols"])
        self.assertEqual(
            [{"symbol": "AAA", "reason": "DAILY_BARS_UNAVAILABLE"}],
            payload["unavailable_symbols"],
        )
        self.assertIn("DUPLICATE_DAILY_BAR_GROUP:AAA", payload["warnings"])

    def test_report_payload_rejects_invalid_group_without_exposing_details(self) -> None:
        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol={
                "AAA": [daily_bar("AAA", 0, close=10.0, high=9.0, low=10.0)]
            },
            breakout_events=[],
            source_paths={},
        )

        self.assertEqual(
            [{"symbol": "AAA", "reason": "DAILY_BAR_INPUT_REJECTED"}],
            payload["unavailable_symbols"],
        )

    def test_invalid_benchmark_degrades_benchmark_derived_context_only(self) -> None:
        invalid_benchmark = daily_bars("QQQ", [100.0] * 60)
        invalid_benchmark[-1] = replace(
            invalid_benchmark[-1],
            high=90.0,
        )

        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol={
                "AAA": daily_bars("AAA", [10 + offset * 0.1 for offset in range(60)]),
                "QQQ": invalid_benchmark,
            },
            breakout_events=[],
            source_paths={},
        )

        self.assertEqual(1, payload["summary"]["symbols_evaluated"])
        states_by_name = {
            indicator["name"]: indicator["state"]
            for indicator in payload["symbols"][0]["indicator_states"]
        }
        self.assertEqual(
            "UNAVAILABLE",
            states_by_name["relative_strength_vs_benchmark"],
        )
        self.assertEqual(
            "UNAVAILABLE",
            states_by_name["benchmark_sma_regime"],
        )
        self.assertIn(
            "BENCHMARK_BAR_INPUT_REJECTED:QQQ",
            payload["warnings"],
        )

    def test_markdown_is_research_only_and_avoids_execution_language(self) -> None:
        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol={},
            breakout_events=[],
            source_paths={},
        )

        rendered = render_technical_confluence_markdown(payload)
        lowered = rendered.lower()

        self.assertIn("research-only evidence", lowered)
        self.assertNotIn("buy", lowered)
        self.assertNotIn("sell", lowered)
        self.assertNotIn("guaranteed edge", lowered)
        self.assertNotIn("strategy should change", lowered)

    def test_markdown_exposes_complete_raw_state_denominators(self) -> None:
        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol={
                "AAA": daily_bars(
                    "AAA",
                    [10.0 + offset * 0.2 for offset in range(70)],
                )
            },
            breakout_events=[],
            source_paths={},
        )
        rendered = render_technical_confluence_markdown(payload)
        row = payload["symbols"][0]
        missing = (
            row["raw_unavailable_checks"]
            + row["raw_insufficient_data_checks"]
        )

        self.assertEqual(10, payload["schema_version"])
        self.assertIn(
            "| Raw Green | Raw Yellow | Raw Red | Missing |",
            rendered,
        )
        self.assertIn(
            f"{row['raw_green_checks']} / {row['raw_total_checks']}",
            rendered,
        )
        self.assertIn(
            f"{missing} / {row['raw_total_checks']}",
            rendered,
        )
        self.assertGreater(
            row["raw_total_checks"],
            row["raw_available_checks"],
        )

    def test_invalid_report_identity_fails_closed(self) -> None:
        with self.assertRaises(TechnicalConfluenceError):
            build_technical_confluence_report_payload(
                generated_at="not-a-time",
                daily_bars_by_symbol={},
                breakout_events=[],
                source_paths={},
            )
        with self.assertRaises(TechnicalConfluenceError):
            evaluate_wave1_confluence(
                symbol="AAA|BAD",
                bars=daily_bars("AAA|BAD", [10.0] * 60),
            )

    def test_writer_refuses_to_overwrite_user_authored_target(self) -> None:
        payload = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol={},
            breakout_events=[],
            source_paths={},
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            target = output_dir / "technical-confluence-latest.json"
            original = "Steven's research notes\n"
            target.write_text(original, encoding="utf-8")

            with self.assertRaises(TechnicalConfluenceError):
                write_technical_confluence_reports(
                    payload,
                    output_dir=output_dir,
                )

            self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_writer_replaces_only_verified_generated_reports(self) -> None:
        first = build_technical_confluence_report_payload(
            generated_at="2026-03-01T16:00:00-05:00",
            daily_bars_by_symbol={},
            breakout_events=[],
            source_paths={},
        )
        second = build_technical_confluence_report_payload(
            generated_at="2026-03-02T16:00:00-05:00",
            daily_bars_by_symbol={},
            breakout_events=[],
            source_paths={},
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            write_technical_confluence_reports(first, output_dir=output_dir)
            paths = write_technical_confluence_reports(
                second,
                output_dir=output_dir,
            )

            persisted = json.loads(paths["json"].read_text(encoding="utf-8"))

        self.assertEqual(second["generated_at"], persisted["generated_at"])

    def test_study_groups_same_day_events_and_measures_close_outcomes(self) -> None:
        bars = daily_bars("AAA", [10.0] * 61 + [10.5, 11.0, 10.8, 11.2, 11.5, 11.4, 11.6, 11.7, 11.8, 12.0])
        benchmark = daily_bars(
            "QQQ",
            [100.0 + offset * 0.1 for offset in range(len(bars))],
        )
        bars[63] = replace(bars[63], low=9.8)
        event_date = bars[60].timestamp
        events = [
            breakout_event(
                "AAA",
                BREAKOUT_PRESENT,
                event_id="AAA-donchian",
                event_type="donchian_20_day_breakout",
                event_timestamp=event_date,
            ),
            breakout_event(
                "AAA",
                BREAKOUT_PRESENT,
                event_id="AAA-bollinger",
                event_type="bollinger_upper_band_breakout",
                event_timestamp=event_date,
            ),
        ]
        studies = study_breakout_events(
            events,
            daily_bars_by_symbol={"AAA": bars},
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol={"AAA": bars, "QQQ": benchmark},
            breakout_events=events,
            breakout_studies=studies,
            source_paths={"daily_ohlc_path": "daily.json"},
        )

        self.assertEqual(1, payload["summary"]["unique_symbol_date_rows"])
        row = payload["rows"][0]
        self.assertEqual(2, row["event_count"])
        self.assertEqual(["bollinger_upper_band_breakout", "donchian_20_day_breakout"], row["event_types"])
        self.assertEqual(5.0, row["forward_returns_pct"]["1d"])
        self.assertEqual(10.0, row["forward_returns_pct"]["2d"])
        self.assertEqual(15.0, row["forward_returns_pct"]["5d"])
        self.assertEqual(20.0, row["forward_returns_pct"]["10d"])
        self.assertEqual("QQQ", row["benchmark_symbol"])
        self.assertEqual(106.0, row["benchmark_start_price"])
        self.assertEqual(
            0.9434,
            row["benchmark_forward_returns_pct"]["10d"],
        )
        self.assertEqual(
            19.0566,
            row["benchmark_relative_forward_returns_pct"]["10d"],
        )
        self.assertEqual(
            "COMPLETE",
            row["benchmark_relative_outcome_status"],
        )
        self.assertIsNone(row["benchmark_relative_reason"])
        self.assertEqual(20.0, row["max_favorable_excursion_pct"])
        self.assertEqual(-2.0, row["max_adverse_excursion_pct"])
        self.assertTrue(
            all(
                context["failed_back_below_breakout_level"]
                for context in row["breakout_contexts"]
            )
        )
        self.assertFalse(payload["summary"]["aggregate_outcomes_released"])
        self.assertEqual(29, payload["summary"]["completed_rows_to_minimum"])
        self.assertEqual(
            1,
            payload["summary"]["benchmark_relative_complete_rows"],
        )
        self.assertEqual(
            29,
            payload["summary"]["benchmark_relative_rows_to_minimum"],
        )
        confluence = row["confluence_summary"]
        raw_bucket = (
            f"{confluence['raw_green_checks']}/"
            f"{confluence['raw_total_checks']}"
        )
        family_bucket = (
            f"{confluence['independent_green_families']}/"
            f"{confluence['independent_total_families']}"
        )
        self.assertEqual(
            {},
            payload["aggregate_outcomes_by_raw_green_checks"],
        )
        self.assertEqual(
            {},
            payload[
                "aggregate_outcomes_by_independent_green_families"
            ],
        )
        self.assertEqual(
            [raw_bucket],
            payload["withheld_raw_green_check_buckets"],
        )
        self.assertEqual(
            [family_bucket],
            payload["withheld_independent_green_family_buckets"],
        )
        self.assertEqual(
            [SUPPORTIVE],
            payload["withheld_market_regime_buckets"],
        )
        self.assertFalse(
            any(
                warning.startswith("SMALL_MARKET_REGIME_BUCKETS_WITHHELD")
                for warning in payload["warnings"]
            )
        )
        self.assertEqual(
            TEMPORAL_STABILITY_WITHHELD,
            payload["temporal_stability"]["status"],
        )
        self.assertEqual(
            "MINIMUM_COMPLETE_SAMPLE_NOT_MET",
            payload["temporal_stability"]["reason"],
        )

    def test_study_does_not_substitute_missing_benchmark_target_date(
        self,
    ) -> None:
        bars = daily_bars(
            "AAA",
            [10.0] * 61
            + [10.1 + step * 0.1 for step in range(10)],
        )
        benchmark = daily_bars("QQQ", [100.0] * 70)
        event = breakout_event(
            "AAA",
            BREAKOUT_PRESENT,
            event_id="AAA-event",
            event_timestamp=bars[60].timestamp,
        )
        studies = study_breakout_events(
            [event],
            daily_bars_by_symbol={"AAA": bars},
        )
        benchmark_before = fingerprint_bars(benchmark)

        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol={
                "AAA": bars,
                "QQQ": benchmark,
            },
            breakout_events=[event],
            breakout_studies=studies,
            source_paths={},
        )

        row = payload["rows"][0]
        self.assertEqual("COMPLETE", row["outcome_status"])
        self.assertEqual(
            "PARTIAL",
            row["benchmark_relative_outcome_status"],
        )
        self.assertEqual(
            "BENCHMARK_TARGET_SESSION_UNAVAILABLE",
            row["benchmark_relative_reason"],
        )
        self.assertIsNotNone(
            row["benchmark_relative_forward_returns_pct"]["5d"]
        )
        self.assertIsNone(
            row["benchmark_relative_forward_returns_pct"]["10d"]
        )
        self.assertEqual(
            0,
            payload["summary"]["benchmark_relative_complete_rows"],
        )
        self.assertEqual(
            1,
            payload["summary"]["benchmark_relative_partial_rows"],
        )
        self.assertEqual(
            0,
            payload["summary"][
                "benchmark_relative_insufficient_rows"
            ],
        )
        self.assertEqual(benchmark_before, fingerprint_bars(benchmark))

    def test_study_separates_market_drift_from_excess_return(
        self,
    ) -> None:
        benchmark = daily_bars(
            "QQQ",
            [100.0] * 61
            + [101.0 + step for step in range(10)],
            volume=200,
        )
        groups: dict[str, list[TechnicalPriceBar]] = {
            "QQQ": benchmark,
        }
        events: list[BreakoutEvent] = []
        for offset in range(30):
            symbol = f"X{offset:02d}"
            groups[symbol] = daily_bars(
                symbol,
                [10.0] * 61
                + [10.1 + step * 0.1 for step in range(10)],
                volume=200,
            )
            events.append(
                breakout_event(
                    symbol,
                    BREAKOUT_PRESENT,
                    event_id=f"{symbol}-event",
                    event_timestamp=groups[symbol][60].timestamp,
                )
            )
        studies = study_breakout_events(
            events,
            daily_bars_by_symbol=groups,
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol=groups,
            breakout_events=events,
            breakout_studies=studies,
            source_paths={},
        )

        self.assertEqual(
            30,
            payload["summary"]["benchmark_relative_complete_rows"],
        )
        self.assertTrue(
            payload["summary"][
                "benchmark_relative_aggregates_released"
            ]
        )
        json.dumps(payload, allow_nan=False)
        aggregate = next(
            iter(
                payload[
                    "benchmark_relative_outcomes_by_conclusion"
                ].values()
            )
        )
        self.assertEqual(30, aggregate["sample_count"])
        self.assertEqual(
            0.0,
            aggregate["mean_excess_forward_returns_pct"]["10d"],
        )
        self.assertEqual(
            0.0,
            aggregate["median_excess_forward_returns_pct"]["10d"],
        )
        self.assertEqual(
            {"p25": 0.0, "p75": 0.0},
            aggregate[
                "interquartile_excess_forward_returns_pct"
            ]["10d"],
        )
        self.assertEqual(
            0.0,
            aggregate["positive_excess_return_rate_pct"]["10d"],
        )
        uncertainty = aggregate[
            "excess_forward_return_uncertainty"
        ]["10d"]
        self.assertEqual(
            {
                "lower": 0.0,
                "upper": 0.0,
            },
            uncertainty["mean_95pct_confidence_interval_pct"],
        )
        self.assertEqual(
            "INCLUDES_ZERO",
            uncertainty["mean_interval_relation_to_zero"],
        )
        self.assertEqual(
            0.0,
            uncertainty[
                "positive_rate_95pct_confidence_interval_pct"
            ]["lower"],
        )
        self.assertGreater(
            uncertainty[
                "positive_rate_95pct_confidence_interval_pct"
            ]["upper"],
            0.0,
        )
        self.assertEqual(
            30,
            next(
                iter(
                    payload[
                        "benchmark_relative_outcomes_by_raw_green_checks"
                    ].values()
                )
            )["sample_count"],
        )
        self.assertEqual(
            30,
            next(
                iter(
                    payload[
                        "benchmark_relative_outcomes_by_"
                        "independent_green_families"
                    ].values()
                )
            )["sample_count"],
        )
        self.assertEqual(
            30,
            payload["benchmark_relative_outcomes_by_market_regime"][
                MIXED
            ]["sample_count"],
        )
        rendered = render_technical_confluence_study_markdown(payload)
        self.assertIn("## Benchmark-Relative Outcomes", rendered)
        self.assertIn("Mean Excess 10d", rendered)
        self.assertIn("Positive Excess 10d", rendered)
        self.assertIn("Positive 10d 95% Interval", rendered)
        self.assertIn("Benchmark Outcome", rendered)

    def test_study_releases_equal_weighted_date_cluster_uncertainty(
        self,
    ) -> None:
        groups: dict[str, list[TechnicalPriceBar]] = {
            "QQQ": daily_bars(
                "QQQ",
                [100.0] * 80,
                volume=200,
            ),
        }
        events: list[BreakoutEvent] = []
        for date_offset in range(10):
            event_index = 60 + date_offset
            future = (
                [10.1 + step * 0.1 for step in range(10)]
                if date_offset < 5
                else [9.9 - step * 0.1 for step in range(10)]
            )
            for symbol_offset in range(3):
                symbol = f"D{date_offset}{symbol_offset}"
                groups[symbol] = daily_bars(
                    symbol,
                    [10.0] * (event_index + 1) + future,
                    volume=200,
                )
                events.append(
                    breakout_event(
                        symbol,
                        BREAKOUT_PRESENT,
                        event_id=f"{symbol}-event",
                        event_timestamp=groups[symbol][
                            event_index
                        ].timestamp,
                    )
                )
        studies = study_breakout_events(
            events,
            daily_bars_by_symbol=groups,
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol=groups,
            breakout_events=events,
            breakout_studies=studies,
            source_paths={},
        )
        json.dumps(payload, allow_nan=False)

        absolute_aggregate = next(
            iter(payload["aggregate_outcomes_by_conclusion"].values())
        )
        relative_aggregate = next(
            iter(
                payload[
                    "benchmark_relative_outcomes_by_conclusion"
                ].values()
            )
        )
        absolute_cluster = absolute_aggregate[
            "date_clustered_forward_return_uncertainty"
        ]["10d"]
        relative_cluster = relative_aggregate[
            "date_clustered_excess_forward_return_uncertainty"
        ]["10d"]
        for cluster in (absolute_cluster, relative_cluster):
            self.assertEqual(
                TEMPORAL_STABILITY_RELEASED,
                cluster["status"],
            )
            self.assertEqual(10, cluster["distinct_event_dates"])
            self.assertEqual(3, cluster["minimum_rows_per_date"])
            self.assertEqual(3, cluster["maximum_rows_per_date"])
            self.assertEqual(
                0.0,
                cluster["equal_weighted_date_mean_pct"],
            )
            self.assertEqual(
                "INCLUDES_ZERO",
                cluster["date_mean_uncertainty"][
                    "mean_interval_relation_to_zero"
                ],
            )
            self.assertEqual(
                5,
                cluster["date_mean_uncertainty"][
                    "positive_count"
                ],
            )
        rendered = render_technical_confluence_study_markdown(payload)
        self.assertIn("Date-Clustered Uncertainty", rendered)
        self.assertIn("Equal-Weighted Date Mean", rendered)
        self.assertIn("| 10 | RELEASED |", rendered)

    def test_study_confluence_uses_only_event_date_history(self) -> None:
        historical = daily_bars(
            "AAA",
            [10.0 + offset * 0.05 for offset in range(61)],
            volume=200,
        )
        event = breakout_event(
            "AAA",
            BREAKOUT_PRESENT,
            event_id="AAA-event",
            event_timestamp=historical[-1].timestamp,
        )
        rising = historical + daily_bars_from_index(
            "AAA",
            61,
            [13.5 + offset * 0.2 for offset in range(10)],
        )
        falling = historical + daily_bars_from_index(
            "AAA",
            61,
            [12.5 - offset * 0.2 for offset in range(10)],
        )

        rising_payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol={"AAA": rising},
            breakout_events=[event],
            breakout_studies=[],
            source_paths={},
        )
        falling_payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol={"AAA": falling},
            breakout_events=[event],
            breakout_studies=[],
            source_paths={},
        )

        self.assertEqual(
            rising_payload["rows"][0]["confluence_summary"],
            falling_payload["rows"][0]["confluence_summary"],
        )
        self.assertNotEqual(
            rising_payload["rows"][0]["forward_returns_pct"],
            falling_payload["rows"][0]["forward_returns_pct"],
        )

    def test_study_requires_consistent_hold_failure_evidence(self) -> None:
        bars = daily_bars(
            "AAA",
            [10.0] * 61 + [10.1 + step * 0.1 for step in range(10)],
        )
        event = breakout_event(
            "AAA",
            BREAKOUT_PRESENT,
            event_id="AAA-event",
            event_timestamp=bars[60].timestamp,
        )
        study = study_breakout_events(
            [event],
            daily_bars_by_symbol={"AAA": bars},
        )[0]
        invalid_study = replace(
            study,
            held_above_breakout_level=True,
            failed_back_below_breakout_level=True,
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol={"AAA": bars},
            breakout_events=[event],
            breakout_studies=[invalid_study],
            source_paths={},
        )

        self.assertEqual("PARTIAL", payload["rows"][0]["outcome_status"])
        self.assertEqual(
            "BREAKOUT_STUDY_EVIDENCE_INVALID",
            payload["rows"][0]["breakout_contexts"][0]["reason"],
        )
        self.assertEqual(0, payload["summary"]["complete_rows"])

    def test_study_releases_only_sufficient_conclusion_buckets(self) -> None:
        groups: dict[str, list[TechnicalPriceBar]] = {}
        events: list[BreakoutEvent] = []
        for offset in range(30):
            symbol = f"S{offset:02d}"
            future = (
                [10.1 + step * 0.1 for step in range(9)] + [110.0]
                if offset == 29
                else [10.1 + step * 0.1 for step in range(10)]
            )
            groups[symbol] = daily_bars(
                symbol,
                [10.0] * 61 + future,
                volume=200,
            )
            events.append(
                breakout_event(
                    symbol,
                    BREAKOUT_PRESENT,
                    event_id=f"{symbol}-event",
                    event_timestamp=groups[symbol][60].timestamp,
                )
            )
        studies = study_breakout_events(
            events,
            daily_bars_by_symbol=groups,
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol=groups,
            breakout_events=events,
            breakout_studies=studies,
            source_paths={},
        )

        self.assertEqual(30, payload["summary"]["complete_rows"])
        self.assertTrue(payload["summary"]["aggregate_outcomes_released"])
        self.assertEqual(
            INSUFFICIENT_DATA,
            payload["rows"][0][
                "benchmark_relative_outcome_status"
            ],
        )
        self.assertEqual(
            "BENCHMARK_BARS_UNAVAILABLE",
            payload["rows"][0]["benchmark_relative_reason"],
        )
        self.assertEqual(
            30,
            payload["summary"][
                "benchmark_relative_insufficient_rows"
            ],
        )
        self.assertEqual(
            "median_and_inclusive_interquartile_range",
            payload["outcome_methodology"]["distribution_statistics"],
        )
        json.dumps(payload, allow_nan=False)
        self.assertEqual(1, len(payload["aggregate_outcomes_by_conclusion"]))
        aggregate = next(
            iter(payload["aggregate_outcomes_by_conclusion"].values())
        )
        self.assertEqual(30, aggregate["sample_count"])
        self.assertEqual(100.0, aggregate["positive_forward_return_rate_pct"]["10d"])
        self.assertEqual(43.0, aggregate["mean_forward_returns_pct"]["10d"])
        self.assertEqual(10.0, aggregate["median_forward_returns_pct"]["10d"])
        self.assertEqual(
            {"p25": 10.0, "p75": 10.0},
            aggregate["interquartile_forward_returns_pct"]["10d"],
        )
        uncertainty = aggregate[
            "forward_return_uncertainty"
        ]["10d"]
        self.assertGreater(
            uncertainty["sample_standard_deviation_pct"],
            0.0,
        )
        self.assertLess(
            uncertainty["mean_95pct_confidence_interval_pct"][
                "lower"
            ],
            0.0,
        )
        self.assertGreater(
            uncertainty["mean_95pct_confidence_interval_pct"][
                "upper"
            ],
            0.0,
        )
        self.assertEqual(
            "INCLUDES_ZERO",
            uncertainty["mean_interval_relation_to_zero"],
        )
        self.assertLess(
            uncertainty[
                "positive_rate_95pct_confidence_interval_pct"
            ]["lower"],
            100.0,
        )
        self.assertEqual(
            "normal_mean_95pct_and_wilson_positive_rate_95pct",
            payload["outcome_methodology"]["uncertainty_intervals"],
        )
        clustered = aggregate[
            "date_clustered_forward_return_uncertainty"
        ]["10d"]
        self.assertEqual(
            TEMPORAL_STABILITY_WITHHELD,
            clustered["status"],
        )
        self.assertEqual(1, clustered["distinct_event_dates"])
        self.assertEqual(
            "MINIMUM_DISTINCT_EVENT_DATES_NOT_MET",
            clustered["reason"],
        )
        self.assertIsNone(clustered["date_mean_uncertainty"])
        self.assertEqual(
            10,
            payload["outcome_methodology"][
                "date_clustered_minimum_distinct_event_dates"
            ],
        )
        self.assertEqual(
            43.0,
            aggregate["mean_max_favorable_excursion_pct"],
        )
        self.assertEqual(
            10.0,
            aggregate["median_max_favorable_excursion_pct"],
        )
        self.assertEqual(
            {"p25": 10.0, "p75": 10.0},
            aggregate["interquartile_max_favorable_excursion_pct"],
        )
        self.assertEqual(
            1.0,
            aggregate["median_max_adverse_excursion_pct"],
        )
        self.assertEqual(
            {"p25": 1.0, "p75": 1.0},
            aggregate["interquartile_max_adverse_excursion_pct"],
        )
        raw_aggregates = payload[
            "aggregate_outcomes_by_raw_green_checks"
        ]
        family_aggregates = payload[
            "aggregate_outcomes_by_independent_green_families"
        ]
        self.assertEqual(1, len(raw_aggregates))
        self.assertEqual(1, len(family_aggregates))
        self.assertEqual(
            30,
            next(iter(raw_aggregates.values()))["sample_count"],
        )
        self.assertEqual(
            aggregate["median_forward_returns_pct"],
            next(iter(raw_aggregates.values()))[
                "median_forward_returns_pct"
            ],
        )
        self.assertEqual(
            aggregate["interquartile_forward_returns_pct"],
            next(iter(raw_aggregates.values()))[
                "interquartile_forward_returns_pct"
            ],
        )
        self.assertEqual(
            30,
            next(iter(family_aggregates.values()))["sample_count"],
        )
        self.assertEqual(
            0,
            payload["summary"]["market_regime_eligible_rows"],
        )
        self.assertEqual(
            30,
            payload["summary"]["market_regime_unavailable_rows"],
        )
        self.assertEqual(
            {},
            payload["aggregate_outcomes_by_market_regime"],
        )
        self.assertIn(
            "MARKET_REGIME_AGGREGATES_WITHHELD_MINIMUM_SAMPLE",
            payload["warnings"],
        )
        self.assertEqual(
            TEMPORAL_STABILITY_WITHHELD,
            payload["temporal_stability"]["status"],
        )
        self.assertEqual(
            "INSUFFICIENT_DISTINCT_EVENT_DATES",
            payload["temporal_stability"]["reason"],
        )
        self.assertIn(
            (
                "TEMPORAL_STABILITY_WITHHELD:"
                "INSUFFICIENT_DISTINCT_EVENT_DATES"
            ),
            payload["warnings"],
        )
        rendered = render_technical_confluence_study_markdown(payload)
        self.assertIn("#### Median And Interquartile Range", rendered)
        self.assertIn("#### Statistical Uncertainty", rendered)
        self.assertIn("##### Date-Clustered Uncertainty", rendered)
        self.assertIn("Mean 10d 95% Interval", rendered)
        self.assertIn("10d IQR", rendered)
        self.assertIn("10.0000% to 10.0000%", rendered)
        self.assertIn(
            "CONFIDENCE_INTERVALS_ARE_DESCRIPTIVE_NOT_EDGE_PROOF",
            rendered,
        )
        self.assertIn(
            "ROW_LEVEL_CONFIDENCE_INTERVALS_ARE_NOT_CLUSTER_ROBUST",
            rendered,
        )
        self.assertIn(
            "DATE_CLUSTER_INTERVALS_REMAIN_DESCRIPTIVE_NOT_EDGE_PROOF",
            rendered,
        )
        self.assertFalse(
            payload["outcome_methodology"][
                "row_level_uncertainty_cluster_robust"
            ]
        )

    def test_study_stratifies_outcomes_by_exact_confluence_counts(self) -> None:
        groups: dict[str, list[TechnicalPriceBar]] = {}
        events: list[BreakoutEvent] = []
        for offset in range(30):
            symbol = f"C{offset:02d}"
            history = (
                [10.0 + step * 0.1 for step in range(61)]
                if offset < 9
                else [10.0] * 61
            )
            groups[symbol] = daily_bars(
                symbol,
                history
                + [
                    history[-1] + 0.1 + step * 0.1
                    for step in range(10)
                ],
                volume=200,
            )
            events.append(
                breakout_event(
                    symbol,
                    BREAKOUT_PRESENT,
                    event_id=f"{symbol}-event",
                    event_timestamp=groups[symbol][60].timestamp,
                )
            )
        studies = study_breakout_events(
            events,
            daily_bars_by_symbol=groups,
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol=groups,
            breakout_events=events,
            breakout_studies=studies,
            source_paths={},
        )

        expected_raw: dict[str, int] = {}
        expected_families: dict[str, int] = {}
        for row in payload["rows"]:
            summary = row["confluence_summary"]
            raw_bucket = (
                f"{summary['raw_green_checks']}/"
                f"{summary['raw_total_checks']}"
            )
            family_bucket = (
                f"{summary['independent_green_families']}/"
                f"{summary['independent_total_families']}"
            )
            expected_raw[raw_bucket] = expected_raw.get(raw_bucket, 0) + 1
            expected_families[family_bucket] = (
                expected_families.get(family_bucket, 0) + 1
            )

        self.assertEqual(2, len(expected_raw))
        self.assertEqual(2, len(expected_families))
        self.assertEqual(
            {9, 21},
            set(expected_raw.values()),
        )
        self.assertEqual(
            {9, 21},
            set(expected_families.values()),
        )
        released_raw = {
            key: count
            for key, count in expected_raw.items()
            if count >= 10
        }
        released_families = {
            key: count
            for key, count in expected_families.items()
            if count >= 10
        }
        self.assertEqual(
            released_raw,
            {
                key: aggregate["sample_count"]
                for key, aggregate in payload[
                    "aggregate_outcomes_by_raw_green_checks"
                ].items()
            },
        )
        self.assertEqual(
            released_families,
            {
                key: aggregate["sample_count"]
                for key, aggregate in payload[
                    "aggregate_outcomes_by_independent_green_families"
                ].items()
            },
        )
        self.assertEqual(
            sorted(
                key
                for key, count in expected_raw.items()
                if count < 10
            ),
            payload["withheld_raw_green_check_buckets"],
        )
        self.assertEqual(
            sorted(
                key
                for key, count in expected_families.items()
                if count < 10
            ),
            payload["withheld_independent_green_family_buckets"],
        )
        rendered = render_technical_confluence_study_markdown(payload)
        self.assertIn("### By Raw Green Checks", rendered)
        self.assertIn("### By Independent Green Families", rendered)
        for bucket in released_raw:
            self.assertIn(f"| {bucket} |", rendered)
        for bucket in released_families:
            self.assertIn(f"| {bucket} |", rendered)
        self.assertIn(
            "SMALL_RAW_GREEN_CHECK_BUCKETS_WITHHELD:",
            rendered,
        )
        self.assertIn(
            "SMALL_INDEPENDENT_GREEN_FAMILY_BUCKETS_WITHHELD:",
            rendered,
        )
        monotonicity = payload["confluence_monotonicity"]
        self.assertEqual(
            technical_confluence.MONOTONICITY_WITHHELD,
            monotonicity["independent_green_families"][
                "absolute_return"
            ]["status"],
        )
        self.assertEqual(
            "MINIMUM_RELEASED_ORDERED_BUCKETS_NOT_MET",
            monotonicity["independent_green_families"][
                "absolute_return"
            ]["reason"],
        )
        self.assertIn("## Confluence Monotonicity", rendered)
        self.assertIn(
            "| Independent Green Families | Absolute Return | WITHHELD |",
            rendered,
        )

    def test_monotonicity_releases_increasing_same_denominator_buckets(
        self,
    ) -> None:
        aggregates = monotonicity_aggregates(
            {
                "2/7": (-1.0, -0.5),
                "3/7": (1.0, 1.5),
                "4/7": (3.0, 3.5),
            },
            cluster_status=TEMPORAL_STABILITY_RELEASED,
        )
        before = json.dumps(aggregates, sort_keys=True, allow_nan=False)

        result = technical_confluence._build_count_monotonicity_study(
            aggregates
        )

        self.assertEqual(
            technical_confluence.MONOTONICITY_RELEASED,
            result["status"],
        )
        self.assertIsNone(result["reason"])
        self.assertEqual(7, result["denominator"])
        self.assertEqual(
            ["2/7", "3/7", "4/7"],
            [row["bucket"] for row in result["ordered_buckets"]],
        )
        self.assertEqual(
            [-1.0, 1.0, 3.0],
            result["median_10d_pct_sequence"],
        )
        self.assertEqual(
            "STRICTLY_INCREASING",
            result["median_direction"],
        )
        self.assertEqual(
            "STRICTLY_INCREASING",
            result["mean_direction"],
        )
        self.assertEqual(
            1.0,
            result["median_spearman_rank_correlation"],
        )
        self.assertEqual(
            technical_confluence.MONOTONICITY_RELEASED,
            result["date_cluster_support_status"],
        )
        self.assertTrue(result["descriptive_only"])
        self.assertFalse(result["causal_relationship_proven"])
        self.assertFalse(result["production_behavior_changed"])
        self.assertEqual(
            "equal_weight_per_released_count_bucket",
            result["bucket_weighting"],
        )
        self.assertFalse(result["statistical_significance_tested"])
        self.assertFalse(result["confidence_interval_separation_tested"])
        self.assertEqual(
            before,
            json.dumps(aggregates, sort_keys=True, allow_nan=False),
        )
        json.dumps(result, allow_nan=False)

    def test_monotonicity_reports_mixed_direction_and_withheld_clusters(
        self,
    ) -> None:
        aggregates = monotonicity_aggregates(
            {
                "3/7": (3.0, 4.0),
                "4/7": (1.0, 2.0),
                "5/7": (2.0, 1.0),
            },
            cluster_status=TEMPORAL_STABILITY_WITHHELD,
        )

        result = technical_confluence._build_count_monotonicity_study(
            aggregates
        )

        self.assertEqual(
            technical_confluence.MONOTONICITY_RELEASED,
            result["status"],
        )
        self.assertEqual("MIXED", result["median_direction"])
        self.assertEqual("STRICTLY_DECREASING", result["mean_direction"])
        self.assertEqual(
            -0.5,
            result["median_spearman_rank_correlation"],
        )
        self.assertEqual(
            -1.0,
            result["mean_spearman_rank_correlation"],
        )
        self.assertEqual(
            technical_confluence.MONOTONICITY_WITHHELD,
            result["date_cluster_support_status"],
        )
        self.assertEqual(
            "ONE_OR_MORE_BUCKETS_LACK_DATE_CLUSTER_RELEASE",
            result["date_cluster_support_reason"],
        )
        tied = technical_confluence._build_count_monotonicity_study(
            monotonicity_aggregates(
                {
                    "2/7": (1.0, 1.0),
                    "3/7": (1.0, 1.0),
                    "4/7": (2.0, 1.0),
                }
            )
        )
        self.assertEqual("NON_DECREASING", tied["median_direction"])
        self.assertEqual(
            0.866,
            tied["median_spearman_rank_correlation"],
        )
        self.assertEqual("FLAT", tied["mean_direction"])
        self.assertIsNone(tied["mean_spearman_rank_correlation"])
        json.dumps(tied, allow_nan=False)

    def test_monotonicity_withholds_too_few_or_mixed_denominator_buckets(
        self,
    ) -> None:
        too_few = technical_confluence._build_count_monotonicity_study(
            monotonicity_aggregates(
                {
                    "3/7": (1.0, 1.0),
                    "4/7": (2.0, 2.0),
                }
            )
        )
        mixed_denominators = (
            technical_confluence._build_count_monotonicity_study(
                monotonicity_aggregates(
                    {
                        "2/7": (1.0, 1.0),
                        "3/7": (2.0, 2.0),
                        "4/8": (3.0, 3.0),
                    }
                )
            )
        )
        no_benchmark = technical_confluence._build_count_monotonicity_study(
            {},
            benchmark_relative=True,
            empty_reason="BENCHMARK_RELATIVE_AGGREGATES_UNAVAILABLE",
        )

        self.assertEqual(
            "MINIMUM_RELEASED_ORDERED_BUCKETS_NOT_MET",
            too_few["reason"],
        )
        self.assertEqual(
            "MIXED_BUCKET_DENOMINATORS",
            mixed_denominators["reason"],
        )
        self.assertEqual(
            "BENCHMARK_RELATIVE_AGGREGATES_UNAVAILABLE",
            no_benchmark["reason"],
        )
        self.assertEqual(
            technical_confluence.MONOTONICITY_WITHHELD,
            no_benchmark["status"],
        )

    def test_monotonicity_uses_benchmark_relative_outcomes(self) -> None:
        aggregates = monotonicity_aggregates(
            {
                "2/7": (-2.0, -1.5),
                "3/7": (0.0, 0.5),
                "4/7": (2.0, 2.5),
            },
            benchmark_relative=True,
            cluster_status=TEMPORAL_STABILITY_RELEASED,
        )

        result = technical_confluence._build_count_monotonicity_study(
            aggregates,
            benchmark_relative=True,
        )

        self.assertEqual(
            "BENCHMARK_RELATIVE_RETURN",
            result["outcome_basis"],
        )
        self.assertEqual(
            [-2.0, 0.0, 2.0],
            result["median_10d_pct_sequence"],
        )
        self.assertEqual(
            "STRICTLY_INCREASING",
            result["median_direction"],
        )
        self.assertEqual(
            1.0,
            result["median_spearman_rank_correlation"],
        )

    def test_study_stratifies_by_historical_market_regime(self) -> None:
        benchmark = daily_bars(
            "QQQ",
            [100.0 + step * 0.2 for step in range(250)]
            + [149.8 - step * 0.3 for step in range(250)],
            volume=200,
        )
        early_event_index = 219
        late_event_index = 449
        groups: dict[str, list[TechnicalPriceBar]] = {
            "QQQ": benchmark,
        }
        events: list[BreakoutEvent] = []
        for offset in range(30):
            symbol = f"R{offset:02d}"
            event_index = (
                early_event_index if offset < 9 else late_event_index
            )
            groups[symbol] = daily_bars(
                symbol,
                [10.0] * (event_index + 1)
                + [10.1 + step * 0.1 for step in range(10)],
                volume=200,
            )
            events.append(
                breakout_event(
                    symbol,
                    BREAKOUT_PRESENT,
                    event_id=f"{symbol}-event",
                    event_timestamp=groups[symbol][event_index].timestamp,
                )
            )
        studies = study_breakout_events(
            events,
            daily_bars_by_symbol=groups,
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-06-01T16:00:00-05:00",
            daily_bars_by_symbol=groups,
            breakout_events=events,
            breakout_studies=studies,
            source_paths={},
        )

        regime_counts: dict[str, int] = {}
        for row in payload["rows"]:
            regime = row["confluence_summary"]["family_states"][
                FAMILY_MARKET_REGIME
            ]["state"]
            regime_counts[regime] = regime_counts.get(regime, 0) + 1

        self.assertEqual(
            {
                SUPPORTIVE: 9,
                HOSTILE: 21,
            },
            regime_counts,
        )
        self.assertEqual(
            30,
            payload["summary"]["market_regime_eligible_rows"],
        )
        self.assertEqual(
            0,
            payload["summary"]["market_regime_unavailable_rows"],
        )
        self.assertEqual(
            {
                HOSTILE: 21,
            },
            {
                regime: aggregate["sample_count"]
                for regime, aggregate in payload[
                    "aggregate_outcomes_by_market_regime"
                ].items()
            },
        )
        self.assertEqual(
            [SUPPORTIVE],
            payload["withheld_market_regime_buckets"],
        )
        self.assertIn(
            "SMALL_MARKET_REGIME_BUCKETS_WITHHELD:SUPPORTIVE",
            payload["warnings"],
        )
        rendered = render_technical_confluence_study_markdown(payload)
        self.assertIn("### By Market Regime", rendered)
        self.assertIn("- Market-regime-classified samples: 30", rendered)
        self.assertIn("- Market-regime samples still required: 0", rendered)
        self.assertIn(f"| {HOSTILE} | 21 |", rendered)
        self.assertNotIn(f"| {SUPPORTIVE} | 9 |", rendered)
        self.assertEqual(
            TEMPORAL_STABILITY_WITHHELD,
            payload["temporal_stability"]["status"],
        )
        self.assertEqual(
            (
                "NO_VALID_DATE_BOUNDARY_WITH_MINIMUM_PERIOD_SAMPLES"
            ),
            payload["temporal_stability"]["reason"],
        )

    def test_study_releases_contiguous_temporal_stability_periods(self) -> None:
        groups: dict[str, list[TechnicalPriceBar]] = {
            "QQQ": daily_bars("QQQ", [100.0] * 101, volume=200),
        }
        events: list[BreakoutEvent] = []
        for offset in range(30):
            symbol = f"T{offset:02d}"
            event_index = 60 if offset < 15 else 90
            future = (
                [10.1 + step * 0.1 for step in range(10)]
                if offset < 15
                else [9.9 - step * 0.1 for step in range(10)]
            )
            groups[symbol] = daily_bars(
                symbol,
                [10.0] * (event_index + 1) + future,
                volume=200,
            )
            events.append(
                breakout_event(
                    symbol,
                    BREAKOUT_PRESENT,
                    event_id=f"{symbol}-event",
                    event_timestamp=groups[symbol][event_index].timestamp,
                )
            )
        studies = study_breakout_events(
            events,
            daily_bars_by_symbol=groups,
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-06-01T16:00:00-05:00",
            daily_bars_by_symbol=groups,
            breakout_events=events,
            breakout_studies=studies,
            source_paths={},
        )

        temporal = payload["temporal_stability"]
        early_date = groups["T00"][60].timestamp
        late_date = groups["T15"][90].timestamp
        self.assertEqual(TEMPORAL_STABILITY_RELEASED, temporal["status"])
        self.assertEqual(early_date, temporal["split_after_date"])
        self.assertEqual(2, temporal["distinct_event_dates"])
        self.assertEqual(
            {
                "start_date": early_date,
                "end_date": early_date,
                "sample_count": 15,
            },
            {
                key: temporal["periods"]["EARLIER"][key]
                for key in ("start_date", "end_date", "sample_count")
            },
        )
        self.assertEqual(
            {
                "start_date": late_date,
                "end_date": late_date,
                "sample_count": 15,
            },
            {
                key: temporal["periods"]["LATER"][key]
                for key in ("start_date", "end_date", "sample_count")
            },
        )
        self.assertEqual(
            10.0,
            temporal["periods"]["EARLIER"][
                "mean_forward_returns_pct"
            ]["10d"],
        )
        self.assertEqual(
            -10.0,
            temporal["periods"]["LATER"][
                "mean_forward_returns_pct"
            ]["10d"],
        )
        self.assertEqual(
            100.0,
            temporal["periods"]["EARLIER"][
                "positive_forward_return_rate_pct"
            ]["10d"],
        )
        self.assertEqual(
            0.0,
            temporal["periods"]["LATER"][
                "positive_forward_return_rate_pct"
            ]["10d"],
        )
        self.assertEqual(
            10.0,
            temporal["periods"]["EARLIER"][
                "median_forward_returns_pct"
            ]["10d"],
        )
        self.assertEqual(
            -10.0,
            temporal["periods"]["LATER"][
                "median_forward_returns_pct"
            ]["10d"],
        )
        self.assertEqual(
            {"p25": 10.0, "p75": 10.0},
            temporal["periods"]["EARLIER"][
                "interquartile_forward_returns_pct"
            ]["10d"],
        )
        self.assertEqual(
            {"p25": -10.0, "p75": -10.0},
            temporal["periods"]["LATER"][
                "interquartile_forward_returns_pct"
            ]["10d"],
        )
        relative_temporal = payload[
            "benchmark_relative_temporal_stability"
        ]
        self.assertEqual(
            TEMPORAL_STABILITY_RELEASED,
            relative_temporal["status"],
        )
        self.assertEqual(
            10.0,
            relative_temporal["periods"]["EARLIER"][
                "mean_excess_forward_returns_pct"
            ]["10d"],
        )
        self.assertEqual(
            -10.0,
            relative_temporal["periods"]["LATER"][
                "mean_excess_forward_returns_pct"
            ]["10d"],
        )
        self.assertEqual(
            "ABOVE_ZERO",
            temporal["periods"]["EARLIER"][
                "forward_return_uncertainty"
            ]["10d"]["mean_interval_relation_to_zero"],
        )
        self.assertEqual(
            "BELOW_ZERO",
            temporal["periods"]["LATER"][
                "forward_return_uncertainty"
            ]["10d"]["mean_interval_relation_to_zero"],
        )
        self.assertEqual(
            "ABOVE_ZERO",
            relative_temporal["periods"]["EARLIER"][
                "excess_forward_return_uncertainty"
            ]["10d"]["mean_interval_relation_to_zero"],
        )
        self.assertEqual(
            "BELOW_ZERO",
            relative_temporal["periods"]["LATER"][
                "excess_forward_return_uncertainty"
            ]["10d"]["mean_interval_relation_to_zero"],
        )
        self.assertEqual(
            TEMPORAL_STABILITY_WITHHELD,
            temporal["periods"]["EARLIER"][
                "date_clustered_forward_return_uncertainty"
            ]["10d"]["status"],
        )
        self.assertEqual(
            TEMPORAL_STABILITY_WITHHELD,
            relative_temporal["periods"]["LATER"][
                "date_clustered_excess_forward_return_uncertainty"
            ]["10d"]["status"],
        )
        rendered = render_technical_confluence_study_markdown(payload)
        self.assertIn("## Temporal Stability", rendered)
        self.assertIn("### Median And Interquartile Range", rendered)
        self.assertIn("### Statistical Uncertainty", rendered)
        self.assertIn(f"- Split after event date: {early_date}", rendered)
        self.assertIn(f"| EARLIER | {early_date} to {early_date} | 15 |", rendered)
        self.assertIn(f"| LATER | {late_date} to {late_date} | 15 |", rendered)

    def test_study_excludes_duplicate_event_ids_and_marks_missing_bars(self) -> None:
        duplicate = breakout_event(
            "AAA",
            BREAKOUT_PRESENT,
            event_id="duplicate",
            event_timestamp="2026-03-01",
        )
        missing = breakout_event(
            "BBB",
            BREAKOUT_PRESENT,
            event_id="missing-bars",
            event_timestamp="2026-03-01",
        )

        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol={},
            breakout_events=[duplicate, replace(duplicate), missing],
            breakout_studies=[],
            source_paths={},
        )

        self.assertEqual([], payload["rows"])
        self.assertIn("DUPLICATE_BREAKOUT_EVENT_IDS:1", payload["warnings"])
        self.assertEqual(
            [
                {
                    "symbol": "BBB",
                    "event_date": "2026-03-01",
                    "reason": "DAILY_BARS_UNAVAILABLE",
                }
            ],
            payload["unavailable_event_groups"],
        )

    def test_study_markdown_is_research_only_and_avoids_execution_language(self) -> None:
        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol={},
            breakout_events=[],
            breakout_studies=[],
            source_paths={},
        )

        rendered = render_technical_confluence_study_markdown(payload)
        lowered = rendered.lower()

        self.assertIn("research-only evidence", lowered)
        self.assertNotIn("buy", lowered)
        self.assertNotIn("sell", lowered)
        self.assertNotIn("guaranteed edge", lowered)
        self.assertNotIn("strategy should change", lowered)

    def test_study_writer_refuses_user_authored_target(self) -> None:
        payload = build_technical_confluence_study_payload(
            generated_at="2026-04-01T16:00:00-05:00",
            daily_bars_by_symbol={},
            breakout_events=[],
            breakout_studies=[],
            source_paths={},
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            target = output_dir / "technical-confluence-study-latest.json"
            original = "Steven's research notes\n"
            target.write_text(original, encoding="utf-8")

            with self.assertRaises(TechnicalConfluenceError):
                write_technical_confluence_study_reports(
                    payload,
                    output_dir=output_dir,
                )

            self.assertEqual(original, target.read_text(encoding="utf-8"))

    def test_study_writer_rejects_wrong_payload_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(TechnicalConfluenceError):
                write_technical_confluence_study_reports(
                    {
                        "artifact_type": "NOT_A_STUDY",
                        "research_only": True,
                        "generated_at": "2026-04-01T16:00:00-05:00",
                    },
                    output_dir=Path(temporary),
                )


def daily_bars(symbol: str, closes: list[float], *, volume: int = 100) -> list[TechnicalPriceBar]:
    return [
        daily_bar(symbol, offset, close=close, high=close, low=close, volume=volume)
        for offset, close in enumerate(closes)
    ]


def daily_bars_from_index(
    symbol: str,
    start_index: int,
    closes: list[float],
    *,
    volume: int = 100,
) -> list[TechnicalPriceBar]:
    return [
        daily_bar(
            symbol,
            start_index + offset,
            close=close,
            high=close,
            low=close,
            volume=volume,
        )
        for offset, close in enumerate(closes)
    ]


def daily_bar(
    symbol: str,
    offset: int,
    *,
    close: float,
    high: float,
    low: float,
    volume: int = 100,
) -> TechnicalPriceBar:
    day = datetime(2026, 1, 1) + timedelta(days=offset)
    return TechnicalPriceBar(
        symbol=symbol,
        timestamp=day.date().isoformat(),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source="test_daily",
    )


def breakout_event(
    symbol: str,
    status: str,
    *,
    event_id: str | None = None,
    event_type: str = "donchian_20_day_breakout",
    event_timestamp: str = "2026-03-01",
) -> BreakoutEvent:
    return BreakoutEvent(
        event_id=event_id or f"{symbol}-{status}",
        symbol=symbol,
        event_timestamp=event_timestamp,
        event_type=event_type,
        timeframe="daily",
        trigger_price=10.0,
        reference_label="prior_20_day_high",
        prior_high_band_or_moving_average_value=10.0,
        distance_above_trigger_pct=0.0,
        volume=100,
        relative_volume=2.0,
        market_regime="bull",
        source_data="test",
        data_sufficiency="Sufficient",
        quality_flag="HIGH",
        status=status,
        volume_confirmed=True,
    )


def fingerprint_bars(bars: list[TechnicalPriceBar]) -> str:
    digest = hashlib.sha256()
    for bar in bars:
        digest.update(repr(bar).encode("utf-8"))
    return digest.hexdigest()


def monotonicity_aggregates(
    bucket_values: dict[str, tuple[float, float]],
    *,
    benchmark_relative: bool = False,
    cluster_status: str = TEMPORAL_STABILITY_WITHHELD,
) -> dict[str, dict[str, object]]:
    mean_field = (
        "mean_excess_forward_returns_pct"
        if benchmark_relative
        else "mean_forward_returns_pct"
    )
    median_field = (
        "median_excess_forward_returns_pct"
        if benchmark_relative
        else "median_forward_returns_pct"
    )
    cluster_field = (
        "date_clustered_excess_forward_return_uncertainty"
        if benchmark_relative
        else "date_clustered_forward_return_uncertainty"
    )
    return {
        bucket: {
            "sample_count": 10,
            median_field: {"10d": median_value},
            mean_field: {"10d": mean_value},
            cluster_field: {
                "10d": {
                    "status": cluster_status,
                }
            },
        }
        for bucket, (median_value, mean_value) in bucket_values.items()
    }


if __name__ == "__main__":
    unittest.main()
