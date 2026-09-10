import json
from pathlib import Path
import shutil
import subprocess
import unittest


class RetryWorkflowTests(unittest.TestCase):
    def test_json_timestamp_identity_survives_utc_and_offset_roundtrip(self):
        source = Path(__file__).resolve().parents[1]
        pwsh = shutil.which("pwsh")
        self.assertIsNotNone(pwsh)
        module = str(source / "tools/automation_retry_workflow.psm1").replace("'", "''")
        raw = json.dumps({"cutoff": "2026-09-10T12:45:00Z", "scheduled": "2026-09-10T08:35:00-05:00",
                          "heartbeat": "2026-09-10T05:03:42.123456+00:00"})
        script = (f"Import-Module '{module}'; $p=ConvertFrom-MHRetryJson '{raw}'; "
            "$result=@{cutoff=$p.cutoff;scheduled=$p.scheduled;heartbeat=$p.heartbeat;"
            "stringTypes=($p.cutoff -is [string] -and $p.scheduled -is [string] -and $p.heartbeat -is [string]);"
            "validCutoff=([DateTimeOffset]::Parse($p.cutoff) -lt [DateTimeOffset]::Parse($p.scheduled));"
            "utc=[DateTimeOffset]::Parse($p.scheduled).UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ssZ')};$result|ConvertTo-Json")
        result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=15)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        actual = json.loads(result.stdout)
        for key, value in json.loads(raw).items():
            self.assertEqual(value, actual[key])
        self.assertTrue(actual["stringTypes"])
        self.assertTrue(actual["validCutoff"])
        self.assertEqual("2026-09-10T13:35:00Z", actual["utc"])

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
