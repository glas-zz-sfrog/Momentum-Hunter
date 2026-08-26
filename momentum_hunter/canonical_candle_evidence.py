"""Read-only access to reconciled Schwab minute-candle evidence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
    normalize_symbols,
)
from momentum_hunter.schwab_candle_store import (
    SCHWAB_CANDLE_STORE_ROOT,
    SchwabCandleStore,
    SchwabCandleStoreError,
)


CANONICAL_OUTCOME_STATES = frozenset(
    {"RECONCILED", "CORRECTED", "HISTORY_ONLY_GAP_FILL"}
)
MAX_READ_PARTITIONS = 5_000


class CanonicalCandleEvidenceError(RuntimeError):
    """Raised when canonical candle evidence is ambiguous or invalid."""


@dataclass(frozen=True)
class CanonicalMinuteBar:
    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    state: str
    session_date: str


@dataclass(frozen=True)
class CompletedCanonicalMinuteVersion:
    bar: CanonicalMinuteBar
    first_received_at: str
    original_first_received_at: str
    bar_end: str
    version_id: str
    semantic_identity: str


@dataclass(frozen=True)
class CanonicalMinuteFinalitySnapshot:
    versions: tuple[CompletedCanonicalMinuteVersion, ...]
    observed_version_count: int
    provisional_version_count: int
    completed_version_count: int


def load_canonical_minute_finality_as_of(
    *,
    cutoff: datetime,
    store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
    windows_by_symbol: Mapping[str, tuple[datetime, datetime]] | None = None,
    symbols: tuple[str, ...] | list[str] | None = None,
) -> CanonicalMinuteFinalitySnapshot:
    """Select price-history versions actually complete and known by ``cutoff``."""

    evaluated = _aware(cutoff)
    store = SchwabCandleStore(store_root)
    paths = _partition_requests(
        store,
        windows_by_symbol=windows_by_symbol,
        symbols=symbols,
    )
    if len(paths) > MAX_READ_PARTITIONS:
        raise CanonicalCandleEvidenceError(
            "Canonical candle read exceeded the bounded partition limit."
        )
    selected: dict[tuple[str, str], CompletedCanonicalMinuteVersion] = {}
    observed_versions = 0
    provisional_versions = 0
    completed_versions = 0
    for symbol, session_date, path in paths:
        if not path.exists():
            continue
        try:
            partition = store.load_partition(symbol, session_date)
        except SchwabCandleStoreError as exc:
            raise CanonicalCandleEvidenceError(
                f"Canonical Schwab candle partition failed validation: {path}"
            ) from exc
        for item in partition.get("bars", []):
            if not isinstance(item, Mapping):
                raise CanonicalCandleEvidenceError(
                    "Canonical Schwab candle partition contained an invalid bar."
                )
            eligible: list[tuple[datetime, str, Mapping[object, object]]] = []
            versions = item.get("historyVersions")
            if not isinstance(versions, list):
                raise CanonicalCandleEvidenceError(
                    "Canonical Schwab candle history versions were invalid."
                )
            for version in versions:
                if not isinstance(version, Mapping):
                    raise CanonicalCandleEvidenceError(
                        "Canonical Schwab candle history version was invalid."
                    )
                original_received = str(version.get("firstReceivedAt", ""))
                received = _aware_datetime(original_received)
                if received > evaluated:
                    continue
                candle = version.get("candle")
                if not isinstance(candle, Mapping):
                    raise CanonicalCandleEvidenceError(
                        "Canonical Schwab candle history version omitted its candle."
                    )
                observed_versions += 1
                bar_start = _aware_datetime(str(candle.get("timestamp", "")))
                if received < bar_start + timedelta(minutes=1):
                    provisional_versions += 1
                    continue
                completed_versions += 1
                eligible.append(
                    (received, str(version.get("versionId", "")), candle)
                )
            if not eligible:
                continue
            received, version_id, candle = max(
                eligible, key=lambda value: (value[0], value[1])
            )
            state = _state_as_of(
                item,
                canonical_candle=candle,
                cutoff=evaluated,
            )
            bar = _canonical_bar(
                candle,
                expected_symbol=symbol,
                expected_session_date=session_date,
                state=state,
            )
            semantic_identity = hashlib.sha256(
                json.dumps(
                    {
                        "symbol": bar.symbol,
                        "timestamp": bar.timestamp,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "source": bar.source,
                        "sessionDate": bar.session_date,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
            ).hexdigest()
            identity = (bar.symbol, bar.timestamp)
            selected[identity] = CompletedCanonicalMinuteVersion(
                bar=bar,
                first_received_at=received.isoformat(),
                original_first_received_at=str(
                    next(
                        version.get("firstReceivedAt", "")
                        for version in versions
                        if isinstance(version, Mapping)
                        and str(version.get("versionId", "")) == version_id
                    )
                ),
                bar_end=(
                    _aware_datetime(bar.timestamp) + timedelta(minutes=1)
                ).isoformat(),
                version_id=version_id,
                semantic_identity=semantic_identity,
            )
    return CanonicalMinuteFinalitySnapshot(
        versions=tuple(
            sorted(
                selected.values(),
                key=lambda value: (value.bar.timestamp, value.bar.symbol),
            )
        ),
        observed_version_count=observed_versions,
        provisional_version_count=provisional_versions,
        completed_version_count=completed_versions,
    )


def load_canonical_minute_bars(
    *,
    store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
    windows_by_symbol: Mapping[str, tuple[datetime, datetime]] | None = None,
    symbols: tuple[str, ...] | list[str] | None = None,
) -> dict[str, list[CanonicalMinuteBar]]:
    """Load only price-history-backed, terminal canonical one-minute bars."""

    store = SchwabCandleStore(store_root)
    paths = _partition_requests(
        store,
        windows_by_symbol=windows_by_symbol,
        symbols=symbols,
    )
    if len(paths) > MAX_READ_PARTITIONS:
        raise CanonicalCandleEvidenceError(
            "Canonical candle read exceeded the bounded partition limit."
        )

    result: dict[str, list[CanonicalMinuteBar]] = {}
    identities: dict[tuple[str, str], CanonicalMinuteBar] = {}
    for symbol, session_date, path in paths:
        if not path.exists():
            continue
        try:
            partition = store.load_partition(symbol, session_date)
        except SchwabCandleStoreError as exc:
            raise CanonicalCandleEvidenceError(
                f"Canonical Schwab candle partition failed validation: {path}"
            ) from exc
        for item in partition.get("bars", []):
            if not isinstance(item, Mapping):
                raise CanonicalCandleEvidenceError(
                    "Canonical Schwab candle partition contained an invalid bar."
                )
            state = str(item.get("state") or "")
            candle = item.get("canonicalCandle")
            if state not in CANONICAL_OUTCOME_STATES or not isinstance(candle, Mapping):
                continue
            bar = _canonical_bar(
                candle,
                expected_symbol=symbol,
                expected_session_date=session_date,
                state=state,
            )
            identity = (bar.symbol, bar.timestamp)
            previous = identities.get(identity)
            if previous is not None and previous != bar:
                raise CanonicalCandleEvidenceError(
                    "Canonical Schwab candle identity had conflicting evidence."
                )
            identities[identity] = bar

    for bar in identities.values():
        result.setdefault(bar.symbol, []).append(bar)
    for bars in result.values():
        bars.sort(key=lambda item: item.timestamp)
    return dict(sorted(result.items()))


def canonical_minute_bar_symbols(
    *,
    store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
) -> set[str]:
    return set(load_canonical_minute_bars(store_root=store_root))


def canonical_minute_bar_count(
    *,
    store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
) -> int:
    return sum(
        len(items)
        for items in load_canonical_minute_bars(store_root=store_root).values()
    )


def _partition_requests(
    store: SchwabCandleStore,
    *,
    windows_by_symbol: Mapping[str, tuple[datetime, datetime]] | None,
    symbols: tuple[str, ...] | list[str] | None,
) -> list[tuple[str, str, Path]]:
    requests: set[tuple[str, str, Path]] = set()
    if windows_by_symbol is not None:
        for symbol, window in windows_by_symbol.items():
            normalized = normalize_symbols((symbol,))[0]
            start, end = (_aware(window[0]), _aware(window[1]))
            if end < start:
                raise CanonicalCandleEvidenceError(
                    "Canonical candle window ended before it started."
                )
            current = start.astimezone(EASTERN_TZ).date()
            final = end.astimezone(EASTERN_TZ).date()
            while current <= final:
                session_date = current.isoformat()
                requests.add(
                    (
                        normalized,
                        session_date,
                        store.partition_path(normalized, session_date),
                    )
                )
                current += timedelta(days=1)
        return sorted(requests, key=lambda item: (item[1], item[0]))

    wanted = set(normalize_symbols(tuple(symbols))) if symbols else set()
    if not store.root.exists():
        return []
    for path in sorted(store.root.glob("*/*.json")):
        session_date = path.parent.name
        if not _is_session_date(session_date):
            if session_date == "runs":
                continue
            raise CanonicalCandleEvidenceError(
                f"Unexpected directory in canonical Schwab candle store: {path.parent}"
            )
        symbol = path.stem.upper()
        if wanted and symbol not in wanted:
            continue
        expected = store.partition_path(symbol, session_date)
        if path.resolve(strict=False) != expected.resolve(strict=False):
            raise CanonicalCandleEvidenceError(
                f"Unexpected file in canonical Schwab candle store: {path}"
            )
        requests.add((symbol, session_date, path))
    return sorted(requests, key=lambda item: (item[1], item[0]))


def _canonical_bar(
    candle: Mapping[object, object],
    *,
    expected_symbol: str,
    expected_session_date: str,
    state: str,
) -> CanonicalMinuteBar:
    symbol = str(candle.get("symbol") or "").strip().upper()
    timestamp = str(candle.get("timestamp") or "")
    session_date = str(candle.get("sessionDate") or "")
    source = str(candle.get("source") or "")
    if symbol != expected_symbol or session_date != expected_session_date:
        raise CanonicalCandleEvidenceError(
            "Canonical Schwab candle identity did not match its partition."
        )
    if source != SCHWAB_PRICE_HISTORY_SOURCE:
        raise CanonicalCandleEvidenceError(
            "Outcome evidence requires reconciled Schwab price-history bars."
        )
    if candle.get("ohlcvComplete") is not True:
        raise CanonicalCandleEvidenceError(
            "Canonical Schwab candle was not marked OHLCV-complete."
        )
    parsed = _aware_datetime(timestamp)
    if parsed.astimezone(EASTERN_TZ).date().isoformat() != session_date:
        raise CanonicalCandleEvidenceError(
            "Canonical Schwab candle timestamp did not match its session date."
        )
    values = {
        name: _finite_number(candle.get(name), name)
        for name in ("open", "high", "low", "close", "volume")
    }
    if min(values[name] for name in ("open", "high", "low", "close")) <= 0:
        raise CanonicalCandleEvidenceError(
            "Canonical Schwab OHLC values must be positive."
        )
    if values["volume"] < 0:
        raise CanonicalCandleEvidenceError(
            "Canonical Schwab volume must be nonnegative."
        )
    if values["high"] < max(values["open"], values["low"], values["close"]):
        raise CanonicalCandleEvidenceError("Canonical Schwab candle high was invalid.")
    if values["low"] > min(values["open"], values["high"], values["close"]):
        raise CanonicalCandleEvidenceError("Canonical Schwab candle low was invalid.")
    return CanonicalMinuteBar(
        symbol=symbol,
        timestamp=parsed.astimezone(timezone.utc).isoformat(),
        open=values["open"],
        high=values["high"],
        low=values["low"],
        close=values["close"],
        volume=values["volume"],
        source=source,
        state=state,
        session_date=session_date,
    )


def _state_as_of(
    item: Mapping[object, object],
    *,
    canonical_candle: Mapping[object, object],
    cutoff: datetime,
) -> str:
    stream_versions = item.get("streamVersions")
    if not isinstance(stream_versions, list):
        raise CanonicalCandleEvidenceError(
            "Canonical Schwab candle stream versions were invalid."
        )
    observed = []
    for version in stream_versions:
        if not isinstance(version, Mapping):
            raise CanonicalCandleEvidenceError(
                "Canonical Schwab candle stream version was invalid."
            )
        received = _aware_datetime(str(version.get("firstReceivedAt", "")))
        candle = version.get("candle")
        if received <= cutoff and isinstance(candle, Mapping):
            observed.append((received, str(version.get("versionId", "")), candle))
    if not observed:
        return "HISTORY_ONLY_GAP_FILL"
    stream = max(observed, key=lambda value: (value[0], value[1]))[2]
    equal = all(
        math.isclose(
            _finite_number(stream.get(field), field),
            _finite_number(canonical_candle.get(field), field),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        for field in ("open", "high", "low", "close", "volume")
    )
    return "RECONCILED" if equal else "CORRECTED"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalCandleEvidenceError(
            "Canonical candle windows require timezone-aware timestamps."
        )
    return value.astimezone(timezone.utc)


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanonicalCandleEvidenceError(
            "Canonical Schwab candle timestamp was invalid."
        ) from exc
    return _aware(parsed)


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalCandleEvidenceError(
            f"Canonical Schwab candle {name} was not numeric."
        )
    number = float(value)
    if not math.isfinite(number):
        raise CanonicalCandleEvidenceError(
            f"Canonical Schwab candle {name} was not finite."
        )
    return number


def _is_session_date(value: str) -> bool:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat() == value
    except ValueError:
        return False
