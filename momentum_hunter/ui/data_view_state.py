from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from momentum_hunter.time_utils import CENTRAL_TZ, format_central, now_central


class DataViewState(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    NEXT_SESSION_REVIEW = "next_session_review"
    EXPIRED_REVIEW = "expired_review"
    HISTORICAL = "historical"
    STUDY = "study"


@dataclass(frozen=True)
class FreshnessSettings:
    timezone: str = "America/Chicago"
    current_dashboard_warning_minutes: int = 10
    current_dashboard_stale_minutes: int = 20
    require_manual_refresh_after_stale: bool = True
    show_age_seconds_under_minutes: int = 5
    show_age_minutes: bool = True


@dataclass(frozen=True)
class DataViewStyle:
    state: DataViewState
    object_name: str
    banner_text: str
    detail_label: str
    chart_prefix: str
    header_stylesheet: str
    read_only: bool
    decision_status: str
    age_text: str
    captured_text: str
    is_warning: bool = False


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ui_freshness_settings.json"


def load_freshness_settings() -> FreshnessSettings:
    if not CONFIG_PATH.exists():
        return FreshnessSettings()
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return FreshnessSettings(
        timezone=raw.get("timezone", "America/Chicago"),
        current_dashboard_warning_minutes=int(raw.get("current_dashboard_warning_minutes", 10)),
        current_dashboard_stale_minutes=int(raw.get("current_dashboard_stale_minutes", 20)),
        require_manual_refresh_after_stale=bool(raw.get("require_manual_refresh_after_stale", True)),
        show_age_seconds_under_minutes=int(raw.get("show_age_seconds_under_minutes", 5)),
        show_age_minutes=bool(raw.get("show_age_minutes", True)),
    )


def get_data_view_style(
    state: DataViewState,
    *,
    captured_at: datetime | None,
    session_label: str = "",
    study_run_id: str = "",
    source_range: str = "",
    now: datetime | None = None,
    settings: FreshnessSettings | None = None,
) -> DataViewStyle:
    settings = settings or load_freshness_settings()
    current_time = now or now_central()
    captured_at = normalize_datetime(captured_at)
    age_minutes = age_in_minutes(captured_at, current_time)
    age_text = format_age(captured_at, current_time, settings)
    captured_text = format_central(captured_at) if captured_at else "No current capture loaded"

    if state == DataViewState.CURRENT:
        if captured_at is None or age_minutes is None:
            return missing_style()
        if age_minutes > settings.current_dashboard_stale_minutes:
            return current_manual_aging_style(captured_text, age_text)
        if age_minutes > settings.current_dashboard_warning_minutes:
            return current_aging_style(captured_text, age_text)
        return current_style(captured_text, age_text)

    if state == DataViewState.STALE:
        return stale_style(captured_text, age_text)

    if state == DataViewState.NEXT_SESSION_REVIEW:
        if age_minutes is not None and age_minutes > settings.current_dashboard_stale_minutes:
            return next_session_aging_style(captured_text, age_text, session_label)
        return next_session_ready_style(captured_text, age_text, session_label)

    if state == DataViewState.EXPIRED_REVIEW:
        return expired_review_style(captured_text, age_text, session_label)

    if state == DataViewState.HISTORICAL:
        label = session_label.upper() if session_label else "SNAPSHOT"
        return DataViewStyle(
            state=DataViewState.HISTORICAL,
            object_name="viewStateHistorical",
            banner_text=(
                "HISTORICAL SNAPSHOT - READ ONLY\n"
                f"{label} capture from {captured_text} | Age: {age_text}\n"
                "Research only. This is not current market data."
            ),
            detail_label="HISTORICAL CANDIDATE - READ ONLY",
            chart_prefix="HISTORICAL - ",
            header_stylesheet=header_style("#4a355f", "#f4ecff", "#6d5780"),
            read_only=True,
            decision_status="Research only - not current market data",
            age_text=age_text,
            captured_text=captured_text,
        )

    return DataViewStyle(
        state=DataViewState.STUDY,
        object_name="viewStateStudy",
        banner_text=(
            "STUDY RESULTS - SIMULATED HISTORICAL DATA\n"
            f"Run: {study_run_id or 'unspecified'} | Source: {source_range or 'unspecified'}\n"
            "Research only. These results are not live market data."
        ),
        detail_label="STUDY CANDIDATE - SIMULATED DATA",
        chart_prefix="STUDY - ",
        header_stylesheet=header_style("#263f75", "#eaf1ff", "#3c5d9d"),
        read_only=True,
        decision_status="Research only - no live trading decision",
        age_text=age_text,
        captured_text=captured_text,
    )


def current_style(captured_text: str, age_text: str) -> DataViewStyle:
    return DataViewStyle(
        state=DataViewState.CURRENT,
        object_name="viewStateCurrent",
        banner_text=(
            "CURRENT DASHBOARD - LIVE REVIEW\n"
            f"Captured {captured_text} | Age: {age_text}\n"
            "Fresh decisions belong here."
        ),
        detail_label="LIVE REVIEW CANDIDATE",
        chart_prefix="LIVE - ",
        header_stylesheet=header_style("#1f6f4a", "#d8ffe8", "#2f8a61"),
        read_only=False,
        decision_status="Fresh decisions allowed here",
        age_text=age_text,
        captured_text=captured_text,
    )


def current_aging_style(captured_text: str, age_text: str) -> DataViewStyle:
    return DataViewStyle(
        state=DataViewState.CURRENT,
        object_name="viewStateAging",
        banner_text=(
            "DATA AGING - CONSIDER REFRESH\n"
            f"Captured {captured_text} | Age: {age_text}\n"
            "Refresh soon before making a new decision."
        ),
        detail_label="LIVE REVIEW CANDIDATE - DATA AGING",
        chart_prefix="LIVE - ",
        header_stylesheet=header_style("#80651e", "#fff0bd", "#a4812a"),
        read_only=False,
        decision_status="Freshness warning - consider refresh",
        age_text=age_text,
        captured_text=captured_text,
        is_warning=True,
    )


def current_manual_aging_style(captured_text: str, age_text: str) -> DataViewStyle:
    return DataViewStyle(
        state=DataViewState.CURRENT,
        object_name="viewStateAging",
        banner_text=(
            "CURRENT MANUAL SCAN - AGED BUT REVIEWABLE\n"
            f"Captured {captured_text} | Age: {age_text}\n"
            "Review is allowed, but confirm the setup before acting."
        ),
        detail_label="CURRENT MANUAL SCAN - AGED BUT REVIEWABLE",
        chart_prefix="AGED - ",
        header_stylesheet=header_style("#80651e", "#fff0bd", "#a4812a"),
        read_only=False,
        decision_status="Aged manual scan - review allowed with caution",
        age_text=age_text,
        captured_text=captured_text,
        is_warning=True,
    )


def next_session_ready_style(captured_text: str, age_text: str, session_label: str) -> DataViewStyle:
    label = review_session_label(session_label)
    return DataViewStyle(
        state=DataViewState.NEXT_SESSION_REVIEW,
        object_name="viewStateCurrent",
        banner_text=(
            "READY FOR NEXT SESSION REVIEW\n"
            f"{label} capture from {captured_text} | Age: {age_text}\n"
            "Review decisions, watchlist creation, and entry plans are allowed."
        ),
        detail_label="NEXT SESSION REVIEW CANDIDATE",
        chart_prefix="REVIEW - ",
        header_stylesheet=header_style("#1f6f4a", "#d8ffe8", "#2f8a61"),
        read_only=False,
        decision_status="Next-session review workflow allowed",
        age_text=age_text,
        captured_text=captured_text,
    )


def next_session_aging_style(captured_text: str, age_text: str, session_label: str) -> DataViewStyle:
    label = review_session_label(session_label)
    return DataViewStyle(
        state=DataViewState.NEXT_SESSION_REVIEW,
        object_name="viewStateAging",
        banner_text=(
            "AGING BUT REVIEWABLE\n"
            f"{label} capture from {captured_text} | Age: {age_text}\n"
            "This is still the active review snapshot for the next market session."
        ),
        detail_label="AGING BUT REVIEWABLE CANDIDATE",
        chart_prefix="AGING REVIEW - ",
        header_stylesheet=header_style("#80651e", "#fff0bd", "#a4812a"),
        read_only=False,
        decision_status="Aged next-session snapshot - review allowed with acknowledgement",
        age_text=age_text,
        captured_text=captured_text,
        is_warning=True,
    )


def expired_review_style(captured_text: str, age_text: str, session_label: str) -> DataViewStyle:
    label = review_session_label(session_label)
    return DataViewStyle(
        state=DataViewState.EXPIRED_REVIEW,
        object_name="viewStateStale",
        banner_text=(
            "EXPIRED REVIEW SNAPSHOT - READ ONLY\n"
            f"{label} capture from {captured_text} | Age: {age_text}\n"
            "The intended market session has started or passed. Do not create a new watchlist from this screen."
        ),
        detail_label="EXPIRED REVIEW SNAPSHOT - READ ONLY",
        chart_prefix="EXPIRED - ",
        header_stylesheet=header_style("#7a2e2e", "#ffe1e1", "#a14646"),
        read_only=True,
        decision_status="Expired for trading workflow",
        age_text=age_text,
        captured_text=captured_text,
    )


def missing_style() -> DataViewStyle:
    return DataViewStyle(
        state=DataViewState.STALE,
        object_name="viewStateStale",
        banner_text=(
            "CAPTURE MISSING\n"
            "No current capture is loaded.\n"
            "Run Scanner or open the latest review snapshot first."
        ),
        detail_label="NO CANDIDATE DATA LOADED",
        chart_prefix="MISSING - ",
        header_stylesheet=header_style("#7a2e2e", "#ffe1e1", "#a14646"),
        read_only=True,
        decision_status="Capture missing",
        age_text="unknown",
        captured_text="No current capture loaded",
    )


def stale_style(captured_text: str, age_text: str) -> DataViewStyle:
    return DataViewStyle(
        state=DataViewState.STALE,
        object_name="viewStateStale",
        banner_text=(
            "STALE DATA - REFRESH REQUIRED\n"
            f"Captured {captured_text} | Age: {age_text}\n"
            "Do not make a trading decision from this screen."
        ),
        detail_label="STALE CANDIDATE DATA - REFRESH BEFORE DECISION",
        chart_prefix="STALE - ",
        header_stylesheet=header_style("#7a2e2e", "#ffe1e1", "#a14646"),
        read_only=True,
        decision_status="Refresh required before decisions",
        age_text=age_text,
        captured_text=captured_text,
    )


def review_session_label(session_label: str) -> str:
    if session_label == "preopen":
        return "Pre-Open Gap Review"
    if session_label == "evening":
        return "Evening"
    if session_label == "morning":
        return "Morning"
    if session_label == "manual":
        return "Manual"
    return (session_label or "Review").title()


def header_style(background: str, color: str, border: str) -> str:
    return (
        "QHeaderView::section { "
        f"background: {background}; color: {color}; border: 0; "
        f"border-right: 1px solid {border}; padding: 6px; font-weight: 600; "
        "}"
    )


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=CENTRAL_TZ)
    return value.astimezone(CENTRAL_TZ)


def age_in_minutes(captured_at: datetime | None, now: datetime) -> float | None:
    if captured_at is None:
        return None
    return max(0.0, (normalize_datetime(now) - captured_at).total_seconds() / 60)


def format_age(captured_at: datetime | None, now: datetime, settings: FreshnessSettings) -> str:
    if captured_at is None:
        return "unknown"
    seconds = int(max(0, (normalize_datetime(now) - captured_at).total_seconds()))
    if seconds < settings.show_age_seconds_under_minutes * 60:
        return f"{seconds} seconds"
    minutes = seconds // 60
    if settings.show_age_minutes or minutes < 60:
        return f"{minutes} minutes"
    hours = minutes // 60
    return f"{hours} hours"
