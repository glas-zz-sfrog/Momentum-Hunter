from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.storage import file_sha256
from momentum_hunter.user_state_safety import build_user_state_backup, validate_user_state_backup_restore


class UserStateSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-user-state-safety-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(
            self.root / "review-decisions.json",
            {
                "schema_version": 1,
                "decisions": {
                    "cap|2026-06-25|morning|finviz|Base Momentum|AAA": {
                        "identity": {
                            "capture_id": "cap",
                            "capture_date": "2026-06-25",
                            "session": "morning",
                            "provider": "finviz",
                            "scanner": "Base Momentum",
                            "ticker": "AAA",
                        },
                        "review_status": "watchlist",
                        "decision_timestamp": "2026-06-25T09:00:00-05:00",
                        "decision_note": "watch breakout",
                    }
                },
            },
        )
        write_json(
            self.root / "entry-plans.json",
            {
                "schema_version": 1,
                "plans": {
                    "cap|2026-06-25|morning|finviz|Base Momentum|AAA": {
                        "identity": {
                            "capture_id": "cap",
                            "capture_date": "2026-06-25",
                            "session": "morning",
                            "provider": "finviz",
                            "scanner": "Base Momentum",
                            "ticker": "AAA",
                        },
                        "trigger": "above 10",
                        "stop": "9.50",
                        "invalidation": "loses 9.50",
                        "max_loss": "$20",
                        "plan_complete": True,
                        "updated_at": "2026-06-25T09:05:00-05:00",
                    }
                },
            },
        )
        write_json(self.root / "watchlist-2026-06-25.json", [{"ticker": "AAA", "score": 91, "price": 10.0}])
        self.backup_root = self.root / "backups"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_backup_manifest_preserves_hashes_and_does_not_mutate_sources(self) -> None:
        review_path = self.root / "review-decisions.json"
        before_hash = file_sha256(review_path)

        payload = build_user_state_backup(
            data_dir=self.root,
            backup_root=self.backup_root,
            generated_at="2026-06-25T10:00:00-05:00",
            sqlite_schema_version=6,
        )

        self.assertEqual(before_hash, file_sha256(review_path))
        self.assertEqual(3, payload["summary"]["files_included"])
        self.assertTrue((Path(payload["backup_dir"]) / "manifest.json").exists())
        review_record = next(item for item in payload["files"] if item["category"] == "candidate_reviews")
        self.assertEqual(before_hash, review_record["sha256"])
        self.assertTrue((Path(payload["backup_dir"]) / review_record["backup_relative_path"]).exists())

    def test_restore_validation_restores_to_temp_directory_and_verifies_hashes(self) -> None:
        backup = build_user_state_backup(
            data_dir=self.root,
            backup_root=self.backup_root,
            generated_at="2026-06-25T10:00:00-05:00",
        )
        validation_dir = self.root / "restore-validation"

        payload = validate_user_state_backup_restore(Path(backup["backup_dir"]), validation_dir=validation_dir)

        self.assertEqual("PASS", payload["overall_status"])
        self.assertGreaterEqual(payload["files_restored"], 3)
        self.assertTrue((validation_dir / "data" / "review-decisions.json").exists())
        self.assertEqual(file_sha256(self.root / "review-decisions.json"), file_sha256(validation_dir / "data" / "review-decisions.json"))

    def test_missing_required_file_is_reported_without_crashing(self) -> None:
        (self.root / "review-decisions.json").unlink()

        payload = build_user_state_backup(
            data_dir=self.root,
            backup_root=self.backup_root,
            generated_at="2026-06-25T10:00:00-05:00",
        )

        self.assertIn("REQUIRED_USER_STATE_FILE_MISSING", " ".join(payload["warnings"]))
        missing_review = next(item for item in payload["files"] if item["category"] == "candidate_reviews")
        self.assertFalse(missing_review["exists"])


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
