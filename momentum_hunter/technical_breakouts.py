from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.canonical_candle_evidence import load_canonical_minute_bars
from momentum_hunter.daily_ohlc import (
    DAILY_OHLC_COVERAGE_LATEST_JSON,
    DAILY_OHLC_COVERAGE_LATEST_MD,
    DAILY_OHLC_SOURCE_PATH,
    DailyOhlcRecord,
    build_daily_ohlc_coverage_report,
    load_daily_ohlc_records,
    write_daily_ohlc_coverage_report,
)
from momentum_hunter.time_utils import now_central
from momentum_hunter.schwab_candle_store import SCHWAB_CANDLE_STORE_ROOT


ENGINE_VERSION = "technical_breakout_research_engine_v2"
SCHEMA_VERSION = 1

ANALYSIS_CAPTURES_PATH = DATA_DIR / "analysis-captures.csv"
ANALYSIS_OUTCOMES_PATH = DATA_DIR / "analysis-outcomes.csv"
OPPORTUNITY_ALERTS_PATH = DATA_DIR / "opportunity-alerts.json"

TECHNICAL_BREAKOUT_EVENTS_LATEST_JSON = DATA_DIR / "reports" / "technical-breakout-events-latest.json"
TECHNICAL_BREAKOUT_EVENTS_LATEST_MD = DATA_DIR / "reports" / "technical-breakout-events-latest.md"
TECHNICAL_BREAKOUT_STUDY_LATEST_JSON = DATA_DIR / "reports" / "technical-breakout-study-latest.json"
TECHNICAL_BREAKOUT_STUDY_LATEST_MD = DATA_DIR / "reports" / "technical-breakout-study-latest.md"

BREAKOUT_PRESENT = "Breakout present"
BREAKOUT_ABSENT = "Breakout absent"
BREAKOUT_FAILED = "Breakout failed"
BREAKOUT_UNCONFIRMED = "Breakout unconfirmed"
INSUFFICIENT_DATA = "Insufficient data"

DAILY_HORIZONS = (1, 2, 5, 10)
INTRADAY_HORIZONS = (5, 15, 30, 60)


@dataclass(frozen=True)
class TechnicalPriceBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None
    source: str = "technical_research"


@dataclass(frozen=True)
class BreakoutResearchOptions:
    donchian_windows: tuple[int, ...] = (20, 30, 50)
    sma_short_window: int = 20
    sma_long_window: int = 50
    bollinger_window: int = 20
    bollinger_stddevs: float = 2.0
    atr_window: int = 20
    atr_multiple: float = 1.5
    volume_average_window: int = 20
    volume_confirmation_multiple: float = 1.5
    relative_strength_window: int = 5
    opening_range_minutes: int = 30
    extension_fallback_pct: float = 5.0


@dataclass(frozen=True)
class BreakoutEvent:
    event_id: str
    symbol: str
    event_timestamp: str
    event_type: str
    timeframe: str
    trigger_price: float | None
    reference_label: str
    prior_high_band_or_moving_average_value: float | None
    distance_above_trigger_pct: float | None
    volume: int | None
    relative_volume: float | None
    market_regime: str | None
    source_data: str
    data_sufficiency: str
    quality_flag: str
    status: str
    volume_confirmed: bool | None = None
    relative_strength_confirmed: bool | None = None
    notes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BreakoutStudyResult:
    event_id: str
    symbol: str
    event_timestamp: str
    event_type: str
    timeframe: str
    trigger_price: float | None
    forward_returns_pct: dict[str, float | None]
    max_favorable_excursion_pct: float | None
    max_adverse_excursion_pct: float | None
    held_above_breakout_level: bool | None
    failed_back_below_breakout_level: bool | None
    volume_confirmed: bool | None
    became_extended: bool | None
    data_sufficiency: str
    status: str
    notes: list[str] = field(default_factory=list)


def build_technical_breakout_reports(
    *,
    captures_path: Path = ANALYSIS_CAPTURES_PATH,
    outcomes_path: Path = ANALYSIS_OUTCOMES_PATH,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path | None = None,
    minute_store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
    daily_bars_path: Path | None = None,
    daily_ohlc_path: Path | None = DAILY_OHLC_SOURCE_PATH,
    output_dir: Path | None = None,
    generated_at: str | None = None,
    options: BreakoutResearchOptions | None = None,
) -> dict[str, Path]:
    options = options or BreakoutResearchOptions()
    generated_at = generated_at or now_central().isoformat()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)

    captures = load_csv_rows(captures_path)
    outcomes = load_csv_rows(outcomes_path)
    alerts = load_json_records(alerts_path, "alerts")
    if minute_bars_path is not None:
        minute_bars_by_symbol = load_bar_source(
            minute_bars_path,
            default_source="explicit-minute-bar-fixture",
        )
        minute_source_path = minute_bars_path
        minute_source_name = "explicit-minute-bar-fixture"
    else:
        canonical = load_canonical_minute_bars(store_root=minute_store_root)
        minute_bars_by_symbol = {
            symbol: [
                TechnicalPriceBar(
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=int(bar.volume) if bar.volume.is_integer() else None,
                    source=bar.source,
                )
                for bar in bars
            ]
            for symbol, bars in canonical.items()
        }
        minute_source_path = minute_store_root
        minute_source_name = "schwab-reconciled-minute-store-v1"
    requested_symbols = tracked_symbols(captures, alerts, minute_bars_by_symbol)
    if "QQQ" not in requested_symbols:
        requested_symbols.append("QQQ")
    daily_ohlc_result = None
    if daily_bars_path:
        daily_bars_by_symbol = load_bar_source(daily_bars_path, default_source="daily-bars")
    elif daily_ohlc_path:
        daily_ohlc_result = load_daily_ohlc_records(daily_ohlc_path, requested_symbols=requested_symbols, generated_at=generated_at)
        daily_bars_by_symbol = daily_ohlc_records_to_technical_bars(daily_ohlc_result.valid_records)
    else:
        daily_bars_by_symbol = {}

    events = detect_breakout_events(
        daily_bars_by_symbol=daily_bars_by_symbol,
        minute_bars_by_symbol=minute_bars_by_symbol,
        captures=captures,
        alerts=alerts,
        options=options,
        minute_source_data=minute_source_name,
    )
    studies = study_breakout_events(
        [event for event in events if event.status == BREAKOUT_PRESENT],
        daily_bars_by_symbol=daily_bars_by_symbol,
        minute_bars_by_symbol=minute_bars_by_symbol,
        options=options,
    )

    source_paths = {
        "captures_path": str(captures_path),
        "outcomes_path": str(outcomes_path),
        "alerts_path": str(alerts_path),
        "minute_bars_path": str(minute_source_path),
        "minute_bars_source_kind": minute_source_name,
        "daily_bars_path": str(daily_bars_path) if daily_bars_path else None,
        "daily_ohlc_path": str(daily_ohlc_path) if daily_ohlc_path else None,
    }
    event_payload = build_event_report_payload(
        generated_at=generated_at,
        source_paths=source_paths,
        events=events,
        captures_seen=len(captures),
        outcomes_seen=len(outcomes),
        alerts_seen=len(alerts),
        daily_symbols=len(daily_bars_by_symbol),
        daily_ohlc_valid_records=len(daily_ohlc_result.valid_records) if daily_ohlc_result else None,
        daily_ohlc_invalid_records=len(daily_ohlc_result.invalid_records) if daily_ohlc_result else None,
        minute_symbols=len(minute_bars_by_symbol),
    )
    study_payload = build_study_report_payload(
        generated_at=generated_at,
        source_paths=source_paths,
        events=events,
        studies=studies,
    )

    event_json = output_dir / TECHNICAL_BREAKOUT_EVENTS_LATEST_JSON.name
    event_md = output_dir / TECHNICAL_BREAKOUT_EVENTS_LATEST_MD.name
    study_json = output_dir / TECHNICAL_BREAKOUT_STUDY_LATEST_JSON.name
    study_md = output_dir / TECHNICAL_BREAKOUT_STUDY_LATEST_MD.name
    write_json(event_payload, event_json)
    write_markdown_event_report(event_payload, event_md)
    write_json(study_payload, study_json)
    write_markdown_study_report(study_payload, study_md)
    paths = {
        "events_json": event_json,
        "events_markdown": event_md,
        "study_json": study_json,
        "study_markdown": study_md,
    }
    if daily_ohlc_result is not None:
        coverage_report = build_daily_ohlc_coverage_report(daily_ohlc_result, requested_symbols=requested_symbols)
        coverage_paths = write_daily_ohlc_coverage_report(
            coverage_report,
            json_path=output_dir / DAILY_OHLC_COVERAGE_LATEST_JSON.name,
            markdown_path=output_dir / DAILY_OHLC_COVERAGE_LATEST_MD.name,
        )
        paths["daily_ohlc_coverage_json"] = coverage_paths["json"]
        paths["daily_ohlc_coverage_markdown"] = coverage_paths["markdown"]
    return paths


