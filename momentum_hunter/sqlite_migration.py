from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH
from momentum_hunter.storage import ANALYSIS_CSV
from momentum_hunter.sqlite_store import (
    CaptureIndexImportResult,
    SQLITE_DB_PATH,
    EvidenceImportResult,
    EvidenceRunsImportResult,
    MinuteBarsImportResult,
    ProviderQualityImportResult,
    SystemStatusImportResult,
    connect_database,
    current_schema_version,
    import_capture_candidate_index,
    import_evidence_runs,
    import_minute_bars,
    import_opportunity_alerts,
    import_provider_quality_report,
    import_system_status_events,
    initialize_schema,
)


SQLITE_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-import-latest.json"
SQLITE_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-import-latest.md"
SQLITE_IMPORT_ALL_SAFE_LATEST_JSON = DATA_DIR / "reports" / "sqlite-import-all-safe-latest.json"
SQLITE_IMPORT_ALL_SAFE_LATEST_MD = DATA_DIR / "reports" / "sqlite-import-all-safe-latest.md"
SQLITE_EVIDENCE_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-evidence-import-latest.json"
SQLITE_EVIDENCE_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-evidence-import-latest.md"
SQLITE_MINUTE_BARS_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-minute-bars-import-latest.json"
SQLITE_MINUTE_BARS_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-minute-bars-import-latest.md"
SQLITE_EVIDENCE_RUNS_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-evidence-runs-import-latest.json"
SQLITE_EVIDENCE_RUNS_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-evidence-runs-import-latest.md"
SQLITE_SYSTEM_STATUS_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-system-status-import-latest.json"
SQLITE_SYSTEM_STATUS_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-system-status-import-latest.md"
SQLITE_CAPTURE_INDEX_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-capture-index-import-latest.json"
SQLITE_CAPTURE_INDEX_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-capture-index-import-latest.md"


def initialize_database(db_path: Path | None = None) -> int:
    with connect_database(db_path) as connection:
        initialize_schema(connection)
        return current_schema_version(connection)


