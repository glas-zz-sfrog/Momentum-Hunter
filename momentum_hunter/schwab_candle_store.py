"""Partitioned evidence store for reconciled Schwab one-minute candles."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_CHART_EQUITY_SOURCE,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabMinuteCandle,
    SchwabStreamCandleObservation,
    normalize_symbols,
    session_for_timestamp,
)


SCHWAB_CANDLE_STORE_SCHEMA_VERSION = 1
SCHWAB_CANDLE_STORE_KIND = "SCHWAB_INCREMENTAL_MINUTE_CANDLES"
SCHWAB_CANDLE_STORE_ROOT = DATA_DIR / "schwab-candles-v1"
MAX_PARTITION_BYTES = 16 * 1024 * 1024
ONE_MINUTE = timedelta(minutes=1)
BAR_STATES = frozenset(
    {
        "IN_PROGRESS",
        "COMPLETED_UNRECONCILED",
        "RECONCILED",
        "CORRECTED",
        "HISTORY_ONLY_GAP_FILL",
    }
)


class SchwabCandleStoreError(RuntimeError):
    """Raised when candle evidence cannot be preserved without ambiguity."""


@dataclass(frozen=True)
class CandleStoreMutation:
    inserted_count: int
    duplicate_count: int
    partition_count: int
    affected_minutes: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.inserted_count > 0


@dataclass(frozen=True)
class CandleStoreHealth:
    symbol: str
    status: str
    latest_minute: datetime | None
    latest_received_at: datetime | None
    stale: bool
    gap_count: int
    unreconciled_count: int
    corrected_count: int
    canonical_count: int


class CandleStoreLease:
    """Cross-process writer lease released automatically on process death."""

    def __init__(self, root: Path, *, acquired_at: datetime | None = None) -> None:
        self.root = root.resolve(strict=False)
        self.path = self.root / ".collector.lock"
        self.acquired_at = _aware(acquired_at or datetime.now(timezone.utc))
        self.token = uuid.uuid4().hex
        self._held = False
        self._handle: object | None = None

    def acquire(self) -> "CandleStoreLease":
        self.root.mkdir(parents=True, exist_ok=True)
        payload = _canonical_json_bytes(
            {
                "schemaVersion": 1,
                "token": self.token,
                "processId": os.getpid(),
                "acquiredAt": self.acquired_at.isoformat(),
            }
        )
        try:
            handle = self.path.open("x+b", buffering=0)
        except FileExistsError:
            handle = self.path.open("r+b", buffering=0)
        try:
            _lock_handle(handle)
        except OSError as exc:
            handle.close()
            raise SchwabCandleStoreError(
                "Schwab candle store already has an active writer lease."
            ) from exc
        try:
            handle.seek(1)
            handle.truncate()
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            _unlock_handle(handle)
            handle.close()
            raise
        self._handle = handle
        self._held = True
        return self

    def release(self) -> None:
        if not self._held:
            return
        handle = self._handle
        if handle is None:
            raise SchwabCandleStoreError(
                "Schwab candle writer lease lost its operating-system handle."
            )
        _unlock_handle(handle)
        handle.close()
        self._handle = None
        self._held = False

    def __enter__(self) -> "CandleStoreLease":
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()


class SchwabCandleStore:
    """Atomic daily/symbol partitions with immutable source-version identities."""

    def __init__(self, root: Path = SCHWAB_CANDLE_STORE_ROOT) -> None:
        self.root = root.resolve(strict=False)
        legacy = OPPORTUNITY_MINUTE_BARS_PATH.resolve(strict=False)
        if _same_or_ancestor(self.root, legacy) or self.root == legacy:
            raise SchwabCandleStoreError(
                "Schwab candle storage must not contain the legacy minute-bar cache."
            )
        self._lock = threading.RLock()

    def lease(self, *, acquired_at: datetime | None = None) -> CandleStoreLease:
        return CandleStoreLease(self.root, acquired_at=acquired_at)

    def append_stream(
        self,
        observations: Sequence[SchwabStreamCandleObservation],
    ) -> CandleStoreMutation:
        inserted = 0
        duplicates = 0
        affected: set[str] = set()
        touched: set[Path] = set()
        grouped: dict[tuple[str, str], list[SchwabStreamCandleObservation]] = {}
        for observation in observations:
            candle = observation.candle
            if candle.source != SCHWAB_CHART_EQUITY_SOURCE:
                raise SchwabCandleStoreError(
                    "Schwab stream storage rejected a non-CHART_EQUITY source."
                )
            session_date = candle.timestamp.astimezone(EASTERN_TZ).date().isoformat()
            grouped.setdefault((session_date, candle.symbol), []).append(observation)

        with self._lock:
            for (session_date, symbol), items in sorted(grouped.items()):
                path = self.partition_path(symbol, session_date)
                partition = self._load_partition(path, symbol, session_date)
                bars = _bars_by_identity(partition)
                partition_changed = False
                for observation in items:
                    minute_id = minute_identity(observation.candle)
                    bar = bars.setdefault(
                        minute_id,
                        _new_bar(observation.candle),
                    )
                    version = _stream_version(observation)
                    existing = {
                        str(item["versionId"]): item
                        for item in bar["streamVersions"]
                    }
                    current = existing.get(str(version["versionId"]))
                    if current is not None:
                        if _semantic_version(current) != _semantic_version(version):
                            raise SchwabCandleStoreError(
                                "A stream version identity was reused with conflicting evidence."
                            )
                        duplicates += 1
                        continue
                    bar["streamVersions"].append(version)
                    _refresh_bar(bar)
                    inserted += 1
                    affected.add(minute_id)
                    partition_changed = True
                partition["bars"] = sorted(
                    bars.values(), key=lambda item: str(item["timestamp"])
                )
                if partition_changed:
                    self._write_partition(path, partition)
                    touched.add(path)
        return CandleStoreMutation(
            inserted_count=inserted,
            duplicate_count=duplicates,
            partition_count=len(touched),
            affected_minutes=tuple(sorted(affected)),
        )

    def append_history(
        self,
        candles: Sequence[SchwabMinuteCandle],
        *,
        received_at: datetime,
    ) -> CandleStoreMutation:
        received = _aware(received_at)
        inserted = 0
        duplicates = 0
        affected: set[str] = set()
        touched: set[Path] = set()
        grouped: dict[tuple[str, str], list[SchwabMinuteCandle]] = {}
        for candle in candles:
            if candle.source != SCHWAB_PRICE_HISTORY_SOURCE:
                raise SchwabCandleStoreError(
                    "Schwab history storage rejected a non-price-history source."
                )
            session_date = candle.timestamp.astimezone(EASTERN_TZ).date().isoformat()
            grouped.setdefault((session_date, candle.symbol), []).append(candle)

        with self._lock:
            for (session_date, symbol), items in sorted(grouped.items()):
                path = self.partition_path(symbol, session_date)
                partition = self._load_partition(path, symbol, session_date)
                bars = _bars_by_identity(partition)
                partition_changed = False
                for candle in items:
                    minute_id = minute_identity(candle)
                    bar = bars.setdefault(minute_id, _new_bar(candle))
                    version = _history_version(candle, received)
                    existing = {
                        str(item["versionId"]): item
                        for item in bar["historyVersions"]
                    }
                    current = existing.get(str(version["versionId"]))
                    if current is not None:
                        if _semantic_version(current) != _semantic_version(version):
                            raise SchwabCandleStoreError(
                                "A history version identity was reused with conflicting evidence."
                            )
                        duplicates += 1
                        continue
                    bar["historyVersions"].append(version)
                    _refresh_bar(bar)
                    inserted += 1
                    affected.add(minute_id)
                    partition_changed = True
                partition["bars"] = sorted(
                    bars.values(), key=lambda item: str(item["timestamp"])
                )
                if partition_changed:
                    self._write_partition(path, partition)
                    touched.add(path)
        return CandleStoreMutation(
            inserted_count=inserted,
            duplicate_count=duplicates,
            partition_count=len(touched),
            affected_minutes=tuple(sorted(affected)),
        )

    def partition_path(self, symbol: str, session_date: str) -> Path:
        normalized = normalize_symbols((symbol,))[0]
        try:
            parsed_date = datetime.strptime(session_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SchwabCandleStoreError(
                "Schwab candle partition date was invalid."
            ) from exc
        return self.root / parsed_date.isoformat() / f"{normalized}.json"

    def load_partition(self, symbol: str, session_date: str) -> dict[str, object]:
        with self._lock:
            return self._load_partition(
                self.partition_path(symbol, session_date),
                normalize_symbols((symbol,))[0],
                session_date,
            )

    def canonical_bars(
        self,
        symbol: str,
        session_date: str,
    ) -> tuple[dict[str, object], ...]:
        partition = self.load_partition(symbol, session_date)
        return tuple(
            dict(bar["canonicalCandle"])
            for bar in partition["bars"]
            if isinstance(bar.get("canonicalCandle"), Mapping)
        )

    def health(
        self,
        symbols: Iterable[str],
        *,
        evaluated_at: datetime,
        stale_after: timedelta,
    ) -> tuple[CandleStoreHealth, ...]:
        evaluated = _aware(evaluated_at)
        stale_seconds = stale_after.total_seconds()
        if not math.isfinite(stale_seconds) or stale_seconds <= 0:
            raise SchwabCandleStoreError(
                "Schwab candle stale threshold must be positive and finite."
            )
        results: list[CandleStoreHealth] = []
        session_date = evaluated.astimezone(EASTERN_TZ).date().isoformat()
        for symbol in normalize_symbols(tuple(symbols)):
            bars = self._load_symbol_bars(symbol, session_date)
            if not bars:
                results.append(
                    CandleStoreHealth(
                        symbol=symbol,
                        status="NO_OBSERVATIONS",
                        latest_minute=None,
                        latest_received_at=None,
                        stale=True,
                        gap_count=0,
                        unreconciled_count=0,
                        corrected_count=0,
                        canonical_count=0,
                    )
                )
                continue
            latest_minute = max(_parse_datetime(bar["timestamp"]) for bar in bars)
            receipts = [
                _parse_datetime(version["firstReceivedAt"])
                for bar in bars
                for key in ("streamVersions", "historyVersions")
                for version in bar[key]
            ]
            latest_receipt = max(receipts)
            if latest_receipt > evaluated:
                raise SchwabCandleStoreError(
                    "Schwab candle receipt occurred after the health clock."
                )
            timestamps = sorted({_parse_datetime(bar["timestamp"]) for bar in bars})
            gap_count = sum(
                current - previous > ONE_MINUTE
                for previous, current in zip(timestamps, timestamps[1:])
                if previous.date() == current.date()
            )
            stale = evaluated - (latest_minute + ONE_MINUTE) > stale_after
            unreconciled = sum(
                bar["state"] in {"IN_PROGRESS", "COMPLETED_UNRECONCILED"}
                for bar in bars
            )
            corrected = sum(bar["state"] == "CORRECTED" for bar in bars)
            canonical = sum(bar["canonicalCandle"] is not None for bar in bars)
            status = "STALE" if stale else "CURRENT"
            if gap_count:
                status += "_WITH_GAPS"
            if unreconciled:
                status += "_UNRECONCILED"
            results.append(
                CandleStoreHealth(
                    symbol=symbol,
                    status=status,
                    latest_minute=latest_minute,
                    latest_received_at=latest_receipt,
                    stale=stale,
                    gap_count=gap_count,
                    unreconciled_count=unreconciled,
                    corrected_count=corrected,
                    canonical_count=canonical,
                )
            )
        return tuple(results)

    def _load_symbol_bars(
        self,
        symbol: str,
        session_date: str,
    ) -> list[dict[str, object]]:
        path = self.partition_path(symbol, session_date)
        if not path.exists():
            return []
        return list(self._load_partition(path, symbol, session_date)["bars"])

    def _load_partition(
        self,
        path: Path,
        symbol: str,
        session_date: str,
    ) -> dict[str, object]:
        if not path.exists():
            return _new_partition(symbol, session_date)
        try:
            if path.stat().st_size > MAX_PARTITION_BYTES:
                raise SchwabCandleStoreError(
                    "Schwab candle partition exceeded its bounded size."
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
        except SchwabCandleStoreError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SchwabCandleStoreError(
                "Schwab candle partition was unreadable."
            ) from exc
        _validate_partition(payload, symbol=symbol, session_date=session_date)
        return payload

    def _write_partition(self, path: Path, partition: Mapping[str, object]) -> None:
        _validate_partition(
            partition,
            symbol=str(partition["symbol"]),
            session_date=str(partition["sessionDate"]),
        )
        content = _canonical_json_bytes(partition)
        if len(content) > MAX_PARTITION_BYTES:
            raise SchwabCandleStoreError(
                "Schwab candle partition exceeded its bounded size."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def minute_identity(candle: SchwabMinuteCandle) -> str:
    timestamp = _aware(candle.timestamp).astimezone(timezone.utc)
    return f"schwab-equity-1m:v1|{candle.symbol}|{timestamp.isoformat()}"


def _new_partition(symbol: str, session_date: str) -> dict[str, object]:
    return {
        "schemaVersion": SCHWAB_CANDLE_STORE_SCHEMA_VERSION,
        "storeKind": SCHWAB_CANDLE_STORE_KIND,
        "symbol": normalize_symbols((symbol,))[0],
        "sessionDate": session_date,
        "streamSource": SCHWAB_CHART_EQUITY_SOURCE,
        "canonicalSource": SCHWAB_PRICE_HISTORY_SOURCE,
        "legacySourceMixed": False,
        "consumerActivation": "DEFERRED_TO_R033",
        "bars": [],
    }


def _new_bar(candle: SchwabMinuteCandle) -> dict[str, object]:
    timestamp = _aware(candle.timestamp).astimezone(timezone.utc)
    return {
        "minuteIdentity": minute_identity(candle),
        "timestamp": timestamp.isoformat(),
        "session": session_for_timestamp(timestamp),
        "state": "IN_PROGRESS",
        "streamVersions": [],
        "historyVersions": [],
        "canonicalCandle": None,
        "discrepancyFields": [],
    }


def _stream_version(
    observation: SchwabStreamCandleObservation,
) -> dict[str, object]:
    semantic = {
        "source": SCHWAB_CHART_EQUITY_SOURCE,
        "candle": observation.candle.to_evidence(),
    }
    return {
        "versionId": _sha256(_canonical_json_bytes(semantic)),
        "source": SCHWAB_CHART_EQUITY_SOURCE,
        "firstReceivedAt": _aware(observation.received_at).isoformat(),
        "arrivalIndex": observation.arrival_index,
        "payloadIndex": observation.payload_index,
        "outOfOrder": observation.out_of_order,
        "sequenceDeltaFromPreviousArrival": (
            observation.sequence_delta_from_previous_arrival
        ),
        "candle": observation.candle.to_evidence(),
    }


def _history_version(
    candle: SchwabMinuteCandle,
    received_at: datetime,
) -> dict[str, object]:
    semantic = {
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "candle": candle.to_evidence(),
    }
    return {
        "versionId": _sha256(_canonical_json_bytes(semantic)),
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "firstReceivedAt": received_at.isoformat(),
        "candle": candle.to_evidence(),
    }


def _semantic_version(version: Mapping[str, object]) -> dict[str, object]:
    return {
        "source": version.get("source"),
        "candle": version.get("candle"),
    }


def _refresh_bar(bar: dict[str, object]) -> None:
    stream_versions = sorted(
        bar["streamVersions"],
        key=lambda item: (str(item["firstReceivedAt"]), str(item["versionId"])),
    )
    history_versions = sorted(
        bar["historyVersions"],
        key=lambda item: (str(item["firstReceivedAt"]), str(item["versionId"])),
    )
    bar["streamVersions"] = stream_versions
    bar["historyVersions"] = history_versions
    if history_versions:
        canonical = dict(history_versions[-1]["candle"])
        bar["canonicalCandle"] = canonical
        if not stream_versions:
            bar["state"] = "HISTORY_ONLY_GAP_FILL"
            bar["discrepancyFields"] = []
            return
        discrepancies = _candle_differences(
            stream_versions[-1]["candle"], canonical
        )
        bar["discrepancyFields"] = list(discrepancies)
        bar["state"] = "CORRECTED" if discrepancies else "RECONCILED"
        return
    bar["canonicalCandle"] = None
    bar["discrepancyFields"] = []
    if not stream_versions:
        bar["state"] = "IN_PROGRESS"
        return
    latest = stream_versions[-1]
    candle_at = _parse_datetime(latest["candle"]["timestamp"])
    received_at = _parse_datetime(latest["firstReceivedAt"])
    bar["state"] = (
        "COMPLETED_UNRECONCILED"
        if received_at >= candle_at + ONE_MINUTE
        else "IN_PROGRESS"
    )


def _candle_differences(
    stream: Mapping[str, object],
    history: Mapping[str, object],
) -> tuple[str, ...]:
    differences: list[str] = []
    for field in ("open", "high", "low", "close", "volume"):
        left = _finite(stream.get(field), field)
        right = _finite(history.get(field), field)
        if not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12):
            differences.append(field)
    return tuple(differences)


def _bars_by_identity(partition: Mapping[str, object]) -> dict[str, dict[str, object]]:
    return {str(bar["minuteIdentity"]): bar for bar in partition["bars"]}


def _validate_partition(
    payload: object,
    *,
    symbol: str,
    session_date: str,
) -> None:
    if not isinstance(payload, Mapping):
        raise SchwabCandleStoreError("Schwab candle partition was not an object.")
    expected_keys = {
        "schemaVersion",
        "storeKind",
        "symbol",
        "sessionDate",
        "streamSource",
        "canonicalSource",
        "legacySourceMixed",
        "consumerActivation",
        "bars",
    }
    if set(payload) != expected_keys:
        raise SchwabCandleStoreError(
            "Schwab candle partition fields were not the exact supported schema."
        )
    expected = {
        "schemaVersion": SCHWAB_CANDLE_STORE_SCHEMA_VERSION,
        "storeKind": SCHWAB_CANDLE_STORE_KIND,
        "symbol": normalize_symbols((symbol,))[0],
        "sessionDate": session_date,
        "streamSource": SCHWAB_CHART_EQUITY_SOURCE,
        "canonicalSource": SCHWAB_PRICE_HISTORY_SOURCE,
        "legacySourceMixed": False,
        "consumerActivation": "DEFERRED_TO_R033",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise SchwabCandleStoreError(
                f"Schwab candle partition metadata {key} was invalid."
            )
    bars = payload.get("bars")
    if not isinstance(bars, list):
        raise SchwabCandleStoreError("Schwab candle partition bars were invalid.")
    identities: set[str] = set()
    timestamps: list[datetime] = []
    for bar in bars:
        if not isinstance(bar, Mapping):
            raise SchwabCandleStoreError("Schwab candle bar was not an object.")
        if set(bar) != {
            "minuteIdentity",
            "timestamp",
            "session",
            "state",
            "streamVersions",
            "historyVersions",
            "canonicalCandle",
            "discrepancyFields",
        }:
            raise SchwabCandleStoreError(
                "Schwab candle bar fields were not the exact supported schema."
            )
        identity = str(bar["minuteIdentity"])
        if identity in identities:
            raise SchwabCandleStoreError("Schwab candle minute identity was repeated.")
        identities.add(identity)
        timestamp = _parse_datetime(bar["timestamp"])
        timestamps.append(timestamp)
        if bar["state"] not in BAR_STATES:
            raise SchwabCandleStoreError("Schwab candle bar state was invalid.")
        for collection, source in (
            (bar["streamVersions"], SCHWAB_CHART_EQUITY_SOURCE),
            (bar["historyVersions"], SCHWAB_PRICE_HISTORY_SOURCE),
        ):
            if not isinstance(collection, list):
                raise SchwabCandleStoreError("Schwab candle versions were invalid.")
            version_ids: set[str] = set()
            for version in collection:
                if not isinstance(version, Mapping) or version.get("source") != source:
                    raise SchwabCandleStoreError(
                        "Schwab candle version source was invalid."
                    )
                version_id = str(version.get("versionId", ""))
                if version_id in version_ids:
                    raise SchwabCandleStoreError(
                        "Schwab candle version identity was repeated."
                    )
                version_ids.add(version_id)
                expected_id = _sha256(
                    _canonical_json_bytes(_semantic_version(version))
                )
                if version_id != expected_id:
                    raise SchwabCandleStoreError(
                        "Schwab candle version hash did not match its evidence."
                    )
                _parse_datetime(version.get("firstReceivedAt"))
                candle = version.get("candle")
                if not isinstance(candle, Mapping):
                    raise SchwabCandleStoreError(
                        "Schwab candle version omitted candle evidence."
                    )
                if str(candle.get("symbol")) != symbol:
                    raise SchwabCandleStoreError(
                        "Schwab candle version symbol contradicted its partition."
                    )
                if _parse_datetime(candle.get("timestamp")) != timestamp:
                    raise SchwabCandleStoreError(
                        "Schwab candle version timestamp contradicted its partition."
                    )
                for field in ("open", "high", "low", "close", "volume"):
                    _finite(candle.get(field), field)
                if candle.get("source") != source:
                    raise SchwabCandleStoreError(
                        "Schwab candle evidence source contradicted its version."
                    )
                if str(candle.get("sessionDate")) != session_date:
                    raise SchwabCandleStoreError(
                        "Schwab candle session date contradicted its partition."
                    )
                low = _finite(candle.get("low"), "low")
                high = _finite(candle.get("high"), "high")
                opened = _finite(candle.get("open"), "open")
                closed = _finite(candle.get("close"), "close")
                if low > high or not low <= opened <= high or not low <= closed <= high:
                    raise SchwabCandleStoreError(
                        "Schwab candle OHLC values contradicted one another."
                    )
        versions = list(bar["streamVersions"]) + list(bar["historyVersions"])
        if not versions:
            raise SchwabCandleStoreError(
                "Schwab candle bar contained no source versions."
            )
        representative = versions[0]["candle"]
        expected_identity = minute_identity(
            SchwabMinuteCandle(
                symbol=str(representative["symbol"]),
                timestamp=_parse_datetime(representative["timestamp"]),
                open=_finite(representative["open"], "open"),
                high=_finite(representative["high"], "high"),
                low=_finite(representative["low"], "low"),
                close=_finite(representative["close"], "close"),
                volume=_finite(representative["volume"], "volume"),
                source=str(representative["source"]),
                sequence=representative.get("sequence"),
            )
        )
        if identity != expected_identity:
            raise SchwabCandleStoreError(
                "Schwab candle minute identity contradicted its evidence."
            )
        expected_bar = dict(bar)
        _refresh_bar(expected_bar)
        for field in ("state", "canonicalCandle", "discrepancyFields"):
            if bar[field] != expected_bar[field]:
                raise SchwabCandleStoreError(
                    f"Schwab candle derived field {field} contradicted its evidence."
                )
    if timestamps != sorted(timestamps):
        raise SchwabCandleStoreError(
            "Schwab candle partition bars were not chronologically ordered."
        )


def _canonical_json_bytes(payload: object) -> bytes:
    try:
        text = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise SchwabCandleStoreError(
            "Schwab candle evidence was not canonical JSON."
        ) from exc
    return (text + "\n").encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def _parse_datetime(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchwabCandleStoreError(
            "Schwab candle timestamp was invalid."
        ) from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabCandleStoreError(
            "Schwab candle timestamps require an explicit UTC offset."
        )
    return value


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchwabCandleStoreError(f"Schwab candle {label} was not numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise SchwabCandleStoreError(f"Schwab candle {label} was not finite.")
    return number


def _same_or_ancestor(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _lock_handle(handle: object) -> None:
    handle.seek(0)
    if handle.read(1) == b"":
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: object) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
