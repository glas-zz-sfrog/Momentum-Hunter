from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socketserver
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from momentum_hunter.config import DATA_DIR


PROTOCOL_VERSION = "1.0"
STATE_SCHEMA_VERSION = 1
DEFAULT_COLLECTION_INTERVAL_SECONDS = 300
HOST_LOCK_FILENAME = "python-engine-host.lock"
ENDPOINT_FILENAME = "python-engine-endpoint.json"
MAX_REQUEST_BYTES = 64 * 1024

COMMAND_SNAPSHOT = "get_host_snapshot"
COMMAND_PAUSE = "pause_collection"
COMMAND_RESUME = "resume_collection"
COMMAND_RUN_CYCLE = "run_collection_cycle"
COMMAND_SHUTDOWN = "shutdown_host"
COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT = "get_readonly_workspace_snapshot"
COMMAND_SIMULATION_WORKSPACE_SNAPSHOT = "get_simulation_workspace_snapshot"
COMMAND_CHART_SNAPSHOT = "get_chart_snapshot"
COMMAND_RUN_SIMULATION = "run_simulation"
SUPPORTED_COMMANDS = frozenset(
    {
        COMMAND_SNAPSHOT,
        COMMAND_PAUSE,
        COMMAND_RESUME,
        COMMAND_RUN_CYCLE,
        COMMAND_SHUTDOWN,
        COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT,
        COMMAND_SIMULATION_WORKSPACE_SNAPSHOT,
        COMMAND_CHART_SNAPSHOT,
        COMMAND_RUN_SIMULATION,
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
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
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class EngineHostEndpoint:
    protocol_version: str
    host_instance_id: str
    process_id: int
    started_at_utc: str
    address: str
    port: int
    access_token: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "schemaVersion": STATE_SCHEMA_VERSION,
            "protocolVersion": self.protocol_version,
            "hostInstanceId": self.host_instance_id,
            "processId": self.process_id,
            "startedAtUtc": self.started_at_utc,
            "address": self.address,
            "port": self.port,
            "accessToken": self.access_token,
        }


class HostLease:
    """Atomic, process-owned local lease for one Python Engine Host instance."""

    def __init__(self, path: Path, host_instance_id: str, *, process_id: int | None = None) -> None:
        self.path = path
        self.host_instance_id = host_instance_id
        self.process_id = process_id or os.getpid()
        self._owned = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(3):
            try:
                descriptor = json.dumps(
                    {
                        "hostInstanceId": self.host_instance_id,
                        "processId": self.process_id,
                        "createdAtUtc": utc_now(),
                    }
                ).encode("utf-8")
                descriptor_fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(descriptor_fd, descriptor)
                    os.fsync(descriptor_fd)
                finally:
                    os.close(descriptor_fd)
                self._owned = True
                return True
            except FileExistsError:
                existing = read_json(self.path)
                existing_pid = int(existing.get("processId", 0)) if existing else 0
                if existing and process_is_running(existing_pid):
                    return False

                # A just-created lock may briefly be unreadable while its owner writes it.
                try:
                    age_seconds = time.time() - self.path.stat().st_mtime
                except OSError:
                    continue
                if existing is None and age_seconds < 3:
                    return False
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    continue
                except OSError:
                    return False
        return False

    def release(self) -> None:
        if not self._owned:
            return
        existing = read_json(self.path)
        if existing and existing.get("hostInstanceId") == self.host_instance_id:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self._owned = False


@dataclass(frozen=True)
class EngineHostCommandResult:
    accepted: bool
    code: str
    summary: str
    snapshot: dict[str, Any]
    shutdown_requested: bool = False
    payload: dict[str, Any] | None = None

    def to_wire(self, request_id: str) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "requestId": request_id,
            "accepted": self.accepted,
            "error": None if self.accepted else {"code": self.code, "summary": self.summary},
            "result": {
                "code": self.code,
                "summary": self.summary,
                "snapshot": self.snapshot,
                "payload": self.payload,
            },
        }


