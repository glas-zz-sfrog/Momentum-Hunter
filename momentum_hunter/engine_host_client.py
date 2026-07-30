from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from momentum_hunter.config import DATA_DIR
from momentum_hunter.engine_host import (
    COMMAND_RUN_CYCLE,
    COMMAND_SHUTDOWN,
    COMMAND_SNAPSHOT,
    ENDPOINT_FILENAME,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PROTOCOL_VERSION,
    process_is_running,
)
from momentum_hunter.shadow_market_validity import (
    SHADOW_SELECTOR_ARM_SCHEMA_VERSION,
    runtime_build_hash,
)


DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120.0
DEFAULT_START_TIMEOUT_SECONDS = 20.0
DEFAULT_STALE_HOST_SHUTDOWN_TIMEOUT_SECONDS = 10.0


class EngineHostClientError(RuntimeError):
    pass


class EngineHostRetryableError(EngineHostClientError):
    pass


class EngineHostTerminalError(EngineHostClientError):
    pass


@dataclass(frozen=True)
class EngineHostClientResult:
    accepted: bool
    code: str
    summary: str
    snapshot: dict[str, Any]
    payload: dict[str, Any] | None
    command_id: str = ""


@dataclass(frozen=True)
class EngineHostClientEndpoint:
    protocol_version: str
    host_instance_id: str
    process_id: int
    address: str
    port: int
    access_token: str
    runtime_build_hash: str = ""
    selector_arm_schema_version: int = 0


HostLauncher = Callable[[Path], None]
ProcessChecker = Callable[[int], bool]


def default_state_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "MomentumHunter" / "python-engine-host"
    return DATA_DIR / "python-engine-host"


