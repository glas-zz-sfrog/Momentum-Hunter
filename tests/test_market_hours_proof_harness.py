from __future__ import annotations

import shutil
import subprocess
import unittest
import uuid
from pathlib import Path

from momentum_hunter.market_hours_proof_harness import (
    proof_steps,
    run_market_hours_proof_harness,
    write_market_hours_proof_report,
)


class MarketHoursProofHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-market-hours-proof-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_dry_run_plans_all_required_steps_without_executing(self) -> None:
        payload = run_market_hours_proof_harness(execute=False, generated_at="2026-06-27T02:00:00-05:00")

        self.assertEqual("DRY_RUN", payload["overall_status"])
        names = {step["name"] for step in payload["steps"]}
        self.assertEqual({step.name for step in proof_steps()}, names)
        self.assertTrue(all(step["status"] == "PLANNED_DRY_RUN" for step in payload["steps"]))
        self.assertIn("active_monitor_cycle", names)
        self.assertIn("sqlite_analytics", names)

    def test_execute_without_live_market_skips_market_data_step(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="OK", stderr="")

        payload = run_market_hours_proof_harness(
            execute=True,
            allow_live_market=False,
            generated_at="2026-06-27T02:00:00-05:00",
            runner=runner,
        )

        by_name = {step["name"]: step for step in payload["steps"]}
        self.assertEqual("WARN", payload["overall_status"])
        self.assertEqual("SKIPPED_MARKET_HOURS_REQUIRED", by_name["active_monitor_cycle"]["status"])
        self.assertFalse(any("momentum_hunter.active_monitor" in " ".join(command) for command in calls))
        self.assertTrue(any("momentum_hunter.sqlite_validation" in " ".join(command) for command in calls))

    def test_report_writes_json_and_markdown(self) -> None:
        payload = run_market_hours_proof_harness(execute=False, generated_at="2026-06-27T02:00:00-05:00")
        paths = write_market_hours_proof_report(
            payload,
            json_path=self.root / "market-hours-proof-harness-latest.json",
            markdown_path=self.root / "market-hours-proof-harness-latest.md",
        )

        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())
        self.assertIn("Market-Hours Proof Run Harness", paths["markdown"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
