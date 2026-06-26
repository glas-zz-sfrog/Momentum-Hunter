from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.opportunity_alerts import (
    OPPORTUNITY_ALERTS_PATH,
    is_completed_alert,
    is_pending_alert,
    is_unscorable_alert,
    load_alerts,
)
from momentum_hunter.sqlite_store import (
    SQLITE_DB_PATH,
    connect_database,
    count_capture_candidate_index_for_source,
    count_capture_index_for_source,
    count_minute_bars_for_source,
    count_rows_for_source,
    current_schema_version,
    discover_evidence_run_sources,
    discover_system_status_sources,
    parse_minute_bar_source,
    parse_system_status_source,
    read_analysis_capture_rows,
)
from momentum_hunter.storage import ANALYSIS_CSV, file_sha256
from momentum_hunter.time_utils import now_central
from momentum_hunter.user_state_diff import (
    USER_STATE_DIFF_LATEST_JSON,
    USER_STATE_DIFF_LATEST_MD,
    build_user_state_diff_report,
    write_user_state_diff_report,
)


SQLITE_VALIDATION_LATEST_JSON = DATA_DIR / "reports" / "sqlite-validation-latest.json"
SQLITE_VALIDATION_LATEST_MD = DATA_DIR / "reports" / "sqlite-validation-latest.md"


@dataclass(frozen=True)
class ValidationCheck:
    name: str
    status: str
    source_count: int
    sqlite_count: int
    message: str


def build_sqlite_validation_report(
    *,
    db_path: Path | None = None,
    data_quality_report: Path = DATA_QUALITY_LATEST_JSON,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    analysis_captures_path: Path = ANALYSIS_CSV,
    evidence_run_source_paths: list[Path] | None = None,
    system_status_source_paths: list[Path] | None = None,
) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    warnings: list[str] = []
    checks: list[ValidationCheck] = []
    table_counts: dict[str, int] = {}
    schema_version = 0
    database = db_path or SQLITE_DB_PATH
    if not database.exists():
        warnings.append(f"SQLITE_DATABASE_MISSING:{database}")
        return validation_payload(generated_at, database, schema_version, table_counts, checks, warnings)

    with connect_database(database) as connection:
        schema_version = current_schema_version(connection)
        evidence_sources = evidence_run_source_paths if evidence_run_source_paths is not None else discover_evidence_run_sources()
        system_status_sources = (
            system_status_source_paths if system_status_source_paths is not None else discover_system_status_sources()
        )
        for table in [
            "provider_quality_checks",
            "opportunity_alerts",
            "alert_outcomes",
            "minute_bars",
            "evidence_runs",
            "evidence_metrics",
            "system_status_events",
            "captures",
            "capture_candidates",
        ]:
            table_counts[table] = int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])

        checks.append(provider_quality_check(connection, data_quality_report))
        checks.extend(alert_evidence_checks(connection, alerts_path))
        checks.extend(alert_state_checks(connection, alerts_path))
        checks.append(minute_bars_check(connection, minute_bars_path))
        checks.extend(evidence_run_checks(connection, source_paths=evidence_sources))
        checks.append(system_status_check(connection, source_paths=system_status_sources))
        checks.extend(capture_index_checks(connection, analysis_captures_path))
        details = {
            "source_files": source_file_details(
                data_quality_report=data_quality_report,
                alerts_path=alerts_path,
                minute_bars_path=minute_bars_path,
                analysis_captures_path=analysis_captures_path,
                evidence_run_source_paths=evidence_sources,
                system_status_source_paths=system_status_sources,
            ),
            "import_timestamps": import_timestamp_details(connection),
            "missing_slices": missing_slice_details(table_counts),
            "alert_state_counts": alert_state_count_details(connection, alerts_path),
            "minute_bar_symbol_counts": minute_bar_symbol_count_details(connection, minute_bars_path),
            "capture_session_counts": capture_session_count_details(connection, analysis_captures_path),
            "capture_candidate_symbol_counts": capture_candidate_symbol_count_details(connection, analysis_captures_path),
        }

    warnings.extend(warning_messages_from_checks(checks))
    return validation_payload(generated_at, database, schema_version, table_counts, checks, warnings, details=details)


