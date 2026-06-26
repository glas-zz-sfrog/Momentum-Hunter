from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_migration import run_sqlite_migration
from momentum_hunter.sqlite_store import (
    connect_database,
    import_system_status_events,
    read_system_status_events,
    system_status_event_count,
)
from momentum_hunter.storage import file_sha256


class SQLiteSystemStatusStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-system-status-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_system_readiness_import_creates_overall_and_section_events(self) -> None:
        source = self.root / "system-readiness-latest.json"
        write_json(
            source,
            {
                "schema_version": 1,
                "engine_version": "system_readiness_v1",
                "report": {
                    "generated_at": "2026-06-25T12:00:00-05:00",
                    "overall_status": "WARNING",
                    "issues_requiring_attention": ["market tape missing"],
                    "sections": [
                        {
                            "name": "Market Tape",
                            "status": "FAILED",
                            "explanation": "No usable market tape.",
                            "recommended_next_action": "Repair provider access.",
                        },
                        {
                            "name": "Evidence",
                            "status": "READY",
                            "explanation": "Evidence files are present.",
                            "recommended_next_action": "Continue collecting.",
                        },
                    ],
                },
            },
        )
        before = file_sha256(source)

        result = import_system_status_events(db_path=self.db_path, source_paths=[source])

        with connect_database(self.db_path) as connection:
            rows = read_system_status_events(connection)
            failed = read_system_status_events(connection, status="failed")

        self.assertEqual(3, result.events_seen)
        self.assertEqual(3, result.events_inserted)
        self.assertEqual(0, result.events_updated)
        self.assertEqual(0, result.events_skipped)
        self.assertEqual({"FAILED": 1, "READY": 1, "WARNING": 1}, result.status_counts)
        self.assertEqual(3, len(rows))
        self.assertEqual(1, len(failed))
        self.assertEqual("system_readiness:market_tape", failed[0]["event_type"])
        self.assertEqual("Repair provider access.", failed[0]["recommended_action"])
        self.assertEqual(before, file_sha256(source))

    def test_system_status_import_is_idempotent(self) -> None:
        source = self.root / "active-monitor-status.json"
        write_json(
            source,
            {
                "state": "RUNNING",
                "updated_at": "2026-06-25T12:01:00-05:00",
                "target_count": 5,
                "warnings": [],
            },
        )

        first = import_system_status_events(db_path=self.db_path, source_paths=[source])
        second = import_system_status_events(db_path=self.db_path, source_paths=[source])

        with connect_database(self.db_path) as connection:
            rows = read_system_status_events(connection)

        self.assertEqual(1, first.events_inserted)
        self.assertEqual(0, second.events_inserted)
        self.assertEqual(1, second.events_skipped)
        self.assertEqual(1, len(rows))
        self.assertEqual("INFO", rows[0]["status"])

    def test_data_quality_status_marks_missing_tape_as_warning(self) -> None:
        source = self.root / "data-quality-latest.json"
        write_json(
            source,
            {
                "schema_version": 1,
                "engine_version": "data_quality_audit_v1",
                "report": {
                    "generated_at": "2026-06-25T12:02:00-05:00",
                    "symbols": ["AAA", "BBB"],
                    "usable_market_tape_count": 1,
                    "missing_market_tape_count": 1,
                    "warnings": [],
                },
            },
        )

        result = import_system_status_events(db_path=self.db_path, source_paths=[source])

        with connect_database(self.db_path) as connection:
            rows = read_system_status_events(connection, event_type="data_quality:market_tape")

        self.assertEqual(1, result.events_inserted)
        self.assertEqual("WARNING", rows[0]["status"])
        self.assertIn("1 usable, 1 missing", rows[0]["summary"])

    def test_market_tape_status_marks_full_provider_success_ready(self) -> None:
        source = self.root / "market-tape-health-20260625T120300-0500.json"
        write_json(
            source,
            {
                "schema_version": 1,
                "engine_version": "market_tape_health_v1",
                "report": {
                    "generated_at": "2026-06-25T12:03:00-05:00",
                    "symbols": ["AAA", "BBB"],
                    "usable_symbol_count": 2,
                    "missing_symbol_count": 0,
                    "warnings": [],
                },
            },
        )

        result = import_system_status_events(db_path=self.db_path, source_paths=[source])

        with connect_database(self.db_path) as connection:
            rows = read_system_status_events(connection, event_type="market_tape_health")

        self.assertEqual(1, result.events_inserted)
        self.assertEqual("READY", rows[0]["status"])
        self.assertIn("2 usable, 0 missing", rows[0]["summary"])

    def test_sqlite_migration_writes_system_status_report(self) -> None:
        reports_dir = self.root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            reports_dir / "system-readiness-latest.json",
            {
                "engine_version": "system_readiness_v1",
                "report": {
                    "generated_at": "2026-06-25T12:04:00-05:00",
                    "overall_status": "READY",
                    "sections": [],
                    "issues_requiring_attention": [],
                },
            },
        )
        payload = run_sqlite_migration(
            db_path=self.db_path,
            system_status_source_paths=[reports_dir / "system-readiness-latest.json"],
            import_provider_quality=False,
            import_system_status_slice=True,
            system_status_report_json=self.root / "sqlite-system-status-import-latest.json",
            system_status_report_md=self.root / "sqlite-system-status-import-latest.md",
        )

        self.assertEqual(7, payload["schema_version"])
        self.assertIsNotNone(payload["system_status_import"])
        self.assertTrue((self.root / "sqlite-system-status-import-latest.json").exists())
        self.assertTrue((self.root / "sqlite-system-status-import-latest.md").exists())

    def test_missing_source_is_warned_without_creating_events(self) -> None:
        result = import_system_status_events(db_path=self.db_path, source_paths=[self.root / "missing.json"])

        with connect_database(self.db_path) as connection:
            count = system_status_event_count(connection)

        self.assertEqual(0, result.events_seen)
        self.assertEqual(0, result.events_inserted)
        self.assertEqual(0, count)
        self.assertTrue(any("SYSTEM_STATUS_SOURCE_MISSING" in warning for warning in result.warnings))


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
