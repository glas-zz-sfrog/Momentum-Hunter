from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import tempfile
import threading
import unittest

import momentum_hunter.schwab_canary_process_evidence as evidence_module
from momentum_hunter.schwab_canary_process_evidence import (
    PROCESS_EVIDENCE_NOT_CREATED,
    PROCESS_EVIDENCE_RECORDED,
    PROCESS_EVIDENCE_TARGET_ONLY,
    PROCESS_OBSERVATIONS_DIRECTORY,
    PROCESS_TARGET_FILENAME,
    CanaryProcessEvidenceConflict,
    CanaryProcessEvidenceError,
    CanaryProcessEvidenceStore,
)
from momentum_hunter.schwab_canary_process_observer import (
    PROCESS_ACCESS_DENIED,
    PROCESS_NOT_FOUND,
    PROCESS_RUNNING,
    WINDOWS_PROCESS_OBSERVER_SOURCE,
    CanaryProcessLivenessEvidence,
    CanaryProcessTarget,
)


UTC = timezone.utc
PROCESS_CREATED_AT = datetime(2026, 7, 27, 20, 0, tzinfo=UTC)
TARGET_CAPTURED_AT = PROCESS_CREATED_AT + timedelta(seconds=5)
EXECUTABLE_COMMITMENT = "a" * 64


class CanaryProcessEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "process-evidence"
        self.store = CanaryProcessEvidenceStore(self.root)
        self.target = CanaryProcessTarget(
            observer_id="external-process-observer",
            source=WINDOWS_PROCESS_OBSERVER_SOURCE,
            runtime_instance_id="broker-worker-001",
            process_id=4242,
            process_created_at=PROCESS_CREATED_AT.isoformat(),
            executable_path_sha256=EXECUTABLE_COMMITMENT,
            captured_at=TARGET_CAPTURED_AT.isoformat(),
        )

    def test_target_is_write_once_loadable_and_inspectable(self) -> None:
        self.assertEqual(
            PROCESS_EVIDENCE_NOT_CREATED,
            self.store.inspect()["status"],
        )

        persisted = self.store.persist_target(self.target)
        original = self.store.target_path.read_bytes()
        duplicate = self.store.persist_target(self.target)
        inspection = self.store.inspect()

        self.assertEqual(self.target, persisted)
        self.assertEqual(self.target, duplicate)
        self.assertEqual(original, self.store.target_path.read_bytes())
        self.assertEqual(PROCESS_EVIDENCE_TARGET_ONLY, inspection["status"])
        self.assertEqual(self.target.target_sha256, inspection["targetSha256"])
        self.assertEqual(0, inspection["observationCount"])
        self.assertFalse(inspection["processMutationPerformed"])
        self.assertFalse(inspection["credentialMutationPerformed"])
        self.assertFalse(inspection["brokerActionAllowed"])
        self.assertFalse(inspection["transmitting"])
        self.assertEqual("UNAVAILABLE", inspection["orderTransmission"])

    def test_conflicting_target_is_rejected_without_overwrite(self) -> None:
        self.store.persist_target(self.target)
        original = self.store.target_path.read_bytes()
        conflict = replace(self.target, runtime_instance_id="other-worker")

        with self.assertRaises(CanaryProcessEvidenceConflict):
            self.store.persist_target(conflict)

        self.assertEqual(original, self.store.target_path.read_bytes())
        self.assertEqual(self.target, self.store.load_target())

    def test_observations_are_sequential_hash_linked_and_immutable(self) -> None:
        self.store.persist_target(self.target)
        running = self.running_evidence(seconds=6)
        stopped = self.stopped_evidence(seconds=10)

        first = self.store.append_observation(running)
        first_bytes = (
            self.store.observations_path / "000001.json"
        ).read_bytes()
        second = self.store.append_observation(stopped)
        records = self.store.load_observations()
        inspection = self.store.inspect()

        self.assertEqual((first, second), records)
        self.assertEqual(1, first.sequence)
        self.assertIsNone(first.previous_record_sha256)
        self.assertEqual(2, second.sequence)
        self.assertEqual(first.record_sha256, second.previous_record_sha256)
        self.assertEqual(
            first_bytes,
            (self.store.observations_path / "000001.json").read_bytes(),
        )
        self.assertEqual(PROCESS_EVIDENCE_RECORDED, inspection["status"])
        self.assertEqual(2, inspection["observationCount"])
        self.assertEqual(second.record_sha256, inspection["latestRecordSha256"])
        self.assertEqual(
            "TARGET_PROCESS_STOPPED",
            inspection["latestConclusion"],
        )
        self.assertFalse(inspection["latestProcessRunning"])

    def test_exact_duplicate_observation_is_byte_idempotent(self) -> None:
        self.store.persist_target(self.target)
        evidence = self.running_evidence(seconds=6)
        first = self.store.append_observation(evidence)
        path = self.store.observations_path / "000001.json"
        original = path.read_bytes()

        duplicate = self.store.append_observation(evidence)

        self.assertEqual(first, duplicate)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(1, len(tuple(self.store.observations_path.iterdir())))

    def test_target_is_required_and_identity_drift_is_rejected(self) -> None:
        evidence = self.running_evidence(seconds=6)
        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "target must be persisted",
        ):
            self.store.append_observation(evidence)

        self.store.persist_target(self.target)
        drifted = replace(evidence, runtime_instance_id="other-worker")
        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "does not match",
        ):
            self.store.append_observation(drifted)

        self.assertFalse(self.store.observations_path.exists())

    def test_observation_chronology_cannot_reverse(self) -> None:
        self.store.persist_target(self.target)
        self.store.append_observation(self.running_evidence(seconds=10))

        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "cannot move backward",
        ):
            self.store.append_observation(self.stopped_evidence(seconds=9))

        self.assertEqual(1, len(self.store.load_observations()))

    def test_conclusively_stopped_target_cannot_become_running(self) -> None:
        self.store.persist_target(self.target)
        self.store.append_observation(self.stopped_evidence(seconds=9))

        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "cannot become running",
        ):
            self.store.append_observation(self.running_evidence(seconds=10))

        self.assertEqual(1, len(self.store.load_observations()))

    def test_observation_cannot_predate_target_capture(self) -> None:
        self.store.persist_target(self.target)
        evidence = self.running_evidence(seconds=4)

        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "predates target capture",
        ):
            self.store.append_observation(evidence)

    def test_tampered_target_fails_closed_without_repair(self) -> None:
        self.store.persist_target(self.target)
        payload = json.loads(
            self.store.target_path.read_text(encoding="ascii")
        )
        payload["runtimeInstanceId"] = "tampered-worker"
        self.store.target_path.write_text(
            json.dumps(payload),
            encoding="ascii",
        )
        tampered = self.store.target_path.read_bytes()

        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "content or hash is invalid",
        ):
            self.store.load_target()
        with self.assertRaises(CanaryProcessEvidenceConflict):
            self.store.persist_target(self.target)

        self.assertEqual(tampered, self.store.target_path.read_bytes())

    def test_tampered_observation_breaks_the_chain_without_repair(self) -> None:
        self.store.persist_target(self.target)
        self.store.append_observation(self.running_evidence(seconds=6))
        path = self.store.observations_path / "000001.json"
        payload = json.loads(path.read_text(encoding="ascii"))
        payload["evidence"]["conclusion"] = "TAMPERED"
        path.write_text(json.dumps(payload), encoding="ascii")
        tampered = path.read_bytes()

        with self.assertRaises(CanaryProcessEvidenceError):
            self.store.load_observations()
        with self.assertRaises(CanaryProcessEvidenceError):
            self.store.append_observation(self.stopped_evidence(seconds=10))

        self.assertEqual(tampered, path.read_bytes())

    def test_gap_or_unexpected_directory_entry_fails_closed(self) -> None:
        self.store.persist_target(self.target)
        self.store.observations_path.mkdir()
        (self.store.observations_path / "000002.json").write_text(
            "{}",
            encoding="ascii",
        )

        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "contiguous sequence",
        ):
            self.store.load_observations()

    def test_partial_empty_and_oversize_records_fail_closed(self) -> None:
        self.root.mkdir()
        self.store.target_path.write_bytes(b"")
        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "invalid size",
        ):
            self.store.load_target()

        self.store.target_path.write_bytes(b"x" * 40_000)
        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "invalid size",
        ):
            self.store.load_target()

    def test_symlink_target_and_observations_directory_are_rejected(self) -> None:
        backing = Path(self.temporary_directory.name) / "backing.json"
        backing.write_text("{}", encoding="ascii")
        self.root.mkdir()
        try:
            self.store.target_path.symlink_to(backing)
        except OSError:
            self.skipTest("Creating a file symlink is unavailable.")

        with self.assertRaisesRegex(
            CanaryProcessEvidenceError,
            "non-symlink",
        ):
            self.store.load_target()

    def test_unavailable_observation_is_preserved_but_not_stop_proof(self) -> None:
        self.store.persist_target(self.target)
        evidence = self.unavailable_evidence(seconds=7)

        record = self.store.append_observation(evidence)

        self.assertIsNone(record.evidence.process_running)
        with self.assertRaisesRegex(ValueError, "cannot satisfy a stop drill"):
            record.evidence.to_stop_observation()

    def test_concurrent_competing_append_never_overwrites(self) -> None:
        self.store.persist_target(self.target)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []

        class BarrierStore(CanaryProcessEvidenceStore):
            def _load_observations_for_append(self, target):
                records = super()._load_observations_for_append(target)
                barrier.wait(timeout=5)
                return records

        def append(evidence: CanaryProcessLivenessEvidence) -> None:
            try:
                BarrierStore(self.root).append_observation(evidence)
            except CanaryProcessEvidenceConflict:
                outcomes.append("CONFLICT")
            else:
                outcomes.append("PERSISTED")

        threads = (
            threading.Thread(
                target=append,
                args=(self.running_evidence(seconds=6),),
            ),
            threading.Thread(
                target=append,
                args=(self.stopped_evidence(seconds=7),),
            ),
        )
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(["CONFLICT", "PERSISTED"], sorted(outcomes))
        records = self.store.load_observations()
        self.assertEqual(1, len(records))
        self.assertIn(
            records[0].evidence,
            (
                self.running_evidence(seconds=6),
                self.stopped_evidence(seconds=7),
            ),
        )

    def test_persisted_files_retain_no_raw_executable_path(self) -> None:
        self.store.persist_target(self.target)
        self.store.append_observation(self.running_evidence(seconds=6))
        rendered = b"".join(
            path.read_bytes()
            for path in (
                self.store.target_path,
                self.store.observations_path / "000001.json",
            )
        )

        self.assertNotIn(b"C:\\", rendered)
        self.assertNotIn(b"/usr/", rendered)
        self.assertIn(EXECUTABLE_COMMITMENT.encode("ascii"), rendered)
        self.assertIn(b'"rawExecutablePathRetained": false', rendered)

    def test_module_has_no_network_process_control_credential_or_order_capability(
        self,
    ) -> None:
        source = inspect.getsource(evidence_module)
        tree = ast.parse(source)
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        called_names = {
            (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }

        self.assertTrue(
            imported_roots.isdisjoint(
                {
                    "requests",
                    "httpx",
                    "urllib",
                    "socket",
                    "subprocess",
                    "psutil",
                    "signal",
                }
            )
        )
        self.assertTrue(
            called_names.isdisjoint(
                {
                    "kill",
                    "terminate",
                    "revoke",
                    "unlink",
                    "remove",
                    "clear",
                    "submit_order",
                    "replace_order",
                    "cancel_order",
                    "preview_order",
                    "transmit_order",
                }
            )
        )
        self.assertNotIn("schwab_setup", source)
        self.assertNotIn("schwab_onboarding", source)

    def running_evidence(
        self,
        *,
        seconds: int,
    ) -> CanaryProcessLivenessEvidence:
        return CanaryProcessLivenessEvidence(
            target_sha256=self.target.target_sha256,
            observer_id=self.target.observer_id,
            source=self.target.source,
            runtime_instance_id=self.target.runtime_instance_id,
            process_id=self.target.process_id,
            observed_at=(PROCESS_CREATED_AT + timedelta(seconds=seconds)).isoformat(),
            observation_state=PROCESS_RUNNING,
            process_running=True,
            pid_reused=False,
            observed_process_created_at=self.target.process_created_at,
            observed_executable_path_sha256=EXECUTABLE_COMMITMENT,
            conclusion="TARGET_PROCESS_RUNNING",
        )

    def stopped_evidence(
        self,
        *,
        seconds: int,
    ) -> CanaryProcessLivenessEvidence:
        return CanaryProcessLivenessEvidence(
            target_sha256=self.target.target_sha256,
            observer_id=self.target.observer_id,
            source=self.target.source,
            runtime_instance_id=self.target.runtime_instance_id,
            process_id=self.target.process_id,
            observed_at=(PROCESS_CREATED_AT + timedelta(seconds=seconds)).isoformat(),
            observation_state=PROCESS_NOT_FOUND,
            process_running=False,
            pid_reused=False,
            observed_process_created_at=None,
            observed_executable_path_sha256=None,
            conclusion="TARGET_PROCESS_STOPPED",
        )

    def unavailable_evidence(
        self,
        *,
        seconds: int,
    ) -> CanaryProcessLivenessEvidence:
        return CanaryProcessLivenessEvidence(
            target_sha256=self.target.target_sha256,
            observer_id=self.target.observer_id,
            source=self.target.source,
            runtime_instance_id=self.target.runtime_instance_id,
            process_id=self.target.process_id,
            observed_at=(PROCESS_CREATED_AT + timedelta(seconds=seconds)).isoformat(),
            observation_state=PROCESS_ACCESS_DENIED,
            process_running=None,
            pid_reused=False,
            observed_process_created_at=None,
            observed_executable_path_sha256=None,
            conclusion="PROCESS_LIVENESS_UNAVAILABLE",
        )


if __name__ == "__main__":
    unittest.main()
