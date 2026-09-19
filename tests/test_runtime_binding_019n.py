"""Real compiled worker launch; disposable fixtures, not SCM/runtime acceptance."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

from tests.test_continuous_host_boundaries import configuration, seal


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "tests-dotnet/MomentumHunter.RuntimeBinding.Probe/MomentumHunter.RuntimeBinding.Probe.csproj"
PROBE = "MomentumHunter.RuntimeBinding.Probe.exe"
SECRET = re.compile("SCHWAB|FINVIZ|ALPACA|IBKR|MH_CANARY|API_KEY|API_SECRET|OAUTH|ACCESS_TOKEN|REFRESH_TOKEN", re.I)

# Only the domain callback is replaced in the disposable package. main(), config
# validation, HostGeneration, stdin STOP and OfflineNetworkGuard are real Product.
FIXTURE_INIT = r'''
import json, os, sys, time
from pathlib import Path
from momentum_hunter import continuous_production as _product
from momentum_hunter import continuous_host_generation as _generation

_case = Path(os.environ["ARGUS_019N_PROBE_ROOT"])
def _fixture_runtime(config_path, stop, host):
    import tzdata
    denied = False
    try:
        sys.audit("socket.gethostbyname", "fixture.invalid")
    except PermissionError:
        denied = True
    value = {"scope": "TEST_CALLBACK_NOT_DOMAIN_RUNTIME", "pid": os.getpid(),
        "parentPid": os.getppid(), "birth": _generation.process_birth(os.getpid()),
        "executable": sys.executable, "generation": host.generation,
        "sysPath": sys.path, "productionModule": _product.__file__,
        "generationModule": _generation.__file__, "tzdataModule": tzdata.__file__,
        "timezone": str(_product.CENTRAL), "networkAuditDenied": denied,
        "isolated": sys.flags.isolated, "noSite": sys.flags.no_site,
        "noBytecode": sys.dont_write_bytecode, "sitecustomizeLoaded": "sitecustomize" in sys.modules,
        "diagnosticKeys": [k for k in os.environ if k.startswith("MH_QUALIFICATION_DIAGNOSTIC_")],
        "credentialKeys": [k for k in os.environ if k.endswith("API_KEY")]}
    _generation.replace_status(_case / "child-observation.json", value)
    print("FIXTURE_CHILD_ADMITTED:" + str(os.getpid()), flush=True)
    print("FIXTURE_STDERR_DRAIN", file=sys.stderr, flush=True)
    if not stop.wait(20):
        return 9
    (_case / "stdio-stop-observed").write_text("STOP", encoding="ascii")
    host.status("STOPPED", drainComplete=True, cleanupComplete=True, pendingWork=0,
                proofScope="FIXTURE_CALLBACK_ONLY")
    return 7 if os.environ.get("ARGUS_019N_PROBE_MODE") == "child-failure" else 0

_product.run_runtime = _fixture_runtime
_generation.replace_status(_case / "pre-admission.json", {"pid": os.getpid(),
    "parentPid": os.getppid(), "birth": _generation.process_birth(os.getpid())})
_deadline = time.monotonic() + 20
while not (_case / "release").exists():
    if time.monotonic() > _deadline:
        raise RuntimeError("TEST_RELEASE_DEADLINE")
    time.sleep(0.01)
'''


@unittest.skipUnless(os.name == "nt", "Windows direct/redirector PID and manifest lease proof")
class CompiledRuntimeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        evidence = os.environ.get("ARGUS_RUNTIME_BINDING_EVIDENCE")
        cls.temporary = None if evidence else tempfile.TemporaryDirectory(prefix="mh-019n-binding-")
        cls.root = Path(evidence or cls.temporary.name).resolve()
        cls.root.mkdir(parents=True, exist_ok=True)
        cls.image = cls.root / "install"
        if cls.image.exists():
            raise RuntimeError("Use a fresh evidence root; previous receipts must not be overwritten")
        cls.image.mkdir()
        cls.env = {k: v for k, v in os.environ.items() if not SECRET.search(k)
                   and not k.startswith("PYTHON") and not k.startswith("MH_QUALIFICATION_DIAGNOSTIC_")}
        cls.env.update(PYTHONDONTWRITEBYTECODE="1", DOTNET_CLI_TELEMETRY_OPTOUT="1",
                       DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE="1")
        cache = Path(os.environ["USERPROFILE"]) / ".nuget/packages"
        cls.command("restore", ["dotnet", "restore", str(PROJECT), "--source", str(cache), "-p:NuGetAudit=false"])
        cls.command("build", ["dotnet", "build", str(PROJECT), "--no-restore", "-c", "Release",
                              "-p:NuGetAudit=false", "-o", str(cls.root / "compiled")])
        shutil.copytree(cls.root / "compiled", cls.image / "host")
        cls.executable = cls.image / "host" / PROBE
        base = Path(sys.base_prefix)
        pinned = cls.image / "python-base"
        pinned.mkdir()
        for path in [base / "python.exe", *base.glob("*.dll")]:
            shutil.copyfile(path, pinned / path.name)
        ignored = shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages", "test", "tests", "idlelib", "tkinter", "turtledemo")
        shutil.copytree(base / "Lib", pinned / "Lib", ignore=ignored)
        shutil.copytree(base / "DLLs", pinned / "DLLs", ignore=ignored)
        cls.command("venv", [str(pinned / "python.exe"), "-B", "-m", "venv", "--without-pip", str(cls.image / "python")])
        tzdata = Path(sys.prefix) / "Lib/site-packages/tzdata"
        if not tzdata.is_dir():
            raise RuntimeError("Approved .venv tzdata is required")
        shutil.copytree(tzdata, cls.image / "python/Lib/site-packages/tzdata", ignore=ignored)
        cls.source = cls.image / "source"
        package = cls.source / "momentum_hunter"
        shutil.copytree(ROOT / "momentum_hunter", package, ignore=ignored)
        (package / "__init__.py").write_text(FIXTURE_INIT, encoding="ascii")
        (cls.image / "science-authority.json").write_text('{"scope":"TEST_ONLY_NOT_AUTHORITY"}', encoding="ascii")
        cls.paths = ["python-base/Lib", "python-base/DLLs", "python/Lib/site-packages", "source"]
        cls.manifest = {"profile": "SCIENCE_DIRECT_IMAGE_V1", "pythonDll": "python-base/python312.dll",
            "pythonPaths": cls.paths, "files": []}
        cls.inventory()
        cls.poison = cls.root / "poison"
        cls.poison.mkdir()
        (cls.poison / "sitecustomize.py").write_text("raise RuntimeError('UNTRUSTED_SITE')\n", encoding="ascii")
        (cls.poison / "json.py").write_text("raise RuntimeError('UNTRUSTED_JSON')\n", encoding="ascii")

    @classmethod
    def tearDownClass(cls):
        if cls.temporary is not None:
            cls.temporary.cleanup()

    @classmethod
    def command(cls, name, args):
        result = subprocess.run(args, cwd=ROOT, env=cls.env, capture_output=True, text=True, timeout=180)
        (cls.root / (name + ".command.json")).write_text(json.dumps(args), encoding="ascii")
        (cls.root / (name + ".stdout.log")).write_text(result.stdout, encoding="utf-8")
        (cls.root / (name + ".stderr.log")).write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{name} failed ({result.returncode}); receipts: {cls.root}\n{result.stdout}\n{result.stderr}")

    @classmethod
    def inventory(cls):
        cls.manifest["files"] = [{"path": p.relative_to(cls.image).as_posix(), "length": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(cls.image.rglob("*"))
            if p.is_file() and p.name != "science-image-manifest.json"]

    def run_probe(self, mode, *, mutate_config=None, source=None, python=None, poison=True, missing_manifest=False):
        case = self.root / "cases" / (mode + "-" + uuid.uuid4().hex)
        case.mkdir(parents=True)
        manifest_bytes = json.dumps(self.manifest, ensure_ascii=True).encode("ascii")
        (self.image / "science-image-manifest.json").write_bytes(manifest_bytes)
        config = configuration(self.root)
        config["logRoot"] = str(case / "logs")
        config["hostStateRoot"] = str(case / "supervision")
        config["configRoot"] = str(case / "config")
        config["ipcKeyPath"] = str(case / "config/writer.key")
        config["host"]["science"]["imageManifestSha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        if mode == "matrix":
            config["host"]["science"]["custodyPolicy"]["actor_profile"] = {"profile": "bounded-existing-scm-writer-v1",
                "writer": {"python_path": str(self.image / "python-base/python.exe")}}
        if mutate_config:
            mutate_config(config)
        seal(config)
        path = case / "config/continuous-deployment.json"
        path.parent.mkdir()
        path.write_text(json.dumps(config, ensure_ascii=True), encoding="ascii")
        if missing_manifest:
            (self.image / "science-image-manifest.json").unlink()
        env = dict(self.env, ARGUS_019N_PROBE_ROOT=str(case), ARGUS_019N_PROBE_MODE=mode)
        env.update(OPENAI_API_KEY="FIXTURE_NOT_A_CREDENTIAL", FINVIZ_API_KEY="FIXTURE_NOT_A_CREDENTIAL")
        if poison:
            env.update(PYTHONPATH=str(self.poison), PYTHONHOME=str(self.poison), PYTHONUSERBASE=str(self.poison),
                       MH_QUALIFICATION_DIAGNOSTIC_ROOT=str(case / "stale-diagnostic"),
                       MH_QUALIFICATION_DIAGNOSTIC_PIPE="STALE_FIXTURE_PIPE",
                       MH_QUALIFICATION_DIAGNOSTIC_PARENT_ACK="REQUIRED")
        command = [str(self.executable), mode, str(path), str(source or self.source),
                   str(python or self.image / "python/Scripts/python.exe"), str(case)]
        (case / "command.json").write_text(json.dumps(command), encoding="ascii")
        result = subprocess.run(command, env=env, cwd=self.source, capture_output=True, text=True, timeout=80)
        (case / "stdout.log").write_text(result.stdout, encoding="utf-8")
        (case / "stderr.log").write_text(result.stderr, encoding="utf-8")
        self.assertEqual(0, result.returncode, str(case) + "\n" + result.stderr)
        receipt = json.loads(result.stdout)
        (case / "result.json").write_text(json.dumps(receipt, indent=2), encoding="ascii")
        return receipt, case, result.stderr

    @contextmanager
    def manifest_change(self):
        before = json.loads(json.dumps(self.manifest))
        try:
            yield self.manifest
        finally:
            self.manifest.clear()
            self.manifest.update(before)

    def test_01_compiled_command_matrix_keeps_validator_and_other_modes(self):
        result, _, _ = self.run_probe("matrix")
        self.assertEqual("OBSERVED", result["status"], result)
        rows = result["rows"]
        runtime = rows["runtime-console"]
        self.assertTrue(runtime["imageBound"])
        self.assertEqual(str(self.image / "python-base/python.exe"), runtime["child"]["FileName"])
        self.assertEqual(["-I", "-S", "-B", "-X", "utf8", "-c"], runtime["child"]["arguments"][:6])
        self.assertEqual(str(self.image / "python/Scripts/python.exe"), runtime["validator"]["FileName"])
        self.assertEqual(["-B", "-m", "momentum_hunter.continuous_production"], runtime["validator"]["arguments"][:3])
        self.assertEqual("--print-install-plan", runtime["validator"]["arguments"][-1])
        for key in ("diagnosticRoot", "diagnosticPipe"):
            self.assertFalse(runtime["child"][key])
            self.assertTrue(runtime["validator"][key])
        for label in ("runtime-scm", "runtime-live", "runtime-legacy", "science-selection-only"):
            self.assertFalse(rows[label]["imageBound"])
            self.assertEqual(["-B", "-m", "momentum_hunter.continuous_production"], rows[label]["child"]["arguments"][:3])
        writer = rows["writer"]
        self.assertTrue(writer["imageBound"])
        for command in (writer["child"], writer["validator"]):
            self.assertEqual(str(self.image / "python-base/python.exe"), command["FileName"])
            self.assertEqual(["-I", "-S", "-B", "-X", "utf8", "-c"], command["arguments"][:6])
        self.assertEqual("--verify-writer-launch-profile", writer["validator"]["arguments"][-1])
        self.assertFalse(writer["validator"]["diagnosticRoot"])
        for label, row in rows.items():
            self.assertEqual([], row["validator"]["credentialKeys"])
            expected = ["FINVIZ_API_KEY"] if label in ("runtime-live", "runtime-legacy") else []
            self.assertEqual(expected, row["child"]["credentialKeys"])

    def assert_child(self, result, case, stderr, *, failure=False):
        self.assertEqual("OBSERVED", result["status"], result)
        if failure:
            self.assertIn("exited 7", result["workerResult"])
        else:
            self.assertEqual("EXIT_0", result["workerResult"], stderr)
        child, started = result["childObservation"], result["startedGeneration"]
        self.assertEqual(started["childPid"], child["pid"])
        self.assertEqual(started["childBirth"], child["birth"])
        self.assertEqual(started["supervisorPid"], child["parentPid"])
        self.assertEqual(started["generation"], child["generation"])
        self.assertEqual(str(self.image / "python-base/python.exe"), child["executable"])
        self.assertEqual("EXITED", result["terminalGeneration"]["phase"])
        self.assertEqual([], child["diagnosticKeys"])
        self.assertEqual([], child["credentialKeys"])
        self.assertEqual(1, child["isolated"])
        self.assertEqual(1, child["noSite"])
        self.assertTrue(child["noBytecode"])
        self.assertFalse(child["sitecustomizeLoaded"])
        self.assertEqual([str(self.image / p) for p in self.paths], child["sysPath"])
        self.assertTrue(Path(child["productionModule"]).is_relative_to(self.source))
        self.assertTrue(Path(child["generationModule"]).is_relative_to(self.source))
        self.assertTrue(Path(child["tzdataModule"]).is_relative_to(self.image / "python/Lib/site-packages"))
        self.assertEqual("America/Chicago", child["timezone"])
        self.assertTrue(child["networkAuditDenied"])
        self.assertTrue((case / "stdio-stop-observed").exists())
        self.assertIn("FIXTURE_STDERR_DRAIN", stderr)
        self.assertIn("FIXTURE_CHILD_ADMITTED", stderr)
        self.assertFalse(result["retainedChildAlive"])
        self.assertTrue(result["leaseHeldBeforeStop"])
        self.assertTrue(result["leaseHeldAfterExit"])
        self.assertTrue(result["leaseReleased"])
        network = json.loads(next((case / "logs/runtime").glob("network-*.json")).read_text())
        self.assertEqual(1, network["deniedProviderNetworkAttempts"])
        self.assertFalse(network["providerContact"])
        self.assertFalse(list(self.image.rglob("*.pyc")))

    def test_02_real_main_direct_pid_birth_isolation_and_stop(self):
        self.assert_child(*self.run_probe("direct"))

    def test_03_real_venv_redirector_is_rejected_by_unchanged_generation(self):
        result, _, stderr = self.run_probe("redirector", poison=False)
        self.assertIn("CURRENT_SUPERVISOR_GENERATION_NOT_BOUND", stderr)
        self.assertIn("exited 1", result["workerResult"])
        self.assertNotIn("childObservation", result)
        self.assertFalse(result["retainedChildAlive"])
        self.assertNotEqual(result["startedGeneration"]["childPid"], result["preAdmission"]["pid"])
        self.assertEqual(result["startedGeneration"]["childPid"], result["preAdmission"]["parentPid"])

    def test_04_generation_negatives_remain_rejected(self):
        for mode in ("wrong-pid", "wrong-birth", "wrong-supervisor-birth", "wrong-generation", "wrong-fingerprint", "missing-generation"):
            with self.subTest(mode=mode):
                result, _, stderr = self.run_probe(mode)
                self.assertIn("CURRENT_SUPERVISOR_GENERATION_NOT_BOUND", stderr)
                self.assertIn("exited 1", result["workerResult"])
                self.assertNotIn("childObservation", result)
                self.assertFalse(result["retainedChildAlive"])
                self.assertTrue(result["leaseHeldAfterExit"])
                self.assertTrue(result["leaseReleased"])

    def test_05_child_nonzero_exit_is_failure_not_restart(self):
        self.assert_child(*self.run_probe("child-failure"), failure=True)

    def test_06_generation_publication_failure_does_not_release_live_child(self):
        result, _, _ = self.run_probe("publication-failure")
        self.assertEqual("OBSERVED", result["status"], result)
        self.assertNotEqual("EXIT_0", result["workerResult"])
        self.assertNotIn("childObservation", result)
        self.assertFalse(result["retainedChildAlive"])
        self.assertTrue(result["leaseHeldAfterExit"])
        self.assertTrue(result["leaseReleased"])

    def assert_rejected(self, expected, **kwargs):
        result, case, _ = self.run_probe("image-check", **kwargs)
        self.assertEqual("REJECTED", result["status"], result)
        self.assertIn(expected, result["error"])
        self.assertFalse((case / "supervision").exists())

    def test_07_wrong_manifest_hash_source_and_validator_executable(self):
        self.assert_rejected("SCIENCE_IMAGE_MANIFEST_HASH_MISMATCH", mutate_config=lambda c: c["host"]["science"].update(imageManifestSha256="0" * 64))
        self.assert_rejected("NullReferenceException", mutate_config=lambda c: c["host"]["science"].pop("imageManifestSha256"))
        self.assert_rejected("SCIENCE_IMAGE_REPARSE_PATH", missing_manifest=True)
        self.assert_rejected("SCIENCE_SOURCE_ROOT_MISMATCH", source=self.poison)
        self.assert_rejected("pinned staged venv", python=self.image / "python-base/python.exe")

    def test_08_missing_base_membership_and_bad_hash(self):
        with self.manifest_change() as manifest:
            row = next(f for f in manifest["files"] if f["path"] == "python-base/python.exe")
            row["sha256"] = "0" * 64
            self.assert_rejected("SCIENCE_IMAGE_BYTE_MISMATCH:python-base/python.exe")
        with self.manifest_change() as manifest:
            manifest["files"] = [f for f in manifest["files"] if f["path"] != "python-base/python.exe"]
            base = self.image / "python-base/python.exe"
            saved = self.root / "temporarily-held-python.exe"
            base.rename(saved)
            try:
                self.assert_rejected("RUNTIME_DIRECT_INTERPRETER_UNBOUND")
            finally:
                saved.rename(base)

    def test_09_import_escape_extra_and_altered_image(self):
        with self.manifest_change() as manifest:
            manifest["pythonPaths"] = ["../poison", *self.paths]
            self.assert_rejected("SCIENCE_IMAGE_RELATIVE_PATH_INVALID")
        extra = self.source / "unlisted.py"
        extra.write_text("TEST_ONLY=1\n", encoding="ascii")
        try:
            self.assert_rejected("SCIENCE_IMAGE_INVENTORY_DRIFT")
        finally:
            extra.unlink()
        entry = self.source / "momentum_hunter/continuous_production.py"
        before = entry.read_bytes()
        entry.write_bytes(before + b"\n# Test-only byte tamper\n")
        try:
            self.assert_rejected("SCIENCE_IMAGE_BYTE_MISMATCH")
        finally:
            entry.write_bytes(before)

    def test_10_reparse_image_rejected_without_elevation(self):
        import _winapi
        junction = self.image / "junction"
        _winapi.CreateJunction(str(self.poison), str(junction))
        try:
            self.assert_rejected("SCIENCE_IMAGE_REPARSE_INVENTORY")
        finally:
            os.rmdir(junction)

    def test_11_poisoned_cwd_cannot_redirect_stdlib_or_site(self):
        files = [self.source / "json.py", self.source / "sitecustomize.py"]
        with self.manifest_change():
            for path in files:
                path.write_text("raise RuntimeError('CWD_IMPORT_POISON')\n", encoding="ascii")
            try:
                self.inventory()
                self.assert_child(*self.run_probe("direct"))
            finally:
                for path in files:
                    path.unlink()

    def test_12_pinned_executable_start_failure_preserves_original_error(self):
        executable = self.image / "python-base/python.exe"
        before = executable.read_bytes()
        with self.manifest_change():
            executable.write_bytes(b"INVALID_TEST_EXECUTABLE")
            try:
                self.inventory()
                result, _, _ = self.run_probe("start-failure")
                self.assertIn("Win32Exception", result["workerResult"])
                self.assertFalse(result["retainedChildAlive"])
                self.assertTrue(result["leaseReleased"])
            finally:
                executable.write_bytes(before)


if __name__ == "__main__":
    unittest.main()
