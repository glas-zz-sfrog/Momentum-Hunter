"""Build and verify the sanitized Producer-001E second-eye review package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


FOCUSED_MODULES = (
    "tests.test_continuous_producer_001b_forensic_canary",
    "tests.test_approved_environment_hard_chew",
)
OVERLAY_PATHS = (
    "tools/run_continuous_producer_001b_forensic_canary.py",
    "tools/run_approved_environment_tests.py",
    "tools/replay_continuous_producer_001d_forensic_evidence.py",
    "tools/package_continuous_producer_001e_review.py",
    "tools/run_schwab_candle_observer.ps1",
    "tests/test_continuous_producer_001b_forensic_canary.py",
    "tests/test_approved_environment_hard_chew.py",
    "tests/test_automation_service_install.py",
    "tests/test_schwab_candle_observer.py",
    "docs/argus-office/goal-charters/ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001E-forensic-analyzer-repair.md",
)
TEXT_SUFFIXES = {".json", ".md", ".ps1", ".py", ".txt"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="ascii")


def _safe_extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        root = destination.resolve()
        for item in bundle.infolist():
            target = (destination / item.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise RuntimeError("ZIP contains an escaping path.") from exc
        bundle.extractall(destination)


def _copy_sanitized(source: Path, target: Path, forbidden: str) -> dict[str, object]:
    target.parent.mkdir(parents=True, exist_ok=True)
    original = _sha256(source)
    replacements = 0
    if forbidden and source.suffix.lower() in TEXT_SUFFIXES:
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copy2(source, target)
        else:
            replacements = text.count(forbidden)
            target.write_text(text.replace(forbidden, "0000"), encoding="utf-8", newline="")
    else:
        shutil.copy2(source, target)
    return {
        "path": target.as_posix(),
        "originalSha256": original,
        "packagedSha256": _sha256(target),
        "replacementCount": replacements,
    }


def _manifest(root: Path) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "PACKAGE-MANIFEST.json"
    ]


def _verify_manifest(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "PACKAGE-MANIFEST.json").read_text(encoding="ascii"))
    failures = []
    for item in manifest["files"]:
        path = root / item["path"]
        if not path.is_file() or _sha256(path) != item["sha256"]:
            failures.append(item["path"])
    return {
        "status": "PASS" if not failures else "FAIL",
        "verified": len(manifest["files"]) - len(failures),
        "failures": failures,
    }


def _secret_scan(root: Path, forbidden: str) -> dict[str, object]:
    patterns = (
        ("BEARER_CREDENTIAL", re.compile(r"Bearer\s+[A-Za-z0-9._~-]{20,}")),
        ("ALPACA_KEY_SHAPE", re.compile(r"\bPK[A-Z0-9]{18,}\b")),
        ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    )
    findings = []
    scanned = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() in {".zip", ".png", ".exe", ".dll"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        relative = path.relative_to(root).as_posix()
        for name, pattern in patterns:
            if pattern.search(text):
                findings.append({"path": relative, "term": name})
        if forbidden and forbidden in text:
            findings.append({"path": relative, "term": "BOUND_IDENTITY"})
    return {
        "status": "PASS" if not findings else "FAIL",
        "filesScanned": scanned,
        "findings": findings,
    }


def _run_focused(source: Path, output: Path) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source)
    env["MH_CANARY_CANONICAL_ROOT"] = str(source)
    completed = subprocess.run(
        (sys.executable, "-B", "-m", "unittest", "-v", *FOCUSED_MODULES),
        cwd=source,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    result = {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returnCode": completed.returncode,
        "command": ["python.exe", "-B", "-m", "unittest", "-v", *FOCUSED_MODULES],
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    _write(output, result)
    return result


def _run_replay(source: Path, evidence_zip: Path, evidence_sha: str, output: Path) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source)
    replay_root = output.parent / "reproduced-replay"
    completed = subprocess.run(
        (
            sys.executable,
            "-B",
            str(source / "tools" / "replay_continuous_producer_001d_forensic_evidence.py"),
            "--evidence-zip",
            str(evidence_zip),
            "--expected-evidence-sha256",
            evidence_sha,
            "--repository-root",
            str(source),
            "--output-root",
            str(replay_root),
        ),
        cwd=source,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=1800,
    )
    result = {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returnCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "summary": json.loads((replay_root / "replay-summary.json").read_text(encoding="ascii"))
        if (replay_root / "replay-summary.json").is_file()
        else None,
    }
    _write(output, result)
    shutil.rmtree(replay_root, ignore_errors=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--adjudication-root", type=Path, required=True)
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument("--expected-evidence-sha256", required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    args = parser.parse_args(argv)

    repository = args.repository_root.resolve(strict=True)
    replay_root = args.replay_root.resolve(strict=True)
    adjudication = args.adjudication_root.resolve(strict=True)
    evidence_zip = args.evidence_zip.resolve(strict=True)
    output_zip = args.output_zip.resolve(strict=False)
    package_root = output_zip.with_suffix("")
    extracted_verify = output_zip.with_name(output_zip.stem + "-EXTRACTED-VERIFY")
    for path in (output_zip, package_root, extracted_verify):
        if path.exists():
            raise SystemExit(f"Package output already exists: {path}")
    evidence_sha = _sha256(evidence_zip)
    if evidence_sha != args.expected_evidence_sha256.strip().upper():
        raise SystemExit("Immutable 001D evidence ZIP hash did not match.")
    forbidden = os.environ.get("MH_PACKAGE_FORBIDDEN_VALUE", "").strip()

    package_root.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="MomentumHunter-001E-Package-") as directory:
        extracted_original = Path(directory)
        _safe_extract(evidence_zip, extracted_original)
        shutil.copytree(extracted_original / "source", package_root / "source")

    substitutions = []
    for relative in OVERLAY_PATHS:
        source = repository / relative
        substitutions.append(
            _copy_sanitized(source, package_root / "source" / relative, forbidden)
        )
    (package_root / "inputs").mkdir()
    shutil.copy2(evidence_zip, package_root / "inputs" / evidence_zip.name)
    (package_root / "results").mkdir()
    (package_root / "independent-adjudication").mkdir()
    for name in (
        "replay-summary.json",
        "repaired-forensic-analysis.json",
        "repaired-forensic-timeline.json",
        "approved-environment.json",
        "focused-approved-environment-tests.json",
        "full-approved-environment-discovery.json",
        "capability-ownership-scan.json",
        "hard-chew-source-binding.json",
    ):
        shutil.copy2(replay_root / name, package_root / "results" / name)
    for name in (
        "FINAL-ADJUDICATION.md",
        "FINAL-CLASSIFICATIONS.json",
        "completed-bar-reconciliation-summary.json",
        "tradeplan-provenance.json",
        "hard-chew-environment-analysis.json",
        "minimum-repair-map.json",
    ):
        shutil.copy2(adjudication / name, package_root / "independent-adjudication" / name)

    package_root.joinpath("README.md").write_text(
        "# Producer-001E Second-Eye Package\n\n"
        "This package replays the repaired forensic analyzer against the embedded, "
        "immutable, sanitized Producer-001D evidence ZIP. It performs no provider, "
        "account, Paper, Shadow, broker, or order action.\n\n"
        "Run the focused tests from `source/` with an approved Python environment:\n\n"
        "```text\npython -B -m unittest -v " + " ".join(FOCUSED_MODULES) + "\n```\n\n"
        "Run `source/tools/replay_continuous_producer_001d_forensic_evidence.py` "
        "against the ZIP under `inputs/` using its SHA-256 recorded in INDEX.md.\n",
        encoding="ascii",
    )
    package_root.joinpath("INDEX.md").write_text(
        "# Index\n\n"
        f"- Immutable 001D ZIP: `inputs/{evidence_zip.name}`\n"
        f"- Immutable 001D ZIP SHA-256: `{evidence_sha}`\n"
        "- `source/`: sanitized 001D self-contained source with 001E tooling overlays.\n"
        "- `results/`: repaired replay and approved-environment Hard Chew evidence.\n"
        "- `independent-adjudication/`: governing independent 001D findings.\n"
        "- Unknown instrument classification remains a downstream execution blocker.\n",
        encoding="ascii",
    )
    _write(package_root / "PACKAGE-SANITIZATION-LEDGER.json", substitutions)
    prezip_tests = _run_focused(
        package_root / "source", package_root / "PREZIP-FOCUSED-TESTS.json"
    )
    prezip_replay = _run_replay(
        package_root / "source",
        package_root / "inputs" / evidence_zip.name,
        evidence_sha,
        package_root / "PREZIP-REPLAY.json",
    )
    scan = _secret_scan(package_root, forbidden)
    _write(package_root / "SECRET-SCAN.json", scan)
    if scan["status"] != "PASS" or prezip_tests["status"] != "PASS" or prezip_replay["status"] != "PASS":
        raise SystemExit("Pre-ZIP verification failed; package was not emitted.")
    files = _manifest(package_root)
    _write(
        package_root / "PACKAGE-MANIFEST.json",
        {"schemaVersion": 1, "fileCount": len(files), "files": files},
    )
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(package_root).as_posix())

    _safe_extract(output_zip, extracted_verify)
    manifest_verification = _verify_manifest(extracted_verify)
    extracted_tests = _run_focused(
        extracted_verify / "source", extracted_verify / "EXTRACTED-FOCUSED-TESTS.json"
    )
    extracted_replay = _run_replay(
        extracted_verify / "source",
        extracted_verify / "inputs" / evidence_zip.name,
        evidence_sha,
        extracted_verify / "EXTRACTED-REPLAY.json",
    )
    result = {
        "status": "PASS"
        if manifest_verification["status"] == "PASS"
        and extracted_tests["status"] == "PASS"
        and extracted_replay["status"] == "PASS"
        else "FAIL",
        "zipPath": str(output_zip),
        "zipSha256": _sha256(output_zip),
        "fileCount": sum(1 for path in package_root.rglob("*") if path.is_file()),
        "manifestCount": len(files),
        "secretScan": scan,
        "preZipTests": prezip_tests["status"],
        "preZipReplay": prezip_replay["status"],
        "manifestVerification": manifest_verification,
        "extractedZipTests": extracted_tests["status"],
        "extractedZipReplay": extracted_replay["status"],
        "extractedVerificationRoot": str(extracted_verify),
    }
    _write(output_zip.with_suffix(".result.json"), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