def run_sqlite_migration(
    *,
    db_path: Path | None = None,
    data_quality_report: Path = DATA_QUALITY_LATEST_JSON,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    analysis_captures_path: Path = ANALYSIS_CSV,
    system_status_source_paths: list[Path] | None = None,
    import_provider_quality: bool = True,
    import_evidence: bool = False,
    import_minute_bar_slice: bool = False,
    import_evidence_run_slice: bool = False,
    import_system_status_slice: bool = False,
    import_capture_index_slice: bool = False,
    report_json: Path = SQLITE_IMPORT_LATEST_JSON,
    report_md: Path = SQLITE_IMPORT_LATEST_MD,
    evidence_report_json: Path = SQLITE_EVIDENCE_IMPORT_LATEST_JSON,
    evidence_report_md: Path = SQLITE_EVIDENCE_IMPORT_LATEST_MD,
    minute_bars_report_json: Path = SQLITE_MINUTE_BARS_IMPORT_LATEST_JSON,
    minute_bars_report_md: Path = SQLITE_MINUTE_BARS_IMPORT_LATEST_MD,
    evidence_runs_report_json: Path = SQLITE_EVIDENCE_RUNS_IMPORT_LATEST_JSON,
    evidence_runs_report_md: Path = SQLITE_EVIDENCE_RUNS_IMPORT_LATEST_MD,
    system_status_report_json: Path = SQLITE_SYSTEM_STATUS_IMPORT_LATEST_JSON,
    system_status_report_md: Path = SQLITE_SYSTEM_STATUS_IMPORT_LATEST_MD,
    capture_index_report_json: Path = SQLITE_CAPTURE_INDEX_IMPORT_LATEST_JSON,
    capture_index_report_md: Path = SQLITE_CAPTURE_INDEX_IMPORT_LATEST_MD,
) -> dict[str, object]:
    ensure_app_dirs()
    schema_version = initialize_database(db_path)
    provider_quality_result: ProviderQualityImportResult | None = None
    evidence_result: EvidenceImportResult | None = None
    minute_bars_result: MinuteBarsImportResult | None = None
    evidence_runs_result: EvidenceRunsImportResult | None = None
    system_status_result: SystemStatusImportResult | None = None
    capture_index_result: CaptureIndexImportResult | None = None
    if import_provider_quality:
        provider_quality_result = import_provider_quality_report(data_quality_report, db_path=db_path)
    if import_evidence:
        evidence_result = import_opportunity_alerts(alerts_path, db_path=db_path)
    if import_minute_bar_slice:
        minute_bars_result = import_minute_bars(minute_bars_path, db_path=db_path)
    if import_evidence_run_slice:
        evidence_runs_result = import_evidence_runs(db_path=db_path)
    if import_system_status_slice:
        system_status_result = import_system_status_events(db_path=db_path, source_paths=system_status_source_paths)
    if import_capture_index_slice:
        capture_index_result = import_capture_candidate_index(analysis_captures_path, db_path=db_path)
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "database_path": str(db_path or SQLITE_DB_PATH),
        "provider_quality_import": asdict(provider_quality_result) if provider_quality_result else None,
        "evidence_import": asdict(evidence_result) if evidence_result else None,
        "minute_bars_import": asdict(minute_bars_result) if minute_bars_result else None,
        "evidence_runs_import": asdict(evidence_runs_result) if evidence_runs_result else None,
        "system_status_import": asdict(system_status_result) if system_status_result else None,
        "capture_index_import": asdict(capture_index_result) if capture_index_result else None,
    }
    write_import_report(payload, json_path=report_json, markdown_path=report_md)
    if evidence_result:
        write_evidence_import_report(
            asdict(evidence_result),
            json_path=evidence_report_json,
            markdown_path=evidence_report_md,
        )
    if minute_bars_result:
        write_minute_bars_import_report(
            asdict(minute_bars_result),
            json_path=minute_bars_report_json,
            markdown_path=minute_bars_report_md,
        )
    if evidence_runs_result:
        write_evidence_runs_import_report(
            asdict(evidence_runs_result),
            json_path=evidence_runs_report_json,
            markdown_path=evidence_runs_report_md,
        )
    if system_status_result:
        write_system_status_import_report(
            asdict(system_status_result),
            json_path=system_status_report_json,
            markdown_path=system_status_report_md,
        )
    if capture_index_result:
        write_capture_index_import_report(
            asdict(capture_index_result),
            json_path=capture_index_report_json,
            markdown_path=capture_index_report_md,
        )
    return payload


def write_import_report(payload: dict[str, object], *, json_path: Path, markdown_path: Path) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_markdown(payload), encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def format_markdown(payload: dict[str, object]) -> str:
    result = payload.get("provider_quality_import")
    evidence = payload.get("evidence_import")
    minute_bars = payload.get("minute_bars_import")
    evidence_runs = payload.get("evidence_runs_import")
    system_status = payload.get("system_status_import")
    capture_index = payload.get("capture_index_import")
    lines = [
        "# Momentum Hunter SQLite Import",
        "",
        "Additive SQLite foundation report. Existing JSON/CSV files remain in place and are not deleted or rewritten.",
        "",
        f"- Database: `{payload.get('database_path', '')}`",
        f"- Schema version: {payload.get('schema_version', 0)}",
        "",
        "## Provider Quality Import",
        "",
    ]
    if not isinstance(result, dict):
        lines.append("- Not run.")
    else:
        lines.extend(
            [
                f"- Source: `{result.get('source_path', '')}`",
                f"- Source hash: `{result.get('source_hash', '')}`",
                f"- Generated at: {result.get('generated_at', '')}",
                f"- Rows seen: {result.get('rows_seen', 0)}",
                f"- Rows inserted: {result.get('rows_inserted', 0)}",
                f"- Rows skipped: {result.get('rows_skipped', 0)}",
                f"- Provider quality table rows: {result.get('table_row_count', 0)}",
            ]
        )
    lines.extend(["", "## Evidence Import", ""])
    if not isinstance(evidence, dict):
        lines.append("- Not run.")
    else:
        lines.extend(evidence_import_markdown_lines(evidence))
    lines.extend(["", "## Minute Bars Import", ""])
    if not isinstance(minute_bars, dict):
        lines.append("- Not run.")
    else:
        lines.extend(minute_bars_import_markdown_lines(minute_bars))
    lines.extend(["", "## Evidence Runs Import", ""])
    if not isinstance(evidence_runs, dict):
        lines.append("- Not run.")
    else:
        lines.extend(evidence_runs_import_markdown_lines(evidence_runs))
    lines.extend(["", "## System Status Import", ""])
    if not isinstance(system_status, dict):
        lines.append("- Not run.")
    else:
        lines.extend(system_status_import_markdown_lines(system_status))
    lines.extend(["", "## Capture Index Import", ""])
    if not isinstance(capture_index, dict):
        lines.append("- Not run.")
    else:
        lines.extend(capture_index_import_markdown_lines(capture_index))
    return "\n".join(lines)


