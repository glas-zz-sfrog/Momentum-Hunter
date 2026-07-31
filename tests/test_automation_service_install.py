from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY_ROOT / "tools" / "install_automation_service.ps1"
HARDEN_CLOCK = (
    REPOSITORY_ROOT / "tools" / "harden_automation_clock_task.ps1"
)
ARCHIVE_REBOOT = (
    REPOSITORY_ROOT / "tools" / "archive_passed_automation_reboot_canary.ps1"
)
STATUS = REPOSITORY_ROOT / "tools" / "get_automation_service_status.ps1"
SET_JOBS = REPOSITORY_ROOT / "tools" / "set_automation_service_jobs.ps1"
PREPARE_REBOOT = (
    REPOSITORY_ROOT / "tools" / "prepare_automation_reboot_canary.ps1"
)
START_REBOOT = (
    REPOSITORY_ROOT / "tools" / "start_automation_reboot_canary.ps1"
)
VERIFY_REBOOT = (
    REPOSITORY_ROOT / "tools" / "verify_automation_reboot_canary.ps1"
)
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
            self.assertEqual("WINDOWS_TIME_RESYNC", plan["wakeTask"]["action"])
            self.assertEqual(
                ["AT_STARTUP", "DAILY_08_15"],
                plan["wakeTask"]["triggers"],
            )
            self.assertEqual(5, plan["wakeTask"]["restartCount"])
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

    def test_file_invocation_resolves_default_project_root(self) -> None:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(INSTALLER),
                "-PlanOnly",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(
            str(REPOSITORY_ROOT),
            plan["repositoryRoot"],
        )

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
        self.assertIn('"WINDOWS_TIME_RESYNC"', source)
        self.assertIn('"$env:SystemRoot\\System32\\w32tm.exe"', source)
        self.assertIn('"/resync /rediscover"', source)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", source)
        self.assertIn("-RestartCount 5", source)
        self.assertIn('"installation-codex-probe"', source)
        self.assertIn('"CODEX_SERVICE_READY"', source)
        self.assertIn(
            "Move-Item -LiteralPath $temporaryManifest "
            "-Destination $manifestPath -Force",
            source,
        )
        self.assertIn("[System.Text.UTF8Encoding]::new($false)", source)
        self.assertNotIn(
            "Set-Content -LiteralPath $temporaryManifest -Encoding utf8",
            source,
        )
        self.assertNotIn("AutoAdminLogon", source)
        self.assertIn("actions= restart/5000/restart/15000/restart/60000", source)
        self.assertNotIn("-Password", source)
        self.assertNotIn("LocalSystem", source)
        self.assertNotIn("ArmShadowSelector", source)

    def test_clock_hardener_is_bounded_and_plan_only_is_nonmutating(self) -> None:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(HARDEN_CLOCK),
                "-PlanOnly",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual("SYSTEM", plan["principal"])
        self.assertEqual(
            "w32tm.exe /resync /rediscover",
            plan["action"],
        )
        self.assertEqual(["AT_STARTUP", "DAILY_08_15"], plan["triggers"])
        self.assertEqual(5, plan["restartCount"])
        self.assertFalse(plan["startWhenAvailable"])
        self.assertFalse(plan["deletesTask"])
        self.assertEqual("UNAVAILABLE", plan["orderTransmission"])

        source = HARDEN_CLOCK.read_text(encoding="utf-8")
        self.assertIn("Set-ScheduledTask", source)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", source)
        self.assertIn("-WakeToRun", source)
        self.assertIn("-RestartCount 5", source)
        self.assertIn("Start-ScheduledTask", source)
        self.assertNotIn("Unregister-ScheduledTask", source)
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn("Restart-Computer", source)

    def test_reboot_archive_preserves_evidence_and_requires_verified_pass(
        self,
    ) -> None:
        source = ARCHIVE_REBOOT.read_text(encoding="utf-8")

        self.assertIn("verify_automation_reboot_canary.ps1", source)
        self.assertIn('classification -ne "PASS"', source)
        self.assertIn("Copy-Item", source)
        self.assertIn("Move-Item -LiteralPath $baselinePath", source)
        self.assertIn("Get-FileHash", source)
        self.assertIn("evidenceDeleted = $false", source)
        self.assertNotIn("Remove-Item", source)
        self.assertNotIn("Restart-Computer", source)
        self.assertNotIn("shutdown.exe", source)

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
        self.assertIn("PRESENT_REQUIRES_ELEVATION", source)
        self.assertIn("openingCaptureCoverageStatus", source)
        self.assertIn("pendingOpeningCaptureJobs", source)
        self.assertIn("failedOpeningCaptureJobs", source)

    def test_reboot_canary_scripts_preserve_nonmarket_boundary(self) -> None:
        prepare = PREPARE_REBOOT.read_text(encoding="utf-8")
        start = START_REBOOT.read_text(encoding="utf-8")
        verify = VERIFY_REBOOT.read_text(encoding="utf-8")

        self.assertIn("[switch]$PlanOnly", prepare)
        self.assertIn("requiresNoInteractiveLogin", prepare)
        self.assertIn("serviceRestarted = $false", prepare)
        self.assertIn('shadowJobsEnabled = 0', prepare)
        self.assertIn('orderTransmission = "UNAVAILABLE"', prepare)
        self.assertIn("[System.Text.UTF8Encoding]::new($false)", prepare)
        self.assertIn("[DateTimeOffset]$canaryLocal", prepare)
        self.assertIn('$canaryOffset.ToString("o")', prepare)
        self.assertIn("Push-Location -LiteralPath $projectPath", prepare)
        self.assertIn("Pop-Location", prepare)
        self.assertNotIn("Test-IsAdministrator", prepare)
        self.assertNotIn("requires an elevated PowerShell session", prepare)
        self.assertNotIn("Restart-Service", prepare)
        self.assertNotIn("Start-Service", prepare)
        self.assertNotIn("Restart-Computer", prepare)
        self.assertNotIn("shutdown.exe", prepare)
        self.assertNotIn("submit_order", prepare)
        self.assertNotIn("cancel_order", prepare)

        self.assertIn("[ValidateRange(5, 15)][int]$LeadMinutes = 5", start)
        self.assertIn('$ConfirmImmediateReboot -cne "REBOOT NOW"', start)
        self.assertIn("& $prepareScript @prepareArguments", start)
        self.assertIn('$canaryReceipt.status -eq "PENDING"', start)
        self.assertIn('$codexReceipt.status -eq "PENDING"', start)
        self.assertIn(
            "$pendingOpeningAfter.Count -ne $pendingOpeningBefore.Count",
            start,
        )
        self.assertIn(
            "@($baseline.preservedPendingOpeningJobs).Count -ne "
            "$pendingOpeningBefore.Count",
            start,
        )
        self.assertIn('$secondsRemaining -lt 180', start)
        self.assertIn('classification = "VERIFIED_REBOOT_REQUESTED"', start)
        self.assertIn('shutdown.exe" /r /t 0', start)
        self.assertEqual(1, start.count('shutdown.exe" /r /t 0'))
        self.assertIn('orderTransmission = "UNAVAILABLE"', start)
        self.assertNotIn("Restart-Service", start)
        self.assertNotIn("Start-Service", start)
        self.assertNotIn("submit_order", start)
        self.assertNotIn("cancel_order", start)

        for forbidden in (
            "Set-Content",
            "Move-Item",
            "Remove-Item",
            "Restart-Service",
            "Start-Service",
            "Restart-Computer",
            "shutdown.exe",
            "submit_order",
            "cancel_order",
        ):
            self.assertNotIn(forbidden, verify)
        self.assertIn("Push-Location -LiteralPath $projectPath", verify)
        self.assertIn("Pop-Location", verify)

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
        self.assertIn("[System.Text.UTF8Encoding]::new($false)", source)
        self.assertNotIn(
            "Set-Content -LiteralPath $temporaryManifest -Encoding utf8",
            source,
        )
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
