from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.opening_runtime_boundary import (
    analyze_opening_boundary,
)
from momentum_hunter.opening_runtime_identity import (
    OpeningRuntimeIdentityError,
    OpeningRuntimeReleaseStore,
    RuntimeIdentityContext,
    build_release_record,
    build_release_record_v2,
    build_runtime_identity_v2,
    canonical_json_bytes,
    file_sha256,
    payload_fingerprint,
    probe_runtime_environment_v2,
    verify_execution_gate,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HEAD = "1" * 40
RESEARCH_ONLY_MODULE = "momentum_hunter/event_shock_specialist.py"
WPF_ONLY_SOURCE = "src/MomentumHunter.Desktop.Wpf/MainWindow.xaml.cs"


class OpeningRuntimeIdentityV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo"
        shutil.copytree(REPOSITORY_ROOT / "momentum_hunter", self.root / "momentum_hunter")
        for relative in (
            "tools/capture_job.py",
            "tools/run_capture_job.ps1",
            "requirements.txt",
            WPF_ONLY_SOURCE,
            "docs/argus-office/ROADMAP.md",
        ):
            source = REPOSITORY_ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.python = self.root / "python.exe"
        self.powershell = self.root / "powershell.exe"
        self.service = self.root / "service.exe"
        for path in (self.python, self.powershell, self.service):
            path.write_text(path.name, encoding="utf-8")
        self.state = self.root / "state"
        self.engine = self.root / "engine"
        self.state.mkdir()
        self.engine.mkdir()
        config = self.root / "MomentumHunterData/config.json"
        config.parent.mkdir()
        config.write_text("{}", encoding="utf-8")
        self.release_root = self.root / "release-store"
        self.context = RuntimeIdentityContext(
            repository_root=self.root,
            python_executable=self.python,
            powershell_executable=self.powershell,
            state_directory=self.state,
            engine_host_state_directory=self.engine,
            poll_interval_seconds=1,
            service_host_executable=self.service,
            release_root=self.release_root,
        )
        self.environment = self.environment_identity()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def mutate(path: Path, marker: str = "# identity v2 mutation\n") -> None:
        path.write_bytes(path.read_bytes() + marker.encode("utf-8"))

    def environment_identity(self, dependency_marker: str = "a") -> dict[str, object]:
        records = [
            ("beautifulsoup4", "import-root:bs4"),
            ("requests", "import-root:requests"),
            ("websocket-client", "import-root:websocket"),
            ("lxml", "explicit-runtime-contract:lxml"),
            ("tzdata", "explicit-runtime-contract:tzdata"),
        ]
        payload: dict[str, object] = {
            "schemaVersion": "OpeningRuntimeEnvironmentV2",
            "python": {"path": str(self.python), "sha256": file_sha256(self.python)},
            "powershell": {
                "path": str(self.powershell),
                "sha256": file_sha256(self.powershell),
            },
            "serviceHost": {"path": str(self.service), "sha256": file_sha256(self.service)},
            "requirementsSha256": file_sha256(self.root / "requirements.txt"),
            "declaredRequirements": [],
            "importRoots": ["bs4", "requests", "websocket"],
            "explicitDistributionContracts": ["lxml", "tzdata"],
            "relevantDistributions": sorted([
                {
                    "name": name,
                    "displayName": name,
                    "version": "1.0",
                    "fileCount": 1,
                    "fileFingerprint": dependency_marker * 64,
                    "selectionReasons": [reason],
                    "requiredBy": [],
                }
                for name, reason in records
            ], key=lambda item: str(item["name"])),
            "platform": {"system": "Windows", "timezone": "Central Standard Time"},
        }
        payload["environmentFingerprint"] = payload_fingerprint(
            payload,
            "environmentFingerprint",
        )
        return payload

    def probe_environment(
        self,
        *,
        dependency_marker: str,
        unused_version: str,
    ) -> dict[str, object]:
        relevant = self.environment_identity(dependency_marker)[
            "relevantDistributions"
        ]

        def runner(arguments: tuple[str, ...]) -> str:
            if arguments[0] == "tzutil.exe":
                return "Central Standard Time"
            if arguments[0] == str(self.python) and arguments[1] == "--version":
                return "Python 3.12.6"
            if arguments[0] == str(self.powershell):
                return "5.1.0"
            return json.dumps(
                {
                    "relevantDistributions": relevant,
                    "unusedInstalledDistributions": {
                        "unused-analysis": unused_version,
                    },
                },
                sort_keys=True,
            )

        return probe_runtime_environment_v2(self.context, command_runner=runner)

    def identity(self, environment: dict[str, object] | None = None) -> dict[str, object]:
        return build_runtime_identity_v2(
            self.context,
            environment=environment or self.environment,
        )

    def release(self) -> dict[str, object]:
        return build_release_record_v2(
            self.context,
            source_git_sha=HEAD,
            qualification_evidence=["test://identity-v2"],
            environment=self.environment,
        )

    def legacy_v2_release(self) -> dict[str, object]:
        record = copy.deepcopy(self.release())
        closure = record["dependencyClosureEvidence"]
        surface = record["runtimeSurfaceIdentity"]
        surface_closure = surface["dependencyClosureEvidence"]
        for item in (closure, surface_closure):
            item.pop("identityInputVersion", None)
            item.pop("nonAuthoritativeFields", None)
            item["dependencyClosureFingerprint"] = payload_fingerprint(
                item,
                "dependencyClosureFingerprint",
            )
        surface["runtimeSurfaceFingerprint"] = payload_fingerprint(
            surface,
            "runtimeSurfaceFingerprint",
        )
        record["runtimeSurfaceFingerprint"] = surface[
            "runtimeSurfaceFingerprint"
        ]
        aggregate = {
            "runtimeSurfaceFingerprint": record["runtimeSurfaceFingerprint"],
            "configurationFingerprint": record["configurationFingerprint"],
            "environmentFingerprint": record["environmentFingerprint"],
            "promotionPolicyVersion": record["promotionPolicyVersion"],
        }
        approved = hashlib.sha256(canonical_json_bytes(aggregate)).hexdigest()
        record["approvedRuntimeFingerprint"] = approved
        record["releaseId"] = f"OPENING-RUNTIME-{approved[:20].upper()}"
        record["releaseFingerprint"] = payload_fingerprint(
            record,
            "releaseFingerprint",
        )
        return record

    @staticmethod
    def loaded_hashes(record: dict[str, object]) -> tuple[str, str, str]:
        components = {
            str(item["path"]): str(item["sha256"])
            for item in record["runtimeComponents"]
        }
        return (
            components["momentum_hunter/automation_supervisor.py"],
            components["momentum_hunter/opening_runtime_identity.py"],
            str(record["environmentIdentity"]["serviceHost"]["sha256"]),
        )

    def test_included_module_explicit_file_and_relevant_dependency_change_identity(self) -> None:
        baseline = self.identity()["approvedRuntimeFingerprint"]
        self.mutate(self.root / "momentum_hunter/providers.py")
        self.assertNotEqual(baseline, self.identity()["approvedRuntimeFingerprint"])

        shutil.copy2(
            REPOSITORY_ROOT / "momentum_hunter/providers.py",
            self.root / "momentum_hunter/providers.py",
        )
        self.mutate(self.root / "tools/run_capture_job.ps1", "# launcher mutation\n")
        self.assertNotEqual(baseline, self.identity()["approvedRuntimeFingerprint"])
        shutil.copy2(
            REPOSITORY_ROOT / "tools/run_capture_job.ps1",
            self.root / "tools/run_capture_job.ps1",
        )

        changed_environment = self.environment_identity("b")
        self.assertNotEqual(
            baseline,
            self.identity(changed_environment)["approvedRuntimeFingerprint"],
        )

        (self.root / "MomentumHunterData/config.json").write_text(
            '{"provider":"finviz"}',
            encoding="utf-8",
        )
        self.assertNotEqual(baseline, self.identity()["approvedRuntimeFingerprint"])

    def test_research_wpf_docs_and_unused_distribution_do_not_change_identity(self) -> None:
        baseline = self.identity()["approvedRuntimeFingerprint"]
        self.mutate(self.root / RESEARCH_ONLY_MODULE)
        self.mutate(self.root / WPF_ONLY_SOURCE, "// WPF only\n")
        self.mutate(self.root / "docs/argus-office/ROADMAP.md")
        self.assertEqual(baseline, self.identity()["approvedRuntimeFingerprint"])

        first_probe = self.probe_environment(
            dependency_marker="a",
            unused_version="1.0",
        )
        second_probe = self.probe_environment(
            dependency_marker="a",
            unused_version="99.0",
        )
        self.assertEqual(
            first_probe["environmentFingerprint"],
            second_probe["environmentFingerprint"],
        )
        self.assertEqual(
            baseline,
            self.identity(copy.deepcopy(self.environment))["approvedRuntimeFingerprint"],
        )

    def test_unreachable_package_inventory_add_and_remove_do_not_change_identity(
        self,
    ) -> None:
        baseline = self.identity()
        baseline_closure = baseline["runtimeSurface"]["dependencyClosureEvidence"]
        module = self.root / "momentum_hunter/identity_003a_unreachable.py"
        module.write_text("VALUE = 1\n", encoding="utf-8")

        added = self.identity()
        added_closure = added["runtimeSurface"]["dependencyClosureEvidence"]
        self.assertEqual(
            baseline["approvedRuntimeFingerprint"],
            added["approvedRuntimeFingerprint"],
        )
        self.assertEqual(
            baseline["runtimeSurface"]["runtimeSurfaceFingerprint"],
            added["runtimeSurface"]["runtimeSurfaceFingerprint"],
        )
        self.assertEqual(
            baseline_closure["dependencyClosureFingerprint"],
            added_closure["dependencyClosureFingerprint"],
        )
        self.assertEqual(
            int(baseline_closure["packagePythonCount"]) + 1,
            added_closure["packagePythonCount"],
        )
        self.assertEqual(
            int(baseline_closure["excludedPackageCount"]) + 1,
            added_closure["excludedPackageCount"],
        )
        self.assertEqual(
            baseline_closure["reachablePackageCount"],
            added_closure["reachablePackageCount"],
        )
        self.assertEqual(
            ["excludedPackageCount", "packagePythonCount"],
            baseline_closure["nonAuthoritativeFields"],
        )
        self.assertNotEqual(
            payload_fingerprint(
                baseline_closure,
                "dependencyClosureFingerprint",
            ),
            payload_fingerprint(
                added_closure,
                "dependencyClosureFingerprint",
            ),
        )
        self.assertNotEqual(
            payload_fingerprint(
                baseline["runtimeSurface"],
                "runtimeSurfaceFingerprint",
            ),
            payload_fingerprint(
                added["runtimeSurface"],
                "runtimeSurfaceFingerprint",
            ),
        )

        module.unlink()
        removed = self.identity()
        self.assertEqual(
            baseline["approvedRuntimeFingerprint"],
            removed["approvedRuntimeFingerprint"],
        )

    def test_new_and_changed_reachable_module_change_identity(self) -> None:
        baseline = self.identity()["approvedRuntimeFingerprint"]
        module = self.root / "momentum_hunter/identity_003a_reachable.py"
        module.write_text("VALUE = 1\n", encoding="utf-8")
        self.mutate(
            self.root / "momentum_hunter/providers.py",
            "\nfrom momentum_hunter import identity_003a_reachable\n",
        )
        added = self.identity()["approvedRuntimeFingerprint"]
        self.assertNotEqual(baseline, added)

        self.mutate(module)
        changed = self.identity()["approvedRuntimeFingerprint"]
        self.assertNotEqual(added, changed)

    def test_new_reachable_import_expands_closure(self) -> None:
        before = analyze_opening_boundary(self.root)
        module = self.root / "momentum_hunter/new_opening_dependency.py"
        module.write_text("VALUE = 1\n", encoding="utf-8")
        self.mutate(
            self.root / "momentum_hunter/providers.py",
            "\nfrom momentum_hunter import new_opening_dependency\n",
        )
        after = analyze_opening_boundary(self.root)
        self.assertEqual(
            before.reachable_package_count + 1,
            after.reachable_package_count,
        )
        self.assertIn(
            "momentum_hunter/new_opening_dependency.py",
            after.dependency_closure_files,
        )

    def test_outside_root_import_and_dynamic_loading_fail_promotion_build(self) -> None:
        support = self.root / "support"
        support.mkdir()
        (support / "__init__.py").write_text("", encoding="utf-8")
        (support / "external.py").write_text("VALUE = 1\n", encoding="utf-8")
        capture = self.root / "tools/capture_job.py"
        self.mutate(capture, "\nfrom support import external\n")
        with self.assertRaises(OpeningRuntimeIdentityError) as escaped:
            self.identity()
        self.assertEqual("OPENING_DEPENDENCY_IMPORT_ESCAPE", escaped.exception.code)

        shutil.copy2(REPOSITORY_ROOT / "tools/capture_job.py", capture)
        self.mutate(
            capture,
            '\nimport importlib\nimportlib.import_module("momentum_hunter.providers")\n',
        )
        with self.assertRaises(OpeningRuntimeIdentityError) as dynamic:
            self.identity()
        self.assertEqual("OPENING_DYNAMIC_LOADING_UNCLASSIFIED", dynamic.exception.code)

    def test_v2_promotion_gate_detects_tampering_and_loaded_byte_drift(self) -> None:
        record = self.release()
        store = OpeningRuntimeReleaseStore(self.release_root)
        store.promote(record, current_git_sha=HEAD)
        supervisor, identity_gate, service = self.loaded_hashes(record)
        result = verify_execution_gate(
            self.context,
            loaded_supervisor_sha256=supervisor,
            loaded_identity_module_sha256=identity_gate,
            loaded_service_host_sha256=service,
            environment=self.environment,
            git_identity=(HEAD, ""),
        )
        self.assertTrue(result.runtime_match)

        with self.assertRaises(OpeningRuntimeIdentityError) as loaded:
            verify_execution_gate(
                self.context,
                loaded_supervisor_sha256="0" * 64,
                loaded_identity_module_sha256=identity_gate,
                loaded_service_host_sha256=service,
                environment=self.environment,
                git_identity=(HEAD, ""),
            )
        self.assertEqual("LOADED_SUPERVISOR_MISMATCH", loaded.exception.code)

        self.mutate(self.root / "momentum_hunter/providers.py")
        with self.assertRaises(OpeningRuntimeIdentityError) as tampered:
            verify_execution_gate(
                self.context,
                loaded_supervisor_sha256=supervisor,
                loaded_identity_module_sha256=identity_gate,
                loaded_service_host_sha256=service,
                environment=self.environment,
                git_identity=(HEAD, ""),
            )
        self.assertEqual("APPROVED_RUNTIME_MISMATCH", tampered.exception.code)

    def test_v1_release_remains_verifiable_as_rollback(self) -> None:
        v1_environment = {
            "schemaVersion": "OpeningRuntimeEnvironmentV1",
            "serviceHost": {"sha256": file_sha256(self.service)},
        }
        v1_environment["environmentFingerprint"] = payload_fingerprint(
            v1_environment,
            "environmentFingerprint",
        )
        record = build_release_record(
            self.context,
            source_git_sha=HEAD,
            qualification_evidence=["test://v1-rollback"],
            environment=v1_environment,
        )
        release, _, changed = OpeningRuntimeReleaseStore(self.release_root).promote(
            record,
            current_git_sha=HEAD,
        )
        self.assertTrue(changed)
        self.assertEqual("OpeningRuntimeReleaseV1", release["schemaVersion"])
        supervisor, identity_gate, service = self.loaded_hashes(record)
        result = verify_execution_gate(
            self.context,
            loaded_supervisor_sha256=supervisor,
            loaded_identity_module_sha256=identity_gate,
            loaded_service_host_sha256=service,
            environment=v1_environment,
            git_identity=(HEAD, ""),
        )
        self.assertTrue(result.runtime_match)

    def test_legacy_v2_release_remains_verifiable(self) -> None:
        record = self.legacy_v2_release()
        release, _, changed = OpeningRuntimeReleaseStore(
            self.release_root
        ).promote(record, current_git_sha=HEAD)

        self.assertTrue(changed)
        self.assertEqual(record["releaseId"], release["releaseId"])
        self.assertNotIn(
            "identityInputVersion",
            release["dependencyClosureEvidence"],
        )

    def test_mixed_v1_v2_chain_can_promote_v1_rollback(self) -> None:
        v1_environment: dict[str, object] = {
            "schemaVersion": "OpeningRuntimeEnvironmentV1",
            "serviceHost": {"sha256": file_sha256(self.service)},
        }
        v1_environment["environmentFingerprint"] = payload_fingerprint(
            v1_environment,
            "environmentFingerprint",
        )
        store = OpeningRuntimeReleaseStore(self.release_root)
        v1 = build_release_record(
            self.context,
            source_git_sha=HEAD,
            qualification_evidence=["test://v1"],
            environment=v1_environment,
        )
        store.promote(v1, current_git_sha=HEAD)
        v2 = build_release_record_v2(
            self.context,
            source_git_sha="2" * 40,
            qualification_evidence=["test://v2"],
            predecessor_release_id=str(v1["releaseId"]),
            environment=self.environment,
        )
        store.promote(v2, current_git_sha="2" * 40)
        active, _, changed = store.promote(v1, current_git_sha="3" * 40)

        self.assertTrue(changed)
        self.assertEqual(v1["releaseId"], active["releaseId"])
        self.assertEqual("OpeningRuntimeReleaseV1", active["schemaVersion"])


if __name__ == "__main__":
    unittest.main()
