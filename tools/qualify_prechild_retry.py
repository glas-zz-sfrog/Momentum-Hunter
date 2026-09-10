"""Bounded, external-output qualification of the prechild source and exact binary."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, sort_keys=True)


def qualify(source, output, head, python, full_python, packaged_binary=None):
    source, output, python = source.resolve(), output.resolve(), python.resolve()
    if output.exists() or output.is_relative_to(source) or "ProgramData" in output.parts:
        raise ValueError("New external qualification output required")
    output.mkdir(parents=True)
    env = dict(os.environ, DOTNET_SKIP_FIRST_TIME_EXPERIENCE="1", DOTNET_GENERATE_ASPNET_CERTIFICATE="false",
        DOTNET_CLI_TELEMETRY_OPTOUT="1", MSBUILDDISABLENODEREUSE="1", PYTHONDONTWRITEBYTECODE="1",
        GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    base = subprocess.run([str(python), "-B", "-c", "import sys; print(sys._base_executable)"],
        capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    results = []
    if (source / ".git").exists():
        tracked = subprocess.run(["git", "--no-optional-locks", "-C", str(source), "ls-files", "-z"],
            check=True, capture_output=True, timeout=30).stdout.decode().split("\0")
        source_paths = sorted(source / name for name in tracked if name)
    else:
        source_paths = sorted(p for p in source.rglob("*") if p.is_file() and not any(
            part in {"bin", "obj", "__pycache__", ".git"} for part in p.relative_to(source).parts))
    before_source = {p.relative_to(source).as_posix(): sha(p) for p in source_paths}
    write(output / "SOURCE-BEFORE.json", before_source)
    def run(label, args, seconds=600, extra_env=None):
        started = time.monotonic()
        command = [str(x) for x in args]
        with (output / (label + ".stdout.txt")).open("x", encoding="utf-8") as out, \
             (output / (label + ".stderr.txt")).open("x", encoding="utf-8") as err:
            try:
                result = subprocess.run(command, cwd=source, env=dict(env, **(extra_env or {})), stdout=out, stderr=err, timeout=seconds)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
        record = {"label": label, "command": command, "exitCode": code, "elapsedSeconds": time.monotonic() - started,
            "status": "PASS" if code == 0 else "FAIL"}
        write(output / (label + ".json"), record)
        results.append(record)
        print(json.dumps(record), flush=True)
        return record
    props = ["-p:ContinuousIntegrationBuild=true", "-p:Deterministic=true", "-p:UseSharedCompilation=false",
             "-p:DeterministicSourcePaths=false", "-p:EnableSourceControlManagerQueries=false", "-p:EnableSourceLink=false",
             "-p:SourceRevisionId=" + head, "-p:PathMap=" + str(source) + "=/_/source"]
    run("dotnet-environment", ["dotnet", "--info"], 30)
    run("python-environment", [python, "-B", "-c",
        "import sys,json,importlib.metadata as m; print(json.dumps({'executable':sys.executable,'baseExecutable':sys._base_executable,'version':sys.version,'distributions':sorted((d.metadata['Name'],d.version) for d in m.distributions())}))"], 30)
    run("powershell-environment", ["pwsh", "-NoProfile", "-NonInteractive", "-Command",
        "@{version=$PSVersionTable.PSVersion.ToString();framework=[Runtime.InteropServices.RuntimeInformation]::FrameworkDescription;executable=(Join-Path $PSHOME 'pwsh.exe');sha256=(Get-FileHash -LiteralPath (Join-Path $PSHOME 'pwsh.exe') -Algorithm SHA256).Hash}|ConvertTo-Json"], 30)
    run("native-build", ["dotnet", "build", "src/MomentumHunter.AutomationService", "-t:Rebuild", "-c", "Release", *props])
    run("probe-build", ["dotnet", "build", "tests-dotnet/MomentumHunter.Containment.Probe", "-t:Rebuild", "-c", "Release", *props])
    built = source / "src/MomentumHunter.AutomationService/bin/Release/net8.0"
    binary = {p.relative_to(built).as_posix(): sha(p) for p in built.rglob("*") if p.is_file() and p.suffix.lower() in {".dll", ".exe", ".json"}}
    mismatch = []
    if packaged_binary:
        packaged_binary = packaged_binary.resolve()
        expected = {p.relative_to(packaged_binary).as_posix(): sha(p) for p in packaged_binary.rglob("*") if p.is_file() and p.suffix.lower() in {".dll", ".exe", ".json"}}
        mismatch = [key for key in sorted(set(binary) | set(expected)) if binary.get(key) != expected.get(key)]
    write(output / "BINARY-SOURCE-BINDING.json", {"head": head, "binary": binary, "buildProperties": props,
        "packagedBinaryMismatch": mismatch, "status": "PASS" if not mismatch else "FAIL",
        "sourceRoot": str(source), "executionBinaryRoot": str(packaged_binary or built)})
    host = (packaged_binary or built) / "MomentumHunter.AutomationService.exe"
    fixture_root = output / "native-temp"
    fixture_root.mkdir()
    native_env = {"MH_CONTAINMENT_TEST_PYTHON": base, "MH_CONTAINMENT_TEST_VENV": str(python),
        "TEMP": str(fixture_root), "TMP": str(fixture_root),
        "MH_CONTAINMENT_TEST_HOST": str(host),
        "MH_CONTAINMENT_TEST_PROBE": str(source / "tests-dotnet/MomentumHunter.Containment.Probe/bin/Release/net8.0/MomentumHunter.Containment.Probe.exe")}
    fixture_before = set(fixture_root.glob("MH-Prechild-*"))
    for project in ("Integration", "Presentation", "Layout"):
        # Presentation tests intentionally resolve XAML from CallerFilePath. Mapping
        # their test source to a fictional deterministic root breaks those tests.
        # They do not reference the native host, whose binary remains reproducible.
        test_props = props if project == "Integration" else ["-p:ContinuousIntegrationBuild=false",
            "-p:Deterministic=true", "-p:UseSharedCompilation=false", "-p:SourceRevisionId=" + head]
        run("dotnet-" + project.lower(), ["dotnet", "test", "tests-dotnet/MomentumHunter." + project + ".Tests",
            "-c", "Release", *test_props, "--logger", "trx;LogFileName=" + project + ".trx", "--results-directory", output], extra_env=native_env)
    fixtures = []
    for root in sorted(set(fixture_root.glob("MH-Prechild-*")) - fixture_before):
        if root.is_dir() and not root.is_symlink():
            for file in sorted(root.rglob("*")):
                if file.is_file() and not file.is_symlink():
                    destination = output / "native-fixtures" / root.name / file.relative_to(root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(file, destination)
                    fixtures.append({"source": str(file), "path": destination.relative_to(output).as_posix(), "sha256": sha(destination)})
    write(output / "NATIVE-FIXTURE-INVENTORY.json", fixtures)
    modules = sorted(p.stem for p in (source / "tests").glob("test_*.py"))
    write(output / "PYTHON-DISCOVERY.json", {"modules": modules, "moduleCount": len(modules)})
    focused = ["tests." + m for m in modules if m.startswith(("test_automation", "test_opening_runtime", "test_prechild"))]
    run("python-focused", [python, "-B", "-m", "unittest", *focused, "-v"], 900)
    if full_python:
        run("python-full", [python, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], 3600)
    run("compileall", [python, "-B", "-m", "compileall", "-q", "momentum_hunter", "tools", "tests"],
        extra_env={"PYTHONPYCACHEPREFIX": str(output / "pycache")})
    parse = "$bad=@(); foreach($f in @('tools/invoke_prechild_automation_retry.ps1','tools/automation_retry_workflow.psm1','tests/test_automation_retry_workflow.ps1','tests/test_prechild_quiesce.ps1')) {$t=$null;$e=$null;[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD $f),[ref]$t,[ref]$e)|Out-Null;foreach($x in $e){$bad+=@{file=$f;error=$x.Message}}}; @($bad)|ConvertTo-Json; if($bad.Count){exit 1}"
    run("powershell-parse", ["pwsh", "-NoProfile", "-NonInteractive", "-Command", parse])
    native_counts = []
    for path in output.glob("*.trx"):
        root = ET.parse(path).getroot()
        counts = next((e.attrib for e in root.iter() if e.tag.endswith("}Counters")), {})
        tier_one = [e for e in root.iter() if e.tag.endswith("}UnitTestResult")
            and any(name in e.get("testName", "") for name in ("Prechild", "RetryLaunchGate"))]
        native_counts.append({"file": path.name, "counts": counts,
            "tierOneCount": len(tier_one), "tierOneNotPassed": [e.get("testName") for e in tier_one if e.get("outcome") != "Passed"]})
    failures = [r["label"] for r in results if r["status"] != "PASS"]
    if mismatch: failures.append("binary-source-rebuild")
    if not any(c["tierOneCount"] for c in native_counts) or any(c["tierOneNotPassed"] for c in native_counts):
        failures.append("missing-or-unpassed-tier-one-native-test")
    drift = [name for name, expected in before_source.items() if not (source / name).is_file() or sha(source / name) != expected]
    write(output / "SOURCE-AFTER.json", {"status": "PASS" if not drift else "FAIL", "changedPaths": drift, "fileCount": len(before_source)})
    if drift: failures.append("source-byte-drift-during-qualification")
    summary = {"status": "PASS" if not failures else "FAIL", "failures": failures, "head": head,
        "fullPythonIncluded": full_python, "native": native_counts, "commands": results,
        "finishedAt": datetime.now(timezone.utc).isoformat(), "productionServiceOperations": 0, "providerCallsAuthorized": 0}
    write(output / "QUALIFICATION.json", summary)
    return summary


def main():
    p = argparse.ArgumentParser()
    for name in ("source", "output", "python"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--full-python", action="store_true")
    p.add_argument("--packaged-binary", type=Path)
    args = p.parse_args()
    result = qualify(args.source, args.output, args.head, args.python, args.full_python, args.packaged_binary)
    print(json.dumps({"status": result["status"], "failures": result["failures"], "output": str(args.output)}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
