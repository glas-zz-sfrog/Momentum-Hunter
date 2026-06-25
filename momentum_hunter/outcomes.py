from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from momentum_hunter.scheduling import is_market_open_day, next_market_open_date
from momentum_hunter.storage import ANALYSIS_CSV, DATA_DIR, ensure_app_dirs
from momentum_hunter.time_utils import now_central


OUTCOMES_CSV = DATA_DIR / "analysis-outcomes.csv"
OUTCOME_CALCULATION_VERSION = "outcome-session-v1"

OUTCOME_STATE_PENDING_NOT_MATURE = "pending_not_mature"
OUTCOME_STATE_COMPLETE = "complete"
OUTCOME_STATE_PROVIDER_DATA_MISSING = "provider_data_missing"
OUTCOME_STATE_CALCULATION_FAILED = "calculation_failed"
OUTCOME_STATE_INELIGIBLE_CAPTURE = "ineligible_capture"
OUTCOME_STATE_CALENDAR_MAPPING_ERROR = "calendar_mapping_error"


@dataclass(frozen=True)
class PriceBar:
    day: str
    high: float
    low: float
    close: float
    volume: int | None = None


@dataclass(frozen=True)
class CandidateOutcome:
    status: str
    next_day_return_pct: float | None
    five_day_return_pct: float | None
    max_gain_pct: float | None
    max_drawdown_pct: float | None
    outcome_start_date: str = ""
    outcome_end_date: str = ""
    expected_next_day_session_date: str = ""
    expected_five_day_session_date: str = ""
    next_day_outcome_state: str = ""
    five_day_outcome_state: str = ""
    outcome_reason: str = ""
    outcome_calculation_version: str = OUTCOME_CALCULATION_VERSION


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
    "expected_next_day_session_date",
    "expected_five_day_session_date",
    "next_day_outcome_state",
    "five_day_outcome_state",
    "outcome_reason",
    "outcome_calculation_version",
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


