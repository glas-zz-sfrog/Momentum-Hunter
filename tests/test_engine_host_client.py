from __future__ import annotations

import json
import os
import shutil
import threading
import unittest
import uuid
from pathlib import Path

from momentum_hunter.engine_host import (
    ENDPOINT_FILENAME,
    EngineHostEndpoint,
    EngineHostRuntime,
    EngineHostServer,
    PROTOCOL_VERSION,
)
from momentum_hunter.engine_host_client import (
    EngineHostClientError,
    ensure_engine_host,
    read_engine_host_endpoint,
    run_immediate_collection_cycle,
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

        with self.assertRaises(EngineHostClientError) as context:
            run_immediate_collection_cycle(
                state_directory=self.root,
                launcher=lambda _path: self.fail("launcher should not run"),
                process_checker=lambda _process_id: True,
            )

        self.assertNotIn(self.token, str(context.exception))
        self.assertIn("COLLECTION_FAILED", str(context.exception))

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


if __name__ == "__main__":
    unittest.main()
