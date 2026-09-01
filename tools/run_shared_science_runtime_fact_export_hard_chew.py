"""Run and seal the offline Hard Chew for the shared fact-export candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


TASK = "ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001"
EXPECTED_BRANCH = "codex/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001"
BASE_SHA_FOR_EXPECTED_SKIP = "986407467ae8de27df1bc228d843a8701014ac06"
ALLOWED_PATHS = {
    "docs/argus-office/reports/releases/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001.md",
    "momentum_hunter/research_fact_export.py",
    "tests/test_research_fact_export.py",
    "tools/package_shared_science_runtime_fact_export.py",
    "tools/run_shared_science_runtime_fact_export_hard_chew.py",
    "tools/verify_research_fact_export.py",
}
SECRET_PATTERNS = (
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(rb"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
EXPECTED_SKIP_IDS = (
    "tests.test_gui_states.GuiStateTests.test_research_lab_open_returns_control_before_slow_report_finishes",
)
EXPECTED_SKIP_SUFFIXES = tuple(item.removeprefix("tests.") for item in EXPECTED_SKIP_IDS)
EXPECTED_SKIP_REASON = (
    "Exact admitted canonical independently fails this untouched GUI timing assertion "
    "under the approved Python environment; GUI repair is outside the shared-contract task boundary."
)
EXPECTED_REPOSITORY_PLATFORM_SKIP_COUNT = 1
EXPECTED_SKIP_RUNNER = r'''
import json
import sys
import unittest

suffixes = json.loads(sys.argv[1])
reason = sys.argv[2]
suite = unittest.defaultTestLoader.discover("tests")

def cases(node):
    for item in node:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item

all_cases = list(cases(suite))
matches = []
for suffix in suffixes:
    resolved = [case for case in all_cases if case.id().endswith(suffix)]
    if len(resolved) != 1:
        raise SystemExit(f"EXPECTED_SKIP_RESOLUTION_FAILED:{suffix}:{len(resolved)}")
    matches.extend(resolved)
for case in matches:
    name = case._testMethodName
    original = getattr(case.__class__, name)
    setattr(case.__class__, name, unittest.skip(reason)(original))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
'''


class HardChewError(RuntimeError):
    pass


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    *,
    name: str,
    command: Sequence[str],
    cwd: Path,
    evidence_root: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            capture_output=True,
            text=False,
            timeout=timeout_seconds,
            check=False,
        )
        returncode = completed.returncode
        output = completed.stdout + completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        output = (exc.stdout or b"") + (exc.stderr or b"") + b"\nTIMEOUT_FAIL_CLOSED\n"
    duration = round(time.monotonic() - started, 3)
    log_path = evidence_root / f"{name}.log"
    _write_once(log_path, output)
    text = output.decode("utf-8", errors="replace")
    ran_match = re.search(r"Ran (\d+) tests?", text)
    skipped_match = re.search(r"skipped=(\d+)", text)
    dotnet_totals = [int(item) for item in re.findall(r"Total:\s+(\d+)", text)]
    dotnet_skips = [int(item) for item in re.findall(r"Skipped:\s+(\d+)", text)]
    result = {
        "command": list(command),
        "duration_seconds": str(duration),
        "exit_code": returncode,
        "log": log_path.name,
        "log_sha256": _sha256(log_path),
        "name": name,
        "status": "PASS" if returncode == 0 else ("TIMEOUT" if timed_out else "FAIL"),
        "tests_ran": int(ran_match.group(1)) if ran_match else sum(dotnet_totals),
        "tests_skipped": int(skipped_match.group(1)) if skipped_match else sum(dotnet_skips),
    }
    _write_once(evidence_root / f"{name}.json", _json_bytes(result))
    return result


def _run_expected_baseline_failure(
    *,
    python: Path,
    baseline_worktree: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    if _git(baseline_worktree, "rev-parse", "HEAD") != BASE_SHA_FOR_EXPECTED_SKIP:
        raise HardChewError("Expected-skip baseline worktree is not at admitted canonical")
    if _git(baseline_worktree, "status", "--porcelain"):
        raise HardChewError("Expected-skip baseline worktree is not clean")
    started = time.monotonic()
    probes: list[dict[str, Any]] = []
    output_parts: list[bytes] = []
    for test_id in EXPECTED_SKIP_IDS:
        command = [str(python), "-m", "unittest", "-v", test_id]
        probe_started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=baseline_worktree,
                capture_output=True,
                text=False,
                timeout=10,
                check=False,
            )
            output = completed.stdout + completed.stderr
            observed_expected_failure = (
                completed.returncode == 1
                and b"AssertionError" in output
                and b"not less than 0.15" in output
            )
            returncode = completed.returncode
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or b"") + (exc.stderr or b"") + b"\nUNEXPECTED_BASELINE_TIMEOUT\n"
            observed_expected_failure = False
            returncode = 124
        output_parts.append(output)
        probes.append(
            {
                "duration_seconds": str(round(time.monotonic() - probe_started, 3)),
                "exit_code": returncode,
                "expected_failure_observed": observed_expected_failure,
                "test_id": test_id,
            }
        )
    log_path = evidence_root / "expected_skip_baseline_probe.log"
    _write_once(log_path, b"\n".join(output_parts))
    result = {
        "baseline_head": BASE_SHA_FOR_EXPECTED_SKIP,
        "duration_seconds": str(round(time.monotonic() - started, 3)),
        "expected_skip_ids": list(EXPECTED_SKIP_IDS),
        "log": log_path.name,
        "log_sha256": _sha256(log_path),
        "probes": probes,
        "reason": EXPECTED_SKIP_REASON,
        "status": "PASS" if all(item["expected_failure_observed"] for item in probes) else "FAIL",
    }
    _write_once(evidence_root / "expected_skip_baseline_probe.json", _json_bytes(result))
    return result


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise HardChewError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _verify_checksum_sidecar(root: Path, expected_sha: str) -> dict[str, Any]:
    sidecar = root / "artifact-checksums.sha256"
    actual_sidecar = _sha256(sidecar)
    if actual_sidecar != expected_sha.lower():
        raise HardChewError(f"Checksum sidecar mismatch: {root.name}")
    verified = 0
    for line in sidecar.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        expected, name = line.split(None, 1)
        relative = Path(name.strip().lstrip("*"))
        if relative.is_absolute() or ".." in relative.parts:
            raise HardChewError("Unsafe checksum-sidecar path")
        if _sha256(root / relative) != expected.lower():
            raise HardChewError(f"Artifact checksum mismatch: {relative.as_posix()}")
        verified += 1
    return {
        "artifact_count": verified,
        "root": str(root),
        "sidecar_sha256": actual_sidecar,
        "status": "PASS",
    }


def _scan_candidate(repo: Path, base_sha: str) -> dict[str, Any]:
    changed = set(
        line
        for line in _git(repo, "diff", "--name-only", base_sha, "--").splitlines()
        if line
    )
    changed.update(
        line
        for line in _git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
        if line
    )
    unexpected = sorted(changed - ALLOWED_PATHS)
    if unexpected:
        raise HardChewError(f"Candidate changed paths outside the declared scope: {unexpected}")
    secret_hits: list[str] = []
    for relative in sorted(changed):
        data = (repo / relative).read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            secret_hits.append(relative)
    if secret_hits:
        raise HardChewError(f"Secret-like values found in candidate paths: {secret_hits}")
    module = (repo / "momentum_hunter/research_fact_export.py").read_text(
        encoding="utf-8"
    )
    forbidden_imports = sorted(
        token
        for token in ("requests", "httpx", "schwab", "alpaca", "socket")
        if re.search(rf"^(?:from|import)\s+{re.escape(token)}\b", module, re.MULTILINE)
    )
    if forbidden_imports:
        raise HardChewError(f"Provider/network imports found: {forbidden_imports}")
    return {
        "allowed_path_count": len(changed),
        "changed_paths": sorted(changed),
        "forbidden_imports": forbidden_imports,
        "secret_scan": "PASS",
        "status": "PASS",
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repository.resolve()
    evidence_root = args.evidence_root.resolve(strict=False)
    if not repo.is_absolute() or not evidence_root.is_absolute():
        raise HardChewError("Repository and evidence roots must be absolute")
    evidence_root.mkdir(parents=True, exist_ok=True)
    if any(evidence_root.iterdir()):
        raise HardChewError("Evidence root must be empty for a create-only Hard Chew")
    if _git(repo, "branch", "--show-current") != EXPECTED_BRANCH:
        raise HardChewError("Candidate branch identity mismatch")
    head = _git(repo, "rev-parse", "HEAD")
    tree = _git(repo, "write-tree")
    if _git(repo, "merge-base", args.base_sha, head) != args.base_sha:
        raise HardChewError("Candidate is not descended from the admitted canonical")
    design_before = _verify_checksum_sidecar(
        args.design_root.resolve(), args.expected_design_sidecar_sha256
    )
    baseline_before = _verify_checksum_sidecar(
        args.baseline_root.resolve(), args.expected_baseline_sidecar_sha256
    )
    candidate_scan = _scan_candidate(repo, args.base_sha)
    expected_skip_probe = _run_expected_baseline_failure(
        python=args.python,
        baseline_worktree=args.baseline_worktree.resolve(),
        evidence_root=evidence_root,
    )
    commands = [
        (
            "approved_python_environment",
            [
                str(args.python),
                "-c",
                (
                    "import bs4,json,PySide6,requests,sys; "
                    "assert sys.version_info[:3] == (3,12,6); "
                    "assert bs4.__version__ == '4.12.3'; "
                    "assert requests.__version__ == '2.32.3'; "
                    "assert PySide6.__version__ == '6.7.3'; "
                    "print(json.dumps({'python':sys.version.split()[0],'bs4':bs4.__version__,"
                    "'requests':requests.__version__,'PySide6':PySide6.__version__},sort_keys=True))"
                ),
            ],
            120,
        ),
        (
            "compileall",
            [str(args.python), "-m", "compileall", "-q", "momentum_hunter", "tests", "tools"],
            300,
        ),
        (
            "focused_25",
            [str(args.python), "-m", "unittest", "-v", "tests.test_research_fact_export"],
            300,
        ),
        (
            "adjacent_owner_regression",
            [
                str(args.python),
                "-m",
                "unittest",
                "-v",
                "tests.test_opportunity_denominator",
                "tests.test_research_governance",
                "tests.test_candidate_lifecycle",
                "tests.test_event_runtime_writer_ipc",
            ],
            600,
        ),
        (
            "preserved_evidence_rehearsal",
            [
                str(args.python),
                "tools/verify_research_fact_export.py",
                "--source-root",
                str(args.baseline_root.resolve()),
                "--output-root",
                str(args.rehearsal_root.resolve(strict=False)),
                "--expected-sidecar-sha256",
                args.expected_baseline_sidecar_sha256,
                "--protected-root",
                str(args.production_root.resolve()),
                "--protected-root",
                str(args.foreign_root.resolve()),
            ],
            300,
        ),
        (
            "full_python_suite",
            [
                str(args.python),
                "-c",
                EXPECTED_SKIP_RUNNER,
                json.dumps(EXPECTED_SKIP_SUFFIXES),
                EXPECTED_SKIP_REASON,
            ],
            args.full_suite_timeout_seconds,
        ),
        (
            "full_dotnet_suite",
            ["dotnet", "test", "MomentumHunter.Workstation.sln", "-c", "Release", "--verbosity", "minimal"],
            args.full_suite_timeout_seconds,
        ),
        ("git_diff_check", ["git", "diff", "--check", args.base_sha, "--"], 120),
    ]
    results = [
        _run(
            name=name,
            command=command,
            cwd=repo,
            evidence_root=evidence_root,
            timeout_seconds=timeout,
        )
        for name, command, timeout in commands
    ]
    design_after = _verify_checksum_sidecar(
        args.design_root.resolve(), args.expected_design_sidecar_sha256
    )
    baseline_after = _verify_checksum_sidecar(
        args.baseline_root.resolve(), args.expected_baseline_sidecar_sha256
    )
    production = args.production_root.resolve()
    production_head = _git(production, "rev-parse", "HEAD")
    production_origin = _git(production, "rev-parse", "origin/master")
    production_status = _git(production, "status", "--porcelain")
    foreign = args.foreign_root.resolve()
    foreign_head = _git(foreign, "rev-parse", "HEAD")
    foreign_status = _git(foreign, "status", "--porcelain")
    external = {
        "foreign_expected_head": args.expected_foreign_head,
        "foreign_head": foreign_head,
        "foreign_unchanged": foreign_head == args.expected_foreign_head and not foreign_status,
        "production_clean": not production_status,
        "production_head": production_head,
        "production_origin": production_origin,
        "production_synchronized": production_head == production_origin == args.base_sha,
    }
    all_pass = expected_skip_probe["status"] == "PASS" and all(
        item["status"] == "PASS" for item in results
    )
    full_python = next(item for item in results if item["name"] == "full_python_suite")
    all_pass = all_pass and full_python["tests_skipped"] == (
        len(EXPECTED_SKIP_SUFFIXES) + EXPECTED_REPOSITORY_PLATFORM_SKIP_COUNT
    )
    all_pass = all_pass and external["foreign_unchanged"] and external["production_clean"] and external["production_synchronized"]
    summary = {
        "admitted_canonical": args.base_sha,
        "baseline_packet": baseline_after,
        "candidate_branch": EXPECTED_BRANCH,
        "candidate_head_at_test": head,
        "candidate_scan": candidate_scan,
        "candidate_tree_at_test": tree,
        "design_packet": design_after,
        "external_state": external,
        "expected_skips": [expected_skip_probe],
        "live_provider_contact": False,
        "provider_authentication_changed": False,
        "results": results,
        "status": "PASS" if all_pass else "FAIL_CLOSED",
        "task": TASK,
        "trading_or_execution_authority_used": False,
    }
    _write_once(evidence_root / "hard-chew-summary.json", _json_bytes(summary))
    if not all_pass:
        raise HardChewError("One or more Hard Chew gates failed; see sealed evidence logs")
    return summary


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--rehearsal-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--foreign-root", type=Path, required=True)
    parser.add_argument("--baseline-worktree", type=Path, required=True)
    parser.add_argument("--design-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--expected-foreign-head", required=True)
    parser.add_argument("--expected-design-sidecar-sha256", required=True)
    parser.add_argument("--expected-baseline-sidecar-sha256", required=True)
    parser.add_argument("--full-suite-timeout-seconds", type=int, default=1200)
    args = parser.parse_args(argv)
    try:
        summary = run(args)
    except (HardChewError, OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}", "status": "FAIL_CLOSED"}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
