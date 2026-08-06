"""Bounded background history loading for workstation candle charts."""

from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.config import DATA_DIR
from momentum_hunter.schwab_candle_backfill import (
    CandleBackfillOptions,
    SchwabHistoricalCandleBackfiller,
)
from momentum_hunter.schwab_candle_collector import CandleSymbolUniverse
from momentum_hunter.schwab_candle_contract import normalize_symbols
from momentum_hunter.schwab_candle_store import (
    SCHWAB_CANDLE_STORE_ROOT,
    SchwabCandleStore,
)
from momentum_hunter.schwab_daily_candle_store import (
    SCHWAB_DAILY_CANDLE_STORE_ROOT,
    SchwabDailyCandleStore,
)


AUTOMATIC_BACKFILL_SCHEMA_VERSION = 1
DEFAULT_AUTOMATIC_BACKFILL_STATE_PATH = (
    DATA_DIR / "runtime" / "automatic-candle-backfill-state.json"
)
DEFAULT_AUTOMATION_MANIFEST_PATH = (
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "MomentumHunter"
    / "Automation"
    / "automation-manifest.json"
)
DEFAULT_REFRESH_COOLDOWN = timedelta(minutes=5)
MAX_AUTOMATIC_SYMBOLS = 10
ACTIVE_STATES = frozenset({"QUEUED", "RUNNING"})
TERMINAL_STATES = frozenset({"COMPLETE", "PARTIAL", "FAILED"})


class AutomaticCandleBackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutomaticBackfillRequest:
    symbol: str
    status: str
    detail: str
    requested_at: str | None
    started_at: str | None
    completed_at: str | None
    attempt_count: int
    coalesced: bool = False

    def to_evidence(self) -> dict[str, object]:
        return {
            "schemaVersion": AUTOMATIC_BACKFILL_SCHEMA_VERSION,
            "symbol": self.symbol,
            "status": self.status,
            "detail": self.detail,
            "requestedAt": self.requested_at,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "attemptCount": self.attempt_count,
            "coalesced": self.coalesced,
            "networkMayRun": self.status in ACTIVE_STATES,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }


