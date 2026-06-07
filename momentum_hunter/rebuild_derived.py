from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.integrity import (
    audit_raw_captures,
    overall_audit_status,
    raw_capture_files,
    write_integrity_audit_report,
)
from momentum_hunter.outcomes import OUTCOMES_CSV, update_outcomes
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.storage import (
    ANALYSIS_CSV,
    CAPTURE_INTEGRITY_MANIFEST,
    CAPTURE_VERSION,
    CAPTURES_DIR,
    capture_manifest_key,
    file_sha256,
    load_capture_integrity_manifest,
    save_capture_integrity_manifest,
    write_analysis_rows,
)
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


@dataclass(frozen=True)
class RebuildResult:
    analysis_path: Path
    outcomes_path: Path
    backup_dir: Path
    analysis_rows: int
    outcome_rows: int
    manifest_entries_added: int
    before_status: str
    after_status: str
    before_audit_csv: Path
    before_audit_report: Path
    after_audit_csv: Path
    after_audit_report: Path
    backups: list[Path] = field(default_factory=list)


def rebuild_derived_data_from_raw_captures(
    *,
    captures_dir: Path = CAPTURES_DIR,
    analysis_csv: Path = ANALYSIS_CSV,
    outcomes_csv: Path = OUTCOMES_CSV,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    backup_dir: Path | None = None,
    outcome_session: requests.Session | None = None,
    rebuild_outcomes: bool = True,
    before_audit_csv: Path | None = None,
    before_audit_report: Path | None = None,
    after_audit_csv: Path | None = None,
    after_audit_report: Path | None = None,
) -> RebuildResult:
    ensure_app_dirs()
    started_at = now_central()
    backup_dir = backup_dir or DATA_DIR / "backups" / "derived-rebuild" / started_at.strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    raw_hashes_before = raw_capture_hashes(captures_dir)

    before_rows = audit_raw_captures(
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        analysis_csv=analysis_csv,
        outcomes_csv=outcomes_csv,
        review_decisions_path=review_decisions_path,
    )
    before_audit_csv, before_audit_report = write_integrity_audit_report(
        before_rows,
        csv_path=before_audit_csv or DATA_DIR / "integrity" / "raw_capture_integrity_audit_before_rebuild.csv",
        markdown_path=before_audit_report or DATA_DIR / "integrity" / "raw_capture_integrity_audit_before_rebuild.md",
    )

    backups = backup_existing_csvs([analysis_csv, outcomes_csv], backup_dir)
    manifest_entries_added = register_legacy_raw_captures(
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        registered_at=started_at,
    )

    analysis_rows = build_analysis_rows_from_raw_captures(captures_dir)
    write_analysis_rows(analysis_rows, analysis_csv)

    if rebuild_outcomes:
        _, outcome_rows = update_outcomes(
            capture_path=analysis_csv,
            output_path=outcomes_csv,
            session=outcome_session,
        )
    else:
        outcome_rows = 0
        if outcomes_csv.exists():
            outcomes_csv.unlink()

    raw_hashes_after = raw_capture_hashes(captures_dir)
    if raw_hashes_before != raw_hashes_after:
        raise RuntimeError("Raw capture files changed during derived-data rebuild.")

    after_rows = audit_raw_captures(
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        analysis_csv=analysis_csv,
        outcomes_csv=outcomes_csv,
        review_decisions_path=review_decisions_path,
    )
    after_audit_csv, after_audit_report = write_integrity_audit_report(
        after_rows,
        csv_path=after_audit_csv or DATA_DIR / "integrity" / "raw_capture_integrity_audit_after_rebuild.csv",
        markdown_path=after_audit_report or DATA_DIR / "integrity" / "raw_capture_integrity_audit_after_rebuild.md",
    )

    return RebuildResult(
        analysis_path=analysis_csv,
        outcomes_path=outcomes_csv,
        backup_dir=backup_dir,
        analysis_rows=len(analysis_rows),
        outcome_rows=outcome_rows,
        manifest_entries_added=manifest_entries_added,
        before_status=overall_audit_status(before_rows),
        after_status=overall_audit_status(after_rows),
        before_audit_csv=before_audit_csv,
        before_audit_report=before_audit_report,
        after_audit_csv=after_audit_csv,
        after_audit_report=after_audit_report,
        backups=backups,
    )


