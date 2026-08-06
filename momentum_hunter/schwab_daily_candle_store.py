"""Atomic, source-specific storage for canonical Schwab daily candles."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from momentum_hunter.config import DATA_DIR
from momentum_hunter.daily_ohlc import DAILY_OHLC_SOURCE_PATH
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabDailyCandle,
    normalize_symbols,
)
from momentum_hunter.schwab_candle_store import CandleStoreLease


SCHWAB_DAILY_CANDLE_STORE_SCHEMA_VERSION = 1
SCHWAB_DAILY_CANDLE_STORE_KIND = "SCHWAB_CANONICAL_DAILY_CANDLES"
SCHWAB_DAILY_CANDLE_STORE_ROOT = DATA_DIR / "schwab-daily-candles-v1"
MAX_SYMBOL_BYTES = 16 * 1024 * 1024
DAILY_BAR_STATES = frozenset({"CANONICAL", "CORRECTED"})


class SchwabDailyCandleStoreError(RuntimeError):
    """Raised when daily candle evidence cannot be preserved unambiguously."""


@dataclass(frozen=True)
class DailyCandleStoreMutation:
    inserted_count: int
    duplicate_count: int
    affected_sessions: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.inserted_count > 0


class SchwabDailyCandleStore:
    def __init__(self, root: Path = SCHWAB_DAILY_CANDLE_STORE_ROOT) -> None:
        self.root = root.resolve(strict=False)
        legacy = DAILY_OHLC_SOURCE_PATH.resolve(strict=False)
        if self.root == legacy or _is_relative_to(legacy, self.root):
            raise SchwabDailyCandleStoreError(
                "Schwab daily storage must not contain the legacy daily OHLC cache."
            )
        self._lock = threading.RLock()

    def lease(self, *, acquired_at: datetime | None = None) -> CandleStoreLease:
        return CandleStoreLease(self.root, acquired_at=acquired_at)

    def append_history(
        self,
        candles: Sequence[SchwabDailyCandle],
        *,
        received_at: datetime,
    ) -> DailyCandleStoreMutation:
        received = _aware(received_at)
        grouped: dict[str, list[SchwabDailyCandle]] = {}
        for candle in candles:
            if candle.source != SCHWAB_PRICE_HISTORY_SOURCE:
                raise SchwabDailyCandleStoreError(
                    "Schwab daily storage rejected a non-price-history source."
                )
            expected_date = candle.timestamp.astimezone(EASTERN_TZ).date().isoformat()
            if candle.session_date != expected_date:
                raise SchwabDailyCandleStoreError(
                    "Schwab daily candle date contradicted its provider timestamp."
                )
            grouped.setdefault(candle.symbol, []).append(candle)

        inserted = 0
        duplicates = 0
        affected: set[str] = set()
        with self._lock:
            for symbol, items in sorted(grouped.items()):
                path = self.symbol_path(symbol)
                payload = self._load_symbol(path, symbol)
                bars = {str(item["dailyIdentity"]): item for item in payload["bars"]}
                changed = False
                for candle in items:
                    identity = daily_identity(candle)
                    bar = bars.setdefault(identity, _new_bar(candle))
                    history_versions = list(bar["historyVersions"])
                    latest = history_versions[-1] if history_versions else None
                    if latest is not None and latest["candle"] == candle.to_evidence():
                        duplicates += 1
                        continue
                    reasserted_after = None
                    if any(
                        item["candle"] == candle.to_evidence()
                        for item in history_versions
                    ):
                        reasserted_after = str(latest["versionId"])
                    version = _history_version(
                        candle,
                        received,
                        reasserted_after_version_id=reasserted_after,
                    )
                    existing = {
                        str(item["versionId"]): item for item in history_versions
                    }
                    current = existing.get(str(version["versionId"]))
                    if current is not None:
                        if _semantic_version(current) != _semantic_version(version):
                            raise SchwabDailyCandleStoreError(
                                "A daily history version identity was reused with conflicting evidence."
                            )
                        duplicates += 1
                        continue
                    bar["historyVersions"].append(version)
                    _refresh_bar(bar)
                    inserted += 1
                    affected.add(identity)
                    changed = True
                payload["bars"] = sorted(
                    bars.values(), key=lambda item: str(item["sessionDate"])
                )
                if changed:
                    self._write_symbol(path, payload)
        return DailyCandleStoreMutation(
            inserted_count=inserted,
            duplicate_count=duplicates,
            affected_sessions=tuple(sorted(affected)),
        )

    def symbol_path(self, symbol: str) -> Path:
        normalized = normalize_symbols((symbol,))[0]
        return self.root / f"{normalized}.json"

    def load_symbol(self, symbol: str) -> dict[str, object]:
        normalized = normalize_symbols((symbol,))[0]
        with self._lock:
            return self._load_symbol(self.symbol_path(normalized), normalized)

    def canonical_bars(self, symbol: str) -> tuple[dict[str, object], ...]:
        payload = self.load_symbol(symbol)
        return tuple(dict(bar["canonicalCandle"]) for bar in payload["bars"])

    def _load_symbol(self, path: Path, symbol: str) -> dict[str, object]:
        if not path.exists():
            return _new_symbol(symbol)
        try:
            raw = path.read_bytes()
            if len(raw) > MAX_SYMBOL_BYTES:
                raise SchwabDailyCandleStoreError(
                    "Schwab daily candle file exceeded its bounded size."
                )
            payload = json.loads(raw)
        except SchwabDailyCandleStoreError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SchwabDailyCandleStoreError(
                "Schwab daily candle file was unreadable."
            ) from exc
        _validate_symbol(payload, symbol=symbol)
        return payload

    def _write_symbol(self, path: Path, payload: Mapping[str, object]) -> None:
        _validate_symbol(payload, symbol=str(payload["symbol"]))
        content = _canonical_json_bytes(payload)
        if len(content) > MAX_SYMBOL_BYTES:
            raise SchwabDailyCandleStoreError(
                "Schwab daily candle file exceeded its bounded size."
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


def daily_identity(candle: SchwabDailyCandle) -> str:
    return f"schwab-equity-1d:v1|{candle.symbol}|{candle.session_date}"


def _new_symbol(symbol: str) -> dict[str, object]:
    return {
        "schemaVersion": SCHWAB_DAILY_CANDLE_STORE_SCHEMA_VERSION,
        "storeKind": SCHWAB_DAILY_CANDLE_STORE_KIND,
        "symbol": normalize_symbols((symbol,))[0],
        "canonicalSource": SCHWAB_PRICE_HISTORY_SOURCE,
        "timeframe": "1d",
        "legacySourceMixed": False,
        "consumerActivation": "DEFERRED_TO_R033_RECONCILIATION",
        "bars": [],
    }


def _new_bar(candle: SchwabDailyCandle) -> dict[str, object]:
    return {
        "dailyIdentity": daily_identity(candle),
        "sessionDate": candle.session_date,
        "timestamp": _aware(candle.timestamp).astimezone(timezone.utc).isoformat(),
        "state": "CANONICAL",
        "historyVersions": [],
        "canonicalCandle": None,
    }


def _history_version(
    candle: SchwabDailyCandle,
    received_at: datetime,
    *,
    reasserted_after_version_id: str | None = None,
) -> dict[str, object]:
    semantic = {
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "candle": candle.to_evidence(),
    }
    if reasserted_after_version_id is not None:
        semantic["reassertedAfterVersionId"] = reasserted_after_version_id
    return {
        "versionId": _sha256(_canonical_json_bytes(semantic)),
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "firstReceivedAt": _aware(received_at).isoformat(),
        "candle": candle.to_evidence(),
        **(
            {"reassertedAfterVersionId": reasserted_after_version_id}
            if reasserted_after_version_id is not None
            else {}
        ),
    }


def _semantic_version(version: Mapping[str, object]) -> dict[str, object]:
    semantic = {"source": version.get("source"), "candle": version.get("candle")}
    if version.get("reassertedAfterVersionId") is not None:
        semantic["reassertedAfterVersionId"] = version.get(
            "reassertedAfterVersionId"
        )
    return semantic


def _refresh_bar(bar: dict[str, object]) -> None:
    versions = sorted(
        bar["historyVersions"],
        key=lambda item: (str(item["firstReceivedAt"]), str(item["versionId"])),
    )
    bar["historyVersions"] = versions
    bar["canonicalCandle"] = dict(versions[-1]["candle"]) if versions else None
    bar["state"] = "CORRECTED" if len(versions) > 1 else "CANONICAL"


def _validate_symbol(payload: object, *, symbol: str) -> None:
    if not isinstance(payload, Mapping):
        raise SchwabDailyCandleStoreError("Schwab daily candle file was not an object.")
    expected_keys = {
        "schemaVersion",
        "storeKind",
        "symbol",
        "canonicalSource",
        "timeframe",
        "legacySourceMixed",
        "consumerActivation",
        "bars",
    }
    if set(payload) != expected_keys:
        raise SchwabDailyCandleStoreError(
            "Schwab daily candle file fields were not the exact supported schema."
        )
    expected = _new_symbol(symbol)
    for key in expected_keys - {"bars"}:
        if payload.get(key) != expected[key]:
            raise SchwabDailyCandleStoreError(
                f"Schwab daily candle metadata {key} was invalid."
            )
    bars = payload.get("bars")
    if not isinstance(bars, list):
        raise SchwabDailyCandleStoreError("Schwab daily candle bars were invalid.")
    identities: set[str] = set()
    dates: list[str] = []
    for bar in bars:
        if not isinstance(bar, Mapping) or set(bar) != {
            "dailyIdentity",
            "sessionDate",
            "timestamp",
            "state",
            "historyVersions",
            "canonicalCandle",
        }:
            raise SchwabDailyCandleStoreError("Schwab daily candle bar was invalid.")
        identity = str(bar["dailyIdentity"])
        session_date = str(bar["sessionDate"])
        if identity in identities:
            raise SchwabDailyCandleStoreError("Schwab daily candle identity was repeated.")
        identities.add(identity)
        dates.append(session_date)
        timestamp = _parse_datetime(bar["timestamp"])
        if timestamp.astimezone(EASTERN_TZ).date().isoformat() != session_date:
            raise SchwabDailyCandleStoreError(
                "Schwab daily candle date contradicted its timestamp."
            )
        versions = bar["historyVersions"]
        if not isinstance(versions, list) or not versions:
            raise SchwabDailyCandleStoreError(
                "Schwab daily candle bar omitted its source versions."
            )
        version_ids: set[str] = set()
        for version in versions:
            if not isinstance(version, Mapping):
                raise SchwabDailyCandleStoreError("Schwab daily version was invalid.")
            version_id = str(version.get("versionId", ""))
            if version_id in version_ids:
                raise SchwabDailyCandleStoreError("Schwab daily version was repeated.")
            reasserted_after = version.get("reassertedAfterVersionId")
            if reasserted_after is not None and str(reasserted_after) not in version_ids:
                raise SchwabDailyCandleStoreError(
                    "Schwab daily reassertion did not reference an earlier version."
                )
            if version.get("source") != SCHWAB_PRICE_HISTORY_SOURCE:
                raise SchwabDailyCandleStoreError("Schwab daily source was invalid.")
            if version_id != _sha256(_canonical_json_bytes(_semantic_version(version))):
                raise SchwabDailyCandleStoreError("Schwab daily version hash was invalid.")
            version_ids.add(version_id)
            _parse_datetime(version.get("firstReceivedAt"))
            candle = version.get("candle")
            if not isinstance(candle, Mapping):
                raise SchwabDailyCandleStoreError("Schwab daily candle evidence was invalid.")
            if candle.get("symbol") != symbol or candle.get("sessionDate") != session_date:
                raise SchwabDailyCandleStoreError("Schwab daily identity was inconsistent.")
            if candle.get("timeframe") != "1d" or candle.get("source") != SCHWAB_PRICE_HISTORY_SOURCE:
                raise SchwabDailyCandleStoreError("Schwab daily lineage was inconsistent.")
            if _parse_datetime(candle.get("timestamp")) != timestamp:
                raise SchwabDailyCandleStoreError("Schwab daily timestamp was inconsistent.")
            _validate_ohlcv(candle)
        representative = versions[0]["candle"]
        expected_identity = (
            f"schwab-equity-1d:v1|{representative['symbol']}|{representative['sessionDate']}"
        )
        if identity != expected_identity:
            raise SchwabDailyCandleStoreError("Schwab daily identity hash input was invalid.")
        expected_bar = dict(bar)
        _refresh_bar(expected_bar)
        if bar["state"] not in DAILY_BAR_STATES or any(
            bar[field] != expected_bar[field] for field in ("state", "canonicalCandle")
        ):
            raise SchwabDailyCandleStoreError("Schwab daily derived state was invalid.")
    if dates != sorted(dates):
        raise SchwabDailyCandleStoreError("Schwab daily candles were not ordered.")


def _validate_ohlcv(candle: Mapping[str, object]) -> None:
    values = {field: _finite(candle.get(field), field) for field in ("open", "high", "low", "close", "volume")}
    if values["open"] <= 0 or values["high"] <= 0 or values["low"] <= 0 or values["close"] <= 0:
        raise SchwabDailyCandleStoreError("Schwab daily price was not positive.")
    if values["volume"] < 0:
        raise SchwabDailyCandleStoreError("Schwab daily volume was negative.")
    if values["low"] > min(values["open"], values["close"], values["high"]):
        raise SchwabDailyCandleStoreError("Schwab daily low contradicted OHLC.")
    if values["high"] < max(values["open"], values["close"], values["low"]):
        raise SchwabDailyCandleStoreError("Schwab daily high contradicted OHLC.")


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SchwabDailyCandleStoreError(f"Schwab daily {name} was not numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise SchwabDailyCandleStoreError(f"Schwab daily {name} was not finite.")
    return number


def _parse_datetime(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchwabDailyCandleStoreError("Schwab daily timestamp was invalid.") from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabDailyCandleStoreError("Schwab daily timestamp lacked an offset.")
    return value


def _canonical_json_bytes(payload: object) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SchwabDailyCandleStoreError(
            "Schwab daily evidence was not canonical JSON."
        ) from exc


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest().upper()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
