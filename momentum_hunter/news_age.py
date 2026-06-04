from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from momentum_hunter.models import Candidate, NewsItem, NewsStack
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


def build_news_stack(candidate: Candidate, now: datetime | None = None) -> NewsStack:
    article_count = len(candidate.news)
    if not candidate.news:
        return NewsStack()

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
        return NewsStack(
            article_count=article_count,
            known_timestamp_count=0,
            unknown_timestamp_count=article_count,
            freshness=FRESHNESS_UNKNOWN,
            freshness_score=0,
        )

    freshest = min(known, key=lambda item: item.hours_old or 0)
    oldest = max(known, key=lambda item: item.hours_old or 0)
    unknown_count = article_count - len(known)
    return NewsStack(
        article_count=article_count,
        known_timestamp_count=len(known),
        unknown_timestamp_count=unknown_count,
        latest_article_age_hours=freshest.hours_old,
        oldest_article_age_hours=oldest.hours_old,
        latest_article_published_at=freshest.publish_time,
        oldest_article_published_at=oldest.publish_time,
        freshest_headline=freshest.headline,
        freshest_url=next((item.url for item in candidate.news if item.headline == freshest.headline), ""),
        freshness=freshest.freshness,
        freshness_score=freshest.score,
    )


def apply_candidate_news_stack(candidate: Candidate, now: datetime | None = None) -> Candidate:
    candidate.news_stack = build_news_stack(candidate, now=now)
    candidate.news_hours_old = candidate.news_stack.latest_article_age_hours
    candidate.freshness = candidate.news_stack.freshness
    candidate.freshness_score = candidate.news_stack.freshness_score
    return candidate


def apply_candidate_news_freshness(candidate: Candidate, now: datetime | None = None) -> Candidate:
    apply_candidate_news_stack(candidate, now=now)
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
        minutes = int(round(hours_old * 60))
        if minutes <= 0:
            return "<1m"
        return f"{minutes}m"
    if hours_old < 48:
        return f"{int(round(hours_old))}h"
    return f"{int(round(hours_old / 24))}d"


def format_news_range(stack: NewsStack) -> str:
    if stack.latest_article_age_hours is None or stack.oldest_article_age_hours is None:
        return "unknown"
    latest = format_news_age(stack.latest_article_age_hours)
    oldest = format_news_age(stack.oldest_article_age_hours)
    if latest == oldest:
        return latest
    return f"{latest}-{oldest}"


def news_stack_badge(candidate: Candidate) -> str:
    stack = candidate.news_stack
    if stack.article_count == 0:
        return "No articles"
    latest = format_news_age(stack.latest_article_age_hours)
    return f"{stack.freshness} {latest} | {stack.article_count} | {format_news_range(stack)}"


def news_stack_summary(candidate: Candidate) -> list[str]:
    stack = candidate.news_stack
    if stack.article_count == 0:
        return ["Articles Found: 0", "Range: unknown", "Freshest: n/a"]
    return [
        f"Latest Article: {format_news_age(stack.latest_article_age_hours)}",
        f"Articles Found: {stack.article_count}",
        f"Range: {format_news_range(stack)}",
        f"Freshest: {stack.freshest_headline or 'n/a'}",
    ]


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
