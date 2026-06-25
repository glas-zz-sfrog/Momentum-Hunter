from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.storage import file_sha256
from momentum_hunter.time_utils import now_central


SQLITE_DB_PATH = DATA_DIR / "momentum-hunter.sqlite3"
SQLITE_SCHEMA_VERSION = 1


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
        (SQLITE_SCHEMA_VERSION, "sqlite_migration_foundation_v1", applied_at),
    )
    connection.commit()


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
    entry_price REAL,
    bid REAL,
    ask REAL,
    spread_percent REAL,
    rvol REAL,
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
    mfe_60m REAL,
    mae_60m REAL,
    target_1_hit INTEGER,
    target_2_hit INTEGER,
    stop_hit INTEGER,
    updated_at TEXT NOT NULL
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
