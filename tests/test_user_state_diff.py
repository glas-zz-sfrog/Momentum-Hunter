from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_store import connect_database, import_user_state
from momentum_hunter.user_state_diff import build_user_state_diff_report, write_user_state_diff_report
from tests.test_sqlite_user_state_store import write_user_state_fixture


class UserStateDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-user-state-diff-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.review_path = self.root / "review-decisions.json"
        self.entry_path = self.root / "entry-plans.json"
        write_user_state_fixture(self.root)
        import_user_state(
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
            db_path=self.db_path,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_diff_report_passes_when_files_match_sqlite_mirror(self) -> None:
        payload = build_user_state_diff_report(
            db_path=self.db_path,
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
        )
        write_user_state_diff_report(
            payload,
            json_path=self.root / "sqlite-user-state-diff-latest.json",
            markdown_path=self.root / "sqlite-user-state-diff-latest.md",
        )

        self.assertEqual("PASS", payload["overall_status"])
        self.assertEqual(5, payload["records_in_files"])
        self.assertEqual(5, payload["records_in_sqlite"])
        self.assertEqual(0, payload["missing_in_sqlite"])
        self.assertEqual(0, payload["changed_values"])
        self.assertTrue((self.root / "sqlite-user-state-diff-latest.json").exists())

    def test_diff_report_detects_missing_sqlite_row(self) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute("DELETE FROM candidate_reviews WHERE ticker = 'AAA'")
            connection.commit()

        payload = build_user_state_diff_report(
            db_path=self.db_path,
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
        )

        self.assertEqual("WARN", payload["overall_status"])
        self.assertEqual(1, payload["missing_in_sqlite"])
        self.assertEqual(1, payload["tables"]["candidate_reviews"]["missing_in_sqlite_count"])

    def test_diff_report_detects_changed_sqlite_value(self) -> None:
        with connect_database(self.db_path) as connection:
            connection.execute("UPDATE entry_plans SET max_loss = '$999' WHERE ticker = 'AAA'")
            connection.commit()

        payload = build_user_state_diff_report(
            db_path=self.db_path,
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
        )
        changed = payload["tables"]["entry_plans"]["changed_values"]

        self.assertEqual("WARN", payload["overall_status"])
        self.assertEqual(1, payload["changed_values"])
        self.assertEqual("max_loss", changed[0]["fields"][0]["field"])


if __name__ == "__main__":
    unittest.main()

