"""Read-only observation and bounded startup contracts. No runtime construction."""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from momentum_hunter.automation_state_recovery import StateRecoveryError, timestamp


FRESHNESS_SECONDS = 120
# This is an admission deadline, not a claim that Windows startup has an SLA.
# It reuses the accepted freshness ceiling; no stale evidence gains more time.
STARTUP_DEADLINE_SECONDS = 120


class ObservationClock:
    def __init__(self, clock: Callable[[], datetime]):
        self.clock = clock
        self.samples: list[dict] = []
        self.valid = True

    def take(self, label: str) -> datetime:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GUARDIAN_AWARE_CLOCK_REQUIRED")
        value = value.astimezone(timezone.utc)
        if self.samples and value < timestamp(self.samples[-1]["at"]):
            self.valid = False
        self.samples.append({"event": label, "at": value.isoformat()})
        return value


def automation_heartbeat(state: dict, service: dict, binding: dict, *,
                         now: datetime, read_at: datetime, source_sha256: str | None = None) -> dict:
    """Bind persisted tick completion to a separately admitted SCM generation."""
    result = {"state": "UNKNOWN", "ready": False, "pending": False,
              "heartbeatType": "SUPERVISOR_TICK_COMPLETION",
              "heartbeatProducer": "AutomationSupervisor._owned_tick",
              "field": "last_heartbeat_at", "heartbeatAt": state.get("last_heartbeat_at"),
              "serviceInstanceId": state.get("service_instance_id"),
              "serviceStartedAt": state.get("service_started_at"),
              "stateVersion": state.get("state_version"),
              "readCompletedAt": read_at.isoformat(), "evaluatedAt": now.isoformat(),
              "freshnessCeilingSeconds": FRESHNESS_SECONDS,
              "startupDeadlineSeconds": STARTUP_DEADLINE_SECONDS}

    def finish(name: str, *, ready=False, pending=False):
        return dict(result, state=name, ready=ready, pending=pending)

    if service.get("State") not in {"Running", "Start Pending"}:
        return finish("SERVICE_STOPPED")
    try:
        if not isinstance(binding, dict) or not binding:
            return finish("RUNTIME_INSTANCE_MISMATCH")
        pid = binding["wrapperProcessId"]
        born = timestamp(binding["wrapperCreatedAt"])
        if (type(pid) is not int or pid <= 0 or service.get("ProcessId") != pid
                or timestamp(service["ProcessCreatedAt"]) != born):
            return finish("RUNTIME_INSTANCE_MISMATCH")
        if not born <= read_at <= now:
            return finish("CLOCK_ANOMALY")
        epoch = state["prospective_epoch"]
        boundary = timestamp(epoch["boundaryAt"])
        if epoch["epochId"] != binding["epochId"] or born < boundary:
            return finish("EPOCH_MISMATCH")
        age_since_birth = (now-born).total_seconds()
        result["startupAgeSeconds"] = age_since_birth
        heartbeat_raw = state.get("last_heartbeat_at")
        prestart_hash = binding.get("preStartStateSha256")
        if (isinstance(prestart_hash, str) and len(prestart_hash) == 64
                and all(c in "0123456789abcdef" for c in prestart_hash)
                and source_sha256 == prestart_hash and heartbeat_raw
                and boundary <= timestamp(heartbeat_raw) < born
                and timestamp(state["service_started_at"]) < born):
            # Reusing an epoch also retains its last stopped-process heartbeat.
            # Only the exact independently preserved pre-start bytes may wait;
            # arbitrary foreign/old state still fails closed.
            result["waitingReason"] = "UNCHANGED_BOUND_PRESTART_STATE"
            if age_since_birth >= STARTUP_DEADLINE_SECONDS:
                return finish("STARTUP_TIMEOUT")
            return finish("STARTING" if service["State"] == "Start Pending"
                          else "WAITING_FOR_FIRST_HEARTBEAT", pending=True)
        if not heartbeat_raw:
            # An initializer has no runtime identity. A partially populated or
            # foreign persisted runtime is never explained away as "starting".
            if any(state.get(key) for key in ("service_instance_id", "service_started_at")):
                return finish("RUNTIME_INSTANCE_MISMATCH")
            if any(state.get(key) for key in ("loaded_supervisor_sha256",
                    "loaded_runtime_identity_module_sha256", "loaded_service_host_sha256")):
                return finish("UNKNOWN")
            if age_since_birth >= STARTUP_DEADLINE_SECONDS:
                return finish("STARTUP_TIMEOUT")
            return finish("STARTING" if service["State"] == "Start Pending"
                          else "WAITING_FOR_FIRST_HEARTBEAT", pending=True)
        heartbeat = timestamp(heartbeat_raw)
        started = timestamp(state["service_started_at"])
        result["heartbeatAgeSeconds"] = (now-heartbeat).total_seconds()
        if heartbeat < boundary or started < boundary:
            return finish("EPOCH_MISMATCH")
        if not born <= started <= heartbeat <= read_at <= now:
            return finish("CLOCK_ANOMALY")
        if (not binding.get("serviceInstanceId") or
                state.get("service_instance_id") != binding["serviceInstanceId"]
                or started != timestamp(binding["serviceStartedAt"])
                or type(binding.get("minimumStateVersion")) is not int
                or binding["minimumStateVersion"] < 1
                or state.get("state_version", 0) < binding["minimumStateVersion"]):
            return finish("RUNTIME_INSTANCE_MISMATCH")
        if service["State"] == "Start Pending":
            return finish("STARTUP_TIMEOUT" if age_since_birth >= STARTUP_DEADLINE_SECONDS
                          else "STARTING", pending=age_since_birth < STARTUP_DEADLINE_SECONDS)
        if now-heartbeat > timedelta(seconds=FRESHNESS_SECONDS):
            return finish("STALE")
        return finish("HEALTHY", ready=True)
    except (StateRecoveryError, ValueError, TypeError, KeyError, OverflowError):
        return finish("UNKNOWN")


