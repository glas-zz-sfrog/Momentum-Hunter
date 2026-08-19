from __future__ import annotations

import unittest
from pathlib import Path


class ContinuousDeploymentInstallerTests(unittest.TestCase):
    @staticmethod
    def _script() -> str:
        return (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "install_research_only_continuous_deployment.ps1"
        ).read_text(encoding="utf-8")

    def test_config_fingerprint_runs_from_repository_root(self):
        script = self._script()

        fingerprint_call = "& $plan.pythonExecutable -B -m momentum_hunter.continuous_production"
        call_index = script.index(fingerprint_call)
        push_index = script.rfind(
            "Push-Location -LiteralPath ([string]$plan.repositoryRoot)",
            0,
            call_index,
        )
        pop_index = script.index("Pop-Location", call_index)

        self.assertGreaterEqual(push_index, 0)
        self.assertLess(push_index, call_index)
        self.assertGreater(pop_index, call_index)

    def test_installer_does_not_assign_to_powershell_host_variable(self):
        script = self._script()

        self.assertNotIn("$host =", script.lower())
        self.assertNotIn("$home =", script.lower())

    def test_service_host_is_staged_then_installed_under_production_root(self):
        script = self._script()

        self.assertIn("serviceHostStagingRoot = $publish", script)
        self.assertIn(
            'serviceHostRoot = $hostInstallRoot',
            script,
        )
        self.assertIn(
            'Join-Path $ConfigRoot "continuous-service-host"',
            script,
        )
        self.assertIn(
            "Get-ChildItem -LiteralPath $serviceHostStagingRoot -Force | Copy-Item -Destination $serviceHostRoot",
            script,
        )
        self.assertIn(
            "Protect-ReadOnlyDirectory $serviceHostRoot",
            script,
        )

    def test_services_use_hash_addressed_programdata_python_source(self):
        script = self._script()

        self.assertIn(
            'runtimeSourceRoot = Assert-ProductionPath (Join-Path $ConfigRoot ("continuous-python-" + $identity.head))',
            script,
        )
        self.assertIn(
            "Copy-Item -Path $sourcePackage -Destination $runtimeSourceRoot -Recurse -Force",
            script,
        )
        self.assertIn("function Invoke-PythonRuntimeBuild", script)
        self.assertIn('Get-SystemPythonExecutable', script)
        self.assertIn('continuous_runtime_requirements.txt', script)
        self.assertIn('pythonRuntimeStagingRoot = $pythonRuntimeStagingRoot', script)
        self.assertIn('pythonRuntimeRoot = $pythonRuntimeRoot', script)
        self.assertIn('("continuous-python-runtime-" + $identity.head)', script)
        self.assertIn('pythonExecutable = Join-Path $pythonRuntimeRoot "Scripts\\python.exe"', script)
        self.assertIn("Protect-ReadOnlyDirectory $pythonRuntimeRoot", script)
        self.assertNotIn("Grant-PathTraverse", script)
        self.assertNotIn("Grant-ReadExecuteDirectory", script)
        self.assertNotIn('Join-Path $project ".venv\\Scripts\\python.exe"', script)
        self.assertIn(
            ' -f $serviceHostPath, $runtimeSourceRoot, $plan.pythonExecutable, $configPath',
            script,
        )

    def test_existing_runtime_service_accepts_reentered_windows_credential(self):
        script = self._script()

        self.assertIn(
            "Set-Service -Name $Name -Credential $Credential",
            script,
        )

    def test_credential_is_validated_before_service_or_file_mutation(self):
        script = self._script()

        validation = script.index(
            "Assert-WindowsCredential $credential ([string]$plan.runtimeAccount)"
        )
        automation_repair = script.index(
            'Set-Service -Name "MomentumHunterAutomation" -Credential $credential'
        )
        continuous_stop = script.index("Stop-ServiceIfRunning $writerServiceName")
        source_copy = script.index(
            "Copy-Item -Path $sourcePackage -Destination $runtimeSourceRoot"
        )
        runtime_install = script.index(
            'Install-ContinuousService $runtimeServiceName'
        )

        self.assertLess(validation, automation_repair)
        self.assertLess(validation, continuous_stop)
        self.assertLess(validation, source_copy)
        self.assertLess(validation, runtime_install)

    def test_recovery_reuses_one_credential_without_changing_automation_definition(self):
        script = self._script()

        self.assertIn("[switch]$RepairAutomationCredential", script)
        self.assertEqual(script.count("Get-Credential"), 1)
        self.assertIn(
            'Set-Service -Name "MomentumHunterAutomation" -Credential $credential',
            script,
        )
        self.assertIn(
            'existingAutomationCredentialRefreshed = [bool]$RepairAutomationCredential',
            script,
        )
        self.assertIn(
            'foreach ($field in @("name", "startMode", "startName", "pathName"))',
            script,
        )

    def test_existing_continuous_services_stop_before_host_replacement(self):
        script = self._script()

        writer_stop = script.index("Stop-ServiceIfRunning $writerServiceName")
        host_copy = script.index(
            "Get-ChildItem -LiteralPath $serviceHostStagingRoot -Force | Copy-Item -Destination $serviceHostRoot"
        )
        self.assertLess(writer_stop, host_copy)


if __name__ == "__main__":
    unittest.main()
