from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from math import isfinite
import os
from pathlib import Path
import re
from statistics import mean, pstdev
from typing import Any
from uuid import uuid4

from momentum_hunter.config import DATA_DIR
from momentum_hunter.technical_breakouts import (
    BREAKOUT_FAILED,
    BREAKOUT_PRESENT,
    INSUFFICIENT_DATA,
    BreakoutEvent,
    BreakoutStudyResult,
    TechnicalPriceBar,
    matching_daily_index,
    parse_datetime,
    prior_atr,
    prior_keltner_upper,
    relative_volume,
    return_pct,
    rolling_sma,
    sorted_bars,
    true_range,
)


TECHNICAL_CONFLUENCE_ENGINE_VERSION = "technical_confluence_research_v4"
TECHNICAL_CONFLUENCE_SCHEMA_VERSION = 1
TECHNICAL_CONFLUENCE_ARTIFACT_TYPE = (
    "TECHNICAL_CONFLUENCE_RESEARCH_REPORT"
)
TECHNICAL_CONFLUENCE_LATEST_JSON = (
    DATA_DIR / "reports" / "technical-confluence-latest.json"
)
TECHNICAL_CONFLUENCE_LATEST_MD = (
    DATA_DIR / "reports" / "technical-confluence-latest.md"
)
TECHNICAL_CONFLUENCE_STUDY_LATEST_JSON = (
    DATA_DIR / "reports" / "technical-confluence-study-latest.json"
)
TECHNICAL_CONFLUENCE_STUDY_LATEST_MD = (
    DATA_DIR / "reports" / "technical-confluence-study-latest.md"
)
TECHNICAL_CONFLUENCE_STUDY_ARTIFACT_TYPE = (
    "TECHNICAL_CONFLUENCE_EVENT_STUDY"
)
CONFLUENCE_STUDY_HORIZONS = (1, 2, 5, 10)
CONFLUENCE_STUDY_MINIMUM_COMPLETED_ROWS = 30
CONFLUENCE_STUDY_MINIMUM_BUCKET_ROWS = 10
STUDY_COMPLETE = "COMPLETE"
STUDY_PARTIAL = "PARTIAL"
_REPORT_ROW_LIMIT = 200
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,15}$")

GREEN = "GREEN"
YELLOW = "YELLOW"
RED = "RED"
CAUTION = "CAUTION"
BLOCKED = "BLOCKED"
UNAVAILABLE = "UNAVAILABLE"
CLEAR = "CLEAR"
PASS = "PASS"
PARTIAL = "PARTIAL"
FAIL = "FAIL"

STRONG_CONFLUENCE = "STRONG_CONFLUENCE"
MODERATE_CONFLUENCE = "MODERATE_CONFLUENCE"
WEAK_CONFLUENCE = "WEAK_CONFLUENCE"
CONFLICTED_CONFLUENCE = "CONFLICTED_CONFLUENCE"

FAMILY_TREND = "Trend / Structure"
FAMILY_MOMENTUM = "Momentum"
FAMILY_VOLATILITY = "Volatility / Compression"
FAMILY_VOLUME = "Volume / Participation"
FAMILY_RELATIVE_STRENGTH = "Relative Strength"
FAMILY_RISK = "Overextension / Risk"
FAMILY_DATA_QUALITY = "Data Quality"


class TechnicalConfluenceError(ValueError):
    pass


@dataclass(frozen=True)
class TechnicalConfluenceOptions:
    ema_fast_window: int = 8
    ema_mid_window: int = 20
    ema_slow_window: int = 50
    sma_short_window: int = 20
    sma_mid_window: int = 50
    sma_long_window: int = 200
    adx_window: int = 14
    adx_green_threshold: float = 20.0
    adx_yellow_threshold: float = 15.0
    bollinger_window: int = 20
    bollinger_stddevs: float = 2.0
    keltner_atr_window: int = 20
    keltner_atr_multiple: float = 1.5
    volume_average_window: int = 20
    volume_confirmation_multiple: float = 1.5
    relative_strength_window: int = 20
    relative_strength_mid_window: int = 50
    relative_strength_long_window: int = 60
    atr_extension_window: int = 14
    atr_extension_multiple: float = 2.5
    anchored_vwap_anchor_index: int | None = None
    rsi_window: int = 14
    rsi_hold_bars: int = 5
    rsi_floor: float = 50.0
    rsi_reach: float = 60.0
    macd_fast_window: int = 12
    macd_slow_window: int = 26
    macd_signal_window: int = 9
    obv_short_window: int = 20
    obv_long_window: int = 50
    mfi_window: int = 14
    cmf_window: int = 20
    roc_short_window: int = 10
    roc_mid_window: int = 20
    roc_long_window: int = 60
    accumulation_distribution_minimum_bars: int = 50
    accumulation_distribution_slope_window: int = 20
    up_down_volume_short_window: int = 10
    up_down_volume_long_window: int = 20

    def __post_init__(self) -> None:
        windows = {
            "EMA fast window": self.ema_fast_window,
            "EMA mid window": self.ema_mid_window,
            "EMA slow window": self.ema_slow_window,
            "SMA short window": self.sma_short_window,
            "SMA mid window": self.sma_mid_window,
            "SMA long window": self.sma_long_window,
            "ADX window": self.adx_window,
            "Bollinger window": self.bollinger_window,
            "Keltner ATR window": self.keltner_atr_window,
            "Volume average window": self.volume_average_window,
            "Relative-strength window": self.relative_strength_window,
            "Relative-strength mid window": (
                self.relative_strength_mid_window
            ),
            "Relative-strength long window": (
                self.relative_strength_long_window
            ),
            "ATR extension window": self.atr_extension_window,
            "RSI window": self.rsi_window,
            "RSI hold bars": self.rsi_hold_bars,
            "MACD fast window": self.macd_fast_window,
            "MACD slow window": self.macd_slow_window,
            "MACD signal window": self.macd_signal_window,
            "OBV short window": self.obv_short_window,
            "OBV long window": self.obv_long_window,
            "MFI window": self.mfi_window,
            "CMF window": self.cmf_window,
            "ROC short window": self.roc_short_window,
            "ROC mid window": self.roc_mid_window,
            "ROC long window": self.roc_long_window,
            "A/D minimum bars": (
                self.accumulation_distribution_minimum_bars
            ),
            "A/D slope window": self.accumulation_distribution_slope_window,
            "Up/down-volume short window": (
                self.up_down_volume_short_window
            ),
            "Up/down-volume long window": self.up_down_volume_long_window,
        }
        for label, value in windows.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise TechnicalConfluenceError(
                    f"{label} must be a positive integer."
                )
        if not (
            self.ema_fast_window
            < self.ema_mid_window
            < self.ema_slow_window
        ):
            raise TechnicalConfluenceError(
                "EMA windows must be ordered fast < mid < slow."
            )
        if not (
            self.sma_short_window
            < self.sma_mid_window
            < self.sma_long_window
        ):
            raise TechnicalConfluenceError(
                "SMA windows must be ordered short < mid < long."
            )
        if not (
            self.relative_strength_window
            < self.relative_strength_mid_window
            < self.relative_strength_long_window
        ):
            raise TechnicalConfluenceError(
                "Relative-strength windows must be ordered short < mid < long."
            )
        if self.macd_fast_window >= self.macd_slow_window:
            raise TechnicalConfluenceError(
                "MACD fast window must be below its slow window."
            )
        if self.obv_short_window >= self.obv_long_window:
            raise TechnicalConfluenceError(
                "OBV short window must be below its long window."
            )
        if not (
            self.roc_short_window
            < self.roc_mid_window
            < self.roc_long_window
        ):
            raise TechnicalConfluenceError(
                "ROC windows must be ordered short < mid < long."
            )
        if (
            self.accumulation_distribution_slope_window
            >= self.accumulation_distribution_minimum_bars
        ):
            raise TechnicalConfluenceError(
                "A/D slope window must be below its minimum bar count."
            )
        if (
            self.up_down_volume_short_window
            >= self.up_down_volume_long_window
        ):
            raise TechnicalConfluenceError(
                "Up/down-volume short window must be below its long window."
            )
        numeric_options = {
            "ADX green threshold": self.adx_green_threshold,
            "ADX yellow threshold": self.adx_yellow_threshold,
            "Bollinger standard-deviation multiple": self.bollinger_stddevs,
            "Keltner ATR multiple": self.keltner_atr_multiple,
            "Volume confirmation multiple": (
                self.volume_confirmation_multiple
            ),
            "ATR extension multiple": self.atr_extension_multiple,
            "RSI floor": self.rsi_floor,
            "RSI reach": self.rsi_reach,
        }
        for label, value in numeric_options.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or float(value) <= 0
            ):
                raise TechnicalConfluenceError(
                    f"{label} must be finite and greater than zero."
                )
        if self.adx_green_threshold < self.adx_yellow_threshold:
            raise TechnicalConfluenceError(
                "ADX green threshold cannot be below the yellow threshold."
            )
        if not (
            0.0 < self.rsi_floor < self.rsi_reach <= 100.0
        ):
            raise TechnicalConfluenceError(
                "RSI thresholds must satisfy 0 < floor < reach <= 100."
            )
        if self.anchored_vwap_anchor_index is not None and (
            isinstance(self.anchored_vwap_anchor_index, bool)
            or not isinstance(self.anchored_vwap_anchor_index, int)
            or self.anchored_vwap_anchor_index < 0
        ):
            raise TechnicalConfluenceError(
                "Anchored VWAP index must be a non-negative integer."
            )


@dataclass(frozen=True)
class IndicatorState:
    name: str
    family: str
    state: str
    role: str
    value: float | str | bool | None
    reason: str
    data_sufficiency: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfluenceFamilyState:
    family: str
    state: str
    reason: str
    indicator_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TechnicalConfluenceSummary:
    symbol: str
    timestamp: str | None
    research_only: bool
    schema_version: int
    engine_version: str
    raw_green_checks: int
    raw_total_checks: int
    independent_green_families: int
    independent_total_families: int
    major_red_flags: int
    warning_flags: int
    conclusion: str
    indicator_states: list[IndicatorState]
    family_states: dict[str, ConfluenceFamilyState]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TechnicalConfluenceStudyRow:
    symbol: str
    event_date: str
    event_ids: tuple[str, ...]
    event_types: tuple[str, ...]
    event_count: int
    start_price: float
    forward_returns_pct: dict[str, float | None]
    max_favorable_excursion_pct: float | None
    max_adverse_excursion_pct: float | None
    outcome_status: str
    confluence_summary: TechnicalConfluenceSummary
    breakout_contexts: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "event_date": self.event_date,
            "event_ids": list(self.event_ids),
            "event_types": list(self.event_types),
            "event_count": self.event_count,
            "start_price": self.start_price,
            "forward_returns_pct": dict(self.forward_returns_pct),
            "max_favorable_excursion_pct": (
                self.max_favorable_excursion_pct
            ),
            "max_adverse_excursion_pct": (
                self.max_adverse_excursion_pct
            ),
            "outcome_status": self.outcome_status,
            "confluence_summary": self.confluence_summary.to_dict(),
            "breakout_contexts": [
                dict(context) for context in self.breakout_contexts
            ],
        }


