from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.storage import (
    CAPTURE_INTEGRITY_MANIFEST,
    CAPTURES_DIR,
    capture_manifest_key,
    capture_source_hash,
    file_sha256,
    load_capture_integrity_manifest,
)


OK = "OK"
MODIFIED = "MODIFIED"
MISSING = "MISSING"
UNTRACKED = "UNTRACKED"
JSON_SOURCE_HASH_MISMATCH = "JSON_SOURCE_HASH_MISMATCH"

AUDIT_CSV = DATA_DIR / "raw-capture-integrity-audit.csv"
AUDIT_MD = DATA_DIR / "raw-capture-integrity-audit.md"


@dataclass(frozen=True)
class IntegrityAuditRow:
    path: str
    kind: str
    status: str
    created_at: str = ""
    manifest_hash: str = ""
    current_hash: str = ""
    details: str = ""


def audit_raw_captures(
    *,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
) -> list[IntegrityAuditRow]:
    manifest = load_capture_integrity_manifest(manifest_path)
    records = manifest.get("records", {})
    rows: list[IntegrityAuditRow] = []
    seen_paths: set[str] = set()

    for key, record in sorted(records.items()):
        path = resolve_manifest_path(key)
        seen_paths.add(key)
        expected_hash = record.get("source_hash", "")
        if not path.exists():
            rows.append(
                IntegrityAuditRow(
                    path=key,
                    kind=record.get("kind", ""),
                    status=MISSING,
                    created_at=record.get("created_at", ""),
                    manifest_hash=expected_hash,
                    details="Manifest references a raw capture file that no longer exists.",
                )
            )
            continue
        current_hash = file_sha256(path)
        status = OK if current_hash == expected_hash else MODIFIED
        details = "" if status == OK else "Raw capture file hash differs from manifest."
        json_status, json_details = json_source_hash_status(path)
        if json_status == JSON_SOURCE_HASH_MISMATCH:
            status = JSON_SOURCE_HASH_MISMATCH if status == OK else status
            details = "; ".join(item for item in [details, json_details] if item)
        rows.append(
            IntegrityAuditRow(
                path=key,
                kind=record.get("kind", ""),
                status=status,
                created_at=record.get("created_at", ""),
                manifest_hash=expected_hash,
                current_hash=current_hash,
                details=details,
            )
        )

    for path in sorted(raw_capture_files(captures_dir)):
        key = capture_manifest_key(path)
        if key in seen_paths:
            continue
        status, details = json_source_hash_status(path)
        if status == OK:
            status = UNTRACKED
            details = "Raw capture file has embedded JSON integrity but is not listed in manifest."
        elif status != JSON_SOURCE_HASH_MISMATCH:
            status = UNTRACKED
            details = "Raw capture file predates the integrity manifest or was not created through capture storage."
        rows.append(
            IntegrityAuditRow(
                path=key,
                kind=kind_for_path(path),
                status=status,
                current_hash=file_sha256(path),
                details=details,
            )
        )

    return rows


def write_integrity_audit_report(
    rows: list[IntegrityAuditRow],
    *,
    csv_path: Path = AUDIT_CSV,
    markdown_path: Path = AUDIT_MD,
) -> tuple[Path, Path]:
    ensure_app_dirs()
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["path", "kind", "status", "created_at", "manifest_hash", "current_hash", "details"]
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)
    markdown_path.write_text(integrity_audit_markdown(rows), encoding="utf-8")
    return csv_path, markdown_path


def integrity_audit_markdown(rows: list[IntegrityAuditRow]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    lines = [
        "# Momentum Hunter Raw Capture Integrity Audit",
        "",
        "Raw capture JSON/MD files are expected to remain immutable after creation.",
        "",
        "## Summary",
        "",
    ]
    if counts:
        for status, count in sorted(counts.items()):
            lines.append(f"- {status}: {count}")
    else:
        lines.append("- No raw capture files found.")
    lines.extend(["", "## Details", "", "| Status | Kind | Path | Details |", "| --- | --- | --- | --- |"])
    for row in rows:
        lines.append(f"| {row.status} | {row.kind} | `{row.path}` | {row.details or ''} |")
    return "\n".join(lines)


def raw_capture_files(captures_dir: Path) -> list[Path]:
    if not captures_dir.exists():
        return []
    return [path for path in captures_dir.rglob("*") if path.suffix.lower() in {".json", ".md"} and path.is_file()]


def resolve_manifest_path(key: str) -> Path:
    path = Path(key)
    if path.is_absolute():
        return path
    return DATA_DIR / path


def kind_for_path(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "raw_capture_json"
    if path.suffix.lower() == ".md":
        return "raw_capture_markdown"
    return "raw_capture"


def json_source_hash_status(path: Path) -> tuple[str, str]:
    if path.suffix.lower() != ".json":
        return "", ""
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or not integrity.get("source_hash"):
        return "", ""
    actual = capture_source_hash(payload)
    expected = integrity["source_hash"]
    if actual != expected:
        return JSON_SOURCE_HASH_MISMATCH, "Embedded JSON source_hash does not match payload content."
    return OK, ""
