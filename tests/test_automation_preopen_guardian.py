from datetime import timedelta
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter.automation_preopen_guardian import inspect_readiness
from momentum_hunter.automation_state_recovery import digest
from momentum_hunter.automation_supervisor import (
    parse_manifest, ManifestValidationError, AutomationSupervisor, AutomationSupervisorError,
)
from tests import test_automation_state_recovery as fixtures
from tests import test_automation_supervisor as supervisor_fixtures

NOW = fixtures.NOW


class GuardianTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.manifest = self.root / "manifest.json"
        self.continuous = self.root / "continuous.json"
        self.fixture.store().save(self.state())
        for name in ("python.exe", "powershell.exe"):
            (self.root / name).write_bytes(b"synthetic executable placeholder")
        self.manifest.write_text(json.dumps({"schemaVersion": 1,
            "repositoryRoot": str(self.root), "pythonExecutable": str(self.root / "python.exe"),
            "powershellExecutable": str(self.root / "powershell.exe"),
            "engineHostStateDirectory": str(self.root / "engine"),
            "expectedAccountEnding": "0000", "expectedAccountType": "INDIVIDUAL_CASH",
            "stateDirectory": str(self.fixture.path.parent), "jobs": [
            {"jobId": "opening-capture-20260909", "kind": "opening_capture", "enabled": True,
             "approvedRuntimeChannel": "opening-capture",
             "scheduledAt": NOW.isoformat(), "latestStartAt": (NOW + timedelta(minutes=5)).isoformat()}]}))
        self.continuous.write_text(json.dumps({"mode": "RESEARCH_ONLY", "executionAuthority": "NONE",
            "orderCapability": "UNAVAILABLE", "positionsRequested": False, "ordersRequested": False}))

    def tearDown(self):
        self.fixture.tearDown()

    def state(self, status="PENDING"):
        state = self.fixture.state(status)
        state.jobs["opening-capture-20260909"].approved_runtime_channel = "opening-capture"
        return state

    def inspect(self):
        return inspect_readiness(manifest_path=self.manifest, state_path=self.fixture.path,
            continuous_path=self.continuous, expected_manifest_sha256=digest(self.manifest.read_bytes()),
            expected_continuous_sha256=digest(self.continuous.read_bytes()),
            canonical_head="a" * 40, origin_head="a" * 40, canonical_clean=True, expected_canonical="a" * 40,
            services={"MomentumHunterAutomation": "Running", "MomentumHunterContinuousRuntime": "Running"},
            session_date="2026-09-09", now=NOW - timedelta(seconds=0))

    def test_exact_separate_continuous_service_is_not_fake_scheduled_job(self):
        result = self.inspect()
        self.assertEqual(["CONTINUOUS_JOB_PRESENT"], result["failedGates"])
        self.assertEqual("RED_NOT_READY", result["status"])
        self.assertTrue(result["continuousServicePresent"])

    def test_zero_state_can_be_reported_without_service_parser_or_mutation(self):
        self.fixture.corrupt()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch("momentum_hunter.automation_supervisor.SupervisorStateStore.load", side_effect=AssertionError("service parser")):
            result = self.inspect()
        self.assertEqual("RED_NOT_READY", result["status"])
        self.assertIn("STATE_SCHEMA_VALID", result["failedGates"])
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_no_generation_stale_heartbeat_paper_or_execution_rejected(self):
        state = self.state()
        state.last_heartbeat_at = (NOW - timedelta(minutes=10)).isoformat()
        self.fixture.store().save(state)
        manifest = json.loads(self.manifest.read_text())
        manifest["jobs"].append({"jobId": "paper", "kind": "paper_engineering", "enabled": True})
        self.manifest.write_text(json.dumps(manifest))
        continuous = json.loads(self.continuous.read_text())
        continuous["orderCapability"] = "AVAILABLE"
        self.continuous.write_text(json.dumps(continuous))
        result = self.inspect()
        self.assertFalse(result["gates"]["STATE_HEARTBEAT_CURRENT"])
        self.assertFalse(result["gates"]["NO_PAPER_LIVE_AUTHORITY"])

    def test_duplicate_opening_and_wrong_latest_rejected(self):
        manifest = json.loads(self.manifest.read_text())
        manifest["jobs"].append(manifest["jobs"][0])
        self.manifest.write_text(json.dumps(manifest))
        self.assertFalse(self.inspect()["gates"]["OPENING_JOB_PRESENT"])

    def test_f4_matching_hash_does_not_admit_invalid_manifest(self):
        valid = json.loads(self.manifest.read_text())
        parse_manifest(self.manifest)
        mutations = [lambda p: p["jobs"].append(dict(p["jobs"][0], jobId="continuous-invented", kind="continuous_invented")),
                     lambda p: p.update(schemaVersion=9), lambda p: p.pop("repositoryRoot"),
                     lambda p: p["jobs"][0].pop("approvedRuntimeChannel")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                value = json.loads(json.dumps(valid))
                mutate(value)
                self.manifest.write_text(json.dumps(value))
                with self.assertRaises(ManifestValidationError):
                    parse_manifest(self.manifest)
                before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                with patch("momentum_hunter.automation_supervisor.AutomationSupervisor", side_effect=AssertionError("runtime")), \
                     patch("momentum_hunter.automation_supervisor.SupervisorStateStore.load", side_effect=AssertionError("service parser")):
                    result = self.inspect()
                self.assertTrue(result["gates"]["PRODUCTION_CONFIG_EXPECTED"])
                self.assertFalse(result["gates"]["MANIFEST_SCHEMA_VALID"])
                self.assertEqual("RED_NOT_READY", result["status"])
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_f3_orphan_completion_is_authority_and_running_is_not_ready(self):
        store = self.fixture.store()
        state = self.state("RUNNING")
        store.save(state)
        self.assertFalse(self.inspect()["gates"]["OPENING_NOT_IN_PROGRESS"])
        state.jobs["opening-capture-20260909"].status = "COMPLETED"
        state.jobs["opening-capture-20260909"].completed_at = NOW.isoformat()
        state.jobs["opening-capture-20260909"].exit_code = 0
        retain = store.storage._retain
        def fail_new_generation(payload):
            if payload.get("state_version", 0) > state.state_version:
                raise OSError("after claim before new generation")
            retain(payload)
        with patch.object(store.storage, "_retain", side_effect=fail_new_generation):
            with self.assertRaises(OSError):
                store.save(state)
        self.assertEqual("RUNNING", json.loads(self.fixture.path.read_text())["jobs"]["opening-capture-20260909"]["status"])
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = self.inspect()
        self.assertFalse(result["gates"]["OPENING_NOT_ALREADY_TERMINAL"])
        self.assertFalse(result["gates"]["STATE_RECONCILIATION_HEALTHY"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_f5_guardian_matches_runtime_receipt_identity_contract(self):
        variants = ("valid", "schedule", "latest", "channel", "definition", "legacy", "legacy_bad")
        for variant in variants:
            with self.subTest(variant=variant):
                self.fixture.path = self.root / variant / "state" / "automation-service-state.json"
                value = json.loads(self.manifest.read_text())
                value["stateDirectory"] = str(self.fixture.path.parent)
                self.manifest.write_text(json.dumps(value))
                manifest = parse_manifest(self.manifest)
                job = manifest.jobs[0]
                old_job = job
                if variant in ("schedule", "legacy_bad"):
                    old_job = replace(job, scheduled_at=job.scheduled_at - timedelta(minutes=1))
                elif variant == "latest":
                    old_job = replace(job, latest_start_at=job.latest_start_at - timedelta(minutes=1))
                elif variant == "channel":
                    old_job = replace(job, approved_runtime_channel="")
                elif variant == "definition":
                    old_job = replace(job, timeout_seconds=job.timeout_seconds - 1)
                state = self.state()
                state.jobs[job.job_id] = AutomationSupervisor._receipt(old_job, NOW, "PENDING", "")
                if variant in ("legacy", "legacy_bad"):
                    state.jobs[job.job_id].job_definition_sha256 = ""
                self.fixture.store().save(state)
                before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                with patch("momentum_hunter.automation_supervisor.AutomationSupervisor", side_effect=AssertionError("runtime construction")), \
                     patch("momentum_hunter.automation_supervisor.SupervisorStateStore.load", side_effect=AssertionError("state parser")):
                    result = self.inspect()
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
                valid = variant in ("valid", "legacy")
                self.assertEqual(valid, result["gates"]["OPENING_RECEIPT_COMPATIBLE"])
                calls = []
                supervisor = AutomationSupervisor(manifest, clock=lambda: NOW, engine_host_probe=lambda: {},
                    job_executor=lambda j, p: (calls.append(j.job_id) or 0, "synthetic"),
                    runtime_gate=lambda j: supervisor_fixtures.AutomationSupervisorTests.runtime_gate_result())
                if valid:
                    self.assertEqual(["CONTINUOUS_JOB_PRESENT"], result["failedGates"])
                    supervisor.tick()
                    self.assertEqual([job.job_id], calls)
                else:
                    expected = "JOB_DEFINITION_MISMATCH" if variant == "definition" else "JOB_IDENTITY_MISMATCH"
                    self.assertEqual(expected, result["errors"]["openingReceipt"])
                    with self.assertRaisesRegex(AutomationSupervisorError, expected):
                        supervisor.tick()
                    self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
