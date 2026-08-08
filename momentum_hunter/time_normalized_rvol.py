"""Time-normalized relative-volume evidence from canonical Schwab minute bars."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

from momentum_hunter.canonical_candle_evidence import (
    CanonicalCandleEvidenceError,
    CanonicalMinuteBar,
    load_canonical_minute_bars,
)
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE, EXECUTION_INELIGIBLE
from momentum_hunter.scheduling import is_market_open_day
from momentum_hunter.schwab_candle_contract import EASTERN_TZ, SCHWAB_PRICE_HISTORY_SOURCE
from momentum_hunter.schwab_candle_store import SCHWAB_CANDLE_STORE_ROOT


TIME_NORMALIZED_RVOL_SCHEMA_VERSION = 1
TIME_NORMALIZED_RVOL_PROFILE = "time-normalized-rvol-v1"
TIME_NORMALIZED_RVOL_FORMULA = (
    "current cumulative canonical minute volume through the last completed session minute "
    "/ mean prior-session cumulative volume through the same session minute"
)
PREMARKET_RVOL = "PREMARKET_RVOL"
INTRADAY_RVOL = "INTRADAY_RVOL"
DAILY_RVOL = "DAILY_RVOL"
UNKNOWN_RVOL = "UNKNOWN_RVOL"
DEFAULT_BASELINE_SESSION_TARGET = 20
DEFAULT_MINIMUM_BASELINE_SESSIONS = 5
LEGACY_RVOL_RESEARCH_ONLY = "LEGACY_RVOL_RESEARCH_ONLY"
RVOL_EVIDENCE_EXECUTION_INELIGIBLE = "RVOL_EVIDENCE_EXECUTION_INELIGIBLE"


@dataclass(frozen=True)
class TimeNormalizedRvolEvidence:
    schema_version: int = TIME_NORMALIZED_RVOL_SCHEMA_VERSION
    profile: str = TIME_NORMALIZED_RVOL_PROFILE
    status: str = EXECUTION_INELIGIBLE
    source: str = SCHWAB_PRICE_HISTORY_SOURCE
    symbol: str = ""
    rvol_type: str = UNKNOWN_RVOL
    session_name: str = "UNAVAILABLE"
    session_date: str = ""
    session_minute: int | None = None
    window_start: str = ""
    through_minute: str = ""
    observed_volume: int | None = None
    expected_volume: float | None = None
    relative_volume: float | None = None
    current_bar_count: int = 0
    expected_current_bar_count: int = 0
    baseline_session_count: int = 0
    minimum_baseline_sessions: int = DEFAULT_MINIMUM_BASELINE_SESSIONS
    target_baseline_sessions: int = DEFAULT_BASELINE_SESSION_TARGET
    baseline_session_dates: tuple[str, ...] = ()
    formula: str = TIME_NORMALIZED_RVOL_FORMULA
    findings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def execution_eligible(self) -> bool:
        return self.status == EXECUTION_ELIGIBLE


def load_time_normalized_rvol_evidence(
    symbols: Iterable[str],
    *,
    as_of: datetime,
    store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
    minimum_baseline_sessions: int = DEFAULT_MINIMUM_BASELINE_SESSIONS,
    target_baseline_sessions: int = DEFAULT_BASELINE_SESSION_TARGET,
) -> dict[str, TimeNormalizedRvolEvidence]:
    """Read canonical bars once and calculate one fail-closed result per symbol."""

    normalized = tuple(sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}))
    if not normalized:
        return {}
    try:
        bars_by_symbol = load_canonical_minute_bars(
            store_root=store_root,
            symbols=normalized,
        )
    except CanonicalCandleEvidenceError:
        return {
            symbol: unavailable_rvol_evidence(
                symbol,
                as_of=as_of,
                finding="CANONICAL_CANDLE_EVIDENCE_INVALID",
                minimum_baseline_sessions=minimum_baseline_sessions,
                target_baseline_sessions=target_baseline_sessions,
            )
            for symbol in normalized
        }
    return {
        symbol: calculate_time_normalized_rvol(
            symbol,
            bars_by_symbol.get(symbol, ()),
            as_of=as_of,
            minimum_baseline_sessions=minimum_baseline_sessions,
            target_baseline_sessions=target_baseline_sessions,
        )
        for symbol in normalized
    }


def calculate_time_normalized_rvol(
    symbol: str,
    bars: Iterable[CanonicalMinuteBar],
    *,
    as_of: datetime,
    minimum_baseline_sessions: int = DEFAULT_MINIMUM_BASELINE_SESSIONS,
    target_baseline_sessions: int = DEFAULT_BASELINE_SESSION_TARGET,
) -> TimeNormalizedRvolEvidence:
    """Compare elapsed-session volume with identical elapsed windows in prior sessions."""

    normalized_symbol = str(symbol).strip().upper()
    if not normalized_symbol:
        raise ValueError("Time-normalized RVOL requires a symbol.")
    aware_as_of = _aware(as_of)
    if minimum_baseline_sessions < 1:
        raise ValueError("minimum_baseline_sessions must be positive.")
    if target_baseline_sessions < minimum_baseline_sessions:
        raise ValueError("target_baseline_sessions must meet the minimum.")

    session = _session_window(aware_as_of)
    if session is None:
        return unavailable_rvol_evidence(
            normalized_symbol,
            as_of=aware_as_of,
            finding="RVOL_SESSION_UNAVAILABLE",
            minimum_baseline_sessions=minimum_baseline_sessions,
            target_baseline_sessions=target_baseline_sessions,
        )
    rvol_type, session_name, current_date, start, through = session
    expected_minutes = _minute_range(start, through)
    if not expected_minutes:
        return _evidence(
            normalized_symbol,
            rvol_type=rvol_type,
            session_name=session_name,
            session_date=current_date,
            start=start,
            through=through,
            expected_count=0,
            minimum_baseline_sessions=minimum_baseline_sessions,
            target_baseline_sessions=target_baseline_sessions,
            findings=("NO_COMPLETED_SESSION_MINUTE",),
        )

    grouped: dict[date, dict[datetime, float]] = {}
    findings: list[str] = []
    for bar in bars:
        if bar.symbol.upper() != normalized_symbol:
            findings.append("FOREIGN_SYMBOL_BAR_IGNORED")
            continue
        parsed = _parse_timestamp(bar.timestamp).astimezone(EASTERN_TZ)
        minute = parsed.replace(second=0, microsecond=0)
        if parsed != minute:
            findings.append("NON_MINUTE_TIMESTAMP_IGNORED")
            continue
        if bar.source != SCHWAB_PRICE_HISTORY_SOURCE:
            findings.append("NONCANONICAL_SOURCE_BAR_IGNORED")
            continue
        if not math.isfinite(bar.volume) or bar.volume < 0:
            findings.append("INVALID_VOLUME_BAR_IGNORED")
            continue
        grouped.setdefault(minute.date(), {})[minute] = float(bar.volume)

    current_window = grouped.get(current_date, {})
    current_volume, current_missing = _window_volume(current_window, expected_minutes)
    if current_missing:
        findings.append("MISSING_CURRENT_SESSION_BARS")
        findings.append(f"CURRENT_SESSION_MISSING_MINUTES:{len(current_missing)}")

    baseline: list[tuple[date, float]] = []
    for session_date in sorted((item for item in grouped if item < current_date), reverse=True):
        if not is_market_open_day(session_date):
            continue
        historical_start = datetime.combine(session_date, start.timetz().replace(tzinfo=None), EASTERN_TZ)
        historical_through = historical_start + (through - start)
        historical_minutes = _minute_range(historical_start, historical_through)
        volume, missing = _window_volume(grouped[session_date], historical_minutes)
        if missing:
            continue
        baseline.append((session_date, volume))
        if len(baseline) >= target_baseline_sessions:
            break

    if len(baseline) < minimum_baseline_sessions:
        findings.append("INSUFFICIENT_COMPARABLE_BASELINE_SESSIONS")
    expected_volume = (
        sum(volume for _, volume in baseline) / len(baseline)
        if baseline
        else None
    )
    if expected_volume is not None and expected_volume <= 0:
        findings.append("ZERO_EXPECTED_BASELINE_VOLUME")
        expected_volume = None
    relative_volume = (
        current_volume / expected_volume
        if current_volume is not None and expected_volume is not None
        else None
    )
    eligible = (
        not current_missing
        and current_volume is not None
        and expected_volume is not None
        and len(baseline) >= minimum_baseline_sessions
    )
    if eligible:
        findings.append("TIME_NORMALIZED_RVOL_AVAILABLE")
    return _evidence(
        normalized_symbol,
        rvol_type=rvol_type,
        session_name=session_name,
        session_date=current_date,
        start=start,
        through=through,
        expected_count=len(expected_minutes),
        minimum_baseline_sessions=minimum_baseline_sessions,
        target_baseline_sessions=target_baseline_sessions,
        observed_volume=int(round(current_volume)) if current_volume is not None else None,
        expected_volume=expected_volume,
        relative_volume=relative_volume,
        current_bar_count=len(expected_minutes) - len(current_missing),
        baseline=baseline,
        findings=tuple(dict.fromkeys(findings)),
        eligible=eligible,
    )


def unavailable_rvol_evidence(
    symbol: str,
    *,
    as_of: datetime,
    finding: str,
    minimum_baseline_sessions: int = DEFAULT_MINIMUM_BASELINE_SESSIONS,
    target_baseline_sessions: int = DEFAULT_BASELINE_SESSION_TARGET,
) -> TimeNormalizedRvolEvidence:
    session = _session_window(_aware(as_of))
    if session is None:
        return TimeNormalizedRvolEvidence(
            symbol=str(symbol).strip().upper(),
            minimum_baseline_sessions=minimum_baseline_sessions,
            target_baseline_sessions=target_baseline_sessions,
            findings=(finding,),
        )
    rvol_type, session_name, session_date, start, through = session
    return _evidence(
        str(symbol).strip().upper(),
        rvol_type=rvol_type,
        session_name=session_name,
        session_date=session_date,
        start=start,
        through=through,
        expected_count=len(_minute_range(start, through)),
        minimum_baseline_sessions=minimum_baseline_sessions,
        target_baseline_sessions=target_baseline_sessions,
        findings=(finding,),
    )


def _session_window(
    as_of: datetime,
) -> tuple[str, str, date, datetime, datetime] | None:
    eastern = as_of.astimezone(EASTERN_TZ)
    session_date = eastern.date()
    if not is_market_open_day(session_date):
        return None
    local_time = eastern.timetz().replace(tzinfo=None)
    if time(4, 0) <= local_time < time(9, 30):
        rvol_type = PREMARKET_RVOL
        session_name = "PREMARKET"
        start_time = time(4, 0)
    elif time(9, 30) <= local_time < time(16, 0):
        rvol_type = INTRADAY_RVOL
        session_name = "REGULAR"
        start_time = time(9, 30)
    elif local_time >= time(16, 0):
        rvol_type = DAILY_RVOL
        session_name = "REGULAR_COMPLETE"
        start_time = time(9, 30)
    else:
        return None
    start = datetime.combine(session_date, start_time, EASTERN_TZ)
    through = (
        datetime.combine(session_date, time(15, 59), EASTERN_TZ)
        if rvol_type == DAILY_RVOL
        else eastern.replace(second=0, microsecond=0) - timedelta(minutes=1)
    )
    return rvol_type, session_name, session_date, start, through


def _minute_range(start: datetime, through: datetime) -> tuple[datetime, ...]:
    if through < start:
        return ()
    count = int((through - start).total_seconds() // 60) + 1
    return tuple(start + timedelta(minutes=index) for index in range(count))


def _window_volume(
    available: Mapping[datetime, float],
    expected_minutes: tuple[datetime, ...],
) -> tuple[float | None, tuple[datetime, ...]]:
    missing = tuple(minute for minute in expected_minutes if minute not in available)
    if missing:
        return None, missing
    return sum(available[minute] for minute in expected_minutes), ()


def _evidence(
    symbol: str,
    *,
    rvol_type: str,
    session_name: str,
    session_date: date,
    start: datetime,
    through: datetime,
    expected_count: int,
    minimum_baseline_sessions: int,
    target_baseline_sessions: int,
    observed_volume: int | None = None,
    expected_volume: float | None = None,
    relative_volume: float | None = None,
    current_bar_count: int = 0,
    baseline: list[tuple[date, float]] | None = None,
    findings: tuple[str, ...] = (),
    eligible: bool = False,
) -> TimeNormalizedRvolEvidence:
    baseline = baseline or []
    return TimeNormalizedRvolEvidence(
        status=EXECUTION_ELIGIBLE if eligible else EXECUTION_INELIGIBLE,
        symbol=symbol,
        rvol_type=rvol_type,
        session_name=session_name,
        session_date=session_date.isoformat(),
        session_minute=expected_count or None,
        window_start=start.astimezone(timezone.utc).isoformat(),
        through_minute=(through.astimezone(timezone.utc).isoformat() if expected_count else ""),
        observed_volume=observed_volume,
        expected_volume=(round(expected_volume, 6) if expected_volume is not None else None),
        relative_volume=(round(relative_volume, 4) if relative_volume is not None else None),
        current_bar_count=current_bar_count,
        expected_current_bar_count=expected_count,
        baseline_session_count=len(baseline),
        minimum_baseline_sessions=minimum_baseline_sessions,
        target_baseline_sessions=target_baseline_sessions,
        baseline_session_dates=tuple(item.isoformat() for item, _ in baseline),
        findings=findings,
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Canonical RVOL candle timestamp was invalid.") from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Time-normalized RVOL requires a timezone-aware timestamp.")
    return value.astimezone(timezone.utc)
