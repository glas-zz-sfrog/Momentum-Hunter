from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.news_age import evaluate_news_freshness, normalize_datetime


FIELDNAMES = [
    "ticker",
    "headline",
    "source",
    "published_at",
    "captured_at",
    "age_hours",
    "freshness_score",
    "freshness_bucket",
]

SUMMARY_FIELDNAMES = ["metric", "count"]


def export_news_freshness_audit(
    output_path: Path | None = None,
    summary_path: Path | None = None,
) -> tuple[Path, int, Path, dict[str, int]]:
    ensure_app_dirs()
    output_path = output_path or DATA_DIR / "news-freshness-audit.csv"
    summary_path = summary_path or output_path.with_name(f"{output_path.stem}-summary.csv")
    rows = []
    summary = {
        "valid timestamp rows": 0,
        "unknown timestamp rows": 0,
        "future timestamp rows": 0,
        "excluded-from-scoring rows": 0,
    }
    for capture_path in sorted((DATA_DIR / "captures").glob("*/*.json")):
        payload = json.loads(capture_path.read_text(encoding="utf-8"))
        captured_at = parse_datetime(payload.get("capture_time"))
        for candidate in payload.get("candidates", []):
            ticker = candidate.get("ticker", "")
            for item in candidate.get("news", []):
                published_at = parse_datetime(item.get("published_at"))
                age_hours, freshness_score, freshness_bucket = audit_freshness(
                    ticker=ticker,
                    headline=item.get("headline", ""),
                    published_at=published_at,
                    captured_at=captured_at,
                )
                update_summary_counts(summary, freshness_bucket)
                rows.append(
                    {
                        "ticker": ticker,
                        "headline": item.get("headline", ""),
                        "source": item.get("source", ""),
                        "published_at": published_at.isoformat() if published_at else "",
                        "captured_at": captured_at.isoformat() if captured_at else "",
                        "age_hours": "" if age_hours is None else f"{age_hours:.2f}",
                        "freshness_score": freshness_score,
                        "freshness_bucket": freshness_bucket,
                    }
                )

    rows.sort(
        key=lambda row: (
            -int(row["freshness_score"]),
            float(row["age_hours"]) if row["age_hours"] else float("inf"),
            row["ticker"],
            row["headline"],
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    with summary_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        for metric, count in summary.items():
            writer.writerow({"metric": metric, "count": count})
    return output_path, len(rows), summary_path, summary


def parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def audit_freshness(
    *,
    ticker: str,
    headline: str,
    published_at: datetime | None,
    captured_at: datetime | None,
) -> tuple[float | None, int, str]:
    published = normalize_datetime(published_at)
    captured = normalize_datetime(captured_at)
    if published is None or captured is None:
        return None, 0, "UNKNOWN"
    age_hours = round((captured - published).total_seconds() / 3600, 2)
    if age_hours < 0:
        return age_hours, 0, "FUTURE_TIMESTAMP"
    freshness = evaluate_news_freshness(
        ticker=ticker,
        headline=headline,
        publish_time=published,
        now=captured,
    )
    return freshness.hours_old, freshness.score, freshness.freshness


def update_summary_counts(summary: dict[str, int], freshness_bucket: str) -> None:
    if freshness_bucket == "UNKNOWN":
        summary["unknown timestamp rows"] += 1
        summary["excluded-from-scoring rows"] += 1
    elif freshness_bucket == "FUTURE_TIMESTAMP":
        summary["future timestamp rows"] += 1
        summary["excluded-from-scoring rows"] += 1
    else:
        summary["valid timestamp rows"] += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Export article-level News Freshness Audit CSV.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV output path. Defaults to MomentumHunterData/data/news-freshness-audit.csv.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=None,
        help="Summary CSV output path. Defaults beside the audit CSV.",
    )
    args = parser.parse_args()
    output_path, row_count, summary_path, summary = export_news_freshness_audit(args.output, args.summary_output)
    print(f"Wrote {row_count} rows to {output_path}")
    print(f"Wrote summary counts to {summary_path}")
    for metric, count in summary.items():
        print(f"{metric}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
