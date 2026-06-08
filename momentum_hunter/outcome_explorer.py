from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from momentum_hunter.catalyst_age import load_catalyst_age_records
from momentum_hunter.catalyst_clusters import (
    load_catalyst_headlines,
    summarize_catalyst_cluster,
)
from momentum_hunter.config import DATA_DIR
from momentum_hunter.headline_events import build_headline_dedup_report
from momentum_hunter.historical_clusters import (
    classify_candidate_cluster,
    load_cluster_candidates,
)
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.score_breakdowns import SCORE_BREAKDOWNS_PATH
from momentum_hunter.storage import CAPTURES_DIR
from momentum_hunter.study import (
    AGE_BUCKET_ALL,
    CATALYST_CLUSTER_ALL,
    REGIME_ALL,
    REVIEW_ALL,
    SCANNER_ALL,
    SCORE_BUCKET_ALL,
    SECTOR_ALL,
    SESSION_ALL,
    StudyFilter,
    bucket_for_score,
    parse_int,
    parse_optional_float,
    row_is_study_eligible,
    row_review_status,
)


OUTCOME_EXPLORER_LABEL = "OUTCOME EXPLORER — POST-CAPTURE DATA"
SMALL_SAMPLE_LIMIT = 10
MANY_PENDING_WARNING_PCT = 30.0
HIGH_UNKNOWN_TIMESTAMP_WARNING_PCT = 40.0
HIGH_DUPLICATE_WARNING_PCT = 40.0
LOW_CLUSTER_PURITY_WARNING_PCT = 60.0


@dataclass(frozen=True)
class OutcomeCandidate:
    capture_date: str
    capture_time: str
    session: str
    provider: str
    scanner: str
    ticker: str
    sector: str
    industry: str
    market_regime: str
    score: int
    score_bucket: str
    review_status: str
    outcome_status: str
    next_day_return_pct: float | None
    five_day_return_pct: float | None
    max_gain_pct: float | None
    max_drawdown_pct: float | None
    historical_cluster: str
    catalyst_cluster: str
    catalyst_confidence_score: float | None
    catalyst_confidence: str
    cluster_purity_pct: float | None
    timestamp_status: str
    age_bucket: str
    duplicate_event_count: int
    active_raw_capture: bool
    is_study_eligible: bool


@dataclass(frozen=True)
class OutcomeSummary:
    candidate_count: int
    completed_outcome_count: int
    pending_outcome_count: int
    average_next_day_return_pct: float | None
    median_next_day_return_pct: float | None
    average_five_day_return_pct: float | None
    median_five_day_return_pct: float | None
    average_max_gain_pct: float | None
    average_max_drawdown_pct: float | None
    win_rate_pct: float | None
    best_winner: str
    worst_loser: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OutcomePerformanceRow:
    group: str
    candidate_count: int
    completed_count: int
    pending_count: int
    average_next_day_return_pct: float | None
    median_next_day_return_pct: float | None
    average_five_day_return_pct: float | None
    median_five_day_return_pct: float | None
    average_max_gain_pct: float | None
    average_max_drawdown_pct: float | None
    win_rate_pct: float | None
    best_winner: str
    worst_loser: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OutcomeExplorerReport:
    label: str
    source: str
    filters: StudyFilter
    summary: OutcomeSummary
    candidates: list[OutcomeCandidate]
    score_bucket_performance: list[OutcomePerformanceRow]
    regime_performance: list[OutcomePerformanceRow]
    scanner_performance: list[OutcomePerformanceRow]
    sector_performance: list[OutcomePerformanceRow]
    review_status_performance: list[OutcomePerformanceRow]
    catalyst_cluster_performance: list[OutcomePerformanceRow]
    catalyst_age_bucket_performance: list[OutcomePerformanceRow]
    cluster_purity_performance: list[OutcomePerformanceRow]
    warnings: list[str] = field(default_factory=list)


