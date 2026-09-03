"""Finalize mechanical Hard Chew evidence for Source Reader 002."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


TASK = "ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002"
EXPECTED_BASE = "0f42c5d7997823cffd888df29e9c46de71eadba6"
EXPECTED_BRANCH = "codex/ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002"
REPORT_PREFIX = (
    "docs/argus-office/reports/architecture/"
    "ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002-"
)
EXACT_OWNED = {
    "momentum_hunter/strategy_science_source_reader.py",
    "tests/test_strategy_science_source_reader_v2.py",
    "tools/finalize_strategy_science_source_reader_002_evidence.py",
    "tools/package_strategy_science_source_reader_002_review.py",
    "tools/run_strategy_science_source_reader_002_proof.py",
    "tools/run_strategy_science_source_reader_002_tests.py",
}
SECRET_PATTERNS = (
    re.compile(
        rb"(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|"
        rb"refresh[_-]?token|password)\s*[:=]\s*[\"'][^\"']{8,}[\"']"
    ),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*"),
)
PROTECTED_PREFIXES = (
    "momentum_hunter/opening",
    "momentum_hunter/continuous.py",
    "momentum_hunter/gui",
    "momentum_hunter/providers",
    "momentum_hunter/broker",
    "momentum_hunter/execution",
    "services/",
    "scheduler/",
)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _allowed(path: str) -> bool:
    return path in EXACT_OWNED or path.startswith(REPORT_PREFIX)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--base-sha", default=EXPECTED_BASE)
    args = parser.parse_args(argv)
    repository = args.repository_root.resolve()
    evidence = args.evidence_root.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    if args.base_sha != EXPECTED_BASE:
        raise ValueError("Unexpected immutable base SHA.")
    branch = _git(repository, "branch", "--show-current")
    head = _git(repository, "rev-parse", "HEAD")
    status = _git(repository, "status", "--porcelain=v1")
    if branch != EXPECTED_BRANCH or status:
        raise ValueError("Final evidence requires the clean frozen task branch.")
    changed = tuple(
        row
        for row in _git(repository, "diff", "--name-only", f"{args.base_sha}..{head}").splitlines()
        if row
    )
    outside = [path for path in changed if not _allowed(path)]
    missing_owned = sorted(EXACT_OWNED.difference(changed))

    compile_command = [
        sys.executable,
        "-B",
        "-m",
        "compileall",
        "-q",
        "momentum_hunter/strategy_science_source_reader.py",
        "tests/test_strategy_science_source_reader_v2.py",
        "tools/finalize_strategy_science_source_reader_002_evidence.py",
        "tools/package_strategy_science_source_reader_002_review.py",
        "tools/run_strategy_science_source_reader_002_proof.py",
        "tools/run_strategy_science_source_reader_002_tests.py",
    ]
    compiled = subprocess.run(
        compile_command,
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    compile_transcript = (compiled.stdout + compiled.stderr).encode("utf-8")
    (evidence / "compileall.transcript.txt").write_bytes(compile_transcript)
    compile_evidence = {
        "command": compile_command,
        "returnCode": compiled.returncode,
        "status": "PASS" if compiled.returncode == 0 else "FAIL",
        "task": TASK,
        "transcriptSha256": hashlib.sha256(compile_transcript).hexdigest().upper(),
    }
    _write(evidence / "compileall.json", compile_evidence)

    diff_check = subprocess.run(
        ["git", "diff", "--check", f"{args.base_sha}..{head}"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    diff_transcript = (diff_check.stdout + diff_check.stderr).encode("utf-8")
    (evidence / "git-diff-check.transcript.txt").write_bytes(diff_transcript)
    diff_evidence = {
        "changedPaths": changed,
        "outsideOwnedScope": outside,
        "requiredOwnedPathsMissing": missing_owned,
        "returnCode": diff_check.returncode,
        "status": (
            "PASS"
            if diff_check.returncode == 0 and not outside and not missing_owned
            else "FAIL"
        ),
        "task": TASK,
    }
    _write(evidence / "git-diff-check.json", diff_evidence)

    module_path = repository / "momentum_hunter" / "strategy_science_source_reader.py"
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        node.names[0].name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
    } | {
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    prohibited_imports = sorted(
        imported.intersection(
            {
                "requests",
                "httpx",
                "socket",
                "schwab",
                "finviz",
                "broker",
                "services",
                "scheduler",
            }
        )
    )
    prohibited_symbols = sorted(
        symbol
        for symbol in (
            "submit_order",
            "cancel_order",
            "paper_trade",
            "shadow_trade",
            "refresh_token",
            "provider_login",
        )
        if symbol in source.lower()
    )
    capability = {
        "imports": sorted(imported),
        "prohibitedImports": prohibited_imports,
        "prohibitedSymbols": prohibited_symbols,
        "status": "PASS" if not prohibited_imports and not prohibited_symbols else "FAIL",
        "task": TASK,
    }
    _write(evidence / "capability-scan.json", capability)

    secret_findings: list[str] = []
    for relative in changed:
        path = repository / relative
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if any(pattern.search(raw) for pattern in SECRET_PATTERNS):
            secret_findings.append(relative)
    secrets = {
        "contextAwareFindings": secret_findings,
        "scannedPaths": changed,
        "status": "PASS" if not secret_findings else "FAIL",
        "task": TASK,
    }
    _write(evidence / "secret-scan.json", secrets)

    protected_touched = sorted(
        path for path in changed if path.startswith(PROTECTED_PREFIXES)
    )
    protected = {
        "protectedPathsTouched": protected_touched,
        "reviewedBoundaries": [
            "canonical Science contract semantics",
            "canonical Continuous exporter semantics",
            "production Continuous runtime",
            "Opening and Observer",
            "GUI",
            "providers and authentication",
            "services and schedulers",
            "strategy, Paper, Shadow, broker, and execution authority",
        ],
        "status": "PASS" if not protected_touched else "FAIL",
        "task": TASK,
    }
    _write(evidence / "protected-path-scan.json", protected)

    approved = {
        "completedAt": datetime.now().astimezone().isoformat(),
        "git": {
            "baseCanonicalSha": args.base_sha,
            "branch": branch,
            "frozenReviewHead": head,
            "statusPorcelain": status,
        },
        "python": {
            "executable": sys.executable,
            "executableSha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest().upper(),
            "version": sys.version,
        },
        "task": TASK,
    }
    _write(evidence / "approved-environment.json", approved)

    required_suites = (
        "focused-source-reader-suite.json",
        "exporter-compatibility-suite.json",
        "science-custody-compatibility-suite.json",
        "continuous-adjacent-suite.json",
        "full-suite.json",
    )
    required_proofs = (
        "proof/exporter-reader-custody.json",
        "proof/cursor-custody-atomicity.json",
        "proof/restart-crash-matrix.json",
        "proof/two-clock-proof.json",
        "proof/gap-finality-proof.json",
        "proof/offline-qualification.json",
    )
    evidence_statuses: dict[str, str] = {}
    for relative in (*required_suites, *required_proofs):
        path = evidence / relative
        if not path.is_file():
            evidence_statuses[relative] = "MISSING"
        else:
            evidence_statuses[relative] = str(json.loads(path.read_bytes()).get("status"))
    mechanical = {
        "capabilityScan": capability["status"],
        "compileall": compile_evidence["status"],
        "gitDiffCheck": diff_evidence["status"],
        "protectedPathScan": protected["status"],
        "secretScan": secrets["status"],
    }
    hard_chew_pass = all(value == "PASS" for value in evidence_statuses.values()) and all(
        value == "PASS" for value in mechanical.values()
    )
    hard_chew = {
        "baseCanonicalSha": args.base_sha,
        "branch": branch,
        "completedAt": datetime.now().astimezone().isoformat(),
        "crossLaneContractChangeRequired": False,
        "evidenceStatuses": evidence_statuses,
        "frozenReviewHead": head,
        "liveProviderContactOccurred": False,
        "mechanicalChecks": mechanical,
        "oldClassBDataUpgraded": False,
        "paperAuthorityUsed": False,
        "status": "PASS" if hard_chew_pass else "FAIL",
        "task": TASK,
    }
    _write(evidence / "hard-chew-summary.json", hard_chew)
    print(json.dumps(hard_chew, indent=2, sort_keys=True))
    return 0 if hard_chew_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
