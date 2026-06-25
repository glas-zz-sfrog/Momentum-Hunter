from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.sqlite_store import (
    SQLITE_DB_PATH,
    ProviderQualityImportResult,
    connect_database,
    current_schema_version,
    import_provider_quality_report,
    initialize_schema,
)


SQLITE_IMPORT_LATEST_JSON = DATA_DIR / "reports" / "sqlite-import-latest.json"
SQLITE_IMPORT_LATEST_MD = DATA_DIR / "reports" / "sqlite-import-latest.md"


def initialize_database(db_path: Path | None = None) -> int:
    with connect_database(db_path) as connection:
        initialize_schema(connection)
        return current_schema_version(connection)


def run_sqlite_migration(
    *,
    db_path: Path | None = None,
    data_quality_report: Path = DATA_QUALITY_LATEST_JSON,
    import_provider_quality: bool = True,
    report_json: Path = SQLITE_IMPORT_LATEST_JSON,
    report_md: Path = SQLITE_IMPORT_LATEST_MD,
) -> dict[str, object]:
    ensure_app_dirs()
    schema_version = initialize_database(db_path)
    provider_quality_result: ProviderQualityImportResult | None = None
    if import_provider_quality:
        provider_quality_result = import_provider_quality_report(data_quality_report, db_path=db_path)
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "database_path": str(db_path or SQLITE_DB_PATH),
        "provider_quality_import": asdict(provider_quality_result) if provider_quality_result else None,
    }
    write_import_report(payload, json_path=report_json, markdown_path=report_md)
    return payload


def write_import_report(payload: dict[str, object], *, json_path: Path, markdown_path: Path) -> dict[str, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_markdown(payload), encoding="utf-8")
    return {"json": json_path, "report": markdown_path}


def format_markdown(payload: dict[str, object]) -> str:
    result = payload.get("provider_quality_import")
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
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            f"- Source: `{result.get('source_path', '')}`",
            f"- Source hash: `{result.get('source_hash', '')}`",
            f"- Generated at: {result.get('generated_at', '')}",
            f"- Rows seen: {result.get('rows_seen', 0)}",
            f"- Rows inserted: {result.get('rows_inserted', 0)}",
            f"- Rows skipped: {result.get('rows_skipped', 0)}",
            f"- Provider quality table rows: {result.get('table_row_count', 0)}",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize Momentum Hunter SQLite and import low-risk derived data.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--data-quality-report", type=Path, default=DATA_QUALITY_LATEST_JSON)
    parser.add_argument("--init-only", action="store_true", help="Initialize schema without importing provider/data-quality rows.")
    parser.add_argument("--report-json", type=Path, default=SQLITE_IMPORT_LATEST_JSON)
    parser.add_argument("--report-md", type=Path, default=SQLITE_IMPORT_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_sqlite_migration(
        db_path=args.db,
        data_quality_report=args.data_quality_report,
        import_provider_quality=not args.init_only,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
