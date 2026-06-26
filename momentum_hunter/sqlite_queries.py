from __future__ import annotations

from pathlib import Path
from typing import Any

from momentum_hunter.sqlite_store import SQLITE_DB_PATH, connect_database, current_schema_version, normalize_status


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
