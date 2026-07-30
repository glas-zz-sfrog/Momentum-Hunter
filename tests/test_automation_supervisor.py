from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from momentum_hunter.automation_supervisor import (
    AutomationJob,
    AutomationManifest,
    AutomationSupervisor,
    JobReceipt,
    ManifestValidationError,
    SupervisorState,
    SupervisorStateStore,
    parse_manifest,
)


UTC = timezone.utc


class AutomationSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
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
        self.state_dir = self.root / "state"
        self.engine_dir = self.root / "engine"
        self.engine_dir.mkdir()
        self.now = datetime(2026, 7, 30, 13, 35, tzinfo=UTC)
        self.executed: list[str] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_due_job_executes_once_and_persists_terminal_receipt(self) -> None:
        job = self.job(kind="nonmarket_canary")
        supervisor = self.supervisor(job)

        first = supervisor.tick()
        second = supervisor.tick()

        self.assertEqual(["canary"], self.executed)
        self.assertEqual("COMPLETED", first.jobs["canary"].status)
        self.assertEqual("COMPLETED", second.jobs["canary"].status)
        stored = SupervisorStateStore(
            self.state_dir / "automation-service-state.json"
        ).load(started_at=self.now)
        self.assertEqual("COMPLETED", stored.jobs["canary"].status)

    def test_restart_after_window_marks_job_missed_without_execution(self) -> None:
        job = self.job(
            kind="shadow_opening",
            scheduled_at=self.now - timedelta(minutes=10),
            latest_start_at=self.now - timedelta(minutes=9, seconds=55),
        )
        supervisor = self.supervisor(job)

        state = supervisor.tick()

        self.assertEqual([], self.executed)
        self.assertEqual("MISSED", state.jobs["canary"].status)
        self.assertIn("will not run late", state.jobs["canary"].reason)

    def test_slow_engine_probe_cannot_launch_after_market_window(self) -> None:
        job = self.job(
            kind="shadow_opening",
            scheduled_at=self.now,
            latest_start_at=self.now + timedelta(seconds=5),
        )
        current = self.now

        def clock() -> datetime:
            nonlocal current
            observed = current
            current += timedelta(seconds=6)
            return observed

        state = AutomationSupervisor(
            self.manifest(job),
            clock=clock,
            engine_host_probe=self.healthy_engine,
            job_executor=self.execute,
        ).tick()

        self.assertEqual([], self.executed)
        self.assertEqual("MISSED", state.jobs["canary"].status)

    def test_interrupted_job_is_failed_instead_of_restarted_late(self) -> None:
        job = self.job(
            kind="shadow_opening",
            scheduled_at=self.now - timedelta(minutes=1),
            latest_start_at=self.now - timedelta(seconds=55),
        )
        first = SupervisorStateStore(
            self.state_dir / "automation-service-state.json"
        )
        first.save(
            self.running_state(
                job,
                started_at=self.now - timedelta(minutes=1),
            )
        )

        state = self.supervisor(job).tick()

        self.assertEqual([], self.executed)
        self.assertEqual("FAILED", state.jobs["canary"].status)
        self.assertIn("not resumed late", state.jobs["canary"].reason)

    def test_unhealthy_engine_host_fails_due_job_closed(self) -> None:
        job = self.job(kind="nonmarket_canary")
        supervisor = AutomationSupervisor(
            self.manifest(job),
            clock=lambda: self.now,
            engine_host_probe=lambda: {
                "identity": {},
                "health": {"state": "Failed", "detail": "not ready"},
            },
            job_executor=self.execute,
        )

        state = supervisor.tick()

        self.assertEqual([], self.executed)
        self.assertEqual("FAILED", state.jobs["canary"].status)
        self.assertIn("not healthy", state.jobs["canary"].reason)

    def test_nonmarket_canary_fails_closed_on_account_binding_anomaly(
        self,
    ) -> None:
        job = self.job(kind="nonmarket_canary")
        binding = MagicMock(
            account_number_last_four="9999",
            account_type="INDIVIDUAL_CASH",
            account_hash="opaque-account-hash",
        )
        auth = MagicMock()
        auth.status.return_value = {"tokenState": "READY"}
        log_path = self.state_dir / "canary.log"
        with (
            patch(
                "momentum_hunter.automation_supervisor."
                "EncryptedSchwabAccountBindingStore"
            ) as store_type,
            patch(
                "momentum_hunter.automation_supervisor."
                "SchwabOAuthSecretRepository",
                return_value=auth,
            ),
        ):
            store_type.return_value.load.return_value = binding
            supervisor = AutomationSupervisor(
                self.manifest(job),
                clock=lambda: self.now,
                engine_host_probe=self.healthy_engine,
            )
            exit_code, detail = supervisor._run_nonmarket_canary(log_path)

        self.assertEqual(1, exit_code)
        self.assertIn("failed closed", detail)
        receipt = json.loads(log_path.read_text(encoding="utf-8"))
        self.assertFalse(receipt["accountBindingMatches"])
        self.assertIn("codexExecutablePresent", receipt)
        self.assertIn("codexAuthMaterialPresent", receipt)
        self.assertNotIn("codexHeadlessReady", receipt)
        self.assertFalse(receipt["positionsRequested"])
        self.assertFalse(receipt["ordersRequested"])
        self.assertEqual("UNAVAILABLE", receipt["orderTransmission"])

    def test_codex_review_requires_completed_dependency(self) -> None:
        runtime = self.job(kind="nonmarket_canary", job_id="runtime")
        prompt = self.repo / "review-prompt.txt"
        prompt.write_text("Inspect only.", encoding="utf-8")
        codex = self.root / "codex.cmd"
        codex.write_text("", encoding="utf-8")
        review = self.job(
            kind="codex_review",
            job_id="review",
            depends_on_job_id="runtime",
            prompt_path=prompt,
        )
        manifest = self.manifest(runtime, review, codex_executable=codex)
        executions: list[str] = []

        def execute(job: AutomationJob, _log: Path) -> tuple[int, str]:
            executions.append(job.job_id)
            return (1, "runtime failed") if job.job_id == "runtime" else (0, "")

        state = AutomationSupervisor(
            manifest,
            clock=lambda: self.now,
            engine_host_probe=self.healthy_engine,
            job_executor=execute,
        ).tick()

        self.assertEqual(["runtime"], executions)
        self.assertEqual("FAILED", state.jobs["runtime"].status)
        self.assertEqual("BLOCKED_DEPENDENCY", state.jobs["review"].status)

    def test_disabled_job_never_executes(self) -> None:
        job = self.job(kind="nonmarket_canary", enabled=False)

        state = self.supervisor(job).tick()

        self.assertEqual([], self.executed)
        self.assertEqual("DISABLED", state.jobs["canary"].status)

    def test_manifest_rejects_shadow_opening_late_window(self) -> None:
        bundle = self.repo / "MomentumHunterData" / "data" / "reports" / "bundle"
        bundle.mkdir(parents=True)
        definition = bundle.parent / "launch.xml"
        definition.write_text("<Task />", encoding="utf-8")
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening",
                    "kind": "shadow_opening",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:35:06-05:00",
                    "expectedGitHead": "a" * 40,
                    "proofBundlePath": str(bundle),
                    "taskDefinitionPath": str(definition),
                }
            ]
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "five-second start window",
        ):
            self.parse_payload(payload)

    def test_manifest_rejects_codex_review_without_dependency(self) -> None:
        prompt = self.repo / "prompt.txt"
        prompt.write_text("Inspect only.", encoding="utf-8")
        codex = self.root / "codex.cmd"
        codex.write_text("", encoding="utf-8")
        payload = self.manifest_payload(
            codex_executable=codex,
            jobs=[
                {
                    "jobId": "review",
                    "kind": "codex_review",
                    "scheduledAt": "2026-07-30T08:50:00-05:00",
                    "latestStartAt": "2026-07-30T09:00:00-05:00",
                    "promptPath": str(prompt),
                }
            ],
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "terminal runtime dependency",
        ):
            self.parse_payload(payload)

    def test_manifest_rejects_runtime_dependency(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "review",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-07-30T08:34:00-05:00",
                    "latestStartAt": "2026-07-30T08:34:30-05:00",
                },
                {
                    "jobId": "opening",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:35:30-05:00",
                    "dependsOnJobId": "review",
                },
            ],
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "Runtime jobs cannot depend",
        ):
            self.parse_payload(payload)

    def test_manifest_rejects_codex_review_chain(self) -> None:
        prompt = self.repo / "prompt.txt"
        prompt.write_text("Inspect only.", encoding="utf-8")
        codex = self.root / "codex.cmd"
        codex.write_text("", encoding="utf-8")
        payload = self.manifest_payload(
            codex_executable=codex,
            jobs=[
                {
                    "jobId": "runtime",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-07-30T08:34:00-05:00",
                    "latestStartAt": "2026-07-30T08:34:30-05:00",
                },
                {
                    "jobId": "review-one",
                    "kind": "codex_review",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:45:00-05:00",
                    "dependsOnJobId": "runtime",
                    "promptPath": str(prompt),
                },
                {
                    "jobId": "review-two",
                    "kind": "codex_review",
                    "scheduledAt": "2026-07-30T08:50:00-05:00",
                    "latestStartAt": "2026-07-30T09:00:00-05:00",
                    "dependsOnJobId": "review-one",
                    "promptPath": str(prompt),
                },
            ],
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "depend directly on a runtime job",
        ):
            self.parse_payload(payload)

    def test_manifest_accepts_machine_checked_codex_output(self) -> None:
        prompt = self.repo / "prompt.txt"
        prompt.write_text("Return the readiness token.", encoding="utf-8")
        codex = self.root / "codex.exe"
        codex.write_text("", encoding="utf-8")
        payload = self.manifest_payload(
            codex_executable=codex,
            jobs=[
                {
                    "jobId": "runtime",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-07-30T08:34:00-05:00",
                    "latestStartAt": "2026-07-30T08:34:30-05:00",
                },
                {
                    "jobId": "review",
                    "kind": "codex_review",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:45:00-05:00",
                    "dependsOnJobId": "runtime",
                    "promptPath": str(prompt),
                    "expectedOutput": "CODEX_SERVICE_READY",
                },
            ],
        )

        manifest = self.parse_payload(payload)

        self.assertEqual(
            "CODEX_SERVICE_READY",
            manifest.jobs[1].expected_output,
        )

    def test_manifest_rejects_unsafe_codex_expected_output(self) -> None:
        prompt = self.repo / "prompt.txt"
        prompt.write_text("Return the readiness token.", encoding="utf-8")
        codex = self.root / "codex.exe"
        codex.write_text("", encoding="utf-8")
        payload = self.manifest_payload(
            codex_executable=codex,
            jobs=[
                {
                    "jobId": "runtime",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-07-30T08:34:00-05:00",
                    "latestStartAt": "2026-07-30T08:34:30-05:00",
                },
                {
                    "jobId": "review",
                    "kind": "codex_review",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:45:00-05:00",
                    "dependsOnJobId": "runtime",
                    "promptPath": str(prompt),
                    "expectedOutput": "run a command",
                },
            ],
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "uppercase machine token",
        ):
            self.parse_payload(payload)

    def test_codex_command_is_ephemeral_read_only_and_has_no_runtime_authority(
        self,
    ) -> None:
        prompt = self.repo / "prompt.txt"
        prompt.write_text("Inspect evidence only.", encoding="utf-8")
        codex = self.root / "codex.cmd"
        codex.write_text("", encoding="utf-8")
        review = self.job(
            kind="codex_review",
            prompt_path=prompt,
            depends_on_job_id="runtime",
        )
        supervisor = AutomationSupervisor(
            self.manifest(review, codex_executable=codex),
            clock=lambda: self.now,
            engine_host_probe=self.healthy_engine,
            job_executor=self.execute,
        )

        command = supervisor._codex_review_command(
            review,
            self.state_dir / "review.log",
        )

        self.assertEqual(str(codex), command[0])
        self.assertIn("exec", command)
        self.assertIn("--ephemeral", command)
        sandbox = command.index("--sandbox")
        self.assertEqual("read-only", command[sandbox + 1])
        joined = " ".join(command).lower()
        self.assertNotIn("armshadowselector", joined)
        self.assertNotIn("run_capture_job", joined)

    def test_codex_service_probe_requires_exact_expected_output(self) -> None:
        prompt = self.repo / "prompt.txt"
        prompt.write_text("Return the readiness token.", encoding="utf-8")
        codex = self.root / "codex.exe"
        codex.write_text("", encoding="utf-8")
        review = self.job(
            kind="codex_review",
            prompt_path=prompt,
            depends_on_job_id="runtime",
            expected_output="CODEX_SERVICE_READY",
        )
        supervisor = AutomationSupervisor(
            self.manifest(review, codex_executable=codex),
            clock=lambda: self.now,
            engine_host_probe=self.healthy_engine,
        )
        log_path = self.state_dir / "probe.log"
        log_path.parent.mkdir(parents=True)

        def write_output(
            _command: object,
            **_kwargs: object,
        ) -> tuple[int, str]:
            log_path.with_suffix(".final.txt").write_text(
                "WRONG_OUTPUT\n",
                encoding="utf-8",
            )
            return 0, "Job process exited with code 0."

        with patch.object(
            supervisor,
            "_run_process",
            side_effect=write_output,
        ):
            exit_code, detail = supervisor._execute_job(review, log_path)

        self.assertEqual(1, exit_code)
        self.assertIn("unexpected output", detail)

        log_path.with_suffix(".final.txt").write_text(
            "CODEX_SERVICE_READY\n",
            encoding="utf-8",
        )
        with patch.object(
            supervisor,
            "_run_process",
            return_value=(0, "Job process exited with code 0."),
        ):
            exit_code, detail = supervisor._execute_job(review, log_path)

        self.assertEqual(0, exit_code)
        self.assertIn("expected output", detail)

    def test_shadow_command_contains_one_arm_switch_and_no_order_command(
        self,
    ) -> None:
        bundle = self.repo / "MomentumHunterData" / "data" / "reports" / "bundle"
        bundle.mkdir(parents=True)
        definition = bundle.parent / "launch.xml"
        definition.write_text("<Task />", encoding="utf-8")
        job = self.job(
            kind="shadow_opening",
            expected_git_head="a" * 40,
            proof_bundle_path=bundle,
            task_definition_path=definition,
        )
        supervisor = self.supervisor(job)

        command = supervisor._shadow_opening_command(job)

        self.assertEqual(1, command.count("-ArmShadowSelector"))
        self.assertNotIn("--shadow-opening-proof-only", command)
        self.assertNotIn("submit", " ".join(command).lower())
        self.assertNotIn("cancel", " ".join(command).lower())

    def test_existing_final_receipt_survives_service_restart(self) -> None:
        job = self.job(kind="nonmarket_canary")
        first = self.supervisor(job)
        first.tick()
        second = self.supervisor(job)

        state = second.tick()

        self.assertEqual(["canary"], self.executed)
        self.assertEqual("COMPLETED", state.jobs["canary"].status)
        self.assertNotEqual(
            first.state.service_instance_id,
            second.state.service_instance_id,
        )

    def supervisor(self, *jobs: AutomationJob) -> AutomationSupervisor:
        return AutomationSupervisor(
            self.manifest(*jobs),
            clock=lambda: self.now,
            engine_host_probe=self.healthy_engine,
            job_executor=self.execute,
        )

    def running_state(
        self,
        job: AutomationJob,
        *,
        started_at: datetime,
    ) -> SupervisorState:
        return SupervisorState(
            service_started_at=started_at.isoformat(),
            jobs={
                job.job_id: JobReceipt(
                    job_id=job.job_id,
                    kind=job.kind,
                    status="RUNNING",
                    scheduled_at=job.scheduled_at.isoformat(),
                    latest_start_at=job.latest_start_at.isoformat(),
                    observed_at=started_at.isoformat(),
                    started_at=started_at.isoformat(),
                )
            },
        )

    def manifest(
        self,
        *jobs: AutomationJob,
        codex_executable: Path | None = None,
    ) -> AutomationManifest:
        return AutomationManifest(
            repository_root=self.repo,
            python_executable=self.python,
            powershell_executable=self.powershell,
            codex_executable=codex_executable,
            state_directory=self.state_dir,
            engine_host_state_directory=self.engine_dir,
            poll_interval_seconds=1,
            jobs=tuple(jobs),
            expected_account_ending="2573",
            expected_account_type="INDIVIDUAL_CASH",
        )

    def job(
        self,
        *,
        kind: str,
        job_id: str = "canary",
        scheduled_at: datetime | None = None,
        latest_start_at: datetime | None = None,
        enabled: bool = True,
        depends_on_job_id: str = "",
        expected_git_head: str = "",
        proof_bundle_path: Path | None = None,
        task_definition_path: Path | None = None,
        prompt_path: Path | None = None,
        expected_output: str = "",
    ) -> AutomationJob:
        scheduled = scheduled_at or self.now
        latest = latest_start_at or (
            scheduled + timedelta(seconds=5)
            if kind == "shadow_opening"
            else scheduled + timedelta(minutes=10)
        )
        return AutomationJob(
            job_id=job_id,
            kind=kind,
            scheduled_at=scheduled,
            latest_start_at=latest,
            enabled=enabled,
            depends_on_job_id=depends_on_job_id,
            expected_git_head=expected_git_head,
            proof_bundle_path=proof_bundle_path,
            task_definition_path=task_definition_path,
            prompt_path=prompt_path,
            expected_output=expected_output,
            timeout_seconds=30,
        )

    def execute(self, job: AutomationJob, _log_path: Path) -> tuple[int, str]:
        self.executed.append(job.job_id)
        return 0, "completed"

    @staticmethod
    def healthy_engine() -> dict[str, object]:
        return {
            "identity": {"transport": "loopback-tcp"},
            "health": {"state": "Healthy", "detail": "ready"},
        }

    def manifest_payload(
        self,
        *,
        jobs: list[dict[str, object]],
        codex_executable: Path | None = None,
    ) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "repositoryRoot": str(self.repo),
            "pythonExecutable": str(self.python),
            "powershellExecutable": str(self.powershell),
            "codexExecutable": str(codex_executable or ""),
            "stateDirectory": str(self.state_dir),
            "engineHostStateDirectory": str(self.engine_dir),
            "expectedAccountEnding": "2573",
            "expectedAccountType": "INDIVIDUAL_CASH",
            "pollIntervalSeconds": 1,
            "jobs": jobs,
        }

    def parse_payload(self, payload: dict[str, object]) -> AutomationManifest:
        path = self.root / "manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return parse_manifest(path)


if __name__ == "__main__":
    unittest.main()
