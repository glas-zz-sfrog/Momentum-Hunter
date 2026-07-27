from __future__ import annotations

"""Compose fresh inactive candle staging with a read-only cutover inventory."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.candle_cutover_inventory import (
    CandleCutoverInventoryError,
    build_candle_cutover_inventory,
    sqlite_sidecar_paths,
    write_cutover_inventory_receipt,
)
from momentum_hunter.daily_ohlc import DAILY_OHLC_SOURCE_PATH
from momentum_hunter.schwab_candle_staging import (
    DEFAULT_REPORTS_DIR,
    DEFAULT_STAGED_CANDLES_PATH,
    CandidateCandleStagingError,
    latest_monitor_target_report,
    load_monitor_target_selection,
    stage_candidate_candles,
)
from momentum_hunter.schwab_price_history import (
    ACTIVE_CANDLE_FILENAMES,
    ACTIVE_CANDLE_PATHS,
    MAX_PRICE_HISTORY_SYMBOLS,
    SchwabPriceHistoryError,
)
from momentum_hunter.sqlite_store import SQLITE_DB_PATH
from momentum_hunter.staged_schwab_charts import StagedSchwabChartPaths


CUTOVER_PREFLIGHT_SCHEMA_VERSION = 1
DEFAULT_STAGED_MANIFEST_PATH = DEFAULT_STAGED_CANDLES_PATH.with_name(
    f"{DEFAULT_STAGED_CANDLES_PATH.stem}.manifest.json"
)


class CandleCutoverPreflightError(RuntimeError):
    pass


def run_candle_cutover_preflight(
    *,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    target_report: Path | None = None,
    source: object | None = None,
    staged_candles_path: Path = DEFAULT_STAGED_CANDLES_PATH,
    staged_manifest_path: Path = DEFAULT_STAGED_MANIFEST_PATH,
    receipt_path: Path,
    legacy_minute_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    legacy_daily_path: Path = DAILY_OHLC_SOURCE_PATH,
    database_path: Path = SQLITE_DB_PATH,
    observed_at: datetime | None = None,
    active_paths: Sequence[Path] = tuple(ACTIVE_CANDLE_PATHS),
) -> dict[str, Any]:
    checked_at = require_aware_utc(
        observed_at or datetime.now(timezone.utc)
    )
    report_path = Path(
        target_report or latest_monitor_target_report(reports_dir)
    ).resolve()
    selection = load_monitor_target_selection(
        report_path,
        limit=MAX_PRICE_HISTORY_SYMBOLS,
    )
    if selection.truncated:
        raise CandleCutoverPreflightError(
            "Cutover preflight requires the full persisted target set; "
            f"{selection.source_target_count} targets exceed the bounded "
            f"{MAX_PRICE_HISTORY_SYMBOLS}-symbol provider batch."
        )

    staged_path = Path(staged_candles_path).resolve()
    manifest_path = Path(staged_manifest_path).resolve()
    output_receipt = Path(receipt_path).resolve()
    minute_path = Path(legacy_minute_path).resolve()
    daily_path = Path(legacy_daily_path).resolve()
    db_path = Path(database_path).resolve()
    protected_inputs = (
        report_path,
        minute_path,
        daily_path,
        db_path,
        *sqlite_sidecar_paths(db_path),
    )
    validate_receipt_path(
        output_receipt,
        protected_inputs=(
            *protected_inputs,
            staged_path,
            manifest_path,
        ),
    )
    before = input_fingerprints(protected_inputs)

    staging = stage_candidate_candles(
        selection,
        source=source,
        output_path=staged_path,
        manifest_path=manifest_path,
        observed_at=checked_at,
        active_paths=active_paths,
    )
    inventory = build_candle_cutover_inventory(
        staged_paths=StagedSchwabChartPaths(
            candles_path=staged_path,
            manifest_path=manifest_path,
        ),
        legacy_minute_path=minute_path,
        legacy_daily_path=daily_path,
        database_path=db_path,
        observed_at=checked_at,
    )
    require_bound_results(staging, inventory)
    after = input_fingerprints(protected_inputs)
    if before != after:
        raise CandleCutoverPreflightError(
            "A cutover preflight input changed while fresh staging and "
            "inventory were being bound."
        )

    payload = {
        "schemaVersion": CUTOVER_PREFLIGHT_SCHEMA_VERSION,
        "status": inventory["status"],
        "mode": "SCHWAB_CANDLE_CUTOVER_PREFLIGHT",
        "observedAt": timestamp_text(checked_at),
        "readOnlyProvider": True,
        "readOnlyInventory": True,
        "activeChartSource": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "accountDataIncluded": False,
        "deletionPerformed": False,
        "databaseMutationPerformed": False,
        "activeChartSourceChanged": False,
        "cutoverPermitted": False,
        "decisionRequiredImmediatelyBeforeCutover": True,
        "receiptPath": str(output_receipt),
        "staging": staging,
        "inventory": inventory,
    }
    write_cutover_inventory_receipt(
        payload,
        output_receipt,
        protected_inputs=(
            *protected_inputs,
            staged_path,
            manifest_path,
        ),
    )
    return payload


def require_bound_results(
    staging: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> None:
    replacement = inventory.get("replacement")
    if not isinstance(replacement, Mapping):
        raise CandleCutoverPreflightError(
            "The cutover inventory omitted replacement identity."
        )
    if (
        staging.get("stagedSha256") != replacement.get("stagedSha256")
        or str(Path(str(staging.get("stagedPath", ""))).resolve())
        != str(Path(str(replacement.get("stagedPath", ""))).resolve())
        or str(Path(str(staging.get("manifestPath", ""))).resolve())
        != str(Path(str(replacement.get("manifestPath", ""))).resolve())
    ):
        raise CandleCutoverPreflightError(
            "Fresh candle staging and cutover inventory identities do not match."
        )
    selected = tuple(str(item) for item in staging.get("selectedSymbols", ()))
    replacement_symbols = tuple(
        str(item) for item in replacement.get("symbols", ())
    )
    if not selected or selected != replacement_symbols:
        raise CandleCutoverPreflightError(
            "Fresh candle staging and cutover inventory target sets do not match."
        )


def validate_receipt_path(
    receipt_path: Path,
    *,
    protected_inputs: Sequence[Path],
) -> None:
    target = Path(receipt_path).resolve()
    protected = {Path(item).resolve() for item in protected_inputs}
    if (
        target in protected
        or target.name.casefold() in ACTIVE_CANDLE_FILENAMES
        or target.name.casefold().endswith((".sqlite", ".sqlite3", ".db"))
    ):
        raise CandleCutoverPreflightError(
            "Cutover preflight receipt cannot overwrite a source, staged "
            "artifact, manifest, or data store."
        )
    if target.exists():
        raise CandleCutoverPreflightError(
            "Cutover preflight receipts are write-once; choose a new receipt path."
        )


def input_fingerprints(paths: Sequence[Path]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for value in paths:
        path = Path(value).resolve()
        if path.is_file():
            stat = path.stat()
            digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            result[str(path)] = {
                "exists": True,
                "sizeBytes": int(stat.st_size),
                "sha256": digest.hexdigest().upper(),
            }
        else:
            result[str(path)] = {
                "exists": False,
                "sizeBytes": 0,
                "sha256": "",
            }
    return result


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CandleCutoverPreflightError(
            "Cutover preflight timestamps must include a UTC offset."
        )
    return value.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return require_aware_utc(value).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh inactive Schwab candle staging and bind it to a read-only "
            "legacy cutover inventory."
        )
    )
    parser.add_argument("command", choices=("preflight",))
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--target-report", type=Path)
    parser.add_argument(
        "--staged-candles",
        type=Path,
        default=DEFAULT_STAGED_CANDLES_PATH,
    )
    parser.add_argument(
        "--staged-manifest",
        type=Path,
        default=DEFAULT_STAGED_MANIFEST_PATH,
    )
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
    parser.add_argument(
        "--receipt",
        type=Path,
        required=True,
    )
    args = parser.parse_args(argv)
    try:
        payload = run_candle_cutover_preflight(
            reports_dir=args.reports_dir,
            target_report=args.target_report,
            staged_candles_path=args.staged_candles,
            staged_manifest_path=args.staged_manifest,
            receipt_path=args.receipt,
            legacy_minute_path=args.legacy_minute,
            legacy_daily_path=args.legacy_daily,
            database_path=args.database,
        )
    except (
        CandleCutoverPreflightError,
        CandidateCandleStagingError,
        SchwabPriceHistoryError,
        CandleCutoverInventoryError,
        OSError,
        ValueError,
    ) as exc:
        payload = {
            "schemaVersion": CUTOVER_PREFLIGHT_SCHEMA_VERSION,
            "status": "FAILED_SAFE",
            "mode": "SCHWAB_CANDLE_CUTOVER_PREFLIGHT",
            "failure": f"{type(exc).__name__}: {exc}",
            "readOnlyProvider": True,
            "readOnlyInventory": True,
            "activeChartSource": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
            "accountDataIncluded": False,
            "deletionPerformed": False,
            "databaseMutationPerformed": False,
            "activeChartSourceChanged": False,
            "cutoverPermitted": False,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return (
        0
        if payload["status"] == "READY_FOR_EXPLICIT_DESTRUCTIVE_DECISION"
        else 3
    )


if __name__ == "__main__":
    raise SystemExit(main())