def evaluate_wave1_confluence(
    *,
    symbol: str,
    bars: list[TechnicalPriceBar],
    benchmark_bars: list[TechnicalPriceBar] | None = None,
    breakout_events: list[BreakoutEvent] | None = None,
    index: int | None = None,
    options: TechnicalConfluenceOptions | None = None,
) -> TechnicalConfluenceSummary:
    options = options or TechnicalConfluenceOptions()
    normalized_symbol = str(symbol).upper().strip()
    if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
        raise TechnicalConfluenceError(
            "Confluence symbol must use the bounded market-symbol format."
        )
    _validate_price_bars(
        bars,
        expected_symbol=normalized_symbol,
        source_label="symbol",
    )
    if benchmark_bars:
        _validate_price_bars(
            benchmark_bars,
            expected_symbol=None,
            source_label="benchmark",
        )
    ordered_bars = sorted_bars(bars)
    index = len(ordered_bars) - 1 if index is None else index
    timestamp = ordered_bars[index].timestamp if 0 <= index < len(ordered_bars) else None

    indicators = [
        ema_stack_state(ordered_bars, index, options=options),
        sma_position_state(ordered_bars, index, options=options),
        adx_trend_strength_state(ordered_bars, index, options=options),
        anchored_vwap_state(ordered_bars, index, options=options),
        rsi_regime_state(ordered_bars, index, options=options),
        macd_momentum_state(ordered_bars, index, options=options),
        ppo_momentum_state(ordered_bars, index, options=options),
        rate_of_change_state(ordered_bars, index, options=options),
        squeeze_release_state(ordered_bars, index, options=options),
        volume_confirmation_state(ordered_bars, index, options=options),
        obv_new_high_state(ordered_bars, index, options=options),
        money_flow_index_state(ordered_bars, index, options=options),
        chaikin_money_flow_state(ordered_bars, index, options=options),
        accumulation_distribution_state(
            ordered_bars,
            index,
            options=options,
        ),
        up_down_volume_state(ordered_bars, index, options=options),
        relative_strength_state(ordered_bars, benchmark_bars or [], index, options=options),
        relative_strength_short_slope_state(
            ordered_bars,
            benchmark_bars or [],
            index,
            options=options,
        ),
        relative_strength_long_slope_state(
            ordered_bars,
            benchmark_bars or [],
            index,
            options=options,
        ),
        relative_strength_new_high_state(
            ordered_bars,
            benchmark_bars or [],
            index,
            options=options,
        ),
        atr_extension_risk_state(ordered_bars, index, options=options),
        failed_breakout_state(
            symbol=normalized_symbol,
            breakout_events=breakout_events or [],
            as_of=timestamp,
        ),
    ]
    family_states = build_family_states(indicators)
    raw_total = sum(1 for indicator in indicators if indicator.state not in {UNAVAILABLE, INSUFFICIENT_DATA})
    raw_green = sum(1 for indicator in indicators if indicator.state == GREEN)
    signal_families = [
        FAMILY_TREND,
        FAMILY_MOMENTUM,
        FAMILY_VOLATILITY,
        FAMILY_VOLUME,
        FAMILY_RELATIVE_STRENGTH,
    ]
    independent_green = sum(1 for family in signal_families if family_states[family].state == GREEN)
    independent_total = sum(1 for family in signal_families if family_states[family].state not in {UNAVAILABLE, INSUFFICIENT_DATA})
    major_red_flags = sum(1 for state in family_states.values() if state.state in {RED, BLOCKED, FAIL})
    warning_flags = sum(1 for state in family_states.values() if state.state in {YELLOW, CAUTION, PARTIAL})
    conclusion = confluence_conclusion(
        independent_green_families=independent_green,
        independent_total_families=independent_total,
        major_red_flags=major_red_flags,
        warning_flags=warning_flags,
        data_quality_state=family_states[FAMILY_DATA_QUALITY].state,
    )
    return TechnicalConfluenceSummary(
        symbol=normalized_symbol,
        timestamp=timestamp,
        research_only=True,
        schema_version=TECHNICAL_CONFLUENCE_SCHEMA_VERSION,
        engine_version=TECHNICAL_CONFLUENCE_ENGINE_VERSION,
        raw_green_checks=raw_green,
        raw_total_checks=raw_total,
        independent_green_families=independent_green,
        independent_total_families=independent_total,
        major_red_flags=major_red_flags,
        warning_flags=warning_flags,
        conclusion=conclusion,
        indicator_states=indicators,
        family_states=family_states,
    )


def build_technical_confluence_report_payload(
    *,
    generated_at: str,
    daily_bars_by_symbol: dict[str, list[TechnicalPriceBar]],
    breakout_events: list[BreakoutEvent],
    source_paths: dict[str, str | None],
    benchmark_symbol: str = "QQQ",
    options: TechnicalConfluenceOptions | None = None,
) -> dict[str, Any]:
    if parse_datetime(generated_at) is None:
        raise TechnicalConfluenceError(
            "Confluence report timestamp must be valid ISO 8601."
        )
    options = options or TechnicalConfluenceOptions()
    normalized_benchmark = str(benchmark_symbol).upper().strip()
    if not _SYMBOL_PATTERN.fullmatch(normalized_benchmark):
        raise TechnicalConfluenceError(
            "Benchmark symbol must use the bounded market-symbol format."
        )

    groups: dict[str, list[TechnicalPriceBar]] = {}
    duplicate_groups: set[str] = set()
    invalid_group_names = 0
    for raw_symbol, bars in daily_bars_by_symbol.items():
        symbol = str(raw_symbol).upper().strip()
        if not _SYMBOL_PATTERN.fullmatch(symbol):
            invalid_group_names += 1
            continue
        if symbol in groups:
            duplicate_groups.add(symbol)
            continue
        groups[symbol] = list(bars)
    for symbol in duplicate_groups:
        groups.pop(symbol, None)

    event_symbols = {
        str(event.symbol).upper().strip()
        for event in breakout_events
        if _SYMBOL_PATTERN.fullmatch(str(event.symbol).upper().strip())
    }
    symbols = sorted(
        (set(groups) | event_symbols) - {normalized_benchmark}
    )
    benchmark_bars = groups.get(normalized_benchmark, [])
    summaries: list[TechnicalConfluenceSummary] = []
    unavailable_symbols: list[dict[str, str]] = []
    warnings: list[str] = []
    if invalid_group_names:
        warnings.append(
            f"INVALID_DAILY_BAR_GROUP_NAMES:{invalid_group_names}"
        )
    if duplicate_groups:
        warnings.extend(
            f"DUPLICATE_DAILY_BAR_GROUP:{symbol}"
            for symbol in sorted(duplicate_groups)
        )
    if benchmark_bars:
        try:
            _validate_price_bars(
                benchmark_bars,
                expected_symbol=normalized_benchmark,
                source_label="benchmark",
            )
        except TechnicalConfluenceError:
            benchmark_bars = []
            warnings.append(
                f"BENCHMARK_BAR_INPUT_REJECTED:{normalized_benchmark}"
            )
    if (
        not benchmark_bars
        and f"BENCHMARK_BAR_INPUT_REJECTED:{normalized_benchmark}"
        not in warnings
    ):
        warnings.append(
            f"BENCHMARK_BARS_UNAVAILABLE:{normalized_benchmark}"
        )
    if not symbols:
        warnings.append("NO_RESEARCH_SYMBOLS_AVAILABLE")

    for symbol in symbols:
        bars = groups.get(symbol, [])
        if not bars:
            unavailable_symbols.append(
                {
                    "symbol": symbol,
                    "reason": "DAILY_BARS_UNAVAILABLE",
                }
            )
            continue
        try:
            summaries.append(
                evaluate_wave1_confluence(
                    symbol=symbol,
                    bars=bars,
                    benchmark_bars=benchmark_bars,
                    breakout_events=breakout_events,
                    options=options,
                )
            )
        except TechnicalConfluenceError:
            unavailable_symbols.append(
                {
                    "symbol": symbol,
                    "reason": "DAILY_BAR_INPUT_REJECTED",
                }
            )

    conclusion_counts: dict[str, int] = {}
    for summary in summaries:
        conclusion_counts[summary.conclusion] = (
            conclusion_counts.get(summary.conclusion, 0) + 1
        )
    partial_data_symbols = sum(
        1
        for summary in summaries
        if summary.family_states[FAMILY_DATA_QUALITY].state != PASS
    )
    red_flag_symbols = sum(
        1 for summary in summaries if summary.major_red_flags > 0
    )
    return {
        "artifact_type": TECHNICAL_CONFLUENCE_ARTIFACT_TYPE,
        "schema_version": TECHNICAL_CONFLUENCE_SCHEMA_VERSION,
        "engine_version": TECHNICAL_CONFLUENCE_ENGINE_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "trade_recommendation": False,
        "production_score_changed": False,
        "alert_logic_changed": False,
        "broker_action_allowed": False,
        "benchmark_symbol": normalized_benchmark,
        "source_paths": dict(sorted(source_paths.items())),
        "summary": {
            "symbols_considered": len(symbols),
            "symbols_evaluated": len(summaries),
            "symbols_unavailable": len(unavailable_symbols),
            "symbols_with_partial_data": partial_data_symbols,
            "symbols_with_major_red_flags": red_flag_symbols,
            "conclusion_counts": dict(sorted(conclusion_counts.items())),
        },
        "symbols": [summary.to_dict() for summary in summaries],
        "unavailable_symbols": unavailable_symbols,
        "warnings": warnings,
    }


