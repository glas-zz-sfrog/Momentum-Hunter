from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from momentum_hunter.active_monitor import ACTIVE_MONITOR_STATUS_PATH
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.time_utils import now_central


ACTIVE_MONITOR_RUNNER_PATH = DATA_DIR / "active-monitor-runner.json"
DEFAULT_BACKGROUND_CYCLES = 1_000_000
DEFAULT_BACKGROUND_INTERVAL_SECONDS = 300


@dataclass(frozen=True)
class ActiveMonitorRunnerState:
    state: str
    pid: int
    started_at: str
    updated_at: str
    command: list[str] = field(default_factory=list)
    interval_seconds: int = DEFAULT_BACKGROUND_INTERVAL_SECONDS
    cycles: int = DEFAULT_BACKGROUND_CYCLES
    fetch_missing_market_data: bool = False
    refresh_target_market_data: bool = False
    status_path: str = ""
    last_error: str = ""


def build_active_monitor_command(
    *,
    python_executable: str | None = None,
    cycles: int = DEFAULT_BACKGROUND_CYCLES,
    interval_seconds: int = DEFAULT_BACKGROUND_INTERVAL_SECONDS,
    fetch_missing_market_data: bool = False,
    refresh_target_market_data: bool = False,
    status_path: Path = ACTIVE_MONITOR_STATUS_PATH,
) -> list[str]:
    command = [
        python_executable or sys.executable,
        "-m",
        "momentum_hunter.active_monitor",
        "--cycles",
        str(max(1, cycles)),
        "--interval-seconds",
        str(max(1, interval_seconds)),
        "--status-path",
        str(status_path),
    ]
    if fetch_missing_market_data:
        command.append("--fetch-missing-market-data")
    if refresh_target_market_data:
        command.append("--refresh-target-market-data")
    return command


def start_active_monitor_background(
    *,
    cycles: int = DEFAULT_BACKGROUND_CYCLES,
    interval_seconds: int = DEFAULT_BACKGROUND_INTERVAL_SECONDS,
    fetch_missing_market_data: bool = False,
    refresh_target_market_data: bool = False,
    status_path: Path = ACTIVE_MONITOR_STATUS_PATH,
    runner_path: Path = ACTIVE_MONITOR_RUNNER_PATH,
    python_executable: str | None = None,
    popen_factory=subprocess.Popen,
    process_checker=None,
) -> ActiveMonitorRunnerState:
    process_checker = process_checker or process_is_running
    existing = load_active_monitor_runner_state(runner_path)
    if existing and existing.state == "RUNNING" and process_checker(existing.pid):
        return existing

    command = build_active_monitor_command(
        python_executable=python_executable,
        cycles=cycles,
        interval_seconds=interval_seconds,
        fetch_missing_market_data=fetch_missing_market_data,
        refresh_target_market_data=refresh_target_market_data,
        status_path=status_path,
    )
    kwargs = {
        "cwd": str(Path(__file__).resolve().parents[1]),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        process = popen_factory(command, **kwargs)
    except Exception as exc:
        failed = ActiveMonitorRunnerState(
            state="FAILED",
            pid=0,
            started_at=now_central().isoformat(),
            updated_at=now_central().isoformat(),
            command=command,
            interval_seconds=max(1, interval_seconds),
            cycles=max(1, cycles),
            fetch_missing_market_data=fetch_missing_market_data,
            refresh_target_market_data=refresh_target_market_data,
            status_path=str(status_path),
            last_error=f"{type(exc).__name__}: {exc}",
        )
        save_active_monitor_runner_state(failed, runner_path)
        raise

    state = ActiveMonitorRunnerState(
        state="RUNNING",
        pid=int(process.pid),
        started_at=now_central().isoformat(),
        updated_at=now_central().isoformat(),
        command=command,
        interval_seconds=max(1, interval_seconds),
        cycles=max(1, cycles),
        fetch_missing_market_data=fetch_missing_market_data,
        refresh_target_market_data=refresh_target_market_data,
        status_path=str(status_path),
    )
    save_active_monitor_runner_state(state, runner_path)
    return state


def stop_active_monitor_background(
    *,
    runner_path: Path = ACTIVE_MONITOR_RUNNER_PATH,
    process_checker=None,
    terminator=None,
) -> ActiveMonitorRunnerState:
    process_checker = process_checker or process_is_running
    terminator = terminator or terminate_process_tree
    existing = load_active_monitor_runner_state(runner_path)
    if not existing:
        state = ActiveMonitorRunnerState(
            state="STOPPED",
            pid=0,
            started_at="",
            updated_at=now_central().isoformat(),
            last_error="No active monitor runner state found.",
        )
        save_active_monitor_runner_state(state, runner_path)
        return state

    error = ""
    if existing.pid and process_checker(existing.pid):
        try:
            terminator(existing.pid)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    state = ActiveMonitorRunnerState(
        state="FAILED" if error else "STOPPED",
        pid=existing.pid,
        started_at=existing.started_at,
        updated_at=now_central().isoformat(),
        command=existing.command,
        interval_seconds=existing.interval_seconds,
        cycles=existing.cycles,
        fetch_missing_market_data=existing.fetch_missing_market_data,
        refresh_target_market_data=existing.refresh_target_market_data,
        status_path=existing.status_path,
        last_error=error,
    )
    save_active_monitor_runner_state(state, runner_path)
    return state


def load_active_monitor_runner_state(path: Path = ACTIVE_MONITOR_RUNNER_PATH) -> ActiveMonitorRunnerState | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return runner_state_from_dict(payload)


def save_active_monitor_runner_state(state: ActiveMonitorRunnerState, path: Path = ACTIVE_MONITOR_RUNNER_PATH) -> Path:
    ensure_app_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    return path


def runner_state_from_dict(payload: dict) -> ActiveMonitorRunnerState:
    return ActiveMonitorRunnerState(
        state=str(payload.get("state", "")),
        pid=parse_int(payload.get("pid")),
        started_at=str(payload.get("started_at", "")),
        updated_at=str(payload.get("updated_at", "")),
        command=[str(item) for item in payload.get("command", [])] if isinstance(payload.get("command"), list) else [],
        interval_seconds=parse_int(payload.get("interval_seconds"), default=DEFAULT_BACKGROUND_INTERVAL_SECONDS),
        cycles=parse_int(payload.get("cycles"), default=DEFAULT_BACKGROUND_CYCLES),
        fetch_missing_market_data=bool(payload.get("fetch_missing_market_data", False)),
        refresh_target_market_data=bool(payload.get("refresh_target_market_data", False)),
        status_path=str(payload.get("status_path", "")),
        last_error=str(payload.get("last_error", "")),
    )


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def windows_process_is_running(pid: int) -> bool:
    try:
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def terminate_process_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.kill(pid, signal.SIGTERM)


def parse_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
