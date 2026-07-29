from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import isfinite
from statistics import mean, pstdev
from typing import Any

from momentum_hunter.technical_breakouts import (
    BREAKOUT_FAILED,
    BREAKOUT_PRESENT,
    INSUFFICIENT_DATA,
    BreakoutEvent,
    TechnicalPriceBar,
    matching_daily_index,
    parse_datetime,
    prior_atr,
    prior_keltner_upper,
    relative_volume,
    return_pct,
    sorted_bars,
    true_range,
)


TECHNICAL_CONFLUENCE_ENGINE_VERSION = "technical_confluence_research_v1"
TECHNICAL_CONFLUENCE_SCHEMA_VERSION = 1

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
    atr_extension_window: int = 14
    atr_extension_multiple: float = 2.5
    anchored_vwap_anchor_index: int = 0

    def __post_init__(self) -> None:
        windows = {
            "EMA fast window": self.ema_fast_window,
            "EMA mid window": self.ema_mid_window,
            "EMA slow window": self.ema_slow_window,
            "ADX window": self.adx_window,
            "Bollinger window": self.bollinger_window,
            "Keltner ATR window": self.keltner_atr_window,
            "Volume average window": self.volume_average_window,
            "Relative-strength window": self.relative_strength_window,
            "ATR extension window": self.atr_extension_window,
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
        numeric_options = {
            "ADX green threshold": self.adx_green_threshold,
            "ADX yellow threshold": self.adx_yellow_threshold,
            "Bollinger standard-deviation multiple": self.bollinger_stddevs,
            "Keltner ATR multiple": self.keltner_atr_multiple,
            "Volume confirmation multiple": (
                self.volume_confirmation_multiple
            ),
            "ATR extension multiple": self.atr_extension_multiple,
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
        if (
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
    if not normalized_symbol:
        raise TechnicalConfluenceError("Confluence symbol is required.")
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
        adx_trend_strength_state(ordered_bars, index, options=options),
        anchored_vwap_state(ordered_bars, index, options=options),
        squeeze_release_state(ordered_bars, index, options=options),
        volume_confirmation_state(ordered_bars, index, options=options),
        relative_strength_state(ordered_bars, benchmark_bars or [], index, options=options),
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
    signal_families = [FAMILY_TREND, FAMILY_VOLATILITY, FAMILY_VOLUME, FAMILY_RELATIVE_STRENGTH]
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
    value = anchored_vwap(bars, options.anchored_vwap_anchor_index, index)
    if value is None:
        return indicator(
            "anchored_vwap",
            FAMILY_TREND,
            UNAVAILABLE,
            "primary signal",
            None,
            "Anchored VWAP unavailable because volume or anchor window is missing.",
        )
    close = sorted_bars(bars)[index].close
    state = GREEN if close > value else RED
    reason = "Close is above anchored VWAP." if state == GREEN else "Close is not above anchored VWAP."
    return indicator("anchored_vwap", FAMILY_TREND, state, "primary signal", round_value(value), reason)


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
        for family in (FAMILY_TREND, FAMILY_VOLATILITY, FAMILY_VOLUME, FAMILY_RELATIVE_STRENGTH)
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
    if all(state == GREEN for state in states):
        return ConfluenceFamilyState(
            family,
            GREEN,
            "All usable family indicators are green.",
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
