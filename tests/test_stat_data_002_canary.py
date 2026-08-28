from __future__ import annotations

import json
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
                self.assertTrue((evidence / "terminal-result.json").is_file())

    def test_provider_failure_preserves_attempt_and_observed_contact_separately(self) -> None:
        evidence = self.root / "provider-failure"
        task_identity, production_identity = self.write_execution_inputs(evidence)

        def provider_failure(**kwargs):
            source = (
                evidence
                / "natural-runtime"
                / "runtime-artifacts"
                / "source-evidence"
                / "finviz"
                / "attempt.json"
            )
            source.parent.mkdir(parents=True)
            source.write_text('{"status":"RECEIVED"}\n', encoding="ascii")
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
