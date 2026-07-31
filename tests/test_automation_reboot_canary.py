from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.automation_reboot_canary import (
    RebootCanaryError,
    build_reboot_canary_plan,
    verify_reboot_canary,
)


UTC = timezone.utc


class AutomationRebootCanaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.state_dir = self.root / "state"
        self.logs_dir = self.state_dir / "logs"
        self.logs_dir.mkdir(parents=True)
        self.python = self.root / "python.exe"
        self.powershell = self.root / "powershell.exe"
        self.python.touch()
        self.powershell.touch()
        self.prepared = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
        self.previous_boot = self.prepared - timedelta(hours=2)
        self.scheduled = self.prepared + timedelta(minutes=5)
        self.baseline_path = self.state_dir / "reboot-canary-baseline.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_preserves_terminal_jobs_and_adds_only_nonmarket_work(self) -> None:
        manifest = self.manifest(
            jobs=[
                {
                    "jobId": "installation-canary",
                    "kind": "nonmarket_canary",
                    "scheduledAt": (self.prepared - timedelta(days=1)).isoformat(),
                    "latestStartAt": self.prepared.isoformat(),
                    "enabled": True,
                    "timeoutSeconds": 60,
                }
            ]
        )
        state = self.state(
            jobs={
                "installation-canary": {
                    "status": "COMPLETED",
                }
            }
        )

        result = build_reboot_canary_plan(
            manifest,
            state,
            scheduled_at=self.scheduled,
            prepared_at=self.prepared,
            pre_reboot_boot_time=self.previous_boot,
            baseline_path=self.baseline_path,
        )

        jobs = result["manifest"]["jobs"]
        self.assertEqual(
            ["installation-canary", "reboot-canary-20260731T120500"],
            [job["jobId"] for job in jobs],
        )
        self.assertEqual("nonmarket_canary", jobs[-1]["kind"])
        self.assertEqual(0, result["summary"]["shadowJobsEnabled"])
        self.assertFalse(
            result["summary"]["serviceRestartRequiredDuringPreparation"]
        )
        self.assertTrue(result["summary"]["requiresReboot"])
        self.assertTrue(result["baseline"]["requiresNoInteractiveLogin"])
        self.assertEqual("UNAVAILABLE", result["baseline"]["orderTransmission"])

    def test_plan_adds_exact_response_codex_probe_when_configured(self) -> None:
        codex = self.root / "codex.exe"
        codex.touch()
        prompt = self.repo / "config" / "codex-service-canary-prompt.txt"
        prompt.parent.mkdir()
        prompt.write_text("CODEX_SERVICE_READY", encoding="utf-8")
        manifest = self.manifest(codex_executable=codex)

        result = build_reboot_canary_plan(
            manifest,
            self.state(),
            scheduled_at=self.scheduled,
            prepared_at=self.prepared,
            pre_reboot_boot_time=self.previous_boot,
            baseline_path=self.baseline_path,
        )

        codex_job = result["manifest"]["jobs"][-1]
        self.assertEqual("codex_review", codex_job["kind"])
        self.assertEqual(
            result["baseline"]["canaryJobId"],
            codex_job["dependsOnJobId"],
        )
        self.assertEqual("CODEX_SERVICE_READY", codex_job["expectedOutput"])
        self.assertEqual(
            codex_job["jobId"],
            result["baseline"]["codexProbeJobId"],
        )

    def test_plan_rejects_enabled_shadow_or_nonterminal_existing_job(self) -> None:
        shadow = {
            "jobId": "shadow-opening",
            "kind": "shadow_opening",
            "enabled": True,
        }
        with self.assertRaisesRegex(RebootCanaryError, "enabled Shadow"):
            self.plan(self.manifest(jobs=[shadow]), self.state())

        active = {
            "jobId": "still-running",
            "kind": "nonmarket_canary",
            "enabled": True,
        }
        with self.assertRaisesRegex(RebootCanaryError, "not terminal"):
            self.plan(
                self.manifest(jobs=[active]),
                self.state(jobs={"still-running": {"status": "RUNNING"}}),
            )

    def test_plan_requires_lead_time_and_expected_account_identity(self) -> None:
        with self.assertRaisesRegex(RebootCanaryError, "three minutes"):
            build_reboot_canary_plan(
                self.manifest(),
                self.state(),
                scheduled_at=self.prepared + timedelta(minutes=2),
                prepared_at=self.prepared,
                pre_reboot_boot_time=self.previous_boot,
                baseline_path=self.baseline_path,
            )
        manifest = self.manifest()
        manifest["expectedAccountEnding"] = "9999"
        with self.assertRaisesRegex(RebootCanaryError, "ending"):
            self.plan(manifest, self.state())

    def test_verify_accepts_rebooted_noninteractive_service_chain(self) -> None:
        manifest, state, baseline = self.valid_verification_evidence()

        result = verify_reboot_canary(
            manifest,
            state,
            baseline,
            current_boot_time=self.prepared + timedelta(minutes=1),
            service_status="Running",
            service_start_mode="Auto",
        )

        self.assertEqual("PASS", result["classification"])
        self.assertTrue(result["bootChanged"])
        self.assertTrue(result["serviceInstanceChanged"])
        self.assertTrue(result["serviceSessionIsNonInteractive"])
        self.assertEqual("Healthy", result["engineHostState"])
        self.assertEqual(0, result["shadowJobsEnabled"])
        self.assertEqual("UNAVAILABLE", result["orderTransmission"])

    def test_verify_rejects_old_boot_or_unchanged_service_instance(self) -> None:
        manifest, state, baseline = self.valid_verification_evidence()
        with self.assertRaisesRegex(RebootCanaryError, "No reboot"):
            verify_reboot_canary(
                manifest,
                state,
                baseline,
                current_boot_time=self.previous_boot,
                service_status="Running",
                service_start_mode="Auto",
            )

        state["service_instance_id"] = baseline["preRebootServiceInstanceId"]
        with self.assertRaisesRegex(RebootCanaryError, "instance did not change"):
            self.verify(manifest, state, baseline)

    def test_verify_rejects_interactive_session_or_broker_mutation(self) -> None:
        manifest, state, baseline = self.valid_verification_evidence()
        log_path = Path(state["jobs"][baseline["canaryJobId"]]["log_path"])
        canary_log = json.loads(log_path.read_text(encoding="utf-8"))
        canary_log["serviceSessionId"] = 2
        canary_log["serviceSessionIsNonInteractive"] = False
        log_path.write_text(json.dumps(canary_log), encoding="utf-8")
        with self.assertRaisesRegex(RebootCanaryError, "serviceSessionId"):
            self.verify(manifest, state, baseline)

        canary_log["serviceSessionId"] = 0
        canary_log["serviceSessionIsNonInteractive"] = True
        canary_log["interactiveUserSessionCount"] = 1
        log_path.write_text(json.dumps(canary_log), encoding="utf-8")
        with self.assertRaisesRegex(
            RebootCanaryError,
            "interactiveUserSessionCount",
        ):
            self.verify(manifest, state, baseline)

        canary_log["interactiveUserSessionCount"] = 0
        canary_log["ordersRequested"] = True
        log_path.write_text(json.dumps(canary_log), encoding="utf-8")
        with self.assertRaisesRegex(RebootCanaryError, "ordersRequested"):
            self.verify(manifest, state, baseline)

    def test_verify_rejects_early_run_manifest_tampering_or_missing_process(self) -> None:
        manifest, state, baseline = self.valid_verification_evidence()
        receipt = state["jobs"][baseline["canaryJobId"]]
        receipt["started_at"] = (
            self.scheduled - timedelta(seconds=1)
        ).isoformat()
        with self.assertRaisesRegex(RebootCanaryError, "proof window"):
            self.verify(manifest, state, baseline)

        manifest, state, baseline = self.valid_verification_evidence()
        manifest["jobs"][-1]["latestStartAt"] = (
            self.scheduled + timedelta(minutes=14)
        ).isoformat()
        with self.assertRaisesRegex(RebootCanaryError, "differs from baseline"):
            self.verify(manifest, state, baseline)

        manifest, state, baseline = self.valid_verification_evidence()
        log_path = Path(state["jobs"][baseline["canaryJobId"]]["log_path"])
        canary_log = json.loads(log_path.read_text(encoding="utf-8"))
        canary_log.pop("serviceProcessId")
        log_path.write_text(json.dumps(canary_log), encoding="utf-8")
        with self.assertRaisesRegex(RebootCanaryError, "serviceProcessId"):
            self.verify(manifest, state, baseline)

    def test_verify_rejects_failed_receipt_unhealthy_host_or_enabled_shadow(self) -> None:
        manifest, state, baseline = self.valid_verification_evidence()
        state["jobs"][baseline["canaryJobId"]]["status"] = "FAILED"
        with self.assertRaisesRegex(RebootCanaryError, "complete successfully"):
            self.verify(manifest, state, baseline)

        manifest, state, baseline = self.valid_verification_evidence()
        state["engine_host_state"] = "Failed"
        with self.assertRaisesRegex(RebootCanaryError, "not healthy"):
            self.verify(manifest, state, baseline)

        manifest, state, baseline = self.valid_verification_evidence()
        manifest["jobs"].append(
            {
                "jobId": "forbidden-shadow",
                "kind": "shadow_opening",
                "enabled": True,
            }
        )
        with self.assertRaisesRegex(RebootCanaryError, "enabled Shadow"):
            self.verify(manifest, state, baseline)

    def plan(
        self,
        manifest: dict[str, object],
        state: dict[str, object],
    ) -> dict[str, object]:
        return build_reboot_canary_plan(
            manifest,
            state,
            scheduled_at=self.scheduled,
            prepared_at=self.prepared,
            pre_reboot_boot_time=self.previous_boot,
            baseline_path=self.baseline_path,
        )

    def verify(
        self,
        manifest: dict[str, object],
        state: dict[str, object],
        baseline: dict[str, object],
    ) -> dict[str, object]:
        return verify_reboot_canary(
            manifest,
            state,
            baseline,
            current_boot_time=self.prepared + timedelta(minutes=1),
            service_status="Running",
            service_start_mode="Auto",
        )

    def valid_verification_evidence(
        self,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        plan = self.plan(self.manifest(), self.state())
        manifest = plan["manifest"]
        baseline = plan["baseline"]
        current_boot = self.prepared + timedelta(minutes=1)
        started = self.scheduled
        completed = started + timedelta(seconds=1)
        log_path = self.logs_dir / f"{baseline['canaryJobId']}.log"
        log_path.write_text(
            json.dumps(
                {
                    "mode": "NONMARKET_SERVICE_CANARY",
                    "dpapiBindingReadable": True,
                    "accountEnding": "2573",
                    "accountType": "INDIVIDUAL_CASH",
                    "accountBindingMatches": True,
                    "userProfileAvailable": True,
                    "engineHostState": "Healthy",
                    "positionsRequested": False,
                    "ordersRequested": False,
                    "orderTransmission": "UNAVAILABLE",
                    "serviceSessionId": 0,
                    "serviceSessionIsNonInteractive": True,
                    "interactiveUserSessionCount": 0,
                    "serviceProcessId": 4242,
                }
            ),
            encoding="utf-8",
        )
        state = self.state(
            service_instance_id="after-reboot-instance",
            service_started_at=current_boot + timedelta(seconds=2),
            jobs={
                baseline["canaryJobId"]: {
                    "kind": "nonmarket_canary",
                    "status": "COMPLETED",
                    "started_at": started.isoformat(),
                    "completed_at": completed.isoformat(),
                    "exit_code": 0,
                    "reason": (
                        "Nonmarket service canary completed without runtime mutation."
                    ),
                    "log_path": str(log_path),
                }
            },
        )
        return manifest, state, baseline

    def manifest(
        self,
        *,
        jobs: list[dict[str, object]] | None = None,
        codex_executable: Path | None = None,
    ) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "repositoryRoot": str(self.repo),
            "pythonExecutable": str(self.python),
            "powershellExecutable": str(self.powershell),
            "codexExecutable": str(codex_executable or ""),
            "stateDirectory": str(self.state_dir),
            "engineHostStateDirectory": str(self.root / "engine"),
            "expectedAccountEnding": "2573",
            "expectedAccountType": "INDIVIDUAL_CASH",
            "pollIntervalSeconds": 1,
            "jobs": jobs or [],
        }

    def state(
        self,
        *,
        jobs: dict[str, object] | None = None,
        service_instance_id: str = "before-reboot-instance",
        service_started_at: datetime | None = None,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "service_instance_id": service_instance_id,
            "service_started_at": (
                service_started_at or self.previous_boot + timedelta(seconds=5)
            ).isoformat(),
            "last_heartbeat_at": self.prepared.isoformat(),
            "engine_host_state": "Healthy",
            "engine_host_detail": "ready",
            "engine_host_observed_at": self.prepared.isoformat(),
            "jobs": jobs or {},
        }


if __name__ == "__main__":
    unittest.main()
