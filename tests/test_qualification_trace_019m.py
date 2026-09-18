from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "sitecustomize.py"
REQUIRED = (
    "H2_PYTHON_RUNTIME_STARTED",
    "H3_DIAGNOSTIC_BOOTSTRAP_ACTIVE",
    "H4_TARGET_MODULE_ENTRY_REACHED",
    "H5_PRINT_INSTALL_PLAN_ENTRY_REACHED",
)


class PhysicalShapeTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="mh-019m-startup-")
        cls.root = Path(cls.temporary.name)
        cls.venv = cls.root / "venv"
        base_python = Path(sys.base_prefix) / "python.exe"
        result = subprocess.run(
            [str(base_python), "-m", "venv", "--without-pip", str(cls.venv)],
            capture_output=True, text=True, check=False, timeout=30,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        site = cls.venv / "Lib" / "site-packages"
        cls.installed_hook = site / "sitecustomize.py"
        shutil.copyfile(HOOK, cls.installed_hook)
        tzdata = Path(sys.prefix) / "Lib" / "site-packages" / "tzdata"
        if not tzdata.is_dir():
            raise RuntimeError("Approved tzdata fixture is unavailable")
        shutil.copytree(tzdata, site / "tzdata")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def _run(self, trace: Path | None, *arguments: str) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if not any(
            term in key.upper() for term in (
                "SCHWAB", "FINVIZ", "ALPACA", "IBKR", "API_KEY", "API_SECRET",
                "OAUTH", "ACCESS_TOKEN", "REFRESH_TOKEN", "MH_CANARY",
            )
        )}
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env.pop("MH_QUALIFICATION_DIAGNOSTIC_ROOT", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if trace is not None:
            env["MH_QUALIFICATION_DIAGNOSTIC_ROOT"] = str(trace)
        return subprocess.run(
            [str(self.venv / "Scripts" / "python.exe"), "-B", "-m",
             "momentum_hunter.continuous_production", *arguments],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=15, check=False,
        )

    def test_exact_module_shape_emits_ordered_handshakes_without_pythonpath(self) -> None:
        trace = self.root / "exact-trace"
        trace.mkdir()
        result = self._run(trace, "--config", str(self.root / "missing.json"),
                           "--print-install-plan")
        self.assertNotEqual(0, result.returncode)
        stages = [line.split("|")[2] for line in
                  (trace / "python-stages.log").read_text(encoding="ascii").splitlines()]
        indices = [stages.index(stage) for stage in REQUIRED]
        self.assertEqual(indices, sorted(indices))
        self.assertTrue((trace / "python-stacks.log").exists())

    def test_missing_bootstrap_is_visible(self) -> None:
        backup = self.installed_hook.read_bytes()
        self.installed_hook.unlink()
        try:
            trace = self.root / "missing-hook"
            trace.mkdir()
            result = self._run(trace, "--help")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("DIAGNOSTIC_ACTIVATION_FAILURE: startup hook is not armed",
                          result.stderr)
        finally:
            self.installed_hook.write_bytes(backup)

    def test_wrong_build_is_visible(self) -> None:
        backup = self.installed_hook.read_bytes()
        self.installed_hook.write_bytes(backup.replace(
            b"ARGUS_019M_DIAGNOSTIC_V2", b"ARGUS_019M_DIAGNOSTIC_BAD"))
        try:
            trace = self.root / "wrong-build"
            trace.mkdir()
            result = self._run(trace, "--help")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("DIAGNOSTIC_ACTIVATION_FAILURE: instrumentation build mismatch",
                          result.stderr)
        finally:
            self.installed_hook.write_bytes(backup)

    def test_bootstrap_load_failure_does_not_enter_target_module(self) -> None:
        backup = self.installed_hook.read_bytes()
        self.installed_hook.write_bytes(b"raise RuntimeError('broken bootstrap')\n")
        try:
            trace = self.root / "broken-bootstrap"
            trace.mkdir()
            result = self._run(trace, "--help")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("DIAGNOSTIC_ACTIVATION_FAILURE: startup hook is not armed",
                          result.stderr)
            self.assertFalse((trace / "python-stages.log").exists())
        finally:
            self.installed_hook.write_bytes(backup)

    def test_unwritable_trace_location_fails_before_module(self) -> None:
        result = self._run(self.root / "absent-trace-root", "--help")
        self.assertEqual(86, result.returncode)
        self.assertIn("DIAGNOSTIC_BOOTSTRAP_FAILED:FileNotFoundError", result.stderr)

    def test_disabled_diagnostics_leave_help_unchanged(self) -> None:
        result = self._run(None, "--help")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--print-install-plan", result.stdout)


if __name__ == "__main__":
    unittest.main()
