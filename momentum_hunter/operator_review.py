from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum

from momentum_hunter.models import CaptureSession
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


MARKET_OPEN_CUTOFF = time(8, 30)


class OperatorReviewState(str, Enum):
    READY_FOR_NEXT_SESSION_REVIEW = "READY_FOR_NEXT_SESSION_REVIEW"
    AGING_BUT_REVIEWABLE = "AGING_BUT_REVIEWABLE"
    CURRENT_MANUAL_SCAN = "CURRENT_MANUAL_SCAN"
    EXPIRED_REVIEW_SNAPSHOT = "EXPIRED_REVIEW_SNAPSHOT"
    HISTORICAL_READ_ONLY = "HISTORICAL_READ_ONLY"
    REPLAY_READ_ONLY = "REPLAY_READ_ONLY"
    STUDY_READ_ONLY = "STUDY_READ_ONLY"
    QUARANTINED_BLOCKED = "QUARANTINED_BLOCKED"
    CAPTURE_MISSING = "CAPTURE_MISSING"
    CAPTURE_FAILED = "CAPTURE_FAILED"


@dataclass(frozen=True)
class OperatorReviewContext:
    state: OperatorReviewState
    label: str
    guidance: str
    can_review: bool
    can_generate_watchlist: bool
    acknowledgement_required: bool = False
    block_reason: str = ""
    review_delay_minutes: int | None = None


def classify_current_manual_scan(
    *,
    capture_time: datetime | None,
    candidates_loaded: bool,
    freshness_threshold_minutes: int,
    now: datetime | None = None,
    capture_failed: bool = False,
) -> OperatorReviewContext:
    if capture_failed:
        return blocked_context(
            OperatorReviewState.CAPTURE_FAILED,
            "Capture Failed",
            "Capture failed. Open Capture Health.",
        )
    if not candidates_loaded or capture_time is None:
        return blocked_context(
            OperatorReviewState.CAPTURE_MISSING,
            "Capture Missing",
            "No candidates loaded. Run Scanner or open the latest review snapshot first.",
        )
    current = normalize_central(now or now_central())
    captured = normalize_central(capture_time)
    age_minutes = int(max(0, (current - captured).total_seconds() // 60))
    if age_minutes > freshness_threshold_minutes:
        return OperatorReviewContext(
            state=OperatorReviewState.AGING_BUT_REVIEWABLE,
            label="Aging but Reviewable",
            guidance="This manual scan is aged but still reviewable. Confirm the setup before acting.",
            can_review=True,
            can_generate_watchlist=True,
            acknowledgement_required=True,
            review_delay_minutes=age_minutes,
        )
    return OperatorReviewContext(
        state=OperatorReviewState.CURRENT_MANUAL_SCAN,
        label="Current Manual Scan",
        guidance="Current manual scan is ready for review.",
        can_review=True,
        can_generate_watchlist=True,
        review_delay_minutes=age_minutes,
    )


def classify_scheduled_snapshot(
    *,
    capture_time: datetime | None,
    session: str,
    next_market_session_date: str,
    freshness_threshold_minutes: int,
    now: datetime | None = None,
    quarantined: bool = False,
) -> OperatorReviewContext:
    if quarantined:
        return blocked_context(
            OperatorReviewState.QUARANTINED_BLOCKED,
            "Quarantined Capture - Blocked",
            "This capture is quarantined and blocked from review workflow.",
        )
    if capture_time is None:
        return blocked_context(
            OperatorReviewState.CAPTURE_MISSING,
            "Capture Missing",
            "No candidates loaded. Run Scanner or open the latest review snapshot first.",
        )
    session_value = str(session or "")
    if session_value not in {CaptureSession.EVENING.value, CaptureSession.PREOPEN.value}:
        return blocked_context(
            OperatorReviewState.HISTORICAL_READ_ONLY,
            "Historical Snapshot - Read Only",
            "This capture is historical and cannot be used for a new watchlist.",
        )
    next_session_day = parse_date(next_market_session_date)
    if next_session_day is None:
        return blocked_context(
            OperatorReviewState.HISTORICAL_READ_ONLY,
            "Historical Snapshot - Read Only",
            "This capture has no next-session metadata and cannot be used for a new watchlist.",
        )

    current = normalize_central(now or now_central())
    cutoff = datetime.combine(next_session_day, MARKET_OPEN_CUTOFF, tzinfo=CENTRAL_TZ)
    if current >= cutoff:
        return blocked_context(
            OperatorReviewState.EXPIRED_REVIEW_SNAPSHOT,
            "Expired Review Snapshot - Read Only",
            "This snapshot is expired for trading workflow.",
        )

    captured = normalize_central(capture_time)
    age_minutes = int(max(0, (current - captured).total_seconds() // 60))
    if age_minutes > freshness_threshold_minutes:
        label = "Aging but Reviewable"
        guidance = "This snapshot is aged but still reviewable for the next market session."
        state = OperatorReviewState.AGING_BUT_REVIEWABLE
        acknowledgement_required = True
    else:
        label = "Ready for Next Session Review"
        guidance = "Latest evening capture is ready for next-session review."
        state = OperatorReviewState.READY_FOR_NEXT_SESSION_REVIEW
        acknowledgement_required = False
    return OperatorReviewContext(
        state=state,
        label=label,
        guidance=guidance,
        can_review=True,
        can_generate_watchlist=True,
        acknowledgement_required=acknowledgement_required,
        review_delay_minutes=age_minutes,
    )


def blocked_context(state: OperatorReviewState, label: str, guidance: str) -> OperatorReviewContext:
    return OperatorReviewContext(
        state=state,
        label=label,
        guidance=guidance,
        can_review=False,
        can_generate_watchlist=False,
        block_reason=guidance,
    )


def parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def normalize_central(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=CENTRAL_TZ)
    return value.astimezone(CENTRAL_TZ)
