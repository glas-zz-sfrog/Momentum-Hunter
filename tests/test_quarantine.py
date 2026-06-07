from __future__ import annotations

import csv
import json
import shutil
import unittest
from datetime import datetime
from pathlib import Path

from momentum_hunter.integrity import FAIL, QUARANTINED, WARN, audit_raw_captures, overall_audit_status
from momentum_hunter.quarantine import quarantine_raw_capture
from momentum_hunter.rebuild_derived import build_analysis_rows_from_raw_captures, rebuild_derived_data_from_raw_captures, register_legacy_raw_captures
from momentum_hunter.recover_modified_captures import recover_modified_raw_captures
from momentum_hunter.review import CandidateIdentity, ReviewDecision, ReviewStatus, make_capture_id, save_review_decisions
from momentum_hunter.storage import ANALYSIS_FIELDNAMES, file_sha256, load_capture_integrity_manifest
from momentum_hunter.time_utils import CENTRAL_TZ


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
        write_raw_capture(
            self.json_path,
            capture_time="2026-06-06T07:00:03-05:00",
            scanner="Institutional Momentum",
        )
        self.md_path.write_text("# Institutional morning capture\n", encoding="utf-8")
        self.original_json_hash = file_sha256(self.json_path)
        self.original_md_hash = file_sha256(self.md_path)
        register_legacy_raw_captures(captures_dir=self.captures_dir, manifest_path=self.manifest_path)
        write_analysis_csv(self.analysis_csv, scanner="Institutional Momentum")
        self.review_path.write_text(json.dumps({"schema_version": 1, "decisions": {}}, indent=2), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_quarantine_moves_capture_to_timestamped_batch_and_excludes_it_from_rebuild(self) -> None:
        result = quarantine_raw_capture(
            "2026-06-06",
            "morning",
            reason="Manifest hash mismatch; excluded from studies.",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            quarantine_root=self.quarantine_root,
            quarantined_at=datetime(2026, 6, 6, 17, 0, 0, tzinfo=CENTRAL_TZ),
        )

        quarantined_json = result.quarantine_dir / "2026-06-06-morning.json"
        quarantined_md = result.quarantine_dir / "2026-06-06-morning.md"

        self.assertEqual("20260606-170000", result.quarantine_dir.name)
        self.assertFalse(self.json_path.exists())
        self.assertFalse(self.md_path.exists())
        self.assertTrue(quarantined_json.exists())
        self.assertTrue(quarantined_md.exists())
        self.assertEqual(self.original_json_hash, file_sha256(quarantined_json))
        self.assertEqual(self.original_md_hash, file_sha256(quarantined_md))
        self.assertTrue(result.note_path.exists())
        note = result.note_path.read_text(encoding="utf-8")
        self.assertIn("excluded from analysis-captures.csv", note)
        self.assertIn("Original Manifest Metadata", note)
        self.assertIn("Current File Metadata", note)
        self.assertIn("Hash Mismatch", note)

        manifest = load_capture_integrity_manifest(self.manifest_path)
        json_record = next(
            key for key in manifest["quarantined_records"] if key.endswith("captures/2026-06-06/morning.json")
        )
        self.assertNotIn(json_record, manifest["records"])
        self.assertEqual("quarantined", manifest["quarantined_records"][json_record]["status"])
        self.assertIn("20260606-170000", manifest["quarantined_records"][json_record]["quarantine_path"])

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

    def test_recover_modified_capture_quarantines_rebuilds_and_marks_review_decisions(self) -> None:
        mutate_raw_capture_to_base_momentum(self.json_path, self.md_path)
        write_review_decision(self.review_path)

        before_rows = audit_raw_captures(
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            review_decisions_path=self.review_path,
        )
        self.assertEqual(FAIL, overall_audit_status(before_rows))

        result = recover_modified_raw_captures(
            reason="Manifest recorded Institutional Momentum, but current file contains Base Momentum.",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            quarantine_root=self.quarantine_root,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            review_decisions_path=self.review_path,
            rebuild_outcomes=False,
            recovered_at=datetime(2026, 6, 6, 17, 30, 0, tzinfo=CENTRAL_TZ),
            before_audit_csv=self.root / "integrity" / "modified-before.csv",
            before_audit_report=self.root / "integrity" / "modified-before.md",
            after_audit_csv=self.root / "integrity" / "modified-after.csv",
            after_audit_report=self.root / "integrity" / "modified-after.md",
        )

        self.assertEqual(FAIL, result.before_status)
        self.assertEqual(WARN, result.after_status)
        self.assertEqual(1, len(result.quarantine_results))
        self.assertEqual(1, result.review_decisions_marked)
        self.assertEqual(0, result.rebuild_result.analysis_rows)
        self.assertEqual(0, result.rebuild_result.outcome_rows)
        self.assertFalse(self.json_path.exists())
        self.assertFalse(self.md_path.exists())

        quarantine_dir = result.quarantine_results[0].quarantine_dir
        self.assertEqual("20260606-173000", quarantine_dir.name)
        self.assertTrue((quarantine_dir / "2026-06-06-morning.json").exists())
        self.assertTrue((quarantine_dir / "2026-06-06-morning.md").exists())

        manifest = load_capture_integrity_manifest(self.manifest_path)
        json_record = next(
            record
            for key, record in manifest["quarantined_records"].items()
            if key.endswith("captures/2026-06-06/morning.json")
        )
        self.assertEqual("Institutional Momentum", json_record["original_manifest_metadata"]["scanner"])
        self.assertEqual("Base Momentum", json_record["current_file_metadata"]["scanner"])
        self.assertNotEqual(json_record["hash_mismatch"]["manifest_hash"], json_record["hash_mismatch"]["current_hash"])

        note = result.quarantine_results[0].note_path.read_text(encoding="utf-8")
        self.assertIn("Original Manifest Metadata", note)
        self.assertIn("Current File Metadata", note)
        self.assertIn("Hash Mismatch", note)

        decisions = json.loads(self.review_path.read_text(encoding="utf-8"))["decisions"]
        decision_payload = next(iter(decisions.values()))
        self.assertEqual("quarantined", decision_payload["capture_status"])

        after_rows = audit_raw_captures(
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            review_decisions_path=self.review_path,
        )
        self.assertTrue(any(row.kind == "review_decision" and row.status == QUARANTINED for row in after_rows))
        self.assertEqual(WARN, overall_audit_status(after_rows))

    def test_recover_modified_evening_capture_rebuilds_from_remaining_valid_raw_capture(self) -> None:
        evening_json = self.captures_dir / "2026-06-06" / "evening.json"
        evening_md = self.captures_dir / "2026-06-06" / "evening.md"
        write_raw_capture(
            evening_json,
            capture_time="2026-06-06T19:00:03-05:00",
            scanner="Institutional Momentum",
            session="evening",
            ticker="EVE",
        )
        evening_md.write_text("# Institutional evening capture\n", encoding="utf-8")
        register_legacy_raw_captures(captures_dir=self.captures_dir, manifest_path=self.manifest_path)
        mutate_raw_capture_to_base_momentum(evening_json, evening_md)
        write_analysis_rows(
            self.analysis_csv,
            [
                {"capture_date": "2026-06-06", "session": "morning", "scanner": "Institutional Momentum", "ticker": "COO", "price": "67.34"},
                {"capture_date": "2026-06-06", "session": "evening", "scanner": "Institutional Momentum", "ticker": "EVE", "price": "72.11"},
                {"capture_date": "2026-06-06", "session": "evening", "scanner": "Institutional Momentum", "ticker": "DRIFT", "price": "10.00"},
            ],
        )
        write_evening_review_decision(self.review_path)

        result = recover_modified_raw_captures(
            reason="Evening raw capture hash differed from manifest; quarantine before rebuild.",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            quarantine_root=self.quarantine_root,
            analysis_csv=self.analysis_csv,
            outcomes_csv=self.outcomes_csv,
            review_decisions_path=self.review_path,
            rebuild_outcomes=False,
            recovered_at=datetime(2026, 6, 6, 18, 0, 0, tzinfo=CENTRAL_TZ),
            before_audit_csv=self.root / "integrity" / "evening-before.csv",
            before_audit_report=self.root / "integrity" / "evening-before.md",
            after_audit_csv=self.root / "integrity" / "evening-after.csv",
            after_audit_report=self.root / "integrity" / "evening-after.md",
        )

        self.assertEqual(FAIL, result.before_status)
        self.assertEqual(WARN, result.after_status)
        self.assertEqual(1, result.rebuild_result.analysis_rows)
        self.assertEqual(0, result.rebuild_result.outcome_rows)
        self.assertFalse(evening_json.exists())
        self.assertFalse(evening_md.exists())
        quarantine_dir = result.quarantine_results[0].quarantine_dir
        self.assertTrue((quarantine_dir / "2026-06-06-evening.json").exists())
        self.assertTrue((quarantine_dir / "2026-06-06-evening.md").exists())

        rows = list(csv.DictReader(self.analysis_csv.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(["COO"], [row["ticker"] for row in rows])
        self.assertEqual(["morning"], [row["session"] for row in rows])
        decisions = json.loads(self.review_path.read_text(encoding="utf-8"))["decisions"]
        decision_payload = next(iter(decisions.values()))
        self.assertEqual("quarantined", decision_payload["capture_status"])


def write_raw_capture(path: Path, *, capture_time: str, scanner: str, session: str = "morning", ticker: str = "COO") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "capture_time": capture_time,
        "capture_date": "2026-06-06",
        "session": session,
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": scanner},
        "market": {"regime": "bull", "symbol": "SPY"},
        "candidates": [{"rank": 1, "ticker": ticker, "price": 67.34, "score": 90}],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def mutate_raw_capture_to_base_momentum(json_path: Path, md_path: Path) -> None:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["capture_time"] = "2026-06-06T07:00:35-05:00"
    payload["scanner"] = {"name": "Base Momentum"}
    payload["candidates"][0]["company"] = "Changed After Manifest"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text("# Base momentum overwrite\n", encoding="utf-8")


def write_review_decision(path: Path) -> None:
    identity = CandidateIdentity(
        capture_id=make_capture_id("2026-06-06", "morning", "finviz", "Institutional Momentum"),
        capture_date="2026-06-06",
        session="morning",
        provider="finviz",
        scanner="Institutional Momentum",
        ticker="COO",
    )
    save_review_decisions(
        {
            identity.key: ReviewDecision(
                identity=identity,
                review_status=ReviewStatus.WATCHLIST,
                decision_timestamp=datetime(2026, 6, 6, 8, 0, 0, tzinfo=CENTRAL_TZ),
                decision_note="Watch this one.",
            )
        },
        path=path,
    )


def write_evening_review_decision(path: Path) -> None:
    identity = CandidateIdentity(
        capture_id=make_capture_id("2026-06-06", "evening", "finviz", "Institutional Momentum"),
        capture_date="2026-06-06",
        session="evening",
        provider="finviz",
        scanner="Institutional Momentum",
        ticker="EVE",
    )
    save_review_decisions(
        {
            identity.key: ReviewDecision(
                identity=identity,
                review_status=ReviewStatus.WATCHLIST,
                decision_timestamp=datetime(2026, 6, 6, 20, 0, 0, tzinfo=CENTRAL_TZ),
                decision_note="Evening watch.",
            )
        },
        path=path,
    )


def write_analysis_csv(path: Path, *, scanner: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ANALYSIS_FIELDNAMES)
        writer.writeheader()
        row = {field: "" for field in ANALYSIS_FIELDNAMES}
        row.update({"capture_date": "2026-06-06", "session": "morning", "scanner": scanner, "ticker": "COO", "price": "67.34"})
        writer.writerow(row)


def write_analysis_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ANALYSIS_FIELDNAMES)
        writer.writeheader()
        for row_payload in rows:
            row = {field: "" for field in ANALYSIS_FIELDNAMES}
            row.update(row_payload)
            writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
