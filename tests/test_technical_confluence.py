from __future__ import annotations

from dataclasses import replace
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
    GREEN,
    INSUFFICIENT_DATA,
    RED,
    STRONG_CONFLUENCE,
    TechnicalConfluenceOptions,
    TechnicalConfluenceError,
    adx_trend_strength_state,
    anchored_vwap_state,
    atr_extension_risk_state,
    build_technical_confluence_report_payload,
    build_technical_confluence_study_payload,
    ema_stack_state,
    evaluate_wave1_confluence,
    relative_strength_state,
    render_technical_confluence_markdown,
    render_technical_confluence_study_markdown,
    squeeze_release_state,
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

    def test_invalid_benchmark_degrades_relative_strength_only(self) -> None:
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
        self.assertEqual(
            "UNAVAILABLE",
            next(
                indicator
                for indicator in payload["symbols"][0]["indicator_states"]
                if indicator["name"] == "relative_strength_vs_benchmark"
            )["state"],
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
            daily_bars_by_symbol={"AAA": bars},
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
            groups[symbol] = daily_bars(
                symbol,
                [10.0] * 61 + [10.1 + step * 0.1 for step in range(10)],
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
        self.assertEqual(1, len(payload["aggregate_outcomes_by_conclusion"]))
        aggregate = next(
            iter(payload["aggregate_outcomes_by_conclusion"].values())
        )
        self.assertEqual(30, aggregate["sample_count"])
        self.assertEqual(100.0, aggregate["positive_forward_return_rate_pct"]["10d"])

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


if __name__ == "__main__":
    unittest.main()
