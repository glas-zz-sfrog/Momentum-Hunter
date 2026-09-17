"""Fixed in-process SCM bridge; canonical Science still owns all custody semantics."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import traceback

from momentum_hunter.continuous_host_contract import OfflineNetworkGuard, OFFLINE, SCM_DIRECT, scrub_provider_environment


class NativeStopEvent:
    def __init__(self, handle: int):
        if type(handle) is not int or handle <= 0:
            raise ValueError("IN_PROCESS_STOP_HANDLE_REQUIRED")
        self.handle = handle
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD

    def is_set(self):
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result not in (0, 258):
            raise OSError("IN_PROCESS_STOP_HANDLE_QUERY_FAILED")
        return result == 0


def run(config_path: str, generation: str, stop_handle: int) -> int:
    scrub_provider_environment()
    guard = OfflineNetworkGuard("", 0, "science")
    guard.install()
    # No provider/runtime module is imported until the unconditional Science
    # network denial is active. This is process-local auditing, not a firewall.
    from momentum_hunter.continuous_production import _read_config
    from momentum_hunter.continuous_host_generation import HostGeneration
    from momentum_hunter.continuous_host_lifecycle import run_science
    config = _read_config(Path(config_path))
    if config["inputMode"] != OFFLINE or config["host"]["science"]["hostingModel"] != SCM_DIRECT:
        raise ValueError("DIRECT_SCIENCE_MODE_NOT_ADMITTED")
    host = HostGeneration(config, "science", generation)
    try:
        code = run_science(config, NativeStopEvent(stop_handle), host)
    except BaseException as exc:
        _record(config, generation, "bridge-failure", {
            "exception": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc(),
        })
        raise
    finally:
        _record(config, generation, "network", {"deniedAttempts": guard.denied_attempts,
            "scope": "SECONDARY_PYTHON_AUDIT_GUARD_NOT_NATIVE_NETWORK_ISOLATION",
            "primaryCounter": "network-bootstrap-" + generation + ".json"})
    return code if guard.denied_attempts == 0 else 2


def _record(config, generation, category, value):
    path = Path(config["logRoot"]) / "science" / (category + "-" + generation + ".json")
    with path.open("x", encoding="ascii") as output:
        json.dump({"generation": generation, **value}, output, ensure_ascii=True)
        output.flush()
        os.fsync(output.fileno())
