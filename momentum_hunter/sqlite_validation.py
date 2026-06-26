from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH, load_alerts
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
        checks.append(minute_bars_check(connection, minute_bars_path))
        checks.extend(evidence_run_checks(connection, source_paths=evidence_run_source_paths))
        checks.append(system_status_check(connection, source_paths=system_status_source_paths))
        checks.extend(capture_index_checks(connection, analysis_captures_path))

    warnings.extend(warning_messages_from_checks(checks))
    return validation_payload(generated_at, database, schema_version, table_counts, checks, warnings)


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
    warnings = payload.get("warnings", [])
    lines.extend(["", "## Warnings", ""])
    if isinstance(warnings, list) and warnings:
        lines.extend([f"- {warning}" for warning in warnings])
    else:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Momentum Hunter SQLite mirrors against current source files.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--json", type=Path, default=SQLITE_VALIDATION_LATEST_JSON)
    parser.add_argument("--markdown", type=Path, default=SQLITE_VALIDATION_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_sqlite_validation_report(db_path=args.db)
    write_sqlite_validation_report(payload, json_path=args.json, markdown_path=args.markdown)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("overall_status") in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
