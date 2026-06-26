from __future__ import annotations

import shutil
import unittest
import uuid
import gc
import time
from pathlib import Path

from momentum_hunter.offline_evidence_drill import run_offline_evidence_drill
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH, load_alerts
from momentum_hunter.storage import file_sha256


class OfflineEvidenceDrillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-offline-drill-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.output_dir = self.root / "reports"
        self.production_hash = file_sha256(OPPORTUNITY_ALERTS_PATH) if OPPORTUNITY_ALERTS_PATH.exists() else ""
        self.production_alert_count = len(load_alerts(OPPORTUNITY_ALERTS_PATH)) if OPPORTUNITY_ALERTS_PATH.exists() else 0

    def tearDown(self) -> None:
        for _attempt in range(20):
            gc.collect()
            shutil.rmtree(self.root, ignore_errors=True)
            if not self.root.exists():
                return
            time.sleep(0.1)

    def test_drill_completes_fixture_alert_without_mutating_production_alerts(self) -> None:
        payload = run_offline_evidence_drill(
            output_dir=self.output_dir,
            workspace_root=self.root / "workspace",
            cleanup_workspace=False,
        )

        self.assertEqual("PASS", payload["overall_status"])
        self.assertEqual(1, payload["alerts_processed"])
        self.assertEqual(1, payload["outcomes_completed"])
        self.assertEqual("PASS", payload["sqlite_validation_status"])
        self.assertFalse(payload["production_alert_store_mutated"])
        self.assertEqual(self.production_hash, file_sha256(OPPORTUNITY_ALERTS_PATH) if OPPORTUNITY_ALERTS_PATH.exists() else "")
        self.assertEqual(self.production_alert_count, len(load_alerts(OPPORTUNITY_ALERTS_PATH)) if OPPORTUNITY_ALERTS_PATH.exists() else 0)
        self.assertTrue((self.output_dir / "offline-evidence-drill-latest.json").exists())
        self.assertTrue((self.output_dir / "offline-evidence-drill-latest.md").exists())

    def test_missing_bars_path_reports_warning_instead_of_polluting_production(self) -> None:
        payload = run_offline_evidence_drill(
            output_dir=self.output_dir,
            workspace_root=self.root / "missing-bars-workspace",
            cleanup_workspace=False,
            simulate_missing_bars=True,
        )

        self.assertEqual("WARN", payload["overall_status"])
        self.assertEqual(1, payload["alerts_processed"])
        self.assertEqual(0, payload["outcomes_completed"])
        self.assertEqual(1, payload["outcomes_pending"])
        self.assertIn("DRILL_NO_COMPLETED_OUTCOME", payload["warnings"])
        self.assertFalse(payload["production_alert_store_mutated"])

    def test_cleanup_workspace_removes_named_temporary_fixture_directory(self) -> None:
        workspace = self.root / "_offline-evidence-drill-fixture"

        payload = run_offline_evidence_drill(
            output_dir=self.output_dir,
            workspace_root=workspace,
            cleanup_workspace=True,
        )

        self.assertEqual("PASS", payload["overall_status"])
        self.assertFalse(workspace.exists())


if __name__ == "__main__":
    unittest.main()
