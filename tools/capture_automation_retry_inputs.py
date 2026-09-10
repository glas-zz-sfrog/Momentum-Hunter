"""Freeze current, read-only retry inputs. This is not adoption or startup."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import automation_retry_readonly as observer


def main():
    p = argparse.ArgumentParser()
    for key in ("canonical", "automation-root", "expectations", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--canonical-head", required=True)
    p.add_argument("--expectations-sha256", required=True)
    args = p.parse_args()
    c, a, out = args.canonical.resolve(), args.automation_root.resolve(), args.output.resolve()
    observer.require(not out.exists() and not out.is_relative_to(c) and not out.is_relative_to(a), "NEW_EXTERNAL_OUTPUT_REQUIRED")
    observer.require(observer.digest(args.expectations) == args.expectations_sha256.lower(), "ACCEPTED_EXPECTATIONS_DRIFT")
    expected = observer.load(args.expectations)
    manifest_path = a / "automation-manifest.json"
    manifest = observer.parse_manifest(manifest_path)
    state_path = a / "state/automation-service-state.json"
    state = observer.load(state_path)
    observer.require(Path(manifest.repository_root).resolve() == c, "INSTALLED_SOURCE_ROOT_MISMATCH")
    cfg = {"schemaVersion": 1, "canonicalRoot": str(c), "canonicalHead": args.canonical_head,
           "manifestPath": str(manifest_path), "statePath": str(state_path),
           "continuousPath": str(a / "continuous-deployment.json"),
           "sessionDate": expected["targetSession"]["sessionDate"],
           "expectationsPath": str(args.expectations.resolve()), "expectationsSha256": args.expectations_sha256.lower(),
           "epoch": state["prospective_epoch"], "evidenceRoot": str(out), "staticFiles": {}, "dynamicStateFiles": {}, "staticDirectories": {},
           "services": observer.services(), "scheduledTasks": observer.tasks()}
    observer.canonical(cfg)
    initial_services, initial_tasks = cfg["services"], cfg["scheduledTasks"]
    def add(path, dynamic=False):
        path = Path(path).resolve()
        cfg["dynamicStateFiles" if dynamic else "staticFiles"][str(path)] = observer.digest(path)
    for path in (manifest_path, state_path, a / "continuous-deployment.json", args.expectations,
                 manifest.python_executable, sys._base_executable, manifest.powershell_executable):
        add(path, Path(path).resolve().is_relative_to(state_path.parent))
    for root, dynamic in ((a / "opening-runtime", False), (a / "service", False), (a / "state", True)):
        if not dynamic:
            cfg["staticDirectories"][str(root)] = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
        for path in root.rglob("*"):
            if path.is_file():
                add(path, dynamic)
    for path, sha in expected["continuous"]["files"].items():
        observer.require(observer.digest(path) == sha.lower(), "CONTINUOUS_BASELINE_DRIFT:" + path)
        add(path)
    add(expected["observer"]["path"])
    for relative in observer.git(c, "ls-files", "momentum_hunter/*.py", "tools/check_automation_preopen.py",
                                 "src/MomentumHunter.AutomationService").splitlines():
        add(c / relative)
    release_root = Path(manifest.opening_runtime_release_root)
    from momentum_hunter.opening_runtime_identity import OpeningRuntimeReleaseStore
    class ReadOnlyReleaseStore(OpeningRuntimeReleaseStore):
        def initialize(self):
            observer.require(self.root.is_dir(), "RELEASE_ROOT_MISSING")
        @staticmethod
        def _write_once(*args):
            raise RuntimeError("READ_ONLY")
        @staticmethod
        def _atomic_write(*args):
            raise RuntimeError("READ_ONLY")
    release, _, _ = ReadOnlyReleaseStore(release_root).verify_channel("opening-capture")
    components = {item["path"]: item["sha256"] for item in release["runtimeComponents"]}
    cfg["expectedLoadedBytes"] = {
        "loaded_supervisor_sha256": components["momentum_hunter/automation_supervisor.py"],
        "loaded_runtime_identity_module_sha256": components["momentum_hunter/opening_runtime_identity.py"],
        "loaded_service_host_sha256": release["environmentIdentity"]["serviceHost"]["sha256"],
    }
    cfg["selection"] = {"pythonExecutable": str(manifest.python_executable), "basePython": sys._base_executable,
        "serviceHost": str(manifest.service_host_executable), "workingDirectory": str(c),
        "arguments": ["-B", "-m", "momentum_hunter.automation_supervisor", "run", "--manifest", str(manifest_path)],
        "openingReleaseId": release["releaseId"], "openingFingerprint": release["approvedRuntimeFingerprint"],
        "environmentPolicy": {"PYTHONUTF8": "1", "MOMENTUM_HUNTER_SERVICE_MODE": "1",
            "MOMENTUM_HUNTER_LOADED_SERVICE_HOST_SHA256": "HASH_OF_RUNNING_HOST", "removedKeys": ["OPENAI_API_KEY", "CODEX_API_KEY"]},
        "serviceDefinition": cfg["services"]["MomentumHunterAutomation"], "serviceSession": 0,
        "prechildMechanism": "REVIEWED_HOST_JOB_LIST_CREATE_SUSPENDED_VERIFY_THEN_RESUME",
        "installedHasPrechildContract": "--launch-contract" in cfg["services"]["MomentumHunterAutomation"]["PathName"],
        "candidateAdoptionRequiredBeforeExecute": True}
    result = observer.check(cfg, "preflight")
    observer.require(observer.services() == initial_services and observer.tasks() == initial_tasks, "PROTECTED_STATE_CHANGED_DURING_CAPTURE")
    observer.verify_input_files(cfg)
    for path, sha in cfg["dynamicStateFiles"].items():
        observer.require(observer.digest(path) == sha, "STATE_CHANGED_DURING_CAPTURE")
    out.mkdir(parents=True, exist_ok=False)
    for name, value in (("CURRENT-INPUT-MANIFEST.json", cfg), ("CURRENT-INPUT-READONLY-PROOF.json", result),
        ("CURRENT-INPUT-DRESS.json", {"status": "PASS", "capturedAt": datetime.now(timezone.utc).isoformat(),
            "selection": cfg["selection"], "scope": "EXACT_CURRENT_SELECTION_NONMUTATING_NOT_A_PRODUCTION_LAUNCH",
            "staticFileCount": len(cfg["staticFiles"]), "stateFileCount": len(cfg["dynamicStateFiles"]),
            "productionAutomationStarted": False, "productionMutation": False,
            "newHostRequiresReviewedAdoptionAndOpeningEnvironmentRebinding": True})):
        with (out / name).open("x", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
    print(json.dumps({"status": "PASS", "output": str(out), "count": len(cfg["staticFiles"]) + len(cfg["dynamicStateFiles"])}))


if __name__ == "__main__":
    main()
