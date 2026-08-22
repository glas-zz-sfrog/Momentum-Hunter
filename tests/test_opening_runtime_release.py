from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.automation_supervisor import parse_manifest
from momentum_hunter.opening_runtime_identity import OpeningRuntimeIdentityError
from momentum_hunter.opening_runtime_release import (
    MIGRATION_CONFIRMATION,
    _require_fresh_supervisor_state,
    migrate_future_openings,
    plan_future_opening_migration,
)


UTC = timezone.utc


class OpeningRuntimeReleaseMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repo"
        self.repository.mkdir()
        self.python = self.root / "python.exe"
        self.powershell = self.root / "powershell.exe"
        self.service_host = self.root / "service.exe"
        for path in (self.python, self.powershell, self.service_host):
            path.write_text("fixture", encoding="utf-8")
        self.state_directory = self.root / "state"
        self.engine_directory = self.root / "engine"
        self.engine_directory.mkdir()
        self.manifest_path = self.root / "manifest.json"
        self.state_path = self.root / "state.json"
        self.past = {
            "jobId": "opening-capture-20260821",
            "kind": "opening_capture",
            "scheduledAt": "2026-08-21T08:35:00-05:00",
            "latestStartAt": "2026-08-21T08:40:00-05:00",
            "enabled": True,
            "timeoutSeconds": 900,
            "expectedGitHead": "a" * 40,
        }
        self.future = {
            "jobId": "opening-capture-20260824",
            "kind": "opening_capture",
            "scheduledAt": "2026-08-24T08:35:00-05:00",
            "latestStartAt": "2026-08-24T08:40:00-05:00",
            "enabled": True,
            "timeoutSeconds": 900,
            "expectedGitHead": "a" * 40,
        }
        self.manifest = {
            "schemaVersion": 1,
            "repositoryRoot": str(self.repository),
            "pythonExecutable": str(self.python),
            "powershellExecutable": str(self.powershell),
            "codexExecutable": "",
            "stateDirectory": str(self.state_directory),
            "engineHostStateDirectory": str(self.engine_directory),
            "expectedAccountEnding": "2573",
            "expectedAccountType": "INDIVIDUAL_CASH",
            "pollIntervalSeconds": 1,
            "jobs": [self.past, self.future],
        }
        self.state = {
            "schema_version": 1,
            "jobs": {
                self.past["jobId"]: {"status": "FAILED"},
                self.future["jobId"]: {"status": "PENDING"},
            },
        }
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        self.now = datetime(2026, 8, 21, 22, 0, tzinfo=UTC)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_changes_only_future_pending_opening_and_preserves_history(self) -> None:
        migrated, eligible, changed = plan_future_opening_migration(
            self.manifest,
            self.state,
            now=self.now,
            service_host_executable=self.service_host,
            release_root=self.root / "release-root",
        )

        jobs = {job["jobId"]: job for job in migrated["jobs"]}
        self.assertEqual([self.future["jobId"]], eligible)
        self.assertEqual(eligible, changed)
        self.assertEqual(self.past, jobs[self.past["jobId"]])
        self.assertNotIn("expectedGitHead", jobs[self.future["jobId"]])
        self.assertEqual(
            "opening-capture",
            jobs[self.future["jobId"]]["approvedRuntimeChannel"],
        )

    def test_apply_is_atomic_validated_and_idempotent(self) -> None:
        first = migrate_future_openings(
            self.manifest_path,
            self.state_path,
            apply=True,
            confirmation=MIGRATION_CONFIRMATION,
            now=self.now,
            service_host_executable=self.service_host,
            release_root=self.root / "release-root",
        )
        installed = parse_manifest(self.manifest_path)
        history = next(job for job in installed.jobs if job.job_id == self.past["jobId"])
        future = next(job for job in installed.jobs if job.job_id == self.future["jobId"])

        self.assertEqual("MIGRATED", first["status"])
        self.assertTrue(first["mutationPerformed"])
        self.assertEqual("a" * 40, history.expected_git_head)
        self.assertEqual("", future.expected_git_head)
        self.assertEqual("opening-capture", future.approved_runtime_channel)
        first_bytes = self.manifest_path.read_bytes()

        second = migrate_future_openings(
            self.manifest_path,
            self.state_path,
            apply=True,
            confirmation=MIGRATION_CONFIRMATION,
            now=self.now,
            service_host_executable=self.service_host,
            release_root=self.root / "release-root",
        )

        self.assertEqual("ALREADY_MIGRATED", second["status"])
        self.assertFalse(second["mutationPerformed"])
        self.assertEqual(first_bytes, self.manifest_path.read_bytes())

    def test_apply_requires_confirmation_and_leaves_manifest_unchanged(self) -> None:
        original = self.manifest_path.read_bytes()

        with self.assertRaises(OpeningRuntimeIdentityError) as raised:
            migrate_future_openings(
                self.manifest_path,
                self.state_path,
                apply=True,
                confirmation="",
                now=self.now,
                service_host_executable=self.service_host,
                release_root=self.root / "release-root",
            )

        self.assertEqual("MIGRATION_CONFIRMATION_MISSING", raised.exception.code)
        self.assertEqual(original, self.manifest_path.read_bytes())

    def test_terminal_future_job_blocks_migration(self) -> None:
        self.state["jobs"][self.future["jobId"]]["status"] = "COMPLETED"

        with self.assertRaises(OpeningRuntimeIdentityError) as raised:
            plan_future_opening_migration(
                self.manifest,
                self.state,
                now=self.now,
                service_host_executable=self.service_host,
                release_root=self.root / "release-root",
            )

        self.assertEqual("MIGRATION_FUTURE_JOB_NOT_PENDING", raised.exception.code)

    def test_supervisor_state_must_be_timezone_aware_and_fresh(self) -> None:
        manifest = parse_manifest(self.manifest_path)
        now = datetime(2026, 8, 21, 22, 0, tzinfo=UTC)
        fresh = {"last_heartbeat_at": "2026-08-21T21:59:45+00:00"}

        self.assertEqual(
            datetime(2026, 8, 21, 21, 59, 45, tzinfo=UTC),
            _require_fresh_supervisor_state(manifest, fresh, now=now),
        )

        for heartbeat, expected in (
            ("2026-08-21T21:58:00+00:00", "SUPERVISOR_HEARTBEAT_STALE"),
            ("2026-08-21T22:01:00+00:00", "SUPERVISOR_HEARTBEAT_STALE"),
            ("2026-08-21T21:59:59", "SUPERVISOR_HEARTBEAT_INVALID"),
            ("not-a-time", "SUPERVISOR_HEARTBEAT_INVALID"),
        ):
            with self.subTest(heartbeat=heartbeat):
                with self.assertRaises(OpeningRuntimeIdentityError) as raised:
                    _require_fresh_supervisor_state(
                        manifest,
                        {"last_heartbeat_at": heartbeat},
                        now=now,
                    )
                self.assertEqual(expected, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
