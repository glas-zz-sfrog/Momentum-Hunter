"""Create a deterministic, sanitized second-eye ZIP for the shared export candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Sequence


TASK = "ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001"
EXPECTED_BRANCH = "codex/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001"
BASE_SHA = "986407467ae8de27df1bc228d843a8701014ac06"
REQUIRED_CANDIDATE_PATHS = (
    "docs/argus-office/reports/releases/ARGUS-SHARED-SCIENCE-RUNTIME-FACT-EXPORT-001.md",
    "momentum_hunter/research_fact_export.py",
    "tests/test_research_fact_export.py",
    "tools/package_shared_science_runtime_fact_export.py",
    "tools/run_shared_science_runtime_fact_export_hard_chew.py",
    "tools/verify_research_fact_export.py",
)
SUPPORT_PATHS = ("momentum_hunter/__init__.py",)
SECRET_PATTERNS = (
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    re.compile(rb"Bearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class PackageError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise PackageError(
            f"git {' '.join(args)} failed: {completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return completed.stdout


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _verify_sidecar(root: Path, expected_sha: str) -> dict[str, Any]:
    sidecar = root / "artifact-checksums.sha256"
    if _sha256(sidecar.read_bytes()) != expected_sha.lower():
        raise PackageError(f"Checksum sidecar identity mismatch: {root.name}")
    count = 0
    for line in sidecar.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        expected, name = line.split(None, 1)
        relative = Path(name.strip().lstrip("*"))
        if relative.is_absolute() or ".." in relative.parts:
            raise PackageError("Unsafe checksum-sidecar path")
        if _sha256((root / relative).read_bytes()) != expected.lower():
            raise PackageError(f"Artifact checksum mismatch: {relative.as_posix()}")
        count += 1
    return {"artifact_count": count, "sidecar_sha256": expected_sha.lower()}


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 8, 31, 12, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def _scan_secret_values(entries: dict[str, bytes]) -> None:
    hits = [name for name, data in entries.items() if any(pattern.search(data) for pattern in SECRET_PATTERNS)]
    if hits:
        raise PackageError(f"Secret-like values found in package entries: {hits}")


def build_package(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repository.resolve()
    output_zip = args.output_zip.resolve(strict=False)
    checksum_path = args.checksum_path.resolve(strict=False)
    if not all(path.is_absolute() for path in (repo, output_zip, checksum_path)):
        raise PackageError("Repository and package paths must be absolute")
    if output_zip.exists() or checksum_path.exists():
        raise PackageError("Package and detached checksum targets must be create-only")
    branch = _git(repo, "branch", "--show-current").decode().strip()
    head = _git(repo, "rev-parse", "HEAD").decode().strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").decode().strip()
    status = _git(repo, "status", "--porcelain").decode().strip()
    if branch != EXPECTED_BRANCH or head != args.expected_head or status:
        raise PackageError("Candidate branch/head/cleanliness gate failed")
    if _git(repo, "merge-base", BASE_SHA, head).decode().strip() != BASE_SHA:
        raise PackageError("Candidate is not descended from the admitted canonical")
    changed_paths = tuple(
        line
        for line in _git(repo, "diff", "--name-only", f"{BASE_SHA}..{head}", "--")
        .decode()
        .splitlines()
        if line
    )
    if set(changed_paths) != set(REQUIRED_CANDIDATE_PATHS):
        raise PackageError(f"Candidate path inventory mismatch: {changed_paths}")
    design = _verify_sidecar(
        args.design_root.resolve(), args.expected_design_sidecar_sha256
    )
    baseline = _verify_sidecar(
        args.baseline_root.resolve(), args.expected_baseline_sidecar_sha256
    )
    hard_chew_path = args.evidence_root.resolve() / "hard-chew-summary.json"
    hard_chew = json.loads(hard_chew_path.read_text(encoding="utf-8"))
    if hard_chew.get("status") != "PASS":
        raise PackageError("Hard Chew evidence is not passing")
    entries: dict[str, bytes] = {}
    for relative in (*REQUIRED_CANDIDATE_PATHS, *SUPPORT_PATHS):
        entries[f"candidate/{relative}"] = (repo / relative).read_bytes()
    entries["candidate/candidate.diff"] = _git(
        repo, "diff", "--binary", f"{BASE_SHA}..{head}", "--"
    )
    for path in sorted(args.design_root.resolve().iterdir()):
        if path.is_file():
            entries[f"source-design/{path.name}"] = path.read_bytes()
    for path in sorted(args.baseline_root.resolve().iterdir()):
        if path.is_file():
            entries[f"preserved-baseline/{path.name}"] = path.read_bytes()
    for path in sorted(args.evidence_root.resolve().iterdir()):
        if path.is_file():
            entries[f"hard-chew/{path.name}"] = path.read_bytes()
    metadata = {
        "admitted_canonical": BASE_SHA,
        "baseline_packet": baseline,
        "candidate_branch": branch,
        "candidate_head": head,
        "candidate_tree": tree,
        "changed_paths": list(changed_paths),
        "design_packet": design,
        "executable_semantics_second_eye_required": True,
        "package_scope": "OFFLINE_REVIEW_ONLY_NO_INSTALL_NO_ACTIVATION",
        "second_eye_approval": "PENDING_INDEPENDENT_REVIEW",
        "task": TASK,
    }
    entries["candidate-metadata.json"] = _canonical_json(metadata)
    entries["README-SECOND-EYE.md"] = (
        "# Independent second-eye review\n\n"
        "This package is offline, research-only, and does not install or activate anything.\n\n"
        "1. Verify the detached ZIP SHA-256.\n"
        "2. Review `candidate/candidate.diff` against the source design.\n"
        "3. Extract, change into `candidate`, and run:\n"
        "   `python -m unittest -v tests.test_research_fact_export`\n"
        "4. Confirm all 25 AT cases pass and no provider/account/order/scheduler/service capability exists.\n"
        "5. Independently assess semantic correctness before approving integration.\n"
    ).encode("utf-8")
    _scan_secret_values(entries)
    manifest_entries = {
        name: {"byte_count": len(data), "sha256": _sha256(data)}
        for name, data in sorted(entries.items())
    }
    package_manifest = {
        "canonicalization": "SORTED_COMPACT_UTF8_LF",
        "entries": manifest_entries,
        "entry_count": len(manifest_entries),
        "status": "SEALED",
        "task": TASK,
    }
    entries["package-manifest.json"] = _canonical_json(package_manifest)
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, mode="x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            archive.writestr(_zip_info(name), data)
    with zipfile.ZipFile(output_zip, mode="r") as archive:
        if archive.testzip() is not None:
            raise PackageError("ZIP CRC verification failed")
        restored_manifest = json.loads(archive.read("package-manifest.json"))
        for name, expected in restored_manifest["entries"].items():
            data = archive.read(name)
            if len(data) != expected["byte_count"] or _sha256(data) != expected["sha256"]:
                raise PackageError(f"ZIP entry verification failed: {name}")
    zip_sha = _sha256(output_zip.read_bytes())
    checksum_line = f"{zip_sha}  {output_zip.name}\n".encode("ascii")
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(checksum_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(checksum_line)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "candidate_head": head,
        "candidate_tree": tree,
        "detached_checksum_path": str(checksum_path),
        "entry_count": len(entries),
        "package_path": str(output_zip),
        "package_sha256": zip_sha,
        "second_eye_status": "PACKAGE_READY_PENDING_INDEPENDENT_REVIEW",
        "status": "PASS",
        "task": TASK,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    parser.add_argument("--checksum-path", type=Path, required=True)
    parser.add_argument("--design-root", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-design-sidecar-sha256", required=True)
    parser.add_argument("--expected-baseline-sidecar-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = build_package(args)
    except (PackageError, OSError, subprocess.SubprocessError, zipfile.BadZipFile, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}", "status": "FAIL_CLOSED"}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
