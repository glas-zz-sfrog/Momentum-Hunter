from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import requests

from momentum_hunter.storage import ANALYSIS_CSV, DATA_DIR, ensure_app_dirs


OUTCOMES_CSV = DATA_DIR / "analysis-outcomes.csv"


@dataclass(frozen=True)
class PriceBar:
    day: str
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class CandidateOutcome:
    status: str
    next_day_return_pct: float | None
    five_day_return_pct: float | None
    max_gain_pct: float | None
    max_drawdown_pct: float | None
    outcome_start_date: str = ""
    outcome_end_date: str = ""


OUTCOME_FIELDNAMES = [
    "capture_date",
    "capture_time",
    "session",
    "capture_session",
    "capture_calendar_status",
    "is_market_open_day",
    "is_study_eligible",
    "next_market_session_date",
    "scheduling_policy_version",
    "mode",
    "provider",
    "scanner",
    "market_regime",
    "rank",
    "selected",
    "reviewed",
    "ticker",
    "company",
    "score",
    "news_hours_old",
    "freshness",
    "freshness_score",
    "article_count",
    "valid_timestamp_count",
    "known_timestamp_count",
    "unknown_timestamp_count",
    "future_timestamp_count",
    "excluded_from_scoring_count",
    "latest_article_age_hours",
    "oldest_article_age_hours",
    "news_range",
    "freshest_headline",
    "score_profile",
    "score_regime",
    "price",
    "percent_change",
    "volume",
    "relative_volume",
    "sector",
    "industry",
    "next_day_return_pct",
    "five_day_return_pct",
    "max_gain_pct",
    "max_drawdown_pct",
    "outcome_start_date",
    "outcome_end_date",
    "outcome_status",
]


def update_outcomes(
    *,
    capture_path: Path = ANALYSIS_CSV,
    output_path: Path = OUTCOMES_CSV,
    session: requests.Session | None = None,
) -> tuple[Path, int]:
    ensure_app_dirs()
    if not capture_path.exists():
        write_outcome_rows([], output_path)
        return output_path, 0
    with capture_path.open(newline="", encoding="utf-8") as file:
        capture_rows = list(csv.DictReader(file))

    http = session or build_http_session()
    bars_by_ticker: dict[str, list[PriceBar]] = {}
    outcome_rows = []
    for row in capture_rows:
        ticker = row.get("ticker", "")
        if ticker not in bars_by_ticker:
            bars_by_ticker[ticker] = fetch_price_bars(http, ticker)
        outcome = calculate_outcome(row, bars_by_ticker[ticker])
        outcome_rows.append(row_to_outcome(row, outcome))

    write_outcome_rows(outcome_rows, output_path)
    return output_path, len(outcome_rows)


def calculate_outcome(row: dict, bars: list[PriceBar]) -> CandidateOutcome:
    capture_date = row.get("capture_date", "")
    capture_price = parse_float(row.get("price", "0"))
    if not capture_date or capture_price <= 0:
        return CandidateOutcome("missing_capture_price", None, None, None, None)

    future_bars = [bar for bar in bars if bar.day > capture_date]
    if len(future_bars) < 1:
        return CandidateOutcome("pending_next_day", None, None, None, None)

    first_bar = future_bars[0]
    five_bar = future_bars[4] if len(future_bars) >= 5 else None
    window = future_bars[:5]
    next_day_return = percent_return(first_bar.close, capture_price)
    five_day_return = percent_return(five_bar.close, capture_price) if five_bar else None
    max_gain = percent_return(max(bar.high for bar in window), capture_price)
    max_drawdown = percent_return(min(bar.low for bar in window), capture_price)
    status = "complete" if five_bar else "pending_five_day"
    return CandidateOutcome(
        status=status,
        next_day_return_pct=round(next_day_return, 4),
        five_day_return_pct=round(five_day_return, 4) if five_day_return is not None else None,
        max_gain_pct=round(max_gain, 4),
        max_drawdown_pct=round(max_drawdown, 4),
        outcome_start_date=first_bar.day,
        outcome_end_date=(five_bar.day if five_bar else window[-1].day),
    )


def fetch_price_bars(session: requests.Session, ticker: str) -> list[PriceBar]:
    if not ticker:
        return []
    symbol = ticker.replace(".", "-")
    period1 = int((datetime.now() - timedelta(days=460)).timestamp())
    period2 = int((datetime.now() + timedelta(days=3)).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d&events=history"
    )
    try:
        response = session.get(url, timeout=20)
    except requests.RequestException:
        return []
    if response.status_code != 200:
        return []
    payload = response.json()
    result = payload.get("chart", {}).get("result") or []
    if not result:
        return []
    timestamps = result[0].get("timestamp") or []
    quote = (result[0].get("indicators", {}).get("quote") or [{}])[0]
    adjclose = (result[0].get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
    bars: list[PriceBar] = []
    for index, timestamp in enumerate(timestamps):
        try:
            raw_close = quote["close"][index]
            raw_high = quote["high"][index]
            raw_low = quote["low"][index]
            adjusted_close = adjclose[index] if index < len(adjclose) else raw_close
        except (KeyError, IndexError):
            continue
        if None in (raw_close, raw_high, raw_low, adjusted_close):
            continue
        adjustment_ratio = float(adjusted_close) / float(raw_close) if raw_close else 1.0
        bars.append(
            PriceBar(
                day=datetime.fromtimestamp(timestamp).date().isoformat(),
                high=float(raw_high) * adjustment_ratio,
                low=float(raw_low) * adjustment_ratio,
                close=float(adjusted_close),
            )
        )
    return bars


def build_http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
            )
        }
    )
    return session


def row_to_outcome(row: dict, outcome: CandidateOutcome) -> dict:
    output = {field: row.get(field, "") for field in OUTCOME_FIELDNAMES}
    output.update(
        {
            "next_day_return_pct": format_optional(outcome.next_day_return_pct),
            "five_day_return_pct": format_optional(outcome.five_day_return_pct),
            "max_gain_pct": format_optional(outcome.max_gain_pct),
            "max_drawdown_pct": format_optional(outcome.max_drawdown_pct),
            "outcome_start_date": outcome.outcome_start_date,
            "outcome_end_date": outcome.outcome_end_date,
            "outcome_status": outcome.status,
        }
    )
    return output


def write_outcome_rows(rows: list[dict], output_path: Path) -> None:
    ensure_app_dirs()
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTCOME_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def percent_return(value: float, basis: float) -> float:
    return ((value - basis) / basis) * 100


def format_optional(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def parse_float(value: str) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0
