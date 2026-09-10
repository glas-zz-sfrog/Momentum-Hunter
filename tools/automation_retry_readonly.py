"""Read-only current-input and readiness adapter for the native retry controller.

Never starts a service, constructs a provider, repairs state, or grants authority.
Every invocation writes a new external receipt; Windows callers contain this
observer and its OS-query children before executing it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from momentum_hunter import automation_state_recovery as recovery
from momentum_hunter.automation_guardian_liveness import ObservationClock, automation_heartbeat
from momentum_hunter.automation_preopen_guardian import (
    inspect_readiness, service_and_observer_checks, session_contract, verify_opening_readonly,
)
from momentum_hunter.automation_supervisor import parse_manifest, receipt_compatibility_error


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "DUPLICATE_JSON_FIELD")
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def os_read(script):
    result = subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
         "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, check=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return json.loads(result.stdout)


def services():
    rows = os_read("Get-CimInstance Win32_Service -Filter \"Name LIKE 'MomentumHunter%'\" | ForEach-Object { "
        "$b=$null; if ($_.ProcessId -gt 0) { $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$_.ProcessId); "
        "if ($p.CreationDate) {$b=$p.CreationDate.ToUniversalTime().ToString('o')} }; "
        "[pscustomobject]@{Name=$_.Name;State=$_.State;StartMode=$_.StartMode;StartName=$_.StartName;"
        "PathName=$_.PathName;ProcessId=[int]$_.ProcessId;ProcessCreatedAt=$b}} | ConvertTo-Json -Depth 4 -Compress")
    return {row["Name"]: row for row in (rows if isinstance(rows, list) else [rows])}


def tasks():
    rows = os_read("@(Get-ScheduledTask | Where-Object {$_.TaskName -match 'Momentum|Argus'} | "
        "ForEach-Object {$x=Export-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath; "
        "$h=[Security.Cryptography.SHA256]::Create(); try {$v=([BitConverter]::ToString($h.ComputeHash("
        "[Text.Encoding]::UTF8.GetBytes($x)))).Replace('-','').ToLowerInvariant()} finally {$h.Dispose()}; "
        "[pscustomobject]@{name=$_.TaskName;path=$_.TaskPath;definitionSha256=$v}}) | ConvertTo-Json -Compress")
    return sorted(rows if isinstance(rows, list) else [rows], key=lambda r: (r["path"], r["name"]))


def git(root, *command):
    return subprocess.run(["git", "--no-optional-locks", "-C", str(root), *command],
        capture_output=True, text=True, check=True, timeout=15).stdout.strip()


def canonical(config):
    root, head = Path(config["canonicalRoot"]), config["canonicalHead"]
    require(git(root, "rev-parse", "HEAD") == head
            and git(root, "rev-parse", "origin/master") == head
            and git(root, "branch", "--show-current") == "master"
            and not git(root, "status", "--porcelain"), "CANONICAL_IDENTITY_DRIFT")


def state(config):
    path = Path(config["statePath"])
    for _ in range(3):
        began = datetime.now(timezone.utc)
        raw = path.read_bytes()
        store = recovery.DurableStateStorage(path, lambda *a: (_ for _ in ()).throw(RuntimeError("READ_ONLY")))
        value = store.load(now=datetime.now(timezone.utc), custody=False)
        ended = datetime.now(timezone.utc)
        if raw != path.read_bytes() or value != recovery.decode(raw):
            continue
        require(store.report["state"] == "VALID" and store.report["recovery_source"] == "CURRENT"
                and not store.report["invalid_generations"], "CURRENT_STATE_AUTHORITY_INVALID")
        require(value["prospective_epoch"] == config["epoch"], "EPOCH_DRIFT")
        recovery.validate_epoch(value["prospective_epoch"])
        require(value["recovery_floor_at"] == config["epoch"]["boundaryAt"], "REPLAY_FLOOR_DRIFT")
        require(not list(store.claims.glob("*.json")) and not list(store.custody.glob("*.bin")), "UNEXPECTED_CLAIM_OR_CORRUPTION")
        require(all(v["status"] == "PENDING" and not v.get("started_at") and not v.get("completed_at")
                    for v in value["jobs"].values()), "UNEXPECTED_PREOPEN_JOB_ACTIVITY")
        first = config["epoch"]["firstProspectiveSession"].replace("-", "")
        require(all(k.startswith("opening-capture-") and k >= "opening-capture-" + first for k in value["jobs"]),
                "PRE_EPOCH_OR_FOREIGN_JOB")
        return {"state": value, "sha256": hashlib.sha256(raw).hexdigest(),
                "readStartedAt": began.isoformat(), "readCompletedAt": ended.isoformat(), "recovery": store.report}
    raise RuntimeError("CURRENT_STATE_NOT_COHERENT")


def verify_input_files(config):
    require(config["staticFiles"] and config["dynamicStateFiles"], "INPUT_MANIFEST_INCOMPLETE")
    for path, expected in config["staticFiles"].items():
        require(digest(path) == expected, "CURRENT_INPUT_DRIFT:" + path)
    require(config.get("staticDirectories"), "DIRECTORY_MEMBERSHIP_UNBOUND")
    for root, names in config["staticDirectories"].items():
        actual = sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file())
        require(actual == names, "STATIC_DIRECTORY_MEMBERSHIP_DRIFT:" + root)


def runtime_binding(config, ownership, value):
    require(ownership is not None, "NATIVE_OWNERSHIP_REQUIRED")
    binding = dict(ownership["binding"])
    started = value.get("service_started_at")
    if value.get("last_heartbeat_at") and started and recovery.timestamp(started) >= recovery.timestamp(ownership["supervisorCreatedAt"]):
        require(value["service_instance_id"] != ownership["previousServiceInstanceId"], "OLD_SUPERVISOR_INSTANCE")
        if binding.get("serviceInstanceId"):
            require(value["service_instance_id"] == binding["serviceInstanceId"]
                    and started == binding["serviceStartedAt"], "BOUND_SUPERVISOR_INSTANCE_CHANGED")
            require(value["state_version"] >= binding["minimumStateVersion"], "BOUND_STATE_VERSION_REGRESSED")
        for field, expected_hash in config["expectedLoadedBytes"].items():
            require(value[field] == expected_hash, "LOADED_RUNTIME_DRIFT:" + field)
        if not binding.get("serviceInstanceId"):
            binding.update(serviceInstanceId=value["service_instance_id"], serviceStartedAt=started,
                           minimumStateVersion=value["state_version"])
    return binding


def check(config, action, ownership=None):
    canonical(config)
    verify_input_files(config)
    expected = load(config["expectationsPath"])
    require(digest(config["expectationsPath"]) == config["expectationsSha256"], "EXPECTATIONS_DRIFT")
    target, start, _ = session_contract(expected, config["sessionDate"])
    now = datetime.now(timezone.utc)
    require(now < start, "TARGET_SESSION_ALREADY_STARTED")
    manifest = parse_manifest(Path(config["manifestPath"]))
    found = [job for job in manifest.jobs if job.job_id == target["jobId"]]
    require(len(found) == 1 and found[0].enabled and found[0].kind == "opening_capture"
            and found[0].scheduled_at.isoformat() == target["scheduledAt"]
            and found[0].latest_start_at.isoformat() == target["latestStartAt"]
            and found[0].approved_runtime_channel == "opening-capture", "TARGET_JOB_IDENTITY_DRIFT")
    floor = recovery.timestamp(config["epoch"]["boundaryAt"])
    require(not any(job.enabled and (job.kind in {"paper_engineering", "shadow_opening"}
                    or job.kind != "opening_capture" and job.scheduled_at > floor)
                    for job in manifest.jobs), "UNEXPECTED_ENABLED_JOB_KIND")
    observation = state(config)
    receipt = observation["state"]["jobs"].get(target["jobId"])
    require(receipt and not receipt_compatibility_error(found[0], receipt), "TARGET_RECEIPT_INCOMPATIBLE")
    live = services()
    require(set(live) == set(config["services"]), "SERVICE_SET_DRIFT")
    for name, before in config["services"].items():
        keys = ["Name", "StartMode", "StartName", "PathName"]
        if name != "MomentumHunterAutomation":
            keys += ["State", "ProcessId", "ProcessCreatedAt"]
        if name == "MomentumHunterAutomation":
            permitted = config.get("authorizedServiceDefinitions", [before["PathName"]])
            require(live[name]["PathName"] in permitted, "UNAUTHORIZED_AUTOMATION_SELECTOR")
            keys.remove("PathName")
            expected["services"][name]["PathName"] = live[name]["PathName"]
        require(all(live[name][key] == before[key] for key in keys), "SERVICE_IDENTITY_DRIFT:" + name)
    observed_tasks = tasks()
    baseline = {(r["path"], r["name"]): r for r in config["scheduledTasks"]}
    observed = {(r["path"], r["name"]): r for r in observed_tasks}
    require(len(observed) == len(observed_tasks) and all(observed.get(k) == v for k, v in baseline.items()), "SCHEDULER_DEFINITION_DRIFT")
    extras = set(observed) - set(baseline)
    pending = {(r["path"], r["name"]) for r in (ownership or {}).get("pendingGuardianSlots", [])}
    verified = {(r["path"], r["name"]): r for r in (ownership or {}).get("verifiedGuardianTasks", [])}
    permitted = {(r["path"], r["name"]) for r in config.get("authorizedGuardianSlots", [])}
    require(pending <= permitted and set(verified) <= pending, "GUARDIAN_SLOT_POLICY_VIOLATION")
    require(extras <= pending and all(observed.get(k) == v for k, v in verified.items()), "UNAUTHORIZED_SCHEDULER_ADDITION")
    conf = load(config["continuousPath"])
    gates, errors, phase = service_and_observer_checks(conf, expected, live, now, clock=ObservationClock(lambda: datetime.now(timezone.utc)))
    require(not errors and all(v for k, v in gates.items() if k != "AUTOMATION_SERVICE_RUNNING"), "CONTINUOUS_OR_OBSERVER_REJECTED")
    result = {"action": action, "checkedAt": now.isoformat(), "observation": observation,
              "services": live, "phase": phase, "gates": gates, "providerContact": False,
              "executionAuthority": "NONE", "epoch": config["epoch"],
              "schedulerPendingParentActivation": bool(extras and not verified)}
    if action in {"preflight", "restart-preflight"}:
        require(live["MomentumHunterAutomation"]["State"] == "Stopped"
                and live["MomentumHunterAutomation"]["ProcessId"] == 0, "AUTOMATION_NOT_STOPPED")
        if action == "preflight":
            for path, expected_hash in config["dynamicStateFiles"].items():
                require(digest(path) == expected_hash, "PRESTART_STATE_DRIFT:" + path)
        else:
            require(ownership and observation["state"]["service_instance_id"] == ownership["binding"]["serviceInstanceId"]
                    and observation["state"]["service_started_at"] == ownership["binding"]["serviceStartedAt"]
                    and observation["state"]["state_version"] >= ownership["binding"]["minimumStateVersion"],
                    "RESTART_PRESTART_NOT_BOUND_TO_PRIOR_GENERATION")
        release = verify_opening_readonly(manifest, observation["state"], expected)
        loaded = release.pop("OPENING_LOADED_BYTES_MATCH")
        require(all(release.values()), "OPENING_RELEASE_BINDING_FAILED")
        if not loaded:
            require(action == "preflight" and observation["sha256"] == config.get("acceptedPrestartStateSha256")
                    and all(observation["state"].get(key) == value for key, value in config.get("acceptedPrestartLoadedBytes", {}).items())
                    and set(config.get("acceptedPrestartLoadedBytes", {})) == set(config["expectedLoadedBytes"]),
                    "OPENING_PRESTART_LOADED_BYTES_UNBOUND")
        release["OPENING_LOADED_BYTES_MATCH"] = loaded
        release["PRESTART_ONLY_NO_RUNNING_READINESS_CLAIM"] = True
        result["opening"] = release
    elif action == "sample":
        value = observation["state"]
        binding = runtime_binding(config, ownership, value)
        truth = automation_heartbeat(value, live["MomentumHunterAutomation"], binding,
            now=datetime.now(timezone.utc), read_at=recovery.timestamp(observation["readCompletedAt"]),
            source_sha256=observation["sha256"])
        result.update(binding=binding, truth=truth)
    elif action == "guardian":
        require(ownership and ownership.get("binding", {}).get("serviceInstanceId"), "BOUND_RUNTIME_REQUIRED")
        expected["automationRuntime"] = ownership["binding"]
        report = inspect_readiness(manifest_path=Path(config["manifestPath"]), state_path=Path(config["statePath"]),
            continuous_path=Path(config["continuousPath"]), expected_manifest_sha256=config["staticFiles"][config["manifestPath"]],
            expected_continuous_sha256=config["staticFiles"][config["continuousPath"]], canonical_head=config["canonicalHead"],
            origin_head=config["canonicalHead"], canonical_clean=True, expected_canonical=config["canonicalHead"],
            services=live, session_date=config["sessionDate"], clock=lambda: datetime.now(timezone.utc),
            service_reader=services, expectations=expected)
        result["guardian"] = report
        require(report["status"] == "GREEN_READY" and not report["failedGates"], "GUARDIAN_NOT_GREEN")
    else:
        raise ValueError("UNKNOWN_READONLY_ACTION")
    canonical(config)
    verify_input_files(config)
    result["status"] = "PASS"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "restart-preflight", "sample", "guardian"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--ownership", type=Path)
    parser.add_argument("--ownership-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(digest(args.config) == args.config_sha256, "READONLY_CONFIG_DRIFT")
    config = load(args.config)
    require(bool(args.ownership) == bool(args.ownership_sha256), "OWNERSHIP_HASH_REQUIRED")
    if args.ownership:
        require(digest(args.ownership) == args.ownership_sha256, "OWNERSHIP_RECORD_DRIFT")
    output = args.output.resolve()
    allowed = Path(config["evidenceRoot"]).resolve()
    protected = [Path(config["canonicalRoot"]).resolve(), Path(os.environ.get("ProgramData", "C:/ProgramData")).resolve()]
    require(output.is_relative_to(allowed) and not any(output.is_relative_to(p) for p in protected), "READONLY_OUTPUT_ESCAPE")
    def guard(event, values):
        if event in {"socket.connect", "socket.bind", "socket.sendto", "socket.getaddrinfo"}:
            raise PermissionError("NO_PROVIDER_OR_NETWORK_AUTHORITY")
        if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
            mode, flags = values[1:3]
            writing = isinstance(mode, str) and any(x in mode for x in "wax+")
            writing = writing or isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing and Path(os.fsdecode(values[0])).resolve() != output:
                raise PermissionError("READONLY_ADAPTER_WRITE_DENIED")
    sys.addaudithook(guard)
    try:
        result = check(config, args.action, load(args.ownership) if args.ownership else None)
    except Exception as error:
        result = {"status": "FAIL", "action": args.action, "errorType": type(error).__name__, "error": str(error),
                  "providerContact": False, "executionAuthority": "NONE"}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
    print(json.dumps({"status": result["status"], "receipt": str(output)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