def read_engine_host_endpoint(
    state_directory: Path,
    *,
    process_checker: ProcessChecker = process_is_running,
) -> EngineHostClientEndpoint | None:
    descriptor = state_directory / ENDPOINT_FILENAME
    try:
        payload = json.loads(descriptor.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        endpoint = EngineHostClientEndpoint(
            protocol_version=str(payload.get("protocolVersion", "")),
            host_instance_id=str(payload.get("hostInstanceId", "")),
            process_id=int(payload.get("processId", 0)),
            address=str(payload.get("address", "")),
            port=int(payload.get("port", 0)),
            access_token=str(payload.get("accessToken", "")),
            runtime_build_hash=str(payload.get("runtimeBuildHash", "")),
            selector_arm_schema_version=int(
                payload.get("selectorArmSchemaVersion", 0)
            ),
        )
    except (TypeError, ValueError):
        return None
    if (
        endpoint.protocol_version != PROTOCOL_VERSION
        or not endpoint.host_instance_id
        or endpoint.address != "127.0.0.1"
        or not (1 <= endpoint.port <= 65535)
        or not endpoint.access_token
        or not process_checker(endpoint.process_id)
    ):
        return None
    return endpoint


def send_engine_host_command(
    endpoint: EngineHostClientEndpoint,
    command: str,
    *,
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
    command_id: str | None = None,
) -> EngineHostClientResult:
    request_id = uuid.uuid4().hex
    effective_command_id = command_id or uuid.uuid4().hex
    request = {
        "protocolVersion": PROTOCOL_VERSION,
        "requestId": request_id,
        "accessToken": endpoint.access_token,
        "command": command,
        "commandId": effective_command_id,
        "arguments": {},
    }
    encoded = (json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise EngineHostClientError("Engine Host request exceeded the local protocol limit.")
    try:
        with socket.create_connection(
            (endpoint.address, endpoint.port),
            timeout=min(timeout_seconds, DEFAULT_CONNECT_TIMEOUT_SECONDS),
        ) as connection:
            connection.settimeout(timeout_seconds)
            connection.sendall(encoded)
            response_bytes = read_response_line(connection)
    except (OSError, TimeoutError) as exc:
        raise EngineHostRetryableError(
            "The local Python Engine Host did not accept the command."
        ) from exc
    try:
        response = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EngineHostTerminalError(
            "The local Python Engine Host returned malformed data."
        ) from None
    if (
        not isinstance(response, dict)
        or response.get("protocolVersion") != PROTOCOL_VERSION
        or response.get("requestId") != request_id
    ):
        raise EngineHostTerminalError(
            "The local Python Engine Host response identity did not match."
        )
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("snapshot"), dict):
        raise EngineHostTerminalError(
            "The local Python Engine Host response was incomplete."
        )
    payload = result.get("payload")
    return EngineHostClientResult(
        accepted=response.get("accepted") is True,
        code=str(result.get("code", "")),
        summary=str(result.get("summary", "")),
        snapshot=dict(result["snapshot"]),
        payload=dict(payload) if isinstance(payload, Mapping) else None,
        command_id=effective_command_id,
    )


def ensure_engine_host(
    *,
    state_directory: Path | None = None,
    launcher: HostLauncher | None = None,
    process_checker: ProcessChecker = process_is_running,
    start_timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
    poll_interval_seconds: float = 0.1,
    stale_host_shutdown_timeout_seconds: float = (
        DEFAULT_STALE_HOST_SHUTDOWN_TIMEOUT_SECONDS
    ),
) -> EngineHostClientEndpoint:
    state_directory = state_directory or default_state_directory()
    endpoint = read_engine_host_endpoint(
        state_directory,
        process_checker=process_checker,
    )
    if endpoint is not None:
        try:
            snapshot = send_engine_host_command(
                endpoint,
                COMMAND_SNAPSHOT,
                timeout_seconds=DEFAULT_CONNECT_TIMEOUT_SECONDS,
            )
            if snapshot.accepted and engine_host_identity_matches(snapshot):
                return endpoint
            if snapshot.accepted:
                replace_stale_engine_host(
                    endpoint,
                    snapshot=snapshot,
                    process_checker=process_checker,
                    shutdown_timeout_seconds=stale_host_shutdown_timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                )
            else:
                raise EngineHostRetryableError(
                    "The running Python Engine Host rejected the runtime-identity "
                    "preflight; a second host will not be launched."
                )
        except EngineHostClientError:
            raise

    (launcher or launch_engine_host)(state_directory)
    deadline = time.monotonic() + max(0.1, start_timeout_seconds)
    last_endpoint: EngineHostClientEndpoint | None = None
    while time.monotonic() < deadline:
        last_endpoint = read_engine_host_endpoint(
            state_directory,
            process_checker=process_checker,
        )
        if last_endpoint is not None:
            try:
                snapshot = send_engine_host_command(
                    last_endpoint,
                    COMMAND_SNAPSHOT,
                    timeout_seconds=DEFAULT_CONNECT_TIMEOUT_SECONDS,
                )
                if snapshot.accepted and engine_host_identity_matches(snapshot):
                    return last_endpoint
            except EngineHostClientError:
                pass
        time.sleep(max(0.01, poll_interval_seconds))
    raise EngineHostRetryableError(
        "The local Python Engine Host did not become ready in time."
    )


def engine_host_identity_matches(result: EngineHostClientResult) -> bool:
    identity = result.snapshot.get("identity")
    if not isinstance(identity, Mapping):
        return False
    return (
        identity.get("runtimeBuildHash") == runtime_build_hash()
        and identity.get("selectorArmSchemaVersion")
        == SHADOW_SELECTOR_ARM_SCHEMA_VERSION
    )


def replace_stale_engine_host(
    endpoint: EngineHostClientEndpoint,
    *,
    snapshot: EngineHostClientResult,
    process_checker: ProcessChecker = process_is_running,
    shutdown_timeout_seconds: float = DEFAULT_STALE_HOST_SHUTDOWN_TIMEOUT_SECONDS,
    poll_interval_seconds: float = 0.1,
) -> None:
    collection = snapshot.snapshot.get("collection")
    if isinstance(collection, Mapping) and collection.get("cycleInProgress") is True:
        raise EngineHostRetryableError(
            "The stale Python Engine Host is finishing a collection cycle; "
            "replacement is deferred."
        )
    stopped = send_engine_host_command(
        endpoint,
        COMMAND_SHUTDOWN,
        timeout_seconds=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        command_id=f"replace-stale-engine-host-{runtime_build_hash()}",
    )
    if not stopped.accepted or stopped.code != "SHUTDOWN_REQUESTED":
        raise EngineHostRetryableError(
            "The stale Python Engine Host did not accept a guarded shutdown."
        )
    deadline = time.monotonic() + max(0.1, shutdown_timeout_seconds)
    while time.monotonic() < deadline:
        if not process_checker(endpoint.process_id):
            return
        time.sleep(max(0.01, poll_interval_seconds))
    raise EngineHostRetryableError(
        "The stale Python Engine Host did not stop before the replacement timeout."
    )


def run_immediate_collection_cycle(
    *,
    state_directory: Path | None = None,
    launcher: HostLauncher | None = None,
    process_checker: ProcessChecker = process_is_running,
    command_id: str | None = None,
) -> EngineHostClientResult:
    endpoint = ensure_engine_host(
        state_directory=state_directory,
        launcher=launcher,
        process_checker=process_checker,
    )
    result = send_engine_host_command(
        endpoint,
        COMMAND_RUN_CYCLE,
        timeout_seconds=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        command_id=command_id or f"shadow-opening-capture-{uuid.uuid4().hex}",
    )
    if not result.accepted:
        error_type = (
            EngineHostRetryableError
            if result.payload is not None
            and result.payload.get("retryable") is True
            else EngineHostTerminalError
        )
        raise error_type(
            f"Engine Host collection cycle failed: {result.code}: {result.summary}"
        )
    return result


def launch_engine_host(state_directory: Path) -> None:
    state_directory.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-B",
        "-m",
        "momentum_hunter.engine_host",
        "--state-directory",
        str(state_directory),
    ]
    options: dict[str, Any] = {
        "cwd": str(Path(__file__).resolve().parents[1]),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    try:
        subprocess.Popen(command, **options)
    except OSError as exc:
        raise EngineHostRetryableError(
            "The local Python Engine Host could not be started."
        ) from exc


def read_response_line(connection: socket.socket) -> bytes:
    response = bytearray()
    while len(response) <= MAX_RESPONSE_BYTES:
        chunk = connection.recv(4096)
        if not chunk:
            break
        response.extend(chunk)
        newline = response.find(b"\n")
        if newline >= 0:
            if newline > MAX_RESPONSE_BYTES:
                raise EngineHostTerminalError(
                    "The local Python Engine Host response exceeded the "
                    "protocol limit."
                )
            return bytes(response[:newline])
    if len(response) > MAX_RESPONSE_BYTES:
        raise EngineHostTerminalError(
            "The local Python Engine Host response exceeded the protocol limit."
        )
    if not response:
        raise EngineHostTerminalError(
            "The local Python Engine Host returned no response."
        )
    return bytes(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send a guarded command to the local Python Engine Host."
    )
    parser.add_argument(
        "command",
        choices=("run-collection-cycle", "snapshot"),
    )
    parser.add_argument(
        "--state-directory",
        type=Path,
        default=default_state_directory(),
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "run-collection-cycle":
            result = run_immediate_collection_cycle(
                state_directory=args.state_directory
            )
        else:
            endpoint = ensure_engine_host(state_directory=args.state_directory)
            result = send_engine_host_command(endpoint, COMMAND_SNAPSHOT)
    except EngineHostClientError as exc:
        print(f"Engine Host command failed: {exc}", file=sys.stderr)
        return 1
    print(f"Engine Host: {result.code}")
    print(result.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
