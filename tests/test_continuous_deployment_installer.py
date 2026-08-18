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
        self.assertIn(
            "Grant-ReadExecuteDirectory $pythonEnvironmentRoot $writerAccount",
            script,
        )
        self.assertIn(
            ' -f $serviceHostPath, $runtimeSourceRoot, $plan.pythonExecutable, $configPath',
            script,
        )


if __name__ == "__main__":
    unittest.main()