def calculate_outcome(row: dict, bars: list[PriceBar], *, as_of_date: date | None = None) -> CandidateOutcome:
    capture_date = row.get("capture_date", "")
    capture_price = parse_float(row.get("price", "0"))
    current_date = as_of_date or now_central().date()
    try:
        expected_next_day, expected_five_day = expected_outcome_session_dates(capture_date)
    except ValueError as exc:
        return CandidateOutcome(
            "calendar_mapping_error",
            None,
            None,
            None,
            None,
            next_day_outcome_state=OUTCOME_STATE_CALENDAR_MAPPING_ERROR,
            five_day_outcome_state=OUTCOME_STATE_CALENDAR_MAPPING_ERROR,
            outcome_reason=f"calendar_mapping_error: {exc}",
        )
    expected_next_text = expected_next_day.isoformat()
    expected_five_text = expected_five_day.isoformat()
    if not is_market_open_day(expected_next_day) or not is_market_open_day(expected_five_day):
        return CandidateOutcome(
            "calendar_mapping_error",
            None,
            None,
            None,
            None,
            expected_next_day_session_date=expected_next_text,
            expected_five_day_session_date=expected_five_text,
            next_day_outcome_state=OUTCOME_STATE_CALENDAR_MAPPING_ERROR,
            five_day_outcome_state=OUTCOME_STATE_CALENDAR_MAPPING_ERROR,
            outcome_reason="calendar_mapping_error: expected outcome session is not a market-open day",
        )
    if is_explicit_false(row.get("is_study_eligible", "")):
        return CandidateOutcome(
            "ineligible_capture",
            None,
            None,
            None,
            None,
            expected_next_day_session_date=expected_next_text,
            expected_five_day_session_date=expected_five_text,
            next_day_outcome_state=OUTCOME_STATE_INELIGIBLE_CAPTURE,
            five_day_outcome_state=OUTCOME_STATE_INELIGIBLE_CAPTURE,
            outcome_reason="ineligible_capture: capture is excluded from ordinary study outcome calculations",
        )
    if not capture_date or capture_price <= 0:
        return CandidateOutcome(
            "missing_capture_price",
            None,
            None,
            None,
            None,
            expected_next_day_session_date=expected_next_text,
            expected_five_day_session_date=expected_five_text,
            next_day_outcome_state=OUTCOME_STATE_CALCULATION_FAILED,
            five_day_outcome_state=OUTCOME_STATE_CALCULATION_FAILED,
            outcome_reason="calculation_failed: missing or non-positive capture price",
        )

    bars_by_day = {bar.day: bar for bar in sorted(bars, key=lambda bar: bar.day)}
    first_bar = bars_by_day.get(expected_next_text)
    if first_bar is None:
        state = (
            OUTCOME_STATE_PENDING_NOT_MATURE
            if current_date <= expected_next_day
            else OUTCOME_STATE_PROVIDER_DATA_MISSING
        )
        status = "pending_next_day" if state == OUTCOME_STATE_PENDING_NOT_MATURE else "provider_data_missing"
        return CandidateOutcome(
            status,
            None,
            None,
            None,
            None,
            expected_next_day_session_date=expected_next_text,
            expected_five_day_session_date=expected_five_text,
            next_day_outcome_state=state,
            five_day_outcome_state=state,
            outcome_reason=f"{state}: no price bar for expected next-day session {expected_next_text}",
        )

    future_bars = [bar for bar in sorted(bars, key=lambda bar: bar.day) if expected_next_text <= bar.day <= expected_five_text]
    five_bar = bars_by_day.get(expected_five_text)
    window = future_bars[:5]
    if not window:
        return CandidateOutcome(
            "calculation_failed",
            None,
            None,
            None,
            None,
            expected_next_day_session_date=expected_next_text,
            expected_five_day_session_date=expected_five_text,
            next_day_outcome_state=OUTCOME_STATE_CALCULATION_FAILED,
            five_day_outcome_state=OUTCOME_STATE_CALCULATION_FAILED,
            outcome_reason="calculation_failed: no usable outcome window after expected next-day session",
        )
    next_day_return = percent_return(first_bar.close, capture_price)
    five_day_return = percent_return(five_bar.close, capture_price) if five_bar else None
    max_gain = percent_return(max(bar.high for bar in window), capture_price)
    max_drawdown = percent_return(min(bar.low for bar in window), capture_price)
    if five_bar:
        status = "complete"
        five_day_state = OUTCOME_STATE_COMPLETE
        reason = "complete: next-day and five-day outcome sessions are populated"
    else:
        five_day_state = (
            OUTCOME_STATE_PENDING_NOT_MATURE
            if current_date <= expected_five_day
            else OUTCOME_STATE_PROVIDER_DATA_MISSING
        )
        status = "pending_five_day" if five_day_state == OUTCOME_STATE_PENDING_NOT_MATURE else "provider_data_missing"
        reason = f"{five_day_state}: no price bar for expected five-day session {expected_five_text}"
    return CandidateOutcome(
        status=status,
        next_day_return_pct=round(next_day_return, 4),
        five_day_return_pct=round(five_day_return, 4) if five_day_return is not None else None,
        max_gain_pct=round(max_gain, 4),
        max_drawdown_pct=round(max_drawdown, 4),
        outcome_start_date=first_bar.day,
        outcome_end_date=(five_bar.day if five_bar else window[-1].day),
        expected_next_day_session_date=expected_next_text,
        expected_five_day_session_date=expected_five_text,
        next_day_outcome_state=OUTCOME_STATE_COMPLETE,
        five_day_outcome_state=five_day_state,
        outcome_reason=reason,
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
            volumes = quote.get("volume") or []
            raw_volume = volumes[index] if index < len(volumes) else None
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
                volume=int(raw_volume) if raw_volume is not None else None,
            )
        )
    return bars


def build_http_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
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
            "expected_next_day_session_date": outcome.expected_next_day_session_date,
            "expected_five_day_session_date": outcome.expected_five_day_session_date,
            "next_day_outcome_state": outcome.next_day_outcome_state,
            "five_day_outcome_state": outcome.five_day_outcome_state,
            "outcome_reason": outcome.outcome_reason,
            "outcome_calculation_version": outcome.outcome_calculation_version,
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


def expected_outcome_session_dates(capture_date: str) -> tuple[date, date]:
    try:
        capture_day = date.fromisoformat(capture_date)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid capture_date {capture_date!r}") from exc
    expected_next = next_market_open_date(capture_day, include_today=False)
    expected_five = expected_next
    for _ in range(4):
        expected_five = next_market_open_date(expected_five, include_today=False)
    return expected_next, expected_five


def is_explicit_false(value: object) -> bool:
    return str(value).strip().lower() in {"false", "0", "no"}
