from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.opening_runtime_identity import (
    RuntimeIdentityContext,
    build_runtime_surface,
    file_sha256,
    probe_runtime_environment,
)
from tools.audit_opening_runtime_boundary import (
    BoundaryAuditError,
    analyze_opening_boundary,
    dependency_closure_fingerprint,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_ONLY_MODULE = "momentum_hunter/event_shock_specialist.py"
WPF_ONLY_SOURCE = "src/MomentumHunter.Desktop.Wpf/MainWindow.xaml.cs"
OPENING_DEPENDENCIES = (
    "momentum_hunter/automation_supervisor.py",
    "tools/run_capture_job.ps1",
    "tools/capture_job.py",
    "momentum_hunter/providers.py",
    "momentum_hunter/provider_semantic_plausibility.py",
    "momentum_hunter/models.py",
    "momentum_hunter/scoring.py",
    "momentum_hunter/trade_planning.py",
    "momentum_hunter/storage.py",
    "momentum_hunter/scheduling.py",
    "momentum_hunter/score_breakdowns.py",
    "momentum_hunter/opening_candle_readiness.py",
)


class OpeningRuntimeBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo"
        shutil.copytree(REPOSITORY_ROOT / "momentum_hunter", self.root / "momentum_hunter")
        (self.root / "tools").mkdir(parents=True)
        for relative in ("tools/capture_job.py", "tools/run_capture_job.ps1"):
            source = REPOSITORY_ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        shutil.copy2(REPOSITORY_ROOT / "requirements.txt", self.root / "requirements.txt")
        for relative in (
            WPF_ONLY_SOURCE,
            "docs/argus-office/ROADMAP.md",
            "docs/argus-office/TASK_LOG.md",
        ):
            source = REPOSITORY_ROOT / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def current_fingerprint(self) -> str:
        return str(build_runtime_surface(self.root)["runtimeSurfaceFingerprint"])

    def closure_fingerprint(self) -> str:
        return dependency_closure_fingerprint(self.root)

    def fingerprint_paths(self, paths: tuple[str, ...]) -> str:
        digest = hashlib.sha256()
        for relative in paths:
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update((self.root / relative).read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def mutate(path: Path, marker: str = "# boundary mutation\n") -> None:
        path.write_bytes(path.read_bytes() + marker.encode("utf-8"))

    def test_actual_opening_closure_is_contained_and_static(self) -> None:
        inventory = analyze_opening_boundary(REPOSITORY_ROOT)

        self.assertEqual(
            inventory.package_python_count,
            inventory.reachable_package_count + inventory.excluded_package_count,
        )
        self.assertGreater(inventory.reachable_package_count, 0)
        self.assertFalse(inventory.outside_surface_imports)
        self.assertFalse(inventory.dynamic_import_sites)
        self.assertIn(RESEARCH_ONLY_MODULE, inventory.excluded_package_files)
        for relative in OPENING_DEPENDENCIES:
            if relative.startswith("momentum_hunter/"):
                self.assertIn(relative, inventory.reachable_package_files)

    def test_current_boundary_is_overbroad_for_research_but_not_wpf_or_docs(self) -> None:
        baseline = self.current_fingerprint()

        self.mutate(self.root / RESEARCH_ONLY_MODULE)
        self.assertNotEqual(baseline, self.current_fingerprint())

        research_changed = self.current_fingerprint()
        self.mutate(self.root / WPF_ONLY_SOURCE, "// presentation only\n")
        self.mutate(self.root / "docs/argus-office/ROADMAP.md")
        self.mutate(self.root / "docs/argus-office/TASK_LOG.md")
        self.assertEqual(research_changed, self.current_fingerprint())

    def test_prototype_closure_decouples_unrelated_work_and_binds_opening_parser(self) -> None:
        baseline = self.closure_fingerprint()

        self.mutate(self.root / RESEARCH_ONLY_MODULE)
        self.mutate(self.root / WPF_ONLY_SOURCE, "// presentation only\n")
        self.mutate(self.root / "docs/argus-office/ROADMAP.md")
        self.assertEqual(baseline, self.closure_fingerprint())

        self.mutate(self.root / "momentum_hunter/providers.py")
        self.assertNotEqual(baseline, self.closure_fingerprint())

    def test_every_required_opening_dependency_changes_both_identities(self) -> None:
        inventory = analyze_opening_boundary(self.root)
        dependency_files = set(inventory.dependency_closure_files)
        closure_paths = inventory.dependency_closure_files
        for relative in OPENING_DEPENDENCIES:
            with self.subTest(relative=relative):
                self.assertIn(relative, dependency_files)
                path = self.root / relative
                original = path.read_bytes()
                current_before = self.current_fingerprint()
                closure_before = self.fingerprint_paths(closure_paths)
                self.mutate(path)
                self.assertNotEqual(current_before, self.current_fingerprint())
                self.assertNotEqual(
                    closure_before,
                    self.fingerprint_paths(closure_paths),
                )
                path.write_bytes(original)

    def test_runtime_add_delete_rename_and_modify_change_current_identity(self) -> None:
        baseline = self.current_fingerprint()
        added = self.root / "momentum_hunter/new_opening_dependency.py"
        added.write_text("VALUE = 1\n", encoding="utf-8")
        after_add = self.current_fingerprint()
        self.assertNotEqual(baseline, after_add)

        self.mutate(added)
        after_modify = self.current_fingerprint()
        self.assertNotEqual(after_add, after_modify)

        renamed = added.with_name("renamed_opening_dependency.py")
        added.rename(renamed)
        after_rename = self.current_fingerprint()
        self.assertNotEqual(after_modify, after_rename)

        renamed.unlink()
        self.assertNotEqual(after_rename, self.current_fingerprint())
        self.assertEqual(baseline, self.current_fingerprint())

    def test_static_policy_detects_import_escape_before_future_promotion(self) -> None:
        support = self.root / "support"
        support.mkdir()
        (support / "__init__.py").write_text("", encoding="utf-8")
        escaped = support / "external_opening_dependency.py"
        escaped.write_text("VALUE = 1\n", encoding="utf-8")
        capture = self.root / "tools/capture_job.py"
        self.mutate(capture, "\nfrom support import external_opening_dependency\n")

        inventory = analyze_opening_boundary(self.root)
        self.assertIn(
            "support/external_opening_dependency.py",
            {item.resolved_path for item in inventory.outside_surface_imports},
        )
        with self.assertRaisesRegex(BoundaryAuditError, "outside"):
            self.closure_fingerprint()

        current_after_import = self.current_fingerprint()
        self.mutate(escaped)
        self.assertEqual(current_after_import, self.current_fingerprint())

    def test_dynamic_import_requires_explicit_future_classification(self) -> None:
        capture = self.root / "tools/capture_job.py"
        self.mutate(
            capture,
            '\nimport importlib\nimportlib.import_module("momentum_hunter.providers")\n',
        )

        inventory = analyze_opening_boundary(self.root)
        self.assertEqual(1, len(inventory.dynamic_import_sites))
        self.assertEqual(
            "importlib.import_module",
            inventory.dynamic_import_sites[0].operation,
        )
        with self.assertRaisesRegex(BoundaryAuditError, "dynamic"):
            self.closure_fingerprint()

    def test_realistic_development_sequence_requires_only_true_runtime_promotion(self) -> None:
        current_baseline = self.current_fingerprint()
        closure_baseline = self.closure_fingerprint()

        self.mutate(self.root / "docs/argus-office/ROADMAP.md")
        self.mutate(self.root / RESEARCH_ONLY_MODULE)
        self.mutate(self.root / WPF_ONLY_SOURCE, "// presentation only\n")

        self.assertNotEqual(current_baseline, self.current_fingerprint())
        self.assertEqual(closure_baseline, self.closure_fingerprint())

        self.mutate(self.root / "momentum_hunter/providers.py")
        self.assertNotEqual(closure_baseline, self.closure_fingerprint())

    def test_environment_inventory_binds_unused_and_required_distributions(self) -> None:
        python = self.root / "python.exe"
        powershell = self.root / "powershell.exe"
        service = self.root / "service.exe"
        for path in (python, powershell, service):
            path.write_text(path.name, encoding="utf-8")
        state = self.root / "state"
        engine = self.root / "engine"
        state.mkdir()
        engine.mkdir()
        config = self.root / "MomentumHunterData/config.json"
        config.parent.mkdir()
        config.write_text("{}", encoding="utf-8")
        context = RuntimeIdentityContext(
            repository_root=self.root,
            python_executable=python,
            powershell_executable=powershell,
            state_directory=state,
            engine_host_state_directory=engine,
            poll_interval_seconds=1,
            service_host_executable=service,
            release_root=self.root / "releases",
        )

        def probe(packages: dict[str, str]):
            def runner(arguments: tuple[str, ...]) -> str:
                if arguments[0] == "tzutil.exe":
                    return "Central Standard Time"
                if arguments[0] == str(python) and arguments[1] == "--version":
                    return "Python 3.12.0"
                if arguments[0] == str(powershell):
                    return "7.5.0"
                return json.dumps(packages, sort_keys=True)

            return probe_runtime_environment(context, command_runner=runner)

        baseline = probe({"requests": "2.32.3"})
        unused_added = probe({"requests": "2.32.3", "unused-analysis": "1.0"})
        required_changed = probe({"requests": "2.33.0"})

        self.assertNotEqual(
            baseline["environmentFingerprint"],
            unused_added["environmentFingerprint"],
        )
        self.assertNotEqual(
            baseline["environmentFingerprint"],
            required_changed["environmentFingerprint"],
        )
        self.assertEqual(file_sha256(python), baseline["python"]["sha256"])
        self.assertEqual("Python 3.12.0", baseline["python"]["version"])


if __name__ == "__main__":
    unittest.main()
