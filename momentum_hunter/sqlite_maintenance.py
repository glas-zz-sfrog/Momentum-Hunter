from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.sqlite_store import SQLITE_DB_PATH, SQLITE_SCHEMA_VERSION
from momentum_hunter.storage import file_sha256
from momentum_hunter.time_utils import now_central


REPORTS_DIR = DATA_DIR / "reports"
BACKUP_ROOT = DATA_DIR.parent / "backups" / "sqlite"

EXPECTED_TABLES = [
    "schema_migrations",
    "captures",
    "capture_candidates",
    "candidate_reviews",
    "watchlist_items",
    "entry_plans",
    "opportunity_alerts",
    "alert_outcomes",
    "minute_bars",
    "evidence_runs",
    "evidence_metrics",
    "system_status_events",
    "provider_quality_checks",
]

IMPORT_TIMESTAMP_COLUMNS = {
    "provider_quality_checks": ["generated_at"],
    "opportunity_alerts": ["imported_at", "updated_at"],
    "alert_outcomes": ["imported_at", "updated_at"],
    "minute_bars": ["imported_at", "updated_at"],
    "evidence_runs": ["imported_at", "updated_at", "generated_at"],
    "evidence_metrics": ["imported_at", "updated_at"],
    "system_status_events": ["imported_at", "updated_at", "generated_at"],
    "captures": ["imported_at", "updated_at", "capture_time"],
    "capture_candidates": ["imported_at", "updated_at"],
    "candidate_reviews": ["imported_at", "updated_at", "decision_timestamp"],
    "watchlist_items": ["imported_at", "updated_at", "created_at"],
    "entry_plans": ["imported_at", "updated_at"],
}


def open_read_only_database(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def build_sqlite_maintenance_report(
    *,
    db_path: Path = SQLITE_DB_PATH,
    backup_root: Path = BACKUP_ROOT,
    mode: str = "check",
) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    warnings: list[str] = []
    errors: list[str] = []
    database = db_path
    before_hash = safe_file_hash(database)
    file_size = database.stat().st_size if database.exists() else 0
    integrity_check = "NOT_RUN"
    schema_version = 0
    table_counts: dict[str, int] = {}
    latest_import_timestamps: dict[str, str] = {}
    missing_tables: list[str] = []
    backup: dict[str, Any] | None = None

    if not database.exists():
        errors.append(f"SQLITE_DATABASE_MISSING:{database}")
        overall_status = "FAIL"
    else:
        try:
            with open_read_only_database(database) as connection:
                integrity_check = run_integrity_check(connection)
                schema_version = current_schema_version(connection)
                existing_tables = list_tables(connection)
                missing_tables = [table for table in EXPECTED_TABLES if table not in existing_tables]
                table_counts = {table: table_count(connection, table) for table in EXPECTED_TABLES if table in existing_tables}
                latest_import_timestamps = latest_import_summary(connection, existing_tables)
        except sqlite3.Error as exc:
            errors.append(f"SQLITE_CHECK_FAILED:{type(exc).__name__}:{exc}")

        if integrity_check != "ok":
            errors.append(f"SQLITE_INTEGRITY_CHECK_FAILED:{integrity_check}")
        if schema_version < SQLITE_SCHEMA_VERSION:
            warnings.append(f"SQLITE_SCHEMA_BEHIND:{schema_version}<{SQLITE_SCHEMA_VERSION}")
        if missing_tables:
            errors.append("SQLITE_MISSING_TABLES:" + ",".join(missing_tables))

        if mode == "backup" and not errors:
            try:
                backup = create_sqlite_backup_snapshot(
                    database,
                    backup_root=backup_root,
                    generated_at=generated_at,
                    source_hash=before_hash,
                    schema_version=schema_version,
                    table_counts=table_counts,
                )
                if backup.get("validation_status") != "PASS":
                    warnings.append("SQLITE_BACKUP_VALIDATION_WARNING")
            except OSError as exc:
                errors.append(f"SQLITE_BACKUP_FAILED:{type(exc).__name__}:{exc}")

        after_hash = safe_file_hash(database)
        if before_hash and after_hash and before_hash != after_hash:
            errors.append("SQLITE_SOURCE_HASH_CHANGED_DURING_MAINTENANCE")

        overall_status = "FAIL" if errors else "WARN" if warnings else "PASS"

    return {
        "schema_version": 1,
        "engine_version": "sqlite_maintenance_v1",
        "generated_at": generated_at,
        "mode": mode,
        "overall_status": overall_status,
        "database_path": str(database),
        "database_exists": database.exists(),
        "database_size_bytes": file_size,
        "database_sha256": before_hash,
        "expected_schema_version": SQLITE_SCHEMA_VERSION,
        "sqlite_schema_version": schema_version,
        "integrity_check": integrity_check,
        "expected_tables": EXPECTED_TABLES,
        "missing_tables": missing_tables,
        "table_counts": table_counts,
        "latest_import_timestamps": latest_import_timestamps,
        "backup": backup,
        "warnings": warnings,
        "errors": errors,
    }


def create_sqlite_backup_snapshot(
    db_path: Path,
    *,
    backup_root: Path,
    generated_at: str,
    source_hash: str,
    schema_version: int,
    table_counts: dict[str, int],
) -> dict[str, Any]:
    stamp = now_central().strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_root / stamp
    counter = 1
    while backup_dir.exists():
        counter += 1
        backup_dir = backup_root / f"{stamp}-{counter:02d}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_path = backup_dir / db_path.name
    shutil.copy2(db_path, backup_path)
    backup_hash = file_sha256(backup_path)
    validation = validate_backup_database(backup_path)
    manifest = {
        "schema_version": 1,
        "engine_version": "sqlite_backup_manifest_v1",
        "generated_at": generated_at,
        "source_database_path": str(db_path),
        "backup_database_path": str(backup_path),
        "source_sha256": source_hash,
        "backup_sha256": backup_hash,
        "source_size_bytes": db_path.stat().st_size,
        "backup_size_bytes": backup_path.stat().st_size,
        "sqlite_schema_version": schema_version,
        "table_counts": table_counts,
        "validation_status": validation["status"],
        "validation_integrity_check": validation["integrity_check"],
        "warnings": validation["warnings"],
    }
    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "backup_dir": str(backup_dir),
        "backup_database_path": str(backup_path),
        "manifest_path": str(manifest_path),
        "backup_sha256": backup_hash,
        "validation_status": validation["status"],
        "validation_integrity_check": validation["integrity_check"],
        "warnings": validation["warnings"],
    }


