from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from pathlib import Path

from momentum_hunter.models import CaptureSession
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


SCHEDULING_POLICY_VERSION = "market-calendar-v1"
TARGET_EXCHANGE = "XNYS"
AUTOMATIC_RUN_SEARCH_DAYS = 370


class CaptureCalendarStatus(str, Enum):
    MARKET_OPEN_DAY = "MARKET_OPEN_DAY"
    PREOPEN_GAP_REVIEW_DAY = "PREOPEN_GAP_REVIEW_DAY"
    NON_MARKET_DAY = "NON_MARKET_DAY"
    UNKNOWN = "UNKNOWN"


class SkipReason(str, Enum):
    NONE = ""
    SKIP_NOT_MARKET_DAY = "SKIP_NOT_MARKET_DAY"
    SKIP_NOT_PREOPEN_GAP_REVIEW_DAY = "SKIP_NOT_PREOPEN_GAP_REVIEW_DAY"
    SKIP_DUPLICATE_CAPTURE = "SKIP_DUPLICATE_CAPTURE"
    SKIP_OUTSIDE_CAPTURE_WINDOW = "SKIP_OUTSIDE_CAPTURE_WINDOW"


@dataclass(frozen=True)
class CaptureCalendarClassification:
    capture_session: str
    capture_calendar_status: str
    is_market_open_day: bool | None
    is_study_eligible: bool
    next_market_session_date: str
    scheduling_policy_version: str = SCHEDULING_POLICY_VERSION
    target_exchange: str = TARGET_EXCHANGE

    def as_fields(self) -> dict:
        return {
            "capture_session": self.capture_session,
            "capture_calendar_status": self.capture_calendar_status,
            "is_market_open_day": self.is_market_open_day,
            "is_study_eligible": self.is_study_eligible,
            "next_market_session_date": self.next_market_session_date,
            "scheduling_policy_version": self.scheduling_policy_version,
        }


@dataclass(frozen=True)
class CaptureDecision:
    requested_session: CaptureSession
    capture_session: CaptureSession
    should_capture: bool
    skip_reason: str
    run_at: datetime
    classification: CaptureCalendarClassification

    @property
    def is_skip(self) -> bool:
        return not self.should_capture


def evaluate_automatic_capture(
    requested_session: CaptureSession,
    *,
    current_time: datetime | None = None,
    captures_dir: Path | None = None,
    enforce_time_window: bool = True,
) -> CaptureDecision:
    current = normalize_central(current_time or now_central())
    requested_session = CaptureSession(requested_session)
    target_session = requested_session

    if requested_session == CaptureSession.MANUAL:
        return capture_decision(requested_session, CaptureSession.MANUAL, current, captures_dir=captures_dir)

    if enforce_time_window and not is_capture_window(requested_session, current):
        return skip_decision(
            requested_session,
            requested_session,
            current,
            SkipReason.SKIP_OUTSIDE_CAPTURE_WINDOW,
        )

    if requested_session == CaptureSession.MORNING:
        if not is_market_open_day(current.date()):
            return skip_decision(
                requested_session,
                requested_session,
                current,
                SkipReason.SKIP_NOT_MARKET_DAY,
            )
        target_session = CaptureSession.MORNING

    elif requested_session == CaptureSession.EVENING:
        if is_market_open_day(current.date()):
            target_session = CaptureSession.EVENING
        elif is_preopen_gap_review_day(current.date()):
            target_session = CaptureSession.PREOPEN
        else:
            return skip_decision(
                requested_session,
                requested_session,
                current,
                SkipReason.SKIP_NOT_PREOPEN_GAP_REVIEW_DAY,
            )

    elif requested_session == CaptureSession.PREOPEN:
        if is_preopen_gap_review_day(current.date()):
            target_session = CaptureSession.PREOPEN
        else:
            return skip_decision(
                requested_session,
                requested_session,
                current,
                SkipReason.SKIP_NOT_PREOPEN_GAP_REVIEW_DAY,
            )

    return capture_decision(requested_session, target_session, current, captures_dir=captures_dir)


