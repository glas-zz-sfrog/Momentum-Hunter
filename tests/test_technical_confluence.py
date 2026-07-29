from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
import unittest
from datetime import datetime, timedelta

from momentum_hunter import technical_confluence
from momentum_hunter.technical_breakouts import BREAKOUT_FAILED, BREAKOUT_PRESENT, BreakoutEvent, TechnicalPriceBar
from momentum_hunter.technical_confluence import (
    BLOCKED,
    CAUTION,
    CLEAR,
    GREEN,
    INSUFFICIENT_DATA,
    RED,
    STRONG_CONFLUENCE,
    TechnicalConfluenceOptions,
    TechnicalConfluenceError,
    adx_trend_strength_state,
    anchored_vwap_state,
    atr_extension_risk_state,
    ema_stack_state,
    evaluate_wave1_confluence,
    relative_strength_state,
    squeeze_release_state,
    volume_confirmation_state,
)


class TechnicalConfluenceTests(unittest.TestCase):
    def test_ema_stack_marks_green_without_mutating_source_bars(self) -> None:
        bars = daily_bars("AAA", [10 + offset * 0.2 for offset in range(70)])
        before = fingerprint_bars(bars)

        state = ema_stack_state(bars, len(bars) - 1)

        self.assertEqual(GREEN, state.state)
        self.assertEqual(before, fingerprint_bars(bars))

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

    def test_volume_confirmation_uses_prior_average(self) -> None:
        bars = daily_bars("AAA", [10.0] * 21, volume=100)
        bars.append(daily_bar("AAA", 21, close=10.5, high=10.6, low=10.2, volume=200))

        state = volume_confirmation_state(bars, 21)

        self.assertEqual(GREEN, state.state)
        self.assertEqual(2.0, state.value)

    def test_relative_strength_outperforms_benchmark(self) -> None:
        stock = daily_bars("AAA", [10.0] * 20 + [12.0])
        benchmark = daily_bars("QQQ", [100.0] * 20 + [105.0])

        state = relative_strength_state(stock, benchmark, 20)

        self.assertEqual(GREEN, state.state)
        self.assertEqual(15.0, state.value)

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

        state = anchored_vwap_state(bars, 1)

        self.assertEqual(GREEN, state.state)
        self.assertLess(float(state.value or 0), 11.0)

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
        options = TechnicalConfluenceOptions(atr_extension_multiple=10.0)

        summary = evaluate_wave1_confluence(
            symbol="AAA",
            bars=bars,
            benchmark_bars=benchmark,
            breakout_events=[event],
            options=options,
        )

        self.assertTrue(summary.research_only)
        self.assertEqual(STRONG_CONFLUENCE, summary.conclusion)
        self.assertGreaterEqual(summary.independent_green_families, 4)
        self.assertEqual(CLEAR, summary.family_states["Overextension / Risk"].state)

    def test_insufficient_data_is_explicit(self) -> None:
        bars = daily_bars("AAA", [10.0] * 5)

        summary = evaluate_wave1_confluence(symbol="AAA", bars=bars)

        self.assertEqual(INSUFFICIENT_DATA, summary.conclusion)
        self.assertEqual("FAIL", summary.family_states["Data Quality"].state)

    def test_invalid_options_fail_closed(self) -> None:
        invalid_options = (
            {"ema_fast_window": 0},
            {"ema_fast_window": 20, "ema_mid_window": 8},
            {"adx_green_threshold": 10.0, "adx_yellow_threshold": 15.0},
            {"volume_confirmation_multiple": float("nan")},
            {"anchored_vwap_anchor_index": -1},
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


def daily_bars(symbol: str, closes: list[float], *, volume: int = 100) -> list[TechnicalPriceBar]:
    return [
        daily_bar(symbol, offset, close=close, high=close, low=close, volume=volume)
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
    event_timestamp: str = "2026-03-01",
) -> BreakoutEvent:
    return BreakoutEvent(
        event_id=f"{symbol}-{status}",
        symbol=symbol,
        event_timestamp=event_timestamp,
        event_type="donchian_20_day_breakout",
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


if __name__ == "__main__":
    unittest.main()
