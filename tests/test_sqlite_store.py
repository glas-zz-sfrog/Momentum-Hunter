from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_migration import run_sqlite_migration
from momentum_hunter.sqlite_store import (
    connect_database,
    current_schema_version,
    import_provider_quality_report,
    initialize_schema,
    provider_quality_count,
    read_provider_quality_checks,
)
from momentum_hunter.storage import file_sha256


class SQLiteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.report_path = self.root / "data-quality-latest.json"
        write_data_quality_report(self.report_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_schema_initialization_creates_database_and_tracks_version_idempotently(self) -> None:
        self.assertFalse(self.db_path.exists())
        with connect_database(self.db_path) as connection:
            initialize_schema(connection)
            initialize_schema(connection)

            self.assertEqual(3, current_schema_version(connection))
            migration_count = connection.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()["count"]
            table_count = connection.execute(
                "SELECT COUNT(*) AS count FROM sqlite_master WHERE type = 'table' AND name = 'provider_quality_checks'"
            ).fetchone()["count"]

        self.assertTrue(self.db_path.exists())
        self.assertEqual(3, migration_count)
        self.assertEqual(1, table_count)

    def test_provider_quality_import_round_trips_without_mutating_source(self) -> None:
        before = file_sha256(self.report_path)
        result = import_provider_quality_report(self.report_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            rows = read_provider_quality_checks(connection)
            aaa = read_provider_quality_checks(connection, symbol="aaa")

        self.assertEqual(2, result.rows_seen)
        self.assertEqual(2, result.rows_inserted)
        self.assertEqual(0, result.rows_skipped)
        self.assertEqual(2, result.table_row_count)
        self.assertEqual(2, len(rows))
        self.assertEqual(1, len(aaa))
        self.assertEqual("AAA", aaa[0]["symbol"])
        self.assertEqual(1, aaa[0]["usable_market_tape"])
        self.assertEqual(before, file_sha256(self.report_path))

    def test_provider_quality_import_skips_duplicates(self) -> None:
        first = import_provider_quality_report(self.report_path, db_path=self.db_path)
        second = import_provider_quality_report(self.report_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            count = provider_quality_count(connection)

        self.assertEqual(2, first.rows_inserted)
        self.assertEqual(0, second.rows_inserted)
        self.assertEqual(2, second.rows_skipped)
        self.assertEqual(2, count)

    def test_sqlite_migration_cli_core_writes_import_report(self) -> None:
        report_json = self.root / "sqlite-import-latest.json"
        report_md = self.root / "sqlite-import-latest.md"

        payload = run_sqlite_migration(
            db_path=self.db_path,
            data_quality_report=self.report_path,
            report_json=report_json,
            report_md=report_md,
        )
        imported = payload["provider_quality_import"]

        self.assertEqual(3, payload["schema_version"])
        self.assertEqual(2, imported["rows_seen"])
        self.assertEqual(2, imported["rows_inserted"])
        self.assertTrue(report_json.exists())
        self.assertTrue(report_md.exists())

    def test_init_only_does_not_require_data_quality_report(self) -> None:
        payload = run_sqlite_migration(
            db_path=self.db_path,
            data_quality_report=self.root / "missing.json",
            import_provider_quality=False,
            report_json=self.root / "init-only.json",
            report_md=self.root / "init-only.md",
        )

        self.assertEqual(3, payload["schema_version"])
        self.assertIsNone(payload["provider_quality_import"])
        with connect_database(self.db_path) as connection:
            self.assertEqual(0, provider_quality_count(connection))


def write_data_quality_report(path: Path) -> None:
    payload = {
        "schema_version": 1,
        "engine_version": "data_quality_audit_v1",
        "report": {
            "generated_at": "2026-06-25T15:00:00-05:00",
            "symbols": ["AAA", "BBB"],
            "symbol_rows": [
                {
                    "symbol": "AAA",
                    "usable_market_tape": True,
                    "best_provider": "combined",
                    "fields_returned": ["last_price", "bid", "ask"],
                    "missing_fields": ["relative_volume"],
                    "provider_errors": [],
                    "last_price": 10.5,
                    "bid": 10.49,
                    "ask": 10.51,
                    "spread_percent": 0.19,
                    "relative_volume": None,
                    "warnings": ["MARKET_TAPE_TIMESTAMP_UNAVAILABLE"],
                },
                {
                    "symbol": "BBB",
                    "usable_market_tape": False,
                    "best_provider": "",
                    "fields_returned": [],
                    "missing_fields": ["last_price", "bid", "ask"],
                    "provider_errors": ["QUOTE_FETCH_FAILED"],
                    "last_price": None,
                    "bid": None,
                    "ask": None,
                    "spread_percent": None,
                    "relative_volume": None,
                    "warnings": ["NO_USABLE_COMBINED_TAPE"],
                },
            ],
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
