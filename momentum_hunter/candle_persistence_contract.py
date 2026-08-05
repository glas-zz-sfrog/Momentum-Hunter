"""Provisional, temp-root-only persistence contract for Schwab candle evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Protocol, Sequence

from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_CHART_EQUITY_SOURCE,
    SchwabStreamCandleObservation,
)


PROTOTYPE_CANDLE_STORE_SCHEMA_VERSION = 1
PROTOTYPE_CANDLE_STORE_FILENAME = "schwab-candle-observations-prototype.json"
PROTOTYPE_CONTRACT_STATUS = "PROVISIONAL_R031_LIVE_PROOF_PENDING"
PROVIDER_FINALITY_STATUS = "UNVERIFIED"
VOLUME_AUTHORITY_STATUS = "UNVERIFIED"
MAX_PROTOTYPE_STORE_BYTES = 32 * 1024 * 1024


class CandlePersistenceContractError(ValueError):
    """Raised when prototype evidence cannot be preserved without ambiguity."""


class CandleObservationStore(Protocol):
    """Minimal append/load boundary for a future production candle store."""

    def append(
        self, observations: Sequence[SchwabStreamCandleObservation]
    ) -> "CandleAppendResult": ...

    def load(self) -> "CandleStoreSnapshot": ...


@dataclass(frozen=True)
class StoredCandleObservation:
    observation_id: str
    evidence: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", _freeze_json(self.evidence))

    @property
    def minute_identity(self) -> str:
        return str(self.evidence["minuteIdentity"])

    @property
    def received_at(self) -> datetime:
        return _parse_aware_datetime(
            self.evidence["receivedAt"], "observation receivedAt"
        )

    @property
    def arrival_index(self) -> int:
        return _require_nonnegative_int(
            self.evidence["arrivalIndex"], "observation arrivalIndex"
        )

    @property
    def payload_index(self) -> int:
        return _require_nonnegative_int(
            self.evidence["payloadIndex"], "observation payloadIndex"
        )

    @property
    def update_kind(self) -> str:
        return str(self.evidence["updateKind"])

    @property
    def candle(self) -> Mapping[str, object]:
        value = self.evidence["candle"]
        if not isinstance(value, Mapping):
            raise CandlePersistenceContractError(
                "Stored observation candle was not an object."
            )
        return value

    def to_wire(self) -> dict[str, object]:
        return {
            "observationId": self.observation_id,
            "evidence": _thaw_json(self.evidence),
        }


@dataclass(frozen=True)
class CandleStoreSnapshot:
    observations: tuple[StoredCandleObservation, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "schemaVersion": PROTOTYPE_CANDLE_STORE_SCHEMA_VERSION,
            "contractStatus": PROTOTYPE_CONTRACT_STATUS,
            "providerFinality": PROVIDER_FINALITY_STATUS,
            "volumeAuthority": VOLUME_AUTHORITY_STATUS,
            "singleWriterOnly": True,
            "productionReady": False,
            "observations": [item.to_wire() for item in self.observations],
        }

    @property
    def fingerprint(self) -> str:
        return _sha256(_canonical_json_bytes(self.to_wire()))


@dataclass(frozen=True)
class CandleAppendResult:
    inserted_count: int
    duplicate_count: int
    observation_count: int
    snapshot_fingerprint: str
    changed: bool


@dataclass(frozen=True)
class CandleRevisionChain:
    minute_identity: str
    observation_ids: tuple[str, ...]
    revision_count: int
    replay_count: int
    latest_observation_id: str


@dataclass(frozen=True)
class CandleGap:
    source: str
    symbol: str
    session_date: str
    previous_timestamp: datetime
    next_timestamp: datetime
    observed_delta_seconds: float
    missing_interval_count: int
    interval_aligned: bool


@dataclass(frozen=True)
class CandleSymbolHealth:
    source: str
    symbol: str
    status: str
    provider_finality: str
    volume_authority: str
    latest_candle_at: datetime | None
    latest_received_at: datetime | None
    stale: bool
    gap_count: int
    revision_count: int
    observation_count: int


class PrototypeCandleStore:
    """Single-writer store that refuses every path outside an explicit temp root."""

    def __init__(
        self,
        root: Path,
        *,
        allowed_temporary_root: Path,
        replace_file: Callable[[Path, Path], None] | None = None,
    ) -> None:
        system_temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
        self.allowed_temporary_root = allowed_temporary_root.resolve(strict=False)
        _require_same_or_descendant(
            self.allowed_temporary_root,
            system_temporary_root,
        )
        self.root = root.resolve(strict=False)
        _require_descendant(self.root, self.allowed_temporary_root)
        self.path = self.root / PROTOTYPE_CANDLE_STORE_FILENAME
        self._replace_file = replace_file or _replace_path

    def load(self) -> CandleStoreSnapshot:
        if not self.path.exists():
            return CandleStoreSnapshot()
        try:
            if self.path.stat().st_size > MAX_PROTOTYPE_STORE_BYTES:
                raise CandlePersistenceContractError(
                    "Prototype candle store exceeded its bounded size."
                )
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except CandlePersistenceContractError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise CandlePersistenceContractError(
                "Prototype candle store was unreadable."
            ) from exc
        return _snapshot_from_wire(payload)

    def append(
        self, observations: Sequence[SchwabStreamCandleObservation]
    ) -> CandleAppendResult:
        snapshot = self.load()
        by_id = {item.observation_id: item for item in snapshot.observations}
        inserted = 0
        duplicates = 0

        for observation in observations:
            item = _stored_observation(observation)
            current = by_id.get(item.observation_id)
            if current is not None:
                if current.to_wire() != item.to_wire():
                    raise CandlePersistenceContractError(
                        "Observation identity was reused with conflicting evidence."
                    )
                duplicates += 1
                continue
            by_id[item.observation_id] = item
            inserted += 1

        ordered = tuple(sorted(by_id.values(), key=_observation_sort_key))
        updated = CandleStoreSnapshot(observations=ordered)
        if inserted:
            self._atomic_write(_canonical_json_bytes(updated.to_wire()))

        return CandleAppendResult(
            inserted_count=inserted,
            duplicate_count=duplicates,
            observation_count=len(updated.observations),
            snapshot_fingerprint=updated.fingerprint,
            changed=bool(inserted),
        )

    def _atomic_write(self, content: bytes) -> None:
        if len(content) > MAX_PROTOTYPE_STORE_BYTES:
            raise CandlePersistenceContractError(
                "Prototype candle store exceeded its bounded size."
            )
        self.root.mkdir(parents=True, exist_ok=True)
        resolved_root = self.root.resolve(strict=True)
        _require_descendant(resolved_root, self.allowed_temporary_root)
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_file(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def build_revision_chains(
    snapshot: CandleStoreSnapshot,
) -> tuple[CandleRevisionChain, ...]:
    grouped: dict[str, list[StoredCandleObservation]] = {}
    for observation in snapshot.observations:
        grouped.setdefault(observation.minute_identity, []).append(observation)

    chains: list[CandleRevisionChain] = []
    for minute_identity, observations in grouped.items():
        ordered = sorted(observations, key=_observation_sort_key)
        chains.append(
            CandleRevisionChain(
                minute_identity=minute_identity,
                observation_ids=tuple(item.observation_id for item in ordered),
                revision_count=sum(
                    item.update_kind == "REVISION" for item in ordered
                ),
                replay_count=sum(
                    item.update_kind == "IDENTICAL_REPLAY" for item in ordered
                ),
                latest_observation_id=ordered[-1].observation_id,
            )
        )
    return tuple(sorted(chains, key=lambda item: item.minute_identity))


def detect_observed_gaps(
    snapshot: CandleStoreSnapshot,
    *,
    expected_interval: timedelta = timedelta(minutes=1),
) -> tuple[CandleGap, ...]:
    interval_seconds = expected_interval.total_seconds()
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise CandlePersistenceContractError(
            "Expected candle interval must be positive and finite."
        )

    latest_by_minute = _latest_observations_by_minute(snapshot)
    grouped: dict[tuple[str, str, str], set[datetime]] = {}
    for observation in latest_by_minute.values():
        candle = observation.candle
        key = (
            str(candle["source"]),
            str(candle["symbol"]),
            str(candle["sessionDate"]),
        )
        grouped.setdefault(key, set()).add(
            _parse_aware_datetime(candle["timestamp"], "candle timestamp")
        )

    gaps: list[CandleGap] = []
    for (source, symbol, session_date), timestamps in grouped.items():
        ordered = sorted(timestamps)
        for previous, current in zip(ordered, ordered[1:]):
            delta_seconds = (current - previous).total_seconds()
            if delta_seconds <= interval_seconds:
                continue
            ratio = delta_seconds / interval_seconds
            missing = max(1, math.ceil(ratio) - 1)
            gaps.append(
                CandleGap(
                    source=source,
                    symbol=symbol,
                    session_date=session_date,
                    previous_timestamp=previous,
                    next_timestamp=current,
                    observed_delta_seconds=delta_seconds,
                    missing_interval_count=missing,
                    interval_aligned=math.isclose(ratio, round(ratio)),
                )
            )
    return tuple(
        sorted(
            gaps,
            key=lambda item: (
                item.source,
                item.symbol,
                item.session_date,
                item.previous_timestamp,
            ),
        )
    )


def assess_candle_health(
    snapshot: CandleStoreSnapshot,
    *,
    evaluated_at: datetime,
    stale_after: timedelta,
    expected_symbols: Iterable[str] = (),
) -> tuple[CandleSymbolHealth, ...]:
    evaluated = _require_aware(evaluated_at, "evaluated_at")
    stale_seconds = stale_after.total_seconds()
    if not math.isfinite(stale_seconds) or stale_seconds <= 0:
        raise CandlePersistenceContractError(
            "Stale threshold must be positive and finite."
        )

    latest_by_minute = _latest_observations_by_minute(snapshot)
    grouped: dict[tuple[str, str], list[StoredCandleObservation]] = {}
    for observation in latest_by_minute.values():
        candle = observation.candle
        grouped.setdefault(
            (str(candle["source"]), str(candle["symbol"])), []
        ).append(observation)

    expected = {str(symbol).strip().upper() for symbol in expected_symbols}
    expected.discard("")
    for symbol in expected:
        grouped.setdefault((SCHWAB_CHART_EQUITY_SOURCE, symbol), [])

    gaps = detect_observed_gaps(snapshot)
    gap_counts: dict[tuple[str, str], int] = {}
    for gap in gaps:
        key = (gap.source, gap.symbol)
        gap_counts[key] = gap_counts.get(key, 0) + 1

    chains = build_revision_chains(snapshot)
    revision_by_minute = {
        chain.minute_identity: chain.revision_count for chain in chains
    }

    results: list[CandleSymbolHealth] = []
    for (source, symbol), observations in sorted(grouped.items()):
        if not observations:
            results.append(
                CandleSymbolHealth(
                    source=source,
                    symbol=symbol,
                    status="NO_OBSERVATIONS",
                    provider_finality=PROVIDER_FINALITY_STATUS,
                    volume_authority=VOLUME_AUTHORITY_STATUS,
                    latest_candle_at=None,
                    latest_received_at=None,
                    stale=True,
                    gap_count=0,
                    revision_count=0,
                    observation_count=0,
                )
            )
            continue

        latest_candle_at = max(
            _parse_aware_datetime(item.candle["timestamp"], "candle timestamp")
            for item in observations
        )
        latest_received_at = max(item.received_at for item in observations)
        if latest_received_at > evaluated:
            raise CandlePersistenceContractError(
                "Candle receipt occurred after the evaluation clock."
            )
        stale = evaluated - latest_received_at > stale_after
        gap_count = gap_counts.get((source, symbol), 0)
        if stale and gap_count:
            status = "PROVISIONAL_STALE_WITH_GAPS"
        elif stale:
            status = "PROVISIONAL_STALE"
        elif gap_count:
            status = "PROVISIONAL_WITH_GAPS"
        else:
            status = "PROVISIONAL_CURRENT"
        results.append(
            CandleSymbolHealth(
                source=source,
                symbol=symbol,
                status=status,
                provider_finality=PROVIDER_FINALITY_STATUS,
                volume_authority=VOLUME_AUTHORITY_STATUS,
                latest_candle_at=latest_candle_at,
                latest_received_at=latest_received_at,
                stale=stale,
                gap_count=gap_count,
                revision_count=sum(
                    revision_by_minute.get(item.minute_identity, 0)
                    for item in observations
                ),
                observation_count=len(observations),
            )
        )
    return tuple(results)


def _snapshot_from_wire(payload: object) -> CandleStoreSnapshot:
    if not isinstance(payload, Mapping):
        raise CandlePersistenceContractError(
            "Prototype candle store root was not an object."
        )
    expected_metadata = {
        "schemaVersion": PROTOTYPE_CANDLE_STORE_SCHEMA_VERSION,
        "contractStatus": PROTOTYPE_CONTRACT_STATUS,
        "providerFinality": PROVIDER_FINALITY_STATUS,
        "volumeAuthority": VOLUME_AUTHORITY_STATUS,
        "singleWriterOnly": True,
        "productionReady": False,
    }
    expected_root_keys = set(expected_metadata) | {"observations"}
    if set(payload) != expected_root_keys:
        raise CandlePersistenceContractError(
            "Prototype candle store fields were not the exact supported schema."
        )
    for key, expected in expected_metadata.items():
        if payload.get(key) != expected:
            raise CandlePersistenceContractError(
                f"Prototype candle store metadata {key} was invalid."
            )
    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, list):
        raise CandlePersistenceContractError(
            "Prototype candle store observations were not a list."
        )

    observations: list[StoredCandleObservation] = []
    seen_ids: set[str] = set()
    for raw in raw_observations:
        if not isinstance(raw, Mapping):
            raise CandlePersistenceContractError(
                "Stored candle observation was not an object."
            )
        if set(raw) != {"observationId", "evidence"}:
            raise CandlePersistenceContractError(
                "Stored candle observation fields were not the exact schema."
            )
        evidence = raw.get("evidence")
        observation_id = str(raw.get("observationId", ""))
        if not isinstance(evidence, Mapping):
            raise CandlePersistenceContractError(
                "Stored candle observation evidence was invalid."
            )
        item = StoredCandleObservation(
            observation_id=observation_id,
            evidence=dict(evidence),
        )
        _validate_stored_observation(item)
        if observation_id in seen_ids:
            raise CandlePersistenceContractError(
                "Prototype candle store repeated an observation identity."
            )
        seen_ids.add(observation_id)
        observations.append(item)

    ordered = tuple(sorted(observations, key=_observation_sort_key))
    if tuple(observations) != ordered:
        raise CandlePersistenceContractError(
            "Prototype candle store observations were not canonicalized."
        )
    return CandleStoreSnapshot(observations=ordered)


def _stored_observation(
    observation: SchwabStreamCandleObservation,
) -> StoredCandleObservation:
    if observation.candle.source != SCHWAB_CHART_EQUITY_SOURCE:
        raise CandlePersistenceContractError(
            "Prototype store accepts only Schwab CHART_EQUITY observations."
        )
    evidence = observation.to_evidence()
    observation_id = _sha256(_canonical_json_bytes(evidence))
    item = StoredCandleObservation(observation_id=observation_id, evidence=evidence)
    _validate_stored_observation(item)
    return item


def _validate_stored_observation(item: StoredCandleObservation) -> None:
    expected_id = _sha256(_canonical_json_bytes(item.to_wire()["evidence"]))
    if item.observation_id != expected_id:
        raise CandlePersistenceContractError(
            "Stored candle observation hash did not match its evidence."
        )
    expected_evidence_keys = {
        "arrivalIndex",
        "payloadIndex",
        "receivedAt",
        "minuteIdentity",
        "updateKind",
        "changedFields",
        "outOfOrder",
        "sequenceDeltaFromPreviousArrival",
        "candle",
    }
    if set(item.evidence) != expected_evidence_keys:
        raise CandlePersistenceContractError(
            "Stored candle evidence fields were not the exact schema."
        )
    if item.update_kind not in {
        "FIRST_OBSERVATION",
        "IDENTICAL_REPLAY",
        "REVISION",
    }:
        raise CandlePersistenceContractError(
            "Stored candle observation update kind was invalid."
        )
    _parse_aware_datetime(item.evidence.get("receivedAt"), "receivedAt")
    item.arrival_index
    item.payload_index
    if not isinstance(item.evidence.get("changedFields"), tuple):
        raise CandlePersistenceContractError(
            "Stored candle changed fields were invalid."
        )
    if not isinstance(item.evidence.get("outOfOrder"), bool):
        raise CandlePersistenceContractError(
            "Stored candle out-of-order flag was invalid."
        )
    sequence_delta = item.evidence.get("sequenceDeltaFromPreviousArrival")
    if sequence_delta is not None and (
        isinstance(sequence_delta, bool) or not isinstance(sequence_delta, int)
    ):
        raise CandlePersistenceContractError(
            "Stored candle sequence delta was invalid."
        )
    candle = item.candle
    required = {
        "symbol",
        "timestamp",
        "sessionDate",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "sequence",
        "source",
        "ohlcvComplete",
    }
    if set(candle) != required:
        raise CandlePersistenceContractError(
            "Stored candle fields were not the exact schema."
        )
    if candle.get("source") != SCHWAB_CHART_EQUITY_SOURCE:
        raise CandlePersistenceContractError(
            "Stored candle observation source was not CHART_EQUITY."
        )
    if candle.get("ohlcvComplete") is not True:
        raise CandlePersistenceContractError(
            "Stored candle did not contain complete OHLCV evidence."
        )
    timestamp = _parse_aware_datetime(candle.get("timestamp"), "candle timestamp")
    symbol = str(candle.get("symbol", ""))
    session_date = timestamp.astimezone(EASTERN_TZ).date().isoformat()
    if candle.get("sessionDate") != session_date:
        raise CandlePersistenceContractError(
            "Stored candle session date contradicted its timestamp."
        )
    expected_minute_identity = "|".join(
        (
            SCHWAB_CHART_EQUITY_SOURCE,
            symbol,
            session_date,
            timestamp.isoformat(),
        )
    )
    if item.minute_identity != expected_minute_identity:
        raise CandlePersistenceContractError(
            "Stored candle minute identity contradicted its evidence."
        )
    open_price = _finite_number(candle.get("open"), "candle open", positive=True)
    high = _finite_number(candle.get("high"), "candle high", positive=True)
    low = _finite_number(candle.get("low"), "candle low", positive=True)
    close = _finite_number(candle.get("close"), "candle close", positive=True)
    _finite_number(candle.get("volume"), "candle volume", nonnegative=True)
    _require_positive_int(candle.get("sequence"), "candle sequence")
    if high < max(open_price, low, close) or low > min(open_price, high, close):
        raise CandlePersistenceContractError(
            "Stored candle OHLC values were contradictory."
        )


def _latest_observations_by_minute(
    snapshot: CandleStoreSnapshot,
) -> dict[str, StoredCandleObservation]:
    latest: dict[str, StoredCandleObservation] = {}
    for observation in snapshot.observations:
        current = latest.get(observation.minute_identity)
        if current is None or _observation_sort_key(current) < _observation_sort_key(
            observation
        ):
            latest[observation.minute_identity] = observation
    return latest


def _observation_sort_key(
    observation: StoredCandleObservation,
) -> tuple[datetime, int, int, str]:
    return (
        observation.received_at,
        observation.arrival_index,
        observation.payload_index,
        observation.observation_id,
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
        raise CandlePersistenceContractError(
            "Candle evidence was not canonically serializable."
        ) from exc
    return (text + "\n").encode("utf-8")


def _parse_aware_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise CandlePersistenceContractError(f"{label} was not a timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandlePersistenceContractError(f"{label} was invalid.") from exc
    return _require_aware(parsed, label)


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CandlePersistenceContractError(f"{label} was timezone-naive.")
    return value


def _require_nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CandlePersistenceContractError(
            f"{label} was not a nonnegative integer."
        )
    return value


def _require_positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CandlePersistenceContractError(
            f"{label} was not a positive integer."
        )
    return value


def _finite_number(
    value: object,
    label: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandlePersistenceContractError(f"{label} was not numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise CandlePersistenceContractError(f"{label} was not finite.")
    if positive and number <= 0:
        raise CandlePersistenceContractError(f"{label} was not positive.")
    if nonnegative and number < 0:
        raise CandlePersistenceContractError(f"{label} was negative.")
    return number


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_descendant(path: Path, root: Path) -> None:
    if path == root or root not in path.parents:
        raise CandlePersistenceContractError(
            "Prototype candle store path must be below the allowed temporary root."
        )


def _require_same_or_descendant(path: Path, root: Path) -> None:
    if path != root and root not in path.parents:
        raise CandlePersistenceContractError(
            "Allowed prototype root must be inside the operating-system temp directory."
        )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _replace_path(source: Path, destination: Path) -> None:
    os.replace(source, destination)
