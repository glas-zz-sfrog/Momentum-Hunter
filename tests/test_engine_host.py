from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from momentum_hunter.engine_host import (
    COMMAND_CHART_SNAPSHOT,
    COMMAND_PAUSE,
    COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT,
    COMMAND_RESUME,
    COMMAND_RUN_CYCLE,
    COMMAND_SHUTDOWN,
    COMMAND_SNAPSHOT,
    ENDPOINT_FILENAME,
    HOST_LOCK_FILENAME,
    PROTOCOL_VERSION,
    EngineHostRuntime,
    EngineHostServer,
    HostLease,
    read_json,
)


class EngineHostRuntimeTests(unittest.TestCase):
    def test_host_lease_allows_one_owner_and_releases_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / HOST_LOCK_FILENAME
            first = HostLease(lock_path, "first-host")
            second = HostLease(lock_path, "second-host")

            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()
            self.assertFalse(lock_path.exists())

    def test_duplicate_command_id_runs_a_collection_cycle_only_once(self) -> None:
        runs: list[str] = []
        runtime = EngineHostRuntime(cycle_runner=lambda: runs.append("cycle") or SimpleNamespace(target_count=3))

        first = runtime.execute(COMMAND_RUN_CYCLE, "same-command")
        repeated = runtime.execute(COMMAND_RUN_CYCLE, "same-command")

        self.assertTrue(first.accepted)
        self.assertEqual(first, repeated)
        self.assertEqual(["cycle"], runs)
        self.assertEqual(1, first.snapshot["collection"]["cycleCount"])
        self.assertEqual(3, first.snapshot["collection"]["monitoredSymbolCount"])

    def test_pause_blocks_collection_until_resume(self) -> None:
        runs: list[str] = []
        runtime = EngineHostRuntime(cycle_runner=lambda: runs.append("cycle") or SimpleNamespace(target_count=1))

        paused = runtime.execute(COMMAND_PAUSE, "pause")
        blocked = runtime.execute(COMMAND_RUN_CYCLE, "blocked-cycle")
        resumed = runtime.execute(COMMAND_RESUME, "resume")
        completed = runtime.execute(COMMAND_RUN_CYCLE, "completed-cycle")

        self.assertTrue(paused.accepted)
        self.assertFalse(blocked.accepted)
        self.assertEqual("COLLECTION_PAUSED", blocked.code)
        self.assertTrue(resumed.accepted)
        self.assertTrue(completed.accepted)
        self.assertEqual(["cycle"], runs)

    def test_existing_legacy_monitor_runner_blocks_duplicate_collection_loop(self) -> None:
        runs: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: runs.append("cycle") or SimpleNamespace(target_count=1),
            external_monitor_running=lambda: True,
        )

        result = runtime.execute(COMMAND_RUN_CYCLE, "legacy-monitor-active")

        self.assertFalse(result.accepted)
        self.assertEqual("EXISTING_MONITOR_RUNNER_ACTIVE", result.code)
        self.assertEqual("Blocked", result.snapshot["collection"]["state"])
        self.assertEqual([], runs)

    def test_concurrent_cycle_request_does_not_start_a_second_loop(self) -> None:
        started = threading.Event()
        release = threading.Event()
        runs: list[str] = []

        def cycle_runner() -> SimpleNamespace:
            runs.append("cycle")
            started.set()
            self.assertTrue(release.wait(timeout=3))
            return SimpleNamespace(target_count=2)

        runtime = EngineHostRuntime(cycle_runner=cycle_runner)
        first_result: list[object] = []
        first = threading.Thread(target=lambda: first_result.append(runtime.execute(COMMAND_RUN_CYCLE, "first")))
        first.start()
        self.assertTrue(started.wait(timeout=3))
        overlapping = runtime.execute(COMMAND_RUN_CYCLE, "second")
        release.set()
        first.join(timeout=3)

        self.assertFalse(overlapping.accepted)
        self.assertEqual("COLLECTION_IN_PROGRESS", overlapping.code)
        self.assertEqual(["cycle"], runs)
        self.assertEqual(1, len(first_result))

    def test_collection_failure_is_visible_without_stopping_the_host(self) -> None:
        runtime = EngineHostRuntime(cycle_runner=lambda: (_ for _ in ()).throw(RuntimeError("provider unavailable")))

        failed = runtime.execute(COMMAND_RUN_CYCLE, "failing-cycle")
        snapshot = runtime.execute(COMMAND_SNAPSHOT, "snapshot")

        self.assertFalse(failed.accepted)
        self.assertEqual("COLLECTION_FAILED", failed.code)
        self.assertEqual("Blocked", failed.snapshot["health"]["state"])
        self.assertTrue(snapshot.accepted)
        self.assertEqual("Blocked", snapshot.snapshot["collection"]["state"])

    def test_unexpected_command_failure_stays_structured(self) -> None:
        runtime = EngineHostRuntime(external_monitor_running=lambda: (_ for _ in ()).throw(RuntimeError("unexpected")))

        result = runtime.execute(COMMAND_RUN_CYCLE, "unexpected-command-failure")

        self.assertFalse(result.accepted)
        self.assertEqual("HOST_COMMAND_FAILED", result.code)

    def test_host_runtime_does_not_mutate_canonical_monitor_source(self) -> None:
        source = Path("momentum_hunter") / "active_monitor.py"
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        runtime = EngineHostRuntime(cycle_runner=lambda: SimpleNamespace(target_count=1))

        result = runtime.execute(COMMAND_RUN_CYCLE, "source-integrity")

        self.assertTrue(result.accepted)
        self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_read_only_workspace_command_returns_injected_payload_without_starting_collection(self) -> None:
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(AssertionError("collection should not run")),
            workspace_snapshot_loader=lambda: {"schemaVersion": 1, "planningAvailable": False, "candidates": []},
        )

        result = runtime.execute(COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT, "read-only-snapshot")

        self.assertTrue(result.accepted)
        self.assertEqual("READ_ONLY_WORKSPACE_SNAPSHOT", result.code)
        self.assertEqual({"schemaVersion": 1, "planningAvailable": False, "candidates": []}, result.payload)
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])

    def test_chart_command_returns_injected_read_only_payload_without_starting_collection(self) -> None:
        calls: list[tuple[str, str]] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: (_ for _ in ()).throw(AssertionError("collection should not run")),
            chart_snapshot_loader=lambda symbol, interval: calls.append((symbol, interval))
            or {"schemaVersion": 1, "symbol": symbol, "interval": interval, "state": "AVAILABLE", "candles": []},
        )

        result = runtime.execute(
            COMMAND_CHART_SNAPSHOT,
            "chart-snapshot",
            {"symbol": "AAA", "interval": "5m"},
        )
        repeated = runtime.execute(
            COMMAND_CHART_SNAPSHOT,
            "chart-snapshot",
            {"symbol": "AAA", "interval": "5m"},
        )

        self.assertTrue(result.accepted)
        self.assertEqual("CHART_SNAPSHOT", result.code)
        self.assertEqual(result, repeated)
        self.assertEqual([("AAA", "5m")], calls)
        self.assertEqual(0, result.snapshot["collection"]["cycleCount"])

    def test_chart_command_rejects_missing_or_invalid_arguments(self) -> None:
        runtime = EngineHostRuntime(
            chart_snapshot_loader=lambda symbol, interval: (_ for _ in ()).throw(ValueError("unsupported interval"))
        )

        missing_symbol = runtime.execute(COMMAND_CHART_SNAPSHOT, "missing-symbol", {"interval": "5m"})
        missing_interval = runtime.execute(COMMAND_CHART_SNAPSHOT, "missing-interval", {"symbol": "AAA"})
        invalid = runtime.execute(COMMAND_CHART_SNAPSHOT, "invalid", {"symbol": "AAA", "interval": "60m"})

        self.assertFalse(missing_symbol.accepted)
        self.assertEqual("CHART_SYMBOL_REQUIRED", missing_symbol.code)
        self.assertFalse(missing_interval.accepted)
        self.assertEqual("CHART_INTERVAL_REQUIRED", missing_interval.code)
        self.assertFalse(invalid.accepted)
        self.assertEqual("INVALID_CHART_REQUEST", invalid.code)


class EngineHostProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = EngineHostRuntime(cycle_runner=lambda: SimpleNamespace(target_count=4))
        self.token = "test-token"
        self.server = EngineHostServer(self.runtime, self.token)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_protocol_rejects_bad_token_and_bad_version(self) -> None:
        bad_token = self.send(command=COMMAND_SNAPSHOT, command_id="bad-token", token="wrong")
        bad_version = self.send(command=COMMAND_SNAPSHOT, command_id="bad-version", version="9.9")

        self.assertFalse(bad_token["accepted"])
        self.assertEqual("UNAUTHENTICATED", bad_token["error"]["code"])
        self.assertFalse(bad_version["accepted"])
        self.assertEqual("PROTOCOL_VERSION_MISMATCH", bad_version["error"]["code"])

    def test_protocol_returns_versioned_snapshot_and_no_execution_capability(self) -> None:
        response = self.send(command=COMMAND_SNAPSHOT, command_id="snapshot")
        snapshot = response["result"]["snapshot"]

        self.assertTrue(response["accepted"])
        self.assertEqual(PROTOCOL_VERSION, response["protocolVersion"])
        self.assertEqual("loopback-tcp", snapshot["identity"]["transport"])
        self.assertIn(COMMAND_RUN_CYCLE, snapshot["capabilities"])
        self.assertIn(COMMAND_CHART_SNAPSHOT, snapshot["capabilities"])
        self.assertNotIn("submit_order", snapshot["capabilities"])
        self.assertNotIn("paper_order", snapshot["capabilities"])
        self.assertNotIn("live_order", snapshot["capabilities"])

    def test_protocol_returns_read_only_workspace_payload(self) -> None:
        self.runtime._workspace_snapshot_loader = lambda: {"schemaVersion": 1, "planningAvailable": False, "candidates": []}

        response = self.send(command=COMMAND_READ_ONLY_WORKSPACE_SNAPSHOT, command_id="read-only-workspace")

        self.assertTrue(response["accepted"])
        self.assertEqual("READ_ONLY_WORKSPACE_SNAPSHOT", response["result"]["code"])
        self.assertEqual([], response["result"]["payload"]["candidates"])
        self.assertFalse(response["result"]["payload"]["planningAvailable"])

    def test_protocol_returns_chart_payload_with_arguments(self) -> None:
        self.runtime._chart_snapshot_loader = lambda symbol, interval: {
            "schemaVersion": 1,
            "symbol": symbol,
            "interval": interval,
            "state": "AVAILABLE",
            "candles": [],
        }

        response = self.send(
            command=COMMAND_CHART_SNAPSHOT,
            command_id="chart",
            arguments={"symbol": "AAA", "interval": "Daily"},
        )

        self.assertTrue(response["accepted"])
        self.assertEqual("CHART_SNAPSHOT", response["result"]["code"])
        self.assertEqual("AAA", response["result"]["payload"]["symbol"])
        self.assertEqual("Daily", response["result"]["payload"]["interval"])

    def test_shutdown_command_stops_server_after_a_response(self) -> None:
        response = self.send(command=COMMAND_SHUTDOWN, command_id="shutdown")

        self.assertTrue(response["accepted"])
        self.assertEqual("SHUTDOWN_REQUESTED", response["result"]["code"])
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())

    def send(
        self,
        *,
        command: str,
        command_id: str,
        token: str | None = None,
        version: str = PROTOCOL_VERSION,
        arguments: dict[str, str] | None = None,
    ) -> dict:
        address, port = self.server.server_address
        payload = {
            "protocolVersion": version,
            "requestId": f"request-{command_id}",
            "accessToken": self.token if token is None else token,
            "command": command,
            "commandId": command_id,
            "arguments": arguments or {},
        }
        with socket.create_connection((address, port), timeout=3) as connection:
            connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            raw = connection.makefile("rb").readline()
        return json.loads(raw.decode("utf-8"))


