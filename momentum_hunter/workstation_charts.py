from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo

from momentum_hunter.schwab_candle_store import (
    SCHWAB_CANDLE_STORE_ROOT,
    SchwabCandleStore,
    SchwabCandleStoreError,
)
from momentum_hunter.schwab_daily_candle_store import (
    SCHWAB_DAILY_CANDLE_STORE_ROOT,
    SchwabDailyCandleStore,
    SchwabDailyCandleStoreError,
)


CHART_SNAPSHOT_SCHEMA_VERSION = 2
SUPPORTED_CHART_INTERVALS = frozenset({"1m", "5m", "15m", "Daily"})
DEFAULT_MAX_CANDLES = 180
MAX_INTRADAY_SESSION_PARTITIONS = 10
INTRADAY_STALE_AFTER = timedelta(seconds=180)
DAILY_STALE_AFTER = timedelta(days=7)
SCHWAB_PROVIDER_LABEL = "Schwab Trader API"
SCHWAB_INTRADAY_SOURCE_LABEL = "Schwab CHART_EQUITY + price history"
SCHWAB_DAILY_SOURCE_LABEL = "Schwab price history daily OHLC"
EASTERN_TZ = ZoneInfo("America/New_York")
MIN_HISTORY_CANDLES = {"1m": 30, "5m": 12, "15m": 8, "Daily": 20}


class CandleBackfillCoordinator(Protocol):
    def request(self, symbol: str, *, reason: str) -> dict[str, object]: ...

    def status(self, symbol: str) -> dict[str, object] | None: ...


@dataclass(frozen=True)
class WorkstationChartPaths:
    schwab_candle_store_root: Path = SCHWAB_CANDLE_STORE_ROOT
    schwab_daily_candle_store_root: Path = SCHWAB_DAILY_CANDLE_STORE_ROOT


