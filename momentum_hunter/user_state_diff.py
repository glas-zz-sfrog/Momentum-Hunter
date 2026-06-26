from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.entry_plans import ENTRY_PLANS_PATH
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.sqlite_store import (
    SQLITE_DB_PATH,
    candidate_review_row,
    connect_database,
    entry_plan_row,
    initialize_schema,
    load_entry_plan_source_records,
    load_review_source_records,
    load_watchlist_source_records,
    watchlist_item_row,
)
from momentum_hunter.time_utils import now_central


USER_STATE_DIFF_LATEST_JSON = DATA_DIR / "reports" / "sqlite-user-state-diff-latest.json"
USER_STATE_DIFF_LATEST_MD = DATA_DIR / "reports" / "sqlite-user-state-diff-latest.md"

USER_STATE_TABLES = {
    "candidate_reviews": ("capture_id", "ticker"),
    "entry_plans": ("capture_id", "ticker"),
    "watchlist_items": ("capture_id", "ticker", "watchlist_date"),
}

COMPARE_EXCLUDE = {
    "candidate_reviews": {"imported_at", "updated_at"},
    "entry_plans": {"imported_at"},
    "watchlist_items": {"imported_at", "updated_at"},
}


def build_user_state_diff_report(
    *,
    db_path: Path | None = None,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    data_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    database = db_path or SQLITE_DB_PATH
    imported_at = generated_at
    warnings: list[str] = []
    source_rows: dict[str, dict[str, dict[str, Any]]] = {
        "candidate_reviews": {},
        "entry_plans": {},
        "watchlist_items": {},
    }
    source_files: list[str] = []

    review_records, review_warnings = load_review_source_records(review_decisions_path)
    warnings.extend(review_warnings)
    if review_decisions_path.exists():
        source_files.append(str(review_decisions_path))
    for record in review_records:
        row = candidate_review_row(record, imported_at=imported_at)
        source_rows["candidate_reviews"][row_key("candidate_reviews", row)] = row

    entry_records, entry_warnings = load_entry_plan_source_records(entry_plans_path)
    warnings.extend(entry_warnings)
    if entry_plans_path.exists():
        source_files.append(str(entry_plans_path))
    for record in entry_records:
        row = entry_plan_row(record, imported_at=imported_at)
        source_rows["entry_plans"][row_key("entry_plans", row)] = row

    watchlist_files = sorted(data_dir.glob("watchlist-*.json"))
    for path in watchlist_files:
        source_files.append(str(path))
        records, file_warnings = load_watchlist_source_records(path)
        warnings.extend(file_warnings)
        for record in records:
            row = watchlist_item_row(record, imported_at=imported_at)
            source_rows["watchlist_items"][row_key("watchlist_items", row)] = row

    table_reports: dict[str, Any] = {}
    if not database.exists():
        warnings.append(f"SQLITE_DATABASE_MISSING:{database}")
        for table, rows in source_rows.items():
            table_reports[table] = empty_table_report(len(rows), missing_in_sqlite=list(sorted(rows)))
        return user_state_diff_payload(generated_at, database, source_files, table_reports, warnings)

    with connect_database(database) as connection:
        initialize_schema(connection)
        for table, rows in source_rows.items():
            sqlite_rows = read_user_state_table(connection, table)
            table_reports[table] = compare_table_rows(table, rows, sqlite_rows)

    return user_state_diff_payload(generated_at, database, source_files, table_reports, warnings)


def read_user_state_table(connection, table: str) -> dict[str, dict[str, Any]]:
    rows = connection.execute(f"SELECT * FROM {table}").fetchall()
    return {row_key(table, dict(row)): dict(row) for row in rows}


def compare_table_rows(
    table: str,
    source_rows: dict[str, dict[str, Any]],
    sqlite_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_keys = set(source_rows)
    sqlite_keys = set(sqlite_rows)
    missing = sorted(source_keys - sqlite_keys)
    extra = sorted(sqlite_keys - source_keys)
    changed: list[dict[str, Any]] = []
    for key in sorted(source_keys & sqlite_keys):
        differences = compare_row(table, source_rows[key], sqlite_rows[key])
        if differences:
            changed.append({"key": key, "fields": differences})
    status = "PASS" if not missing and not extra and not changed else "WARN"
    return {
        "status": status,
        "records_in_files": len(source_rows),
        "records_in_sqlite": len(sqlite_rows),
        "missing_in_sqlite_count": len(missing),
        "extra_in_sqlite_count": len(extra),
        "changed_values_count": len(changed),
        "missing_in_sqlite": missing,
        "extra_in_sqlite": extra,
        "changed_values": changed,
    }


def compare_row(table: str, source: dict[str, Any], sqlite: dict[str, Any]) -> list[dict[str, str]]:
    excluded = COMPARE_EXCLUDE.get(table, set())
    differences: list[dict[str, str]] = []
    for field, source_value in sorted(source.items()):
        if field in excluded:
            continue
        sqlite_value = sqlite.get(field)
        if normalize_value(source_value) != normalize_value(sqlite_value):
            differences.append(
                {
                    "field": field,
                    "file_value": normalize_value(source_value),
                    "sqlite_value": normalize_value(sqlite_value),
                }
            )
    return differences


def row_key(table: str, row: dict[str, Any]) -> str:
    columns = USER_STATE_TABLES[table]
    return "|".join(str(row.get(column, "") or "").replace("|", "/") for column in columns)


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def empty_table_report(records_in_files: int, *, missing_in_sqlite: list[str]) -> dict[str, Any]:
    return {
        "status": "WARN" if records_in_files else "PASS",
        "records_in_files": records_in_files,
        "records_in_sqlite": 0,
        "missing_in_sqlite_count": len(missing_in_sqlite),
        "extra_in_sqlite_count": 0,
        "changed_values_count": 0,
        "missing_in_sqlite": missing_in_sqlite,
        "extra_in_sqlite": [],
        "changed_values": [],
    }


def user_state_diff_payload(
    generated_at: str,
    database: Path,
    source_files: list[str],
    table_reports: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    conflict_count = sum(int(report.get("changed_values_count", 0)) for report in table_reports.values())
    missing_count = sum(int(report.get("missing_in_sqlite_count", 0)) for report in table_reports.values())
    extra_count = sum(int(report.get("extra_in_sqlite_count", 0)) for report in table_reports.values())
    malformed_count = sum(1 for warning in warnings if "MALFORMED" in warning or "DUPLICATE" in warning)
    statuses = {str(report.get("status", "PASS")) for report in table_reports.values()}
    overall_status = "WARN" if warnings or conflict_count or missing_count or extra_count or "WARN" in statuses else "PASS"
    recommended_action = (
        "Import user-state slice again, then re-run this dry-run diff."
        if missing_count or extra_count or conflict_count
        else "No action required. File-authoritative user state matches the SQLite mirror."
    )
    return {
        "schema_version": 1,
        "engine_version": "sqlite_user_state_diff_v1",
        "generated_at": generated_at,
        "database_path": str(database),
        "overall_status": overall_status,
        "source_files": source_files,
        "tables": table_reports,
        "records_in_files": sum(int(report.get("records_in_files", 0)) for report in table_reports.values()),
        "records_in_sqlite": sum(int(report.get("records_in_sqlite", 0)) for report in table_reports.values()),
        "missing_in_sqlite": missing_count,
        "extra_in_sqlite": extra_count,
        "changed_values": conflict_count,
        "conflicts": conflict_count,
        "malformed_records": malformed_count,
        "stale_imports": conflict_count + missing_count + extra_count,
        "warnings": sorted(set(warnings)),
        "recommended_next_action": recommended_action,
    }


def write_user_state_diff_report(
    payload: dict[str, Any],
    *,
    json_path: Path = USER_STATE_DIFF_LATEST_JSON,
    markdown_path: Path = USER_STATE_DIFF_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_user_state_diff_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_user_state_diff_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Hunter SQLite User-State Diff",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Database: `{payload.get('database_path', '')}`",
        f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Records in files: {payload.get('records_in_files', 0)}",
        f"- Records in SQLite: {payload.get('records_in_sqlite', 0)}",
        f"- Missing in SQLite: {payload.get('missing_in_sqlite', 0)}",
        f"- Extra in SQLite: {payload.get('extra_in_sqlite', 0)}",
        f"- Changed values: {payload.get('changed_values', 0)}",
        f"- Malformed records: {payload.get('malformed_records', 0)}",
        "",
        "## Table Summary",
        "",
    ]
    tables = payload.get("tables", {})
    if isinstance(tables, dict):
        for table, report in sorted(tables.items()):
            if not isinstance(report, dict):
                continue
            lines.append(
                f"- {report.get('status', 'UNKNOWN')} `{table}`: "
                f"files {report.get('records_in_files', 0)} / sqlite {report.get('records_in_sqlite', 0)}; "
                f"missing {report.get('missing_in_sqlite_count', 0)}, "
                f"extra {report.get('extra_in_sqlite_count', 0)}, "
                f"changed {report.get('changed_values_count', 0)}"
            )
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.extend([f"- {warning}" for warning in warnings])
    else:
        lines.append("- None.")
    lines.extend(["", "## Recommended Next Action", "", str(payload.get("recommended_next_action", ""))])
    return "\n".join(lines) + "\n"