def capture_decision(
    requested_session: CaptureSession,
    target_session: CaptureSession,
    current: datetime,
    *,
    captures_dir: Path | None,
) -> CaptureDecision:
    classification = classify_capture(current, target_session)
    if capture_file_exists(current.date(), target_session, captures_dir):
        return CaptureDecision(
            requested_session=requested_session,
            capture_session=target_session,
            should_capture=False,
            skip_reason=SkipReason.SKIP_DUPLICATE_CAPTURE.value,
            run_at=current,
            classification=classification,
        )
    return CaptureDecision(
        requested_session=requested_session,
        capture_session=target_session,
        should_capture=True,
        skip_reason=SkipReason.NONE.value,
        run_at=current,
        classification=classification,
    )


def skip_decision(
    requested_session: CaptureSession,
    target_session: CaptureSession,
    current: datetime,
    reason: SkipReason,
) -> CaptureDecision:
    return CaptureDecision(
        requested_session=requested_session,
        capture_session=target_session,
        should_capture=False,
        skip_reason=reason.value,
        run_at=current,
        classification=classify_capture(current, target_session),
    )


def classify_capture(
    capture_time: datetime | str | None,
    session: CaptureSession | str,
    *,
    capture_date: str = "",
) -> CaptureCalendarClassification:
    session_value = normalize_session_value(session)
    capture_day = capture_day_from_value(capture_time, capture_date)
    if capture_day is None:
        return CaptureCalendarClassification(
            capture_session=session_value,
            capture_calendar_status=CaptureCalendarStatus.UNKNOWN.value,
            is_market_open_day=None,
            is_study_eligible=False,
            next_market_session_date="",
        )

    market_day = is_market_open_day(capture_day)
    next_session = capture_day if market_day else next_market_open_date(capture_day)
    status = CaptureCalendarStatus.MARKET_OPEN_DAY if market_day else CaptureCalendarStatus.NON_MARKET_DAY
    if session_value == CaptureSession.PREOPEN.value and is_preopen_gap_review_day(capture_day):
        status = CaptureCalendarStatus.PREOPEN_GAP_REVIEW_DAY

    is_study_eligible = session_value in {CaptureSession.MORNING.value, CaptureSession.EVENING.value} and market_day
    return CaptureCalendarClassification(
        capture_session=session_value,
        capture_calendar_status=status.value,
        is_market_open_day=market_day,
        is_study_eligible=is_study_eligible,
        next_market_session_date=next_session.isoformat(),
    )


def classification_fields_for_payload(payload: dict) -> dict:
    existing = {field: payload.get(field) for field in calendar_fieldnames()}
    if all(value not in (None, "") for value in existing.values()):
        return existing
    return classify_capture(
        payload.get("capture_time"),
        payload.get("session", ""),
        capture_date=payload.get("capture_date", ""),
    ).as_fields()


def calendar_fieldnames() -> list[str]:
    return [
        "capture_session",
        "capture_calendar_status",
        "is_market_open_day",
        "is_study_eligible",
        "next_market_session_date",
        "scheduling_policy_version",
    ]


def calendar_label(classification: CaptureCalendarClassification) -> str:
    if classification.capture_calendar_status == CaptureCalendarStatus.PREOPEN_GAP_REVIEW_DAY.value:
        return "Pre-Open Gap Review"
    if classification.capture_calendar_status == CaptureCalendarStatus.MARKET_OPEN_DAY.value:
        return "Market Open Day"
    if classification.capture_calendar_status == CaptureCalendarStatus.NON_MARKET_DAY.value:
        return "Non-Trading-Day Observation"
    return "Unknown Calendar Status"


def row_is_study_eligible(row: dict) -> bool:
    if "is_study_eligible" in row and str(row.get("is_study_eligible", "")).strip() != "":
        return parse_bool(row.get("is_study_eligible"))
    return classify_capture(
        row.get("capture_time"),
        row.get("session", ""),
        capture_date=row.get("capture_date", ""),
    ).is_study_eligible


def is_capture_window(session: CaptureSession, current: datetime) -> bool:
    if session == CaptureSession.MORNING:
        return time(7, 0) <= current.time().replace(second=0, microsecond=0) <= time(8, 0)
    if session == CaptureSession.EVENING:
        return time(19, 0) <= current.time().replace(second=0, microsecond=0) <= time(20, 0)
    if session == CaptureSession.PREOPEN:
        return time(19, 0) <= current.time().replace(second=0, microsecond=0) <= time(20, 0)
    return True


