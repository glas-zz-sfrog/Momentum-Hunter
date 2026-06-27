from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.evidence_census import (
    build_candidate_data_completeness_report,
    build_evidence_census_report,
    write_candidate_completeness_report,
    write_evidence_census_report,
)
from momentum_hunter.sqlite_store import connect_database, initialize_schema
from tests.test_sqlite_analytics import seed_database


class EvidenceCensusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-evidence-census-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "census.sqlite3"
        with connect_database(self.db_path) as connection:
            initialize_schema(connection)
            seed_database(connection)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_evidence_census_counts_alerts_captures_and_user_state(self) -> None:
        payload = build_evidence_census_report(db_path=self.db_path)

        self.assertEqual("WARN", payload["overall_status"])
        self.assertEqual(1, payload["alerts"]["total_alerts"])
        self.assertEqual(1, payload["alerts"]["completed"])
        self.assertEqual(2, payload["captures"]["total_candidates"])
        self.assertEqual(1, payload["user_state"]["candidate_reviews"])
        self.assertIn("LOW_COMPLETED_ALERT_SAMPLE", payload["warnings"])

    def test_candidate_completeness_reports_missing_fields(self) -> None:
        payload = build_candidate_data_completeness_report(db_path=self.db_path)

        self.assertEqual(2, payload["candidate_rows"])
        fields = {item["field"]: item for item in payload["field_summary"]}
        self.assertEqual(0, fields["score"]["missing_count"])
        self.assertGreater(fields["relative_volume"]["missing_count"], 0)
        self.assertTrue(any(str(item).startswith("HIGH_MISSING_RATE:relative_volume") for item in payload["warnings"]))

    def test_reports_write_json_and_markdown(self) -> None:
        census = build_evidence_census_report(db_path=self.db_path)
        completeness = build_candidate_data_completeness_report(db_path=self.db_path)
        census_paths = write_evidence_census_report(
            census,
            json_path=self.root / "evidence-census-latest.json",
            markdown_path=self.root / "evidence-census-latest.md",
        )
        completeness_paths = write_candidate_completeness_report(
            completeness,
            json_path=self.root / "candidate-data-completeness-latest.json",
            markdown_path=self.root / "candidate-data-completeness-latest.md",
        )

        self.assertTrue(census_paths["json"].exists())
        self.assertTrue(census_paths["markdown"].exists())
        self.assertTrue(completeness_paths["json"].exists())
        self.assertTrue(completeness_paths["markdown"].exists())


if __name__ == "__main__":
    unittest.main()
