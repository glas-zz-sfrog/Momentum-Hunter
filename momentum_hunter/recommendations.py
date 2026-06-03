from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.study import BUCKETS, bucket_for_score, parse_optional_float


@dataclass(frozen=True)
class ScoreWeightRecommendation:
    regime: str
    bucket: str
    sample_size: int
    avg_five_day_return_pct: float | None
    win_rate_pct: float | None
    recommendation: str
    rationale: str


@dataclass(frozen=True)
class RecommendationReport:
    status: str
    minimum_rows: int
    completed_rows: int
    recommendations: list[ScoreWeightRecommendation]


def build_weight_recommendations(
    path: Path = OUTCOMES_CSV,
    *,
    minimum_rows: int = 20,
    minimum_regime_rows: int = 8,
) -> RecommendationReport:
    if not path.exists():
        return RecommendationReport(
            status="No outcome file exists yet.",
            minimum_rows=minimum_rows,
            completed_rows=0,
            recommendations=[],
        )
    with path.open(newline="", encoding="utf-8") as file:
        rows = [row for row in csv.DictReader(file) if parse_optional_float(row.get("five_day_return_pct", "")) is not None]

    if len(rows) < minimum_rows:
        return RecommendationReport(
            status=f"Insufficient completed 5-day outcomes: {len(rows)} of {minimum_rows} required.",
            minimum_rows=minimum_rows,
            completed_rows=len(rows),
            recommendations=[],
        )

    recommendations: list[ScoreWeightRecommendation] = []
    for regime in sorted({(row.get("market_regime") or "unknown").lower() for row in rows}):
        regime_rows = [row for row in rows if (row.get("market_regime") or "unknown").lower() == regime]
        if len(regime_rows) < minimum_regime_rows:
            recommendations.append(
                ScoreWeightRecommendation(
                    regime=regime,
                    bucket="all",
                    sample_size=len(regime_rows),
                    avg_five_day_return_pct=None,
                    win_rate_pct=None,
                    recommendation="Hold weights",
                    rationale=f"Only {len(regime_rows)} completed rows for {regime}; need {minimum_regime_rows}.",
                )
            )
            continue
        recommendations.extend(recommend_for_regime(regime, regime_rows))

    return RecommendationReport(
        status="Recommendations generated from completed 5-day outcomes.",
        minimum_rows=minimum_rows,
        completed_rows=len(rows),
        recommendations=recommendations,
    )


def recommend_for_regime(regime: str, rows: list[dict]) -> list[ScoreWeightRecommendation]:
    bucket_stats = {label: bucket_statistics(rows, label) for label, _, _ in BUCKETS}
    high = bucket_stats["85-100"]
    mid = bucket_stats["70-84"]
    output: list[ScoreWeightRecommendation] = []

    for label, stats in bucket_stats.items():
        if stats["count"] == 0:
            continue
        avg_return = stats["avg"]
        win_rate = stats["win_rate"]
        if label == "85-100" and avg_return is not None and mid["avg"] is not None:
            if avg_return > mid["avg"] and win_rate is not None and win_rate >= 50:
                recommendation = "Keep or modestly increase high-score momentum/catalyst weight"
                rationale = "Top score bucket is outperforming the next bucket with acceptable win rate."
            elif avg_return < mid["avg"]:
                recommendation = "Reduce high-score momentum/catalyst weight or raise risk penalties"
                rationale = "Top score bucket is underperforming the 70-84 bucket."
            else:
                recommendation = "Hold weights"
                rationale = "Top bucket advantage is not clear yet."
        elif avg_return is not None and avg_return < 0 and win_rate is not None and win_rate < 45:
            recommendation = "Reduce exposure to this bucket"
            rationale = "Average return is negative and win rate is weak."
        else:
            recommendation = "Hold weights"
            rationale = "No strong adjustment signal."

        output.append(
            ScoreWeightRecommendation(
                regime=regime,
                bucket=label,
                sample_size=stats["count"],
                avg_five_day_return_pct=avg_return,
                win_rate_pct=win_rate,
                recommendation=recommendation,
                rationale=rationale,
            )
        )
    return output


def bucket_statistics(rows: list[dict], bucket: str) -> dict:
    values = [
        parse_optional_float(row.get("five_day_return_pct", ""))
        for row in rows
        if bucket_for_score(parse_int(row.get("score", "0"))) == bucket
    ]
    values = [value for value in values if value is not None]
    if not values:
        return {"count": 0, "avg": None, "win_rate": None}
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values), 4),
        "win_rate": round((sum(1 for value in values if value > 0) / len(values)) * 100, 2),
    }


def parse_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
