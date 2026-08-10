from __future__ import annotations

"""One-use, non-scheduled launcher for OVERNIGHT-002."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

TASK_ROOT = Path(__file__).resolve().parents[1]
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))

from momentum_hunter.overnight_midweek_replication import (
    OvernightReplicationError,
    build_comparison,
    canonical_json,
    ensure_sanitized,
    render_markdown,
    require_midweek_overnight,
    write_once,
)


SCHWAB_COMMIT = "295ab243e1b908ca1e20ae20c7fbd6b8ea7834bf"
SCHWAB_MODULE_SHA256 = "CE3FE31E7120C259A8D97AC16172B650ED57DCABC8159467E337D29C0581730A"
ALPACA_COMMIT = "897f18a6b27ee050767feb8ed6f805f34ea4305c"
ALPACA_MODULE_SHA256 = "30D39D8BBCB84EAEC4995A96E1FA4FB2BDBE34F4C9714997586167E250ACC992"
UTC = timezone.utc


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, timeout=30
    )
    return completed.stdout.strip()


def verify_source(root: Path, *, commit: str, module: str, module_hash: str) -> dict[str, object]:
    if _git(root, "rev-parse", "HEAD") != commit:
        raise OvernightReplicationError(f"Frozen source identity mismatch: {root.name}")
    if _git(root, "status", "--porcelain"):
        raise OvernightReplicationError(f"Frozen source worktree is dirty: {root.name}")
    path = root / module
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest().upper()
    if actual_hash != module_hash:
        raise OvernightReplicationError(f"Frozen module hash mismatch: {path.name}")
    return {
        "root": str(root),
        "commit": commit,
        "module": module,
        "moduleSha256": module_hash,
        "clean": True,
    }


def run_replication(
    *,
    output_dir: Path,
    python: Path,
    shim: Path,
    schwab_root: Path,
    alpaca_root: Path,
    duration_seconds: int,
) -> dict[str, object]:
    if not 300 <= duration_seconds <= 600:
        raise OvernightReplicationError("Duration must be between 300 and 600 seconds.")
    expected_shim = (TASK_ROOT / "tools/run_midweek_overnight_probe.py").resolve()
    if shim.resolve() != expected_shim:
        raise OvernightReplicationError("The replication refused an unpinned probe shim.")
    if not python.is_file():
        raise OvernightReplicationError("The pinned Python executable is unavailable.")
    orchestrator_status = _git(TASK_ROOT, "status", "--porcelain")
    if orchestrator_status:
        raise OvernightReplicationError("The replication orchestrator worktree is dirty.")
    require_midweek_overnight(datetime.now(UTC))
    raw = output_dir / "raw"
    logs = output_dir / "logs"
    baseline = output_dir / "baseline"
    for path in (raw, logs, baseline):
        path.mkdir(parents=True, exist_ok=True)
    source_identity = {
        "orchestrator": {
            "root": str(TASK_ROOT),
            "commit": _git(TASK_ROOT, "rev-parse", "HEAD"),
            "clean": True,
            "shim": str(expected_shim),
            "shimSha256": hashlib.sha256(expected_shim.read_bytes()).hexdigest().upper(),
        },
        "schwab": verify_source(
            schwab_root,
            commit=SCHWAB_COMMIT,
            module="momentum_hunter/schwab_overnight_probe.py",
            module_hash=SCHWAB_MODULE_SHA256,
        ),
        "alpaca": verify_source(
            alpaca_root,
            commit=ALPACA_COMMIT,
            module="momentum_hunter/alpaca_overnight_probe.py",
            module_hash=ALPACA_MODULE_SHA256,
        ),
    }
    schwab_sunday_source = schwab_root / "docs/argus-office/reports/releases/ARGUS-SCHWAB-OVERNIGHT-001-proof.json"
    alpaca_sunday_source = alpaca_root / "docs/argus-office/reports/releases/ARGUS-OVERNIGHT-001-sunday-night-proof.json"
    schwab_sunday = baseline / "schwab-sunday.json"
    alpaca_sunday = baseline / "alpaca-sunday.json"
    if schwab_sunday.exists() or alpaca_sunday.exists():
        raise OvernightReplicationError("Baseline output already exists.")
    shutil.copyfile(schwab_sunday_source, schwab_sunday)
    shutil.copyfile(alpaca_sunday_source, alpaca_sunday)

    schwab_output = raw / "schwab-midweek.json"
    start_dir = raw / "alpaca-start"
    end_dir = raw / "alpaca-end"
    started = datetime.now(UTC)
    window_started_monotonic = time.monotonic()
    schwab_command = [
        str(python), "-B", str(shim), "schwab", "--source-root", str(schwab_root),
        "--output", str(schwab_output), "--duration-seconds", str(duration_seconds),
    ]
    alpaca_start_command = [
        str(python), "-B", str(shim), "alpaca", "--source-root", str(alpaca_root),
        "--output-dir", str(start_dir), "--phase", "start", "--repeat-delay-seconds", "5",
    ]
    schwab_process = subprocess.Popen(schwab_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    alpaca_start = subprocess.run(
        alpaca_start_command, capture_output=True, text=True, timeout=90, check=False
    )
    _write_log(logs / "alpaca-start.stdout.txt", alpaca_start.stdout)
    _write_log(logs / "alpaca-start.stderr.txt", alpaca_start.stderr)
    end_sample_at = window_started_monotonic + max(0, duration_seconds - 15)
    while time.monotonic() < end_sample_at:
        time.sleep(min(5.0, end_sample_at - time.monotonic()))
    alpaca_end_command = [
        str(python), "-B", str(shim), "alpaca", "--source-root", str(alpaca_root),
        "--output-dir", str(end_dir), "--phase", "end", "--repeat-delay-seconds", "5",
    ]
    alpaca_end = subprocess.run(
        alpaca_end_command, capture_output=True, text=True, timeout=90, check=False
    )
    _write_log(logs / "alpaca-end.stdout.txt", alpaca_end.stdout)
    _write_log(logs / "alpaca-end.stderr.txt", alpaca_end.stderr)
    try:
        schwab_stdout, schwab_stderr = schwab_process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        schwab_process.kill()
        schwab_stdout, schwab_stderr = schwab_process.communicate()
    _write_log(logs / "schwab.stdout.txt", schwab_stdout)
    _write_log(logs / "schwab.stderr.txt", schwab_stderr)

    exits = {
        "schwab": schwab_process.returncode,
        "alpacaStart": alpaca_start.returncode,
        "alpacaEnd": alpaca_end.returncode,
    }
    schwab_proof = _read_json(schwab_output)
    alpaca_start_proof = _read_json(start_dir / "alpaca-midweek-start.json")
    alpaca_end_proof = _read_json(end_dir / "alpaca-midweek-end.json")
    comparison = build_comparison(
        schwab_sunday=_read_json(schwab_sunday) or {},
        alpaca_sunday=_read_json(alpaca_sunday) or {},
        schwab_midweek=schwab_proof,
        alpaca_midweek_start=alpaca_start_proof,
        alpaca_midweek_end=alpaca_end_proof,
        source_identity=source_identity,
        created_at=datetime.now(UTC),
    )
    comparison_json = output_dir / "OVERNIGHT-002-midweek-comparison.json"
    comparison_md = output_dir / "OVERNIGHT-002-midweek-comparison.md"
    write_once(comparison_json, canonical_json(comparison))
    write_once(comparison_md, render_markdown(comparison).encode("utf-8"))
    receipt = {
        "schemaVersion": "OVERNIGHT_002_RUN_RECEIPT_V1",
        "startedAt": started.isoformat(),
        "completedAt": datetime.now(UTC).isoformat(),
        "exitCodes": exits,
        "terminalStatus": "COMPLETED" if all(value == 0 for value in exits.values()) else "FAILED",
        "overallClassification": comparison["overallClassification"],
        "readOnly": True,
        "schedulerChanged": False,
        "serviceChanged": False,
        "ordersRequested": False,
    }
    receipt_path = output_dir / "run-receipt.json"
    write_once(receipt_path, canonical_json(receipt))
    evidence_paths = sorted(
        path for path in output_dir.rglob("*") if path.is_file() and path.name != "SHA256SUMS.json"
    )
    ensure_sanitized(evidence_paths)
    manifest = {
        "schemaVersion": "OVERNIGHT_002_HASH_MANIFEST_V1",
        "files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                "bytes": path.stat().st_size,
            }
            for path in evidence_paths
        ],
    }
    write_once(output_dir / "SHA256SUMS.json", canonical_json(manifest))
    return receipt


def wait_and_run(args: argparse.Namespace) -> int:
    target = datetime.fromisoformat(args.target_local)
    if target.tzinfo is None or target.utcoffset() is None:
        raise OvernightReplicationError("Target time must include an explicit UTC offset.")
    now = datetime.now(UTC)
    delay = (target.astimezone(UTC) - now).total_seconds()
    if not 0 < delay <= 24 * 60 * 60:
        raise OvernightReplicationError("Target time must be within the next 24 hours.")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    arm_receipt = {
        "schemaVersion": "OVERNIGHT_002_ARM_RECEIPT_V1",
        "armedAt": now.isoformat(),
        "targetLocal": target.isoformat(),
        "targetUtc": target.astimezone(UTC).isoformat(),
        "processId": __import__("os").getpid(),
        "mechanism": "ONE_USE_USER_SESSION_WAITER",
        "taskSchedulerChanged": False,
        "serviceChanged": False,
        "requiresPoweredOn": True,
        "requiresUserSessionSignedIn": True,
        "lockedSessionAllowed": True,
        "survivesRebootOrLogout": False,
    }
    write_once(args.output_dir / "arm-receipt.json", canonical_json(arm_receipt))
    while datetime.now(UTC) < target.astimezone(UTC):
        remaining = (target.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        time.sleep(min(30.0, max(0.1, remaining)))
    try:
        run_replication(
            output_dir=args.output_dir,
            python=args.python,
            shim=args.shim,
            schwab_root=args.schwab_root,
            alpaca_root=args.alpaca_root,
            duration_seconds=args.duration_seconds,
        )
        return 0
    except Exception as exc:
        failure = {
            "schemaVersion": "OVERNIGHT_002_LAUNCH_FAILURE_V1",
            "failedAt": datetime.now(UTC).isoformat(),
            "exceptionType": type(exc).__name__,
            "message": str(exc),
            "terminalStatus": "FAILED",
            "retryAttempted": False,
            "ordersRequested": False,
            "serviceChanged": False,
            "schedulerChanged": False,
        }
        failure_path = args.output_dir / "launcher-failure.json"
        if not failure_path.exists():
            write_once(failure_path, canonical_json(failure))
        raise


def _write_log(path: Path, value: str) -> None:
    safe = value.replace("APCA-API-KEY-ID", "[REDACTED_HEADER]").replace(
        "APCA-API-SECRET-KEY", "[REDACTED_HEADER]"
    )
    write_once(path, safe.encode("utf-8"))


def _read_json(path: Path) -> Mapping[str, object] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, Mapping) else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the one-use midweek overnight replication.")
    parser.add_argument("--target-local", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--shim", type=Path, required=True)
    parser.add_argument("--schwab-root", type=Path, required=True)
    parser.add_argument("--alpaca-root", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    return wait_and_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
