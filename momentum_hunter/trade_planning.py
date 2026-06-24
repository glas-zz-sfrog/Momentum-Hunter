from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time
from pathlib import Path
from typing import Iterable

from momentum_hunter.catalyst_clusters import classify_catalyst_headline_detail
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.models import Candidate
from momentum_hunter.outcomes import PriceBar, fetch_price_bars, build_http_session
from momentum_hunter.storage import CAPTURES_DIR, candidate_from_dict, format_market_cap
from momentum_hunter.time_utils import now_central


REPORT_SCHEMA_VERSION = 1
COMPOSITE_PROFILE = "trade-planning-composite-v1"
DEFAULT_CAPITAL = 500.0
REPORT_COLUMNS = [
    "Rank",
    "Symbol",
    "Last Price",
    "Premarket Price",
    "Premarket %",
    "Premarket Volume",
    "Intraday Volume",
    "20-Day Average Daily Volume",
    "RVOL Formula Used",
    "RVOL Numerator",
    "RVOL Denominator",
    "RVOL Type",
    "Current Bid",
    "Current Ask",
    "Spread %",
    "Relative Volume",
    "Float",
    "Market Cap",
    "ATR",
    "Momentum Score",
    "News Score",
    "Composite Score",
    "Catalyst Summary",
    "Previous Day High",
    "Previous Day Low",
    "Previous Day Close",
    "5-Day High",
    "20-Day High",
    "Support Level",
    "Resistance Level",
    "Bullish Entry",
    "Bullish Stop",
    "Bullish Target 1",
    "Bullish Target 2",
    "Risk/Reward Ratio",
    "Estimated Shares for $500",
    "Estimated Dollar Risk",
    "Estimated Target 1 Reward",
    "Risk-On Rank",
    "Risk-Off Rank",
    "Likely Outperform QQQ",
    "Likely Outperform SMH",
    "Plan Confidence",
    "Tradeability",
    "Readiness",
    "Blocking Reasons",
    "Warnings",
]

SPREAD_TIGHT_THRESHOLD_PCT = 0.25
SPREAD_WIDE_THRESHOLD_PCT = 2.0
RELATIVE_VOLUME_READY_THRESHOLD = 1.2
PREMARKET_VOLUME_READY_THRESHOLD = 500_000
PREMARKET_MOVE_READY_THRESHOLD_PCT = 1.0
PRICE_ENTRY_PROXIMITY_THRESHOLD_PCT = 3.0
PREMARKET_RVOL = "PREMARKET_RVOL"
INTRADAY_RVOL = "INTRADAY_RVOL"
DAILY_RVOL = "DAILY_RVOL"
UNKNOWN_RVOL = "UNKNOWN_RVOL"
EVENT_MODE = "EVENT_MODE"
EXECUTION_READY_PREMARKET = "EXECUTION_READY_PREMARKET"
EXECUTION_READY_TRADE = "EXECUTION_READY_TRADE"
PLANNING_SCAFFOLD = "PLANNING_SCAFFOLD"
FED_KEYWORDS = [
    "fed",
    "fomc",
    "powell",
    "rate cut",
    "rate hike",
    "dot plot",
    "inflation",
    "higher for longer",
    "labor market",
    "yields",
]


@dataclass(frozen=True)
class TechnicalLevels:
    previous_day_high: float | None = None
    previous_day_low: float | None = None
    previous_day_close: float | None = None
    five_day_high: float | None = None
    twenty_day_high: float | None = None
    atr: float | None = None
    support_level: float | None = None
    resistance_level: float | None = None
    source: str = "capture_only"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MarketTape:
    last_price: float | None = None
    premarket_price: float | None = None
    premarket_percent: float | None = None
    premarket_volume: int | None = None
    intraday_volume: int | None = None
    average_daily_volume_20: int | None = None
    rvol_formula_used: str = ""
    rvol_numerator: int | None = None
    rvol_denominator: int | None = None
    rvol_type: str = UNKNOWN_RVOL
    current_bid: float | None = None
    current_ask: float | None = None
    spread_percent: float | None = None
    relative_volume: float | None = None
    source: str = "capture_only"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TradePlan:
    bullish_entry: float | None
    bullish_stop: float | None
    bullish_target_1: float | None
    bullish_target_2: float | None
    risk_reward_ratio: float | None
    estimated_shares_for_500: float | None
    estimated_dollar_risk: float | None
    estimated_target_1_reward: float | None
    confidence: str
    tradeability: str
    readiness: str
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TradePlanRow:
    rank: int
    symbol: str
    company: str
    sector: str
    industry: str
    last_price: float | None
    premarket_price: float | None
    premarket_percent: float | None
    premarket_volume: int | None
    intraday_volume: int | None
    average_daily_volume_20: int | None
    rvol_formula_used: str
    rvol_numerator: int | None
    rvol_denominator: int | None
    rvol_type: str
    current_bid: float | None
    current_ask: float | None
    spread_percent: float | None
    relative_volume: float | None
    float_shares: int | None
    market_cap: int | None
    atr: float | None
    momentum_score: int
    news_score: int
    composite_score: int
    catalyst_summary: str
    catalyst_cluster: str
    catalyst_confidence: int
    technical_levels: TechnicalLevels
    market_tape: MarketTape
    trade_plan: TradePlan
    risk_on_rank: int = 0
    risk_off_rank: int = 0
    likely_outperform_qqq: bool = False
    likely_outperform_smh: bool = False
    opportunity_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TradePlanningReport:
    generated_at: str
    source_capture_path: str
    source_capture_time: str
    source_session: str
    source_provider: str
    source_scanner: str
    composite_profile: str
    capital_assumption: float
    event_mode: bool
    polling_interval_seconds: int
    rows: list[TradePlanRow]
    state_transition_log: list[dict[str, str]] = field(default_factory=list)
    fed_news_summary: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_trade_planning_report(
    capture_path: Path,
    *,
    capital: float = DEFAULT_CAPITAL,
    bars_by_ticker: dict[str, list[PriceBar]] | None = None,
    market_tape_by_ticker: dict[str, MarketTape] | None = None,
    fetch_bars: bool = False,
    fetch_market_data: bool = False,
    event_mode: bool = False,
    as_of: datetime | None = None,
    previous_state_path: Path | None = None,
) -> TradePlanningReport:
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    candidates = [candidate_from_dict(item) for item in payload.get("candidates", [])]
    capture_time = parse_datetime(payload.get("capture_time")) or now_central()
    capture_date = capture_time.date().isoformat()
    scanner = payload.get("scanner", {})
    scanner_name = scanner.get("name", "") if isinstance(scanner, dict) else str(scanner or "")
    as_of = as_of or now_central()
    rvol_type = rvol_type_for_time(as_of)
    bars_by_ticker = bars_by_ticker or {}
    market_tape_by_ticker = market_tape_by_ticker or {}

    if fetch_bars or fetch_market_data:
        session = build_http_session()
        for candidate in candidates:
            if fetch_bars or fetch_market_data:
                bars_by_ticker.setdefault(candidate.ticker, fetch_price_bars(session, candidate.ticker))
            if fetch_market_data:
                market_tape_by_ticker.setdefault(candidate.ticker, fetch_market_tape(session, candidate.ticker))

    rows = [
        build_trade_plan_row(
            candidate,
            capture_date=capture_date,
            capital=capital,
            bars=bars_by_ticker.get(candidate.ticker, []),
            market_tape=market_tape_by_ticker.get(candidate.ticker),
            rvol_type=rvol_type,
        )
        for candidate in candidates
    ]
    rows = sorted(rows, key=lambda row: row.composite_score, reverse=True)
    rows = assign_ranks(rows)
    transition_log = build_state_transition_log(rows, previous_state_path=previous_state_path, as_of=as_of)
    fed_news = build_fed_news_summary(candidates)
    warnings = report_warnings(rows, fetch_bars=fetch_bars or fetch_market_data, fetch_market_data=fetch_market_data)
    return TradePlanningReport(
        generated_at=as_of.isoformat(),
        source_capture_path=str(capture_path),
        source_capture_time=payload.get("capture_time", ""),
        source_session=payload.get("session", ""),
        source_provider=payload.get("provider", ""),
        source_scanner=scanner_name,
        composite_profile=COMPOSITE_PROFILE,
        capital_assumption=capital,
        event_mode=event_mode,
        polling_interval_seconds=event_polling_interval_seconds(as_of) if event_mode else 15 * 60,
        rows=rows,
        state_transition_log=transition_log,
        fed_news_summary=fed_news,
        warnings=warnings,
    )