def build_technical_confluence_study_payload(
    *,
    generated_at: str,
    daily_bars_by_symbol: dict[str, list[TechnicalPriceBar]],
    breakout_events: list[BreakoutEvent],
    breakout_studies: list[BreakoutStudyResult],
    source_paths: dict[str, str | None],
    benchmark_symbol: str = "QQQ",
    options: TechnicalConfluenceOptions | None = None,
) -> dict[str, Any]:
    if parse_datetime(generated_at) is None:
        raise TechnicalConfluenceError(
            "Confluence study timestamp must be valid ISO 8601."
        )
    options = options or TechnicalConfluenceOptions()
    normalized_benchmark = str(benchmark_symbol).upper().strip()
    if not _SYMBOL_PATTERN.fullmatch(normalized_benchmark):
        raise TechnicalConfluenceError(
            "Benchmark symbol must use the bounded market-symbol format."
        )

    groups: dict[str, list[TechnicalPriceBar]] = {}
    duplicate_groups: set[str] = set()
    warnings: list[str] = []
    for raw_symbol, bars in daily_bars_by_symbol.items():
        symbol = str(raw_symbol).upper().strip()
        if not _SYMBOL_PATTERN.fullmatch(symbol):
            warnings.append("INVALID_DAILY_BAR_GROUP_NAME")
            continue
        if symbol in groups:
            duplicate_groups.add(symbol)
            continue
        groups[symbol] = list(bars)
    for symbol in duplicate_groups:
        groups.pop(symbol, None)
        warnings.append(f"DUPLICATE_DAILY_BAR_GROUP:{symbol}")

    benchmark_bars = groups.get(normalized_benchmark, [])
    if benchmark_bars:
        try:
            _validate_price_bars(
                benchmark_bars,
                expected_symbol=normalized_benchmark,
                source_label="benchmark",
            )
        except TechnicalConfluenceError:
            benchmark_bars = []
            warnings.append(
                f"BENCHMARK_BAR_INPUT_REJECTED:{normalized_benchmark}"
            )
    else:
        warnings.append(
            f"BENCHMARK_BARS_UNAVAILABLE:{normalized_benchmark}"
        )

    eligible_events: list[BreakoutEvent] = []
    events_by_id: dict[str, list[BreakoutEvent]] = {}
    ignored_event_count = 0
    for event in breakout_events:
        symbol = str(event.symbol).upper().strip()
        event_time = parse_datetime(event.event_timestamp)
        if (
            event.status != BREAKOUT_PRESENT
            or event.timeframe != "daily"
            or event_time is None
            or not _SYMBOL_PATTERN.fullmatch(symbol)
            or symbol == normalized_benchmark
        ):
            ignored_event_count += 1
            continue
        events_by_id.setdefault(event.event_id, []).append(event)
    duplicate_event_ids = {
        event_id
        for event_id, matching_events in events_by_id.items()
        if len(matching_events) != 1
    }
    if duplicate_event_ids:
        warnings.append(
            f"DUPLICATE_BREAKOUT_EVENT_IDS:{len(duplicate_event_ids)}"
        )
    for event_id, matching_events in events_by_id.items():
        if event_id not in duplicate_event_ids:
            eligible_events.append(matching_events[0])

    event_groups: dict[tuple[str, str], list[BreakoutEvent]] = {}
    for event in eligible_events:
        event_time = parse_datetime(event.event_timestamp)
        assert event_time is not None
        event_groups.setdefault(
            (str(event.symbol).upper().strip(), event_time.date().isoformat()),
            [],
        ).append(event)

    studies_by_event_id: dict[str, BreakoutStudyResult] = {}
    duplicate_study_ids: set[str] = set()
    for study in breakout_studies:
        if study.event_id in studies_by_event_id:
            duplicate_study_ids.add(study.event_id)
            continue
        studies_by_event_id[study.event_id] = study
    for event_id in duplicate_study_ids:
        studies_by_event_id.pop(event_id, None)
    if duplicate_study_ids:
        warnings.append(
            f"DUPLICATE_BREAKOUT_STUDY_IDS:{len(duplicate_study_ids)}"
        )
    if ignored_event_count:
        warnings.append(
            f"NON_DAILY_OR_NON_PRESENT_EVENTS_IGNORED:{ignored_event_count}"
        )

    rows: list[TechnicalConfluenceStudyRow] = []
    unavailable_groups: list[dict[str, str]] = []
    for (symbol, event_date), grouped_events in sorted(
        event_groups.items()
    ):
        bars = groups.get(symbol, [])
        if not bars:
            unavailable_groups.append(
                {
                    "symbol": symbol,
                    "event_date": event_date,
                    "reason": "DAILY_BARS_UNAVAILABLE",
                }
            )
            continue
        try:
            _validate_price_bars(
                bars,
                expected_symbol=symbol,
                source_label="study symbol",
            )
        except TechnicalConfluenceError:
            unavailable_groups.append(
                {
                    "symbol": symbol,
                    "event_date": event_date,
                    "reason": "DAILY_BAR_INPUT_REJECTED",
                }
            )
            continue
        ordered_bars = sorted_bars(bars)
        event_time = parse_datetime(event_date)
        event_index = (
            matching_daily_index(ordered_bars, event_time)
            if event_time is not None
            else None
        )
        if event_index is None:
            unavailable_groups.append(
                {
                    "symbol": symbol,
                    "event_date": event_date,
                    "reason": "EVENT_DATE_BAR_UNAVAILABLE",
                }
            )
            continue

        historical_bars = ordered_bars[: event_index + 1]
        historical_benchmark: list[TechnicalPriceBar] = []
        if benchmark_bars and event_time is not None:
            ordered_benchmark = sorted_bars(benchmark_bars)
            benchmark_index = matching_daily_index(
                ordered_benchmark,
                event_time,
            )
            if benchmark_index is not None:
                historical_benchmark = ordered_benchmark[: benchmark_index + 1]
        try:
            confluence = evaluate_wave1_confluence(
                symbol=symbol,
                bars=historical_bars,
                benchmark_bars=historical_benchmark,
                breakout_events=breakout_events,
                options=options,
            )
        except TechnicalConfluenceError:
            unavailable_groups.append(
                {
                    "symbol": symbol,
                    "event_date": event_date,
                    "reason": "CONFLUENCE_INPUT_REJECTED",
                }
            )
            continue
        start_price = ordered_bars[event_index].close
        returns: dict[str, float | None] = {}
        for horizon in CONFLUENCE_STUDY_HORIZONS:
            target_index = event_index + horizon
            returns[f"{horizon}d"] = (
                return_pct(
                    start_price,
                    ordered_bars[target_index].close,
                )
                if target_index < len(ordered_bars)
                else None
            )
        future_bars = ordered_bars[
            event_index + 1 : min(
                len(ordered_bars),
                event_index + max(CONFLUENCE_STUDY_HORIZONS) + 1,
            )
        ]
        max_favorable = (
            round(
                max(
                    return_pct(start_price, bar.high)
                    for bar in future_bars
                ),
                4,
            )
            if future_bars
            else None
        )
        max_adverse = (
            round(
                min(
                    return_pct(start_price, bar.low)
                    for bar in future_bars
                ),
                4,
            )
            if future_bars
            else None
        )
        sorted_events = sorted(
            grouped_events,
            key=lambda event: (event.event_type, event.event_id),
        )
        contexts = tuple(
            _breakout_study_context(
                event,
                studies_by_event_id.get(event.event_id),
            )
            for event in sorted_events
        )
        available_returns = sum(
            value is not None for value in returns.values()
        )
        complete_breakout_context = all(
            context["reason"] is None
            and context["held_above_breakout_level"] is not None
            and context["failed_back_below_breakout_level"] is not None
            for context in contexts
        )
        outcome_status = (
            STUDY_COMPLETE
            if (
                available_returns == len(CONFLUENCE_STUDY_HORIZONS)
                and complete_breakout_context
            )
            else STUDY_PARTIAL
            if available_returns or contexts
            else INSUFFICIENT_DATA
        )
        rows.append(
            TechnicalConfluenceStudyRow(
                symbol=symbol,
                event_date=event_date,
                event_ids=tuple(event.event_id for event in sorted_events),
                event_types=tuple(
                    event.event_type for event in sorted_events
                ),
                event_count=len(sorted_events),
                start_price=start_price,
                forward_returns_pct=returns,
                max_favorable_excursion_pct=max_favorable,
                max_adverse_excursion_pct=max_adverse,
                outcome_status=outcome_status,
                confluence_summary=confluence,
                breakout_contexts=contexts,
            )
        )

    complete_rows = [
        row for row in rows if row.outcome_status == STUDY_COMPLETE
    ]
    if len(complete_rows) >= CONFLUENCE_STUDY_MINIMUM_COMPLETED_ROWS:
        aggregate_outcomes, withheld_conclusions = (
            _aggregate_confluence_study_rows(complete_rows)
        )
    else:
        aggregate_outcomes = {}
        withheld_conclusions = sorted(
            {
                row.confluence_summary.conclusion
                for row in complete_rows
            }
        )
    aggregate_released = bool(aggregate_outcomes)
    if (
        len(complete_rows)
        < CONFLUENCE_STUDY_MINIMUM_COMPLETED_ROWS
    ):
        warnings.append(
            "AGGREGATE_OUTCOMES_WITHHELD_MINIMUM_SAMPLE"
        )
    elif withheld_conclusions:
        warnings.append(
            "SMALL_CONCLUSION_BUCKETS_WITHHELD:"
            + ",".join(withheld_conclusions)
        )
    return {
        "artifact_type": TECHNICAL_CONFLUENCE_STUDY_ARTIFACT_TYPE,
        "schema_version": TECHNICAL_CONFLUENCE_SCHEMA_VERSION,
        "engine_version": TECHNICAL_CONFLUENCE_ENGINE_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "trade_recommendation": False,
        "production_score_changed": False,
        "alert_logic_changed": False,
        "broker_action_allowed": False,
        "benchmark_symbol": normalized_benchmark,
        "source_paths": dict(sorted(source_paths.items())),
        "minimum_completed_rows": (
            CONFLUENCE_STUDY_MINIMUM_COMPLETED_ROWS
        ),
        "minimum_conclusion_bucket_rows": (
            CONFLUENCE_STUDY_MINIMUM_BUCKET_ROWS
        ),
        "outcome_methodology": {
            "sample_identity": "one_per_symbol_event_date",
            "return_baseline": "event_date_close",
            "forward_sessions": list(CONFLUENCE_STUDY_HORIZONS),
            "complete_requires_breakout_hold_failure_evidence": True,
        },
        "summary": {
            "unique_symbol_date_rows": len(rows),
            "complete_rows": len(complete_rows),
            "partial_rows": sum(
                row.outcome_status == STUDY_PARTIAL for row in rows
            ),
            "insufficient_rows": sum(
                row.outcome_status == INSUFFICIENT_DATA for row in rows
            ),
            "unavailable_event_groups": len(unavailable_groups),
            "completed_rows_to_minimum": max(
                0,
                CONFLUENCE_STUDY_MINIMUM_COMPLETED_ROWS
                - len(complete_rows),
            ),
            "aggregate_outcomes_released": aggregate_released,
        },
        "rows": [row.to_dict() for row in rows],
        "unavailable_event_groups": unavailable_groups,
        "aggregate_outcomes_by_conclusion": aggregate_outcomes,
        "withheld_conclusions": withheld_conclusions,
        "warnings": warnings,
    }


def _breakout_study_context(
    event: BreakoutEvent,
    study: BreakoutStudyResult | None,
) -> dict[str, Any]:
    base = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "trigger_price": _finite_number_or_none(event.trigger_price),
        "volume_confirmed": event.volume_confirmed,
    }
    if study is None:
        return {
            **base,
            "study_status": INSUFFICIENT_DATA,
            "data_sufficiency": INSUFFICIENT_DATA,
            "held_above_breakout_level": None,
            "failed_back_below_breakout_level": None,
            "became_extended": None,
            "forward_returns_pct": {},
            "reason": "BREAKOUT_STUDY_NOT_AVAILABLE",
        }
    event_time = parse_datetime(event.event_timestamp)
    study_time = parse_datetime(study.event_timestamp)
    identity_matches = (
        study.symbol.upper().strip() == event.symbol.upper().strip()
        and study.event_type == event.event_type
        and study.timeframe == event.timeframe
        and event_time is not None
        and study_time is not None
        and event_time.date() == study_time.date()
        and _same_optional_number(study.trigger_price, event.trigger_price)
    )
    if not identity_matches:
        return {
            **base,
            "study_status": INSUFFICIENT_DATA,
            "data_sufficiency": INSUFFICIENT_DATA,
            "held_above_breakout_level": None,
            "failed_back_below_breakout_level": None,
            "became_extended": None,
            "forward_returns_pct": {},
            "reason": "BREAKOUT_STUDY_IDENTITY_MISMATCH",
        }
    evidence_is_consistent = (
        isinstance(study.held_above_breakout_level, bool)
        and isinstance(study.failed_back_below_breakout_level, bool)
        and study.held_above_breakout_level
        is not study.failed_back_below_breakout_level
        and (
            (
                study.failed_back_below_breakout_level
                and study.status == BREAKOUT_FAILED
            )
            or (
                study.held_above_breakout_level
                and study.status == BREAKOUT_PRESENT
            )
        )
        and study.data_sufficiency != INSUFFICIENT_DATA
    )
    if not evidence_is_consistent:
        return {
            **base,
            "study_status": INSUFFICIENT_DATA,
            "data_sufficiency": INSUFFICIENT_DATA,
            "held_above_breakout_level": None,
            "failed_back_below_breakout_level": None,
            "became_extended": None,
            "forward_returns_pct": {},
            "reason": "BREAKOUT_STUDY_EVIDENCE_INVALID",
        }
    return {
        **base,
        "study_status": study.status,
        "data_sufficiency": study.data_sufficiency,
        "held_above_breakout_level": study.held_above_breakout_level,
        "failed_back_below_breakout_level": (
            study.failed_back_below_breakout_level
        ),
        "became_extended": study.became_extended,
        "forward_returns_pct": {
            str(horizon): _finite_number_or_none(value)
            for horizon, value in sorted(study.forward_returns_pct.items())
        },
        "reason": None,
    }


