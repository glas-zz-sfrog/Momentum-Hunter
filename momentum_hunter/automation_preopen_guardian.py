"""Independent read-only readiness inspection; never constructs a runtime."""
from __future__ import annotations

import json
import math
import re
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Callable

from momentum_hunter.automation_guardian_liveness import ObservationClock, automation_heartbeat

from momentum_hunter.automation_state_recovery import (
    DurableStateStorage, StateRecoveryError, decode, digest, timestamp,
    validate_epoch,
)


def parse_session_date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("SESSION_DATE_REQUIRES_ISO_YYYY_MM_DD")
    return date.fromisoformat(value)


def session_contract(expectations: dict, session_date: str) -> tuple[dict, datetime, datetime]:
    requested = parse_session_date(session_date)
    contract = expectations["targetSession"]
    if not isinstance(contract, dict) or contract.get("sessionDate") != requested.isoformat():
        raise ValueError("TARGET_SESSION_EXPECTATION_MISMATCH")
    if contract.get("timezone") != "America/Chicago":
        raise ValueError("TARGET_SESSION_TIMEZONE_MISMATCH")
    start, latest = timestamp(contract["scheduledAt"]), timestamp(contract["latestStartAt"])
    central = ZoneInfo("America/Chicago")
    if any(value.astimezone(central).date() != requested
           or value.utcoffset() != value.astimezone(central).utcoffset() for value in (start, latest)):
        raise ValueError("TARGET_SESSION_DATE_OR_OFFSET_MISMATCH")
    if not start < latest or contract.get("jobId") != "opening-capture-" + requested.strftime("%Y%m%d"):
        raise ValueError("TARGET_SESSION_JOB_OR_WINDOW_MISMATCH")
    if (contract.get("approvedRuntimeChannel") != "opening-capture"
        or contract.get("observerId") != "argus-opening-authorized-release-observer"
        or contract.get("observerId") != expectations.get("observer", {}).get("id")):
        raise ValueError("TARGET_SESSION_HANDOFF_MISMATCH")
    return contract, start, latest


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


def continuous_phase_liveness(status: dict, config: dict, expected: dict, now: datetime) -> tuple[bool, dict]:
    from momentum_hunter.continuous_production import (
        _market_session_phase, _resolved_discovery_cadence, PROFILE,
    )
    health = status["health"]
    started = timestamp(health["started_at"]).astimezone(timezone.utc)
    uptime = health["uptime_seconds"]
    if type(uptime) not in (int, float) or not math.isfinite(uptime) or uptime < 0:
        raise ValueError("CONTINUOUS_STATUS_UPTIME_INVALID")
    observed = started + timedelta(seconds=uptime)
    checked = now.astimezone(timezone.utc)
    phase = _market_session_phase(now)
    snapshot_phase = _market_session_phase(observed)
    cadence = _resolved_discovery_cadence(phase, config)
    heartbeat = timestamp(health["last_heartbeat_at"]).astimezone(timezone.utc)
    current = timedelta(0) <= checked-observed <= timedelta(seconds=120)
    identity = (bool(expected.get("runtimeInstanceId"))
        and health.get("runtime_instance_id") == expected["runtimeInstanceId"]
        and status.get("activationStart") == config.get("activationStart"))
    matching_phase = phase == snapshot_phase == status.get("sessionPhase")
    matching_cadence = ("resolvedDiscoveryCadenceSeconds" in status
        and status["resolvedDiscoveryCadenceSeconds"] == cadence
        and (cadence is None or (math.isfinite(cadence) and cadence > 0)))
    flags = health.get("health_flags")
    healthy = (health.get("stall_blocker") is None and health.get("stalled_since") is None
        and health.get("pipeline_state") in {"INITIALIZING", "FORWARD_PROGRESS"}
        and isinstance(flags, list) and "FAILED_FORWARD_PROGRESS" not in flags)
    chronology = started <= heartbeat <= observed <= checked
    tick_raw = health.get("last_tick_at")
    tick = timestamp(tick_raw).astimezone(timezone.utc) if tick_raw is not None else None
    if phase == "SESSION_CLOSED":
        state_ok = status.get("state") == "IDLE_OUT_OF_SESSION" and health.get("process_state") in {"READY", "RUNNING"}
        clocks_ok = chronology and (tick is None or started <= tick <= observed)
        model = "CLOSED_SESSION"
    else:
        state_ok = status.get("state") == health.get("process_state") == "RUNNING"
        clocks_ok = (chronology and tick is not None and heartbeat <= tick <= observed
            and checked-heartbeat <= timedelta(seconds=120) and checked-tick <= timedelta(seconds=120))
        model = "PREOPEN" if phase == "PREMARKET" else "REGULAR_SESSION"
    valid = (status.get("schemaVersion") == 1 and status.get("profile") == PROFILE
        and current and identity and matching_phase and matching_cadence and healthy and state_ok and clocks_ok)
    return bool(valid), {"currentPhase":phase, "guardianPhase":model, "snapshotPhase":snapshot_phase,
        "snapshotObservedAt":observed.isoformat(), "snapshotAgeSeconds":(checked-observed).total_seconds(),
        "snapshotCurrent":current, "phaseMatches":matching_phase, "cadenceMatches":matching_cadence,
        "expectedDiscoveryCadenceSeconds":cadence, "stateValid":state_ok, "clocksValid":clocks_ok,
        "runtimeInstanceId": health.get("runtime_instance_id"), "runtimeIdentityMatches": identity,
        "runtimeStartedAt": started.isoformat(), "heartbeatAt": heartbeat.isoformat(),
        "heartbeatType": "RUNTIME_START_OR_HOUSEKEEPING",
        "heartbeatAgeSeconds": (checked-heartbeat).total_seconds(),
        "lastTickAt": tick.isoformat() if tick else None,
        "evaluatedAt": now.isoformat(),
        "readinessState": ("HEALTHY_CLOSED_SESSION" if model == "CLOSED_SESSION" else
                          "HEALTHY_PREOPEN" if model == "PREOPEN" else "HEALTHY_ACTIVE_SESSION") if valid else
                         "RUNTIME_INSTANCE_MISMATCH" if not identity else
                         "CONFIG_MISMATCH" if not matching_cadence else
                         "STALE" if not current else "UNKNOWN",
        "policy":"Fresh serialized status in every phase; active tick/housekeeping freshness <=120 seconds. No market-data success inferred."}