class EngineHostRuntime:
    """Owns the host lifecycle and one canonical collection loop without any execution authority."""

    def __init__(
        self,
        *,
        host_instance_id: str | None = None,
        collection_interval_seconds: int = DEFAULT_COLLECTION_INTERVAL_SECONDS,
        cycle_runner: Callable[[], Any] | None = None,
        external_monitor_running: Callable[[], bool] | None = None,
        workspace_snapshot_loader: Callable[[], dict[str, Any]] | None = None,
        simulation_workspace_loader: Callable[[], dict[str, Any]] | None = None,
        simulation_runner: Callable[[str], dict[str, Any]] | None = None,
        chart_snapshot_loader: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.host_instance_id = host_instance_id or uuid.uuid4().hex
        self.started_at_utc = utc_now()
        self.collection_interval_seconds = max(1, int(collection_interval_seconds))
        self._cycle_runner = cycle_runner or self._run_canonical_monitor_cycle
        self._external_monitor_running = external_monitor_running or self._is_legacy_monitor_runner_active
        self._workspace_snapshot_loader = workspace_snapshot_loader or self._load_read_only_workspace_snapshot
        self._simulation_workspace_service = None
        if simulation_workspace_loader is None or simulation_runner is None:
            from momentum_hunter.workstation_simulation import SimulationWorkspaceService

            self._simulation_workspace_service = SimulationWorkspaceService()
        self._simulation_workspace_loader = simulation_workspace_loader or self._simulation_workspace_service.snapshot
        self._simulation_runner = simulation_runner or self._simulation_workspace_service.run_simulation
        if chart_snapshot_loader is None:
            from momentum_hunter.workstation_charts import WorkstationChartService

            self._chart_service = WorkstationChartService()
        else:
            self._chart_service = None
        self._chart_snapshot_loader = chart_snapshot_loader or self._chart_service.snapshot
        self._state_lock = threading.RLock()
        self._command_condition = threading.Condition(self._state_lock)
        self._cycle_lock = threading.Lock()
        self._stop_requested = threading.Event()
        self._schedule_changed = threading.Event()
        self._collection_thread: threading.Thread | None = None
        self._command_receipts: dict[str, EngineHostCommandResult] = {}
        self._command_receipt_requests: dict[str, tuple[str, str]] = {}
        self._commands_in_progress: set[str] = set()
        self._paused = False
        self._stopping = False
        self._cycle_in_progress = False
        self._cycle_count = 0
        self._monitored_symbol_count = 0
        self._last_completed_cycle_at_utc = ""
        self._next_scheduled_cycle_at_utc = ""
        self._detail = "Python Engine Host is ready; collection is scheduled locally."
        self._state = "Healthy"

    def start_collection_loop(self) -> None:
        with self._state_lock:
            if self._collection_thread and self._collection_thread.is_alive():
                return
            self._set_next_scheduled_locked()
            self._collection_thread = threading.Thread(
                target=self._collection_loop,
                name="momentum-hunter-collection",
                daemon=True,
            )
            self._collection_thread.start()

    def request_shutdown(self) -> None:
        with self._state_lock:
            self._stopping = True
            self._state = "Stopping"
            self._detail = "Python Engine Host is shutting down deliberately."
            self._next_scheduled_cycle_at_utc = ""
        self._stop_requested.set()
        self._schedule_changed.set()

    def close(self) -> None:
        self.request_shutdown()
        if self._collection_thread and self._collection_thread.is_alive():
            self._collection_thread.join(timeout=5)

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "schemaVersion": STATE_SCHEMA_VERSION,
                "identity": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "hostInstanceId": self.host_instance_id,
                    "processId": os.getpid(),
                    "startedAtUtc": self.started_at_utc,
                    "transport": "loopback-tcp",
                },
                "health": {
                    "state": self._state,
                    "observedAtUtc": utc_now(),
                    "detail": self._detail,
                },
                "collection": {
                    "state": self._state,
                    "isPaused": self._paused,
                    "cycleInProgress": self._cycle_in_progress,
                    "cycleCount": self._cycle_count,
                    "monitoredSymbolCount": self._monitored_symbol_count,
                    "lastCompletedCycleAtUtc": self._last_completed_cycle_at_utc or None,
                    "nextScheduledCycleAtUtc": self._next_scheduled_cycle_at_utc or None,
                    "detail": self._detail,
                },
                "capabilities": sorted(SUPPORTED_COMMANDS),
            }

    def execute(
        self,
        command: str,
        command_id: str,
        arguments: dict[str, Any] | None = None,
    ) -> EngineHostCommandResult:
        if not command_id.strip():
            return EngineHostCommandResult(False, "COMMAND_ID_REQUIRED", "A stable command ID is required.", self.snapshot())
        if command not in SUPPORTED_COMMANDS:
            return EngineHostCommandResult(False, "UNSUPPORTED_COMMAND", "The requested host command is unavailable.", self.snapshot())
        if arguments is not None and not isinstance(arguments, dict):
            return EngineHostCommandResult(False, "INVALID_COMMAND_ARGUMENTS", "Host command arguments must be an object.", self.snapshot())
        normalized_arguments = dict(arguments or {})
        request_key = (command, json.dumps(normalized_arguments, sort_keys=True, separators=(",", ":")))

        with self._command_condition:
            while command_id in self._commands_in_progress:
                self._command_condition.wait()
            cached = self._command_receipts.get(command_id)
            if cached is not None:
                if self._command_receipt_requests.get(command_id) != request_key:
                    return EngineHostCommandResult(
                        False,
                        "COMMAND_ID_REUSED",
                        "A command ID cannot be reused with a different command or argument set.",
                        self.snapshot(),
                    )
                return cached
            self._commands_in_progress.add(command_id)

        try:
            result = self._execute_once(command, normalized_arguments)
        except Exception:
            result = EngineHostCommandResult(
                False,
                "HOST_COMMAND_FAILED",
                "The Python Engine Host could not complete the requested command.",
                self.snapshot(),
            )
        finally:
            with self._command_condition:
                if "result" in locals():
                    self._command_receipts[command_id] = result
                    self._command_receipt_requests[command_id] = request_key
                self._commands_in_progress.discard(command_id)
                self._command_condition.notify_all()
        return result

    def _execute_once(self, command: str, arguments: dict[str, Any]) -> EngineHostCommandResult:
        if command == COMMAND_SNAPSHOT:
            return EngineHostCommandResult(True, "SNAPSHOT", "Host snapshot returned.", self.snapshot())
        if command == COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT:
            payload = self._workspace_snapshot_loader()
            return EngineHostCommandResult(
                True,
                "READ_ONLY_WORKSPACE_SNAPSHOT",
                "Read-only workstation snapshot returned.",
                self.snapshot(),
                payload=payload,
            )
        if command == COMMAND_SIMULATION_WORKSPACE_SNAPSHOT:
            payload = self._simulation_workspace_loader()
            return EngineHostCommandResult(
                True,
                "SIMULATION_WORKSPACE_SNAPSHOT",
                "Simulation workspace snapshot returned.",
                self.snapshot(),
                payload=payload,
            )
        if command == COMMAND_CHART_SNAPSHOT:
            symbol = arguments.get("symbol")
            interval = arguments.get("interval")
            if not isinstance(symbol, str) or not symbol.strip():
                return EngineHostCommandResult(
                    False,
                    "CHART_SYMBOL_REQUIRED",
                    "A non-empty symbol is required for a chart snapshot.",
                    self.snapshot(),
                )
            if not isinstance(interval, str) or not interval.strip():
                return EngineHostCommandResult(
                    False,
                    "CHART_INTERVAL_REQUIRED",
                    "A supported interval is required for a chart snapshot.",
                    self.snapshot(),
                )
            try:
                payload = self._chart_snapshot_loader(symbol, interval)
            except ValueError as exc:
                return EngineHostCommandResult(
                    False,
                    "INVALID_CHART_REQUEST",
                    str(exc),
                    self.snapshot(),
                )
            return EngineHostCommandResult(
                True,
                "CHART_SNAPSHOT",
                "Read-only chart snapshot returned.",
                self.snapshot(),
                payload=payload,
            )
        if command == COMMAND_RUN_SIMULATION:
            symbol = arguments.get("symbol")
            if not isinstance(symbol, str) or not symbol.strip():
                return EngineHostCommandResult(
                    False,
                    "SIMULATION_SYMBOL_REQUIRED",
                    "A non-empty symbol is required for FakeBroker simulation.",
                    self.snapshot(),
                )
            payload = self._simulation_runner(symbol.strip().upper())
            return EngineHostCommandResult(
                True,
                "SIMULATION_COMPLETED",
                "Simulation command completed through the FakeBroker-only boundary.",
                self.snapshot(),
                payload=payload,
            )
        if command == COMMAND_PAUSE:
            with self._state_lock:
                if self._stopping:
                    return EngineHostCommandResult(False, "HOST_STOPPING", "The host is shutting down.", self.snapshot())
                self._paused = True
                self._state = "Paused"
                self._detail = "Background collection is paused by operator request."
                self._next_scheduled_cycle_at_utc = ""
                self._schedule_changed.set()
            return EngineHostCommandResult(True, "PAUSED", "Background collection paused.", self.snapshot())
        if command == COMMAND_RESUME:
            with self._state_lock:
                if self._stopping:
                    return EngineHostCommandResult(False, "HOST_STOPPING", "The host is shutting down.", self.snapshot())
                self._paused = False
                self._state = "Healthy"
                self._detail = "Background collection resumed."
                self._set_next_scheduled_locked()
                self._schedule_changed.set()
            return EngineHostCommandResult(True, "RESUMED", "Background collection resumed.", self.snapshot())
        if command == COMMAND_RUN_CYCLE:
            return self._run_collection_cycle()
        if command == COMMAND_SHUTDOWN:
            self.request_shutdown()
            return EngineHostCommandResult(True, "SHUTDOWN_REQUESTED", "Python Engine Host shutdown requested.", self.snapshot(), True)
        return EngineHostCommandResult(False, "UNSUPPORTED_COMMAND", "The requested host command is unavailable.", self.snapshot())

    def _collection_loop(self) -> None:
        while not self._stop_requested.is_set():
            if self._schedule_changed.wait(self.collection_interval_seconds):
                self._schedule_changed.clear()
                continue
            with self._state_lock:
                if self._paused or self._stopping:
                    continue
            self._run_collection_cycle()

    def _run_collection_cycle(self) -> EngineHostCommandResult:
        with self._state_lock:
            if self._stopping:
                return EngineHostCommandResult(False, "HOST_STOPPING", "The host is shutting down.", self.snapshot())
            if self._paused:
                return EngineHostCommandResult(False, "COLLECTION_PAUSED", "Background collection is paused.", self.snapshot())
        if self._external_monitor_running():
            with self._state_lock:
                self._state = "Blocked"
                self._detail = "An existing active monitor runner is already collecting; the Python Engine Host will not start a duplicate loop."
                self._set_next_scheduled_locked()
                self._schedule_changed.set()
            return EngineHostCommandResult(
                False,
                "EXISTING_MONITOR_RUNNER_ACTIVE",
                "An existing active monitor runner is already collecting.",
                self.snapshot(),
            )
        if not self._cycle_lock.acquire(blocking=False):
            return EngineHostCommandResult(False, "COLLECTION_IN_PROGRESS", "A collection cycle is already running.", self.snapshot())

        try:
            with self._state_lock:
                self._cycle_in_progress = True
                self._state = "Healthy"
                self._detail = "Background collection cycle is running."
            report = self._cycle_runner()
            monitored_count = int(getattr(report, "target_count", 0))
            with self._state_lock:
                self._cycle_in_progress = False
                self._cycle_count += 1
                self._monitored_symbol_count = max(0, monitored_count)
                self._last_completed_cycle_at_utc = utc_now()
                self._state = "Healthy"
                self._detail = "Background collection cycle completed."
                self._set_next_scheduled_locked()
                self._schedule_changed.set()
            return EngineHostCommandResult(True, "COLLECTION_COMPLETED", "Background collection cycle completed.", self.snapshot())
        except Exception as exc:
            with self._state_lock:
                self._cycle_in_progress = False
                self._state = "Blocked"
                self._detail = f"Background collection cycle failed: {type(exc).__name__}: {exc}"
                self._set_next_scheduled_locked()
                self._schedule_changed.set()
            return EngineHostCommandResult(False, "COLLECTION_FAILED", self._detail, self.snapshot())
        finally:
            self._cycle_lock.release()

    def _set_next_scheduled_locked(self) -> None:
        if self._paused or self._stopping:
            self._next_scheduled_cycle_at_utc = ""
            return
        next_cycle = datetime.now(timezone.utc).timestamp() + self.collection_interval_seconds
        self._next_scheduled_cycle_at_utc = datetime.fromtimestamp(next_cycle, timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _run_canonical_monitor_cycle() -> Any:
        # Keep all provider-fetch flags false. The existing monitor owns its own reports and data policy.
        from momentum_hunter.active_monitor import run_monitor_cycle

        return run_monitor_cycle()

    @staticmethod
    def _load_read_only_workspace_snapshot() -> dict[str, Any]:
        from momentum_hunter.workstation_read_models import build_read_only_workspace_snapshot

        return build_read_only_workspace_snapshot()

    @staticmethod
    def _is_legacy_monitor_runner_active() -> bool:
        from momentum_hunter.active_monitor_runner import load_active_monitor_runner_state, process_is_running

        state = load_active_monitor_runner_state()
        return bool(state and state.state == "RUNNING" and process_is_running(state.pid))


class EngineHostServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, runtime: EngineHostRuntime, access_token: str) -> None:
        super().__init__(("127.0.0.1", 0), EngineHostRequestHandler)
        self.runtime = runtime
        self.access_token = access_token


class EngineHostRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        request_id = ""
        shutdown_requested = False
        try:
            raw = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if len(raw) > MAX_REQUEST_BYTES:
                response = failure_response(request_id, "REQUEST_TOO_LARGE", "The host request exceeded the local protocol limit.", self.server.runtime.snapshot())
            else:
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Request payload must be an object.")
                request_id = str(payload.get("requestId", ""))
                response, shutdown_requested = self._dispatch(payload, request_id)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            response = failure_response(request_id, "MALFORMED_REQUEST", str(exc), self.server.runtime.snapshot())
        except Exception:
            response = failure_response(request_id, "HOST_REQUEST_FAILED", "The host could not process the request.", self.server.runtime.snapshot())

        self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))
        self.wfile.flush()
        if shutdown_requested:
            threading.Thread(target=self.server.shutdown, name="momentum-hunter-host-stop", daemon=True).start()

    def _dispatch(self, payload: dict[str, Any], request_id: str) -> tuple[dict[str, Any], bool]:
        if payload.get("protocolVersion") != PROTOCOL_VERSION:
            return (
                failure_response(request_id, "PROTOCOL_VERSION_MISMATCH", "The workstation protocol version is unsupported.", self.server.runtime.snapshot()),
                False,
            )
        token = str(payload.get("accessToken", ""))
        if not token or not secrets.compare_digest(token, self.server.access_token):
            return (
                failure_response(request_id, "UNAUTHENTICATED", "The local host token was not accepted.", self.server.runtime.snapshot()),
                False,
            )
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            return (
                failure_response(
                    request_id,
                    "INVALID_COMMAND_ARGUMENTS",
                    "Host command arguments must be an object.",
                    self.server.runtime.snapshot(),
                ),
                False,
            )
        result = self.server.runtime.execute(
            str(payload.get("command", "")),
            str(payload.get("commandId", "")),
            arguments,
        )
        return result.to_wire(request_id), result.shutdown_requested


