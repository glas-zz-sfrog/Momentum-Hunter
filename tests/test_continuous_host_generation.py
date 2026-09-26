from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from momentum_hunter import continuous_host_generation as generation
from momentum_hunter.continuous_host_contract import science_custody_policy
from tests.test_continuous_host_boundaries import configuration


class GenerationBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="MH-H013B-Generations-")
        self.addCleanup(temporary.cleanup)
        self.config = configuration(Path(temporary.name))
        self.generations = {}
        self.exited = set()
        self.lifetime = patch.object(generation, "process_lifetime", side_effect=lambda pid, birth, **kwargs:
            "UNKNOWN" if type(pid) is not int or type(birth) is not int else
            "EXITED_PID_RECYCLED" if birth != pid * 100 else "EXITED" if pid in self.exited else "ALIVE")
        self.lifetime.start()
        self.addCleanup(self.lifetime.stop)
        self.birth = patch.object(generation, "process_birth", side_effect=lambda pid: pid * 100 if type(pid) is int and pid > 0 else None)
        self.birth.start()
        self.addCleanup(self.birth.stop)
        for index, role in enumerate(("writer", "runtime", "science"), 1):
            value = {"hostFingerprint": self.config["hostFingerprint"], "role": role,
                "generation": str(uuid.uuid4()), "supervisorPid": index, "supervisorBirth": index * 100,
                "childPid": index + 10, "childBirth": (index + 10) * 100, "phase": "RUNNING"}
            if role == "science":
                value = {key: item for key, item in value.items() if key not in ("supervisorPid", "supervisorBirth", "childPid", "childBirth")}
                value.update(executionModel=generation.SCM_DIRECT, servicePid=index, serviceBirth=index * 100)
            self.generations[role] = value
            generation.replace_status(generation.generation_path(self.config, role), value)
        for role in self.generations:
            self.health(role)

    def health(self, role, **changes):
        data = {"hostFingerprint": self.config["hostFingerprint"], "generation": self.generations[role]["generation"],
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "state": {"writer": "LISTENING", "runtime": "RUNNING", "science": "HEALTHY"}[role],
            "scienceCustody": {"state": "READY", "threadAlive": True, "stopRequested": False},
            "custodyBoundary": {"role": "science", "policySha256": science_custody_policy(self.config).policy_sha256,
                                "exactOwnerDaclLabelPolicyVerified": True},
            "v2Ready": True, "auditRequired": False,
            "dependencies": {key: self.generations[key]["generation"] for key in ("writer", "runtime")}, **changes}
        generation.replace_status(generation.status_path(self.config, role), data)

    def test_current_live_generations_ready(self):
        self.assertTrue(generation.aggregate_health(self.config)["ready"])

    def test_each_restarted_role_invalidates_previous_ready(self):
        for role in self.generations:
            old = deepcopy(self.generations[role])
            generation.replace_status(generation.generation_path(self.config, role), {**old, "generation": str(uuid.uuid4())})
            self.assertFalse(generation.aggregate_health(self.config)["ready"])
            generation.replace_status(generation.generation_path(self.config, role), old)

    def test_dead_or_recycled_parent_and_child_fail_closed(self):
        for role in self.generations:
            for field in (("serviceBirth",) if role == "science" else ("supervisorBirth", "childBirth")):
                old = deepcopy(self.generations[role])
                generation.replace_status(generation.generation_path(self.config, role), {**old, field: old[field] + 1})
                self.assertFalse(generation.aggregate_health(self.config)["ready"])
                generation.replace_status(generation.generation_path(self.config, role), old)

    def test_missing_null_or_wrong_generation_evidence_is_not_ready(self):
        for field in ("servicePid", "serviceBirth", "generation", "hostFingerprint"):
            old = self.generations["science"]
            generation.replace_status(generation.generation_path(self.config, "science"), {**old, field: None})
            self.assertFalse(generation.aggregate_health(self.config)["ready"])
            generation.replace_status(generation.generation_path(self.config, "science"), old)

    def test_science_recovering_degraded_failed_or_audit_required_not_ready(self):
        for state in ("STARTING", "RECOVERING", "DEGRADED", "AUDIT_REQUIRED", "FAILED", "DRAINING", "STOPPED"):
            self.health("science", state=state)
            self.assertFalse(generation.aggregate_health(self.config)["ready"])
        self.health("science", auditRequired=True)
        self.assertFalse(generation.aggregate_health(self.config)["ready"])

    def test_runtime_v2_and_writer_required(self):
        self.health("runtime", v2Ready=False)
        self.assertFalse(generation.aggregate_health(self.config)["ready"])
        self.health("runtime")
        self.health("writer", state="FAILED")
        self.assertFalse(generation.aggregate_health(self.config)["ready"])

    def test_science_policy_and_writer_worker_are_both_required(self):
        for change in ({}, {"role": "writer"}, {"policySha256": "f" * 64},
                       {"exactOwnerDaclLabelPolicyVerified": False}):
            value = {"role": "science", "policySha256": science_custody_policy(self.config).policy_sha256,
                     "exactOwnerDaclLabelPolicyVerified": True, **change} if change else {}
            self.health("science", custodyBoundary=value)
            self.assertFalse(generation.aggregate_health(self.config)["ready"])
        self.health("science")
        for worker in ({}, {"state": "STOP_PENDING", "threadAlive": True, "stopRequested": True},
                       {"state": "READY", "threadAlive": False, "stopRequested": False},
                       {"state": "FAILED", "threadAlive": False, "stopRequested": False}):
            self.health("writer", scienceCustody=worker)
            self.assertFalse(generation.aggregate_health(self.config)["ready"])

    def test_stale_or_future_clock_fails(self):
        for offset in (-60, 60):
            self.health("science", observedAt=(datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat())
            self.assertFalse(generation.aggregate_health(self.config)["ready"])

    def test_science_must_recover_current_upstream_generations(self):
        self.health("science", dependencies={"writer": "prior", "runtime": "prior"})
        self.assertFalse(generation.aggregate_health(self.config)["ready"])

    def finish(self, target_role, **changes):
        role = target_role
        parent = self.generations[role]
        generation.replace_status(generation.generation_path(self.config, role), {**parent,
            "phase": "RETURNED_PENDING_SERVICE_EXIT" if role == "science" else "EXITED"})
        if role == "science": self.exited.add(parent["servicePid"])
        upstream = {key: self.generations[key]["generation"] for key in
                    {"runtime": ("writer",), "science": ("writer", "runtime"), "writer": ()}[role]}
        generation.replace_status(Path(self.config["hostStateRoot"]) / role / "completion.json",
            {"hostFingerprint": self.config["hostFingerprint"], "generation": parent["generation"],
             "role": role,
             "exitCode": 0, "drainComplete": True, "cleanupComplete": True, "pendingWork": 0,
             "dependencies": upstream,
             **({key: parent[key] for key in ("executionModel", "servicePid", "serviceBirth")} if role == "science" else {}), **changes})

    def test_direct_service_cannot_fabricate_a_child(self):
        old = self.generations["science"]
        for extra in ({"childPid": old["servicePid"]}, {"supervisorPid": old["servicePid"]}, {"executionModel": "UNKNOWN"}):
            generation.replace_status(generation.generation_path(self.config, "science"), {**old, **extra})
            self.assertFalse(generation.aggregate_health(self.config)["ready"])

    def test_direct_return_does_not_prove_service_exit(self):
        self.finish("runtime")
        self.finish("science")
        self.exited.clear()
        self.assertFalse(generation.dependencies_drained(self.config, "writer"))
        with patch.object(generation, "process_lifetime", return_value="UNKNOWN"):
            self.assertFalse(generation.dependencies_drained(self.config, "writer"))
        self.exited.add(self.generations["science"]["servicePid"])
        self.assertTrue(generation.dependencies_drained(self.config, "writer"))

    def test_direct_completion_requires_exact_service_birth_and_model(self):
        self.finish("runtime")
        for extra in ({"serviceBirth": 1}, {"servicePid": 100}, {"executionModel": "CHILD"},
                      {"role": "runtime"}, {"childPid": 3}, {"supervisorBirth": 300}):
            self.finish("science", **extra)
            self.assertFalse(generation.dependencies_drained(self.config, "writer"))

    def test_early_science_and_writer_stop_must_wait(self):
        self.assertFalse(generation.dependencies_drained(self.config, "science"))
        self.assertFalse(generation.dependencies_drained(self.config, "writer"))
        self.finish("runtime")
        self.assertTrue(generation.dependencies_drained(self.config, "science"))
        self.assertFalse(generation.dependencies_drained(self.config, "writer"))
        self.finish("science")
        self.assertTrue(generation.dependencies_drained(self.config, "writer"))

    def test_incomplete_failure_timeout_pending_and_forced_exit_block_dependencies(self):
        for change in ({"exitCode": 2}, {"exitCode": 137}, {"pendingWork": 1},
                       {"publicationFailure": "PENDING"}, {"drainComplete": False}, {"cleanupComplete": False}):
            self.finish("runtime", **change)
            self.assertFalse(generation.dependencies_drained(self.config, "science"))

    def test_old_completions_do_not_satisfy_new_writer(self):
        self.finish("runtime")
        self.finish("science")
        self.assertTrue(generation.dependencies_drained(self.config, "writer"))
        generation.replace_status(generation.generation_path(self.config, "writer"),
            {**self.generations["writer"], "generation": str(uuid.uuid4())})
        self.assertFalse(generation.dependencies_drained(self.config, "writer"))

    def test_completion_before_actual_child_exit_rejected(self):
        self.finish("runtime")
        generation.replace_status(generation.generation_path(self.config, "runtime"), self.generations["runtime"])
        self.assertFalse(generation.dependencies_drained(self.config, "science"))

    def test_drain_observation_preserves_each_lifetime_decision_and_read_count(self):
        self.finish("runtime")
        self.finish("science")
        for state in ("ALIVE", "UNKNOWN", "EXITED", "EXITED_PID_RECYCLED"):
            def lifetime(pid, birth, *, observation=None):
                if observation is not None:
                    observation.update(pid=pid, birth=birth, state=state)
                return state
            with self.subTest(state=state), patch.object(generation, "process_lifetime", side_effect=lifetime), \
                 patch.object(generation, "read_record", wraps=generation.read_record) as read:
                plain = generation.dependencies_drained(self.config, "writer")
                plain_paths = [call.args[0] for call in read.call_args_list]
                read.reset_mock()
                observed = {}
                self.assertEqual(plain, generation.dependencies_drained(self.config, "writer", observation=observed))
                self.assertEqual(plain_paths, [call.args[0] for call in read.call_args_list])
                self.assertEqual(state, observed["science"]["processLifetime"]["state"])
                self.assertEqual(plain, observed["science"]["accepted"])
                self.assertTrue(observed["runtime"]["accepted"])
                self.assertEqual(self.generations["science"]["generation"], observed["science"]["generation"])
                json_safe = json.loads(json.dumps(observed))
                self.assertEqual(observed, json_safe)

    def test_drain_observation_preserves_short_circuit_and_rejects_stale_receipt(self):
        self.finish("runtime", generation=str(uuid.uuid4()))
        self.finish("science")
        observed = {}
        with patch.object(generation, "process_lifetime") as lifetime:
            self.assertFalse(generation.dependencies_drained(self.config, "writer", observation=observed))
        lifetime.assert_not_called()
        self.assertEqual({"runtime"}, set(observed))
        self.assertFalse(observed["runtime"]["accepted"])

    def test_drain_observation_preserves_receipt_guards(self):
        self.finish("runtime")
        for change in ({"exitCode": 2}, {"pendingWork": 1}, {"drainComplete": False},
                       {"cleanupComplete": False}, {"publicationFailure": "PENDING"},
                       {"hostFingerprint": "wrong"}, {"dependencies": {}}, {"serviceBirth": 1}):
            self.finish("science", **change)
            observed = {}
            with self.subTest(change=change):
                self.assertFalse(generation.dependencies_drained(self.config, "writer", observation=observed))
                self.assertFalse(observed["science"]["accepted"])

    def test_record_observation_distinguishes_native_read_failure_and_invalid_json(self):
        path = Path(self.config["hostStateRoot"]) / "science" / "completion.json"
        denied = PermissionError(13, "test denial")
        denied.winerror = 5
        for raw, error, state in ((None, denied, "READ_FAILED"), ("{", None, "READ_FAILED"),
                                  ("[]", None, "NOT_OBJECT"), ("{}", None, "READ_OBJECT")):
            observed = {}
            with patch.object(Path, "read_text", return_value=raw, side_effect=error) as read:
                self.assertEqual({}, generation.read_record(path, observation=observed))
            read.assert_called_once_with(encoding="utf-8")
            self.assertEqual(str(path), observed["path"])
            self.assertEqual(state, observed["state"])
            if error is not None:
                self.assertEqual(5, observed["winerror"])
                self.assertEqual("PermissionError", observed["exception"])

    @unittest.skipUnless(os.name == "nt", "Windows native API contract")
    def test_native_lifetime_observation_never_treats_access_denial_as_exit(self):
        self.lifetime.stop()
        self.addCleanup(self.lifetime.start)
        kernel = Mock()
        kernel.OpenProcess.return_value = 0
        for error, expected in ((5, "UNKNOWN"), (87, "EXITED")):
            with self.subTest(error=error), patch.object(generation.ctypes, "WinDLL", return_value=kernel), \
                 patch.object(generation.ctypes, "get_last_error", return_value=error):
                observed = {}
                self.assertEqual(expected, generation.process_lifetime(123, 456, observation=observed))
            self.assertEqual({"pid": 123, "birth": 456, "requestedAccess": 0x1000,
                              "state": expected, "operation": "OpenProcess", "winerror": error}, observed)
        kernel.CloseHandle.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows native API contract")
    def test_native_lifetime_observation_closes_acquired_handle_on_query_failure(self):
        self.lifetime.stop()
        self.addCleanup(self.lifetime.start)
        kernel = Mock()
        kernel.OpenProcess.return_value = 99
        kernel.GetProcessTimes.return_value = 0
        with patch.object(generation.ctypes, "WinDLL", return_value=kernel), \
             patch.object(generation.ctypes, "get_last_error", return_value=5):
            observed = {}
            self.assertEqual("UNKNOWN", generation.process_lifetime(123, 456, observation=observed))
        self.assertEqual("GetProcessTimes", observed["operation"])
        self.assertEqual(5, observed["winerror"])
        kernel.CloseHandle.assert_called_once_with(99)

    @unittest.skipUnless(os.name == "nt", "Windows process lifetime metadata")
    def test_native_current_process_birth_and_invalid_pid(self):
        self.birth.stop()
        self.assertIsInstance(generation.process_birth(os.getpid()), int)
        self.assertIsNone(generation.process_birth(0))
        self.birth.start()