def validate_backup_database(path: Path) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        with open_read_only_database(path) as connection:
            integrity_check = run_integrity_check(connection)
            status = "PASS" if integrity_check == "ok" else "WARN"
    except sqlite3.Error as exc:
        integrity_check = f"{type(exc).__name__}:{exc}"
        status = "FAIL"
        warnings.append("BACKUP_READ_FAILED")
    return {"status": status, "integrity_check": integrity_check, "warnings": warnings}


def run_integrity_check(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA integrity_check").fetchone()
    if row is None:
        return "UNKNOWN"
    return str(row[0])


def current_schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    except sqlite3.Error:
        return 0
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])


def list_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def table_count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"] if row else 0)


def latest_import_summary(connection: sqlite3.Connection, existing_tables: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for table, candidates in IMPORT_TIMESTAMP_COLUMNS.items():
        if table not in existing_tables:
            continue
        columns = table_columns(connection, table)
        expressions = [f"MAX({column})" for column in candidates if column in columns]
        if not expressions:
            continue
        row = connection.execute(f"SELECT {', '.join(expressions)} FROM {table}").fetchone()
        values = [str(value) for value in tuple(row) if value not in (None, "")]
        result[table] = max(values) if values else ""
    return result


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def safe_file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return file_sha256(path)


def write_sqlite_maintenance_report(
    payload: dict[str, Any],
    *,
    output_dir: Path = REPORTS_DIR,
) -> tuple[Path, Path]:
    ensure_app_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "sqlite-maintenance-latest.json"
    markdown_path = output_dir / "sqlite-maintenance-latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(sqlite_maintenance_markdown(payload), encoding="utf-8")
    return json_path, markdown_path


def sqlite_maintenance_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# SQLite Maintenance Report",
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Mode: {payload.get('mode', '')}",
        f"- Status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Database: `{payload.get('database_path', '')}`",
        f"- Integrity check: `{payload.get('integrity_check', '')}`",
        f"- Schema version: {payload.get('sqlite_schema_version', 0)} / expected {payload.get('expected_schema_version', 0)}",
        f"- Size: {payload.get('database_size_bytes', 0)} bytes",
        f"- SHA-256: `{payload.get('database_sha256', '')}`",
        "",
        "## Table Counts",
        "",
        "| Table | Rows | Latest import/update |",
        "| --- | ---: | --- |",
    ]
    table_counts = payload.get("table_counts") or {}
    latest = payload.get("latest_import_timestamps") or {}
    if table_counts:
        for table in sorted(table_counts):
            lines.append(f"| `{table}` | {table_counts[table]} | {latest.get(table, '')} |")
    else:
        lines.append("| n/a | 0 |  |")
    if payload.get("backup"):
        backup = payload["backup"]
        lines.extend(
            [
                "",
                "## Backup",
                "",
                f"- Backup directory: `{backup.get('backup_dir', '')}`",
                f"- Backup database: `{backup.get('backup_database_path', '')}`",
                f"- Manifest: `{backup.get('manifest_path', '')}`",
                f"- Backup SHA-256: `{backup.get('backup_sha256', '')}`",
                f"- Validation: {backup.get('validation_status', '')}",
                f"- Integrity check: `{backup.get('validation_integrity_check', '')}`",
            ]
        )
    warnings = payload.get("warnings") or []
    errors = payload.get("errors") or []
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in warnings] if warnings else ["- None"])
    lines.extend(["", "## Errors", ""])
    lines.extend([f"- {item}" for item in errors] if errors else ["- None"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check and back up the Momentum Hunter SQLite mirror.")
    parser.add_argument("--check", action="store_true", help="Run read-only integrity/schema/table checks.")
    parser.add_argument("--backup", action="store_true", help="Create a timestamped SQLite backup snapshot.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--backup-root", type=Path, default=BACKUP_ROOT)
    args = parser.parse_args(argv)

    mode = "backup" if args.backup else "check"
    payload = build_sqlite_maintenance_report(db_path=args.db, backup_root=args.backup_root, mode=mode)
    json_path, markdown_path = write_sqlite_maintenance_report(payload, output_dir=args.output_dir)
    payload = dict(payload)
    payload["report_paths"] = {"json": str(json_path), "markdown": str(markdown_path)}
    print(json.dumps(payload, indent=2))
    return 1 if payload.get("overall_status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
