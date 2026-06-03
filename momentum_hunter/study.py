from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from momentum_hunter.storage import ANALYSIS_CSV


@dataclass(frozen=True)
class ScoreBucketSummary:
    label: str
    count: int = 0
    selected_count: int = 0
    reviewed_count: int = 0


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
    score_buckets: list[ScoreBucketSummary] = field(default_factory=list)
    regimes: list[RegimeSummary] = field(default_factory=list)
    has_data: bool = False


BUCKETS = [
    ("0-49", 0, 49),
    ("50-69", 50, 69),
    ("70-84", 70, 84),
    ("85-100", 85, 100),
]


def build_capture_study(path: Path = ANALYSIS_CSV) -> StudySummary:
    if not path.exists():
        return empty_study("No analysis capture file exists yet.")
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        return empty_study("No captured candidate rows exist yet.")
    return summarize_capture_rows(rows)


def summarize_capture_rows(rows: list[dict]) -> StudySummary:
    dates = sorted({row.get("capture_date", "") for row in rows if row.get("capture_date")})
    captures = {
        (row.get("capture_date", ""), row.get("capture_time", ""), row.get("session", ""))
        for row in rows
    }
    bucket_counts = {label: {"count": 0, "selected": 0, "reviewed": 0} for label, _, _ in BUCKETS}
    regime_counts: dict[str, int] = {}
    selected_count = 0
    reviewed_count = 0

    for row in rows:
        score = parse_int(row.get("score", "0"))
        bucket = bucket_for_score(score)
        selected = parse_bool(row.get("selected", "false"))
        reviewed = parse_bool(row.get("reviewed", "false"))
        regime = (row.get("market_regime") or "unknown").lower()

        bucket_counts[bucket]["count"] += 1
        if selected:
            bucket_counts[bucket]["selected"] += 1
            selected_count += 1
        if reviewed:
            bucket_counts[bucket]["reviewed"] += 1
            reviewed_count += 1
        regime_counts[regime] = regime_counts.get(regime, 0) + 1

    source_range = f"{dates[0]} to {dates[-1]}" if dates else "unknown"
    run_id = f"{dates[-1] if dates else 'unknown'}_study_v1"
    return StudySummary(
        run_id=run_id,
        source_range=source_range,
        capture_count=len(captures),
        candidate_count=len(rows),
        selected_count=selected_count,
        reviewed_count=reviewed_count,
        score_buckets=[
            ScoreBucketSummary(
                label=label,
                count=values["count"],
                selected_count=values["selected"],
                reviewed_count=values["reviewed"],
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
        score_buckets=[ScoreBucketSummary(label=label) for label, _, _ in BUCKETS],
        regimes=[],
        has_data=False,
    )


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
