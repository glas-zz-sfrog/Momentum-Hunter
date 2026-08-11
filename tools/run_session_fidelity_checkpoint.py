from __future__ import annotations

"""Dispatch one write-once SESSION-FIDELITY-001 checkpoint."""

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from momentum_hunter.session_fidelity import (
    TASK_ID,
    fingerprint,
    get_checkpoint,
    require_checkpoint_start,
    require_sanitized,
    write_json_once,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _verified_existing(path: Path, *, task_id: str | None = TASK_ID) -> bool:
    if not path.is_file():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(value, dict):
        return False
    if task_id is not None and value.get("taskId") != task_id:
        return False
    expected = str(value.get("evidenceFingerprint", ""))
    if not expected or expected != fingerprint(value):
        return False
    try:
        require_sanitized(value, forbidden_values=())
    except Exception:
        return False
    return True


def _run_child(command: Sequence[str], *, timeout: int) -> dict[str, object]:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=dict(os.environ),
    )
    return {
        "exitCode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def _child_result(
    *,
    provider: str,
    output: Path,
    result: Mapping[str, object],
) -> dict[str, object]:
    return {
        "provider": provider,
        "exitCode": int(result["exitCode"]),
        "outputName": output.name,
        "outputSha256": _hash(output) if output.is_file() else None,
        "stdout": str(result.get("stdout", "")),
        "stderr": str(result.get("stderr", "")),
    }


