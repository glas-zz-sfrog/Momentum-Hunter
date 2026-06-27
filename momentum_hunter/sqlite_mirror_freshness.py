from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.entry_plans import ENTRY_PLANS_PATH
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH, load_alerts
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.source_registry import (
    SOURCE_REGISTRY_VERSION,
    SourceDefinition,
    registered_source_definitions,
)
from momentum_hunter.sqlite_store import (
    SQLITE_DB_PATH,
    connect_database,
    current_schema_version,
    load_entry_plan_source_records,
    load_review_source_records,
    load_watchlist_source_records,
    parse_evidence_run_source,
    parse_minute_bar_source,
    parse_system_status_source,
    read_analysis_capture_rows,
)
from momentum_hunter.storage import ANALYSIS_CSV, file_sha256
from momentum_hunter.time_utils import now_central


SQLITE_MIRROR_FRESHNESS_LATEST_JSON = DATA_DIR / "reports" / "sqlite-mirror-freshness-latest.json"
SQLITE_MIRROR_FRESHNESS_LATEST_MD = DATA_DIR / "reports" / "sqlite-mirror-freshness-latest.md"
MIRROR_FRESHNESS_ENGINE_VERSION = "sqlite_mirror_freshness_v1"


@dataclass(frozen=True)
class SourceFileState:
    path: str
    exists: bool
    sha256: str
    modified_at: str
    size_bytes: int


@dataclass(frozen=True)
class MirrorCheck:
    name: str
    source_name: str
    sqlite_table: str
    source_count: int
    sqlite_current_count: int
    sqlite_table_count: int
    status: str
    included_in_all_safe: bool
    import_required: str
    latest_imported_at: str
    latest_source_modified_at: str
    source_files: list[SourceFileState]
    warnings: list[str]


@dataclass(frozen=True)
class MirrorSpec:
    name: str
    source_name: str
    table: str
    path_column: str
    hash_column: str
    import_time_expression: str
    expected_count: Callable[["MirrorContext"], tuple[int, list[Path], list[str]]]
    included_in_all_safe: bool
    import_required: str


@dataclass(frozen=True)
class MirrorContext:
    data_dir: Path
    reports_dir: Path
    data_quality_report: Path
    alerts_path: Path
    minute_bars_path: Path
    analysis_captures_path: Path
    review_decisions_path: Path
    entry_plans_path: Path
    imported_at: str


