from __future__ import annotations

"""Read-only inventory for the explicitly gated actual-candle cutover."""

import argparse
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.daily_ohlc import DAILY_OHLC_SOURCE_PATH
from momentum_hunter.schwab_price_history import ACTIVE_CANDLE_FILENAMES
from momentum_hunter.sqlite_store import SQLITE_DB_PATH
from momentum_hunter.staged_schwab_charts import (
    StagedSchwabChartPaths,
    load_staged_schwab_artifact,
)


CUTOVER_INVENTORY_SCHEMA_VERSION = 1
REQUIRED_MINUTE_BAR_COLUMNS = frozenset(
    {
        "symbol",
        "timestamp",
        "source",
        "source_file_path",
        "source_file_hash",
    }
)


class CandleCutoverInventoryError(RuntimeError):
    pass


def build_candle_cutover_inventory(
    *,
    staged_paths: StagedSchwabChartPaths,
    legacy_minute_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    legacy_daily_path: Path = DAILY_OHLC_SOURCE_PATH,
    database_path: Path = SQLITE_DB_PATH,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    checked_at = strict_utc(observed_at or datetime.now(timezone.utc))
    candles_path = Path(staged_paths.candles_path).resolve()
    manifest_path = Path(staged_paths.manifest_path).resolve()
    minute_path = Path(legacy_minute_path).resolve()
    daily_path = Path(legacy_daily_path).resolve()
    db_path = Path(database_path).resolve()
    db_sidecars = sqlite_sidecar_paths(db_path)
    protected_inputs = (
        candles_path,
        manifest_path,
        minute_path,
        daily_path,
        db_path,
        *db_sidecars,
    )
    before = existing_hashes(protected_inputs)

    artifact = load_staged_schwab_artifact(
        StagedSchwabChartPaths(
            candles_path=candles_path,
            manifest_path=manifest_path,
        )
    )
    minute_state = file_state(minute_path)
    daily_state = file_state(daily_path)
    sidecar_states = [file_state(path) for path in db_sidecars]
    if any(item["exists"] for item in sidecar_states):
        raise CandleCutoverInventoryError(
            "SQLite sidecar state exists; exact cutover inventory stopped safely."
        )
    sqlite_inventory = read_minute_bar_inventory(
        db_path,
        legacy_source_path=minute_path,
        legacy_source_hash=str(minute_state["sha256"]),
    )
    replacement_states = list(artifact.coverage.values())
    replacement_complete = (
        bool(replacement_states)
        and set(replacement_states) == {"AVAILABLE"}
        and not artifact.selection_truncated
        and len(artifact.selected_symbols) == artifact.source_target_count
    )
    requirements = [
        requirement(
            "STAGED_ARTIFACT_VERIFIED",
            True,
            f"Staged artifact SHA-256 {artifact.staged_sha256}.",
        ),
        requirement(
            "FULL_TARGET_SELECTION",
            (
                not artifact.selection_truncated
                and len(artifact.selected_symbols) == artifact.source_target_count
            ),
            (
                f"Selected {len(artifact.selected_symbols)} of "
                f"{artifact.source_target_count} persisted monitor targets."
            ),
        ),
        requirement(
            "REPLACEMENT_COVERAGE_AVAILABLE",
            replacement_complete,
            coverage_detail(artifact.coverage),
        ),
        requirement(
            "LEGACY_MINUTE_ARTIFACT_PRESENT",
            bool(minute_state["exists"]),
            file_detail(minute_state),
        ),
        requirement(
            "LEGACY_DAILY_ARTIFACT_PRESENT",
            bool(daily_state["exists"]),
            file_detail(daily_state),
        ),
        requirement(
            "LEGACY_SQLITE_ROWS_IDENTIFIED",
            sqlite_inventory["legacyRows"] > 0,
            (
                f"{sqlite_inventory['legacyRows']} row(s) match the exact legacy "
                "minute path and hash."
            ),
        ),
        requirement(
            "NO_UNEXPECTED_MINUTE_ROWS",
            sqlite_inventory["otherRows"] == 0,
            (
                f"{sqlite_inventory['otherRows']} minute-bar row(s) fall outside "
                "the exact legacy path/hash identity."
            ),
        ),
        requirement(
            "NO_PATH_OR_HASH_ALIAS_ROWS",
            (
                sqlite_inventory["samePathOtherHashRows"] == 0
                and sqlite_inventory["sameHashOtherPathRows"] == 0
            ),
            (
                f"same-path/other-hash={sqlite_inventory['samePathOtherHashRows']}; "
                f"same-hash/other-path={sqlite_inventory['sameHashOtherPathRows']}."
            ),
        ),
    ]
    ready = all(item["passed"] for item in requirements)
    after = existing_hashes(protected_inputs)
    if before != after:
        raise CandleCutoverInventoryError(
            "A cutover inventory input changed during the read-only audit."
        )
    return {
        "schemaVersion": CUTOVER_INVENTORY_SCHEMA_VERSION,
        "status": (
            "READY_FOR_EXPLICIT_DESTRUCTIVE_DECISION"
            if ready
            else "NOT_READY"
        ),
        "observedAt": timestamp_text(checked_at),
        "readOnlyAudit": True,
        "deletionPerformed": False,
        "databaseMutationPerformed": False,
        "activeChartSourceChanged": False,
        "cutoverPermitted": False,
        "decisionRequiredImmediatelyBeforeCutover": True,
        "requirements": requirements,
        "replacement": {
            "provider": "schwab_marketdata_v1_pricehistory",
            "stagedPath": str(candles_path),
            "stagedSha256": artifact.staged_sha256,
            "manifestPath": str(manifest_path),
            "targetReportPath": str(artifact.target_report_path),
            "targetReportSha256": artifact.target_report_sha256,
            "sourceTargetCount": artifact.source_target_count,
            "selectedCount": len(artifact.selected_symbols),
            "selectionTruncated": artifact.selection_truncated,
            "symbols": list(artifact.selected_symbols),
            "coverage": [
                {
                    "symbol": symbol,
                    "interval": interval,
                    "state": state,
                }
                for (symbol, interval), state in artifact.coverage.items()
            ],
        },
        "legacyFiles": {
            "minute": minute_state,
            "daily": daily_state,
        },
        "sqlite": sqlite_inventory,
        "exactCutoverScope": {
            "filesToRetireFromActiveUse": [
                {
                    "path": str(minute_path),
                    "sha256": minute_state["sha256"],
                    "exists": minute_state["exists"],
                },
                {
                    "path": str(daily_path),
                    "sha256": daily_state["sha256"],
                    "exists": daily_state["exists"],
                },
            ],
            "sqliteDatabase": str(db_path),
            "sqliteSidecars": sidecar_states,
            "sqliteRowsToRemove": {
                "table": "minute_bars",
                "sourceFilePath": str(minute_path),
                "sourceFileHash": minute_state["sha256"],
                "rowCount": sqlite_inventory["legacyRows"],
                "symbols": sqlite_inventory["legacySymbols"],
            },
            "actionsPerformed": [],
            "warning": (
                "Inventory only. Retiring files, removing SQLite rows, changing "
                "chart defaults, rebuilding caches, and enabling the staged source "
                "remain separately gated destructive/runtime actions."
            ),
        },
    }


def read_minute_bar_inventory(
    database_path: Path,
    *,
    legacy_source_path: Path,
    legacy_source_hash: str,
) -> dict[str, Any]:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise CandleCutoverInventoryError(
            "The canonical SQLite database is missing."
        )
    normalized_hash = strict_sha256(
        legacy_source_hash,
        "legacy minute artifact hash",
    )
    uri = path.as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        raise CandleCutoverInventoryError(
            "The canonical SQLite database could not be opened read-only."
        ) from None
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'minute_bars'
            """
        ).fetchone()
        if table is None:
            raise CandleCutoverInventoryError(
                "The canonical SQLite database has no minute_bars table."
            )
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(minute_bars)"
            ).fetchall()
        }
        if not REQUIRED_MINUTE_BAR_COLUMNS.issubset(columns):
            raise CandleCutoverInventoryError(
                "The minute_bars table lacks required source-identity columns."
            )
        total = scalar_count(
            connection,
            "SELECT COUNT(*) FROM minute_bars",
            (),
        )
        exact = scalar_count(
            connection,
            """
            SELECT COUNT(*)
            FROM minute_bars
            WHERE source_file_path = ?
              AND LOWER(source_file_hash) = ?
            """,
            (str(legacy_source_path), normalized_hash.lower()),
        )
        same_path_other_hash = scalar_count(
            connection,
            """
            SELECT COUNT(*)
            FROM minute_bars
            WHERE source_file_path = ?
              AND LOWER(COALESCE(source_file_hash, '')) <> ?
            """,
            (str(legacy_source_path), normalized_hash.lower()),
        )
        same_hash_other_path = scalar_count(
            connection,
            """
            SELECT COUNT(*)
            FROM minute_bars
            WHERE source_file_path <> ?
              AND LOWER(COALESCE(source_file_hash, '')) = ?
            """,
            (str(legacy_source_path), normalized_hash.lower()),
        )
        symbol_rows = connection.execute(
            """
            SELECT symbol, COUNT(*) AS row_count
            FROM minute_bars
            WHERE source_file_path = ?
              AND LOWER(source_file_hash) = ?
            GROUP BY symbol
            ORDER BY symbol
            """,
            (str(legacy_source_path), normalized_hash.lower()),
        ).fetchall()
        groups = connection.execute(
            """
            SELECT
                source_file_path,
                source_file_hash,
                symbol,
                source,
                COUNT(*) AS row_count
            FROM minute_bars
            GROUP BY source_file_path, source_file_hash, symbol, source
            ORDER BY source_file_path, source_file_hash, symbol, source
            """
        ).fetchall()
    except sqlite3.Error:
        raise CandleCutoverInventoryError(
            "The canonical SQLite minute-bar inventory query failed safely."
        ) from None
    finally:
        connection.close()
    return {
        "databasePath": str(path),
        "databaseSha256": file_sha256(path),
        "queryMode": "READ_ONLY_QUERY_ONLY",
        "table": "minute_bars",
        "totalRows": total,
        "legacyRows": exact,
        "otherRows": total - exact,
        "samePathOtherHashRows": same_path_other_hash,
        "sameHashOtherPathRows": same_hash_other_path,
        "legacySymbols": [
            {
                "symbol": str(row["symbol"]),
                "rowCount": int(row["row_count"]),
            }
            for row in symbol_rows
        ],
        "allSourceGroups": [
            {
                "sourceFilePath": str(row["source_file_path"] or ""),
                "sourceFileHash": str(row["source_file_hash"] or ""),
                "symbol": str(row["symbol"] or ""),
                "source": str(row["source"] or ""),
                "rowCount": int(row["row_count"]),
            }
            for row in groups
        ],
        "sidecars": [
            file_state(sidecar)
            for sidecar in sqlite_sidecar_paths(path)
        ],
    }


def write_cutover_inventory_receipt(
    payload: Mapping[str, Any],
    path: Path,
    *,
    protected_inputs: Sequence[Path] = (),
) -> Path:
    target = Path(path).resolve()
    protected = {Path(item).resolve() for item in protected_inputs}
    if (
        target in protected
        or target.name.casefold() in ACTIVE_CANDLE_FILENAMES
        or target.name.casefold().endswith((".sqlite", ".sqlite3", ".db"))
    ):
        raise CandleCutoverInventoryError(
            "The cutover inventory receipt cannot overwrite a source or data store."
        )
    if target.exists():
        raise CandleCutoverInventoryError(
            "The cutover inventory receipt is write-once and already exists."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            os.link(temporary, target)
        except FileExistsError:
            raise CandleCutoverInventoryError(
                "The cutover inventory receipt is write-once and already exists."
            ) from None
    finally:
        temporary.unlink(missing_ok=True)
    return target


def file_state(path: Path) -> dict[str, Any]:
    target = Path(path).resolve()
    try:
        stat = target.stat()
    except OSError:
        return {
            "path": str(target),
            "exists": False,
            "sha256": "",
            "sizeBytes": 0,
            "modifiedAt": "",
        }
    return {
        "path": str(target),
        "exists": target.is_file(),
        "sha256": file_sha256(target) if target.is_file() else "",
        "sizeBytes": int(stat.st_size),
        "modifiedAt": timestamp_text(
            datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        ),
    }


def existing_hashes(paths: Sequence[Path]) -> dict[str, str]:
    return {
        str(path): file_sha256(path)
        for path in paths
        if path.is_file()
    }


def sqlite_sidecar_paths(database_path: Path) -> tuple[Path, ...]:
    path = Path(database_path).resolve()
    return tuple(
        path.with_name(f"{path.name}{suffix}")
        for suffix in ("-wal", "-shm", "-journal")
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def scalar_count(
    connection: sqlite3.Connection,
    query: str,
    params: Sequence[object],
) -> int:
    row = connection.execute(query, tuple(params)).fetchone()
    return int(row[0] if row else 0)


def strict_sha256(value: object, label: str) -> str:
    text = str(value).strip().upper()
    if len(text) != 64 or any(character not in "0123456789ABCDEF" for character in text):
        raise CandleCutoverInventoryError(f"The {label} is invalid.")
    return text


def strict_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CandleCutoverInventoryError(
            "The cutover inventory timestamp must include a UTC offset."
        )
    return value.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return strict_utc(value).isoformat().replace("+00:00", "Z")


def requirement(
    name: str,
    passed: bool,
    detail: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "detail": detail,
    }


def coverage_detail(
    coverage: Mapping[tuple[str, str], str],
) -> str:
    counts: dict[str, int] = {}
    for state in coverage.values():
        counts[state] = counts.get(state, 0) + 1
    return "; ".join(
        f"{state}={count}"
        for state, count in sorted(counts.items())
    )


def file_detail(state: Mapping[str, Any]) -> str:
    return (
        f"path={state.get('path', '')}; exists={state.get('exists', False)}; "
        f"sha256={state.get('sha256', '')}; size={state.get('sizeBytes', 0)}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory the exact candle cutover scope without changing data."
    )
    parser.add_argument("command", choices=("audit",))
    parser.add_argument("--staged-candles", type=Path, required=True)
    parser.add_argument("--staged-manifest", type=Path, required=True)
    parser.add_argument(
        "--legacy-minute",
        type=Path,
        default=OPPORTUNITY_MINUTE_BARS_PATH,
    )
    parser.add_argument(
        "--legacy-daily",
        type=Path,
        default=DAILY_OHLC_SOURCE_PATH,
    )
    parser.add_argument("--database", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    inputs = (
        args.staged_candles,
        args.staged_manifest,
        args.legacy_minute,
        args.legacy_daily,
        args.database,
    )
    try:
        payload = build_candle_cutover_inventory(
            staged_paths=StagedSchwabChartPaths(
                candles_path=args.staged_candles,
                manifest_path=args.staged_manifest,
            ),
            legacy_minute_path=args.legacy_minute,
            legacy_daily_path=args.legacy_daily,
            database_path=args.database,
        )
        if args.output is not None:
            write_cutover_inventory_receipt(
                payload,
                args.output,
                protected_inputs=inputs,
            )
            payload["receiptPath"] = str(Path(args.output).resolve())
    except (CandleCutoverInventoryError, RuntimeError, ValueError) as exc:
        payload = {
            "schemaVersion": CUTOVER_INVENTORY_SCHEMA_VERSION,
            "status": "FAILED_SAFE",
            "failure": f"{type(exc).__name__}: {exc}",
            "readOnlyAudit": True,
            "deletionPerformed": False,
            "databaseMutationPerformed": False,
            "activeChartSourceChanged": False,
            "cutoverPermitted": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
