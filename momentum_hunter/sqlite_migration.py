from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH
from momentum_hunter.sqlite_store import (
    SQLITE_DB_PATH,
    EvidenceImportResult,
    ProviderQualityImportResult,
    connect_database,
    current_schema_version,
    import_opportunity_alerts,
    import_provider_quality_report,
    initialize_schema,
)


SQLITE_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-import-latest.json"
SQLITE_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-import-latest.md"
SQLITE_EVIDENCE_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-evidence-import-latest.json"
SQLITE_EVIDENCE_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-evidence-import-latest.md"


def initialize_database(db_path: Path | None = None) -> int:
    with connect_database(db_path) as connection:
        initialize_schema(connection)
        return current_schema_version(connection)


def run_sqlite_migration(
    *,
    db_path: Path | None = None,
    data_quality_report: Path = DATA_QUALITY_LATEST_JSON,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    import_provider_quality: bool = True,
    import_evidence: bool = False,
    report_json: Path = SQLITE_IMPORT_LATEST_JSON,
    report_md: Path = SQLITE_IMPORT_LATEST_MD,
    evidence_report_json: Path = SQLITE_EVIDENCE_IMPORT_LATEST_JSON,
    evidence_report_md: Path = SQLITE_EVIDENCE_IMPORT_LATEST_MD,
) -> dict[str, object]:
    ensure_app_dirs()
    schema_version = initialize_database(db_path)
    provider_quality_result: ProviderQualityImportResult | None = None
    evidence_result: EvidenceImportResult | None = None
    if import_provider_quality:
        provider_quality_result = import_provider_quality_report(data_quality_report, db_path=db_path)
    if import_evidence:
        evidence_result = import_opportunity_alerts(alerts_path, db_path=db_path)
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "database_path": str(db_path or SQLITE_DB_PATH),
        "provider_quality_import": asdict(provider_quality_result) if provider_quality_result else None,
        "evidence_import": asdict(evidence_result) if evidence_result else None,
    }
    write_import_report(payload, json_path=report_json, markdown_path=report_md)
    if evidence_result:
        write_evidence_import_report(
            asdict(evidence_result),
            json_path=evidence_report_json,
            markdown_path=evidence_report_md,
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
    parser.add_argument(
        "--slice",
        choices=["provider-quality", "evidence", "all", "init"],
        default="provider-quality",
        help="SQLite import slice to run. Default preserves the original provider-quality-only behavior.",
    )
    parser.add_argument("--init-only", action="store_true", help="Initialize schema without importing provider/data-quality rows.")
    parser.add_argument("--report-json", type=Path, default=SQLITE_IMPORT_LATEST_JSON)
    parser.add_argument("--report-md", type=Path, default=SQLITE_IMPORT_LATEST_MD)
    parser.add_argument("--evidence-report-json", type=Path, default=SQLITE_EVIDENCE_IMPORT_LATEST_JSON)
    parser.add_argument("--evidence-report-md", type=Path, default=SQLITE_EVIDENCE_IMPORT_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    slice_name = "init" if args.init_only else args.slice
    payload = run_sqlite_migration(
        db_path=args.db,
        data_quality_report=args.data_quality_report,
        alerts_path=args.alerts_path,
        import_provider_quality=slice_name in {"provider-quality", "all"},
        import_evidence=slice_name in {"evidence", "all"},
        report_json=args.report_json,
        report_md=args.report_md,
        evidence_report_json=args.evidence_report_json,
        evidence_report_md=args.evidence_report_md,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
