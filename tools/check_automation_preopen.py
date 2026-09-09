"""Read-only guardian CLI. Writes only new operator-selected external reports."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from momentum_hunter.automation_preopen_guardian import inspect_readiness, parse_session_date


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-date", type=parse_session_date, required=True)
    for name in ("manifest", "state", "continuous", "canonical", "output-root", "expectations"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("expected-manifest-sha256", "expected-continuous-sha256", "expected-canonical", "expected-expectations-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    from momentum_hunter.automation_state_recovery import digest
    raw_expectations = args.expectations.read_bytes()
    if digest(raw_expectations) != args.expected_expectations_sha256.lower():
        parser.error("Expected guardian contract hash does not match.")
    expectations = json.loads(raw_expectations)
    output = args.output_root.resolve()
    protected = [args.canonical.resolve(), Path(os.environ.get("ProgramData", "C:/ProgramData")).resolve(),
                 args.state.parent.resolve(), args.manifest.parent.resolve(), args.continuous.parent.resolve()]
    if any(output == p or output.is_relative_to(p) for p in protected):
        parser.error("Guardian reports must use a separate external output root.")
    def git(*command):
        result = subprocess.run(["git", "--no-optional-locks", "-C", str(args.canonical), *command],
            capture_output=True, text=True, timeout=15, check=True)
        return result.stdout.strip()
    service_query = "Get-CimInstance Win32_Service -Filter \"Name LIKE 'MomentumHunter%'\" | Select-Object Name,State,StartMode,StartName,PathName | ConvertTo-Json -Compress"
    services = {}
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", service_query],
            capture_output=True, text=True, timeout=20, check=True)
        values = json.loads(result.stdout)
        services = {v["Name"]: v for v in (values if isinstance(values, list) else [values])}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        head, origin, clean = git("rev-parse", "HEAD"), git("rev-parse", "origin/master"), not git("status", "--porcelain")
    except (OSError, subprocess.SubprocessError):
        head, origin, clean = "UNAVAILABLE", "UNAVAILABLE", False
    report = inspect_readiness(manifest_path=args.manifest, state_path=args.state, continuous_path=args.continuous,
        expected_manifest_sha256=args.expected_manifest_sha256, expected_continuous_sha256=args.expected_continuous_sha256,
        canonical_head=head, origin_head=origin, canonical_clean=clean, expected_canonical=args.expected_canonical,
        services=services, session_date=args.session_date.isoformat(), now=datetime.now().astimezone(), expectations=expectations)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "TOMORROW-OPENING-READINESS.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
    with (output / "TOMORROW-OPENING-READINESS.txt").open("x", encoding="utf-8") as stream:
        stream.write(report["status"] + "\n" + "\n".join(report["failedGates"]) + "\n")
    print(report["status"])
    return 0 if report["status"] == "GREEN_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
