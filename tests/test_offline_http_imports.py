"""Fresh-process zero-socket qualification; all state is disposable test data."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODES = ("imports", "host_admission", "science_cleanup", "failure_cleanup", "restart")


def probe(mode, root):
    import os
    import uuid

    attempts = []

    def deny(event, unused):
        if event.startswith("socket."):
            attempts.append(event)
            raise PermissionError("015A_TEST_DENIES_EVERY_SOCKET_OPERATION")

    sys.addaudithook(deny)
    from momentum_hunter import continuous_production as production
    from momentum_hunter import continuous_science_service as bridge
    from momentum_hunter import continuous_host_generation as generations
    from momentum_hunter import continuous_host_lifecycle as lifecycle
    from momentum_hunter import continuous_live_qualification

    detail = {"scope": "OFFLINE_UNIT_FIXTURES_NOT_SCM_AUTHORITY_OR_PROVIDER_EVIDENCE"}
    if mode != "imports":
        from tests.test_continuous_host_boundaries import configuration, seal, save_config
        from tests.test_strategy_science_continuous_recorder import core_fixtures, publication
        from tests.test_strategy_science_recorder_contract import SOURCE_ROOT_IDENTITY
        config = configuration(root)
        config["runtimeBuildHash"] = SOURCE_ROOT_IDENTITY
        config["host"]["science"]["custodyPolicy"]["source_root_identity"] = SOURCE_ROOT_IDENTITY
        config["researchFactExportV2"]["startManifest"]["source_root_identity"] = SOURCE_ROOT_IDENTITY
        config["configurationFingerprint"] = production.deployment_configuration_fingerprint(config)
        seal(config)
        path = save_config(config)
        assert production._read_config(path) == config
        if mode == "host_admission":
            plan = production.install_plan(config, path, root / "source", Path(sys.executable))
            assert plan["windowsMutation"] is False
            detail["hostAdmission"] = "PASS"
        else:
            # Generation receipts here are explicit unit fixtures, never SCM proof.
            for role in ("writer", "runtime"):
                generations.replace_status(generations.generation_path(config, role),
                    {"hostFingerprint": config["hostFingerprint"], "role": role,
                     "generation": str(uuid.uuid4()), "phase": "EXITED"})
            upstream = lifecycle.upstream_generations(config, "science")
            generations.replace_status(Path(config["hostStateRoot"]) / "runtime" / "completion.json",
                {"hostFingerprint": config["hostFingerprint"], "role": "runtime",
                 "generation": upstream["runtime"], "dependencies": {"writer": upstream["writer"]},
                 "exitCode": 0, "drainComplete": True, "cleanupComplete": True, "pendingWork": 0})
            published = Path(config["researchFactExportV2"]["exportRoot"]) / "published"
            for ordinal, raw in enumerate(core_fixtures(), 1):
                publication(published, raw, ordinal)
            if mode == "failure_cleanup":
                next(published.iterdir()).write_bytes(b"not-json-unit-fixture")
            import ctypes
            from ctypes import wintypes
            from unittest.mock import patch
            from tests.test_continuous_host_science007 import host_filesystem_fixture
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.CreateEventW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            event = kernel.CreateEventW(None, True, True, None)
            assert event
            results = []
            try:
                for unused in range(2 if mode == "restart" else 1):
                    generation = str(uuid.uuid4())
                    generations.replace_status(generations.generation_path(config, "science"),
                        {"hostFingerprint": config["hostFingerprint"], "role": "science",
                         "generation": generation, "phase": "RUNNING",
                         "executionModel": generations.SCM_DIRECT,
                         "servicePid": os.getpid(), "serviceBirth": generations.process_birth(os.getpid())})
                    # Structural transport fixture only; the unconditional audit
                    # guard and actual stop-event bridge remain under test.
                    backend = host_filesystem_fixture(root, config)
                    try:
                        with patch("momentum_hunter.windows_science_custody.open_science_custody_backend", return_value=backend):
                            code = bridge.run(str(path), generation, int(event))
                    finally:
                        backend.close()
                    status = generations.read_record(generations.status_path(config, "science"))
                    assert code == (2 if mode == "failure_cleanup" else 0), status
                    results.append({"generation": generation, "exitCode": code, "status": status})
                if mode == "restart":
                    assert results[0]["generation"] != results[1]["generation"]
                    assert results[0]["status"]["coverage"] == results[1]["status"]["coverage"]
            finally:
                kernel.CloseHandle(event)
            detail["generations"] = results
    assert not attempts, attempts
    assert "requests" not in sys.modules and "urllib3" not in sys.modules
    return {"status": "PASS", "mode": mode, "socketCreationAttempts": 0,
            "dnsAttempts": 0, "allSocketEvents": attempts, "providerContact": 0,
            "brokerContact": 0, "socketMonkeypatch": False, **detail}


class OfflineHttpImportTests(unittest.TestCase):
    def run_probe(self, mode):
        source = str(Path(__file__).resolve().parents[1])
        code = ("import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                "from tests.test_offline_http_imports import probe; "
                "print(json.dumps(probe(sys.argv[2],Path(sys.argv[3]))))")
        with tempfile.TemporaryDirectory(prefix="MH-015A-ZeroSocket-") as temporary:
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                source, mode, temporary], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["allSocketEvents"], [])
        return payload

    def test_imports_do_not_initialize_http_library(self):
        self.run_probe("imports")

    def test_offline_host_admission_zero_sockets(self):
        self.run_probe("host_admission")

    @unittest.skipUnless(sys.platform == "win32", "Native Science stop-event bridge")
    def test_science_startup_and_successful_cleanup_zero_sockets(self):
        self.run_probe("science_cleanup")

    @unittest.skipUnless(sys.platform == "win32", "Native Science stop-event bridge")
    def test_science_failure_cleanup_zero_sockets(self):
        self.run_probe("failure_cleanup")

    @unittest.skipUnless(sys.platform == "win32", "Native Science stop-event bridge")
    def test_science_restart_preparation_and_reentry_zero_sockets(self):
        self.run_probe("restart")
