from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

import momentum_hunter.schwab_canary_broker_worker as worker_module
import momentum_hunter.schwab_canary_worker_lifecycle_evidence as package_module
from momentum_hunter.schwab_canary_broker_worker import (
    WORKER_BUILD_MANIFEST_FILENAME,
    WORKER_PROCESS_EVIDENCE_DIRECTORY,
    CanaryBrokerWorkerLaunchContract,
    CanaryBrokerWorkerLaunchStore,
)
from momentum_hunter.schwab_canary_process_evidence import (
    CanaryProcessEvidenceStore,
)
from momentum_hunter.schwab_canary_worker_lifecycle import (
    LIFECYCLE_CONTROLLER_ID,
    LIFECYCLE_OBSERVER_ID,
    LIFECYCLE_REVOCATION_SOURCE,
    CanaryWorkerLifecycleResultStore,
    run_canary_worker_lifecycle,
)
from momentum_hunter.schwab_canary_worker_lifecycle_evidence import (
    LIFECYCLE_PACKAGE_BLOCKED_CONCLUSION,
    LIFECYCLE_PACKAGE_VERIFIED_CONCLUSION,
    CanaryWorkerLifecyclePackageError,
    CanaryWorkerLifecyclePackagePolicy,
    verify_canary_worker_lifecycle_package,
)


ACCOUNT_BINDING_COMMITMENT = "a" * 64
RUNTIME_INSTANCE_ID = "broker-worker-package-001"
BUILD_MANIFEST = b'{"build":"canary-lifecycle-package-v1"}\n'


