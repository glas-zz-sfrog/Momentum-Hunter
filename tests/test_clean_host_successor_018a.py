"""Source-selection controls; behavioral admission is covered by the owner suites."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "src" / "MomentumHunter.ContinuousServiceHost"


class CleanSuccessorTests(unittest.TestCase):
    def test_retired_child_launch_model_is_absent(self):
        for name in ("WindowsScienceProcess.cs", "WindowsScienceToken.cs", "WindowsScienceTokenContract.cs"):
            self.assertFalse((HOST / name).exists(), name)
        worker = (HOST / "ContinuousProcessWorker.cs").read_text(encoding="utf-8")
        self.assertNotIn("WindowsScienceProcess", worker)
        self.assertIn("Science requires the direct SCM service host", worker)
        program = (HOST / "Program.cs").read_text(encoding="utf-8")
        self.assertIn("AddHostedService<DirectScienceService>", program)

    def test_successor_owner_not_retired_task(self):
        source = (HOST / "ScienceQualificationTargets.cs").read_text(encoding="utf-8")
        self.assertIn('TaskId = "ARGUS-013B-CLEAN-SUCCESSOR-018A"', source)
        self.assertNotIn("SECURE-BEFORE-ACTIVATE-SERVICE-RECREATION-015", source)

    def test_host_modules_do_not_depend_on_retired_physical_paths(self):
        files = list(HOST.glob("*.cs")) + list((ROOT / "momentum_hunter").glob("continuous_host_*.py"))
        for file in files:
            text = file.read_text(encoding="utf-8")
            for retired in ("017F01", "20260917-017F", "archived-instance"):
                self.assertNotIn(retired, text, str(file))

    def test_validator_uses_durable_runner_not_linked_ambiguous_timeout(self):
        text = (HOST / "ContinuousProcessWorker.cs").read_text(encoding="utf-8")
        method = text.split("private async Task ValidateQualificationAsync", 1)[1].split("public override", 1)[0]
        self.assertIn("QualificationValidator.RunAsync", method)
        self.assertNotIn("CreateLinkedTokenSource", method)
        self.assertNotIn("ReadToEndAsync", method)
