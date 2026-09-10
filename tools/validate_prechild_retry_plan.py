"""Validate a reviewed adoption before the retry controller may touch SCM.

Plan fields are not authority by themselves: bind Git ancestry/tree, immutable
package bytes, packaged source, installed native closure, and exact phase inputs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import automation_retry_readonly as ro
from prepare_prechild_retry_plan import quote


def validate(plan, package):
    ro.require(plan["status"] == "REVIEWED_ADOPTION_BOUND" and
        plan["astraDisposition"] == "ACCEPT_PRECHILD_CONTAINMENT_AND_RETRY_CONTROLLER", "REVIEWED_ADOPTION_REQUIRED")
    head, tree = plan["acceptedCandidateCommit"], plan["acceptedCandidateTree"]
    ro.require(len(head) == 40 and len(tree) == 40 and all(c in "0123456789abcdef" for c in head + tree), "INVALID_GIT_IDENTITY")
    ro.require(ro.digest(package) == plan["acceptedPackageSha256"], "ACCEPTED_PACKAGE_DRIFT")
    canonical = Path(plan["canonicalRoot"]).resolve()
    ro.require(ro.git(canonical, "rev-parse", head + "^{tree}") == tree, "CANDIDATE_TREE_MISMATCH")
    ro.require(ro.git(canonical, "merge-base", head, "HEAD") == head, "CANDIDATE_NOT_ANCESTOR_OF_ADOPTION")
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        ro.require(len(names) == len(set(names)), "AMBIGUOUS_PACKAGE_MEMBERS")
        metadata = json.loads(archive.read("CANDIDATE.json"))
        ro.require(metadata["head"] == head and metadata["tree"] == tree, "PACKAGE_GIT_IDENTITY_MISMATCH")
        review = json.loads(archive.read("ASTRA-DISPOSITION.json"))
        ro.require(review["head"] == head and review["tree"] == tree and review["unresolvedMaterialFindings"] == 0
            and review["disposition"] == plan["astraDisposition"], "PACKAGE_REVIEW_BINDING_REJECTED")
        for directory, field, prefix in ((Path(plan["hostExecutable"]).parent, "nativeClosure", "binary/"),
                                        (Path(plan["nativeAssembly"]).parent, "controllerNativeClosure", "binary/")):
            actual = {str(p.resolve()) for p in directory.iterdir() if p.is_file() and p.suffix.lower() in {".dll", ".exe", ".json"}}
            ro.require(actual == set(plan[field]), "NATIVE_DIRECTORY_CLOSURE_INCOMPLETE")
            for path, sha in plan[field].items():
                ro.require(ro.digest(path) == sha == hashlib.sha256(archive.read(prefix + Path(path).name)).hexdigest(), "PACKAGED_NATIVE_BYTES_MISMATCH")
        source = Path(plan["toolSourceRoot"]).resolve()
        ro.require(source == canonical, "ADOPTED_TOOLS_MUST_USE_ACCEPTED_CANONICAL")
        required = {str(p.resolve()) for p in (source / "momentum_hunter").glob("*.py")}
        required |= {str(source / "tools" / name) for name in (
            "invoke_prechild_automation_retry.ps1", "automation_retry_workflow.psm1", "automation_retry_readonly.py",
            "validate_prechild_retry_plan.py", "capture_automation_retry_inputs.py", "prepare_prechild_retry_plan.py", "check_automation_preopen.py")}
        ro.require(required == set(plan["toolClosure"]), "OBSERVER_IMPORT_CLOSURE_INCOMPLETE")
        for path, sha in plan["toolClosure"].items():
            relative = Path(path).relative_to(source).as_posix()
            ro.require(ro.digest(path) == sha == hashlib.sha256(archive.read("source/" + relative)).hexdigest(), "PACKAGED_TOOL_SOURCE_MISMATCH")
    ro.require(plan["serviceSid"].startswith("S-1-") and "UNRESOLVED" not in plan["serviceSid"], "SERVICE_SID_UNBOUND")
    phases = plan["phases"]
    ro.require(len(phases) == 2 and phases[0]["launchContract"] != phases[1]["launchContract"], "FRESH_TWO_PHASE_CONTRACT_REQUIRED")
    definitions = [plan["installedServiceDefinition"], *(phase["serviceDefinition"] for phase in phases)]
    ro.require(len(set(definitions)) == 3, "TWO_EXPLICIT_SELECTOR_TRANSITIONS_REQUIRED")
    for phase in phases:
        expected_definition = " ".join(map(quote, [plan["hostExecutable"], "--repository-root", str(canonical),
            "--python-executable", plan["pythonExecutable"], "--manifest", plan["pythonArguments"][-1],
            "--launch-contract", phase["launchContract"]]))
        ro.require(phase["serviceDefinition"] == expected_definition, "ADOPTION_SELECTOR_ARGUMENTS_MISMATCH")
        ro.require(not Path(phase["launchContract"]).exists() and not Path(phase["launchContract"] + ".permanent.json").exists(), "LAUNCH_CONTRACT_ALREADY_USED")
        ro.require(ro.digest(phase["readonlyConfig"]) == phase["readonlyConfigSha256"], "ADOPTION_CONFIG_DRIFT")
        config = ro.load(phase["readonlyConfig"])
        ro.canonical(config)
        ro.verify_input_files(config)
        ro.require(Path(config["canonicalRoot"]).resolve() == canonical, "ADOPTED_CANONICAL_ROOT_MISMATCH")
        ro.require(config.get("authorizedServiceDefinitions") == definitions, "SELECTOR_TRANSITIONS_UNBOUND")
        ro.require(config.get("authorizedGuardianSlots") == plan["requiredGuardianSlots"], "GUARDIAN_SLOT_POLICY_UNBOUND")
        ro.require(config["selection"]["serviceHost"] == plan["hostExecutable"] and
            config["selection"]["pythonExecutable"] == plan["pythonExecutable"] and
            config["selection"]["arguments"] == plan["pythonArguments"], "ADOPTED_RUNTIME_SELECTION_MISMATCH")
        ro.require(config["services"]["MomentumHunterAutomation"]["StartName"] == plan["serviceUser"] and
            config["services"]["MomentumHunterAutomation"]["PathName"] == plan["installedServiceDefinition"], "ADOPTION_SERVICE_BASELINE_MISMATCH")
        ro.require(config["expectedLoadedBytes"]["loaded_service_host_sha256"] == plan["nativeClosure"][plan["hostExecutable"]], "ADOPTED_OPENING_HOST_BINDING_MISMATCH")
        required = set(plan["nativeClosure"]) | {plan["pythonExecutable"], config["manifestPath"]}
        required |= {str(p.resolve()) for p in (canonical / "momentum_hunter").glob("*.py")}
        ro.require(required <= set(plan["launchStaticFiles"]), "PRESTART_STATIC_LAUNCH_CLOSURE_INCOMPLETE")
    for path, sha in plan["launchStaticFiles"].items():
        ro.require(ro.digest(path) == sha, "PRESTART_STATIC_LAUNCH_DRIFT")
    slots = plan["requiredGuardianSlots"]
    ro.require(slots and len({(s["path"], s["name"]) for s in slots}) == len(slots), "GUARDIAN_SLOTS_UNBOUND_OR_DUPLICATED")
    for slot in slots:
        ro.require(slot["readOnly"] is True and slot["occurrences"] == 1 and slot["sessionDate"] == plan["sessionDate"], "GUARDIAN_SLOT_AUTHORITY")
        at = ro.recovery.timestamp(slot["atUtc"])
        ro.require(at > ro.recovery.timestamp(plan["cutoffAt"]) and at < ro.recovery.timestamp(plan["targetScheduledAt"]), "GUARDIAN_SLOT_OUTSIDE_REVIEWED_WINDOW")
    ro.require(not Path(plan["scheduleAckPath"]).exists(), "STALE_GUARDIAN_ACK")
    return {"status": "PASS", "candidate": head, "tree": tree, "sourceAndBinaryPackageBound": True, "mutationPerformed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    ro.require(ro.digest(args.plan) == args.plan_sha256.lower(), "PLAN_DRIFT")
    print(json.dumps(validate(ro.load(args.plan), args.package)))


if __name__ == "__main__":
    main()
