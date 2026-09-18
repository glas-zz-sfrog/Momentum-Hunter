from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
MODULE = "momentum_hunter.continuous_production"


class QualificationTraceTests(unittest.TestCase):
    def _run(self, args: list[str], trace_root: Path | None = None, timeout: int = 35):
        env = {key: value for key, value in os.environ.items() if not any(
            term in key.upper() for term in (
                "SCHWAB", "FINVIZ", "ALPACA", "IBKR", "API_KEY", "API_SECRET",
                "OAUTH", "ACCESS_TOKEN", "REFRESH_TOKEN", "MH_CANARY",
            )
        )}
        env["PYTHONPATH"] = str(ROOT)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.pop("MH_QUALIFICATION_DIAGNOSTIC_ROOT", None)
        if trace_root is not None:
            env["MH_QUALIFICATION_DIAGNOSTIC_ROOT"] = str(trace_root)
        return subprocess.run(
            [PYTHON, "-B", *args], cwd=ROOT, env=env, capture_output=True,
            text=True, timeout=timeout, check=False,
        )

    def test_hook_is_inert_without_trace_root(self):
        result = self._run(["-c", "import sitecustomize; print(sitecustomize.argus_trace is None)"])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("True", result.stdout.strip())

    def test_module_import_and_parse_progress_are_durable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._run(["-m", MODULE, "--help"], root)
            self.assertEqual(0, result.returncode, result.stderr)
            stages = (root / "python-stages.log").read_text(encoding="ascii")
            for stage in (
                "PYTHON_STARTUP_HOOK_ARMED", "MODULE_IMPORT_ENTER",
                "MODULE_IMPORT_EXIT", "ARGUMENT_PARSE_ENTER",
            ):
                self.assertIn(stage, stages)
            self.assertTrue((root / "python-stacks.log").exists())

    def test_help_output_is_unchanged(self):
        without = self._run(["-m", MODULE, "--help"])
        with tempfile.TemporaryDirectory() as temporary:
            with_trace = self._run(["-m", MODULE, "--help"], Path(temporary))
        self.assertEqual(0, without.returncode)
        self.assertEqual(0, with_trace.returncode)
        self.assertEqual(without.stdout, with_trace.stdout)

    def test_configuration_read_failure_retains_last_entered_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing-config.json"
            result = self._run(["-m", MODULE, "--config", str(missing), "--print-install-plan"], root)
            self.assertNotEqual(0, result.returncode)
            stages = (root / "python-stages.log").read_text(encoding="ascii")
            self.assertIn("CONFIG_READ_ENTER", stages)
            self.assertNotIn("CONFIG_READ_EXIT", stages)

    def test_normal_plan_stages_and_output(self):
        code = (
            "import momentum_hunter.continuous_production as p; "
            "p._read_config=lambda _: {'mode':'RESEARCH_ONLY'}; "
            "p.install_plan=lambda *a: {'status':'DIAGNOSTIC_TEST'}; "
            "raise SystemExit(p.main(['--config','unused','--print-install-plan']))"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = self._run(["-c", code], root)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('"status": "DIAGNOSTIC_TEST"', result.stdout)
            stages = (root / "python-stages.log").read_text(encoding="ascii")
            for stage in (
                "INSTALL_PLAN_ENTER", "INSTALL_PLAN_EXIT", "INSTALL_PLAN_SERIALIZE_ENTER",
                "INSTALL_PLAN_SERIALIZE_EXIT", "INSTALL_PLAN_PRINT_EXIT",
            ):
                self.assertIn(stage, stages)

    def test_invalid_trace_root_fails_closed(self):
        result = self._run(["-c", "print('must not run')"], Path("relative-path"))
        self.assertEqual(86, result.returncode)
        self.assertNotIn("must not run", result.stdout)

    def test_existing_trace_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "python-stages.log").write_text("existing", encoding="ascii")
            result = self._run(["-c", "print('must not run')"], root)
            self.assertEqual(86, result.returncode)
            self.assertNotIn("must not run", result.stdout)

    def test_invalid_stage_name_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self._run(["-c", "import sitecustomize; sitecustomize.argus_trace('bad stage')"],
                               Path(temporary))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("Invalid diagnostic stage", result.stderr)

    def test_stack_timer_captures_blocked_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "blocked_import_019k.py").write_text("import time\ntime.sleep(21)\n", encoding="ascii")
            code = (
                "import sitecustomize,sys; "
                "sitecustomize.argus_trace('IMPORT_BLOCKED_STAGE'); "
                "sys.path.insert(0,sys.argv[1]); import blocked_import_019k"
            )
            result = self._run([
                "-c", code, str(root)
            ], root, timeout=27)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("IMPORT_BLOCKED_STAGE", (root / "python-stages.log").read_text(encoding="ascii"))
            stack = (root / "python-stacks.log").read_text(encoding="ascii")
            self.assertIn("Timeout", stack)
            self.assertIn("blocked_import_019k.py", stack)


if __name__ == "__main__":
    unittest.main()