class EngineHostProcessProofTests(unittest.TestCase):
    def test_separate_client_exit_does_not_stop_host_and_shutdown_cleans_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_directory = Path(directory)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "momentum_hunter.engine_host",
                    "--state-directory",
                    str(state_directory),
                    "--collection-interval-seconds",
                    "3600",
                ],
                cwd=Path.cwd(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                descriptor_path = state_directory / ENDPOINT_FILENAME
                descriptor = wait_for_descriptor(descriptor_path, process)
                first_host_id = descriptor["hostInstanceId"]

                client_code = """
import json, socket, sys
from pathlib import Path
descriptor = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
payload = {'protocolVersion': '1.0', 'requestId': 'separate-client', 'accessToken': descriptor['accessToken'], 'command': 'get_host_snapshot', 'commandId': 'separate-client-snapshot'}
with socket.create_connection((descriptor['address'], descriptor['port']), timeout=3) as connection:
    connection.sendall((json.dumps(payload) + '\\n').encode('utf-8'))
    response = json.loads(connection.makefile('rb').readline().decode('utf-8'))
assert response['accepted']
"""
                completed_client = subprocess.run(
                    [sys.executable, "-c", client_code, str(descriptor_path)],
                    cwd=Path.cwd(),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(0, completed_client.returncode, completed_client.stderr)
                self.assertIsNone(process.poll())

                snapshot = send_process_request(descriptor, COMMAND_SNAPSHOT, "reconnect-snapshot")
                self.assertTrue(snapshot["accepted"])
                self.assertEqual(first_host_id, snapshot["result"]["snapshot"]["identity"]["hostInstanceId"])

                shutdown = send_process_request(descriptor, COMMAND_SHUTDOWN, "deliberate-shutdown")
                self.assertTrue(shutdown["accepted"])
                self.assertEqual(0, process.wait(timeout=10))
                self.assertFalse(descriptor_path.exists())
                self.assertFalse((state_directory / HOST_LOCK_FILENAME).exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                if process.stderr is not None:
                    process.stderr.close()


def wait_for_descriptor(path: Path, process: subprocess.Popen[str]) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        descriptor = read_json(path)
        if descriptor:
            return descriptor
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr else ""
            raise AssertionError(f"Python Engine Host exited before publishing an endpoint: {stderr}")
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for the Python Engine Host endpoint descriptor.")


def send_process_request(descriptor: dict, command: str, command_id: str) -> dict:
    payload = {
        "protocolVersion": PROTOCOL_VERSION,
        "requestId": command_id,
        "accessToken": descriptor["accessToken"],
        "command": command,
        "commandId": command_id,
    }
    with socket.create_connection((descriptor["address"], descriptor["port"]), timeout=3) as connection:
        connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        raw = connection.makefile("rb").readline()
    return json.loads(raw.decode("utf-8"))
