from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.opportunity_alerts import (
    OPPORTUNITY_ALERTS_PATH,
    OpportunityAlert,
    alert_to_dict,
    is_completed_alert,
    is_pending_alert,
    is_unscorable_alert,
    load_alerts,
)
from momentum_hunter.storage import file_sha256
from momentum_hunter.time_utils import now_central


SQLITE_DB_PATH = DATA_DIR / "momentum-hunter.sqlite3"
SQLITE_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class ProviderQualityImportResult:
    source_path: str
    source_hash: str
    generated_at: str
    rows_seen: int
    rows_inserted: int
    rows_skipped: int
    table_row_count: int
    database_path: str


@dataclass(frozen=True)
class EvidenceImportResult:
    source_path: str
    source_hash: str
    imported_at: str
    alerts_seen: int
    alerts_inserted: int
    alerts_updated: int
    alerts_skipped: int
    alert_table_row_count: int
    source_alert_rows_in_sqlite: int
    outcomes_seen: int
    outcomes_inserted: int
    outcomes_updated: int
    outcomes_skipped: int
    outcome_table_row_count: int
    source_outcome_rows_in_sqlite: int
    pending_outcomes: int
    completed_outcomes: int
    unscorable_outcomes: int
    warnings: list[str]
    database_path: str


def connect_database(path: Path | None = None) -> sqlite3.Connection:
    ensure_app_dirs()
    db_path = path or SQLITE_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    applied_at = now_central().isoformat()
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (1, "sqlite_migration_foundation_v1", applied_at),
    )
    apply_schema_migrations(connection, applied_at=applied_at)
    connection.commit()


def apply_schema_migrations(connection: sqlite3.Connection, *, applied_at: str | None = None) -> None:
    applied_at = applied_at or now_central().isoformat()
    ensure_column(connection, "opportunity_alerts", "previous_state", "TEXT")
    ensure_column(connection, "opportunity_alerts", "reason", "TEXT")
    ensure_column(connection, "opportunity_alerts", "alert_price", "REAL")
    ensure_column(connection, "opportunity_alerts", "volume", "INTEGER")
    ensure_column(connection, "opportunity_alerts", "premarket_volume", "INTEGER")
    ensure_column(connection, "opportunity_alerts", "premarket_percent", "REAL")
    ensure_column(connection, "opportunity_alerts", "rvol_type", "TEXT")
    ensure_column(connection, "opportunity_alerts", "suggested_entry", "REAL")
    ensure_column(connection, "opportunity_alerts", "stop", "REAL")
    ensure_column(connection, "opportunity_alerts", "target_1", "REAL")
    ensure_column(connection, "opportunity_alerts", "target_2", "REAL")
    ensure_column(connection, "opportunity_alerts", "news_catalyst", "TEXT")
    ensure_column(connection, "opportunity_alerts", "market_regime", "TEXT")
    ensure_column(connection, "opportunity_alerts", "event_mode", "INTEGER")
    ensure_column(connection, "opportunity_alerts", "source_report", "TEXT")
    ensure_column(connection, "opportunity_alerts", "engine_version", "TEXT")
    ensure_column(connection, "opportunity_alerts", "source_alerts_path", "TEXT")
    ensure_column(connection, "opportunity_alerts", "source_alerts_hash", "TEXT")
    ensure_column(connection, "opportunity_alerts", "imported_at", "TEXT")
    ensure_column(connection, "opportunity_alerts", "updated_at", "TEXT")

    ensure_column(connection, "alert_outcomes", "mfe_15m", "REAL")
    ensure_column(connection, "alert_outcomes", "mae_15m", "REAL")
    ensure_column(connection, "alert_outcomes", "mfe_30m", "REAL")
    ensure_column(connection, "alert_outcomes", "mae_30m", "REAL")
    ensure_column(connection, "alert_outcomes", "stop_hit_before_target", "INTEGER")
    ensure_column(connection, "alert_outcomes", "evaluation_notes", "TEXT")
    ensure_column(connection, "alert_outcomes", "source_alerts_path", "TEXT")
    ensure_column(connection, "alert_outcomes", "source_alerts_hash", "TEXT")
    ensure_column(connection, "alert_outcomes", "imported_at", "TEXT")
    ensure_column(connection, "alert_outcomes", "source_json", "TEXT")
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (2, "sqlite_evidence_slice_v1", applied_at),
    )


