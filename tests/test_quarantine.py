from __future__ import annotations

import csv
import json
import shutil
import unittest
from pathlib import Path

from momentum_hunter.integrity import QUARANTINED, WARN, audit_raw_captures, overall_audit_status
from momentum_hunter.quarantine import quarantine_raw_capture
from momentum_hunter.rebuild_derived import build_analysis_rows_from_raw_captures, rebuild_derived_data_from_raw_captures, register_legacy_raw_captures
from momentum_hunter.storage import ANALYSIS_FIELDNAMES, file_sha256, load_capture_integrity_manifest


class QuarantineCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_quarantine"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.manifest_path = self.root / "integrity" / "capture_manifest.json"
        self.analysis_csv = self.root / "analysis-captures.csv"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"
        self.review_path = self.root / "review-decisions.json"
        self.quarantine_root = self.root / "quarantine" / "raw-captures"
        self.json_path = self.captures_dir / "2026-06-06" / "morning.json"
        self.md_path = self.captures_dir / "2026-06-06" / "morning.md"
        write_raw_capture(self.json_path)
        self.md_path.write_text("# Morning capture\n", encoding="utf-8")
        self.original_json_hash = file_sha256(self.json_path)
        self.original_md_hash = file_sha256(self.md_path)
        register_legacy_raw_captures(captures_dir=self.captures_dir, manifest_path=self.manifest_path)
        write_analysis_csv(self.analysis_csv)
        self.review_path.write_text(json.dumps({"schema_version": 1, "decisions": {}}, indent=2), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_quarantine_moves_capture_and_excludes_it_from_rebuild(self) -> None:
        result = quarantine_raw_capture(
            "2026-06-06",
            "morning",
            reason="Manifest recorded Institutional Momentum but active file contained Base Momentum; excluded from studies.",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            quarantine_root=self.quarantine_root,
        )

        quarantined_json = result.quarantine_dir / "morning.json"
        quarantined_md = result.quarantine_dir / "morning.md"

        self.assertFalse(self.json_path.exists())
        self.assertFalse(self.md_path.exists())
        self.assertTrue(quarantined_json.exists())
        self.assertTrue(quarantined_md.exists())
        self.assertEqual(self.original_json_hash, file_sha256(quarantined_json))
        self.assertEqual(self.original_md_hash, file_sha256(quarantined_md))
        self.assertTrue(result.note_path.exists())
        self.assertIn("excluded from analysis-captures.csv", result.note_path.read_text(encoding="utf-8"))

        manifest = load_capture_integrity_manifest(self.manifest_path)
        json_record = next(
            key for key in manifest["quarantined_records"] if key.endswith("captures/2026-06-06/morning.json")
        )
        self.assertNotIn(json_record, manifest["records"])
        self.assertEqual("quarantined", manifest["quarantined_records"][json_record]["status"])

        rows = audit_raw_captures(
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            analysis_csv=self.root / "missing-analysis.csv",
            outcomes_csv=self.root / "missing-outcomes.csv",
            review_decisions_path=self.review_path,
        )
        self.assertTrue(any(row.status == QUARANTINED for row in rows))
        self.assertEqual(WARN, overall_audit_status(rows))
        self.assertEqual([], build_analysis_rows_from_raw_captures(self.captures_dir))

        rebuild_result = rebuild_derived_data_from_raw_captures(
            captures_dir=self.captures_dir,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            manifest_path=self.manifest_path,
            review_decisions_path=self.review_path,
            backup_dir=self.root / "backups",
            rebuild_outcomes=False,
            before_audit_csv=self.root / "integrity" / "before.csv",
            before_audit_report=self.root / "integrity" / "before.md",
            after_audit_csv=self.root / "integrity" / "after.csv",
            after_audit_report=self.root / "integrity" / "after.md",
        )
        self.assertEqual(0, rebuild_result.analysis_rows)
        self.assertEqual([], list(csv.DictReader(self.analysis_csv.read_text(encoding="utf-8").splitlines())))


def write_raw_capture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "capture_time": "2026-06-06T07:00:35-05:00",
        "capture_date": "2026-06-06",
        "session": "morning",
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": "Base Momentum"},
        "market": {"regime": "bull", "symbol": "SPY"},
        "candidates": [{"rank": 1, "ticker": "COO", "price": 67.34, "score": 90}],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_analysis_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ANALYSIS_FIELDNAMES)
        writer.writeheader()
        row = {field: "" for field in ANALYSIS_FIELDNAMES}
        row.update({"capture_date": "2026-06-06", "session": "morning", "ticker": "COO", "price": "67.34"})
        writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