def build_outcome_explorer_report(
    *,
    study_filter: StudyFilter | None = None,
    outcomes_csv: Path = OUTCOMES_CSV,
    captures_dir: Path = CAPTURES_DIR,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
) -> OutcomeExplorerReport:
    study_filter = study_filter or StudyFilter()
    rows = load_outcome_csv_rows(outcomes_csv)
    context = build_context_maps(
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
        study_filter=study_filter,
    )
    candidates = [build_outcome_candidate(row, context) for row in rows]
    filtered = filter_outcome_candidates(candidates, study_filter)
    summary = summarize_outcomes(filtered)
    warnings = list(summary.warnings)
    if not rows:
        warnings.append("No analysis-outcomes.csv rows found.")
    elif not filtered:
        warnings.append("Filters removed all outcome rows.")
    return OutcomeExplorerReport(
        label=OUTCOME_EXPLORER_LABEL,
        source="active raw captures + analysis-captures.csv + analysis-outcomes.csv + score-breakdowns.json + review-decisions.json + catalyst/age/dedup derived context",
        filters=study_filter,
        summary=summary,
        candidates=sorted(filtered, key=lambda item: (item.capture_date, item.capture_time, item.ticker)),
        score_bucket_performance=summarize_by(filtered, "score_bucket"),
        regime_performance=summarize_by(filtered, "market_regime"),
        scanner_performance=summarize_by(filtered, "scanner"),
        sector_performance=summarize_by(filtered, "sector"),
        review_status_performance=summarize_by(filtered, "review_status"),
        catalyst_cluster_performance=summarize_by(filtered, "catalyst_cluster"),
        catalyst_age_bucket_performance=summarize_by(filtered, "age_bucket"),
        cluster_purity_performance=summarize_by_purity_bucket(filtered),
        warnings=warnings,
    )


def load_outcome_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def build_context_maps(
    *,
    captures_dir: Path,
    score_breakdowns_path: Path,
    review_decisions_path: Path,
    outcomes_csv: Path,
    study_filter: StudyFilter,
) -> dict:
    historical = {}
    for candidate in load_cluster_candidates(
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    ):
        historical[candidate_key(candidate.capture_date, candidate.capture_time, candidate.session, candidate.provider, candidate.scanner, candidate.ticker)] = classify_candidate_cluster(candidate)

    headlines, _future_count = load_catalyst_headlines(
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    )
    headlines_by_candidate = defaultdict(list)
    for headline in headlines:
        headlines_by_candidate[candidate_key(headline.capture_date, headline.capture_time, headline.session, headline.provider, headline.scanner, headline.ticker)].append(headline)
    catalyst = {}
    purity_by_cluster = {}
    for key, rows in headlines_by_candidate.items():
        non_future = [row for row in rows if row.timestamp_status != "future"] or rows
        cluster = most_common([row.cluster_name for row in non_future], default="No catalyst data")
        confidence_values = [row.classification_confidence_score for row in non_future]
        confidence_score = average(confidence_values)
        confidence = confidence_label(confidence_score)
        catalyst[key] = {
            "cluster": cluster,
            "confidence_score": confidence_score,
            "confidence": confidence,
        }
    for cluster_name, rows in group_by(headlines, "cluster_name").items():
        non_future = [row for row in rows if row.timestamp_status != "future"]
        if non_future:
            purity_by_cluster[cluster_name] = summarize_catalyst_cluster(cluster_name, non_future).purity_pct

    age = {}
    for record in load_catalyst_age_records(
        captures_dir=captures_dir,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    ):
        key = candidate_key(record.capture_date, record.capture_timestamp, record.session, record.provider, record.scanner, record.ticker)
        age.setdefault(key, []).append(record)
    age_context = {key: summarize_age_context(records) for key, records in age.items()}

    dedup = {}
    dedup_report = build_headline_dedup_report(
        study_filter=StudyFilter(include_non_study_eligible=study_filter.include_non_study_eligible),
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    )
    for event in dedup_report.events:
        if event.duplicate_headline_count <= 1:
            continue
        for headline in event.headlines:
            key = candidate_key(headline.capture_date, headline.capture_time, headline.session, headline.provider, headline.scanner, headline.ticker)
            dedup[key] = dedup.get(key, 0) + 1

    return {
        "historical": historical,
        "active_keys": set(historical.keys()),
        "catalyst": catalyst,
        "purity_by_cluster": purity_by_cluster,
        "age": age_context,
        "dedup": dedup,
    }


