from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter import continuous_host_contract as contract
from momentum_hunter import continuous_production as production
from tests.test_continuous_host_boundaries import configuration, save_config, seal


class InstalledSourceTopologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MH-013B-source006-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = configuration(self.root)
        self.source = self.root / "install" / "source"
        self.source.mkdir(parents=True)
        self.module = self.source / "momentum_hunter" / "continuous_host_contract.py"

    def loaded_from(self, root):
        return patch.object(contract, "__file__", str(root / "momentum_hunter" / "continuous_host_contract.py"))

    def assert_rejected(self, config=None):
        with self.assertRaises(contract.HostConfigurationError):
            contract.validate_host(config or self.config)

    def test_disjoint_external_checkout_is_admitted(self):
        self.assertEqual(contract.validate_host(self.config)["inputMode"], contract.OFFLINE)

    def test_exact_installed_role_and_plan_agree(self):
        with self.loaded_from(self.source):
            self.assertTrue(contract.validate_host(self.config)["scienceEnabled"])
            plan = contract.install_plan(self.config, save_config(self.config), self.source, Path(sys.executable))
        for role in plan["services"]:
            args = role["arguments"]
            self.assertEqual(Path(args[args.index("--repository-root") + 1]), self.source)
        self.assertFalse(plan["permissions"]["runtimeSource"]["write"])
        self.assertFalse(plan["windowsMutation"])

    def test_non_role_source_overlap_stays_rejected(self):
        for source in (self.root, self.root.parent, self.source.parent, self.root / "source",
                       self.source / "nested", self.source.with_name("source-other"), self.root / "runtime"):
            with self.subTest(source=str(source)), self.loaded_from(source):
                self.assert_rejected()

    def test_git_file_and_directory_on_role_or_ancestors_rejected(self):
        for parent in (self.source, self.source.parent, self.root):
            for directory in (False, True):
                marker = parent / ".git"
                if directory:
                    marker.mkdir()
                else:
                    marker.write_text("gitdir: absent-disposable-metadata", encoding="ascii")
                try:
                    with self.subTest(parent=str(parent), directory=directory), self.loaded_from(self.source):
                        self.assert_rejected()
                finally:
                    marker.rmdir() if directory else marker.unlink()

    def test_unreadable_git_metadata_is_not_absence(self):
        original = Path.lstat
        def checked(path, *args, **kwargs):
            if path == self.source / ".git":
                raise PermissionError("synthetic denied metadata inspection")
            return original(path, *args, **kwargs)
        with self.loaded_from(self.source), patch.object(Path, "lstat", checked):
            with self.assertRaisesRegex(contract.HostConfigurationError, "metadata is unreadable"):
                contract.validate_host(self.config)

    def test_writable_roots_cannot_overlap_install_tree(self):
        for name in (*contract.ROOT_FIELDS[1:], "scienceStateRoot", "exportRoot"):
            for value in (self.source, self.source / "nested", self.source.parent, self.source.parent / "sibling"):
                config = deepcopy(self.config)
                if name == "scienceStateRoot":
                    config["host"]["science"]["stateRoot"] = str(value)
                    config["researchFactExportV2"]["scienceCustodyRoots"] = [str(value)]
                elif name == "exportRoot":
                    config["researchFactExportV2"]["exportRoot"] = str(value)
                else:
                    config[name] = str(value)
                seal(config)
                with self.subTest(name=name, value=str(value)), self.loaded_from(self.source):
                    self.assert_rejected(config)

    def test_relative_and_ambiguous_install_paths_rejected(self):
        for value in ("install", "./install", str(self.root / "install."), str(self.root / "install "),
                      str(self.root / "NUL"), str(self.root / "install" / ".." / "install"),
                      "//server/share/install", str(self.root / "install") + ":stream"):
            config = deepcopy(self.config)
            config["installRoot"] = value
            seal(config)
            with self.subTest(value=value), self.loaded_from(self.source):
                self.assert_rejected(config)

    def test_relative_or_ambiguous_module_origin_rejected(self):
        for value in ("momentum_hunter/continuous_host_contract.py", str(self.module) + " ", str(self.module) + ":stream"):
            with self.subTest(value=value), patch.object(contract, "__file__", value):
                self.assert_rejected()

    @unittest.skipUnless(os.name == "nt", "Windows case equivalence")
    def test_windows_case_equivalent_role_admitted_and_collision_denied(self):
        config = deepcopy(self.config)
        config["installRoot"] = config["installRoot"].upper()
        seal(config)
        with self.loaded_from(Path(str(self.source).upper())):
            self.assertEqual(contract.validate_host(config)["inputMode"], contract.OFFLINE)
            config["runtimeStateRoot"] = str(self.source).swapcase()
            seal(config)
            self.assert_rejected(config)

    def test_installed_role_still_requires_mode_authority_and_fingerprint(self):
        for key, value in (("inputMode", contract.LIVE), ("inputMode", None), ("executionAuthority", "AVAILABLE"),
                           ("orderCapability", "AVAILABLE"), ("ipcPort", 49281), ("credentials", "synthetic")):
            config = deepcopy(self.config)
            config[key] = value
            seal(config)
            with self.subTest(key=key), self.loaded_from(self.source):
                self.assert_rejected(config)
        config = deepcopy(self.config)
        config["logRoot"] += "-changed"
        with self.loaded_from(self.source):
            self.assert_rejected(config)

    def test_real_reparse_source_and_state_paths_rejected(self):
        if os.name != "nt":
            self.skipTest("Physical Windows junction contract")
        target = self.root / "redirect-target"
        target.mkdir()
        paths = (self.source, self.source / "momentum_hunter", self.root / "logs")
        for alias in paths:
            if alias.exists():
                alias.rmdir()
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(target)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                self.assertTrue(alias.is_junction())
                with self.subTest(alias=str(alias)), self.loaded_from(self.source):
                    self.assert_rejected()
            finally:
                # Remove only the verified disposable junction, never its target.
                self.assertTrue(alias.is_relative_to(self.root) and alias.is_junction())
                alias.rmdir()
                if alias == self.source:
                    alias.mkdir()
        self.assertTrue(target.is_dir())

    def test_module_file_reparse_rejected_when_supported(self):
        self.module.parent.mkdir()
        target = self.root / "outside.py"
        target.write_text("# disposable source", encoding="ascii")
        try:
            self.module.symlink_to(target)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest("WinError1314: file symlink privilege unavailable; junction cases remain required")
            raise
        with self.loaded_from(self.source):
            self.assert_rejected()


