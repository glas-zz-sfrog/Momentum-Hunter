from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from momentum_hunter.automation_paper_engineering import (
    INSTALL_CONFIRMATION,
    PaperAutomationInstallError,
    install_paper_engineering_job,
    plan_paper_engineering_job,
)


HEAD = "a" * 40


class PaperAutomationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.python = self.root / "python.exe"
        self.python.write_text("", encoding="utf-8")
        self.powershell = self.root / "powershell.exe"
        self.powershell.write_text("", encoding="utf-8")
        self.service = self.root / "service"
        self.service.mkdir()
        self.manifest = self.service / "automation-manifest.json"
        self.payload = {
            "schemaVersion": 1,
            "repositoryRoot": str(self.repo),
            "pythonExecutable": str(self.python),
            "powershellExecutable": str(self.powershell),
            "codexExecutable": "",
            "stateDirectory": str(self.service / "state"),
            "engineHostStateDirectory": str(self.service / "engine"),
            "pollIntervalSeconds": 1,
            "expectedAccountEnding": "2573",
            "expectedAccountType": "INDIVIDUAL_CASH",
            "jobs": [
                {
                    "jobId": "opening-capture-20260811",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-08-11T08:35:00-05:00",
                    "latestStartAt": "2026-08-11T08:40:00-05:00",
                    "enabled": True,
                    "timeoutSeconds": 900,
                    "expectedGitHead": HEAD,
                }
            ],
        }
        self.manifest.write_text(json.dumps(self.payload), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_binds_paper_job_to_same_date_opening_and_head(self) -> None:
        planned = plan_paper_engineering_job(
            self.payload,
            market_date=date(2026, 8, 11),
            expected_git_head=HEAD,
        )

        paper = next(item for item in planned["jobs"] if item["kind"] == "paper_engineering")
        self.assertEqual("opening-capture-20260811", paper["dependsOnJobId"])
        self.assertEqual(HEAD, paper["expectedGitHead"])
        self.assertEqual("2026-08-11T08:50:00-05:00", paper["latestStartAt"])
        self.assertEqual(25_200, paper["timeoutSeconds"])

    def test_install_is_atomic_and_preserves_write_once_backup(self) -> None:
        result = install_paper_engineering_job(
            manifest_path=self.manifest,
            market_date=date(2026, 8, 11),
            expected_git_head=HEAD,
            confirmation=INSTALL_CONFIRMATION,
        )

        self.assertEqual("ALPACA_PAPER_ENGINEERING_JOB_INSTALLED", result["classification"])
        self.assertTrue(Path(result["backupPath"]).is_file())
        installed = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(1, sum(item["kind"] == "paper_engineering" for item in installed["jobs"]))

    def test_running_job_blocks_manifest_mutation(self) -> None:
        state = self.service / "state" / "automation-service-state.json"
        state.parent.mkdir()
        state.write_text(
            json.dumps({"jobs": {"opening": {"status": "RUNNING"}}}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(PaperAutomationInstallError, "running"):
            install_paper_engineering_job(
                manifest_path=self.manifest,
                market_date=date(2026, 8, 11),
                expected_git_head=HEAD,
                confirmation=INSTALL_CONFIRMATION,
            )

    def test_wrong_head_and_missing_interlock_fail_closed(self) -> None:
        with self.assertRaisesRegex(PaperAutomationInstallError, "confirmation"):
            install_paper_engineering_job(
                manifest_path=self.manifest,
                market_date=date(2026, 8, 11),
                expected_git_head=HEAD,
                confirmation="yes",
            )
        with self.assertRaisesRegex(PaperAutomationInstallError, "Git identities"):
            plan_paper_engineering_job(
                self.payload,
                market_date=date(2026, 8, 11),
                expected_git_head="b" * 40,
            )


if __name__ == "__main__":
    unittest.main()
