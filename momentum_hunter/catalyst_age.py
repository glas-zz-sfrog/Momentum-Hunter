from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

from momentum_hunter.catalyst_clusters import classify_catalyst_headline
from momentum_hunter.config import DATA_DIR
from momentum_hunter.historical_clusters import SCANNER_ALL, scanner_name
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.replay import outcome_key
from momentum_hunter.review import load_review_decisions, make_capture_id, CandidateIdentity
from momentum_hunter.scheduling import classify_capture
from momentum_hunter.storage import CAPTURES_DIR
from momentum_hunter.study import (
    AGE_BUCKET_ALL,
    CATALYST_CLUSTER_ALL,
    REGIME_ALL,
    TIMESTAMP_STATUS_ALL,
    StudyFilter,
    parse_optional_float,
)


CATALYST_AGE_RESEARCH_LABEL = "CATALYST AGE / FRESHNESS — RESEARCH ONLY"
TIMESTAMP_STATUSES = [
    "EXACT_TIMESTAMP",
    "DATE_ONLY",
    "ESTIMATED",
    "UNKNOWN_TIMESTAMP",
    "FUTURE_TIMESTAMP",
    "INVALID_TIMESTAMP",
]
AGE_BUCKETS = ["<1h", "1-4h", "4-12h", "12-24h", "1-3d", "3d+", "unknown", "invalid_future"]


@dataclass(frozen=True)
class CatalystAgeRecord:
    capture_timestamp: str
    capture_date: str
    session: str
    provider: str
    scanner: str
    ticker: str
    market_regime: str
    sector: str
    catalyst_cluster: str
    headline: str
    source: str
    url: str
    published_at: str
    timestamp_status: str
    age_at_capture_hours: float | None
    age_bucket: str
    timestamp_confidence: str
    score: int
    review_status: str
    outcome_status: str
    max_gain_pct: float | None
    max_drawdown_pct: float | None
    is_study_eligible: bool


@dataclass(frozen=True)
class CatalystAgeSummary:
    name: str
    headline_count: int
    tickers: list[str]
    exact_count: int
    unknown_count: int
    future_count: int
    invalid_count: int
    bucket_distribution: dict[str, int]
    average_age_hours: float | None


@dataclass(frozen=True)
class CatalystAgeAuditReport:
    label: str
    source: str
    total_headlines: int
    exact_timestamp_count: int
    date_only_count: int
    estimated_count: int
    unknown_timestamp_count: int
    future_timestamp_count: int
    invalid_timestamp_count: int
    age_bucket_distribution: dict[str, int]
    affected_tickers: list[str]
    affected_clusters: list[str]
    cluster_summaries: list[CatalystAgeSummary]
    ticker_summaries: list[CatalystAgeSummary]
    records: list[CatalystAgeRecord]
    warnings: list[str] = field(default_factory=list)


def build_catalyst_age_audit_report(
    *,
    study_filter: StudyFilter | None = None,
    captures_dir: Path = CAPTURES_DIR,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
    outcomes_csv: Path = OUTCOMES_CSV,
) -> CatalystAgeAuditReport:
    study_filter = study_filter or StudyFilter()
    records = filter_age_records(
        load_catalyst_age_records(
            captures_dir=captures_dir,
            review_decisions_path=review_decisions_path,
            outcomes_csv=outcomes_csv,
        ),
        study_filter,
    )
    status_counts = Counter(record.timestamp_status for record in records)
    bucket_counts = {bucket: 0 for bucket in AGE_BUCKETS}
    bucket_counts.update(Counter(record.age_bucket for record in records))
    warnings = []
    if status_counts["FUTURE_TIMESTAMP"]:
        warnings.append(f"{status_counts['FUTURE_TIMESTAMP']} future timestamp headline(s) excluded from freshness-style analysis.")
    if status_counts["UNKNOWN_TIMESTAMP"]:
        warnings.append(f"{status_counts['UNKNOWN_TIMESTAMP']} headline(s) have unknown timestamps; freshness is not inferred.")
    if status_counts["INVALID_TIMESTAMP"]:
        warnings.append(f"{status_counts['INVALID_TIMESTAMP']} headline(s) have invalid timestamps.")
    return CatalystAgeAuditReport(
        label=CATALYST_AGE_RESEARCH_LABEL,
        source="active raw captures + stored capture headlines + review-decisions.json + analysis-outcomes.csv",
        total_headlines=len(records),
        exact_timestamp_count=status_counts["EXACT_TIMESTAMP"],
        date_only_count=status_counts["DATE_ONLY"],
        estimated_count=status_counts["ESTIMATED"],
        unknown_timestamp_count=status_counts["UNKNOWN_TIMESTAMP"],
        future_timestamp_count=status_counts["FUTURE_TIMESTAMP"],
        invalid_timestamp_count=status_counts["INVALID_TIMESTAMP"],
        age_bucket_distribution=bucket_counts,
        affected_tickers=sorted({record.ticker for record in records if record.timestamp_status in {"UNKNOWN_TIMESTAMP", "FUTURE_TIMESTAMP", "INVALID_TIMESTAMP"}}),
        affected_clusters=sorted({record.catalyst_cluster for record in records if record.timestamp_status in {"UNKNOWN_TIMESTAMP", "FUTURE_TIMESTAMP", "INVALID_TIMESTAMP"}}),
        cluster_summaries=summarize_age_records_by(records, "catalyst_cluster"),
        ticker_summaries=summarize_age_records_by(records, "ticker"),
        records=sorted(records, key=lambda record: (record.capture_timestamp, record.ticker, record.headline)),
        warnings=warnings,
    )