class AutomaticCandleBackfillCoordinator:
    """Coalesces chart-triggered backfills behind one finite worker queue."""

    def __init__(
        self,
        *,
        state_path: Path = DEFAULT_AUTOMATIC_BACKFILL_STATE_PATH,
        manifest_path: Path = DEFAULT_AUTOMATION_MANIFEST_PATH,
        minute_store_root: Path = SCHWAB_CANDLE_STORE_ROOT,
        daily_store_root: Path = SCHWAB_DAILY_CANDLE_STORE_ROOT,
        run_backfill: Callable[[tuple[str, ...]], Mapping[str, object]] | None = None,
        utc_clock: Callable[[], datetime] | None = None,
        refresh_cooldown: timedelta = DEFAULT_REFRESH_COOLDOWN,
        max_symbols: int = MAX_AUTOMATIC_SYMBOLS,
    ) -> None:
        self.state_path = state_path
        self.manifest_path = manifest_path
        self.minute_store_root = minute_store_root
        self.daily_store_root = daily_store_root
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self.refresh_cooldown = refresh_cooldown
        self.max_symbols = max(1, min(MAX_AUTOMATIC_SYMBOLS, int(max_symbols)))
        self._run_backfill = run_backfill or self._run_guarded_backfill
        self._lock = threading.Lock()
        self._queue: deque[str] = deque()
        self._records: dict[str, dict[str, object]] = {}
        self._state_error: str | None = None
        self._worker: threading.Thread | None = None
        self._load_state()
        with self._lock:
            if self._queue:
                self._start_worker_locked()

    def request(self, symbol: str, *, reason: str) -> dict[str, object]:
        clean_symbol = _symbol(symbol)
        now = _aware(self.utc_clock())
        with self._lock:
            if self._state_error is not None:
                return self._request_evidence(
                    clean_symbol,
                    status="FAILED",
                    detail=self._state_error,
                )
            current = self._records.get(clean_symbol)
            if current is not None and str(current.get("status")) in ACTIVE_STATES:
                return self._record_evidence(current, coalesced=True)
            if current is not None and str(current.get("status")) == "FAILED":
                return self._record_evidence(current, coalesced=True)
            if current is not None and str(current.get("status")) in {"COMPLETE", "PARTIAL"}:
                completed_at = _optional_timestamp(current.get("completedAt"))
                if completed_at is not None and now - completed_at < self.refresh_cooldown:
                    return self._record_evidence(current, coalesced=True)
            active_count = sum(
                str(record.get("status")) in ACTIVE_STATES
                for record in self._records.values()
            )
            if active_count >= self.max_symbols:
                return self._request_evidence(
                    clean_symbol,
                    status="FAILED",
                    detail="Automatic candle history queue is at its ten-symbol safety limit.",
                )
            attempt_count = int(current.get("attemptCount", 0)) + 1 if current else 1
            record: dict[str, object] = {
                "symbol": clean_symbol,
                "status": "QUEUED",
                "detail": reason,
                "requestedAt": _timestamp(now),
                "startedAt": None,
                "completedAt": None,
                "attemptCount": attempt_count,
                "recoveryCount": int(current.get("recoveryCount", 0)) if current else 0,
            }
            self._records[clean_symbol] = record
            self._queue.append(clean_symbol)
            try:
                self._persist_locked()
            except OSError as exc:
                self._queue.pop()
                self._records.pop(clean_symbol, None)
                self._state_error = (
                    "Automatic candle history state could not be persisted; "
                    f"network loading stayed locked ({type(exc).__name__})."
                )
                return self._request_evidence(
                    clean_symbol,
                    status="FAILED",
                    detail=self._state_error,
                )
            evidence = self._record_evidence(record)
            self._start_worker_locked()
            return evidence

    def status(self, symbol: str) -> dict[str, object] | None:
        clean_symbol = _symbol(symbol)
        with self._lock:
            record = self._records.get(clean_symbol)
            return self._record_evidence(record) if record is not None else None

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        deadline = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, timeout_seconds))
        while datetime.now(timezone.utc) < deadline:
            with self._lock:
                if not self._queue and not any(
                    str(record.get("status")) in ACTIVE_STATES
                    for record in self._records.values()
                ):
                    return True
            threading.Event().wait(0.01)
        return False

    def _start_worker_locked(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="MomentumHunterCandleBackfill",
            daemon=True,
        )
        self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                symbol = self._queue.popleft()
                record = self._records[symbol]
                record["status"] = "RUNNING"
                record["startedAt"] = _timestamp(_aware(self.utc_clock()))
                record["detail"] = "Loading bounded Schwab minute and Daily history."
                try:
                    self._persist_locked()
                except OSError as exc:
                    record["status"] = "FAILED"
                    record["completedAt"] = _timestamp(_aware(self.utc_clock()))
                    record["detail"] = (
                        "Automatic candle history state could not record the running job; "
                        f"network loading stayed locked ({type(exc).__name__})."
                    )
                    self._state_error = str(record["detail"])
                    return
            try:
                result = self._run_backfill((symbol,))
                result_status = str(result.get("status", "FAILED")).upper()
                if result_status not in {"COMPLETE", "PARTIAL"}:
                    result_status = "FAILED"
                detail = _result_detail(result)
            except Exception as exc:  # Fail closed; error details never include credentials.
                result_status = "FAILED"
                detail = f"Automatic candle history load failed ({type(exc).__name__})."
            with self._lock:
                record = self._records[symbol]
                record["status"] = result_status
                record["completedAt"] = _timestamp(_aware(self.utc_clock()))
                record["detail"] = detail
                try:
                    self._persist_locked()
                except OSError as exc:
                    record["status"] = "FAILED"
                    record["detail"] = (
                        "Automatic candle history result could not be persisted; "
                        f"further loading stayed locked ({type(exc).__name__})."
                    )
                    self._state_error = str(record["detail"])
                    return

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping) or payload.get("schemaVersion") != AUTOMATIC_BACKFILL_SCHEMA_VERSION:
                raise AutomaticCandleBackfillError("Automatic candle history state schema is unsupported.")
            raw_records = payload.get("records")
            if not isinstance(raw_records, Mapping):
                raise AutomaticCandleBackfillError("Automatic candle history state omitted records.")
            for raw_symbol, raw_record in raw_records.items():
                symbol = _symbol(str(raw_symbol))
                if not isinstance(raw_record, Mapping):
                    raise AutomaticCandleBackfillError("Automatic candle history state contained an invalid record.")
                status = str(raw_record.get("status", ""))
                if status not in ACTIVE_STATES | TERMINAL_STATES:
                    raise AutomaticCandleBackfillError("Automatic candle history state contained an invalid status.")
                record = dict(raw_record)
                record["symbol"] = symbol
                if status in ACTIVE_STATES:
                    recovery_count = int(record.get("recoveryCount", 0))
                    if recovery_count >= 1:
                        record["status"] = "FAILED"
                        record["completedAt"] = _timestamp(_aware(self.utc_clock()))
                        record["detail"] = "Interrupted history load exhausted its one restart recovery."
                    else:
                        record["status"] = "QUEUED"
                        record["startedAt"] = None
                        record["recoveryCount"] = recovery_count + 1
                        record["detail"] = "Recovered one interrupted history load after Engine Host restart."
                        self._queue.append(symbol)
                self._records[symbol] = record
            self._persist_unlocked()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, AutomaticCandleBackfillError) as exc:
            self._records.clear()
            self._queue.clear()
            self._state_error = (
                "Automatic candle history state is unreadable or untrusted; "
                f"network loading stayed locked ({type(exc).__name__})."
            )

    def _persist_locked(self) -> None:
        self._persist_unlocked()

    def _persist_unlocked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": AUTOMATIC_BACKFILL_SCHEMA_VERSION,
            "updatedAt": _timestamp(_aware(self.utc_clock())),
            "records": {
                symbol: self._records[symbol] for symbol in sorted(self._records)
            },
            "maximumSymbols": self.max_symbols,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    def _run_guarded_backfill(self, symbols: tuple[str, ...]) -> Mapping[str, object]:
        ending = expected_account_ending_from_manifest(self.manifest_path)
        universe = _automatic_universe(symbols)
        backfiller = SchwabHistoricalCandleBackfiller(
            minute_store=SchwabCandleStore(self.minute_store_root),
            daily_store=SchwabDailyCandleStore(self.daily_store_root),
        )
        return backfiller.backfill(
            universe,
            CandleBackfillOptions(expected_account_ending=ending),
        )

    def _record_evidence(
        self,
        record: Mapping[str, object],
        *,
        coalesced: bool = False,
    ) -> dict[str, object]:
        return AutomaticBackfillRequest(
            symbol=str(record.get("symbol", "")),
            status=str(record.get("status", "FAILED")),
            detail=str(record.get("detail", "History-load status unavailable.")),
            requested_at=_optional_text(record.get("requestedAt")),
            started_at=_optional_text(record.get("startedAt")),
            completed_at=_optional_text(record.get("completedAt")),
            attempt_count=int(record.get("attemptCount", 0)),
            coalesced=coalesced,
        ).to_evidence()

    def _request_evidence(
        self,
        symbol: str,
        *,
        status: str,
        detail: str,
    ) -> dict[str, object]:
        return AutomaticBackfillRequest(
            symbol=symbol,
            status=status,
            detail=detail,
            requested_at=None,
            started_at=None,
            completed_at=None,
            attempt_count=0,
        ).to_evidence()


