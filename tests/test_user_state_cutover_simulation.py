from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.user_state_cutover_simulation import (
    run_user_state_cutover_simulation,
    write_user_state_cutover_simulation_report,
)


class UserStateCutoverSimulationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-cutover-sim-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_cutover_simulation_runs_all_required_scenarios(self) -> None:
        payload = run_user_state_cutover_simulation(
            work_dir=self.root / "work",
            keep_work_dir=False,
            generated_at="2026-06-26T22:00:00-05:00",
        )

        self.assertEqual("PASS", payload["overall_status"])
        scenario_names = {scenario["name"] for scenario in payload["scenarios"]}
        self.assertEqual(
            {
                "clean_import",
                "missing_watchlist_row",
                "stale_entry_plan",
                "duplicate_review",
                "conflicting_review_status",
                "malformed_entry_plan",
                "incomplete_entry_plan",
                "backup_restore_validation_failure",
                "rollback_simulation",
                "source_files_unchanged",
            },
            scenario_names,
        )
        self.assertEqual(10, payload["passed_scenarios"])
        self.assertTrue(all(scenario["source_files_unchanged"] for scenario in payload["scenarios"]))

    def test_cutover_simulation_report_writes_json_and_markdown(self) -> None:
        payload = run_user_state_cutover_simulation(
            work_dir=self.root / "work",
            keep_work_dir=False,
            generated_at="2026-06-26T22:00:00-05:00",
        )
        paths = write_user_state_cutover_simulation_report(
            payload,
            json_path=self.root / "user-state-cutover-simulation-latest.json",
            markdown_path=self.root / "user-state-cutover-simulation-latest.md",
        )

        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["markdown"].exists())
        text = paths["markdown"].read_text(encoding="utf-8")
        self.assertIn("missing_watchlist_row", text)
        self.assertIn("Production user-state files are not modified", text)


if __name__ == "__main__":
    unittest.main()