class InstalledSourceEntrypointTests(unittest.TestCase):
    def test_actual_installed_import_and_unsafe_checkout_with_no_provider_construction(self):
        with tempfile.TemporaryDirectory(prefix="MH-013B-entry006-") as temporary:
            root = Path(temporary).resolve()
            config = configuration(root)
            path = save_config(config)
            source = root / "install" / "source"
            original = Path(contract.__file__).resolve().parents[1]
            shutil.copytree(original / "momentum_hunter", source / "momentum_hunter",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            code = r'''
import contextlib, io, json, os, sys
from pathlib import Path
from unittest.mock import patch
attempts = []
def deny(event, args):
    if event.startswith("socket.") and event != "socket.__new__":
        attempts.append(event)
        raise PermissionError("disposable entrypoint test prohibits network")
sys.addaudithook(deny)
from momentum_hunter import continuous_production as product
from momentum_hunter import continuous_host_contract as contract
assert Path(contract.__file__).resolve().is_relative_to(Path.cwd())
out = io.StringIO()
try:
    with patch.object(product, "LiveDiscoverySource") as discovery, patch.object(product, "LiveMarketDataSource") as market:
        with contextlib.redirect_stdout(out):
            result = product.main(["--config", sys.argv[1], "--print-install-plan"])
        discovery.assert_not_called()
        market.assert_not_called()
    print(json.dumps({"result": result, "root": str(Path(contract.__file__).resolve().parents[1]), "plan": json.loads(out.getvalue()), "deniedSocketEvents": attempts}))
except contract.HostConfigurationError as error:
    print(json.dumps({"rejected": str(error), "deniedSocketEvents": attempts}))
    raise SystemExit(2)
'''
            environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH") if key in os.environ}
            environment.update(USERPROFILE=str(root), LOCALAPPDATA=str(root / "profile"), APPDATA=str(root / "profile"),
                               PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTHONUTF8="1", TMP=str(root), TEMP=str(root),
                               SCHWAB_TOKEN="synthetic-not-a-credential", FINVIZ_MODE="LIVE_PRODUCTION")
            command = [sys.executable, "-B", "-c", code, str(path)]
            positive = subprocess.run(command, cwd=source, env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(positive.returncode, 0, positive.stderr + positive.stdout)
            data = json.loads(positive.stdout)
            self.assertEqual(Path(data["root"]), source)
            self.assertEqual(data["result"], 0)
            self.assertEqual(data["plan"]["environment"]["providerCredentials"], "NOT_REQUIRED_OR_PROPAGATED")
            (source / ".git").write_text("gitdir: not-a-real-repository", encoding="ascii")
            negative = subprocess.run(command, cwd=source, env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(negative.returncode, 2, negative.stderr + negative.stdout)
            self.assertIn("source checkout", json.loads(negative.stdout)["rejected"])


if __name__ == "__main__":
    unittest.main()
