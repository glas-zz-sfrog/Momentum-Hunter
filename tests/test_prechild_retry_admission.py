from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import validate_prechild_retry_plan as admission


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MH-Prechild-Adoption-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "canonical"
        self.installed = self.root / "installed"
        self.controller = self.root / "controller"
        self.native = {"MomentumHunter.AutomationService.exe": b"test-only-exe",
            "MomentumHunter.AutomationService.dll": b"test-only-dll", "MomentumHunter.AutomationService.runtimeconfig.json": b"{}",
            "runtimes/win/lib/net8.0/nested.dll": b"nested-test-only-dll"}
        self.tool_names = ("invoke_prechild_automation_retry.ps1", "automation_retry_workflow.psm1", "automation_retry_readonly.py",
            "validate_prechild_retry_plan.py", "capture_automation_retry_inputs.py", "prepare_prechild_retry_plan.py", "check_automation_preopen.py")
        source_files = {"momentum_hunter/__init__.py": b"", "momentum_hunter/automation_supervisor.py": b"# synthetic fixture"}
        source_files.update({"tools/" + n: b"# non-executable admission fixture" for n in self.tool_names})
        def write(path, content):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return str(path)
        for name, raw in source_files.items():
            write(self.source / name, raw)
        for directory in (self.installed, self.controller):
            for name, raw in self.native.items():
                write(directory / name, raw)
        python = write(self.root / "python.exe", b"non-executable")
        manifest = write(self.root / "manifest.json", b"{}")
        head, tree = "a" * 40, "b" * 40
        self.package = self.root / "fixture.zip"
        with zipfile.ZipFile(self.package, "x") as z:
            for name, raw in self.native.items(): z.writestr("binary/" + name, raw)
            for name, raw in source_files.items(): z.writestr("source/" + name, raw)
            z.writestr("CANDIDATE.json", json.dumps({"head": head, "tree": tree}))
            z.writestr("ASTRA-DISPOSITION.json", json.dumps({"head": head, "tree": tree, "unresolvedMaterialFindings": 0,
                "disposition": "ACCEPT_PRECHILD_CONTAINMENT_AND_RETRY_CONTROLLER", "fixtureOnly": True}))
        sha = admission.ro.digest
        closure = lambda d: {str(p): sha(p) for p in sorted(d.rglob("*")) if p.is_file()}
        host = str(self.installed / "MomentumHunter.AutomationService.exe")
        args = ["-B", "-m", "momentum_hunter.automation_supervisor", "run", "--manifest", manifest]
        phases = []
        for i in range(2):
            launch = str(self.root / ("launch-" + str(i) + ".json"))
            definition = " ".join(map(admission.quote, [host, "--repository-root", str(self.source),
                "--python-executable", python, "--manifest", manifest, "--launch-contract", launch]))
            phases.append({"launchContract": launch, "serviceDefinition": definition})
        slots = [{"name": "fixture-guardian", "path": "\\fixture\\", "atUtc": "2026-09-10T13:00:00Z",
            "readOnly": True, "occurrences": 1, "sessionDate": "2026-09-10", "logonType": "Interactive"}]
        self.plan = {"status": "REVIEWED_ADOPTION_BOUND", "astraDisposition": "ACCEPT_PRECHILD_CONTAINMENT_AND_RETRY_CONTROLLER",
            "acceptedCandidateCommit": head, "acceptedCandidateTree": tree, "acceptedPackageSha256": sha(self.package),
            "canonicalRoot": str(self.source), "hostExecutable": host, "nativeClosure": closure(self.installed),
            "nativeAssembly": str(self.controller / "MomentumHunter.AutomationService.dll"), "controllerNativeClosure": closure(self.controller),
            "toolSourceRoot": str(self.source), "toolClosure": {str(self.source/n): sha(self.source/n) for n in source_files},
            "serviceSid": "S-1-5-21-0", "serviceUser": "fixture-only", "phases": phases,
            "installedServiceDefinition": "original fixture-only selector", "pythonExecutable": python, "pythonArguments": args,
            "launchStaticFiles": {**closure(self.installed), python: sha(python), manifest: sha(manifest),
                **{str(p): sha(p) for p in (self.source/"momentum_hunter").glob("*.py")}},
            "requiredGuardianSlots": slots, "sessionDate": "2026-09-10", "cutoffAt": "2026-09-10T12:55:00Z",
            "targetScheduledAt": "2026-09-10T13:35:00Z", "scheduleAckPath": str(self.root/"ack.json")}
        self.config = {"canonicalRoot": str(self.source), "manifestPath": manifest,
            "staticFiles": {manifest: sha(manifest)}, "dynamicStateFiles": {"fixture-state": "bound"},
            "staticDirectories": {str(self.installed): sorted(str(Path(n)) for n in self.native)},
            "authorizedServiceDefinitions": [self.plan["installedServiceDefinition"], *(p["serviceDefinition"] for p in phases)],
            "authorizedGuardianSlots": slots, "expectedLoadedBytes": {"loaded_service_host_sha256": sha(host)},
            "selection": {"serviceHost": host, "pythonExecutable": python, "arguments": args},
            "services": {"MomentumHunterAutomation": {"StartName": self.plan["serviceUser"], "PathName": self.plan["installedServiceDefinition"]}}}
        self.save_configs()

    def save_configs(self):
        for i, phase in enumerate(self.plan["phases"]):
            path = self.root / ("phase-config-" + str(i) + ".json")
            path.write_text(json.dumps(self.config))
            phase.update(readonlyConfig=str(path), readonlyConfigSha256=admission.ro.digest(path))

    def run_check(self):
        def git(root, *command):
            return self.plan["acceptedCandidateTree"] if command[0] == "rev-parse" else self.plan["acceptedCandidateCommit"]
        with patch.object(admission.ro, "git", side_effect=git), patch.object(admission.ro, "canonical"):
            return admission.validate(self.plan, self.package)

    def test_exact_fixture_adoption_passes_without_scm(self):
        self.assertEqual("PASS", self.run_check()["status"])

    def test_package_identity_cannot_be_replaced_by_format_valid_fields(self):
        self.plan["acceptedCandidateCommit"] = "c" * 40
        with self.assertRaisesRegex(RuntimeError, "PACKAGE_GIT_IDENTITY_MISMATCH"):
            self.run_check()

    def test_dress_proposal_not_executable(self):
        self.plan["status"] = "DRESS_ONLY_PROPOSAL_NOT_PRODUCTION_ADOPTION"
        with self.assertRaisesRegex(RuntimeError, "REVIEWED_ADOPTION_REQUIRED"):
            self.run_check()

    def test_wrong_selector_rejected_before_start(self):
        self.plan["phases"][0]["serviceDefinition"] = "unreviewed executable"
        with self.assertRaisesRegex(RuntimeError, "SELECTOR_ARGUMENTS_MISMATCH"):
            self.run_check()

    def test_native_changed_or_added_rejected(self):
        (self.installed/"extra.dll").write_bytes(b"extra")
        with self.assertRaisesRegex(RuntimeError, "NATIVE_DIRECTORY_CLOSURE_INCOMPLETE"):
            self.run_check()

    def test_nested_runtime_tamper_is_package_bound(self):
        path = self.installed / "runtimes/win/lib/net8.0/nested.dll"
        path.write_bytes(b"changed")
        self.plan["nativeClosure"][str(path)] = admission.ro.digest(path)
        with self.assertRaisesRegex(RuntimeError, "PACKAGED_NATIVE_BYTES_MISMATCH"):
            self.run_check()

    def test_nested_runtime_deleted_and_removed_from_plan_still_fails(self):
        path = self.installed / "runtimes/win/lib/net8.0/nested.dll"
        path.unlink()
        del self.plan["nativeClosure"][str(path)]
        with self.assertRaisesRegex(RuntimeError, "PACKAGED_NATIVE_CLOSURE_INCOMPLETE"):
            self.run_check()

    def test_nested_controller_runtime_missing_fails(self):
        path = self.controller / "runtimes/win/lib/net8.0/nested.dll"
        path.unlink()
        with self.assertRaisesRegex(RuntimeError, "NATIVE_DIRECTORY_CLOSURE_INCOMPLETE"):
            self.run_check()

    def test_adapter_imported_module_is_package_bound(self):
        (self.source/"momentum_hunter/automation_supervisor.py").write_bytes(b"changed imported code")
        with self.assertRaisesRegex(RuntimeError, "PACKAGED_TOOL_SOURCE_MISMATCH"):
            self.run_check()

    def test_static_launch_closure_complete_before_start(self):
        self.plan["launchStaticFiles"].clear()
        with self.assertRaisesRegex(RuntimeError, "PRESTART_STATIC_LAUNCH_CLOSURE_INCOMPLETE"):
            self.run_check()

    def test_already_used_contract_rejected(self):
        Path(self.plan["phases"][0]["launchContract"]).write_text("used")
        with self.assertRaisesRegex(RuntimeError, "LAUNCH_CONTRACT_ALREADY_USED"):
            self.run_check()

    def test_existing_abort_or_commit_decision_cannot_reuse_selector(self):
        Path(self.plan["phases"][0]["launchContract"] + ".decision.json").write_text("used")
        with self.assertRaisesRegex(RuntimeError, "LAUNCH_CONTRACT_ALREADY_USED"):
            self.run_check()

    def test_phase_config_cannot_silently_rebind_opening_loaded_bytes(self):
        self.config["expectedLoadedBytes"]["loaded_service_host_sha256"] = "0" * 64
        self.save_configs()
        with self.assertRaisesRegex(RuntimeError, "OPENING_HOST_BINDING_MISMATCH"):
            self.run_check()

    def test_selector_transition_list_required(self):
        self.config["authorizedServiceDefinitions"].pop()
        self.save_configs()
        with self.assertRaisesRegex(RuntimeError, "SELECTOR_TRANSITIONS_UNBOUND"):
            self.run_check()

    def test_no_guardian_slots_is_not_ready(self):
        self.plan["requiredGuardianSlots"].clear()
        self.save_configs()
        with self.assertRaisesRegex(RuntimeError, "GUARDIAN_SLOTS_UNBOUND"):
            self.run_check()

    def test_stale_ack_rejected(self):
        Path(self.plan["scheduleAckPath"]).write_text("stale")
        with self.assertRaisesRegex(RuntimeError, "STALE_GUARDIAN_ACK"):
            self.run_check()

    def test_recurring_guardian_rejected(self):
        self.plan["requiredGuardianSlots"][0]["occurrences"] = 2
        self.save_configs()
        with self.assertRaisesRegex(RuntimeError, "GUARDIAN_SLOT_AUTHORITY"):
            self.run_check()

    def test_early_guardian_rejected(self):
        self.plan["requiredGuardianSlots"][0]["atUtc"] = "2026-09-10T12:00:00Z"
        self.save_configs()
        with self.assertRaisesRegex(RuntimeError, "GUARDIAN_SLOT_OUTSIDE"):
            self.run_check()


if __name__ == "__main__":
    unittest.main()
