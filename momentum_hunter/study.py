from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.scheduling import row_is_study_eligible
from momentum_hunter.storage import ANALYSIS_CSV


FILTER_ALL = "all candidates"
FILTER_SELECTED = "selected only"
FILTER_REVIEWED = "reviewed only"
SESSION_ALL = "all sessions"
REGIME_ALL = "all regimes"


@dataclass(frozen=True)
class StudyFilter:
    row_filter: str = FILTER_ALL
    start_date: str = ""
    end_date: str = ""
    session: str = SESSION_ALL
    regime: str = REGIME_ALL
    include_non_study_eligible: bool = False

    def label(self) -> str:
        parts = [self.row_filter]
        if self.start_date or self.end_date:
            parts.append(f"{self.start_date or 'start'} to {self.end_date or 'end'}")
        if self.session != SESSION_ALL:
            parts.append(self.session)
        if self.regime != REGIME_ALL:
            parts.append(self.regime)
        if self.include_non_study_eligible:
            parts.append("including non-trading-day captures")
        return " | ".join(parts)


@dataclass(frozen=True)
class ScoreBucketSummary:
    label: str
    count: int = 0
    selected_count: int = 0
    reviewed_count: int = 0
    avg_next_day_return_pct: float | None = None
    avg_five_day_return_pct: float | None = None


@dataclass(frozen=True)
class RegimeSummary:
    regime: str
    count: int = 0


@dataclass(frozen=True)
class StudySummary:
    run_id: str
    source_range: str
    capture_count: int
    candidate_count: int
    selected_count: int
    reviewed_count: int
    scoring_profiles: list[str] = field(default_factory=list)
    outcome_count: int = 0
    complete_outcome_count: int = 0
    avg_next_day_return_pct: float | None = None
    avg_five_day_return_pct: float | None = None
    next_day_win_rate_pct: float | None = None
    five_day_win_rate_pct: float | None = None
    score_buckets: list[ScoreBucketSummary] = field(default_factory=list)
    regimes: list[RegimeSummary] = field(default_factory=list)
    has_data: bool = False


BUCKETS = [
    ("0-49", 0, 49),
    ("50-69", 50, 69),
    ("70-84", 70, 84),
    ("85-100", 85, 100),
]


def build_capture_study(
    path: Path = ANALYSIS_CSV,
    row_filter: str = FILTER_ALL,
    study_filter: StudyFilter | None = None,
) -> StudySummary:
    study_filter = study_filter or StudyFilter(row_filter=row_filter)
    outcome_path = OUTCOMES_CSV if OUTCOMES_CSV.exists() else path
    if not outcome_path.exists():
        return empty_study("No analysis capture file exists yet.")
    with outcome_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        return empty_study("No captured candidate rows exist yet.")
    return summarize_capture_rows(rows, study_filter=study_filter)


