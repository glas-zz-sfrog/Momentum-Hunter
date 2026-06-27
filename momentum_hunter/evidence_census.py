from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.sqlite_store import SQLITE_DB_PATH, connect_database, current_schema_version
from momentum_hunter.time_utils import now_central


EVIDENCE_CENSUS_ENGINE_VERSION = "sqlite_evidence_census_v1"
EVIDENCE_CENSUS_LATEST_JSON = DATA_DIR / "reports" / "evidence-census-latest.json"
EVIDENCE_CENSUS_LATEST_MD = DATA_DIR / "reports" / "evidence-census-latest.md"
CANDIDATE_COMPLETENESS_LATEST_JSON = DATA_DIR / "reports" / "candidate-data-completeness-latest.json"
CANDIDATE_COMPLETENESS_LATEST_MD = DATA_DIR / "reports" / "candidate-data-completeness-latest.md"


CANDIDATE_FIELDS = [
    "score",
    "price",
    "percent_change",
    "volume",
    "relative_volume",
    "market_cap",
    "sector",
    "industry",
    "freshness",
    "freshness_score",
    "article_count",
]


def build_evidence_census_report(*, db_path: Path = SQLITE_DB_PATH) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    if not db_path.exists():
        return {
            "schema_version": 1,
            "engine_version": EVIDENCE_CENSUS_ENGINE_VERSION,
            "generated_at": generated_at,
            "database_path": str(db_path),
            "sqlite_schema_version": 0,
            "overall_status": "WARN",
            "table_counts": {},
            "alerts": {},
            "captures": {},
            "minute_bars": {},
            "evidence_runs": {},
            "user_state": {},
            "warnings": ["SQLITE_DATABASE_MISSING"],
        }
    warnings: list[str] = []
    with connect_database(db_path) as connection:
        schema_version = current_schema_version(connection)
        table_counts = {table: count_table(connection, table) for table in census_tables()}
        alerts = alert_census(connection)
        captures = capture_census(connection)
        minute_bars = minute_bar_census(connection)
        evidence_runs = evidence_run_census(connection)
        user_state = user_state_census(connection)
    if int(alerts.get("completed", 0)) < 25:
        warnings.append("LOW_COMPLETED_ALERT_SAMPLE")
    if int(minute_bars.get("total_bars", 0)) == 0:
        warnings.append("NO_MINUTE_BARS")
    return {
        "schema_version": 1,
        "engine_version": EVIDENCE_CENSUS_ENGINE_VERSION,
        "generated_at": generated_at,
        "database_path": str(db_path),
        "sqlite_schema_version": schema_version,
        "overall_status": "WARN" if warnings else "PASS",
        "table_counts": table_counts,
        "alerts": alerts,
        "captures": captures,
        "minute_bars": minute_bars,
        "evidence_runs": evidence_runs,
        "user_state": user_state,
        "warnings": warnings,
    }


def build_candidate_data_completeness_report(*, db_path: Path = SQLITE_DB_PATH) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    if not db_path.exists():
        return {
            "schema_version": 1,
            "engine_version": "candidate_data_completeness_v1",
            "generated_at": generated_at,
            "database_path": str(db_path),
            "sqlite_schema_version": 0,
            "overall_status": "WARN",
            "candidate_rows": 0,
            "field_summary": [],
            "symbol_summary": [],
            "warnings": ["SQLITE_DATABASE_MISSING"],
        }
    with connect_database(db_path) as connection:
        schema_version = current_schema_version(connection)
        total = count_table(connection, "capture_candidates")
        field_summary = candidate_field_summary(connection, total)
        symbol_summary = candidate_symbol_completeness(connection)
    warnings = [
        f"HIGH_MISSING_RATE:{item['field']}:{item['missing_rate_pct']}%"
        for item in field_summary
        if float(item.get("missing_rate_pct", 0)) >= 50.0 and int(item.get("missing_count", 0)) > 0
    ]
    return {
        "schema_version": 1,
        "engine_version": "candidate_data_completeness_v1",
        "generated_at": generated_at,
        "database_path": str(db_path),
        "sqlite_schema_version": schema_version,
        "overall_status": "WARN" if warnings else "PASS",
        "candidate_rows": total,
        "field_summary": field_summary,
        "symbol_summary": symbol_summary,
        "warnings": warnings,
    }


def census_tables() -> list[str]:
    return [
        "provider_quality_checks",
        "opportunity_alerts",
        "alert_outcomes",
        "minute_bars",
        "evidence_runs",
        "evidence_metrics",
        "system_status_events",
        "captures",
        "capture_candidates",
        "candidate_reviews",
        "watchlist_items",
        "entry_plans",
    ]


