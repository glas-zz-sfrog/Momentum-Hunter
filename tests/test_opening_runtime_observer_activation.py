from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.opening_runtime_identity import (
    DEFAULT_CHANNEL,
    OpeningRuntimeReleaseStore,
    RuntimeIdentityContext,
    build_release_record,
    file_sha256,
    payload_fingerprint,
)
from momentum_hunter.opening_runtime_observer import (
    CURRENT_AUTHORIZED_RELEASE,
    FIXED_EXPECTED_RELEASE,
    OBSERVATION_SCHEMA,
)
from momentum_hunter.opening_runtime_observer_activation import (
    OpeningObserverActivationError,
    build_observer_receipt,
    build_operational_automation_prompt,
    create_observer_activation,
    validate_observer_activation,
    write_new_json,
)


UTC = timezone.utc
HEAD_A = "a" * 40
HEAD_B = "b" * 40
HEAD_C = "c" * 40


class OpeningRuntimeObserverActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repo"
        package = self.repository / "momentum_hunter"
        tools = self.repository / "tools"
        data = self.repository / "MomentumHunterData"
        package.mkdir(parents=True)
        tools.mkdir()
        data.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        for name in (
            "automation_supervisor.py",
            "opening_runtime_identity.py",
            "providers.py",
            "models.py",
            "scoring.py",
            "trade_planning.py",
            "scheduling.py",
        ):
            (package / name).write_text(f"{name} = 1\n", encoding="utf-8")
        (tools / "capture_job.py").write_text("CAPTURE = 1\n", encoding="utf-8")
        (tools / "run_capture_job.ps1").write_text("exit 0\n", encoding="utf-8")
        (self.repository / "requirements.txt").write_text(
            "requests==2.32.3\n", encoding="utf-8"
        )
        (data / "config.json").write_text(
            json.dumps(
                {
                    "mode": "PAPER",
                    "provider": "finviz",
                    "review_timezone": "America/Chicago",
                    "evening_review_window": "7:00 PM - 8:00 PM CT",
                    "morning_review_window": "7:00 AM - 8:00 AM CT",
                }
            ),
            encoding="utf-8",
        )
        self.python = self.root / "python.exe"
        self.powershell = self.root / "powershell.exe"
        self.service_host = self.root / "service.exe"
        for path, value in (
            (self.python, "python"),
            (self.powershell, "powershell"),
            (self.service_host, "service"),
        ):
            path.write_text(value, encoding="utf-8")
        self.release_root = self.root / "opening-runtime"
        self.context = RuntimeIdentityContext(
            repository_root=self.repository,
            python_executable=self.python,
            powershell_executable=self.powershell,
            state_directory=self.root / "state",
            engine_host_state_directory=self.root / "engine",
            poll_interval_seconds=1,
            service_host_executable=self.service_host,
            release_root=self.release_root,
        )
        self.environment = {
            "schemaVersion": "OpeningRuntimeEnvironmentV1",
            "fixture": "stable",
            "serviceHost": {"sha256": file_sha256(self.service_host)},
        }
        self.environment["environmentFingerprint"] = payload_fingerprint(
            self.environment, "environmentFingerprint"
        )
        self.store = OpeningRuntimeReleaseStore(self.release_root)
        self.release_a = self._release(HEAD_A)
        self.store.promote(
            self.release_a,
            current_git_sha=HEAD_A,
            promoted_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _release(
        self, source_git_sha: str, *, predecessor: str = ""
    ) -> dict[str, object]:
        return build_release_record(
            self.context,
            source_git_sha=source_git_sha,
            qualification_evidence=[f"fixture://{source_git_sha}"],
            predecessor_release_id=predecessor,
            created_at=datetime(2026, 8, 31, 11, 59, tzinfo=UTC),
            environment=self.environment,
        )

    def _promote(
        self, source_git_sha: str, predecessor: dict[str, object]
    ) -> dict[str, object]:
        provider = self.repository / "momentum_hunter" / "providers.py"
        provider.write_text(f"providers.py = {source_git_sha[0]}\n", encoding="utf-8")
        release = self._release(
            source_git_sha, predecessor=str(predecessor["releaseId"])
        )
        self.store.promote(
            release,
            current_git_sha=source_git_sha,
            promoted_at=datetime(2026, 8, 31, 13, 0, tzinfo=UTC),
        )
        return release

    @staticmethod
    def _observation(
        release: dict[str, object], *, canonical_sha: str
    ) -> dict[str, object]:
        return {
            "schemaVersion": OBSERVATION_SCHEMA,
            "actualReleaseId": release["releaseId"],
            "actualRuntimeFingerprint": release["approvedRuntimeFingerprint"],
            "actualCanonicalGitSha": canonical_sha,
            "canonicalWorktreeClean": True,
        }

    def _current_activation(self) -> dict[str, object]:
        return create_observer_activation(
            created_at=datetime(2026, 8, 31, 12, 5, tzinfo=UTC)
        )

    def test_default_operational_payload_is_current_and_contains_no_fixed_identity(
        self,
    ) -> None:
        activation = self._current_activation()
        prompt = build_operational_automation_prompt(activation)

        self.assertEqual(CURRENT_AUTHORIZED_RELEASE, activation["mode"])
        self.assertNotIn("fixedExpectedIdentity", activation)
        self.assertNotIn("OPENING-RUNTIME-", prompt)
        self.assertIn("AT_OBSERVATION_TIME", prompt)
        self.assertIn(CURRENT_AUTHORIZED_RELEASE, prompt)
        self.assertIn(
            "python -m tools.prepare_opening_runtime_observer observe", prompt
        )

    def test_current_mode_plus_fixed_identity_is_rejected(self) -> None:
        with self.assertRaises(OpeningObserverActivationError) as captured:
            create_observer_activation(
                created_at=datetime(2026, 8, 31, 12, 5, tzinfo=UTC),
                fixed_expected_release_id=str(self.release_a["releaseId"]),
                fixed_expected_runtime_fingerprint=str(
                    self.release_a["approvedRuntimeFingerprint"]
                ),
            )

        self.assertEqual(
            "CURRENT_MODE_FIXED_IDENTITY_AMBIGUOUS", captured.exception.code
        )

    def test_fixed_mode_requires_explicit_complete_identity(self) -> None:
        with self.assertRaises(OpeningObserverActivationError) as captured:
            create_observer_activation(
                created_at=datetime(2026, 8, 31, 12, 5, tzinfo=UTC),
                mode=FIXED_EXPECTED_RELEASE,
            )

        self.assertEqual("FIXED_EXPECTATION_INVALID", captured.exception.code)

    def test_fixed_historical_mode_delegates_to_accepted_verifier(self) -> None:
        activation = create_observer_activation(
            created_at=datetime(2026, 8, 31, 12, 5, tzinfo=UTC),
            mode=FIXED_EXPECTED_RELEASE,
            fixed_expected_release_id=str(self.release_a["releaseId"]),
            fixed_expected_runtime_fingerprint=str(
                self.release_a["approvedRuntimeFingerprint"]
            ),
        )

        receipt = build_observer_receipt(
            activation,
            self._observation(self.release_a, canonical_sha=HEAD_A),
            expected_canonical_git_sha=HEAD_A,
            observed_at=datetime(2026, 8, 31, 12, 10, tzinfo=UTC),
            release_root=self.release_root,
        )

        self.assertEqual("PASS", receipt["observerResult"])
        self.assertEqual(FIXED_EXPECTED_RELEASE, receipt["observerMode"])
        self.assertTrue(receipt["authorizedReleaseVerified"])
        self.assertFalse(receipt["promotionChainVerified"])

    def test_promotion_between_creation_and_run_resolves_successor(self) -> None:
        activation = self._current_activation()
        release_b = self._promote(HEAD_B, self.release_a)

        receipt = build_observer_receipt(
            activation,
            self._observation(release_b, canonical_sha=HEAD_A),
            expected_canonical_git_sha=HEAD_A,
            observed_at=datetime(2026, 8, 31, 13, 5, tzinfo=UTC),
            release_root=self.release_root,
        )

        self.assertEqual("PASS", receipt["observerResult"])
        self.assertEqual(
            release_b["releaseId"],
            receipt["authoritySnapshot"]["authorizedReleaseId"],
        )

    def test_observation_authority_snapshot_is_write_once_and_immutable(self) -> None:
        activation = self._current_activation()
        release_b = self._promote(HEAD_B, self.release_a)
        receipt = build_observer_receipt(
            activation,
            self._observation(release_b, canonical_sha=HEAD_A),
            expected_canonical_git_sha=HEAD_A,
            observed_at=datetime(2026, 8, 31, 13, 5, tzinfo=UTC),
            release_root=self.release_root,
        )
        receipt_path = self.root / "receipt.json"
        write_new_json(receipt_path, receipt)
        before = receipt_path.read_bytes()

        self._promote(HEAD_C, release_b)

        self.assertEqual(before, receipt_path.read_bytes())
        with self.assertRaises(FileExistsError):
            write_new_json(receipt_path, receipt)

    def test_predecessor_runtime_fails_after_successor_promotion(self) -> None:
        activation = self._current_activation()
        self._promote(HEAD_B, self.release_a)

        receipt = build_observer_receipt(
            activation,
            self._observation(self.release_a, canonical_sha=HEAD_A),
            expected_canonical_git_sha=HEAD_A,
            observed_at=datetime(2026, 8, 31, 13, 5, tzinfo=UTC),
            release_root=self.release_root,
        )

        self.assertEqual("RUNTIME_DRIFT", receipt["classification"])
        self.assertTrue(receipt["failClosed"])

    def test_missing_channel_fails_closed_in_operational_receipt(self) -> None:
        self.store.pointer_path(DEFAULT_CHANNEL).unlink()

        receipt = build_observer_receipt(
            self._current_activation(),
            self._observation(self.release_a, canonical_sha=HEAD_A),
            expected_canonical_git_sha=HEAD_A,
            observed_at=datetime(2026, 8, 31, 13, 5, tzinfo=UTC),
            release_root=self.release_root,
        )

        self.assertEqual("UNKNOWN_AUTHORIZED_RELEASE", receipt["classification"])
        self.assertEqual("RELEASE_POINTER_MISSING", receipt["diagnosticCode"])
        self.assertFalse(receipt["promotionChainVerified"])

    def test_malformed_channel_fails_closed(self) -> None:
        self.store.pointer_path(DEFAULT_CHANNEL).write_text("{bad-json", encoding="utf-8")

        receipt = build_observer_receipt(
            self._current_activation(),
            self._observation(self.release_a, canonical_sha=HEAD_A),
            expected_canonical_git_sha=HEAD_A,
            observed_at=datetime(2026, 8, 31, 13, 5, tzinfo=UTC),
            release_root=self.release_root,
        )

        self.assertEqual("UNKNOWN_AUTHORIZED_RELEASE", receipt["classification"])
        self.assertEqual("RELEASE_RECORD_MALFORMED", receipt["diagnosticCode"])

    def test_dirty_canonical_state_fails(self) -> None:
        observation = self._observation(self.release_a, canonical_sha=HEAD_A)
        observation["canonicalWorktreeClean"] = False

        receipt = build_observer_receipt(
            self._current_activation(),
            observation,
            expected_canonical_git_sha=HEAD_A,
            observed_at=datetime(2026, 8, 31, 13, 5, tzinfo=UTC),
            release_root=self.release_root,
        )

        self.assertEqual("CANONICAL_DRIFT", receipt["classification"])

    def test_activation_fingerprint_detects_payload_tampering(self) -> None:
        activation = self._current_activation()
        activation["mutationAllowed"] = True

        with self.assertRaises(OpeningObserverActivationError) as captured:
            validate_observer_activation(activation)

        self.assertEqual("OBSERVER_ACTIVATION_AUTHORITY_INVALID", captured.exception.code)

    def test_receipt_preserves_required_authority_and_safety_fields(self) -> None:
        receipt = build_observer_receipt(
            self._current_activation(),
            self._observation(self.release_a, canonical_sha=HEAD_A),
            expected_canonical_git_sha=HEAD_A,
            observed_at=datetime(2026, 8, 31, 13, 5, tzinfo=UTC),
            release_root=self.release_root,
        )

        self.assertEqual("PASS", receipt["observerResult"])
        self.assertTrue(receipt["promotionChainVerified"])
        self.assertFalse(receipt["mutationPerformed"])
        self.assertFalse(receipt["providerContact"])
        self.assertEqual("UNAVAILABLE", receipt["orderTransmission"])
        self.assertEqual(HEAD_A, receipt["actualObservation"]["canonicalGitSha"])
        self.assertTrue(receipt["receiptFingerprint"])

    def test_module_cli_creates_and_validates_current_activation(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        activation_path = self.root / "cli-activation.json"
        prompt_path = self.root / "cli-prompt.txt"
        created = subprocess.run(
            (
                sys.executable,
                "-B",
                "-m",
                "tools.prepare_opening_runtime_observer",
                "create",
                "--activation",
                str(activation_path),
                "--prompt",
                str(prompt_path),
                "--created-at",
                "2026-08-31T12:05:00+00:00",
            ),
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
        validated = subprocess.run(
            (
                sys.executable,
                "-B",
                "-m",
                "tools.prepare_opening_runtime_observer",
                "validate",
                "--activation",
                str(activation_path),
            ),
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(0, created.returncode, created.stderr)
        self.assertEqual(0, validated.returncode, validated.stderr)
        self.assertIn("OBSERVER_ACTIVATION_CREATED", created.stdout)
        self.assertIn("OBSERVER_ACTIVATION_VALID", validated.stdout)
        self.assertNotIn("OPENING-RUNTIME-", prompt_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