def load_catalyst_age_records(
    *,
    captures_dir: Path,
    review_decisions_path: Path,
    outcomes_csv: Path,
) -> list[CatalystAgeRecord]:
    from momentum_hunter.catalyst_clusters import load_outcome_rows

    reviews = load_review_decisions(review_decisions_path)
    outcomes = load_outcome_rows(outcomes_csv)
    records: list[CatalystAgeRecord] = []
    for capture_path in sorted(captures_dir.rglob("*.json")):
        payload = load_json(capture_path)
        if not payload:
            continue
        capture_timestamp = payload.get("capture_time", "")
        capture_dt = parse_capture_datetime(capture_timestamp)
        capture_date = payload.get("capture_date", capture_timestamp[:10])
        session = payload.get("session", "")
        provider = payload.get("provider", "")
        scanner = scanner_name(payload)
        market_regime = (payload.get("market", {}).get("regime") or payload.get("scoring", {}).get("regime") or "unknown").lower()
        classification = classify_capture(capture_timestamp, session, capture_date=capture_date)
        sector_counts = Counter(str(item.get("sector", "") or "unknown") for item in payload.get("candidates", []))
        for candidate in payload.get("candidates", []):
            ticker = str(candidate.get("ticker", "")).upper()
            sector = str(candidate.get("sector", "") or "unknown")
            identity = CandidateIdentity(
                capture_id=make_capture_id(capture_date, session, provider, scanner),
                capture_date=capture_date,
                session=session,
                provider=provider,
                scanner=scanner,
                ticker=ticker,
            )
            review = reviews.get(identity.key)
            outcome = outcomes.get(outcome_key(capture_date, capture_timestamp, session, provider, scanner, ticker), {})
            news_items = candidate.get("news", [])
            if not isinstance(news_items, list) or not news_items:
                news_items = [{"headline": "No stored headline", "source": "", "url": "", "published_at": ""}]
            for news_item in news_items:
                if not isinstance(news_item, dict):
                    continue
                headline = str(news_item.get("headline", "")).strip() or "No stored headline"
                timestamp = evaluate_timestamp(news_item, capture_dt)
                records.append(
                    CatalystAgeRecord(
                        capture_timestamp=capture_timestamp,
                        capture_date=capture_date,
                        session=session,
                        provider=provider,
                        scanner=scanner,
                        ticker=ticker,
                        market_regime=market_regime,
                        sector=sector,
                        catalyst_cluster=classify_catalyst_headline(
                            headline,
                            sector=sector,
                            industry=str(candidate.get("industry", "") or ""),
                            sector_sympathy=sector_counts.get(sector, 0) >= 2,
                        ),
                        headline=headline,
                        source=str(news_item.get("source", "")),
                        url=str(news_item.get("url", "")),
                        published_at=str(news_item.get("published_at", "")),
                        timestamp_status=timestamp["status"],
                        age_at_capture_hours=timestamp["age_hours"],
                        age_bucket=timestamp["age_bucket"],
                        timestamp_confidence=timestamp["confidence"],
                        score=parse_int(candidate.get("score")),
                        review_status=review.review_status.value if review else "unreviewed",
                        outcome_status=outcome.get("outcome_status", "missing") if outcome else "missing",
                        max_gain_pct=parse_optional_float(outcome.get("max_gain_pct", "")),
                        max_drawdown_pct=parse_optional_float(outcome.get("max_drawdown_pct", "")),
                        is_study_eligible=classification.is_study_eligible,
                    )
                )
    return records


