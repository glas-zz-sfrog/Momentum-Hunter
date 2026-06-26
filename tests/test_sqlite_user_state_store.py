from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_store import connect_database, current_schema_version, import_user_state
from momentum_hunter.storage import file_sha256


class SQLiteUserStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-user-state-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.review_path = self.root / "review-decisions.json"
        self.entry_path = self.root / "entry-plans.json"
        write_user_state_fixture(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_user_state_import_round_trip_and_schema_version(self) -> None:
        result = import_user_state(
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
            db_path=self.db_path,
        )

        self.assertEqual(2, result.review_records_seen)
        self.assertEqual(1, result.watchlist_files_seen)
        self.assertEqual(1, result.watchlist_records_seen)
        self.assertEqual(2, result.entry_plan_records_seen)
        self.assertEqual(1, result.complete_entry_plans)
        self.assertEqual(1, result.incomplete_entry_plans)
        with connect_database(self.db_path) as connection:
            self.assertEqual(7, current_schema_version(connection))
            review = connection.execute("SELECT * FROM candidate_reviews WHERE ticker = 'AAA'").fetchone()
            watchlist = connection.execute("SELECT * FROM watchlist_items WHERE ticker = 'AAA'").fetchone()
            complete_plan = connection.execute("SELECT * FROM entry_plans WHERE ticker = 'AAA'").fetchone()
            incomplete_plan = connection.execute("SELECT * FROM entry_plans WHERE ticker = 'BBB'").fetchone()
        self.assertEqual("watchlist", review["review_status"])
        self.assertEqual("2026-06-25", watchlist["watchlist_date"])
        self.assertEqual(1, complete_plan["plan_complete"])
        self.assertEqual(0, incomplete_plan["plan_complete"])
        self.assertIn("missing trigger", incomplete_plan["warnings_json"])

    def test_user_state_import_is_idempotent(self) -> None:
        first = import_user_state(
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
            db_path=self.db_path,
        )
        second = import_user_state(
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
            db_path=self.db_path,
        )

        self.assertGreater(first.review_records_inserted, 0)
        self.assertEqual(2, second.review_records_skipped)
        self.assertEqual(1, second.watchlist_records_skipped)
        self.assertEqual(2, second.entry_plan_records_skipped)

    def test_malformed_records_warn_and_source_files_are_not_mutated(self) -> None:
        review_hash = file_sha256(self.review_path)
        payload = json.loads(self.review_path.read_text(encoding="utf-8"))
        payload["decisions"]["bad"] = {"review_status": "interested"}
        self.review_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        before_hash = file_sha256(self.review_path)

        result = import_user_state(
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
            db_path=self.db_path,
        )

        self.assertNotEqual(review_hash, before_hash)
        self.assertEqual(before_hash, file_sha256(self.review_path))
        self.assertIn("MALFORMED_REVIEW_RECORD", " ".join(result.warnings))
        self.assertEqual(2, result.review_records_seen)

    def test_duplicate_identity_is_warned_and_not_duplicated(self) -> None:
        payload = json.loads(self.review_path.read_text(encoding="utf-8"))
        payload["decisions"]["duplicate"] = dict(payload["decisions"]["a"])
        self.review_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        result = import_user_state(
            review_decisions_path=self.review_path,
            entry_plans_path=self.entry_path,
            data_dir=self.root,
            db_path=self.db_path,
        )

        with connect_database(self.db_path) as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM candidate_reviews").fetchone()["count"]

        self.assertEqual(2, result.review_records_seen)
        self.assertEqual(2, count)
        self.assertIn("DUPLICATE_REVIEW_IDENTITY", " ".join(result.warnings))


def write_user_state_fixture(root: Path) -> None:
    identity_a = {
        "capture_id": "2026-06-25|morning|finviz|Base Momentum",
        "capture_date": "2026-06-25",
        "session": "morning",
        "provider": "finviz",
        "scanner": "Base Momentum",
        "ticker": "AAA",
    }
    identity_b = dict(identity_a, ticker="BBB")
    write_json(
        root / "review-decisions.json",
        {
            "schema_version": 1,
            "decisions": {
                "a": {
                    "identity": identity_a,
                    "review_status": "watchlist",
                    "decision_timestamp": "2026-06-25T09:00:00-05:00",
                    "decision_note": "watch breakout",
                },
                "b": {
                    "identity": identity_b,
                    "review_status": "rejected",
                    "decision_timestamp": "2026-06-25T09:05:00-05:00",
                    "decision_note": "spread too wide",
                },
            },
        },
    )
    write_json(
        root / "entry-plans.json",
        {
            "schema_version": 1,
            "plans": {
                "a": {
                    "identity": identity_a,
                    "trigger": "above 10",
                    "stop": "9.50",
                    "thesis": "continuation",
                    "invalidation": "loses 9.50",
                    "max_loss": "$20",
                    "position_size": "$100",
                    "planned_hold_time": "1 day",
                    "notes": "tight plan",
                    "plan_complete": True,
                    "updated_at": "2026-06-25T09:10:00-05:00",
                },
                "b": {
                    "identity": identity_b,
                    "trigger": "",
                    "stop": "",
                    "invalidation": "",
                    "max_loss": "",
                    "plan_complete": False,
                    "updated_at": "2026-06-25T09:15:00-05:00",
                },
            },
        },
    )
    write_json(root / "watchlist-2026-06-25.json", [{"ticker": "AAA", "company": "AAA Co", "score": 91, "price": 10.0}])


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
