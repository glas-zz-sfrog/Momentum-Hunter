from __future__ import annotations

import ast
from contextlib import redirect_stderr
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import momentum_hunter.schwab_canary_broker_worker as worker_module
from momentum_hunter.schwab_canary_broker_worker import (
    WORKER_BUILD_MANIFEST_FILENAME,
    WORKER_IDENTITY_FILENAME,
    WORKER_PRESTART_STOPPED,
    WORKER_PROCESS_EVIDENCE_DIRECTORY,
    WORKER_RUNTIME_TIMEOUT,
    WORKER_STARTUP_TIMEOUT,
    WORKER_STOPPED_ACKNOWLEDGED,
    WORKER_STOP_ACK_FILENAME,
    WORKER_STOP_LATCH_FILENAME,
    CanaryBrokerWorkerConflict,
    CanaryBrokerWorkerError,
    CanaryBrokerWorkerLaunchContract,
    CanaryBrokerWorkerLaunchStore,
    CanaryWorkerStopAcknowledgementRecord,
    CanaryWorkerStopAcknowledgementStore,
    run_canary_broker_worker,
)
from momentum_hunter.schwab_canary_process_evidence import (
    CanaryProcessEvidenceStore,
)
from momentum_hunter.schwab_canary_process_observer import (
    WINDOWS_PROCESS_OBSERVER_SOURCE,
    CanaryProcessTarget,
    WindowsProcessIdentitySource,
    capture_canary_process_target,
    observe_canary_process_target,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    RUNTIME_STOPPED,
    CanaryStopLatchStore,
    CanaryStopRequest,
)
from momentum_hunter.schwab_canary_worker_identity import (
    WORKER_IDENTITY_BOUND_STOPPED,
    CanaryWorkerIdentityPolicy,
    CanaryWorkerIdentityStore,
    evaluate_canary_worker_identity_binding,
)


UTC = timezone.utc
BASE_TIME = datetime(2026, 7, 28, 14, 0, tzinfo=UTC)
ACCOUNT_BINDING_COMMITMENT = "a" * 64
RUNTIME_INSTANCE_ID = "broker-worker-test-001"
BUILD_MANIFEST = b'{"build":"synthetic-broker-worker-v1"}\n'
SYNTHETIC_ARTIFACT = b"synthetic broker worker artifact\n"


class AdvancingClock:
    def __init__(self, now: datetime = BASE_TIME) -> None:
        self.current = now
        self.elapsed = 0.0
        self.on_sleep = None

    def now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds
        self.current += timedelta(seconds=seconds)
        if self.on_sleep is not None:
            self.on_sleep(self)


class CanaryBrokerWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "worker-run"
        self.root.mkdir()
        self.build_path = self.root / WORKER_BUILD_MANIFEST_FILENAME
        self.build_path.write_bytes(BUILD_MANIFEST)
        self.artifact_path = self.root / "synthetic-worker.py"
        self.artifact_path.write_bytes(SYNTHETIC_ARTIFACT)
        self.process_store = CanaryProcessEvidenceStore(
            self.root / WORKER_PROCESS_EVIDENCE_DIRECTORY
        )
        self.stop_store = CanaryStopLatchStore(
            self.root / WORKER_STOP_LATCH_FILENAME
        )
        self.launch = CanaryBrokerWorkerLaunchContract(
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            account_binding_commitment=ACCOUNT_BINDING_COMMITMENT,
            expected_worker_build_sha256=hashlib.sha256(
                BUILD_MANIFEST
            ).hexdigest(),
            expected_worker_artifact_sha256=hashlib.sha256(
                SYNTHETIC_ARTIFACT
            ).hexdigest(),
            poll_interval_milliseconds=10,
            startup_timeout_seconds=0.1,
            maximum_runtime_seconds=0.3,
        )
        CanaryBrokerWorkerLaunchStore(self.root).persist(self.launch)

    def test_launch_contract_is_bounded_and_grants_no_authority(self) -> None:
        payload = self.launch.to_dict()

        self.assertFalse(payload["executionEnabled"])
        self.assertFalse(payload["providerAccessAllowed"])
        self.assertFalse(payload["credentialAccessAllowed"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        with self.assertRaises(CanaryBrokerWorkerError):
            replace(self.launch, poll_interval_milliseconds=1)
        with self.assertRaises(CanaryBrokerWorkerError):
            replace(self.launch, startup_timeout_seconds=0)
        with self.assertRaises(CanaryBrokerWorkerError):
            replace(
                self.launch,
                startup_timeout_seconds=2,
                maximum_runtime_seconds=1,
            )

    def test_launch_store_is_write_once_idempotent_and_tamper_evident(
        self,
    ) -> None:
        store = CanaryBrokerWorkerLaunchStore(self.root)
        original = store.path.read_bytes()

        self.assertEqual(self.launch, store.persist(self.launch))
        self.assertEqual(original, store.path.read_bytes())
        with self.assertRaises(CanaryBrokerWorkerConflict):
            store.persist(
                replace(
                    self.launch,
                    expected_worker_artifact_sha256="b" * 64,
                )
            )
        self.assertEqual(original, store.path.read_bytes())

        payload = json.loads(store.path.read_text(encoding="ascii"))
        payload["providerAccessAllowed"] = True
        store.path.write_text(json.dumps(payload), encoding="ascii")
        tampered = store.path.read_bytes()
        with self.assertRaisesRegex(
            CanaryBrokerWorkerError,
            "safety metadata",
        ):
            store.load()
        with self.assertRaises(CanaryBrokerWorkerConflict):
            store.persist(self.launch)
        self.assertEqual(tampered, store.path.read_bytes())

    def test_stop_acknowledgement_is_write_once_and_non_authorizing(
        self,
    ) -> None:
        record = CanaryWorkerStopAcknowledgementRecord(
            latch_sha256="b" * 64,
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            account_binding_commitment=ACCOUNT_BINDING_COMMITMENT,
            acknowledged_at=BASE_TIME.isoformat(),
            worker_identity_receipt_sha256="c" * 64,
            process_target_sha256="d" * 64,
        )
        store = CanaryWorkerStopAcknowledgementStore(self.root)
        persisted = store.persist(record)
        payload = persisted.to_dict()

        self.assertEqual(record, store.load())
        self.assertEqual(RUNTIME_STOPPED, payload["state"])
        self.assertTrue(payload["executionDisabled"])
        self.assertEqual(0, payload["outstandingCommandCount"])
        self.assertFalse(payload["providerEvidence"])
        self.assertFalse(payload["processMutationPerformed"])
        self.assertFalse(payload["credentialAccessed"])
        self.assertFalse(payload["credentialMutationPerformed"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["realOrderApproval"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        self.assertEqual(
            record.latch_sha256,
            record.to_stop_acknowledgement().latch_sha256,
        )

        with self.assertRaises(CanaryBrokerWorkerConflict):
            store.persist(replace(record, latch_sha256="e" * 64))

    def test_worker_binds_identity_acknowledges_stop_and_returns_to_exit(
        self,
    ) -> None:
        target = self.persist_current_process_target()
        clock = AdvancingClock()
        latch_engaged = False

        def engage_latch(active_clock: AdvancingClock) -> None:
            nonlocal latch_engaged
            if latch_engaged:
                return
            latch_engaged = True
            self.stop_store.engage(
                self.stop_request(requested_at=active_clock.now())
            )

        clock.on_sleep = engage_latch
        result = run_canary_broker_worker(
            self.root,
            clock=clock,
            worker_artifact_path=self.artifact_path,
        )
        identity = CanaryWorkerIdentityStore(
            self.root / WORKER_IDENTITY_FILENAME
        ).load()
        acknowledgement = CanaryWorkerStopAcknowledgementStore(
            self.root
        ).load()

        self.assertEqual(WORKER_STOPPED_ACKNOWLEDGED, result.status)
        self.assertIsNotNone(identity)
        self.assertIsNotNone(acknowledgement)
        assert identity is not None
        assert acknowledgement is not None
        self.assertEqual(target.target_sha256, identity.process_target_sha256)
        self.assertEqual(
            identity.receipt_sha256,
            acknowledgement.worker_identity_receipt_sha256,
        )
        self.assertEqual(
            target.target_sha256,
            acknowledgement.process_target_sha256,
        )
        self.assertFalse(result.to_dict()["workerProcessExited"])
        self.assertTrue(result.to_dict()["workerProcessExitPending"])
        self.assertFalse(result.to_dict()["providerEvidence"])
        self.assertFalse(result.to_dict()["executionPermit"])
        self.assertFalse(result.to_dict()["transmitting"])

    def test_prestart_stop_is_acknowledged_without_identity_overclaim(
        self,
    ) -> None:
        self.stop_store.engage(
            self.stop_request(requested_at=BASE_TIME)
        )

        result = run_canary_broker_worker(
            self.root,
            clock=AdvancingClock(),
            worker_artifact_path=self.artifact_path,
        )
        acknowledgement = CanaryWorkerStopAcknowledgementStore(
            self.root
        ).load()

        self.assertEqual(WORKER_PRESTART_STOPPED, result.status)
        self.assertIsNone(result.identity_receipt_id)
        self.assertFalse(
            (self.root / WORKER_IDENTITY_FILENAME).exists()
        )
        self.assertIsNotNone(acknowledgement)
        assert acknowledgement is not None
        self.assertIsNone(
            acknowledgement.worker_identity_receipt_sha256
        )
        self.assertIsNone(acknowledgement.process_target_sha256)

    def test_startup_and_runtime_timeouts_are_bounded_and_do_not_ack(
        self,
    ) -> None:
        startup_clock = AdvancingClock()
        startup = run_canary_broker_worker(
            self.root,
            clock=startup_clock,
            worker_artifact_path=self.artifact_path,
        )

        self.assertEqual(WORKER_STARTUP_TIMEOUT, startup.status)
        self.assertGreater(startup_clock.elapsed, 0)
        self.assertLessEqual(startup_clock.elapsed, 0.12)
        self.assertFalse((self.root / WORKER_STOP_ACK_FILENAME).exists())

        other_root = self.make_run_root("runtime-timeout")
        self.persist_current_process_target(root=other_root)
        runtime_clock = AdvancingClock()
        runtime = run_canary_broker_worker(
            other_root,
            clock=runtime_clock,
            worker_artifact_path=other_root / "synthetic-worker.py",
        )

        self.assertEqual(WORKER_RUNTIME_TIMEOUT, runtime.status)
        self.assertGreater(runtime_clock.elapsed, 0)
        self.assertLessEqual(runtime_clock.elapsed, 0.32)
        self.assertTrue(
            (other_root / WORKER_IDENTITY_FILENAME).exists()
        )
        self.assertFalse(
            (other_root / WORKER_STOP_ACK_FILENAME).exists()
        )

    def test_worker_rejects_build_artifact_and_process_target_mismatches(
        self,
    ) -> None:
        self.build_path.write_bytes(b"tampered build")
        with self.assertRaisesRegex(
            CanaryBrokerWorkerError,
            "build manifest",
        ):
            run_canary_broker_worker(
                self.root,
                clock=AdvancingClock(),
                worker_artifact_path=self.artifact_path,
            )

        self.build_path.write_bytes(BUILD_MANIFEST)
        self.artifact_path.write_bytes(b"tampered artifact")
        with self.assertRaisesRegex(
            CanaryBrokerWorkerError,
            "artifact",
        ):
            run_canary_broker_worker(
                self.root,
                clock=AdvancingClock(),
                worker_artifact_path=self.artifact_path,
            )

        mismatch_root = self.make_run_root("target-mismatch")
        CanaryProcessEvidenceStore(
            mismatch_root / WORKER_PROCESS_EVIDENCE_DIRECTORY
        ).persist_target(
            self.synthetic_target(
                process_id=os.getpid() + 10_000,
                root=mismatch_root,
            )
        )
        with self.assertRaisesRegex(
            CanaryBrokerWorkerError,
            "does not match this worker",
        ):
            run_canary_broker_worker(
                mismatch_root,
                clock=AdvancingClock(),
                worker_artifact_path=mismatch_root / "synthetic-worker.py",
            )

    def test_worker_rejects_wrong_account_self_controller_and_future_stop(
        self,
    ) -> None:
        cases = (
            (
                replace(
                    self.stop_request(requested_at=BASE_TIME),
                    account_binding_commitment="b" * 64,
                ),
                "different account",
            ),
            (
                replace(
                    self.stop_request(requested_at=BASE_TIME),
                    controller_id=RUNTIME_INSTANCE_ID,
                ),
                "own independent stop controller",
            ),
            (
                self.stop_request(
                    requested_at=BASE_TIME + timedelta(seconds=1)
                ),
                "cannot predate",
            ),
        )
        for index, (request, message) in enumerate(cases):
            with self.subTest(message=message):
                root = self.make_run_root(f"bad-stop-{index}")
                CanaryStopLatchStore(
                    root / WORKER_STOP_LATCH_FILENAME
                ).engage(request)
                with self.assertRaisesRegex(
                    CanaryBrokerWorkerError,
                    message,
                ):
                    run_canary_broker_worker(
                        root,
                        clock=AdvancingClock(),
                        worker_artifact_path=(
                            root / "synthetic-worker.py"
                        ),
                    )
                self.assertFalse(
                    (root / WORKER_STOP_ACK_FILENAME).exists()
                )

    def test_malformed_symlink_and_oversize_evidence_fail_closed(
        self,
    ) -> None:
        launch_store = CanaryBrokerWorkerLaunchStore(self.root)
        launch_store.path.write_text("{", encoding="ascii")
        with self.assertRaisesRegex(
            CanaryBrokerWorkerError,
            "malformed",
        ):
            launch_store.load()

        oversize_root = self.make_run_root("oversize")
        ack_path = oversize_root / WORKER_STOP_ACK_FILENAME
        ack_path.write_bytes(b"x" * 32_769)
        with self.assertRaisesRegex(
            CanaryBrokerWorkerError,
            "invalid size",
        ):
            CanaryWorkerStopAcknowledgementStore(
                oversize_root
            ).load()

        link_root = Path(self.temporary_directory.name) / "linked-root"
        try:
            link_root.symlink_to(
                self.root,
                target_is_directory=True,
            )
        except OSError:
            return
        with self.assertRaisesRegex(
            CanaryBrokerWorkerError,
            "cannot be a symlink",
        ):
            CanaryBrokerWorkerLaunchStore(link_root).load()

    def test_cli_failure_is_generic_and_does_not_echo_sensitive_path(
        self,
    ) -> None:
        sensitive = (
            Path(self.temporary_directory.name)
            / "account-2573-client-secret"
        )
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = worker_module.main(
                ["--run-root", str(sensitive)]
            )

        self.assertEqual(2, exit_code)
        rendered = stderr.getvalue()
        self.assertIn("failed closed", rendered)
        self.assertNotIn(str(sensitive), rendered)
        self.assertNotIn("2573", rendered)
        self.assertNotIn("secret", rendered.lower())

    def test_runtime_module_has_no_provider_secret_process_control_or_order_surface(
        self,
    ) -> None:
        source = inspect.getsource(worker_module)
        tree = ast.parse(source)
        imported_roots: set[str] = set()
        called_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    called_names.add(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    called_names.add(node.func.id)

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
        self.assertNotIn("schwab_setup", source)
        self.assertNotIn("schwab_onboarding", source)
        self.assertNotIn("/orders", source)
        self.assertNotIn("client_secret", source)
        self.assertNotIn("access_token", source)
        self.assertNotIn("refresh_token", source)

    @unittest.skipUnless(
        os.name == "nt",
        "Real broker-worker lifecycle proof is Windows-specific.",
    )
    def test_real_child_lifecycle_is_bound_stopped_and_nontransmitting(
        self,
    ) -> None:
        root = self.make_real_child_root()
        account_commitment = "e" * 64
        runtime_instance_id = "broker-worker-real-001"
        artifact_path = Path(inspect.getfile(worker_module))
        build_manifest = (root / WORKER_BUILD_MANIFEST_FILENAME).read_bytes()
        artifact = artifact_path.read_bytes()
        launch = CanaryBrokerWorkerLaunchContract(
            runtime_instance_id=runtime_instance_id,
            account_binding_commitment=account_commitment,
            expected_worker_build_sha256=hashlib.sha256(
                build_manifest
            ).hexdigest(),
            expected_worker_artifact_sha256=hashlib.sha256(
                artifact
            ).hexdigest(),
            poll_interval_milliseconds=20,
            startup_timeout_seconds=15,
            maximum_runtime_seconds=30,
        )
        CanaryBrokerWorkerLaunchStore(root).persist(launch)
        worker_python = getattr(
            sys,
            "_base_executable",
            sys.executable,
        )
        command = [
            worker_python,
            "-B",
            "-m",
            "momentum_hunter.schwab_canary_broker_worker",
            "--run-root",
            str(root),
        ]
        self.assertNotIn(account_commitment, " ".join(command))
        child = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            source = WindowsProcessIdentitySource()
            process_store = CanaryProcessEvidenceStore(
                root / WORKER_PROCESS_EVIDENCE_DIRECTORY
            )
            target = capture_canary_process_target(
                observer_id="external-process-observer",
                runtime_instance_id=runtime_instance_id,
                process_id=child.pid,
                captured_at=datetime.now(UTC),
                source=source,
            )
            process_store.persist_target(target)
            identity_store = CanaryWorkerIdentityStore(
                root / WORKER_IDENTITY_FILENAME
            )
            identity = self.wait_for_identity(
                identity_store,
                child=child,
            )
            running = observe_canary_process_target(
                target,
                observed_at=datetime.now(UTC),
                source=source,
            )
            self.assertTrue(running.process_running)
            process_store.append_observation(running)

            stop_store = CanaryStopLatchStore(
                root / WORKER_STOP_LATCH_FILENAME
            )
            stop_request = CanaryStopRequest(
                latch_id="real-child-stop-001",
                controller_id="external-stop-controller",
                account_binding_commitment=account_commitment,
                requested_at=datetime.now(UTC).isoformat(),
                reason_code="TEST_LIFECYCLE_COMPLETE",
            )
            stop_store.engage(stop_request)
            stdout, stderr = child.communicate(timeout=15)

            self.assertEqual("", stderr)
            self.assertEqual(0, child.returncode)
            result = json.loads(stdout)
            self.assertEqual(
                WORKER_STOPPED_ACKNOWLEDGED,
                result["status"],
            )
            self.assertFalse(result["workerProcessExited"])
            self.assertTrue(result["workerProcessExitPending"])
            self.assertFalse(result["providerEvidence"])
            self.assertFalse(result["credentialAccessed"])
            self.assertFalse(result["brokerActionAllowed"])
            self.assertFalse(result["executionPermit"])
            self.assertFalse(result["transmitting"])
            self.assertEqual(
                "UNAVAILABLE",
                result["orderTransmission"],
            )

            stopped = observe_canary_process_target(
                target,
                observed_at=datetime.now(UTC),
                source=source,
            )
            self.assertFalse(stopped.process_running)
            process_store.append_observation(stopped)
            policy = CanaryWorkerIdentityPolicy(
                expected_worker_build_sha256=(
                    launch.expected_worker_build_sha256
                ),
                expected_worker_artifact_sha256=(
                    launch.expected_worker_artifact_sha256
                ),
                expected_account_binding_commitment=account_commitment,
                expected_executable_path_sha256=(
                    target.executable_path_sha256
                ),
                expected_observer_id=target.observer_id,
                expected_process_source=target.source,
            )
            binding = evaluate_canary_worker_identity_binding(
                identity_store=identity_store,
                process_store=process_store,
                policy=policy,
                evaluated_at=datetime.now(UTC),
            )
            acknowledgement = CanaryWorkerStopAcknowledgementStore(
                root
            ).load()

            self.assertEqual(
                WORKER_IDENTITY_BOUND_STOPPED,
                binding.status,
            )
            self.assertTrue(binding.identity_binding_verified)
            self.assertTrue(binding.stop_lifecycle_observed)
            self.assertFalse(
                binding.to_dict()["physicalStopDrillComplete"]
            )
            self.assertFalse(
                binding.to_dict()["providerRevocationVerified"]
            )
            self.assertIsNotNone(acknowledgement)
            assert acknowledgement is not None
            self.assertEqual(
                identity.receipt_sha256,
                acknowledgement.worker_identity_receipt_sha256,
            )
            self.assertEqual(
                target.target_sha256,
                acknowledgement.process_target_sha256,
            )
            self.assertEqual(
                stop_request.record_sha256,
                acknowledgement.latch_sha256,
            )
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)

    def persist_current_process_target(
        self,
        *,
        root: Path | None = None,
    ) -> CanaryProcessTarget:
        active_root = root or self.root
        target = self.synthetic_target(
            process_id=os.getpid(),
            root=active_root,
        )
        CanaryProcessEvidenceStore(
            active_root / WORKER_PROCESS_EVIDENCE_DIRECTORY
        ).persist_target(target)
        return target

    def synthetic_target(
        self,
        *,
        process_id: int,
        root: Path,
    ) -> CanaryProcessTarget:
        del root
        return CanaryProcessTarget(
            observer_id="synthetic-external-observer",
            source=WINDOWS_PROCESS_OBSERVER_SOURCE,
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            process_id=process_id,
            process_created_at=(
                BASE_TIME - timedelta(seconds=1)
            ).isoformat(),
            executable_path_sha256="f" * 64,
            captured_at=BASE_TIME.isoformat(),
        )

    def stop_request(
        self,
        *,
        requested_at: datetime,
    ) -> CanaryStopRequest:
        return CanaryStopRequest(
            latch_id="worker-stop-001",
            controller_id="external-stop-controller",
            account_binding_commitment=ACCOUNT_BINDING_COMMITMENT,
            requested_at=requested_at.isoformat(),
            reason_code="BOUNDED_TEST_COMPLETE",
        )

    def make_run_root(self, name: str) -> Path:
        root = Path(self.temporary_directory.name) / name
        root.mkdir()
        (root / WORKER_BUILD_MANIFEST_FILENAME).write_bytes(
            BUILD_MANIFEST
        )
        (root / "synthetic-worker.py").write_bytes(
            SYNTHETIC_ARTIFACT
        )
        CanaryBrokerWorkerLaunchStore(root).persist(self.launch)
        return root

    def make_real_child_root(self) -> Path:
        root = Path(self.temporary_directory.name) / "real-child"
        root.mkdir()
        (root / WORKER_BUILD_MANIFEST_FILENAME).write_bytes(
            b'{"build":"real-child-test"}\n'
        )
        return root

    def wait_for_identity(
        self,
        store: CanaryWorkerIdentityStore,
        *,
        child: subprocess.Popen[str],
    ):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            identity = store.load()
            if identity is not None:
                return identity
            if child.poll() is not None:
                stdout, stderr = child.communicate(timeout=1)
                self.fail(
                    "Worker exited before identity binding: "
                    f"popen_pid={child.pid!r}, "
                    f"stdout={stdout!r}, stderr={stderr!r}"
                )
            time.sleep(0.02)
        self.fail("Worker identity receipt was not created in time.")


if __name__ == "__main__":
    unittest.main()
