from __future__ import annotations

import hashlib
import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import (
    ALERT_OUTCOME_UPDATE_STATUS_PATH,
    OPPORTUNITY_MINUTE_BARS_PATH,
    MinutePriceBar,
    minute_bar_from_dict,
)
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
    parse_datetime,
)
from momentum_hunter.entry_plans import ENTRY_PLANS_PATH, entry_plan_from_dict, entry_plan_warnings
from momentum_hunter.review import REVIEW_DECISIONS_PATH, review_decision_from_dict
from momentum_hunter.storage import ANALYSIS_CSV, CAPTURES_DIR, file_sha256
from momentum_hunter.time_utils import now_central


SQLITE_DB_PATH = DATA_DIR / "momentum-hunter.sqlite3"
SQLITE_SCHEMA_VERSION = 7


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


@dataclass(frozen=True)
class MinuteBarsImportResult:
    source_path: str
    source_hash: str
    imported_at: str
    symbols_seen: int
    bars_seen: int
    valid_bars: int
    invalid_bars: int
    duplicate_bars: int
    bars_inserted: int
    bars_updated: int
    bars_skipped: int
    table_row_count: int
    source_rows_in_sqlite: int
    symbol_counts: dict[str, int]
    first_timestamps: dict[str, str]
    latest_timestamps: dict[str, str]
    warnings: list[str]
    database_path: str


@dataclass(frozen=True)
class EvidenceRunsImportResult:
    source_paths: list[str]
    imported_at: str
    runs_seen: int
    runs_inserted: int
    runs_updated: int
    runs_skipped: int
    runs_removed_stale: int
    metrics_seen: int
    metrics_inserted: int
    metrics_updated: int
    metrics_skipped: int
    metrics_removed_stale: int
    evidence_run_table_row_count: int
    evidence_metric_table_row_count: int
    run_types: dict[str, int]
    warnings: list[str]
    database_path: str


@dataclass(frozen=True)
class SystemStatusImportResult:
    source_paths: list[str]
    imported_at: str
    events_seen: int
    events_inserted: int
    events_updated: int
    events_skipped: int
    events_removed_stale: int
    table_row_count: int
    status_counts: dict[str, int]
    event_type_counts: dict[str, int]
    warnings: list[str]
    database_path: str


@dataclass(frozen=True)
class CaptureIndexImportResult:
    source_path: str
    source_hash: str
    imported_at: str
    analysis_rows_seen: int
    captures_seen: int
    captures_inserted: int
    captures_updated: int
    captures_skipped: int
    candidates_seen: int
    candidates_inserted: int
    candidates_updated: int
    candidates_skipped: int
    capture_table_row_count: int
    candidate_table_row_count: int
    source_capture_rows_in_sqlite: int
    source_candidate_rows_in_sqlite: int
    warnings: list[str]
    database_path: str


