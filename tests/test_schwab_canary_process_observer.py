from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
import os
import subprocess
import sys
import time
import unittest

import momentum_hunter.schwab_canary_process_observer as observer_module
from momentum_hunter.schwab_canary_process_observer import (
    PROCESS_ACCESS_DENIED,
    PROCESS_NOT_FOUND,
    PROCESS_QUERY_FAILED,
    PROCESS_RUNNING,
    PROCESS_UNSUPPORTED,
    WINDOWS_PROCESS_OBSERVER_SOURCE,
    CanaryProcessLivenessEvidence,
    CanaryProcessObserverError,
    ProcessIdentitySnapshot,
    WindowsProcessIdentitySource,
    capture_canary_process_target,
    observe_canary_process_target,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CREDENTIAL_REVOKED,
    RUNTIME_STOPPED,
    CanaryCredentialRevocationObservation,
    CanaryRuntimeStopAcknowledgement,
    CanaryStopDrillPolicy,
    CanaryStopRequest,
    evaluate_canary_stop_drill,
)


UTC = timezone.utc
CAPTURED_AT = datetime(2026, 7, 27, 21, 0, tzinfo=UTC)
OBSERVED_AT = CAPTURED_AT + timedelta(seconds=3)
CREATED_AT = CAPTURED_AT - timedelta(seconds=10)
PATH_COMMITMENT = "a" * 64
OTHER_PATH_COMMITMENT = "b" * 64
ACCOUNT_COMMITMENT = "c" * 64


class FakeProcessIdentitySource:
    source_id = WINDOWS_PROCESS_OBSERVER_SOURCE

    def __init__(self, *snapshots: ProcessIdentitySnapshot) -> None:
        self.snapshots = list(snapshots)
        self.calls: list[int] = []

    def inspect(self, process_id: int) -> ProcessIdentitySnapshot:
        self.calls.append(process_id)
        if not self.snapshots:
            raise AssertionError("No fake process snapshot remains.")
        return self.snapshots.pop(0)