def build_trade_plan_row(
    candidate: Candidate,
    *,
    capture_date: str,
    capital: float,
    bars: list[PriceBar],
    market_tape: MarketTape | None = None,
    rvol_type: str = UNKNOWN_RVOL,
) -> TradePlanRow:
    technicals = build_technical_levels(candidate, capture_date=capture_date, bars=bars)
    base_tape = market_tape or tape_from_candidate(candidate)
    volume_20 = average_daily_volume_20(bars, capture_date=capture_date)
    if base_tape.average_daily_volume_20 is None and volume_20 is not None:
        base_tape = replace(base_tape, average_daily_volume_20=volume_20)
    tape = apply_rvol_policy(base_tape, rvol_type)
    catalyst = catalyst_summary(candidate)
    catalyst_detail = classify_catalyst_headline_detail(
        catalyst,
        sector=candidate.sector,
        industry=candidate.industry,
        sector_sympathy=False,
    )
    plan = build_trade_plan(candidate, technicals, tape, capital=capital)
    composite = composite_score(candidate, technicals, plan, catalyst_detail.confidence_score)
    row = TradePlanRow(
        rank=0,
        symbol=candidate.ticker,
        company=candidate.company,
        sector=candidate.sector,
        industry=candidate.industry,
        last_price=rounded(tape.last_price or candidate.price),
        premarket_price=tape.premarket_price,
        premarket_percent=tape.premarket_percent,
        premarket_volume=tape.premarket_volume,
        intraday_volume=tape.intraday_volume,
        average_daily_volume_20=tape.average_daily_volume_20,
        rvol_formula_used=tape.rvol_formula_used,
        rvol_numerator=tape.rvol_numerator,
        rvol_denominator=tape.rvol_denominator,
        rvol_type=tape.rvol_type,
        current_bid=tape.current_bid,
        current_ask=tape.current_ask,
        spread_percent=tape.spread_percent,
        relative_volume=rounded(tape.relative_volume if tape.relative_volume is not None else candidate.relative_volume),
        float_shares=candidate.float_shares,
        market_cap=candidate.market_cap,
        atr=rounded(technicals.atr),
        momentum_score=int(candidate.score or 0),
        news_score=int(candidate.freshness_score or candidate.news_stack.freshness_score or 0),
        composite_score=composite,
        catalyst_summary=catalyst,
        catalyst_cluster=catalyst_detail.cluster_name,
        catalyst_confidence=catalyst_detail.confidence_score,
        technical_levels=technicals,
        market_tape=tape,
        trade_plan=plan,
        likely_outperform_qqq=likely_outperform_qqq(candidate, composite, catalyst_detail.cluster_name),
        likely_outperform_smh=likely_outperform_smh(candidate, composite, catalyst_detail.cluster_name),
        opportunity_notes=opportunity_notes(candidate, technicals, plan, catalyst_detail.cluster_name),
    )
    return row


def build_technical_levels(candidate: Candidate, *, capture_date: str, bars: list[PriceBar]) -> TechnicalLevels:
    warnings: list[str] = []
    completed_bars = sorted([bar for bar in bars if bar.day < capture_date], key=lambda bar: bar.day)
    previous = completed_bars[-1] if completed_bars else None
    five = completed_bars[-5:]
    twenty = completed_bars[-20:]
    previous_high = previous.high if previous else None
    previous_low = previous.low if previous else None
    previous_close = previous.close if previous else None
    five_high = max((bar.high for bar in five), default=None)
    twenty_high = max((bar.high for bar in twenty), default=None)
    atr = candidate.atr or average_daily_range(completed_bars[-14:])
    if not completed_bars:
        warnings.append("DATA_REQUIRED_DAILY_BARS")
    if atr is None:
        warnings.append("ATR_ESTIMATED_FROM_PRICE")
        atr = max(candidate.price * 0.02, 0.05) if candidate.price else None
    support = previous_low
    resistance_candidates = [value for value in (previous_high, five_high, twenty_high) if value is not None]
    resistance = max(resistance_candidates) if resistance_candidates else None
    source = "daily_bars" if completed_bars else "estimated_from_capture_price"
    if support is None and candidate.price and atr:
        support = candidate.price - atr
    if resistance is None and candidate.price:
        resistance = candidate.price * 1.005
    return TechnicalLevels(
        previous_day_high=rounded(previous_high),
        previous_day_low=rounded(previous_low),
        previous_day_close=rounded(previous_close),
        five_day_high=rounded(five_high),
        twenty_day_high=rounded(twenty_high),
        atr=rounded(atr),
        support_level=rounded(support),
        resistance_level=rounded(resistance),
        source=source,
        warnings=warnings,
    )


def build_trade_plan(candidate: Candidate, technicals: TechnicalLevels, tape: MarketTape, *, capital: float) -> TradePlan:
    warnings = dedupe(list(technicals.warnings) + list(tape.warnings))
    price = current_trade_price(candidate, tape)
    if price <= 0:
        return TradePlan(None, None, None, None, None, None, None, None, "LOW", "LOW", "DO_NOT_TRADE_MISSING_DATA", ["MISSING_PRICE"], ["MISSING_PRICE"])
    original_entry = technicals.resistance_level or (price * 1.005)
    entry = original_entry
    if price > original_entry:
        warnings.append("PRICE_ALREADY_ABOVE_ENTRY")
        entry = price * 1.001
    stop = technicals.support_level or (entry - (technicals.atr or price * 0.02))
    if stop >= entry:
        stop = entry - max(technicals.atr or price * 0.02, price * 0.01)
        warnings.append("STOP_ADJUSTED_BELOW_ENTRY")
    risk = entry - stop
    if risk <= 0:
        return TradePlan(
            rounded(entry),
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "LOW",
            "LOW",
            "DO_NOT_TRADE_POOR_DATA",
            dedupe(warnings + ["INVALID_RISK"]),
            dedupe(warnings + ["INVALID_RISK"]),
        )
    target_1 = entry + (risk * 2)
    target_2 = entry + (risk * 3)
    shares = capital / entry if entry else None
    dollar_risk = risk * shares if shares is not None else None
    reward_1 = (target_1 - entry) * shares if shares is not None else None
    readiness, confidence, tradeability, blocking_reasons = classify_readiness(
        technicals,
        tape,
        current_price=price,
        original_entry=original_entry,
    )
    if technicals.source != "daily_bars":
        warnings.append("TECHNICAL_LEVELS_ESTIMATED")
    return TradePlan(
        bullish_entry=rounded(entry),
        bullish_stop=rounded(stop),
        bullish_target_1=rounded(target_1),
        bullish_target_2=rounded(target_2),
        risk_reward_ratio=rounded((target_1 - entry) / risk),
        estimated_shares_for_500=round(shares, 4) if shares is not None else None,
        estimated_dollar_risk=rounded(dollar_risk),
        estimated_target_1_reward=rounded(reward_1),
        confidence=confidence,
        tradeability=tradeability,
        readiness=readiness,
        blocking_reasons=blocking_reasons,
        warnings=dedupe(warnings),
    )


def composite_score(candidate: Candidate, technicals: TechnicalLevels, plan: TradePlan, catalyst_confidence: int) -> int:
    momentum = clamp(candidate.score, 0, 100)
    news = clamp(candidate.freshness_score or candidate.news_stack.freshness_score, 0, 100)
    liquidity = liquidity_score(candidate)
    technical = 75 if technicals.source == "daily_bars" else 45
    plan_quality = 80 if plan.confidence == "MEDIUM" else 55
    missing_penalty = min(15, 3 * len(plan.warnings))
    score = (
        momentum * 0.42
        + news * 0.23
        + liquidity * 0.15
        + technical * 0.10
        + plan_quality * 0.05
        + catalyst_confidence * 0.05
        - missing_penalty
    )
    return int(round(clamp(score, 0, 100)))


def liquidity_score(candidate: Candidate) -> int:
    volume = candidate.volume or 0
    market_cap = candidate.market_cap or 0
    volume_score = 40
    if volume >= 50_000_000:
        volume_score = 100
    elif volume >= 20_000_000:
        volume_score = 88
    elif volume >= 10_000_000:
        volume_score = 76
    elif volume >= 3_000_000:
        volume_score = 62
    cap_bonus = 0
    if market_cap >= 100_000_000_000:
        cap_bonus = 8
    elif market_cap >= 10_000_000_000:
        cap_bonus = 5
    return clamp(volume_score + cap_bonus, 0, 100)


def assign_ranks(rows: list[TradePlanRow]) -> list[TradePlanRow]:
    risk_on = sorted(rows, key=risk_on_score, reverse=True)
    risk_off = sorted(rows, key=risk_off_score, reverse=True)
    risk_on_ranks = {row.symbol: index for index, row in enumerate(risk_on, 1)}
    risk_off_ranks = {row.symbol: index for index, row in enumerate(risk_off, 1)}
    ranked = []
    for index, row in enumerate(rows, 1):
        ranked.append(
            TradePlanRow(
                **{
                    **asdict(row),
                    "rank": index,
                    "technical_levels": row.technical_levels,
                    "market_tape": row.market_tape,
                    "trade_plan": row.trade_plan,
                    "risk_on_rank": risk_on_ranks[row.symbol],
                    "risk_off_rank": risk_off_ranks[row.symbol],
                }
            )
        )
    return ranked


