from __future__ import annotations

"""Stage Schwab candles for persisted monitor targets without activating chart data."""

import argparse
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from momentum_hunter.config import DATA_DIR
from momentum_hunter.schwab_price_history import (
    ACTIVE_CANDLE_FILENAMES,
    ACTIVE_CANDLE_PATHS,
    MAX_PRICE_HISTORY_SYMBOLS,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabPriceHistoryError,
    SchwabPriceHistoryResult,
    SchwabPriceHistorySource,
    normalize_symbol,
    parse_timestamp,
    require_artifact_snapshot_unchanged,
    replaceable_staged_artifact_snapshot,
    timestamp_text,
    write_staged_price_history,
)


STAGING_MANIFEST_SCHEMA_VERSION = 1
MONITOR_TARGET_REPORT_PATTERN = "opportunity-monitor-targets-*.json"
DEFAULT_REPORTS_DIR = DATA_DIR / "reports"
DEFAULT_STAGED_CANDLES_PATH = DATA_DIR / "staging" / "schwab-candidate-candles.json"
MAX_TARGET_REPORT_BYTES = 2 * 1024 * 1024
MAX_STAGING_MANIFEST_BYTES = 4 * 1024 * 1024
REQUIRED_INTERVALS = ("1m", "Daily")
INTRADAY_STALE_AFTER = timedelta(days=1)
DAILY_STALE_AFTER = timedelta(days=7)
MAX_FUTURE_BAR = timedelta(seconds=5)


class CandidateCandleStagingError(RuntimeError):
    pass


@dataclass(frozen=True)
class MonitorTargetSelection:
    report_path: Path
    report_sha256: str
    report_generated_at: str
    source_target_count: int
    symbols: tuple[str, ...]
    truncated: bool


def latest_monitor_target_report(reports_dir: Path = DEFAULT_REPORTS_DIR) -> Path:
    candidates = [
        path
        for path in Path(reports_dir).glob(MONITOR_TARGET_REPORT_PATTERN)
        if path.is_file()
    ]
    if not candidates:
        raise CandidateCandleStagingError(
            "No persisted monitor-target report is available for candle staging."
        )
    return max(
        candidates,
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )


def load_monitor_target_selection(
    report_path: Path,
    *,
    limit: int = MAX_PRICE_HISTORY_SYMBOLS,
) -> MonitorTargetSelection:
    if limit <= 0 or limit > MAX_PRICE_HISTORY_SYMBOLS:
        raise CandidateCandleStagingError(
            f"Candidate candle staging limit must be between 1 and {MAX_PRICE_HISTORY_SYMBOLS}."
        )
    path = Path(report_path)
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_TARGET_REPORT_BYTES:
            raise CandidateCandleStagingError(
                "The persisted monitor-target report has an invalid size."
            )
        with path.open("rb") as source:
            raw = source.read(MAX_TARGET_REPORT_BYTES + 1)
    except OSError:
        raise CandidateCandleStagingError(
            "The persisted monitor-target report could not be read."
        ) from None
    if not raw or len(raw) > MAX_TARGET_REPORT_BYTES:
        raise CandidateCandleStagingError(
            "The persisted monitor-target report has an invalid size."
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateCandleStagingError(
            "The persisted monitor-target report is not valid JSON."
        ) from None
    if not isinstance(payload, Mapping):
        raise CandidateCandleStagingError(
            "The persisted monitor-target report has an invalid shape."
        )
    metadata = payload.get("metadata")
    targets = payload.get("targets")
    if not isinstance(metadata, Mapping) or not isinstance(targets, list):
        raise CandidateCandleStagingError(
            "The persisted monitor-target report omitted metadata or targets."
        )
    generated_at = require_timestamp(
        metadata.get("generated_at"),
        "monitor-target generated_at",
    )
    symbols: list[str] = []
    for item in targets:
        if not isinstance(item, Mapping):
            raise CandidateCandleStagingError(
                "The persisted monitor-target report contains an invalid target row."
            )
        try:
            symbol = normalize_symbol(item.get("symbol", ""))
        except ValueError:
            raise CandidateCandleStagingError(
                "The persisted monitor-target report contains an invalid symbol."
            ) from None
        if symbol in symbols:
            raise CandidateCandleStagingError(
                "The persisted monitor-target report contains duplicate symbols."
            )
        symbols.append(symbol)
    if not symbols:
        raise CandidateCandleStagingError(
            "The persisted monitor-target report contains no symbols."
        )
    selected = tuple(symbols[:limit])
    return MonitorTargetSelection(
        report_path=path.resolve(),
        report_sha256=hashlib.sha256(raw).hexdigest().upper(),
        report_generated_at=generated_at,
        source_target_count=len(symbols),
        symbols=selected,
        truncated=len(symbols) > len(selected),
    )


def stage_candidate_candles(
    selection: MonitorTargetSelection,
    *,
    source: object | None = None,
    output_path: Path = DEFAULT_STAGED_CANDLES_PATH,
    manifest_path: Path | None = None,
    observed_at: datetime | None = None,
    active_paths: Sequence[Path] = tuple(ACTIVE_CANDLE_PATHS),
) -> dict[str, Any]:
    output, manifest = validate_output_paths(
        output_path,
        manifest_path=manifest_path,
        active_paths=active_paths,
        protected_inputs=(selection.report_path,),
    )
    staged_snapshot = replaceable_staged_artifact_snapshot(output)
    manifest_snapshot = replaceable_staging_manifest_snapshot(manifest)
    require_selection_source_unchanged(selection)
    history_source = source or SchwabPriceHistorySource()
    history_batch = getattr(history_source, "history_batch", None)
    if not callable(history_batch):
        raise CandidateCandleStagingError(
            "The Schwab candle source does not provide bounded batch history."
        )
    results = tuple(history_batch(selection.symbols, REQUIRED_INTERVALS))
    require_selection_source_unchanged(selection)
    checked_at = as_utc(observed_at or datetime.now(timezone.utc))
    coverage = validate_result_coverage(
        selection,
        results,
        observed_at=checked_at,
    )
    require_artifact_snapshot_unchanged(output, staged_snapshot)
    require_manifest_snapshot_unchanged(manifest, manifest_snapshot)
    write_staged_price_history(
        results,
        path=output,
        active_paths=active_paths,
        expected_existing=staged_snapshot,
    )
    staged_sha256 = file_sha256(output)
    manifest_payload = {
        "schemaVersion": STAGING_MANIFEST_SCHEMA_VERSION,
        "status": "STAGED_INACTIVE",
        "generatedAt": timestamp_text(checked_at),
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "readOnlyProvider": True,
        "activeChartSource": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "accountDataIncluded": False,
        "selection": {
            "sourceLabel": selection.report_path.name,
            "sourcePath": str(selection.report_path),
            "sourceSha256": selection.report_sha256,
            "sourceGeneratedAt": selection.report_generated_at,
            "sourceTargetCount": selection.source_target_count,
            "selectedCount": len(selection.symbols),
            "symbols": list(selection.symbols),
            "truncated": selection.truncated,
            "selectionRule": "Persisted monitor-target report order; no rescoring or readiness recalculation.",
        },
        "stagedArtifact": {
            "path": str(output),
            "sha256": staged_sha256,
        },
        "coverageStatus": coverage_status(coverage),
        "coverage": coverage,
        "activation": {
            "permitted": False,
            "reason": "Legacy candle purge and actual-source cutover remain separately gated.",
        },
    }
    atomic_write_json(
        manifest,
        manifest_payload,
        expected_existing=manifest_snapshot,
    )
    return {
        "schemaVersion": STAGING_MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "mode": "SCHWAB_CANDIDATE_CANDLE_STAGING",
        "activeChartSource": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "accountDataIncluded": False,
        "selectedSymbols": list(selection.symbols),
        "resultCount": len(results),
        "coverageStatus": manifest_payload["coverageStatus"],
        "stagedPath": str(output),
        "stagedSha256": staged_sha256,
        "manifestPath": str(manifest),
    }


def validate_result_coverage(
    selection: MonitorTargetSelection,
    results: Sequence[SchwabPriceHistoryResult],
    *,
    observed_at: datetime,
) -> list[dict[str, Any]]:
    checked_at = as_utc(observed_at)
    expected = [
        (symbol, interval)
        for symbol in selection.symbols
        for interval in REQUIRED_INTERVALS
    ]
    by_key: dict[tuple[str, str], SchwabPriceHistoryResult] = {}
    for result in results:
        key = (result.symbol, result.interval)
        if key in by_key:
            raise CandidateCandleStagingError(
                "Schwab candle staging received duplicate symbol/interval results."
            )
        by_key[key] = result
    if set(by_key) != set(expected):
        raise CandidateCandleStagingError(
            "Schwab candle staging result identities did not match the selected symbols and intervals."
        )

    coverage: list[dict[str, Any]] = []
    for key in expected:
        result = by_key[key]
        if result.source != SCHWAB_PRICE_HISTORY_SOURCE:
            raise CandidateCandleStagingError(
                "Schwab candle staging received an unexpected provider identity."
            )
        if result.clock_skew_proof.get("status") != "PASS":
            raise CandidateCandleStagingError(
                "Schwab candle staging requires a passing HTTPS clock proof."
            )
        timestamps: list[datetime] = []
        for bar in result.bars:
            if (
                bar.symbol != result.symbol
                or bar.interval != result.interval
                or bar.source != SCHWAB_PRICE_HISTORY_SOURCE
            ):
                raise CandidateCandleStagingError(
                    "Schwab candle staging received a mismatched candle identity."
                )
            timestamps.append(parse_timestamp(bar.timestamp))
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise CandidateCandleStagingError(
                "Schwab candle staging requires ordered, unique candle timestamps."
            )
        latest = timestamps[-1] if timestamps else None
        if latest is not None and latest > checked_at + MAX_FUTURE_BAR:
            raise CandidateCandleStagingError(
                "Schwab candle staging received a future-dated candle."
            )
        state = candle_coverage_state(
            result.interval,
            len(result.bars),
            latest,
            checked_at,
        )
        coverage.append(
            {
                "symbol": result.symbol,
                "interval": result.interval,
                "state": state,
                "barCount": len(result.bars),
                "firstBar": result.bars[0].timestamp if result.bars else "",
                "lastBar": result.bars[-1].timestamp if result.bars else "",
                "clockStatus": "PASS",
            }
        )
    return coverage


def candle_coverage_state(
    interval: str,
    count: int,
    latest: datetime | None,
    observed_at: datetime,
) -> str:
    if count < 2 or latest is None:
        return "INSUFFICIENT_DATA"
    stale_after = DAILY_STALE_AFTER if interval == "Daily" else INTRADAY_STALE_AFTER
    return "STALE" if observed_at - latest > stale_after else "AVAILABLE"


def coverage_status(coverage: Sequence[Mapping[str, Any]]) -> str:
    states = {str(item.get("state", "")) for item in coverage}
    return "COMPLETE" if states == {"AVAILABLE"} else "PARTIAL"


def validate_output_paths(
    output_path: Path,
    *,
    manifest_path: Path | None,
    active_paths: Sequence[Path],
    protected_inputs: Sequence[Path] = (),
) -> tuple[Path, Path]:
    output = Path(output_path).resolve()
    manifest = (
        Path(manifest_path).resolve()
        if manifest_path is not None
        else output.with_name(f"{output.stem}.manifest.json")
    )
    protected = {
        Path(item).resolve()
        for item in (*active_paths, *protected_inputs)
    }
    if (
        output in protected
        or manifest in protected
        or output.name.casefold() in ACTIVE_CANDLE_FILENAMES
        or manifest.name.casefold() in ACTIVE_CANDLE_FILENAMES
    ):
        raise CandidateCandleStagingError(
            "Candidate candle staging cannot overwrite a source or active chart artifact."
        )
    if output == manifest:
        raise CandidateCandleStagingError(
            "Candidate candle staging data and manifest paths must be different."
        )
    return output, manifest


def require_selection_source_unchanged(
    selection: MonitorTargetSelection,
) -> None:
    try:
        current_hash = file_sha256(selection.report_path)
    except OSError:
        raise CandidateCandleStagingError(
            "The selected monitor-target report disappeared during candle staging."
        ) from None
    if current_hash != selection.report_sha256:
        raise CandidateCandleStagingError(
            "The selected monitor-target report changed during candle staging."
        )


def replaceable_staging_manifest_snapshot(path: Path) -> bytes | None:
    target = Path(path).resolve()
    try:
        stat = target.stat()
    except FileNotFoundError:
        return None
    except OSError:
        raise CandidateCandleStagingError(
            "The existing candle staging manifest could not be inspected."
        ) from None
    if (
        target.is_symlink()
        or not target.is_file()
        or stat.st_size <= 0
        or stat.st_size > MAX_STAGING_MANIFEST_BYTES
    ):
        raise CandidateCandleStagingError(
            "The existing candle staging manifest is not replaceable."
        )
    try:
        raw = target.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise CandidateCandleStagingError(
            "The existing candle staging manifest is not replaceable."
        ) from None
    activation = payload.get("activation") if isinstance(payload, Mapping) else None
    staged_artifact = (
        payload.get("stagedArtifact")
        if isinstance(payload, Mapping)
        else None
    )
    selection = payload.get("selection") if isinstance(payload, Mapping) else None
    coverage = payload.get("coverage") if isinstance(payload, Mapping) else None
    if (
        not isinstance(payload, Mapping)
        or payload.get("schemaVersion") != STAGING_MANIFEST_SCHEMA_VERSION
        or payload.get("status") != "STAGED_INACTIVE"
        or payload.get("source") != SCHWAB_PRICE_HISTORY_SOURCE
        or payload.get("readOnlyProvider") is not True
        or payload.get("activeChartSource") is not False
        or payload.get("transmitting") is not False
        or payload.get("orderTransmission") != "UNAVAILABLE"
        or payload.get("accountDataIncluded") is not False
        or not isinstance(payload.get("generatedAt"), str)
        or not isinstance(selection, Mapping)
        or not isinstance(selection.get("symbols"), list)
        or not isinstance(staged_artifact, Mapping)
        or not isinstance(staged_artifact.get("path"), str)
        or not isinstance(staged_artifact.get("sha256"), str)
        or not isinstance(coverage, list)
        or not isinstance(activation, Mapping)
        or activation.get("permitted") is not False
    ):
        raise CandidateCandleStagingError(
            "The existing candle staging manifest is not replaceable."
        )
    return raw


def atomic_write_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    expected_existing: bytes | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        require_manifest_snapshot_unchanged(path, expected_existing)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def require_manifest_snapshot_unchanged(
    path: Path,
    expected: bytes | None,
) -> None:
    try:
        current = replaceable_staging_manifest_snapshot(path)
    except CandidateCandleStagingError:
        raise CandidateCandleStagingError(
            "The candle staging manifest changed during the write."
        ) from None
    if current != expected:
        raise CandidateCandleStagingError(
            "The candle staging manifest changed during the write."
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def require_timestamp(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateCandleStagingError(
            f"The persisted {field_name} is missing."
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise CandidateCandleStagingError(
            f"The persisted {field_name} is invalid."
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateCandleStagingError(
            f"The persisted {field_name} must include a UTC offset."
        )
    return timestamp_text(parsed)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CandidateCandleStagingError(
            "Candidate candle staging timestamps must include a UTC offset."
        )
    return value.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage current monitor-target Schwab candles without activating chart data."
    )
    parser.add_argument("command", choices=("stage-current-targets",))
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--target-report", type=Path)
    parser.add_argument("--limit", type=int, default=MAX_PRICE_HISTORY_SYMBOLS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        target_report = args.target_report or latest_monitor_target_report(
            args.reports_dir
        )
        selection = load_monitor_target_selection(
            target_report,
            limit=args.limit,
        )
        summary = stage_candidate_candles(
            selection,
            output_path=args.output,
            manifest_path=args.manifest,
        )
    except (CandidateCandleStagingError, SchwabPriceHistoryError, ValueError) as exc:
        summary = {
            "schemaVersion": STAGING_MANIFEST_SCHEMA_VERSION,
            "status": "FAILED_SAFE",
            "mode": "SCHWAB_CANDIDATE_CANDLE_STAGING",
            "failure": f"{type(exc).__name__}: {exc}",
            "activeChartSource": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
            "accountDataIncluded": False,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
