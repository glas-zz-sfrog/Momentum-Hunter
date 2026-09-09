from datetime import timedelta
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter.automation_preopen_guardian import inspect_readiness
from momentum_hunter.automation_state_recovery import digest, prospective_epoch
from momentum_hunter.opening_runtime_identity import file_sha256
from momentum_hunter.continuous_production import _write_runtime_status
from momentum_hunter.automation_supervisor import (
    parse_manifest, ManifestValidationError, AutomationSupervisor, AutomationSupervisorError,
)
from tests import test_automation_state_recovery as fixtures
from tests import test_automation_supervisor as supervisor_fixtures
from tests import test_opening_runtime_identity as opening_fixtures

NOW = fixtures.NOW


class GuardianTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RecoveryTests()
        self.fixture.setUp()
        self.root = self.fixture.root
        self.manifest = self.root / "manifest.json"
        self.continuous = self.root / "continuous.json"
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
        self.opening = opening_fixtures.OpeningRuntimeIdentityTests()
        self.opening.setUp()
        self.opening.context = replace(self.opening.context, state_directory=self.fixture.path.parent, poll_interval_seconds=1.0)
        release = self.opening.promote()
        self.release = release
        payload = json.loads(self.manifest.read_text())
        payload.update(repositoryRoot=str(self.opening.repository), pythonExecutable=str(self.opening.python),
            powershellExecutable=str(self.opening.powershell), serviceHostExecutable=str(self.opening.service_host),
            openingRuntimeReleaseRoot=str(self.opening.release_root),
            engineHostStateDirectory=str(self.opening.context.engine_host_state_directory), pollIntervalSeconds=1)
        self.manifest.write_text(json.dumps(payload))
        self.services = {name: {"Name": name, "State": "Running", "StartMode": "Auto", "StartName": "synthetic-user",
            "PathName": str(self.root / (name + ".exe"))} for name in (
                "MomentumHunterAutomation", "MomentumHunterContinuousRuntime", "MomentumHunterContinuousWriter")}
        config = {"mode": "RESEARCH_ONLY", "executionAuthority": "NONE", "orderCapability": "UNAVAILABLE",
            "positionsRequested": False, "ordersRequested": False, "runtimeStateRoot": str(self.root / "runtime"),
            "runtimeIdentity": "synthetic-continuous", "runtimeBuildHash": "b"*40,
            "configurationFingerprint": "c"*64, "activationStart": "2026-09-09T07:00:00-05:00"}
        self.continuous.write_text(json.dumps(config))
        self.status_path = self.root / "runtime" / "runtime-status.json"
        self.status_path.parent.mkdir()
        # Use the production serializer; no runtime construction or provider contact.
        _write_runtime_status(self.status_path, None, state="RUNNING", config=config)
        status = json.loads(self.status_path.read_text())
        status["health"] = {"last_heartbeat_at": NOW.isoformat(), "process_state": "RUNNING",
            "runtime_instance_id": "production-continuous-runtime-" + "1"*24, "stall_blocker": None, "stalled_since": None}
        self.write_status(status)
        self.observer = self.root / "automations" / "observer" / "automation.toml"
        self.observer.parent.mkdir(parents=True)
        self.observer.write_text('id = "argus-opening-authorized-release-observer"\nkind = "heartbeat"\nstatus = "ACTIVE"\n'
            'prompt = "strictly read-only mode=CURRENT_AUTHORIZED_RELEASE orderTransmission UNAVAILABLE executionAuthorityUsed false paperAuthorityUsed false"\n')
        self.expectations = {"schemaVersion": 1, "continuousAuthorityModel": "SEPARATE_CONTINUOUS_SERVICE",
            "services": json.loads(json.dumps(self.services)), "continuous": dict(config, files={str(self.opening.python): file_sha256(self.opening.python)}),
            "observer": {"path": str(self.observer), "sha256": digest(self.observer.read_bytes()),
                         "id": "argus-opening-authorized-release-observer"},
            "openingReleaseId": release["releaseId"], "openingReleaseFingerprint": release["releaseFingerprint"]}
        self.expectations["continuous"]["runtimeInstanceId"] = status["health"]["runtime_instance_id"]
        self.epoch = prospective_epoch(floor=NOW-timedelta(hours=1), first_session="2026-09-09",
            manifest_sha256=digest(self.manifest.read_bytes()), corrupt_sha256=digest(bytes(36072)))
        self.expectations["expectedEpochId"] = self.epoch["epochId"]
        self.fixture.store().save(self.state())

    def write_status(self, status):
        from momentum_hunter.continuous_production import _fingerprint
        status.pop("fingerprint", None)
        status["fingerprint"] = _fingerprint("production-continuous-runtime-status-v1", status)
        self.status_path.write_text(json.dumps(status))

    def tearDown(self):
        self.opening.tearDown()
        self.fixture.tearDown()

    def state(self, status="PENDING"):
        state = self.fixture.state(status)
        state.jobs["opening-capture-20260909"].approved_runtime_channel = "opening-capture"
        state.prospective_epoch = self.epoch
        state.recovery_floor_at = self.epoch["boundaryAt"]
        state.loaded_supervisor_sha256, state.loaded_runtime_identity_module_sha256, state.loaded_service_host_sha256 = self.opening.loaded_hashes(self.release)
        return state

    def inspect(self, **overrides):
        arguments = dict(manifest_path=self.manifest, state_path=self.fixture.path,
            continuous_path=self.continuous, expected_manifest_sha256=digest(self.manifest.read_bytes()) if self.manifest.exists() else "a"*64,
            expected_continuous_sha256=digest(self.continuous.read_bytes()) if self.continuous.exists() else "b"*64,
            canonical_head="a" * 40, origin_head="a" * 40, canonical_clean=True, expected_canonical="a" * 40,
            services=self.services, expectations=self.expectations, session_date="2026-09-09", now=NOW)
        arguments.update(overrides)
        with patch("momentum_hunter.opening_runtime_identity.probe_runtime_environment", return_value=self.opening.environment):
            return inspect_readiness(**arguments)

    def test_valid_fixture_green_real_separate_service_not_fake_job(self):
        result = self.inspect()
        self.assertEqual([], result["failedGates"])
        self.assertEqual("GREEN_READY", result["status"])
        self.assertNotIn("CONTINUOUS_JOB_PRESENT", result["gates"])
        self.assertTrue(result["continuousServicePresent"])

    def test_continuous_instance_identity_is_not_deployment_identity(self):
        expected = self.expectations["continuous"]
        self.assertNotEqual(expected["runtimeIdentity"], expected["runtimeInstanceId"])
        self.assertEqual("GREEN_READY", self.inspect()["status"])
        status = json.loads(self.status_path.read_text())
        status["health"]["runtime_instance_id"] = expected["runtimeIdentity"]
        self.write_status(status)
        self.assertFalse(self.inspect()["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_missing_bound_continuous_instance_fails_closed(self):
        self.expectations["continuous"].pop("runtimeInstanceId")
        self.assertFalse(self.inspect()["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

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
                    self.assertTrue(result["gates"]["OPENING_RECEIPT_COMPATIBLE"])
                    supervisor.tick()
                    self.assertEqual([job.job_id], calls)
                else:
                    expected = "JOB_DEFINITION_MISMATCH" if variant == "definition" else "JOB_IDENTITY_MISMATCH"
                    self.assertEqual(expected, result["errors"]["openingReceipt"])
                    with self.assertRaisesRegex(AutomationSupervisorError, expected):
                        supervisor.tick()
                    self.assertEqual([], calls)

    def test_manifest_missing_malformed_or_hash_mismatch_red(self):
        raw = self.manifest.read_bytes()
        self.assertEqual("RED_NOT_READY", self.inspect(expected_manifest_sha256="0"*64)["status"])
        for value in (None, b"broken-json"):
            if value is None:
                self.manifest.unlink()
            else:
                self.manifest.write_bytes(value)
            self.assertEqual("RED_NOT_READY", self.inspect()["status"])
        self.manifest.write_bytes(raw)

    def test_opening_absent_wrong_schedule_or_completed_red(self):
        raw = self.manifest.read_bytes()
        for change in ("absent", "schedule", "latest"):
            payload = json.loads(raw)
            if change == "absent":
                payload["jobs"] = []
            else:
                payload["jobs"][0]["scheduledAt" if change == "schedule" else "latestStartAt"] = (NOW+timedelta(minutes=1)).isoformat()
            self.manifest.write_text(json.dumps(payload))
            self.assertEqual("RED_NOT_READY", self.inspect()["status"])
        self.manifest.write_bytes(raw)
        self.fixture.store().save(self.state("COMPLETED"))
        self.assertEqual("RED_NOT_READY", self.inspect()["status"])

    def test_release_identity_bytes_loaded_hash_and_pointer_tamper_red(self):
        expected = self.expectations["openingReleaseId"]
        self.expectations["openingReleaseId"] = "OPENING-RUNTIME-" + "A"*20
        self.assertFalse(self.inspect()["gates"]["OPENING_RELEASE_IDENTITY_EXPECTED"])
        self.expectations["openingReleaseId"] = expected
        state = self.state()
        state.loaded_supervisor_sha256 = "0"*64
        self.fixture.store().save(state)
        self.assertFalse(self.inspect()["gates"]["OPENING_LOADED_BYTES_MATCH"])
        self.fixture.store().save(self.state())
        module = self.opening.repository / "momentum_hunter" / "automation_supervisor.py"
        module.write_bytes(module.read_bytes()+b"#tamper\n")
        self.assertFalse(self.inspect()["gates"]["OPENING_RUNTIME_BYTES_MATCH"])
        pointer = self.opening.release_root / "channels" / "opening-capture.json"
        pointer.write_bytes(b"{}")
        self.assertFalse(self.inspect()["gates"]["OPENING_AUTHORIZED_BINDING_VALID"])

    def test_missing_epoch_wrong_id_boundary_or_replay_red(self):
        raw = self.fixture.path.read_bytes()
        for mutation in ("missing", "id", "boundary", "replay", "floor"):
            state = json.loads(raw)
            if mutation == "missing":
                state.pop("prospective_epoch")
            elif mutation == "id":
                state["prospective_epoch"]["epochId"] = "invented"
            elif mutation == "boundary":
                state["prospective_epoch"]["boundaryAt"] = (NOW+timedelta(minutes=1)).isoformat()
            elif mutation == "replay":
                state["prospective_epoch"]["preEpochReplayBlocked"] = False
            else:
                state["recovery_floor_at"] = ""
            self.fixture.path.write_text(json.dumps(state))
            self.assertEqual("RED_NOT_READY", self.inspect()["status"], mutation)
        self.fixture.path.write_bytes(raw)
        self.expectations["expectedEpochId"] = "wrong"
        self.assertFalse(self.inspect()["gates"]["EPOCH_ID_VALID"])

    def test_service_missing_stopped_configuration_and_file_drift_red(self):
        baseline = json.loads(json.dumps(self.services))
        for name in baseline:
            for mutation in ("missing", "stopped", "configuration", "identity"):
                self.services = json.loads(json.dumps(baseline))
                if mutation == "missing":
                    self.services.pop(name)
                else:
                    field = {"stopped":"State", "configuration":"PathName", "identity":"StartName"}[mutation]
                    self.services[name][field] = "wrong"
                self.assertEqual("RED_NOT_READY", self.inspect()["status"], (name, mutation))
        self.services = baseline
        self.expectations["continuous"]["files"][str(self.opening.python)] = "0"*64
        self.assertFalse(self.inspect()["gates"]["CONTINUOUS_INSTALLED_BYTES_EXPECTED"])

    def test_continuous_config_identity_status_freshness_and_authority_red(self):
        config = self.continuous.read_bytes()
        wrong = json.loads(config)
        wrong["runtimeIdentity"] = "wrong"
        self.continuous.write_text(json.dumps(wrong))
        self.assertFalse(self.inspect()["gates"]["CONTINUOUS_RUNTIME_IDENTITY_EXPECTED"])
        self.continuous.write_bytes(config)
        baseline = json.loads(self.status_path.read_text())
        for variant in ("old", "future", "identity", "stalled", "stopped", "orders", "integrity"):
            status = json.loads(json.dumps(baseline))
            health = status["health"]
            if variant in ("old", "future"):
                health["last_heartbeat_at"] = (NOW+timedelta(seconds=121 if variant == "future" else -121)).isoformat()
            elif variant == "identity":
                health["runtime_instance_id"] = "wrong"
            elif variant == "stalled":
                health["stall_blocker"] = "writer unavailable"
            elif variant == "stopped":
                status["state"] = "STOPPED"
            elif variant == "orders":
                status["alpacaPaper"] = "AVAILABLE"
            self.write_status(status)
            if variant == "integrity":
                status["fingerprint"] = "0"*64
                self.status_path.write_text(json.dumps(status))
            self.assertEqual("RED_NOT_READY", self.inspect()["status"], variant)

    def test_observer_missing_wrong_identity_mutation_duplicate_red(self):
        raw = self.observer.read_bytes()
        self.observer.unlink()
        self.assertFalse(self.inspect()["gates"]["OBSERVER_CONFIGURATION_PRESENT"])
        self.observer.write_bytes(raw.replace(b"argus-opening-authorized-release-observer", b"impostor"))
        self.assertFalse(self.inspect()["gates"]["OBSERVER_EXPECTED_IDENTITY"])
        self.observer.write_bytes(raw)
        duplicate = self.observer.parent.parent / "duplicate" / "automation.toml"
        duplicate.parent.mkdir()
        duplicate.write_bytes(raw)
        self.assertFalse(self.inspect()["gates"]["OBSERVER_SINGLETON"])

    def test_green_inspection_is_readonly_and_no_runtime_or_provider_construction(self):
        before = {str(p): p.read_bytes() for root in (self.root, self.opening.root) for p in root.rglob("*") if p.is_file()}
        with patch("pathlib.Path.mkdir", side_effect=AssertionError("write")), \
             patch("momentum_hunter.automation_supervisor.AutomationSupervisor", side_effect=AssertionError("launch")), \
             patch("momentum_hunter.continuous_production.run_runtime", side_effect=AssertionError("launch")):
            result = self.inspect()
        self.assertEqual("GREEN_READY", result["status"])
        self.assertEqual(before, {str(p): p.read_bytes() for root in (self.root, self.opening.root) for p in root.rglob("*") if p.is_file()})
        self.assertEqual("FUTURE_PROVIDER_RESULTS_UNPROVEN", result["providerReadiness"])

    def test_past_latest_start_is_red_even_with_healthy_fixture(self):
        self.assertFalse(self.inspect(now=NOW+timedelta(minutes=6))["gates"]["OPENING_WINDOW_NOT_PASSED"])


if __name__ == "__main__":
    unittest.main()
