"""Independent read-only readiness inspection; never constructs a runtime."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.automation_state_recovery import (
    DurableStateStorage, StateRecoveryError, decode, digest, timestamp,
)


def inspect_readiness(*, manifest_path: Path, state_path: Path,
                      continuous_path: Path, expected_manifest_sha256: str,
                      expected_continuous_sha256: str, canonical_head: str,
                      origin_head: str, canonical_clean: bool, expected_canonical: str,
                      services: dict, session_date: str, now: datetime) -> dict:
    gates = {}
    errors = {}
    def read_json(path, label):
        try:
            raw = path.read_bytes()
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("object required")
            return raw, result
        except (OSError, ValueError) as exc:
            errors[label] = type(exc).__name__
            return b"", {}
    raw_manifest, manifest = read_json(manifest_path, "manifest")
    raw_continuous, continuous = read_json(continuous_path, "continuous")
    parsed_manifest = None
    try:
        # Reuse the real grammar, never construct/tick a supervisor or load state.
        from momentum_hunter.automation_supervisor import parse_manifest, receipt_compatibility_error
        parsed_manifest = parse_manifest(manifest_path)
        gates["MANIFEST_SCHEMA_VALID"] = manifest_path.read_bytes() == raw_manifest
    except Exception as exc:
        gates["MANIFEST_SCHEMA_VALID"] = False
        errors["manifestValidation"] = type(exc).__name__
    gates["AUTOMATION_SERVICE_RUNNING"] = services.get("MomentumHunterAutomation") == "Running"
    gates["STATE_FILE_EXISTS"] = state_path.is_file()
    try:
        raw_state = state_path.read_bytes()
    except OSError:
        raw_state = b""
    gates["STATE_FILE_NONZERO"] = bool(raw_state) and any(raw_state)
    try:
        json.loads(raw_state)
        gates["STATE_PARSEABLE"] = True
    except (ValueError, UnicodeError):
        gates["STATE_PARSEABLE"] = False
    try:
        state = decode(raw_state)
        gates["STATE_SCHEMA_VALID"] = True
    except StateRecoveryError as exc:
        errors["state"] = exc.code
        state = {}
        gates["STATE_SCHEMA_VALID"] = False
    def forbidden_replace(*args):
        raise AssertionError("READ_ONLY_GUARDIAN")
    authoritative_state = {}
    try:
        storage = DurableStateStorage(state_path, forbidden_replace)
        authoritative_state = storage.load(now=now, custody=False) or {}
        gates["RECOVERY_GENERATION_AVAILABLE"] = storage.report.get("valid_generations", 0) > 0
        gates["STATE_RECONCILIATION_HEALTHY"] = storage.report.get("recovery_source") == "CURRENT"
    except (OSError, StateRecoveryError) as exc:
        errors["recovery"] = str(exc)
        gates["RECOVERY_GENERATION_AVAILABLE"] = False
        gates["STATE_RECONCILIATION_HEALTHY"] = False
    try:
        age = now - timestamp(state.get("last_heartbeat_at"))
        gates["STATE_HEARTBEAT_CURRENT"] = timedelta(0) <= age <= timedelta(seconds=120)
    except StateRecoveryError:
        gates["STATE_HEARTBEAT_CURRENT"] = False
    jobs = manifest.get("jobs", [])
    jobs_valid = isinstance(jobs, list) and all(isinstance(j, dict) for j in jobs)
    jobs = jobs if jobs_valid else []
    opening = [j for j in jobs if j.get("jobId") == "opening-capture-" + session_date.replace("-", "") and j.get("enabled") is True and j.get("kind") == "opening_capture"]
    gates["OPENING_JOB_PRESENT"] = len(opening) == 1
    target_id = "opening-capture-" + session_date.replace("-", "")
    receipt = authoritative_state.get("jobs", {}).get(target_id)
    parsed_jobs = [j for j in parsed_manifest.jobs if j.job_id == target_id] if parsed_manifest else []
    compatibility = "STATE_OR_MANIFEST_AUTHORITY_UNAVAILABLE"
    if authoritative_state and gates["MANIFEST_SCHEMA_VALID"] and len(parsed_jobs) == 1:
        compatibility = receipt_compatibility_error(parsed_jobs[0], receipt) if receipt else ""
    gates["OPENING_RECEIPT_COMPATIBLE"] = not compatibility
    if compatibility:
        errors["openingReceipt"] = compatibility
    disposition = receipt.get("status") if receipt else None
    gates["OPENING_NOT_ALREADY_TERMINAL"] = disposition not in {"COMPLETED", "FAILED", "MISSED", "DISABLED", "BLOCKED_DEPENDENCY"}
    gates["OPENING_NOT_IN_PROGRESS"] = disposition != "RUNNING"
    start = datetime.fromisoformat(session_date + "T08:35:00-05:00")
    latest = start + timedelta(minutes=5)
    # The target task is Sep09 CDT. Other dates require an explicit time contract.
    gates["TARGET_SESSION_SUPPORTED"] = session_date == "2026-09-09"
    gates["OPENING_SCHEDULE_CORRECT"] = len(opening) == 1 and opening[0].get("scheduledAt") == start.isoformat()
    gates["LATEST_START_CORRECT"] = len(opening) == 1 and opening[0].get("latestStartAt") == latest.isoformat()
    gates["CONTINUOUS_JOB_PRESENT"] = any(j.get("enabled") is True and str(j.get("kind", "")).startswith("continuous") for j in jobs)
    gates["PRODUCTION_CONFIG_EXPECTED"] = (bool(raw_manifest) and digest(raw_manifest) == expected_manifest_sha256.lower()
        and bool(raw_continuous) and digest(raw_continuous) == expected_continuous_sha256.lower()
        and Path(str(manifest.get("stateDirectory", ""))).resolve() == state_path.parent.resolve())
    gates["CANONICAL_EXPECTED"] = canonical_head == origin_head == expected_canonical and canonical_clean
    gates["NO_PAPER_LIVE_AUTHORITY"] = (jobs_valid and bool(raw_manifest) and bool(raw_continuous)
        and not any(j.get("enabled") is not False and j.get("kind") in {"paper_engineering", "shadow_opening"} for j in jobs)
        and continuous.get("mode") == "RESEARCH_ONLY" and continuous.get("executionAuthority") == "NONE"
        and continuous.get("orderCapability") == "UNAVAILABLE"
        and continuous.get("positionsRequested") is False and continuous.get("ordersRequested") is False)
    try:
        floor = timestamp(authoritative_state["recovery_floor_at"]) if authoritative_state.get("recovery_floor_at") else None
        gates["OPENING_NOT_QUARANTINED"] = floor is None or start > floor
    except StateRecoveryError:
        gates["OPENING_NOT_QUARANTINED"] = False
    failed = [key for key, value in gates.items() if value is not True]
    return {"schemaVersion": 1, "checkedAt": now.isoformat(), "sessionDate": session_date,
            "status": "RED_NOT_READY" if failed else "GREEN_READY", "gates": gates,
            "failedGates": failed, "errors": errors, "authority": "READ_ONLY",
            "continuousServicePresent": "MomentumHunterContinuousRuntime" in services,
            "continuousSchedulingNote": "Separate service is not an Automation scheduled job; no equivalence is inferred.",
            "mutationsPerformed": False, "executionAuthority": "NONE"}
