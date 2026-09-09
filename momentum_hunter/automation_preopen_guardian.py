"""Independent read-only readiness inspection; never constructs a runtime."""
from __future__ import annotations

import json
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.automation_state_recovery import (
    DurableStateStorage, StateRecoveryError, decode, digest, timestamp,
    validate_epoch,
)


def verify_opening_readonly(manifest, state: dict, expected: dict) -> dict:
    from momentum_hunter.opening_runtime_identity import (
        OpeningRuntimeReleaseStore, RuntimeIdentityContext, RELEASE_SCHEMA_V2,
        build_runtime_identity, build_runtime_identity_v2, _require_regular_path,
    )
    class ExistingReleaseStore(OpeningRuntimeReleaseStore):
        def initialize(self):
            for directory in (self.root, self.releases_directory, self.promotions_directory, self.channels_directory):
                _require_regular_path(directory, directory=True)

        @staticmethod
        def _write_once(*args):
            raise RuntimeError("READ_ONLY_GUARDIAN")

        @staticmethod
        def _atomic_write(*args):
            raise RuntimeError("READ_ONLY_GUARDIAN")

    release, _, _ = ExistingReleaseStore(manifest.opening_runtime_release_root).verify_channel("opening-capture")
    context = RuntimeIdentityContext(repository_root=manifest.repository_root,
        python_executable=manifest.python_executable, powershell_executable=manifest.powershell_executable,
        state_directory=manifest.state_directory, engine_host_state_directory=manifest.engine_host_state_directory,
        poll_interval_seconds=manifest.poll_interval_seconds, service_host_executable=manifest.service_host_executable,
        release_root=manifest.opening_runtime_release_root)
    current = (build_runtime_identity_v2 if release["schemaVersion"] == RELEASE_SCHEMA_V2 else build_runtime_identity)(context)
    components = {item["path"]: item["sha256"] for item in release["runtimeComponents"]}
    return {
        "OPENING_RELEASE_IDENTITY_EXPECTED": release["releaseId"] == expected.get("openingReleaseId")
            and release["releaseFingerprint"] == expected.get("openingReleaseFingerprint"),
        "OPENING_AUTHORIZED_BINDING_VALID": True,
        "OPENING_RUNTIME_BYTES_MATCH": current["approvedRuntimeFingerprint"] == release["approvedRuntimeFingerprint"],
        "OPENING_LOADED_BYTES_MATCH": all((state.get(k) and state[k] == v) for k, v in {
            "loaded_supervisor_sha256": components.get("momentum_hunter/automation_supervisor.py"),
            "loaded_runtime_identity_module_sha256": components.get("momentum_hunter/opening_runtime_identity.py"),
            "loaded_service_host_sha256": release["environmentIdentity"]["serviceHost"]["sha256"],
        }.items()),
    }