def detect_breakout_events(
    *,
    daily_bars_by_symbol: dict[str, list[TechnicalPriceBar]] | None = None,
    minute_bars_by_symbol: dict[str, list[TechnicalPriceBar]] | None = None,
    captures: list[dict[str, str]] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    options: BreakoutResearchOptions | None = None,
    minute_source_data: str = "explicit-minute-bar-fixture",
) -> list[BreakoutEvent]:
    options = options or BreakoutResearchOptions()
    daily_bars_by_symbol = daily_bars_by_symbol or {}
    minute_bars_by_symbol = minute_bars_by_symbol or {}
    captures = captures or []
    alerts = alerts or []
    market_regimes = latest_market_regime_by_symbol(captures, alerts)

    events: list[BreakoutEvent] = []
    qqq_bars = sorted_bars(daily_bars_by_symbol.get("QQQ", []))
    if daily_bars_by_symbol:
        for symbol, bars in sorted(daily_bars_by_symbol.items()):
            if symbol == "QQQ":
                continue
            daily_events = detect_daily_breakout_events(
                symbol=symbol,
                bars=bars,
                qqq_bars=qqq_bars,
                market_regime=market_regimes.get(symbol),
                source_data="daily_bars",
                options=options,
            )
            events.extend(daily_events)
    else:
        for symbol in tracked_symbols(captures, alerts, minute_bars_by_symbol):
            events.append(
                insufficient_event(
                    symbol=symbol,
                    event_type="daily_technical_breakout_scan",
                    timeframe="daily",
                    source_data="daily_bars",
                    note="No local daily OHLC bar source was supplied. Daily Donchian, SMA, Bollinger, ATR/Keltner, and QQQ relative-strength signals are unavailable.",
                    market_regime=market_regimes.get(symbol),
                )
            )

    for symbol, bars in sorted(minute_bars_by_symbol.items()):
        events.extend(
            detect_intraday_breakout_events(
                symbol=symbol,
                bars=bars,
                market_regime=market_regimes.get(symbol),
                source_data=minute_source_data,
                options=options,
            )
        )
    return sorted(events, key=lambda event: (event.event_timestamp, event.symbol, event.event_type))


def detect_daily_breakout_events(
    *,
    symbol: str,
    bars: list[TechnicalPriceBar],
    qqq_bars: list[TechnicalPriceBar] | None = None,
    market_regime: str | None = None,
    source_data: str = "daily_bars",
    options: BreakoutResearchOptions | None = None,
) -> list[BreakoutEvent]:
    options = options or BreakoutResearchOptions()
    bars = sorted_bars(bars)
    if len(bars) < options.bollinger_window + 1:
        return [
            insufficient_event(
                symbol=symbol,
                event_type="daily_technical_breakout_scan",
                timeframe="daily",
                source_data=source_data,
                note=f"Only {len(bars)} daily bar(s) available; at least {options.bollinger_window + 1} are needed for the first daily breakout scan.",
                market_regime=market_regime,
                event_timestamp=bars[-1].timestamp if bars else None,
            )
        ]

    events: list[BreakoutEvent] = []
    for index, bar in enumerate(bars):
        events.extend(
            detect_donchian_breakouts_at_index(
                symbol=symbol,
                bars=bars,
                index=index,
                market_regime=market_regime,
                source_data=source_data,
                options=options,
            )
        )
        events.extend(
            detect_moving_average_events_at_index(
                symbol=symbol,
                bars=bars,
                index=index,
                market_regime=market_regime,
                source_data=source_data,
                options=options,
            )
        )
        bollinger = detect_bollinger_breakout_at_index(
            symbol=symbol,
            bars=bars,
            index=index,
            market_regime=market_regime,
            source_data=source_data,
            options=options,
        )
        if bollinger:
            events.append(bollinger)
        keltner = detect_atr_keltner_breakout_at_index(
            symbol=symbol,
            bars=bars,
            index=index,
            market_regime=market_regime,
            source_data=source_data,
            options=options,
        )
        if keltner:
            events.append(keltner)

    return [attach_daily_confirmations(event, bars, qqq_bars or [], options) for event in events]