def write_evidence_import_report(payload: dict[str, object], *, json_path: Path, markdown_path: Path) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Momentum Hunter SQLite Evidence Import",
        "",
        "Additive import report. `opportunity-alerts.json` remains the active derived source of truth.",
        "",
    ]
    lines.extend(evidence_import_markdown_lines(payload))
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def write_minute_bars_import_report(payload: dict[str, object], *, json_path: Path, markdown_path: Path) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Momentum Hunter SQLite Minute Bars Import",
        "",
        "Additive import report. `opportunity-minute-bars.json` remains the active derived minute-bar cache.",
        "",
    ]
    lines.extend(minute_bars_import_markdown_lines(payload))
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def write_evidence_runs_import_report(payload: dict[str, object], *, json_path: Path, markdown_path: Path) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Momentum Hunter SQLite Evidence Runs Import",
        "",
        "Additive import report. Structured evidence JSON files remain the active source files.",
        "",
    ]
    lines.extend(evidence_runs_import_markdown_lines(payload))
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def write_system_status_import_report(payload: dict[str, object], *, json_path: Path, markdown_path: Path) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Momentum Hunter SQLite System Status Import",
        "",
        "Additive import report. Structured status/report JSON files remain the active source files.",
        "",
    ]
    lines.extend(system_status_import_markdown_lines(payload))
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def write_capture_index_import_report(payload: dict[str, object], *, json_path: Path, markdown_path: Path) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# Momentum Hunter SQLite Capture Index Import",
        "",
        "Additive import report. `analysis-captures.csv` and raw capture files remain authoritative.",
        "",
    ]
    lines.extend(capture_index_import_markdown_lines(payload))
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def evidence_import_markdown_lines(result: dict[str, object]) -> list[str]:
    warnings = result.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    lines = [
        f"- Source: `{result.get('source_path', '')}`",
        f"- Source hash: `{result.get('source_hash', '')}`",
        f"- Imported at: {result.get('imported_at', '')}",
        f"- Alerts seen: {result.get('alerts_seen', 0)}",
        f"- Alerts inserted: {result.get('alerts_inserted', 0)}",
        f"- Alerts updated: {result.get('alerts_updated', 0)}",
        f"- Alerts skipped unchanged: {result.get('alerts_skipped', 0)}",
        f"- Alert table rows: {result.get('alert_table_row_count', 0)}",
        f"- Source alert rows in SQLite: {result.get('source_alert_rows_in_sqlite', 0)}",
        f"- Outcomes seen: {result.get('outcomes_seen', 0)}",
        f"- Outcomes inserted: {result.get('outcomes_inserted', 0)}",
        f"- Outcomes updated: {result.get('outcomes_updated', 0)}",
        f"- Outcomes skipped unchanged: {result.get('outcomes_skipped', 0)}",
        f"- Outcome table rows: {result.get('outcome_table_row_count', 0)}",
        f"- Source outcome rows in SQLite: {result.get('source_outcome_rows_in_sqlite', 0)}",
        f"- Pending outcomes: {result.get('pending_outcomes', 0)}",
        f"- Completed outcomes: {result.get('completed_outcomes', 0)}",
        f"- Unscorable outcomes: {result.get('unscorable_outcomes', 0)}",
        "",
        "## Validation",
        "",
        f"- SQLite alert count matches source: {yes_no(result.get('alerts_seen') == result.get('source_alert_rows_in_sqlite'))}",
        f"- SQLite outcome count matches source: {yes_no(result.get('outcomes_seen') == result.get('source_outcome_rows_in_sqlite'))}",
        f"- Pending and unscorable states preserved: {yes_no(int_value(result.get('pending_outcomes')) >= 0 and int_value(result.get('unscorable_outcomes')) >= 0)}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    return lines


def evidence_runs_import_markdown_lines(result: dict[str, object]) -> list[str]:
    warnings = result.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    run_types = result.get("run_types", {})
    if not isinstance(run_types, dict):
        run_types = {}
    source_paths = result.get("source_paths", [])
    if not isinstance(source_paths, list):
        source_paths = []
    lines = [
        f"- Imported at: {result.get('imported_at', '')}",
        f"- Source files considered: {len(source_paths)}",
        f"- Runs seen: {result.get('runs_seen', 0)}",
        f"- Runs inserted: {result.get('runs_inserted', 0)}",
        f"- Runs updated: {result.get('runs_updated', 0)}",
        f"- Runs skipped unchanged: {result.get('runs_skipped', 0)}",
        f"- Metrics seen: {result.get('metrics_seen', 0)}",
        f"- Metrics inserted: {result.get('metrics_inserted', 0)}",
        f"- Metrics updated: {result.get('metrics_updated', 0)}",
        f"- Metrics skipped unchanged: {result.get('metrics_skipped', 0)}",
        f"- Evidence run table rows: {result.get('evidence_run_table_row_count', 0)}",
        f"- Evidence metric table rows: {result.get('evidence_metric_table_row_count', 0)}",
        "",
        "## Run Types",
        "",
    ]
    if run_types:
        lines.extend([f"- {run_type}: {count}" for run_type, count in sorted(run_types.items())])
    else:
        lines.append("- None.")
    lines.extend(["", "## Source Files", ""])
    lines.extend([f"- `{path}`" for path in source_paths] if source_paths else ["- None."])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    return lines


def system_status_import_markdown_lines(result: dict[str, object]) -> list[str]:
    warnings = result.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    status_counts = result.get("status_counts", {})
    if not isinstance(status_counts, dict):
        status_counts = {}
    event_type_counts = result.get("event_type_counts", {})
    if not isinstance(event_type_counts, dict):
        event_type_counts = {}
    source_paths = result.get("source_paths", [])
    if not isinstance(source_paths, list):
        source_paths = []
    lines = [
        f"- Imported at: {result.get('imported_at', '')}",
        f"- Source files considered: {len(source_paths)}",
        f"- Events seen: {result.get('events_seen', 0)}",
        f"- Events inserted: {result.get('events_inserted', 0)}",
        f"- Events updated: {result.get('events_updated', 0)}",
        f"- Events skipped unchanged: {result.get('events_skipped', 0)}",
        f"- System status table rows: {result.get('table_row_count', 0)}",
        "",
        "## Status Counts",
        "",
    ]
    lines.extend([f"- {status}: {count}" for status, count in sorted(status_counts.items())] if status_counts else ["- None."])
    lines.extend(["", "## Event Types", ""])
    lines.extend([f"- {event_type}: {count}" for event_type, count in sorted(event_type_counts.items())] if event_type_counts else ["- None."])
    lines.extend(["", "## Source Files", ""])
    lines.extend([f"- `{path}`" for path in source_paths] if source_paths else ["- None."])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    return lines


def capture_index_import_markdown_lines(result: dict[str, object]) -> list[str]:
    warnings = result.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    lines = [
        f"- Source: `{result.get('source_path', '')}`",
        f"- Source hash: `{result.get('source_hash', '')}`",
        f"- Imported at: {result.get('imported_at', '')}",
        f"- Analysis rows seen: {result.get('analysis_rows_seen', 0)}",
        f"- Captures seen: {result.get('captures_seen', 0)}",
        f"- Captures inserted: {result.get('captures_inserted', 0)}",
        f"- Captures updated: {result.get('captures_updated', 0)}",
        f"- Captures skipped unchanged: {result.get('captures_skipped', 0)}",
        f"- Candidates seen: {result.get('candidates_seen', 0)}",
        f"- Candidates inserted: {result.get('candidates_inserted', 0)}",
        f"- Candidates updated: {result.get('candidates_updated', 0)}",
        f"- Candidates skipped unchanged: {result.get('candidates_skipped', 0)}",
        f"- Capture table rows: {result.get('capture_table_row_count', 0)}",
        f"- Candidate table rows: {result.get('candidate_table_row_count', 0)}",
        "",
        "## Validation",
        "",
        f"- SQLite capture count matches source captures: {yes_no(result.get('captures_seen') == result.get('source_capture_rows_in_sqlite'))}",
        f"- SQLite candidate count matches source candidates: {yes_no(result.get('candidates_seen') == result.get('source_candidate_rows_in_sqlite'))}",
        f"- Source files unchanged by import: yes",
        "",
        "## Warnings",
        "",
    ]
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    return lines


def minute_bars_import_markdown_lines(result: dict[str, object]) -> list[str]:
    warnings = result.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    symbol_counts = result.get("symbol_counts", {})
    first_timestamps = result.get("first_timestamps", {})
    latest_timestamps = result.get("latest_timestamps", {})
    if not isinstance(symbol_counts, dict):
        symbol_counts = {}
    if not isinstance(first_timestamps, dict):
        first_timestamps = {}
    if not isinstance(latest_timestamps, dict):
        latest_timestamps = {}
    lines = [
        f"- Source: `{result.get('source_path', '')}`",
        f"- Source hash: `{result.get('source_hash', '')}`",
        f"- Imported at: {result.get('imported_at', '')}",
        f"- Symbols seen: {result.get('symbols_seen', 0)}",
        f"- Bars seen: {result.get('bars_seen', 0)}",
        f"- Valid bars: {result.get('valid_bars', 0)}",
        f"- Invalid bars skipped: {result.get('invalid_bars', 0)}",
        f"- Duplicate source bars: {result.get('duplicate_bars', 0)}",
        f"- Bars inserted: {result.get('bars_inserted', 0)}",
        f"- Bars updated: {result.get('bars_updated', 0)}",
        f"- Bars skipped unchanged: {result.get('bars_skipped', 0)}",
        f"- Minute bar table rows: {result.get('table_row_count', 0)}",
        f"- Source rows in SQLite: {result.get('source_rows_in_sqlite', 0)}",
        "",
        "## Validation",
        "",
        f"- SQLite source row count matches valid de-duplicated bars: {yes_no((int_value(result.get('valid_bars')) - int_value(result.get('duplicate_bars'))) == int_value(result.get('source_rows_in_sqlite')))}",
        f"- Source file unchanged by import: yes",
        "",
        "## Symbol Counts",
        "",
    ]
    if symbol_counts:
        lines.extend(
            [
                f"- {symbol}: {count} bars, {first_timestamps.get(symbol, 'n/a')} -> {latest_timestamps.get(symbol, 'n/a')}"
                for symbol, count in sorted(symbol_counts.items())
            ]
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None."])
    return lines


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize Momentum Hunter SQLite and import low-risk derived data.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--data-quality-report", type=Path, default=DATA_QUALITY_LATEST_JSON)
    parser.add_argument("--alerts-path", type=Path, default=OPPORTUNITY_ALERTS_PATH)
    parser.add_argument("--minute-bars-path", type=Path, default=OPPORTUNITY_MINUTE_BARS_PATH)
    parser.add_argument("--analysis-captures-path", type=Path, default=ANALYSIS_CSV)
    parser.add_argument(
        "--slice",
        choices=["provider-quality", "evidence", "minute-bars", "evidence-runs", "system-status", "capture-index", "all", "all-safe", "init"],
        default="provider-quality",
        help="SQLite import slice to run. Default preserves the original provider-quality-only behavior.",
    )
    parser.add_argument("--init-only", action="store_true", help="Initialize schema without importing provider/data-quality rows.")
    parser.add_argument("--report-json", type=Path, default=SQLITE_IMPORT_LATEST_JSON)
    parser.add_argument("--report-md", type=Path, default=SQLITE_IMPORT_LATEST_MD)
    parser.add_argument("--all-safe-report-json", type=Path, default=SQLITE_IMPORT_ALL_SAFE_LATEST_JSON)
    parser.add_argument("--all-safe-report-md", type=Path, default=SQLITE_IMPORT_ALL_SAFE_LATEST_MD)
    parser.add_argument("--evidence-report-json", type=Path, default=SQLITE_EVIDENCE_IMPORT_LATEST_JSON)
    parser.add_argument("--evidence-report-md", type=Path, default=SQLITE_EVIDENCE_IMPORT_LATEST_MD)
    parser.add_argument("--minute-bars-report-json", type=Path, default=SQLITE_MINUTE_BARS_IMPORT_LATEST_JSON)
    parser.add_argument("--minute-bars-report-md", type=Path, default=SQLITE_MINUTE_BARS_IMPORT_LATEST_MD)
    parser.add_argument("--evidence-runs-report-json", type=Path, default=SQLITE_EVIDENCE_RUNS_IMPORT_LATEST_JSON)
    parser.add_argument("--evidence-runs-report-md", type=Path, default=SQLITE_EVIDENCE_RUNS_IMPORT_LATEST_MD)
    parser.add_argument("--system-status-report-json", type=Path, default=SQLITE_SYSTEM_STATUS_IMPORT_LATEST_JSON)
    parser.add_argument("--system-status-report-md", type=Path, default=SQLITE_SYSTEM_STATUS_IMPORT_LATEST_MD)
    parser.add_argument("--capture-index-report-json", type=Path, default=SQLITE_CAPTURE_INDEX_IMPORT_LATEST_JSON)
    parser.add_argument("--capture-index-report-md", type=Path, default=SQLITE_CAPTURE_INDEX_IMPORT_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    slice_name = "init" if args.init_only else args.slice
    run_all = slice_name in {"all", "all-safe"}
    report_json = args.all_safe_report_json if slice_name == "all-safe" else args.report_json
    report_md = args.all_safe_report_md if slice_name == "all-safe" else args.report_md
    payload = run_sqlite_migration(
        db_path=args.db,
        data_quality_report=args.data_quality_report,
        alerts_path=args.alerts_path,
        minute_bars_path=args.minute_bars_path,
        analysis_captures_path=args.analysis_captures_path,
        import_provider_quality=slice_name == "provider-quality" or run_all,
        import_evidence=slice_name == "evidence" or run_all,
        import_minute_bar_slice=slice_name == "minute-bars" or run_all,
        import_evidence_run_slice=slice_name == "evidence-runs" or run_all,
        import_system_status_slice=slice_name == "system-status" or run_all,
        import_capture_index_slice=slice_name == "capture-index" or run_all,
        report_json=report_json,
        report_md=report_md,
        evidence_report_json=args.evidence_report_json,
        evidence_report_md=args.evidence_report_md,
        minute_bars_report_json=args.minute_bars_report_json,
        minute_bars_report_md=args.minute_bars_report_md,
        evidence_runs_report_json=args.evidence_runs_report_json,
        evidence_runs_report_md=args.evidence_runs_report_md,
        system_status_report_json=args.system_status_report_json,
        system_status_report_md=args.system_status_report_md,
        capture_index_report_json=args.capture_index_report_json,
        capture_index_report_md=args.capture_index_report_md,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
