"""Replay actual frozen pending schedules/state with all execution intercepted.

Only disposable state is written. Release/provider/Engine Host launch boundaries
are explicit doubles; this proves schedule/epoch/persistence, not market capture.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import automation_retry_readonly as ro
from momentum_hunter.automation_supervisor import AutomationSupervisor


def rehearse(config):
    ro.canonical(config)
    ro.verify_input_files(config)
    manifest = ro.parse_manifest(Path(config["manifestPath"]))
    snapshot = ro.state(config)
    target = "opening-capture-" + config["sessionDate"].replace("-", "")
    job = next(j for j in manifest.jobs if j.job_id == target)
    cases = []
    with tempfile.TemporaryDirectory(prefix="MH-Prechild-Schedule-") as temporary:
        root = Path(temporary)
        for label, minute, exit_code, expected in (("before", -1, 0, "PENDING"), ("at-start", 0, 0, "COMPLETED"),
            ("late-4", 4, 0, "COMPLETED"), ("latest-inclusive", 5, 0, "COMPLETED"),
            ("missed", 6, 0, "MISSED"), ("executor-failed", 0, 1, "FAILED")):
            state_root = root / label / "state"
            state_root.mkdir(parents=True)
            for original, sha in config["dynamicStateFiles"].items():
                source = Path(original)
                ro.require(ro.digest(source) == sha, "FROZEN_STATE_CHANGED_BEFORE_REHEARSAL")
                relative = source.relative_to(Path(config["statePath"]).parent)
                destination = state_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            transformed = replace(manifest, state_directory=state_root, engine_host_state_directory=root / label / "engine")
            now = job.scheduled_at + timedelta(minutes=minute)
            calls = []
            def execute(actual, log):
                ro.require(actual.job_id == target and actual.kind == "opening_capture", "UNEXPECTED_EXECUTION_IDENTITY")
                ro.require(log.is_relative_to(state_root), "FIXTURE_OUTPUT_ESCAPE")
                calls.append({"jobId": actual.job_id, "at": now.isoformat(), "scheduledAt": actual.scheduled_at.isoformat(),
                    "latestStartAt": actual.latest_start_at.isoformat(), "approvedRuntimeChannel": actual.approved_runtime_channel})
                return exit_code, "DISPOSABLE_EXECUTOR_INTERCEPT_NO_PROVIDER"
            def make():
                return AutomationSupervisor(transformed, clock=lambda: now, job_executor=execute,
                    runtime_gate=lambda _: None,
                    engine_host_probe=lambda: {"identity": {}, "health": {"state": "UNAVAILABLE", "detail": "NO_ENGINE_HOST_LAUNCH"}})
            first = make()
            first.tick()
            initial_instance = first.state.service_instance_id
            initial_version = first.state.state_version
            ro.require(first.state.jobs[target].status == expected, "COPIED_SCHEDULE_OUTCOME_MISMATCH:" + label)
            count = 0 if expected in {"PENDING", "MISSED"} else 1
            ro.require(len(calls) == count, "COPIED_SCHEDULE_EXECUTOR_COUNT")
            # Reconstruct the production class from its real durable fixture store.
            second = make()
            second.tick()
            ro.require(second.state.service_instance_id != initial_instance and second.state.state_version > initial_version,
                       "RESTART_GENERATION_OR_VERSION_NOT_ADVANCING")
            ro.require(len(calls) == count and second.state.jobs[target].status == expected, "DUPLICATE_EXECUTION_AFTER_RESTART")
            ro.require(second.state.prospective_epoch == config["epoch"] and
                second.state.recovery_floor_at == config["epoch"]["boundaryAt"], "EPOCH_REPLAY_FLOOR_CHANGED")
            ro.require(set(second.state.jobs) == set(snapshot["state"]["jobs"]), "HISTORICAL_RECEIPTS_FABRICATED")
            cases.append({"case": label, "status": "PASS", "clock": now.isoformat(), "outcome": expected,
                "interceptedExecutorCalls": calls, "restartCount": 1, "epochId": config["epoch"]["epochId"],
                "firstVersion": initial_version, "restartedVersion": second.state.state_version,
                "terminalFixtureState": asdict(second.state)})
    ro.canonical(config)
    ro.verify_input_files(config)
    ro.require(ro.state(config)["sha256"] == snapshot["sha256"], "PRODUCTION_STATE_CHANGED_DURING_REHEARSAL")
    return {"status": "PASS", "cases": cases, "sourceStateSha256": snapshot["sha256"],
        "manifestSha256": ro.digest(config["manifestPath"]), "epochReminted": False, "providerCalls": 0,
        "productionStarts": 0, "productionMutation": False,
        "explicitInterceptions": ["job executor", "runtime gate result", "Engine Host probe"],
        "relocations": ["state directory and state copies", "Engine Host state directory"],
        "scope": "CURRENT_COPIED_STATE_SCHEDULER_EPOCH_RESTART_NOT_MARKET_OR_PHYSICAL_RELEASE_PROOF"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--config-sha256", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    ro.require(ro.digest(args.config) == args.config_sha256.lower(), "INPUT_CONFIG_DRIFT")
    config = ro.load(args.config)
    ro.require(not args.output.exists() and args.output.resolve().is_relative_to(Path(config["evidenceRoot"]).resolve()), "NEW_EXTERNAL_RECEIPT_REQUIRED")
    result = rehearse(config)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    print(json.dumps({"status": result["status"], "cases": len(result["cases"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
