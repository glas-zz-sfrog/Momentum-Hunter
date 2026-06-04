from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from momentum_hunter.models import Candidate, NewsItem
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


FRESHNESS_HOT = "HOT"
FRESHNESS_ACTIVE = "ACTIVE"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class NewsFreshness:
    ticker: str
    headline: str
    publish_time: datetime | None
    hours_old: float | None
    freshness: str
    score: int


def evaluate_news_freshness(
    *,
    ticker: str,
    headline: str,
    publish_time: datetime | None,
    now: datetime | None = None,
) -> NewsFreshness:
    current_time = normalize_datetime(now or now_central())
    published = normalize_datetime(publish_time)
    if published is None:
        return NewsFreshness(
            ticker=ticker,
            headline=headline,
            publish_time=None,
            hours_old=None,
            freshness=FRESHNESS_UNKNOWN,
            score=0,
        )

    hours_old = max(0.0, (current_time - published).total_seconds() / 3600)
    return NewsFreshness(
        ticker=ticker,
        headline=headline,
        publish_time=published,
        hours_old=round(hours_old, 2),
        freshness=freshness_label(hours_old),
        score=freshness_score(hours_old),
    )


def apply_candidate_news_freshness(candidate: Candidate, now: datetime | None = None) -> Candidate:
    if not candidate.news:
        candidate.news_hours_old = None
        candidate.freshness = FRESHNESS_UNKNOWN
        candidate.freshness_score = 0
        return candidate

    evaluations = [
        evaluate_news_freshness(
            ticker=candidate.ticker,
            headline=item.headline,
            publish_time=item.published_at,
            now=now,
        )
        for item in candidate.news
    ]
    known = [item for item in evaluations if item.hours_old is not None]
    if not known:
        candidate.news_hours_old = None
        candidate.freshness = FRESHNESS_UNKNOWN
        candidate.freshness_score = 0
        return candidate

    freshest = min(known, key=lambda item: item.hours_old or 0)
    candidate.news_hours_old = freshest.hours_old
    candidate.freshness = freshest.freshness
    candidate.freshness_score = freshest.score
    return candidate


def freshness_label(hours_old: float) -> str:
    if hours_old <= 24:
        return FRESHNESS_HOT
    if hours_old <= 168:
        return FRESHNESS_ACTIVE
    return FRESHNESS_STALE


def freshness_score(hours_old: float) -> int:
    if hours_old <= 24:
        return max(90, min(100, 100 - int(round(hours_old / 6))))
    if hours_old <= 72:
        return max(75, 89 - int((hours_old - 24) // 4))
    if hours_old <= 168:
        return max(45, 74 - int((hours_old - 72) // 3))
    if hours_old <= 336:
        return max(20, 44 - int((hours_old - 168) // 7))
    return 10


def format_news_age(hours_old: float | None) -> str:
    if hours_old is None:
        return "unknown"
    if hours_old < 1:
        return "<1h"
    if hours_old < 48:
        return f"{int(round(hours_old))}h"
    return f"{int(round(hours_old / 24))}d"


def freshness_badge(candidate: Candidate) -> str:
    if candidate.freshness == FRESHNESS_HOT:
        return f"HOT {candidate.freshness_score} ({format_news_age(candidate.news_hours_old)})"
    if candidate.freshness == FRESHNESS_ACTIVE:
        return f"ACTIVE {candidate.freshness_score} ({format_news_age(candidate.news_hours_old)})"
    if candidate.freshness == FRESHNESS_STALE:
        return f"STALE {candidate.freshness_score} ({format_news_age(candidate.news_hours_old)})"
    return "UNKNOWN"


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=CENTRAL_TZ)
    return value.astimezone(CENTRAL_TZ)