def risk_on_score(row: TradePlanRow) -> float:
    bonus = 0
    sector = row_sector(row)
    cluster = row.catalyst_cluster.lower()
    if sector in {"technology", "communication services", "consumer cyclical", "financial"}:
        bonus += 8
    if "ai" in cluster or "growth" in cluster:
        bonus += 6
    return row.composite_score + bonus


def risk_off_score(row: TradePlanRow) -> float:
    bonus = 0
    sector = row_sector(row)
    if sector in {"healthcare", "consumer defensive", "utilities"}:
        bonus += 12
    if row.market_cap and row.market_cap >= 50_000_000_000:
        bonus += 5
    if row.trade_plan.confidence == "LOW":
        bonus -= 3
    return row.composite_score + bonus


def row_sector(row: TradePlanRow) -> str:
    return row.sector.lower()


def likely_outperform_qqq(candidate: Candidate, composite: int, cluster: str) -> bool:
    sector = candidate.sector.lower()
    cluster_text = cluster.lower()
    return composite >= 70 and (
        sector in {"technology", "communication services", "consumer cyclical", "financial"}
        or "ai" in cluster_text
    )


def likely_outperform_smh(candidate: Candidate, composite: int, cluster: str) -> bool:
    text = f"{candidate.sector} {candidate.industry} {cluster} {catalyst_summary(candidate)}".lower()
    return composite >= 68 and any(term in text for term in ["semiconductor", "chip", "gpu", "memory", "data center", "ai infrastructure"])


def opportunity_notes(candidate: Candidate, technicals: TechnicalLevels, plan: TradePlan, cluster: str) -> list[str]:
    notes = [f"Catalyst cluster: {cluster}"]
    if candidate.freshness_score >= 90:
        notes.append("Fresh news context")
    if candidate.volume >= 20_000_000:
        notes.append("Large-volume participation")
    if technicals.source != "daily_bars":
        notes.append("Needs real daily OHLC levels before execution")
    if plan.readiness == EXECUTION_READY_PREMARKET:
        notes.append("Premarket execution-ready tape and levels available")
    elif plan.readiness == EXECUTION_READY_TRADE:
        notes.append("Intraday execution-ready tape and levels available")
    if "PRICE_ALREADY_ABOVE_ENTRY" in plan.warnings:
        notes.append("Price already exceeded original breakout; entry was reset to a pullback/reclaim level")
    if plan.readiness in {EXECUTION_READY_PREMARKET, EXECUTION_READY_TRADE}:
        pass
    elif plan.readiness.startswith("DO_NOT_TRADE"):
        notes.append("Do not trade until blocking data issues clear")
    else:
        notes.append("Use as planning scaffold, not final execution levels")
    return notes


def catalyst_summary(candidate: Candidate) -> str:
    if candidate.news_stack.freshest_headline:
        return candidate.news_stack.freshest_headline
    if candidate.news:
        item = candidate.news[0]
        return item.headline or item.summary
    if candidate.score_reasons:
        return "; ".join(candidate.score_reasons[:3])
    return "No stored catalyst headline"


def premarket_price(candidate: Candidate) -> float | None:
    if candidate.gap_percent is None or not candidate.price:
        return None
    return rounded(candidate.price * (1 + candidate.gap_percent / 100))


def current_trade_price(candidate: Candidate, tape: MarketTape) -> float:
    if tape.rvol_type == PREMARKET_RVOL and tape.premarket_price is not None:
        return tape.premarket_price
    if tape.last_price is not None:
        return tape.last_price
    if tape.premarket_price is not None:
        return tape.premarket_price
    return candidate.price


def tape_from_candidate(candidate: Candidate) -> MarketTape:
    warnings: list[str] = []
    if candidate.gap_percent is None:
        warnings.append("MISSING_PREMARKET_PERCENT")
    if candidate.premarket_volume is None:
        warnings.append("MISSING_PREMARKET_VOLUME")
    return MarketTape(
        last_price=rounded(candidate.price),
        premarket_price=premarket_price(candidate),
        premarket_percent=rounded(candidate.gap_percent),
        premarket_volume=candidate.premarket_volume,
        relative_volume=rounded(candidate.relative_volume) if candidate.relative_volume else None,
        source="capture_only",
        warnings=warnings,
    )


def fetch_market_tape(session, ticker: str) -> MarketTape:
    nasdaq_tape = fetch_nasdaq_market_tape(session, ticker)
    yahoo_tape = fetch_yahoo_market_tape(session, ticker)
    if has_core_tape(nasdaq_tape):
        return overlay_tapes(primary=nasdaq_tape, fallback=yahoo_tape)
    return overlay_tapes(primary=yahoo_tape, fallback=nasdaq_tape)


def fetch_nasdaq_market_tape(session, ticker: str) -> MarketTape:
    if not ticker:
        return MarketTape(source="nasdaq", warnings=["MISSING_TICKER"])
    symbol = ticker.replace(".", "-").upper()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }
    info, info_warnings = request_json(
        session,
        f"https://api.nasdaq.com/api/quote/{symbol}/info?assetclass=stocks",
        headers=headers,
        warning_prefix="NASDAQ_INFO",
    )
    summary, summary_warnings = request_json(
        session,
        f"https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass=stocks",
        headers=headers,
        warning_prefix="NASDAQ_SUMMARY",
    )
    extended, extended_warnings = request_json(
        session,
        f"https://api.nasdaq.com/api/quote/{symbol}/extended-trading?assetclass=stocks&markettype=pre",
        headers=headers,
        warning_prefix="NASDAQ_EXTENDED",
    )
    info_data = (info or {}).get("data") or {}
    summary_data = ((summary or {}).get("data") or {}).get("summaryData") or {}
    bid_ask = ((summary or {}).get("data") or {}).get("bidAsk") or {}
    primary = info_data.get("primaryData") or {}
    market_status = str(info_data.get("marketStatus") or "")
    extended_row = first_extended_row(extended)

    bid = parse_money(primary.get("bidPrice")) or parse_bid_ask_value((bid_ask.get("Bid * Size") or {}).get("value"))
    ask = parse_money(primary.get("askPrice")) or parse_bid_ask_value((bid_ask.get("Ask * Size") or {}).get("value"))
    spread = spread_percent(bid, ask)
    share_volume = parse_int_text((summary_data.get("ShareVolume") or {}).get("value")) or parse_int_text(primary.get("volume"))
    average_volume = parse_int_text((summary_data.get("AverageVolume") or {}).get("value"))
    premarket_volume = parse_int_text(extended_row.get("volume")) if extended_row else None
    if premarket_volume is None and "pre" in market_status.lower():
        premarket_volume = share_volume
    premarket_price_value = parse_extended_consolidated_price(extended_row.get("consolidated") if extended_row else "")
    premarket_percent_value = parse_extended_consolidated_percent(extended_row.get("consolidated") if extended_row else "")
    if premarket_price_value is None and "pre" in market_status.lower():
        premarket_price_value = parse_money(primary.get("lastSalePrice"))
    if premarket_percent_value is None and "pre" in market_status.lower():
        premarket_percent_value = parse_percent(primary.get("percentageChange"))
    current_volume = premarket_volume or share_volume
    relative_volume = (current_volume / average_volume) if current_volume and average_volume else None
    warnings = dedupe(
        tape_warnings(
            premarket_price=premarket_price_value,
            premarket_volume=premarket_volume,
            bid=bid,
            ask=ask,
            spread=spread,
            relative_volume=relative_volume,
        )
        + info_warnings
        + summary_warnings
        + extended_warnings
    )
    return MarketTape(
        last_price=rounded(parse_money(primary.get("lastSalePrice"))),
        premarket_price=rounded(premarket_price_value),
        premarket_percent=rounded(premarket_percent_value),
        premarket_volume=premarket_volume,
        intraday_volume=share_volume,
        average_daily_volume_20=average_volume,
        rvol_numerator=current_volume,
        rvol_denominator=average_volume,
        current_bid=rounded(bid),
        current_ask=rounded(ask),
        spread_percent=rounded(spread),
        relative_volume=rounded(relative_volume),
        source="nasdaq",
        warnings=warnings,
    )