def expected_account_ending_from_manifest(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AutomaticCandleBackfillError(
            "Automation manifest could not authorize candle history loading."
        ) from exc
    if not isinstance(payload, Mapping) or payload.get("schemaVersion") != 1:
        raise AutomaticCandleBackfillError("Automation manifest schema is unsupported.")
    ending = str(payload.get("expectedAccountEnding", "")).strip()
    if not re.fullmatch(r"\d{4}", ending):
        raise AutomaticCandleBackfillError("Automation manifest account ending is invalid.")
    if str(payload.get("expectedAccountType", "")).strip() != "INDIVIDUAL_CASH":
        raise AutomaticCandleBackfillError("Automation manifest account type is not INDIVIDUAL_CASH.")
    configured_root = Path(str(payload.get("repositoryRoot", ""))).resolve(strict=False)
    current_root = Path(__file__).resolve().parents[1]
    if configured_root != current_root:
        raise AutomaticCandleBackfillError(
            "Automation manifest is pinned to a different checkout; automatic history loading stayed locked."
        )
    return ending


def _automatic_universe(symbols: Sequence[str]) -> CandleSymbolUniverse:
    normalized = normalize_symbols(symbols)
    if not normalized or len(normalized) > MAX_AUTOMATIC_SYMBOLS:
        raise AutomaticCandleBackfillError("Automatic candle history universe is invalid.")
    return CandleSymbolUniverse(
        symbols=normalized,
        sources_by_symbol={symbol: ("WORKSTATION_CHART_REQUEST",) for symbol in normalized},
        excluded_symbols=(),
        warnings=(),
        input_fingerprints={},
    )


def _result_detail(result: Mapping[str, object]) -> str:
    status = str(result.get("status", "FAILED")).upper()
    raw_symbols = result.get("symbols")
    symbol_count = len(raw_symbols) if isinstance(raw_symbols, list) else 0
    if status == "COMPLETE":
        return f"Schwab minute and Daily history loaded for {symbol_count or 1} symbol(s)."
    if status == "PARTIAL":
        return "Schwab history load completed with insufficient or failed timeframe evidence."
    return "Schwab history load did not complete."


def _symbol(value: str) -> str:
    symbols = normalize_symbols((value,))
    if len(symbols) != 1:
        raise ValueError("Automatic candle history request requires one valid symbol.")
    return symbols[0]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _aware(value).isoformat().replace("+00:00", "Z")


def _optional_timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _aware(parsed)


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
