from __future__ import annotations

import unittest
from pathlib import Path


class ContinuousDeploymentInstallerTests(unittest.TestCase):
    def test_config_fingerprint_runs_from_repository_root(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "install_research_only_continuous_deployment.ps1"
        ).read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
