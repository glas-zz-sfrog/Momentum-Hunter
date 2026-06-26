from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from momentum_hunter.sqlite_store import SQLITE_DB_PATH, connect_database, current_schema_version, normalize_status
from momentum_hunter.sqlite_migration import SQLITE_USER_STATE_IMPORT_LATEST_JSON
from momentum_hunter.user_state_diff import USER_STATE_DIFF_LATEST_JSON


def sqlite_backbone_summary(*, db_path: Path | None = None) -> dict[str, Any]:
    tables = [
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
    with connect_database(db_path) as connection:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
            for table in tables
        }
        return {
            "database_path": str(db_path or SQLITE_DB_PATH),
            "schema_version": current_schema_version(connection),
            "table_counts": counts,
        }


def alert_evidence_summary(*, db_path: Path | None = None) -> dict[str, Any]:
    with connect_database(db_path) as connection:
        rows = connection.execute(
            """
            SELECT status, classification, COUNT(*) AS count
            FROM alert_outcomes
            GROUP BY status, classification
            ORDER BY status, classification
            """
        ).fetchall()
        completed = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count FROM alert_outcomes
                WHERE classification IN ('SUCCESSFUL', 'FAILED', 'NOISE', 'LATE')
                """
            ).fetchone()["count"]
        )
        pending = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count FROM alert_outcomes
                WHERE status LIKE 'PENDING%'
                """
            ).fetchone()["count"]
        )
        unscorable = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count FROM alert_outcomes
                WHERE status = 'UNSCORABLE_OUTCOME' OR classification LIKE 'UNSCORABLE%'
                """
            ).fetchone()["count"]
        )
    return {
        "completed_outcomes": completed,
        "pending_outcomes": pending,
        "unscorable_outcomes": unscorable,
        "classification_counts": [
            {"status": row["status"], "classification": row["classification"], "count": int(row["count"])}
            for row in rows
        ],
    }


def get_alerts_by_symbol(symbol: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    ticker = symbol.strip().upper()
    with connect_database(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM opportunity_alerts
            WHERE symbol = ?
            ORDER BY timestamp, alert_type
            """,
            (ticker,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_outcomes_by_alert_id(alert_id: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    with connect_database(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM alert_outcomes
            WHERE alert_id = ?
            ORDER BY updated_at, alert_id
            """,
            (alert_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_minute_bars_by_symbol(
    symbol: str,
    *,
    db_path: Path | None = None,
    start: str | None = None,
    end: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    ticker = symbol.strip().upper()
    conditions = ["symbol = ?"]
    params: list[object] = [ticker]
    if start:
        conditions.append("timestamp >= ?")
        params.append(start)
    if end:
        conditions.append("timestamp <= ?")
        params.append(end)
    if source:
        conditions.append("source = ?")
        params.append(source)
    with connect_database(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM minute_bars
            WHERE {' AND '.join(conditions)}
            ORDER BY timestamp, source
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_evidence_runs_by_date_range(
    *,
    db_path: Path | None = None,
    start: str | None = None,
    end: str | None = None,
    run_type: str | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[object] = []
    if start:
        conditions.append("generated_at >= ?")
        params.append(start)
    if end:
        conditions.append("generated_at <= ?")
        params.append(end)
    if run_type:
        conditions.append("run_type = ?")
        params.append(run_type)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with connect_database(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM evidence_runs
            {where}
            ORDER BY generated_at, run_type, source_path
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_latest_provider_quality_checks(
    *,
    db_path: Path | None = None,
    symbol: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    params: list[object] = []
    where = ""
    if symbol:
        where = "WHERE symbol = ?"
        params.append(symbol.strip().upper())
    params.append(limit)
    with connect_database(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM provider_quality_checks
            {where}
            ORDER BY generated_at DESC, symbol, provider
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def candidate_history_for_ticker(ticker: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    symbol = ticker.strip().upper()
    with connect_database(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                c.capture_date,
                c.capture_time,
                c.session,
                c.provider,
                c.scanner,
                c.market_regime,
                c.capture_calendar_status,
                c.is_study_eligible,
                cc.ticker,
                cc.rank,
                cc.score,
                cc.price,
                cc.percent_change,
                cc.volume,
                cc.relative_volume,
                cc.market_cap,
                cc.sector,
                cc.industry
            FROM capture_candidates cc
            JOIN captures c ON c.capture_id = cc.capture_id
            WHERE cc.ticker = ?
            ORDER BY c.capture_time, cc.rank
            """,
            (symbol,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_candidate_capture_trail(symbol: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    return candidate_history_for_ticker(symbol, db_path=db_path)


def get_first_latest_capture_for_symbol(symbol: str, *, db_path: Path | None = None) -> dict[str, dict[str, Any] | None]:
    rows = candidate_history_for_ticker(symbol, db_path=db_path)
    if not rows:
        return {"first": None, "latest": None}
    return {"first": rows[0], "latest": rows[-1]}


def get_peak_score_capture_for_symbol(symbol: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    rows = candidate_history_for_ticker(symbol, db_path=db_path)
    if not rows:
        return None
    return max(rows, key=lambda row: ((row.get("score") or -1), str(row.get("capture_time") or "")))


def latest_system_status(
    *,
    db_path: Path | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    params: list[object] = []
    where = ""
    if status:
        where = "WHERE status = ?"
        params.append(normalize_status(status))
    params.append(limit)
    with connect_database(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT event_type, status, occurred_at, summary, recommended_action, source_path
            FROM system_status_events
            {where}
            ORDER BY occurred_at DESC, event_type
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_candidate_reviews_by_symbol(symbol: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    ticker = symbol.strip().upper()
    with connect_database(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM candidate_reviews
            WHERE ticker = ?
            ORDER BY decision_timestamp, capture_date, session, provider, scanner
            """,
            (ticker,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_all_interested_candidates(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    return get_reviews_by_status("interested", db_path=db_path)


def get_all_rejected_candidates(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    return get_reviews_by_status("rejected", db_path=db_path)


def get_reviews_by_status(status: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    with connect_database(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM candidate_reviews
            WHERE review_status = ?
            ORDER BY decision_timestamp, ticker
            """,
            (status,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_watchlist_items(*, db_path: Path | None = None, watchlist_date: str | None = None) -> list[dict[str, Any]]:
    params: list[object] = []
    where = ""
    if watchlist_date:
        where = "WHERE watchlist_date = ?"
        params.append(watchlist_date)
    with connect_database(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM watchlist_items
            {where}
            ORDER BY watchlist_date, ticker
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_complete_entry_plans(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    return get_entry_plans_by_completion(True, db_path=db_path)


def get_incomplete_entry_plans(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    return get_entry_plans_by_completion(False, db_path=db_path)


def get_entry_plans_by_completion(complete: bool, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    with connect_database(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM entry_plans
            WHERE plan_complete = ?
            ORDER BY updated_at, ticker
            """,
            (1 if complete else 0,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_latest_user_state_import_summary(
    *, report_path: Path = SQLITE_USER_STATE_IMPORT_LATEST_JSON
) -> dict[str, Any]:
    if not report_path.exists():
        return {"exists": False, "path": str(report_path)}
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload["exists"] = True
        return payload
    return {"exists": True, "path": str(report_path), "payload_type": type(payload).__name__}


def get_user_state_conflicts(*, report_path: Path = USER_STATE_DIFF_LATEST_JSON) -> dict[str, Any]:
    if not report_path.exists():
        return {"exists": False, "path": str(report_path), "conflicts": 0, "warnings": ["USER_STATE_DIFF_REPORT_MISSING"]}
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"exists": True, "path": str(report_path), "conflicts": 0, "warnings": ["USER_STATE_DIFF_REPORT_MALFORMED"]}
    tables = payload.get("tables", {})
    changed: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []
    if isinstance(tables, dict):
        for table, report in tables.items():
            if not isinstance(report, dict):
                continue
            for item in report.get("changed_values", []) or []:
                changed.append({"table": table, **item})
            for key in report.get("missing_in_sqlite", []) or []:
                missing.append({"table": table, "key": key})
            for key in report.get("extra_in_sqlite", []) or []:
                extra.append({"table": table, "key": key})
    return {
        "exists": True,
        "path": str(report_path),
        "overall_status": payload.get("overall_status", ""),
        "conflicts": int(payload.get("conflicts", 0) or 0),
        "changed_values": changed,
        "missing_in_sqlite": missing,
        "extra_in_sqlite": extra,
        "warnings": payload.get("warnings", []),
    }
