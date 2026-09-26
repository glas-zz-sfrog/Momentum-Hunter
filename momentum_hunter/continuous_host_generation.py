"""Observed process generations and ordered drain barriers for the existing host."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import uuid

from momentum_hunter.continuous_host_contract import canonical_bytes, SCM_DIRECT, science_custody_policy


def _drain_observation_value(value, *, text_limit=64):
    """Bound diagnostic retention only; predicates still receive the original value."""
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        return value if len(value) <= text_limit else {"type": "str", "characters": len(value), "omitted": True}
    if type(value) is int and -(1 << 63) <= value < (1 << 64):
        return value
    return {"type": type(value).__name__[:64], "omitted": True}


class _ProcessEntry32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def _process_absent_from_snapshot(kernel, pid, *, observation=None):
    """Prove absence from one complete native snapshot, never from a query denial."""
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32)]
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.restype = wintypes.BOOL
    detail = {"complete": False, "count": 0, "targetPresent": False, "selfPresent": False}
    handle = kernel.CreateToolhelp32Snapshot(0x2, 0)
    if not handle or handle == ctypes.c_void_p(-1).value:
        detail.update(operation="CreateToolhelp32Snapshot", winerror=ctypes.get_last_error())
        if observation is not None:
            observation.update(detail)
        return False
    seen = set()
    try:
        entry = _ProcessEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel.Process32FirstW(handle, ctypes.byref(entry)):
            detail.update(operation="Process32FirstW", winerror=ctypes.get_last_error())
        else:
            while True:
                if entry.dwSize != ctypes.sizeof(entry) or entry.th32ProcessID in seen:
                    detail.update(operation="SNAPSHOT_ENTRY_INVALID", winerror=None)
                    break
                seen.add(entry.th32ProcessID)
                if len(seen) >= 65536:
                    detail.update(operation="SNAPSHOT_BOUND", winerror=None)
                    break
                ctypes.set_last_error(0)
                if not kernel.Process32NextW(handle, ctypes.byref(entry)):
                    error = ctypes.get_last_error()
                    detail.update(operation="Process32NextW", winerror=error, complete=error == 18)
                    break
    finally:
        closed = bool(kernel.CloseHandle(handle))
        detail.update(count=len(seen), targetPresent=pid in seen, selfPresent=os.getpid() in seen,
                      handleClosed=closed)
        if observation is not None:
            observation.update(detail)
    return bool(detail["complete"] and detail["selfPresent"] and not detail["targetPresent"] and closed)


def process_lifetime(pid: int, birth: int, *, observation: dict | None = None) -> str:
    """Query denial alone is UNKNOWN; a complete native snapshot can prove exit."""
    def result(state, operation, error=None):
        if observation is not None:
            observation.update(pid=_drain_observation_value(pid), birth=_drain_observation_value(birth), requestedAccess=0x1000,
                               state=state, operation=operation, winerror=error)
        return state

    if os.name != "nt" or type(pid) is not int or pid <= 0 or type(birth) is not int or birth <= 0:
        return result("UNKNOWN", "INPUT_VALIDATION")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 5:
            detail = {} if observation is not None else None
            absent = _process_absent_from_snapshot(kernel, pid, observation=detail)
            if observation is not None:
                observation["exitSnapshot"] = detail
            if absent:
                return result("EXITED", "COMPLETE_PROCESS_SNAPSHOT_ABSENCE", error)
        return result("EXITED" if error == 87 else "UNKNOWN", "OpenProcess", error)
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        code = wintypes.DWORD()
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            return result("UNKNOWN", "GetProcessTimes", ctypes.get_last_error())
        actual = times[0].dwLowDateTime | (times[0].dwHighDateTime << 32)
        if observation is not None:
            observation["actualBirth"] = actual
        if actual != birth:
            return result("EXITED_PID_RECYCLED", "GetProcessTimes")
        if times[1].dwLowDateTime or times[1].dwHighDateTime:
            return result("EXITED", "GetProcessTimes")
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return result("UNKNOWN", "GetExitCodeProcess", ctypes.get_last_error())
        if observation is not None:
            observation["exitCode"] = code.value
        return result("ALIVE" if code.value == 259 else "EXITED", "GetExitCodeProcess")
    finally:
        kernel.CloseHandle(handle)


def process_birth(pid: int) -> int | None:
    """Query only process lifetime metadata; a recycled PID never matches."""
    if os.name != "nt" or type(pid) is not int or pid <= 0:
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
            return None
        return times[0].dwLowDateTime | (times[0].dwHighDateTime << 32)
    finally:
        kernel.CloseHandle(handle)


def replace_status(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("xb") as output:
        output.write(canonical_bytes(payload))
        output.flush()
        os.fsync(output.fileno())
    deadline = time.monotonic() + 0.5
    while True:
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def read_record(path: Path, *, observation: dict | None = None) -> dict:
    if observation is not None:
        observation["path"] = _drain_observation_value(str(path), text_limit=4096)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        if observation is not None:
            observation["state"] = "READ_OBJECT" if isinstance(result, dict) else "NOT_OBJECT"
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError) as exc:
        if observation is not None:
            observation.update(state="READ_FAILED", exception=type(exc).__name__,
                               winerror=getattr(exc, "winerror", None), errno=getattr(exc, "errno", None))
        return {}


def generation_path(config, role):
    return Path(config["hostStateRoot"]) / role / "generation.json"


def status_path(config, role):
    return Path(config["logRoot"]) / role / "status.json"


def current_generation(config, role, *, require_running=True):
    value = read_record(generation_path(config, role))
    if value.get("hostFingerprint") != config["hostFingerprint"] or value.get("role") != role:
        return None
    try:
        if str(uuid.UUID(value["generation"])) != value["generation"]:
            return None
        if value.get("executionModel") == SCM_DIRECT:
            if role != "science" or config["host"]["science"].get("hostingModel") != SCM_DIRECT:
                return None
            if any(key in value for key in ("supervisorPid", "supervisorBirth", "childPid", "childBirth")):
                return None
            if any(type(value.get(key)) is not int or value[key] <= 0 for key in ("servicePid", "serviceBirth")):
                return None
            if process_lifetime(value["servicePid"], value["serviceBirth"]) != "ALIVE":
                return None
            if require_running and value.get("phase") != "RUNNING":
                return None
            return value
        if role == "science" and config["host"]["science"].get("hostingModel") == SCM_DIRECT:
            return None
        if any(type(value.get(key)) is not int or value[key] <= 0
               for key in ("supervisorPid", "supervisorBirth", "childPid", "childBirth")):
            return None
        if process_birth(value["supervisorPid"]) != value["supervisorBirth"]:
            return None
        if require_running and (value["phase"] != "RUNNING" or
                                process_birth(value["childPid"]) != value["childBirth"]):
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return value


def generation_vector(config):
    return {role: (current_generation(config, role) or {}).get("generation")
            for role in ("writer", "runtime", "science")}


def aggregate_health(config):
    """A reporting boundary only; never a Science -> Engine eligibility input."""
    vector = generation_vector(config)
    policy = science_custody_policy(config)
    results = {}
    for role, generation in vector.items():
        status = read_record(status_path(config, role))
        valid = bool(generation and status.get("generation") == generation and
                     status.get("hostFingerprint") == config["hostFingerprint"])
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(status["observedAt"])).total_seconds()
            valid = valid and 0 <= age <= 30
        except (KeyError, TypeError, ValueError):
            valid = False
        ready = valid and status.get("state") == {"writer": "LISTENING", "runtime": "RUNNING", "science": "HEALTHY"}[role]
        if role == "runtime":
            ready = ready and status.get("v2Ready") is True
        if role == "writer" and policy is not None:
            custody = status.get("scienceCustody") or {}
            ready = ready and custody.get("state") in ("READY", "POLLING")
            ready = ready and custody.get("threadAlive") is True and custody.get("stopRequested") is False
        if role == "science":
            ready = ready and status.get("dependencies") == {key: vector[key] for key in ("writer", "runtime")}
            ready = ready and not status.get("auditRequired")
            custody = status.get("custodyBoundary") or {}
            ready = ready and policy is not None and custody.get("policySha256") == policy.policy_sha256
            ready = ready and custody.get("role") == "science" and custody.get("exactOwnerDaclLabelPolicyVerified") is True
        results[role] = {"ready": bool(ready), "state": status.get("state", "UNAVAILABLE") if valid else "STALE_OR_UNAVAILABLE"}
    return {"ready": all(row["ready"] for row in results.values()), "generations": vector, "components": results}


def completion(config, role, *, observation: dict | None = None):
    """Accept a bound drain receipt only after the matching process has exited."""
    def read(path):
        if observation is None:
            return read_record(path)
        detail = {}
        observation.setdefault("reads", []).append(detail)
        return read_record(path, observation=detail)

    generation = read(generation_path(config, role))
    value = read(Path(config["hostStateRoot"]) / role / "completion.json")
    if observation is not None:
        observation.update(role=role, generation=_drain_observation_value(generation.get("generation")),
                           completionGeneration=_drain_observation_value(value.get("generation")),
                           phase=_drain_observation_value(generation.get("phase")))
    try:
        if str(uuid.UUID(generation["generation"])) != generation["generation"]:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    upstream = {key: read(generation_path(config, key)).get("generation")
                for key in {"runtime": ("writer",), "science": ("writer", "runtime"), "writer": ()}[role]}
    def lifetime():
        if observation is None:
            return process_lifetime(generation.get("servicePid"), generation.get("serviceBirth"))
        detail = observation["processLifetime"] = {}
        return process_lifetime(generation.get("servicePid"), generation.get("serviceBirth"), observation=detail)

    exited = generation.get("phase") == "EXITED"
    if role == "science" and config["host"]["science"].get("hostingModel") == SCM_DIRECT:
        exited = bool(generation.get("executionModel") == SCM_DIRECT and
            generation.get("role") == role and value.get("role") == role and
            not any(key in record for record in (generation, value)
                    for key in ("supervisorPid", "supervisorBirth", "childPid", "childBirth")) and
            generation.get("phase") == "RETURNED_PENDING_SERVICE_EXIT" and
            value.get("executionModel") == SCM_DIRECT and
            value.get("servicePid") == generation.get("servicePid") and
            value.get("serviceBirth") == generation.get("serviceBirth") and
            lifetime() in ("EXITED", "EXITED_PID_RECYCLED"))
    return bool(all(upstream.values()) and value.get("dependencies") == upstream and
                generation.get("hostFingerprint") == config["hostFingerprint"] and
                exited and value.get("generation") == generation.get("generation") and
                value.get("hostFingerprint") == config["hostFingerprint"] and
                value.get("exitCode") == 0 and value.get("drainComplete") is True and
                value.get("cleanupComplete") is True and value.get("pendingWork") == 0 and
                not value.get("publicationFailure"))


def dependencies_drained(config, role, *, observation: dict | None = None):
    def check(dependency):
        if observation is None:
            return completion(config, dependency)
        detail = observation[dependency] = {}
        accepted = completion(config, dependency, observation=detail)
        detail["accepted"] = accepted
        return accepted

    return all(check(dependency) for dependency in
               {"runtime": (), "science": ("runtime",), "writer": ("runtime", "science")}[role])


class HostGeneration:
    def __init__(self, config, role, generation):
        self.config, self.role, self.generation = config, role, generation
        self.enabled = config.get("schemaVersion") == 2
        if not self.enabled:
            return
        deadline = time.monotonic() + 5
        while True:
            parent = current_generation(config, role)
            identity_key = "servicePid" if parent and parent.get("executionModel") == SCM_DIRECT else "childPid"
            if parent and parent["generation"] == generation and parent[identity_key] == os.getpid():
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("CURRENT_SUPERVISOR_GENERATION_NOT_BOUND")
            time.sleep(0.02)

    def status(self, state, **detail):
        if self.enabled:
            replace_status(status_path(self.config, self.role), {"hostFingerprint": self.config["hostFingerprint"],
                "generation": self.generation, "role": self.role, "pid": os.getpid(),
                "observedAt": datetime.now(timezone.utc).isoformat(), "state": state, **detail})

    def wait_for_dependencies(self, stop_deadline, *, tick=lambda: None):
        if not self.enabled:
            return True
        while not dependencies_drained(self.config, self.role):
            if time.monotonic() >= stop_deadline:
                self.status("INCOMPLETE", drainComplete=False, reason="DEPENDENCY_DRAIN_TIMEOUT")
                return False
            tick()
            time.sleep(0.05)
        return True
