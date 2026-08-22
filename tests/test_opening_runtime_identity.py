from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.opening_runtime_identity import (
    DEFAULT_CHANNEL,
    OpeningRuntimeIdentityError,
    OpeningRuntimeReleaseStore,
    RuntimeIdentityContext,
    build_release_record,
    build_runtime_identity,
    build_runtime_surface,
    file_sha256,
    payload_fingerprint,
    probe_runtime_environment,
    verify_execution_gate,
)


UTC = timezone.utc
HEAD_A = "a" * 40
HEAD_B = "b" * 40


class OpeningRuntimeIdentityTests(unittest.TestCase):
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
        (package / "automation_supervisor.py").write_text(
            "SUPERVISOR = 1\n", encoding="utf-8"
        )
        (package / "opening_runtime_identity.py").write_text(
            "IDENTITY = 1\n", encoding="utf-8"
        )
        for name, value in (
            ("providers.py", "PROVIDER"),
            ("models.py", "CANDIDATE"),
            ("scoring.py", "SCORING"),
            ("trade_planning.py", "TRADE_PLAN"),
            ("scheduling.py", "CALENDAR"),
        ):
            (package / name).write_text(f"{value} = 1\n", encoding="utf-8")
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
        (self.repository / "docs").mkdir()
        (self.repository / "docs" / "ROADMAP.md").write_text(
            "baseline\n", encoding="utf-8"
        )
        (self.repository / "tests").mkdir()
        (self.repository / "tests" / "test_only.py").write_text(
            "TEST = 1\n", encoding="utf-8"
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
        self.release_root = self.root / "releases"
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
        environment = {
            "schemaVersion": "OpeningRuntimeEnvironmentV1",
            "fixture": "stable",
            "serviceHost": {"sha256": file_sha256(self.service_host)},
        }
        environment["environmentFingerprint"] = payload_fingerprint(
            environment,
            "environmentFingerprint",
        )
        self.environment = environment

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def identity(self) -> dict[str, object]:
        return build_runtime_identity(self.context, environment=self.environment)

    def release(self, *, predecessor: str = "") -> dict[str, object]:
        return build_release_record(
            self.context,
            source_git_sha=HEAD_A,
            qualification_evidence=["fixture://hard-chew-pass"],
            predecessor_release_id=predecessor,
            created_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
            environment=self.environment,
        )

    def promote(self) -> dict[str, object]:
        record = self.release()
        OpeningRuntimeReleaseStore(self.release_root).promote(
            record,
            current_git_sha=HEAD_A,
            promoted_at=datetime(2026, 8, 21, 12, 1, tzinfo=UTC),
        )
        return record

    def loaded_hashes(self, record: dict[str, object]) -> tuple[str, str, str]:
        components = {
            item["path"]: item["sha256"]
            for item in record["runtimeComponents"]
        }
        return (
            components["momentum_hunter/automation_supervisor.py"],
            components["momentum_hunter/opening_runtime_identity.py"],
            record["environmentIdentity"]["serviceHost"]["sha256"],
        )

    def test_docs_governance_review_and_test_changes_do_not_change_identity(self) -> None:
        before = self.identity()["approvedRuntimeFingerprint"]

        (self.repository / "docs" / "ROADMAP.md").write_text(
            "new governance\n", encoding="utf-8"
        )
        (self.repository / "docs" / "review-copy.md").write_text(
            "review\n", encoding="utf-8"
        )
        (self.repository / "tests" / "test_only.py").write_text(
            "TEST = 2\n", encoding="utf-8"
        )

        self.assertEqual(before, self.identity()["approvedRuntimeFingerprint"])

    def test_modify_add_delete_and_rename_runtime_files_change_identity(self) -> None:
        baseline = build_runtime_surface(self.repository)["runtimeSurfaceFingerprint"]
        provider = self.repository / "momentum_hunter" / "providers.py"

        provider.write_text("PROVIDER = 2\n", encoding="utf-8")
        modified = build_runtime_surface(self.repository)["runtimeSurfaceFingerprint"]
        self.assertNotEqual(baseline, modified)

        added_path = self.repository / "momentum_hunter" / "new_runtime.py"
        added_path.write_text("NEW = 1\n", encoding="utf-8")
        added = build_runtime_surface(self.repository)["runtimeSurfaceFingerprint"]
        self.assertNotEqual(modified, added)

        added_path.unlink()
        deleted = build_runtime_surface(self.repository)["runtimeSurfaceFingerprint"]
        self.assertNotEqual(added, deleted)

        renamed = provider.with_name("provider_contract.py")
        provider.rename(renamed)
        rename_identity = build_runtime_surface(self.repository)[
            "runtimeSurfaceFingerprint"
        ]
        self.assertNotEqual(deleted, rename_identity)

    def test_every_opening_execution_class_changes_runtime_identity(self) -> None:
        paths = (
            "momentum_hunter/automation_supervisor.py",
            "tools/run_capture_job.ps1",
            "tools/capture_job.py",
            "momentum_hunter/providers.py",
            "momentum_hunter/models.py",
            "momentum_hunter/scoring.py",
            "momentum_hunter/trade_planning.py",
            "momentum_hunter/scheduling.py",
            "requirements.txt",
        )
        for relative in paths:
            with self.subTest(relative=relative):
                path = self.repository / relative
                original = path.read_bytes()
                before = build_runtime_surface(self.repository)[
                    "runtimeSurfaceFingerprint"
                ]
                path.write_bytes(original + b"\n# mutation\n")
                after = build_runtime_surface(self.repository)[
                    "runtimeSurfaceFingerprint"
                ]
                path.write_bytes(original)
                self.assertNotEqual(before, after)

    def test_config_and_environment_changes_invalidate_identity(self) -> None:
        baseline = self.identity()["approvedRuntimeFingerprint"]
        config_path = self.repository / "MomentumHunterData" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["provider"] = "fixture-provider"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.assertNotEqual(baseline, self.identity()["approvedRuntimeFingerprint"])

        config["provider"] = "finviz"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        changed_environment = dict(self.environment)
        changed_environment["fixture"] = "drifted"
        changed_environment["environmentFingerprint"] = payload_fingerprint(
            changed_environment,
            "environmentFingerprint",
        )
        self.assertNotEqual(
            baseline,
            build_runtime_identity(
                self.context,
                environment=changed_environment,
            )["approvedRuntimeFingerprint"],
        )

    def test_unclassified_config_fails_closed_instead_of_escaping_identity(self) -> None:
        config_path = self.repository / "MomentumHunterData" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["new_runtime_switch"] = True
        config_path.write_text(json.dumps(config), encoding="utf-8")

        with self.assertRaisesRegex(
            OpeningRuntimeIdentityError,
            "unclassified",
        ) as raised:
            self.identity()

        self.assertEqual("RUNTIME_CONFIG_UNCLASSIFIED", raised.exception.code)

    def test_docs_only_git_divergence_passes_and_records_both_git_identities(self) -> None:
        record = self.promote()
        supervisor_hash, identity_hash, service_hash = self.loaded_hashes(record)
        (self.repository / "docs" / "ROADMAP.md").write_text(
            "commit B docs\n", encoding="utf-8"
        )

        result = verify_execution_gate(
            self.context,
            channel=DEFAULT_CHANNEL,
            loaded_supervisor_sha256=supervisor_hash,
            loaded_identity_module_sha256=identity_hash,
            loaded_service_host_sha256=service_hash,
            environment=self.environment,
            git_identity=(HEAD_B, ""),
        )

        self.assertEqual(HEAD_A, result.release_source_git_sha)
        self.assertEqual(HEAD_B, result.current_git_sha)
        self.assertTrue(result.runtime_match)

    def test_runtime_mutation_rejects_before_authority(self) -> None:
        record = self.promote()
        supervisor_hash, identity_hash, service_hash = self.loaded_hashes(record)
        (self.repository / "tools" / "capture_job.py").write_text(
            "CAPTURE = 2\n", encoding="utf-8"
        )

        with self.assertRaises(OpeningRuntimeIdentityError) as raised:
            verify_execution_gate(
                self.context,
                loaded_supervisor_sha256=supervisor_hash,
                loaded_identity_module_sha256=identity_hash,
                loaded_service_host_sha256=service_hash,
                environment=self.environment,
                git_identity=(HEAD_B, ""),
            )

        self.assertEqual("APPROVED_RUNTIME_MISMATCH", raised.exception.code)

    def test_dirty_worktree_is_rejected_even_when_runtime_bytes_match(self) -> None:
        record = self.promote()
        supervisor_hash, identity_hash, service_hash = self.loaded_hashes(record)

        with self.assertRaises(OpeningRuntimeIdentityError) as raised:
            verify_execution_gate(
                self.context,
                loaded_supervisor_sha256=supervisor_hash,
                loaded_identity_module_sha256=identity_hash,
                loaded_service_host_sha256=service_hash,
                environment=self.environment,
                git_identity=(HEAD_B, " M docs/ROADMAP.md"),
            )

        self.assertEqual("RUNTIME_WORKTREE_DIRTY", raised.exception.code)

    def test_loaded_supervisor_and_gate_must_match_release(self) -> None:
        record = self.promote()
        supervisor_hash, identity_hash, service_hash = self.loaded_hashes(record)
        for loaded_supervisor, loaded_identity, loaded_service, expected in (
            ("0" * 64, identity_hash, service_hash, "LOADED_SUPERVISOR_MISMATCH"),
            (supervisor_hash, "0" * 64, service_hash, "LOADED_IDENTITY_GATE_MISMATCH"),
            (supervisor_hash, identity_hash, "0" * 64, "LOADED_SERVICE_HOST_MISMATCH"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(OpeningRuntimeIdentityError) as raised:
                    verify_execution_gate(
                        self.context,
                        loaded_supervisor_sha256=loaded_supervisor,
                        loaded_identity_module_sha256=loaded_identity,
                        loaded_service_host_sha256=loaded_service,
                        environment=self.environment,
                        git_identity=(HEAD_A, ""),
                    )
                self.assertEqual(expected, raised.exception.code)

    def test_release_pointer_and_receipt_tamper_each_fail_closed(self) -> None:
        self.promote()
        store = OpeningRuntimeReleaseStore(self.release_root)
        targets = [
            store.pointer_path(DEFAULT_CHANNEL),
            store._promotion_files()[0],
            store.release_path(store.verify_channel()[0]["releaseId"]),
        ]
        for target in targets:
            with self.subTest(target=target.name):
                original = target.read_bytes()
                payload = json.loads(original)
                payload["tampered"] = True
                target.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(OpeningRuntimeIdentityError):
                    store.verify_channel()
                target.write_bytes(original)
                store.verify_channel()

    def test_environment_identity_includes_all_installed_distributions(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(arguments: tuple[str, ...]) -> str:
            calls.append(arguments)
            if arguments[0] == "tzutil.exe":
                return "Central Standard Time"
            if arguments[0] == str(self.python) and arguments[1] == "--version":
                return "Python 3.12.0"
            if arguments[0] == str(self.powershell):
                return "7.5.0"
            return json.dumps(
                {"requests": "2.32.3", "urllib3": "2.5.0", "certifi": "2026.1"}
            )

        environment = probe_runtime_environment(self.context, command_runner=runner)

        self.assertEqual(["requests"], environment["declaredRequirements"])
        self.assertEqual(
            {"requests": "2.32.3", "urllib3": "2.5.0", "certifi": "2026.1"},
            environment["installedDistributions"],
        )
        package_probe = next(call for call in calls if "-c" in call)
        self.assertIn("m.distributions()", package_probe[3])

    def test_historical_release_and_receipt_filename_are_bound_to_chain(self) -> None:
        store = OpeningRuntimeReleaseStore(self.release_root)
        release_a = self.release()
        store.promote(release_a, current_git_sha=HEAD_A)
        provider = self.repository / "momentum_hunter" / "providers.py"
        provider.write_bytes(provider.read_bytes() + b"\n# release B\n")
        release_b = build_release_record(
            self.context,
            source_git_sha=HEAD_B,
            qualification_evidence=["fixture://hard-chew-pass-b"],
            predecessor_release_id=release_a["releaseId"],
            environment=self.environment,
        )
        store.promote(release_b, current_git_sha=HEAD_B)

        historical_path = store.release_path(release_a["releaseId"])
        historical_bytes = historical_path.read_bytes()
        historical_path.unlink()
        with self.assertRaises(OpeningRuntimeIdentityError) as missing:
            store.verify_channel()
        self.assertEqual("RELEASE_RECORD_MISSING", missing.exception.code)
        historical_path.write_bytes(historical_bytes)

        receipt = store._promotion_files()[0]
        renamed = receipt.with_name("000001-OPENING-RUNTIME-00000000000000000000.json")
        receipt.rename(renamed)
        with self.assertRaises(OpeningRuntimeIdentityError) as wrong_name:
            store.verify_channel()
        self.assertEqual(
            "PROMOTION_RECEIPT_IDENTITY_INVALID",
            wrong_name.exception.code,
        )

    def test_missing_release_unknown_schema_and_wrong_chain_fail_closed(self) -> None:
        record = self.promote()
        store = OpeningRuntimeReleaseStore(self.release_root)
        release_path = store.release_path(record["releaseId"])
        original_release = release_path.read_bytes()
        release_path.unlink()
        with self.assertRaises(OpeningRuntimeIdentityError) as missing:
            store.verify_channel()
        self.assertEqual("RELEASE_RECORD_MISSING", missing.exception.code)
        release_path.write_bytes(original_release)

        pointer_path = store.pointer_path(DEFAULT_CHANNEL)
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["schemaVersion"] = "UnknownV99"
        pointer["pointerFingerprint"] = payload_fingerprint(
            pointer,
            "pointerFingerprint",
        )
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
        with self.assertRaises(OpeningRuntimeIdentityError) as schema:
            store.verify_channel()
        self.assertEqual("RELEASE_POINTER_SCHEMA_UNSUPPORTED", schema.exception.code)

    def test_conflicting_release_id_is_never_overwritten(self) -> None:
        record = self.release()
        store = OpeningRuntimeReleaseStore(self.release_root)
        store.promote(record, current_git_sha=HEAD_A)
        conflicting = dict(record)
        conflicting["qualificationEvidence"] = ["fixture://different-proof"]
        conflicting["releaseFingerprint"] = payload_fingerprint(
            conflicting,
            "releaseFingerprint",
        )

        with self.assertRaises(OpeningRuntimeIdentityError) as raised:
            store.promote(conflicting, current_git_sha=HEAD_A)

        self.assertEqual("RELEASE_WRITE_CONFLICT", raised.exception.code)

    def test_repeated_exact_runtime_promotion_is_idempotent(self) -> None:
        first = self.release()
        store = OpeningRuntimeReleaseStore(self.release_root)
        release, pointer, changed = store.promote(first, current_git_sha=HEAD_A)
        repeated = self.release()
        repeated["createdAt"] = "2026-08-22T00:00:00+00:00"
        repeated["releaseFingerprint"] = payload_fingerprint(
            repeated,
            "releaseFingerprint",
        )

        second_release, second_pointer, second_changed = store.promote(
            repeated,
            current_git_sha=HEAD_A,
        )

        self.assertTrue(changed)
        self.assertFalse(second_changed)
        self.assertEqual(release, second_release)
        self.assertEqual(pointer, second_pointer)
        self.assertEqual(1, len(store._promotion_files()))

    def test_promotion_chain_supports_forward_rollback_to_prior_release(self) -> None:
        store = OpeningRuntimeReleaseStore(self.release_root)
        release_a = self.release()
        store.promote(release_a, current_git_sha=HEAD_A)
        provider = self.repository / "momentum_hunter" / "providers.py"
        original = provider.read_bytes()
        provider.write_bytes(original + b"\n# release B\n")
        release_b = build_release_record(
            self.context,
            source_git_sha=HEAD_B,
            qualification_evidence=["fixture://hard-chew-pass-b"],
            predecessor_release_id=release_a["releaseId"],
            environment=self.environment,
        )
        store.promote(release_b, current_git_sha=HEAD_B)
        provider.write_bytes(original)
        rollback_candidate = self.release(predecessor=release_b["releaseId"])

        active, _, changed = store.promote(
            rollback_candidate,
            current_git_sha=HEAD_A,
        )

        self.assertTrue(changed)
        self.assertEqual(release_a["releaseId"], active["releaseId"])
        self.assertEqual(3, len(store._promotion_files()))
        self.assertEqual(
            release_a["releaseId"],
            store.verify_channel()[0]["releaseId"],
        )

    def test_reparse_runtime_component_is_rejected_when_supported(self) -> None:
        target = self.repository / "momentum_hunter" / "providers.py"
        outside = self.root / "outside.py"
        outside.write_text("OUTSIDE = 1\n", encoding="utf-8")
        target.unlink()
        try:
            os.symlink(outside, target)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable: {exc}")

        with self.assertRaises(OpeningRuntimeIdentityError) as raised:
            build_runtime_surface(self.repository)

        self.assertEqual("RUNTIME_REPARSE_POINT", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
