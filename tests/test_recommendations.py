from __future__ import annotations

import csv
import unittest
import uuid
from pathlib import Path

from momentum_hunter.recommendations import build_weight_recommendations


class RecommendationTests(unittest.TestCase):
    def test_reports_insufficient_completed_outcomes(self) -> None:
        path = temp_csv_path()
        write_rows(path, [{"market_regime": "bull", "score": "90", "five_day_return_pct": "2.0"}])

        report = build_weight_recommendations(path, minimum_rows=3)

        self.assertEqual(1, report.completed_rows)
        self.assertIn("Insufficient completed", report.status)
        self.assertEqual([], report.recommendations)

    def test_recommends_boost_when_top_bucket_outperforms(self) -> None:
        rows = []
        for _ in range(8):
            rows.append({"market_regime": "bull", "score": "90", "five_day_return_pct": "4.0"})
        for _ in range(8):
            rows.append({"market_regime": "bull", "score": "75", "five_day_return_pct": "1.0"})
        path = temp_csv_path()
        write_rows(path, rows)

        report = build_weight_recommendations(path, minimum_rows=10, minimum_regime_rows=8)

        top_bucket = next(item for item in report.recommendations if item.bucket == "85-100")
        self.assertIn("increase", top_bucket.recommendation)
        self.assertEqual(8, top_bucket.sample_size)
        self.assertEqual(4.0, top_bucket.avg_five_day_return_pct)


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["market_regime", "score", "five_day_return_pct"]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def temp_csv_path() -> Path:
    return Path.cwd() / ".tmp" / "tests" / f"recommendations-{uuid.uuid4().hex}.csv"


if __name__ == "__main__":
    unittest.main()