def build_outcome_candidate(row: dict, context: dict) -> OutcomeCandidate:
    score = parse_int(row.get("score", "0"))
    key = candidate_key(row.get("capture_date", ""), row.get("capture_time", ""), row.get("session", ""), row.get("provider", ""), row.get("scanner", ""), row.get("ticker", ""))
    catalyst = context["catalyst"].get(key, {})
    cluster = catalyst.get("cluster", "No catalyst data")
    age_context = context["age"].get(key, {"timestamp_status": "UNKNOWN_TIMESTAMP", "age_bucket": "unknown"})
    return OutcomeCandidate(
        capture_date=row.get("capture_date", ""),
        capture_time=row.get("capture_time", ""),
        session=row.get("session", ""),
        provider=row.get("provider", ""),
        scanner=row.get("scanner", ""),
        ticker=row.get("ticker", "").upper(),
        sector=row.get("sector", "") or "unknown",
        industry=row.get("industry", "") or "unknown",
        market_regime=(row.get("market_regime") or "unknown").lower(),
        score=score,
        score_bucket=bucket_for_score(score),
        review_status=row_review_status(row),
        outcome_status=row.get("outcome_status", "missing") or "missing",
        next_day_return_pct=parse_optional_float(row.get("next_day_return_pct", "")),
        five_day_return_pct=parse_optional_float(row.get("five_day_return_pct", "")),
        max_gain_pct=parse_optional_float(row.get("max_gain_pct", "")),
        max_drawdown_pct=parse_optional_float(row.get("max_drawdown_pct", "")),
        historical_cluster=context["historical"].get(key, "No historical cluster"),
        catalyst_cluster=cluster,
        catalyst_confidence_score=catalyst.get("confidence_score"),
        catalyst_confidence=catalyst.get("confidence", "unknown"),
        cluster_purity_pct=context["purity_by_cluster"].get(cluster),
        timestamp_status=age_context["timestamp_status"],
        age_bucket=age_context["age_bucket"],
        duplicate_event_count=context["dedup"].get(key, 0),
        active_raw_capture=key in context["active_keys"],
        is_study_eligible=row_is_study_eligible(row),
    )


def filter_outcome_candidates(candidates: list[OutcomeCandidate], study_filter: StudyFilter) -> list[OutcomeCandidate]:
    filtered = candidates
    filtered = [row for row in filtered if row.active_raw_capture]
    if not study_filter.include_non_study_eligible:
        filtered = [row for row in filtered if row.is_study_eligible]
    if study_filter.start_date:
        filtered = [row for row in filtered if row.capture_date >= study_filter.start_date]
    if study_filter.end_date:
        filtered = [row for row in filtered if row.capture_date <= study_filter.end_date]
    if study_filter.session != SESSION_ALL:
        filtered = [row for row in filtered if row.session == study_filter.session]
    if study_filter.regime != REGIME_ALL:
        filtered = [row for row in filtered if row.market_regime == study_filter.regime]
    if study_filter.scanner != SCANNER_ALL:
        filtered = [row for row in filtered if row.scanner == study_filter.scanner]
    if study_filter.sector != SECTOR_ALL:
        filtered = [row for row in filtered if row.sector == study_filter.sector]
    if study_filter.industry:
        needle = study_filter.industry.lower()
        filtered = [row for row in filtered if needle in row.industry.lower()]
    if study_filter.ticker:
        filtered = [row for row in filtered if row.ticker == study_filter.ticker.upper()]
    if study_filter.minimum_score:
        filtered = [row for row in filtered if row.score >= study_filter.minimum_score]
    if study_filter.score_bucket != SCORE_BUCKET_ALL:
        filtered = [row for row in filtered if row.score_bucket == study_filter.score_bucket]
    if study_filter.review_status != REVIEW_ALL:
        filtered = [row for row in filtered if row.review_status == study_filter.review_status]
    if study_filter.historical_cluster_theme != "all historical themes":
        filtered = [row for row in filtered if row.historical_cluster == study_filter.historical_cluster_theme]
    if study_filter.catalyst_cluster != CATALYST_CLUSTER_ALL:
        filtered = [row for row in filtered if row.catalyst_cluster == study_filter.catalyst_cluster]
    if study_filter.minimum_confidence:
        filtered = [row for row in filtered if (row.catalyst_confidence_score or 0) >= study_filter.minimum_confidence]
    if study_filter.minimum_purity:
        filtered = [row for row in filtered if (row.cluster_purity_pct or 0) >= study_filter.minimum_purity]
    if study_filter.timestamp_status != "all timestamp statuses":
        filtered = [row for row in filtered if row.timestamp_status == study_filter.timestamp_status]
    if study_filter.age_bucket != AGE_BUCKET_ALL:
        filtered = [row for row in filtered if row.age_bucket == study_filter.age_bucket]
    return filtered


