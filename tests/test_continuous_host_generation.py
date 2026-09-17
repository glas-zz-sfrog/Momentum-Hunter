from copy import deepcopy
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
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
        self.lifetime = patch.object(generation, "process_lifetime", side_effect=lambda pid, birth:
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

    @unittest.skipUnless(os.name == "nt", "Windows process lifetime metadata")
    def test_native_current_process_birth_and_invalid_pid(self):
        self.birth.stop()
        self.assertIsInstance(generation.process_birth(os.getpid()), int)
        self.assertIsNone(generation.process_birth(0))
        self.birth.start()
