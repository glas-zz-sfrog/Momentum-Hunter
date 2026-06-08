from __future__ import annotations

import hashlib
import re
import string
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from momentum_hunter.catalyst_clusters import (
    CatalystHeadline,
    load_catalyst_headlines,
    parse_datetime,
    percent,
)
from momentum_hunter.config import DATA_DIR
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.score_breakdowns import SCORE_BREAKDOWNS_PATH
from momentum_hunter.storage import CAPTURES_DIR
from momentum_hunter.study import CATALYST_CLUSTER_ALL, SESSION_ALL, TIMESTAMP_STATUS_ALL, StudyFilter


HEADLINE_DEDUP_RESEARCH_LABEL = "HEADLINE DEDUP / SOURCE QUALITY — RESEARCH ONLY"
HIGH_DUPLICATE_RATE_WARNING_PCT = 40.0
LOW_TIMESTAMP_RELIABILITY_WARNING_PCT = 50.0
HIGH_FUTURE_SOURCE_WARNING_PCT = 5.0
HIGH_UNKNOWN_SOURCE_WARNING_PCT = 40.0

FILLER_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "for",
    "from",
    "in",
    "inc",
    "ltd",
    "of",
    "on",
    "plc",
    "shares",
    "stock",
    "the",
    "to",
    "today",
    "why",
    "with",
}

BOILERPLATE_TERMS = [
    "yahoo finance",
    "finviz",
    "reuters",
    "bloomberg",
    "marketwatch",
    "investingcom",
    "seeking alpha",
    "benzinga",
    "zacks",
    "motley fool",
]


@dataclass(frozen=True)
class HeadlineEvent:
    event_id: str
    fingerprint: str
    representative_headline: str
    tickers: list[str]
    sources: list[str]
    providers: list[str]
    first_seen_capture_time: str
    latest_seen_capture_time: str
    earliest_published_at: str
    timestamp_status_summary: dict[str, int]
    duplicate_headline_count: int
    unique_source_count: int
    catalyst_cluster: str
    confidence: str
    confidence_score: int
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    headlines: list[CatalystHeadline] = field(default_factory=list)


@dataclass(frozen=True)
class SourceReliabilitySummary:
    source: str
    total_headlines: int
    exact_pct: float
    unknown_pct: float
    future_pct: float
    invalid_pct: float
    duplicate_rate_pct: float
    unique_event_count: int
    average_headlines_per_event: float | None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DedupImpactSummary:
    name: str
    raw_headline_count: int
    deduped_event_count: int
    duplicate_rate_pct: float
    top_duplicated_stories: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HeadlineDedupReport:
    label: str
    source: str
    total_raw_headlines: int
    total_events: int
    duplicate_headline_count: int
    duplicate_rate_pct: float
    filters: StudyFilter
    events: list[HeadlineEvent]
    source_reliability: list[SourceReliabilitySummary]
    cluster_impact: list[DedupImpactSummary]
    ticker_impact: list[DedupImpactSummary]
    warnings: list[str] = field(default_factory=list)


def build_headline_dedup_report(
    *,
    study_filter: StudyFilter | None = None,
    captures_dir: Path = CAPTURES_DIR,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
    outcomes_csv: Path = OUTCOMES_CSV,
) -> HeadlineDedupReport:
    study_filter = study_filter or StudyFilter()
    headlines, _future_count = load_catalyst_headlines(
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    )
    filtered = filter_headlines(headlines, study_filter)
    events = group_headline_events(filtered)
    events = filter_events(events, study_filter)
    event_headlines = [headline for event in events for headline in event.headlines]
    duplicate_headline_count = sum(event.duplicate_headline_count for event in events if event.duplicate_headline_count > 1)
    warnings = []
    if any(headline.timestamp_status == "future" for headline in filtered):
        warnings.append("Future timestamp headline(s) are included in source-quality warnings but are not treated as fresh.")
    if not headlines:
        warnings.append("No stored historical headlines found in active raw captures.")
    if not filtered and headlines:
        warnings.append("Filters removed all stored historical headlines.")
    duplicate_rate = percent(duplicate_headline_count, len(event_headlines))
    if duplicate_rate >= HIGH_DUPLICATE_RATE_WARNING_PCT and duplicate_headline_count:
        warnings.append("HIGH DUPLICATE RATE")
    return HeadlineDedupReport(
        label=HEADLINE_DEDUP_RESEARCH_LABEL,
        source="active raw captures + stored headlines + catalyst clusters + catalyst age metrics + analysis-outcomes.csv display context",
        total_raw_headlines=len(event_headlines),
        total_events=len(events),
        duplicate_headline_count=duplicate_headline_count,
        duplicate_rate_pct=duplicate_rate,
        filters=study_filter,
        events=events,
        source_reliability=summarize_source_reliability(filtered, events),
        cluster_impact=summarize_dedup_impact(event_headlines, events, "cluster_name"),
        ticker_impact=summarize_dedup_impact(event_headlines, events, "ticker"),
        warnings=warnings,
    )