def _aggregate_confluence_study_rows(
    rows: list[TechnicalConfluenceStudyRow],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    grouped: dict[str, list[TechnicalConfluenceStudyRow]] = {}
    for row in rows:
        grouped.setdefault(
            row.confluence_summary.conclusion,
            [],
        ).append(row)

    aggregates: dict[str, dict[str, Any]] = {}
    withheld: list[str] = []
    for conclusion, bucket in sorted(grouped.items()):
        if len(bucket) < CONFLUENCE_STUDY_MINIMUM_BUCKET_ROWS:
            withheld.append(conclusion)
            continue
        mean_returns: dict[str, float] = {}
        positive_rates: dict[str, float] = {}
        for horizon in CONFLUENCE_STUDY_HORIZONS:
            label = f"{horizon}d"
            values = [
                float(row.forward_returns_pct[label])
                for row in bucket
                if row.forward_returns_pct[label] is not None
            ]
            if len(values) != len(bucket):
                raise TechnicalConfluenceError(
                    "Complete confluence rows require every study horizon."
                )
            mean_returns[label] = round(mean(values), 4)
            positive_rates[label] = round(
                100.0
                * sum(value > 0 for value in values)
                / len(values),
                4,
            )
        favorable = [
            float(row.max_favorable_excursion_pct)
            for row in bucket
            if row.max_favorable_excursion_pct is not None
        ]
        adverse = [
            float(row.max_adverse_excursion_pct)
            for row in bucket
            if row.max_adverse_excursion_pct is not None
        ]
        aggregates[conclusion] = {
            "sample_count": len(bucket),
            "mean_forward_returns_pct": mean_returns,
            "positive_forward_return_rate_pct": positive_rates,
            "mean_max_favorable_excursion_pct": (
                round(mean(favorable), 4) if favorable else None
            ),
            "mean_max_adverse_excursion_pct": (
                round(mean(adverse), 4) if adverse else None
            ),
        }
    return aggregates, withheld


def write_technical_confluence_reports(
    payload: dict[str, Any],
    *,
    output_dir: Path,
) -> dict[str, Path]:
    _validate_output_payload(
        payload,
        artifact_type=TECHNICAL_CONFLUENCE_ARTIFACT_TYPE,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / TECHNICAL_CONFLUENCE_LATEST_JSON.name
    markdown_path = output_dir / TECHNICAL_CONFLUENCE_LATEST_MD.name
    _validate_report_target(
        json_path,
        format_name="json",
        artifact_type=TECHNICAL_CONFLUENCE_ARTIFACT_TYPE,
        markdown_heading="# Technical Confluence Research - ",
    )
    _validate_report_target(
        markdown_path,
        format_name="markdown",
        artifact_type=TECHNICAL_CONFLUENCE_ARTIFACT_TYPE,
        markdown_heading="# Technical Confluence Research - ",
    )
    _write_report_text(
        json_path,
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
    )
    _write_report_text(
        markdown_path,
        render_technical_confluence_markdown(payload),
    )
    return {"json": json_path, "markdown": markdown_path}


def write_technical_confluence_study_reports(
    payload: dict[str, Any],
    *,
    output_dir: Path,
) -> dict[str, Path]:
    _validate_output_payload(
        payload,
        artifact_type=TECHNICAL_CONFLUENCE_STUDY_ARTIFACT_TYPE,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / TECHNICAL_CONFLUENCE_STUDY_LATEST_JSON.name
    markdown_path = output_dir / TECHNICAL_CONFLUENCE_STUDY_LATEST_MD.name
    _validate_report_target(
        json_path,
        format_name="json",
        artifact_type=TECHNICAL_CONFLUENCE_STUDY_ARTIFACT_TYPE,
        markdown_heading="# Technical Confluence Event Study - ",
    )
    _validate_report_target(
        markdown_path,
        format_name="markdown",
        artifact_type=TECHNICAL_CONFLUENCE_STUDY_ARTIFACT_TYPE,
        markdown_heading="# Technical Confluence Event Study - ",
    )
    _write_report_text(
        json_path,
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
    )
    _write_report_text(
        markdown_path,
        render_technical_confluence_study_markdown(payload),
    )
    return {"json": json_path, "markdown": markdown_path}


def render_technical_confluence_markdown(
    payload: dict[str, Any],
) -> str:
    summary = payload["summary"]
    lines = [
        f"# Technical Confluence Research - {payload['generated_at']}",
        "",
        (
            "Research-only evidence. This report does not change production "
            "scoring, alerts, readiness, trade planning, or broker behavior."
        ),
        "",
        "## Summary",
        "",
        f"- Symbols considered: {summary['symbols_considered']}",
        f"- Symbols evaluated: {summary['symbols_evaluated']}",
        f"- Symbols unavailable: {summary['symbols_unavailable']}",
        (
            "- Symbols with partial data: "
            f"{summary['symbols_with_partial_data']}"
        ),
        (
            "- Symbols with major red flags: "
            f"{summary['symbols_with_major_red_flags']}"
        ),
        f"- Benchmark: {payload['benchmark_symbol']}",
        "",
        "## Symbol Evidence",
        "",
    ]
    symbols = payload["symbols"][:_REPORT_ROW_LIMIT]
    if not symbols:
        lines.append("- No symbols had sufficient valid daily bars.")
    else:
        lines.extend(
            [
                (
                    "| Symbol | Conclusion | Raw Green | Green Families | "
                    "Red Flags | Risk | Data Quality |"
                ),
                "| --- | --- | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for item in symbols:
            family_states = item["family_states"]
            risk = family_states[FAMILY_RISK]["state"]
            quality = family_states[FAMILY_DATA_QUALITY]["state"]
            lines.append(
                f"| {item['symbol']} | {item['conclusion']} | "
                f"{item['raw_green_checks']} / {item['raw_total_checks']} | "
                f"{item['independent_green_families']} / "
                f"{item['independent_total_families']} | "
                f"{item['major_red_flags']} | {risk} | {quality} |"
            )
    lines.extend(["", "## Unavailable Symbols", ""])
    unavailable = payload["unavailable_symbols"][:_REPORT_ROW_LIMIT]
    if unavailable:
        lines.extend(
            f"- {item['symbol']}: {item['reason']}"
            for item in unavailable
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Warnings", ""])
    if payload["warnings"]:
        lines.extend(f"- {warning}" for warning in payload["warnings"])
    else:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def render_technical_confluence_study_markdown(
    payload: dict[str, Any],
) -> str:
    summary = payload["summary"]
    lines = [
        f"# Technical Confluence Event Study - {payload['generated_at']}",
        "",
        (
            "Research-only evidence. This report measures historical outcomes "
            "and does not change production scoring, alerts, readiness, trade "
            "planning, UI behavior, or broker behavior."
        ),
        "",
        "## Sample Status",
        "",
        (
            "- Unique symbol/date samples: "
            f"{summary['unique_symbol_date_rows']}"
        ),
        f"- Complete samples: {summary['complete_rows']}",
        f"- Partial samples: {summary['partial_rows']}",
        f"- Insufficient samples: {summary['insufficient_rows']}",
        (
            "- Samples still required for aggregate release: "
            f"{summary['completed_rows_to_minimum']}"
        ),
        (
            "- Aggregate outcomes released: "
            f"{summary['aggregate_outcomes_released']}"
        ),
        "",
        "## Event Samples",
        "",
    ]
    rows = payload["rows"][:_REPORT_ROW_LIMIT]
    if rows:
        lines.extend(
            [
                (
                    "| Symbol | Date | Conclusion | Green Families | "
                    "Events | Outcome | 1d | 2d | 5d | 10d | MFE | MAE |"
                ),
                (
                    "| --- | --- | --- | ---: | ---: | --- | ---: | "
                    "---: | ---: | ---: | ---: | ---: |"
                ),
            ]
        )
        for row in rows:
            confluence = row["confluence_summary"]
            returns = row["forward_returns_pct"]
            lines.append(
                f"| {row['symbol']} | {row['event_date']} | "
                f"{confluence['conclusion']} | "
                f"{confluence['independent_green_families']} / "
                f"{confluence['independent_total_families']} | "
                f"{row['event_count']} | {row['outcome_status']} | "
                f"{_display_pct(returns['1d'])} | "
                f"{_display_pct(returns['2d'])} | "
                f"{_display_pct(returns['5d'])} | "
                f"{_display_pct(returns['10d'])} | "
                f"{_display_pct(row['max_favorable_excursion_pct'])} | "
                f"{_display_pct(row['max_adverse_excursion_pct'])} |"
            )
    else:
        lines.append("- No eligible daily breakout samples were available.")

    lines.extend(["", "## Aggregate Outcomes", ""])
    aggregates = payload["aggregate_outcomes_by_conclusion"]
    if not aggregates:
        lines.append(
            "- Withheld until the minimum complete sample requirements pass."
        )
    else:
        lines.extend(
            [
                (
                    "| Conclusion | Samples | Mean 1d | Mean 2d | "
                    "Mean 5d | Mean 10d | Positive 10d | Mean MFE | "
                    "Mean MAE |"
                ),
                (
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | "
                    "---: | ---: |"
                ),
            ]
        )
        for conclusion, aggregate in sorted(aggregates.items()):
            mean_returns = aggregate["mean_forward_returns_pct"]
            positive_rates = aggregate[
                "positive_forward_return_rate_pct"
            ]
            lines.append(
                f"| {conclusion} | {aggregate['sample_count']} | "
                f"{_display_pct(mean_returns['1d'])} | "
                f"{_display_pct(mean_returns['2d'])} | "
                f"{_display_pct(mean_returns['5d'])} | "
                f"{_display_pct(mean_returns['10d'])} | "
                f"{_display_pct(positive_rates['10d'])} | "
                f"{_display_pct(aggregate['mean_max_favorable_excursion_pct'])} | "
                f"{_display_pct(aggregate['mean_max_adverse_excursion_pct'])} |"
            )

    lines.extend(["", "## Unavailable Event Groups", ""])
    unavailable = payload["unavailable_event_groups"][:_REPORT_ROW_LIMIT]
    if unavailable:
        lines.extend(
            (
                f"- {item['symbol']} {item['event_date']}: "
                f"{item['reason']}"
            )
            for item in unavailable
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Warnings", ""])
    if payload["warnings"]:
        lines.extend(f"- {warning}" for warning in payload["warnings"])
    else:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def ema_stack_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    required = options.ema_slow_window + 1
    if index < required - 1 or index >= len(bars):
        return indicator(
            "ema_stack",
            FAMILY_TREND,
            INSUFFICIENT_DATA,
            "primary signal",
            None,
            f"Need at least {required} bars for EMA stack and slope.",
        )
    fast = ema_at_index(bars, index, options.ema_fast_window)
    mid = ema_at_index(bars, index, options.ema_mid_window)
    slow = ema_at_index(bars, index, options.ema_slow_window)
    previous_mid = ema_at_index(bars, index - 1, options.ema_mid_window)
    if None in (fast, mid, slow, previous_mid):
        return indicator("ema_stack", FAMILY_TREND, INSUFFICIENT_DATA, "primary signal", None, "EMA value unavailable.")
    assert fast is not None and mid is not None and slow is not None and previous_mid is not None
    close = bars[index].close
    stacked = close > fast > mid > slow
    mid_slope_up = mid > previous_mid
    if stacked and mid_slope_up:
        state = GREEN
        reason = "Close is above fast/mid/slow EMAs and mid EMA slope is positive."
    elif close > mid and mid_slope_up:
        state = YELLOW
        reason = "Close is above mid EMA with positive slope, but full EMA stack is incomplete."
    else:
        state = RED
        reason = "EMA stack is not aligned."
    return indicator(
        "ema_stack",
        FAMILY_TREND,
        state,
        "primary signal",
        round(close - mid, 4),
        reason,
        details={
            "ema_fast": round_value(fast),
            "ema_mid": round_value(mid),
            "ema_slow": round_value(slow),
            "mid_slope_up": mid_slope_up,
        },
    )


def sma_position_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    minimum_bars = options.sma_mid_window
    if index < minimum_bars - 1 or index >= len(bars):
        return indicator(
            "sma_position",
            FAMILY_TREND,
            INSUFFICIENT_DATA,
            "primary signal",
            None,
            (
                f"Need at least {minimum_bars} completed bars for "
                "short/mid SMA structure."
            ),
        )
    short = rolling_sma(bars, index, options.sma_short_window)
    mid = rolling_sma(bars, index, options.sma_mid_window)
    long = rolling_sma(bars, index, options.sma_long_window)
    if short is None or mid is None:
        return indicator(
            "sma_position",
            FAMILY_TREND,
            INSUFFICIENT_DATA,
            "primary signal",
            None,
            "Short/mid SMA values are unavailable.",
        )
    close = bars[index].close
    short_mid_bullish = close > short > mid
    short_mid_bearish = close < short < mid
    full_history = long is not None
    full_bullish = short_mid_bullish and (
        long is None or mid > long
    )
    full_bearish = short_mid_bearish and (
        long is None or mid < long
    )
    if full_bullish:
        state = GREEN
        reason = (
            "Close and available SMA windows are bullishly aligned."
            if full_history
            else (
                "Close/SMA20/SMA50 are bullishly aligned; SMA200 is "
                "not yet available."
            )
        )
    elif full_bearish:
        state = RED
        reason = (
            "Close and available SMA windows are bearishly aligned."
            if full_history
            else (
                "Close/SMA20/SMA50 are bearishly aligned; SMA200 is "
                "not yet available."
            )
        )
    else:
        state = YELLOW
        reason = "Available SMA windows are not fully aligned."
    return indicator(
        "sma_position",
        FAMILY_TREND,
        state,
        "primary signal",
        round_value(close - short),
        reason,
        details={
            "close": round_value(close),
            "sma_short": round_value(short),
            "sma_mid": round_value(mid),
            "sma_long": round_value(long),
            "short_window": options.sma_short_window,
            "mid_window": options.sma_mid_window,
            "long_window": options.sma_long_window,
            "long_window_available": full_history,
            "short_mid_bullish": short_mid_bullish,
            "full_bullish": full_bullish and full_history,
        },
    )


def adx_trend_strength_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    value = adx_value(bars, index, options.adx_window)
    if value is None:
        return indicator(
            "adx_trend_strength",
            FAMILY_TREND,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            f"Need enough bars to calculate ADX{options.adx_window}.",
        )
    if value >= options.adx_green_threshold:
        state = GREEN
        reason = "ADX is above the research trend-strength threshold."
    elif value >= options.adx_yellow_threshold:
        state = YELLOW
        reason = "ADX is near trend-strength threshold."
    else:
        state = RED
        reason = "ADX does not confirm a strong trend."
    return indicator("adx_trend_strength", FAMILY_TREND, state, "confirmation signal", round_value(value), reason)


def anchored_vwap_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    anchor_index = options.anchored_vwap_anchor_index
    if anchor_index is None:
        return indicator(
            "anchored_vwap",
            FAMILY_TREND,
            UNAVAILABLE,
            "primary signal",
            None,
            "Anchored VWAP unavailable because no anchor event is defined.",
        )
    value = anchored_vwap(bars, anchor_index, index)
    if value is None:
        return indicator(
            "anchored_vwap",
            FAMILY_TREND,
            UNAVAILABLE,
            "primary signal",
            None,
            "Anchored VWAP unavailable because volume or anchor window is missing.",
        )
    ordered_bars = sorted_bars(bars)
    close = ordered_bars[index].close
    anchor_timestamp = ordered_bars[anchor_index].timestamp
    state = GREEN if close > value else RED
    reason = (
        f"Close is above anchored VWAP from {anchor_timestamp}."
        if state == GREEN
        else f"Close is not above anchored VWAP from {anchor_timestamp}."
    )
    return indicator(
        "anchored_vwap",
        FAMILY_TREND,
        state,
        "primary signal",
        round_value(value),
        reason,
        details={
            "anchor_index": anchor_index,
            "anchor_timestamp": anchor_timestamp,
        },
    )


def rsi_regime_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    minimum_bars = max(
        20,
        options.rsi_window + options.rsi_hold_bars + 1,
    )
    if index < minimum_bars - 1 or index >= len(bars):
        return indicator(
            "rsi_regime",
            FAMILY_MOMENTUM,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            f"Need at least {minimum_bars} completed bars for RSI regime.",
        )
    recent_values = [
        rsi_value(bars, offset, options.rsi_window)
        for offset in range(
            index - options.rsi_hold_bars + 1,
            index + 1,
        )
    ]
    if any(value is None for value in recent_values):
        return indicator(
            "rsi_regime",
            FAMILY_MOMENTUM,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            "RSI regime values are incomplete.",
        )
    values = [float(value) for value in recent_values if value is not None]
    held_floor = all(value > options.rsi_floor for value in values)
    reached_strength = max(values) >= options.rsi_reach
    if held_floor and reached_strength:
        state = GREEN
        reason = (
            "RSI held above the constructive floor and reached the "
            "research strength level."
        )
    elif held_floor:
        state = YELLOW
        reason = (
            "RSI held above the constructive floor but has not reached "
            "the research strength level."
        )
    else:
        state = RED
        reason = "RSI did not sustain the constructive momentum regime."
    return indicator(
        "rsi_regime",
        FAMILY_MOMENTUM,
        state,
        "confirmation signal",
        round_value(values[-1]),
        reason,
        details={
            "held_above_floor": held_floor,
            "reached_strength": reached_strength,
            "recent_values": [round_value(value) for value in values],
        },
    )


def macd_momentum_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    return _macd_like_momentum_state(
        bars,
        index,
        options=options or TechnicalConfluenceOptions(),
        percentage=False,
    )


def ppo_momentum_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    return _macd_like_momentum_state(
        bars,
        index,
        options=options or TechnicalConfluenceOptions(),
        percentage=True,
    )


def _macd_like_momentum_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions,
    percentage: bool,
) -> IndicatorState:
    name = "ppo_momentum" if percentage else "macd_momentum"
    minimum_bars = (
        options.macd_slow_window + options.macd_signal_window
    )
    current = macd_components(
        bars,
        index,
        options=options,
        percentage=percentage,
    )
    previous = macd_components(
        bars,
        index - 1,
        options=options,
        percentage=percentage,
    )
    if (
        index < minimum_bars - 1
        or current is None
        or previous is None
    ):
        return indicator(
            name,
            FAMILY_MOMENTUM,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            f"Need at least {minimum_bars} completed bars for {name}.",
        )
    current_line, current_signal, current_histogram = current
    previous_line, previous_signal, previous_histogram = previous
    crossed_above = (
        previous_line <= previous_signal
        and current_line > current_signal
    )
    histogram_expanding = (
        current_histogram > previous_histogram > 0
    )
    if crossed_above or histogram_expanding:
        state = GREEN
        reason = (
            f"{name} crossed above its signal or its positive histogram "
            "expanded for two completed bars."
        )
    elif current_line > current_signal or current_histogram > 0:
        state = YELLOW
        reason = f"{name} is positive but lacks a fresh acceleration event."
    else:
        state = RED
        reason = f"{name} does not confirm constructive momentum."
    return indicator(
        name,
        FAMILY_MOMENTUM,
        state,
        "confirmation signal",
        round_value(current_histogram),
        reason,
        details={
            "line": round_value(current_line),
            "signal": round_value(current_signal),
            "histogram": round_value(current_histogram),
            "crossed_above": crossed_above,
            "histogram_expanding": histogram_expanding,
            "percentage_based": percentage,
        },
    )


def rate_of_change_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    windows = (
        options.roc_short_window,
        options.roc_mid_window,
        options.roc_long_window,
    )
    minimum_bars = options.roc_long_window + 1
    if index < minimum_bars - 1 or index >= len(bars):
        return indicator(
            "rate_of_change",
            FAMILY_MOMENTUM,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            (
                f"Need at least {minimum_bars} completed bars for "
                f"{'/'.join(str(window) for window in windows)}-window ROC."
            ),
        )
    values = {
        str(window): return_pct(
            bars[index - window].close,
            bars[index].close,
        )
        for window in windows
    }
    if any(value is None for value in values.values()):
        return indicator(
            "rate_of_change",
            FAMILY_MOMENTUM,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            "ROC requires positive finite prices at every configured window.",
        )
    numeric_values = [
        float(value) for value in values.values() if value is not None
    ]
    if all(value > 0 for value in numeric_values):
        state = GREEN
        reason = "ROC is positive across all configured research windows."
    elif all(value < 0 for value in numeric_values):
        state = RED
        reason = "ROC is negative across all configured research windows."
    else:
        state = YELLOW
        reason = "ROC is mixed or neutral across configured research windows."
    rounded_values = {
        window: round_value(value)
        for window, value in values.items()
    }
    return indicator(
        "rate_of_change",
        FAMILY_MOMENTUM,
        state,
        "confirmation signal",
        rounded_values[str(options.roc_mid_window)],
        reason,
        details={
            "windows": list(windows),
            "returns_pct": rounded_values,
        },
    )


def squeeze_release_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    if index < options.keltner_atr_window + 2 or index >= len(bars):
        return indicator(
            "bollinger_keltner_squeeze_release",
            FAMILY_VOLATILITY,
            INSUFFICIENT_DATA,
            "primary signal",
            None,
            "Need enough bars for Bollinger/Keltner squeeze release.",
        )
    previous_bollinger = bollinger_bands_through_index(bars, index - 1, options)
    previous_keltner = keltner_bands_through_index(bars, index - 1, options)
    trigger_upper = max_or_none(
        prior_bollinger_upper_confluence(bars, index, options),
        prior_keltner_upper_confluence(bars, index, options),
    )
    if previous_bollinger is None or previous_keltner is None or trigger_upper is None:
        return indicator(
            "bollinger_keltner_squeeze_release",
            FAMILY_VOLATILITY,
            INSUFFICIENT_DATA,
            "primary signal",
            None,
            "Squeeze band values unavailable.",
        )
    bollinger_lower, bollinger_upper = previous_bollinger
    keltner_lower, keltner_upper = previous_keltner
    was_compressed = bollinger_lower >= keltner_lower and bollinger_upper <= keltner_upper
    released = was_compressed and bars[index].close > trigger_upper
    if released:
        state = GREEN
        reason = "Prior Bollinger Bands were inside Keltner Channels and close released above upper trigger."
    elif was_compressed:
        state = YELLOW
        reason = "Compression exists, but no upside release has occurred."
    else:
        state = RED
        reason = "No prior Bollinger/Keltner compression was detected."
    return indicator(
        "bollinger_keltner_squeeze_release",
        FAMILY_VOLATILITY,
        state,
        "primary signal",
        round_value(trigger_upper),
        reason,
        details={"was_compressed": was_compressed, "released": released},
    )


def volume_confirmation_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    value = relative_volume(sorted_bars(bars), index, options.volume_average_window)
    if value is None:
        return indicator(
            "relative_volume",
            FAMILY_VOLUME,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            "Need current volume and prior comparable volume window.",
        )
    if value >= options.volume_confirmation_multiple:
        state = GREEN
        reason = "Relative volume confirms participation."
    elif value >= 1.0:
        state = YELLOW
        reason = "Volume is above baseline but below confirmation threshold."
    else:
        state = RED
        reason = "Volume does not confirm participation."
    return indicator("relative_volume", FAMILY_VOLUME, state, "confirmation signal", value, reason)


def obv_new_high_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    minimum_bars = options.obv_long_window + 1
    values = obv_values(bars, index)
    if (
        index < minimum_bars - 1
        or index >= len(bars)
        or values is None
    ):
        return indicator(
            "obv_new_high",
            FAMILY_VOLUME,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            f"Need {minimum_bars} completed OHLCV bars for OBV new highs.",
        )
    current = values[index]
    prior_short = values[index - options.obv_short_window : index]
    prior_long = values[index - options.obv_long_window : index]
    short_high = current > max(prior_short)
    long_high = current > max(prior_long)
    if long_high:
        state = GREEN
        reason = "OBV reached a new long-window high."
    elif short_high:
        state = YELLOW
        reason = "OBV reached a new short-window high only."
    else:
        state = RED
        reason = "OBV did not reach a new participation high."
    return indicator(
        "obv_new_high",
        FAMILY_VOLUME,
        state,
        "confirmation signal",
        float(current),
        reason,
        details={
            "short_window_new_high": short_high,
            "long_window_new_high": long_high,
        },
    )


def money_flow_index_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    minimum_bars = max(20, options.mfi_window + 2)
    current = money_flow_index_value(bars, index, options.mfi_window)
    previous = money_flow_index_value(
        bars,
        index - 1,
        options.mfi_window,
    )
    if (
        index < minimum_bars - 1
        or current is None
        or previous is None
    ):
        return indicator(
            "money_flow_index",
            FAMILY_VOLUME,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            f"Need at least {minimum_bars} completed OHLCV bars for MFI.",
        )
    improving = current > previous
    if current > 50.0 and improving:
        state = GREEN
        reason = "MFI is improving above its constructive midpoint."
    elif current > 50.0 or improving:
        state = YELLOW
        reason = "MFI has only one constructive condition."
    else:
        state = RED
        reason = "MFI is not improving above its constructive midpoint."
    return indicator(
        "money_flow_index",
        FAMILY_VOLUME,
        state,
        "confirmation signal",
        round_value(current),
        reason,
        details={
            "previous": round_value(previous),
            "improving": improving,
        },
    )


def chaikin_money_flow_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    minimum_bars = options.cmf_window + 1
    value = chaikin_money_flow_value(
        bars,
        index,
        options.cmf_window,
    )
    if index < minimum_bars - 1 or value is None:
        return indicator(
            "chaikin_money_flow",
            FAMILY_VOLUME,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            f"Need {minimum_bars} completed OHLCV bars for CMF.",
        )
    if value > 0:
        state = GREEN
        reason = "CMF is positive."
    elif value < 0:
        state = RED
        reason = "CMF is negative."
    else:
        state = YELLOW
        reason = "CMF is neutral."
    return indicator(
        "chaikin_money_flow",
        FAMILY_VOLUME,
        state,
        "confirmation signal",
        round_value(value),
        reason,
    )


def accumulation_distribution_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    minimum_bars = options.accumulation_distribution_minimum_bars
    values = accumulation_distribution_values(bars, index)
    prior_index = index - options.accumulation_distribution_slope_window
    if (
        index < minimum_bars - 1
        or prior_index < 0
        or values is None
    ):
        return indicator(
            "accumulation_distribution_trend",
            FAMILY_VOLUME,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            (
                f"Need at least {minimum_bars} completed OHLCV bars "
                "for A/D trend."
            ),
        )
    current = values[index]
    prior = values[prior_index]
    delta = current - prior
    if delta > 0:
        state = GREEN
        reason = "The A/D line has a positive research-window slope."
    elif delta < 0:
        state = RED
        reason = "The A/D line has a negative research-window slope."
    else:
        state = YELLOW
        reason = "The A/D line is flat across the research window."
    return indicator(
        "accumulation_distribution_trend",
        FAMILY_VOLUME,
        state,
        "confirmation signal",
        round_value(delta),
        reason,
        details={
            "slope_window": options.accumulation_distribution_slope_window,
            "current_line": round_value(current),
            "prior_line": round_value(prior),
            "delta": round_value(delta),
        },
    )


def up_down_volume_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    windows = (
        options.up_down_volume_short_window,
        options.up_down_volume_long_window,
    )
    minimum_bars = options.up_down_volume_long_window + 1
    values = {
        str(window): up_down_volume_totals(bars, index, window)
        for window in windows
    }
    if (
        index < minimum_bars - 1
        or index >= len(bars)
        or any(value is None for value in values.values())
    ):
        return indicator(
            "up_down_volume",
            FAMILY_VOLUME,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            (
                f"Need at least {minimum_bars} completed bars with volume "
                "for up/down-volume comparison."
            ),
        )
    totals = {
        window: value
        for window, value in values.items()
        if value is not None
    }
    comparisons = [
        up_volume - down_volume
        for up_volume, down_volume in totals.values()
    ]
    if all(comparison > 0 for comparison in comparisons):
        state = GREEN
        reason = "Up-volume exceeds down-volume in both research windows."
    elif all(comparison < 0 for comparison in comparisons):
        state = RED
        reason = "Down-volume exceeds up-volume in both research windows."
    else:
        state = YELLOW
        reason = "Up/down-volume participation is mixed or neutral."
    details: dict[str, Any] = {"windows": list(windows), "totals": {}}
    for window, (up_volume, down_volume) in totals.items():
        ratio = (
            up_volume / down_volume
            if down_volume > 0
            else None
        )
        details["totals"][window] = {
            "up_volume": up_volume,
            "down_volume": down_volume,
            "ratio": round_value(ratio),
            "ratio_state": (
                "UP_ONLY"
                if up_volume > 0 and down_volume == 0
                else "NO_DIRECTIONAL_VOLUME"
                if up_volume == 0 and down_volume == 0
                else "FINITE"
            ),
        }
    mid_window = str(options.up_down_volume_long_window)
    mid_totals = details["totals"][mid_window]
    value: float | str | None = mid_totals["ratio"]
    if value is None:
        value = mid_totals["ratio_state"]
    return indicator(
        "up_down_volume",
        FAMILY_VOLUME,
        state,
        "confirmation signal",
        value,
        reason,
        details=details,
    )


def relative_strength_state(
    bars: list[TechnicalPriceBar],
    benchmark_bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    benchmark_bars = sorted_bars(benchmark_bars)
    if not benchmark_bars:
        return indicator(
            "relative_strength_vs_benchmark",
            FAMILY_RELATIVE_STRENGTH,
            UNAVAILABLE,
            "confirmation signal",
            None,
            "No benchmark bars supplied.",
        )
    if index < options.relative_strength_window or index >= len(bars):
        return indicator(
            "relative_strength_vs_benchmark",
            FAMILY_RELATIVE_STRENGTH,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            f"Need at least {options.relative_strength_window + 1} aligned stock bars.",
        )
    current_time = parse_datetime(bars[index].timestamp)
    start_time = parse_datetime(bars[index - options.relative_strength_window].timestamp)
    if current_time is None or start_time is None:
        return indicator(
            "relative_strength_vs_benchmark",
            FAMILY_RELATIVE_STRENGTH,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            "Could not parse stock timestamps.",
        )
    benchmark_current = matching_daily_index(benchmark_bars, current_time)
    benchmark_start = matching_daily_index(benchmark_bars, start_time)
    if benchmark_current is None or benchmark_start is None:
        return indicator(
            "relative_strength_vs_benchmark",
            FAMILY_RELATIVE_STRENGTH,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            "Benchmark bars are not aligned with stock bars.",
        )
    stock_start_close = bars[index - options.relative_strength_window].close
    benchmark_start_close = benchmark_bars[benchmark_start].close
    if stock_start_close <= 0 or benchmark_start_close <= 0:
        return indicator(
            "relative_strength_vs_benchmark",
            FAMILY_RELATIVE_STRENGTH,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            "Relative-strength starting prices must be positive.",
        )
    stock_return = return_pct(stock_start_close, bars[index].close)
    benchmark_return = return_pct(
        benchmark_start_close,
        benchmark_bars[benchmark_current].close,
    )
    spread = round_value(stock_return - benchmark_return)
    state = GREEN if stock_return > benchmark_return else RED
    reason = "Stock outperformed benchmark over the research window." if state == GREEN else "Stock did not outperform benchmark."
    return indicator(
        "relative_strength_vs_benchmark",
        FAMILY_RELATIVE_STRENGTH,
        state,
        "confirmation signal",
        spread,
        reason,
        details={"stock_return_pct": stock_return, "benchmark_return_pct": benchmark_return},
    )


def relative_strength_short_slope_state(
    bars: list[TechnicalPriceBar],
    benchmark_bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    return _relative_strength_slope_state(
        bars,
        benchmark_bars,
        index,
        window=options.relative_strength_window,
        minimum_aligned_bars=max(
            25,
            options.relative_strength_window + 1,
        ),
        name="relative_strength_short_slope",
    )


def relative_strength_long_slope_state(
    bars: list[TechnicalPriceBar],
    benchmark_bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    return _relative_strength_slope_state(
        bars,
        benchmark_bars,
        index,
        window=options.relative_strength_long_window,
        minimum_aligned_bars=max(
            65,
            options.relative_strength_long_window + 1,
        ),
        name="relative_strength_long_slope",
    )


def _relative_strength_slope_state(
    bars: list[TechnicalPriceBar],
    benchmark_bars: list[TechnicalPriceBar],
    index: int,
    *,
    window: int,
    minimum_aligned_bars: int,
    name: str,
) -> IndicatorState:
    bars = sorted_bars(bars)
    benchmark_bars = sorted_bars(benchmark_bars)
    if not benchmark_bars:
        return indicator(
            name,
            FAMILY_RELATIVE_STRENGTH,
            UNAVAILABLE,
            "confirmation signal",
            None,
            "No benchmark bars supplied.",
        )
    if index < minimum_aligned_bars - 1 or index >= len(bars):
        return indicator(
            name,
            FAMILY_RELATIVE_STRENGTH,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            (
                f"Need at least {minimum_aligned_bars} aligned bars "
                f"for {window}-session relative-strength slope."
            ),
        )
    start_index = index - minimum_aligned_bars + 1
    ratios = relative_strength_ratio_series(
        bars,
        benchmark_bars,
        start_index,
        index,
    )
    if ratios is None:
        return indicator(
            name,
            FAMILY_RELATIVE_STRENGTH,
            INSUFFICIENT_DATA,
            "confirmation signal",
            None,
            "Benchmark bars are not completely aligned with stock bars.",
        )
    start_ratio = ratios[-(window + 1)]
    current_ratio = ratios[-1]
    change = return_pct(start_ratio, current_ratio)
    if change > 0:
        state = GREEN
        reason = (
            f"Relative-strength ratio has a positive {window}-session slope."
        )
    elif change < 0:
        state = RED
        reason = (
            f"Relative-strength ratio has a negative {window}-session slope."
        )
    else:
        state = YELLOW
        reason = (
            f"Relative-strength ratio is flat over {window} sessions."
        )
    return indicator(
        name,
        FAMILY_RELATIVE_STRENGTH,
        state,
        "confirmation signal",
        round_value(change),
        reason,
        details={
            "window": window,
            "aligned_bars": len(ratios),
            "start_ratio": round_value(start_ratio),
            "current_ratio": round_value(current_ratio),
            "ratio_change_pct": round_value(change),
        },
    )


def relative_strength_new_high_state(
    bars: list[TechnicalPriceBar],
    benchmark_bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    benchmark_bars = sorted_bars(benchmark_bars)
    if not benchmark_bars:
        return indicator(
            "relative_strength_new_high",
            FAMILY_RELATIVE_STRENGTH,
            UNAVAILABLE,
            "primary confirmation",
            None,
            "No benchmark bars supplied.",
        )
    minimum_bars = max(25, options.relative_strength_window + 1)
    if index < minimum_bars - 1 or index >= len(bars):
        return indicator(
            "relative_strength_new_high",
            FAMILY_RELATIVE_STRENGTH,
            INSUFFICIENT_DATA,
            "primary confirmation",
            None,
            (
                f"Need at least {minimum_bars} aligned bars for "
                "relative-strength new-high research."
            ),
        )
    windows = (
        options.relative_strength_window,
        options.relative_strength_mid_window,
        options.relative_strength_long_window,
    )
    new_highs: dict[str, bool | None] = {}
    current_ratio: float | None = None
    for window in windows:
        if index < window:
            new_highs[str(window)] = None
            continue
        ratios = relative_strength_ratio_series(
            bars,
            benchmark_bars,
            index - window,
            index,
        )
        if ratios is None:
            return indicator(
                "relative_strength_new_high",
                FAMILY_RELATIVE_STRENGTH,
                INSUFFICIENT_DATA,
                "primary confirmation",
                None,
                "Benchmark bars are not completely aligned with stock bars.",
            )
        current_ratio = ratios[-1]
        new_highs[str(window)] = current_ratio > max(ratios[:-1])
    available = [
        value for value in new_highs.values() if value is not None
    ]
    if not available or current_ratio is None:
        return indicator(
            "relative_strength_new_high",
            FAMILY_RELATIVE_STRENGTH,
            INSUFFICIENT_DATA,
            "primary confirmation",
            None,
            "No configured relative-strength high window is available.",
        )
    if any(available):
        state = GREEN
        reason = "Relative-strength ratio reached a new configured-window high."
    else:
        state = RED
        reason = "Relative-strength ratio did not reach a new configured-window high."
    return indicator(
        "relative_strength_new_high",
        FAMILY_RELATIVE_STRENGTH,
        state,
        "primary confirmation",
        round_value(current_ratio),
        reason,
        details={
            "windows": list(windows),
            "new_highs": new_highs,
            "current_ratio": round_value(current_ratio),
        },
    )


def atr_extension_risk_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions | None = None,
) -> IndicatorState:
    options = options or TechnicalConfluenceOptions()
    bars = sorted_bars(bars)
    atr = prior_atr(bars, index, options.atr_extension_window)
    ema_mid = ema_at_index(bars, index, options.ema_mid_window)
    if atr is None or atr <= 0 or ema_mid is None or index >= len(bars):
        return indicator(
            "atr_extension_risk",
            FAMILY_RISK,
            INSUFFICIENT_DATA,
            "warning signal",
            None,
            "Need ATR and mid EMA to evaluate extension risk.",
        )
    extension = (bars[index].close - ema_mid) / atr
    if extension >= options.atr_extension_multiple:
        state = CAUTION
        reason = "Price is extended above mid EMA by multiple ATRs."
    else:
        state = CLEAR
        reason = "ATR-normalized extension is within research threshold."
    return indicator("atr_extension_risk", FAMILY_RISK, state, "warning signal", round_value(extension), reason)


def failed_breakout_state(
    *,
    symbol: str,
    breakout_events: list[BreakoutEvent],
    as_of: str | None = None,
) -> IndicatorState:
    as_of_time = parse_datetime(as_of)
    matching_events: list[tuple[tuple[int, int, int, int, int], BreakoutEvent]] = []
    for event in breakout_events:
        if event.symbol.upper() != symbol.upper():
            continue
        event_time = parse_datetime(event.event_timestamp)
        if event_time is None:
            continue
        event_key = _datetime_sort_key(event_time)
        if (
            as_of_time is not None
            and event_key > _datetime_sort_key(as_of_time)
        ):
            continue
        matching_events.append((event_key, event))
    matching_events.sort(key=lambda item: item[0])
    latest = matching_events[-1][1] if matching_events else None
    if matching_events:
        latest_key = matching_events[-1][0]
        latest_statuses = {
            event.status
            for event_key, event in matching_events
            if event_key == latest_key
        }
        if len(latest_statuses) > 1:
            return indicator(
                "failed_breakout",
                FAMILY_RISK,
                UNAVAILABLE,
                "blocker / gate",
                None,
                "Latest breakout context contains conflicting statuses.",
            )
    if latest is not None and latest.status == BREAKOUT_FAILED:
        return indicator(
            "failed_breakout",
            FAMILY_RISK,
            BLOCKED,
            "blocker / gate",
            True,
            "A breakout event failed back below its trigger.",
        )
    if latest is not None and latest.status == BREAKOUT_PRESENT:
        return indicator(
            "failed_breakout",
            FAMILY_RISK,
            CLEAR,
            "blocker / gate",
            False,
            "Breakout context is present and no failed breakout was supplied.",
        )
    return indicator(
        "failed_breakout",
        FAMILY_RISK,
        UNAVAILABLE,
        "blocker / gate",
        None,
        (
            "Latest breakout context is not a present or failed signal."
            if latest is not None
            else "No usable breakout context supplied."
        ),
    )


def build_family_states(indicators: list[IndicatorState]) -> dict[str, ConfluenceFamilyState]:
    grouped: dict[str, list[IndicatorState]] = {}
    for item in indicators:
        grouped.setdefault(item.family, []).append(item)
    family_states = {
        FAMILY_TREND: summarize_signal_family(FAMILY_TREND, grouped.get(FAMILY_TREND, [])),
        FAMILY_MOMENTUM: summarize_signal_family(
            FAMILY_MOMENTUM,
            grouped.get(FAMILY_MOMENTUM, []),
        ),
        FAMILY_VOLATILITY: summarize_signal_family(FAMILY_VOLATILITY, grouped.get(FAMILY_VOLATILITY, [])),
        FAMILY_VOLUME: summarize_signal_family(FAMILY_VOLUME, grouped.get(FAMILY_VOLUME, [])),
        FAMILY_RELATIVE_STRENGTH: summarize_signal_family(
            FAMILY_RELATIVE_STRENGTH, grouped.get(FAMILY_RELATIVE_STRENGTH, [])
        ),
        FAMILY_RISK: summarize_risk_family(grouped.get(FAMILY_RISK, [])),
        FAMILY_DATA_QUALITY: summarize_data_quality(indicators),
    }
    usable_signal_families = sum(
        1
        for family in (
            FAMILY_TREND,
            FAMILY_MOMENTUM,
            FAMILY_VOLATILITY,
            FAMILY_VOLUME,
            FAMILY_RELATIVE_STRENGTH,
        )
        if family_states[family].state not in {UNAVAILABLE, INSUFFICIENT_DATA}
    )
    if usable_signal_families < 2:
        family_states[FAMILY_DATA_QUALITY] = ConfluenceFamilyState(
            FAMILY_DATA_QUALITY,
            FAIL,
            "Fewer than two signal families have usable data.",
            [],
        )
    return family_states


def summarize_signal_family(family: str, indicators: list[IndicatorState]) -> ConfluenceFamilyState:
    names = [item.name for item in indicators]
    states = [
        item.state
        for item in indicators
        if item.state not in {UNAVAILABLE, INSUFFICIENT_DATA}
    ]
    if not states:
        return ConfluenceFamilyState(family, INSUFFICIENT_DATA, "No sufficient indicators in family.", names)
    if GREEN in states and RED not in states:
        return ConfluenceFamilyState(
            family,
            GREEN,
            "At least one family indicator confirms and none contradict.",
            names,
        )
    if all(state == RED for state in states):
        return ConfluenceFamilyState(family, RED, "Family indicators do not confirm.", names)
    return ConfluenceFamilyState(
        family,
        YELLOW,
        "Usable family indicators are mixed or early.",
        names,
    )


def summarize_risk_family(indicators: list[IndicatorState]) -> ConfluenceFamilyState:
    names = [item.name for item in indicators]
    states = [item.state for item in indicators]
    if BLOCKED in states:
        return ConfluenceFamilyState(FAMILY_RISK, BLOCKED, "At least one risk gate is blocked.", names)
    if CAUTION in states:
        return ConfluenceFamilyState(FAMILY_RISK, CAUTION, "At least one risk warning is present.", names)
    usable = [
        state
        for state in states
        if state not in {UNAVAILABLE, INSUFFICIENT_DATA}
    ]
    if not usable:
        return ConfluenceFamilyState(
            FAMILY_RISK,
            UNAVAILABLE,
            "No usable risk indicators were supplied.",
            names,
        )
    if any(state in {UNAVAILABLE, INSUFFICIENT_DATA} for state in states):
        return ConfluenceFamilyState(
            FAMILY_RISK,
            PARTIAL,
            "Available risk indicators are clear, but some risk data is unavailable.",
            names,
        )
    return ConfluenceFamilyState(
        FAMILY_RISK,
        CLEAR,
        "All supplied risk indicators are clear.",
        names,
    )


def summarize_data_quality(indicators: list[IndicatorState]) -> ConfluenceFamilyState:
    states = [item.state for item in indicators]
    if not indicators or all(state == INSUFFICIENT_DATA for state in states):
        return ConfluenceFamilyState(FAMILY_DATA_QUALITY, FAIL, "No sufficient indicator data.", [])
    if any(state in {UNAVAILABLE, INSUFFICIENT_DATA} for state in states):
        return ConfluenceFamilyState(FAMILY_DATA_QUALITY, PARTIAL, "Some indicators lack sufficient data.", [])
    return ConfluenceFamilyState(FAMILY_DATA_QUALITY, PASS, "All evaluated indicators have usable data.", [])


def confluence_conclusion(
    *,
    independent_green_families: int,
    independent_total_families: int,
    major_red_flags: int,
    warning_flags: int,
    data_quality_state: str,
) -> str:
    if data_quality_state == FAIL or independent_total_families < 2:
        return INSUFFICIENT_DATA
    if major_red_flags:
        return CONFLICTED_CONFLUENCE
    if independent_green_families >= 4 and warning_flags <= 1:
        return STRONG_CONFLUENCE
    if independent_green_families >= 3:
        return MODERATE_CONFLUENCE
    if independent_green_families >= 1:
        return WEAK_CONFLUENCE
    return CONFLICTED_CONFLUENCE


def ema_at_index(bars: list[TechnicalPriceBar], index: int, window: int) -> float | None:
    if index < window - 1 or index >= len(bars):
        return None
    closes = [bar.close for bar in sorted_bars(bars)[: index + 1]]
    multiplier = 2.0 / (window + 1)
    value = closes[0]
    for close in closes[1:]:
        value = close * multiplier + value * (1.0 - multiplier)
    return value


def relative_strength_ratio_series(
    bars: list[TechnicalPriceBar],
    benchmark_bars: list[TechnicalPriceBar],
    start_index: int,
    end_index: int,
) -> list[float] | None:
    bars = sorted_bars(bars)
    benchmark_bars = sorted_bars(benchmark_bars)
    if (
        start_index < 0
        or end_index < start_index
        or end_index >= len(bars)
    ):
        return None
    ratios: list[float] = []
    for stock_bar in bars[start_index : end_index + 1]:
        stock_time = parse_datetime(stock_bar.timestamp)
        if stock_time is None or stock_bar.close <= 0:
            return None
        benchmark_index = matching_daily_index(
            benchmark_bars,
            stock_time,
        )
        if benchmark_index is None:
            return None
        benchmark_close = benchmark_bars[benchmark_index].close
        if benchmark_close <= 0:
            return None
        ratios.append(stock_bar.close / benchmark_close)
    return ratios


def rsi_value(
    bars: list[TechnicalPriceBar],
    index: int,
    window: int,
) -> float | None:
    bars = sorted_bars(bars)
    if index < window or index >= len(bars):
        return None
    changes = [
        bars[offset].close - bars[offset - 1].close
        for offset in range(1, index + 1)
    ]
    initial = changes[:window]
    average_gain = sum(max(change, 0.0) for change in initial) / window
    average_loss = sum(max(-change, 0.0) for change in initial) / window
    for change in changes[window:]:
        average_gain = (
            average_gain * (window - 1) + max(change, 0.0)
        ) / window
        average_loss = (
            average_loss * (window - 1) + max(-change, 0.0)
        ) / window
    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    if average_gain == 0:
        return 0.0
    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def macd_components(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: TechnicalConfluenceOptions,
    percentage: bool,
) -> tuple[float, float, float] | None:
    bars = sorted_bars(bars)
    if index < 0 or index >= len(bars):
        return None
    closes = [bar.close for bar in bars[: index + 1]]
    fast_values = exponential_moving_average_values(
        closes,
        options.macd_fast_window,
    )
    slow_values = exponential_moving_average_values(
        closes,
        options.macd_slow_window,
    )
    oscillator_values: list[float] = []
    oscillator_indexes: list[int] = []
    for offset, (fast, slow) in enumerate(
        zip(fast_values, slow_values)
    ):
        if fast is None or slow is None:
            continue
        if percentage:
            if slow <= 0:
                return None
            oscillator = (fast - slow) / slow * 100.0
        else:
            oscillator = fast - slow
        oscillator_values.append(oscillator)
        oscillator_indexes.append(offset)
    signal_values = exponential_moving_average_values(
        oscillator_values,
        options.macd_signal_window,
    )
    by_index = {
        original_index: (oscillator, signal)
        for original_index, oscillator, signal in zip(
            oscillator_indexes,
            oscillator_values,
            signal_values,
        )
        if signal is not None
    }
    current = by_index.get(index)
    if current is None:
        return None
    oscillator, signal = current
    return oscillator, signal, oscillator - signal


def exponential_moving_average_values(
    values: list[float],
    window: int,
) -> list[float | None]:
    if not values:
        return []
    multiplier = 2.0 / (window + 1)
    current = float(values[0])
    results: list[float | None] = []
    for offset, value in enumerate(values):
        if offset:
            current = float(value) * multiplier + current * (
                1.0 - multiplier
            )
        results.append(current if offset >= window - 1 else None)
    return results


def obv_values(
    bars: list[TechnicalPriceBar],
    index: int,
) -> list[int] | None:
    bars = sorted_bars(bars)
    if index < 0 or index >= len(bars):
        return None
    selected = bars[: index + 1]
    if any(bar.volume is None for bar in selected):
        return None
    values = [0]
    for offset in range(1, len(selected)):
        volume = selected[offset].volume
        assert volume is not None
        current = values[-1]
        if selected[offset].close > selected[offset - 1].close:
            current += volume
        elif selected[offset].close < selected[offset - 1].close:
            current -= volume
        values.append(current)
    return values


def money_flow_index_value(
    bars: list[TechnicalPriceBar],
    index: int,
    window: int,
) -> float | None:
    bars = sorted_bars(bars)
    if index < window or index >= len(bars):
        return None
    selected = bars[index - window : index + 1]
    if any(bar.volume is None for bar in selected):
        return None
    typical_prices = [
        (bar.high + bar.low + bar.close) / 3.0
        for bar in selected
    ]
    positive_flow = 0.0
    negative_flow = 0.0
    for offset in range(1, len(selected)):
        volume = selected[offset].volume
        assert volume is not None
        raw_flow = typical_prices[offset] * volume
        if typical_prices[offset] > typical_prices[offset - 1]:
            positive_flow += raw_flow
        elif typical_prices[offset] < typical_prices[offset - 1]:
            negative_flow += raw_flow
    if positive_flow == 0 and negative_flow == 0:
        return 50.0
    if negative_flow == 0:
        return 100.0
    if positive_flow == 0:
        return 0.0
    ratio = positive_flow / negative_flow
    return 100.0 - (100.0 / (1.0 + ratio))


def chaikin_money_flow_value(
    bars: list[TechnicalPriceBar],
    index: int,
    window: int,
) -> float | None:
    bars = sorted_bars(bars)
    if index < window - 1 or index >= len(bars):
        return None
    selected = bars[index - window + 1 : index + 1]
    if any(bar.volume is None for bar in selected):
        return None
    total_volume = sum(
        int(bar.volume)
        for bar in selected
        if bar.volume is not None
    )
    if total_volume <= 0:
        return None
    money_flow_volume = 0.0
    for bar in selected:
        volume = bar.volume
        assert volume is not None
        spread = bar.high - bar.low
        multiplier = (
            0.0
            if spread == 0
            else (
                (bar.close - bar.low) - (bar.high - bar.close)
            )
            / spread
        )
        money_flow_volume += multiplier * volume
    return money_flow_volume / total_volume


def accumulation_distribution_values(
    bars: list[TechnicalPriceBar],
    index: int,
) -> list[float] | None:
    bars = sorted_bars(bars)
    if index < 0 or index >= len(bars):
        return None
    selected = bars[: index + 1]
    if any(bar.volume is None for bar in selected):
        return None
    values: list[float] = []
    current = 0.0
    for bar in selected:
        volume = bar.volume
        assert volume is not None
        spread = bar.high - bar.low
        multiplier = (
            0.0
            if spread == 0
            else (
                (bar.close - bar.low) - (bar.high - bar.close)
            )
            / spread
        )
        current += multiplier * volume
        values.append(current)
    return values


def up_down_volume_totals(
    bars: list[TechnicalPriceBar],
    index: int,
    window: int,
) -> tuple[int, int] | None:
    bars = sorted_bars(bars)
    if index < window or index >= len(bars):
        return None
    selected = bars[index - window : index + 1]
    if any(bar.volume is None for bar in selected[1:]):
        return None
    up_volume = 0
    down_volume = 0
    for offset in range(1, len(selected)):
        volume = selected[offset].volume
        assert volume is not None
        if selected[offset].close > selected[offset - 1].close:
            up_volume += volume
        elif selected[offset].close < selected[offset - 1].close:
            down_volume += volume
    return up_volume, down_volume


def adx_value(bars: list[TechnicalPriceBar], index: int, window: int) -> float | None:
    bars = sorted_bars(bars)
    if index < (window * 2) or index >= len(bars):
        return None
    true_ranges: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for position in range(1, index + 1):
        current = bars[position]
        previous = bars[position - 1]
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        true_ranges.append(true_range(current, previous))
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
    dx_values: list[float] = []
    for end in range(window - 1, len(true_ranges)):
        start = end - window + 1
        tr_sum = sum(true_ranges[start : end + 1])
        if tr_sum <= 0:
            dx_values.append(0.0)
            continue
        plus_di = 100.0 * sum(plus_dm[start : end + 1]) / tr_sum
        minus_di = 100.0 * sum(minus_dm[start : end + 1]) / tr_sum
        denominator = plus_di + minus_di
        dx_values.append(0.0 if denominator <= 0 else 100.0 * abs(plus_di - minus_di) / denominator)
    if len(dx_values) < window:
        return None
    return mean(dx_values[-window:])


def anchored_vwap(bars: list[TechnicalPriceBar], anchor_index: int, index: int) -> float | None:
    bars = sorted_bars(bars)
    if anchor_index < 0 or index < anchor_index or index >= len(bars):
        return None
    cumulative_volume = 0
    cumulative_price_volume = 0.0
    for bar in bars[anchor_index : index + 1]:
        volume = bar.volume or 0
        if volume <= 0:
            continue
        typical_price = (bar.high + bar.low + bar.close) / 3.0
        cumulative_volume += volume
        cumulative_price_volume += typical_price * volume
    if cumulative_volume <= 0:
        return None
    return cumulative_price_volume / cumulative_volume


def bollinger_bands_through_index(
    bars: list[TechnicalPriceBar],
    index: int,
    options: TechnicalConfluenceOptions,
) -> tuple[float, float] | None:
    if index < options.bollinger_window - 1 or index >= len(bars):
        return None
    closes = [bar.close for bar in bars[index - options.bollinger_window + 1 : index + 1]]
    center = mean(closes)
    spread = pstdev(closes) * options.bollinger_stddevs
    return center - spread, center + spread


def keltner_bands_through_index(
    bars: list[TechnicalPriceBar],
    index: int,
    options: TechnicalConfluenceOptions,
) -> tuple[float, float] | None:
    if index < options.keltner_atr_window + 1 or index >= len(bars):
        return None
    closes = [bar.close for bar in bars[index - options.keltner_atr_window + 1 : index + 1]]
    atr = mean([true_range(bars[position], bars[position - 1]) for position in range(index - options.keltner_atr_window + 1, index + 1)])
    center = mean(closes)
    spread = atr * options.keltner_atr_multiple
    return center - spread, center + spread


def prior_bollinger_upper_confluence(
    bars: list[TechnicalPriceBar],
    index: int,
    options: TechnicalConfluenceOptions,
) -> float | None:
    if index < options.bollinger_window:
        return None
    closes = [bar.close for bar in bars[index - options.bollinger_window : index]]
    center = mean(closes)
    return center + options.bollinger_stddevs * pstdev(closes)


def prior_keltner_upper_confluence(
    bars: list[TechnicalPriceBar],
    index: int,
    options: TechnicalConfluenceOptions,
) -> float | None:
    breakout_options = _breakout_options_from_confluence(options)
    return prior_keltner_upper(bars, index, breakout_options)


def _breakout_options_from_confluence(options: TechnicalConfluenceOptions) -> Any:
    from momentum_hunter.technical_breakouts import BreakoutResearchOptions

    return BreakoutResearchOptions(
        bollinger_window=options.bollinger_window,
        bollinger_stddevs=options.bollinger_stddevs,
        atr_window=options.keltner_atr_window,
        atr_multiple=options.keltner_atr_multiple,
        volume_average_window=options.volume_average_window,
        volume_confirmation_multiple=options.volume_confirmation_multiple,
        relative_strength_window=options.relative_strength_window,
    )


def max_or_none(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def indicator(
    name: str,
    family: str,
    state: str,
    role: str,
    value: float | str | bool | None,
    reason: str,
    *,
    data_sufficiency: str | None = None,
    details: dict[str, Any] | None = None,
) -> IndicatorState:
    if data_sufficiency is None:
        data_sufficiency = (
            state
            if state in {UNAVAILABLE, INSUFFICIENT_DATA}
            else "Sufficient"
        )
    return IndicatorState(
        name=name,
        family=family,
        state=state,
        role=role,
        value=value,
        reason=reason,
        data_sufficiency=data_sufficiency,
        details=details or {},
    )


def round_value(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def _finite_number_or_none(value: Any) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(float(value))
    ):
        return None
    return round(float(value), 4)


def _same_optional_number(left: Any, right: Any) -> bool:
    left_number = _finite_number_or_none(left)
    right_number = _finite_number_or_none(right)
    if left_number is None or right_number is None:
        return left_number is None and right_number is None
    return left_number == right_number


def _display_pct(value: Any) -> str:
    number = _finite_number_or_none(value)
    return "N/A" if number is None else f"{number:.4f}%"


def _validate_price_bars(
    bars: list[TechnicalPriceBar],
    *,
    expected_symbol: str | None,
    source_label: str,
) -> None:
    seen_timestamps: set[str] = set()
    observed_symbols: set[str] = set()
    for bar in bars:
        symbol = str(bar.symbol).upper().strip()
        if not symbol:
            raise TechnicalConfluenceError(
                f"{source_label.capitalize()} bars require a symbol."
            )
        observed_symbols.add(symbol)
        if expected_symbol is not None and symbol != expected_symbol:
            raise TechnicalConfluenceError(
                f"{source_label.capitalize()} bars contain a different symbol."
            )
        parsed_timestamp = parse_datetime(bar.timestamp)
        if parsed_timestamp is None:
            raise TechnicalConfluenceError(
                f"{source_label.capitalize()} bars contain an invalid timestamp."
            )
        timestamp_identity = _timestamp_identity(parsed_timestamp)
        if timestamp_identity in seen_timestamps:
            raise TechnicalConfluenceError(
                f"{source_label.capitalize()} bars contain duplicate timestamps."
            )
        seen_timestamps.add(timestamp_identity)
        prices = (bar.open, bar.high, bar.low, bar.close)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
            or float(value) <= 0
            for value in prices
        ):
            raise TechnicalConfluenceError(
                f"{source_label.capitalize()} bars contain invalid prices."
            )
        if bar.high < max(bar.open, bar.close) or bar.low > min(
            bar.open,
            bar.close,
        ) or bar.high < bar.low:
            raise TechnicalConfluenceError(
                f"{source_label.capitalize()} bars contain invalid OHLC geometry."
            )
        if (
            bar.volume is not None
            and (
                isinstance(bar.volume, bool)
                or not isinstance(bar.volume, int)
                or bar.volume < 0
            )
        ):
            raise TechnicalConfluenceError(
                f"{source_label.capitalize()} bars contain invalid volume."
            )
    if len(observed_symbols) > 1:
        raise TechnicalConfluenceError(
            f"{source_label.capitalize()} bars contain multiple symbols."
        )


def _timestamp_identity(value: datetime) -> str:
    if value.tzinfo is not None and value.utcoffset() is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None).isoformat()


def _datetime_sort_key(value: datetime) -> tuple[int, int, int, int, int]:
    return (
        value.date().toordinal(),
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
    )


def _write_report_text(path: Path, content: str) -> None:
    temporary = path.with_name(
        f".{path.name}.{uuid4().hex}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_report_target(
    path: Path,
    *,
    format_name: str,
    artifact_type: str,
    markdown_heading: str,
) -> None:
    if path.is_symlink():
        raise TechnicalConfluenceError(
            "Confluence report target cannot be a symbolic link."
        )
    if not path.exists():
        return
    if not path.is_file():
        raise TechnicalConfluenceError(
            "Confluence report target must be a regular file."
        )
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TechnicalConfluenceError(
            "Existing confluence report target cannot be verified."
        ) from exc
    if format_name == "json":
        try:
            payload = json.loads(current)
        except json.JSONDecodeError as exc:
            raise TechnicalConfluenceError(
                "Existing JSON target is not a generated confluence report."
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("artifact_type")
            != artifact_type
            or payload.get("research_only") is not True
        ):
            raise TechnicalConfluenceError(
                "Existing JSON target is not a generated confluence report."
            )
        return
    if format_name != "markdown":
        raise TechnicalConfluenceError(
            "Confluence report format must be JSON or Markdown."
        )
    if not current.startswith(markdown_heading):
        raise TechnicalConfluenceError(
            "Existing Markdown target is not a generated confluence report."
        )


def _validate_output_payload(
    payload: dict[str, Any],
    *,
    artifact_type: str,
) -> None:
    if (
        not isinstance(payload, dict)
        or payload.get("artifact_type") != artifact_type
        or payload.get("research_only") is not True
        or parse_datetime(str(payload.get("generated_at", ""))) is None
    ):
        raise TechnicalConfluenceError(
            "Confluence output payload identity is invalid."
        )