def ensure_column(connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    existing = {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def current_schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None or row["version"] is None:
        return 0
    return int(row["version"])


def import_provider_quality_report(
    report_path: Path = DATA_QUALITY_LATEST_JSON,
    *,
    db_path: Path | None = None,
) -> ProviderQualityImportResult:
    source = report_path
    payload = json.loads(source.read_text(encoding="utf-8"))
    report = payload.get("report", payload)
    if not isinstance(report, dict):
        raise ValueError(f"Provider quality report has no report object: {source}")
    generated_at = str(report.get("generated_at", ""))
    source_hash = file_sha256(source)
    symbol_rows = report.get("symbol_rows", [])
    if not isinstance(symbol_rows, list):
        symbol_rows = []

    with connect_database(db_path) as connection:
        initialize_schema(connection)
        inserted = 0
        skipped = 0
        for item in symbol_rows:
            if not isinstance(item, dict):
                continue
            row = provider_quality_row(item, generated_at=generated_at, source_path=source, source_hash=source_hash)
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO provider_quality_checks(
                    check_id,
                    generated_at,
                    symbol,
                    provider,
                    usable_market_tape,
                    last_price,
                    bid,
                    ask,
                    spread_percent,
                    relative_volume,
                    fields_returned,
                    missing_fields,
                    warnings,
                    source_report_path,
                    source_report_hash
                )
                VALUES (
                    :check_id,
                    :generated_at,
                    :symbol,
                    :provider,
                    :usable_market_tape,
                    :last_price,
                    :bid,
                    :ask,
                    :spread_percent,
                    :relative_volume,
                    :fields_returned,
                    :missing_fields,
                    :warnings,
                    :source_report_path,
                    :source_report_hash
                )
                """,
                row,
            )
            if cursor.rowcount:
                inserted += 1
            else:
                skipped += 1
        connection.commit()
        table_count = provider_quality_count(connection)
    return ProviderQualityImportResult(
        source_path=str(source),
        source_hash=source_hash,
        generated_at=generated_at,
        rows_seen=len(symbol_rows),
        rows_inserted=inserted,
        rows_skipped=skipped,
        table_row_count=table_count,
        database_path=str(db_path or SQLITE_DB_PATH),
    )


def import_opportunity_alerts(
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    *,
    db_path: Path | None = None,
) -> EvidenceImportResult:
    source = alerts_path
    imported_at = now_central().isoformat()
    warnings: list[str] = []
    if not source.exists():
        warnings.append(f"SOURCE_ALERTS_FILE_MISSING:{source}")
        with connect_database(db_path) as connection:
            initialize_schema(connection)
            return EvidenceImportResult(
                source_path=str(source),
                source_hash="",
                imported_at=imported_at,
                alerts_seen=0,
                alerts_inserted=0,
                alerts_updated=0,
                alerts_skipped=0,
                alert_table_row_count=opportunity_alert_count(connection),
                source_alert_rows_in_sqlite=0,
                outcomes_seen=0,
                outcomes_inserted=0,
                outcomes_updated=0,
                outcomes_skipped=0,
                outcome_table_row_count=alert_outcome_count(connection),
                source_outcome_rows_in_sqlite=0,
                pending_outcomes=0,
                completed_outcomes=0,
                unscorable_outcomes=0,
                warnings=warnings,
                database_path=str(db_path or SQLITE_DB_PATH),
            )

    source_hash = file_sha256(source)
    alerts = load_alerts(source)
    seen_alert_ids: set[str] = set()
    alert_inserted = 0
    alert_updated = 0
    alert_skipped = 0
    outcome_inserted = 0
    outcome_updated = 0
    outcome_skipped = 0
    outcomes_seen = 0

    with connect_database(db_path) as connection:
        initialize_schema(connection)
        for alert in alerts:
            if not alert.alert_id:
                warnings.append(f"ALERT_MISSING_ID:{alert.symbol}:{alert.timestamp}:{alert.alert_type}")
                continue
            if alert.alert_id in seen_alert_ids:
                warnings.append(f"DUPLICATE_ALERT_ID_IN_SOURCE:{alert.alert_id}")
                continue
            seen_alert_ids.add(alert.alert_id)

            alert_row = opportunity_alert_row(
                alert,
                source_path=source,
                source_hash=source_hash,
                imported_at=imported_at,
            )
            alert_action = upsert_row(
                connection,
                "opportunity_alerts",
                "alert_id",
                alert_row,
                compare_exclude={"imported_at", "updated_at"},
            )
            if alert_action == "inserted":
                alert_inserted += 1
            elif alert_action == "updated":
                alert_updated += 1
            else:
                alert_skipped += 1

            outcome_row = alert_outcome_row(
                alert,
                source_path=source,
                source_hash=source_hash,
                imported_at=imported_at,
            )
            outcomes_seen += 1
            outcome_action = upsert_row(
                connection,
                "alert_outcomes",
                "alert_id",
                outcome_row,
                compare_exclude={"imported_at", "updated_at"},
            )
            if outcome_action == "inserted":
                outcome_inserted += 1
            elif outcome_action == "updated":
                outcome_updated += 1
            else:
                outcome_skipped += 1
        connection.commit()
        alert_table_count = opportunity_alert_count(connection)
        outcome_table_count = alert_outcome_count(connection)
        source_alert_rows = count_rows_for_source(connection, "opportunity_alerts", source)
        source_outcome_rows = count_rows_for_source(connection, "alert_outcomes", source)

    pending = len([alert for alert in alerts if is_pending_alert(alert)])
    completed = len([alert for alert in alerts if is_completed_alert(alert)])
    unscorable = len([alert for alert in alerts if is_unscorable_alert(alert)])
    if source_alert_rows != len(seen_alert_ids):
        warnings.append(f"SQLITE_ALERT_SOURCE_COUNT_MISMATCH:{source_alert_rows}!={len(seen_alert_ids)}")
    if source_outcome_rows != outcomes_seen:
        warnings.append(f"SQLITE_OUTCOME_SOURCE_COUNT_MISMATCH:{source_outcome_rows}!={outcomes_seen}")

    return EvidenceImportResult(
        source_path=str(source),
        source_hash=source_hash,
        imported_at=imported_at,
        alerts_seen=len(alerts),
        alerts_inserted=alert_inserted,
        alerts_updated=alert_updated,
        alerts_skipped=alert_skipped,
        alert_table_row_count=alert_table_count,
        source_alert_rows_in_sqlite=source_alert_rows,
        outcomes_seen=outcomes_seen,
        outcomes_inserted=outcome_inserted,
        outcomes_updated=outcome_updated,
        outcomes_skipped=outcome_skipped,
        outcome_table_row_count=outcome_table_count,
        source_outcome_rows_in_sqlite=source_outcome_rows,
        pending_outcomes=pending,
        completed_outcomes=completed,
        unscorable_outcomes=unscorable,
        warnings=dedupe(warnings),
        database_path=str(db_path or SQLITE_DB_PATH),
    )


def opportunity_alert_row(
    alert: OpportunityAlert,
    *,
    source_path: Path,
    source_hash: str,
    imported_at: str,
) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "symbol": alert.symbol,
        "alert_type": alert.alert_type,
        "timestamp": alert.timestamp,
        "current_state": alert.current_state,
        "previous_state": alert.previous_state,
        "reason": alert.reason,
        "entry_price": optional_float(alert.price),
        "alert_price": optional_float(alert.price),
        "bid": optional_float(alert.bid),
        "ask": optional_float(alert.ask),
        "spread_percent": optional_float(alert.spread_percent),
        "volume": optional_int(alert.volume),
        "premarket_volume": optional_int(alert.premarket_volume),
        "premarket_percent": optional_float(alert.premarket_percent),
        "rvol": optional_float(alert.rvol),
        "rvol_type": alert.rvol_type,
        "suggested_entry": optional_float(alert.suggested_entry),
        "stop": optional_float(alert.stop),
        "target_1": optional_float(alert.target_1),
        "target_2": optional_float(alert.target_2),
        "news_catalyst": alert.news_catalyst,
        "market_regime": alert.market_regime,
        "event_mode": int(bool(alert.event_mode)),
        "source_report": alert.source_report,
        "engine_version": alert.engine_version,
        "source_alerts_path": str(source_path),
        "source_alerts_hash": source_hash,
        "imported_at": imported_at,
        "updated_at": imported_at,
        "source_json": json.dumps(alert_to_dict(alert), sort_keys=True),
    }


def alert_outcome_row(
    alert: OpportunityAlert,
    *,
    source_path: Path,
    source_hash: str,
    imported_at: str,
) -> dict[str, Any]:
    outcome = alert.outcome
    return {
        "alert_id": alert.alert_id,
        "status": outcome.status,
        "classification": outcome.classification,
        "return_5m": optional_float(outcome.five_minute_return_pct),
        "return_15m": optional_float(outcome.fifteen_minute_return_pct),
        "return_30m": optional_float(outcome.thirty_minute_return_pct),
        "return_60m": optional_float(outcome.sixty_minute_return_pct),
        "mfe_15m": optional_float(outcome.mfe_15m_pct),
        "mae_15m": optional_float(outcome.mae_15m_pct),
        "mfe_30m": optional_float(outcome.mfe_30m_pct),
        "mae_30m": optional_float(outcome.mae_30m_pct),
        "mfe_60m": optional_float(outcome.mfe_60m_pct),
        "mae_60m": optional_float(outcome.mae_60m_pct),
        "target_1_hit": optional_bool(outcome.target_1_hit),
        "target_2_hit": optional_bool(outcome.target_2_hit),
        "stop_hit": optional_bool(outcome.stop_hit),
        "stop_hit_before_target": optional_bool(outcome.stop_hit_before_target),
        "evaluation_notes": json.dumps(outcome.evaluation_notes, sort_keys=True),
        "source_alerts_path": str(source_path),
        "source_alerts_hash": source_hash,
        "imported_at": imported_at,
        "updated_at": imported_at,
        "source_json": json.dumps(alert_to_dict(alert).get("outcome", {}), sort_keys=True),
    }


def upsert_row(
    connection: sqlite3.Connection,
    table: str,
    primary_key: str,
    row: dict[str, Any],
    *,
    compare_exclude: set[str] | None = None,
) -> str:
    compare_exclude = compare_exclude or set()
    existing = connection.execute(
        f"SELECT * FROM {table} WHERE {primary_key} = ?",
        (row[primary_key],),
    ).fetchone()
    if existing is None:
        insert_row(connection, table, row)
        return "inserted"
    comparable_keys = [key for key in row if key not in compare_exclude]
    if all(existing[key] == row[key] for key in comparable_keys):
        return "skipped"
    update_row(connection, table, primary_key, row)
    return "updated"


def insert_row(connection: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    columns = list(row)
    placeholders = ", ".join(f":{column}" for column in columns)
    column_sql = ", ".join(columns)
    connection.execute(f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})", row)


def update_row(connection: sqlite3.Connection, table: str, primary_key: str, row: dict[str, Any]) -> None:
    assignments = ", ".join(f"{column} = :{column}" for column in row if column != primary_key)
    connection.execute(f"UPDATE {table} SET {assignments} WHERE {primary_key} = :{primary_key}", row)


def provider_quality_row(item: dict[str, Any], *, generated_at: str, source_path: Path, source_hash: str) -> dict[str, Any]:
    symbol = str(item.get("symbol", "")).strip().upper()
    provider = str(item.get("best_provider") or "combined").strip() or "combined"
    check_id = deterministic_id("provider_quality", generated_at, symbol, provider, source_hash)
    return {
        "check_id": check_id,
        "generated_at": generated_at,
        "symbol": symbol,
        "provider": provider,
        "usable_market_tape": 1 if bool(item.get("usable_market_tape", False)) else 0,
        "last_price": optional_float(item.get("last_price")),
        "bid": optional_float(item.get("bid")),
        "ask": optional_float(item.get("ask")),
        "spread_percent": optional_float(item.get("spread_percent")),
        "relative_volume": optional_float(item.get("relative_volume")),
        "fields_returned": json.dumps(item.get("fields_returned", []), sort_keys=True),
        "missing_fields": json.dumps(item.get("missing_fields", []), sort_keys=True),
        "warnings": json.dumps(item.get("warnings", []), sort_keys=True),
        "source_report_path": str(source_path),
        "source_report_hash": source_hash,
    }


def read_provider_quality_checks(
    connection: sqlite3.Connection,
    *,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    if symbol:
        rows = connection.execute(
            """
            SELECT * FROM provider_quality_checks
            WHERE symbol = ?
            ORDER BY generated_at, provider
            """,
            (symbol.strip().upper(),),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT * FROM provider_quality_checks
            ORDER BY generated_at, symbol, provider
            """
        ).fetchall()
    return [dict(row) for row in rows]


def provider_quality_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM provider_quality_checks").fetchone()
    return int(row["count"] if row else 0)


def read_opportunity_alerts(
    connection: sqlite3.Connection,
    *,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    if symbol:
        rows = connection.execute(
            """
            SELECT * FROM opportunity_alerts
            WHERE symbol = ?
            ORDER BY timestamp, alert_type
            """,
            (symbol.strip().upper(),),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT * FROM opportunity_alerts
            ORDER BY timestamp, symbol, alert_type
            """
        ).fetchall()
    return [dict(row) for row in rows]


def read_alert_outcomes(
    connection: sqlite3.Connection,
    *,
    classification: str | None = None,
) -> list[dict[str, Any]]:
    if classification:
        rows = connection.execute(
            """
            SELECT * FROM alert_outcomes
            WHERE classification = ?
            ORDER BY alert_id
            """,
            (classification,),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT * FROM alert_outcomes
            ORDER BY alert_id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def opportunity_alert_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM opportunity_alerts").fetchone()
    return int(row["count"] if row else 0)


def alert_outcome_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM alert_outcomes").fetchone()
    return int(row["count"] if row else 0)


def count_rows_for_source(connection: sqlite3.Connection, table: str, source_path: Path) -> int:
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE source_alerts_path = ?",
        (str(source_path),),
    ).fetchone()
    return int(row["count"] if row else 0)


def deterministic_id(*parts: object) -> str:
    joined = "|".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def optional_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def optional_bool(value: object) -> int | None:
    if value is None:
        return None
    return int(bool(value))


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY,
    capture_date TEXT NOT NULL,
    capture_time TEXT NOT NULL,
    session TEXT NOT NULL,
    provider TEXT NOT NULL,
    scanner TEXT NOT NULL,
    source_path TEXT NOT NULL UNIQUE,
    source_hash TEXT,
    capture_version TEXT,
    is_quarantined INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_captures_date_session ON captures(capture_date, session);

CREATE TABLE IF NOT EXISTS capture_candidates (
    candidate_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    rank INTEGER,
    score INTEGER,
    price REAL,
    percent_change REAL,
    volume INTEGER,
    relative_volume REAL,
    market_cap INTEGER,
    sector TEXT,
    industry TEXT,
    raw_json TEXT,
    UNIQUE(capture_id, ticker, rank)
);

CREATE INDEX IF NOT EXISTS idx_capture_candidates_ticker_capture ON capture_candidates(ticker, capture_id);

CREATE TABLE IF NOT EXISTS candidate_reviews (
    review_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    review_status TEXT NOT NULL,
    decision_timestamp TEXT NOT NULL,
    decision_note TEXT,
    review_context_state TEXT,
    delayed_review INTEGER NOT NULL DEFAULT 0,
    UNIQUE(capture_id, ticker)
);

CREATE TABLE IF NOT EXISTS watchlist_items (
    watchlist_item_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    watchlist_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_review_id TEXT,
    UNIQUE(capture_id, ticker, watchlist_date)
);

CREATE TABLE IF NOT EXISTS entry_plans (
    entry_plan_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    trigger_condition TEXT,
    stop_price REAL,
    thesis TEXT,
    invalidation TEXT,
    max_loss TEXT,
    position_size_idea TEXT,
    planned_hold_time TEXT,
    notes TEXT,
    plan_complete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(capture_id, ticker)
);

CREATE TABLE IF NOT EXISTS opportunity_alerts (
    alert_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    current_state TEXT,
    previous_state TEXT,
    reason TEXT,
    entry_price REAL,
    alert_price REAL,
    bid REAL,
    ask REAL,
    spread_percent REAL,
    volume INTEGER,
    premarket_volume INTEGER,
    premarket_percent REAL,
    rvol REAL,
    rvol_type TEXT,
    suggested_entry REAL,
    stop REAL,
    target_1 REAL,
    target_2 REAL,
    news_catalyst TEXT,
    market_regime TEXT,
    event_mode INTEGER,
    source_report TEXT,
    engine_version TEXT,
    source_alerts_path TEXT,
    source_alerts_hash TEXT,
    imported_at TEXT,
    updated_at TEXT,
    source_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_opportunity_alerts_symbol_timestamp ON opportunity_alerts(symbol, timestamp);

CREATE TABLE IF NOT EXISTS alert_outcomes (
    alert_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    classification TEXT NOT NULL,
    return_5m REAL,
    return_15m REAL,
    return_30m REAL,
    return_60m REAL,
    mfe_15m REAL,
    mae_15m REAL,
    mfe_30m REAL,
    mae_30m REAL,
    mfe_60m REAL,
    mae_60m REAL,
    target_1_hit INTEGER,
    target_2_hit INTEGER,
    stop_hit INTEGER,
    stop_hit_before_target INTEGER,
    evaluation_notes TEXT,
    source_alerts_path TEXT,
    source_alerts_hash TEXT,
    imported_at TEXT,
    updated_at TEXT NOT NULL,
    source_json TEXT
);

CREATE TABLE IF NOT EXISTS minute_bars (
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    source TEXT,
    PRIMARY KEY(symbol, timestamp, source)
);

CREATE TABLE IF NOT EXISTS evidence_runs (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    source_path TEXT,
    source_hash TEXT,
    summary_json TEXT,
    UNIQUE(run_type, generated_at, source_hash)
);

CREATE TABLE IF NOT EXISTS evidence_metrics (
    metric_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    metric_text TEXT,
    UNIQUE(run_id, metric_name)
);

CREATE TABLE IF NOT EXISTS system_status_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    source_path TEXT,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_system_status_events_type_time ON system_status_events(event_type, occurred_at);

CREATE TABLE IF NOT EXISTS provider_quality_checks (
    check_id TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    provider TEXT NOT NULL,
    usable_market_tape INTEGER NOT NULL,
    last_price REAL,
    bid REAL,
    ask REAL,
    spread_percent REAL,
    relative_volume REAL,
    fields_returned TEXT,
    missing_fields TEXT,
    warnings TEXT,
    source_report_path TEXT,
    source_report_hash TEXT,
    UNIQUE(generated_at, symbol, provider, source_report_hash)
);

CREATE INDEX IF NOT EXISTS idx_provider_quality_symbol_time ON provider_quality_checks(symbol, generated_at);
"""