def build_analysis_rows_from_raw_captures(captures_dir: Path = CAPTURES_DIR) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(captures_dir.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        normalized = normalized_capture_payload(payload)
        for index, candidate in enumerate(normalized.get("candidates", []), 1):
            row = analysis_row_from_normalized_capture(normalized, candidate, fallback_rank=index)
            rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            row.get("capture_date", ""),
            row.get("capture_time", ""),
            session_order(row.get("session", "")),
            int_or_zero(row.get("rank", "")),
            row.get("ticker", ""),
        ),
    )


def normalized_capture_payload(payload: dict) -> dict:
    output = dict(payload)
    output.setdefault("capture_date", capture_date_from_time(output.get("capture_time", "")))
    output.setdefault("session", "")
    output.setdefault("mode", "")
    output.setdefault("provider", "")
    output.setdefault("scanner", {})
    output.setdefault("market", {})
    return output


def analysis_row_from_normalized_capture(payload: dict, candidate: dict, *, fallback_rank: int) -> dict:
    from momentum_hunter.storage import analysis_row_from_capture

    candidate_payload = dict(candidate)
    candidate_payload.setdefault("rank", fallback_rank)
    candidate_payload.setdefault("selected", bool(candidate.get("selected", False)))
    candidate_payload.setdefault("reviewed", bool(candidate.get("reviewed", False)))
    return analysis_row_from_capture(payload, candidate_payload)


def register_legacy_raw_captures(
    *,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    registered_at: datetime | None = None,
) -> int:
    registered_at = registered_at or now_central()
    manifest = load_capture_integrity_manifest(manifest_path)
    manifest["schema_version"] = 2
    records = manifest.setdefault("records", {})
    added = 0
    for path in sorted(raw_capture_files(captures_dir)):
        key = capture_manifest_key(path)
        if key in records:
            continue
        metadata = raw_capture_metadata(path, registered_at)
        records[key] = {
            "kind": raw_capture_kind(path),
            "capture_version": metadata["capture_version"],
            "created_at": metadata["created_at"],
            "registered_at": registered_at.isoformat(),
            "capture_time": metadata["capture_time"],
            "capture_date": metadata["capture_date"],
            "session": metadata["session"],
            "provider": metadata["provider"],
            "scanner": metadata["scanner"],
            "hash_algorithm": "sha256",
            "source_hash": file_sha256(path),
        }
        added += 1
    manifest["updated_at"] = registered_at.isoformat()
    save_capture_integrity_manifest(manifest, manifest_path)
    return added


def raw_capture_metadata(path: Path, registered_at: datetime) -> dict:
    payload = load_neighbor_json_payload(path)
    capture_time = payload.get("capture_time", "") if payload else ""
    capture_date = payload.get("capture_date", "") if payload else path.parent.name
    session = payload.get("session", "") if payload else path.stem
    scanner = payload.get("scanner", {}) if payload else {}
    scanner_name = scanner.get("name", "") if isinstance(scanner, dict) else str(scanner)
    schema_version = payload.get("schema_version", "") if payload else ""
    created_at = datetime.fromtimestamp(path.stat().st_ctime, tz=CENTRAL_TZ).isoformat()
    return {
        "capture_version": f"raw-capture-v{schema_version}" if schema_version else CAPTURE_VERSION,
        "created_at": created_at,
        "capture_time": capture_time,
        "capture_date": capture_date,
        "session": session,
        "provider": payload.get("provider", "") if payload else "",
        "scanner": scanner_name,
    }


def load_neighbor_json_payload(path: Path) -> dict:
    json_path = path if path.suffix.lower() == ".json" else path.with_suffix(".json")
    if not json_path.exists():
        return {}
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def raw_capture_kind(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "raw_capture_json"
    if path.suffix.lower() == ".md":
        return "raw_capture_markdown"
    return "raw_capture"


def backup_existing_csvs(paths: list[Path], backup_dir: Path) -> list[Path]:
    backups: list[Path] = []
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        destination = backup_dir / path.name
        shutil.copy2(path, destination)
        backups.append(destination)
    return backups


def raw_capture_hashes(captures_dir: Path) -> dict[str, str]:
    return {capture_manifest_key(path): file_sha256(path) for path in sorted(raw_capture_files(captures_dir))}


def capture_date_from_time(value: str) -> str:
    return value[:10] if value else ""


def session_order(session: str) -> int:
    return {"morning": 0, "evening": 1, "preopen": 2, "manual": 3}.get(session, 9)


def int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
