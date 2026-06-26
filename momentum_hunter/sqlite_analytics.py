from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.sqlite_store import SQLITE_DB_PATH, connect_database, current_schema_version
from momentum_hunter.time_utils import now_central


SQLITE_ANALYTICS_SCHEMA_VERSION = 1
SQLITE_ANALYTICS_ENGINE_VERSION = "sqlite_analytics_query_pack_v1"
REPORTS_DIR = DATA_DIR / "reports"
SQLITE_ANALYTICS_LATEST_JSON = REPORTS_DIR / "sqlite-analytics-query-pack-latest.json"
SQLITE_ANALYTICS_LATEST_MD = REPORTS_DIR / "sqlite-analytics-query-pack-latest.md"
STALE_AFTER_HOURS = 24


@dataclass(frozen=True)
class CandidateEvidenceSummary:
    symbol: str
    capture_count: int
    first_seen: str
    latest_seen: str
    score_peak: int | None
    first_price: float | None
    latest_price: float | None
    price_move_pct: float | None
    alerts_count: int
    outcomes_count: int
    latest_review_status: str
    entry_plan_status: str


def build_sqlite_analytics_report(
    *,
    db_path: Path = SQLITE_DB_PATH,
    generated_at: datetime | None = None,
    stale_after_hours: int = STALE_AFTER_HOURS,
) -> dict[str, Any]:
    generated_at = generated_at or now_central()
    if not db_path.exists():
        return {
            "schema_version": SQLITE_ANALYTICS_SCHEMA_VERSION,
            "engine_version": SQLITE_ANALYTICS_ENGINE_VERSION,
            "generated_at": generated_at.isoformat(),
            "database_path": str(db_path),
            "sqlite_schema_version": 0,
            "overall_status": "WARN",
            "candidate_evidence_summary": [],
            "alert_performance_sample_summary": empty_alert_summary(),
            "watchlist_preparedness_summary": empty_watchlist_summary(),
            "stale_evidence_summary": empty_stale_summary(stale_after_hours),
            "warnings": ["SQLITE_DATABASE_MISSING"],
        }
    warnings: list[str] = []
    with connect_database(db_path) as connection:
        schema_version = current_schema_version(connection)
        missing_tables = [table for table in required_tables() if not table_exists(connection, table)]
        if missing_tables:
            warnings.append(f"MISSING_TABLES:{','.join(missing_tables)}")
        candidate_summary = candidate_evidence_summary(connection) if not missing_tables else []
        alert_summary = alert_performance_sample_summary(connection) if not missing_tables else empty_alert_summary()
        watchlist_summary = watchlist_preparedness_summary(connection) if not missing_tables else empty_watchlist_summary()
        stale_summary = (
            stale_evidence_summary(connection, generated_at=generated_at, stale_after_hours=stale_after_hours)
            if not missing_tables
            else empty_stale_summary(stale_after_hours)
        )
    warnings.extend(stale_summary.get("warnings", []))
    return {
        "schema_version": SQLITE_ANALYTICS_SCHEMA_VERSION,
        "engine_version": SQLITE_ANALYTICS_ENGINE_VERSION,
        "generated_at": generated_at.isoformat(),
        "database_path": str(db_path),
        "sqlite_schema_version": schema_version,
        "overall_status": "WARN" if warnings else "PASS",
        "candidate_evidence_summary": [asdict(item) for item in candidate_summary],
        "alert_performance_sample_summary": alert_summary,
        "watchlist_preparedness_summary": watchlist_summary,
        "stale_evidence_summary": stale_summary,
        "warnings": dedupe(warnings),
    }


