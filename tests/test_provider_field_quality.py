from __future__ import annotations

import csv
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.provider_field_quality import (
    build_provider_field_quality_report,
    write_provider_field_quality_report,
)
from momentum_hunter.storage import file_sha256


class ProviderFieldQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-provider-field-quality-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.root / "analysis-captures.csv"
        self.output_dir = self.root / "reports"
        write_analysis_rows(self.csv_path)
        self.scoring_path = Path.cwd() / "momentum_hunter" / "scoring.py"
        self.scoring_hash = file_sha256(self.scoring_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_report_flags_missing_zero_impossible_and_stale_fields(self) -> None:
        payload = build_provider_field_quality_report(
            analysis_captures_path=self.csv_path,
            generated_at=datetime.fromisoformat("2026-06-26T09:00:00-05:00"),
            stale_after_days=7,
        )

        warnings = {item["warning"]: item["count"] for item in payload["top_warnings"]}
        self.assertEqual("WARN", payload["overall_status"])
        self.assertGreaterEqual(warnings["ZERO_RELATIVE_VOLUME"], 1)
        self.assertGreaterEqual(warnings["MISSING_PRICE"], 1)
        self.assertGreaterEqual(warnings["IMPOSSIBLE_NEGATIVE_MARKET_CAP"], 1)
        self.assertGreaterEqual(warnings["STALE_CAPTURE_TIMESTAMP"], 1)
        self.assertEqual("SKIPPED_UNSUPPORTED_SCHEMA", payload["sqlite_write_status"]["status"])

    def test_report_generation_writes_json_and_markdown_without_scoring_mutation(self) -> None:
        payload = build_provider_field_quality_report(
            analysis_captures_path=self.csv_path,
            generated_at=datetime.fromisoformat("2026-06-26T09:00:00-05:00"),
        )

        json_path, markdown_path = write_provider_field_quality_report(payload, output_dir=self.output_dir)

        self.assertTrue(json_path.exists())
        self.assertTrue(markdown_path.exists())
        self.assertIn("Provider Field Quality Audit", markdown_path.read_text(encoding="utf-8"))
        self.assertEqual(self.scoring_hash, file_sha256(self.scoring_path))


def write_analysis_rows(path: Path) -> None:
    rows = [
        {
            "capture_time": "2026-06-25T09:00:00-05:00",
            "provider": "finviz",
            "scanner": "Basic Momentum",
            "ticker": "ZERO",
            "price": "10.50",
            "percent_change": "5.0",
            "volume": "1000000",
            "relative_volume": "0.0",
            "market_cap": "5B",
        },
        {
            "capture_time": "2026-06-25T09:01:00-05:00",
            "provider": "finviz",
            "scanner": "Basic Momentum",
            "ticker": "MISS",
            "price": "",
            "percent_change": "6.0",
            "volume": "1500000",
            "relative_volume": "1.2",
            "market_cap": "6B",
        },
        {
            "capture_time": "2026-06-01T09:02:00-05:00",
            "provider": "finviz",
            "scanner": "Basic Momentum",
            "ticker": "BAD",
            "price": "12.00",
            "percent_change": "7.0",
            "volume": "2000000",
            "relative_volume": "1.8",
            "market_cap": "-10",
        },
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