def build_sqlite_mirror_freshness_report(
    *,
    db_path: Path = SQLITE_DB_PATH,
    data_dir: Path = DATA_DIR,
    reports_dir: Path | None = None,
    data_quality_report: Path = DATA_QUALITY_LATEST_JSON,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    analysis_captures_path: Path = ANALYSIS_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or now_central()
    reports_dir = reports_dir or data_dir / "reports"
    context = MirrorContext(
        data_dir=data_dir,
        reports_dir=reports_dir,
        data_quality_report=data_quality_report,
        alerts_path=alerts_path,
        minute_bars_path=minute_bars_path,
        analysis_captures_path=analysis_captures_path,
        review_decisions_path=review_decisions_path,
        entry_plans_path=entry_plans_path,
        imported_at=generated_at.isoformat(),
    )
    definitions = registered_source_definitions(
        data_dir=data_dir,
        reports_dir=reports_dir,
        analysis_captures_path=analysis_captures_path,
        data_quality_report=data_quality_report,
        alerts_path=alerts_path,
        minute_bars_path=minute_bars_path,
        review_decisions_path=review_decisions_path,
        entry_plans_path=entry_plans_path,
    )
    definition_by_name = {definition.name: definition for definition in definitions}
    warnings: list[str] = []
    if not db_path.exists():
        warnings.append(f"SQLITE_DATABASE_MISSING:{db_path}")
        return {
            "schema_version": 1,
            "engine_version": MIRROR_FRESHNESS_ENGINE_VERSION,
            "source_registry_version": SOURCE_REGISTRY_VERSION,
            "generated_at": generated_at.isoformat(),
            "database_path": str(db_path),
            "sqlite_schema_version": 0,
            "overall_status": "FAIL",
            "checks": [],
            "sources": [definition.to_dict() for definition in definitions],
            "warnings": warnings,
        }

    checks: list[MirrorCheck] = []
    with connect_database(db_path) as connection:
        schema_version = current_schema_version(connection)
        for spec in mirror_specs():
            definition = definition_by_name.get(spec.source_name)
            checks.append(build_check(connection, spec, context, definition))

    warnings.extend(report_warnings(checks))
    overall_status = overall_status_for_checks(checks, warnings)
    return {
        "schema_version": 1,
        "engine_version": MIRROR_FRESHNESS_ENGINE_VERSION,
        "source_registry_version": SOURCE_REGISTRY_VERSION,
        "generated_at": generated_at.isoformat(),
        "database_path": str(db_path),
        "sqlite_schema_version": schema_version,
        "overall_status": overall_status,
        "checks": [check_to_dict(check) for check in checks],
        "sources": [definition.to_dict() for definition in definitions],
        "warnings": warnings,
    }


def build_check(
    connection: sqlite3.Connection,
    spec: MirrorSpec,
    context: MirrorContext,
    definition: SourceDefinition | None,
) -> MirrorCheck:
    source_count, source_paths, count_warnings = spec.expected_count(context)
    source_states = [source_file_state(path) for path in source_paths]
    source_pairs = [(Path(state.path), state.sha256) for state in source_states if state.exists and state.sha256]
    sqlite_current_count = count_current_hash_rows(connection, spec.table, spec.path_column, spec.hash_column, source_pairs)
    sqlite_table_count = table_count(connection, spec.table)
    latest_imported_at = latest_imported(connection, spec.table, spec.import_time_expression)
    latest_source_modified_at = latest_source_modified(source_states)
    warnings = list(count_warnings)
    status = "PASS"
    if source_count != sqlite_current_count:
        if spec.included_in_all_safe:
            status = "FAIL"
            warnings.append(f"MIRROR_COUNT_MISMATCH:{source_count}!={sqlite_current_count}")
        else:
            status = "INFO"
            warnings.append("EXPLICIT_USER_STATE_IMPORT_REQUIRED")
    if source_count == 0 and not source_states and spec.included_in_all_safe:
        status = "WARN" if status == "PASS" else status
        warnings.append("NO_SOURCE_FILES_FOUND")
    if sqlite_table_count > sqlite_current_count:
        warnings.append(f"OLDER_OR_OTHER_SOURCE_ROWS:{sqlite_table_count - sqlite_current_count}")
    if definition and definition.cleanup_rule:
        warnings = dedupe(warnings)
    return MirrorCheck(
        name=spec.name,
        source_name=spec.source_name,
        sqlite_table=spec.table,
        source_count=source_count,
        sqlite_current_count=sqlite_current_count,
        sqlite_table_count=sqlite_table_count,
        status=status,
        included_in_all_safe=spec.included_in_all_safe,
        import_required=spec.import_required,
        latest_imported_at=latest_imported_at,
        latest_source_modified_at=latest_source_modified_at,
        source_files=source_states,
        warnings=warnings,
    )


def mirror_specs() -> list[MirrorSpec]:
    return [
        MirrorSpec(
            "provider_quality_checks",
            "provider_quality_report",
            "provider_quality_checks",
            "source_report_path",
            "source_report_hash",
            "generated_at",
            expected_provider_quality_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "opportunity_alerts",
            "opportunity_alerts",
            "opportunity_alerts",
            "source_alerts_path",
            "source_alerts_hash",
            "COALESCE(imported_at, updated_at)",
            expected_alert_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "alert_outcomes",
            "opportunity_alerts",
            "alert_outcomes",
            "source_alerts_path",
            "source_alerts_hash",
            "COALESCE(imported_at, updated_at)",
            expected_alert_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "minute_bars",
            "opportunity_minute_bars",
            "minute_bars",
            "source_file_path",
            "source_file_hash",
            "COALESCE(imported_at, updated_at)",
            expected_minute_bar_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "evidence_runs",
            "evidence_run_reports",
            "evidence_runs",
            "source_path",
            "source_hash",
            "COALESCE(imported_at, updated_at)",
            expected_evidence_run_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "evidence_metrics",
            "evidence_run_reports",
            "evidence_metrics",
            "",
            "",
            "",
            expected_evidence_metric_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "system_status_events",
            "system_status_sources",
            "system_status_events",
            "source_path",
            "source_hash",
            "COALESCE(imported_at, updated_at)",
            expected_system_status_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "captures",
            "analysis_capture_index",
            "captures",
            "source_csv_path",
            "source_csv_hash",
            "COALESCE(imported_at, updated_at)",
            expected_capture_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "capture_candidates",
            "analysis_capture_index",
            "capture_candidates",
            "source_csv_path",
            "source_csv_hash",
            "COALESCE(imported_at, updated_at)",
            expected_capture_candidate_count,
            True,
            "all-safe",
        ),
        MirrorSpec(
            "candidate_reviews",
            "review_decisions",
            "candidate_reviews",
            "source_path",
            "source_hash",
            "COALESCE(imported_at, updated_at)",
            expected_review_count,
            False,
            "explicit-user-state",
        ),
        MirrorSpec(
            "watchlist_items",
            "watchlists",
            "watchlist_items",
            "source_path",
            "source_hash",
            "COALESCE(imported_at, updated_at)",
            expected_watchlist_count,
            False,
            "explicit-user-state",
        ),
        MirrorSpec(
            "entry_plans",
            "entry_plans",
            "entry_plans",
            "source_path",
            "source_hash",
            "COALESCE(imported_at, updated_at)",
            expected_entry_plan_count,
            False,
            "explicit-user-state",
        ),
    ]


def expected_provider_quality_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    source = context.data_quality_report
    if not source.exists():
        return 0, [], [f"SOURCE_MISSING:{source}"]
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return 0, [source], [f"SOURCE_UNREADABLE:{type(exc).__name__}:{source}"]
    body = payload.get("report", payload) if isinstance(payload, dict) else {}
    rows = body.get("symbol_rows", []) if isinstance(body, dict) else []
    return (len(rows) if isinstance(rows, list) else 0), [source], []


def expected_alert_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    source = context.alerts_path
    if not source.exists():
        return 0, [], [f"SOURCE_MISSING:{source}"]
    return len(load_alerts(source)), [source], []


def expected_minute_bar_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    source = context.minute_bars_path
    if not source.exists():
        return 0, [], [f"SOURCE_MISSING:{source}"]
    parsed = parse_minute_bar_source(source)
    unique = {(bar.symbol, bar.timestamp, bar.source) for bar in parsed["bars"]}
    return len(unique), [source], [str(warning) for warning in parsed.get("warnings", [])]


def expected_evidence_run_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    sources = discover_evidence_sources(context)
    parsed = 0
    warnings: list[str] = []
    for source in sources:
        if parse_evidence_run_source(source, imported_at=context.imported_at) is None:
            warnings.append(f"EVIDENCE_SOURCE_UNPARSED:{source}")
        else:
            parsed += 1
    return parsed, sources, warnings


def expected_evidence_metric_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    sources = discover_evidence_sources(context)
    metric_count = 0
    warnings: list[str] = []
    for source in sources:
        parsed = parse_evidence_run_source(source, imported_at=context.imported_at)
        if parsed is None:
            warnings.append(f"EVIDENCE_SOURCE_UNPARSED:{source}")
            continue
        _run, metrics, _source_warnings = parsed
        metric_count += len(metrics)
    return metric_count, sources, warnings


def expected_system_status_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    sources = discover_system_status_sources_for_context(context)
    event_count = 0
    warnings: list[str] = []
    for source in sources:
        events, source_warnings = parse_system_status_source(source, imported_at=context.imported_at)
        event_count += len(events)
        warnings.extend(source_warnings)
    return event_count, sources, warnings


def expected_capture_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    source = context.analysis_captures_path
    if not source.exists():
        return 0, [], [f"SOURCE_MISSING:{source}"]
    rows, warnings = read_analysis_capture_rows(source)
    keys = {
        (
            row.get("capture_date", ""),
            row.get("capture_time", ""),
            row.get("session", ""),
            row.get("provider", ""),
            row.get("scanner", ""),
        )
        for row in rows
    }
    return len(keys), [source], warnings


def expected_capture_candidate_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    source = context.analysis_captures_path
    if not source.exists():
        return 0, [], [f"SOURCE_MISSING:{source}"]
    rows, warnings = read_analysis_capture_rows(source)
    return len(rows), [source], warnings


def expected_review_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    source = context.review_decisions_path
    records, warnings = load_review_source_records(source)
    return len(records), [source] if source.exists() else [], warnings


def expected_entry_plan_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    source = context.entry_plans_path
    records, warnings = load_entry_plan_source_records(source)
    return len(records), [source] if source.exists() else [], warnings


def expected_watchlist_count(context: MirrorContext) -> tuple[int, list[Path], list[str]]:
    sources = sorted(context.data_dir.glob("watchlist-*.json"))
    count = 0
    warnings: list[str] = []
    for source in sources:
        records, source_warnings = load_watchlist_source_records(source)
        count += len(records)
        warnings.extend(source_warnings)
    return count, sources, warnings


def discover_evidence_sources(context: MirrorContext) -> list[Path]:
    sources = [
        context.data_dir / "evidence-autopilot-status.json",
        context.data_dir / "alert-outcome-update-status.json",
        context.reports_dir / "evidence-autopilot-latest.json",
    ]
    for pattern in [
        "evidence-health-report-*.json",
        "reliability-report-*.json",
        "alert-performance-report-*.json",
    ]:
        sources.extend(sorted(context.reports_dir.glob(pattern)))
    return dedupe_paths([path for path in sources if path.exists()])


def discover_system_status_sources_for_context(context: MirrorContext) -> list[Path]:
    sources = [
        context.data_dir / "active-monitor-status.json",
        context.data_dir / "evidence-autopilot-status.json",
        context.data_dir / "alert-outcome-update-status.json",
        context.reports_dir / "system-readiness-latest.json",
        context.reports_dir / "data-quality-latest.json",
    ]
    sources.extend(sorted(context.reports_dir.glob("market-tape-health-*.json")))
    return dedupe_paths([path for path in sources if path.exists()])


def source_file_state(path: Path) -> SourceFileState:
    exists = path.exists()
    stat = path.stat() if exists else None
    modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat() if stat else ""
    return SourceFileState(
        path=str(path),
        exists=exists,
        sha256=file_sha256(path) if exists else "",
        modified_at=modified_at,
        size_bytes=int(stat.st_size) if stat else 0,
    )


def count_current_hash_rows(
    connection: sqlite3.Connection,
    table: str,
    path_column: str,
    hash_column: str,
    source_pairs: list[tuple[Path, str]],
) -> int:
    if table == "evidence_metrics":
        return count_current_evidence_metrics(connection, source_pairs)
    if not source_pairs or not path_column or not hash_column:
        return 0
    conditions = " OR ".join(f"({path_column} = ? AND {hash_column} = ?)" for _item in source_pairs)
    params: list[str] = []
    for path, source_hash in source_pairs:
        params.extend([str(path), source_hash])
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {conditions}", params).fetchone()
    return int(row["count"] if row else 0)


def count_current_evidence_metrics(connection: sqlite3.Connection, source_pairs: list[tuple[Path, str]]) -> int:
    if not source_pairs:
        return 0
    conditions = " OR ".join("(source_path = ? AND source_hash = ?)" for _item in source_pairs)
    params: list[str] = []
    for path, source_hash in source_pairs:
        params.extend([str(path), source_hash])
    run_rows = connection.execute(f"SELECT run_id FROM evidence_runs WHERE {conditions}", params).fetchall()
    run_ids = [str(row["run_id"]) for row in run_rows]
    if not run_ids:
        return 0
    placeholders = ",".join("?" for _item in run_ids)
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM evidence_metrics WHERE run_id IN ({placeholders})",
        run_ids,
    ).fetchone()
    return int(row["count"] if row else 0)


