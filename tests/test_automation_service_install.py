from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY_ROOT / "tools" / "install_automation_service.ps1"
STATUS = REPOSITORY_ROOT / "tools" / "get_automation_service_status.ps1"
SET_JOBS = REPOSITORY_ROOT / "tools" / "set_automation_service_jobs.ps1"
EXAMPLE = REPOSITORY_ROOT / "config" / "automation-service.example.json"


class AutomationServiceInstallTests(unittest.TestCase):
    def test_plan_only_is_nonmutating_and_market_jobs_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service_root = Path(temporary) / "service-root"
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(INSTALLER),
                    "-ProjectRoot",
                    str(REPOSITORY_ROOT),
                    "-PythonExe",
                    sys.executable,
                    "-ServiceRoot",
                    str(service_root),
                    "-PlanOnly",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual("Automatic", plan["startupType"])
            self.assertEqual(0, plan["shadowJobsEnabled"])
            self.assertEqual("UNAVAILABLE", plan["orderTransmission"])
            self.assertEqual("SYSTEM", plan["wakeTask"]["principal"])
            self.assertTrue(plan["wakeTask"]["wakeToRun"])
            self.assertFalse(plan["wakeTask"]["interactiveLogon"])
            self.assertEqual("NO_OP_WAKE_ONLY", plan["wakeTask"]["action"])
            initial_kinds = [job["kind"] for job in plan["initialJobs"]]
            self.assertEqual("nonmarket_canary", initial_kinds[0])
            if plan["codexHeadlessConfigured"]:
                self.assertEqual(
                    ["nonmarket_canary", "codex_review"],
                    initial_kinds,
                )
                codex_probe = plan["initialJobs"][1]
                self.assertEqual(
                    "installation-canary",
                    codex_probe["dependsOnJobId"],
                )
                self.assertEqual(
                    "CODEX_SERVICE_READY",
                    codex_probe["expectedOutput"],
                )
            else:
                self.assertEqual(["nonmarket_canary"], initial_kinds)
            self.assertFalse(service_root.exists())

    def test_installer_uses_local_secure_credential_and_recovery(self) -> None:
        source = INSTALLER.read_text(encoding="utf-8")

        self.assertIn("Get-Credential", source)
        self.assertIn("New-Service", source)
        self.assertIn("-Credential $credential", source)
        self.assertIn("-LoadUserProfile", source)
        self.assertIn("Grant-LogOnAsService", source)
        self.assertIn("@openai\\codex-win32-x64", source)
        self.assertIn("-StartupType Automatic", source)
        self.assertIn("-WakeToRun", source)
        self.assertIn('-UserId "SYSTEM"', source)
        self.assertIn('"NO_OP_WAKE_ONLY"', source)
        self.assertIn('"installation-codex-probe"', source)
        self.assertIn('"CODEX_SERVICE_READY"', source)
        self.assertIn(
            "Move-Item -LiteralPath $temporaryManifest "
            "-Destination $manifestPath -Force",
            source,
        )
        self.assertNotIn("AutoAdminLogon", source)
        self.assertIn("actions= restart/5000/restart/15000/restart/60000", source)
        self.assertNotIn("-Password", source)
        self.assertNotIn("LocalSystem", source)
        self.assertNotIn("ArmShadowSelector", source)

    def test_status_script_is_read_only(self) -> None:
        source = STATUS.read_text(encoding="utf-8")

        for forbidden in (
            "New-Service",
            "Start-Service",
            "Stop-Service",
            "Restart-Service",
            "Remove-Service",
            "Set-Content",
            "Move-Item",
            "Remove-Item",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn('orderTransmission = "UNAVAILABLE"', source)

    def test_market_manifest_update_has_hard_interlocks(self) -> None:
        source = SET_JOBS.read_text(encoding="utf-8")

        self.assertIn("[switch]$EnableShadowOpening", source)
        self.assertIn("exact -EnableShadowOpening interlock", source)
        self.assertIn('ToString("HH:mm:ss") -ne "08:35:00"', source)
        self.assertIn('Id -ne "Central Standard Time"', source)
        self.assertIn('latestStartAt = $ShadowRunAt.AddSeconds(5)', source)
        self.assertIn("Current Git HEAD does not match", source)
        self.assertIn("repository must be clean", source)
        self.assertIn("Restart-Service", source)
        self.assertIn('orderTransmission = "UNAVAILABLE"', source)
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)

    def test_example_manifest_is_disabled_and_has_no_shadow_job(self) -> None:
        payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))

        self.assertEqual(1, payload["schemaVersion"])
        self.assertRegex(payload["expectedAccountEnding"], r"^\d{4}$")
        self.assertEqual(
            "INDIVIDUAL_CASH",
            payload["expectedAccountType"],
        )
        self.assertTrue(payload["jobs"])
        self.assertTrue(all(not job["enabled"] for job in payload["jobs"]))
        self.assertNotIn(
            "shadow_opening",
            {job["kind"] for job in payload["jobs"]},
        )


if __name__ == "__main__":
    unittest.main()
