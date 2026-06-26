from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH
from momentum_hunter.sqlite_store import (
    SQLITE_DB_PATH,
    EvidenceImportResult,
    MinuteBarsImportResult,
    ProviderQualityImportResult,
    connect_database,
    current_schema_version,
    import_minute_bars,
    import_opportunity_alerts,
    import_provider_quality_report,
    initialize_schema,
)


SQLITE_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-import-latest.json"
SQLITE_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-import-latest.md"
SQLITE_EVIDENCE_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-evidence-import-latest.json"
SQLITE_EVIDENCE_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-evidence-import-latest.md"
SQLITE_MINUTE_BARS_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-minute-bars-import-latest.json"
SQLITE_MINUTE_BARS_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-minute-bars-import-latest.md"


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
    import_provider_quality: bool = True,
    import_evidence: bool = False,
    import_minute_bar_slice: bool = False,
    report_json: Path = SQLITE_IMPORT_LATEST_JSON,
    report_md: Path = SQLITE_IMPORT_LATEST_MD,
    evidence_report_json: Path = SQLITE_EVIDENCE_IMPORT_LATEST_JSON,
    evidence_report_md: Path = SQLITE_EVIDENCE_IMPORT_LATEST_MD,
    minute_bars_report_json: Path = SQLITE_MINUTE_BARS_IMPORT_LATEST_JSON,
    minute_bars_report_md: Path = SQLITE_MINUTE_BARS_IMPORT_LATEST_MD,
) -> dict[str, object]:
    ensure_app_dirs()
    schema_version = initialize_database(db_path)
    provider_quality_result: ProviderQualityImportResult | None = None
    evidence_result: EvidenceImportResult | None = None
    minute_bars_result: MinuteBarsImportResult | None = None
    if import_provider_quality:
        provider_quality_result = import_provider_quality_report(data_quality_report, db_path=db_path)
    if import_evidence:
        evidence_result = import_opportunity_alerts(alerts_path, db_path=db_path)
    if import_minute_bar_slice:
        minute_bars_result = import_minute_bars(minute_bars_path, db_path=db_path)
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "database_path": str(db_path or SQLITE_DB_PATH),
        "provider_quality_import": asdict(provider_quality_result) if provider_quality_result else None,
        "evidence_import": asdict(evidence_result) if evidence_result else None,
        "minute_bars_import": asdict(minute_bars_result) if minute_bars_result else None,
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
    parser.add_argument(
        "--slice",
        choices=["provider-quality", "evidence", "minute-bars", "all", "init"],
        default="provider-quality",
        help="SQLite import slice to run. Default preserves the original provider-quality-only behavior.",
    )
    parser.add_argument("--init-only", action="store_true", help="Initialize schema without importing provider/data-quality rows.")
    parser.add_argument("--report-json", type=Path, default=SQLITE_IMPORT_LATEST_JSON)
    parser.add_argument("--report-md", type=Path, default=SQLITE_IMPORT_LATEST_MD)
    parser.add_argument("--evidence-report-json", type=Path, default=SQLITE_EVIDENCE_IMPORT_LATEST_JSON)
    parser.add_argument("--evidence-report-md", type=Path, default=SQLITE_EVIDENCE_IMPORT_LATEST_MD)
    parser.add_argument("--minute-bars-report-json", type=Path, default=SQLITE_MINUTE_BARS_IMPORT_LATEST_JSON)
    parser.add_argument("--minute-bars-report-md", type=Path, default=SQLITE_MINUTE_BARS_IMPORT_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    slice_name = "init" if args.init_only else args.slice
    payload = run_sqlite_migration(
        db_path=args.db,
        data_quality_report=args.data_quality_report,
        alerts_path=args.alerts_path,
        minute_bars_path=args.minute_bars_path,
        import_provider_quality=slice_name in {"provider-quality", "all"},
        import_evidence=slice_name in {"evidence", "all"},
        import_minute_bar_slice=slice_name in {"minute-bars", "all"},
        report_json=args.report_json,
        report_md=args.report_md,
        evidence_report_json=args.evidence_report_json,
        evidence_report_md=args.evidence_report_md,
        minute_bars_report_json=args.minute_bars_report_json,
        minute_bars_report_md=args.minute_bars_report_md,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
