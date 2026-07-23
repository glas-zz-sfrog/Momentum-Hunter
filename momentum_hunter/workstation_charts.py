from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import (
    OPPORTUNITY_MINUTE_BARS_PATH,
    MinutePriceBar,
    load_minute_bars,
)
from momentum_hunter.daily_ohlc import (
    DAILY_OHLC_SOURCE_PATH,
    QUALITY_VALID,
    DailyOhlcRecord,
    normalize_daily_ohlc_payload,
)


CHART_SNAPSHOT_SCHEMA_VERSION = 1
SUPPORTED_CHART_INTERVALS = frozenset({"1m", "5m", "15m", "Daily"})
DEFAULT_MAX_CANDLES = 180
INTRADAY_STALE_AFTER = timedelta(days=1)
DAILY_STALE_AFTER = timedelta(days=7)


@dataclass(frozen=True)
class WorkstationChartPaths:
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH
    daily_ohlc_path: Path = DAILY_OHLC_SOURCE_PATH


class WorkstationChartService:
    """Maps persisted OHLC evidence into a read-only workstation chart contract."""

    def __init__(
        self,
        *,
        paths: WorkstationChartPaths | None = None,
        max_candles: int = DEFAULT_MAX_CANDLES,
    ) -> None:
        self.paths = paths or WorkstationChartPaths()
        self.max_candles = max(2, int(max_candles))
        self._cache_lock = threading.RLock()
        self._daily_signature: tuple[int, int] | None = None
        self._daily_by_symbol: dict[str, list[DailyOhlcRecord]] = {}
        self._daily_error: str | None = None
        self._minute_signature: tuple[int, int] | None = None
        self._minute_by_symbol: dict[str, list[MinutePriceBar]] = {}
        self._minute_error: str | None = None

    def snapshot(
        self,
        symbol: str,
        interval: str,
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        clean_symbol = normalize_symbol(symbol)
        clean_interval = normalize_interval(interval)
        observed_at = as_utc(observed_at or datetime.now(timezone.utc))
        if clean_interval == "Daily":
            candles, source_error = self._daily_candles(clean_symbol)
            source_path = self.paths.daily_ohlc_path
            stale_after = DAILY_STALE_AFTER
        else:
            candles, source_error = self._intraday_candles(clean_symbol, clean_interval)
            source_path = self.paths.minute_bars_path
            stale_after = INTRADAY_STALE_AFTER

        if source_error is not None:
            return unavailable_snapshot(
                clean_symbol,
                clean_interval,
                observed_at,
                source_path,
                source_error,
            )
        if not candles:
            return unavailable_snapshot(
                clean_symbol,
                clean_interval,
                observed_at,
                source_path,
                f"No stored {clean_interval} bars are available for {clean_symbol}.",
            )

        selected = candles[-self.max_candles :]
        latest = parse_timestamp(selected[-1]["timestamp"])
        state = "INSUFFICIENT_DATA" if len(selected) < 2 else "AVAILABLE"
        if state == "AVAILABLE" and latest is not None and observed_at - latest > stale_after:
            state = "STALE"
        as_of = latest or observed_at
        state_label = state.replace("_", " ")
        summary = (
            f"{state_label} | {len(selected)} stored {clean_interval} candle(s) from {source_path.name} | "
            f"as of {timestamp_text(as_of)} | read-only local evidence; no provider fetch"
        )
        return {
            "schemaVersion": CHART_SNAPSHOT_SCHEMA_VERSION,
            "symbol": clean_symbol,
            "interval": clean_interval,
            "state": state,
            "observedAt": timestamp_text(observed_at),
            "asOf": timestamp_text(as_of),
            "summary": summary,
            "lineage": {
                "sourceLabel": source_path.name,
                "asOf": timestamp_text(as_of),
                "summary": f"Read-only local OHLC evidence from {source_path.name}. No bars were fetched, interpolated, or written.",
            },
            "candles": selected,
        }

    def _daily_candles(self, symbol: str) -> tuple[list[dict[str, Any]], str | None]:
        records, error = self._load_daily_records()
        if error is not None:
            return [], error
        candles = [
            {
                "timestamp": f"{record.date}T00:00:00Z",
                "open": record.open,
                "high": record.high,
                "low": record.low,
                "close": record.close,
                "volume": record.volume or 0,
            }
            for record in records.get(symbol, [])
            if record.quality_status == QUALITY_VALID
            and record.open is not None
            and record.high is not None
            and record.low is not None
            and record.close is not None
        ]
        return sorted(candles, key=lambda item: item["timestamp"]), None

    def _intraday_candles(self, symbol: str, interval: str) -> tuple[list[dict[str, Any]], str | None]:
        bars_by_symbol, error = self._load_minute_records()
        if error is not None:
            return [], error
        bars = sorted(
            bars_by_symbol.get(symbol, []),
            key=lambda item: parse_timestamp(item.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
        )
        if interval == "1m":
            return [minute_candle(bar) for bar in bars], None
        bucket_minutes = int(interval.removesuffix("m"))
        return aggregate_minute_bars(bars, bucket_minutes), None

    def _load_daily_records(self) -> tuple[dict[str, list[DailyOhlcRecord]], str | None]:
        with self._cache_lock:
            signature = file_signature(self.paths.daily_ohlc_path)
            if signature is None:
                return {}, f"Stored daily OHLC source is missing: {self.paths.daily_ohlc_path.name}."
            if signature == self._daily_signature:
                return self._daily_by_symbol, self._daily_error
            try:
                payload = json.loads(self.paths.daily_ohlc_path.read_text(encoding="utf-8"))
                imported_at = str(payload.get("generated_at", "")) if isinstance(payload, dict) else ""
                records = normalize_daily_ohlc_payload(payload, imported_at=imported_at)
                grouped: dict[str, list[DailyOhlcRecord]] = {}
                for record in records:
                    if record.quality_status == QUALITY_VALID:
                        grouped.setdefault(record.symbol, []).append(record)
                for items in grouped.values():
                    items.sort(key=lambda item: item.date)
                self._daily_by_symbol = grouped
                self._daily_error = None
            except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
                self._daily_by_symbol = {}
                self._daily_error = f"Stored daily OHLC source is unreadable: {type(exc).__name__}."
            self._daily_signature = signature
            return self._daily_by_symbol, self._daily_error

    def _load_minute_records(self) -> tuple[dict[str, list[MinutePriceBar]], str | None]:
        with self._cache_lock:
            signature = file_signature(self.paths.minute_bars_path)
            if signature is None:
                return {}, f"Stored minute-bar source is missing: {self.paths.minute_bars_path.name}."
            if signature == self._minute_signature:
                return self._minute_by_symbol, self._minute_error
            try:
                self._minute_by_symbol = load_minute_bars(self.paths.minute_bars_path)
                self._minute_error = None
            except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
                self._minute_by_symbol = {}
                self._minute_error = f"Stored minute-bar source is unreadable: {type(exc).__name__}."
            self._minute_signature = signature
            return self._minute_by_symbol, self._minute_error


def aggregate_minute_bars(bars: list[MinutePriceBar], bucket_minutes: int) -> list[dict[str, Any]]:
    if bucket_minutes not in {5, 15}:
        raise ValueError(f"Unsupported minute aggregation: {bucket_minutes}.")
    grouped: dict[datetime, list[tuple[datetime, MinutePriceBar]]] = {}
    for bar in bars:
        parsed = parse_timestamp(bar.timestamp)
        if parsed is None:
            continue
        bucket = parsed.replace(
            minute=(parsed.minute // bucket_minutes) * bucket_minutes,
            second=0,
            microsecond=0,
        )
        grouped.setdefault(bucket, []).append((parsed, bar))

    candles: list[dict[str, Any]] = []
    for bucket, items in sorted(grouped.items()):
        ordered = [item[1] for item in sorted(items, key=lambda item: item[0])]
        candles.append(
            {
                "timestamp": timestamp_text(bucket),
                "open": ordered[0].open,
                "high": max(item.high for item in ordered),
                "low": min(item.low for item in ordered),
                "close": ordered[-1].close,
                "volume": sum(item.volume or 0 for item in ordered),
            }
        )
    return candles


def minute_candle(bar: MinutePriceBar) -> dict[str, Any]:
    parsed = parse_timestamp(bar.timestamp)
    return {
        "timestamp": timestamp_text(parsed) if parsed is not None else bar.timestamp,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume or 0,
    }


def unavailable_snapshot(
    symbol: str,
    interval: str,
    observed_at: datetime,
    source_path: Path,
    reason: str,
) -> dict[str, Any]:
    summary = f"UNAVAILABLE | {reason} No simulated or cross-timeframe fallback was created."
    return {
        "schemaVersion": CHART_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "interval": interval,
        "state": "UNAVAILABLE",
        "observedAt": timestamp_text(observed_at),
        "asOf": timestamp_text(observed_at),
        "summary": summary,
        "lineage": {
            "sourceLabel": source_path.name,
            "asOf": timestamp_text(observed_at),
            "summary": f"Expected read-only local OHLC evidence from {source_path.name}; source data was unavailable.",
        },
        "candles": [],
    }


def normalize_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper()
    if not normalized or len(normalized) > 12 or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for character in normalized):
        raise ValueError("Chart symbol must contain 1-12 ticker characters.")
    return normalized


def normalize_interval(interval: str) -> str:
    normalized = str(interval).strip()
    if normalized not in SUPPORTED_CHART_INTERVALS:
        raise ValueError(f"Unsupported chart interval: {normalized or '<empty>'}.")
    return normalized


def file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return as_utc(parsed)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")
