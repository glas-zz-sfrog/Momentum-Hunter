"""Create an external, non-executing native retry proposal from frozen current inputs.

The emitted plan is deliberately NOT an accepted handoff. Integration must bind
its accepted review/package and actual authorized guardian registrations before
the separately gated executor can admit it. No SCM/provider mutation occurs.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import automation_retry_readonly as ro


def quote(value):
    # Match WindowsContainedProcess.Quote, including empty arguments and final backslashes.
    result, slashes = ['"'], 0
    for char in value:
        if char == "\\":
            slashes += 1
            continue
        result.append("\\" * (slashes * 2 + 1 if char == '"' else slashes))
        result.append(char)
        slashes = 0
    return "".join(result) + "\\" * (slashes * 2) + '"'


def prepare(config_path, host_root, source, output, cutoff):
    config = ro.load(config_path)
    selection = config["selection"]
    host_root, source, output = host_root.resolve(), source.resolve(), output.resolve()
    ro.require(not output.exists(), "PROPOSAL_ALREADY_EXISTS")
    ro.require(output.parent == Path(config["evidenceRoot"]), "PROPOSAL_OUTSIDE_EVIDENCE_ROOT")
    ro.verify_input_files(config)
    host = host_root / "MomentumHunter.AutomationService.exe"
    assembly = host_root / "MomentumHunter.AutomationService.dll"
    closure = {str(path): ro.digest(path) for path in sorted(host_root.rglob("*"))
               if path.is_file() and path.suffix.lower() in {".dll", ".exe", ".json"}}
    ro.require(str(host) in closure and str(assembly) in closure, "BUILT_HOST_CLOSURE_REQUIRED")
    tools = [source / "tools" / name for name in ("invoke_prechild_automation_retry.ps1", "automation_retry_workflow.psm1",
             "automation_retry_readonly.py", "capture_automation_retry_inputs.py", "prepare_prechild_retry_plan.py",
             "validate_prechild_retry_plan.py", "check_automation_preopen.py")]
    tools += sorted((source / "momentum_hunter").glob("*.py"))
    contracts = [str(output.parent / ("phase-" + str(i) + "-launch.json")) for i in (1, 2)]
    old = selection["serviceDefinition"]["PathName"]
    # This namespace is PROPOSED. The current service path/source are never overwritten.
    definitions = [" ".join(map(quote, [selection["serviceHost"], "--repository-root", config["canonicalRoot"],
        "--python-executable", selection["pythonExecutable"], "--manifest", config["manifestPath"],
        "--launch-contract", contract])) for contract in contracts]
    conhost = str(Path(__import__('os').environ["SystemRoot"]) / "System32/conhost.exe")
    base = selection["basePython"]
    rules = [dict(role="BASE_PYTHON", executable=base, sha256=ro.digest(base),
                  commandLine=" ".join(map(quote, [base, *selection["arguments"]])), parentRole="PYTHON_TARGET", minimum=1, maximum=1),
             dict(role="CONSOLE_HOST", executable=conhost, sha256=ro.digest(conhost),
                  commandLine="\\??\\C:\\WINDOWS\\system32\\conhost.exe 0x4", parentRole="PYTHON_TARGET", minimum=1, maximum=1)]
    value = {"schemaVersion": 1, "task": "ARGUS-AUTOMATION-PRECHILD-CONTAINMENT-LAUNCHER-REPAIR-001",
        "evidenceRoot": config["evidenceRoot"], "canonicalRoot": config["canonicalRoot"],
        "cutoffAt": cutoff, "targetScheduledAt": ro.load(config["expectationsPath"])["targetSession"]["scheduledAt"],
        "startupSeconds": 120, "stabilitySeconds": 180, "sampleGapSeconds": 15, "scheduleAckSeconds": 600,
        "cleanupSeconds": 60, "maximumSeconds": 1800, "sessionDate": config["sessionDate"],
        "nativeAssembly": str(assembly), "nativeClosure": closure, "controllerNativeClosure": closure,
        "toolSourceRoot": str(source), "toolClosure": {str(path): ro.digest(path) for path in tools},
        "readonlyAdapter": str(source / "tools/automation_retry_readonly.py"), "observerPython": selection["basePython"],
        "pythonExecutable": selection["pythonExecutable"], "basePythonExecutable": selection["basePython"],
        "pythonArguments": selection["arguments"], "hostExecutable": selection["serviceHost"],
        "serviceUser": selection["serviceDefinition"]["StartName"], "serviceSid": "UNRESOLVED_INTEGRATION_BOUND_SERVICE_SID",
        "installedServiceDefinition": old, "topologyRules": rules,
        "phases": [dict(readonlyConfig=str(config_path.resolve()), readonlyConfigSha256=ro.digest(config_path),
                        launchContract=contract, serviceDefinition=definition) for contract, definition in zip(contracts, definitions)],
        "launchStaticFiles": {}, "requiredGuardianSlots": [], "scheduleAckPath": str(output.parent / "READONLY-GUARDIAN-SCHEDULE-ACK.json"),
        "acceptedCandidateCommit": None, "acceptedCandidateTree": None,
        "acceptedPackageSha256": None, "acceptedPackagePath": None, "astraDisposition": "NOT_YET_ACCEPTED",
        "status": "DRESS_ONLY_PROPOSAL_NOT_PRODUCTION_ADOPTION"}
    with output.open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, sort_keys=True)
    return value


def main():
    p = argparse.ArgumentParser()
    for name in ("config", "host-root", "source", "output"):
        p.add_argument("--" + name, required=True, type=Path)
    p.add_argument("--cutoff-at", required=True)
    args = p.parse_args()
    prepare(args.config, args.host_root, args.source, args.output, args.cutoff_at)
    print(json.dumps({"status": "PROPOSAL_ONLY", "output": str(args.output), "sha256": ro.digest(args.output)}))


if __name__ == "__main__":
    main()