def service_and_observer_checks(continuous: dict, expected: dict, services: dict, now: datetime,
                                *, clock: ObservationClock | None = None,
                                snapshot: dict | None = None) -> tuple[dict, dict, dict]:
    gates, errors, phase_evidence = {}, {}, {}
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
        read_started = clock.take("continuousReadStarted") if clock else now
        raw_status = status_path.read_bytes()
        read_completed = clock.take("continuousReadCompleted") if clock else now
        status = json.loads(raw_status)
        health = status["health"]
        # The status fingerprint is integrity, not proof of provider freshness.
        body = {k: v for k, v in status.items() if k != "fingerprint"}
        material = (json.dumps({"domain": "production-continuous-runtime-status-v1", "value": body},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
        status_hash = digest(material)
        gates["CONTINUOUS_STATUS_INTEGRITY_VALID"] = status.get("fingerprint") == status_hash
        gates["CONTINUOUS_EXPECTED_LIVENESS"], phase_evidence = continuous_phase_liveness(status, continuous, runtime, read_completed)
        phase_evidence.update(sourcePath=str(status_path), sourceSha256=digest(raw_status),
                              readStartedAt=read_started.isoformat(), readCompletedAt=read_completed.isoformat())
        if snapshot is not None:
            snapshot.update(status=status, read_completed=read_completed,
                            read_liveness=gates["CONTINUOUS_EXPECTED_LIVENESS"])
        gates["CONTINUOUS_STATUS_NO_EXECUTION"] = (status.get("mode") == "RESEARCH_ONLY"
            and status.get("executionAuthority") == "EXECUTION_AUTHORITY_NONE"
            and all(status.get(k) == "UNAVAILABLE" for k in ("orderCapability", "accountReads", "positionReads",
                "brokerOrders", "alpacaPaper", "alpacaLive", "shadowExecution")))
    except (OSError, ValueError, TypeError, KeyError, OverflowError, StateRecoveryError) as exc:
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
    return gates, errors, phase_evidence


def inspect_readiness(*, manifest_path: Path, state_path: Path,
                      continuous_path: Path, expected_manifest_sha256: str,
                      expected_continuous_sha256: str, canonical_head: str,
                      origin_head: str, canonical_clean: bool, expected_canonical: str,
                      services: dict, session_date: str, now: datetime | None = None,
                      expectations: dict | None = None,
                      clock: Callable[[], datetime] | None = None,
                      service_reader: Callable[[], dict] | None = None) -> dict:
    expectations = expectations or {}
    fixed_now = now
    observation_clock = ObservationClock(clock or ((lambda: fixed_now) if fixed_now is not None
                                                  else (lambda: datetime.now().astimezone())))
    now = observation_clock.take("inspectionStarted")
    gates = {}
    errors = {}
    contract, start, latest = {}, None, None
    try:
        contract, start, latest = session_contract(expectations, session_date)
        gates["TARGET_SESSION_CONTRACT_VALID"] = True
    except (ValueError, TypeError, KeyError, StateRecoveryError) as exc:
        gates["TARGET_SESSION_CONTRACT_VALID"] = False
        errors["targetSession"] = str(exc)
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
    continuous_snapshot = {}
    more_gates, more_errors, phase_evidence = service_and_observer_checks(
        continuous, expectations, services, now, clock=observation_clock, snapshot=continuous_snapshot)
    gates.update(more_gates)
    errors.update(more_errors)
    gates["STATE_FILE_EXISTS"] = state_path.is_file()
    def forbidden_replace(*args):
        raise AssertionError("READ_ONLY_GUARDIAN")
    authoritative_state, recovery_report, raw_state = {}, {}, b""
    state_attempts = []
    # Never mix a heartbeat from one current JSON with another generation's
    # epoch/receipts. A concurrent atomic publish gets three bounded attempts.
    for attempt in range(3):
        read_started = observation_clock.take("stateReadStarted")
        try:
            raw_state = state_path.read_bytes()
        except OSError:
            raw_state = b""
        recovery_report, authoritative_state = {}, {}
        recovery_error = None
        try:
            storage = DurableStateStorage(state_path, forbidden_replace)
            authoritative_state = storage.load(now=read_started, custody=False) or {}
            recovery_report = storage.report
        except (OSError, StateRecoveryError) as exc:
            recovery_error = str(exc)
        try:
            after_raw = state_path.read_bytes()
        except OSError:
            after_raw = b""
        read_completed = observation_clock.take("stateReadCompleted")
        stable = raw_state == after_raw
        state_attempts.append({"attempt": attempt+1, "readStartedAt": read_started.isoformat(),
            "readCompletedAt": read_completed.isoformat(), "beforeSha256": digest(raw_state),
            "afterSha256": digest(after_raw), "stable": stable, "recoveryError": recovery_error})
        if stable:
            break
    gates["STATE_SNAPSHOT_STABLE"] = stable
    if recovery_error:
        errors["recovery"] = recovery_error
    gates["RECOVERY_GENERATION_AVAILABLE"] = recovery_report.get("valid_generations", 0) > 0
    gates["STATE_RECONCILIATION_HEALTHY"] = recovery_report.get("recovery_source") == "CURRENT"
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
    gates["STATE_SNAPSHOT_COHERENT"] = bool(state) and state == authoritative_state
    state_read_completed = read_completed
    jobs = manifest.get("jobs", [])
    jobs_valid = isinstance(jobs, list) and all(isinstance(j, dict) for j in jobs)
    jobs = jobs if jobs_valid else []
    target_id = contract.get("jobId", "")
    opening = [j for j in jobs if target_id and j.get("jobId") == target_id and j.get("enabled") is True and j.get("kind") == "opening_capture"]
    gates["OPENING_JOB_PRESENT"] = len(opening) == 1
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
    gates["TARGET_SESSION_SUPPORTED"] = gates["TARGET_SESSION_CONTRACT_VALID"] and len(parsed_jobs) == 1 and len(opening) == 1
    gates["OPENING_SCHEDULE_CORRECT"] = start is not None and len(opening) == 1 and opening[0].get("scheduledAt") == start.isoformat()
    gates["LATEST_START_CORRECT"] = latest is not None and len(opening) == 1 and opening[0].get("latestStartAt") == latest.isoformat()
    gates["OPENING_SESSION_HANDOFF_CORRECT"] = len(opening) == 1 and opening[0].get("approvedRuntimeChannel") == contract.get("approvedRuntimeChannel")
    gates["PRODUCTION_CONFIG_EXPECTED"] = (bool(raw_manifest) and digest(raw_manifest) == expected_manifest_sha256.lower()
        and bool(raw_continuous) and digest(raw_continuous) == expected_continuous_sha256.lower()
        and Path(str(manifest.get("stateDirectory", ""))).resolve() == state_path.parent.resolve())
    gates["GUARDIAN_EXPECTATIONS_VALID"] = expectations.get("schemaVersion") == 2 and expectations.get("continuousAuthorityModel") == "SEPARATE_CONTINUOUS_SERVICE"
    gates["CANONICAL_EXPECTED"] = canonical_head == origin_head == expected_canonical and canonical_clean
    gates["NO_PAPER_LIVE_AUTHORITY"] = (jobs_valid and bool(raw_manifest) and bool(raw_continuous)
        and not any(j.get("enabled") is not False and j.get("kind") in {"paper_engineering", "shadow_opening"} for j in jobs)
        and continuous.get("mode") == "RESEARCH_ONLY" and continuous.get("executionAuthority") == "NONE"
        and continuous.get("orderCapability") == "UNAVAILABLE"
        and continuous.get("positionsRequested") is False and continuous.get("ordersRequested") is False)
    try:
        floor = timestamp(authoritative_state["recovery_floor_at"]) if authoritative_state.get("recovery_floor_at") else None
        gates["OPENING_NOT_QUARANTINED"] = start is not None and (floor is None or start > floor)
    except StateRecoveryError:
        gates["OPENING_NOT_QUARANTINED"] = False
    epoch = authoritative_state.get("prospective_epoch", {})
    gates["EPOCH_PRESENT"] = bool(epoch)
    try:
        validate_epoch(epoch)
        gates["EPOCH_ID_VALID"] = epoch["epochId"] == expectations.get("expectedEpochId")
        boundary = timestamp(epoch["boundaryAt"])
        gates["EPOCH_BOUNDARY_VALID"] = (start is not None and boundary <= now and boundary < start
            and epoch["boundaryAt"] == expectations.get("expectedEpochBoundary"))
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
    if service_reader is not None:
        try:
            gates["SERVICE_OBSERVATION_STABLE"] = service_reader() == services
        except Exception as exc:
            gates["SERVICE_OBSERVATION_STABLE"] = False
            errors["serviceRecheck"] = type(exc).__name__
    evaluated_at = observation_clock.take("inspectionCompleted")
    gates["OBSERVATION_CLOCK_ORDERED"] = observation_clock.valid
    heartbeat_evidence = automation_heartbeat(authoritative_state,
        services.get("MomentumHunterAutomation", {}), expectations.get("automationRuntime", {}),
        now=evaluated_at, read_at=state_read_completed, source_sha256=digest(raw_state))
    heartbeat_evidence.update(sourcePath=str(state_path), sourceSha256=digest(raw_state),
                             readAttempts=state_attempts, recovery=recovery_report)
    gates["STATE_HEARTBEAT_CURRENT"] = heartbeat_evidence["ready"]
    if continuous_snapshot:
        final_valid, final_phase = continuous_phase_liveness(continuous_snapshot["status"], continuous,
                                                           expectations.get("continuous", {}), evaluated_at)
        phase_evidence.update(final_phase)
        gates["CONTINUOUS_EXPECTED_LIVENESS"] = continuous_snapshot["read_liveness"] and final_valid
    now = evaluated_at
    gates["OPENING_WINDOW_NOT_PASSED"] = latest is not None and now <= latest
    failed = [key for key, value in gates.items() if value is not True]
    # Partial startup is explicitly non-green. Other failed invariants always
    # remain RED, including mismatched epoch, loaded bytes, or service identity.
    pending = heartbeat_evidence["pending"] and set(failed) <= {
        "STATE_HEARTBEAT_CURRENT", "OPENING_LOADED_BYTES_MATCH", "AUTOMATION_SERVICE_RUNNING"}
    readiness = "PENDING_NOT_READY" if pending else "RED_NOT_READY" if failed else "GREEN_READY"
    return {"schemaVersion": 1, "checkedAt": now.isoformat(), "sessionDate": session_date,
            "status": readiness, "targetSession": contract, "gates": gates,
            "failedGates": failed, "errors": errors, "authority": "READ_ONLY",
            "continuousServicePresent": "MomentumHunterContinuousRuntime" in services,
            "continuousSchedulingNote": "Separate service/configuration/identity and persisted liveness; no Automation Continuous job exists.",
            "continuousAuthorityModel": "SEPARATE_CONTINUOUS_SERVICE",
            "continuousPhaseEvidence": phase_evidence,
            "automationHeartbeatEvidence": heartbeat_evidence,
            "observationChronology": observation_clock.samples,
            "providerReadiness": "FUTURE_PROVIDER_RESULTS_UNPROVEN",
            "mutationsPerformed": False, "executionAuthority": "NONE"}
