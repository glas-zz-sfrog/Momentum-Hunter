from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.entry_plans import ENTRY_PLANS_PATH
from momentum_hunter.monitor_targets import MONITOR_SYMBOLS_PATH
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.storage import file_sha256
from momentum_hunter.time_utils import now_central


USER_STATE_SAFETY_VERSION = "sqlite_user_state_safety_cage_v1"
BACKUP_ROOT = DATA_DIR.parent / "backups" / "user-state"
USER_STATE_BACKUP_LATEST_JSON = DATA_DIR / "reports" / "user-state-backup-latest.json"
USER_STATE_BACKUP_LATEST_MD = DATA_DIR / "reports" / "user-state-backup-latest.md"
USER_STATE_RESTORE_VALIDATION_LATEST_JSON = DATA_DIR / "reports" / "user-state-restore-validation-latest.json"
USER_STATE_RESTORE_VALIDATION_LATEST_MD = DATA_DIR / "reports" / "user-state-restore-validation-latest.md"


@dataclass(frozen=True)
class UserStateSource:
    category: str
    path: Path
    required: bool
    authoritative: bool
    user_authored: bool
    description: str


@dataclass(frozen=True)
class UserStateFileRecord:
    category: str
    source_path: str
    backup_relative_path: str
    exists: bool
    required: bool
    authoritative: bool
    user_authored: bool
    size_bytes: int
    sha256: str
    description: str


def discover_user_state_sources(data_dir: Path = DATA_DIR) -> list[UserStateSource]:
    sources = [
        UserStateSource(
            "candidate_reviews",
            data_dir / REVIEW_DECISIONS_PATH.name,
            True,
            True,
            True,
            "Authoritative review decisions and review/watchlist status transitions.",
        ),
        UserStateSource(
            "entry_plans",
            data_dir / ENTRY_PLANS_PATH.name,
            True,
            True,
            True,
            "Authoritative entry-plan/journaling records for watchlist candidates.",
        ),
        UserStateSource(
            "monitor_symbols",
            data_dir / MONITOR_SYMBOLS_PATH.name,
            False,
            True,
            True,
            "Optional user-defined active monitor symbols.",
        ),
    ]
    for path in sorted(data_dir.glob("watchlist-*.json")):
        sources.append(
            UserStateSource(
                "watchlist_items",
                path,
                False,
                True,
                True,
                "Generated/user watchlist artifact for a review date.",
            )
        )
    for path in sorted(data_dir.glob("watchlist-report-*.md")):
        sources.append(
            UserStateSource(
                "watchlist_reports",
                path,
                False,
                False,
                False,
                "Human-readable derived watchlist report artifact.",
            )
        )
    return sources


