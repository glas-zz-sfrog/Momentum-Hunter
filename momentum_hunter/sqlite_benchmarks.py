from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.sqlite_store import SQLITE_DB_PATH, connect_database, current_schema_version
from momentum_hunter.time_utils import now_central


SQLITE_BENCHMARK_ENGINE_VERSION = "sqlite_query_benchmark_v1"
SQLITE_BENCHMARK_LATEST_JSON = DATA_DIR / "reports" / "sqlite-query-benchmark-latest.json"
SQLITE_BENCHMARK_LATEST_MD = DATA_DIR / "reports" / "sqlite-query-benchmark-latest.md"


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    status: str
    elapsed_ms: float
    row_count: int
    warning: str


QUERY_SPECS: list[tuple[str, str]] = [
    (
        "table_counts",
        """
        SELECT name AS table_name,
               (SELECT COUNT(*) FROM sqlite_master sm2 WHERE sm2.name = sm.name) AS exists_count
        FROM sqlite_master sm
        WHERE type = 'table'
        ORDER BY name
        """,
    ),
    (
        "candidate_history_by_symbol",
        """
        SELECT cc.ticker, COUNT(*) AS capture_count, MAX(cc.score) AS max_score
        FROM capture_candidates cc
        JOIN captures c ON c.capture_id = cc.capture_id
        WHERE COALESCE(c.is_quarantined, 0) = 0
        GROUP BY cc.ticker
        ORDER BY capture_count DESC, cc.ticker
        LIMIT 50
        """,
    ),
    (
        "capture_session_counts",
        """
        SELECT session, COUNT(*) AS count
        FROM captures
        GROUP BY session
        ORDER BY session
        """,
    ),
    (
        "alert_outcome_counts",
        """
        SELECT status, classification, COUNT(*) AS count
        FROM alert_outcomes
        GROUP BY status, classification
        ORDER BY count DESC, status, classification
        """,
    ),
    (
        "minute_bar_symbol_counts",
        """
        SELECT symbol, COUNT(*) AS count, MIN(timestamp) AS first_timestamp, MAX(timestamp) AS latest_timestamp
        FROM minute_bars
        GROUP BY symbol
        ORDER BY count DESC, symbol
        LIMIT 50
        """,
    ),
    (
        "evidence_run_counts",
        """
        SELECT run_type, COUNT(*) AS count, MAX(generated_at) AS latest_generated_at
        FROM evidence_runs
        GROUP BY run_type
        ORDER BY count DESC, run_type
        """,
    ),
    (
        "system_status_latest",
        """
        SELECT event_type, status, MAX(occurred_at) AS latest_occurred_at
        FROM system_status_events
        GROUP BY event_type, status
        ORDER BY latest_occurred_at DESC
        LIMIT 50
        """,
    ),
    (
        "provider_quality_latest",
        """
        SELECT symbol, provider, usable_market_tape, MAX(generated_at) AS latest_generated_at
        FROM provider_quality_checks
        GROUP BY symbol, provider, usable_market_tape
        ORDER BY latest_generated_at DESC, symbol
        LIMIT 50
        """,
    ),
    (
        "user_state_counts",
        """
        SELECT 'candidate_reviews' AS table_name, COUNT(*) AS count FROM candidate_reviews
        UNION ALL
        SELECT 'watchlist_items' AS table_name, COUNT(*) AS count FROM watchlist_items
        UNION ALL
        SELECT 'entry_plans' AS table_name, COUNT(*) AS count FROM entry_plans
        """,
    ),
]


def build_sqlite_benchmark_report(*, db_path: Path = SQLITE_DB_PATH, slow_query_ms: float = 250.0) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    if not db_path.exists():
        return {
            "schema_version": 1,
            "engine_version": SQLITE_BENCHMARK_ENGINE_VERSION,
            "generated_at": generated_at,
            "database_path": str(db_path),
            "sqlite_schema_version": 0,
            "overall_status": "WARN",
            "slow_query_ms": slow_query_ms,
            "benchmarks": [],
            "warnings": ["SQLITE_DATABASE_MISSING"],
        }
    benchmarks: list[BenchmarkResult] = []
    warnings: list[str] = []
    with connect_database(db_path) as connection:
        schema_version = current_schema_version(connection)
        for name, sql in QUERY_SPECS:
            benchmark = run_query_benchmark(connection, name, sql, slow_query_ms=slow_query_ms)
            benchmarks.append(benchmark)
            if benchmark.warning:
                warnings.append(benchmark.warning)
    return {
        "schema_version": 1,
        "engine_version": SQLITE_BENCHMARK_ENGINE_VERSION,
        "generated_at": generated_at,
        "database_path": str(db_path),
        "sqlite_schema_version": schema_version,
        "overall_status": "WARN" if warnings else "PASS",
        "slow_query_ms": slow_query_ms,
        "benchmarks": [asdict(item) for item in benchmarks],
        "warnings": warnings,
    }


def run_query_benchmark(connection: sqlite3.Connection, name: str, sql: str, *, slow_query_ms: float) -> BenchmarkResult:
    started = time.perf_counter()
    warning = ""
    status = "PASS"
    try:
        rows = connection.execute(sql).fetchall()
        row_count = len(rows)
    except sqlite3.Error as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return BenchmarkResult(name=name, status="FAIL", elapsed_ms=elapsed_ms, row_count=0, warning=f"QUERY_FAILED:{name}:{type(exc).__name__}")
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    if elapsed_ms > slow_query_ms:
        status = "WARN"
        warning = f"SLOW_QUERY:{name}:{elapsed_ms}ms"
    return BenchmarkResult(name=name, status=status, elapsed_ms=elapsed_ms, row_count=row_count, warning=warning)


def write_sqlite_benchmark_report(
    payload: dict[str, Any],
    *,
    json_path: Path = SQLITE_BENCHMARK_LATEST_JSON,
    markdown_path: Path = SQLITE_BENCHMARK_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_sqlite_benchmark_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_sqlite_benchmark_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Hunter SQLite Query Benchmark",
        "",
        "Read-only query benchmark for offline analytics readiness.",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Database: `{payload.get('database_path', '')}`",
        f"- SQLite schema version: {payload.get('sqlite_schema_version', 0)}",
        f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Slow query threshold ms: {payload.get('slow_query_ms', '')}",
        "",
        "| Query | Status | Elapsed ms | Rows | Warning |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in payload.get("benchmarks", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"| {item.get('name', '')} | {item.get('status', '')} | {item.get('elapsed_ms', 0)} | "
            f"{item.get('row_count', 0)} | {item.get('warning', '')} |"
        )
    warnings = payload.get("warnings", [])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] if isinstance(warnings, list) and warnings else ["- None."])
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only SQLite query benchmarks.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--slow-query-ms", type=float, default=250.0)
    parser.add_argument("--json", type=Path, default=SQLITE_BENCHMARK_LATEST_JSON)
    parser.add_argument("--markdown", type=Path, default=SQLITE_BENCHMARK_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_sqlite_benchmark_report(db_path=args.db, slow_query_ms=args.slow_query_ms)
    paths = write_sqlite_benchmark_report(payload, json_path=args.json, markdown_path=args.markdown)
    print(json.dumps({"overall_status": payload.get("overall_status"), "warnings": payload.get("warnings", []), "paths": {key: str(value) for key, value in paths.items()}}, indent=2))
    return 0 if payload.get("overall_status") in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