def wait_for_heartbeat(observe: Callable[[], dict], *, poll_interval_seconds: float,
                       startup_elapsed_seconds: float = 0,
                       monotonic: Callable[[], float] = time.monotonic,
                       pause: Callable[[float], None] = time.sleep) -> dict:
    """Wait for two advancing real observations, never for a fixed hopeful sleep.

    The caller owns SCM/process birth verification and immutable observation
    receipts. This helper has no service-control or heartbeat-write capability.
    """
    if (type(poll_interval_seconds) not in (float, int)
            or not math.isfinite(poll_interval_seconds)
            or not 0.25 <= poll_interval_seconds <= 60):
        raise ValueError("INVALID_POLL_INTERVAL")
    if (type(startup_elapsed_seconds) not in (float, int)
            or not math.isfinite(startup_elapsed_seconds) or startup_elapsed_seconds < 0):
        raise ValueError("INVALID_STARTUP_ELAPSED")
    remaining = max(0, STARTUP_DEADLINE_SECONDS-startup_elapsed_seconds)
    started = monotonic()
    if not math.isfinite(started):
        raise ValueError("INVALID_MONOTONIC_CLOCK")
    previous_clock = started
    first = None
    previous_healthy = None
    observations = []
    # The iteration ceiling also prevents a broken injected monotonic clock from
    # making the wait unbounded. Callers must bound each OS/state observation.
    interval = min(1.0, poll_interval_seconds)
    limit = math.ceil(remaining / interval) + 1
    for _ in range(limit):
        before = monotonic()
        if (not math.isfinite(before) or before < previous_clock
                or observations and before == previous_clock):
            return {"status": "RED_NOT_READY", "reason": "CLOCK_ANOMALY", "observations": observations}
        if before-started >= remaining:
            break
        value = observe()
        after = monotonic()
        observations.append(value)
        if not math.isfinite(after) or after < before:
            return {"status": "RED_NOT_READY", "reason": "CLOCK_ANOMALY", "observations": observations}
        previous_clock = after
        if after-started >= remaining:
            break
        if value.get("ready") is True and value.get("state") == "HEALTHY":
            try:
                if (not isinstance(value.get("serviceInstanceId"), str) or not value["serviceInstanceId"]
                        or type(value.get("stateVersion")) is not int or value["stateVersion"] < 1
                        or timestamp(value["heartbeatAt"]) < timestamp(value["serviceStartedAt"])):
                    raise ValueError("INVALID_OBSERVATION")
            except (KeyError, ValueError, TypeError, StateRecoveryError):
                return {"status": "RED_NOT_READY", "reason": "INVALID_OBSERVATION", "observations": observations}
            if previous_healthy is not None:
                old_version, new_version = previous_healthy["stateVersion"], value["stateVersion"]
                old_heartbeat = timestamp(previous_healthy["heartbeatAt"])
                new_heartbeat = timestamp(value["heartbeatAt"])
                if (new_version < old_version or new_heartbeat < old_heartbeat
                        or new_version == old_version and new_heartbeat != old_heartbeat):
                    return {"status": "RED_NOT_READY", "reason": "HEARTBEAT_GENERATION_REGRESSION",
                            "observations": observations}
            previous_healthy = value
            if first is None:
                first = value
            else:
                try:
                    same = all(value.get(k) == first.get(k) for k in ("serviceInstanceId", "serviceStartedAt"))
                    advanced = (value["stateVersion"] > first["stateVersion"]
                                and timestamp(value["heartbeatAt"]) > timestamp(first["heartbeatAt"]))
                    if not same:
                        return {"status": "RED_NOT_READY", "reason": "RUNTIME_INSTANCE_MISMATCH", "observations": observations}
                    if advanced:
                        return {"status": "HEARTBEAT_ADVANCEMENT_PROVEN", "observations": observations}
                except (KeyError, TypeError, StateRecoveryError):
                    return {"status": "RED_NOT_READY", "reason": "INVALID_OBSERVATION", "observations": observations}
        elif not (first is None and value.get("pending") is True
                  and value.get("state") in {"STARTING", "WAITING_FOR_FIRST_HEARTBEAT"}):
            return {"status": "RED_NOT_READY", "reason": value.get("state", "UNKNOWN"), "observations": observations}
        pause(min(interval, remaining-(after-started)))
    return {"status": "RED_NOT_READY", "reason": "STARTUP_TIMEOUT", "observations": observations}
