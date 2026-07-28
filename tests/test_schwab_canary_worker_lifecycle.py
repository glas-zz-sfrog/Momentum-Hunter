from __future__ import annotations

import ast
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import momentum_hunter.schwab_canary_broker_worker as worker_module
import momentum_hunter.schwab_canary_worker_lifecycle as lifecycle_module
from momentum_hunter.schwab_canary_broker_worker import (
    WORKER_BUILD_MANIFEST_FILENAME,
    WORKER_IDENTITY_FILENAME,
    WORKER_PROCESS_EVIDENCE_DIRECTORY,
    WORKER_STOP_ACK_FILENAME,
    WORKER_STOP_LATCH_FILENAME,
    CanaryBrokerWorkerLaunchContract,
    CanaryBrokerWorkerLaunchStore,
    CanaryWorkerStopAcknowledgementStore,
)
from momentum_hunter.schwab_canary_process_evidence import (
    CanaryProcessEvidenceStore,
)
from momentum_hunter.schwab_canary_process_observer import (
    PROCESS_NOT_FOUND,
    ProcessIdentitySnapshot,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CanaryStopLatchStore,
)
from momentum_hunter.schwab_canary_worker_identity import (
    CanaryWorkerIdentityStore,
)
from momentum_hunter.schwab_canary_worker_lifecycle import (
    CANARY_WORKER_LIFECYCLE_SCHEMA_VERSION,
    CANARY_WORKER_LIFECYCLE_STATUS,
    LIFECYCLE_CONTROLLER_ID,
    LIFECYCLE_OBSERVER_ID,
    LIFECYCLE_REVOCATION_MISSING,
    WORKER_LIFECYCLE_RESULT_FILENAME,
    CanaryWorkerLifecycleConflict,
    CanaryWorkerLifecycleError,
    CanaryWorkerLifecycleResult,
    CanaryWorkerLifecycleResultStore,
    run_canary_worker_lifecycle,
    worker_lifecycle_command,
)


UTC = timezone.utc
ACCOUNT_BINDING_COMMITMENT = "a" * 64
RUNTIME_INSTANCE_ID = "broker-worker-lifecycle-001"
BUILD_MANIFEST = b'{"build":"canary-lifecycle-real-v1"}\n'


class RecordingLauncher:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def launch(self, command, *, cwd):
        self.calls.append((command, cwd))
        raise AssertionError("Process launch was not expected.")


class AdvancingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 28, 15, 0, tzinfo=UTC)
        self.elapsed = 0.0

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds


class NeverRunningSource:
    source_id = "windows-limited-process-query-v1"

    def inspect(self, process_id: int) -> ProcessIdentitySnapshot:
        return ProcessIdentitySnapshot(
            process_id=process_id,
            state=PROCESS_NOT_FOUND,
        )


class CooperativeFakeChild:
    def __init__(self) -> None:
        self.pid = os.getpid() + 10_000
        self.returncode = None
        self.communicate_calls = 0

    def poll(self):
        return self.returncode

    def communicate(self, input=None, timeout=None):
        del input, timeout
        self.communicate_calls += 1
        self.returncode = 0
        return "", ""


class FakeChildLauncher:
    def __init__(self, child: CooperativeFakeChild) -> None:
        self.child = child
        self.calls = 0

    def launch(self, command, *, cwd):
        del command, cwd
        self.calls += 1
        return self.child


class CanaryWorkerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "lifecycle"
        self.root.mkdir()
        self.build_path = self.root / WORKER_BUILD_MANIFEST_FILENAME
        self.build_path.write_bytes(BUILD_MANIFEST)
        self.worker_path = Path(inspect.getfile(worker_module))
        self.worker_bytes = self.worker_path.read_bytes()
        self.launch = CanaryBrokerWorkerLaunchContract(
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            account_binding_commitment=ACCOUNT_BINDING_COMMITMENT,
            expected_worker_build_sha256=hashlib.sha256(
                BUILD_MANIFEST
            ).hexdigest(),
            expected_worker_artifact_sha256=hashlib.sha256(
                self.worker_bytes
            ).hexdigest(),
            poll_interval_milliseconds=20,
            startup_timeout_seconds=10,
            maximum_runtime_seconds=20,
        )
        CanaryBrokerWorkerLaunchStore(self.root).persist(self.launch)

    def test_command_uses_exact_base_interpreter_and_minimal_arguments(
        self,
    ) -> None:
        interpreter = Path(getattr(sys, "_base_executable"))
        command = worker_lifecycle_command(
            run_root=self.root,
        )
        rendered = " ".join(command)

        self.assertEqual(str(interpreter.resolve()), command[0])
        self.assertEqual(
            (
                "-B",
                "-m",
                "momentum_hunter.schwab_canary_broker_worker",
                "--run-root",
                str(self.root.resolve()),
            ),
            command[1:],
        )
        self.assertNotIn(ACCOUNT_BINDING_COMMITMENT, rendered)
        self.assertNotIn("2573", rendered)
        self.assertNotIn("token", rendered.lower())
        self.assertNotIn("secret", rendered.lower())

    def test_result_is_honest_nonauthorizing_and_write_once(self) -> None:
        result = self.synthetic_result()
        payload = result.to_dict()
        store = CanaryWorkerLifecycleResultStore(self.root)

        self.assertEqual(
            CANARY_WORKER_LIFECYCLE_SCHEMA_VERSION,
            payload["schemaVersion"],
        )
        self.assertEqual(
            CANARY_WORKER_LIFECYCLE_STATUS,
            payload["status"],
        )
        self.assertTrue(payload["localWorkerLifecycleVerified"])
        self.assertTrue(payload["runtimeAcknowledgementVerified"])
        self.assertTrue(payload["processStoppedVerified"])
        self.assertTrue(payload["workerProcessExited"])
        self.assertTrue(payload["processLaunchPerformed"])
        self.assertTrue(payload["processMutationPerformed"])
        self.assertFalse(payload["providerRevocationVerified"])
        self.assertTrue(payload["providerRevocationRequired"])
        self.assertFalse(payload["physicalStopDrillComplete"])
        self.assertFalse(payload["processTerminationPerformed"])
        self.assertFalse(payload["processSignalPerformed"])
        self.assertFalse(payload["providerEvidence"])
        self.assertFalse(payload["credentialAccessed"])
        self.assertFalse(payload["credentialMutationPerformed"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["realOrderApproval"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        self.assertEqual(
            [LIFECYCLE_REVOCATION_MISSING],
            payload["stopDrillFindingCodes"],
        )

        persisted = store.persist(result)
        original = store.path.read_bytes()
        duplicate = store.persist(result)
        self.assertEqual(result, persisted)
        self.assertEqual(result, duplicate)
        self.assertEqual(original, store.path.read_bytes())
        with self.assertRaises(CanaryWorkerLifecycleConflict):
            store.persist(
                replace(
                    result,
                    process_evidence_chain_sha256="f" * 64,
                )
            )
        self.assertEqual(original, store.path.read_bytes())

    def test_result_tamper_and_authority_escalation_fail_closed(
        self,
    ) -> None:
        store = CanaryWorkerLifecycleResultStore(self.root)
        store.persist(self.synthetic_result())
        payload = json.loads(store.path.read_text(encoding="ascii"))

        for field, value in (
            ("providerRevocationVerified", True),
            ("physicalStopDrillComplete", True),
            ("executionPermit", True),
            ("transmitting", True),
        ):
            with self.subTest(field=field):
                mutated = dict(payload)
                mutated[field] = value
                store.path.write_text(
                    json.dumps(mutated),
                    encoding="ascii",
                )
                with self.assertRaisesRegex(
                    CanaryWorkerLifecycleError,
                    "safety state",
                ):
                    store.load()
                store.path.write_text(
                    json.dumps(payload),
                    encoding="ascii",
                )

        payload["processEvidenceChainSha256"] = "e" * 64
        store.path.write_text(json.dumps(payload), encoding="ascii")
        with self.assertRaisesRegex(
            CanaryWorkerLifecycleError,
            "hash is invalid",
        ):
            store.load()

    def test_missing_or_mismatched_prerequisites_block_before_launch(
        self,
    ) -> None:
        cases: list[tuple[str, object]] = []

        missing_launch = self.make_root("missing-launch")
        cases.append(("launch contract is missing", missing_launch))

        missing_build = self.make_root(
            "missing-build",
            persist_launch=True,
        )
        (missing_build / WORKER_BUILD_MANIFEST_FILENAME).unlink()
        cases.append(("build manifest", missing_build))

        mismatched_build = self.make_root(
            "mismatched-build",
            persist_launch=True,
        )
        (
            mismatched_build / WORKER_BUILD_MANIFEST_FILENAME
        ).write_bytes(b"tampered")
        cases.append(("does not match", mismatched_build))

        wrong_artifact = self.make_root(
            "wrong-artifact",
            persist_launch=True,
            artifact_sha256="b" * 64,
        )
        cases.append(("artifact does not match", wrong_artifact))

        for message, root in cases:
            with self.subTest(message=message):
                launcher = RecordingLauncher()
                with self.assertRaisesRegex(
                    CanaryWorkerLifecycleError,
                    str(message),
                ):
                    run_canary_worker_lifecycle(
                        Path(root),
                        launcher=launcher,
                    )
                self.assertEqual([], launcher.calls)

    def test_existing_lifecycle_evidence_blocks_before_launch(self) -> None:
        evidence_paths = (
            self.root / WORKER_PROCESS_EVIDENCE_DIRECTORY,
            self.root / WORKER_IDENTITY_FILENAME,
            self.root / WORKER_STOP_LATCH_FILENAME,
            self.root / WORKER_STOP_ACK_FILENAME,
            self.root / WORKER_LIFECYCLE_RESULT_FILENAME,
        )
        for index, evidence_path in enumerate(evidence_paths):
            with self.subTest(evidence=evidence_path.name):
                root = self.make_root(
                    f"existing-evidence-{index}",
                    persist_launch=True,
                )
                target = root / evidence_path.name
                if evidence_path.name == (
                    WORKER_PROCESS_EVIDENCE_DIRECTORY
                ):
                    target.mkdir()
                else:
                    target.write_text("preserve", encoding="ascii")
                launcher = RecordingLauncher()
                with self.assertRaisesRegex(
                    CanaryWorkerLifecycleError,
                    "evidence already exists",
                ):
                    run_canary_worker_lifecycle(
                        root,
                        launcher=launcher,
                    )
                self.assertEqual([], launcher.calls)
                self.assertTrue(target.exists())

    def test_unobservable_child_gets_fail_closed_stop_without_termination(
        self,
    ) -> None:
        root = self.make_root(
            "unobservable-child",
            persist_launch=True,
        )
        launch_store = CanaryBrokerWorkerLaunchStore(root)
        launch = launch_store.load()
        assert launch is not None
        launch_store.path.unlink()
        launch_store.persist(
            replace(
                launch,
                startup_timeout_seconds=0.1,
                maximum_runtime_seconds=0.2,
            )
        )
        child = CooperativeFakeChild()
        launcher = FakeChildLauncher(child)

        with self.assertRaisesRegex(
            CanaryWorkerLifecycleError,
            "not captured in time",
        ):
            run_canary_worker_lifecycle(
                root,
                clock=AdvancingClock(),
                process_source=NeverRunningSource(),
                launcher=launcher,
            )
        stop_request = CanaryStopLatchStore(
            root / WORKER_STOP_LATCH_FILENAME
        ).load()

        self.assertEqual(1, launcher.calls)
        self.assertEqual(1, child.communicate_calls)
        self.assertEqual(0, child.returncode)
        self.assertIsNotNone(stop_request)
        assert stop_request is not None
        self.assertEqual(
            "SUPERVISOR_FAIL_CLOSED",
            stop_request.reason_code,
        )
        self.assertEqual(
            LIFECYCLE_CONTROLLER_ID,
            stop_request.controller_id,
        )
        self.assertFalse(
            (root / WORKER_LIFECYCLE_RESULT_FILENAME).exists()
        )

    def test_cli_failure_is_generic_and_does_not_echo_path(self) -> None:
        sensitive = (
            Path(self.temporary_directory.name)
            / "account-2573-client-secret"
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = lifecycle_module.main(
                ["--run-root", str(sensitive)]
            )

        self.assertEqual(2, exit_code)
        rendered = stderr.getvalue()
        self.assertIn("failed closed", rendered)
        self.assertNotIn(str(sensitive), rendered)
        self.assertNotIn("2573", rendered)
        self.assertNotIn("secret", rendered.lower())
        payload = json.loads(rendered)
        self.assertIsNone(payload["processLaunchPerformed"])
        self.assertIsNone(payload["processMutationPerformed"])

    @unittest.skipUnless(
        os.name == "nt",
        "Real lifecycle supervisor proof is Windows-specific.",
    )
    def test_cli_success_prints_sanitized_blocked_on_revocation_result(
        self,
    ) -> None:
        root = self.make_root(
            "cli-success",
            persist_launch=True,
        )
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = lifecycle_module.main(
                ["--run-root", str(root)]
            )
        payload = json.loads(stdout.getvalue())
        rendered = json.dumps(payload, sort_keys=True)

        self.assertEqual(0, exit_code)
        self.assertEqual(
            CANARY_WORKER_LIFECYCLE_STATUS,
            payload["status"],
        )
        self.assertEqual(
            [LIFECYCLE_REVOCATION_MISSING],
            payload["stopDrillFindingCodes"],
        )
        self.assertTrue(payload["localWorkerLifecycleVerified"])
        self.assertFalse(payload["providerRevocationVerified"])
        self.assertFalse(payload["physicalStopDrillComplete"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["transmitting"])
        self.assertNotIn(ACCOUNT_BINDING_COMMITMENT, rendered)
        self.assertNotIn(str(root), rendered)

    @unittest.skipUnless(
        os.name == "nt",
        "Real lifecycle supervisor proof is Windows-specific.",
    )
    def test_real_lifecycle_launches_binds_stops_and_remains_blocked(
        self,
    ) -> None:
        launch_before = (
            CanaryBrokerWorkerLaunchStore(self.root).path.read_bytes()
        )
        build_before = self.build_path.read_bytes()
        worker_before = self.worker_path.read_bytes()

        result = run_canary_worker_lifecycle(self.root)
        payload = result.to_dict()
        target = CanaryProcessEvidenceStore(
            self.root / WORKER_PROCESS_EVIDENCE_DIRECTORY
        ).load_target()
        records = CanaryProcessEvidenceStore(
            self.root / WORKER_PROCESS_EVIDENCE_DIRECTORY
        ).load_observations()
        identity = CanaryWorkerIdentityStore(
            self.root / WORKER_IDENTITY_FILENAME
        ).load()
        stop_request = CanaryStopLatchStore(
            self.root / WORKER_STOP_LATCH_FILENAME
        ).load()
        acknowledgement = CanaryWorkerStopAcknowledgementStore(
            self.root
        ).load()
        persisted = CanaryWorkerLifecycleResultStore(
            self.root
        ).load()

        self.assertEqual(result, persisted)
        self.assertEqual(
            CANARY_WORKER_LIFECYCLE_STATUS,
            result.to_dict()["status"],
        )
        self.assertEqual(
            (True, False),
            tuple(
                record.evidence.process_running for record in records
            ),
        )
        self.assertIsNotNone(target)
        self.assertIsNotNone(identity)
        self.assertIsNotNone(stop_request)
        self.assertIsNotNone(acknowledgement)
        assert target is not None
        assert identity is not None
        assert stop_request is not None
        assert acknowledgement is not None
        self.assertEqual(
            LIFECYCLE_OBSERVER_ID,
            target.observer_id,
        )
        self.assertEqual(
            LIFECYCLE_CONTROLLER_ID,
            stop_request.controller_id,
        )
        self.assertEqual(
            target.target_sha256,
            result.process_target_sha256,
        )
        self.assertEqual(
            identity.receipt_id,
            result.identity_receipt_id,
        )
        self.assertEqual(
            stop_request.record_sha256,
            result.stop_latch_sha256,
        )
        self.assertEqual(
            acknowledgement.acknowledgement_sha256,
            result.stop_acknowledgement_sha256,
        )
        self.assertEqual(
            [LIFECYCLE_REVOCATION_MISSING],
            payload["stopDrillFindingCodes"],
        )
        self.assertFalse(payload["providerRevocationVerified"])
        self.assertFalse(payload["physicalStopDrillComplete"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["transmitting"])
        rendered = json.dumps(payload, sort_keys=True)
        self.assertNotIn(ACCOUNT_BINDING_COMMITMENT, rendered)
        self.assertNotIn(str(target.process_id), rendered)
        self.assertNotIn(str(self.root), rendered)

        self.assertEqual(
            launch_before,
            CanaryBrokerWorkerLaunchStore(self.root).path.read_bytes(),
        )
        self.assertEqual(build_before, self.build_path.read_bytes())
        self.assertEqual(worker_before, self.worker_path.read_bytes())

    def test_runtime_module_has_only_bounded_process_launch_capability(
        self,
    ) -> None:
        source = inspect.getsource(lifecycle_module)
        tree = ast.parse(source)
        imported_roots: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    calls.add(node.func.id)

        self.assertTrue(
            imported_roots.isdisjoint(
                {
                    "requests",
                    "httpx",
                    "urllib",
                    "socket",
                    "psutil",
                    "signal",
                }
            )
        )
        self.assertTrue(
            calls.isdisjoint(
                {
                    "kill",
                    "terminate",
                    "send_signal",
                    "unlink",
                    "remove",
                    "revoke",
                    "preview_order",
                    "submit_order",
                    "replace_order",
                    "cancel_order",
                    "transmit_order",
                }
            )
        )
        self.assertEqual(1, source.count("subprocess.Popen("))
        self.assertIn("shell=False", source)
        self.assertIn("stdin=subprocess.DEVNULL", source)
        self.assertNotIn("/orders", source)
        self.assertNotIn("client_secret", source)
        self.assertNotIn("access_token", source)
        self.assertNotIn("refresh_token", source)

    def synthetic_result(self) -> CanaryWorkerLifecycleResult:
        return CanaryWorkerLifecycleResult(
            completed_at=datetime(
                2026,
                7,
                28,
                15,
                0,
                tzinfo=UTC,
            ).isoformat(),
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            worker_exit_code=0,
            identity_receipt_id="identity-receipt-001",
            process_target_sha256="b" * 64,
            process_evidence_chain_sha256="c" * 64,
            stop_latch_sha256="d" * 64,
            stop_acknowledgement_sha256="e" * 64,
        )

    def make_root(
        self,
        name: str,
        *,
        persist_launch: bool = False,
        artifact_sha256: str | None = None,
    ) -> Path:
        root = Path(self.temporary_directory.name) / name
        root.mkdir()
        (root / WORKER_BUILD_MANIFEST_FILENAME).write_bytes(
            BUILD_MANIFEST
        )
        if persist_launch:
            CanaryBrokerWorkerLaunchStore(root).persist(
                replace(
                    self.launch,
                    expected_worker_artifact_sha256=(
                        artifact_sha256
                        or self.launch.expected_worker_artifact_sha256
                    ),
                )
            )
        return root
if __name__ == "__main__":
    unittest.main()