def summarize_outcomes(candidates: list[OutcomeCandidate]) -> OutcomeSummary:
    completed = [row for row in candidates if row.outcome_status == "complete"]
    pending = [row for row in candidates if row.outcome_status != "complete"]
    next_returns = [row.next_day_return_pct for row in completed if row.next_day_return_pct is not None]
    five_returns = [row.five_day_return_pct for row in completed if row.five_day_return_pct is not None]
    max_gains = [row.max_gain_pct for row in completed if row.max_gain_pct is not None]
    max_drawdowns = [row.max_drawdown_pct for row in completed if row.max_drawdown_pct is not None]
    warnings = outcome_warnings(candidates, completed, pending)
    return OutcomeSummary(
        candidate_count=len(candidates),
        completed_outcome_count=len(completed),
        pending_outcome_count=len(pending),
        average_next_day_return_pct=average(next_returns),
        median_next_day_return_pct=median_value(next_returns),
        average_five_day_return_pct=average(five_returns),
        median_five_day_return_pct=median_value(five_returns),
        average_max_gain_pct=average(max_gains),
        average_max_drawdown_pct=average(max_drawdowns),
        win_rate_pct=win_rate(five_returns),
        best_winner=best_row(completed, "five_day_return_pct"),
        worst_loser=worst_row(completed, "five_day_return_pct"),
        warnings=warnings,
    )


def summarize_by(candidates: list[OutcomeCandidate], field_name: str) -> list[OutcomePerformanceRow]:
    groups = group_by(candidates, field_name)
    return [summary_to_performance(name, summarize_outcomes(rows)) for name, rows in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))]


def summarize_by_purity_bucket(candidates: list[OutcomeCandidate]) -> list[OutcomePerformanceRow]:
    groups: dict[str, list[OutcomeCandidate]] = defaultdict(list)
    for row in candidates:
        groups[purity_bucket(row.cluster_purity_pct)].append(row)
    order = {"unknown": 0, "0-39": 1, "40-59": 2, "60-79": 3, "80-100": 4}
    return [summary_to_performance(name, summarize_outcomes(rows)) for name, rows in sorted(groups.items(), key=lambda item: order.get(item[0], 99))]


def summary_to_performance(name: str, summary: OutcomeSummary) -> OutcomePerformanceRow:
    return OutcomePerformanceRow(
        group=name or "unknown",
        candidate_count=summary.candidate_count,
        completed_count=summary.completed_outcome_count,
        pending_count=summary.pending_outcome_count,
        average_next_day_return_pct=summary.average_next_day_return_pct,
        median_next_day_return_pct=summary.median_next_day_return_pct,
        average_five_day_return_pct=summary.average_five_day_return_pct,
        median_five_day_return_pct=summary.median_five_day_return_pct,
        average_max_gain_pct=summary.average_max_gain_pct,
        average_max_drawdown_pct=summary.average_max_drawdown_pct,
        win_rate_pct=summary.win_rate_pct,
        best_winner=summary.best_winner,
        worst_loser=summary.worst_loser,
        warnings=summary.warnings,
    )