def detect_donchian_breakouts_at_index(
    *,
    symbol: str,
    bars: list[TechnicalPriceBar],
    index: int,
    market_regime: str | None,
    source_data: str,
    options: BreakoutResearchOptions,
) -> list[BreakoutEvent]:
    events: list[BreakoutEvent] = []
    if index <= 0:
        return events
    current = bars[index]
    previous = bars[index - 1]
    for window in options.donchian_windows:
        if index < window + 1:
            continue
        prior_high = max(bar.high for bar in bars[index - window : index])
        previous_prior_high = max(bar.high for bar in bars[index - window - 1 : index - 1])
        if current.close > prior_high and previous.close <= previous_prior_high:
            events.append(
                make_event(
                    symbol=symbol,
                    timestamp=current.timestamp,
                    event_type=f"donchian_{window}_day_breakout",
                    timeframe="daily",
                    trigger_price=current.close,
                    reference_label=f"prior_{window}_day_high",
                    reference_value=prior_high,
                    volume=current.volume,
                    relative_volume=relative_volume(bars, index, options.volume_average_window),
                    market_regime=market_regime,
                    source_data=source_data,
                    status=BREAKOUT_PRESENT,
                    notes=[f"Close crossed above the prior {window}-day high."],
                    details={"lookback_days": window},
                )
            )
    return events


def detect_moving_average_events_at_index(
    *,
    symbol: str,
    bars: list[TechnicalPriceBar],
    index: int,
    market_regime: str | None,
    source_data: str,
    options: BreakoutResearchOptions,
) -> list[BreakoutEvent]:
    events: list[BreakoutEvent] = []
    if index <= 0:
        return events
    current = bars[index]
    previous = bars[index - 1]
    for window in (options.sma_short_window, options.sma_long_window):
        current_sma = rolling_sma(bars, index, window)
        previous_sma = rolling_sma(bars, index - 1, window)
        if current_sma is None or previous_sma is None:
            continue
        if current.close > current_sma and previous.close <= previous_sma:
            events.append(
                make_event(
                    symbol=symbol,
                    timestamp=current.timestamp,
                    event_type=f"price_cross_above_sma_{window}",
                    timeframe="daily",
                    trigger_price=current.close,
                    reference_label=f"sma_{window}",
                    reference_value=current_sma,
                    volume=current.volume,
                    relative_volume=relative_volume(bars, index, options.volume_average_window),
                    market_regime=market_regime,
                    source_data=source_data,
                    status=BREAKOUT_PRESENT,
                    notes=[f"Close crossed above the {window}-day simple moving average."],
                    details={"sma_window": window},
                )
            )
    short_sma = rolling_sma(bars, index, options.sma_short_window)
    long_sma = rolling_sma(bars, index, options.sma_long_window)
    previous_short_sma = rolling_sma(bars, index - 1, options.sma_short_window)
    previous_long_sma = rolling_sma(bars, index - 1, options.sma_long_window)
    if (
        short_sma is not None
        and long_sma is not None
        and previous_short_sma is not None
        and previous_long_sma is not None
        and short_sma > long_sma
        and previous_short_sma <= previous_long_sma
    ):
        events.append(
            make_event(
                symbol=symbol,
                timestamp=current.timestamp,
                event_type="sma_20_cross_above_sma_50",
                timeframe="daily",
                trigger_price=current.close,
                reference_label="sma_50",
                reference_value=long_sma,
                volume=current.volume,
                relative_volume=relative_volume(bars, index, options.volume_average_window),
                market_regime=market_regime,
                source_data=source_data,
                status=BREAKOUT_PRESENT,
                notes=["The 20-day simple moving average crossed above the 50-day simple moving average."],
                details={"sma_20": short_sma, "sma_50": long_sma},
            )
        )
    return events


def detect_bollinger_breakout_at_index(
    *,
    symbol: str,
    bars: list[TechnicalPriceBar],
    index: int,
    market_regime: str | None,
    source_data: str,
    options: BreakoutResearchOptions,
) -> BreakoutEvent | None:
    if index < options.bollinger_window + 1:
        return None
    current = bars[index]
    previous = bars[index - 1]
    band = prior_bollinger_upper(bars, index, options)
    previous_band = prior_bollinger_upper(bars, index - 1, options)
    if band is None or previous_band is None:
        return None
    if current.close > band and previous.close <= previous_band:
        return make_event(
            symbol=symbol,
            timestamp=current.timestamp,
            event_type="bollinger_upper_band_breakout",
            timeframe="daily",
            trigger_price=current.close,
            reference_label=f"prior_{options.bollinger_window}_day_upper_bollinger_band",
            reference_value=band,
            volume=current.volume,
            relative_volume=relative_volume(bars, index, options.volume_average_window),
            market_regime=market_regime,
            source_data=source_data,
            status=BREAKOUT_PRESENT,
            notes=["Close crossed above the prior upper Bollinger Band."],
            details={"bollinger_window": options.bollinger_window, "standard_deviations": options.bollinger_stddevs},
        )
    return None


def detect_atr_keltner_breakout_at_index(
    *,
    symbol: str,
    bars: list[TechnicalPriceBar],
    index: int,
    market_regime: str | None,
    source_data: str,
    options: BreakoutResearchOptions,
) -> BreakoutEvent | None:
    if index < options.atr_window + 2:
        return None
    current = bars[index]
    previous = bars[index - 1]
    trigger = prior_keltner_upper(bars, index, options)
    previous_trigger = prior_keltner_upper(bars, index - 1, options)
    current_atr = prior_atr(bars, index, options.atr_window)
    if trigger is None or previous_trigger is None:
        return None
    if current.close > trigger and previous.close <= previous_trigger:
        details: dict[str, Any] = {"atr_window": options.atr_window, "atr_multiple": options.atr_multiple}
        if current_atr is not None and current.close:
            details["atr_pct"] = round(current_atr / current.close * 100.0, 4)
        return make_event(
            symbol=symbol,
            timestamp=current.timestamp,
            event_type="atr_keltner_breakout",
            timeframe="daily",
            trigger_price=current.close,
            reference_label=f"prior_{options.atr_window}_day_sma_plus_{options.atr_multiple}_atr",
            reference_value=trigger,
            volume=current.volume,
            relative_volume=relative_volume(bars, index, options.volume_average_window),
            market_regime=market_regime,
            source_data=source_data,
            status=BREAKOUT_PRESENT,
            notes=["Close crossed above the prior SMA plus ATR channel."],
            details=details,
        )
    return None


