from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from tools import run_stat_data_002_canary as canary


class StatData002CanaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write_resource_cleanup(self, runtime_root: Path) -> None:
        receipt = canary._resource_cleanup_receipt(
            {
                "writerCreated": True,
                "writerReleaseAttempted": True,
                "writerClosed": True,
                "capabilityCreated": True,
                "capabilityReleaseAttempted": True,
                "capabilityClosed": True,
                "runtimeCreated": True,
                "runtimeShutdownAttempted": True,
                "runtimeShutdownCompleted": True,
            }
        )
        canary._write_once(
            runtime_root / "resource-cleanup.json",
            receipt,
        )

    def write_execution_inputs(self, evidence: Path) -> tuple[dict[str, str], dict[str, str]]:
        task_identity = {"head": "1" * 40, "branch": canary.TASK_BRANCH, "status": ""}
        production_identity = {"head": "2" * 40, "branch": "master", "status": ""}
        activation = canary.build_activation_record(
            activated_at="2026-08-28T09:32:00-04:00",
            first_eligible_session_date="2026-08-28",
            source_git_sha=task_identity["head"],
            configuration_fingerprint="3" * 64,
        )
        canary._write_once(
            evidence / "configuration.json",
            {
                "taskGit": task_identity,
                "productionGit": production_identity,
                "durationSeconds": 1800,
                "discoveryCadenceSeconds": 300,
                "offlineRehearsal": True,
            },
        )
        canary._write_once(
            evidence / "activation.json",
            {
                "recordType": "STAT_DATA_002_ACTIVATION",
                "payload": asdict(activation),
            },
        )
        return task_identity, production_identity

    def test_write_once_is_idempotent_and_conflicts_fail_closed(self) -> None:
        path = self.root / "evidence.json"
        value = {"status": "PASS", "authority": "RESEARCH_ONLY"}

        canary._write_once(path, value)
        original = path.read_bytes()
        canary._write_once(path, value)

        self.assertEqual(original, path.read_bytes())
        with self.assertRaises(canary.StatDataCanaryError):
            canary._write_once(path, {"status": "FAIL"})

    def test_manifest_verification_detects_tamper(self) -> None:
        payload = self.root / "payload.json"
        payload.write_text('{"safe":true}\n', encoding="ascii")
        canary._write_once(self.root / "MANIFEST.json", canary._manifest(self.root))

        self.assertEqual("PASS", canary._verify_manifest(self.root))
        payload.write_text('{"safe":false}\n', encoding="ascii")
        self.assertEqual("FAIL", canary._verify_manifest(self.root))

    def test_secret_scan_and_terminal_message_redaction(self) -> None:
        safe = self.root / "safe.json"
        safe.write_text(json.dumps({"authority": "RESEARCH_ONLY"}), encoding="ascii")
        self.assertEqual("PASS", canary._secret_scan(self.root)["status"])

        unsafe = self.root / "unsafe.txt"
        unsafe.write_text("Bearer " + "A" * 30, encoding="ascii")
        result = canary._secret_scan(self.root)
        self.assertEqual("FAIL", result["status"])
        self.assertEqual("BEARER_TOKEN", result["findings"][0]["pattern"])

        message = canary._sanitized_message(
            "identity 1234 key PK" + "A" * 22,
            "1234",
        )
        self.assertNotIn("1234", message)
        self.assertNotIn("PK" + "A" * 22, message)

        assignment = canary._sanitized_message(
            "refresh_token=" + "S" * 32,
            "1234",
        )
        self.assertNotIn("S" * 32, assignment)
        self.assertEqual(
            "Expected market-data identity ending is invalid.",
            canary._sanitized_message(
                "Expected market-data identity ending is invalid.",
                "",
            ),
        )

    def test_live_launch_is_restricted_to_regular_session(self) -> None:
        eastern = ZoneInfo("America/New_York")
        accepted = canary._assert_regular_session(
            datetime(2026, 8, 28, 9, 32, tzinfo=eastern)
        )
        self.assertIn("2026-08-28T09:32:00", accepted)
        for observed in (
            datetime(2026, 8, 28, 9, 29, tzinfo=eastern),
            datetime(2026, 8, 28, 16, 0, tzinfo=eastern),
            datetime(2026, 8, 29, 10, 0, tzinfo=eastern),
        ):
            with self.subTest(observed=observed):
                with self.assertRaises(canary.StatDataCanaryError):
                    canary._assert_regular_session(observed)

    def test_ephemeral_runtime_export_is_verified_and_never_runtime_authority(self) -> None:
        runtime = canary._new_ephemeral_runtime_root()
        self.addCleanup(lambda: runtime.exists() and __import__("shutil").rmtree(runtime))
        artifact = runtime / "runtime-artifacts" / "checkpoint.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text('{"state":"STOPPED"}\n', encoding="ascii")
        self.write_resource_cleanup(runtime)
        evidence = self.root / "durable-evidence"
        evidence.mkdir()

        receipt = canary._export_ephemeral_runtime(
            runtime_root=runtime,
            evidence_root=evidence,
        )

        self.assertEqual("PASS", receipt["status"])
        self.assertTrue(receipt["sourceRetired"])
        self.assertFalse(runtime.exists())
        self.assertFalse(receipt["runtimeAuthority"])
        self.assertEqual(
            receipt["sourceFingerprint"], receipt["destinationFingerprint"]
        )
        marker = json.loads(
            (
                evidence
                / "natural-runtime-forensic"
                / "FORENSIC_COPY_ONLY.json"
            ).read_text(encoding="ascii")
        )
        self.assertEqual("FORENSIC_COPY_ONLY", marker["classification"])
        self.assertFalse(marker["runtimeAuthority"])

    def test_named_exports_use_distinct_write_once_receipts(self) -> None:
        evidence = self.root / "named-exports"
        evidence.mkdir()
        for name in ("offline-runtime-forensic", "offline-init-failure-forensic"):
            runtime = canary._new_ephemeral_runtime_root()
            runtime.mkdir(parents=True)
            (runtime / "state.json").write_text("{}\n", encoding="ascii")
            self.write_resource_cleanup(runtime)
            receipt = canary._export_ephemeral_runtime(
                runtime_root=runtime,
                evidence_root=evidence,
                export_name=name,
            )
            self.assertEqual("PASS", receipt["status"])
            self.assertTrue((evidence / f"{name}-export.json").is_file())

    def test_durable_runtime_root_remains_rejected(self) -> None:
        self.assertFalse(
            canary._runtime_root_is_ephemeral(
                Path("C:/Users/steve/OneDrive/Documents/ArgusReviewBundles/runtime")
            )
        )
        with self.assertRaises(canary.StatDataCanaryError):
            canary._export_ephemeral_runtime(
                runtime_root=Path(
                    "C:/Users/steve/OneDrive/Documents/ArgusReviewBundles/runtime"
                ),
                evidence_root=self.root,
            )

    def test_export_refuses_missing_or_tampered_cleanup_evidence(self) -> None:
        for name, tampered in (("missing", False), ("tampered", True)):
            with self.subTest(name=name):
                runtime = canary._new_ephemeral_runtime_root()
                runtime.mkdir(parents=True)
                (runtime / "state.json").write_text("{}\n", encoding="ascii")
                if tampered:
                    self.write_resource_cleanup(runtime)
                    payload = json.loads(
                        (runtime / "resource-cleanup.json").read_text(encoding="ascii")
                    )
                    payload["writerClosed"] = False
                    (runtime / "resource-cleanup.json").write_text(
                        json.dumps(payload), encoding="ascii"
                    )
                with self.assertRaises(canary.StatDataCanaryError):
                    canary._export_ephemeral_runtime(
                        runtime_root=runtime,
                        evidence_root=self.root / f"evidence-{name}",
                    )
                self.assertTrue(runtime.exists())
                __import__("shutil").rmtree(runtime)

    def test_packaging_refuses_active_or_unexported_runtime(self) -> None:
        evidence = self.root / "packaging-order"
        canary._write_once(
            evidence / "terminal-result.json",
            {
                "status": "FAIL",
                "providerContactAttempted": True,
                "forensicRuntimeExport": None,
            },
        )
        with self.assertRaisesRegex(
            canary.StatDataCanaryError,
            "before verified runtime export",
        ):
            canary.package(
                task_root=self.root,
                evidence_root=evidence,
                python_executable=Path(__file__),
            )

    def test_activation_reload_failure_is_terminal_before_provider_contact(self) -> None:
        evidence = self.root / "reload-failure"
        self.write_execution_inputs(evidence)
        with (
            mock.patch.object(
                canary,
                "load_activation_record",
                side_effect=canary.StatDataCanaryError("reload failed"),
            ),
            mock.patch.object(canary, "run_live_qualification") as provider,
        ):
            result = canary.execute(
                task_root=self.root,
                production_root=self.root,
                evidence_root=evidence,
                expected_account_ending="1234",
            )

        provider.assert_not_called()
        self.assertEqual("FAIL", result["status"])
        self.assertEqual("LOAD_ACTIVATION", result["failureStage"])
        self.assertFalse(result["providerContactAttempted"])
        self.assertFalse(result["providerContact"])
        self.assertEqual(0, result["prospectiveSummary"]["unique_prospective_members"])
        self.assertFalse((evidence / "prospective-denominator").exists())
        persisted = json.loads(
            (evidence / "terminal-result.json").read_text(encoding="ascii")
        )
        self.assertEqual(result, persisted)

    def test_every_pre_provider_gate_is_terminalized(self) -> None:
        cases = (
            ("task-identity", "VERIFY_TASK_IDENTITY", "1234", 1),
            ("production-identity", "VERIFY_PRODUCTION_IDENTITY", "1234", 2),
            ("account-ending", "VALIDATE_MARKET_DATA_IDENTITY", "bad", 0),
            ("market-window", "ASSERT_MARKET_WINDOW", "1234", 0),
        )
        for name, expected_stage, ending, identity_failure_call in cases:
            with self.subTest(name=name):
                evidence = self.root / name
                task_identity, production_identity = self.write_execution_inputs(evidence)
                identities = [task_identity, production_identity]
                if identity_failure_call:
                    identities[identity_failure_call - 1] = {
                        **identities[identity_failure_call - 1],
                        "head": "9" * 40,
                    }
                if name == "account-ending":
                    (evidence / "prospective-denominator").mkdir()
                with (
                    mock.patch.object(canary, "_git_identity", side_effect=identities),
                    mock.patch.object(
                        canary,
                        "_assert_regular_session",
                        side_effect=(
                            canary.StatDataCanaryError("outside window")
                            if name == "market-window"
                            else None
                        ),
                    ),
                    mock.patch.object(canary, "run_live_qualification") as provider,
                ):
                    result = canary.execute(
                        task_root=self.root,
                        production_root=self.root,
                        evidence_root=evidence,
                        expected_account_ending=ending,
                    )
                provider.assert_not_called()
                self.assertEqual("FAIL", result["status"])
                self.assertEqual(expected_stage, result["failureStage"])
                self.assertFalse(result["providerContact"])
                self.assertEqual(
                    0,
                    result["prospectiveSummary"]["unique_prospective_members"],
                )
                self.assertTrue((evidence / "terminal-result.json").is_file())

    def test_provider_failure_preserves_attempt_and_observed_contact_separately(self) -> None:
        evidence = self.root / "provider-failure"
        task_identity, production_identity = self.write_execution_inputs(evidence)

        def provider_failure(**kwargs):
            source = (
                kwargs["generation_root"]
                / "source-evidence"
                / "finviz"
                / "attempt.json"
            )
            source.parent.mkdir(parents=True)
            source.write_text('{"status":"RECEIVED"}\n', encoding="ascii")
            self.write_resource_cleanup(kwargs["generation_root"])
            raise RuntimeError("provider runtime failed")

        with (
            mock.patch.object(
                canary,
                "_git_identity",
                side_effect=(task_identity, production_identity),
            ),
            mock.patch.object(
                canary,
                "_assert_regular_session",
                return_value="2026-08-28T09:32:00-04:00",
            ),
            mock.patch.object(
                canary,
                "run_live_qualification",
                side_effect=provider_failure,
            ),
        ):
            result = canary.execute(
                task_root=self.root,
                production_root=self.root,
                evidence_root=evidence,
                expected_account_ending="1234",
            )

        self.assertEqual("FAIL", result["status"])
        self.assertEqual("RUN_NATURAL_PROVIDER_PATH", result["failureStage"])
        self.assertTrue(result["providerContactAttempted"])
        self.assertTrue(result["providerContact"])
        self.assertEqual(1, len(result["providerContactEvidence"]))
        self.assertTrue(result["providerContactByProvider"]["finviz"]["contact"])
        self.assertFalse(result["providerContactByProvider"]["schwab"]["contact"])
        self.assertEqual("PASS", result["forensicRuntimeExport"]["status"])
        self.assertTrue(result["forensicRuntimeExport"]["sourceRetired"])

    def test_provider_contact_uses_verified_export_inventory_and_rejects_tamper(self) -> None:
        evidence = self.root / "provider-inventory"
        runtime = Path(tempfile.gettempdir()) / f"MomentumHunter-StatData002C-test-{id(self)}"
        self.addCleanup(lambda: runtime.exists() and shutil.rmtree(runtime))
        source = runtime / "source-evidence" / "finviz" / "snapshot.json"
        source.parent.mkdir(parents=True)
        source.write_text('{"status":"RECEIVED"}\n', encoding="ascii")
        self.write_resource_cleanup(runtime)

        canary._export_ephemeral_runtime(runtime_root=runtime, evidence_root=evidence)

        report = canary._provider_contact_report(evidence, None)
        self.assertTrue(report["providerContact"])
        self.assertTrue(report["providerContactByProvider"]["finviz"]["contact"])
        exported = (
            evidence
            / "natural-runtime-forensic"
            / "payload"
            / "source-evidence"
            / "finviz"
            / "snapshot.json"
        )
        exported.write_text('{"status":"TAMPERED"}\n', encoding="ascii")
        self.assertFalse(canary._provider_contact_report(evidence, None)["providerContact"])

    def test_attempt_without_preserved_provider_response_is_not_contact(self) -> None:
        evidence = self.root / "provider-attempt-only"
        runtime = Path(tempfile.gettempdir()) / f"MomentumHunter-StatData002C-empty-{id(self)}"
        self.addCleanup(lambda: runtime.exists() and shutil.rmtree(runtime))
        runtime.mkdir(parents=True)
        self.write_resource_cleanup(runtime)
        canary._export_ephemeral_runtime(runtime_root=runtime, evidence_root=evidence)

        report = canary._provider_contact_report(evidence, None)
        self.assertFalse(report["providerContact"])
        self.assertEqual([], report["providerContactEvidence"])

    def test_schwab_contact_requires_verified_success_evidence(self) -> None:
        evidence = self.root / "schwab-contact"
        runtime = Path(tempfile.gettempdir()) / f"MomentumHunter-StatData002C-schwab-{id(self)}"
        self.addCleanup(lambda: runtime.exists() and shutil.rmtree(runtime))
        runtime.mkdir(parents=True)
        (runtime / "qualification-summary.json").write_text(
            json.dumps(
                {
                    "schwabQuoteSymbols": 1,
                    "schwabMinuteRows": 390,
                    "schwabDailyRows": 30,
                }
            ),
            encoding="ascii",
        )
        self.write_resource_cleanup(runtime)
        canary._export_ephemeral_runtime(runtime_root=runtime, evidence_root=evidence)

        report = canary._provider_contact_report(
            evidence,
            {
                "schwabQuoteSymbols": 1,
                "schwabMinuteRows": 390,
                "schwabDailyRows": 30,
            },
        )

        self.assertTrue(report["providerContactByProvider"]["schwab"]["contact"])
        self.assertTrue(report["providerContactByProvider"]["schwab"]["quoteData"])
        self.assertTrue(report["providerContactByProvider"]["schwab"]["historyData"])
        self.assertEqual(2, len(report["providerContactByProvider"]["schwab"]["evidence"]))

    def test_schwab_preflight_uses_read_only_quote_history_and_disposable_stores(self) -> None:
        evidence = self.root / "schwab-preflight"
        task_identity = {"head": "1" * 40, "branch": canary.TASK_BRANCH, "status": ""}
        production_identity = {
            "head": canary.PRODUCTION_BASE,
            "branch": "master",
            "status": "",
        }
        guard = mock.Mock()
        backfiller = mock.Mock()
        backfiller.backfill.return_value = {
            "status": "COMPLETE",
            "resultFingerprint": "a" * 64,
            "symbols": [
                {"minute": {"rows": 390}, "daily": {"rows": 30}}
            ],
        }
        with (
            mock.patch.object(
                canary,
                "_git_identity",
                side_effect=(task_identity, production_identity),
            ),
            mock.patch.object(
                canary,
                "_git",
                side_effect=(task_identity["head"], canary.PRODUCTION_BASE),
            ),
            mock.patch.object(canary, "SchwabReadOnlyAccessTokenProvider"),
            mock.patch.object(
                canary,
                "SchwabMarketDataOnlyAccessGuard",
                return_value=guard,
            ),
            mock.patch.object(canary, "SchwabMarketDataQuoteSource"),
            mock.patch.object(
                canary,
                "build_regular_market_quote_proof",
                return_value={
                    "proofStatus": "PASS",
                    "clockSkewProof": {"status": "PASS"},
                    "accountDataIncluded": False,
                    "orderTransmission": "UNAVAILABLE",
                },
            ),
            mock.patch.object(
                canary,
                "SchwabHistoricalCandleBackfiller",
                return_value=backfiller,
            ),
        ):
            result = canary.run_schwab_preflight(
                task_root=self.root,
                production_root=self.root,
                evidence_root=evidence,
                expected_account_ending="1234",
            )

        self.assertEqual("PASS", result["status"])
        self.assertEqual("READY", result["schwabAuthState"])
        self.assertEqual("PASS", result["schwabQuotePreflight"])
        self.assertEqual("PASS", result["schwabHistoryPreflight"])
        self.assertFalse(result["accountValuesRequested"])
        self.assertFalse(result["positionsRequested"])
        self.assertFalse(result["ordersRequested"])
        self.assertTrue(result["disposableStoresRetired"])
        guard.authorize.assert_called_once_with("1234")
        self.assertTrue((evidence / "schwab-preflight.json").is_file())

    def test_failed_or_missing_schwab_preflight_creates_no_activation(self) -> None:
        evidence = self.root / "blocked-canary"
        with self.assertRaisesRegex(
            canary.StatDataCanaryError,
            "passing Schwab provider preflight",
        ):
            canary.prepare(
                task_root=self.root,
                production_root=self.root,
                evidence_root=evidence,
                session_date="2026-08-28",
                duration_seconds=1800,
                discovery_cadence_seconds=300,
            )
        self.assertFalse(evidence.exists())

    def test_schwab_preflight_fingerprint_and_freshness_are_enforced(self) -> None:
        proof_path = self.root / "proof.json"
        task_identity = {"head": "1" * 40, "branch": canary.TASK_BRANCH, "status": ""}
        production_identity = {
            "head": canary.PRODUCTION_BASE,
            "branch": "master",
            "status": "",
        }
        proof = {
            "status": "PASS",
            "observedAt": datetime.now(ZoneInfo("UTC")).isoformat(),
            "taskGit": task_identity,
            "productionGit": production_identity,
            "schwabAuthState": "READY",
            "schwabQuotePreflight": "PASS",
            "schwabHistoryPreflight": "PASS",
            "schwabInteractiveReauthRequired": False,
            "disposableStoresRetired": True,
            "accountValuesRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "executionAuthority": canary.EXECUTION_AUTHORITY,
        }
        proof["fingerprint"] = canary._fingerprint(
            "stat-data-002c-schwab-preflight-v1",
            proof,
        )
        canary._write_once(proof_path, proof)
        with mock.patch.object(
            canary,
            "_git_identity",
            side_effect=(task_identity, production_identity),
        ):
            loaded = canary._validate_schwab_preflight(
                proof_path,
                task_root=self.root,
                production_root=self.root,
            )
        self.assertEqual(proof["fingerprint"], loaded["fingerprint"])

        payload = json.loads(proof_path.read_text(encoding="ascii"))
        payload["schwabHistoryPreflight"] = "FAIL"
        proof_path.write_text(json.dumps(payload), encoding="ascii")
        with self.assertRaisesRegex(canary.StatDataCanaryError, "fingerprint"):
            canary._validate_schwab_preflight(
                proof_path,
                task_root=self.root,
                production_root=self.root,
            )

    def test_summary_failure_is_preserved_without_losing_terminal_record(self) -> None:
        evidence = self.root / "summary-failure"
        task_identity, production_identity = self.write_execution_inputs(evidence)

        def provider_failure(**kwargs):
            (evidence / "prospective-denominator").mkdir()
            kwargs["generation_root"].mkdir(parents=True)
            self.write_resource_cleanup(kwargs["generation_root"])
            raise RuntimeError("provider runtime failed")

        with (
            mock.patch.object(
                canary,
                "_git_identity",
                side_effect=(task_identity, production_identity),
            ),
            mock.patch.object(
                canary,
                "_assert_regular_session",
                return_value="2026-08-28T09:32:00-04:00",
            ),
            mock.patch.object(
                canary,
                "run_live_qualification",
                side_effect=provider_failure,
            ),
            mock.patch.object(
                canary.ProspectiveDenominatorStore,
                "summary",
                side_effect=RuntimeError("summary unavailable"),
            ),
        ):
            result = canary.execute(
                task_root=self.root,
                production_root=self.root,
                evidence_root=evidence,
                expected_account_ending="1234",
            )

        self.assertEqual("FAIL", result["status"])
        self.assertIsNone(result["prospectiveSummary"])
        self.assertEqual(
            "RuntimeError",
            result["prospectiveSummaryError"]["exceptionClass"],
        )
        self.assertTrue((evidence / "terminal-result.json").is_file())

    def test_run_all_packages_terminal_failure_even_when_verification_raises(self) -> None:
        evidence = self.root / "terminal-failure"

        def prepare_root(**kwargs):
            self.write_execution_inputs(kwargs["evidence_root"])
            return {"status": "PASS"}

        def emit_package(**kwargs):
            zip_path = kwargs["evidence_root"].parent / "safe.zip"
            zip_path.write_bytes(b"sanitized-package")
            return {
                "status": "PASS",
                "zipPath": str(zip_path),
                "secretScan": "PASS",
            }

        arguments = (
            "run-all",
            "--task-root",
            str(self.root),
            "--production-root",
            str(self.root),
            "--evidence-root",
            str(evidence),
            "--session-date",
            "2026-08-28",
            "--python-executable",
            str(Path(__file__)),
        )
        with (
            mock.patch.object(canary, "prepare", side_effect=prepare_root),
            mock.patch.object(
                canary,
                "load_activation_record",
                side_effect=canary.StatDataCanaryError("activation reload failed"),
            ),
            mock.patch.object(
                canary,
                "package",
                side_effect=emit_package,
            ) as package,
            mock.patch("builtins.print"),
        ):
            return_code = canary.main(arguments)

        self.assertEqual(1, return_code)
        package.assert_called_once()
        terminal = json.loads(
            (evidence / "terminal-result.json").read_text(encoding="ascii")
        )
        self.assertEqual("FAIL", terminal["status"])
        self.assertEqual("LOAD_ACTIVATION", terminal["failureStage"])
        self.assertFalse(terminal["providerContact"])
        self.assertEqual(0, terminal["prospectiveSummary"]["unique_prospective_members"])
        self.assertTrue((self.root / "safe.zip").is_file())
        self.assertFalse((evidence / "prospective-denominator").exists())
        failure = json.loads(
            (evidence / "verification-failure.json").read_text(encoding="ascii")
        )
        self.assertEqual("FAIL", failure["status"])


if __name__ == "__main__":
    unittest.main()
