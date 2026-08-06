from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from momentum_hunter.daily_ohlc import (
    DAILY_OHLC_SOURCE_PATH,
    QUALITY_VALID,
    DailyOhlcRecord,
    normalize_daily_ohlc_payload,
)
from momentum_hunter.schwab_candle_store import (
    SCHWAB_CANDLE_STORE_ROOT,
    SchwabCandleStore,
    SchwabCandleStoreError,
)


CHART_SNAPSHOT_SCHEMA_VERSION = 2
SUPPORTED_CHART_INTERVALS = frozenset({"1m", "5m", "15m", "Daily"})
DEFAULT_MAX_CANDLES = 180
MAX_INTRADAY_SESSION_PARTITIONS = 10
INTRADAY_STALE_AFTER = timedelta(seconds=180)
DAILY_STALE_AFTER = timedelta(days=7)
SCHWAB_PROVIDER_LABEL = "Schwab Trader API"
SCHWAB_INTRADAY_SOURCE_LABEL = "Schwab CHART_EQUITY + price history"
DAILY_SOURCE_LABEL = "Stored daily OHLC"


@dataclass(frozen=True)
class WorkstationChartPaths:
    schwab_candle_store_root: Path = SCHWAB_CANDLE_STORE_ROOT
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
        self._candle_store = SchwabCandleStore(self.paths.schwab_candle_store_root)
        self._cache_lock = threading.RLock()
        self._daily_signature: tuple[int, int] | None = None
        self._daily_by_symbol: dict[str, list[DailyOhlcRecord]] = {}
        self._daily_error: str | None = None

    def snapshot(
        self,
        symbol: str,
        interval: str,
        *,
        observed_at: datetime | None = None,
    ) -> dict[str, Any]:
        clean_symbol = normalize_symbol(symbol)
        clean_interval = normalize_interval(interval)
        observed = as_utc(observed_at or datetime.now(timezone.utc))
        if clean_interval == "Daily":
            return self._daily_snapshot(clean_symbol, observed)
        return self._intraday_snapshot(clean_symbol, clean_interval, observed)

    def _daily_snapshot(self, symbol: str, observed_at: datetime) -> dict[str, Any]:
        records, error = self._load_daily_records()
        if error is not None:
            return unavailable_snapshot(
                symbol,
                "Daily",
                observed_at,
                DAILY_SOURCE_LABEL,
                self.paths.daily_ohlc_path,
                error,
            )
        candles = [
            {
                "timestamp": f"{record.date}T00:00:00Z",
                "open": record.open,
                "high": record.high,
                "low": record.low,
                "close": record.close,
                "volume": record.volume or 0,
                "state": "DAILY_SOURCE",
                "source": str(record.source or self.paths.daily_ohlc_path.name),
                "providerTimestamp": f"{record.date}T00:00:00Z",
                "receivedAt": None,
                "isCanonical": True,
                "isInProgress": False,
                "hasGapBefore": False,
                "discrepancyFields": [],
                "presentMinuteCount": 1,
                "expectedMinuteCount": 1,
            }
            for record in records.get(symbol, [])
            if record.quality_status == QUALITY_VALID
            and record.open is not None
            and record.high is not None
            and record.low is not None
            and record.close is not None
        ]
        candles.sort(key=lambda item: str(item["timestamp"]))
        if not candles:
            return unavailable_snapshot(
                symbol,
                "Daily",
                observed_at,
                DAILY_SOURCE_LABEL,
                self.paths.daily_ohlc_path,
                f"No stored Daily bars are available for {symbol}.",
            )
        return available_snapshot(
            symbol=symbol,
            interval="Daily",
            observed_at=observed_at,
            candles=candles[-self.max_candles :],
            source_label=DAILY_SOURCE_LABEL,
            source_path=self.paths.daily_ohlc_path,
            provider="Persisted daily OHLC source",
            session_dates=tuple(sorted({str(item["timestamp"])[:10] for item in candles})),
            stale_after=DAILY_STALE_AFTER,
        )

    def _intraday_snapshot(
        self,
        symbol: str,
        interval: str,
        observed_at: datetime,
    ) -> dict[str, Any]:
        candles, session_dates, error = self._load_intraday_candles(symbol)
        if error is not None:
            return unavailable_snapshot(
                symbol,
                interval,
                observed_at,
                SCHWAB_INTRADAY_SOURCE_LABEL,
                self.paths.schwab_candle_store_root,
                error,
            )
        if interval != "1m":
            candles = aggregate_schwab_minute_candles(
                candles,
                int(interval.removesuffix("m")),
            )
        if not candles:
            return unavailable_snapshot(
                symbol,
                interval,
                observed_at,
                SCHWAB_INTRADAY_SOURCE_LABEL,
                self.paths.schwab_candle_store_root,
                f"No stored {interval} Schwab bars are available for {symbol}.",
            )
        return available_snapshot(
            symbol=symbol,
            interval=interval,
            observed_at=observed_at,
            candles=candles[-self.max_candles :],
            source_label=SCHWAB_INTRADAY_SOURCE_LABEL,
            source_path=self.paths.schwab_candle_store_root,
            provider=SCHWAB_PROVIDER_LABEL,
            session_dates=session_dates,
            stale_after=INTRADAY_STALE_AFTER,
        )

    def _load_intraday_candles(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], tuple[str, ...], str | None]:
        root = self.paths.schwab_candle_store_root
        if not root.exists():
            return [], (), f"Stored Schwab candle source is missing: {root.name}."
        try:
            session_dates = available_session_dates(root, symbol)
            selected_dates = session_dates[-MAX_INTRADAY_SESSION_PARTITIONS:]
            candles: list[dict[str, Any]] = []
            for session_date in selected_dates:
                partition = self._candle_store.load_partition(symbol, session_date)
                candles.extend(project_partition_bars(partition))
            candles.sort(key=lambda item: str(item["timestamp"]))
            mark_intraday_gaps(candles)
            return candles, tuple(selected_dates), None
        except (OSError, SchwabCandleStoreError, TypeError, ValueError) as exc:
            return (
                [],
                (),
                f"Stored Schwab candle source is unreadable or untrusted: {type(exc).__name__}.",
            )

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