def candidate_evidence_summary(connection: sqlite3.Connection, *, limit: int = 50) -> list[CandidateEvidenceSummary]:
    rows = connection.execute(
        """
        SELECT
            cc.ticker AS symbol,
            c.capture_time,
            cc.score,
            cc.price
        FROM capture_candidates cc
        JOIN captures c ON c.capture_id = cc.capture_id
        WHERE COALESCE(c.is_quarantined, 0) = 0
        ORDER BY cc.ticker, c.capture_time
        """
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["symbol"] or "").upper(), []).append(row)
    alert_counts = grouped_count(connection, "opportunity_alerts", "symbol")
    outcome_counts = outcome_counts_by_symbol(connection)
    review_statuses = latest_review_status_by_symbol(connection)
    entry_plan_statuses = entry_plan_status_by_symbol(connection)
    summaries: list[CandidateEvidenceSummary] = []
    for symbol, symbol_rows in sorted(grouped.items()):
        first = symbol_rows[0]
        latest = symbol_rows[-1]
        first_price = optional_float(first["price"])
        latest_price = optional_float(latest["price"])
        move = None
        if first_price and latest_price is not None:
            move = round((latest_price - first_price) / first_price * 100.0, 3)
        scores = [int(row["score"]) for row in symbol_rows if row["score"] is not None]
        summaries.append(
            CandidateEvidenceSummary(
                symbol=symbol,
                capture_count=len(symbol_rows),
                first_seen=str(first["capture_time"] or ""),
                latest_seen=str(latest["capture_time"] or ""),
                score_peak=max(scores) if scores else None,
                first_price=first_price,
                latest_price=latest_price,
                price_move_pct=move,
                alerts_count=alert_counts.get(symbol, 0),
                outcomes_count=outcome_counts.get(symbol, 0),
                latest_review_status=review_statuses.get(symbol, ""),
                entry_plan_status=entry_plan_statuses.get(symbol, "none"),
            )
        )
    return sorted(summaries, key=lambda item: (-item.capture_count, item.symbol))[:limit]


def alert_performance_sample_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    total_alerts = table_count(connection, "opportunity_alerts")
    completed = scalar_count(
        connection,
        """
        SELECT COUNT(*) FROM alert_outcomes
        WHERE classification IN ('SUCCESSFUL', 'FAILED', 'NOISE', 'LATE')
        """,
    )
    pending = scalar_count(connection, "SELECT COUNT(*) FROM alert_outcomes WHERE status LIKE 'PENDING%'")
    unscorable = scalar_count(
        connection,
        """
        SELECT COUNT(*) FROM alert_outcomes
        WHERE status = 'UNSCORABLE_OUTCOME' OR classification LIKE 'UNSCORABLE%'
        """,
    )
    return {
        "total_alerts": total_alerts,
        "completed": completed,
        "pending": pending,
        "unscorable": unscorable,
        "by_classification": rows_to_dicts(
            connection.execute(
                """
                SELECT classification, COUNT(*) AS count
                FROM alert_outcomes
                GROUP BY classification
                ORDER BY count DESC, classification
                """
            ).fetchall()
        ),
        "by_alert_type": rows_to_dicts(
            connection.execute(
                """
                SELECT alert_type, COUNT(*) AS count
                FROM opportunity_alerts
                GROUP BY alert_type
                ORDER BY count DESC, alert_type
                """
            ).fetchall()
        ),
        "by_symbol": rows_to_dicts(
            connection.execute(
                """
                SELECT symbol, COUNT(*) AS alert_count
                FROM opportunity_alerts
                GROUP BY symbol
                ORDER BY alert_count DESC, symbol
                """
            ).fetchall()
        ),
    }


def watchlist_preparedness_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    watchlist_count = scalar_count(
        connection,
        "SELECT COUNT(*) FROM candidate_reviews WHERE review_status = 'watchlist'",
    )
    complete_plans = scalar_count(connection, "SELECT COUNT(*) FROM entry_plans WHERE plan_complete = 1")
    incomplete_plans = scalar_count(connection, "SELECT COUNT(*) FROM entry_plans WHERE plan_complete = 0")
    missing_entry = scalar_count(
        connection,
        "SELECT COUNT(*) FROM entry_plans WHERE trigger_condition IS NULL OR TRIM(trigger_condition) = ''",
    )
    missing_stop = scalar_count(connection, "SELECT COUNT(*) FROM entry_plans WHERE stop_price IS NULL")
    return {
        "watchlist_count": watchlist_count,
        "watchlist_artifact_count": table_count(connection, "watchlist_items"),
        "complete_plans": complete_plans,
        "incomplete_plans": incomplete_plans,
        "missing_entry": missing_entry,
        "missing_stop": missing_stop,
        "missing_target": "unavailable_current_schema",
        "plan_completion_rate_pct": round(complete_plans / (complete_plans + incomplete_plans) * 100.0, 2)
        if complete_plans + incomplete_plans
        else 0.0,
    }