def detect_intraday_breakout_events(
    *,
    symbol: str,
    bars: list[TechnicalPriceBar],
    market_regime: str | None = None,
    source_data: str = "explicit-minute-bar-fixture",
    options: BreakoutResearchOptions | None = None,
) -> list[BreakoutEvent]:
    options = options or BreakoutResearchOptions()
    bars = sorted_bars(bars)
    if len(bars) < 2:
        return [
            insufficient_event(
                symbol=symbol,
                event_type="intraday_technical_breakout_scan",
                timeframe="intraday",
                source_data=source_data,
                note=f"Only {len(bars)} minute bar(s) available.",
                market_regime=market_regime,
                event_timestamp=bars[-1].timestamp if bars else None,
            )
        ]
    events: list[BreakoutEvent] = []
    for day, day_bars in bars_by_day(bars).items():
        day_events = detect_intraday_day_events(
            symbol=symbol,
            bars=day_bars,
            market_regime=market_regime,
            source_data=source_data,
            options=options,
        )
        if not day_events and len(day_bars) < 15:
            events.append(
                insufficient_event(
                    symbol=symbol,
                    event_type="intraday_technical_breakout_scan",
                    timeframe="intraday",
                    source_data=source_data,
                    note=f"{day} has only {len(day_bars)} minute bar(s); intraday breakout windows are limited.",
                    market_regime=market_regime,
                    event_timestamp=day_bars[-1].timestamp,
                )
            )
        events.extend(day_events)
    return events


def detect_intraday_day_events(
    *,
    symbol: str,
    bars: list[TechnicalPriceBar],
    market_regime: str | None,
    source_data: str,
    options: BreakoutResearchOptions,
) -> list[BreakoutEvent]:
    events: list[BreakoutEvent] = []
    bars = sorted_bars(bars)
    vwap_values = cumulative_vwap_values(bars)
    for index in range(1, len(bars)):
        current = bars[index]
        previous = bars[index - 1]
        rel_volume = relative_volume(bars, index, options.volume_average_window)
        if vwap_values[index] is not None and vwap_values[index - 1] is not None:
            if previous.close <= vwap_values[index - 1] and current.close > vwap_values[index]:
                events.append(
                    make_event(
                        symbol=symbol,
                        timestamp=current.timestamp,
                        event_type="intraday_reclaim_vwap",
                        timeframe="intraday",
                        trigger_price=current.close,
                        reference_label="session_vwap",
                        reference_value=vwap_values[index],
                        volume=current.volume,
                        relative_volume=rel_volume,
                        market_regime=market_regime,
                        source_data=source_data,
                        status=BREAKOUT_PRESENT,
                        notes=["Close reclaimed intraday VWAP."],
                    )
                )
        if index >= options.opening_range_minutes:
            opening_range_high = max(bar.high for bar in bars[: options.opening_range_minutes])
            if current.close > opening_range_high and previous.close <= opening_range_high:
                events.append(
                    make_event(
                        symbol=symbol,
                        timestamp=current.timestamp,
                        event_type="intraday_opening_range_high_breakout",
                        timeframe="intraday",
                        trigger_price=current.close,
                        reference_label=f"opening_range_{options.opening_range_minutes}_minute_high",
                        reference_value=opening_range_high,
                        volume=current.volume,
                        relative_volume=rel_volume,
                        market_regime=market_regime,
                        source_data=source_data,
                        status=BREAKOUT_PRESENT,
                        notes=[f"Close crossed above the first {options.opening_range_minutes}-minute high."],
                    )
                )
        for window in (15, 60):
            if index < window + 1:
                continue
            prior_high = max(bar.high for bar in bars[index - window : index])
            previous_prior_high = max(bar.high for bar in bars[index - window - 1 : index - 1])
            if current.close > prior_high and previous.close <= previous_prior_high:
                events.append(
                    make_event(
                        symbol=symbol,
                        timestamp=current.timestamp,
                        event_type=f"intraday_{window}_minute_high_breakout",
                        timeframe="intraday",
                        trigger_price=current.close,
                        reference_label=f"prior_{window}_minute_high",
                        reference_value=prior_high,
                        volume=current.volume,
                        relative_volume=rel_volume,
                        market_regime=market_regime,
                        source_data=source_data,
                        status=BREAKOUT_PRESENT,
                        notes=[f"Close crossed above the prior {window}-minute high."],
                        details={"lookback_minutes": window},
                    )
                )
    return events


def study_breakout_events(
    events: list[BreakoutEvent],
    *,
    daily_bars_by_symbol: dict[str, list[TechnicalPriceBar]] | None = None,
    minute_bars_by_symbol: dict[str, list[TechnicalPriceBar]] | None = None,
    options: BreakoutResearchOptions | None = None,
) -> list[BreakoutStudyResult]:
    options = options or BreakoutResearchOptions()
    daily_bars_by_symbol = daily_bars_by_symbol or {}
    minute_bars_by_symbol = minute_bars_by_symbol or {}
    studies: list[BreakoutStudyResult] = []
    for event in events:
        if event.timeframe == "intraday":
            studies.append(study_intraday_event(event, minute_bars_by_symbol.get(event.symbol, []), options))
        elif event.timeframe == "daily":
            studies.append(study_daily_event(event, daily_bars_by_symbol.get(event.symbol, []), options))
        else:
            studies.append(insufficient_study(event, "Unsupported event timeframe."))
    return studies


def study_intraday_event(
    event: BreakoutEvent,
    bars: list[TechnicalPriceBar],
    options: BreakoutResearchOptions,
) -> BreakoutStudyResult:
    event_time = parse_datetime(event.event_timestamp)
    if event_time is None or event.trigger_price is None or event.trigger_price <= 0:
        return insufficient_study(event, "Event timestamp or trigger price is missing.")
    future = [
        bar
        for bar in sorted_bars(bars)
        if (parsed := parse_datetime(bar.timestamp)) is not None and parsed >= event_time
    ]
    if not future:
        return insufficient_study(event, "No minute bars are available at or after the breakout event.")
    returns: dict[str, float | None] = {}
    horizon_bars: list[TechnicalPriceBar] = []
    for minutes in INTRADAY_HORIZONS:
        target = event_time + timedelta(minutes=minutes)
        selected = first_bar_at_or_after(future, target)
        returns[f"{minutes}m"] = return_pct(event.trigger_price, selected.close) if selected else None
        horizon_bars.extend(bars_until(future, target))
    return completed_study(event, returns, dedupe_bars(horizon_bars), options)