def failure_response(request_id: str, code: str, summary: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "requestId": request_id,
        "accepted": False,
        "error": {"code": code, "summary": summary},
        "result": {"code": code, "summary": summary, "snapshot": snapshot},
    }


def endpoint_path(state_directory: Path) -> Path:
    return state_directory / ENDPOINT_FILENAME


def remove_endpoint_if_owned(path: Path, host_instance_id: str) -> None:
    existing = read_json(path)
    if existing and existing.get("hostInstanceId") == host_instance_id:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def run_host(*, state_directory: Path, collection_interval_seconds: int = DEFAULT_COLLECTION_INTERVAL_SECONDS) -> int:
    state_directory.mkdir(parents=True, exist_ok=True)
    runtime = EngineHostRuntime(collection_interval_seconds=collection_interval_seconds)
    lease = HostLease(state_directory / HOST_LOCK_FILENAME, runtime.host_instance_id)
    if not lease.acquire():
        return 2

    access_token = secrets.token_urlsafe(32)
    server: EngineHostServer | None = None
    descriptor = endpoint_path(state_directory)
    try:
        server = EngineHostServer(runtime, access_token)
        address, port = server.server_address
        endpoint = EngineHostEndpoint(
            protocol_version=PROTOCOL_VERSION,
            host_instance_id=runtime.host_instance_id,
            process_id=os.getpid(),
            started_at_utc=runtime.started_at_utc,
            address=str(address),
            port=int(port),
            access_token=access_token,
        )
        atomic_write_json(descriptor, endpoint.to_wire())
        runtime.start_collection_loop()

        def request_shutdown(_signal_number: int, _frame: Any) -> None:
            runtime.request_shutdown()
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, request_shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, request_shutdown)
        server.serve_forever(poll_interval=0.2)
        return 0
    finally:
        runtime.close()
        if server is not None:
            server.server_close()
        remove_endpoint_if_owned(descriptor, runtime.host_instance_id)
        lease.release()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Momentum Hunter Python Engine Host.")
    parser.add_argument("--state-directory", type=Path, default=DATA_DIR / "python-engine-host")
    parser.add_argument("--collection-interval-seconds", type=int, default=DEFAULT_COLLECTION_INTERVAL_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_host(
        state_directory=args.state_directory,
        collection_interval_seconds=max(1, args.collection_interval_seconds),
    )


if __name__ == "__main__":
    raise SystemExit(main())