def run_checkpoint(
    code: str,
    *,
    output_dir: Path,
    python: Path,
    project_root: Path,
    alpaca_root: Path,
    overnight_shim: Path,
    schwab_overnight_root: Path,
) -> dict[str, object]:
    checkpoint = require_checkpoint_start(code, datetime.now(timezone.utc))
    if checkpoint.code in {"D", "I"}:
        raise RuntimeError("Existing lanes own checkpoints D and I.")
    root = output_dir.expanduser().resolve() / f"checkpoint-{checkpoint.code.lower()}"
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "checkpoint-manifest.json"
    if manifest_path.exists():
        if not _verified_existing(manifest_path):
            raise RuntimeError("The existing checkpoint manifest failed verification.")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    commands: list[tuple[str, Path, list[str]]] = []
    if checkpoint.code in {"A", "B", "C", "E", "F", "G"}:
        schwab_output = root / "schwab.json"
        if not _verified_existing(schwab_output):
            commands.append(
                (
                    "SCHWAB",
                    schwab_output,
                    [
                        str(python),
                        "-B",
                        "-m",
                        "momentum_hunter.session_fidelity",
                        "--checkpoint",
                        checkpoint.code,
                        "--output",
                        str(schwab_output),
                    ],
                )
            )
        if checkpoint.code in {"A", "B", "C"}:
            alpaca_output = root / "alpaca.json"
            if not _verified_existing(alpaca_output):
                commands.append(
                    (
                        "ALPACA",
                        alpaca_output,
                        [
                            str(python),
                            "-B",
                            str(project_root / "tools" / "run_session_fidelity_alpaca.py"),
                            "--checkpoint",
                            checkpoint.code,
                            "--source-root",
                            str(alpaca_root),
                            "--output",
                            str(alpaca_output),
                        ],
                    )
                )
    elif checkpoint.code == "H":
        schwab_output = root / "schwab.json"
        if not _verified_existing(schwab_output, task_id=None):
            commands.append(
                (
                    "SCHWAB",
                    schwab_output,
                    [
                        str(python),
                        "-B",
                        str(overnight_shim),
                        "schwab",
                        "--source-root",
                        str(schwab_overnight_root),
                        "--output",
                        str(schwab_output),
                        "--duration-seconds",
                        str(checkpoint.duration_seconds),
                    ],
                )
            )
        alpaca_output = root / "alpaca-midweek-start.json"
        alpaca_markdown = root / "alpaca-midweek-start.md"
        if not (_verified_existing(alpaca_output, task_id=None) and alpaca_markdown.is_file()):
            commands.append(
                (
                    "ALPACA",
                    alpaca_output,
                    [
                        str(python),
                        "-B",
                        str(overnight_shim),
                        "alpaca",
                        "--source-root",
                        str(alpaca_root),
                        "--output-dir",
                        str(root),
                        "--phase",
                        "start",
                        "--repeat-delay-seconds",
                        "5",
                    ],
                )
            )
    else:
        raise RuntimeError("Unsupported checkpoint.")

    child_rows: list[dict[str, object]] = []
    if commands:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(commands)) as pool:
            futures = {
                pool.submit(_run_child, command, timeout=checkpoint.duration_seconds + 120): (
                    provider,
                    output,
                )
                for provider, output, command in commands
            }
            for future in concurrent.futures.as_completed(futures):
                provider, output = futures[future]
                child_rows.append(
                    _child_result(provider=provider, output=output, result=future.result())
                )
    expected_outputs = [root / "schwab.json"]
    if checkpoint.alpaca:
        expected_outputs.append(
            root / ("alpaca-midweek-start.json" if checkpoint.code == "H" else "alpaca.json")
        )
    missing = [path.name for path in expected_outputs if not path.is_file()]
    failed = [row for row in child_rows if row["exitCode"] != 0]
    if missing or failed:
        attempt = {
            "taskId": TASK_ID,
            "checkpoint": checkpoint.evidence(),
            "completed": False,
            "missingOutputs": missing,
            "children": child_rows,
            "ordersRequested": False,
            "positionsRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }
        require_sanitized(attempt, forbidden_values=())
        attempt_name = (
            "failed-attempt-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + ".json"
        )
        (root / attempt_name).write_text(
            json.dumps(attempt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise RuntimeError("One or more read-only checkpoint providers failed safely.")

    evidence = [
        {
            "provider": "SCHWAB" if path.name.startswith("schwab") else "ALPACA",
            "fileName": path.name,
            "sha256": _hash(path),
        }
        for path in expected_outputs
    ]
    manifest = {
        "schemaVersion": 1,
        "taskId": TASK_ID,
        "mode": "READ_ONLY_NONPERSISTING_SESSION_FIDELITY",
        "checkpoint": checkpoint.evidence(),
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "status": "CAPTURED",
        "evidence": evidence,
        "children": sorted(child_rows, key=lambda row: str(row["provider"])),
        "productionPersistence": False,
        "accountValuesIncluded": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "previewsRequested": False,
        "orderTransmission": "UNAVAILABLE",
        "strategyAuthorityGranted": False,
        "executionAuthorityGranted": False,
        "credentialMaterialIncluded": False,
    }
    manifest["evidenceFingerprint"] = fingerprint(manifest)
    write_json_once(manifest, manifest_path)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one SESSION-FIDELITY-001 checkpoint.")
    parser.add_argument("--checkpoint", choices=tuple("ABCEFGH"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--alpaca-root", type=Path, required=True)
    parser.add_argument("--overnight-shim", type=Path, required=True)
    parser.add_argument("--schwab-overnight-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_checkpoint(
            args.checkpoint,
            output_dir=args.output_dir,
            python=args.python,
            project_root=args.project_root,
            alpaca_root=args.alpaca_root,
            overnight_shim=args.overnight_shim,
            schwab_overnight_root=args.schwab_overnight_root,
        )
        print(
            json.dumps(
                {
                    "checkpoint": args.checkpoint,
                    "status": result["status"],
                    "evidenceCount": len(result["evidence"]),
                    "ordersRequested": False,
                    "positionsRequested": False,
                    "orderTransmission": "UNAVAILABLE",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "SESSION_FIDELITY_CHECKPOINT_FAILED_SAFE",
                    "credentialMaterialIncluded": False,
                    "errorType": type(exc).__name__,
                    "ordersRequested": False,
                    "positionsRequested": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