@unittest.skipUnless(
    os.name == "nt",
    "Lifecycle package proof uses the real Windows process observer.",
)
class CanaryWorkerLifecyclePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_directory = tempfile.TemporaryDirectory()
        cls.fixture_root = (
            Path(cls.fixture_directory.name) / "source-package"
        )
        cls.fixture_root.mkdir()
        (
            cls.fixture_root / WORKER_BUILD_MANIFEST_FILENAME
        ).write_bytes(BUILD_MANIFEST)
        worker_path = Path(inspect.getfile(worker_module))
        worker_sha256 = hashlib.sha256(
            worker_path.read_bytes()
        ).hexdigest()
        launch = CanaryBrokerWorkerLaunchContract(
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            account_binding_commitment=(
                ACCOUNT_BINDING_COMMITMENT
            ),
            expected_worker_build_sha256=hashlib.sha256(
                BUILD_MANIFEST
            ).hexdigest(),
            expected_worker_artifact_sha256=worker_sha256,
            poll_interval_milliseconds=20,
            startup_timeout_seconds=10,
            maximum_runtime_seconds=20,
        )
        CanaryBrokerWorkerLaunchStore(cls.fixture_root).persist(
            launch
        )
        result = run_canary_worker_lifecycle(cls.fixture_root)
        target = CanaryProcessEvidenceStore(
            cls.fixture_root / WORKER_PROCESS_EVIDENCE_DIRECTORY
        ).load_target()
        if target is None:
            raise AssertionError("Lifecycle fixture target is missing.")
        cls.fixture_result = result
        cls.fixture_policy = CanaryWorkerLifecyclePackagePolicy(
            expected_runtime_instance_id=RUNTIME_INSTANCE_ID,
            expected_account_binding_commitment=(
                ACCOUNT_BINDING_COMMITMENT
            ),
            expected_worker_build_sha256=(
                launch.expected_worker_build_sha256
            ),
            expected_worker_artifact_sha256=(
                launch.expected_worker_artifact_sha256
            ),
            expected_executable_path_sha256=(
                target.executable_path_sha256
            ),
            expected_lifecycle_result_sha256=(
                result.result_sha256
            ),
            expected_process_observer_id=LIFECYCLE_OBSERVER_ID,
            expected_process_source=target.source,
            expected_stop_controller_id=LIFECYCLE_CONTROLLER_ID,
            expected_revocation_source=(
                LIFECYCLE_REVOCATION_SOURCE
            ),
            max_evidence_age_seconds=60,
            max_future_skew_seconds=2,
        )
        cls.fixture_evaluated_at = (
            datetime.fromisoformat(result.completed_at)
            + timedelta(seconds=1)
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_directory.cleanup()

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = (
            Path(self.temporary_directory.name) / "package"
        )
        shutil.copytree(self.fixture_root, self.root)

    def test_complete_package_revalidates_read_only_without_authority(
        self,
    ) -> None:
        before = tree_hashes(self.root)

        result = self.verify()
        payload = result.to_dict()
        rendered = json.dumps(payload, sort_keys=True)

        self.assertTrue(result.local_package_verified)
        self.assertEqual(
            LIFECYCLE_PACKAGE_VERIFIED_CONCLUSION,
            result.conclusion,
        )
        self.assertEqual(
            {
                "launchContract": "PASS",
                "buildManifest": "PASS",
                "workerArtifact": "PASS",
                "processEvidence": "PASS",
                "workerIdentity": "PASS",
                "stopLatch": "PASS",
                "stopAcknowledgement": "PASS",
                "lifecycleResult": "PASS",
                "packageComposition": "PASS",
            },
            payload["components"],
        )
        self.assertTrue(payload["sourceProcessLaunchVerified"])
        self.assertTrue(payload["sourceProcessLaunchPerformed"])
        self.assertTrue(payload["sourceProcessMutationPerformed"])
        self.assertTrue(payload["sourceProcessStoppedVerified"])
        self.assertFalse(
            payload["sourceProcessTerminationPerformed"]
        )
        self.assertFalse(payload["sourceProcessSignalPerformed"])
        self.assertFalse(payload["providerRevocationVerified"])
        self.assertTrue(payload["providerRevocationRequired"])
        self.assertFalse(payload["physicalStopDrillComplete"])
        self.assertFalse(
            payload["verificationProcessMutationPerformed"]
        )
        self.assertFalse(payload["credentialAccessed"])
        self.assertFalse(payload["credentialMutationPerformed"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["realOrderApproval"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        self.assertNotIn(ACCOUNT_BINDING_COMMITMENT, rendered)
        self.assertNotIn(str(self.root), rendered)
        self.assertEqual(before, tree_hashes(self.root))

    def test_result_without_supporting_process_evidence_blocks(
        self,
    ) -> None:
        shutil.rmtree(
            self.root / WORKER_PROCESS_EVIDENCE_DIRECTORY
        )

        result = self.verify()

        self.assertFalse(result.local_package_verified)
        self.assertEqual(
            LIFECYCLE_PACKAGE_BLOCKED_CONCLUSION,
            result.conclusion,
        )
        self.assertIn("PROCESS_TARGET_MISSING", finding_codes(result))
        self.assertIn(
            "PROCESS_OBSERVATION_MISSING",
            finding_codes(result),
        )

    def test_build_manifest_drift_blocks(self) -> None:
        (
            self.root / WORKER_BUILD_MANIFEST_FILENAME
        ).write_bytes(b'{"build":"changed"}\n')

        result = self.verify()

        self.assertIn(
            "BUILD_MANIFEST_MISMATCH",
            finding_codes(result),
        )
        self.assertFalse(result.local_package_verified)

    def test_process_chain_tamper_blocks(self) -> None:
        observation = (
            self.root
            / WORKER_PROCESS_EVIDENCE_DIRECTORY
            / "observations"
            / "000001.json"
        )
        payload = json.loads(observation.read_text(encoding="ascii"))
        payload["evidence"]["processRunning"] = False
        observation.write_text(
            json.dumps(payload),
            encoding="ascii",
        )

        result = self.verify()

        self.assertIn(
            "PROCESS_EVIDENCE_INVALID",
            finding_codes(result),
        )
        self.assertFalse(result.local_package_verified)

    def test_swapped_result_policy_blocks(self) -> None:
        result = self.verify(
            policy=replace(
                self.fixture_policy,
                expected_lifecycle_result_sha256="f" * 64,
            )
        )

        self.assertIn(
            "LIFECYCLE_RESULT_MISMATCH",
            finding_codes(result),
        )
        self.assertFalse(result.local_package_verified)

    def test_account_or_runtime_policy_drift_blocks(self) -> None:
        cases = (
            (
                replace(
                    self.fixture_policy,
                    expected_account_binding_commitment="b" * 64,
                ),
                "LAUNCH_ACCOUNT_BINDING_MISMATCH",
            ),
            (
                replace(
                    self.fixture_policy,
                    expected_runtime_instance_id="other-runtime-001",
                ),
                "LAUNCH_RUNTIME_MISMATCH",
            ),
        )
        for policy, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = self.verify(policy=policy)
                self.assertIn(
                    expected_code,
                    finding_codes(result),
                )
                self.assertFalse(result.local_package_verified)

    def test_stale_or_future_package_blocks(self) -> None:
        cases = (
            (
                self.fixture_evaluated_at + timedelta(seconds=61),
                "EVIDENCE_STALE",
            ),
            (
                datetime.fromisoformat(
                    self.fixture_result.completed_at
                )
                - timedelta(seconds=3),
                "EVIDENCE_FROM_FUTURE",
            ),
        )
        for evaluated_at, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = self.verify(evaluated_at=evaluated_at)
                self.assertIn(
                    expected_code,
                    finding_codes(result),
                )
                self.assertFalse(result.local_package_verified)

    def test_lifecycle_result_authority_tamper_blocks(self) -> None:
        store = CanaryWorkerLifecycleResultStore(self.root)
        payload = json.loads(store.path.read_text(encoding="ascii"))
        payload["executionPermit"] = True
        store.path.write_text(
            json.dumps(payload),
            encoding="ascii",
        )

        result = self.verify()

        self.assertIn(
            "LIFECYCLE_RESULT_INVALID",
            finding_codes(result),
        )
        self.assertFalse(result.local_package_verified)

    def test_policy_rejects_unbounded_or_malformed_identity(self) -> None:
        for changes in (
            {"expected_runtime_instance_id": ""},
            {"expected_account_binding_commitment": "not-a-sha"},
            {"expected_process_observer_id": "observer with spaces"},
            {"max_evidence_age_seconds": 0},
            {"max_evidence_age_seconds": 3_601},
            {"max_future_skew_seconds": 61},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(
                    CanaryWorkerLifecyclePackageError
                ):
                    replace(self.fixture_policy, **changes)

    def test_verifier_has_no_network_process_control_or_broker_action(
        self,
    ) -> None:
        source = inspect.getsource(package_module)
        tree = ast.parse(source)
        imported_roots: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(
                    alias.name.split(".", 1)[0]
                    for alias in node.names
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
                    "subprocess",
                    "psutil",
                    "signal",
                }
            )
        )
        self.assertTrue(
            calls.isdisjoint(
                {
                    "persist",
                    "write_text",
                    "write_bytes",
                    "mkdir",
                    "unlink",
                    "remove",
                    "kill",
                    "terminate",
                    "send_signal",
                    "revoke",
                    "preview_order",
                    "submit_order",
                    "replace_order",
                    "cancel_order",
                    "transmit_order",
                }
            )
        )
        self.assertNotIn("/orders", source)
        self.assertNotIn("client_secret", source)
        self.assertNotIn("access_token", source)
        self.assertNotIn("refresh_token", source)

    def verify(
        self,
        *,
        evaluated_at: datetime | None = None,
        policy: CanaryWorkerLifecyclePackagePolicy | None = None,
    ):
        return verify_canary_worker_lifecycle_package(
            self.root,
            evaluated_at=(
                evaluated_at or self.fixture_evaluated_at
            ),
            policy=policy or self.fixture_policy,
        )


def finding_codes(result: object) -> set[str]:
    return {finding.code for finding in result.findings}


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()