def study_daily_event(
    event: BreakoutEvent,
    bars: list[TechnicalPriceBar],
    options: BreakoutResearchOptions,
) -> BreakoutStudyResult:
    event_time = parse_datetime(event.event_timestamp)
    if event_time is None or event.trigger_price is None or event.trigger_price <= 0:
        return insufficient_study(event, "Event timestamp or trigger price is missing.")
    bars = sorted_bars(bars)
    event_index = matching_daily_index(bars, event_time)
    if event_index is None:
        return insufficient_study(event, "No daily bar matches the breakout event date.")
    returns: dict[str, float | None] = {}
    horizon_bars: list[TechnicalPriceBar] = []
    for days in DAILY_HORIZONS:
        target_index = event_index + days
        selected = bars[target_index] if target_index < len(bars) else None
        returns[f"{days}d"] = return_pct(event.trigger_price, selected.close) if selected else None
        horizon_bars.extend(bars[event_index + 1 : min(len(bars), target_index + 1)])
    return completed_study(event, returns, dedupe_bars(horizon_bars), options)


def completed_study(
    event: BreakoutEvent,
    returns: dict[str, float | None],
    bars: list[TechnicalPriceBar],
    options: BreakoutResearchOptions,
) -> BreakoutStudyResult:
    if event.trigger_price is None or event.trigger_price <= 0 or not bars:
        return BreakoutStudyResult(
            event_id=event.event_id,
            symbol=event.symbol,
            event_timestamp=event.event_timestamp,
            event_type=event.event_type,
            timeframe=event.timeframe,
            trigger_price=event.trigger_price,
            forward_returns_pct=returns,
            max_favorable_excursion_pct=None,
            max_adverse_excursion_pct=None,
            held_above_breakout_level=None,
            failed_back_below_breakout_level=None,
            volume_confirmed=event.volume_confirmed,
            became_extended=None,
            data_sufficiency=INSUFFICIENT_DATA,
            status=INSUFFICIENT_DATA,
            notes=["No forward bars are available for excursion calculations."],
        )
    mfe = round(max(return_pct(event.trigger_price, bar.high) for bar in bars), 4)
    mae = round(min(return_pct(event.trigger_price, bar.low) for bar in bars), 4)
    failed = any(bar.low < event.trigger_price for bar in bars)
    atr_pct = safe_float(event.details.get("atr_pct"))
    extension_threshold = (2.0 * atr_pct) if atr_pct is not None else options.extension_fallback_pct
    return BreakoutStudyResult(
        event_id=event.event_id,
        symbol=event.symbol,
        event_timestamp=event.event_timestamp,
        event_type=event.event_type,
        timeframe=event.timeframe,
        trigger_price=event.trigger_price,
        forward_returns_pct=returns,
        max_favorable_excursion_pct=mfe,
        max_adverse_excursion_pct=mae,
        held_above_breakout_level=not failed,
        failed_back_below_breakout_level=failed,
        volume_confirmed=event.volume_confirmed,
        became_extended=mfe >= extension_threshold,
        data_sufficiency="Sufficient",
        status=BREAKOUT_FAILED if failed else BREAKOUT_PRESENT,
        notes=[],
    )


def insufficient_study(event: BreakoutEvent, note: str) -> BreakoutStudyResult:
    horizons = INTRADAY_HORIZONS if event.timeframe == "intraday" else DAILY_HORIZONS
    suffix = "m" if event.timeframe == "intraday" else "d"
    return BreakoutStudyResult(
        event_id=event.event_id,
        symbol=event.symbol,
        event_timestamp=event.event_timestamp,
        event_type=event.event_type,
        timeframe=event.timeframe,
        trigger_price=event.trigger_price,
        forward_returns_pct={f"{horizon}{suffix}": None for horizon in horizons},
        max_favorable_excursion_pct=None,
        max_adverse_excursion_pct=None,
        held_above_breakout_level=None,
        failed_back_below_breakout_level=None,
        volume_confirmed=event.volume_confirmed,
        became_extended=None,
        data_sufficiency=INSUFFICIENT_DATA,
        status=INSUFFICIENT_DATA,
        notes=[note],
    )


def moving_average_state(
    bars: list[TechnicalPriceBar],
    index: int,
    *,
    options: BreakoutResearchOptions | None = None,
) -> dict[str, bool | None]:
    options = options or BreakoutResearchOptions()
    if index < 0 or index >= len(bars):
        return {
            "price_above_sma_20": None,
            "price_above_sma_50": None,
            "sma_20_above_sma_50": None,
        }
    bar = sorted_bars(bars)[index]
    sma_short = rolling_sma(bars, index, options.sma_short_window)
    sma_long = rolling_sma(bars, index, options.sma_long_window)
    return {
        "price_above_sma_20": None if sma_short is None else bar.close > sma_short,
        "price_above_sma_50": None if sma_long is None else bar.close > sma_long,
        "sma_20_above_sma_50": None if sma_short is None or sma_long is None else sma_short > sma_long,
    }


def attach_daily_confirmations(
    event: BreakoutEvent,
    bars: list[TechnicalPriceBar],
    qqq_bars: list[TechnicalPriceBar],
    options: BreakoutResearchOptions,
) -> BreakoutEvent:
    index = matching_timestamp_index(bars, event.event_timestamp)
    if index is None:
        return event
    state = moving_average_state(bars, index, options=options)
    rs_confirmed = relative_strength_confirmation(bars, qqq_bars, index, options)
    details = dict(event.details)
    details.update(state)
    if rs_confirmed is None:
        details["qqq_relative_strength"] = INSUFFICIENT_DATA
    else:
        details["qqq_relative_strength"] = "outperforming" if rs_confirmed else "not_outperforming"
    notes = list(event.notes)
    if rs_confirmed is None:
        notes.append("QQQ relative-strength confirmation unavailable.")
    return BreakoutEvent(
        **{
            **asdict(event),
            "relative_strength_confirmed": rs_confirmed,
            "notes": notes,
            "details": details,
        }
    )