def outcome_warnings(candidates: list[OutcomeCandidate], completed: list[OutcomeCandidate], pending: list[OutcomeCandidate]) -> list[str]:
    warnings = []
    if len(completed) < SMALL_SAMPLE_LIMIT:
        warnings.append("SMALL SAMPLE SIZE")
        warnings.append("DIAGNOSTIC ONLY")
    if candidates and percent(len(pending), len(candidates)) >= MANY_PENDING_WARNING_PCT:
        warnings.append("MANY PENDING OUTCOMES")
    unknown_count = sum(1 for row in candidates if row.timestamp_status == "UNKNOWN_TIMESTAMP")
    if candidates and percent(unknown_count, len(candidates)) >= HIGH_UNKNOWN_TIMESTAMP_WARNING_PCT:
        warnings.append("HIGH UNKNOWN TIMESTAMP RATE")
    duplicate_count = sum(1 for row in candidates if row.duplicate_event_count > 0)
    if candidates and percent(duplicate_count, len(candidates)) >= HIGH_DUPLICATE_WARNING_PCT:
        warnings.append("HIGH DUPLICATE RATE")
    low_purity_count = sum(1 for row in candidates if row.cluster_purity_pct is not None and row.cluster_purity_pct < LOW_CLUSTER_PURITY_WARNING_PCT)
    if candidates and percent(low_purity_count, len(candidates)) >= LOW_CLUSTER_PURITY_WARNING_PCT:
        warnings.append("LOW CLUSTER PURITY")
    return unique_preserve_order(warnings)


def summarize_age_context(records) -> dict:
    non_future_known = [record for record in records if record.age_at_capture_hours is not None and record.timestamp_status != "FUTURE_TIMESTAMP"]
    if non_future_known:
        freshest = sorted(non_future_known, key=lambda record: record.age_at_capture_hours)[0]
        return {"timestamp_status": freshest.timestamp_status, "age_bucket": freshest.age_bucket}
    if any(record.timestamp_status == "FUTURE_TIMESTAMP" for record in records):
        return {"timestamp_status": "FUTURE_TIMESTAMP", "age_bucket": "invalid_future"}
    if any(record.timestamp_status == "INVALID_TIMESTAMP" for record in records):
        return {"timestamp_status": "INVALID_TIMESTAMP", "age_bucket": "unknown"}
    return {"timestamp_status": "UNKNOWN_TIMESTAMP", "age_bucket": "unknown"}


def candidate_key(capture_date: str, capture_time: str, session: str, provider: str, scanner: str, ticker: str) -> str:
    return "|".join([capture_date, capture_time, session, provider, scanner, ticker.upper()])


def group_by(rows, field_name: str) -> dict:
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[getattr(row, field_name)].append(row)
    return grouped


def most_common(values: list[str], *, default: str) -> str:
    counts = Counter(value for value in values if value)
    if not counts:
        return default
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def confidence_label(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"


def purity_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 40:
        return "0-39"
    if value < 60:
        return "40-59"
    if value < 80:
        return "60-79"
    return "80-100"


def best_row(candidates: list[OutcomeCandidate], metric_name: str) -> str:
    available = [row for row in candidates if getattr(row, metric_name) is not None]
    if not available:
        return "n/a"
    row = max(available, key=lambda item: getattr(item, metric_name))
    return f"{row.ticker} {getattr(row, metric_name):.2f}%"


def worst_row(candidates: list[OutcomeCandidate], metric_name: str) -> str:
    available = [row for row in candidates if getattr(row, metric_name) is not None]
    if not available:
        return "n/a"
    row = min(available, key=lambda item: getattr(item, metric_name))
    return f"{row.ticker} {getattr(row, metric_name):.2f}%"


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def median_value(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(median(values)), 4)


def win_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round((sum(1 for value in values if value > 0) / len(values)) * 100, 2)


def percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