def stale_evidence_summary(
    connection: sqlite3.Connection,
    *,
    generated_at: datetime,
    stale_after_hours: int,
) -> dict[str, Any]:
    rows = rows_to_dicts(
        connection.execute(
            """
            SELECT event_type, status, MAX(occurred_at) AS latest_occurred_at
            FROM system_status_events
            GROUP BY event_type, status
            ORDER BY latest_occurred_at DESC, event_type
            """
        ).fetchall()
    )
    events: list[dict[str, Any]] = []
    stale_events = 0
    for row in rows:
        age = age_hours(str(row.get("latest_occurred_at") or ""), generated_at)
        stale = bool(age is not None and age > stale_after_hours)
        if stale:
            stale_events += 1
        events.append({**row, "age_hours": round(age, 3) if age is not None else None, "stale": stale})
    latest_provider = connection.execute("SELECT MAX(generated_at) AS value FROM provider_quality_checks").fetchone()
    provider_age = age_hours(str(latest_provider["value"] or ""), generated_at) if latest_provider else None
    latest_import = latest_import_age_hours(connection, generated_at)
    warnings: list[str] = []
    if stale_events:
        warnings.append(f"STALE_SYSTEM_STATUS_EVENTS:{stale_events}")
    if provider_age is not None and provider_age > stale_after_hours:
        warnings.append("STALE_PROVIDER_CHECKS")
    if latest_import is not None and latest_import > stale_after_hours:
        warnings.append("STALE_SQLITE_IMPORT")
    return {
        "stale_after_hours": stale_after_hours,
        "system_status_events": events,
        "stale_system_status_event_count": stale_events,
        "latest_provider_check_age_hours": round(provider_age, 3) if provider_age is not None else None,
        "latest_sqlite_import_age_hours": round(latest_import, 3) if latest_import is not None else None,
        "warnings": warnings,
    }


def write_sqlite_analytics_report(payload: dict[str, Any], *, output_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    ensure_app_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "sqlite-analytics-query-pack-latest.json"
    markdown_path = output_dir / "sqlite-analytics-query-pack-latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_sqlite_analytics_markdown(payload), encoding="utf-8")
    return json_path, markdown_path


def format_sqlite_analytics_markdown(payload: dict[str, Any]) -> str:
    alerts = payload.get("alert_performance_sample_summary", {})
    watchlist = payload.get("watchlist_preparedness_summary", {})
    stale = payload.get("stale_evidence_summary", {})
    lines = [
        "# SQLite Analytics Query Pack",
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- SQLite schema version: {payload.get('sqlite_schema_version', 0)}",
        f"- Database: `{payload.get('database_path', '')}`",
        "",
        "## Candidate Evidence Summary",
        "",
        "| Symbol | Captures | First Seen | Latest Seen | Peak Score | Price Move | Alerts | Outcomes | Review | Plan |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for item in payload.get("candidate_evidence_summary", [])[:25]:
        lines.append(
            f"| {item['symbol']} | {item['capture_count']} | {item['first_seen']} | {item['latest_seen']} | "
            f"{item['score_peak'] if item['score_peak'] is not None else ''} | "
            f"{item['price_move_pct'] if item['price_move_pct'] is not None else ''} | "
            f"{item['alerts_count']} | {item['outcomes_count']} | {item['latest_review_status']} | {item['entry_plan_status']} |"
        )
    lines.extend(
        [
            "",
            "## Alert Performance Sample Summary",
            "",
            f"- Total alerts: {alerts.get('total_alerts', 0)}",
            f"- Completed: {alerts.get('completed', 0)}",
            f"- Pending: {alerts.get('pending', 0)}",
            f"- Unscorable: {alerts.get('unscorable', 0)}",
            "",
            "## Watchlist Preparedness Summary",
            "",
            f"- Watchlist reviews: {watchlist.get('watchlist_count', 0)}",
            f"- Watchlist artifacts: {watchlist.get('watchlist_artifact_count', 0)}",
            f"- Complete plans: {watchlist.get('complete_plans', 0)}",
            f"- Incomplete plans: {watchlist.get('incomplete_plans', 0)}",
            f"- Missing entry: {watchlist.get('missing_entry', 0)}",
            f"- Missing stop: {watchlist.get('missing_stop', 0)}",
            f"- Missing target: {watchlist.get('missing_target', '')}",
            "",
            "## Stale Evidence Summary",
            "",
            f"- Stale threshold hours: {stale.get('stale_after_hours', 0)}",
            f"- Stale system status events: {stale.get('stale_system_status_event_count', 0)}",
            f"- Latest provider check age hours: {stale.get('latest_provider_check_age_hours', '')}",
            f"- Latest SQLite import age hours: {stale.get('latest_sqlite_import_age_hours', '')}",
            "",
            "## Warnings",
            "",
        ]
    )
    warnings = payload.get("warnings") or []
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None"])
    return "\n".join(lines) + "\n"


def required_tables() -> list[str]:
    return [
        "captures",
        "capture_candidates",
        "candidate_reviews",
        "watchlist_items",
        "entry_plans",
        "opportunity_alerts",
        "alert_outcomes",
        "system_status_events",
        "provider_quality_checks",
        "schema_migrations",
    ]


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])