def provider_quality_check(connection, source: Path) -> ValidationCheck:
    if not source.exists():
        return ValidationCheck("provider_quality", "WARN", 0, 0, f"Source missing: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        report = payload.get("report", payload) if isinstance(payload, dict) else {}
        rows = report.get("symbol_rows", []) if isinstance(report, dict) else []
        source_count = len(rows) if isinstance(rows, list) else 0
    except (OSError, json.JSONDecodeError):
        return ValidationCheck("provider_quality", "WARN", 0, 0, f"Source unreadable: {source}")
    sqlite_count = int(
        connection.execute(
            "SELECT COUNT(*) AS count FROM provider_quality_checks WHERE source_report_hash = ?",
            (file_sha256(source),),
        ).fetchone()["count"]
    )
    return count_check("provider_quality", source_count, sqlite_count)


def alert_evidence_checks(connection, source: Path) -> list[ValidationCheck]:
    if not source.exists():
        return [
            ValidationCheck("opportunity_alerts", "WARN", 0, 0, f"Source missing: {source}"),
            ValidationCheck("alert_outcomes", "WARN", 0, 0, f"Source missing: {source}"),
        ]
    alerts = load_alerts(source)
    alert_count = len(alerts)
    outcome_count = sum(1 for alert in alerts if alert.outcome is not None)
    return [
        count_check("opportunity_alerts", alert_count, count_rows_for_source(connection, "opportunity_alerts", source)),
        count_check("alert_outcomes", outcome_count, count_rows_for_source(connection, "alert_outcomes", source)),
    ]


def alert_state_checks(connection, source: Path) -> list[ValidationCheck]:
    counts = alert_state_count_details(connection, source)
    source_counts = counts.get("source", {}) if isinstance(counts, dict) else {}
    sqlite_counts = counts.get("sqlite", {}) if isinstance(counts, dict) else {}
    return [
        count_check("completed_alert_outcomes", int(source_counts.get("completed", 0)), int(sqlite_counts.get("completed", 0))),
        count_check("pending_alert_outcomes", int(source_counts.get("pending", 0)), int(sqlite_counts.get("pending", 0))),
        count_check("unscorable_alert_outcomes", int(source_counts.get("unscorable", 0)), int(sqlite_counts.get("unscorable", 0))),
    ]


def minute_bars_check(connection, source: Path) -> ValidationCheck:
    if not source.exists():
        return ValidationCheck("minute_bars", "WARN", 0, 0, f"Source missing: {source}")
    parsed = parse_minute_bar_source(source)
    source_count = len({(bar.symbol, bar.timestamp, bar.source) for bar in parsed["bars"]})
    sqlite_count = count_minute_bars_for_source(connection, source)
    return count_check("minute_bars", source_count, sqlite_count)


def evidence_run_checks(connection, *, source_paths: list[Path] | None = None) -> list[ValidationCheck]:
    sources = source_paths if source_paths is not None else discover_evidence_run_sources()
    source_paths = [str(path) for path in sources]
    run_count = int(
        connection.execute(
            f"SELECT COUNT(*) AS count FROM evidence_runs WHERE source_path IN ({','.join(['?'] * len(source_paths))})"
            if source_paths
            else "SELECT 0 AS count",
            source_paths,
        ).fetchone()["count"]
    )
    return [count_check("evidence_runs", len(sources), run_count)]


def system_status_check(connection, *, source_paths: list[Path] | None = None) -> ValidationCheck:
    sources = source_paths if source_paths is not None else discover_system_status_sources()
    imported_at = now_central().isoformat()
    source_count = 0
    for source in sources:
        events, _warnings = parse_system_status_source(source, imported_at=imported_at)
        source_count += len(events)
    source_paths = [str(path) for path in sources]
    sqlite_count = int(
        connection.execute(
            f"SELECT COUNT(*) AS count FROM system_status_events WHERE source_path IN ({','.join(['?'] * len(source_paths))})"
            if source_paths
            else "SELECT 0 AS count",
            source_paths,
        ).fetchone()["count"]
    )
    return count_check("system_status_events", source_count, sqlite_count)


def capture_index_checks(connection, source: Path) -> list[ValidationCheck]:
    if not source.exists():
        return [
            ValidationCheck("captures", "WARN", 0, 0, f"Source missing: {source}"),
            ValidationCheck("capture_candidates", "WARN", 0, 0, f"Source missing: {source}"),
        ]
    rows, read_warnings = read_analysis_capture_rows(source)
    capture_keys = {
        (
            row.get("capture_date", ""),
            row.get("capture_time", ""),
            row.get("session", ""),
            row.get("provider", ""),
            row.get("scanner", ""),
        )
        for row in rows
    }
    checks = [
        count_check("captures", len(capture_keys), count_capture_index_for_source(connection, source)),
        count_check("capture_candidates", len(rows), count_capture_candidate_index_for_source(connection, source)),
    ]
    if read_warnings:
        checks.append(ValidationCheck("analysis_capture_source_quality", "WARN", len(read_warnings), 0, "; ".join(read_warnings[:5])))
    return checks


def source_file_details(
    *,
    data_quality_report: Path,
    alerts_path: Path,
    minute_bars_path: Path,
    analysis_captures_path: Path,
    evidence_run_source_paths: list[Path],
    system_status_source_paths: list[Path],
) -> dict[str, Any]:
    return {
        "provider_quality": file_detail(data_quality_report),
        "opportunity_alerts": file_detail(alerts_path),
        "minute_bars": file_detail(minute_bars_path),
        "analysis_captures": file_detail(analysis_captures_path),
        "evidence_runs": [file_detail(path) for path in evidence_run_source_paths],
        "system_status": [file_detail(path) for path in system_status_source_paths],
    }


def file_detail(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": file_sha256(path) if path.exists() else "",
    }


def import_timestamp_details(connection) -> dict[str, dict[str, str]]:
    timestamp_specs = {
        "provider_quality_checks": "generated_at",
        "opportunity_alerts": "COALESCE(imported_at, updated_at)",
        "alert_outcomes": "COALESCE(imported_at, updated_at)",
        "minute_bars": "COALESCE(imported_at, updated_at)",
        "evidence_runs": "COALESCE(imported_at, updated_at)",
        "system_status_events": "COALESCE(imported_at, updated_at)",
        "captures": "COALESCE(imported_at, updated_at)",
        "capture_candidates": "COALESCE(imported_at, updated_at)",
    }
    details: dict[str, dict[str, str]] = {}
    for table, expression in timestamp_specs.items():
        row = connection.execute(
            f"SELECT MIN({expression}) AS first_imported_at, MAX({expression}) AS latest_imported_at FROM {table}"
        ).fetchone()
        details[table] = {
            "first_imported_at": str(row["first_imported_at"] or ""),
            "latest_imported_at": str(row["latest_imported_at"] or ""),
        }
    return details


def missing_slice_details(table_counts: dict[str, int]) -> list[str]:
    expected_tables = [
        "provider_quality_checks",
        "opportunity_alerts",
        "alert_outcomes",
        "minute_bars",
        "evidence_runs",
        "system_status_events",
        "captures",
        "capture_candidates",
    ]
    return [table for table in expected_tables if int(table_counts.get(table, 0)) == 0]


def alert_state_count_details(connection, source: Path) -> dict[str, dict[str, int]]:
    if source.exists():
        alerts = load_alerts(source)
        source_counts = {
            "total": len(alerts),
            "completed": sum(1 for alert in alerts if is_completed_alert(alert)),
            "pending": sum(1 for alert in alerts if is_pending_alert(alert)),
            "unscorable": sum(1 for alert in alerts if is_unscorable_alert(alert)),
        }
    else:
        source_counts = {"total": 0, "completed": 0, "pending": 0, "unscorable": 0}
    source_path = str(source)
    sqlite_counts = {
        "total": int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM alert_outcomes WHERE source_alerts_path = ?",
                (source_path,),
            ).fetchone()["count"]
        ),
        "completed": int(
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM alert_outcomes
                WHERE source_alerts_path = ?
                  AND classification IN ('SUCCESSFUL', 'FAILED', 'NOISE', 'LATE')
                """,
                (source_path,),
            ).fetchone()["count"]
        ),
        "pending": int(
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM alert_outcomes
                WHERE source_alerts_path = ?
                  AND classification = 'PENDING'
                  AND status IN ('PENDING_OUTCOME', 'ACTIVE')
                """,
                (source_path,),
            ).fetchone()["count"]
        ),
        "unscorable": int(
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM alert_outcomes
                WHERE source_alerts_path = ?
                  AND (status = 'UNSCORABLE_OUTCOME' OR classification LIKE 'UNSCORABLE_%')
                """,
                (source_path,),
            ).fetchone()["count"]
        ),
    }
    return {"source": source_counts, "sqlite": sqlite_counts}


def minute_bar_symbol_count_details(connection, source: Path) -> dict[str, dict[str, dict[str, Any]]]:
    source_counts: dict[str, dict[str, Any]] = {}
    if source.exists():
        parsed = parse_minute_bar_source(source)
        for bar in parsed["bars"]:
            update_symbol_window(source_counts, bar.symbol, bar.timestamp)
    sqlite_counts: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        """
        SELECT symbol, COUNT(*) AS count, MIN(timestamp) AS first_timestamp, MAX(timestamp) AS latest_timestamp
        FROM minute_bars
        WHERE source_file_path = ?
        GROUP BY symbol
        ORDER BY symbol
        """,
        (str(source),),
    ).fetchall():
        sqlite_counts[str(row["symbol"])] = {
            "count": int(row["count"]),
            "first_timestamp": str(row["first_timestamp"] or ""),
            "latest_timestamp": str(row["latest_timestamp"] or ""),
        }
    return {"source": source_counts, "sqlite": sqlite_counts}


def capture_session_count_details(connection, source: Path) -> dict[str, dict[str, int]]:
    source_counts: dict[str, int] = {}
    if source.exists():
        rows, _warnings = read_analysis_capture_rows(source)
        capture_keys: set[tuple[str, str, str, str, str]] = set()
        for row in rows:
            key = (
                row.get("capture_date", ""),
                row.get("capture_time", ""),
                row.get("session", ""),
                row.get("provider", ""),
                row.get("scanner", ""),
            )
            if key in capture_keys:
                continue
            capture_keys.add(key)
            session = row.get("session", "") or "unknown"
            source_counts[session] = source_counts.get(session, 0) + 1
    sqlite_counts = {
        str(row["session"] or "unknown"): int(row["count"])
        for row in connection.execute(
            """
            SELECT session, COUNT(*) AS count
            FROM captures
            WHERE source_csv_path = ?
            GROUP BY session
            ORDER BY session
            """,
            (str(source),),
        ).fetchall()
    }
    return {"source": source_counts, "sqlite": sqlite_counts}


def capture_candidate_symbol_count_details(connection, source: Path) -> dict[str, dict[str, dict[str, Any]]]:
    source_counts: dict[str, dict[str, Any]] = {}
    if source.exists():
        rows, _warnings = read_analysis_capture_rows(source)
        for row in rows:
            ticker = str(row.get("ticker", "")).upper()
            if not ticker:
                continue
            timestamp = str(row.get("capture_time", ""))
            update_symbol_window(source_counts, ticker, timestamp)
    sqlite_counts: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        """
        SELECT cc.ticker AS ticker,
               COUNT(*) AS count,
               MIN(c.capture_time) AS first_timestamp,
               MAX(c.capture_time) AS latest_timestamp
        FROM capture_candidates cc
        LEFT JOIN captures c ON c.capture_id = cc.capture_id
        WHERE cc.source_csv_path = ?
        GROUP BY cc.ticker
        ORDER BY cc.ticker
        """,
        (str(source),),
    ).fetchall():
        sqlite_counts[str(row["ticker"])] = {
            "count": int(row["count"]),
            "first_timestamp": str(row["first_timestamp"] or ""),
            "latest_timestamp": str(row["latest_timestamp"] or ""),
        }
    return {"source": source_counts, "sqlite": sqlite_counts}


def update_symbol_window(counts: dict[str, dict[str, Any]], symbol: str, timestamp: str) -> None:
    key = str(symbol).upper()
    current = counts.setdefault(key, {"count": 0, "first_timestamp": "", "latest_timestamp": ""})
    current["count"] = int(current["count"]) + 1
    if timestamp and (not current["first_timestamp"] or timestamp < current["first_timestamp"]):
        current["first_timestamp"] = timestamp
    if timestamp and (not current["latest_timestamp"] or timestamp > current["latest_timestamp"]):
        current["latest_timestamp"] = timestamp


def count_check(name: str, source_count: int, sqlite_count: int) -> ValidationCheck:
    status = "PASS" if source_count == sqlite_count else "FAIL"
    return ValidationCheck(name, status, source_count, sqlite_count, f"{name}: source={source_count}, sqlite={sqlite_count}")


def validation_payload(
    generated_at: str,
    database: Path,
    schema_version: int,
    table_counts: dict[str, int],
    checks: list[ValidationCheck],
    warnings: list[str],
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    statuses = {check.status for check in checks}
    overall = "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses or warnings else "PASS"
    return {
        "schema_version": 1,
        "engine_version": "sqlite_validation_v1",
        "generated_at": generated_at,
        "database_path": str(database),
        "sqlite_schema_version": schema_version,
        "overall_status": overall,
        "table_counts": table_counts,
        "source_files": (details or {}).get("source_files", {}),
        "import_timestamps": (details or {}).get("import_timestamps", {}),
        "missing_slices": (details or {}).get("missing_slices", []),
        "alert_state_counts": (details or {}).get("alert_state_counts", {}),
        "minute_bar_symbol_counts": (details or {}).get("minute_bar_symbol_counts", {}),
        "capture_session_counts": (details or {}).get("capture_session_counts", {}),
        "capture_candidate_symbol_counts": (details or {}).get("capture_candidate_symbol_counts", {}),
        "checks": [asdict(check) for check in checks],
        "warnings": warnings,
    }


def warning_messages_from_checks(checks: list[ValidationCheck]) -> list[str]:
    return [f"{check.status}:{check.name}:{check.message}" for check in checks if check.status in {"WARN", "FAIL"}]


def write_sqlite_validation_report(
    payload: dict[str, Any],
    *,
    json_path: Path = SQLITE_VALIDATION_LATEST_JSON,
    markdown_path: Path = SQLITE_VALIDATION_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_validation_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_validation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Hunter SQLite Validation",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Database: `{payload.get('database_path', '')}`",
        f"- SQLite schema version: {payload.get('sqlite_schema_version', 0)}",
        f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
        "",
        "## Table Counts",
        "",
    ]
    table_counts = payload.get("table_counts", {})
    if isinstance(table_counts, dict):
        lines.extend([f"- {table}: {count}" for table, count in sorted(table_counts.items())])
    lines.extend(["", "## Source Count Checks", ""])
    checks = payload.get("checks", [])
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict):
                lines.append(
                    f"- {check.get('status', 'UNKNOWN')} `{check.get('name', '')}`: "
                    f"source {check.get('source_count', 0)} / sqlite {check.get('sqlite_count', 0)}"
                )
    lines.extend(["", "## Source Files", ""])
    source_files = payload.get("source_files", {})
    if isinstance(source_files, dict) and source_files:
        for name, detail in source_files.items():
            if isinstance(detail, list):
                lines.append(f"- {name}: {len(detail)} file(s)")
                for item in detail[:10]:
                    if isinstance(item, dict):
                        lines.append(f"  - `{item.get('path', '')}` exists={item.get('exists', False)}")
                if len(detail) > 10:
                    lines.append(f"  - ... {len(detail) - 10} more")
            elif isinstance(detail, dict):
                lines.append(f"- {name}: `{detail.get('path', '')}` exists={detail.get('exists', False)}")
    else:
        lines.append("- No source file details recorded.")
    lines.extend(["", "## Import Timestamps", ""])
    import_timestamps = payload.get("import_timestamps", {})
    if isinstance(import_timestamps, dict) and import_timestamps:
        for table, detail in sorted(import_timestamps.items()):
            if isinstance(detail, dict):
                lines.append(
                    f"- {table}: first `{detail.get('first_imported_at', '')}` / latest `{detail.get('latest_imported_at', '')}`"
                )
    else:
        lines.append("- No import timestamps recorded.")
    lines.extend(["", "## Missing Slices", ""])
    missing_slices = payload.get("missing_slices", [])
    if isinstance(missing_slices, list) and missing_slices:
        lines.extend([f"- {name}" for name in missing_slices])
    else:
        lines.append("- None.")
    lines.extend(["", "## Alert State Counts", ""])
    append_nested_count_section(lines, payload.get("alert_state_counts", {}))
    lines.extend(["", "## Minute Bar Symbol Counts", ""])
    append_symbol_count_section(lines, payload.get("minute_bar_symbol_counts", {}), limit=25)
    lines.extend(["", "## Capture Session Counts", ""])
    append_nested_count_section(lines, payload.get("capture_session_counts", {}))
    lines.extend(["", "## Capture Candidate Symbol Counts", ""])
    append_symbol_count_section(lines, payload.get("capture_candidate_symbol_counts", {}), limit=25)
    warnings = payload.get("warnings", [])
    lines.extend(["", "## Warnings", ""])
    if isinstance(warnings, list) and warnings:
        lines.extend([f"- {warning}" for warning in warnings])
    else:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def append_nested_count_section(lines: list[str], section: object) -> None:
    if not isinstance(section, dict) or not section:
        lines.append("- No counts recorded.")
        return
    for source_name, counts in section.items():
        if isinstance(counts, dict):
            joined = ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))
            lines.append(f"- {source_name}: {joined}")


def append_symbol_count_section(lines: list[str], section: object, *, limit: int) -> None:
    if not isinstance(section, dict) or not section:
        lines.append("- No symbol counts recorded.")
        return
    for side in ["source", "sqlite"]:
        counts = section.get(side)
        if not isinstance(counts, dict):
            continue
        lines.append(f"- {side}: {len(counts)} symbol(s)")
        for symbol, detail in sorted(counts.items())[:limit]:
            if isinstance(detail, dict):
                lines.append(
                    f"  - {symbol}: {detail.get('count', 0)} "
                    f"({detail.get('first_timestamp', '')} -> {detail.get('latest_timestamp', '')})"
                )
        if len(counts) > limit:
            lines.append(f"  - ... {len(counts) - limit} more")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Momentum Hunter SQLite mirrors against current source files.")
    parser.add_argument("--slice", choices=["evidence", "user-state"], default="evidence")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--json", type=Path, default=SQLITE_VALIDATION_LATEST_JSON)
    parser.add_argument("--markdown", type=Path, default=SQLITE_VALIDATION_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.slice == "user-state":
        json_path = args.json if args.json != SQLITE_VALIDATION_LATEST_JSON else USER_STATE_DIFF_LATEST_JSON
        markdown_path = args.markdown if args.markdown != SQLITE_VALIDATION_LATEST_MD else USER_STATE_DIFF_LATEST_MD
        payload = build_user_state_diff_report(db_path=args.db)
        write_user_state_diff_report(payload, json_path=json_path, markdown_path=markdown_path)
        print(json.dumps(payload, indent=2))
        return 0 if payload.get("overall_status") in {"PASS", "WARN"} else 1
    payload = build_sqlite_validation_report(db_path=args.db)
    write_sqlite_validation_report(payload, json_path=args.json, markdown_path=args.markdown)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("overall_status") in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