def filter_headlines(headlines: list[CatalystHeadline], study_filter: StudyFilter) -> list[CatalystHeadline]:
    filtered = headlines
    if not study_filter.include_non_study_eligible:
        filtered = [headline for headline in filtered if headline.is_study_eligible]
    if study_filter.start_date:
        filtered = [headline for headline in filtered if headline.capture_date >= study_filter.start_date]
    if study_filter.end_date:
        filtered = [headline for headline in filtered if headline.capture_date <= study_filter.end_date]
    if study_filter.session != SESSION_ALL:
        filtered = [headline for headline in filtered if headline.session == study_filter.session]
    if study_filter.ticker:
        filtered = [headline for headline in filtered if headline.ticker == study_filter.ticker.upper()]
    if study_filter.catalyst_cluster != CATALYST_CLUSTER_ALL:
        filtered = [headline for headline in filtered if headline.cluster_name == study_filter.catalyst_cluster]
    if study_filter.timestamp_status != TIMESTAMP_STATUS_ALL:
        filtered = [headline for headline in filtered if timestamp_status_matches(headline.timestamp_status, study_filter.timestamp_status)]
    if study_filter.source:
        needle = study_filter.source.lower()
        filtered = [
            headline
            for headline in filtered
            if needle in source_label(headline).lower()
            or needle in headline.provider.lower()
            or needle in headline.source.lower()
        ]
    return filtered


def filter_events(events: list[HeadlineEvent], study_filter: StudyFilter) -> list[HeadlineEvent]:
    if not study_filter.minimum_duplicate_count:
        return events
    return [event for event in events if event.duplicate_headline_count >= study_filter.minimum_duplicate_count]


def group_headline_events(headlines: list[CatalystHeadline]) -> list[HeadlineEvent]:
    grouped: dict[tuple[str, str], list[CatalystHeadline]] = defaultdict(list)
    for headline in headlines:
        fingerprint = fingerprint_headline(headline.headline, ticker=headline.ticker, source=headline.source)
        grouped[(headline.cluster_name, fingerprint)].append(headline)
    events = [
        build_headline_event(cluster_name, fingerprint, rows)
        for (cluster_name, fingerprint), rows in grouped.items()
    ]
    return sorted(events, key=lambda event: (event.first_seen_capture_time, event.catalyst_cluster, event.representative_headline))


def build_headline_event(cluster_name: str, fingerprint: str, rows: list[CatalystHeadline]) -> HeadlineEvent:
    sorted_rows = sorted(rows, key=lambda row: (row.capture_time, row.ticker, row.headline))
    statuses = Counter(row.timestamp_status for row in sorted_rows)
    published_values = [
        row.published_at
        for row in sorted_rows
        if row.timestamp_status == "known" and row.published_at and parse_datetime(row.published_at) is not None
    ]
    earliest_published = min(published_values) if published_values else ""
    sources = sorted({source_label(row) for row in sorted_rows})
    confidence_score = event_confidence_score(fingerprint, sorted_rows)
    warnings = event_warnings(sorted_rows, confidence_score)
    return HeadlineEvent(
        event_id=event_id(cluster_name, fingerprint),
        fingerprint=fingerprint,
        representative_headline=representative_headline(sorted_rows),
        tickers=sorted({row.ticker for row in sorted_rows}),
        sources=sources,
        providers=sorted({row.provider or "unknown" for row in sorted_rows}),
        first_seen_capture_time=sorted_rows[0].capture_time,
        latest_seen_capture_time=sorted_rows[-1].capture_time,
        earliest_published_at=earliest_published,
        timestamp_status_summary=dict(sorted(statuses.items())),
        duplicate_headline_count=len(sorted_rows),
        unique_source_count=len(sources),
        catalyst_cluster=cluster_name,
        confidence=event_confidence_label(confidence_score),
        confidence_score=confidence_score,
        notes=event_notes(sorted_rows),
        warnings=warnings,
        headlines=sorted_rows,
    )


