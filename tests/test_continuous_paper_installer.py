from __future__ import annotations

import unittest
from pathlib import Path


class ContinuousPaperInstallerTests(unittest.TestCase):
    @staticmethod
    def script() -> str:
        return (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "install_continuous_paper_canary.ps1"
        ).read_text(encoding="utf-8")

    @staticmethod
    def host() -> str:
        return (
            Path(__file__).resolve().parents[1]
            / "src"
            / "MomentumHunter.ContinuousServiceHost"
            / "ContinuousProcessWorker.cs"
        ).read_text(encoding="utf-8")

    def test_install_is_staged_and_starts_with_entry_authority_disabled(self):
        script = self.script()

        self.assertIn(
            '[ValidateSet("Prepare", "InstallDisabled", "Verify", "Preflight", "Arm")]',
            script,
        )
        self.assertIn('entryAuthority = "ENTRY_AUTHORITY_DISABLED"', script)
        self.assertIn('"InstallDisabled" { "CONTINUOUS_PAPER_INSTALLED_DISABLED" }', script)
        self.assertLess(
            script.index("Assert-WindowsCredential $credential"),
            script.index("Protect-PaperPath ([string]$plan.paperRoot)"),
        )

    def test_only_exact_paper_host_is_present(self):
        script = self.script()

        self.assertIn("https://paper-api.alpaca.markets", script)
        self.assertNotIn("https://api.alpaca.markets", script)
        self.assertIn('alpacaLive = "UNAVAILABLE"', script)
        self.assertIn('schwabOrders = "UNAVAILABLE"', script)
        self.assertIn('liveExecution = "UNAVAILABLE"', script)

    def test_local_password_is_not_passed_on_command_line(self):
        script = self.script()

        self.assertEqual(1, script.count("Get-Credential"))
        self.assertIn("StartPassword = $password", script)
        self.assertIn("ZeroFreeBSTR($pointer)", script)
        self.assertNotIn("sc.exe config $paperServiceName password=", script)

    def test_arm_is_separate_and_restarts_service_even_on_safe_refusal(self):
        script = self.script()

        arm = script[script.index('if ($Stage -eq "Arm")') :]
        self.assertIn("Stop-PaperService", arm)
        self.assertIn("ARM ONE CONTINUOUS ALPACA PAPER ENTRY", arm)
        self.assertIn("finally", arm)
        self.assertIn("Start-Service -Name $paperServiceName", arm)

    def test_installer_requires_exact_installed_product_and_research_authority(self):
        script = self.script()

        self.assertIn("researchConfig.installedProductSha", script)
        self.assertIn('researchConfig.mode -ne "RESEARCH_ONLY"', script)
        self.assertIn('researchConfig.orderCapability -ne "UNAVAILABLE"', script)
        self.assertIn("tradePlanProducer", script)

    def test_service_host_has_independent_paper_role(self):
        source = self.host()

        self.assertIn('role is not ("writer" or "runtime" or "paper")', source)
        self.assertIn('info.ArgumentList.Add("momentum_hunter.continuous_paper")', source)
        self.assertIn('"MomentumHunterContinuous{suffix}"', source)
        self.assertIn("MOMENTUM_HUNTER_CONTINUOUS_PAPER_MODE", source)


if __name__ == "__main__":
    unittest.main()
