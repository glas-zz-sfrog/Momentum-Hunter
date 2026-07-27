from __future__ import annotations

"""Read-only chart snapshots from hash-verified, explicitly inactive Schwab staging."""

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from momentum_hunter.schwab_candle_staging import (
    REQUIRED_INTERVALS,
    STAGING_MANIFEST_SCHEMA_VERSION,
)
from momentum_hunter.schwab_price_history import (
    SCHWAB_PRICE_HISTORY_SOURCE,
    STAGED_CANDLE_SCHEMA_VERSION,
)
from momentum_hunter.workstation_charts import (
    CHART_SNAPSHOT_SCHEMA_VERSION,
    DAILY_STALE_AFTER,
    DEFAULT_MAX_CANDLES,
    INTRADAY_STALE_AFTER,
    normalize_interval,
    normalize_symbol,
)


MAX_STAGED_CANDLE_BYTES = 64 * 1024 * 1024
MAX_STAGED_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FUTURE_BAR = timedelta(seconds=5)
ALLOWED_COVERAGE_STATES = frozenset(
    {"AVAILABLE", "STALE", "INSUFFICIENT_DATA"}
)


class StagedSchwabChartError(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedSchwabChartPaths:
    candles_path: Path
    manifest_path: Path


@dataclass(frozen=True)
class StagedCandle:
    symbol: str
    interval: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: str


@dataclass(frozen=True)
class StagedResult:
    symbol: str
    interval: str
    requested_at: str
    received_at: str
    bars: tuple[StagedCandle, ...]


@dataclass(frozen=True)
class StagedSchwabArtifact:
    generated_at: str
    manifest_generated_at: str
    selected_symbols: tuple[str, ...]
    target_report_path: Path
    target_report_sha256: str
    staged_sha256: str
    results: Mapping[tuple[str, str], StagedResult]
    coverage: Mapping[tuple[str, str], str]


class StagedSchwabChartService:
    """Maps verified inactive Schwab evidence into the existing chart wire shape."""

    def __init__(
        self,
        *,
        paths: StagedSchwabChartPaths,
        max_candles: int = DEFAULT_MAX_CANDLES,
    ) -> None:
        self.paths = paths
        self.max_candles = max(2, int(max_candles))

    def snapshot(
        self,
        symbol: str,
        interval: str,
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        clean_symbol = normalize_symbol(symbol)
        clean_interval = normalize_interval(interval)
        checked_at = strict_utc(
            observed_at or datetime.now(timezone.utc),
            "Chart preview observed_at",
        )
        artifact = load_staged_schwab_artifact(self.paths)
        if clean_symbol not in artifact.selected_symbols:
            return unavailable_snapshot(
                clean_symbol,
                clean_interval,
                checked_at,
                "The symbol is not present in the hash-bound monitor-target selection.",
                artifact,
            )

        source_interval = "Daily" if clean_interval == "Daily" else "1m"
        result = artifact.results[(clean_symbol, source_interval)]
        candles = [candle_payload(item) for item in result.bars]
        if clean_interval in {"5m", "15m"}:
            candles = aggregate_candles(
                candles,
                int(clean_interval.removesuffix("m")),
            )
        selected = candles[-self.max_candles :]
        if not selected:
            return unavailable_snapshot(
                clean_symbol,
                clean_interval,
                checked_at,
                f"The verified staged {source_interval} result contains no candles.",
                artifact,
            )

        latest = strict_timestamp(
            selected[-1]["timestamp"],
            "Chart preview latest candle",
        )
        state = snapshot_state(
            count=len(selected),
            latest=latest,
            observed_at=checked_at,
            interval=clean_interval,
            staged_state=artifact.coverage[(clean_symbol, source_interval)],
        )
        state_label = state.replace("_", " ")
        summary = (
            f"STAGED PREVIEW ONLY | {state_label} | {len(selected)} verified "
            f"{clean_interval} candle(s) from Schwab price history | "
            f"as of {timestamp_text(latest)} | inactive; no active chart source changed"
        )
        return {
            "schemaVersion": CHART_SNAPSHOT_SCHEMA_VERSION,
            "symbol": clean_symbol,
            "interval": clean_interval,
            "state": state,
            "observedAt": timestamp_text(checked_at),
            "asOf": timestamp_text(latest),
            "summary": summary,
            "previewOnly": True,
            "activeChartSource": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
            "lineage": {
                "sourceLabel": "Schwab Trader API price history (inactive staging)",
                "asOf": timestamp_text(latest),
                "summary": (
                    f"Hash-verified staged artifact {artifact.staged_sha256}; "
                    f"target report {artifact.target_report_path.name} "
                    f"{artifact.target_report_sha256}. No provider fetch or source write occurred."
                ),
            },
            "candles": selected,
        }


def load_staged_schwab_artifact(
    paths: StagedSchwabChartPaths,
) -> StagedSchwabArtifact:
    candles_path = Path(paths.candles_path).resolve()
    manifest_path = Path(paths.manifest_path).resolve()
    manifest_raw = read_bounded(
        manifest_path,
        MAX_STAGED_MANIFEST_BYTES,
        "staged candle manifest",
    )
    manifest = parse_object(manifest_raw, "staged candle manifest")
    require_schema(
        manifest,
        STAGING_MANIFEST_SCHEMA_VERSION,
        "staged candle manifest",
    )
    if manifest.get("status") != "STAGED_INACTIVE":
        raise StagedSchwabChartError(
            "The staged candle manifest is not explicitly inactive."
        )
    require_safety_flags(manifest, "staged candle manifest")
    activation = require_mapping(manifest.get("activation"), "manifest activation")
    if activation.get("permitted") is not False:
        raise StagedSchwabChartError(
            "The staged candle manifest does not keep activation locked."
        )
    if manifest.get("source") != SCHWAB_PRICE_HISTORY_SOURCE:
        raise StagedSchwabChartError(
            "The staged candle manifest has an unexpected provider identity."
        )

    staged_identity = require_mapping(
        manifest.get("stagedArtifact"),
        "manifest stagedArtifact",
    )
    recorded_path = strict_path(
        staged_identity.get("path"),
        "manifest staged artifact path",
    )
    if recorded_path != candles_path:
        raise StagedSchwabChartError(
            "The staged candle path does not match its manifest identity."
        )
    recorded_stage_hash = strict_sha256(
        staged_identity.get("sha256"),
        "manifest staged artifact hash",
    )
    candles_raw = read_bounded(
        candles_path,
        MAX_STAGED_CANDLE_BYTES,
        "staged candle artifact",
    )
    actual_stage_hash = sha256_bytes(candles_raw)
    if recorded_stage_hash != actual_stage_hash:
        raise StagedSchwabChartError(
            "The staged candle artifact hash does not match its manifest."
        )

    selection = require_mapping(manifest.get("selection"), "manifest selection")
    target_report_path = strict_path(
        selection.get("sourcePath"),
        "monitor-target source path",
    )
    target_report_hash = strict_sha256(
        selection.get("sourceSha256"),
        "monitor-target source hash",
    )
    target_raw = read_bounded(
        target_report_path,
        MAX_STAGED_MANIFEST_BYTES,
        "monitor-target source report",
    )
    if sha256_bytes(target_raw) != target_report_hash:
        raise StagedSchwabChartError(
            "The monitor-target source report changed after candle staging."
        )
    symbols = strict_symbols(selection.get("symbols"))
    selected_count = strict_integer(
        selection.get("selectedCount"),
        "selection selectedCount",
    )
    source_count = strict_integer(
        selection.get("sourceTargetCount"),
        "selection sourceTargetCount",
    )
    if selected_count != len(symbols) or source_count < selected_count:
        raise StagedSchwabChartError(
            "The staged candle selection counts are inconsistent."
        )
    if not isinstance(selection.get("truncated"), bool):
        raise StagedSchwabChartError(
            "The staged candle selection omitted its truncation state."
        )

    candles_payload = parse_object(candles_raw, "staged candle artifact")
    require_schema(
        candles_payload,
        STAGED_CANDLE_SCHEMA_VERSION,
        "staged candle artifact",
    )
    require_safety_flags(candles_payload, "staged candle artifact")
    if candles_payload.get("source") != SCHWAB_PRICE_HISTORY_SOURCE:
        raise StagedSchwabChartError(
            "The staged candle artifact has an unexpected provider identity."
        )
    results = parse_results(candles_payload.get("results"), symbols)
    coverage = parse_coverage(manifest.get("coverage"), symbols, results)
    coverage_status = manifest.get("coverageStatus")
    expected_status = (
        "COMPLETE"
        if set(coverage.values()) == {"AVAILABLE"}
        else "PARTIAL"
    )
    if coverage_status != expected_status:
        raise StagedSchwabChartError(
            "The staged candle manifest coverage summary is inconsistent."
        )
    return StagedSchwabArtifact(
        generated_at=timestamp_text(
            strict_timestamp(
                candles_payload.get("generatedAt"),
                "staged candle generatedAt",
            )
        ),
        manifest_generated_at=timestamp_text(
            strict_timestamp(
                manifest.get("generatedAt"),
                "staged manifest generatedAt",
            )
        ),
        selected_symbols=symbols,
        target_report_path=target_report_path,
        target_report_sha256=target_report_hash,
        staged_sha256=actual_stage_hash,
        results=results,
        coverage=coverage,
    )


def parse_results(
    value: object,
    symbols: tuple[str, ...],
) -> dict[tuple[str, str], StagedResult]:
    if not isinstance(value, list):
        raise StagedSchwabChartError(
            "The staged candle artifact omitted its results."
        )
    expected = {
        (symbol, interval)
        for symbol in symbols
        for interval in REQUIRED_INTERVALS
    }
    results: dict[tuple[str, str], StagedResult] = {}
    for raw_result in value:
        item = require_mapping(raw_result, "staged result")
        symbol = strict_symbol(item.get("symbol"))
        interval = str(item.get("interval", ""))
        key = (symbol, interval)
        if key not in expected or key in results:
            raise StagedSchwabChartError(
                "The staged candle result identities are incomplete or duplicated."
            )
        requested_at = strict_timestamp(
            item.get("requestedAt"),
            "staged result requestedAt",
        )
        received_at = strict_timestamp(
            item.get("receivedAt"),
            "staged result receivedAt",
        )
        if received_at < requested_at:
            raise StagedSchwabChartError(
                "A staged candle response predates its request."
            )
        clock = require_mapping(
            item.get("clockSkewProof"),
            "staged result clock proof",
        )
        if clock.get("status") != "PASS":
            raise StagedSchwabChartError(
                "A staged candle result lacks a passing clock proof."
            )
        raw_bars = item.get("bars")
        if not isinstance(raw_bars, list):
            raise StagedSchwabChartError(
                "A staged candle result omitted its bars."
            )
        bars = tuple(
            parse_bar(
                raw_bar,
                expected_symbol=symbol,
                expected_interval=interval,
            )
            for raw_bar in raw_bars
        )
        timestamps = [
            strict_timestamp(bar.timestamp, "staged candle timestamp")
            for bar in bars
        ]
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise StagedSchwabChartError(
                "Staged candle timestamps must be ordered and unique."
            )
        if timestamps and timestamps[-1] > received_at + MAX_FUTURE_BAR:
            raise StagedSchwabChartError(
                "A staged candle is future-dated relative to its response."
            )
        results[key] = StagedResult(
            symbol=symbol,
            interval=interval,
            requested_at=timestamp_text(requested_at),
            received_at=timestamp_text(received_at),
            bars=bars,
        )
    if set(results) != expected:
        raise StagedSchwabChartError(
            "The staged candle results do not cover the selected symbols."
        )
    return results


def parse_bar(
    value: object,
    *,
    expected_symbol: str,
    expected_interval: str,
) -> StagedCandle:
    item = require_mapping(value, "staged candle")
    symbol = strict_symbol(item.get("symbol"))
    interval = str(item.get("interval", ""))
    source = str(item.get("source", ""))
    if (
        symbol != expected_symbol
        or interval != expected_interval
        or source != SCHWAB_PRICE_HISTORY_SOURCE
    ):
        raise StagedSchwabChartError(
            "A staged candle does not match its result identity."
        )
    timestamp = timestamp_text(
        strict_timestamp(item.get("timestamp"), "staged candle timestamp")
    )
    open_value = strict_price(item.get("open"), "open")
    high = strict_price(item.get("high"), "high")
    low = strict_price(item.get("low"), "low")
    close = strict_price(item.get("close"), "close")
    if high < max(open_value, low, close) or low > min(open_value, high, close):
        raise StagedSchwabChartError(
            "A staged candle contains impossible OHLC geometry."
        )
    return StagedCandle(
        symbol=symbol,
        interval=interval,
        timestamp=timestamp,
        open=open_value,
        high=high,
        low=low,
        close=close,
        volume=strict_volume(item.get("volume")),
        source=source,
    )


def parse_coverage(
    value: object,
    symbols: tuple[str, ...],
    results: Mapping[tuple[str, str], StagedResult],
) -> dict[tuple[str, str], str]:
    if not isinstance(value, list):
        raise StagedSchwabChartError(
            "The staged candle manifest omitted coverage evidence."
        )
    expected = {
        (symbol, interval)
        for symbol in symbols
        for interval in REQUIRED_INTERVALS
    }
    coverage: dict[tuple[str, str], str] = {}
    for raw_item in value:
        item = require_mapping(raw_item, "staged coverage")
        key = (strict_symbol(item.get("symbol")), str(item.get("interval", "")))
        if key not in expected or key in coverage:
            raise StagedSchwabChartError(
                "The staged candle coverage identities are incomplete or duplicated."
            )
        state = str(item.get("state", ""))
        if state not in ALLOWED_COVERAGE_STATES:
            raise StagedSchwabChartError(
                "The staged candle coverage state is invalid."
            )
        result = results[key]
        bar_count = strict_integer(item.get("barCount"), "coverage barCount")
        first_bar = str(item.get("firstBar", ""))
        last_bar = str(item.get("lastBar", ""))
        expected_first = result.bars[0].timestamp if result.bars else ""
        expected_last = result.bars[-1].timestamp if result.bars else ""
        if (
            bar_count != len(result.bars)
            or first_bar != expected_first
            or last_bar != expected_last
            or item.get("clockStatus") != "PASS"
        ):
            raise StagedSchwabChartError(
                "The staged candle coverage evidence does not match its bars."
            )
        coverage[key] = state
    if set(coverage) != expected:
        raise StagedSchwabChartError(
            "The staged candle coverage does not cover the selected symbols."
        )
    return coverage


def aggregate_candles(
    candles: Sequence[Mapping[str, Any]],
    bucket_minutes: int,
) -> list[dict[str, Any]]:
    if bucket_minutes not in {5, 15}:
        raise ValueError(f"Unsupported staged candle aggregation: {bucket_minutes}.")
    grouped: dict[datetime, list[tuple[datetime, Mapping[str, Any]]]] = {}
    for candle in candles:
        parsed = strict_timestamp(
            candle.get("timestamp"),
            "staged aggregation timestamp",
        )
        bucket = parsed.replace(
            minute=(parsed.minute // bucket_minutes) * bucket_minutes,
            second=0,
            microsecond=0,
        )
        grouped.setdefault(bucket, []).append((parsed, candle))
    result: list[dict[str, Any]] = []
    for bucket, items in sorted(grouped.items()):
        ordered = [item[1] for item in sorted(items, key=lambda item: item[0])]
        result.append(
            {
                "timestamp": timestamp_text(bucket),
                "open": ordered[0]["open"],
                "high": max(float(item["high"]) for item in ordered),
                "low": min(float(item["low"]) for item in ordered),
                "close": ordered[-1]["close"],
                "volume": sum(int(item["volume"]) for item in ordered),
            }
        )
    return result


def candle_payload(candle: StagedCandle) -> dict[str, Any]:
    return {
        "timestamp": candle.timestamp,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
    }


def snapshot_state(
    *,
    count: int,
    latest: datetime,
    observed_at: datetime,
    interval: str,
    staged_state: str,
) -> str:
    if count < 2 or staged_state == "INSUFFICIENT_DATA":
        return "INSUFFICIENT_DATA"
    stale_after = DAILY_STALE_AFTER if interval == "Daily" else INTRADAY_STALE_AFTER
    if staged_state == "STALE" or observed_at - latest > stale_after:
        return "STALE"
    return "AVAILABLE"


def unavailable_snapshot(
    symbol: str,
    interval: str,
    observed_at: datetime,
    reason: str,
    artifact: StagedSchwabArtifact,
) -> dict[str, Any]:
    return {
        "schemaVersion": CHART_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "interval": interval,
        "state": "UNAVAILABLE",
        "observedAt": timestamp_text(observed_at),
        "asOf": timestamp_text(observed_at),
        "summary": (
            f"STAGED PREVIEW ONLY | UNAVAILABLE | {reason} "
            "No fallback or active chart mutation occurred."
        ),
        "previewOnly": True,
        "activeChartSource": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "lineage": {
            "sourceLabel": "Schwab Trader API price history (inactive staging)",
            "asOf": timestamp_text(observed_at),
            "summary": (
                f"Verified staged artifact {artifact.staged_sha256}; "
                "requested evidence is unavailable."
            ),
        },
        "candles": [],
    }


def require_safety_flags(payload: Mapping[str, Any], label: str) -> None:
    expected = {
        "readOnlyProvider": True,
        "activeChartSource": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
        "accountDataIncluded": False,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise StagedSchwabChartError(
            f"The {label} does not preserve inactive nontransmitting safety flags."
        )


def require_schema(
    payload: Mapping[str, Any],
    expected: int,
    label: str,
) -> None:
    if payload.get("schemaVersion") != expected:
        raise StagedSchwabChartError(
            f"The {label} schema version is unsupported."
        )


def read_bounded(path: Path, maximum: int, label: str) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError:
        raise StagedSchwabChartError(f"The {label} could not be read.") from None
    if not raw or len(raw) > maximum:
        raise StagedSchwabChartError(f"The {label} has an invalid size.")
    return raw


def parse_object(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise StagedSchwabChartError(f"The {label} is not valid JSON.") from None
    return require_mapping(payload, label)


def require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StagedSchwabChartError(f"The {label} has an invalid shape.")
    return value


def strict_symbols(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise StagedSchwabChartError(
            "The staged candle selection omitted its symbols."
        )
    symbols = tuple(strict_symbol(item) for item in value)
    if len(symbols) != len(set(symbols)):
        raise StagedSchwabChartError(
            "The staged candle selection contains duplicate symbols."
        )
    return symbols


def strict_symbol(value: object) -> str:
    if not isinstance(value, str):
        raise StagedSchwabChartError(
            "The staged candle evidence contains an invalid symbol."
        )
    try:
        return normalize_symbol(value)
    except ValueError:
        raise StagedSchwabChartError(
            "The staged candle evidence contains an invalid symbol."
        ) from None


def strict_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise StagedSchwabChartError(f"The {label} is missing.")
    return Path(value).resolve()


def strict_sha256(value: object, label: str) -> str:
    text = str(value).strip().upper()
    if len(text) != 64 or any(character not in "0123456789ABCDEF" for character in text):
        raise StagedSchwabChartError(f"The {label} is invalid.")
    return text


def strict_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise StagedSchwabChartError(f"The {label} is missing.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise StagedSchwabChartError(f"The {label} is invalid.") from None
    return strict_utc(parsed, label)


def strict_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StagedSchwabChartError(f"The {label} must include a UTC offset.")
    return value.astimezone(timezone.utc)


def strict_price(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StagedSchwabChartError(f"A staged candle has an invalid {label}.")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise StagedSchwabChartError(f"A staged candle has an invalid {label}.")
    return result


def strict_volume(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StagedSchwabChartError("A staged candle has invalid volume.")
    result = float(value)
    if not math.isfinite(result) or result < 0 or not result.is_integer():
        raise StagedSchwabChartError("A staged candle has invalid volume.")
    return int(result)


def strict_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StagedSchwabChartError(f"The {label} is invalid.")
    return value


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest().upper()


def timestamp_text(value: datetime) -> str:
    return strict_utc(value, "Timestamp").isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview hash-verified inactive Schwab candles as a chart snapshot."
    )
    parser.add_argument("command", choices=("preview",))
    parser.add_argument("--candles", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--interval",
        choices=("1m", "5m", "15m", "Daily"),
        required=True,
    )
    args = parser.parse_args(argv)
    try:
        snapshot = StagedSchwabChartService(
            paths=StagedSchwabChartPaths(
                candles_path=args.candles,
                manifest_path=args.manifest,
            )
        ).snapshot(args.symbol, args.interval)
    except (StagedSchwabChartError, ValueError) as exc:
        snapshot = {
            "schemaVersion": CHART_SNAPSHOT_SCHEMA_VERSION,
            "status": "FAILED_SAFE",
            "mode": "STAGED_SCHWAB_CHART_PREVIEW",
            "failure": f"{type(exc).__name__}: {exc}",
            "previewOnly": True,
            "activeChartSource": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }
        print(json.dumps(snapshot, indent=2, sort_keys=True))
        return 2
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
