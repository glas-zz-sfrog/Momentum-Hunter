from __future__ import annotations

import errno
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
from momentum_hunter.opening_runtime_identity import (
    OpeningRuntimeGateResult,
    OpeningRuntimeIdentityError,
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

    def test_state_save_retries_transient_windows_replace_denial(self) -> None:
        path = self.state_dir / "automation-service-state.json"
        store = SupervisorStateStore(path)
        state = SupervisorState(service_started_at=self.now.isoformat())
        original_replace = Path.replace
        attempts = 0

        def replace_with_transient_denial(
            temporary: Path,
            destination: Path,
        ) -> Path:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                error = PermissionError(errno.EACCES, "Access is denied")
                error.winerror = 5
                raise error
            return original_replace(temporary, destination)

        with (
            patch.object(
                Path,
                "replace",
                autospec=True,
                side_effect=replace_with_transient_denial,
            ),
            patch("momentum_hunter.automation_supervisor.time.sleep") as sleep,
        ):
            store.save(state)

        self.assertEqual(3, attempts)
        self.assertEqual(2, sleep.call_count)
        stored = store.load(started_at=self.now)
        self.assertEqual(state.service_started_at, stored.service_started_at)
        self.assertEqual([], list(self.state_dir.glob("*.tmp")))

    def test_state_save_fails_closed_after_persistent_replace_denial(self) -> None:
        path = self.state_dir / "automation-service-state.json"
        path.parent.mkdir(parents=True)
        original = b'{"schema_version": 1, "jobs": {}}\n'
        path.write_bytes(original)
        store = SupervisorStateStore(path)
        denial = PermissionError(errno.EACCES, "Access is denied")
        denial.winerror = 5

        with (
            patch.object(Path, "replace", autospec=True, side_effect=denial) as replace,
            patch("momentum_hunter.automation_supervisor.time.sleep") as sleep,
            self.assertRaises(PermissionError),
        ):
            store.save(SupervisorState(service_started_at=self.now.isoformat()))

        self.assertEqual(20, replace.call_count)
        self.assertEqual(19, sleep.call_count)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual([], list(self.state_dir.glob("*.tmp")))

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
        self.assertIn("not relaunched", state.jobs["canary"].reason)

    def test_interrupted_job_is_not_relaunched_inside_start_window(self) -> None:
        job = self.job(
            kind="opening_capture",
            scheduled_at=self.now - timedelta(minutes=1),
            latest_start_at=self.now + timedelta(minutes=4),
        )
        SupervisorStateStore(
            self.state_dir / "automation-service-state.json"
        ).save(
            self.running_state(
                job,
                started_at=self.now - timedelta(minutes=1),
            )
        )

        state = self.supervisor(job).tick()

        self.assertEqual([], self.executed)
        self.assertEqual("FAILED", state.jobs["canary"].status)
        self.assertIn("could duplicate", state.jobs["canary"].reason)

    def test_interrupted_paper_job_recovers_idempotently_after_start_window(self) -> None:
        opening = self.job(
            kind="opening_capture",
            job_id="opening-capture-20260730",
            scheduled_at=self.now - timedelta(minutes=30),
            latest_start_at=self.now - timedelta(minutes=25),
        )
        paper = self.job(
            kind="paper_engineering",
            job_id="paper-engineering-20260730",
            scheduled_at=self.now - timedelta(minutes=30),
            latest_start_at=self.now - timedelta(minutes=15),
            depends_on_job_id=opening.job_id,
        )
        state = SupervisorState(
            service_started_at=(self.now - timedelta(minutes=30)).isoformat(),
            jobs={
                opening.job_id: JobReceipt(
                    job_id=opening.job_id,
                    kind=opening.kind,
                    status="COMPLETED",
                    scheduled_at=opening.scheduled_at.isoformat(),
                    latest_start_at=opening.latest_start_at.isoformat(),
                    observed_at=(self.now - timedelta(minutes=20)).isoformat(),
                    completed_at=(self.now - timedelta(minutes=20)).isoformat(),
                    exit_code=0,
                ),
                paper.job_id: JobReceipt(
                    job_id=paper.job_id,
                    kind=paper.kind,
                    status="RUNNING",
                    scheduled_at=paper.scheduled_at.isoformat(),
                    latest_start_at=paper.latest_start_at.isoformat(),
                    observed_at=(self.now - timedelta(minutes=20)).isoformat(),
                    started_at=(self.now - timedelta(minutes=20)).isoformat(),
                    depends_on_job_id=opening.job_id,
                ),
            },
        )
        SupervisorStateStore(
            self.state_dir / "automation-service-state.json"
        ).save(state)

        recovered = self.supervisor(opening, paper).tick()

        self.assertEqual([paper.job_id], self.executed)
        self.assertEqual("COMPLETED", recovered.jobs[paper.job_id].status)

    def test_slow_opening_capture_cannot_launch_paper_after_admission_window(self) -> None:
        opening = self.job(
            kind="opening_capture",
            job_id="opening-capture-20260730",
            scheduled_at=self.now,
            latest_start_at=self.now + timedelta(minutes=5),
        )
        paper = self.job(
            kind="paper_engineering",
            job_id="paper-engineering-20260730",
            scheduled_at=self.now,
            latest_start_at=self.now + timedelta(minutes=15),
            depends_on_job_id=opening.job_id,
        )
        current = self.now

        def clock() -> datetime:
            return current

        def execute(job: AutomationJob, _log_path: Path) -> tuple[int, str]:
            nonlocal current
            self.executed.append(job.job_id)
            if job.kind == "opening_capture":
                current += timedelta(minutes=16)
            return 0, "completed"

        supervisor = AutomationSupervisor(
            self.manifest(opening, paper),
            clock=clock,
            engine_host_probe=self.healthy_engine,
            job_executor=execute,
        )

        state = supervisor.tick()

        self.assertEqual([opening.job_id], self.executed)
        self.assertEqual("MISSED", state.jobs[paper.job_id].status)

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

    def test_opening_capture_runs_without_engine_host_dependency(self) -> None:
        job = self.job(kind="opening_capture")
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

        self.assertEqual(["canary"], self.executed)
        self.assertEqual("COMPLETED", state.jobs["canary"].status)
        self.assertEqual("Failed", state.engine_host_state)

    def test_failed_opening_does_not_block_next_market_day(self) -> None:
        monday = self.job(
            kind="opening_capture",
            job_id="opening-capture-20260803",
            scheduled_at=self.now,
            latest_start_at=self.now + timedelta(minutes=5),
        )
        tuesday_time = self.now + timedelta(days=1)
        tuesday = self.job(
            kind="opening_capture",
            job_id="opening-capture-20260804",
            scheduled_at=tuesday_time,
            latest_start_at=tuesday_time + timedelta(minutes=5),
        )
        current = self.now

        def execute(job: AutomationJob, _log_path: Path) -> tuple[int, str]:
            self.executed.append(job.job_id)
            return (1, "Monday failed") if job is monday else (0, "Tuesday completed")

        supervisor = AutomationSupervisor(
            self.manifest(monday, tuesday),
            clock=lambda: current,
            engine_host_probe=self.healthy_engine,
            job_executor=execute,
        )

        monday_state = supervisor.tick()
        current = tuesday_time
        tuesday_state = supervisor.tick()

        self.assertEqual(
            ["opening-capture-20260803", "opening-capture-20260804"],
            self.executed,
        )
        self.assertEqual("FAILED", monday_state.jobs[monday.job_id].status)
        self.assertEqual("COMPLETED", tuesday_state.jobs[tuesday.job_id].status)

    def test_opening_terminal_receipt_is_saved_before_later_probe_crash(self) -> None:
        job = self.job(kind="opening_capture")
        supervisor = AutomationSupervisor(
            self.manifest(job),
            clock=lambda: self.now,
            engine_host_probe=lambda: (_ for _ in ()).throw(
                SystemExit("simulated host-process interruption")
            ),
            job_executor=self.execute,
        )

        with self.assertRaises(SystemExit):
            supervisor.tick()

        stored = SupervisorStateStore(
            self.state_dir / "automation-service-state.json"
        ).load(started_at=self.now)
        self.assertEqual(["canary"], self.executed)
        self.assertEqual("COMPLETED", stored.jobs["canary"].status)
        self.assertEqual(0, stored.jobs["canary"].exit_code)

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
            patch(
                "momentum_hunter.automation_supervisor."
                "_current_process_session_id",
                return_value=0,
            ),
            patch(
                "momentum_hunter.automation_supervisor."
                "_interactive_user_session_count",
                return_value=0,
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
        self.assertEqual(0, receipt["serviceSessionId"])
        self.assertTrue(receipt["serviceSessionIsNonInteractive"])
        self.assertEqual(0, receipt["interactiveUserSessionCount"])

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

    def test_manifest_accepts_capture_only_opening_window(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260730",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:40:00-05:00",
                    "timeoutSeconds": 900,
                    "expectedGitHead": "a" * 40,
                }
            ]
        )

        manifest = self.parse_payload(payload)

        self.assertEqual("opening_capture", manifest.jobs[0].kind)
        self.assertEqual("a" * 40, manifest.jobs[0].expected_git_head)
        self.assertIsNone(manifest.jobs[0].proof_bundle_path)
        self.assertIsNone(manifest.jobs[0].task_definition_path)

    def test_manifest_accepts_bounded_paper_job_after_same_date_capture(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260730",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:40:00-05:00",
                    "timeoutSeconds": 900,
                    "expectedGitHead": "a" * 40,
                },
                {
                    "jobId": "paper-engineering-20260730",
                    "kind": "paper_engineering",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:50:00-05:00",
                    "timeoutSeconds": 25200,
                    "expectedGitHead": "a" * 40,
                    "dependsOnJobId": "opening-capture-20260730",
                },
            ]
        )

        manifest = self.parse_payload(payload)

        paper = manifest.jobs[1]
        self.assertEqual("paper_engineering", paper.kind)
        self.assertEqual("opening-capture-20260730", paper.depends_on_job_id)
        self.assertEqual(25200, paper.timeout_seconds)

    def test_manifest_accepts_bounded_successor_pass_pair(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260817",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:40:00-05:00",
                    "expectedGitHead": "a" * 40,
                },
                {
                    "jobId": "successor-setup-pass1-20260817",
                    "kind": "successor_setup_pass1",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:50:00-05:00",
                    "timeoutSeconds": 600,
                    "expectedGitHead": "a" * 40,
                    "dependsOnJobId": "opening-capture-20260817",
                },
                {
                    "jobId": "successor-setup-pass2-20260817",
                    "kind": "successor_setup_pass2",
                    "scheduledAt": "2026-08-17T15:05:00-05:00",
                    "latestStartAt": "2026-08-17T16:00:00-05:00",
                    "timeoutSeconds": 900,
                    "expectedGitHead": "a" * 40,
                    "dependsOnJobId": "successor-setup-pass1-20260817",
                },
            ]
        )

        manifest = self.parse_payload(payload)

        self.assertEqual(
            ("opening_capture", "successor_setup_pass1", "successor_setup_pass2"),
            tuple(job.kind for job in manifest.jobs),
        )

    def test_manifest_rejects_successor_pass_without_exact_dependency(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "canary",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:35:10-05:00",
                },
                {
                    "jobId": "successor-setup-pass1-20260817",
                    "kind": "successor_setup_pass1",
                    "scheduledAt": "2026-08-17T08:35:00-05:00",
                    "latestStartAt": "2026-08-17T08:50:00-05:00",
                    "timeoutSeconds": 600,
                    "expectedGitHead": "a" * 40,
                    "dependsOnJobId": "canary",
                },
            ]
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "same-date opening capture",
        ):
            self.parse_payload(payload)

    def test_manifest_rejects_paper_job_without_same_date_capture(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "canary",
                    "kind": "nonmarket_canary",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:40:00-05:00",
                },
                {
                    "jobId": "paper-engineering-20260730",
                    "kind": "paper_engineering",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:50:00-05:00",
                    "timeoutSeconds": 25200,
                    "expectedGitHead": "a" * 40,
                    "dependsOnJobId": "canary",
                },
            ]
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "same-date opening capture",
        ):
            self.parse_payload(payload)

    def test_manifest_rejects_opening_without_frozen_git_identity(self) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260730",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:40:00-05:00",
                }
            ]
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "full expectedGitHead",
        ):
            self.parse_payload(payload)

    def test_manifest_accepts_release_channel_opening_and_rejects_dual_identity(
        self,
    ) -> None:
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260730",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:40:00-05:00",
                    "approvedRuntimeChannel": "opening-capture",
                }
            ]
        )

        manifest = self.parse_payload(payload)

        self.assertEqual(
            "opening-capture",
            manifest.jobs[0].approved_runtime_channel,
        )
        self.assertEqual("", manifest.jobs[0].expected_git_head)

        payload["jobs"][0]["expectedGitHead"] = "a" * 40
        with self.assertRaisesRegex(ManifestValidationError, "exactly one"):
            self.parse_payload(payload)

    def test_manifest_rejects_opening_capture_authority_and_wide_window(
        self,
    ) -> None:
        authority = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260730",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:40:00-05:00",
                    "expectedGitHead": "a" * 40,
                    "proofBundlePath": str(self.repo),
                }
            ]
        )
        wide = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260730",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:40:01-05:00",
                }
            ]
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "cannot carry Shadow opening authority",
        ):
            self.parse_payload(authority)
        with self.assertRaisesRegex(
            ManifestValidationError,
            "five-minute start window",
        ):
            self.parse_payload(wide)

    def test_manifest_rejects_duplicate_opening_and_shadow_capture_date(
        self,
    ) -> None:
        bundle = self.repo / "MomentumHunterData" / "data" / "reports" / "bundle"
        bundle.mkdir(parents=True)
        definition = bundle.parent / "launch.xml"
        definition.write_text("<Task />", encoding="utf-8")
        payload = self.manifest_payload(
            jobs=[
                {
                    "jobId": "opening-capture-20260730",
                    "kind": "opening_capture",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:40:00-05:00",
                    "expectedGitHead": "a" * 40,
                },
                {
                    "jobId": "shadow-opening-20260730",
                    "kind": "shadow_opening",
                    "scheduledAt": "2026-07-30T08:35:00-05:00",
                    "latestStartAt": "2026-07-30T08:35:05-05:00",
                    "expectedGitHead": "a" * 40,
                    "proofBundlePath": str(bundle),
                    "taskDefinitionPath": str(definition),
                },
            ]
        )

        with self.assertRaisesRegex(
            ManifestValidationError,
            "cannot schedule both",
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

    def test_opening_capture_command_has_no_selector_or_broker_authority(
        self,
    ) -> None:
        supervisor = self.supervisor(self.job(kind="opening_capture"))

        command = supervisor._opening_capture_command()

        joined = " ".join(command).lower()
        self.assertIn("-session opening", joined)
        self.assertNotIn("shadow", joined)
        self.assertNotIn("selector", joined)
        self.assertNotIn("proof", joined)
        self.assertNotIn("account", joined)
        self.assertNotIn("position", joined)
        self.assertNotIn("order", joined)
        self.assertNotIn("submit", joined)
        self.assertNotIn("cancel", joined)

    def test_paper_command_is_exactly_paper_engineering_session(self) -> None:
        job = self.job(
            kind="paper_engineering",
            job_id="paper-engineering-20260730",
            depends_on_job_id="opening-capture-20260730",
            expected_git_head="a" * 40,
        )
        supervisor = self.supervisor(job)

        command = supervisor._paper_engineering_command(job)
        joined = " ".join(command)

        self.assertIn("momentum_hunter.alpaca_paper_engineering", joined)
        self.assertIn("run-session", command)
        self.assertIn("trade-plan-briefing-2026-07-30-opening.json", joined)
        self.assertNotIn("api.alpaca.markets", joined)
        self.assertNotIn("shadow", joined.lower())

    def test_successor_pass_one_runs_before_paper_and_failure_is_isolated(self) -> None:
        opening = self.job(
            kind="opening_capture",
            job_id="opening-capture-20260730",
            expected_git_head="a" * 40,
        )
        successor = self.job(
            kind="successor_setup_pass1",
            job_id="successor-setup-pass1-20260730",
            depends_on_job_id=opening.job_id,
            expected_git_head="a" * 40,
        )
        paper = self.job(
            kind="paper_engineering",
            job_id="paper-engineering-20260730",
            depends_on_job_id=opening.job_id,
            expected_git_head="a" * 40,
        )
        executions: list[str] = []

        def execute(job: AutomationJob, _log: Path) -> tuple[int, str]:
            executions.append(job.job_id)
            if job.kind == "successor_setup_pass1":
                return 1, "research failed closed"
            return 0, "completed"

        state = AutomationSupervisor(
            self.manifest(opening, paper, successor),
            clock=lambda: self.now,
            engine_host_probe=self.healthy_engine,
            job_executor=execute,
        ).tick()

        self.assertEqual(
            [opening.job_id, successor.job_id, paper.job_id],
            executions,
        )
        self.assertEqual("FAILED", state.jobs[successor.job_id].status)
        self.assertEqual("COMPLETED", state.jobs[paper.job_id].status)

    def test_successor_commands_are_offline_write_once_research_only(self) -> None:
        pass1 = self.job(
            kind="successor_setup_pass1",
            job_id="successor-setup-pass1-20260730",
            depends_on_job_id="opening-capture-20260730",
            expected_git_head="a" * 40,
        )
        pass2 = self.job(
            kind="successor_setup_pass2",
            job_id="successor-setup-pass2-20260730",
            scheduled_at=self.now.replace(hour=20, minute=5),
            latest_start_at=self.now.replace(hour=21, minute=0),
            depends_on_job_id=pass1.job_id,
            expected_git_head="a" * 40,
        )
        supervisor = self.supervisor(pass1, pass2)

        first = supervisor._successor_setup_pass1_command(pass1)
        second = supervisor._successor_setup_pass2_command(pass2)
        joined = " ".join((*first, *second)).lower()

        self.assertIn("momentum_hunter.successor_setup_observer", joined)
        self.assertIn("sample-charter.json", joined)
        self.assertIn("activation.json", joined)
        self.assertIn("pass1-2026-07-30.json", joined)
        self.assertIn("pass2-2026-07-30.json", joined)
        self.assertNotIn("alpaca", joined)
        self.assertNotIn("schwab_onboarding", joined)
        self.assertNotIn("order", joined)
        self.assertNotIn("submit", joined)
        self.assertNotIn("shadow", joined)

    def test_opening_execution_validates_frozen_repository_identity(self) -> None:
        job = self.job(kind="opening_capture", expected_git_head="a" * 40)
        supervisor = self.supervisor(job)
        log_path = self.state_dir / "opening.log"

        with (
            patch.object(supervisor, "_validate_repository_identity") as validate,
            patch.object(supervisor, "_run_process", return_value=(0, "ok")) as run,
        ):
            result = supervisor._execute_job(job, log_path)

        self.assertEqual((0, "ok"), result)
        validate.assert_called_once_with("a" * 40)
        run.assert_called_once()

    def test_opening_identity_failure_stops_before_capture_process(self) -> None:
        job = self.job(kind="opening_capture", expected_git_head="a" * 40)
        supervisor = self.supervisor(job)

        with (
            patch.object(
                supervisor,
                "_validate_repository_identity",
                side_effect=RuntimeError("unexpected canonical HEAD"),
            ),
            patch.object(supervisor, "_run_process") as run,
            self.assertRaisesRegex(RuntimeError, "unexpected canonical HEAD"),
        ):
            supervisor._execute_job(job, self.state_dir / "opening.log")

        run.assert_not_called()

    def test_approved_runtime_opening_records_release_and_current_git(self) -> None:
        job = self.job(
            kind="opening_capture",
            approved_runtime_channel="opening-capture",
        )
        gate = self.runtime_gate_result()
        supervisor = AutomationSupervisor(
            self.manifest(job),
            clock=lambda: self.now,
            engine_host_probe=self.healthy_engine,
            job_executor=self.execute,
            runtime_gate=lambda _job: gate,
        )

        state = supervisor.tick()

        receipt = state.jobs[job.job_id]
        self.assertEqual([job.job_id], self.executed)
        self.assertEqual("COMPLETED", receipt.status)
        self.assertEqual("APPROVED_RUNTIME_RELEASE", receipt.runtime_identity_mode)
        self.assertEqual("OPENING-RUNTIME-" + "1" * 20, receipt.approved_release_id)
        self.assertEqual("a" * 40, receipt.release_source_git_sha)
        self.assertEqual("b" * 40, receipt.current_git_sha_at_execution)
        self.assertTrue(receipt.runtime_match)

    def test_approved_runtime_failure_stops_before_job_executor(self) -> None:
        job = self.job(
            kind="opening_capture",
            approved_runtime_channel="opening-capture",
        )

        def reject(_job: AutomationJob) -> OpeningRuntimeGateResult:
            raise OpeningRuntimeIdentityError(
                "APPROVED_RUNTIME_MISMATCH",
                "fixture mismatch",
            )

        supervisor = AutomationSupervisor(
            self.manifest(job),
            clock=lambda: self.now,
            engine_host_probe=self.healthy_engine,
            job_executor=self.execute,
            runtime_gate=reject,
        )

        state = supervisor.tick()

        receipt = state.jobs[job.job_id]
        self.assertEqual([], self.executed)
        self.assertEqual("FAILED", receipt.status)
        self.assertFalse(receipt.runtime_match)
        self.assertEqual(
            "APPROVED_RUNTIME_MISMATCH",
            receipt.runtime_identity_failure_code,
        )

    def test_runtime_identity_canary_uses_service_boundary_without_provider(self) -> None:
        job = self.job(
            kind="runtime_identity_canary",
            approved_runtime_channel="opening-capture",
        )
        supervisor = AutomationSupervisor(
            self.manifest(job),
            clock=lambda: self.now,
            engine_host_probe=self.healthy_engine,
            runtime_gate=lambda _job: self.runtime_gate_result(),
        )

        state = supervisor.tick()

        receipt = state.jobs[job.job_id]
        evidence = json.loads(Path(receipt.log_path).read_text(encoding="utf-8"))
        self.assertEqual("COMPLETED", receipt.status)
        self.assertTrue(evidence["runtimeMatch"])
        self.assertFalse(evidence["providerRequested"])
        self.assertFalse(evidence["accountValuesRequested"])
        self.assertFalse(evidence["ordersRequested"])
        self.assertEqual("UNAVAILABLE", evidence["orderTransmission"])

    def test_hot_reload_accepts_jobs_only_and_rejects_runtime_change(self) -> None:
        first = self.job(kind="nonmarket_canary", job_id="first")
        second = self.job(kind="opening_capture", job_id="second")
        supervisor = self.supervisor(first)

        supervisor.replace_manifest(self.manifest(first, second))

        self.assertEqual(("first", "second"), tuple(
            job.job_id for job in supervisor.manifest.jobs
        ))
        changed = AutomationManifest(
            **{
                **self.manifest(first, second).__dict__,
                "expected_account_ending": "9999",
            }
        )
        with self.assertRaisesRegex(
            ManifestValidationError,
            "hot-reload jobs only",
        ):
            supervisor.replace_manifest(changed)

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
        approved_runtime_channel: str = "",
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
            approved_runtime_channel=approved_runtime_channel,
        )

    def execute(self, job: AutomationJob, _log_path: Path) -> tuple[int, str]:
        self.executed.append(job.job_id)
        return 0, "completed"

    @staticmethod
    def runtime_gate_result() -> OpeningRuntimeGateResult:
        return OpeningRuntimeGateResult(
            channel="opening-capture",
            release_id="OPENING-RUNTIME-" + "1" * 20,
            release_fingerprint="2" * 64,
            runtime_surface_fingerprint="3" * 64,
            configuration_fingerprint="4" * 64,
            environment_fingerprint="5" * 64,
            approved_runtime_fingerprint="6" * 64,
            release_source_git_sha="a" * 40,
            current_git_sha="b" * 40,
            current_worktree_clean=True,
            runtime_match=True,
        )

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
