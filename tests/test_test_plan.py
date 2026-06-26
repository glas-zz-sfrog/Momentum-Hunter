from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from momentum_hunter.test_plan import build_test_plan, format_text, main


class TestPlanTests(unittest.TestCase):
    def test_required_autonomous_suites_are_listed(self) -> None:
        plan = build_test_plan()

        self.assertEqual("autonomous_test_plan_v1", plan["engine_version"])
        for name in [
            "storage-safe",
            "sqlite-safe",
            "evidence-safe",
            "provider-safe",
            "replay-safe",
            "ui-bounded-safe",
            "do-not-run-unattended",
        ]:
            self.assertIn(name, plan["suites"])

    def test_text_output_includes_commands_and_do_not_run_warning(self) -> None:
        text = format_text(build_test_plan())

        self.assertIn("tools\\run_bounded_tests.py", text)
        self.assertIn("do-not-run-unattended", text)
        self.assertIn("Do not run as an autonomous suite.", text)

    def test_json_cli_outputs_parseable_plan(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["--json"])

        payload = json.loads(buffer.getvalue())
        self.assertEqual(0, exit_code)
        self.assertIn("sqlite-safe", payload["suites"])


if __name__ == "__main__":
    unittest.main()
