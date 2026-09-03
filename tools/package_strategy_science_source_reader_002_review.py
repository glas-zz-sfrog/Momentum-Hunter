"""Build and fresh-extract the Science Source Reader 002 second-eye ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


TASK = "ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002"
EXPECTED_BASE = "0f42c5d7997823cffd888df29e9c46de71eadba6"
EXPECTED_BRANCH = "codex/ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002"
ZIP_TIMESTAMP = (2026, 9, 2, 0, 0, 0)
EXACT_OWNED = {
    "momentum_hunter/strategy_science_source_reader.py",
    "tests/test_strategy_science_source_reader_v2.py",
    "tools/finalize_strategy_science_source_reader_002_evidence.py",
    "tools/package_strategy_science_source_reader_002_review.py",
    "tools/run_strategy_science_source_reader_002_proof.py",
    "tools/run_strategy_science_source_reader_002_tests.py",
}
REPORT_PREFIX = (
    "docs/argus-office/reports/architecture/"
    "ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002-"
)
SECRET_PATTERNS = (
    re.compile(
        rb"(?i)(?:api[_-]?key|client[_-]?secret|access[_-]?token|"
        rb"refresh[_-]?token|password)\s*[:=]\s*[\"'][^\"']{8,}[\"']"
    ),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*"),
)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest().upper()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _allowed_path(path: str) -> bool:
    return path in EXACT_OWNED or path.startswith(REPORT_PREFIX)


def _copy(staging: Path, relative: str, raw: bytes) -> None:
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise ValueError(f"Unsafe package path: {relative}")
    _write(staging / relative, raw)


def _deterministic_zip(staging: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            relative = path.relative_to(staging).as_posix()
            info = zipfile.ZipInfo(relative, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def _verify_extraction(package: Path, verification_output: Path) -> dict[str, object]:
    verification_output.parent.mkdir(parents=True, exist_ok=True)
    extraction = Path(
        tempfile.mkdtemp(
            prefix="ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002-verified-",
            dir=verification_output.parent,
        )
    ).resolve()
    bad_members: list[str] = []
    with zipfile.ZipFile(package, "r") as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC validation failed.")
        for info in archive.infolist():
            target = (extraction / info.filename).resolve()
            try:
                target.relative_to(extraction)
            except ValueError:
                bad_members.append(info.filename)
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info.filename))
    if bad_members:
        raise ValueError(f"ZIP contains unsafe members: {bad_members}")
    checksum_failures: list[str] = []
    for row in (extraction / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines():
        digest, relative = row.split("  ", 1)
        target = extraction / relative
        if not target.is_file() or _sha(target.read_bytes()) != digest:
            checksum_failures.append(relative)
    manifest = json.loads((extraction / "manifest.json").read_bytes())
    manifest_failures: list[str] = []
    for item in manifest["entries"]:
        target = extraction / item["path"]
        if (
            not target.is_file()
            or target.stat().st_size != item["bytes"]
            or _sha(target.read_bytes()) != item["sha256"]
        ):
            manifest_failures.append(item["path"])
    result = {
        "badMembers": bad_members,
        "checksumFailures": checksum_failures,
        "extractionRoot": str(extraction),
        "manifestFailures": manifest_failures,
        "outerZipSha256": _sha(package.read_bytes()),
        "package": str(package),
        "status": (
            "PASS"
            if not bad_members and not checksum_failures and not manifest_failures
            else "FAIL"
        ),
        "task": TASK,
    }
    verification_output.write_bytes(_json_bytes(result))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verification-output", type=Path, required=True)
    parser.add_argument("--base-sha", default=EXPECTED_BASE)
    args = parser.parse_args(argv)
    repository = args.repository_root.resolve()
    evidence_root = args.evidence_root.resolve()
    output = args.output.resolve()
    verification_output = args.verification_output.resolve()
    head = _git(repository, "rev-parse", "HEAD")
    branch = _git(repository, "branch", "--show-current")
    status = _git(repository, "status", "--porcelain=v1")
    if args.base_sha != EXPECTED_BASE:
        raise ValueError("Unexpected immutable base SHA.")
    if branch != EXPECTED_BRANCH or status:
        raise ValueError("Package requires the clean frozen task branch.")
    changed_paths = tuple(
        line
        for line in _git(repository, "diff", "--name-only", f"{args.base_sha}..{head}").splitlines()
        if line
    )
    outside = [path for path in changed_paths if not _allowed_path(path)]
    if outside:
        raise ValueError(f"Changed paths exceed task ownership: {outside}")
    if not EXACT_OWNED.issubset(changed_paths):
        raise ValueError("Frozen head is missing a required source/test/tool path.")

    required_evidence = (
        "focused-source-reader-suite.json",
        "focused-source-reader-suite.transcript.txt",
        "exporter-compatibility-suite.json",
        "exporter-compatibility-suite.transcript.txt",
        "science-custody-compatibility-suite.json",
        "science-custody-compatibility-suite.transcript.txt",
        "continuous-adjacent-suite.json",
        "continuous-adjacent-suite.transcript.txt",
        "full-suite.json",
        "full-suite.transcript.txt",
        "compileall.json",
        "compileall.transcript.txt",
        "git-diff-check.json",
        "git-diff-check.transcript.txt",
        "capability-scan.json",
        "secret-scan.json",
        "protected-path-scan.json",
        "approved-environment.json",
        "hard-chew-summary.json",
        "proof/exporter-reader-custody.json",
        "proof/cursor-custody-atomicity.json",
        "proof/restart-crash-matrix.json",
        "proof/two-clock-proof.json",
        "proof/gap-finality-proof.json",
        "proof/offline-qualification.json",
    )
    missing = [name for name in required_evidence if not (evidence_root / name).is_file()]
    if missing:
        raise ValueError(f"Required review evidence is missing: {missing}")
    for relative in required_evidence:
        if relative.endswith(".json"):
            value = json.loads((evidence_root / relative).read_bytes())
            if value.get("status") != "PASS" and relative != "approved-environment.json":
                raise ValueError(f"Evidence is not passing: {relative}")

    with tempfile.TemporaryDirectory(prefix="argus-source-reader-002-package-") as temporary:
        staging = Path(temporary)
        identities = {
            "baseCanonicalSha": args.base_sha,
            "branch": branch,
            "frozenReviewHead": head,
            "gitStatusPorcelain": status,
            "sourceContract": "ResearchExportEnvelopeV2",
            "sourceContractVersion": "2.0.0-proposal",
            "task": TASK,
        }
        _copy(staging, "git/identities.json", _json_bytes(identities))
        _copy(
            staging,
            "git/changed-paths.txt",
            ("\n".join(changed_paths) + "\n").encode("utf-8"),
        )
        for relative in changed_paths:
            _copy(staging, f"repository/{relative}", (repository / relative).read_bytes())
        for relative in required_evidence:
            _copy(staging, f"evidence/{relative}", (evidence_root / relative).read_bytes())
        diff = subprocess.run(
            ["git", "diff", "--binary", f"{args.base_sha}..{head}"],
            cwd=repository,
            check=True,
            capture_output=True,
        ).stdout
        _copy(staging, "git/base-to-frozen-head.patch", diff)
        readme = f"# {TASK} Second-Eye Review\n\n"
        readme += f"- Base canonical: `{args.base_sha}`\n"
        readme += f"- Frozen review head: `{head}`\n"
        readme += "- Source: exact immutable `ResearchExportEnvelopeV2` public bytes\n"
        readme += "- Ingress: reader to canonical parser/custody with no reserialization\n"
        readme += "- Cursor: advances only after verified Science custody commit\n"
        readme += "- Authority: offline research-only; execution authority none\n"
        readme += "- Outcome reader: separate future task\n"
        readme += "- Merge authority: none; independent review required\n"
        _copy(staging, "README.md", readme.encode("utf-8"))

        secret_findings: list[str] = []
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            raw = path.read_bytes()
            if any(pattern.search(raw) for pattern in SECRET_PATTERNS):
                secret_findings.append(path.relative_to(staging).as_posix())
        sanitization = {
            "contextAwareSecretFindings": secret_findings,
            "status": "PASS" if not secret_findings else "FAIL",
            "task": TASK,
        }
        _copy(staging, "sanitization.json", _json_bytes(sanitization))
        if secret_findings:
            raise ValueError(f"Sanitization failed: {secret_findings}")

        entries = []
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            relative = path.relative_to(staging).as_posix()
            raw = path.read_bytes()
            entries.append({"bytes": len(raw), "path": relative, "sha256": _sha(raw)})
        manifest = {
            "baseCanonicalSha": args.base_sha,
            "entries": entries,
            "frozenReviewHead": head,
            "schemaVersion": 1,
            "task": TASK,
        }
        _copy(staging, "manifest.json", _json_bytes(manifest))
        checksum_rows = []
        for path in sorted(item for item in staging.rglob("*") if item.is_file()):
            relative = path.relative_to(staging).as_posix()
            checksum_rows.append(f"{_sha(path.read_bytes())}  {relative}")
        _copy(
            staging,
            "SHA256SUMS.txt",
            ("\n".join(checksum_rows) + "\n").encode("ascii"),
        )
        _deterministic_zip(staging, output)
    verification = _verify_extraction(output, verification_output)
    print(
        json.dumps(
            {
                "frozenReviewHead": head,
                "outerZipSha256": verification["outerZipSha256"],
                "package": str(output),
                "status": verification["status"],
                "verification": str(verification_output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if verification["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