def alert_census(connection: sqlite3.Connection) -> dict[str, Any]:
    total = count_table(connection, "opportunity_alerts")
    completed = scalar(
        connection,
        """
        SELECT COUNT(*) FROM alert_outcomes
        WHERE classification IN ('SUCCESSFUL', 'FAILED', 'NOISE', 'LATE')
        """,
    )
    pending = scalar(connection, "SELECT COUNT(*) FROM alert_outcomes WHERE status LIKE 'PENDING%'")
    unscorable = scalar(
        connection,
        """
        SELECT COUNT(*) FROM alert_outcomes
        WHERE status = 'UNSCORABLE_OUTCOME' OR classification LIKE 'UNSCORABLE%'
        """,
    )
    return {
        "total_alerts": total,
        "completed": completed,
        "pending": pending,
        "unscorable": unscorable,
        "completion_rate_pct": round(completed / total * 100.0, 2) if total else 0.0,
        "by_type": rows(connection, "SELECT alert_type, COUNT(*) AS count FROM opportunity_alerts GROUP BY alert_type ORDER BY count DESC, alert_type"),
        "by_symbol": rows(connection, "SELECT symbol, COUNT(*) AS count FROM opportunity_alerts GROUP BY symbol ORDER BY count DESC, symbol"),
        "by_classification": rows(
            connection,
            """
            SELECT classification, COUNT(*) AS count
            FROM alert_outcomes
            GROUP BY classification
            ORDER BY count DESC, classification
            """,
        ),
    }


def capture_census(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "total_captures": count_table(connection, "captures"),
        "total_candidates": count_table(connection, "capture_candidates"),
        "by_session": rows(connection, "SELECT session, COUNT(*) AS count FROM captures GROUP BY session ORDER BY session"),
        "by_scanner": rows(connection, "SELECT scanner, COUNT(*) AS count FROM captures GROUP BY scanner ORDER BY count DESC, scanner"),
        "study_eligible": scalar(connection, "SELECT COUNT(*) FROM captures WHERE is_study_eligible = 1"),
        "quarantined": scalar(connection, "SELECT COUNT(*) FROM captures WHERE COALESCE(is_quarantined, 0) = 1"),
    }


def minute_bar_census(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "total_bars": count_table(connection, "minute_bars"),
        "symbols": scalar(connection, "SELECT COUNT(DISTINCT symbol) FROM minute_bars"),
        "by_symbol": rows(
            connection,
            """
            SELECT symbol, COUNT(*) AS count, MIN(timestamp) AS first_timestamp, MAX(timestamp) AS latest_timestamp
            FROM minute_bars
            GROUP BY symbol
            ORDER BY count DESC, symbol
            """,
        ),
    }


def evidence_run_census(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "runs": count_table(connection, "evidence_runs"),
        "metrics": count_table(connection, "evidence_metrics"),
        "by_run_type": rows(
            connection,
            """
            SELECT run_type, COUNT(*) AS count, MAX(generated_at) AS latest_generated_at
            FROM evidence_runs
            GROUP BY run_type
            ORDER BY count DESC, run_type
            """,
        ),
    }


def user_state_census(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "candidate_reviews": count_table(connection, "candidate_reviews"),
        "watchlist_items": count_table(connection, "watchlist_items"),
        "entry_plans": count_table(connection, "entry_plans"),
        "complete_entry_plans": scalar(connection, "SELECT COUNT(*) FROM entry_plans WHERE plan_complete = 1"),
        "incomplete_entry_plans": scalar(connection, "SELECT COUNT(*) FROM entry_plans WHERE plan_complete = 0"),
    }


def candidate_field_summary(connection: sqlite3.Connection, total: int) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for field in CANDIDATE_FIELDS:
        missing = scalar(
            connection,
            f"""
            SELECT COUNT(*)
            FROM capture_candidates
            WHERE {field} IS NULL OR TRIM(CAST({field} AS TEXT)) = '' OR LOWER(TRIM(CAST({field} AS TEXT))) = 'n/a'
            """,
        )
        present = total - missing
        summary.append(
            {
                "field": field,
                "present_count": present,
                "missing_count": missing,
                "missing_rate_pct": round(missing / total * 100.0, 2) if total else 0.0,
            }
        )
    return summary


def candidate_symbol_completeness(connection: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    fields_sql = " + ".join(
        f"CASE WHEN {field} IS NULL OR TRIM(CAST({field} AS TEXT)) = '' OR LOWER(TRIM(CAST({field} AS TEXT))) = 'n/a' THEN 1 ELSE 0 END"
        for field in CANDIDATE_FIELDS
    )
    return rows(
        connection,
        f"""
        SELECT ticker,
               COUNT(*) AS candidate_rows,
               SUM({fields_sql}) AS missing_field_instances
        FROM capture_candidates
        GROUP BY ticker
        ORDER BY missing_field_instances DESC, candidate_rows DESC, ticker
        LIMIT {int(limit)}
        """,
    )


def count_table(connection: sqlite3.Connection, table: str) -> int:
    return scalar(connection, f"SELECT COUNT(*) FROM {table}")


def scalar(connection: sqlite3.Connection, sql: str) -> int:
    try:
        value = connection.execute(sql).fetchone()[0]
    except sqlite3.Error:
        return 0
    return int(value or 0)


def rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in connection.execute(sql).fetchall()]
    except sqlite3.Error:
        return []


