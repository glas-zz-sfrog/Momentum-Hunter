from __future__ import annotations

import json
import os
import shutil
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.engine_host import (
    COMMAND_SHUTDOWN,
    COMMAND_SNAPSHOT,
    ENDPOINT_FILENAME,
    EngineHostEndpoint,
    EngineHostRuntime,
    EngineHostServer,
    PROTOCOL_VERSION,
)
from momentum_hunter.engine_host_client import (
    EngineHostClientError,
    EngineHostClientResult,
    EngineHostRetryableError,
    EngineHostTerminalError,
    ensure_engine_host,
    read_engine_host_endpoint,
    run_immediate_collection_cycle,
)
from momentum_hunter.providers import ProviderUnavailableError
from momentum_hunter.shadow_market_validity import (
    SHADOW_SELECTOR_ARM_SCHEMA_VERSION,
    runtime_build_hash,
)


class EngineHostClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = (
            Path.cwd()
            / "MomentumHunterData"
            / "data"
            / f"_test-engine-host-client-{uuid.uuid4().hex}"
        )
        self.root.mkdir(parents=True)
        self.cycles: list[str] = []
        self.runtime = EngineHostRuntime(
            cycle_runner=lambda: self._record_cycle(),
        )
        self.token = "local-test-token"
        self.server = EngineHostServer(self.runtime, self.token)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.root, ignore_errors=True)

    def test_immediate_cycle_uses_existing_authenticated_loopback_host(self) -> None:
        self.write_endpoint(self.root)
        launches: list[Path] = []

        result = run_immediate_collection_cycle(
            state_directory=self.root,
            launcher=launches.append,
            process_checker=lambda process_id: process_id == os.getpid(),
        )

        self.assertTrue(result.accepted)
        self.assertEqual("COLLECTION_COMPLETED", result.code)
        self.assertEqual(["cycle"], self.cycles)
        self.assertEqual([], launches)

    def test_ensure_host_waits_for_launcher_to_publish_endpoint(self) -> None:
        launches: list[Path] = []

        def launcher(path: Path) -> None:
            launches.append(path)
            self.write_endpoint(path)

        endpoint = ensure_engine_host(
            state_directory=self.root,
            launcher=launcher,
            process_checker=lambda process_id: process_id == os.getpid(),
            start_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )

        self.assertEqual(self.server.server_address[1], endpoint.port)
        self.assertEqual([self.root], launches)

    def test_nonloopback_stale_and_incomplete_endpoints_are_rejected(self) -> None:
        self.write_endpoint(self.root, address="0.0.0.0")
        self.assertIsNone(
            read_engine_host_endpoint(
                self.root,
                process_checker=lambda _process_id: True,
            )
        )

        self.write_endpoint(self.root, process_id=999999)
        self.assertIsNone(
            read_engine_host_endpoint(
                self.root,
                process_checker=lambda _process_id: False,
            )
        )

        (self.root / ENDPOINT_FILENAME).write_text("{}", encoding="utf-8")
        self.assertIsNone(
            read_engine_host_endpoint(
                self.root,
                process_checker=lambda _process_id: True,
            )
        )

    def test_failed_cycle_reports_only_local_host_failure(self) -> None:
        self.runtime._cycle_runner = lambda: (_ for _ in ()).throw(
            RuntimeError("local-cycle-failed")
        )
        self.write_endpoint(self.root)

        with self.assertRaises(EngineHostTerminalError) as context:
            run_immediate_collection_cycle(
                state_directory=self.root,
                launcher=lambda _path: self.fail("launcher should not run"),
                process_checker=lambda _process_id: True,
            )

        self.assertNotIn(self.token, str(context.exception))
        self.assertIn("COLLECTION_FAILED", str(context.exception))

    def test_retryable_provider_failure_is_distinct_from_terminal_failure(
        self,
    ) -> None:
        self.runtime._cycle_runner = lambda: (_ for _ in ()).throw(
            ProviderUnavailableError(
                "finviz",
                "temporary provider outage",
                "network",
            )
        )
        self.write_endpoint(self.root)

        with self.assertRaises(EngineHostRetryableError):
            run_immediate_collection_cycle(
                state_directory=self.root,
                launcher=lambda _path: self.fail("launcher should not run"),
                process_checker=lambda _process_id: True,
            )

        self.assertTrue(issubclass(EngineHostRetryableError, EngineHostClientError))

    def test_authenticated_idle_stale_host_is_replaced_before_use(self) -> None:
        stale_pid = 101
        current_pid = 202
        alive = {stale_pid: True, current_pid: True}
        calls: list[tuple[int, str]] = []
        self.write_descriptor(
            process_id=stale_pid,
            runtime_build_identity="0" * 64,
            selector_arm_schema_version=2,
        )

        stale_snapshot = host_result(
            runtime_build_identity="0" * 64,
            selector_arm_schema_version=2,
        )
        current_snapshot = host_result(
            runtime_build_identity=runtime_build_hash(),
            selector_arm_schema_version=SHADOW_SELECTOR_ARM_SCHEMA_VERSION,
        )

        def sender(endpoint, command, **_kwargs):
            calls.append((endpoint.process_id, command))
            if endpoint.process_id == stale_pid and command == COMMAND_SNAPSHOT:
                return stale_snapshot
            if endpoint.process_id == stale_pid and command == COMMAND_SHUTDOWN:
                alive[stale_pid] = False
                return EngineHostClientResult(
                    accepted=True,
                    code="SHUTDOWN_REQUESTED",
                    summary="stopping",
                    snapshot=stale_snapshot.snapshot,
                    payload=None,
                )
            if endpoint.process_id == current_pid and command == COMMAND_SNAPSHOT:
                return current_snapshot
            raise AssertionError((endpoint.process_id, command))

        def launcher(_path: Path) -> None:
            self.write_descriptor(
                process_id=current_pid,
                runtime_build_identity=runtime_build_hash(),
                selector_arm_schema_version=(
                    SHADOW_SELECTOR_ARM_SCHEMA_VERSION
                ),
            )

        with patch(
            "momentum_hunter.engine_host_client.send_engine_host_command",
            side_effect=sender,
        ):
            endpoint = ensure_engine_host(
                state_directory=self.root,
                launcher=launcher,
                process_checker=lambda process_id: alive.get(process_id, False),
                start_timeout_seconds=1,
                poll_interval_seconds=0.01,
            )

        self.assertEqual(current_pid, endpoint.process_id)
        self.assertEqual(
            [
                (stale_pid, COMMAND_SNAPSHOT),
                (stale_pid, COMMAND_SHUTDOWN),
                (current_pid, COMMAND_SNAPSHOT),
            ],
            calls,
        )

    def test_stale_host_in_active_cycle_is_not_stopped(self) -> None:
        stale_pid = 303
        self.write_descriptor(
            process_id=stale_pid,
            runtime_build_identity="0" * 64,
            selector_arm_schema_version=2,
        )
        stale_snapshot = host_result(
            runtime_build_identity="0" * 64,
            selector_arm_schema_version=2,
            cycle_in_progress=True,
        )
        calls: list[str] = []

        def sender(_endpoint, command, **_kwargs):
            calls.append(command)
            return stale_snapshot

        with (
            patch(
                "momentum_hunter.engine_host_client.send_engine_host_command",
                side_effect=sender,
            ),
            self.assertRaisesRegex(
                EngineHostRetryableError,
                "finishing a collection cycle",
            ),
        ):
            ensure_engine_host(
                state_directory=self.root,
                launcher=lambda _path: self.fail("launcher must not run"),
                process_checker=lambda process_id: process_id == stale_pid,
                start_timeout_seconds=0.1,
                poll_interval_seconds=0.01,
            )

        self.assertEqual([COMMAND_SNAPSHOT], calls)

    def test_rejected_identity_snapshot_never_launches_second_host(self) -> None:
        host_pid = 404
        self.write_descriptor(
            process_id=host_pid,
            runtime_build_identity=runtime_build_hash(),
            selector_arm_schema_version=SHADOW_SELECTOR_ARM_SCHEMA_VERSION,
        )
        rejected = EngineHostClientResult(
            accepted=False,
            code="HOST_STOPPING",
            summary="stopping",
            snapshot={},
            payload=None,
        )

        with (
            patch(
                "momentum_hunter.engine_host_client.send_engine_host_command",
                return_value=rejected,
            ),
            self.assertRaisesRegex(
                EngineHostRetryableError,
                "second host will not be launched",
            ),
        ):
            ensure_engine_host(
                state_directory=self.root,
                launcher=lambda _path: self.fail("launcher must not run"),
                process_checker=lambda process_id: process_id == host_pid,
            )

    def _record_cycle(self):
        self.cycles.append("cycle")
        return type("Report", (), {"target_count": 3})()

    def write_endpoint(
        self,
        directory: Path,
        *,
        address: str = "127.0.0.1",
        process_id: int | None = None,
        token: str | None = None,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        host, port = self.server.server_address
        endpoint = EngineHostEndpoint(
            protocol_version=PROTOCOL_VERSION,
            host_instance_id=self.runtime.host_instance_id,
            process_id=process_id or os.getpid(),
            started_at_utc=self.runtime.started_at_utc,
            address=address or host,
            port=int(port),
            access_token=token or self.token,
        )
        (directory / ENDPOINT_FILENAME).write_text(
            json.dumps(endpoint.to_wire()),
            encoding="utf-8",
        )

    def write_descriptor(
        self,
        *,
        process_id: int,
        runtime_build_identity: str,
        selector_arm_schema_version: int,
    ) -> None:
        endpoint = EngineHostEndpoint(
            protocol_version=PROTOCOL_VERSION,
            host_instance_id=f"host-{process_id}",
            process_id=process_id,
            started_at_utc="2026-07-29T13:00:00Z",
            address="127.0.0.1",
            port=32000 + process_id,
            access_token="local-test-token",
            runtime_build_hash=runtime_build_identity,
            selector_arm_schema_version=selector_arm_schema_version,
        )
        (self.root / ENDPOINT_FILENAME).write_text(
            json.dumps(endpoint.to_wire()),
            encoding="utf-8",
        )


def host_result(
    *,
    runtime_build_identity: str,
    selector_arm_schema_version: int,
    cycle_in_progress: bool = False,
) -> EngineHostClientResult:
    return EngineHostClientResult(
        accepted=True,
        code="SNAPSHOT",
        summary="snapshot",
        snapshot={
            "identity": {
                "runtimeBuildHash": runtime_build_identity,
                "selectorArmSchemaVersion": selector_arm_schema_version,
            },
            "collection": {"cycleInProgress": cycle_in_progress},
        },
        payload=None,
    )


if __name__ == "__main__":
    unittest.main()