def next_automatic_run(
    session: CaptureSession,
    *,
    after: datetime | None = None,
    captures_dir: Path | None = None,
) -> datetime:
    current = normalize_central(after or now_central())
    target_time = time(7, 0) if session == CaptureSession.MORNING else time(19, 0)
    for offset in range(0, AUTOMATIC_RUN_SEARCH_DAYS):
        candidate = datetime.combine(current.date() + timedelta(days=offset), target_time, tzinfo=CENTRAL_TZ)
        if candidate <= current:
            continue
        decision = evaluate_automatic_capture(
            session,
            current_time=candidate,
            captures_dir=captures_dir,
            enforce_time_window=True,
        )
        if decision.should_capture and decision.capture_session == session:
            return candidate
    raise RuntimeError(
        f"Scheduling policy {SCHEDULING_POLICY_VERSION} exhausted "
        f"{AUTOMATIC_RUN_SEARCH_DAYS} day search horizon for {session.value}."
    )


def is_preopen_gap_review_day(value: date) -> bool:
    tomorrow = value + timedelta(days=1)
    yesterday = value - timedelta(days=1)
    return is_market_open_day(tomorrow) and not is_market_open_day(yesterday) and not is_market_open_day(value)


def next_market_open_date(value: date | datetime | None = None, *, include_today: bool = False) -> date:
    if value is None:
        current = now_central().date()
    elif isinstance(value, datetime):
        current = normalize_central(value).date()
    else:
        current = value
    if not include_today:
        current += timedelta(days=1)
    for _ in range(AUTOMATIC_RUN_SEARCH_DAYS):
        if is_market_open_day(current):
            return current
        current += timedelta(days=1)
    raise RuntimeError(
        f"Scheduling policy {SCHEDULING_POLICY_VERSION} exhausted "
        f"{AUTOMATIC_RUN_SEARCH_DAYS} day market-open search horizon."
    )


def is_market_open_day(value: date) -> bool:
    if value.weekday() >= 5:
        return False
    return value not in nyse_full_day_holidays(value.year)


def nyse_full_day_holidays(year: int) -> set[date]:
    holidays = {
        observed_fixed_holiday(year, 1, 1),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        easter_date(year) - timedelta(days=2),
        last_weekday(year, 5, 0),
        observed_fixed_holiday(year, 7, 4),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 11, 3, 4),
        observed_fixed_holiday(year, 12, 25),
    }
    if year >= 2022:
        holidays.add(observed_fixed_holiday(year, 6, 19))

    next_new_year_observed = observed_fixed_holiday(year + 1, 1, 1)
    if next_new_year_observed.year == year:
        holidays.add(next_new_year_observed)
    return holidays


def observed_fixed_holiday(year: int, month: int, day: int) -> date:
    actual = date(year, month, day)
    if actual.weekday() == 5:
        return actual - timedelta(days=1)
    if actual.weekday() == 6:
        return actual + timedelta(days=1)
    return actual


def nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    value = date(year, month, 1)
    while value.weekday() != weekday:
        value += timedelta(days=1)
    return value + timedelta(days=7 * (occurrence - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        value = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        value = date(year, month + 1, 1) - timedelta(days=1)
    while value.weekday() != weekday:
        value -= timedelta(days=1)
    return value


def easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def capture_file_exists(capture_day: date, session: CaptureSession, captures_dir: Path | None) -> bool:
    if captures_dir is None:
        from momentum_hunter.storage import CAPTURES_DIR

        captures_dir = CAPTURES_DIR
    base = captures_dir / capture_day.isoformat()
    return (base / f"{session.value}.json").exists() or (base / f"{session.value}.md").exists()


def capture_day_from_value(value: datetime | str | None, fallback_date: str = "") -> date | None:
    if isinstance(value, datetime):
        return normalize_central(value).date()
    if isinstance(value, str) and value:
        try:
            return normalize_central(datetime.fromisoformat(value)).date()
        except ValueError:
            if len(value) >= 10:
                try:
                    return date.fromisoformat(value[:10])
                except ValueError:
                    pass
    if fallback_date:
        try:
            return date.fromisoformat(fallback_date)
        except ValueError:
            return None
    return None


def normalize_central(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=CENTRAL_TZ)
    return value.astimezone(CENTRAL_TZ)


def normalize_session_value(session: CaptureSession | str) -> str:
    try:
        return CaptureSession(session).value
    except ValueError:
        return str(session or "")


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}
