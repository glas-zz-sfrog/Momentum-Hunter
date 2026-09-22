from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from momentum_hunter import continuous_host_contract as contract
from momentum_hunter import continuous_host_lifecycle as lifecycle
from momentum_hunter import continuous_production as production
from tests.test_continuous_v2_producer import manifest


def custody_policy_fixture(science, instance, source_identity):
    """Configuration-only identities, never native/physical acceptance evidence."""
    from momentum_hunter.windows_science_custody import (
        CustodyRootBinding, ScienceCustodyPolicy, ROOT_NAMES,
    )
    roots = tuple(CustodyRootBinding(name, str(science / "reader" / "cursors" if name == "cursors" else science / name), (1, 0, index),
        "S-1-5-19", "0" * 64) for index, name in enumerate(sorted(ROOT_NAMES), 1))
    ancestors = tuple(CustodyRootBinding("ancestor", str(path), (1, 1, index),
        "S-1-5-18", "0" * 64) for index, path in enumerate((science / "reader", science, *science.parents), 1))
    policy = ScienceCustodyPolicy(source_root_identity=source_identity,
        science_sid=contract.science_service_sid(instance), writer_sid="S-1-5-19",
        science_group_sids=("S-1-1-0",), science_privilege_names=("SeChangeNotifyPrivilege",),
        science_integrity_sid="S-1-16-12288", object_integrity_sid="S-1-16-12288",
        roots=roots, ancestors=ancestors, max_artifact_bytes=4 * 1024 * 1024,
        max_request_bytes=65536, max_history_entries=100000, max_pinned_directories=1024,
        science_enabled_group_sids=("S-1-1-0",), science_enabled_privilege_names=("SeChangeNotifyPrivilege",))
    return json.loads(json.dumps(asdict(policy)))


def configuration(root, *, package=None, port=49393):
    root = Path(root).resolve()
    science = root / "science"
    start = manifest()
    config = {"schemaVersion": 2, "activationProfile": contract.PROFILE,
        "inputMode": contract.OFFLINE, "mode": "RESEARCH_ONLY", "executionAuthority": "NONE",
        "orderCapability": "UNAVAILABLE", "accountReads": "UNAVAILABLE", "positionReads": "UNAVAILABLE",
        "alpacaPaper": "UNAVAILABLE", "alpacaLive": "UNAVAILABLE", "shadowExecution": "UNAVAILABLE",
        "runtimeIdentity": "qual-013b-runtime", "runtimeBuildHash": "a" * 64,
        "evidenceProgramId": "offline-host-013b", "configurationSessionDate": "1970-01-01",
        "ipcHost": "127.0.0.1", "ipcPort": port, "ipcKeyPath": str(root / "config" / "writer.key"),
        "broadDiscoverySeconds": 300, "premarketDiscoverySeconds": 600,
        **{key: str(root / leaf) for key, leaf in zip(contract.ROOT_FIELDS, ("install", "runtime", "evidence", "config", "logs", "supervision"))},
        "host": {"instanceId": "qual-013b", "instanceRoot": str(root), "services": contract.service_names("qual-013b"),
            "shutdownSeconds": 30, "science": {"enabled": True, "stateRoot": str(science), "pollSeconds": 0.05, "maxItems": 64,
                "restrictingSid": contract.science_service_sid("qual-013b"),
                "hostingModel": contract.SCM_DIRECT, "imageManifestSha256": "b" * 64,
                "principal": "NT SERVICE\\MomentumHunterContinuous-qual-013b-Science",
                "custodyPolicy": custody_policy_fixture(science, "qual-013b", "a" * 64)}},
        "researchFactExportV2": {"exportRoot": str(root / "export"), "startManifest": start, "scienceCustodyRoots": [str(science)]},
        "offlineInput": {"packagePath": str(package or (root / "input.zip")),
            "packageSha256": "DAB6F1159893EFAD8F80669A8FCF7759B4473AD1E8252F27261634E3DBC9C831",
            "tickSeconds": 5, "wallPauseSeconds": 0.1, "maxTicks": 10}}
    config["configurationFingerprint"] = production.deployment_configuration_fingerprint(config)
    seal(config)
    return config


def seal(config):
    config["hostFingerprint"] = contract.host_fingerprint(config)


def save_config(config):
    path = Path(config["configRoot"]) / "continuous-deployment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=True), encoding="ascii")
    return path


class HostBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = configuration(self.root)

    def test_valid_offline_and_exact_install_plan(self):
        path = save_config(self.config)
        self.assertEqual(production._read_config(path), self.config)
        plan = contract.install_plan(self.config, path, self.root / "source", Path(sys.executable))
        self.assertEqual([x["role"] for x in plan["services"]], ["writer", "science", "runtime"])
        self.assertFalse(plan["windowsMutation"])
        self.assertEqual(plan["services"][2]["dependsOn"], [plan["services"][1]["name"]])
        self.assertEqual(plan["services"][1]["dependsOn"], [plan["services"][0]["name"]])
        self.assertEqual(plan["services"][1]["principal"], self.config["host"]["science"]["principal"])
        self.assertNotIn("MomentumHunterContinuousRuntime", [x["name"] for x in plan["services"]])

    def test_missing_or_invalid_mode_is_not_live_default(self):
        for value in (None, "", "live", "PAPER", 1, False):
            with self.subTest(value=value):
                config = deepcopy(self.config)
                if value is None: config.pop("inputMode")
                else: config["inputMode"] = value
                seal(config)
                with self.assertRaises(contract.HostConfigurationError): contract.validate_host(config)

    def test_legacy_is_recognized_not_generic_missing_mode(self):
        legacy = {"schemaVersion": 1, "activationProfile": contract.PROFILE, "mode": "RESEARCH_ONLY",
                  "runtimeIdentity": "production-continuous-runtime-v2", "orderCapability": "UNAVAILABLE"}
        self.assertEqual(contract.validate_host(legacy)["inputMode"], contract.LIVE)
        self.assertEqual(contract.validate_host(legacy)["services"]["runtime"], "MomentumHunterContinuousRuntime")
        for key in legacy:
            invalid = dict(legacy)
            invalid.pop(key)
            with self.subTest(key=key), self.assertRaises(contract.HostConfigurationError): contract.validate_host(invalid)

    def test_config_authority_increase_rejected(self):
        for key in ("executionAuthority", "orderCapability", "accountReads", "positionReads", "alpacaPaper", "alpacaLive", "shadowExecution"):
            config = deepcopy(self.config)
            config[key] = "AVAILABLE"
            seal(config)
            with self.subTest(key=key), self.assertRaises(contract.HostConfigurationError): contract.validate_host(config)

    def test_credentials_cannot_select_live(self):
        with patch.dict(os.environ, {"SCHWAB_TOKEN": "synthetic", "MH_CANARY_EXPECTED_ACCOUNT_ENDING": "synthetic", "FINVIZ_MODE": "LIVE_PRODUCTION"}):
            self.assertEqual(contract.validate_host(self.config)["inputMode"], contract.OFFLINE)
            contract.scrub_provider_environment()
            self.assertNotIn("SCHWAB_TOKEN", os.environ)
        for key in ("credentials", "oauth", "expectedAccountEnding", "token", "password"):
            config = deepcopy(self.config)
            config[key] = "synthetic"
            seal(config)
            with self.subTest(key=key), self.assertRaises(contract.HostConfigurationError): contract.validate_host(config)

    def test_live_mode_cannot_use_qualification_instance(self):
        self.config["inputMode"] = contract.LIVE
        seal(self.config)
        with self.assertRaises(contract.HostConfigurationError): contract.validate_host(self.config)

    def test_root_and_partial_overlap_collisions(self):
        for key in contract.ROOT_FIELDS:
            for value in (self.config["runtimeStateRoot"], str(Path(self.config["runtimeStateRoot"]) / "nested"), str(self.root.parent)):
                if key == "runtimeStateRoot" and value == self.config[key]: continue
                if key == "runtimeStateRoot" and value == str(Path(self.config[key]) / "nested"): continue
                config = deepcopy(self.config)
                config[key] = value
                seal(config)
                with self.subTest(key=key, value=value), self.assertRaises(contract.HostConfigurationError): contract.validate_host(config)

    def test_production_root_collision(self):
        for protected in contract.PRODUCTION_ROOTS:
            config = deepcopy(self.config)
            config["host"]["instanceRoot"] = str(protected.resolve())
            seal(config)
            with self.subTest(root=str(protected)), self.assertRaises(contract.HostConfigurationError): contract.validate_host(config)

    def test_same_production_service_or_port_rejected(self):
        for role in contract.ROLES:
            config = deepcopy(self.config)
            config["host"]["services"][role] = contract.service_names("production")[role]
            seal(config)
            with self.assertRaises(contract.HostConfigurationError): contract.validate_host(config)
        self.config["ipcPort"] = 49281
        seal(self.config)
        with self.assertRaises(contract.HostConfigurationError): contract.validate_host(self.config)

    def test_fingerprint_binds_modes_roots_replay_and_science(self):
        original = self.config["hostFingerprint"]
        for name in ("logRoot", "runtimeStateRoot", "inputMode"):
            config = deepcopy(self.config)
            config[name] += "altered"
            self.assertNotEqual(contract.host_fingerprint(config), original)
            with self.assertRaises(contract.HostConfigurationError): contract.validate_host(config)

    def test_config_path_and_ipc_key_outside_root_rejected(self):
        with self.assertRaises(contract.HostConfigurationError): contract.validate_host(self.config, self.root / "wrong.json")
        self.config["ipcKeyPath"] = str(self.root / "outside.key")
        seal(self.config)
        with self.assertRaises(contract.HostConfigurationError): contract.validate_host(self.config)

    def test_replay_wrong_package_fails_before_sources(self):
        path = Path(self.config["offlineInput"]["packagePath"])
        path.write_bytes(b"not an accepted replay")
        with patch("momentum_hunter.continuous_live_qualification.LiveDiscoverySource") as discovery, patch("momentum_hunter.continuous_live_qualification.LiveMarketDataSource") as market:
            with self.assertRaises(ValueError): lifecycle.retained_inputs(self.config)
            discovery.assert_not_called()
            market.assert_not_called()

    def test_network_guard_exact_endpoint_only(self):
        guard = contract.OfflineNetworkGuard("127.0.0.1", 49393, "runtime")
        guard("socket.connect", (None, ("127.0.0.1", 49393)))
        for host in ("finviz.com", "api.schwabapi.com", "api.alpaca.markets", "localhost", "127.0.0.1"):
            with self.subTest(host=host), self.assertRaises(PermissionError): guard("socket.connect", (None, (host, 443)))
        with self.assertRaises(PermissionError): guard("socket.bind", (None, ("127.0.0.1", 49393)))
        science = contract.OfflineNetworkGuard("127.0.0.1", 49393, "science")
        with self.assertRaises(PermissionError): science("socket.connect", (None, ("127.0.0.1", 49393)))

    def test_real_socket_denied_in_disposable_process(self):
        command = "from momentum_hunter.continuous_host_contract import OfflineNetworkGuard; import socket; g=OfflineNetworkGuard('127.0.0.1',49393,'science'); g.install(); socket.create_connection(('127.0.0.1',49393))"
        result = subprocess.run([sys.executable, "-B", "-c", command], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OFFLINE_QUALIFICATION denies", result.stderr)