def table_count(connection: sqlite3.Connection, table: str) -> int:
    try:
        row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["count"] if row else 0)


def latest_imported(connection: sqlite3.Connection, table: str, expression: str) -> str:
    if not expression:
        return ""
    try:
        row = connection.execute(f"SELECT MAX({expression}) AS latest_imported_at FROM {table}").fetchone()
    except sqlite3.OperationalError:
        return ""
    return str(row["latest_imported_at"] or "") if row else ""


def latest_source_modified(states: list[SourceFileState]) -> str:
    values = [state.modified_at for state in states if state.modified_at]
    return max(values) if values else ""


def overall_status_for_checks(checks: list[MirrorCheck], warnings: list[str]) -> str:
    statuses = {check.status for check in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses or warnings:
        return "WARN"
    return "PASS"


def report_warnings(checks: list[MirrorCheck]) -> list[str]:
    warnings: list[str] = []
    failed = sum(1 for check in checks if check.status == "FAIL")
    warn = sum(1 for check in checks if check.status == "WARN")
    info = sum(1 for check in checks if check.status == "INFO")
    if failed:
        warnings.append(f"MIRROR_FAILURES:{failed}")
    if warn:
        warnings.append(f"MIRROR_WARNINGS:{warn}")
    if info:
        warnings.append(f"EXPLICIT_IMPORT_SOURCES:{info}")
    return warnings


def check_to_dict(check: MirrorCheck) -> dict[str, Any]:
    payload = asdict(check)
    payload["source_files"] = [asdict(state) for state in check.source_files]
    return payload


def write_sqlite_mirror_freshness_report(
    payload: dict[str, Any],
    *,
    json_path: Path = SQLITE_MIRROR_FRESHNESS_LATEST_JSON,
    markdown_path: Path = SQLITE_MIRROR_FRESHNESS_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_mirror_freshness_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_mirror_freshness_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Hunter SQLite Mirror Freshness",
        "",
        "SQLite remains an additive mirror. File-based sources remain authoritative unless a future cutover explicitly changes that.",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Database: `{payload.get('database_path', '')}`",
        f"- SQLite schema version: {payload.get('sqlite_schema_version', 0)}",
        f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
        "",
        "## Mirror Checks",
        "",
        "| Check | Source | Table | Status | Source Rows | Current SQLite Rows | Table Rows | Import Path | Warnings |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for check in payload.get("checks", []):
        warnings = ", ".join(check.get("warnings", [])) if isinstance(check, dict) else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    str(check.get("name", "")),
                    str(check.get("source_name", "")),
                    str(check.get("sqlite_table", "")),
                    str(check.get("status", "")),
                    str(check.get("source_count", 0)),
                    str(check.get("sqlite_current_count", 0)),
                    str(check.get("sqlite_table_count", 0)),
                    str(check.get("import_required", "")),
                    warnings.replace("|", "/"),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Source Registry", ""])
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        tables = ", ".join(source.get("sqlite_tables", []))
        lines.extend(
            [
                f"### {source.get('name', '')}",
                "",
                f"- Category: {source.get('category', '')}",
                f"- Authority: {source.get('authority', '')}",
                f"- Mutability: {source.get('mutability', '')}",
                f"- Path: `{source.get('path', '')}`",
                f"- Pattern: `{source.get('pattern', '')}`",
                f"- SQLite tables: {tables or 'not mirrored'}",
                f"- Importer: {source.get('importer', '')}",
                f"- Included in all-safe: {source.get('included_in_all_safe', False)}",
                f"- Preservation rule: {source.get('preservation_rule', '')}",
                f"- Cleanup rule: {source.get('cleanup_rule', '')}",
                f"- Notes: {source.get('notes', '')}",
                "",
            ]
        )
    warnings = payload.get("warnings", [])
    lines.extend(["## Report Warnings", ""])
    if isinstance(warnings, list) and warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def write_mirror_freshness_csv(payload: dict[str, Any], *, csv_path: Path) -> Path:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "name",
        "source_name",
        "sqlite_table",
        "status",
        "source_count",
        "sqlite_current_count",
        "sqlite_table_count",
        "included_in_all_safe",
        "import_required",
        "latest_imported_at",
        "latest_source_modified_at",
        "warnings",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for check in payload.get("checks", []):
            if not isinstance(check, dict):
                continue
            writer.writerow({field: check.get(field, "") for field in fieldnames})
    return csv_path


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value)
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate SQLite mirror freshness against file-authoritative sources.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--json", type=Path, default=SQLITE_MIRROR_FRESHNESS_LATEST_JSON)
    parser.add_argument("--markdown", type=Path, default=SQLITE_MIRROR_FRESHNESS_LATEST_MD)
    parser.add_argument("--csv", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_sqlite_mirror_freshness_report(db_path=args.db)
    paths = write_sqlite_mirror_freshness_report(payload, json_path=args.json, markdown_path=args.markdown)
    if args.csv:
        paths["csv"] = write_mirror_freshness_csv(payload, csv_path=args.csv)
    print(json.dumps({"overall_status": payload.get("overall_status"), "warnings": payload.get("warnings", []), "paths": {k: str(v) for k, v in paths.items()}}, indent=2))
    return 0 if payload.get("overall_status") in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