def available_session_dates(root: Path, symbol: str) -> list[str]:
    dates: list[str] = []
    normalized = normalize_symbol(symbol)
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            parsed = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (child / f"{normalized}.json").is_file():
            dates.append(parsed.isoformat())
    return sorted(set(dates))


def project_partition_bars(partition: Mapping[str, object]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for raw_bar in partition.get("bars", []):
        if not isinstance(raw_bar, Mapping):
            raise SchwabCandleStoreError("Schwab chart source contained an invalid bar.")
        canonical = raw_bar.get("canonicalCandle")
        history_versions = raw_bar.get("historyVersions")
        stream_versions = raw_bar.get("streamVersions")
        if isinstance(canonical, Mapping):
            candle = canonical
            version = latest_version(history_versions)
            is_canonical = True
        else:
            version = latest_version(stream_versions)
            candle = version.get("candle")
            is_canonical = False
        if not isinstance(candle, Mapping):
            raise SchwabCandleStoreError("Schwab chart bar omitted displayable candle evidence.")
        state = str(raw_bar.get("state", ""))
        projected.append(
            {
                "timestamp": timestamp_text(required_timestamp(candle.get("timestamp"))),
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
                "volume": candle.get("volume"),
                "state": state,
                "source": str(candle.get("source", "UNAVAILABLE")),
                "providerTimestamp": timestamp_text(required_timestamp(candle.get("timestamp"))),
                "receivedAt": timestamp_text(required_timestamp(version.get("firstReceivedAt"))),
                "isCanonical": is_canonical,
                "isInProgress": state == "IN_PROGRESS",
                "hasGapBefore": False,
                "discrepancyFields": list(raw_bar.get("discrepancyFields", [])),
                "presentMinuteCount": 1,
                "expectedMinuteCount": 1,
                "sessionDate": str(partition.get("sessionDate", "")),
            }
        )
    return projected


def latest_version(value: object) -> Mapping[str, object]:
    if not isinstance(value, list) or not value:
        raise SchwabCandleStoreError("Schwab chart bar omitted its selected source version.")
    version = value[-1]
    if not isinstance(version, Mapping):
        raise SchwabCandleStoreError("Schwab chart bar source version was invalid.")
    return version


def mark_intraday_gaps(candles: list[dict[str, Any]]) -> None:
    previous: dict[str, Any] | None = None
    for candle in candles:
        if previous is not None and candle.get("sessionDate") == previous.get("sessionDate"):
            current_at = required_timestamp(candle["timestamp"])
            previous_at = required_timestamp(previous["timestamp"])
            candle["hasGapBefore"] = current_at - previous_at > timedelta(minutes=1)
        previous = candle


def aggregate_schwab_minute_candles(
    candles: list[dict[str, Any]],
    bucket_minutes: int,
) -> list[dict[str, Any]]:
    if bucket_minutes not in {5, 15}:
        raise ValueError(f"Unsupported minute aggregation: {bucket_minutes}.")
    grouped: dict[tuple[str, datetime], list[dict[str, Any]]] = {}
    for candle in candles:
        parsed = required_timestamp(candle["timestamp"])
        bucket = parsed.replace(
            minute=(parsed.minute // bucket_minutes) * bucket_minutes,
            second=0,
            microsecond=0,
        )
        grouped.setdefault((str(candle.get("sessionDate", "")), bucket), []).append(candle)

    aggregated: list[dict[str, Any]] = []
    for (session_date, bucket), items in sorted(grouped.items(), key=lambda item: item[0][1]):
        ordered = sorted(items, key=lambda item: str(item["timestamp"]))
        states = {str(item["state"]) for item in ordered}
        sources = {str(item["source"]) for item in ordered}
        discrepancy_fields = sorted(
            {
                str(field)
                for item in ordered
                for field in item.get("discrepancyFields", [])
            }
        )
        has_missing_minute = len(ordered) < bucket_minutes or any(
            bool(item.get("hasGapBefore")) for item in ordered
        )
        state = aggregate_state(states, has_missing_minute=has_missing_minute)
        aggregated.append(
            {
                "timestamp": timestamp_text(bucket),
                "open": ordered[0]["open"],
                "high": max(float(item["high"]) for item in ordered),
                "low": min(float(item["low"]) for item in ordered),
                "close": ordered[-1]["close"],
                "volume": sum(float(item["volume"]) for item in ordered),
                "state": state,
                "source": next(iter(sources)) if len(sources) == 1 else "SCHWAB_MIXED_RECONCILED_PROVISIONAL",
                "providerTimestamp": ordered[-1]["providerTimestamp"],
                "receivedAt": max(str(item["receivedAt"]) for item in ordered),
                "isCanonical": len(ordered) == bucket_minutes
                and all(bool(item["isCanonical"]) for item in ordered),
                "isInProgress": "IN_PROGRESS" in states,
                "hasGapBefore": has_missing_minute,
                "discrepancyFields": discrepancy_fields,
                "presentMinuteCount": len(ordered),
                "expectedMinuteCount": bucket_minutes,
                "sessionDate": session_date,
            }
        )
    return aggregated


def aggregate_state(states: set[str], *, has_missing_minute: bool) -> str:
    if "IN_PROGRESS" in states:
        return "IN_PROGRESS"
    if "COMPLETED_UNRECONCILED" in states:
        return "COMPLETED_UNRECONCILED"
    if has_missing_minute:
        return "GAP"
    if "CORRECTED" in states:
        return "CORRECTED"
    if "HISTORY_ONLY_GAP_FILL" in states:
        return "HISTORY_ONLY_GAP_FILL"
    return "RECONCILED"


def available_snapshot(
    *,
    symbol: str,
    interval: str,
    observed_at: datetime,
    candles: list[dict[str, Any]],
    source_label: str,
    source_path: Path,
    provider: str,
    session_dates: tuple[str, ...],
    stale_after: timedelta,
) -> dict[str, Any]:
    latest = required_timestamp(candles[-1]["timestamp"])
    interval_minutes = interval_duration_minutes(interval)
    age_seconds = max(
        0.0,
        (observed_at - (latest + timedelta(minutes=interval_minutes))).total_seconds(),
    )
    stale = age_seconds > stale_after.total_seconds()
    gap_count = sum(bool(item.get("hasGapBefore")) for item in candles)
    corrected_count = sum(str(item.get("state")) == "CORRECTED" for item in candles)
    unreconciled_count = sum(
        str(item.get("state")) == "COMPLETED_UNRECONCILED" for item in candles
    )
    in_progress = [item for item in candles if bool(item.get("isInProgress"))]
    completed = [item for item in candles if not bool(item.get("isInProgress"))]
    latest_completed = completed[-1] if completed else None
    latest_in_progress = in_progress[-1] if in_progress else None
    if len(candles) < 2:
        state = "INSUFFICIENT_DATA"
    elif stale:
        state = "STALE"
    elif gap_count or unreconciled_count:
        state = "PARTIAL"
    else:
        state = "AVAILABLE"
    findings: list[str] = []
    if stale:
        findings.append("STALE")
    if gap_count:
        findings.append(f"GAPS:{gap_count}")
    if corrected_count:
        findings.append(f"CORRECTIONS:{corrected_count}")
    if unreconciled_count:
        findings.append(f"UNRECONCILED:{unreconciled_count}")
    if latest_in_progress is not None:
        findings.append("IN_PROGRESS_BAR_PRESENT")
    if len(candles) < 2:
        findings.append("INSUFFICIENT_DATA")

    state_label = state.replace("_", " ")
    summary = (
        f"{state_label} | {provider} | {len(candles)} stored {interval} candle(s) | "
        f"as of {timestamp_text(latest)} | read-only persisted evidence"
    )
    latest_receipt = max(
        (
            required_timestamp(item["receivedAt"])
            for item in candles
            if item.get("receivedAt")
        ),
        default=None,
    )
    return {
        "schemaVersion": CHART_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "interval": interval,
        "state": state,
        "observedAt": timestamp_text(observed_at),
        "asOf": timestamp_text(latest),
        "summary": summary,
        "lineage": {
            "sourceLabel": source_label,
            "asOf": timestamp_text(latest),
            "summary": (
                f"Read-only OHLC evidence from {source_path.name}. "
                "No provider call, legacy candle, interpolation, or cross-timeframe fallback was used."
            ),
        },
        "quality": {
            "provider": provider,
            "sourceLabel": source_label,
            "status": state,
            "sessionDates": list(session_dates),
            "latestCompletedBarAt": optional_timestamp(latest_completed, "timestamp"),
            "latestInProgressBarAt": optional_timestamp(latest_in_progress, "timestamp"),
            "latestProviderTimestamp": optional_timestamp(candles[-1], "providerTimestamp"),
            "latestReceiptAt": timestamp_text(latest_receipt) if latest_receipt else None,
            "ageSeconds": round(age_seconds, 3),
            "stale": stale,
            "gapCount": gap_count,
            "correctionCount": corrected_count,
            "unreconciledCount": unreconciled_count,
            "inProgressCount": len(in_progress),
            "completedCount": len(completed),
            "findings": findings,
        },
        "candles": candles,
    }


def unavailable_snapshot(
    symbol: str,
    interval: str,
    observed_at: datetime,
    source_label: str,
    source_path: Path,
    reason: str,
) -> dict[str, Any]:
    summary = f"UNAVAILABLE | {reason} No simulated, legacy, or cross-timeframe fallback was created."
    return {
        "schemaVersion": CHART_SNAPSHOT_SCHEMA_VERSION,
        "symbol": symbol,
        "interval": interval,
        "state": "UNAVAILABLE",
        "observedAt": timestamp_text(observed_at),
        "asOf": timestamp_text(observed_at),
        "summary": summary,
        "lineage": {
            "sourceLabel": source_label,
            "asOf": timestamp_text(observed_at),
            "summary": f"Expected read-only OHLC evidence from {source_path.name}; source data was unavailable.",
        },
        "quality": {
            "provider": "UNAVAILABLE",
            "sourceLabel": source_label,
            "status": "UNAVAILABLE",
            "sessionDates": [],
            "latestCompletedBarAt": None,
            "latestInProgressBarAt": None,
            "latestProviderTimestamp": None,
            "latestReceiptAt": None,
            "ageSeconds": None,
            "stale": True,
            "gapCount": 0,
            "correctionCount": 0,
            "unreconciledCount": 0,
            "inProgressCount": 0,
            "completedCount": 0,
            "findings": ["SOURCE_UNAVAILABLE"],
        },
        "candles": [],
    }


def optional_timestamp(item: Mapping[str, Any] | None, field: str) -> str | None:
    if item is None or not item.get(field):
        return None
    return timestamp_text(required_timestamp(item[field]))


def normalize_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper()
    if not normalized or len(normalized) > 12 or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
        for character in normalized
    ):
        raise ValueError("Chart symbol must contain 1-12 ticker characters.")
    return normalized


def normalize_interval(interval: str) -> str:
    normalized = str(interval).strip()
    if normalized not in SUPPORTED_CHART_INTERVALS:
        raise ValueError(f"Unsupported chart interval: {normalized or '<empty>'}.")
    return normalized


def interval_duration_minutes(interval: str) -> int:
    if interval == "Daily":
        return 24 * 60
    return int(interval.removesuffix("m"))


def file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def required_timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Chart evidence timestamp was invalid.") from exc
    return as_utc(parsed)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def timestamp_text(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")
