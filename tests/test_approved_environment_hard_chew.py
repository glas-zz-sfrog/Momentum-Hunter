from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPOSITORY_ROOT / "tools" / "run_approved_environment_tests.py"


class ApprovedEnvironmentHardChewTests(unittest.TestCase):
    def descriptor(self) -> dict[str, object]:
        result = subprocess.run(
            (sys.executable, "-B", str(RUNNER), "describe"),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_external_approved_environment_runs_repo_without_local_venv(self) -> None:
        descriptor = self.descriptor()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "isolated-worktree"
            (root / "momentum_hunter").mkdir(parents=True)
            (root / "momentum_hunter" / "__init__.py").write_text("", encoding="ascii")
            (root / "tests").mkdir()
            (root / "tests" / "__init__.py").write_text("", encoding="ascii")
            (root / "tests" / "test_smoke.py").write_text(
                "import unittest\n"
                "class Smoke(unittest.TestCase):\n"
                "    def test_ok(self): self.assertTrue(True)\n",
                encoding="ascii",
            )
            output = Path(directory) / "result.json"

            result = subprocess.run(
                (
                    sys.executable,
                    "-B",
                    str(RUNNER),
                    "run",
                    "--repository-root",
                    str(root),
                    "--expected-environment-fingerprint",
                    str(descriptor["environmentFingerprint"]),
                    "--output",
                    str(output),
                    "--",
                    "tests.test_smoke",
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            evidence = json.loads(output.read_text(encoding="ascii"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("PASS", evidence["status"])
        self.assertFalse(evidence["localWorktreeVenvPresent"])
        self.assertTrue(
            evidence["loadedMomentumHunterSource"].startswith(
                evidence["repositoryUnderTest"]["path"]
            )
        )

    def test_unapproved_environment_fingerprint_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "isolated-worktree"
            (root / "momentum_hunter").mkdir(parents=True)
            (root / "momentum_hunter" / "__init__.py").write_text("", encoding="ascii")
            (root / "tests").mkdir()
            output = Path(directory) / "result.json"

            result = subprocess.run(
                (
                    sys.executable,
                    "-B",
                    str(RUNNER),
                    "run",
                    "--repository-root",
                    str(root),
                    "--expected-environment-fingerprint",
                    "0" * 64,
                    "--output",
                    str(output),
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            evidence = json.loads(output.read_text(encoding="ascii"))

        self.assertEqual(1, result.returncode)
        self.assertEqual("FAIL", evidence["status"])
        self.assertIn("approved environment fingerprint", evidence["message"])


if __name__ == "__main__":
    unittest.main()
