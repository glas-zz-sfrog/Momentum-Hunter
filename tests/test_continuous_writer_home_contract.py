from __future__ import annotations

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import unittest

from tests.test_continuous_host_boundaries import configuration, save_config, seal


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import sys,json,os
from pathlib import Path
from unittest.mock import patch, MagicMock
denied=[]
def audit(event,args):
    if event.startswith('socket.'):
        denied.append(event)
        raise PermissionError('ZERO_NETWORK_TEST')
sys.addaudithook(audit)
def no_home(*args,**kwargs):
    raise AssertionError('HOME_MUST_NOT_BE_QUERIED')
# sysconfig may expand unrelated installation metadata; only a real home
# requirement is forbidden. Isolated imports below must ignore those paths.
with patch.object(Path,'home',no_home):
    from momentum_hunter import continuous_production as p
    from momentum_hunter.continuous_science_service import NativeStopEvent
    config_path=Path(sys.argv[1])
    mode=sys.argv[2]
    if mode=='reject':
        try: p._read_config(config_path)
        except (ValueError,RuntimeError): result='REJECTED'
        else: raise AssertionError('INVALID_CONFIG_ACCEPTED')
    else:
        config=p._read_config(config_path)
        result='CONFIG_ACCEPTED'
        if mode in ('writer','writer-failure'):
            events=[]
            admission=MagicMock()
            admission.close.side_effect=lambda:events.append('ADMISSION_CLOSED')
            server=MagicMock()
            server.science_custody_status={'state':'STOPPED','threadAlive':False}
            server.close.side_effect=lambda:events.append('SERVER_CLOSED')
            def serve(*args):
                events.append('SERVE_ENTERED')
                if mode=='writer-failure': raise RuntimeError('CONTROLLED_SERVE_FAILURE')
                return True
            server.serve_forever.side_effect=serve
            def admit(*args): events.append('NATIVE_ADMISSION_CALLED'); return admission
            with patch('momentum_hunter.windows_writer_profile.NativeWriterAdmission',side_effect=admit), patch.object(p,'ProductionWriterServer',return_value=server):
                try: result=p.run_writer(config_path)
                except RuntimeError as exc:
                    assert str(exc)=='CONTROLLED_SERVE_FAILURE'
                    result='EXPECTED_SERVE_FAILURE'
            assert events==['NATIVE_ADMISSION_CALLED','SERVE_ENTERED','SERVER_CLOSED','ADMISSION_CLOSED'],events
            assert result==(0 if mode=='writer' else 'EXPECTED_SERVE_FAILURE')
            result='UNIT_CONTROL_FLOW_PASS_NOT_NATIVE_AUTHORITY'