def fetch_yahoo_market_tape(session, ticker: str) -> MarketTape:
    if not ticker:
        return MarketTape(source="yahoo_quote", warnings=["MISSING_TICKER"])
    chart_tape = fetch_yahoo_chart_tape(session, ticker)
    symbol = ticker.replace(".", "-")
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}"
    try:
        response = session.get(url, timeout=20)
        if response.status_code != 200:
            return merge_tapes(
                quote_tape=MarketTape(source="yahoo_quote", warnings=[f"QUOTE_HTTP_{response.status_code}"]),
                chart_tape=chart_tape,
            )
        result = (response.json().get("quoteResponse", {}).get("result") or [])
    except Exception as exc:
        return merge_tapes(
            quote_tape=MarketTape(source="yahoo_quote", warnings=[f"QUOTE_FETCH_FAILED:{type(exc).__name__}"]),
            chart_tape=chart_tape,
        )
    if not result:
        return merge_tapes(quote_tape=MarketTape(source="yahoo_quote", warnings=["QUOTE_EMPTY"]), chart_tape=chart_tape)
    quote = result[0]
    last = first_float(quote, "regularMarketPrice", "postMarketPrice", "preMarketPrice")
    premarket = first_float(quote, "preMarketPrice")
    previous_close = first_float(quote, "regularMarketPreviousClose", "preMarketPreviousClose")
    premarket_percent = first_float(quote, "preMarketChangePercent")
    if premarket_percent is None and premarket is not None and previous_close:
        premarket_percent = ((premarket - previous_close) / previous_close) * 100
    bid = first_float(quote, "bid")
    ask = first_float(quote, "ask")
    spread = spread_percent(bid, ask)
    premarket_volume = first_int(quote, "preMarketVolume")
    regular_volume = first_int(quote, "regularMarketVolume")
    average_volume = first_int(quote, "averageDailyVolume10Day", "averageDailyVolume3Month")
    relative_volume = (regular_volume / average_volume) if regular_volume and average_volume else None
    warnings = tape_warnings(
        premarket_price=premarket,
        premarket_volume=premarket_volume,
        bid=bid,
        ask=ask,
        spread=spread,
        relative_volume=relative_volume,
    )
    quote_tape = MarketTape(
        last_price=rounded(last),
        premarket_price=rounded(premarket),
        premarket_percent=rounded(premarket_percent),
        premarket_volume=premarket_volume,
        intraday_volume=regular_volume,
        average_daily_volume_20=average_volume,
        rvol_numerator=premarket_volume or regular_volume,
        rvol_denominator=average_volume,
        current_bid=rounded(bid),
        current_ask=rounded(ask),
        spread_percent=rounded(spread),
        relative_volume=rounded(relative_volume),
        source="yahoo_quote",
        warnings=warnings,
    )
    return merge_tapes(quote_tape=quote_tape, chart_tape=chart_tape)