def build_user_state_backup(
    *,
    data_dir: Path = DATA_DIR,
    backup_root: Path = BACKUP_ROOT,
    generated_at: str | None = None,
    sqlite_schema_version: int | None = None,
) -> dict[str, Any]:
    ensure_app_dirs()
    generated_at = generated_at or now_central().isoformat()
    backup_id = safe_timestamp(generated_at)
    backup_dir = backup_root / backup_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    records: list[UserStateFileRecord] = []
    warnings: list[str] = []
    for source in discover_user_state_sources(data_dir):
        exists = source.path.exists()
        relative = backup_relative_path(source.path, data_dir=data_dir)
        record = UserStateFileRecord(
            category=source.category,
            source_path=str(source.path),
            backup_relative_path=relative.as_posix(),
            exists=exists,
            required=source.required,
            authoritative=source.authoritative,
            user_authored=source.user_authored,
            size_bytes=source.path.stat().st_size if exists else 0,
            sha256=file_sha256(source.path) if exists else "",
            description=source.description,
        )
        records.append(record)
        if exists:
            destination = backup_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source.path, destination)
        elif source.required:
            warnings.append(f"REQUIRED_USER_STATE_FILE_MISSING:{source.path}")
        else:
            warnings.append(f"OPTIONAL_USER_STATE_FILE_MISSING:{source.path}")

    payload = {
        "schema_version": 1,
        "engine_version": USER_STATE_SAFETY_VERSION,
        "generated_at": generated_at,
        "backup_id": backup_id,
        "backup_dir": str(backup_dir),
        "sqlite_schema_version": sqlite_schema_version,
        "files": [asdict(record) for record in records],
        "summary": summarize_file_records(records),
        "warnings": warnings,
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_user_state_backup_report(payload)
    return payload


def validate_user_state_backup_restore(
    backup_dir: Path,
    *,
    validation_dir: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or now_central().isoformat()
    manifest_path = backup_dir / "manifest.json"
    warnings: list[str] = []
    if not manifest_path.exists():
        payload = {
            "schema_version": 1,
            "engine_version": USER_STATE_SAFETY_VERSION,
            "generated_at": generated_at,
            "backup_dir": str(backup_dir),
            "validation_dir": str(validation_dir or ""),
            "overall_status": "FAIL",
            "files_checked": 0,
            "files_restored": 0,
            "missing_files": 0,
            "hash_mismatches": 0,
            "file_results": [],
            "warnings": [f"BACKUP_MANIFEST_MISSING:{manifest_path}"],
        }
        write_user_state_restore_validation_report(payload)
        return payload

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validation_dir = validation_dir or (backup_dir / "restore-validation")
    if validation_dir.exists():
        shutil.rmtree(validation_dir)
    validation_dir.mkdir(parents=True, exist_ok=True)

    file_results: list[dict[str, Any]] = []
    restored = 0
    missing = 0
    mismatches = 0
    for item in manifest.get("files", []):
        if not isinstance(item, dict):
            continue
        relative_path = Path(str(item.get("backup_relative_path", "")))
        expected_hash = str(item.get("sha256", ""))
        existed_at_backup = bool(item.get("exists", False))
        source_backup = backup_dir / relative_path
        restore_path = validation_dir / relative_path
        result = {
            "category": item.get("category", ""),
            "backup_relative_path": relative_path.as_posix(),
            "expected_hash": expected_hash,
            "actual_hash": "",
            "status": "PASS",
        }
        if not existed_at_backup:
            result["status"] = "MISSING_AT_BACKUP"
            file_results.append(result)
            continue
        if not source_backup.exists():
            missing += 1
            result["status"] = "MISSING_BACKUP_FILE"
            warnings.append(f"MISSING_BACKUP_FILE:{source_backup}")
            file_results.append(result)
            continue
        restore_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_backup, restore_path)
        restored += 1
        actual_hash = file_sha256(restore_path)
        result["actual_hash"] = actual_hash
        if expected_hash and actual_hash != expected_hash:
            mismatches += 1
            result["status"] = "HASH_MISMATCH"
            warnings.append(f"HASH_MISMATCH:{relative_path}")
        file_results.append(result)

    status = "FAIL" if missing or mismatches else "WARN" if warnings else "PASS"
    payload = {
        "schema_version": 1,
        "engine_version": USER_STATE_SAFETY_VERSION,
        "generated_at": generated_at,
        "backup_dir": str(backup_dir),
        "validation_dir": str(validation_dir),
        "overall_status": status,
        "files_checked": len(file_results),
        "files_restored": restored,
        "missing_files": missing,
        "hash_mismatches": mismatches,
        "manifest_file_count": len(manifest.get("files", [])) if isinstance(manifest.get("files", []), list) else 0,
        "file_results": file_results,
        "warnings": warnings,
    }
    write_user_state_restore_validation_report(payload)
    return payload


def write_user_state_backup_report(
    payload: dict[str, Any],
    *,
    json_path: Path = USER_STATE_BACKUP_LATEST_JSON,
    markdown_path: Path = USER_STATE_BACKUP_LATEST_MD,
) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_user_state_backup_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def write_user_state_restore_validation_report(
    payload: dict[str, Any],
    *,
    json_path: Path = USER_STATE_RESTORE_VALIDATION_LATEST_JSON,
    markdown_path: Path = USER_STATE_RESTORE_VALIDATION_LATEST_MD,
) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_restore_validation_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def summarize_file_records(records: list[UserStateFileRecord]) -> dict[str, Any]:
    category_counts: dict[str, int] = {}
    existing = 0
    missing = 0
    for record in records:
        category_counts[record.category] = category_counts.get(record.category, 0) + 1
        if record.exists:
            existing += 1
        else:
            missing += 1
    return {
        "files_considered": len(records),
        "files_included": existing,
        "files_missing": missing,
        "category_counts": category_counts,
    }


def format_user_state_backup_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    files = payload.get("files", [])
    warnings = payload.get("warnings", [])
    lines = [
        "# Momentum Hunter User State Backup",
        "",
        "Backup safety report. Live user-state files were copied only; source files were not modified.",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Backup directory: `{payload.get('backup_dir', '')}`",
        f"- SQLite schema version: {payload.get('sqlite_schema_version', '')}",
        f"- Files considered: {summary.get('files_considered', 0) if isinstance(summary, dict) else 0}",
        f"- Files included: {summary.get('files_included', 0) if isinstance(summary, dict) else 0}",
        f"- Files missing: {summary.get('files_missing', 0) if isinstance(summary, dict) else 0}",
        "",
        "## Files",
        "",
    ]
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('category', '')}: `{item.get('source_path', '')}` "
                    f"exists={item.get('exists', False)} size={item.get('size_bytes', 0)}"
                )
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] if isinstance(warnings, list) and warnings else ["- None."])
    return "\n".join(lines) + "\n"


def format_restore_validation_markdown(payload: dict[str, Any]) -> str:
    warnings = payload.get("warnings", [])
    lines = [
        "# Momentum Hunter User State Restore Validation",
        "",
        "Restore validation report. Files were restored into a temporary validation directory only; live user state was not touched.",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Backup directory: `{payload.get('backup_dir', '')}`",
        f"- Validation directory: `{payload.get('validation_dir', '')}`",
        f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Files checked: {payload.get('files_checked', 0)}",
        f"- Files restored: {payload.get('files_restored', 0)}",
        f"- Missing files: {payload.get('missing_files', 0)}",
        f"- Hash mismatches: {payload.get('hash_mismatches', 0)}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in warnings] if isinstance(warnings, list) and warnings else ["- None."])
    return "\n".join(lines) + "\n"


def backup_relative_path(path: Path, *, data_dir: Path = DATA_DIR) -> Path:
    try:
        return Path("data") / path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return Path("external") / path.name


def safe_timestamp(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())
    return digits[:14] or now_central().strftime("%Y%m%d%H%M%S")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup and validate Momentum Hunter user-authored state.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    backup_parser.add_argument("--backup-root", type=Path, default=BACKUP_ROOT)
    restore_parser = subparsers.add_parser("validate-restore")
    restore_parser.add_argument("backup_dir", type=Path)
    restore_parser.add_argument("--validation-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "backup":
        payload = build_user_state_backup(data_dir=args.data_dir, backup_root=args.backup_root)
    else:
        payload = validate_user_state_backup_restore(args.backup_dir, validation_dir=args.validation_dir)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("overall_status", "PASS") in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