def summarize_capture_rows(
    rows: list[dict],
    row_filter: str = FILTER_ALL,
    study_filter: StudyFilter | None = None,
) -> StudySummary:
    study_filter = study_filter or StudyFilter(row_filter=row_filter)
    rows = filter_rows(rows, study_filter)
    dates = sorted({row.get("capture_date", "") for row in rows if row.get("capture_date")})
    captures = {
        (row.get("capture_date", ""), row.get("capture_time", ""), row.get("session", ""))
        for row in rows
    }
    bucket_counts = {label: {"count": 0, "selected": 0, "reviewed": 0} for label, _, _ in BUCKETS}
    regime_counts: dict[str, int] = {}
    scoring_profiles = sorted(
        {
            row.get("score_profile", "")
            for row in rows
            if row.get("score_profile")
        }
    )
    selected_count = 0
    reviewed_count = 0

    for row in rows:
        score = parse_int(row.get("score", "0"))
        bucket = bucket_for_score(score)
        selected = parse_bool(row.get("selected", "false"))
        reviewed = parse_bool(row.get("reviewed", "false"))
        regime = (row.get("market_regime") or "unknown").lower()

        next_day_return = parse_optional_float(row.get("next_day_return_pct", ""))
        five_day_return = parse_optional_float(row.get("five_day_return_pct", ""))

        bucket_counts[bucket].setdefault("next_returns", [])
        bucket_counts[bucket].setdefault("five_returns", [])
        bucket_counts[bucket]["count"] += 1
        if selected:
            bucket_counts[bucket]["selected"] += 1
            selected_count += 1
        if reviewed:
            bucket_counts[bucket]["reviewed"] += 1
            reviewed_count += 1
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        if next_day_return is not None:
            bucket_counts[bucket]["next_returns"].append(next_day_return)
        if five_day_return is not None:
            bucket_counts[bucket]["five_returns"].append(five_day_return)

    all_next_returns = [
        value
        for values in bucket_counts.values()
        for value in values.get("next_returns", [])
    ]
    all_five_returns = [
        value
        for values in bucket_counts.values()
        for value in values.get("five_returns", [])
    ]

    source_range = f"{dates[0]} to {dates[-1]}" if dates else "unknown"
    run_id = f"{dates[-1] if dates else 'unknown'}_study_v1"
    return StudySummary(
        run_id=run_id,
        source_range=f"{source_range} | Filter: {study_filter.label()}",
        capture_count=len(captures),
        candidate_count=len(rows),
        selected_count=selected_count,
        reviewed_count=reviewed_count,
        scoring_profiles=scoring_profiles,
        outcome_count=len(all_next_returns),
        complete_outcome_count=len(all_five_returns),
        avg_next_day_return_pct=average(all_next_returns),
        avg_five_day_return_pct=average(all_five_returns),
        next_day_win_rate_pct=win_rate(all_next_returns),
        five_day_win_rate_pct=win_rate(all_five_returns),
        score_buckets=[
            ScoreBucketSummary(
                label=label,
                count=values["count"],
                selected_count=values["selected"],
                reviewed_count=values["reviewed"],
                avg_next_day_return_pct=average(values.get("next_returns", [])),
                avg_five_day_return_pct=average(values.get("five_returns", [])),
            )
            for label, values in bucket_counts.items()
        ],
        regimes=[
            RegimeSummary(regime=regime, count=count)
            for regime, count in sorted(regime_counts.items(), key=lambda item: item[0])
        ],
        has_data=True,
    )


def empty_study(reason: str) -> StudySummary:
    return StudySummary(
        run_id="no_data_study_v1",
        source_range=reason,
        capture_count=0,
        candidate_count=0,
        selected_count=0,
        reviewed_count=0,
        outcome_count=0,
        complete_outcome_count=0,
        score_buckets=[ScoreBucketSummary(label=label) for label, _, _ in BUCKETS],
        regimes=[],
        has_data=False,
    )


def filter_rows(rows: list[dict], study_filter: StudyFilter) -> list[dict]:
    filtered = rows
    if not study_filter.include_non_study_eligible:
        filtered = [row for row in filtered if row_is_study_eligible(row)]
    if study_filter.row_filter == FILTER_SELECTED:
        filtered = [row for row in filtered if parse_bool(row.get("selected", "false"))]
    elif study_filter.row_filter == FILTER_REVIEWED:
        filtered = [row for row in filtered if parse_bool(row.get("reviewed", "false"))]
    if study_filter.start_date:
        filtered = [row for row in filtered if row.get("capture_date", "") >= study_filter.start_date]
    if study_filter.end_date:
        filtered = [row for row in filtered if row.get("capture_date", "") <= study_filter.end_date]
    if study_filter.session != SESSION_ALL:
        filtered = [row for row in filtered if row.get("session", "") == study_filter.session]
    if study_filter.regime != REGIME_ALL:
        filtered = [
            row for row in filtered if (row.get("market_regime") or "unknown").lower() == study_filter.regime
        ]
    return filtered


def bucket_for_score(score: int) -> str:
    for label, low, high in BUCKETS:
        if low <= score <= high:
            return label
    return "0-49" if score < 0 else "85-100"


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def parse_optional_float(value: str) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def win_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round((sum(1 for value in values if value > 0) / len(values)) * 100, 2)