def fetch_yahoo_chart_tape(session, ticker: str) -> MarketTape:
    symbol = ticker.replace(".", "-")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1m&includePrePost=true"
    try:
        response = session.get(url, timeout=20)
        if response.status_code != 200:
            return MarketTape(source="yahoo_chart", warnings=[f"CHART_HTTP_{response.status_code}"])
        result = (response.json().get("chart", {}).get("result") or [])
    except Exception as exc:
        return MarketTape(source="yahoo_chart", warnings=[f"CHART_FETCH_FAILED:{type(exc).__name__}"])
    if not result:
        return MarketTape(source="yahoo_chart", warnings=["CHART_EMPTY"])
    payload = result[0]
    meta = payload.get("meta", {})
    timestamps = payload.get("timestamp") or []
    quote = (payload.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    regular_start = (
        meta.get("currentTradingPeriod", {})
        .get("regular", {})
        .get("start")
    )
    pre_start = (
        meta.get("currentTradingPeriod", {})
        .get("pre", {})
        .get("start")
    )
    premarket_closes: list[float] = []
    premarket_volume = 0
    for index, timestamp in enumerate(timestamps):
        if pre_start and timestamp < pre_start:
            continue
        if regular_start and timestamp >= regular_start:
            continue
        close = closes[index] if index < len(closes) else None
        volume = volumes[index] if index < len(volumes) else None
        if close is not None:
            premarket_closes.append(float(close))
        if volume is not None:
            premarket_volume += int(volume)
    last = first_float(meta, "regularMarketPrice", "postMarketPrice", "preMarketPrice")
    previous_close = first_float(meta, "previousClose", "chartPreviousClose")
    premarket = first_float(meta, "preMarketPrice")
    if premarket is None and premarket_closes:
        premarket = premarket_closes[-1]
    premarket_percent = None
    if premarket is not None and previous_close:
        premarket_percent = ((premarket - previous_close) / previous_close) * 100
    volume_value = premarket_volume if premarket_volume > 0 else first_int(meta, "preMarketVolume")
    warnings = tape_warnings(
        premarket_price=premarket,
        premarket_volume=volume_value,
        bid=None,
        ask=None,
        spread=None,
        relative_volume=None,
    )
    return MarketTape(
        last_price=rounded(last),
        premarket_price=rounded(premarket),
        premarket_percent=rounded(premarket_percent),
        premarket_volume=volume_value,
        rvol_numerator=volume_value,
        source="yahoo_chart",
        warnings=warnings,
    )


def merge_tapes(*, quote_tape: MarketTape, chart_tape: MarketTape) -> MarketTape:
    source = quote_tape.source if not quote_tape.warnings else f"{quote_tape.source}+{chart_tape.source}"
    used_chart = (
        quote_tape.premarket_price is None and chart_tape.premarket_price is not None
        or quote_tape.premarket_percent is None and chart_tape.premarket_percent is not None
        or quote_tape.premarket_volume is None and chart_tape.premarket_volume is not None
        or quote_tape.last_price is None and chart_tape.last_price is not None
    )
    premarket_price_value = quote_tape.premarket_price if quote_tape.premarket_price is not None else chart_tape.premarket_price
    premarket_percent_value = quote_tape.premarket_percent if quote_tape.premarket_percent is not None else chart_tape.premarket_percent
    premarket_volume_value = quote_tape.premarket_volume if quote_tape.premarket_volume is not None else chart_tape.premarket_volume
    merged = MarketTape(
        last_price=quote_tape.last_price if quote_tape.last_price is not None else chart_tape.last_price,
        premarket_price=premarket_price_value,
        premarket_percent=premarket_percent_value,
        premarket_volume=premarket_volume_value,
        intraday_volume=quote_tape.intraday_volume if quote_tape.intraday_volume is not None else chart_tape.intraday_volume,
        average_daily_volume_20=quote_tape.average_daily_volume_20 if quote_tape.average_daily_volume_20 is not None else chart_tape.average_daily_volume_20,
        rvol_formula_used=quote_tape.rvol_formula_used if quote_tape.rvol_formula_used else chart_tape.rvol_formula_used,
        rvol_numerator=quote_tape.rvol_numerator if quote_tape.rvol_numerator is not None else chart_tape.rvol_numerator,
        rvol_denominator=quote_tape.rvol_denominator if quote_tape.rvol_denominator is not None else chart_tape.rvol_denominator,
        rvol_type=quote_tape.rvol_type if quote_tape.rvol_type != UNKNOWN_RVOL else chart_tape.rvol_type,
        current_bid=quote_tape.current_bid,
        current_ask=quote_tape.current_ask,
        spread_percent=quote_tape.spread_percent,
        relative_volume=quote_tape.relative_volume,
        source=source,
        warnings=dedupe(quote_tape.warnings + chart_tape.warnings),
    )
    return MarketTape(
        last_price=merged.last_price,
        premarket_price=merged.premarket_price,
        premarket_percent=merged.premarket_percent,
        premarket_volume=merged.premarket_volume,
        intraday_volume=merged.intraday_volume,
        average_daily_volume_20=merged.average_daily_volume_20,
        rvol_formula_used=merged.rvol_formula_used,
        rvol_numerator=merged.rvol_numerator,
        rvol_denominator=merged.rvol_denominator,
        rvol_type=merged.rvol_type,
        current_bid=merged.current_bid,
        current_ask=merged.current_ask,
        spread_percent=merged.spread_percent,
        relative_volume=merged.relative_volume,
        source=merged.source,
        warnings=dedupe(tape_warnings(
            premarket_price=merged.premarket_price,
            premarket_volume=merged.premarket_volume,
            bid=merged.current_bid,
            ask=merged.current_ask,
            spread=merged.spread_percent,
            relative_volume=merged.relative_volume,
        )
        + [warning for warning in quote_tape.warnings if warning.startswith("QUOTE_")]
        + ([warning for warning in chart_tape.warnings if warning.startswith("CHART_")] if used_chart or quote_tape.warnings else [])),
    )


def overlay_tapes(*, primary: MarketTape, fallback: MarketTape) -> MarketTape:
    merged = MarketTape(
        last_price=primary.last_price if primary.last_price is not None else fallback.last_price,
        premarket_price=primary.premarket_price if primary.premarket_price is not None else fallback.premarket_price,
        premarket_percent=primary.premarket_percent if primary.premarket_percent is not None else fallback.premarket_percent,
        premarket_volume=primary.premarket_volume if primary.premarket_volume is not None else fallback.premarket_volume,
        intraday_volume=primary.intraday_volume if primary.intraday_volume is not None else fallback.intraday_volume,
        average_daily_volume_20=primary.average_daily_volume_20 if primary.average_daily_volume_20 is not None else fallback.average_daily_volume_20,
        rvol_formula_used=primary.rvol_formula_used if primary.rvol_formula_used else fallback.rvol_formula_used,
        rvol_numerator=primary.rvol_numerator if primary.rvol_numerator is not None else fallback.rvol_numerator,
        rvol_denominator=primary.rvol_denominator if primary.rvol_denominator is not None else fallback.rvol_denominator,
        rvol_type=primary.rvol_type if primary.rvol_type != UNKNOWN_RVOL else fallback.rvol_type,
        current_bid=primary.current_bid if primary.current_bid is not None else fallback.current_bid,
        current_ask=primary.current_ask if primary.current_ask is not None else fallback.current_ask,
        spread_percent=primary.spread_percent if primary.spread_percent is not None else fallback.spread_percent,
        relative_volume=primary.relative_volume if primary.relative_volume is not None else fallback.relative_volume,
        source=f"{primary.source}+{fallback.source}" if fallback.source not in primary.source else primary.source,
    )
    provider_warnings = [
        warning
        for warning in primary.warnings + fallback.warnings
        if warning.startswith(("QUOTE_", "CHART_", "NASDAQ_"))
    ]
    return MarketTape(
        last_price=merged.last_price,
        premarket_price=merged.premarket_price,
        premarket_percent=merged.premarket_percent,
        premarket_volume=merged.premarket_volume,
        intraday_volume=merged.intraday_volume,
        average_daily_volume_20=merged.average_daily_volume_20,
        rvol_formula_used=merged.rvol_formula_used,
        rvol_numerator=merged.rvol_numerator,
        rvol_denominator=merged.rvol_denominator,
        rvol_type=merged.rvol_type,
        current_bid=merged.current_bid,
        current_ask=merged.current_ask,
        spread_percent=merged.spread_percent,
        relative_volume=merged.relative_volume,
        source=merged.source,
        warnings=dedupe(
            tape_warnings(
                premarket_price=merged.premarket_price,
                premarket_volume=merged.premarket_volume,
                bid=merged.current_bid,
                ask=merged.current_ask,
                spread=merged.spread_percent,
                relative_volume=merged.relative_volume,
            )
            + provider_warnings
        ),
    )


def has_core_tape(tape: MarketTape) -> bool:
    return any(
        value is not None
        for value in (
            tape.premarket_price,
            tape.premarket_volume,
            tape.current_bid,
            tape.current_ask,
            tape.relative_volume,
        )
    )


def request_json(session, url: str, *, headers: dict[str, str] | None = None, warning_prefix: str) -> tuple[dict | None, list[str]]:
    try:
        response = session.get(url, headers=headers, timeout=20)
        if response.status_code != 200:
            return None, [f"{warning_prefix}_HTTP_{response.status_code}"]
        return response.json(), []
    except Exception as exc:
        return None, [f"{warning_prefix}_FETCH_FAILED:{type(exc).__name__}"]


def first_extended_row(payload: dict | None) -> dict:
    rows = (((payload or {}).get("data") or {}).get("infoTable") or {}).get("rows") or []
    return rows[0] if rows else {}


def parse_money(value: object) -> float | None:
    return parse_number_text(value)


def parse_percent(value: object) -> float | None:
    return parse_number_text(value)


def parse_int_text(value: object) -> int | None:
    parsed = parse_number_text(value)
    return int(parsed) if parsed is not None else None


def parse_number_text(value: object) -> float | None:
    if value in (None, "", "N/A", "NA", "--"):
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "").replace("%", "").replace("+", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_bid_ask_value(value: object) -> float | None:
    if value in (None, ""):
        return None
    first = str(value).split("*", 1)[0].strip()
    return parse_money(first)


def parse_extended_consolidated_price(value: object) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text.startswith("$"):
        return None
    token = text.split(" ", 1)[0]
    return parse_money(token)


def parse_extended_consolidated_percent(value: object) -> float | None:
    if value in (None, ""):
        return None
    text = str(value)
    start = text.rfind("(")
    end = text.rfind(")")
    if start == -1 or end == -1 or end <= start:
        return None
    return parse_percent(text[start + 1 : end])


def tape_warnings(
    *,
    premarket_price: float | None,
    premarket_volume: int | None,
    bid: float | None,
    ask: float | None,
    spread: float | None,
    relative_volume: float | None,
) -> list[str]:
    warnings: list[str] = []
    if premarket_price is None:
        warnings.append("MISSING_PREMARKET_PRICE")
    if premarket_volume is None:
        warnings.append("MISSING_PREMARKET_VOLUME")
    if bid is None or ask is None:
        warnings.append("MISSING_BID_ASK")
    if spread is None:
        warnings.append("MISSING_SPREAD")
    elif spread > SPREAD_WIDE_THRESHOLD_PCT:
        warnings.append("WIDE_SPREAD")
    if relative_volume is None:
        warnings.append("MISSING_RELATIVE_VOLUME")
    return warnings


def classify_readiness(
    technicals: TechnicalLevels,
    tape: MarketTape,
    *,
    current_price: float | None,
    original_entry: float | None,
) -> tuple[str, str, str, list[str]]:
    blocking: list[str] = []
    if technicals.source != "daily_bars":
        blocking.append("MISSING_DAILY_OHLC_LEVELS")
    if tape.rvol_type == PREMARKET_RVOL:
        if tape.premarket_volume is None:
            blocking.append("MISSING_PREMARKET_VOLUME")
        if tape.premarket_price is None:
            blocking.append("MISSING_PREMARKET_PRICE")
        if tape.premarket_percent is None:
            blocking.append("MISSING_PREMARKET_PERCENT")
    elif tape.intraday_volume is None:
        blocking.append("MISSING_INTRADAY_VOLUME")
    if tape.current_bid is None or tape.current_ask is None:
        blocking.append("MISSING_BID_ASK")
    if tape.spread_percent is None:
        blocking.append("MISSING_SPREAD")
    elif tape.spread_percent > SPREAD_WIDE_THRESHOLD_PCT:
        blocking.append("SPREAD_TOO_WIDE")
    if tape.relative_volume is None:
        blocking.append("MISSING_RVOL")
    blocking.extend(disallowed_provider_warnings(tape.warnings))
    if current_price is None:
        blocking.append("MISSING_CURRENT_PRICE")

    if tape.spread_percent is not None and tape.spread_percent > SPREAD_WIDE_THRESHOLD_PCT:
        return "DO_NOT_TRADE_POOR_DATA", "LOW", "LOW", dedupe(blocking)
    if blocking:
        return "DO_NOT_TRADE_MISSING_DATA", "LOW", "LOW", dedupe(blocking)
    if tape.rvol_type == PREMARKET_RVOL:
        if premarket_ready_conditions_met(technicals, tape, current_price=current_price, original_entry=original_entry):
            return EXECUTION_READY_PREMARKET, "HIGH", "HIGH", []
        return PLANNING_SCAFFOLD, "MEDIUM", "MEDIUM", []
    if intraday_ready_conditions_met(technicals, tape, current_price=current_price, original_entry=original_entry):
        return EXECUTION_READY_TRADE, "HIGH", "HIGH", []
    return PLANNING_SCAFFOLD, "MEDIUM", "MEDIUM", []


def disallowed_provider_warnings(warnings: list[str]) -> list[str]:
    allowed = {"QUOTE_HTTP_401"}
    return [
        warning
        for warning in warnings
        if warning.startswith(("QUOTE_", "CHART_", "NASDAQ_")) and warning not in allowed
    ]


def premarket_ready_conditions_met(
    technicals: TechnicalLevels,
    tape: MarketTape,
    *,
    current_price: float | None,
    original_entry: float | None,
) -> bool:
    return (
        current_price is not None
        and tape.premarket_volume is not None
        and tape.premarket_volume > PREMARKET_VOLUME_READY_THRESHOLD
        and tape.spread_percent is not None
        and tape.spread_percent < SPREAD_TIGHT_THRESHOLD_PCT
        and tape.premarket_percent is not None
        and tape.premarket_percent > PREMARKET_MOVE_READY_THRESHOLD_PCT
        and price_is_near_or_above_breakout(technicals, current_price=current_price, original_entry=original_entry)
    )


def intraday_ready_conditions_met(
    technicals: TechnicalLevels,
    tape: MarketTape,
    *,
    current_price: float | None,
    original_entry: float | None,
) -> bool:
    return (
        current_price is not None
        and tape.relative_volume is not None
        and tape.relative_volume > RELATIVE_VOLUME_READY_THRESHOLD
        and tape.spread_percent is not None
        and tape.spread_percent < SPREAD_TIGHT_THRESHOLD_PCT
        and price_is_above_breakout(technicals, current_price=current_price, original_entry=original_entry)
    )


def price_is_near_or_above_breakout(
    technicals: TechnicalLevels,
    *,
    current_price: float,
    original_entry: float | None,
) -> bool:
    if original_entry and within_percent(current_price, original_entry, PRICE_ENTRY_PROXIMITY_THRESHOLD_PCT):
        return True
    return price_is_above_breakout(technicals, current_price=current_price, original_entry=original_entry)


def price_is_above_breakout(
    technicals: TechnicalLevels,
    *,
    current_price: float,
    original_entry: float | None,
) -> bool:
    if original_entry and current_price >= original_entry:
        return True
    return bool(technicals.previous_day_high and current_price >= technicals.previous_day_high)


def within_percent(value: float, target: float, threshold_percent: float) -> bool:
    if target == 0:
        return False
    return abs(value - target) / abs(target) * 100 <= threshold_percent


def rvol_type_for_time(value: datetime) -> str:
    current = value.timetz().replace(tzinfo=None)
    if current < time(8, 30):
        return PREMARKET_RVOL
    if current < time(15, 0):
        return INTRADAY_RVOL
    return DAILY_RVOL


def apply_rvol_policy(tape: MarketTape, rvol_type: str) -> MarketTape:
    denominator = tape.average_daily_volume_20
    if rvol_type == PREMARKET_RVOL:
        numerator = tape.premarket_volume
        formula = "premarket_volume / 20_day_average_daily_volume"
    elif rvol_type == INTRADAY_RVOL:
        numerator = tape.intraday_volume
        formula = "intraday_volume / 20_day_average_daily_volume"
    elif rvol_type == DAILY_RVOL:
        numerator = tape.intraday_volume
        formula = "daily_volume / 20_day_average_daily_volume"
    else:
        numerator = tape.rvol_numerator
        formula = "unknown"
    relative_volume = (numerator / denominator) if numerator is not None and denominator else None
    warnings = list(tape.warnings)
    if numerator is None:
        warnings.append(f"MISSING_{rvol_type}_NUMERATOR")
    if not denominator:
        warnings.append("MISSING_20_DAY_AVERAGE_DAILY_VOLUME")
    return replace(
        tape,
        relative_volume=rounded(relative_volume),
        rvol_formula_used=formula,
        rvol_numerator=numerator,
        rvol_denominator=denominator,
        rvol_type=rvol_type,
        warnings=dedupe(warnings),
    )


def average_daily_volume_20(bars: list[PriceBar], *, capture_date: str) -> int | None:
    completed = [bar for bar in sorted(bars, key=lambda item: item.day) if bar.day < capture_date and bar.volume is not None]
    window = completed[-20:]
    if not window:
        return None
    return int(sum(int(bar.volume or 0) for bar in window) / len(window))


def event_polling_interval_seconds(value: datetime) -> int:
    current = value.timetz().replace(tzinfo=None)
    if time(12, 55) <= current < time(13, 10):
        return 60
    if time(13, 10) <= current < time(13, 30):
        return 120
    if time(13, 30) <= current < time(14, 30):
        return 60
    return 15 * 60


def build_state_transition_log(
    rows: list[TradePlanRow],
    *,
    previous_state_path: Path | None,
    as_of: datetime,
) -> list[dict[str, str]]:
    path = previous_state_path or DATA_DIR / "reports" / "trade-plan-state.json"
    previous = load_state_snapshot(path)
    current = {row.symbol: row.trade_plan.readiness for row in rows}
    transitions: list[dict[str, str]] = []
    for row in rows:
        old_state = previous.get(row.symbol)
        new_state = row.trade_plan.readiness
        if old_state and old_state != new_state:
            transitions.append(
                {
                    "timestamp": as_of.isoformat(),
                    "symbol": row.symbol,
                    "old_state": old_state,
                    "new_state": new_state,
                    "reason": transition_reason(row),
                }
            )
    save_state_snapshot(path, current)
    return transitions


def load_state_snapshot(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(item.get("symbol")): str(item.get("state")) for item in payload.get("states", []) if item.get("symbol")}


def save_state_snapshot(path: Path, states: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": now_central().isoformat(),
        "states": [{"symbol": symbol, "state": state} for symbol, state in sorted(states.items())],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def transition_reason(row: TradePlanRow) -> str:
    if row.trade_plan.blocking_reasons:
        return " | ".join(row.trade_plan.blocking_reasons)
    if row.trade_plan.readiness == EXECUTION_READY_PREMARKET:
        return (
            f"premarket volume {format_int(row.premarket_volume)} > {format_int(PREMARKET_VOLUME_READY_THRESHOLD)}, "
            f"spread {row.spread_percent}% < {SPREAD_TIGHT_THRESHOLD_PCT}%, "
            f"premarket move {row.premarket_percent}% > {PREMARKET_MOVE_READY_THRESHOLD_PCT}%"
        )
    if row.trade_plan.readiness == EXECUTION_READY_TRADE:
        return f"RVOL {row.relative_volume} > {RELATIVE_VOLUME_READY_THRESHOLD} and spread {row.spread_percent}% < {SPREAD_TIGHT_THRESHOLD_PCT}%"
    if row.trade_plan.readiness == PLANNING_SCAFFOLD:
        return planning_reason(row)
    return "State changed after latest tape/level refresh."


def build_fed_news_summary(candidates: list[Candidate]) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for candidate in candidates:
        for item in candidate.news:
            text = f"{item.headline} {item.summary}".lower()
            matched = [keyword for keyword in FED_KEYWORDS if keyword in text]
            if matched:
                matches.append(
                    {
                        "symbol": candidate.ticker,
                        "headline": item.headline,
                        "matched_keywords": ", ".join(matched),
                        "source": item.source,
                        "published_at": item.published_at.isoformat() if item.published_at else "",
                    }
                )
    return matches


def report_warnings(rows: list[TradePlanRow], *, fetch_bars: bool, fetch_market_data: bool) -> list[str]:
    warnings: list[str] = []
    if len(rows) < 20:
        warnings.append(f"Only {len(rows)} candidates were available in the source capture.")
    if any(row.premarket_price is None for row in rows):
        warnings.append("Premarket price/percent/volume are missing for one or more candidates.")
    if any(row.current_bid is None or row.current_ask is None for row in rows):
        warnings.append("Bid/ask/spread data is missing for one or more candidates.")
    if any("DATA_REQUIRED_DAILY_BARS" in row.trade_plan.warnings for row in rows):
        if fetch_bars:
            warnings.append("Daily OHLC data was requested but unavailable for one or more candidates.")
        else:
            warnings.append("Daily OHLC levels were not fetched; support/resistance and entries are conservative estimates.")
    if fetch_market_data and any(row.market_tape.source != "yahoo_quote" or row.market_tape.warnings for row in rows):
        warnings.append("Live/premarket tape was requested; rows with provider gaps are marked do-not-trade or scaffold.")
    warnings.append("Research/planning output only. No broker action or trade recommendation is generated.")
    return dedupe(warnings)


def export_trade_planning_report(report: TradePlanningReport, output_dir: Path | None = None) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir = output_dir or DATA_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    date_label = capture_date_label(report.source_capture_time)
    session = report.source_session or "session"
    prefix = "event-trade-plan-briefing" if report.event_mode else "trade-plan-briefing"
    base = f"{prefix}-{date_label}-{session}"
    csv_path = output_dir / f"{base}.csv"
    json_path = output_dir / f"{base}.json"
    md_path = output_dir / f"{base}.md"
    write_csv(report, csv_path)
    write_json(report, json_path)
    write_markdown(report, md_path)
    return {"csv": csv_path, "json": json_path, "report": md_path}


def write_csv(report: TradePlanningReport, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in report.rows:
            writer.writerow(row_to_csv(row))


def write_json(report: TradePlanningReport, path: Path) -> None:
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "metadata": {
            "generated_at": report.generated_at,
            "source_capture_path": report.source_capture_path,
            "source_capture_time": report.source_capture_time,
            "source_session": report.source_session,
            "source_provider": report.source_provider,
            "source_scanner": report.source_scanner,
            "composite_profile": report.composite_profile,
            "capital_assumption": report.capital_assumption,
            "event_mode": report.event_mode,
            "polling_interval_seconds": report.polling_interval_seconds,
            "warnings": report.warnings,
        },
        "top_5_for_capital": [row_to_json(row) for row in report.rows[:5]],
        "candidates": [row_to_json(row) for row in report.rows],
        "state_transition_log": report.state_transition_log,
        "fed_news_summary": report.fed_news_summary,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown(report: TradePlanningReport, path: Path) -> None:
    lines = [
        f"# Momentum Hunter Trade Plan Briefing - {capture_date_label(report.source_capture_time)}",
        "",
        "Research/planning output only. This does not place orders, connect to a broker, or guarantee execution quality.",
        "",
        f"- Source capture: `{report.source_capture_path}`",
        f"- Capture time: {report.source_capture_time}",
        f"- Session: {report.source_session}",
        f"- Scanner: {report.source_scanner}",
        f"- Composite profile: {report.composite_profile}",
        f"- Capital assumption: ${report.capital_assumption:,.2f}",
        f"- Event mode: {'ON' if report.event_mode else 'OFF'}",
        f"- Polling interval: {report.polling_interval_seconds} seconds",
        "",
        "## Data Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in report.warnings])
    lines.extend(["", "## Execution Readiness", ""])
    lines.extend(readiness_section_lines("Execution Ready Trades", report.rows, "EXECUTION_READY"))
    lines.extend(readiness_section_lines("Planning Scaffolds", report.rows, PLANNING_SCAFFOLD))
    lines.extend(readiness_section_lines("Do-Not-Trade Due To Missing/Poor Data", report.rows, "DO_NOT_TRADE"))
    lines.extend(["", "## State Transition Log", ""])
    lines.extend(state_transition_lines(report.state_transition_log))
    lines.extend(["", "## RVOL Debug Table", ""])
    lines.extend(rvol_debug_table_lines(report.rows))
    lines.extend(["", "## Fed News Summary", ""])
    lines.extend(fed_news_lines(report.fed_news_summary))
    lines.extend(["", "## Price Already Above Entry Warnings", ""])
    lines.extend(price_above_entry_lines(report.rows))
    lines.extend(
        [
            "",
            "## Top 5 Opportunities For $500",
            "",
            "| Rank | Symbol | Score | Entry | Stop | Target 1 | Target 2 | R/R | Est Shares | Est Risk | Est T1 Reward | Notes |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report.rows[:5]:
        plan = row.trade_plan
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.rank),
                    row.symbol,
                    str(row.composite_score),
                    money(plan.bullish_entry),
                    money(plan.bullish_stop),
                    money(plan.bullish_target_1),
                    money(plan.bullish_target_2),
                    format_optional(plan.risk_reward_ratio),
                    format_optional(plan.estimated_shares_for_500),
                    money(plan.estimated_dollar_risk),
                    money(plan.estimated_target_1_reward),
                    f"{plan.readiness}: {'; '.join(row.opportunity_notes)}",
                ]
            )
            + " |"
        )
    lines.extend(["", "## Scenario Ranking", ""])
    lines.extend(["### If Market Is Risk-On After Fed", ""])
    for row in sorted(report.rows, key=lambda item: item.risk_on_rank)[:5]:
        lines.append(f"{row.risk_on_rank}. {row.symbol} - composite {row.composite_score}; {row.catalyst_cluster}")
    lines.extend(["", "### If Market Is Risk-Off After Fed", ""])
    for row in sorted(report.rows, key=lambda item: item.risk_off_rank)[:5]:
        lines.append(f"{row.risk_off_rank}. {row.symbol} - composite {row.composite_score}; {row.catalyst_cluster}")
    lines.extend(["", "## Full Candidate Plans", ""])
    for row in report.rows:
        plan = row.trade_plan
        tech = row.technical_levels
        lines.extend(
            [
                f"### {row.rank}. {row.symbol} - {row.company}",
                "",
                f"- Last Price: {money(row.last_price)}",
                f"- Premarket Price: {money(row.premarket_price)}",
                f"- Premarket %: {format_optional(row.premarket_percent)}",
                f"- Premarket Volume: {format_int(row.premarket_volume)}",
                f"- Intraday Volume: {format_int(row.intraday_volume)}",
                f"- 20-Day Average Daily Volume: {format_int(row.average_daily_volume_20)}",
                f"- RVOL: {format_optional(row.relative_volume)} ({row.rvol_type}; {row.rvol_formula_used})",
                f"- Bid / Ask / Spread: {money(row.current_bid)} / {money(row.current_ask)} / {format_optional(row.spread_percent)}%",
                f"- Relative Volume: {format_optional(row.relative_volume)}",
                f"- Market Cap: {format_market_cap(row.market_cap or 0) if row.market_cap else 'n/a'}",
                f"- ATR: {format_optional(row.atr)}",
                f"- Momentum Score: {row.momentum_score}",
                f"- News Score: {row.news_score}",
                f"- Composite Score: {row.composite_score}",
                f"- Catalyst: {row.catalyst_summary}",
                f"- Catalyst Cluster: {row.catalyst_cluster} ({row.catalyst_confidence})",
                f"- Previous Day High/Low/Close: {money(tech.previous_day_high)} / {money(tech.previous_day_low)} / {money(tech.previous_day_close)}",
                f"- 5-Day High / 20-Day High: {money(tech.five_day_high)} / {money(tech.twenty_day_high)}",
                f"- Support / Resistance: {money(tech.support_level)} / {money(tech.resistance_level)}",
                f"- Bullish Entry: {money(plan.bullish_entry)}",
                f"- Bullish Stop: {money(plan.bullish_stop)}",
                f"- Targets: {money(plan.bullish_target_1)} / {money(plan.bullish_target_2)}",
                f"- Risk/Reward: {format_optional(plan.risk_reward_ratio)}",
                f"- Likely Outperform QQQ: {'yes' if row.likely_outperform_qqq else 'no'}",
                f"- Likely Outperform SMH: {'yes' if row.likely_outperform_smh else 'no'}",
                f"- Plan Confidence: {plan.confidence}",
                f"- Tradeability: {plan.tradeability}",
                f"- Readiness: {plan.readiness}",
                f"- Blocking Reasons: {' | '.join(plan.blocking_reasons) if plan.blocking_reasons else 'none'}",
                f"- Warnings: {' | '.join(plan.warnings) if plan.warnings else 'none'}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def readiness_section_lines(title: str, rows: list[TradePlanRow], readiness_prefix: str) -> list[str]:
    selected = [
        row
        for row in rows
        if (readiness_prefix == "EXECUTION_READY" and row.trade_plan.readiness in {EXECUTION_READY_PREMARKET, EXECUTION_READY_TRADE})
        or row.trade_plan.readiness == readiness_prefix
        or (readiness_prefix == "DO_NOT_TRADE" and row.trade_plan.readiness.startswith("DO_NOT_TRADE"))
    ]
    lines = [f"### {title}", ""]
    if not selected:
        lines.extend(["- None.", ""])
        return lines
    for row in selected:
        reasons = readiness_reason(row)
        lines.append(
            f"- {row.symbol}: {row.trade_plan.readiness}; "
            f"confidence {row.trade_plan.confidence}; tradeability {row.trade_plan.tradeability}; {reasons}"
        )
    lines.append("")
    return lines


def readiness_reason(row: TradePlanRow) -> str:
    if row.trade_plan.blocking_reasons:
        return " | ".join(row.trade_plan.blocking_reasons)
    if row.trade_plan.readiness == EXECUTION_READY_PREMARKET:
        return (
            f"premarket volume {format_int(row.premarket_volume)} > {format_int(PREMARKET_VOLUME_READY_THRESHOLD)}; "
            f"spread {format_optional(row.spread_percent)}% < {SPREAD_TIGHT_THRESHOLD_PCT}%; "
            f"premarket move {format_optional(row.premarket_percent)}% > {PREMARKET_MOVE_READY_THRESHOLD_PCT}%; "
            f"price near breakout or above previous-day high"
        )
    if row.trade_plan.readiness == EXECUTION_READY_TRADE:
        return (
            f"RVOL {format_optional(row.relative_volume)} > {RELATIVE_VOLUME_READY_THRESHOLD}x; "
            f"spread {format_optional(row.spread_percent)}% < {SPREAD_TIGHT_THRESHOLD_PCT}%; "
            f"price above breakout/reclaim level"
        )
    if row.trade_plan.readiness == PLANNING_SCAFFOLD:
        return planning_reason(row)
    return "State is based on latest tape and stored levels."


def planning_reason(row: TradePlanRow) -> str:
    if row.rvol_type == PREMARKET_RVOL:
        misses: list[str] = []
        if row.premarket_volume is None or row.premarket_volume <= PREMARKET_VOLUME_READY_THRESHOLD:
            misses.append(f"premarket volume <= {format_int(PREMARKET_VOLUME_READY_THRESHOLD)}")
        if row.spread_percent is None or row.spread_percent >= SPREAD_TIGHT_THRESHOLD_PCT:
            misses.append(f"spread >= {SPREAD_TIGHT_THRESHOLD_PCT}%")
        if row.premarket_percent is None or row.premarket_percent <= PREMARKET_MOVE_READY_THRESHOLD_PCT:
            misses.append(f"premarket move <= {PREMARKET_MOVE_READY_THRESHOLD_PCT}%")
        if not misses:
            misses.append("waiting for price to confirm breakout proximity")
        return "; ".join(misses)
    misses = []
    if row.relative_volume is None or row.relative_volume <= RELATIVE_VOLUME_READY_THRESHOLD:
        misses.append(f"RVOL <= {RELATIVE_VOLUME_READY_THRESHOLD}x")
    if row.spread_percent is None or row.spread_percent >= SPREAD_TIGHT_THRESHOLD_PCT:
        misses.append(f"spread >= {SPREAD_TIGHT_THRESHOLD_PCT}%")
    if not misses:
        misses.append("waiting for price to clear/reclaim breakout level")
    return "; ".join(misses)


def state_transition_lines(transitions: list[dict[str, str]]) -> list[str]:
    if not transitions:
        return ["- STATE TRANSITIONS: NONE YET", ""]
    lines = [
        "| Timestamp | Symbol | Old State | New State | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in transitions:
        lines.append(
            f"| {item.get('timestamp', '')} | {item.get('symbol', '')} | "
            f"{item.get('old_state', '')} | {item.get('new_state', '')} | {item.get('reason', '')} |"
        )
    lines.append("")
    return lines


def rvol_debug_table_lines(rows: list[TradePlanRow]) -> list[str]:
    lines = [
        "| Symbol | RVOL | Type | Numerator | Denominator | Formula | Premarket Vol | Intraday Vol | 20D Avg Vol |",
        "| --- | ---: | --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.symbol} | {format_optional(row.relative_volume)} | {row.rvol_type} | "
            f"{format_int(row.rvol_numerator)} | {format_int(row.rvol_denominator)} | "
            f"{row.rvol_formula_used or 'n/a'} | {format_int(row.premarket_volume)} | "
            f"{format_int(row.intraday_volume)} | {format_int(row.average_daily_volume_20)} |"
        )
    lines.append("")
    return lines


def fed_news_lines(items: list[dict[str, str]]) -> list[str]:
    if not items:
        return ["- FED NEWS SUMMARY: NO FED HEADLINES DETECTED", ""]
    lines = [
        "| Symbol | Matched Keywords | Published | Source | Headline |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in items[:25]:
        lines.append(
            f"| {item.get('symbol', '')} | {item.get('matched_keywords', '')} | "
            f"{item.get('published_at', '')} | {item.get('source', '')} | {item.get('headline', '')} |"
        )
    lines.append("")
    return lines


def price_above_entry_lines(rows: list[TradePlanRow]) -> list[str]:
    selected = [row for row in rows if "PRICE_ALREADY_ABOVE_ENTRY" in row.trade_plan.warnings]
    if not selected:
        return ["- None.", ""]
    lines = [
        "| Symbol | Price | Entry | Warning |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in selected:
        lines.append(f"| {row.symbol} | {money(row.last_price)} | {money(row.trade_plan.bullish_entry)} | PRICE_ALREADY_ABOVE_ENTRY |")
    lines.append("")
    return lines


def row_to_csv(row: TradePlanRow) -> dict[str, object]:
    tech = row.technical_levels
    plan = row.trade_plan
    return {
        "Rank": row.rank,
        "Symbol": row.symbol,
        "Last Price": row.last_price,
        "Premarket Price": row.premarket_price,
        "Premarket %": row.premarket_percent,
        "Premarket Volume": row.premarket_volume,
        "Intraday Volume": row.intraday_volume,
        "20-Day Average Daily Volume": row.average_daily_volume_20,
        "RVOL Formula Used": row.rvol_formula_used,
        "RVOL Numerator": row.rvol_numerator,
        "RVOL Denominator": row.rvol_denominator,
        "RVOL Type": row.rvol_type,
        "Current Bid": row.current_bid,
        "Current Ask": row.current_ask,
        "Spread %": row.spread_percent,
        "Relative Volume": row.relative_volume,
        "Float": row.float_shares,
        "Market Cap": row.market_cap,
        "ATR": row.atr,
        "Momentum Score": row.momentum_score,
        "News Score": row.news_score,
        "Composite Score": row.composite_score,
        "Catalyst Summary": row.catalyst_summary,
        "Previous Day High": tech.previous_day_high,
        "Previous Day Low": tech.previous_day_low,
        "Previous Day Close": tech.previous_day_close,
        "5-Day High": tech.five_day_high,
        "20-Day High": tech.twenty_day_high,
        "Support Level": tech.support_level,
        "Resistance Level": tech.resistance_level,
        "Bullish Entry": plan.bullish_entry,
        "Bullish Stop": plan.bullish_stop,
        "Bullish Target 1": plan.bullish_target_1,
        "Bullish Target 2": plan.bullish_target_2,
        "Risk/Reward Ratio": plan.risk_reward_ratio,
        "Estimated Shares for $500": plan.estimated_shares_for_500,
        "Estimated Dollar Risk": plan.estimated_dollar_risk,
        "Estimated Target 1 Reward": plan.estimated_target_1_reward,
        "Risk-On Rank": row.risk_on_rank,
        "Risk-Off Rank": row.risk_off_rank,
        "Likely Outperform QQQ": row.likely_outperform_qqq,
        "Likely Outperform SMH": row.likely_outperform_smh,
        "Plan Confidence": plan.confidence,
        "Tradeability": plan.tradeability,
        "Readiness": plan.readiness,
        "Blocking Reasons": " | ".join(plan.blocking_reasons),
        "Warnings": " | ".join(plan.warnings),
    }


def row_to_json(row: TradePlanRow) -> dict[str, object]:
    return {
        "rank": row.rank,
        "symbol": row.symbol,
        "company": row.company,
        "sector": row.sector,
        "industry": row.industry,
        "market_data": {
            "last_price": row.last_price,
            "premarket_price": row.premarket_price,
            "premarket_percent": row.premarket_percent,
            "premarket_volume": row.premarket_volume,
            "intraday_volume": row.intraday_volume,
            "twenty_day_average_daily_volume": row.average_daily_volume_20,
            "rvol_formula_used": row.rvol_formula_used,
            "rvol_numerator": row.rvol_numerator,
            "rvol_denominator": row.rvol_denominator,
            "rvol_type": row.rvol_type,
            "current_bid": row.current_bid,
            "current_ask": row.current_ask,
            "spread_percent": row.spread_percent,
            "relative_volume": row.relative_volume,
            "float": row.float_shares,
            "market_cap": row.market_cap,
            "atr": row.atr,
        },
        "scoring": {
            "momentum_score": row.momentum_score,
            "news_score": row.news_score,
            "composite_score": row.composite_score,
            "composite_profile": COMPOSITE_PROFILE,
            "catalyst_summary": row.catalyst_summary,
            "catalyst_cluster": row.catalyst_cluster,
            "catalyst_confidence": row.catalyst_confidence,
        },
        "technical_levels": asdict(row.technical_levels),
        "market_tape": asdict(row.market_tape),
        "trade_plan": asdict(row.trade_plan),
        "fed_event_analysis": {
            "risk_on_rank": row.risk_on_rank,
            "risk_off_rank": row.risk_off_rank,
            "likely_outperform_qqq": row.likely_outperform_qqq,
            "likely_outperform_smh": row.likely_outperform_smh,
        },
        "opportunity_notes": row.opportunity_notes,
    }


def latest_capture_path(*, preferred_session: str = "morning") -> Path:
    captures = sorted(CAPTURES_DIR.rglob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    preferred = [path for path in captures if path.stem == preferred_session]
    if preferred:
        return preferred[0]
    if captures:
        return captures[0]
    raise FileNotFoundError(f"No raw capture JSON files found under {CAPTURES_DIR}")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def average_daily_range(bars: Iterable[PriceBar]) -> float | None:
    ranges = [bar.high - bar.low for bar in bars if bar.high is not None and bar.low is not None]
    if not ranges:
        return None
    return sum(ranges) / len(ranges)


def clamp(value: float | int | None, low: int, high: int) -> int:
    if value is None:
        return low
    return max(low, min(high, int(value)))


def rounded(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), 2)


def capture_date_label(value: str) -> str:
    parsed = parse_datetime(value)
    if parsed:
        return parsed.strftime("%Y-%m-%d")
    return now_central().strftime("%Y-%m-%d")


def format_optional(value: float | int | None) -> str:
    return "n/a" if value is None else str(value)


def format_int(value: int | None) -> str:
    return "n/a" if value is None else f"{value:,}"


def money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def first_float(payload: dict, *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def first_int(payload: dict, *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def spread_percent(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    midpoint = (bid + ask) / 2
    if midpoint <= 0:
        return None
    return ((ask - bid) / midpoint) * 100


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Momentum Hunter trade-planning briefing.")
    parser.add_argument("--capture", type=Path, default=None, help="Raw capture JSON to use. Defaults to latest morning capture.")
    parser.add_argument("--capital", type=float, default=DEFAULT_CAPITAL, help="Capital assumption for position/risk math.")
    parser.add_argument("--fetch-bars", action="store_true", help="Fetch daily Yahoo bars for technical levels.")
    parser.add_argument(
        "--fetch-market-data",
        action="store_true",
        help="Fetch Yahoo daily bars and quote tape for execution-readiness fields.",
    )
    parser.add_argument("--event-mode", action="store_true", help="Generate Fed/Event Mode report sections and polling cadence.")
    parser.add_argument("--as-of", default="", help="Override report time for testing/polling policy, ISO format.")
    args = parser.parse_args()
    capture_path = args.capture or latest_capture_path(preferred_session="morning")
    as_of = parse_datetime(args.as_of) if args.as_of else None
    report = build_trade_planning_report(
        capture_path,
        capital=args.capital,
        fetch_bars=args.fetch_bars,
        fetch_market_data=args.fetch_market_data,
        event_mode=args.event_mode,
        as_of=as_of,
    )
    paths = export_trade_planning_report(report)
    print(json.dumps({key: str(value) for key, value in paths.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