class CanaryProcessObserverTests(unittest.TestCase):
    def running_snapshot(
        self,
        *,
        process_id: int = 90_001,
        created_at: datetime = CREATED_AT,
        executable_path_sha256: str = PATH_COMMITMENT,
    ) -> ProcessIdentitySnapshot:
        return ProcessIdentitySnapshot(
            process_id=process_id,
            state=PROCESS_RUNNING,
            created_at=created_at.isoformat(),
            executable_path_sha256=executable_path_sha256,
        )

    def capture(
        self,
        source: FakeProcessIdentitySource | None = None,
        *,
        process_id: int = 90_001,
    ):
        effective_source = source or FakeProcessIdentitySource(
            self.running_snapshot(process_id=process_id)
        )
        return capture_canary_process_target(
            observer_id="external-process-observer",
            runtime_instance_id="runtime-instance-001",
            process_id=process_id,
            captured_at=CAPTURED_AT,
            source=effective_source,
        )

    def test_exact_running_identity_reports_running_and_maps_to_stop_contract(
        self,
    ) -> None:
        target = self.capture()
        source = FakeProcessIdentitySource(self.running_snapshot())

        evidence = observe_canary_process_target(
            target,
            observed_at=OBSERVED_AT,
            source=source,
        )
        stop_observation = evidence.to_stop_observation()

        self.assertTrue(evidence.process_running)
        self.assertFalse(evidence.pid_reused)
        self.assertEqual("TARGET_PROCESS_RUNNING", evidence.conclusion)
        self.assertTrue(stop_observation.process_running)
        self.assertEqual(
            target.runtime_instance_id,
            stop_observation.runtime_instance_id,
        )

    def test_not_found_reports_stopped_and_maps_to_stop_contract(self) -> None:
        target = self.capture()
        source = FakeProcessIdentitySource(
            ProcessIdentitySnapshot(
                process_id=target.process_id,
                state=PROCESS_NOT_FOUND,
            )
        )

        evidence = observe_canary_process_target(
            target,
            observed_at=OBSERVED_AT,
            source=source,
        )
        stop_observation = evidence.to_stop_observation()

        self.assertFalse(evidence.process_running)
        self.assertFalse(evidence.pid_reused)
        self.assertEqual("TARGET_PROCESS_STOPPED", evidence.conclusion)
        self.assertFalse(stop_observation.process_running)

    def test_stopped_evidence_satisfies_canary005_process_requirement(
        self,
    ) -> None:
        target = self.capture()
        evidence = observe_canary_process_target(
            target,
            observed_at=OBSERVED_AT,
            source=FakeProcessIdentitySource(
                ProcessIdentitySnapshot(
                    process_id=target.process_id,
                    state=PROCESS_NOT_FOUND,
                )
            ),
        )
        requested_at = CAPTURED_AT + timedelta(seconds=1)
        request = CanaryStopRequest(
            latch_id="canary-stop-012",
            controller_id="external-stop-controller",
            account_binding_commitment=ACCOUNT_COMMITMENT,
            requested_at=requested_at.isoformat(),
            reason_code="PROCESS_OBSERVER_PROOF",
        )
        acknowledgement = CanaryRuntimeStopAcknowledgement(
            latch_sha256=request.record_sha256,
            runtime_instance_id=target.runtime_instance_id,
            account_binding_commitment=ACCOUNT_COMMITMENT,
            acknowledged_at=(
                requested_at + timedelta(seconds=1)
            ).isoformat(),
            state=RUNTIME_STOPPED,
            execution_disabled=True,
            outstanding_command_count=0,
        )
        revocation = CanaryCredentialRevocationObservation(
            source="PROVIDER_REVOCATION_PROOF_V1",
            account_binding_commitment=ACCOUNT_COMMITMENT,
            observed_at=(
                requested_at + timedelta(seconds=3)
            ).isoformat(),
            credential_state=CREDENTIAL_REVOKED,
        )
        policy = CanaryStopDrillPolicy(
            expected_controller_id="external-stop-controller",
            expected_process_observer_id=target.observer_id,
            expected_process_source=target.source,
            expected_revocation_source="PROVIDER_REVOCATION_PROOF_V1",
            max_evidence_age_seconds=30,
            max_shutdown_latency_seconds=10,
            max_revocation_latency_seconds=10,
        )

        result = evaluate_canary_stop_drill(
            stop_request=request,
            runtime_acknowledgement=acknowledgement,
            process_observation=evidence.to_stop_observation(),
            revocation_observation=revocation,
            evaluated_at=requested_at + timedelta(seconds=4),
            policy=policy,
        )

        self.assertTrue(result.passed)
        self.assertEqual("INDEPENDENT_STOP_DRILL_PROVEN", result.conclusion)
        self.assertFalse(result.to_dict()["processMutationPerformed"])
        self.assertFalse(result.to_dict()["credentialMutationPerformed"])

    def test_pid_reuse_proves_original_target_stopped_without_claiming_absence(
        self,
    ) -> None:
        target = self.capture()
        source = FakeProcessIdentitySource(
            self.running_snapshot(
                created_at=CREATED_AT + timedelta(minutes=1),
                executable_path_sha256=OTHER_PATH_COMMITMENT,
            )
        )

        evidence = observe_canary_process_target(
            target,
            observed_at=OBSERVED_AT,
            source=source,
        )

        self.assertFalse(evidence.process_running)
        self.assertTrue(evidence.pid_reused)
        self.assertEqual(
            "TARGET_PROCESS_STOPPED_PID_REUSED",
            evidence.conclusion,
        )

    def test_access_denied_query_failure_and_unsupported_are_unavailable(
        self,
    ) -> None:
        target = self.capture()
        for state in (
            PROCESS_ACCESS_DENIED,
            PROCESS_QUERY_FAILED,
            PROCESS_UNSUPPORTED,
        ):
            with self.subTest(state=state):
                evidence = observe_canary_process_target(
                    target,
                    observed_at=OBSERVED_AT,
                    source=FakeProcessIdentitySource(
                        ProcessIdentitySnapshot(
                            process_id=target.process_id,
                            state=state,
                        )
                    ),
                )
                self.assertIsNone(evidence.process_running)
                self.assertEqual(
                    "PROCESS_LIVENESS_UNAVAILABLE",
                    evidence.conclusion,
                )
                with self.assertRaisesRegex(
                    CanaryProcessObserverError,
                    "cannot satisfy a stop drill",
                ):
                    evidence.to_stop_observation()

    def test_target_capture_requires_live_independent_process(self) -> None:
        for state in (
            PROCESS_NOT_FOUND,
            PROCESS_ACCESS_DENIED,
            PROCESS_QUERY_FAILED,
        ):
            with self.subTest(state=state):
                with self.assertRaisesRegex(
                    CanaryProcessObserverError,
                    "only while it is running",
                ):
                    self.capture(
                        FakeProcessIdentitySource(
                            ProcessIdentitySnapshot(
                                process_id=90_001,
                                state=state,
                            )
                        )
                    )

        self_snapshot = self.running_snapshot(process_id=os.getpid())
        with self.assertRaisesRegex(
            CanaryProcessObserverError,
            "cannot be the independent observer",
        ):
            self.capture(
                FakeProcessIdentitySource(self_snapshot),
                process_id=os.getpid(),
            )

    def test_source_pid_and_clock_mismatches_fail_closed(self) -> None:
        target = self.capture()
        wrong_source = FakeProcessIdentitySource(self.running_snapshot())
        wrong_source.source_id = "OTHER_SOURCE"
        with self.assertRaisesRegex(
            CanaryProcessObserverError,
            "source does not match",
        ):
            observe_canary_process_target(
                target,
                observed_at=OBSERVED_AT,
                source=wrong_source,
            )
        with self.assertRaisesRegex(
            CanaryProcessObserverError,
            "predates target capture",
        ):
            observe_canary_process_target(
                target,
                observed_at=CAPTURED_AT - timedelta(seconds=1),
                source=FakeProcessIdentitySource(self.running_snapshot()),
            )
        with self.assertRaisesRegex(
            CanaryProcessObserverError,
            "different process ID",
        ):
            observe_canary_process_target(
                target,
                observed_at=OBSERVED_AT,
                source=FakeProcessIdentitySource(
                    self.running_snapshot(process_id=90_002)
                ),
            )

    def test_target_and_evidence_are_content_addressed_and_redacted(self) -> None:
        target = self.capture()
        evidence = observe_canary_process_target(
            target,
            observed_at=OBSERVED_AT,
            source=FakeProcessIdentitySource(self.running_snapshot()),
        )
        target_payload = target.to_dict()
        evidence_payload = evidence.to_dict()

        self.assertEqual(64, len(target_payload["targetSha256"]))
        self.assertEqual(64, len(evidence_payload["recordSha256"]))
        self.assertFalse(target_payload["rawExecutablePathRetained"])
        self.assertFalse(evidence_payload["rawExecutablePathRetained"])
        self.assertFalse(evidence_payload["processMutationPerformed"])
        self.assertFalse(evidence_payload["credentialMutationPerformed"])
        self.assertFalse(evidence_payload["brokerActionAllowed"])
        self.assertFalse(evidence_payload["transmitting"])
        self.assertEqual(
            "UNAVAILABLE",
            evidence_payload["orderTransmission"],
        )
        self.assertNotIn("python.exe", json.dumps(evidence_payload).lower())

    def test_contradictory_liveness_evidence_is_rejected(self) -> None:
        target = self.capture()
        valid = observe_canary_process_target(
            target,
            observed_at=OBSERVED_AT,
            source=FakeProcessIdentitySource(self.running_snapshot()),
        )
        cases = (
            {"process_running": False},
            {"pid_reused": True},
            {"conclusion": "TARGET_PROCESS_STOPPED"},
            {"observed_process_created_at": None},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(
                    CanaryProcessObserverError,
                    "contradicts|requires complete",
                ):
                    replace(valid, **changes)

    @unittest.skipUnless(
        os.name == "nt",
        "Physical process identity proof is Windows-specific.",
    )
    def test_windows_source_observes_real_child_running_then_stopped(
        self,
    ) -> None:
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import time; time.sleep(1.5)",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            source = WindowsProcessIdentitySource()
            deadline = time.monotonic() + 3
            snapshot = source.inspect(child.pid)
            while (
                snapshot.state != PROCESS_RUNNING
                and time.monotonic() < deadline
            ):
                time.sleep(0.02)
                snapshot = source.inspect(child.pid)
            self.assertEqual(PROCESS_RUNNING, snapshot.state)
            target = capture_canary_process_target(
                observer_id="external-process-observer",
                runtime_instance_id="synthetic-child-runtime",
                process_id=child.pid,
                captured_at=datetime.now(UTC),
                source=source,
            )
            running = observe_canary_process_target(
                target,
                observed_at=datetime.now(UTC),
                source=source,
            )
            self.assertTrue(running.process_running)

            child.wait(timeout=10)
            stopped = observe_canary_process_target(
                target,
                observed_at=datetime.now(UTC),
                source=source,
            )
            self.assertFalse(stopped.process_running)
            self.assertEqual("TARGET_PROCESS_STOPPED", stopped.conclusion)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)

    def test_runtime_module_has_no_process_mutation_network_or_broker_surface(
        self,
    ) -> None:
        source = inspect.getsource(observer_module)
        tree = ast.parse(source)
        imports: set[str] = set()
        functions: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.add(node.name)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            ):
                calls.add(node.func.attr)

        self.assertFalse(
            imports
            & {
                "requests",
                "httpx",
                "urllib",
                "socket",
                "subprocess",
                "psutil",
                "signal",
            }
        )
        forbidden = {
            "kill",
            "terminate",
            "send_signal",
            "unlink",
            "remove",
            "write_text",
            "write_bytes",
            "revoke",
            "preview_order",
            "submit_order",
            "replace_order",
            "cancel_order",
            "transmit_order",
        }
        self.assertFalse(functions & forbidden)
        self.assertFalse(calls & forbidden)

    def test_snapshot_validation_rejects_incomplete_or_false_identity(self) -> None:
        with self.assertRaises(CanaryProcessObserverError):
            ProcessIdentitySnapshot(
                process_id=90_001,
                state=PROCESS_RUNNING,
            )
        with self.assertRaises(CanaryProcessObserverError):
            ProcessIdentitySnapshot(
                process_id=90_001,
                state=PROCESS_NOT_FOUND,
                created_at=CREATED_AT.isoformat(),
            )
        with self.assertRaises(CanaryProcessObserverError):
            ProcessIdentitySnapshot(
                process_id=0,
                state=PROCESS_NOT_FOUND,
            )

    def test_observation_constructor_rejects_unavailable_false_claim(self) -> None:
        target = self.capture()
        with self.assertRaisesRegex(
            CanaryProcessObserverError,
            "contradicts",
        ):
            CanaryProcessLivenessEvidence(
                target_sha256=target.target_sha256,
                observer_id=target.observer_id,
                source=target.source,
                runtime_instance_id=target.runtime_instance_id,
                process_id=target.process_id,
                observed_at=OBSERVED_AT.isoformat(),
                observation_state=PROCESS_ACCESS_DENIED,
                process_running=False,
                pid_reused=False,
                observed_process_created_at=None,
                observed_executable_path_sha256=None,
                conclusion="TARGET_PROCESS_STOPPED",
            )


if __name__ == "__main__":
    unittest.main()
