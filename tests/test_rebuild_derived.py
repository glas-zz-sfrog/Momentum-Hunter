from __future__ import annotations

import csv
import json
import shutil
import unittest
from datetime import datetime
from pathlib import Path

from momentum_hunter.integrity import FAIL, ORPHANED_DERIVED_RECORD, PASS, audit_raw_captures, overall_audit_status
from momentum_hunter.outcomes import OUTCOME_FIELDNAMES
from momentum_hunter.rebuild_derived import build_analysis_rows_from_raw_captures, rebuild_derived_data_from_raw_captures
from momentum_hunter.storage import ANALYSIS_FIELDNAMES, file_sha256, load_capture_integrity_manifest


class RebuildDerivedDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_rebuild_derived"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.analysis_csv = self.root / "analysis-captures.csv"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"
        self.manifest_path = self.root / "integrity" / "capture_manifest.json"
        self.review_path = self.root / "review-decisions.json"
        write_raw_capture(self.captures_dir / "2026-06-05" / "morning.json")
        (self.captures_dir / "2026-06-05" / "morning.md").write_text("# Raw capture report\n", encoding="utf-8")
        write_drifted_analysis_csv(self.analysis_csv)
        write_drifted_outcomes_csv(self.outcomes_csv)
        self.review_path.write_text(json.dumps({"schema_version": 1, "decisions": {}}, indent=2), encoding="utf-8")
        self.raw_hashes_before = raw_hashes(self.captures_dir)
        self.review_hash_before = file_sha256(self.review_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_rebuild_is_deterministic_and_removes_orphaned_derived_rows(self) -> None:
        before_rows = audit_raw_captures(
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            review_decisions_path=self.review_path,
        )
        self.assertEqual(FAIL, overall_audit_status(before_rows))
        self.assertTrue(any(row.status == ORPHANED_DERIVED_RECORD for row in before_rows))

        first = rebuild_derived_data_from_raw_captures(
            captures_dir=self.captures_dir,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            manifest_path=self.manifest_path,
            review_decisions_path=self.review_path,
            backup_dir=self.root / "backups" / "first",
            outcome_session=FakePriceSession(),
            before_audit_csv=self.root / "integrity" / "before-first.csv",
            before_audit_report=self.root / "integrity" / "before-first.md",
            after_audit_csv=self.root / "integrity" / "after-first.csv",
            after_audit_report=self.root / "integrity" / "after-first.md",
        )

        first_analysis_text = self.analysis_csv.read_text(encoding="utf-8")
        first_outcomes_text = self.outcomes_csv.read_text(encoding="utf-8")
        analysis_rows = list(csv.DictReader(first_analysis_text.splitlines()))
        outcome_rows = list(csv.DictReader(first_outcomes_text.splitlines()))

        self.assertEqual(PASS, first.after_status)
        self.assertEqual(2, first.manifest_entries_added)
        self.assertEqual(1, first.analysis_rows)
        self.assertEqual(1, first.outcome_rows)
        self.assertEqual(["MDT"], [row["ticker"] for row in analysis_rows])
        self.assertEqual(["MDT"], [row["ticker"] for row in outcome_rows])
        self.assertIn("FAKE", (self.root / "backups" / "first" / "analysis-captures.csv").read_text(encoding="utf-8"))
        self.assertEqual(self.raw_hashes_before, raw_hashes(self.captures_dir))
        self.assertEqual(self.review_hash_before, file_sha256(self.review_path))

        manifest = load_capture_integrity_manifest(self.manifest_path)
        self.assertEqual(2, len(manifest["records"]))

        second = rebuild_derived_data_from_raw_captures(
            captures_dir=self.captures_dir,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            manifest_path=self.manifest_path,
            review_decisions_path=self.review_path,
            backup_dir=self.root / "backups" / "second",
            outcome_session=FakePriceSession(),
            before_audit_csv=self.root / "integrity" / "before-second.csv",
            before_audit_report=self.root / "integrity" / "before-second.md",
            after_audit_csv=self.root / "integrity" / "after-second.csv",
            after_audit_report=self.root / "integrity" / "after-second.md",
        )

        self.assertEqual(PASS, second.after_status)
        self.assertEqual(0, second.manifest_entries_added)
        self.assertEqual(first_analysis_text, self.analysis_csv.read_text(encoding="utf-8"))
        self.assertEqual(first_outcomes_text, self.outcomes_csv.read_text(encoding="utf-8"))
        self.assertEqual(self.raw_hashes_before, raw_hashes(self.captures_dir))
        self.assertEqual(self.review_hash_before, file_sha256(self.review_path))

    def test_build_analysis_rows_from_raw_captures_is_deterministic(self) -> None:
        first = build_analysis_rows_from_raw_captures(self.captures_dir)
        second = build_analysis_rows_from_raw_captures(self.captures_dir)

        self.assertEqual(first, second)
        self.assertEqual("MDT", first[0]["ticker"])


def write_raw_capture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "capture_time": "2026-06-05T07:00:00-05:00",
        "capture_date": "2026-06-05",
        "session": "morning",
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": "Base Momentum"},
        "scoring": {"profile": "regime-aware-v1", "regime": "bull"},
        "market": {"regime": "bull", "symbol": "SPY", "close": 600, "sma_50": 590, "sma_200": 560},
        "candidates": [
            {
                "rank": 1,
                "ticker": "MDT",
                "company": "Medtronic PLC",
                "score": 90,
                "price": 82.0,
                "percent_change": 5.5,
                "volume": 19_000_000,
                "relative_volume": 1.7,
                "market_cap": 105_000_000_000,
                "sector": "Healthcare",
                "industry": "Medical Devices",
                "freshness": "HOT",
                "freshness_score": 100,
                "article_count": 1,
                "news": [],
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_drifted_analysis_csv(path: Path) -> None:
    rows = [
        {"capture_date": "2026-06-05", "capture_time": "2026-06-05T07:00:00-05:00", "session": "morning", "ticker": "MDT", "price": "82.0"},
        {"capture_date": "2026-06-05", "capture_time": "2026-06-05T07:00:00-05:00", "session": "morning", "ticker": "FAKE", "price": "10.0"},
    ]
    write_rows(path, ANALYSIS_FIELDNAMES, rows)


def write_drifted_outcomes_csv(path: Path) -> None:
    rows = [
        {"capture_date": "2026-06-05", "capture_time": "2026-06-05T07:00:00-05:00", "session": "morning", "ticker": "MDT", "price": "82.0"},
        {"capture_date": "2026-06-05", "capture_time": "2026-06-05T07:00:00-05:00", "session": "morning", "ticker": "FAKE", "price": "10.0"},
    ]
    write_rows(path, OUTCOME_FIELDNAMES, rows)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def raw_hashes(captures_dir: Path) -> dict[str, str]:
    return {str(path): file_sha256(path) for path in sorted(captures_dir.rglob("*")) if path.is_file()}


class FakePriceSession:
    def get(self, url: str, timeout: int):
        return FakePriceResponse()


class FakePriceResponse:
    status_code = 200

    def json(self) -> dict:
        timestamps = [
            int(datetime(2026, 6, 8).timestamp()),
            int(datetime(2026, 6, 9).timestamp()),
            int(datetime(2026, 6, 10).timestamp()),
            int(datetime(2026, 6, 11).timestamp()),
            int(datetime(2026, 6, 12).timestamp()),
        ]
        return {
            "chart": {
                "result": [
                    {
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "close": [84.0, 85.0, 86.0, 87.0, 88.0],
                                    "high": [85.0, 86.0, 87.0, 88.0, 89.0],
                                    "low": [81.0, 82.0, 83.0, 84.0, 85.0],
                                }
                            ],
                            "adjclose": [{"adjclose": [84.0, 85.0, 86.0, 87.0, 88.0]}],
                        },
                    }
                ]
            }
        }


if __name__ == "__main__":
    unittest.main()