def make_event(
    *,
    symbol: str,
    timestamp: str,
    event_type: str,
    timeframe: str,
    trigger_price: float | None,
    reference_label: str,
    reference_value: float | None,
    volume: int | None,
    relative_volume: float | None,
    market_regime: str | None,
    source_data: str,
    status: str,
    notes: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> BreakoutEvent:
    distance = None
    if trigger_price is not None and reference_value not in (None, 0):
        distance = round((trigger_price - reference_value) / reference_value * 100.0, 4)
    volume_confirmed = None if relative_volume is None else relative_volume >= BreakoutResearchOptions().volume_confirmation_multiple
    quality = "HIGH" if status == BREAKOUT_PRESENT and volume_confirmed else "MEDIUM" if status == BREAKOUT_PRESENT else "LOW"
    event = BreakoutEvent(
        event_id=event_id(symbol, timestamp, event_type, timeframe),
        symbol=symbol,
        event_timestamp=timestamp,
        event_type=event_type,
        timeframe=timeframe,
        trigger_price=round_float(trigger_price),
        reference_label=reference_label,
        prior_high_band_or_moving_average_value=round_float(reference_value),
        distance_above_trigger_pct=distance,
        volume=volume,
        relative_volume=round_float(relative_volume),
        market_regime=market_regime,
        source_data=source_data,
        data_sufficiency="Sufficient",
        quality_flag=quality,
        status=status if status in allowed_statuses() else BREAKOUT_UNCONFIRMED,
        volume_confirmed=volume_confirmed,
        notes=notes or [],
        details=details or {},
    )
    return event


def insufficient_event(
    *,
    symbol: str,
    event_type: str,
    timeframe: str,
    source_data: str,
    note: str,
    market_regime: str | None = None,
    event_timestamp: str | None = None,
) -> BreakoutEvent:
    timestamp = event_timestamp or now_central().isoformat()
    return BreakoutEvent(
        event_id=event_id(symbol, timestamp, event_type, timeframe),
        symbol=symbol,
        event_timestamp=timestamp,
        event_type=event_type,
        timeframe=timeframe,
        trigger_price=None,
        reference_label="unavailable",
        prior_high_band_or_moving_average_value=None,
        distance_above_trigger_pct=None,
        volume=None,
        relative_volume=None,
        market_regime=market_regime,
        source_data=source_data,
        data_sufficiency=INSUFFICIENT_DATA,
        quality_flag="UNAVAILABLE",
        status=INSUFFICIENT_DATA,
        volume_confirmed=None,
        relative_strength_confirmed=None,
        notes=[note],
        details={},
    )


def build_event_report_payload(
    *,
    generated_at: str,
    source_paths: dict[str, str | None],
    events: list[BreakoutEvent],
    captures_seen: int,
    outcomes_seen: int,
    alerts_seen: int,
    daily_symbols: int,
    minute_symbols: int,
    daily_ohlc_valid_records: int | None = None,
    daily_ohlc_invalid_records: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "source_paths": source_paths,
        "source_counts": {
            "captures_seen": captures_seen,
            "outcomes_seen": outcomes_seen,
            "alerts_seen": alerts_seen,
            "daily_symbols": daily_symbols,
            "daily_ohlc_valid_records": daily_ohlc_valid_records,
            "daily_ohlc_invalid_records": daily_ohlc_invalid_records,
            "minute_symbols": minute_symbols,
        },
        "summary": event_summary(events),
        "events": [asdict(event) for event in events],
        "warnings": report_warnings(daily_symbols=daily_symbols, minute_symbols=minute_symbols, events=events),
    }


def build_study_report_payload(
    *,
    generated_at: str,
    source_paths: dict[str, str | None],
    events: list[BreakoutEvent],
    studies: list[BreakoutStudyResult],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "source_paths": source_paths,
        "events_considered": len([event for event in events if event.status == BREAKOUT_PRESENT]),
        "summary": study_summary(studies),
        "studies": [asdict(study) for study in studies],
        "warnings": [] if studies else ["No breakout-present events had enough forward data for study output."],
    }


def write_json(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_markdown_event_report(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = payload["summary"]
    lines = [
        f"# Technical Breakout Events - {payload['generated_at']}",
        "",
        "Research-only chart-structure scan. This report reads existing local evidence and does not modify Momentum Hunter operating rules.",
        "",
        "## Summary",
        "",
        f"- Total records: {summary['total_records']}",
        f"- Breakout present: {summary['breakout_present']}",
        f"- Breakout failed: {summary['breakout_failed']}",
        f"- Breakout unconfirmed: {summary['breakout_unconfirmed']}",
        f"- Insufficient data: {summary['insufficient_data']}",
        "",
        "## Source Counts",
        "",
    ]
    for key, value in payload["source_counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Events", ""])
    events = payload["events"][:100]
    if not events:
        lines.append("- No breakout records generated.")
    else:
        lines.extend(
            [
                "| Symbol | Time | Type | Timeframe | Status | Trigger | Reference | Distance % | Relative Volume | Quality |",
                "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for event in events:
            lines.append(
                f"| {event['symbol']} | {event['event_timestamp']} | {event['event_type']} | "
                f"{event['timeframe']} | {event['status']} | {format_report_value(event['trigger_price'])} | "
                f"{format_report_value(event['prior_high_band_or_moving_average_value'])} | "
                f"{format_report_value(event['distance_above_trigger_pct'])} | "
                f"{format_report_value(event['relative_volume'])} | {event['quality_flag']} |"
            )
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in payload["warnings"]] if payload["warnings"] else ["- None."])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_markdown_study_report(payload: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = payload["summary"]
    lines = [
        f"# Technical Breakout Event Study - {payload['generated_at']}",
        "",
        "Research-only forward-return study for breakout-present records.",
        "",
        "## Summary",
        "",
        f"- Events considered: {payload['events_considered']}",
        f"- Study rows: {summary['study_rows']}",
        f"- Failed back below level: {summary['failed_back_below_breakout_level']}",
        f"- Held above level: {summary['held_above_breakout_level']}",
        f"- Became extended: {summary['became_extended']}",
        "",
        "## Study Rows",
        "",
    ]
    studies = payload["studies"][:100]
    if not studies:
        lines.append("- No study rows generated.")
    else:
        lines.extend(
            [
                "| Symbol | Time | Type | Status | MFE % | MAE % | Held | Failed | Extended | Volume Confirmed |",
                "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for study in studies:
            lines.append(
                f"| {study['symbol']} | {study['event_timestamp']} | {study['event_type']} | {study['status']} | "
                f"{format_report_value(study['max_favorable_excursion_pct'])} | "
                f"{format_report_value(study['max_adverse_excursion_pct'])} | "
                f"{format_report_value(study['held_above_breakout_level'])} | "
                f"{format_report_value(study['failed_back_below_breakout_level'])} | "
                f"{format_report_value(study['became_extended'])} | {format_report_value(study['volume_confirmed'])} |"
            )
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in payload["warnings"]] if payload["warnings"] else ["- None."])
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def event_summary(events: list[BreakoutEvent]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for event in events:
        by_status[event.status] = by_status.get(event.status, 0) + 1
        by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
    return {
        "total_records": len(events),
        "breakout_present": by_status.get(BREAKOUT_PRESENT, 0),
        "breakout_failed": by_status.get(BREAKOUT_FAILED, 0),
        "breakout_unconfirmed": by_status.get(BREAKOUT_UNCONFIRMED, 0),
        "insufficient_data": by_status.get(INSUFFICIENT_DATA, 0),
        "by_status": by_status,
        "by_type": dict(sorted(by_type.items())),
    }


def study_summary(studies: list[BreakoutStudyResult]) -> dict[str, Any]:
    return {
        "study_rows": len(studies),
        "failed_back_below_breakout_level": sum(1 for study in studies if study.failed_back_below_breakout_level is True),
        "held_above_breakout_level": sum(1 for study in studies if study.held_above_breakout_level is True),
        "became_extended": sum(1 for study in studies if study.became_extended is True),
        "insufficient_data": sum(1 for study in studies if study.status == INSUFFICIENT_DATA),
    }


def report_warnings(*, daily_symbols: int, minute_symbols: int, events: list[BreakoutEvent]) -> list[str]:
    warnings: list[str] = []
    if not daily_symbols:
        warnings.append("No local daily OHLC source was supplied; daily technical signals are marked unavailable.")
    if not minute_symbols:
        warnings.append("No local minute bars were available; intraday technical signals are marked unavailable.")
    if not any(event.status == BREAKOUT_PRESENT for event in events):
        warnings.append("No breakout-present events were detected from available local evidence.")
    return warnings


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as file:
        return [dict(row) for row in csv.DictReader(file)]


def load_json_records(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get(key, []) if isinstance(payload, dict) else payload
    return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []


def load_bar_source(path: Path | None, *, default_source: str) -> dict[str, list[TechnicalPriceBar]]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    grouped: dict[str, list[TechnicalPriceBar]] = {}
    raw_bars: Any
    if isinstance(payload, dict) and isinstance(payload.get("bars"), dict):
        raw_bars = payload["bars"]
    else:
        raw_bars = payload
    if isinstance(raw_bars, dict):
        for symbol, records in raw_bars.items():
            if not isinstance(records, list):
                continue
            for record in records:
                bar = bar_from_dict(record, fallback_symbol=str(symbol), default_source=default_source)
                if bar:
                    grouped.setdefault(bar.symbol, []).append(bar)
    elif isinstance(raw_bars, list):
        for record in raw_bars:
            bar = bar_from_dict(record, default_source=default_source)
            if bar:
                grouped.setdefault(bar.symbol, []).append(bar)
    return {symbol: sorted_bars(bars) for symbol, bars in grouped.items()}


def daily_ohlc_records_to_technical_bars(records: list[DailyOhlcRecord]) -> dict[str, list[TechnicalPriceBar]]:
    grouped: dict[str, list[TechnicalPriceBar]] = {}
    for record in records:
        if None in (record.open, record.high, record.low, record.close):
            continue
        grouped.setdefault(record.symbol, []).append(
            TechnicalPriceBar(
                symbol=record.symbol,
                timestamp=record.date,
                open=record.open or 0.0,
                high=record.high or 0.0,
                low=record.low or 0.0,
                close=record.close or 0.0,
                volume=record.volume,
                source=record.source,
            )
        )
    return {symbol: sorted_bars(bars) for symbol, bars in grouped.items()}


def bar_from_dict(
    payload: Any,
    *,
    fallback_symbol: str = "",
    default_source: str = "technical_research",
) -> TechnicalPriceBar | None:
    if not isinstance(payload, dict):
        return None
    symbol = str(payload.get("symbol") or fallback_symbol).upper().strip()
    timestamp = str(payload.get("timestamp") or payload.get("datetime") or payload.get("date") or payload.get("day") or "").strip()
    close = safe_float(payload.get("close") or payload.get("price"))
    high = safe_float(payload.get("high"))
    low = safe_float(payload.get("low"))
    open_value = safe_float(payload.get("open"))
    if not symbol or not timestamp or close is None:
        return None
    high = close if high is None else high
    low = close if low is None else low
    open_value = close if open_value is None else open_value
    return TechnicalPriceBar(
        symbol=symbol,
        timestamp=timestamp,
        open=open_value,
        high=high,
        low=low,
        close=close,
        volume=safe_int(payload.get("volume")),
        source=str(payload.get("source") or default_source),
    )


def tracked_symbols(
    captures: list[dict[str, str]],
    alerts: list[dict[str, Any]],
    minute_bars_by_symbol: dict[str, list[TechnicalPriceBar]],
) -> list[str]:
    symbols: set[str] = set(minute_bars_by_symbol)
    for row in captures:
        symbol = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if symbol:
            symbols.add(symbol)
    for alert in alerts:
        symbol = str(alert.get("symbol") or "").upper().strip()
        if symbol:
            symbols.add(symbol)
    return sorted(symbols)


def latest_market_regime_by_symbol(
    captures: list[dict[str, str]],
    alerts: list[dict[str, Any]],
) -> dict[str, str]:
    regimes: dict[str, str] = {}
    for row in captures:
        symbol = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        regime = str(row.get("market_regime") or "").strip()
        if symbol and regime:
            regimes[symbol] = regime
    for alert in alerts:
        symbol = str(alert.get("symbol") or "").upper().strip()
        regime = str(alert.get("market_regime") or "").strip()
        if symbol and regime:
            regimes[symbol] = regime
    return regimes


def rolling_sma(bars: list[TechnicalPriceBar], index: int, window: int) -> float | None:
    if index < window - 1 or index >= len(bars):
        return None
    values = [bar.close for bar in bars[index - window + 1 : index + 1]]
    return mean(values)


def prior_bollinger_upper(
    bars: list[TechnicalPriceBar],
    index: int,
    options: BreakoutResearchOptions,
) -> float | None:
    if index < options.bollinger_window:
        return None
    closes = [bar.close for bar in bars[index - options.bollinger_window : index]]
    if len(closes) < options.bollinger_window:
        return None
    return mean(closes) + options.bollinger_stddevs * pstdev(closes)


def prior_atr(bars: list[TechnicalPriceBar], index: int, window: int) -> float | None:
    if index < window + 1:
        return None
    ranges = [true_range(bars[position], bars[position - 1]) for position in range(index - window, index)]
    return mean(ranges) if len(ranges) == window else None


def prior_keltner_upper(
    bars: list[TechnicalPriceBar],
    index: int,
    options: BreakoutResearchOptions,
) -> float | None:
    if index < options.atr_window + 1:
        return None
    closes = [bar.close for bar in bars[index - options.atr_window : index]]
    atr = prior_atr(bars, index, options.atr_window)
    if len(closes) < options.atr_window or atr is None:
        return None
    return mean(closes) + options.atr_multiple * atr


def true_range(current: TechnicalPriceBar, previous: TechnicalPriceBar) -> float:
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def relative_volume(bars: list[TechnicalPriceBar], index: int, window: int) -> float | None:
    if index < window:
        return None
    current_volume = bars[index].volume
    prior = [bar.volume for bar in bars[index - window : index] if bar.volume is not None]
    if current_volume is None or len(prior) < window:
        return None
    average = mean(prior)
    if average <= 0:
        return None
    return round(current_volume / average, 4)


def relative_strength_confirmation(
    bars: list[TechnicalPriceBar],
    qqq_bars: list[TechnicalPriceBar],
    index: int,
    options: BreakoutResearchOptions,
) -> bool | None:
    if not qqq_bars or index < options.relative_strength_window:
        return None
    current = bars[index]
    current_time = parse_datetime(current.timestamp)
    if current_time is None:
        return None
    qqq_index = matching_daily_index(qqq_bars, current_time)
    if qqq_index is None or qqq_index < options.relative_strength_window:
        return None
    symbol_start = bars[index - options.relative_strength_window].close
    qqq_start = qqq_bars[qqq_index - options.relative_strength_window].close
    if symbol_start <= 0 or qqq_start <= 0:
        return None
    symbol_return = return_pct(symbol_start, current.close)
    qqq_return = return_pct(qqq_start, qqq_bars[qqq_index].close)
    return symbol_return > qqq_return


def cumulative_vwap_values(bars: list[TechnicalPriceBar]) -> list[float | None]:
    values: list[float | None] = []
    cumulative_volume = 0
    cumulative_price_volume = 0.0
    for bar in bars:
        volume = bar.volume or 0
        if volume > 0:
            typical = (bar.high + bar.low + bar.close) / 3.0
            cumulative_volume += volume
            cumulative_price_volume += typical * volume
        values.append(cumulative_price_volume / cumulative_volume if cumulative_volume > 0 else None)
    return values


def bars_by_day(bars: list[TechnicalPriceBar]) -> dict[str, list[TechnicalPriceBar]]:
    grouped: dict[str, list[TechnicalPriceBar]] = {}
    for bar in sorted_bars(bars):
        parsed = parse_datetime(bar.timestamp)
        day = parsed.date().isoformat() if parsed else bar.timestamp[:10]
        grouped.setdefault(day, []).append(bar)
    return grouped


def sorted_bars(bars: list[TechnicalPriceBar]) -> list[TechnicalPriceBar]:
    return sorted(bars, key=bar_sort_key)


def bar_sort_key(bar: TechnicalPriceBar) -> tuple[float, str]:
    parsed = parse_datetime(bar.timestamp)
    if parsed is None:
        return (-1.0, bar.timestamp)
    return (parsed.timestamp(), bar.timestamp)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(f"{value}T00:00:00")
        except ValueError:
            return None


def matching_timestamp_index(bars: list[TechnicalPriceBar], timestamp: str) -> int | None:
    for index, bar in enumerate(bars):
        if bar.timestamp == timestamp:
            return index
    parsed = parse_datetime(timestamp)
    if parsed is None:
        return None
    return matching_daily_index(bars, parsed)


def matching_daily_index(bars: list[TechnicalPriceBar], timestamp: datetime) -> int | None:
    for index, bar in enumerate(bars):
        parsed = parse_datetime(bar.timestamp)
        if parsed and parsed.date() == timestamp.date():
            return index
    return None


def first_bar_at_or_after(bars: list[TechnicalPriceBar], target: datetime) -> TechnicalPriceBar | None:
    for bar in bars:
        parsed = parse_datetime(bar.timestamp)
        if parsed is not None and parsed >= target:
            return bar
    return None


def bars_until(bars: list[TechnicalPriceBar], target: datetime) -> list[TechnicalPriceBar]:
    return [bar for bar in bars if (parsed := parse_datetime(bar.timestamp)) is not None and parsed <= target]


def dedupe_bars(bars: list[TechnicalPriceBar]) -> list[TechnicalPriceBar]:
    by_key: dict[tuple[str, str], TechnicalPriceBar] = {}
    for bar in bars:
        by_key[(bar.symbol, bar.timestamp)] = bar
    return sorted_bars(list(by_key.values()))


def return_pct(start: float, end: float) -> float:
    if start == 0:
        return 0.0
    return round((end - start) / start * 100.0, 4)


def event_id(symbol: str, timestamp: str, event_type: str, timeframe: str) -> str:
    raw = f"{symbol}|{timestamp}|{event_type}|{timeframe}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:20]


def allowed_statuses() -> set[str]:
    return {BREAKOUT_PRESENT, BREAKOUT_ABSENT, BREAKOUT_FAILED, BREAKOUT_UNCONFIRMED, INSUFFICIENT_DATA}


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def round_float(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def format_report_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build research-only technical breakout reports.")
    parser.add_argument("--captures", type=Path, default=ANALYSIS_CAPTURES_PATH)
    parser.add_argument("--outcomes", type=Path, default=ANALYSIS_OUTCOMES_PATH)
    parser.add_argument("--alerts", type=Path, default=OPPORTUNITY_ALERTS_PATH)
    parser.add_argument("--minute-bars", type=Path, default=None, help="Explicit synthetic or historical JSON fixture only.")
    parser.add_argument("--minute-store-root", type=Path, default=SCHWAB_CANDLE_STORE_ROOT)
    parser.add_argument("--daily-bars", type=Path, default=None)
    parser.add_argument("--daily-ohlc", type=Path, default=DAILY_OHLC_SOURCE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR / "reports")
    args = parser.parse_args(argv)
    ensure_app_dirs()
    paths = build_technical_breakout_reports(
        captures_path=args.captures,
        outcomes_path=args.outcomes,
        alerts_path=args.alerts,
        minute_bars_path=args.minute_bars,
        minute_store_root=args.minute_store_root,
        daily_bars_path=args.daily_bars,
        daily_ohlc_path=args.daily_ohlc,
        output_dir=args.output_dir,
    )
    for label, path in paths.items():
        print(f"{label}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
