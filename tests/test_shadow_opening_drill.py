from __future__ import annotations

import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from momentum_hunter import shadow_opening_drill
from momentum_hunter.shadow_opening_drill import (
    run_shadow_opening_negative_controls,
    snapshot_protected_shadow_state,
    write_shadow_opening_negative_control_report,
)


class ShadowOpeningNegativeControlDrillTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_directory = self.root / "shadow-trading"
        self.output_directory = self.root / "reports"
        self.state_directory.mkdir()
        self.activation = (
            self.state_directory / "shadow-sample-activation.json"
        )
        self.activation.write_text(
            '{"sample":"official-shadow-v1"}\n',
            encoding="utf-8",
        )
        self.evaluated_at = datetime(
            2026,
            7,
            28,
            8,
            50,
            tzinfo=UTC,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_three_negative_controls_pass_without_state_mutation(
        self,
    ) -> None:
        before = snapshot_protected_shadow_state(self.state_directory)

        report = run_shadow_opening_negative_controls(
            shadow_state_directory=self.state_directory,
            evaluated_at=self.evaluated_at,
        )

        after = snapshot_protected_shadow_state(self.state_directory)
        self.assertEqual("PASS", report["status"])
        self.assertEqual(3, report["scenarioCount"])
        self.assertEqual(3, report["passingScenarioCount"])
        self.assertEqual(before, after)
        self.assertTrue(report["protectedState"]["unchanged"])
        self.assertEqual(
            [],
            report["protectedState"]["forbiddenArtifactsAfter"],
        )
        self.assertEqual(
            {
                "HOST_FAILURE_BLOCKED_NO_HANDOFF",
                "CLOCK_GATE_BLOCKED",
                "IN_PROGRESS_HEARTBEAT_RETAINED",
            },
            {
                scenario["observed"]
                for scenario in report["scenarios"]
            },
        )
        self.assertTrue(
            all(
                scenario["protected_state_unchanged"]
                for scenario in report["scenarios"]
            )
        )

    def test_preexisting_forbidden_state_fails_without_modifying_it(
        self,
    ) -> None:
        arm = self.state_directory / "shadow-selector-arm.json"
        arm.write_text('{"unexpected":"arm"}\n', encoding="utf-8")
        before = snapshot_protected_shadow_state(self.state_directory)

        report = run_shadow_opening_negative_controls(
            shadow_state_directory=self.state_directory,
            evaluated_at=self.evaluated_at,
        )

        self.assertEqual("FAIL", report["status"])
        self.assertEqual(
            before,
            snapshot_protected_shadow_state(self.state_directory),
        )
        self.assertEqual(
            ["shadow-selector-arm.json"],
            report["protectedState"]["forbiddenArtifactsAfter"],
        )
        self.assertTrue(
            all(
                scenario["status"] == "FAIL"
                for scenario in report["scenarios"]
            )
        )

    def test_mutation_during_scenario_is_detected_and_not_concealed(
        self,
    ) -> None:
        policy = self.state_directory / "shadow-selection-policy.json"

        def mutating_clock_scenario() -> tuple[
            bool,
            str,
            tuple[str, ...],
        ]:
            policy.write_text('{"unexpected":"policy"}\n', encoding="utf-8")
            return True, "CLOCK_GATE_BLOCKED", ("synthetic mutation",)

        with patch.object(
            shadow_opening_drill,
            "run_excessive_clock_skew",
            side_effect=mutating_clock_scenario,
        ):
            report = run_shadow_opening_negative_controls(
                shadow_state_directory=self.state_directory,
                evaluated_at=self.evaluated_at,
            )

        self.assertEqual("FAIL", report["status"])
        clock = next(
            item
            for item in report["scenarios"]
            if item["name"] == "clock_skew_over_five_seconds"
        )
        self.assertFalse(clock["protected_state_unchanged"])
        self.assertFalse(clock["forbidden_artifacts_absent"])
        self.assertIn(
            "shadow-selection-policy.json",
            report["protectedState"]["forbiddenArtifactsAfter"],
        )

    def test_reports_are_structured_and_do_not_change_shadow_state(
        self,
    ) -> None:
        report = run_shadow_opening_negative_controls(
            shadow_state_directory=self.state_directory,
            evaluated_at=self.evaluated_at,
        )
        before = snapshot_protected_shadow_state(self.state_directory)

        paths = write_shadow_opening_negative_control_report(
            report,
            output_directory=self.output_directory,
        )

        self.assertEqual(
            before,
            snapshot_protected_shadow_state(self.state_directory),
        )
        payload = json.loads(
            paths["json"].read_text(encoding="utf-8")
        )
        markdown = paths["markdown"].read_text(encoding="utf-8")
        self.assertEqual("PASS", payload["status"])
        self.assertEqual(
            "SHADOW_OPENING_NEGATIVE_CONTROLS",
            payload["reportType"],
        )
        self.assertIn("3 / 3", markdown)
        self.assertIn("Order transmission: `UNAVAILABLE`", markdown)

    def test_cli_writes_only_to_requested_directories(self) -> None:
        result = subprocess.run(
            (
                sys.executable,
                "-B",
                "-m",
                "momentum_hunter.shadow_opening_drill",
                "--shadow-state-directory",
                str(self.state_directory),
                "--output-directory",
                str(self.output_directory),
                "--evaluated-at",
                self.evaluated_at.isoformat(),
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            "Shadow opening negative controls: PASS",
            result.stdout,
        )
        self.assertTrue(
            (
                self.output_directory
                / "shadow-opening-negative-controls-latest.json"
            ).is_file()
        )
        self.assertEqual(
            ['shadow-sample-activation.json'],
            sorted(path.name for path in self.state_directory.iterdir()),
        )

    def test_drill_has_no_network_broker_host_or_subprocess_path(self) -> None:
        source = inspect.getsource(shadow_opening_drill)

        self.assertNotIn("requests", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("socket", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("engine_host_client", source)
        self.assertNotIn("schwab_", source)
        self.assertNotIn("shadow_trading import", source)
        self.assertNotIn("arm_automatic_selector", source)
        self.assertNotIn("run_immediate_collection_cycle", source)


if __name__ == "__main__":
    unittest.main()