assert not denied,denied
assert not any(n.startswith(('momentum_hunter.schwab','momentum_hunter.finviz','momentum_hunter.continuous_live_qualification')) for n in sys.modules)
assert 'site' not in sys.modules
assert not any(n in sys.modules for n in ('sitecustomize','usercustomize','home_injected'))
print(json.dumps({'result':result,'homeUsed':False,'providerImports':False,'nativeAuthorityProven':False,'isolated':sys.flags.isolated,'noSite':sys.flags.no_site}))
'''


class WriterHomeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = configuration(self.root)
        self.config_path = save_config(self.config)

    def probe(self, mode="config", injected=None, path=None):
        env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP", "ProgramData") if k in os.environ}
        env["PATH"] = str(Path(os.environ.get("SystemRoot", "/")) / "System32")
        env.update(injected or {})
        paths = [str(Path(sys.base_prefix) / "Lib"), str(Path(sys.base_prefix) / "DLLs"),
                 sysconfig.get_path("purelib"), str(ROOT)] if os.name == "nt" else [p for p in sys.path if p] + [str(ROOT)]
        code = "import sys;sys.path[:]=" + repr(paths) + ";sys.argv=" + repr(["probe", str(path or self.config_path), mode]) + ";" + PROBE
        proc = subprocess.run([sys.executable, "-I", "-S", "-B", "-X", "utf8", "-c", code],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_no_home_or_profile_is_required_for_configuration_import(self):
        self.assertEqual("CONFIG_ACCEPTED", self.probe()["result"])

    def test_all_home_and_python_environment_injections_are_irrelevant(self):
        for value in (str(self.root / "malicious-profile"), "relative/profile", "../escape", r"\\invalid-host\profile", str(self.root / "unowned")):
            with self.subTest(value=value):
                env = {key: value for key in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE")}
                env["PYTHONNOUSERSITE"] = "0"
                self.assertEqual("CONFIG_ACCEPTED", self.probe(injected=env)["result"])

    def test_user_site_and_current_directory_do_not_supply_code(self):
        for name in ("sitecustomize.py", "usercustomize.py", "home_injected.py"):
            (self.root / name).write_text("raise AssertionError('UNTRUSTED_IMPORT')", encoding="ascii")
        self.probe(injected={"PYTHONPATH": str(self.root), "PYTHONUSERBASE": str(self.root), "USERPROFILE": str(self.root)})

    def test_writer_startup_calls_admission_and_server_without_provider_import(self):
        self.assertEqual("UNIT_CONTROL_FLOW_PASS_NOT_NATIVE_AUTHORITY", self.probe("writer")["result"])

    def test_writer_serve_failure_still_closes_server_and_admission(self):
        self.assertEqual("UNIT_CONTROL_FLOW_PASS_NOT_NATIVE_AUTHORITY", self.probe("writer-failure")["result"])

    def test_authority_and_fingerprint_rejections_are_not_bypassed(self):
        for key, value in (("mode", "LIVE"), ("orderCapability", "AVAILABLE"), ("activationProfile", "other"),
                           ("configurationFingerprint", "0" * 64), ("hostFingerprint", "0" * 64),
                           ("executionAuthority", "LIVE"), ("providerAuthority", "ENABLED")):
            with self.subTest(key=key):
                config = deepcopy(self.config)
                config[key] = value
                save_config(config)
                self.assertEqual("REJECTED", self.probe("reject")["result"])

    def test_wrong_service_identity_and_relative_resource_are_rejected(self):
        for kind in ("service", "path"):
            config = deepcopy(self.config)
            if kind == "service":
                config["host"]["services"]["writer"] = "MomentumHunterContinuous-other-Writer"
            else:
                config["logRoot"] = "relative/logs"
            seal(config)
            save_config(config)
            self.assertEqual("REJECTED", self.probe("reject")["result"])

    def test_provider_import_is_inside_runtime_only(self):
        tree = ast.parse((ROOT / "momentum_hunter/continuous_production.py").read_bytes())
        top = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "momentum_hunter.continuous_live_qualification"]
        self.assertEqual([], top)
        runtime = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run_runtime")
        self.assertIsInstance(runtime.body[0], ast.ImportFrom)
        self.assertEqual("momentum_hunter.continuous_live_qualification", runtime.body[0].module)
        self.assertEqual({"LiveCompositionSource", "LiveDenominatorSource", "LiveDiscoverySource", "LiveMaterialEvents", "LiveMarketDataSource", "QualificationState"}, {n.name for n in runtime.body[0].names})

    def test_replay_models_load_only_when_replay_is_requested(self):
        tree = ast.parse((ROOT / "momentum_hunter/preserved_provider_replay.py").read_bytes())
        modules = {"momentum_hunter.broad_discovery", "momentum_hunter.continuous_tradeplan_producer"}
        self.assertFalse(any(isinstance(n, ast.ImportFrom) and n.module in modules for n in tree.body))
        loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_preserved_provider_replay")
        self.assertEqual(modules, {n.module for n in loader.body if isinstance(n, ast.ImportFrom)})


if __name__ == "__main__":
    unittest.main()