def scalar_count(connection: sqlite3.Connection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    return int(row[0] if row else 0)


def grouped_count(connection: sqlite3.Connection, table: str, symbol_column: str) -> dict[str, int]:
    rows = connection.execute(
        f"""
        SELECT {symbol_column} AS symbol, COUNT(*) AS count
        FROM {table}
        GROUP BY {symbol_column}
        """
    ).fetchall()
    return {str(row["symbol"] or "").upper(): int(row["count"]) for row in rows}


def outcome_counts_by_symbol(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT oa.symbol, COUNT(ao.alert_id) AS count
        FROM opportunity_alerts oa
        JOIN alert_outcomes ao ON ao.alert_id = oa.alert_id
        GROUP BY oa.symbol
        """
    ).fetchall()
    return {str(row["symbol"] or "").upper(): int(row["count"]) for row in rows}


def latest_review_status_by_symbol(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT ticker, review_status, decision_timestamp
        FROM candidate_reviews
        ORDER BY ticker, decision_timestamp
        """
    ).fetchall()
    result: dict[str, str] = {}
    for row in rows:
        result[str(row["ticker"] or "").upper()] = str(row["review_status"] or "")
    return result


def entry_plan_status_by_symbol(connection: sqlite3.Connection) -> dict[str, str]:
    rows = connection.execute(
        """
        SELECT ticker, plan_complete, updated_at
        FROM entry_plans
        ORDER BY ticker, updated_at
        """
    ).fetchall()
    result: dict[str, str] = {}
    for row in rows:
        result[str(row["ticker"] or "").upper()] = "complete" if int(row["plan_complete"] or 0) else "incomplete"
    return result


def latest_import_age_hours(connection: sqlite3.Connection, generated_at: datetime) -> float | None:
    values: list[str] = []
    for table in [
        "captures",
        "capture_candidates",
        "opportunity_alerts",
        "alert_outcomes",
        "evidence_runs",
        "system_status_events",
        "provider_quality_checks",
        "entry_plans",
        "candidate_reviews",
        "watchlist_items",
    ]:
        if not table_exists(connection, table):
            continue
        columns = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        if "imported_at" not in columns and table != "provider_quality_checks":
            continue
        column = "generated_at" if table == "provider_quality_checks" else "imported_at"
        row = connection.execute(f"SELECT MAX({column}) AS value FROM {table}").fetchone()
        value = str(row["value"] or "") if row else ""
        if value:
            values.append(value)
    ages = [age_hours(value, generated_at) for value in values]
    ages = [value for value in ages if value is not None]
    if not ages:
        return None
    return min(ages)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def age_hours(value: str, generated_at: datetime) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None and generated_at.tzinfo is not None:
        parsed = parsed.replace(tzinfo=generated_at.tzinfo)
    return max(0.0, (generated_at - parsed).total_seconds() / 3600.0)


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def empty_alert_summary() -> dict[str, Any]:
    return {
        "total_alerts": 0,
        "completed": 0,
        "pending": 0,
        "unscorable": 0,
        "by_classification": [],
        "by_alert_type": [],
        "by_symbol": [],
    }


def empty_watchlist_summary() -> dict[str, Any]:
    return {
        "watchlist_count": 0,
        "watchlist_artifact_count": 0,
        "complete_plans": 0,
        "incomplete_plans": 0,
        "missing_entry": 0,
        "missing_stop": 0,
        "missing_target": "unavailable_current_schema",
        "plan_completion_rate_pct": 0.0,
    }


def empty_stale_summary(stale_after_hours: int) -> dict[str, Any]:
    return {
        "stale_after_hours": stale_after_hours,
        "system_status_events": [],
        "stale_system_status_event_count": 0,
        "latest_provider_check_age_hours": None,
        "latest_sqlite_import_age_hours": None,
        "warnings": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate read-only SQLite analytics query-pack reports.")
    parser.add_argument("--db-path", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--stale-after-hours", type=int, default=STALE_AFTER_HOURS)
    args = parser.parse_args(argv)

    payload = build_sqlite_analytics_report(db_path=args.db_path, stale_after_hours=args.stale_after_hours)
    json_path, markdown_path = write_sqlite_analytics_report(payload, output_dir=args.output_dir)
    summary = {
        "overall_status": payload.get("overall_status"),
        "candidate_count": len(payload.get("candidate_evidence_summary", [])),
        "total_alerts": payload.get("alert_performance_sample_summary", {}).get("total_alerts", 0),
        "warnings": payload.get("warnings", []),
        "report_paths": {"json": str(json_path), "markdown": str(markdown_path)},
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
