from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from momentum_hunter.config import DATA_DIR
from momentum_hunter.headline_events import build_headline_dedup_report
from momentum_hunter.outcome_explorer import (
    OutcomeCandidate,
    OutcomePerformanceRow,
    OutcomeSummary,
    build_outcome_explorer_report,
    percent,
    purity_bucket,
    summarize_outcomes,
    summary_to_performance,
)
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.score_breakdowns import SCORE_BREAKDOWNS_PATH
from momentum_hunter.storage import CAPTURES_DIR
from momentum_hunter.study import StudyFilter


OPPORTUNITY_RESEARCH_LABEL = "OPPORTUNITY RESEARCH — RESEARCH ONLY"
MIN_COMPLETED_FOR_CONCLUSIONS = 30
SMALL_SAMPLE_COMPLETED_LIMIT = 10
HIGH_PENDING_WARNING_PCT = 30.0


@dataclass(frozen=True)
class OpportunityConditionRow:
    dimension: str
    condition: str
    candidate_count: int
    completed_count: int
    pending_count: int
    pending_rate_pct: float
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
class OpportunityResearchReport:
    label: str
    source: str
    filters: StudyFilter
    summary: OutcomeSummary
    condition_rows: list[OpportunityConditionRow]
    best_performing_conditions: list[OpportunityConditionRow]
    worst_performing_conditions: list[OpportunityConditionRow]
    most_pending_conditions: list[OpportunityConditionRow]
    highest_max_gain_conditions: list[OpportunityConditionRow]
    highest_drawdown_conditions: list[OpportunityConditionRow]
    combination_rows: list[OpportunityConditionRow]
    warnings: list[str] = field(default_factory=list)


def build_opportunity_research_report(
    *,
    study_filter: StudyFilter | None = None,
    outcomes_csv: Path = OUTCOMES_CSV,
    captures_dir: Path = CAPTURES_DIR,
    score_breakdowns_path: Path = SCORE_BREAKDOWNS_PATH,
    review_decisions_path: Path = DATA_DIR / "review-decisions.json",
) -> OpportunityResearchReport:
    study_filter = study_filter or StudyFilter()
    outcome_report = build_outcome_explorer_report(
        study_filter=study_filter,
        outcomes_csv=outcomes_csv,
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
    )
    dedup_report = build_headline_dedup_report(
        study_filter=StudyFilter(include_non_study_eligible=study_filter.include_non_study_eligible),
        captures_dir=captures_dir,
        score_breakdowns_path=score_breakdowns_path,
        review_decisions_path=review_decisions_path,
        outcomes_csv=outcomes_csv,
    )
    source_quality_by_provider = {
        row.source.removeprefix("provider:"): row
        for row in dedup_report.source_reliability
        if row.source.startswith("provider:")
    }
    candidates = outcome_report.candidates
    condition_rows = build_condition_rows(candidates, source_quality_by_provider)
    combination_rows = build_combination_rows(candidates)
    warnings = report_warnings(outcome_report.summary)
    return OpportunityResearchReport(
        label=OPPORTUNITY_RESEARCH_LABEL,
        source="active raw captures + analysis-captures.csv + analysis-outcomes.csv + score-breakdowns.json + review-decisions.json + catalyst clusters + catalyst age + headline dedup/source reliability",
        filters=study_filter,
        summary=outcome_report.summary,
        condition_rows=condition_rows,
        best_performing_conditions=rank_best(condition_rows),
        worst_performing_conditions=rank_worst(condition_rows),
        most_pending_conditions=rank_pending(condition_rows),
        highest_max_gain_conditions=rank_max_gain(condition_rows),
        highest_drawdown_conditions=rank_drawdown(condition_rows),
        combination_rows=combination_rows,
        warnings=warnings,
    )


def build_condition_rows(candidates: list[OutcomeCandidate], source_quality_by_provider: dict) -> list[OpportunityConditionRow]:
    dimensions = [
        ("Score Bucket", lambda row: row.score_bucket),
        ("Market Regime", lambda row: row.market_regime),
        ("Scanner Preset", lambda row: row.scanner),
        ("Sector", lambda row: row.sector),
        ("Industry", lambda row: row.industry),
        ("Catalyst Cluster", lambda row: row.catalyst_cluster),
        ("Catalyst Confidence", lambda row: confidence_bucket(row.catalyst_confidence_score)),
        ("Cluster Purity", lambda row: purity_bucket(row.cluster_purity_pct)),
        ("Catalyst Age Bucket", lambda row: row.age_bucket),
        ("Review Status", lambda row: row.review_status),
        ("Source Reliability", lambda row: source_reliability_bucket(source_quality_by_provider, row.provider)),
        ("Duplicate Rate", lambda row: duplicate_rate_bucket(source_quality_by_provider, row.provider)),
    ]
    rows: list[OpportunityConditionRow] = []
    for dimension, getter in dimensions:
        groups: dict[str, list[OutcomeCandidate]] = {}
        for candidate in candidates:
            groups.setdefault(getter(candidate) or "unknown", []).append(candidate)
        for condition, group_candidates in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
            rows.append(to_condition_row(dimension, condition, group_candidates))
    return rows