def fingerprint_headline(headline: str, *, ticker: str = "", source: str = "") -> str:
    text = headline.lower()
    text = text.replace("&", " and ")
    for term in BOILERPLATE_TERMS:
        text = text.replace(term, " ")
    if source:
        text = text.replace(source.lower(), " ")
    if ticker:
        ticker_lower = ticker.lower()
        text = re.sub(rf"^\s*{re.escape(ticker_lower)}\s+", " ", text)
        text = re.sub(rf"^\s*{re.escape(ticker_lower)}[:\-]\s*", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = text.translate(str.maketrans({char: " " for char in string.punctuation}))
    tokens = [token for token in text.split() if token not in FILLER_WORDS and not token.isdigit()]
    return " ".join(tokens)


def event_id(cluster_name: str, fingerprint: str) -> str:
    digest = hashlib.sha256(f"{cluster_name}|{fingerprint}".encode("utf-8")).hexdigest()
    return f"evt_{digest[:16]}"


def representative_headline(rows: list[CatalystHeadline]) -> str:
    counts = Counter(row.headline for row in rows)
    return sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[0][0]


def event_confidence_score(fingerprint: str, rows: list[CatalystHeadline]) -> int:
    unique_sources = len({source_label(row) for row in rows})
    duplicate_count = len(rows)
    token_count = len(fingerprint.split())
    score = 40
    if token_count >= 5:
        score += 25
    elif token_count >= 3:
        score += 15
    if duplicate_count >= 3:
        score += 20
    elif duplicate_count == 2:
        score += 12
    if unique_sources >= 2:
        score += 15
    if any(row.classification_match_type == "fallback" for row in rows):
        score -= 10
    return max(0, min(100, score))


def event_confidence_label(score: int) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"


def event_notes(rows: list[CatalystHeadline]) -> list[str]:
    notes = []
    if len(rows) > 1:
        notes.append(f"Grouped {len(rows)} similar stored headline rows.")
    if len({source_label(row) for row in rows}) > 1:
        notes.append("Multiple source labels observed.")
    return notes


def event_warnings(rows: list[CatalystHeadline], confidence_score: int) -> list[str]:
    warnings = []
    if confidence_score < 60:
        warnings.append("LOW CONFIDENCE EVENT GROUPING")
    if any(row.timestamp_status == "future" for row in rows):
        warnings.append("FUTURE TIMESTAMP SOURCE ISSUE")
    if any(row.timestamp_status == "unknown" for row in rows):
        warnings.append("UNKNOWN TIMESTAMP SOURCE ISSUE")
    return warnings


def summarize_source_reliability(headlines: list[CatalystHeadline], events: list[HeadlineEvent]) -> list[SourceReliabilitySummary]:
    event_ids_by_headline = {}
    for event in events:
        for headline in event.headlines:
            event_ids_by_headline[id(headline)] = event.event_id
    duplicate_event_ids = {event.event_id for event in events if event.duplicate_headline_count > 1}
    grouped: dict[str, list[CatalystHeadline]] = defaultdict(list)
    for headline in headlines:
        grouped[f"provider:{headline.provider or 'unknown'}"].append(headline)
        grouped[f"source:{headline.source or 'unknown'}"].append(headline)
    summaries = []
    for source_name, rows in grouped.items():
        event_ids = {event_ids_by_headline.get(id(row)) for row in rows if event_ids_by_headline.get(id(row))}
        duplicate_rows = sum(1 for row in rows if event_ids_by_headline.get(id(row)) in duplicate_event_ids)
        total = len(rows)
        exact_count = sum(1 for row in rows if row.timestamp_status == "known")
        unknown_count = sum(1 for row in rows if row.timestamp_status == "unknown")
        future_count = sum(1 for row in rows if row.timestamp_status == "future")
        invalid_count = sum(1 for row in rows if row.timestamp_status == "invalid")
        exact_pct = percent(exact_count, total)
        unknown_pct = percent(unknown_count, total)
        future_pct = percent(future_count, total)
        duplicate_rate = percent(duplicate_rows, total)
        warnings = source_warnings(exact_pct, unknown_pct, future_pct, duplicate_rate)
        summaries.append(
            SourceReliabilitySummary(
                source=source_name,
                total_headlines=total,
                exact_pct=exact_pct,
                unknown_pct=unknown_pct,
                future_pct=future_pct,
                invalid_pct=percent(invalid_count, total),
                duplicate_rate_pct=duplicate_rate,
                unique_event_count=len(event_ids),
                average_headlines_per_event=round(total / len(event_ids), 4) if event_ids else None,
                warnings=warnings,
            )
        )
    return sorted(summaries, key=lambda item: (-item.total_headlines, item.source))


def source_warnings(exact_pct: float, unknown_pct: float, future_pct: float, duplicate_rate_pct: float) -> list[str]:
    warnings = []
    if duplicate_rate_pct >= HIGH_DUPLICATE_RATE_WARNING_PCT:
        warnings.append("HIGH DUPLICATE RATE")
    if exact_pct < LOW_TIMESTAMP_RELIABILITY_WARNING_PCT:
        warnings.append("LOW TIMESTAMP RELIABILITY")
    if unknown_pct >= HIGH_UNKNOWN_SOURCE_WARNING_PCT:
        warnings.append("UNKNOWN TIMESTAMP SOURCE ISSUE")
    if future_pct >= HIGH_FUTURE_SOURCE_WARNING_PCT:
        warnings.append("FUTURE TIMESTAMP SOURCE ISSUE")
    return warnings


def summarize_dedup_impact(headlines: list[CatalystHeadline], events: list[HeadlineEvent], field_name: str) -> list[DedupImpactSummary]:
    headline_groups: dict[str, list[CatalystHeadline]] = defaultdict(list)
    event_groups: dict[str, list[HeadlineEvent]] = defaultdict(list)
    for headline in headlines:
        headline_groups[getattr(headline, field_name)].append(headline)
    for event in events:
        names = sorted({getattr(headline, field_name) for headline in event.headlines})
        for name in names:
            event_groups[name].append(event)
    summaries = []
    for name, rows in headline_groups.items():
        group_events = event_groups.get(name, [])
        duplicate_count = sum(event.duplicate_headline_count for event in group_events if event.duplicate_headline_count > 1)
        duplicate_rate = percent(duplicate_count, len(rows))
        warnings = ["HIGH DUPLICATE RATE"] if duplicate_rate >= HIGH_DUPLICATE_RATE_WARNING_PCT and duplicate_count else []
        summaries.append(
            DedupImpactSummary(
                name=name or "unknown",
                raw_headline_count=len(rows),
                deduped_event_count=len(group_events),
                duplicate_rate_pct=duplicate_rate,
                top_duplicated_stories=top_duplicated_stories(group_events),
                warnings=warnings,
            )
        )
    return sorted(summaries, key=lambda item: (-item.raw_headline_count, item.name))


def top_duplicated_stories(events: list[HeadlineEvent], limit: int = 3) -> list[str]:
    duplicated = [event for event in events if event.duplicate_headline_count > 1]
    ranked = sorted(duplicated, key=lambda event: (-event.duplicate_headline_count, event.representative_headline))
    return [f"{event.duplicate_headline_count}x {event.representative_headline}" for event in ranked[:limit]]


def source_label(headline: CatalystHeadline) -> str:
    return headline.source or headline.provider or "unknown"


def timestamp_status_matches(actual: str, requested: str) -> bool:
    mapping = {
        "EXACT_TIMESTAMP": "known",
        "DATE_ONLY": "known",
        "ESTIMATED": "known",
        "UNKNOWN_TIMESTAMP": "unknown",
        "FUTURE_TIMESTAMP": "future",
        "INVALID_TIMESTAMP": "invalid",
    }
    return actual == mapping.get(requested, requested)