class WorkstationChartService:
    """Maps persisted OHLC evidence into a read-only workstation chart contract."""

    def __init__(
        self,
        *,
        paths: WorkstationChartPaths | None = None,
        max_candles: int = DEFAULT_MAX_CANDLES,
        backfill_coordinator: CandleBackfillCoordinator | None = None,
    ) -> None:
        self.paths = paths or WorkstationChartPaths()
        self.max_candles = max(2, int(max_candles))
        self.backfill_coordinator = backfill_coordinator
        self._candle_store = SchwabCandleStore(self.paths.schwab_candle_store_root)
        self._daily_candle_store = SchwabDailyCandleStore(
            self.paths.schwab_daily_candle_store_root
        )

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
            snapshot = self._daily_snapshot(clean_symbol, observed)
        else:
            snapshot = self._intraday_snapshot(clean_symbol, clean_interval, observed)
        return self._attach_history_load(snapshot, observed)

    def _attach_history_load(
        self,
        snapshot: dict[str, Any],
        observed_at: datetime,
    ) -> dict[str, Any]:
        reason = history_request_reason(snapshot, observed_at=observed_at)
        if self.backfill_coordinator is None:
            summary = str(snapshot.get("summary", ""))
            if "unreadable or untrusted" in summary:
                detail = "Untrusted stored candle evidence is never repaired automatically."
            else:
                detail = "Automatic candle history loading is not enabled for this chart service."
            history_load = {
                "status": "NOT_REQUESTED",
                "detail": detail,
            }
        elif reason is None:
            summary = str(snapshot.get("summary", ""))
            if "unreadable or untrusted" in summary:
                history_load = {
                    "status": "NOT_REQUESTED",
                    "detail": "Untrusted stored candle evidence is never repaired automatically.",
                }
            else:
                previous = self.backfill_coordinator.status(str(snapshot["symbol"]))
                if previous is not None and str(previous.get("status")) in {
                    "QUEUED",
                    "RUNNING",
                    "COMPLETE",
                }:
                    history_load = previous
                else:
                    history_load = {
                        "status": "NOT_REQUESTED",
                        "detail": "Stored candle history satisfies the automatic-load gate.",
                    }
        else:
            history_load = self.backfill_coordinator.request(
                str(snapshot["symbol"]),
                reason=reason,
            )
        snapshot["historyLoad"] = history_load
        quality = snapshot.get("quality")
        if isinstance(quality, dict):
            status = str(history_load.get("status", "NOT_REQUESTED"))
            quality["historyLoadStatus"] = status
            quality["historyLoadDetail"] = str(history_load.get("detail", ""))
            if status in {"QUEUED", "RUNNING"}:
                quality["findings"] = [*quality.get("findings", []), f"HISTORY_LOAD_{status}"]
                snapshot["summary"] = f"LOADING HISTORY | {snapshot['summary']}"
            elif status in {"PARTIAL", "FAILED"}:
                quality["findings"] = [*quality.get("findings", []), f"HISTORY_LOAD_{status}"]
        return snapshot

    def _daily_snapshot(self, symbol: str, observed_at: datetime) -> dict[str, Any]:
        candles, error = self._load_daily_candles(symbol)
        if error is not None:
            return unavailable_snapshot(
                symbol,
                "Daily",
                observed_at,
                SCHWAB_DAILY_SOURCE_LABEL,
                self.paths.schwab_daily_candle_store_root,
                error,
            )
        if not candles:
            return unavailable_snapshot(
                symbol,
                "Daily",
                observed_at,
                SCHWAB_DAILY_SOURCE_LABEL,
                self.paths.schwab_daily_candle_store_root,
                f"No stored Daily Schwab bars are available for {symbol}.",
            )
        return available_snapshot(
            symbol=symbol,
            interval="Daily",
            observed_at=observed_at,
            candles=candles[-self.max_candles :],
            source_label=SCHWAB_DAILY_SOURCE_LABEL,
            source_path=self.paths.schwab_daily_candle_store_root,
            provider=SCHWAB_PROVIDER_LABEL,
            session_dates=tuple(sorted({str(item["sessionDate"]) for item in candles})),
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

    def _load_daily_candles(
        self,
        symbol: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        root = self.paths.schwab_daily_candle_store_root
        path = self._daily_candle_store.symbol_path(symbol)
        if not root.exists():
            return [], f"Stored Schwab daily source is missing: {root.name}."
        if not path.is_file():
            return [], f"No stored Daily Schwab bars are available for {symbol}."
        try:
            payload = self._daily_candle_store.load_symbol(symbol)
            candles = project_daily_bars(payload)
            candles.sort(key=lambda item: str(item["timestamp"]))
            return candles, None
        except (OSError, SchwabDailyCandleStoreError, TypeError, ValueError) as exc:
            return (
                [],
                f"Stored Schwab daily source is unreadable or untrusted: {type(exc).__name__}.",
            )


def project_daily_bars(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for raw_bar in payload.get("bars", []):
        if not isinstance(raw_bar, Mapping):
            raise SchwabDailyCandleStoreError("Schwab daily chart bar was invalid.")
        candle = raw_bar.get("canonicalCandle")
        versions = raw_bar.get("historyVersions")
        if not isinstance(candle, Mapping) or not isinstance(versions, list) or not versions:
            raise SchwabDailyCandleStoreError(
                "Schwab daily chart bar omitted canonical evidence."
            )
        latest_version = versions[-1]
        first_version = versions[0]
        if not isinstance(latest_version, Mapping) or not isinstance(first_version, Mapping):
            raise SchwabDailyCandleStoreError("Schwab daily chart version was invalid.")
        first_candle = first_version.get("candle")
        if not isinstance(first_candle, Mapping):
            raise SchwabDailyCandleStoreError(
                "Schwab daily chart version omitted candle evidence."
            )
        discrepancy_fields = [
            field
            for field in ("open", "high", "low", "close", "volume")
            if first_candle.get(field) != candle.get(field)
        ]
        timestamp = str(candle.get("timestamp", ""))
        required_timestamp(timestamp)
        projected.append(
            {
                "timestamp": timestamp,
                "sessionDate": str(candle.get("sessionDate", "")),
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
                "volume": candle.get("volume"),
                "state": str(raw_bar.get("state", "CANONICAL")),
                "source": str(candle.get("source", "")),
                "providerTimestamp": timestamp,
                "receivedAt": str(latest_version.get("firstReceivedAt", "")),
                "isCanonical": True,
                "isInProgress": False,
                "hasGapBefore": False,
                "discrepancyFields": discrepancy_fields,
                "presentMinuteCount": 1,
                "expectedMinuteCount": 1,
            }
        )
    return projected


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


def history_request_reason(
    snapshot: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> str | None:
    state = str(snapshot.get("state", "UNAVAILABLE"))
    summary = str(snapshot.get("summary", ""))
    interval = str(snapshot.get("interval", ""))
    candles = snapshot.get("candles")
    candle_count = len(candles) if isinstance(candles, list) else 0
    if "unreadable or untrusted" in summary:
        return None
    if state == "UNAVAILABLE":
        return f"No stored {interval} history is available."
    minimum = MIN_HISTORY_CANDLES.get(interval, 2)
    if candle_count < minimum:
        return f"Stored {interval} history has {candle_count} candle(s); at least {minimum} are required."
    if state == "STALE" and _within_extended_market_window(observed_at):
        return f"Stored {interval} history is stale during the extended market window."
    return None


def _within_extended_market_window(observed_at: datetime) -> bool:
    eastern = as_utc(observed_at).astimezone(EASTERN_TZ)
    if eastern.weekday() >= 5:
        return False
    minute = eastern.hour * 60 + eastern.minute
    return 4 * 60 <= minute <= 20 * 60 + 5


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