def build_combination_rows(candidates: list[OutcomeCandidate]) -> list[OpportunityConditionRow]:
    combinations = [
        ("Regime + Catalyst", lambda row: f"{row.market_regime} + {row.catalyst_cluster}"),
        ("Score + Catalyst Confidence", lambda row: f"{row.score_bucket} + {confidence_bucket(row.catalyst_confidence_score)} confidence"),
        ("Score + Cluster Purity", lambda row: f"{row.score_bucket} + {purity_bucket(row.cluster_purity_pct)} purity"),
        ("Review + Catalyst", lambda row: f"{row.review_status} + {row.catalyst_cluster}"),
    ]
    rows: list[OpportunityConditionRow] = []
    for dimension, getter in combinations:
        groups: dict[str, list[OutcomeCandidate]] = {}
        for candidate in candidates:
            groups.setdefault(getter(candidate), []).append(candidate)
        for condition, group_candidates in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
            rows.append(to_condition_row(dimension, condition, group_candidates))
    return rows


def to_condition_row(dimension: str, condition: str, candidates: list[OutcomeCandidate]) -> OpportunityConditionRow:
    summary = summarize_outcomes(candidates)
    perf = summary_to_performance(condition, summary)
    warnings = condition_warnings(summary)
    return OpportunityConditionRow(
        dimension=dimension,
        condition=condition,
        candidate_count=perf.candidate_count,
        completed_count=perf.completed_count,
        pending_count=perf.pending_count,
        pending_rate_pct=percent(perf.pending_count, perf.candidate_count),
        average_next_day_return_pct=perf.average_next_day_return_pct,
        median_next_day_return_pct=perf.median_next_day_return_pct,
        average_five_day_return_pct=perf.average_five_day_return_pct,
        median_five_day_return_pct=perf.median_five_day_return_pct,
        average_max_gain_pct=perf.average_max_gain_pct,
        average_max_drawdown_pct=perf.average_max_drawdown_pct,
        win_rate_pct=perf.win_rate_pct,
        best_winner=perf.best_winner,
        worst_loser=perf.worst_loser,
        warnings=warnings,
    )


def report_warnings(summary: OutcomeSummary) -> list[str]:
    warnings = ["RESEARCH ONLY", "DO NOT USE FOR TRADING DECISIONS YET"]
    if summary.completed_outcome_count < MIN_COMPLETED_FOR_CONCLUSIONS:
        warnings.append("INSUFFICIENT COMPLETED OUTCOMES")
    warnings.extend(condition_warnings(summary))
    return unique_preserve_order(warnings)


def condition_warnings(summary: OutcomeSummary) -> list[str]:
    warnings = []
    if summary.completed_outcome_count < SMALL_SAMPLE_COMPLETED_LIMIT:
        warnings.append("SMALL SAMPLE")
    if summary.candidate_count and percent(summary.pending_outcome_count, summary.candidate_count) >= HIGH_PENDING_WARNING_PCT:
        warnings.append("HIGH PENDING RATE")
    warnings.extend(summary.warnings)
    return normalize_warning_names(unique_preserve_order(warnings))


def normalize_warning_names(warnings: list[str]) -> list[str]:
    normalized = []
    for warning in warnings:
        if warning == "SMALL SAMPLE SIZE":
            normalized.append("SMALL SAMPLE")
        elif warning == "MANY PENDING OUTCOMES":
            normalized.append("HIGH PENDING RATE")
        else:
            normalized.append(warning)
    return unique_preserve_order(normalized)


def rank_best(rows: list[OpportunityConditionRow], limit: int = 10) -> list[OpportunityConditionRow]:
    completed = [row for row in rows if row.completed_count > 0 and row.average_five_day_return_pct is not None]
    return sorted(completed, key=lambda row: (row.average_five_day_return_pct, row.average_next_day_return_pct or 0, row.completed_count), reverse=True)[:limit]


def rank_worst(rows: list[OpportunityConditionRow], limit: int = 10) -> list[OpportunityConditionRow]:
    completed = [row for row in rows if row.completed_count > 0 and row.average_five_day_return_pct is not None]
    return sorted(completed, key=lambda row: (row.average_five_day_return_pct, row.average_next_day_return_pct or 0, -row.completed_count))[:limit]


def rank_pending(rows: list[OpportunityConditionRow], limit: int = 10) -> list[OpportunityConditionRow]:
    return sorted(rows, key=lambda row: (row.pending_rate_pct, row.pending_count, row.candidate_count), reverse=True)[:limit]


def rank_max_gain(rows: list[OpportunityConditionRow], limit: int = 10) -> list[OpportunityConditionRow]:
    completed = [row for row in rows if row.completed_count > 0 and row.average_max_gain_pct is not None]
    return sorted(completed, key=lambda row: (row.average_max_gain_pct, row.completed_count), reverse=True)[:limit]


def rank_drawdown(rows: list[OpportunityConditionRow], limit: int = 10) -> list[OpportunityConditionRow]:
    completed = [row for row in rows if row.completed_count > 0 and row.average_max_drawdown_pct is not None]
    return sorted(completed, key=lambda row: (row.average_max_drawdown_pct, -row.completed_count))[:limit]


def confidence_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 80:
        return "high"
    if value >= 60:
        return "medium"
    return "low"


def source_reliability_bucket(source_quality_by_provider: dict, provider: str) -> str:
    quality = source_quality_by_provider.get(provider)
    if quality is None:
        return "unknown"
    exact_pct = quality.exact_pct
    if exact_pct >= 80:
        return "high reliability"
    if exact_pct >= 50:
        return "medium reliability"
    return "low reliability"


def duplicate_rate_bucket(source_quality_by_provider: dict, provider: str) -> str:
    quality = source_quality_by_provider.get(provider)
    if quality is None:
        return "unknown"
    duplicate_rate = quality.duplicate_rate_pct
    if duplicate_rate >= 60:
        return "high duplicate rate"
    if duplicate_rate >= 30:
        return "medium duplicate rate"
    return "low duplicate rate"


def unique_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
