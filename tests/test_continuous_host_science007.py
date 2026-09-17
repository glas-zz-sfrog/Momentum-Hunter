"""016A composition proofs. Structural fixtures are not actual SCM/ACL proof."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from momentum_hunter import continuous_host_contract as contract
from momentum_hunter import continuous_host_lifecycle as lifecycle
from momentum_hunter import continuous_production as production
from momentum_hunter.science_custody_commit import CustodyCommitError
from momentum_hunter.windows_science_custody import ScienceCustodyPolicy
from tests.test_continuous_host_boundaries import configuration, seal, save_config
from tests.test_science_custody_writer_007 import _ControlledChannel
from tests.test_science_custody_recorder_007 import FilesystemProtocolFixture
from tests.test_strategy_science_continuous_recorder import core_fixtures, publication
from tests.test_strategy_science_recorder_contract import SOURCE_ROOT_IDENTITY
from tests.test_science_custody_commit_007 import MemoryBackend, request_for
from momentum_hunter.science_custody_commit import ScienceCustodyFinalizer


class Host:
    enabled = True

    def __init__(self):
        self.generation = str(uuid.uuid4())
        self.statuses = []

    def status(self, state, **detail):
        self.statuses.append({"state": state, **detail})


def host_filesystem_fixture(root, config):
    backend = FilesystemProtocolFixture(root)
    backend.policy_sha256 = contract.science_custody_policy(config).policy_sha256
    backend.security_contract_evidence = {"profile": "STRUCTURAL_TEST_NOT_SCM_PROOF",
        "policy_sha256": backend.policy_sha256, "role": "science", "token": {"fixture": True},
        "exact_owner_dacl_label_policy_verified": True}
    return backend


class HostScience007ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MH-016A-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = configuration(self.root)

    def test_policy_round_trip_is_exact_canonical_value_object(self):
        value = contract.science_custody_policy(self.config)
        self.assertIs(type(value), ScienceCustodyPolicy)
        self.assertEqual(json.loads(json.dumps(asdict(value))), self.config["host"]["science"]["custodyPolicy"])
        self.assertEqual(value.science_sid, contract.science_service_sid("qual-013b"))
        self.assertEqual(value.writer_sid, "S-1-5-19")

    def test_changed_logon_policy_cannot_rebind_retained_commit(self):
        raw = self.config["host"]["science"]["custodyPolicy"]
        raw["science_group_sids"].append("S-1-5-5-1-2")
        raw["science_enabled_group_sids"].append("S-1-5-5-1-2")
        original = contract.science_custody_policy(self.config)
        backend = MemoryBackend()
        backend.policy_sha256 = original.policy_sha256
        request = request_for(backend)
        finalizer = ScienceCustodyFinalizer(backend)
        finalizer.finalize(request)
        retained = dict(backend.objects)
        for key in ("science_group_sids", "science_enabled_group_sids"):
            raw[key][-1] = "S-1-5-5-1-3"
        changed = contract.science_custody_policy(self.config)
        self.assertNotEqual(original.policy_sha256, changed.policy_sha256)
        backend.policy_sha256 = changed.policy_sha256
        with self.assertRaises(CustodyCommitError):
            finalizer.finalize(request)
        self.assertEqual(retained, backend.objects)

    def test_missing_policy_is_not_legacy_science_fallback(self):
        self.config["host"]["science"].pop("custodyPolicy")
        seal(self.config)
        with self.assertRaises(contract.HostConfigurationError):
            contract.validate_host(self.config)

    def test_policy_account_source_and_namespace_misbinding_rejected(self):
        mutations = (
            lambda p: p.update(science_sid="S-1-5-21-1-2-3-4"),
            lambda p: p.update(writer_sid=p["science_sid"]),
            lambda p: p.update(source_root_identity="f" * 64),
            lambda p: p["roots"][0].update(path=str(self.root / "unbound")),
            lambda p: p["roots"][0].update(owner_sid=p["science_sid"]),
            lambda p: p.update(science_privilege_names=["SeDebugPrivilege"]),
            lambda p: p.update(extra="not admitted"),
            lambda p: p["roots"][0].update(file_identity=[True, 0, 1]),
        )
        for change in mutations:
            candidate = deepcopy(self.config)
            change(candidate["host"]["science"]["custodyPolicy"])
            seal(candidate)
            with self.subTest(change=change), self.assertRaises((contract.HostConfigurationError, CustodyCommitError)):
                contract.validate_host(candidate)

    def test_installed_production_does_not_opt_into_science(self):
        legacy = {"schemaVersion": 1, "activationProfile": contract.PROFILE, "mode": "RESEARCH_ONLY",
                  "runtimeIdentity": "production-continuous-runtime-v2", "orderCapability": "UNAVAILABLE"}
        with patch("momentum_hunter.windows_science_custody.ScienceCustodyPolicy", side_effect=AssertionError):
            self.assertIsNone(contract.science_custody_policy(legacy))
        live = deepcopy(self.config)
        live["inputMode"] = contract.LIVE
        with self.assertRaises(contract.HostConfigurationError):
            contract.science_custody_policy(live)

    def test_install_plan_reports_separate_nonowner_storage_roles(self):
        plan = contract.install_plan(self.config, save_config(self.config), self.root, Path("C:/Python/python.exe"))
        permissions = plan["permissions"]
        self.assertNotIn("scienceCustodyDerived", permissions)
        self.assertFalse(permissions["scienceCustodyRoot"]["write"])
        for name in ("arrivals", "custody", "cursors", "claims", "receipts"):
            self.assertEqual("SCIENCE_READ_AUDIT_ONLY", permissions["scienceStorageRoles"][name]["access"])
        for name in ("staging", "requests", "derived"):
            self.assertEqual("SCIENCE_MUTABLE_TRANSPORT_ONLY", permissions["scienceStorageRoles"][name]["access"])
        self.assertEqual("WRITER_ONLY", permissions["scienceStorageRoles"]["private"]["access"])

    def test_host_writer_binds_policy_and_preserves_pending_close(self):
        path = save_config(self.config)
        Path(self.config["ipcKeyPath"]).write_bytes(b"k" * 32)
        host = Host()
        channel = _ControlledChannel(block=True)
        servers = []

        def serve(server, *args):
            servers.append(server)
            self.assertTrue(channel.entered.wait(2))
            return True

        try:
            with patch.object(production, "_open_science_custody_writer", return_value=channel) as opened, \
                 patch("momentum_hunter.windows_writer_profile.NativeWriterAdmission") as admission, \
                 patch.object(production.ProductionWriterServer, "serve_forever", serve):
                self.assertEqual(2, production.run_writer(path, threading.Event(), host))
                policy = opened.call_args.args[0]
                self.assertEqual(contract.science_custody_policy(self.config), policy)
            admission.return_value.close.assert_called_once()
            last = host.statuses[-1]
            self.assertEqual("INCOMPLETE", last["state"])
            self.assertFalse(last["cleanupComplete"])
            self.assertFalse(last["drainComplete"])
            self.assertEqual("STOP_PENDING", last["scienceCustody"]["state"])
        finally:
            channel.release.set()
            for server in servers:
                server._science_custody_worker._thread.join(3)
                self.assertFalse(server._science_custody_worker._thread.is_alive())

    def test_host_writer_clean_worker_close_is_required_for_success(self):
        path = save_config(self.config)
        Path(self.config["ipcKeyPath"]).write_bytes(b"k" * 32)
        channel = _ControlledChannel()
        host = Host()

        def serve(server, *args):
            self.assertTrue(channel.entered.wait(2))
            return True

        with patch.object(production, "_open_science_custody_writer", return_value=channel), \
             patch("momentum_hunter.windows_writer_profile.NativeWriterAdmission") as admission, \
             patch.object(production.ProductionWriterServer, "serve_forever", serve):
            self.assertEqual(0, production.run_writer(path, threading.Event(), host))
        admission.return_value.close.assert_called_once()
        self.assertTrue(channel.closed.is_set())
        self.assertEqual("STOPPED", host.statuses[-1]["state"])
        self.assertTrue(host.statuses[-1]["cleanupComplete"])

    def test_failed_storage_constructor_closes_native_backend(self):
        backend = SimpleNamespace(close=unittest.mock.Mock())
        with patch("momentum_hunter.windows_science_custody.open_science_custody_backend", return_value=backend), \
             patch("momentum_hunter.science_custody_mailbox.ScienceCustodyMailboxClient", side_effect=RuntimeError("fixture")):
            with self.assertRaises(RuntimeError):
                lifecycle.open_host_science_storage(self.config)
        backend.close.assert_called_once()

    def test_host_recorder_seals_then_restarts_without_direct_raw_writer(self):
        self.config["runtimeBuildHash"] = SOURCE_ROOT_IDENTITY
        self.config["host"]["science"]["custodyPolicy"]["source_root_identity"] = SOURCE_ROOT_IDENTITY
        seal(self.config)
        published = Path(self.config["researchFactExportV2"]["exportRoot"]) / "published"
        published.mkdir(parents=True)
        (Path(self.config["logRoot"]) / "science").mkdir(parents=True)
        for index, raw in enumerate(core_fixtures(), 1):
            publication(published, raw, index)
        original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in published.iterdir()}
        seen = []
        for generation in range(2):
            backend = host_filesystem_fixture(self.root, self.config)
            stop, host = threading.Event(), Host()
            stop.set()
            try:
                with patch("momentum_hunter.windows_science_custody.open_science_custody_backend", return_value=backend) as opened, \
                     patch.object(lifecycle, "upstream_generations", return_value={"writer": "w", "runtime": "r" + str(generation)}), \
                     patch.object(lifecycle, "completion", return_value=True), \
                     patch("momentum_hunter.strategy_science_continuous_recorder.WriterPhysicalStorage", side_effect=AssertionError("direct raw Writer")), \
                     patch("momentum_hunter.strategy_science_recorder.custody.WriterPhysicalStorage", side_effect=AssertionError("direct custody Writer")):
                    self.assertEqual(0, lifecycle.run_science(self.config, stop, host), host.statuses[-1])
                    self.assertEqual("science", opened.call_args.kwargs["role"])
                self.assertEqual("STOPPED", host.statuses[-1]["state"])
                self.assertTrue(host.statuses[-1]["drainComplete"])
                self.assertFalse(backend.thread.is_alive())
                self.assertFalse(backend.errors)
                seen.append(host.statuses[-1]["coverage"]["admitted_arrival_count"])
            finally:
                backend.close()
        self.assertEqual([5, 5], seen)
        self.assertEqual(original, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in published.iterdir()})


if __name__ == "__main__":
    unittest.main()
