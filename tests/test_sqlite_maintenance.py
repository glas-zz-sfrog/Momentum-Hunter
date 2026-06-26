from __future__ import annotations

import json
import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_maintenance import (
    build_sqlite_maintenance_report,
    main as sqlite_maintenance_main,
    write_sqlite_maintenance_report,
)
from momentum_hunter.storage import file_sha256
from tests.test_sqlite_validation import import_all_sources, write_validation_sources


class SQLiteMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-maintenance-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.backup_root = self.root / "backups" / "sqlite"
        self.reports_dir = self.root / "reports"
        self.sources = write_validation_sources(self.root)
        import_all_sources(self.db_path, self.sources)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_check_report_passes_and_does_not_mutate_source_database(self) -> None:
        before_hash = file_sha256(self.db_path)

        payload = build_sqlite_maintenance_report(db_path=self.db_path, backup_root=self.backup_root, mode="check")

        self.assertEqual("PASS", payload["overall_status"])
        self.assertEqual("ok", payload["integrity_check"])
        self.assertEqual(7, payload["sqlite_schema_version"])
        self.assertEqual(3, payload["table_counts"]["opportunity_alerts"])
        self.assertIn("opportunity_alerts", payload["latest_import_timestamps"])
        self.assertEqual(before_hash, file_sha256(self.db_path))

    def test_backup_creates_database_copy_manifest_and_validates_backup(self) -> None:
        before_hash = file_sha256(self.db_path)

        payload = build_sqlite_maintenance_report(db_path=self.db_path, backup_root=self.backup_root, mode="backup")

        self.assertEqual("PASS", payload["overall_status"])
        backup = payload["backup"]
        backup_path = Path(backup["backup_database_path"])
        manifest_path = Path(backup["manifest_path"])
        self.assertTrue(backup_path.exists())
        self.assertTrue(manifest_path.exists())
        self.assertEqual("PASS", backup["validation_status"])
        self.assertEqual("ok", backup["validation_integrity_check"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(before_hash, manifest["source_sha256"])
        self.assertEqual(file_sha256(backup_path), manifest["backup_sha256"])
        self.assertEqual(before_hash, file_sha256(self.db_path))

    def test_missing_database_is_reported_cleanly(self) -> None:
        missing = self.root / "missing.sqlite3"

        payload = build_sqlite_maintenance_report(db_path=missing, backup_root=self.backup_root, mode="check")

        self.assertEqual("FAIL", payload["overall_status"])
        self.assertFalse(payload["database_exists"])
        self.assertTrue(any(item.startswith("SQLITE_DATABASE_MISSING") for item in payload["errors"]))

    def test_report_writer_and_cli_generate_latest_outputs(self) -> None:
        payload = build_sqlite_maintenance_report(db_path=self.db_path, backup_root=self.backup_root, mode="check")
        json_path, markdown_path = write_sqlite_maintenance_report(payload, output_dir=self.reports_dir)

        self.assertTrue(json_path.exists())
        self.assertTrue(markdown_path.exists())
        self.assertIn("SQLite Maintenance Report", markdown_path.read_text(encoding="utf-8"))

        exit_code = sqlite_maintenance_main(
            [
                "--check",
                "--db",
                str(self.db_path),
                "--output-dir",
                str(self.reports_dir),
                "--backup-root",
                str(self.backup_root),
            ]
        )

        self.assertEqual(0, exit_code)
        self.assertTrue((self.reports_dir / "sqlite-maintenance-latest.json").exists())
        self.assertTrue((self.reports_dir / "sqlite-maintenance-latest.md").exists())


if __name__ == "__main__":
    unittest.main()
