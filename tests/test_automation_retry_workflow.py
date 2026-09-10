import json
from pathlib import Path
import shutil
import subprocess
import unittest


class RetryWorkflowTests(unittest.TestCase):
    def test_exact_workflow_with_inert_adapters(self):
        source = Path(__file__).resolve().parents[1]
        pwsh = shutil.which("pwsh")
        self.assertIsNotNone(pwsh, "PowerShell Core is required; this is a Tier-1 workflow proof, not a skip.")
        result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-File",
            str(source / "tests/test_automation_retry_workflow.ps1"), "-Source", str(source)],
            capture_output=True, text=True, timeout=90)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        proof = json.loads(result.stdout)
        self.assertEqual("PASS", proof["status"])
        self.assertEqual(22, proof["cases"])
        self.assertEqual(0, proof["realScmOperations"])
        self.assertEqual(0, proof["realProviderCalls"])


if __name__ == "__main__":
    unittest.main()