@dataclass(frozen=True)
class UserStateImportResult:
    source_paths: list[str]
    imported_at: str
    review_records_seen: int
    review_records_inserted: int
    review_records_updated: int
    review_records_skipped: int
    watchlist_files_seen: int
    watchlist_records_seen: int
    watchlist_records_inserted: int
    watchlist_records_updated: int
    watchlist_records_skipped: int
    entry_plan_records_seen: int
    entry_plan_records_inserted: int
    entry_plan_records_updated: int
    entry_plan_records_skipped: int
    complete_entry_plans: int
    incomplete_entry_plans: int
    candidate_review_table_row_count: int
    watchlist_item_table_row_count: int
    entry_plan_table_row_count: int
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

    ensure_column(connection, "minute_bars", "granularity", "TEXT")
    ensure_column(connection, "minute_bars", "source_file_path", "TEXT")
    ensure_column(connection, "minute_bars", "source_file_hash", "TEXT")
    ensure_column(connection, "minute_bars", "imported_at", "TEXT")
    ensure_column(connection, "minute_bars", "updated_at", "TEXT")
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (3, "sqlite_minute_bars_slice_v1", applied_at),
    )

    ensure_column(connection, "evidence_runs", "status", "TEXT")
    ensure_column(connection, "evidence_runs", "started_at", "TEXT")
    ensure_column(connection, "evidence_runs", "ended_at", "TEXT")
    ensure_column(connection, "evidence_runs", "target_count", "INTEGER")
    ensure_column(connection, "evidence_runs", "alert_count", "INTEGER")
    ensure_column(connection, "evidence_runs", "completed_count", "INTEGER")
    ensure_column(connection, "evidence_runs", "pending_count", "INTEGER")
    ensure_column(connection, "evidence_runs", "unscorable_count", "INTEGER")
    ensure_column(connection, "evidence_runs", "warning_count", "INTEGER")
    ensure_column(connection, "evidence_runs", "report_paths_json", "TEXT")
    ensure_column(connection, "evidence_runs", "imported_at", "TEXT")
    ensure_column(connection, "evidence_runs", "updated_at", "TEXT")
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (4, "sqlite_evidence_runs_slice_v1", applied_at),
    )
    ensure_column(connection, "system_status_events", "source_module", "TEXT")
    ensure_column(connection, "system_status_events", "source_hash", "TEXT")
    ensure_column(connection, "system_status_events", "summary", "TEXT")
    ensure_column(connection, "system_status_events", "recommended_action", "TEXT")
    ensure_column(connection, "system_status_events", "imported_at", "TEXT")
    ensure_column(connection, "system_status_events", "updated_at", "TEXT")
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (5, "sqlite_system_status_slice_v1", applied_at),
    )
    ensure_column(connection, "captures", "capture_session", "TEXT")
    ensure_column(connection, "captures", "capture_calendar_status", "TEXT")
    ensure_column(connection, "captures", "is_market_open_day", "INTEGER")
    ensure_column(connection, "captures", "is_study_eligible", "INTEGER")
    ensure_column(connection, "captures", "next_market_session_date", "TEXT")
    ensure_column(connection, "captures", "scheduling_policy_version", "TEXT")
    ensure_column(connection, "captures", "mode", "TEXT")
    ensure_column(connection, "captures", "market_regime", "TEXT")
    ensure_column(connection, "captures", "source_csv_path", "TEXT")
    ensure_column(connection, "captures", "source_csv_hash", "TEXT")
    ensure_column(connection, "captures", "imported_at", "TEXT")
    ensure_column(connection, "captures", "updated_at", "TEXT")

    ensure_column(connection, "capture_candidates", "company", "TEXT")
    ensure_column(connection, "capture_candidates", "freshness", "TEXT")
    ensure_column(connection, "capture_candidates", "freshness_score", "INTEGER")
    ensure_column(connection, "capture_candidates", "article_count", "INTEGER")
    ensure_column(connection, "capture_candidates", "source_csv_path", "TEXT")
    ensure_column(connection, "capture_candidates", "source_csv_hash", "TEXT")
    ensure_column(connection, "capture_candidates", "imported_at", "TEXT")
    ensure_column(connection, "capture_candidates", "updated_at", "TEXT")
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (6, "sqlite_capture_candidate_index_v1", applied_at),
    )

    for column, column_type in {
        "identity_key": "TEXT",
        "capture_date": "TEXT",
        "session": "TEXT",
        "provider": "TEXT",
        "scanner": "TEXT",
        "review_delay_minutes": "INTEGER",
        "capture_status": "TEXT",
        "capture_quarantined_at": "TEXT",
        "capture_quarantine_reason": "TEXT",
        "source_path": "TEXT",
        "source_hash": "TEXT",
        "source_json": "TEXT",
        "imported_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        ensure_column(connection, "candidate_reviews", column, column_type)

    for column, column_type in {
        "company": "TEXT",
        "score": "INTEGER",
        "price": "REAL",
        "source_path": "TEXT",
        "source_hash": "TEXT",
        "source_json": "TEXT",
        "imported_at": "TEXT",
        "updated_at": "TEXT",
    }.items():
        ensure_column(connection, "watchlist_items", column, column_type)

    for column, column_type in {
        "identity_key": "TEXT",
        "capture_date": "TEXT",
        "session": "TEXT",
        "provider": "TEXT",
        "scanner": "TEXT",
        "stop_text": "TEXT",
        "warnings_json": "TEXT",
        "source_path": "TEXT",
        "source_hash": "TEXT",
        "source_json": "TEXT",
        "imported_at": "TEXT",
    }.items():
        ensure_column(connection, "entry_plans", column, column_type)
    connection.execute(
        """
        INSERT OR IGNORE INTO schema_migrations(version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (7, "sqlite_user_state_safety_cage_v1", applied_at),
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


def import_minute_bars(
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    *,
    db_path: Path | None = None,
) -> MinuteBarsImportResult:
    source = minute_bars_path
    imported_at = now_central().isoformat()
    if not source.exists():
        warnings = [f"SOURCE_MINUTE_BARS_FILE_MISSING:{source}"]
        with connect_database(db_path) as connection:
            initialize_schema(connection)
            return MinuteBarsImportResult(
                source_path=str(source),
                source_hash="",
                imported_at=imported_at,
                symbols_seen=0,
                bars_seen=0,
                valid_bars=0,
                invalid_bars=0,
                duplicate_bars=0,
                bars_inserted=0,
                bars_updated=0,
                bars_skipped=0,
                table_row_count=minute_bar_count(connection),
                source_rows_in_sqlite=0,
                symbol_counts={},
                first_timestamps={},
                latest_timestamps={},
                warnings=warnings,
                database_path=str(db_path or SQLITE_DB_PATH),
            )

    source_hash = file_sha256(source)
    parsed = parse_minute_bar_source(source)
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    duplicate_count = 0
    for bar in parsed["bars"]:
        row = minute_bar_row(
            bar,
            source_path=source,
            source_hash=source_hash,
            imported_at=imported_at,
        )
        key = (row["symbol"], row["timestamp"], row["source"])
        if key in rows_by_key:
            duplicate_count += 1
        rows_by_key[key] = row

    inserted = 0
    updated = 0
    skipped = 0
    with connect_database(db_path) as connection:
        initialize_schema(connection)
        for row in rows_by_key.values():
            action = upsert_row_by_key(
                connection,
                "minute_bars",
                ("symbol", "timestamp", "source"),
                row,
                compare_exclude={"imported_at", "updated_at"},
            )
            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1
            else:
                skipped += 1
        connection.commit()
        table_count = minute_bar_count(connection)
        source_count = count_minute_bars_for_source(connection, source)

    symbol_counts, first_timestamps, latest_timestamps = summarize_minute_bar_rows(rows_by_key.values())
    warnings = list(parsed["warnings"])
    if duplicate_count:
        warnings.append(f"DUPLICATE_MINUTE_BARS_IN_SOURCE:{duplicate_count}")
    if source_count != len(rows_by_key):
        warnings.append(f"SQLITE_MINUTE_BAR_SOURCE_COUNT_MISMATCH:{source_count}!={len(rows_by_key)}")

    return MinuteBarsImportResult(
        source_path=str(source),
        source_hash=source_hash,
        imported_at=imported_at,
        symbols_seen=int(parsed["symbols_seen"]),
        bars_seen=int(parsed["bars_seen"]),
        valid_bars=len(parsed["bars"]),
        invalid_bars=int(parsed["invalid_bars"]),
        duplicate_bars=duplicate_count,
        bars_inserted=inserted,
        bars_updated=updated,
        bars_skipped=skipped,
        table_row_count=table_count,
        source_rows_in_sqlite=source_count,
        symbol_counts=symbol_counts,
        first_timestamps=first_timestamps,
        latest_timestamps=latest_timestamps,
        warnings=dedupe(warnings),
        database_path=str(db_path or SQLITE_DB_PATH),
    )


def import_evidence_runs(
    *,
    db_path: Path | None = None,
    source_paths: list[Path] | None = None,
    reports_dir: Path | None = None,
) -> EvidenceRunsImportResult:
    imported_at = now_central().isoformat()
    sources = source_paths if source_paths is not None else discover_evidence_run_sources(reports_dir)
    warnings: list[str] = []
    parsed_runs: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    seen_run_ids: set[str] = set()
    current_run_ids_by_source: dict[str, set[str]] = {}
    for source in sources:
        parsed = parse_evidence_run_source(source, imported_at=imported_at)
        if parsed is None:
            warnings.append(f"EVIDENCE_SOURCE_MISSING_OR_INVALID:{source}")
            continue
        run_row, metrics, source_warnings = parsed
        warnings.extend(source_warnings)
        run_id = str(run_row["run_id"])
        source_key = str(source)
        current_run_ids_by_source.setdefault(source_key, set())
        if run_id in seen_run_ids:
            warnings.append(f"DUPLICATE_EVIDENCE_RUN_ID_IN_SOURCE_SET:{run_id}")
            continue
        seen_run_ids.add(run_id)
        current_run_ids_by_source[source_key].add(run_id)
        parsed_runs.append((run_row, metrics))

    runs_inserted = 0
    runs_updated = 0
    runs_skipped = 0
    runs_removed_stale = 0
    metrics_inserted = 0
    metrics_updated = 0
    metrics_skipped = 0
    metrics_removed_stale = 0
    with connect_database(db_path) as connection:
        initialize_schema(connection)
        for source_key, current_run_ids in current_run_ids_by_source.items():
            existing_rows = connection.execute(
                "SELECT run_id FROM evidence_runs WHERE source_path = ?",
                (source_key,),
            ).fetchall()
            stale_ids = [str(row["run_id"]) for row in existing_rows if str(row["run_id"]) not in current_run_ids]
            if stale_ids:
                placeholders = ",".join("?" for _item in stale_ids)
                deleted_metrics = connection.execute(
                    f"DELETE FROM evidence_metrics WHERE run_id IN ({placeholders})",
                    stale_ids,
                ).rowcount
                connection.execute(
                    f"DELETE FROM evidence_runs WHERE run_id IN ({placeholders})",
                    stale_ids,
                )
                runs_removed_stale += len(stale_ids)
                metrics_removed_stale += max(0, int(deleted_metrics or 0))
        for run_row, metrics in parsed_runs:
            action = upsert_row(
                connection,
                "evidence_runs",
                "run_id",
                run_row,
                compare_exclude={"imported_at", "updated_at"},
            )
            if action == "inserted":
                runs_inserted += 1
            elif action == "updated":
                runs_updated += 1
            else:
                runs_skipped += 1
            for metric in metrics:
                metric_action = upsert_row(
                    connection,
                    "evidence_metrics",
                    "metric_id",
                    metric,
                    compare_exclude=set(),
                )
                if metric_action == "inserted":
                    metrics_inserted += 1
                elif metric_action == "updated":
                    metrics_updated += 1
                else:
                    metrics_skipped += 1
        connection.commit()
        run_count = evidence_run_count(connection)
        metric_count = evidence_metric_count(connection)

    run_types: dict[str, int] = {}
    for run_row, _metrics in parsed_runs:
        run_type = str(run_row.get("run_type") or "unknown")
        run_types[run_type] = run_types.get(run_type, 0) + 1
    return EvidenceRunsImportResult(
        source_paths=[str(path) for path in sources],
        imported_at=imported_at,
        runs_seen=len(parsed_runs),
        runs_inserted=runs_inserted,
        runs_updated=runs_updated,
        runs_skipped=runs_skipped,
        runs_removed_stale=runs_removed_stale,
        metrics_seen=sum(len(metrics) for _run, metrics in parsed_runs),
        metrics_inserted=metrics_inserted,
        metrics_updated=metrics_updated,
        metrics_skipped=metrics_skipped,
        metrics_removed_stale=metrics_removed_stale,
        evidence_run_table_row_count=run_count,
        evidence_metric_table_row_count=metric_count,
        run_types=dict(sorted(run_types.items())),
        warnings=dedupe(warnings),
        database_path=str(db_path or SQLITE_DB_PATH),
    )


def import_system_status_events(
    *,
    db_path: Path | None = None,
    source_paths: list[Path] | None = None,
    reports_dir: Path | None = None,
) -> SystemStatusImportResult:
    imported_at = now_central().isoformat()
    sources = source_paths if source_paths is not None else discover_system_status_sources(reports_dir)
    warnings: list[str] = []
    parsed_events: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    current_event_ids_by_source: dict[str, set[str]] = {}
    for source in sources:
        events, source_warnings = parse_system_status_source(source, imported_at=imported_at)
        warnings.extend(source_warnings)
        source_key = str(source)
        current_event_ids_by_source.setdefault(source_key, set())
        for event in events:
            event_id = str(event["event_id"])
            if event_id in seen_event_ids:
                warnings.append(f"DUPLICATE_SYSTEM_STATUS_EVENT_ID_IN_SOURCE_SET:{event_id}")
                continue
            seen_event_ids.add(event_id)
            current_event_ids_by_source[source_key].add(event_id)
            parsed_events.append(event)

    inserted = 0
    updated = 0
    skipped = 0
    removed_stale = 0
    with connect_database(db_path) as connection:
        initialize_schema(connection)
        for source_key, current_event_ids in current_event_ids_by_source.items():
            existing_rows = connection.execute(
                "SELECT event_id FROM system_status_events WHERE source_path = ?",
                (source_key,),
            ).fetchall()
            stale_ids = [str(row["event_id"]) for row in existing_rows if str(row["event_id"]) not in current_event_ids]
            if stale_ids:
                placeholders = ",".join("?" for _item in stale_ids)
                connection.execute(
                    f"DELETE FROM system_status_events WHERE event_id IN ({placeholders})",
                    stale_ids,
                )
                removed_stale += len(stale_ids)
        for event in parsed_events:
            action = upsert_row(
                connection,
                "system_status_events",
                "event_id",
                event,
                compare_exclude={"imported_at", "updated_at"},
            )
            if action == "inserted":
                inserted += 1
            elif action == "updated":
                updated += 1
            else:
                skipped += 1
        connection.commit()
        table_count = system_status_event_count(connection)

    status_counts: dict[str, int] = {}
    event_type_counts: dict[str, int] = {}
    for event in parsed_events:
        status = str(event.get("status") or "UNKNOWN")
        event_type = str(event.get("event_type") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
    return SystemStatusImportResult(
        source_paths=[str(path) for path in sources],
        imported_at=imported_at,
        events_seen=len(parsed_events),
        events_inserted=inserted,
        events_updated=updated,
        events_skipped=skipped,
        events_removed_stale=removed_stale,
        table_row_count=table_count,
        status_counts=dict(sorted(status_counts.items())),
        event_type_counts=dict(sorted(event_type_counts.items())),
        warnings=dedupe(warnings),
        database_path=str(db_path or SQLITE_DB_PATH),
    )


def discover_system_status_sources(reports_dir: Path | None = None) -> list[Path]:
    reports_dir = reports_dir or DATA_DIR / "reports"
    sources = [
        DATA_DIR / "active-monitor-status.json",
        DATA_DIR / "evidence-autopilot-status.json",
        ALERT_OUTCOME_UPDATE_STATUS_PATH,
        reports_dir / "system-readiness-latest.json",
        reports_dir / "data-quality-latest.json",
    ]
    sources.extend(sorted(reports_dir.glob("market-tape-health-*.json")))
    return dedupe_paths([path for path in sources if path.exists()])


def parse_system_status_source(source: Path, *, imported_at: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not source.exists():
        return [], [f"SYSTEM_STATUS_SOURCE_MISSING:{source}"]
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [], [f"SYSTEM_STATUS_SOURCE_READ_FAILED:{source}:{type(exc).__name__}"]
    if not isinstance(payload, dict):
        return [], [f"SYSTEM_STATUS_SOURCE_NOT_OBJECT:{source}"]

    source_hash = file_sha256(source)
    source_module = str(payload.get("engine_version") or system_source_module_from_name(source.name))
    body = evidence_payload_body(payload)
    generated_at = evidence_generated_at(body, payload) or imported_at
    name = source.name.lower()
    warnings: list[str] = []

    if name == "system-readiness-latest.json":
        events = system_readiness_events(
            body,
            source=source,
            source_hash=source_hash,
            source_module=source_module,
            occurred_at=generated_at,
            imported_at=imported_at,
            original_payload=payload,
        )
    elif name == "data-quality-latest.json":
        events = [
            data_quality_status_event(
                body,
                source=source,
                source_hash=source_hash,
                source_module=source_module,
                occurred_at=generated_at,
                imported_at=imported_at,
                original_payload=payload,
            )
        ]
    elif name.startswith("market-tape-health-"):
        events = [
            market_tape_status_event(
                body,
                source=source,
                source_hash=source_hash,
                source_module=source_module,
                occurred_at=generated_at,
                imported_at=imported_at,
                original_payload=payload,
            )
        ]
    elif name == "alert-outcome-update-status.json":
        events = [
            outcome_update_status_event(
                body,
                source=source,
                source_hash=source_hash,
                source_module=source_module,
                occurred_at=generated_at,
                imported_at=imported_at,
                original_payload=payload,
            )
        ]
    else:
        events = [
            generic_status_event(
                body,
                source=source,
                source_hash=source_hash,
                source_module=source_module,
                occurred_at=generated_at,
                imported_at=imported_at,
                original_payload=payload,
            )
        ]
    if not events:
        warnings.append(f"SYSTEM_STATUS_SOURCE_PRODUCED_NO_EVENTS:{source}")
    return events, warnings


def system_readiness_events(
    body: dict[str, Any],
    *,
    source: Path,
    source_hash: str,
    source_module: str,
    occurred_at: str,
    imported_at: str,
    original_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    overall_status = str(first_present(body, "overall_status", "status", "state") or "UNKNOWN")
    issues = body.get("issues_requiring_attention", [])
    if not isinstance(issues, list):
        issues = []
    warnings = evidence_warning_list(body)
    events = [
        make_system_status_event(
            event_type="system_readiness:overall",
            status=overall_status,
            occurred_at=occurred_at,
            source=source,
            source_hash=source_hash,
            source_module=source_module,
            summary=f"Overall system readiness: {overall_status}",
            recommended_action="Review issues requiring attention." if issues else "No readiness action required.",
            detail={"report": body, "source_payload": original_payload, "warnings": warnings},
            imported_at=imported_at,
        )
    ]
    sections = body.get("sections", [])
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_name = str(section.get("name") or "unknown")
            section_status = str(section.get("status") or "UNKNOWN")
            events.append(
                make_system_status_event(
                    event_type=f"system_readiness:{normalize_event_token(section_name)}",
                    status=section_status,
                    occurred_at=occurred_at,
                    source=source,
                    source_hash=source_hash,
                    source_module=source_module,
                    summary=str(section.get("explanation") or f"{section_name}: {section_status}"),
                    recommended_action=str(section.get("recommended_next_action") or ""),
                    detail={"section": section, "source_payload": original_payload},
                    imported_at=imported_at,
                )
            )
    return events


def data_quality_status_event(
    body: dict[str, Any],
    *,
    source: Path,
    source_hash: str,
    source_module: str,
    occurred_at: str,
    imported_at: str,
    original_payload: dict[str, Any],
) -> dict[str, Any]:
    symbols = body.get("symbols", [])
    total = len(symbols) if isinstance(symbols, list) else optional_int(body.get("symbol_count")) or 0
    usable = optional_int(first_present(body, "usable_market_tape_count", "usable_symbol_count")) or 0
    missing = optional_int(first_present(body, "missing_market_tape_count", "missing_symbol_count")) or max(total - usable, 0)
    warnings = evidence_warning_list(body)
    if total and usable == 0:
        status = "FAILED"
    elif missing or warnings:
        status = "WARNING"
    else:
        status = "READY"
    return make_system_status_event(
        event_type="data_quality:market_tape",
        status=status,
        occurred_at=occurred_at,
        source=source,
        source_hash=source_hash,
        source_module=source_module,
        summary=f"Market tape quality: {usable} usable, {missing} missing, {total} total.",
        recommended_action="Repair missing market tape before relying on alerts." if missing else "No market tape action required.",
        detail={"report": body, "source_payload": original_payload},
        imported_at=imported_at,
    )


def market_tape_status_event(
    body: dict[str, Any],
    *,
    source: Path,
    source_hash: str,
    source_module: str,
    occurred_at: str,
    imported_at: str,
    original_payload: dict[str, Any],
) -> dict[str, Any]:
    symbols = body.get("symbols", [])
    total = len(symbols) if isinstance(symbols, list) else optional_int(body.get("symbol_count")) or 0
    usable = optional_int(first_present(body, "usable_symbol_count", "usable_market_tape_count")) or 0
    missing = optional_int(first_present(body, "missing_symbol_count", "missing_market_tape_count")) or max(total - usable, 0)
    warnings = evidence_warning_list(body)
    if total and usable == 0:
        status = "FAILED"
    elif missing or warnings:
        status = "WARNING"
    else:
        status = "READY"
    return make_system_status_event(
        event_type="market_tape_health",
        status=status,
        occurred_at=occurred_at,
        source=source,
        source_hash=source_hash,
        source_module=source_module,
        summary=f"Market tape health: {usable} usable, {missing} missing, {total} total.",
        recommended_action="Investigate providers with missing tape." if missing else "Market tape health passed for checked symbols.",
        detail={"report": body, "source_payload": original_payload},
        imported_at=imported_at,
    )


def outcome_update_status_event(
    body: dict[str, Any],
    *,
    source: Path,
    source_hash: str,
    source_module: str,
    occurred_at: str,
    imported_at: str,
    original_payload: dict[str, Any],
) -> dict[str, Any]:
    warnings = evidence_warning_list(body)
    updated = optional_int(first_present(body, "alerts_updated", "outcomes_updated", "completed_outcomes")) or 0
    pending = optional_int(first_present(body, "pending_alerts", "pending_outcomes")) or 0
    status = "WARNING" if warnings else "READY"
    return make_system_status_event(
        event_type="alert_outcome_update",
        status=status,
        occurred_at=occurred_at,
        source=source,
        source_hash=source_hash,
        source_module=source_module,
        summary=f"Alert outcome update: {updated} updated, {pending} pending.",
        recommended_action="Review outcome update warnings." if warnings else "No outcome update action required.",
        detail={"status": body, "source_payload": original_payload},
        imported_at=imported_at,
    )


def generic_status_event(
    body: dict[str, Any],
    *,
    source: Path,
    source_hash: str,
    source_module: str,
    occurred_at: str,
    imported_at: str,
    original_payload: dict[str, Any],
) -> dict[str, Any]:
    status = status_from_state_and_warnings(
        str(first_present(body, "state", "status", "latest_run_state") or ""),
        evidence_warning_list(body),
        first_present(body, "last_error", "error", "error_message"),
    )
    event_type = normalize_event_token(source.stem)
    return make_system_status_event(
        event_type=event_type,
        status=status,
        occurred_at=occurred_at,
        source=source,
        source_hash=source_hash,
        source_module=source_module,
        summary=generic_status_summary(body, source),
        recommended_action=generic_recommended_action(status, body),
        detail={"status": body, "source_payload": original_payload},
        imported_at=imported_at,
    )


def make_system_status_event(
    *,
    event_type: str,
    status: str,
    occurred_at: str,
    source: Path,
    source_hash: str,
    source_module: str,
    summary: str,
    recommended_action: str,
    detail: dict[str, Any],
    imported_at: str,
) -> dict[str, Any]:
    clean_type = normalize_event_token(event_type)
    clean_status = normalize_status(status)
    event_id = deterministic_id("system_status_event", clean_type, occurred_at, source)
    return {
        "event_id": event_id,
        "event_type": clean_type,
        "status": clean_status,
        "occurred_at": occurred_at,
        "source_path": str(source),
        "source_module": source_module,
        "source_hash": source_hash,
        "summary": summary,
        "recommended_action": recommended_action,
        "details_json": json.dumps(detail, sort_keys=True),
        "imported_at": imported_at,
        "updated_at": imported_at,
    }


def status_from_state_and_warnings(state: str, warnings: list[str], error: object) -> str:
    if error:
        return "FAILED"
    normalized = normalize_status(state)
    if warnings and normalized in {"READY", "INFO", "UNKNOWN"}:
        return "WARNING"
    return normalized


def normalize_status(status: str) -> str:
    value = str(status or "").strip().upper().replace("-", "_").replace(" ", "_")
    if value in {"READY", "WARNING", "FAILED", "UNKNOWN", "INFO"}:
        return value
    if value in {"OK", "SUCCESS", "SUCCESSFUL", "COMPLETE", "COMPLETED", "IDLE", "PASSED", "PASS"}:
        return "READY"
    if value in {"WARN", "DEGRADED", "COLLECTING", "DIAGNOSTIC"}:
        return "WARNING"
    if value in {"FAIL", "ERROR", "ERRORED", "FAILED_RUN", "BLOCKED"}:
        return "FAILED"
    if value in {"RUNNING", "ACTIVE", "STARTED", "IN_PROGRESS"}:
        return "INFO"
    return "UNKNOWN" if not value else value


def generic_status_summary(body: dict[str, Any], source: Path) -> str:
    for key in ("summary", "message", "latest_run_state", "state", "status"):
        value = body.get(key)
        if value:
            return f"{source.name}: {value}"
    return f"{source.name}: status captured"


def generic_recommended_action(status: str, body: dict[str, Any]) -> str:
    for key in ("recommended_action", "next_action", "recommended_next_action"):
        value = body.get(key)
        if value:
            return str(value)
    if status == "FAILED":
        return "Review the source status file for the recorded error."
    if status == "WARNING":
        return "Review warnings before relying on this subsystem."
    return "No action required."


def system_source_module_from_name(name: str) -> str:
    normalized = name.lower()
    if normalized == "active-monitor-status.json":
        return "active_monitor_status"
    if normalized == "evidence-autopilot-status.json":
        return "evidence_autopilot_status"
    if normalized == "alert-outcome-update-status.json":
        return "alert_outcome_update_status"
    if normalized == "system-readiness-latest.json":
        return "system_readiness_v1"
    if normalized == "data-quality-latest.json":
        return "data_quality_audit_v1"
    if normalized.startswith("market-tape-health-"):
        return "market_tape_health_v1"
    return normalize_event_token(Path(name).stem)


def normalize_event_token(value: str) -> str:
    token = str(value or "").strip().lower()
    result = []
    previous_was_separator = False
    for character in token:
        if character.isalnum():
            result.append(character)
            previous_was_separator = False
        elif character in {":", "_"}:
            if not previous_was_separator:
                result.append(character)
                previous_was_separator = True
        else:
            if not previous_was_separator:
                result.append("_")
                previous_was_separator = True
    normalized = "".join(result).strip("_:")
    return normalized or "unknown"


def import_capture_candidate_index(
    analysis_path: Path = ANALYSIS_CSV,
    *,
    db_path: Path | None = None,
    captures_dir: Path = CAPTURES_DIR,
) -> CaptureIndexImportResult:
    imported_at = now_central().isoformat()
    source = analysis_path
    warnings: list[str] = []
    if not source.exists():
        return CaptureIndexImportResult(
            source_path=str(source),
            source_hash="",
            imported_at=imported_at,
            analysis_rows_seen=0,
            captures_seen=0,
            captures_inserted=0,
            captures_updated=0,
            captures_skipped=0,
            candidates_seen=0,
            candidates_inserted=0,
            candidates_updated=0,
            candidates_skipped=0,
            capture_table_row_count=0,
            candidate_table_row_count=0,
            source_capture_rows_in_sqlite=0,
            source_candidate_rows_in_sqlite=0,
            warnings=[f"ANALYSIS_CAPTURE_SOURCE_MISSING:{source}"],
            database_path=str(db_path or SQLITE_DB_PATH),
        )
    source_hash = file_sha256(source)
    rows, read_warnings = read_analysis_capture_rows(source)
    warnings.extend(read_warnings)
    capture_rows_by_id: dict[str, dict[str, Any]] = {}
    candidate_rows_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        capture_row = capture_index_row(
            row,
            source_path=source,
            source_hash=source_hash,
            captures_dir=captures_dir,
            imported_at=imported_at,
        )
        capture_id = str(capture_row["capture_id"])
        if capture_id not in capture_rows_by_id:
            capture_rows_by_id[capture_id] = capture_row
        candidate_row = capture_candidate_index_row(
            row,
            capture_id=capture_id,
            source_path=source,
            source_hash=source_hash,
            imported_at=imported_at,
            fallback_rank=index,
        )
        candidate_id = str(candidate_row["candidate_id"])
        if candidate_id in candidate_rows_by_id:
            warnings.append(f"DUPLICATE_CAPTURE_CANDIDATE_ROW:{candidate_id}")
        candidate_rows_by_id[candidate_id] = candidate_row

    for capture in capture_rows_by_id.values():
        if capture.get("source_hash") in {None, ""}:
            warnings.append(f"RAW_CAPTURE_JSON_MISSING:{capture.get('source_path', '')}")

    captures_inserted = 0
    captures_updated = 0
    captures_skipped = 0
    candidates_inserted = 0
    candidates_updated = 0
    candidates_skipped = 0
    with connect_database(db_path) as connection:
        initialize_schema(connection)
        for capture in capture_rows_by_id.values():
            action = upsert_row(
                connection,
                "captures",
                "capture_id",
                capture,
                compare_exclude={"imported_at", "updated_at"},
            )
            if action == "inserted":
                captures_inserted += 1
            elif action == "updated":
                captures_updated += 1
            else:
                captures_skipped += 1
        for candidate in candidate_rows_by_id.values():
            action = upsert_row(
                connection,
                "capture_candidates",
                "candidate_id",
                candidate,
                compare_exclude={"imported_at", "updated_at"},
            )
            if action == "inserted":
                candidates_inserted += 1
            elif action == "updated":
                candidates_updated += 1
            else:
                candidates_skipped += 1
        connection.commit()
        capture_count = capture_index_count(connection)
        candidate_count = capture_candidate_index_count(connection)
        source_capture_count = count_capture_index_for_source(connection, source)
        source_candidate_count = count_capture_candidate_index_for_source(connection, source)

    if source_capture_count != len(capture_rows_by_id):
        warnings.append(f"SQLITE_CAPTURE_SOURCE_COUNT_MISMATCH:{source_capture_count}!={len(capture_rows_by_id)}")
    if source_candidate_count != len(candidate_rows_by_id):
        warnings.append(f"SQLITE_CAPTURE_CANDIDATE_SOURCE_COUNT_MISMATCH:{source_candidate_count}!={len(candidate_rows_by_id)}")
    return CaptureIndexImportResult(
        source_path=str(source),
        source_hash=source_hash,
        imported_at=imported_at,
        analysis_rows_seen=len(rows),
        captures_seen=len(capture_rows_by_id),
        captures_inserted=captures_inserted,
        captures_updated=captures_updated,
        captures_skipped=captures_skipped,
        candidates_seen=len(candidate_rows_by_id),
        candidates_inserted=candidates_inserted,
        candidates_updated=candidates_updated,
        candidates_skipped=candidates_skipped,
        capture_table_row_count=capture_count,
        candidate_table_row_count=candidate_count,
        source_capture_rows_in_sqlite=source_capture_count,
        source_candidate_rows_in_sqlite=source_candidate_count,
        warnings=dedupe(warnings),
        database_path=str(db_path or SQLITE_DB_PATH),
    )


def import_user_state(
    *,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    data_dir: Path = DATA_DIR,
    db_path: Path | None = None,
) -> UserStateImportResult:
    imported_at = now_central().isoformat()
    warnings: list[str] = []
    source_paths: list[str] = []
    review_inserted = review_updated = review_skipped = 0
    watchlist_inserted = watchlist_updated = watchlist_skipped = 0
    entry_inserted = entry_updated = entry_skipped = 0

    review_records, review_warnings = load_review_source_records(review_decisions_path)
    warnings.extend(review_warnings)
    if review_decisions_path.exists():
        source_paths.append(str(review_decisions_path))

    entry_records, entry_warnings = load_entry_plan_source_records(entry_plans_path)
    warnings.extend(entry_warnings)
    if entry_plans_path.exists():
        source_paths.append(str(entry_plans_path))

    watchlist_records: list[dict[str, Any]] = []
    watchlist_files = sorted(data_dir.glob("watchlist-*.json"))
    for path in watchlist_files:
        source_paths.append(str(path))
        records, file_warnings = load_watchlist_source_records(path)
        watchlist_records.extend(records)
        warnings.extend(file_warnings)

    with connect_database(db_path) as connection:
        initialize_schema(connection)
        for record in review_records:
            action = upsert_row_by_key(
                connection,
                "candidate_reviews",
                ("capture_id", "ticker"),
                candidate_review_row(record, imported_at=imported_at),
                compare_exclude={"imported_at", "updated_at"},
            )
            review_inserted += 1 if action == "inserted" else 0
            review_updated += 1 if action == "updated" else 0
            review_skipped += 1 if action == "skipped" else 0
        for record in watchlist_records:
            action = upsert_row_by_key(
                connection,
                "watchlist_items",
                ("capture_id", "ticker", "watchlist_date"),
                watchlist_item_row(record, imported_at=imported_at),
                compare_exclude={"imported_at", "updated_at"},
            )
            watchlist_inserted += 1 if action == "inserted" else 0
            watchlist_updated += 1 if action == "updated" else 0
            watchlist_skipped += 1 if action == "skipped" else 0
        for record in entry_records:
            action = upsert_row_by_key(
                connection,
                "entry_plans",
                ("capture_id", "ticker"),
                entry_plan_row(record, imported_at=imported_at),
                compare_exclude={"imported_at", "updated_at"},
            )
            entry_inserted += 1 if action == "inserted" else 0
            entry_updated += 1 if action == "updated" else 0
            entry_skipped += 1 if action == "skipped" else 0
        connection.commit()
        review_count = table_count(connection, "candidate_reviews")
        watchlist_count = table_count(connection, "watchlist_items")
        entry_count = table_count(connection, "entry_plans")

    complete_plans = sum(1 for record in entry_records if record["plan"].plan_complete)
    incomplete_plans = len(entry_records) - complete_plans
    return UserStateImportResult(
        source_paths=source_paths,
        imported_at=imported_at,
        review_records_seen=len(review_records),
        review_records_inserted=review_inserted,
        review_records_updated=review_updated,
        review_records_skipped=review_skipped,
        watchlist_files_seen=len(watchlist_files),
        watchlist_records_seen=len(watchlist_records),
        watchlist_records_inserted=watchlist_inserted,
        watchlist_records_updated=watchlist_updated,
        watchlist_records_skipped=watchlist_skipped,
        entry_plan_records_seen=len(entry_records),
        entry_plan_records_inserted=entry_inserted,
        entry_plan_records_updated=entry_updated,
        entry_plan_records_skipped=entry_skipped,
        complete_entry_plans=complete_plans,
        incomplete_entry_plans=incomplete_plans,
        candidate_review_table_row_count=review_count,
        watchlist_item_table_row_count=watchlist_count,
        entry_plan_table_row_count=entry_count,
        warnings=dedupe(warnings),
        database_path=str(db_path or SQLITE_DB_PATH),
    )


def load_review_source_records(source: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not source.exists():
        return [], [f"REVIEW_DECISIONS_SOURCE_MISSING:{source}"]
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"REVIEW_DECISIONS_SOURCE_UNREADABLE:{type(exc).__name__}:{source}"]
    raw_decisions = payload.get("decisions", payload if isinstance(payload, dict) else {})
    if not isinstance(raw_decisions, dict):
        return [], [f"REVIEW_DECISIONS_SOURCE_MALFORMED:{source}"]
    source_hash = file_sha256(source)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, item in raw_decisions.items():
        if not isinstance(item, dict) or not item.get("identity"):
            warnings.append(f"MALFORMED_REVIEW_RECORD:{key}")
            continue
        try:
            decision = review_decision_from_dict(item)
        except (KeyError, TypeError, ValueError) as exc:
            warnings.append(f"MALFORMED_REVIEW_RECORD:{key}:{type(exc).__name__}")
            continue
        if decision.identity.key in seen:
            warnings.append(f"DUPLICATE_REVIEW_IDENTITY:{decision.identity.key}")
            continue
        seen.add(decision.identity.key)
        records.append({"key": str(key), "decision": decision, "raw": item, "source_path": source, "source_hash": source_hash})
    return records, warnings


def load_entry_plan_source_records(source: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not source.exists():
        return [], [f"ENTRY_PLANS_SOURCE_MISSING:{source}"]
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"ENTRY_PLANS_SOURCE_UNREADABLE:{type(exc).__name__}:{source}"]
    raw_plans = payload.get("plans", payload if isinstance(payload, dict) else {})
    if not isinstance(raw_plans, dict):
        return [], [f"ENTRY_PLANS_SOURCE_MALFORMED:{source}"]
    source_hash = file_sha256(source)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key, item in raw_plans.items():
        if not isinstance(item, dict) or not item.get("identity"):
            warnings.append(f"MALFORMED_ENTRY_PLAN_RECORD:{key}")
            continue
        try:
            plan = entry_plan_from_dict(item)
        except (KeyError, TypeError, ValueError) as exc:
            warnings.append(f"MALFORMED_ENTRY_PLAN_RECORD:{key}:{type(exc).__name__}")
            continue
        if plan.identity.key in seen:
            warnings.append(f"DUPLICATE_ENTRY_PLAN_IDENTITY:{plan.identity.key}")
            continue
        seen.add(plan.identity.key)
        records.append({"key": str(key), "plan": plan, "raw": item, "source_path": source, "source_hash": source_hash})
    return records, warnings


def load_watchlist_source_records(source: Path) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"WATCHLIST_SOURCE_UNREADABLE:{type(exc).__name__}:{source}"]
    if not isinstance(payload, list):
        return [], [f"WATCHLIST_SOURCE_MALFORMED:{source}"]
    watchlist_date = watchlist_date_from_path(source)
    source_hash = file_sha256(source)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            warnings.append(f"MALFORMED_WATCHLIST_RECORD:{source.name}:{index}")
            continue
        ticker = str(item.get("ticker", "")).strip().upper()
        if not ticker:
            warnings.append(f"WATCHLIST_RECORD_MISSING_TICKER:{source.name}:{index}")
            continue
        key = f"{watchlist_date}|{ticker}"
        if key in seen:
            warnings.append(f"DUPLICATE_WATCHLIST_ITEM:{key}")
            continue
        seen.add(key)
        records.append({"watchlist_date": watchlist_date, "ticker": ticker, "raw": item, "source_path": source, "source_hash": source_hash})
    return records, warnings


def candidate_review_row(record: dict[str, Any], *, imported_at: str) -> dict[str, Any]:
    decision = record["decision"]
    identity = decision.identity
    raw = record["raw"]
    return {
        "review_id": deterministic_id("candidate_review", identity.key),
        "capture_id": identity.capture_id,
        "ticker": identity.ticker.upper(),
        "review_status": decision.review_status.value,
        "decision_timestamp": decision.decision_timestamp.isoformat() if decision.decision_timestamp else "",
        "decision_note": decision.decision_note,
        "review_context_state": decision.review_context_state,
        "delayed_review": optional_bool(decision.delayed_review) or 0,
        "identity_key": identity.key,
        "capture_date": identity.capture_date,
        "session": identity.session,
        "provider": identity.provider,
        "scanner": identity.scanner,
        "review_delay_minutes": optional_int(decision.review_delay_minutes),
        "capture_status": decision.capture_status,
        "capture_quarantined_at": decision.capture_quarantined_at,
        "capture_quarantine_reason": decision.capture_quarantine_reason,
        "source_path": str(record["source_path"]),
        "source_hash": record["source_hash"],
        "source_json": json.dumps(raw, sort_keys=True),
        "imported_at": imported_at,
        "updated_at": imported_at,
    }


def entry_plan_row(record: dict[str, Any], *, imported_at: str) -> dict[str, Any]:
    plan = record["plan"]
    identity = plan.identity
    warnings = entry_plan_warnings(plan)
    return {
        "entry_plan_id": deterministic_id("entry_plan", identity.key),
        "capture_id": identity.capture_id,
        "ticker": identity.ticker.upper(),
        "trigger_condition": plan.trigger,
        "stop_price": optional_float(plan.stop),
        "thesis": plan.thesis,
        "invalidation": plan.invalidation,
        "max_loss": plan.max_loss,
        "position_size_idea": plan.position_size,
        "planned_hold_time": plan.planned_hold_time,
        "notes": plan.notes,
        "plan_complete": optional_bool(plan.plan_complete) or 0,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else imported_at,
        "identity_key": identity.key,
        "capture_date": identity.capture_date,
        "session": identity.session,
        "provider": identity.provider,
        "scanner": identity.scanner,
        "stop_text": plan.stop,
        "warnings_json": json.dumps(warnings, sort_keys=True),
        "source_path": str(record["source_path"]),
        "source_hash": record["source_hash"],
        "source_json": json.dumps(record["raw"], sort_keys=True),
        "imported_at": imported_at,
    }


def watchlist_item_row(record: dict[str, Any], *, imported_at: str) -> dict[str, Any]:
    raw = record["raw"]
    watchlist_date = record["watchlist_date"]
    ticker = record["ticker"]
    capture_id = str(raw.get("capture_id") or f"watchlist:{watchlist_date}")
    return {
        "watchlist_item_id": deterministic_id("watchlist_item", watchlist_date, ticker, str(record["source_path"])),
        "capture_id": capture_id,
        "ticker": ticker,
        "watchlist_date": watchlist_date,
        "created_at": str(raw.get("saved_at") or ""),
        "source_review_id": str(raw.get("source_review_id", "")),
        "company": str(raw.get("company", "")),
        "score": optional_int(raw.get("score")),
        "price": optional_float(raw.get("price")),
        "source_path": str(record["source_path"]),
        "source_hash": record["source_hash"],
        "source_json": json.dumps(raw, sort_keys=True),
        "imported_at": imported_at,
        "updated_at": imported_at,
    }


def watchlist_date_from_path(path: Path) -> str:
    name = path.stem
    prefix = "watchlist-"
    return name[len(prefix) :] if name.startswith(prefix) else ""


def table_count(connection: sqlite3.Connection, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
    return int(row["count"] if row else 0)


def read_analysis_capture_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    warnings: list[str] = []
    try:
        with path.open("r", newline="", encoding="utf-8") as file:
            rows = [dict(row) for row in csv.DictReader(file)]
    except OSError as exc:
        return [], [f"ANALYSIS_CAPTURE_SOURCE_READ_FAILED:{type(exc).__name__}"]
    for index, row in enumerate(rows, start=1):
        if not row.get("capture_time"):
            warnings.append(f"ANALYSIS_CAPTURE_ROW_MISSING_CAPTURE_TIME:{index}")
        if not row.get("ticker"):
            warnings.append(f"ANALYSIS_CAPTURE_ROW_MISSING_TICKER:{index}")
    return rows, warnings


def capture_index_row(
    row: dict[str, str],
    *,
    source_path: Path,
    source_hash: str,
    captures_dir: Path,
    imported_at: str,
) -> dict[str, Any]:
    capture_date = str(row.get("capture_date") or "")
    session = str(row.get("session") or "")
    provider = str(row.get("provider") or "")
    scanner = str(row.get("scanner") or "")
    capture_time = str(row.get("capture_time") or "")
    capture_id = deterministic_id("capture", capture_date, capture_time, session, provider, scanner)
    raw_path = captures_dir / capture_date / f"{session}.json" if capture_date and session else source_path
    raw_exists = raw_path.exists()
    raw_hash = file_sha256(raw_path) if raw_exists else ""
    return {
        "capture_id": capture_id,
        "capture_date": capture_date,
        "capture_time": capture_time,
        "session": session,
        "provider": provider,
        "scanner": scanner,
        "source_path": str(raw_path if raw_exists else source_path.with_name(f"{source_path.name}#{capture_id}")),
        "source_hash": raw_hash,
        "capture_version": "",
        "is_quarantined": 0,
        "capture_session": str(row.get("capture_session") or session),
        "capture_calendar_status": str(row.get("capture_calendar_status") or ""),
        "is_market_open_day": optional_bool(text_to_bool(row.get("is_market_open_day"))),
        "is_study_eligible": optional_bool(text_to_bool(row.get("is_study_eligible"))),
        "next_market_session_date": str(row.get("next_market_session_date") or ""),
        "scheduling_policy_version": str(row.get("scheduling_policy_version") or ""),
        "mode": str(row.get("mode") or ""),
        "market_regime": str(row.get("market_regime") or ""),
        "source_csv_path": str(source_path),
        "source_csv_hash": source_hash,
        "imported_at": imported_at,
        "updated_at": imported_at,
    }


def capture_candidate_index_row(
    row: dict[str, str],
    *,
    capture_id: str,
    source_path: Path,
    source_hash: str,
    imported_at: str,
    fallback_rank: int,
) -> dict[str, Any]:
    ticker = str(row.get("ticker") or "").strip().upper()
    rank = optional_int(row.get("rank")) or fallback_rank
    candidate_id = deterministic_id("capture_candidate", capture_id, ticker, rank)
    return {
        "candidate_id": candidate_id,
        "capture_id": capture_id,
        "ticker": ticker,
        "rank": rank,
        "score": optional_int(row.get("score")),
        "price": optional_float(row.get("price")),
        "percent_change": optional_float(row.get("percent_change")),
        "volume": optional_int(row.get("volume")),
        "relative_volume": optional_float(row.get("relative_volume")),
        "market_cap": optional_int(row.get("market_cap")),
        "sector": str(row.get("sector") or ""),
        "industry": str(row.get("industry") or ""),
        "raw_json": json.dumps(row, sort_keys=True),
        "company": str(row.get("company") or ""),
        "freshness": str(row.get("freshness") or ""),
        "freshness_score": optional_int(row.get("freshness_score")),
        "article_count": optional_int(row.get("article_count")),
        "source_csv_path": str(source_path),
        "source_csv_hash": source_hash,
        "imported_at": imported_at,
        "updated_at": imported_at,
    }


def text_to_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def discover_evidence_run_sources(reports_dir: Path | None = None) -> list[Path]:
    reports_dir = reports_dir or DATA_DIR / "reports"
    sources = [
        DATA_DIR / "evidence-autopilot-status.json",
        ALERT_OUTCOME_UPDATE_STATUS_PATH,
        reports_dir / "evidence-autopilot-latest.json",
    ]
    for pattern in [
        "evidence-health-report-*.json",
        "reliability-report-*.json",
        "alert-performance-report-*.json",
    ]:
        sources.extend(sorted(reports_dir.glob(pattern)))
    return dedupe_paths([path for path in sources if path.exists()])


def parse_evidence_run_source(
    source: Path,
    *,
    imported_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]] | None:
    if not source.exists():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    source_hash = file_sha256(source)
    run_type = evidence_run_type_for_source(source, payload)
    body = evidence_payload_body(payload)
    generated_at = evidence_generated_at(body, payload)
    if not generated_at:
        generated_at = imported_at
    status = evidence_status(run_type, body)
    warnings = evidence_warning_list(body)
    report_paths = evidence_report_paths(body)
    run_id = deterministic_id("evidence_run", run_type, generated_at, source)
    row = {
        "run_id": run_id,
        "run_type": run_type,
        "generated_at": generated_at,
        "source_path": str(source),
        "source_hash": source_hash,
        "summary_json": json.dumps(payload, sort_keys=True),
        "status": status,
        "started_at": first_text(body, "started_at", "latest_run_started_at"),
        "ended_at": first_text(body, "completed_at", "latest_run_completed_at", "updated_at"),
        "target_count": optional_int(first_present(body, "target_count", "targets_checked")),
        "alert_count": optional_int(first_present(body, "total_alerts", "alert_count", "tracked_alert_count", "alerts_generated")),
        "completed_count": optional_int(first_present(body, "completed_alerts", "completed_alert_count", "completed_outcomes", "completed_outcome_count", "alerts_completed")),
        "pending_count": optional_int(first_present(body, "pending_alerts", "pending_alert_count")),
        "unscorable_count": optional_int(first_present(body, "unscorable_alerts", "unscorable_alert_count")),
        "warning_count": optional_int(first_present(body, "warning_count")) if first_present(body, "warning_count") is not None else len(warnings),
        "report_paths_json": json.dumps(report_paths, sort_keys=True),
        "imported_at": imported_at,
        "updated_at": imported_at,
    }
    metrics = evidence_metrics_for_run(run_id, body)
    return row, metrics, []


def evidence_run_type_for_source(source: Path, payload: dict[str, Any]) -> str:
    name = source.name.lower()
    engine = str(payload.get("engine_version", "")).lower()
    if name == "evidence-autopilot-status.json":
        return "evidence_autopilot_status"
    if name == "alert-outcome-update-status.json":
        return "alert_outcome_update_status"
    if name == "evidence-autopilot-latest.json" or "evidence_autopilot_reliability" in engine:
        return "evidence_autopilot_reliability"
    if name.startswith("evidence-health-report-"):
        return "evidence_health"
    if name.startswith("reliability-report-"):
        return "evidence_reliability"
    if name.startswith("alert-performance-report-"):
        return "alert_performance"
    return "evidence_report"


def evidence_payload_body(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("report", "status"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def evidence_generated_at(body: dict[str, Any], payload: dict[str, Any]) -> str:
    return str(
        first_present(body, "generated_at", "completed_at", "updated_at", "started_at")
        or first_present(payload, "generated_at", "updated_at")
        or ""
    )


def evidence_status(run_type: str, body: dict[str, Any]) -> str:
    if body.get("state"):
        return str(body.get("state"))
    if body.get("latest_run_state"):
        return str(body.get("latest_run_state"))
    gate = body.get("evidence_gate")
    if isinstance(gate, dict) and gate.get("evidence_status"):
        return str(gate.get("evidence_status"))
    if body.get("measurable_edge_status"):
        return str(body.get("measurable_edge_status"))
    warnings = evidence_warning_list(body)
    if run_type.endswith("status") and not body:
        return "UNKNOWN"
    return "WARNING" if warnings else "READY"


def evidence_warning_list(body: dict[str, Any]) -> list[str]:
    warnings = body.get("warnings", [])
    if isinstance(warnings, list):
        return [str(item) for item in warnings if str(item)]
    return []


def evidence_report_paths(body: dict[str, Any]) -> dict[str, str]:
    result = {}
    for key, value in body.items():
        if key.endswith("_path") and value:
            result[key] = str(value)
    return result


def evidence_metrics_for_run(run_id: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = []
    for name, value in flatten_metric_values(body):
        metric_value: float | None = None
        metric_text: str | None = None
        if isinstance(value, bool):
            metric_value = 1.0 if value else 0.0
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            metric_value = float(value)
        elif isinstance(value, str):
            metric_text = value
        elif isinstance(value, list):
            metric_value = float(len(value))
        else:
            continue
        metrics.append(
            {
                "metric_id": deterministic_id("evidence_metric", run_id, name),
                "run_id": run_id,
                "metric_name": name,
                "metric_value": metric_value,
                "metric_text": metric_text,
            }
        )
    return metrics


def flatten_metric_values(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        items: list[tuple[str, Any]] = []
        for key, child in sorted(value.items()):
            child_name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, dict):
                items.extend(flatten_metric_values(child, child_name))
            elif isinstance(child, list):
                items.append((child_name, child))
            elif child is not None:
                items.append((child_name, child))
        return items
    return [(prefix or "value", value)]


def parse_minute_bar_source(path: Path) -> dict[str, object]:
    warnings: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "bars": [],
            "symbols_seen": 0,
            "bars_seen": 0,
            "invalid_bars": 0,
            "warnings": [f"MINUTE_BAR_SOURCE_READ_FAILED:{type(exc).__name__}"],
        }
    raw_bars = payload.get("bars", payload) if isinstance(payload, dict) else {}
    if not isinstance(raw_bars, dict):
        return {
            "bars": [],
            "symbols_seen": 0,
            "bars_seen": 0,
            "invalid_bars": 0,
            "warnings": ["MINUTE_BAR_SOURCE_HAS_NO_BARS_OBJECT"],
        }

    bars: list[MinutePriceBar] = []
    bars_seen = 0
    invalid_bars = 0
    for symbol, items in raw_bars.items():
        if not isinstance(items, list):
            warnings.append(f"MINUTE_BAR_SYMBOL_ROWS_NOT_LIST:{symbol}")
            invalid_bars += 1
            continue
        for index, item in enumerate(items):
            bars_seen += 1
            if not isinstance(item, dict):
                invalid_bars += 1
                warnings.append(f"INVALID_MINUTE_BAR_ROW:{symbol}:{index}:NOT_OBJECT")
                continue
            bar = minute_bar_from_dict(item, fallback_symbol=str(symbol))
            if bar is None:
                invalid_bars += 1
                warnings.append(f"INVALID_MINUTE_BAR_ROW:{symbol}:{index}:PARSE_FAILED")
                continue
            if parse_datetime(bar.timestamp) is None:
                invalid_bars += 1
                warnings.append(f"INVALID_MINUTE_BAR_TIMESTAMP:{bar.symbol}:{bar.timestamp}")
                continue
            bars.append(bar)
    return {
        "bars": bars,
        "symbols_seen": len(raw_bars),
        "bars_seen": bars_seen,
        "invalid_bars": invalid_bars,
        "warnings": warnings,
    }


def minute_bar_row(
    bar: MinutePriceBar,
    *,
    source_path: Path,
    source_hash: str,
    imported_at: str,
) -> dict[str, Any]:
    return {
        "symbol": bar.symbol,
        "timestamp": bar.timestamp,
        "open": optional_float(bar.open),
        "high": optional_float(bar.high),
        "low": optional_float(bar.low),
        "close": optional_float(bar.close),
        "volume": optional_int(bar.volume),
        "source": bar.source,
        "granularity": infer_minute_bar_granularity(bar.source),
        "source_file_path": str(source_path),
        "source_file_hash": source_hash,
        "imported_at": imported_at,
        "updated_at": imported_at,
    }


def infer_minute_bar_granularity(source: str) -> str:
    normalized = str(source or "").lower()
    if "1m" in normalized or "minute" in normalized:
        return "1m"
    return "unknown"


def summarize_minute_bar_rows(rows: Any) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    symbol_counts: dict[str, int] = {}
    first_timestamps: dict[str, str] = {}
    latest_timestamps: dict[str, str] = {}
    for row in rows:
        symbol = str(row["symbol"])
        timestamp = str(row["timestamp"])
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        if symbol not in first_timestamps or timestamp < first_timestamps[symbol]:
            first_timestamps[symbol] = timestamp
        if symbol not in latest_timestamps or timestamp > latest_timestamps[symbol]:
            latest_timestamps[symbol] = timestamp
    return dict(sorted(symbol_counts.items())), dict(sorted(first_timestamps.items())), dict(sorted(latest_timestamps.items()))


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


def upsert_row_by_key(
    connection: sqlite3.Connection,
    table: str,
    key_columns: tuple[str, ...],
    row: dict[str, Any],
    *,
    compare_exclude: set[str] | None = None,
) -> str:
    compare_exclude = compare_exclude or set()
    where_sql = " AND ".join(f"{column} = :{column}" for column in key_columns)
    existing = connection.execute(f"SELECT * FROM {table} WHERE {where_sql}", row).fetchone()
    if existing is None:
        insert_row(connection, table, row)
        return "inserted"
    comparable_keys = [key for key in row if key not in compare_exclude]
    if all(existing[key] == row[key] for key in comparable_keys):
        return "skipped"
    assignments = ", ".join(f"{column} = :{column}" for column in row if column not in key_columns)
    connection.execute(f"UPDATE {table} SET {assignments} WHERE {where_sql}", row)
    return "updated"


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


def read_minute_bars(
    connection: sqlite3.Connection,
    *,
    symbol: str | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[str] = []
    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.strip().upper())
    if source:
        conditions.append("source = ?")
        params.append(source)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = connection.execute(
        f"""
        SELECT * FROM minute_bars
        {where}
        ORDER BY symbol, timestamp, source
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def read_evidence_runs(
    connection: sqlite3.Connection,
    *,
    run_type: str | None = None,
) -> list[dict[str, Any]]:
    if run_type:
        rows = connection.execute(
            """
            SELECT * FROM evidence_runs
            WHERE run_type = ?
            ORDER BY generated_at, source_path
            """,
            (run_type,),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT * FROM evidence_runs
            ORDER BY generated_at, run_type, source_path
            """
        ).fetchall()
    return [dict(row) for row in rows]


def read_evidence_metrics(
    connection: sqlite3.Connection,
    *,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    if run_id:
        rows = connection.execute(
            """
            SELECT * FROM evidence_metrics
            WHERE run_id = ?
            ORDER BY metric_name
            """,
            (run_id,),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT * FROM evidence_metrics
            ORDER BY run_id, metric_name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def read_system_status_events(
    connection: sqlite3.Connection,
    *,
    event_type: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[str] = []
    if event_type:
        conditions.append("event_type = ?")
        params.append(normalize_event_token(event_type))
    if status:
        conditions.append("status = ?")
        params.append(normalize_status(status))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = connection.execute(
        f"""
        SELECT * FROM system_status_events
        {where}
        ORDER BY occurred_at, event_type, source_path
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def read_captures(
    connection: sqlite3.Connection,
    *,
    capture_id: str | None = None,
    session: str | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[str] = []
    if capture_id:
        conditions.append("capture_id = ?")
        params.append(capture_id)
    if session:
        conditions.append("session = ?")
        params.append(session)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = connection.execute(
        f"""
        SELECT * FROM captures
        {where}
        ORDER BY capture_time, session, provider, scanner
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def read_capture_candidates(
    connection: sqlite3.Connection,
    *,
    ticker: str | None = None,
    capture_id: str | None = None,
) -> list[dict[str, Any]]:
    conditions = []
    params: list[str] = []
    if ticker:
        conditions.append("ticker = ?")
        params.append(ticker.strip().upper())
    if capture_id:
        conditions.append("capture_id = ?")
        params.append(capture_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = connection.execute(
        f"""
        SELECT * FROM capture_candidates
        {where}
        ORDER BY capture_id, rank, ticker
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def opportunity_alert_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM opportunity_alerts").fetchone()
    return int(row["count"] if row else 0)


def alert_outcome_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM alert_outcomes").fetchone()
    return int(row["count"] if row else 0)


def minute_bar_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM minute_bars").fetchone()
    return int(row["count"] if row else 0)


def evidence_run_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM evidence_runs").fetchone()
    return int(row["count"] if row else 0)


def evidence_metric_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM evidence_metrics").fetchone()
    return int(row["count"] if row else 0)


def system_status_event_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM system_status_events").fetchone()
    return int(row["count"] if row else 0)


def capture_index_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM captures").fetchone()
    return int(row["count"] if row else 0)


def capture_candidate_index_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) AS count FROM capture_candidates").fetchone()
    return int(row["count"] if row else 0)


def count_rows_for_source(connection: sqlite3.Connection, table: str, source_path: Path) -> int:
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE source_alerts_path = ?",
        (str(source_path),),
    ).fetchone()
    return int(row["count"] if row else 0)


def count_minute_bars_for_source(connection: sqlite3.Connection, source_path: Path) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM minute_bars WHERE source_file_path = ?",
        (str(source_path),),
    ).fetchone()
    return int(row["count"] if row else 0)


def count_capture_index_for_source(connection: sqlite3.Connection, source_path: Path) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM captures WHERE source_csv_path = ?",
        (str(source_path),),
    ).fetchone()
    return int(row["count"] if row else 0)


def count_capture_candidate_index_for_source(connection: sqlite3.Connection, source_path: Path) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM capture_candidates WHERE source_csv_path = ?",
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


def first_present(payload: dict[str, Any], *keys: str) -> object:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    return None


def first_text(payload: dict[str, Any], *keys: str) -> str:
    value = first_present(payload, *keys)
    return str(value) if value is not None else ""


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
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
    is_quarantined INTEGER NOT NULL DEFAULT 0,
    capture_session TEXT,
    capture_calendar_status TEXT,
    is_market_open_day INTEGER,
    is_study_eligible INTEGER,
    next_market_session_date TEXT,
    scheduling_policy_version TEXT,
    mode TEXT,
    market_regime TEXT,
    source_csv_path TEXT,
    source_csv_hash TEXT,
    imported_at TEXT,
    updated_at TEXT
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
    company TEXT,
    freshness TEXT,
    freshness_score INTEGER,
    article_count INTEGER,
    source_csv_path TEXT,
    source_csv_hash TEXT,
    imported_at TEXT,
    updated_at TEXT,
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
    granularity TEXT,
    source_file_path TEXT,
    source_file_hash TEXT,
    imported_at TEXT,
    updated_at TEXT,
    PRIMARY KEY(symbol, timestamp, source)
);

CREATE TABLE IF NOT EXISTS evidence_runs (
    run_id TEXT PRIMARY KEY,
    run_type TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    source_path TEXT,
    source_hash TEXT,
    status TEXT,
    started_at TEXT,
    ended_at TEXT,
    target_count INTEGER,
    alert_count INTEGER,
    completed_count INTEGER,
    pending_count INTEGER,
    unscorable_count INTEGER,
    warning_count INTEGER,
    report_paths_json TEXT,
    imported_at TEXT,
    updated_at TEXT,
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
    source_module TEXT,
    source_hash TEXT,
    summary TEXT,
    recommended_action TEXT,
    details_json TEXT,
    imported_at TEXT,
    updated_at TEXT
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
