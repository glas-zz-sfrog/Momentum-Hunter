from __future__ import annotations

import json
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
    observe_opening_runtime,
)


UTC = timezone.utc
HEAD_A = "a" * 40
HEAD_B = "b" * 40


class OpeningRuntimeObserverTests(unittest.TestCase):
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
            self.environment,
            "environmentFingerprint",
        )
        self.store = OpeningRuntimeReleaseStore(self.release_root)
        self.release_a = self._release(HEAD_A)
        self.store.promote(
            self.release_a,
            current_git_sha=HEAD_A,
            promoted_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _release(
        self,
        source_git_sha: str,
        *,
        predecessor: str = "",
    ) -> dict[str, object]:
        return build_release_record(
            self.context,
            source_git_sha=source_git_sha,
            qualification_evidence=[f"fixture://{source_git_sha}"],
            predecessor_release_id=predecessor,
            created_at=datetime(2026, 8, 30, 11, 59, tzinfo=UTC),
            environment=self.environment,
        )

    def _observation(
        self,
        release: dict[str, object] | None = None,
        *,
        canonical_sha: str = HEAD_A,
        clean: bool = True,
    ) -> dict[str, object]:
        active = release or self.release_a
        return {
            "schemaVersion": OBSERVATION_SCHEMA,
            "actualReleaseId": active["releaseId"],
            "actualRuntimeFingerprint": active["approvedRuntimeFingerprint"],
            "actualCanonicalGitSha": canonical_sha,
            "canonicalWorktreeClean": clean,
        }

    def _observe(
        self,
        observation: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        return observe_opening_runtime(
            observation,
            expected_canonical_git_sha=HEAD_A,
            release_root=self.release_root,
            **kwargs,
        )

    def test_current_authorized_runtime_match_passes(self) -> None:
        result = self._observe(self._observation())

        self.assertEqual("PASS", result["observerResult"])
        self.assertEqual("AUTHORIZED_RUNTIME_MATCH", result["classification"])
        self.assertEqual(self.release_a["releaseId"], result["expectedReleaseId"])
        self.assertFalse(result["runtimeDrift"])

    def test_authorized_successor_rejects_predecessor_runtime(self) -> None:
        predecessor_observation = self._observation()
        self._promote_successor()

        result = self._observe(predecessor_observation)

        self.assertEqual("FAIL", result["observerResult"])
        self.assertEqual("RUNTIME_DRIFT", result["diagnosticCode"])

    def test_unknown_actual_fingerprint_fails(self) -> None:
        observation = self._observation()
        observation["actualRuntimeFingerprint"] = "UNKNOWN"

        result = self._observe(observation)

        self.assertEqual("RUNTIME_EVIDENCE_INVALID", result["classification"])
        self.assertEqual(
            "ACTUAL_RUNTIME_FINGERPRINT_INVALID",
            result["diagnosticCode"],
        )

    def test_missing_channel_fails_closed(self) -> None:
        self.store.pointer_path(DEFAULT_CHANNEL).unlink()

        result = self._observe(self._observation())

        self.assertEqual("UNKNOWN_AUTHORIZED_RELEASE", result["classification"])
        self.assertEqual("RELEASE_POINTER_MISSING", result["diagnosticCode"])
        self.assertTrue(result["failClosed"])

    def test_missing_authority_root_fails_without_creating_it(self) -> None:
        missing_root = self.root / "missing-authority"

        result = observe_opening_runtime(
            self._observation(),
            expected_canonical_git_sha=HEAD_A,
            release_root=missing_root,
        )

        self.assertEqual("UNKNOWN_AUTHORIZED_RELEASE", result["classification"])
        self.assertEqual("RELEASE_AUTHORITY_ROOT_MISSING", result["diagnosticCode"])
        self.assertFalse(missing_root.exists())

    def test_malformed_promotion_receipt_fails_closed(self) -> None:
        receipt_path = self.store._promotion_files()[0]
        receipt_path.write_text("{not-json", encoding="utf-8")

        result = self._observe(self._observation())

        self.assertEqual("UNKNOWN_AUTHORIZED_RELEASE", result["classification"])
        self.assertEqual("RELEASE_RECORD_MALFORMED", result["diagnosticCode"])

    def test_matching_release_name_with_different_fingerprint_fails(self) -> None:
        observation = self._observation()
        observation["actualRuntimeFingerprint"] = "0" * 64

        result = self._observe(observation)

        self.assertEqual("RUNTIME_DRIFT", result["classification"])

    def test_matching_fingerprint_with_inconsistent_authority_fails_closed(self) -> None:
        pointer_path = self.store.pointer_path(DEFAULT_CHANNEL)
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["predecessorReleaseId"] = "OPENING-RUNTIME-" + "0" * 20
        pointer["pointerFingerprint"] = payload_fingerprint(
            pointer,
            "pointerFingerprint",
        )
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

        result = self._observe(self._observation())

        self.assertEqual("UNKNOWN_AUTHORIZED_RELEASE", result["classification"])
        self.assertEqual("RELEASE_POINTER_CHAIN_INVALID", result["diagnosticCode"])

    def test_canonical_drift_and_dirty_worktree_each_fail(self) -> None:
        for observation in (
            self._observation(canonical_sha=HEAD_B),
            self._observation(clean=False),
        ):
            with self.subTest(observation=observation):
                result = self._observe(observation)
                self.assertEqual("CANONICAL_DRIFT", result["classification"])
                self.assertTrue(result["canonicalDrift"])

    def test_promotion_after_observer_creation_resolves_successor_at_run_time(self) -> None:
        stale_fixed_release = str(self.release_a["releaseId"])
        stale_fixed_fingerprint = str(self.release_a["approvedRuntimeFingerprint"])
        release_b = self._promote_successor()

        current = self._observe(self._observation(release_b))
        fixed = self._observe(
            self._observation(release_b),
            mode=FIXED_EXPECTED_RELEASE,
            fixed_expected_release_id=stale_fixed_release,
            fixed_expected_runtime_fingerprint=stale_fixed_fingerprint,
        )

        self.assertEqual(CURRENT_AUTHORIZED_RELEASE, current["mode"])
        self.assertEqual(release_b["releaseId"], current["expectedReleaseId"])
        self.assertEqual("PASS", current["observerResult"])
        self.assertEqual(FIXED_EXPECTED_RELEASE, fixed["mode"])
        self.assertEqual("RUNTIME_DRIFT", fixed["classification"])

    def test_fixed_mode_requires_release_bound_identity(self) -> None:
        result = self._observe(
            self._observation(),
            mode=FIXED_EXPECTED_RELEASE,
            fixed_expected_release_id=str(self.release_a["releaseId"]),
            fixed_expected_runtime_fingerprint="0" * 64,
        )

        self.assertEqual("UNKNOWN_AUTHORIZED_RELEASE", result["classification"])
        self.assertEqual(
            "FIXED_EXPECTATION_CONTRADICTS_RELEASE",
            result["diagnosticCode"],
        )

    def _promote_successor(self) -> dict[str, object]:
        provider = self.repository / "momentum_hunter" / "providers.py"
        provider.write_text("providers.py = 2\n", encoding="utf-8")
        release_b = self._release(
            HEAD_B,
            predecessor=str(self.release_a["releaseId"]),
        )
        self.store.promote(
            release_b,
            current_git_sha=HEAD_B,
            promoted_at=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        )
        return release_b


if __name__ == "__main__":
    unittest.main()