def service_and_observer_checks(continuous: dict, expected: dict, services: dict, now: datetime) -> tuple[dict, dict]:
    gates, errors = {}, {}
    for name, label in (("MomentumHunterAutomation", "AUTOMATION"),
                        ("MomentumHunterContinuousRuntime", "CONTINUOUS"),
                        ("MomentumHunterContinuousWriter", "CONTINUOUS_WRITER")):
        actual = services.get(name)
        definition = expected.get("services", {}).get(name)
        gates[label + "_SERVICE_PRESENT"] = isinstance(actual, dict)
        gates[label + "_SERVICE_CONFIGURATION_EXPECTED"] = bool(definition) and isinstance(actual, dict) and all(
            actual.get(key) == definition.get(key) and bool(definition.get(key)) for key in ("PathName", "StartName", "StartMode"))
        gates[label + "_SERVICE_RUNNING"] = isinstance(actual, dict) and actual.get("State") == "Running"
    runtime = expected.get("continuous", {})
    gates["CONTINUOUS_RUNTIME_IDENTITY_EXPECTED"] = bool(runtime.get("runtimeIdentity")) and all(
        continuous.get(key) == runtime.get(key) for key in ("runtimeIdentity", "runtimeBuildHash", "configurationFingerprint"))
    inventory = runtime.get("files", {})
    try:
        gates["CONTINUOUS_INSTALLED_BYTES_EXPECTED"] = bool(inventory) and all(
            digest(Path(path).read_bytes()) == value for path, value in inventory.items())
    except (OSError, ValueError, TypeError):
        gates["CONTINUOUS_INSTALLED_BYTES_EXPECTED"] = False
    try:
        status_path = Path(continuous["runtimeStateRoot"]) / "runtime-status.json"
        status = json.loads(status_path.read_bytes())
        health = status["health"]
        # The status fingerprint is integrity, not proof of provider freshness.
        body = {k: v for k, v in status.items() if k != "fingerprint"}
        material = (json.dumps({"domain": "production-continuous-runtime-status-v1", "value": body},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
        status_hash = digest(material)
        gates["CONTINUOUS_STATUS_INTEGRITY_VALID"] = status.get("fingerprint") == status_hash
        age = now - timestamp(health["last_heartbeat_at"])
        gates["CONTINUOUS_EXPECTED_LIVENESS"] = (status.get("state") == "RUNNING"
            and health.get("process_state") == "RUNNING" and timedelta(0) <= age <= timedelta(seconds=120)
            and bool(runtime.get("runtimeInstanceId"))
            and health.get("runtime_instance_id") == runtime["runtimeInstanceId"]
            and status.get("activationStart") == continuous.get("activationStart")
            and health.get("stall_blocker") is None and health.get("stalled_since") is None)
        gates["CONTINUOUS_STATUS_NO_EXECUTION"] = (status.get("mode") == "RESEARCH_ONLY"
            and status.get("executionAuthority") == "EXECUTION_AUTHORITY_NONE"
            and all(status.get(k) == "UNAVAILABLE" for k in ("orderCapability", "accountReads", "positionReads",
                "brokerOrders", "alpacaPaper", "alpacaLive", "shadowExecution")))
    except (OSError, ValueError, TypeError, KeyError, StateRecoveryError) as exc:
        for key in ("CONTINUOUS_STATUS_INTEGRITY_VALID", "CONTINUOUS_EXPECTED_LIVENESS", "CONTINUOUS_STATUS_NO_EXECUTION"):
            gates[key] = False
        errors["continuousStatus"] = type(exc).__name__
    observer = expected.get("observer", {})
    gates.update({"OBSERVER_CONFIGURATION_PRESENT": False, "OBSERVER_EXPECTED_IDENTITY": False,
                  "OBSERVER_EXPECTED_MODE": False, "OBSERVER_NO_EXECUTION_AUTHORITY": False, "OBSERVER_SINGLETON": False})
    try:
        path = Path(observer["path"])
        raw = path.read_bytes()
        config = tomllib.loads(raw.decode("utf-8"))
        gates["OBSERVER_CONFIGURATION_PRESENT"] = True
        matches = digest(raw) == observer["sha256"]
        gates["OBSERVER_EXPECTED_IDENTITY"] = matches and config.get("id") == "argus-opening-authorized-release-observer"
        gates["OBSERVER_EXPECTED_MODE"] = matches and config.get("kind") == "heartbeat" and config.get("status") == "ACTIVE" and "mode=CURRENT_AUTHORIZED_RELEASE" in config.get("prompt", "")
        gates["OBSERVER_NO_EXECUTION_AUTHORITY"] = matches and all(token in config.get("prompt", "") for token in (
            "strictly read-only", "orderTransmission UNAVAILABLE", "executionAuthorityUsed false", "paperAuthorityUsed false"))
        active = []
        for other in path.parent.parent.glob("*/automation.toml"):
            config = tomllib.loads(other.read_text(encoding="utf-8"))
            if config.get("status") == "ACTIVE" and (config.get("id") == observer.get("id")
                or "argus-opening-authorized-release-observer" in config.get("prompt", "")):
                active.append(other.resolve())
        gates["OBSERVER_SINGLETON"] = active == [path.resolve()]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors["observer"] = type(exc).__name__
    return gates, errors


def inspect_readiness(*, manifest_path: Path, state_path: Path,
                      continuous_path: Path, expected_manifest_sha256: str,
                      expected_continuous_sha256: str, canonical_head: str,
                      origin_head: str, canonical_clean: bool, expected_canonical: str,
                      services: dict, session_date: str, now: datetime,
                      expectations: dict | None = None) -> dict:
    expectations = expectations or {}
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
    more_gates, more_errors = service_and_observer_checks(continuous, expectations, services, now)
    gates.update(more_gates)
    errors.update(more_errors)
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
    gates["PRODUCTION_CONFIG_EXPECTED"] = (bool(raw_manifest) and digest(raw_manifest) == expected_manifest_sha256.lower()
        and bool(raw_continuous) and digest(raw_continuous) == expected_continuous_sha256.lower()
        and Path(str(manifest.get("stateDirectory", ""))).resolve() == state_path.parent.resolve())
    gates["GUARDIAN_EXPECTATIONS_VALID"] = expectations.get("schemaVersion") == 1 and expectations.get("continuousAuthorityModel") == "SEPARATE_CONTINUOUS_SERVICE"
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
    epoch = authoritative_state.get("prospective_epoch", {})
    gates["EPOCH_PRESENT"] = bool(epoch)
    try:
        validate_epoch(epoch)
        gates["EPOCH_ID_VALID"] = epoch["epochId"] == expectations.get("expectedEpochId")
        boundary = timestamp(epoch["boundaryAt"])
        gates["EPOCH_BOUNDARY_VALID"] = boundary <= now and boundary < start
        gates["EPOCH_SESSION_VALID"] = epoch["firstProspectiveSession"] == session_date
        gates["EPOCH_MANIFEST_BOUND"] = epoch["manifestSha256"] == digest(raw_manifest)
        gates["PRE_EPOCH_REPLAY_BLOCKED"] = epoch["preEpochReplayBlocked"] is True and floor is not None and floor >= boundary
    except (KeyError, StateRecoveryError, TypeError):
        for key in ("EPOCH_ID_VALID", "EPOCH_BOUNDARY_VALID", "EPOCH_SESSION_VALID", "EPOCH_MANIFEST_BOUND", "PRE_EPOCH_REPLAY_BLOCKED"):
            gates[key] = False
    try:
        if not parsed_manifest:
            raise ValueError("MANIFEST_UNAVAILABLE")
        gates.update(verify_opening_readonly(parsed_manifest, authoritative_state, expectations))
    except Exception as exc:
        for key in ("OPENING_RELEASE_IDENTITY_EXPECTED", "OPENING_AUTHORIZED_BINDING_VALID", "OPENING_RUNTIME_BYTES_MATCH", "OPENING_LOADED_BYTES_MATCH"):
            gates[key] = False
        errors["openingRuntime"] = getattr(exc, "code", type(exc).__name__)
    gates["OPENING_WINDOW_NOT_PASSED"] = now <= latest
    failed = [key for key, value in gates.items() if value is not True]
    return {"schemaVersion": 1, "checkedAt": now.isoformat(), "sessionDate": session_date,
            "status": "RED_NOT_READY" if failed else "GREEN_READY", "gates": gates,
            "failedGates": failed, "errors": errors, "authority": "READ_ONLY",
            "continuousServicePresent": "MomentumHunterContinuousRuntime" in services,
            "continuousSchedulingNote": "Separate service/configuration/identity and persisted liveness; no Automation Continuous job exists.",
            "continuousAuthorityModel": "SEPARATE_CONTINUOUS_SERVICE",
            "providerReadiness": "FUTURE_PROVIDER_RESULTS_UNPROVEN",
            "mutationsPerformed": False, "executionAuthority": "NONE"}
