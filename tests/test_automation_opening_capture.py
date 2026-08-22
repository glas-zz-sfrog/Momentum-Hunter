from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path

from momentum_hunter.automation_opening_capture import (
    build_opening_capture_jobs,
    plan_opening_capture_manifest,
    write_validated_plan,
)
from momentum_hunter.automation_supervisor import parse_manifest


class AutomationOpeningCaptureTests(unittest.TestCase):
    expected_git_head = "a" * 40

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "tools").mkdir()
        (self.repo / "tools" / "run_capture_job.ps1").write_text(
            "exit 0\n",
            encoding="utf-8",
        )
        self.python = self.root / "python.exe"
        self.python.write_text("", encoding="utf-8")
        self.powershell = self.root / "powershell.exe"
        self.powershell.write_text("", encoding="utf-8")
        self.manifest_path = self.root / "automation-manifest.json"
        self.manifest_path.write_text(
            json.dumps(self.manifest_payload()),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_covers_market_days_and_skips_weekends_and_holidays(self) -> None:
        jobs = build_opening_capture_jobs(
            start_date=date(2026, 8, 1),
            market_sessions=25,
            expected_git_head=self.expected_git_head,
        )

        dates = [
            datetime.fromisoformat(str(job["scheduledAt"])).date()
            for job in jobs
        ]
        self.assertEqual(date(2026, 8, 3), dates[0])
        self.assertNotIn(date(2026, 9, 7), dates)
        self.assertTrue(all(day.weekday() < 5 for day in dates))
        self.assertTrue(all(
            str(job["scheduledAt"])[11:19] == "08:35:00" for job in jobs
        ))

    def test_release_channel_plan_preserves_dates_without_per_job_git_pins(self) -> None:
        jobs = build_opening_capture_jobs(
            start_date=date(2026, 8, 24),
            market_sessions=3,
            approved_runtime_channel="opening-capture",
        )

        self.assertEqual(3, len(jobs))
        self.assertTrue(all(
            job["approvedRuntimeChannel"] == "opening-capture" for job in jobs
        ))
        self.assertTrue(all("expectedGitHead" not in job for job in jobs))
        self.assertTrue(all(
            str(job["scheduledAt"])[11:19] == "08:35:00" for job in jobs
        ))
        self.assertTrue(all(
            (
                datetime.fromisoformat(str(job["latestStartAt"]))
                - datetime.fromisoformat(str(job["scheduledAt"]))
            ).total_seconds()
            == 300
            for job in jobs
        ))

    def test_shadow_date_uses_shadow_capture_instead_of_duplicate_job(self) -> None:
        jobs = build_opening_capture_jobs(
            start_date=date(2026, 8, 3),
            market_sessions=3,
            expected_git_head=self.expected_git_head,
            shadow_dates={date(2026, 8, 4)},
        )

        self.assertEqual(
            ["opening-capture-20260803", "opening-capture-20260805"],
            [str(job["jobId"]) for job in jobs],
        )

    def test_replan_replaces_only_opening_jobs_and_preserves_other_work(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "existing-canary",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-08-01T10:00:00-05:00",
                    "latestStartAt": "2026-08-01T10:05:00-05:00",
                },
                {
                    "jobId": "opening-capture-old",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-31T08:35:00-05:00",
                    "latestStartAt": "2026-07-31T08:40:00-05:00",
                },
            ]
        )

        planned = plan_opening_capture_manifest(
            payload,
            start_date=date(2026, 8, 1),
            market_sessions=2,
            expected_git_head=self.expected_git_head,
        )

        identifiers = [str(job["jobId"]) for job in planned["jobs"]]
        self.assertIn("existing-canary", identifiers)
        self.assertNotIn("opening-capture-old", identifiers)
        self.assertIn("opening-capture-20260803", identifiers)
        self.assertIn("opening-capture-20260804", identifiers)

    def test_replan_updates_retained_paper_job_to_new_opening_identity(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260803",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-08-03T08:35:00-05:00",
                    "latestStartAt": "2026-08-03T08:40:00-05:00",
                    "expectedGitHead": "b" * 40,
                },
                {
                    "jobId": "paper-engineering-20260803",
                    "kind": "paper_engineering",
                    "scheduledAt": "2026-08-03T08:35:00-05:00",
                    "latestStartAt": "2026-08-03T08:50:00-05:00",
                    "timeoutSeconds": 25200,
                    "expectedGitHead": "b" * 40,
                    "dependsOnJobId": "opening-capture-20260803",
                },
            ]
        )

        planned = plan_opening_capture_manifest(
            payload,
            start_date=date(2026, 8, 3),
            market_sessions=2,
            expected_git_head=self.expected_git_head,
        )

        paper = next(job for job in planned["jobs"] if job["kind"] == "paper_engineering")
        self.assertEqual(self.expected_git_head, paper["expectedGitHead"])

    def test_replan_updates_both_successor_passes_to_new_identity(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260817",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:40:00-05:00",
                    "expectedGitHead": "b" * 40,
                },
                {
                    "jobId": "successor-setup-pass1-20260817",
                    "kind": "successor_setup_pass1",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:50:00-05:00",
                    "timeoutSeconds": 600,
                    "expectedGitHead": "b" * 40,
                    "dependsOnJobId": "opening-capture-20260817",
                },
                {
                    "jobId": "successor-setup-pass2-20260817",
                    "kind": "successor_setup_pass2",
                    "scheduledAt": "2026-08-17T15:05:00-05:00",
                    "latestStartAt": "2026-08-17T16:00:00-05:00",
                    "timeoutSeconds": 900,
                    "expectedGitHead": "b" * 40,
                    "dependsOnJobId": "successor-setup-pass1-20260817",
                },
            ]
        )

        planned = plan_opening_capture_manifest(
            payload,
            start_date=date(2026, 8, 17),
            market_sessions=2,
            expected_git_head=self.expected_git_head,
        )

        successor = [
            job for job in planned["jobs"] if str(job["kind"]).startswith("successor_")
        ]
        self.assertEqual(2, len(successor))
        self.assertTrue(
            all(job["expectedGitHead"] == self.expected_git_head for job in successor)
        )

    def test_replan_drops_historical_paper_job_after_terminal_session(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "existing-canary",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-08-01T10:00:00-05:00",
                    "latestStartAt": "2026-08-01T10:05:00-05:00",
                },
                {
                    "jobId": "opening-capture-20260811",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-08-11T08:35:00-05:00",
                    "latestStartAt": "2026-08-11T08:40:00-05:00",
                    "expectedGitHead": "b" * 40,
                },
                {
                    "jobId": "paper-engineering-20260811",
                    "kind": "paper_engineering",
                    "scheduledAt": "2026-08-11T08:35:00-05:00",
                    "latestStartAt": "2026-08-11T08:50:00-05:00",
                    "timeoutSeconds": 25200,
                    "expectedGitHead": "b" * 40,
                    "dependsOnJobId": "opening-capture-20260811",
                },
            ]
        )

        planned = plan_opening_capture_manifest(
            payload,
            start_date=date(2026, 8, 12),
            market_sessions=2,
            expected_git_head=self.expected_git_head,
            terminal_job_ids={"paper-engineering-20260811"},
        )

        identifiers = [str(job["jobId"]) for job in planned["jobs"]]
        self.assertIn("existing-canary", identifiers)
        self.assertNotIn("opening-capture-20260811", identifiers)
        self.assertNotIn("paper-engineering-20260811", identifiers)
        self.assertIn("opening-capture-20260812", identifiers)
        self.assertIn("opening-capture-20260813", identifiers)

    def test_replan_rejects_historical_paper_job_without_terminal_receipt(
        self,
    ) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260811",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-08-11T08:35:00-05:00",
                    "latestStartAt": "2026-08-11T08:40:00-05:00",
                    "expectedGitHead": "b" * 40,
                },
                {
                    "jobId": "paper-engineering-20260811",
                    "kind": "paper_engineering",
                    "scheduledAt": "2026-08-11T08:35:00-05:00",
                    "latestStartAt": "2026-08-11T08:50:00-05:00",
                    "timeoutSeconds": 25200,
                    "expectedGitHead": "b" * 40,
                    "dependsOnJobId": "opening-capture-20260811",
                },
            ]
        )

        with self.assertRaisesRegex(
            ValueError,
            "historical dependent job has no terminal service receipt",
        ):
            plan_opening_capture_manifest(
                payload,
                start_date=date(2026, 8, 12),
                market_sessions=2,
                expected_git_head=self.expected_git_head,
            )

    def test_replan_drops_terminal_historical_successor_dependencies(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260817",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:40:00-05:00",
                    "expectedGitHead": "b" * 40,
                },
                {
                    "jobId": "successor-setup-pass1-20260817",
                    "kind": "successor_setup_pass1",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:50:00-05:00",
                    "timeoutSeconds": 600,
                    "expectedGitHead": "b" * 40,
                    "dependsOnJobId": "opening-capture-20260817",
                },
                {
                    "jobId": "successor-setup-pass2-20260817",
                    "kind": "successor_setup_pass2",
                    "scheduledAt": "2026-08-17T15:05:00-05:00",
                    "latestStartAt": "2026-08-17T16:00:00-05:00",
                    "timeoutSeconds": 900,
                    "expectedGitHead": "b" * 40,
                    "dependsOnJobId": "successor-setup-pass1-20260817",
                },
            ]
        )

        planned = plan_opening_capture_manifest(
            payload,
            start_date=date(2026, 8, 24),
            market_sessions=2,
            expected_git_head=self.expected_git_head,
            terminal_job_ids={
                "successor-setup-pass1-20260817",
                "successor-setup-pass2-20260817",
            },
        )

        identifiers = {str(job["jobId"]) for job in planned["jobs"]}
        self.assertNotIn("opening-capture-20260817", identifiers)
        self.assertNotIn("successor-setup-pass1-20260817", identifiers)
        self.assertNotIn("successor-setup-pass2-20260817", identifiers)
        self.assertIn("opening-capture-20260824", identifiers)

    def test_replan_rejects_nonterminal_historical_successor_dependency(
        self,
    ) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "successor-setup-pass1-20260817",
                    "kind": "successor_setup_pass1",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:50:00-05:00",
                    "timeoutSeconds": 600,
                    "expectedGitHead": "b" * 40,
                    "dependsOnJobId": "opening-capture-20260817",
                }
            ]
        )

        with self.assertRaisesRegex(
            ValueError,
            "historical dependent job has no terminal service receipt",
        ):
            plan_opening_capture_manifest(
                payload,
                start_date=date(2026, 8, 24),
                market_sessions=2,
                expected_git_head=self.expected_git_head,
            )

    def test_validated_plan_does_not_mutate_source_manifest(self) -> None:
        original = self.manifest_path.read_bytes()
        output = self.root / "planned.json"

        summary = write_validated_plan(
            manifest_path=self.manifest_path,
            output_path=output,
            start_date=date(2026, 8, 1),
            market_sessions=30,
            expected_git_head=self.expected_git_head,
        )

        self.assertEqual(original, self.manifest_path.read_bytes())
        self.assertEqual(30, summary["openingCaptureJobs"])
        self.assertEqual("UNAVAILABLE", summary["selectorArming"])
        self.assertEqual("UNAVAILABLE", summary["orderTransmission"])
        planned = parse_manifest(output)
        self.assertEqual(
            30,
            sum(job.kind == "opening_capture" for job in planned.jobs),
        )
        self.assertTrue(all(
            job.expected_git_head == self.expected_git_head
            for job in planned.jobs
            if job.kind == "opening_capture"
        ))

    def test_validated_plan_migrates_legacy_unpinned_opening_jobs(self) -> None:
        legacy = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-legacy",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-31T08:35:00-05:00",
                    "latestStartAt": "2026-07-31T08:40:00-05:00",
                    "timeoutSeconds": 900,
                }
            ]
        )
        self.manifest_path.write_text(json.dumps(legacy), encoding="utf-8")
        original = self.manifest_path.read_bytes()
        output = self.root / "migrated.json"

        write_validated_plan(
            manifest_path=self.manifest_path,
            output_path=output,
            start_date=date(2026, 8, 1),
            market_sessions=2,
            expected_git_head=self.expected_git_head,
        )

        self.assertEqual(original, self.manifest_path.read_bytes())
        planned = parse_manifest(output)
        self.assertEqual(2, len(planned.jobs))
        self.assertTrue(all(
            job.expected_git_head == self.expected_git_head
            for job in planned.jobs
        ))

    def test_installer_and_runner_keep_opening_capture_nontransmitting(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        installer = (
            project_root / "tools" / "set_opening_capture_service_jobs.ps1"
        ).read_text(encoding="utf-8")
        runner = (project_root / "tools" / "run_capture_job.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("-EnableOpeningCaptures", installer)
        self.assertIn('"opening_capture"', installer)
        self.assertIn('"--expected-git-head"', installer)
        self.assertIn("$gitHead", installer)
        self.assertIn('"--terminal-job-id"', installer)
        self.assertIn("$terminalDependentJobIds", installer)
        self.assertIn('"UNAVAILABLE"', installer)
        self.assertIn('"opening"', runner)
        self.assertIn("$OpeningRetryCount = 1", runner)
        self.assertIn(
            '$Session -eq "opening" -and $exitCode -eq $retryableInfrastructureExit',
            runner,
        )
        self.assertNotIn("ArmShadowSelector", installer)
        self.assertNotIn("submit", installer.lower())
        self.assertNotIn("cancel", installer.lower())

    def test_plan_rejects_missing_or_abbreviated_git_identity(self) -> None:
        for value in ("", "a" * 7, "A" * 40):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError,
                "full lowercase Git SHA",
            ):
                build_opening_capture_jobs(
                    start_date=date(2026, 8, 3),
                    market_sessions=1,
                    expected_git_head=value,
                )

    def manifest_payload(
        self,
        *,
        jobs: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "repositoryRoot": str(self.repo),
            "pythonExecutable": str(self.python),
            "powershellExecutable": str(self.powershell),
            "codexExecutable": "",
            "stateDirectory": str(self.root / "state"),
            "engineHostStateDirectory": str(self.root / "engine"),
            "expectedAccountEnding": "2573",
            "expectedAccountType": "INDIVIDUAL_CASH",
            "pollIntervalSeconds": 1,
            "jobs": jobs or [],
        }


class OpeningCaptureRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.runner = (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "run_capture_job.ps1"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_opening_runner_retries_without_selector_or_broker_arguments(
        self,
    ) -> None:
        (self.tools / "capture_job.py").write_text(
            "\n".join(
                (
                    "import json",
                    "import sys",
                    "from pathlib import Path",
                    "root = Path(__file__).resolve().parents[1]",
                    "attempt_path = root / 'attempts.txt'",
                    "attempt = int(attempt_path.read_text()) + 1 if attempt_path.exists() else 1",
                    "attempt_path.write_text(str(attempt))",
                    "(root / 'arguments.json').write_text(json.dumps(sys.argv[1:]))",
                    "raise SystemExit(0 if attempt == 3 else 75)",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (self.tools / "update_outcomes.py").write_text(
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            (
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.runner),
                "-Session",
                "opening",
                "-ProjectRoot",
                str(self.root),
                "-PythonExe",
                sys.executable,
                "-OpeningRetryCount",
                "2",
                "-OpeningRetryDelaySeconds",
                "0",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("3", (self.root / "attempts.txt").read_text())
        arguments = json.loads((self.root / "arguments.json").read_text())
        self.assertIn("--session", arguments)
        self.assertIn("opening", arguments)
        self.assertIn("--require-opening-result", arguments)
        joined = " ".join(arguments).lower()
        self.assertNotIn("shadow", joined)
        self.assertNotIn("selector", joined)
        self.assertNotIn("proof", joined)
        self.assertNotIn("account", joined)
        self.assertNotIn("position", joined)
        self.assertNotIn("order", joined)

    def test_opening_runner_does_not_retry_terminal_failure(self) -> None:
        (self.tools / "capture_job.py").write_text(
            "from pathlib import Path\n"
            "root = Path(__file__).resolve().parents[1]\n"
            "counter = root / 'attempts.txt'\n"
            "attempt = int(counter.read_text()) + 1 if counter.exists() else 1\n"
            "counter.write_text(str(attempt))\n"
            "raise SystemExit(1)\n",
            encoding="utf-8",
        )
        (self.tools / "update_outcomes.py").write_text(
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            (
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.runner),
                "-Session",
                "opening",
                "-ProjectRoot",
                str(self.root),
                "-PythonExe",
                sys.executable,
                "-OpeningRetryCount",
                "3",
                "-OpeningRetryDelaySeconds",
                "0",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(1, result.returncode)
        self.assertEqual("1", (self.root / "attempts.txt").read_text())
        self.assertNotIn("Retrying bounded capture failure", result.stdout)

    def test_opening_capture_defers_unbounded_outcome_maintenance(
        self,
    ) -> None:
        (self.tools / "capture_job.py").write_text(
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )
        (self.tools / "update_outcomes.py").write_text(
            "from pathlib import Path\n"
            "Path(__file__).resolve().parents[1].joinpath('outcome-ran.txt').write_text('ran')\n"
            "raise SystemExit(23)\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            (
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.runner),
                "-Session",
                "opening",
                "-ProjectRoot",
                str(self.root),
                "-PythonExe",
                sys.executable,
                "-OpeningRetryCount",
                "0",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("OutcomeUpdateState: DEFERRED_AFTER_OPENING", result.stdout)
        self.assertFalse((self.root / "outcome-ran.txt").exists())
        status_paths = list(
            (self.root / "MomentumHunterData" / "logs").glob(
                "outcomes-opening-*.status.json"
            )
        )
        self.assertEqual(1, len(status_paths))
        status = json.loads(status_paths[0].read_text(encoding="utf-8-sig"))
        self.assertTrue(status["openingResultPreserved"])
        self.assertEqual("DEFERRED_AFTER_OPENING", status["state"])
        self.assertIsNone(status["exitCode"])

    def test_deferred_status_write_failure_does_not_invalidate_opening(
        self,
    ) -> None:
        (self.tools / "capture_job.py").write_text(
            "import time\n"
            "time.sleep(2)\n"
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )
        logs_dir = self.root / "MomentumHunterData" / "logs"
        process = subprocess.Popen(
            (
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.runner),
                "-Session",
                "opening",
                "-ProjectRoot",
                str(self.root),
                "-PythonExe",
                sys.executable,
                "-OpeningRetryCount",
                "0",
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        capture_log: Path | None = None
        while time.monotonic() < deadline:
            matches = list(logs_dir.glob("capture-opening-*.log"))
            if matches:
                capture_log = matches[0]
                break
            time.sleep(0.05)
        self.assertIsNotNone(capture_log)
        assert capture_log is not None
        suffix = capture_log.name.removeprefix("capture-opening-").removesuffix(
            ".log"
        )
        blocked_status = logs_dir / f"outcomes-opening-{suffix}.status.json"
        blocked_status.mkdir()

        stdout, stderr = process.communicate(timeout=30)

        self.assertEqual(0, process.returncode, stdout + stderr)
        self.assertIn("OpeningAttemptExitCode: 0", stdout)
        self.assertIn(
            "WARNING: Opening capture succeeded, but deferred outcome status "
            "could not be written",
            stdout,
        )
        self.assertIn("ExitCode: 0", stdout)
        self.assertTrue(blocked_status.is_dir())


if __name__ == "__main__":
    unittest.main()
