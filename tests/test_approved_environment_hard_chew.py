from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPOSITORY_ROOT / "tools" / "run_approved_environment_tests.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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

    def test_package_secret_scan_is_context_aware_for_bound_identity(self) -> None:
        package_tool = _load_module(
            "producer_001e_package_tool",
            REPOSITORY_ROOT / "tools" / "package_continuous_producer_001e_review.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "market.json").write_text(
                json.dumps({"price": 12573.25, "fingerprint": "abc2573def"}),
                encoding="ascii",
            )
            self.assertEqual(package_tool._secret_scan(root, "2573")["status"], "PASS")
            (root / "account.json").write_text(
                json.dumps({"accountEnding": "2573"}),
                encoding="ascii",
            )
            scan = package_tool._secret_scan(root, "2573")
            self.assertEqual(scan["status"], "FAIL")
            self.assertIn(
                "UNREDACTED_SENSITIVE_JSON_VALUE",
                {item["term"] for item in scan["findings"]},
            )

    def test_package_secret_scan_allows_only_marked_synthetic_private_key_fixture(
        self,
    ) -> None:
        package_tool = _load_module(
            "producer_001e_package_tool_private_key",
            REPOSITORY_ROOT / "tools" / "package_continuous_producer_001e_review.py",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tests = root / "source" / "tests"
            tests.mkdir(parents=True)
            fixture = tests / "test_fixture.py"
            fixture.write_text(
                'SYNTHETIC_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----\n'
                "TEST-ONLY\n-----END PRIVATE KEY-----\n"
                '"""\n',
                encoding="ascii",
            )
            self.assertEqual(package_tool._secret_scan(root, "")["status"], "PASS")
            (root / "unmarked.pem").write_text(
                "-----BEGIN PRIVATE KEY-----\nNOT-ALLOWLISTED\n",
                encoding="ascii",
            )
            scan = package_tool._secret_scan(root, "")
            self.assertEqual(scan["status"], "FAIL")
            self.assertIn("PRIVATE_KEY", {item["term"] for item in scan["findings"]})


if __name__ == "__main__":
    unittest.main()