def filter_age_records(records: list[CatalystAgeRecord], study_filter: StudyFilter) -> list[CatalystAgeRecord]:
    filtered = records
    if not study_filter.include_non_study_eligible:
        filtered = [record for record in filtered if record.is_study_eligible]
    if study_filter.start_date:
        filtered = [record for record in filtered if record.capture_date >= study_filter.start_date]
    if study_filter.end_date:
        filtered = [record for record in filtered if record.capture_date <= study_filter.end_date]
    if study_filter.ticker:
        filtered = [record for record in filtered if record.ticker == study_filter.ticker.upper()]
    if study_filter.catalyst_cluster != CATALYST_CLUSTER_ALL:
        filtered = [record for record in filtered if record.catalyst_cluster == study_filter.catalyst_cluster]
    if study_filter.regime != REGIME_ALL:
        filtered = [record for record in filtered if record.market_regime == study_filter.regime]
    if study_filter.scanner != SCANNER_ALL:
        filtered = [record for record in filtered if record.scanner == study_filter.scanner]
    if study_filter.timestamp_status != TIMESTAMP_STATUS_ALL:
        filtered = [record for record in filtered if record.timestamp_status == study_filter.timestamp_status]
    if study_filter.age_bucket != AGE_BUCKET_ALL:
        filtered = [record for record in filtered if record.age_bucket == study_filter.age_bucket]
    return filtered


def evaluate_timestamp(news_item: dict, capture_dt: datetime | None) -> dict:
    published_at = news_item.get("published_at", "")
    estimated = bool(news_item.get("published_at_estimated") or news_item.get("estimated"))
    if published_at is None or str(published_at).strip() == "":
        return timestamp_result("UNKNOWN_TIMESTAMP", None, "unknown")
    raw = str(published_at).strip()
    parsed = parse_timestamp(raw)
    if parsed is None:
        return timestamp_result("INVALID_TIMESTAMP", None, "invalid")
    published_dt, date_only = parsed
    if date_only and capture_dt is not None and capture_dt.tzinfo is not None and published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=capture_dt.tzinfo)
    status = "ESTIMATED" if estimated else ("DATE_ONLY" if date_only else "EXACT_TIMESTAMP")
    confidence = "estimated" if estimated else ("partial" if date_only else "exact")
    if capture_dt is None:
        return timestamp_result("INVALID_TIMESTAMP", None, "invalid")
    if published_dt > capture_dt:
        return timestamp_result("FUTURE_TIMESTAMP", None, "invalid")
    age_hours = round((capture_dt - published_dt).total_seconds() / 3600, 4)
    return timestamp_result(status, max(0.0, age_hours), confidence)


def timestamp_result(status: str, age_hours: float | None, confidence: str) -> dict:
    return {
        "status": status,
        "age_hours": age_hours,
        "age_bucket": age_bucket(age_hours, status),
        "confidence": confidence,
    }


def parse_timestamp(value: str) -> tuple[datetime, bool] | None:
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        try:
            return datetime.combine(datetime.fromisoformat(value).date(), time.min), True
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(value), False
    except ValueError:
        return None


def parse_capture_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def age_bucket(age_hours: float | None, status: str) -> str:
    if status == "FUTURE_TIMESTAMP":
        return "invalid_future"
    if age_hours is None:
        return "unknown"
    if age_hours < 1:
        return "<1h"
    if age_hours < 4:
        return "1-4h"
    if age_hours < 12:
        return "4-12h"
    if age_hours < 24:
        return "12-24h"
    if age_hours < 72:
        return "1-3d"
    return "3d+"


def summarize_age_records_by(records: list[CatalystAgeRecord], field_name: str) -> list[CatalystAgeSummary]:
    groups: dict[str, list[CatalystAgeRecord]] = defaultdict(list)
    for record in records:
        groups[getattr(record, field_name)].append(record)
    summaries = [summarize_age_records(name, rows) for name, rows in groups.items()]
    return sorted(summaries, key=lambda item: (-item.headline_count, item.name))


def summarize_age_records(name: str, records: list[CatalystAgeRecord]) -> CatalystAgeSummary:
    status_counts = Counter(record.timestamp_status for record in records)
    bucket_counts = {bucket: 0 for bucket in AGE_BUCKETS}
    bucket_counts.update(Counter(record.age_bucket for record in records))
    age_values = [
        record.age_at_capture_hours
        for record in records
        if record.age_at_capture_hours is not None and record.timestamp_status != "FUTURE_TIMESTAMP"
    ]
    return CatalystAgeSummary(
        name=name,
        headline_count=len(records),
        tickers=sorted({record.ticker for record in records}),
        exact_count=status_counts["EXACT_TIMESTAMP"],
        unknown_count=status_counts["UNKNOWN_TIMESTAMP"],
        future_count=status_counts["FUTURE_TIMESTAMP"],
        invalid_count=status_counts["INVALID_TIMESTAMP"],
        bucket_distribution=bucket_counts,
        average_age_hours=average(age_values),
    )


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def parse_int(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)