def write_evidence_census_report(
    payload: dict[str, Any],
    *,
    json_path: Path = EVIDENCE_CENSUS_LATEST_JSON,
    markdown_path: Path = EVIDENCE_CENSUS_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_evidence_census_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def write_candidate_completeness_report(
    payload: dict[str, Any],
    *,
    json_path: Path = CANDIDATE_COMPLETENESS_LATEST_JSON,
    markdown_path: Path = CANDIDATE_COMPLETENESS_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_candidate_completeness_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_evidence_census_markdown(payload: dict[str, Any]) -> str:
    alerts = payload.get("alerts", {})
    captures = payload.get("captures", {})
    minute_bars = payload.get("minute_bars", {})
    evidence_runs = payload.get("evidence_runs", {})
    user_state = payload.get("user_state", {})
    lines = [
        "# Momentum Hunter Evidence Census",
        "",
        "Read-only census of the current SQLite evidence mirror.",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- SQLite schema version: {payload.get('sqlite_schema_version', 0)}",
        "",
        "## Alerts",
        "",
        f"- Total alerts: {alerts.get('total_alerts', 0)}",
        f"- Completed: {alerts.get('completed', 0)}",
        f"- Pending: {alerts.get('pending', 0)}",
        f"- Unscorable: {alerts.get('unscorable', 0)}",
        f"- Completion rate: {alerts.get('completion_rate_pct', 0)}%",
        "",
        "## Captures",
        "",
        f"- Total captures: {captures.get('total_captures', 0)}",
        f"- Total candidates: {captures.get('total_candidates', 0)}",
        f"- Study eligible: {captures.get('study_eligible', 0)}",
        f"- Quarantined: {captures.get('quarantined', 0)}",
        "",
        "## Minute Bars",
        "",
        f"- Total bars: {minute_bars.get('total_bars', 0)}",
        f"- Symbols: {minute_bars.get('symbols', 0)}",
        "",
        "## Evidence Runs",
        "",
        f"- Runs: {evidence_runs.get('runs', 0)}",
        f"- Metrics: {evidence_runs.get('metrics', 0)}",
        "",
        "## User State Mirror",
        "",
        f"- Candidate reviews: {user_state.get('candidate_reviews', 0)}",
        f"- Watchlist items: {user_state.get('watchlist_items', 0)}",
        f"- Entry plans: {user_state.get('entry_plans', 0)}",
        "",
        "## Warnings",
        "",
    ]
    warnings = payload.get("warnings", [])
    lines.extend([f"- {warning}" for warning in warnings] if isinstance(warnings, list) and warnings else ["- None."])
    return "\n".join(lines) + "\n"


def format_candidate_completeness_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Hunter Candidate Data Completeness",
        "",
        "Read-only completeness report for mirrored capture candidate fields.",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Candidate rows: {payload.get('candidate_rows', 0)}",
        "",
        "| Field | Present | Missing | Missing Rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for item in payload.get("field_summary", []):
        if isinstance(item, dict):
            lines.append(
                f"| {item.get('field', '')} | {item.get('present_count', 0)} | "
                f"{item.get('missing_count', 0)} | {item.get('missing_rate_pct', 0)}% |"
            )
    lines.extend(["", "## Most Incomplete Symbols", "", "| Symbol | Rows | Missing Field Instances |", "| --- | ---: | ---: |"])
    for item in payload.get("symbol_summary", [])[:25]:
        if isinstance(item, dict):
            lines.append(
                f"| {item.get('ticker', '')} | {item.get('candidate_rows', 0)} | {item.get('missing_field_instances', 0)} |"
            )
    warnings = payload.get("warnings", [])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] if isinstance(warnings, list) and warnings else ["- None."])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate read-only evidence census and candidate completeness reports.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--evidence-json", type=Path, default=EVIDENCE_CENSUS_LATEST_JSON)
    parser.add_argument("--evidence-md", type=Path, default=EVIDENCE_CENSUS_LATEST_MD)
    parser.add_argument("--candidate-json", type=Path, default=CANDIDATE_COMPLETENESS_LATEST_JSON)
    parser.add_argument("--candidate-md", type=Path, default=CANDIDATE_COMPLETENESS_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    census = build_evidence_census_report(db_path=args.db)
    completeness = build_candidate_data_completeness_report(db_path=args.db)
    census_paths = write_evidence_census_report(census, json_path=args.evidence_json, markdown_path=args.evidence_md)
    completeness_paths = write_candidate_completeness_report(
        completeness,
        json_path=args.candidate_json,
        markdown_path=args.candidate_md,
    )
    print(
        json.dumps(
            {
                "evidence_status": census.get("overall_status"),
                "candidate_completeness_status": completeness.get("overall_status"),
                "warnings": {
                    "evidence": census.get("warnings", []),
                    "candidate_completeness": completeness.get("warnings", []),
                },
                "paths": {
                    "evidence_json": str(census_paths["json"]),
                    "evidence_markdown": str(census_paths["markdown"]),
                    "candidate_json": str(completeness_paths["json"]),
                    "candidate_markdown": str(completeness_paths["markdown"]),
                },
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
