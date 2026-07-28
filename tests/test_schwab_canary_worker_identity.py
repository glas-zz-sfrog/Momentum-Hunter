from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import tempfile
import unittest

import momentum_hunter.schwab_canary_worker_identity as identity_module
from momentum_hunter.schwab_canary_process_evidence import (
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
from momentum_hunter.schwab_canary_worker_identity import (
    CANARY_WORKER_IDENTITY_SCHEMA_VERSION,
    CANARY_WORKER_ROLE,
    WORKER_IDENTITY_BLOCKED,
    WORKER_IDENTITY_BOUND_RUNNING,
    WORKER_IDENTITY_BOUND_STOPPED,
    CanaryWorkerIdentityConflict,
    CanaryWorkerIdentityError,
    CanaryWorkerIdentityPolicy,
    CanaryWorkerIdentityStore,
    build_canary_worker_identity_receipt,
    evaluate_canary_worker_identity_binding,
)


UTC = timezone.utc
PROCESS_CREATED_AT = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)
TARGET_CAPTURED_AT = PROCESS_CREATED_AT + timedelta(seconds=5)
RECEIPT_ISSUED_AT = PROCESS_CREATED_AT + timedelta(seconds=3)
EXECUTABLE_SHA256 = "a" * 64
ACCOUNT_BINDING_COMMITMENT = "b" * 64
BUILD_MANIFEST = b'{"build":"synthetic-canary-worker-v1"}'
WORKER_ARTIFACT = b"synthetic canary worker artifact bytes"


class CanaryWorkerIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.process_store = CanaryProcessEvidenceStore(
            root / "process-evidence"
        )
        self.identity_store = CanaryWorkerIdentityStore(
            root / "worker-identity.json"
        )
        self.identity_store_counter = 0
        self.target = CanaryProcessTarget(
            observer_id="external-process-observer",
            source=WINDOWS_PROCESS_OBSERVER_SOURCE,
            runtime_instance_id="broker-worker-001",
            process_id=4242,
            process_created_at=PROCESS_CREATED_AT.isoformat(),
            executable_path_sha256=EXECUTABLE_SHA256,
            captured_at=TARGET_CAPTURED_AT.isoformat(),
        )
        self.receipt = build_canary_worker_identity_receipt(
            self.target,
            runtime_build_manifest=BUILD_MANIFEST,
            worker_artifact=WORKER_ARTIFACT,
            account_binding_commitment=ACCOUNT_BINDING_COMMITMENT,
            issued_at=RECEIPT_ISSUED_AT,
        )
        self.policy = CanaryWorkerIdentityPolicy(
            expected_worker_build_sha256=self.receipt.worker_build_sha256,
            expected_worker_artifact_sha256=(
                self.receipt.worker_artifact_sha256
            ),
            expected_account_binding_commitment=(
                ACCOUNT_BINDING_COMMITMENT
            ),
            expected_executable_path_sha256=EXECUTABLE_SHA256,
            expected_observer_id=self.target.observer_id,
            expected_process_source=self.target.source,
        )

    def test_receipt_binds_exact_artifacts_target_and_account_without_authority(
        self,
    ) -> None:
        payload = self.receipt.to_dict()
        rendered = json.dumps(payload, sort_keys=True)

        self.assertEqual(
            CANARY_WORKER_IDENTITY_SCHEMA_VERSION,
            payload["schemaVersion"],
        )
        self.assertEqual(CANARY_WORKER_ROLE, payload["workerRole"])
        self.assertEqual(
            self.target.target_sha256,
            payload["processTargetSha256"],
        )
        self.assertEqual(EXECUTABLE_SHA256, payload["executablePathSha256"])
        self.assertNotIn(BUILD_MANIFEST.decode("ascii"), rendered)
        self.assertNotIn(WORKER_ARTIFACT.decode("ascii"), rendered)
        self.assertFalse(payload["providerEvidence"])
        self.assertFalse(payload["runtimeObserved"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["realOrderApproval"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def test_identity_store_is_write_once_idempotent_and_tamper_evident(
        self,
    ) -> None:
        persisted = self.identity_store.persist(self.receipt)
        original = self.identity_store.path.read_bytes()
        duplicate = self.identity_store.persist(self.receipt)

        self.assertEqual(self.receipt, persisted)
        self.assertEqual(self.receipt, duplicate)
        self.assertEqual(original, self.identity_store.path.read_bytes())

        conflicting = replace(
            self.receipt,
            worker_artifact_sha256="c" * 64,
        )
        with self.assertRaises(CanaryWorkerIdentityConflict):
            self.identity_store.persist(conflicting)
        self.assertEqual(original, self.identity_store.path.read_bytes())

        payload = json.loads(
            self.identity_store.path.read_text(encoding="ascii")
        )
        payload["runtimeInstanceId"] = "tampered-worker"
        self.identity_store.path.write_text(
            json.dumps(payload),
            encoding="ascii",
        )
        tampered = self.identity_store.path.read_bytes()
        with self.assertRaisesRegex(
            CanaryWorkerIdentityError,
            "hash is invalid",
        ):
            self.identity_store.load()
        with self.assertRaises(CanaryWorkerIdentityConflict):
            self.identity_store.persist(self.receipt)
        self.assertEqual(tampered, self.identity_store.path.read_bytes())

    def test_exact_running_process_chain_is_bound_but_never_execution_authority(
        self,
    ) -> None:
        self.process_store.persist_target(self.target)
        self.process_store.append_observation(self.running_evidence(seconds=6))

        result = self.evaluate(seconds=10)
        payload = result.to_dict()

        self.assertEqual(WORKER_IDENTITY_BOUND_RUNNING, result.status)
        self.assertTrue(payload["identityBindingVerified"])
        self.assertFalse(payload["stopLifecycleObserved"])
        self.assertFalse(payload["runtimeAcknowledgementVerified"])
        self.assertFalse(payload["providerRevocationVerified"])
        self.assertFalse(payload["physicalStopDrillComplete"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["realOrderApproval"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        self.assertEqual(
            64,
            len(str(payload["processEvidenceChainSha256"])),
        )

    def test_running_then_stopped_chain_is_bound_but_not_full_stop_drill(
        self,
    ) -> None:
        self.process_store.persist_target(self.target)
        self.process_store.append_observation(self.running_evidence(seconds=6))
        self.process_store.append_observation(self.stopped_evidence(seconds=9))

        result = self.evaluate(seconds=10)

        self.assertEqual(WORKER_IDENTITY_BOUND_STOPPED, result.status)
        self.assertTrue(result.identity_binding_verified)
        self.assertTrue(result.stop_lifecycle_observed)
        self.assertFalse(result.to_dict()["physicalStopDrillComplete"])
        self.assertFalse(result.to_dict()["providerRevocationVerified"])

    def test_missing_receipt_target_or_observation_blocks(self) -> None:
        missing_all = evaluate_canary_worker_identity_binding(
            identity_store=self.identity_store,
            process_store=self.process_store,
            policy=self.policy,
            evaluated_at=PROCESS_CREATED_AT + timedelta(seconds=10),
        )
        self.assertEqual(WORKER_IDENTITY_BLOCKED, missing_all.status)
        self.assertEqual(
            {
                "WORKER_IDENTITY_MISSING",
                "PROCESS_TARGET_MISSING",
                "PROCESS_OBSERVATION_MISSING",
            },
            finding_codes(missing_all),
        )

        self.process_store.persist_target(self.target)
        missing_observation = self.evaluate(seconds=10)
        self.assertEqual(WORKER_IDENTITY_BLOCKED, missing_observation.status)
        self.assertIn(
            "PROCESS_OBSERVATION_MISSING",
            finding_codes(missing_observation),
        )

    def test_stopped_only_or_unavailable_observation_blocks(self) -> None:
        self.process_store.persist_target(self.target)
        self.process_store.append_observation(self.stopped_evidence(seconds=7))

        stopped_only = self.evaluate(seconds=10)
        self.assertEqual(WORKER_IDENTITY_BLOCKED, stopped_only.status)
        self.assertIn(
            "RUNNING_OBSERVATION_MISSING",
            finding_codes(stopped_only),
        )

        other_store = CanaryProcessEvidenceStore(
            Path(self.temporary_directory.name) / "unavailable-evidence"
        )
        other_store.persist_target(self.target)
        other_store.append_observation(self.unavailable_evidence(seconds=7))
        unavailable = evaluate_canary_worker_identity_binding(
            identity_store=self.persisted_identity_store(self.receipt),
            process_store=other_store,
            policy=self.policy,
            evaluated_at=PROCESS_CREATED_AT + timedelta(seconds=10),
        )
        self.assertEqual(WORKER_IDENTITY_BLOCKED, unavailable.status)
        self.assertIn(
            "PROCESS_OBSERVATION_UNAVAILABLE",
            finding_codes(unavailable),
        )

    def test_release_policy_mismatches_all_fail_closed(self) -> None:
        self.process_store.persist_target(self.target)
        self.process_store.append_observation(self.running_evidence(seconds=6))
        mismatches = (
            (
                replace(
                    self.policy,
                    expected_worker_build_sha256="c" * 64,
                ),
                "WORKER_BUILD_MISMATCH",
            ),
            (
                replace(
                    self.policy,
                    expected_worker_artifact_sha256="c" * 64,
                ),
                "WORKER_ARTIFACT_MISMATCH",
            ),
            (
                replace(
                    self.policy,
                    expected_account_binding_commitment="c" * 64,
                ),
                "ACCOUNT_BINDING_MISMATCH",
            ),
            (
                replace(
                    self.policy,
                    expected_executable_path_sha256="c" * 64,
                ),
                "EXECUTABLE_IDENTITY_MISMATCH",
            ),
            (
                replace(
                    self.policy,
                    expected_observer_id="other-observer",
                ),
                "PROCESS_OBSERVER_MISMATCH",
            ),
            (
                replace(
                    self.policy,
                    expected_process_source="OTHER_PROCESS_SOURCE",
                ),
                "PROCESS_SOURCE_MISMATCH",
            ),
        )
        for policy, expected_code in mismatches:
            with self.subTest(expected_code=expected_code):
                result = evaluate_canary_worker_identity_binding(
                    identity_store=self.persisted_identity_store(
                        self.receipt
                    ),
                    process_store=self.process_store,
                    policy=policy,
                    evaluated_at=PROCESS_CREATED_AT
                    + timedelta(seconds=10),
                )
                self.assertEqual(WORKER_IDENTITY_BLOCKED, result.status)
                self.assertIn(expected_code, finding_codes(result))

    def test_receipt_target_runtime_and_executable_mismatch_block(self) -> None:
        self.process_store.persist_target(self.target)
        self.process_store.append_observation(self.running_evidence(seconds=6))
        mismatches = (
            (
                replace(
                    self.receipt,
                    runtime_instance_id="other-runtime",
                ),
                "RUNTIME_INSTANCE_MISMATCH",
            ),
            (
                replace(
                    self.receipt,
                    process_target_sha256="c" * 64,
                ),
                "PROCESS_TARGET_MISMATCH",
            ),
            (
                replace(
                    self.receipt,
                    executable_path_sha256="c" * 64,
                ),
                "EXECUTABLE_IDENTITY_MISMATCH",
            ),
        )
        for receipt, expected_code in mismatches:
            with self.subTest(expected_code=expected_code):
                result = evaluate_canary_worker_identity_binding(
                    identity_store=self.persisted_identity_store(receipt),
                    process_store=self.process_store,
                    policy=self.policy,
                    evaluated_at=PROCESS_CREATED_AT
                    + timedelta(seconds=10),
                )
                self.assertEqual(WORKER_IDENTITY_BLOCKED, result.status)
                self.assertIn(expected_code, finding_codes(result))

    def test_stale_and_future_receipts_block(self) -> None:
        self.process_store.persist_target(self.target)
        self.process_store.append_observation(self.running_evidence(seconds=6))

        stale = self.evaluate(seconds=400)
        self.assertIn("IDENTITY_RECEIPT_STALE", finding_codes(stale))
        self.assertIn("PROCESS_OBSERVATION_STALE", finding_codes(stale))

        future_receipt = replace(
            self.receipt,
            issued_at=(
                PROCESS_CREATED_AT + timedelta(seconds=20)
            ).isoformat(),
        )
        future = evaluate_canary_worker_identity_binding(
            identity_store=self.persisted_identity_store(future_receipt),
            process_store=self.process_store,
            policy=self.policy,
            evaluated_at=PROCESS_CREATED_AT + timedelta(seconds=10),
        )
        self.assertIn(
            "IDENTITY_RECEIPT_FROM_FUTURE",
            finding_codes(future),
        )

    def test_observation_clock_and_post_identity_running_are_required(
        self,
    ) -> None:
        future_store = CanaryProcessEvidenceStore(
            Path(self.temporary_directory.name) / "future-process"
        )
        future_store.persist_target(self.target)
        future_store.append_observation(self.running_evidence(seconds=20))
        future = evaluate_canary_worker_identity_binding(
            identity_store=self.persisted_identity_store(self.receipt),
            process_store=future_store,
            policy=self.policy,
            evaluated_at=PROCESS_CREATED_AT + timedelta(seconds=10),
        )
        self.assertIn(
            "PROCESS_OBSERVATION_FROM_FUTURE",
            finding_codes(future),
        )

        self.process_store.persist_target(self.target)
        self.process_store.append_observation(self.running_evidence(seconds=6))
        later_receipt = replace(
            self.receipt,
            issued_at=(
                PROCESS_CREATED_AT + timedelta(seconds=9)
            ).isoformat(),
        )
        no_post_identity_running = evaluate_canary_worker_identity_binding(
            identity_store=self.persisted_identity_store(later_receipt),
            process_store=self.process_store,
            policy=self.policy,
            evaluated_at=PROCESS_CREATED_AT + timedelta(seconds=10),
        )
        self.assertIn(
            "BOUND_RUNNING_OBSERVATION_MISSING",
            finding_codes(no_post_identity_running),
        )

    def test_direct_receipt_cannot_bypass_startup_chronology(self) -> None:
        self.process_store.persist_target(self.target)
        self.process_store.append_observation(self.running_evidence(seconds=40))
        cases = (
            (
                replace(
                    self.receipt,
                    issued_at=(
                        PROCESS_CREATED_AT - timedelta(seconds=1)
                    ).isoformat(),
                ),
                "IDENTITY_RECEIPT_BEFORE_PROCESS",
            ),
            (
                replace(
                    self.receipt,
                    issued_at=(
                        TARGET_CAPTURED_AT + timedelta(seconds=31)
                    ).isoformat(),
                ),
                "IDENTITY_RECEIPT_LATE",
            ),
        )
        for receipt, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = evaluate_canary_worker_identity_binding(
                    identity_store=self.persisted_identity_store(receipt),
                    process_store=self.process_store,
                    policy=replace(
                        self.policy,
                        max_observation_age_seconds=60,
                    ),
                    evaluated_at=PROCESS_CREATED_AT
                    + timedelta(seconds=45),
                )
                self.assertIn(expected_code, finding_codes(result))

    def test_builder_rejects_bad_bytes_clocks_commitments_and_policy(self) -> None:
        cases = (
            {"runtime_build_manifest": b""},
            {"worker_artifact": b""},
            {"account_binding_commitment": "not-a-sha"},
            {"issued_at": datetime(2026, 7, 28, 6, 0)},
            {
                "issued_at": PROCESS_CREATED_AT
                - timedelta(milliseconds=1)
            },
            {
                "issued_at": TARGET_CAPTURED_AT
                + timedelta(seconds=31)
            },
        )
        defaults = {
            "runtime_build_manifest": BUILD_MANIFEST,
            "worker_artifact": WORKER_ARTIFACT,
            "account_binding_commitment": ACCOUNT_BINDING_COMMITMENT,
            "issued_at": RECEIPT_ISSUED_AT,
        }
        for changes in cases:
            with self.subTest(changes=changes):
                arguments = {**defaults, **changes}
                with self.assertRaises(CanaryWorkerIdentityError):
                    build_canary_worker_identity_receipt(
                        self.target,
                        **arguments,
                    )

        for invalid in (0, -1, float("nan"), float("inf"), 3_601):
            with self.subTest(max_receipt_age_seconds=invalid):
                with self.assertRaises(CanaryWorkerIdentityError):
                    replace(
                        self.policy,
                        max_receipt_age_seconds=invalid,
                    )
            with self.subTest(max_observation_age_seconds=invalid):
                with self.assertRaises(CanaryWorkerIdentityError):
                    replace(
                        self.policy,
                        max_observation_age_seconds=invalid,
                    )

    def test_source_bytes_are_not_mutated_or_retained(self) -> None:
        manifest = bytearray(BUILD_MANIFEST)
        artifact = bytearray(WORKER_ARTIFACT)

        with self.assertRaisesRegex(
            CanaryWorkerIdentityError,
            "bytes",
        ):
            build_canary_worker_identity_receipt(
                self.target,
                runtime_build_manifest=manifest,  # type: ignore[arg-type]
                worker_artifact=artifact,  # type: ignore[arg-type]
                account_binding_commitment=ACCOUNT_BINDING_COMMITMENT,
                issued_at=RECEIPT_ISSUED_AT,
            )

        self.assertEqual(bytearray(BUILD_MANIFEST), manifest)
        self.assertEqual(bytearray(WORKER_ARTIFACT), artifact)

    def test_malformed_identity_receipt_fails_closed(self) -> None:
        self.identity_store.path.write_text("{", encoding="ascii")
        with self.assertRaisesRegex(
            CanaryWorkerIdentityError,
            "unreadable or malformed",
        ):
            self.identity_store.load()

    def test_symlink_identity_receipt_and_parent_fail_closed(self) -> None:
        backing = Path(self.temporary_directory.name) / "backing.json"
        backing.write_text("{}", encoding="ascii")
        try:
            self.identity_store.path.symlink_to(backing)
        except OSError:
            self.skipTest("Creating a file symlink is unavailable.")
        with self.assertRaisesRegex(
            CanaryWorkerIdentityError,
            "regular file",
        ):
            self.identity_store.load()

        parent_target = (
            Path(self.temporary_directory.name) / "identity-parent-target"
        )
        parent_target.mkdir()
        parent_link = (
            Path(self.temporary_directory.name) / "identity-parent-link"
        )
        try:
            parent_link.symlink_to(parent_target, target_is_directory=True)
        except OSError:
            self.skipTest("Creating a directory symlink is unavailable.")
        linked_store = CanaryWorkerIdentityStore(
            parent_link / "worker-identity.json"
        )
        with self.assertRaisesRegex(
            CanaryWorkerIdentityError,
            "parent cannot be a symlink",
        ):
            linked_store.persist(self.receipt)

    def test_module_has_no_network_secret_process_control_or_order_surface(
        self,
    ) -> None:
        source = inspect.getsource(identity_module)
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
                    "revoke",
                    "unlink",
                    "remove",
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
        self.assertNotIn("/orders", source)

    def evaluate(self, *, seconds: int):
        return evaluate_canary_worker_identity_binding(
            identity_store=self.persisted_identity_store(self.receipt),
            process_store=self.process_store,
            policy=self.policy,
            evaluated_at=PROCESS_CREATED_AT + timedelta(seconds=seconds),
        )

    def persisted_identity_store(self, receipt):
        self.identity_store_counter += 1
        store = CanaryWorkerIdentityStore(
            Path(self.temporary_directory.name)
            / f"worker-identity-{self.identity_store_counter}.json"
        )
        store.persist(receipt)
        return store

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
            observed_at=(
                PROCESS_CREATED_AT + timedelta(seconds=seconds)
            ).isoformat(),
            observation_state=PROCESS_RUNNING,
            process_running=True,
            pid_reused=False,
            observed_process_created_at=self.target.process_created_at,
            observed_executable_path_sha256=EXECUTABLE_SHA256,
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
            observed_at=(
                PROCESS_CREATED_AT + timedelta(seconds=seconds)
            ).isoformat(),
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
            observed_at=(
                PROCESS_CREATED_AT + timedelta(seconds=seconds)
            ).isoformat(),
            observation_state=PROCESS_ACCESS_DENIED,
            process_running=None,
            pid_reused=False,
            observed_process_created_at=None,
            observed_executable_path_sha256=None,
            conclusion="PROCESS_LIVENESS_UNAVAILABLE",
        )


def finding_codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


if __name__ == "__main__":
    unittest.main()
