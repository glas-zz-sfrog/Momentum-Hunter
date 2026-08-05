"""Bounded Schwab one-minute collector with explicit reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.config import DATA_DIR
from momentum_hunter.scheduling import is_market_open_day
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_CHART_EQUITY_SERVICE,
    SchwabMinuteCandle,
    SchwabCandleContractError,
    SchwabStreamCandleObservation,
    build_chart_equity_subscription,
    normalize_symbols,
    parse_chart_equity_messages,
    parse_price_history_response,
    session_for_timestamp,
)
from momentum_hunter.schwab_candle_observer import (
    ACK_TIMEOUT_SECONDS,
    GuardedStreamerAccess,
    SchwabCandleAccessGuard,
    SchwabCandleHttpTransport,
    SchwabCandleObserverAuthorizationError,
    SchwabCandleObserverNetworkError,
    SchwabCandleObserverResponseError,
    StreamConnection,
    StreamConnectionFactory,
    WebSocketClientFactory,
    build_streamer_login,
    parse_streamer_bootstrap,
    require_streamer_acknowledgement,
)
from momentum_hunter.schwab_candle_store import (
    SCHWAB_CANDLE_STORE_ROOT,
    CandleStoreMutation,
    SchwabCandleStore,
)


COLLECTOR_SCHEMA_VERSION = 1
COLLECTOR_MODE = "SCHWAB_INCREMENTAL_CANDLE_COLLECTOR"
MAX_COLLECTOR_SYMBOLS = 10
MAX_HUNTER_CANDIDATES = 5
MIN_COLLECTION_SECONDS = 60
MAX_COLLECTION_SECONDS = 900
DEFAULT_COLLECTION_SECONDS = 300
DEFAULT_HISTORY_ATTEMPTS = 2
DEFAULT_STALE_SECONDS = 180
SHADOW_STATE_PATH = DATA_DIR / "shadow-trading" / "shadow-trading-state.json"
SHADOW_DECISION_CYCLES_PATH = (
    DATA_DIR / "shadow-trading" / "shadow-decision-cycles.json"
)
TERMINAL_SHADOW_STATES = frozenset(
    {
        "winner",
        "loser",
        "flat",
        "cancelled",
        "canceled",
        "invalidated",
        "rejected",
        "completed",
        "closed",
    }
)


class SchwabCandleCollectorError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandleUniverseSources:
    candidate_report: Path | None = None
    decision_cycles: Path | None = None
    shadow_state: Path | None = None
    explicit_selected_symbol: str | None = None


@dataclass(frozen=True)
class CandleSymbolUniverse:
    symbols: tuple[str, ...]
    sources_by_symbol: Mapping[str, tuple[str, ...]]
    excluded_symbols: tuple[str, ...]
    warnings: tuple[str, ...]
    input_fingerprints: Mapping[str, str]

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_evidence())

    def to_evidence(self) -> dict[str, object]:
        return {
            "symbols": list(self.symbols),
            "sourcesBySymbol": {
                symbol: list(self.sources_by_symbol[symbol])
                for symbol in sorted(self.sources_by_symbol)
            },
            "excludedSymbols": list(self.excluded_symbols),
            "warnings": list(self.warnings),
            "inputFingerprints": dict(sorted(self.input_fingerprints.items())),
            "maximumSymbols": MAX_COLLECTOR_SYMBOLS,
            "maximumHunterCandidates": MAX_HUNTER_CANDIDATES,
        }


@dataclass(frozen=True)
class CandleCollectorOptions:
    expected_account_ending: str
    duration_seconds: int = DEFAULT_COLLECTION_SECONDS
    extended_hours: bool = True
    history_attempts: int = DEFAULT_HISTORY_ATTEMPTS
    stale_after_seconds: int = DEFAULT_STALE_SECONDS

    def __post_init__(self) -> None:
        if len(self.expected_account_ending) != 4 or not self.expected_account_ending.isdigit():
            raise SchwabCandleCollectorError(
                "Expected account ending must contain exactly four digits."
            )
        if not MIN_COLLECTION_SECONDS <= self.duration_seconds <= MAX_COLLECTION_SECONDS:
            raise SchwabCandleCollectorError(
                "Collection duration must be between 60 and 900 seconds."
            )
        if not 1 <= self.history_attempts <= 3:
            raise SchwabCandleCollectorError(
                "History attempts must be between one and three."
            )
        if not 60 <= self.stale_after_seconds <= 900:
            raise SchwabCandleCollectorError(
                "Stale threshold must be between 60 and 900 seconds."
            )


def resolve_candle_universe(
    sources: CandleUniverseSources,
    *,
    expected_market_date: date | None = None,
) -> CandleSymbolUniverse:
    ranked: list[tuple[int, str]] = []
    active_positions: list[tuple[str, str]] = []
    selected_symbols: list[tuple[str, str]] = []
    fingerprints: dict[str, str] = {}
    warnings: list[str] = []

    if sources.shadow_state is not None and sources.shadow_state.exists():
        payload, digest = _load_json_with_hash(sources.shadow_state, "Shadow state")
        fingerprints["shadowState"] = digest
        trades = payload.get("trades") if isinstance(payload, Mapping) else None
        if not isinstance(trades, list):
            raise SchwabCandleCollectorError("Shadow state omitted its trade list.")
        for trade in trades:
            if not isinstance(trade, Mapping):
                raise SchwabCandleCollectorError("Shadow state contained an invalid trade.")
            status = str(trade.get("status", "")).strip().lower()
            position = trade.get("position")
            outcome = trade.get("outcome")
            if (
                isinstance(position, Mapping)
                and not isinstance(outcome, Mapping)
                and status not in TERMINAL_SHADOW_STATES
            ):
                active_positions.append(
                    (_symbol(trade.get("symbol")), "ACTIVE_SHADOW_POSITION")
                )

    selected = sources.explicit_selected_symbol
    if selected:
        selected_symbols.append((_symbol(selected), "EXPLICIT_SELECTED_SYMBOL"))
    if sources.decision_cycles is not None and sources.decision_cycles.exists():
        payload, digest = _load_json_with_hash(
            sources.decision_cycles, "Shadow decision cycles"
        )
        fingerprints["decisionCycles"] = digest
        cycles = payload.get("cycles") if isinstance(payload, Mapping) else None
        if not isinstance(cycles, list):
            raise SchwabCandleCollectorError(
                "Shadow decision-cycle evidence omitted its cycle list."
            )
        selected_rows = []
        for row in cycles:
            if not isinstance(row, Mapping) or not str(
                row.get("selected_symbol", "")
            ).strip():
                continue
            decision_at = _parse_optional_datetime(row.get("decision_at"))
            if expected_market_date is not None and (
                decision_at is None
                or decision_at.astimezone(EASTERN_TZ).date() != expected_market_date
            ):
                continue
            selected_rows.append(row)
        if selected_rows:
            latest = max(
                selected_rows,
                key=lambda row: str(row.get("decision_at", "")),
            )
            selected_symbols.append(
                (_symbol(latest.get("selected_symbol")), "LATEST_SELECTED_SYMBOL")
            )

    if sources.candidate_report is not None:
        if not sources.candidate_report.exists():
            raise SchwabCandleCollectorError("Hunter candidate report was missing.")
        payload, digest = _load_json_with_hash(
            sources.candidate_report, "Hunter candidate report"
        )
        fingerprints["candidateReport"] = digest
        metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
        if not isinstance(metadata, Mapping):
            raise SchwabCandleCollectorError(
                "Hunter candidate report omitted its metadata."
            )
        if str(metadata.get("source_session", "")).strip().lower() != "opening":
            raise SchwabCandleCollectorError(
                "Hunter candidate report was not an opening-session report."
            )
        generated_at = _parse_optional_datetime(metadata.get("generated_at"))
        if generated_at is None:
            raise SchwabCandleCollectorError(
                "Hunter candidate report generation timestamp was invalid."
            )
        if expected_market_date is not None and (
            generated_at.astimezone(EASTERN_TZ).date() != expected_market_date
        ):
            raise SchwabCandleCollectorError(
                "Hunter candidate report did not match the collection market date."
            )
        rows = payload.get("candidates") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise SchwabCandleCollectorError(
                "Hunter candidate report omitted its candidate list."
            )
        observed_ranks: set[int] = set()
        observed_symbols: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                raise SchwabCandleCollectorError(
                    "Hunter candidate report contained an invalid candidate."
                )
            rank = row.get("rank")
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
                raise SchwabCandleCollectorError(
                    "Hunter candidate report contained an invalid rank."
                )
            symbol = _symbol(row.get("symbol") or row.get("ticker"))
            if rank in observed_ranks:
                raise SchwabCandleCollectorError(
                    "Hunter candidate report contained a duplicate rank."
                )
            if symbol in observed_symbols:
                raise SchwabCandleCollectorError(
                    "Hunter candidate report contained a duplicate symbol."
                )
            observed_ranks.add(rank)
            observed_symbols.add(symbol)
            ranked.append((rank, symbol))
        ranked.sort(key=lambda item: (item[0], item[1]))
        ranked = ranked[:MAX_HUNTER_CANDIDATES]

    # Selected symbols and both market benchmarks are never displaced by a
    # crowded active-position list. Lower-priority exclusions remain visible.
    ordered: list[tuple[str, str]] = []
    ordered.extend(selected_symbols)
    ordered.extend(active_positions[: max(0, MAX_COLLECTOR_SYMBOLS - 4)])
    ordered.extend((symbol, "BENCHMARK") for symbol in ("SPY", "IWM"))
    ordered.extend((symbol, f"HUNTER_CANDIDATE_RANK_{rank}") for rank, symbol in ranked)
    ordered.extend(active_positions[max(0, MAX_COLLECTOR_SYMBOLS - 4) :])
    sources_by_symbol: dict[str, list[str]] = {}
    symbol_order: list[str] = []
    for symbol, source in ordered:
        if symbol not in sources_by_symbol:
            symbol_order.append(symbol)
            sources_by_symbol[symbol] = []
        if source not in sources_by_symbol[symbol]:
            sources_by_symbol[symbol].append(source)

    excluded = tuple(symbol_order[MAX_COLLECTOR_SYMBOLS:])
    selected_symbols = tuple(symbol_order[:MAX_COLLECTOR_SYMBOLS])
    if excluded:
        warnings.append("SYMBOL_LIMIT_EXCLUDED_LOWER_PRIORITY_ITEMS")
    return CandleSymbolUniverse(
        symbols=selected_symbols,
        sources_by_symbol={
            symbol: tuple(sources_by_symbol[symbol]) for symbol in selected_symbols
        },
        excluded_symbols=excluded,
        warnings=tuple(warnings),
        input_fingerprints=fingerprints,
    )


class SchwabIncrementalCandleCollector:
    def __init__(
        self,
        *,
        store: SchwabCandleStore,
        access_guard: object | None = None,
        http_transport: object | None = None,
        stream_factory: StreamConnectionFactory | None = None,
        utc_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.store = store
        self.access_guard = access_guard or SchwabCandleAccessGuard()
        self.http = http_transport or SchwabCandleHttpTransport()
        self.stream_factory = stream_factory or WebSocketClientFactory()
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self.monotonic_clock = monotonic_clock or time.monotonic
        self.sleep = sleep or time.sleep

    def collect(
        self,
        universe: CandleSymbolUniverse,
        options: CandleCollectorOptions,
    ) -> dict[str, object]:
        started_at = _aware_now(self.utc_clock())
        market_date = started_at.astimezone(EASTERN_TZ).date()
        session = session_for_timestamp(started_at)
        if not is_market_open_day(market_date) or session == "closed":
            raise SchwabCandleCollectorError(
                "Schwab candle collection requires a U.S. equity market session."
            )
        if session == "extended" and not options.extended_hours:
            raise SchwabCandleCollectorError(
                "Extended-hours candle collection was not enabled."
            )
        if not universe.symbols or len(universe.symbols) > MAX_COLLECTOR_SYMBOLS:
            raise SchwabCandleCollectorError(
                "Schwab candle universe was empty or exceeded its bounded size."
            )

        run_id = _fingerprint(
            {
                "schemaVersion": COLLECTOR_SCHEMA_VERSION,
                "startedAt": started_at.isoformat(),
                "universeFingerprint": universe.fingerprint,
            }
        )
        stream_inserted = 0
        stream_duplicates = 0
        history_inserted = 0
        history_duplicates = 0
        received_by_symbol: dict[str, list[SchwabMinuteCandle]] = {
            symbol: [] for symbol in universe.symbols
        }
        history_results: list[dict[str, object]] = []
        findings: list[str] = list(universe.warnings)
        transport_events: list[dict[str, object]] = []
        stream_failure: str | None = None

        with self.store.lease(acquired_at=started_at):
            access: GuardedStreamerAccess = self.access_guard.authorize(
                options.expected_account_ending
            )
            bootstrap = parse_streamer_bootstrap(
                self.http.fetch_bootstrap(access.access_token),
                expected_account_ending=options.expected_account_ending,
            )
            stream = self.stream_factory.connect(bootstrap.socket_url)
            transport_events.append(
                {"kind": "CONNECTED", "observedAt": _aware_now(self.utc_clock()).isoformat()}
            )
            buffered: list[tuple[Mapping[str, object], datetime]] = []
            try:
                stream.send_json(build_streamer_login(access.access_token, bootstrap))
                self._receive_ack(
                    stream,
                    service="ADMIN",
                    command="LOGIN",
                    request_id="0",
                    buffered=buffered,
                )
                stream.send_json(
                    build_chart_equity_subscription(
                        universe.symbols,
                        customer_id=bootstrap.customer_id,
                        correlation_id=bootstrap.correlation_id,
                        request_id="1",
                    )
                )
                self._receive_ack(
                    stream,
                    service=SCHWAB_CHART_EQUITY_SERVICE,
                    command="SUBS",
                    request_id="1",
                    buffered=buffered,
                )
                transport_events.append(
                    {
                        "kind": "SUBSCRIPTION_ACKNOWLEDGED",
                        "observedAt": _aware_now(self.utc_clock()).isoformat(),
                    }
                )
                tracker = _ObservationTracker(universe.symbols)
                for payload, received_at in buffered:
                    mutation, candles = self._persist_payload(
                        payload,
                        received_at=received_at,
                        tracker=tracker,
                    )
                    stream_inserted += mutation.inserted_count
                    stream_duplicates += mutation.duplicate_count
                    _extend_received(received_by_symbol, candles)
                deadline = self.monotonic_clock() + options.duration_seconds
                while self.monotonic_clock() < deadline:
                    payload = stream.receive_json(
                        max(0.1, min(2.0, deadline - self.monotonic_clock()))
                    )
                    if payload is None:
                        continue
                    if "data" not in payload:
                        continue
                    received_at = _aware_now(self.utc_clock())
                    mutation, candles = self._persist_payload(
                        payload,
                        received_at=received_at,
                        tracker=tracker,
                    )
                    stream_inserted += mutation.inserted_count
                    stream_duplicates += mutation.duplicate_count
                    _extend_received(received_by_symbol, candles)
            except SchwabCandleObserverNetworkError as exc:
                stream_failure = type(exc).__name__
                findings.append("STREAM_DISCONNECTED_BEFORE_DURATION")
            finally:
                stream.close()
                transport_events.append(
                    {
                        "kind": "DISCONNECTED",
                        "observedAt": _aware_now(self.utc_clock()).isoformat(),
                    }
                )

            for symbol in universe.symbols:
                observed = received_by_symbol[symbol]
                if not observed:
                    history_results.append(
                        {
                            "symbol": symbol,
                            "status": "NO_STREAM_CANDLES",
                            "attempts": 0,
                            "historyRows": 0,
                            "matchedStreamMinutes": 0,
                        }
                    )
                    findings.append(f"NO_STREAM_CANDLES:{symbol}")
                    continue
                start_at = min(item.timestamp for item in observed) - timedelta(minutes=1)
                end_at = max(item.timestamp for item in observed) + timedelta(minutes=2)
                history_payload, attempts, error = self._fetch_history(
                    access.access_token,
                    symbol,
                    start_at=start_at,
                    end_at=end_at,
                    extended_hours=options.extended_hours,
                    attempts=options.history_attempts,
                )
                if error is not None:
                    history_results.append(
                        {
                            "symbol": symbol,
                            "status": "FAILED",
                            "attempts": attempts,
                            "historyRows": 0,
                            "matchedStreamMinutes": 0,
                            "error": error,
                        }
                    )
                    findings.append(f"HISTORY_RECONCILIATION_FAILED:{symbol}")
                    continue
                try:
                    history = parse_price_history_response(
                        history_payload,
                        expected_symbol=symbol,
                    )
                except SchwabCandleContractError as exc:
                    history_results.append(
                        {
                            "symbol": symbol,
                            "status": "INVALID_RESPONSE",
                            "attempts": attempts,
                            "historyRows": 0,
                            "matchedStreamMinutes": 0,
                            "error": type(exc).__name__,
                        }
                    )
                    findings.append(f"HISTORY_RESPONSE_INVALID:{symbol}")
                    continue
                bounded = tuple(
                    candle for candle in history if start_at <= candle.timestamp <= end_at
                )
                received_at = _aware_now(self.utc_clock())
                mutation = self.store.append_history(
                    bounded,
                    received_at=received_at,
                )
                history_inserted += mutation.inserted_count
                history_duplicates += mutation.duplicate_count
                observed_minutes = {item.timestamp for item in observed}
                history_minutes = {item.timestamp for item in bounded}
                matched = len(observed_minutes & history_minutes)
                status = "PASS" if observed_minutes <= history_minutes else "PARTIAL"
                if status != "PASS":
                    findings.append(f"HISTORY_MINUTES_MISSING:{symbol}")
                history_results.append(
                    {
                        "symbol": symbol,
                        "status": status,
                        "attempts": attempts,
                        "historyRows": len(bounded),
                        "matchedStreamMinutes": matched,
                    }
                )

            completed_at = _aware_now(self.utc_clock())
            health = self.store.health(
                universe.symbols,
                evaluated_at=completed_at,
                stale_after=timedelta(seconds=options.stale_after_seconds),
            )

        for item in health:
            if item.stale:
                findings.append(f"CANDLE_HEALTH_STALE:{item.symbol}")
            if item.gap_count:
                findings.append(f"CANDLE_HEALTH_GAPS:{item.symbol}:{item.gap_count}")
            if item.unreconciled_count:
                findings.append(
                    f"CANDLE_HEALTH_UNRECONCILED:{item.symbol}:{item.unreconciled_count}"
                )

        history_complete = all(item["status"] == "PASS" for item in history_results)
        stream_complete = stream_failure is None and all(received_by_symbol.values())
        quality_complete = all(
            not item.stale
            and item.gap_count == 0
            and item.unreconciled_count == 0
            for item in health
        )
        status = (
            "COMPLETE"
            if history_complete and stream_complete and quality_complete
            else "PARTIAL"
        )
        result = {
            "schemaVersion": COLLECTOR_SCHEMA_VERSION,
            "mode": COLLECTOR_MODE,
            "runId": run_id,
            "status": status,
            "startedAt": started_at.isoformat(),
            "completedAt": completed_at.isoformat(),
            "session": session,
            "universe": universe.to_evidence(),
            "stream": {
                "status": "PASS" if stream_complete else "PARTIAL",
                "insertedVersions": stream_inserted,
                "duplicateVersions": stream_duplicates,
                "receivedBySymbol": {
                    symbol: len(received_by_symbol[symbol])
                    for symbol in universe.symbols
                },
                "failure": stream_failure,
                "events": transport_events,
            },
            "history": {
                "status": "PASS" if history_complete else "PARTIAL",
                "insertedVersions": history_inserted,
                "duplicateVersions": history_duplicates,
                "symbols": history_results,
            },
            "health": [
                {
                    "symbol": item.symbol,
                    "status": item.status,
                    "latestMinute": (
                        item.latest_minute.isoformat() if item.latest_minute else None
                    ),
                    "latestReceivedAt": (
                        item.latest_received_at.isoformat()
                        if item.latest_received_at
                        else None
                    ),
                    "stale": item.stale,
                    "gapCount": item.gap_count,
                    "unreconciledCount": item.unreconciled_count,
                    "correctedCount": item.corrected_count,
                    "canonicalCount": item.canonical_count,
                }
                for item in health
            ],
            "findings": sorted(set(findings)),
            "accountInvariant": {
                "authorizedAccountCount": 1,
                "accountEnding": access.account_ending,
                "accountType": access.account_type,
                "positionsRequested": False,
                "ordersRequested": False,
            },
            "boundaries": {
                "legacyMinuteBarsWritten": False,
                "wpfInvoked": False,
                "engineHostInvoked": False,
                "shadowStateMutated": False,
                "scoreOrReadinessChanged": False,
                "orderTransmission": "UNAVAILABLE",
            },
        }
        result["resultFingerprint"] = _fingerprint(result)
        return result

    def _persist_payload(
        self,
        payload: Mapping[str, object],
        *,
        received_at: datetime,
        tracker: "_ObservationTracker",
    ) -> tuple[CandleStoreMutation, tuple[SchwabMinuteCandle, ...]]:
        candles = parse_chart_equity_messages(
            [payload],
            expected_symbols=tracker.symbols,
        )
        observations = tracker.observe(candles, received_at=received_at)
        return self.store.append_stream(observations), candles

    def _receive_ack(
        self,
        stream: StreamConnection,
        *,
        service: str,
        command: str,
        request_id: str,
        buffered: list[tuple[Mapping[str, object], datetime]],
    ) -> None:
        deadline = self.monotonic_clock() + ACK_TIMEOUT_SECONDS
        while self.monotonic_clock() < deadline:
            payload = stream.receive_json(
                max(0.1, min(2.0, deadline - self.monotonic_clock()))
            )
            if payload is None:
                continue
            if "data" in payload:
                buffered.append((payload, _aware_now(self.utc_clock())))
            if "response" in payload:
                require_streamer_acknowledgement(
                    payload,
                    service=service,
                    command=command,
                    request_id=request_id,
                )
                return
            if "data" in payload or "notify" in payload:
                continue
            raise SchwabCandleObserverResponseError(
                "Schwab Streamer returned an unexpected acknowledgement frame."
            )
        raise SchwabCandleObserverNetworkError(
            "Schwab Streamer acknowledgement timed out."
        )

    def _fetch_history(
        self,
        access_token: str,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        extended_hours: bool,
        attempts: int,
    ) -> tuple[object | None, int, str | None]:
        for attempt in range(1, attempts + 1):
            try:
                return (
                    self.http.fetch_price_history(
                        access_token,
                        symbol,
                        start_at=start_at,
                        end_at=end_at,
                        extended_hours=extended_hours,
                    ),
                    attempt,
                    None,
                )
            except SchwabCandleObserverNetworkError as exc:
                if attempt >= attempts:
                    return None, attempt, type(exc).__name__
                self.sleep(0.25 * attempt)
            except (SchwabCandleObserverResponseError, SchwabCandleObserverAuthorizationError) as exc:
                return None, attempt, type(exc).__name__
        raise AssertionError("bounded history loop did not return")


class _ObservationTracker:
    def __init__(self, symbols: Sequence[str]) -> None:
        self.symbols = normalize_symbols(symbols)
        self.arrival_index = 0
        self.latest_by_minute: dict[tuple[str, datetime], SchwabMinuteCandle] = {}
        self.greatest_by_symbol: dict[str, datetime] = {}
        self.previous_by_symbol: dict[str, SchwabMinuteCandle] = {}

    def observe(
        self,
        candles: Sequence[SchwabMinuteCandle],
        *,
        received_at: datetime,
    ) -> tuple[SchwabStreamCandleObservation, ...]:
        received = _aware_now(received_at)
        observations: list[SchwabStreamCandleObservation] = []
        for payload_index, candle in enumerate(candles):
            key = (candle.symbol, candle.timestamp)
            previous_version = self.latest_by_minute.get(key)
            changed = _changed_fields(previous_version, candle)
            update_kind = (
                "FIRST_OBSERVATION"
                if previous_version is None
                else "REVISION"
                if changed
                else "IDENTICAL_REPLAY"
            )
            greatest = self.greatest_by_symbol.get(candle.symbol)
            previous = self.previous_by_symbol.get(candle.symbol)
            observation = SchwabStreamCandleObservation(
                arrival_index=self.arrival_index,
                payload_index=payload_index,
                received_at=received,
                candle=candle,
                minute_identity=(
                    f"{candle.source}|{candle.symbol}|{candle.timestamp.isoformat()}"
                ),
                update_kind=update_kind,
                changed_fields=changed,
                out_of_order=greatest is not None and candle.timestamp < greatest,
                sequence_delta_from_previous_arrival=(
                    candle.sequence - previous.sequence
                    if candle.sequence is not None
                    and previous is not None
                    and previous.sequence is not None
                    else None
                ),
            )
            observations.append(observation)
            self.arrival_index += 1
            self.latest_by_minute[key] = candle
            self.previous_by_symbol[candle.symbol] = candle
            if greatest is None or candle.timestamp > greatest:
                self.greatest_by_symbol[candle.symbol] = candle.timestamp
        return tuple(observations)


def build_collection_plan(
    universe: CandleSymbolUniverse,
    options: CandleCollectorOptions,
    *,
    store_root: Path,
) -> dict[str, object]:
    return {
        "schemaVersion": COLLECTOR_SCHEMA_VERSION,
        "mode": f"{COLLECTOR_MODE}_PLAN",
        "execute": False,
        "networkCalled": False,
        "productionDataWritten": False,
        "universe": universe.to_evidence(),
        "durationSeconds": options.duration_seconds,
        "extendedHours": options.extended_hours,
        "historyAttempts": options.history_attempts,
        "staleAfterSeconds": options.stale_after_seconds,
        "storeRoot": str(store_root.resolve(strict=False)),
        "legacyMinuteBarsWritten": False,
        "wpfInvoked": False,
        "engineHostInvoked": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
    }


def write_result_once(result: Mapping[str, object], path: Path) -> Path:
    destination = path.expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = (_canonical_json(result) + "\n").encode("utf-8")
    temporary = destination.with_name(f".{destination.name}.{time.time_ns()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            if destination.read_bytes() == content:
                return destination
            raise SchwabCandleCollectorError(
                "Collector result already exists with conflicting content."
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _changed_fields(
    previous: SchwabMinuteCandle | None,
    current: SchwabMinuteCandle,
) -> tuple[str, ...]:
    if previous is None:
        return ()
    return tuple(
        field
        for field in ("open", "high", "low", "close", "volume", "sequence")
        if getattr(previous, field) != getattr(current, field)
    )


def _extend_received(
    target: dict[str, list[SchwabMinuteCandle]],
    candles: Sequence[SchwabMinuteCandle],
) -> None:
    for candle in candles:
        target[candle.symbol].append(candle)


def _load_json_with_hash(path: Path, label: str) -> tuple[object, str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabCandleCollectorError(f"{label} was unreadable.") from exc
    return payload, hashlib.sha256(raw).hexdigest().upper()


def _symbol(value: object) -> str:
    try:
        return normalize_symbols((str(value),))[0]
    except ValueError as exc:
        raise SchwabCandleCollectorError("Candle-universe symbol was invalid.") from exc


def _aware_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabCandleCollectorError(
            "Collector clock must return an offset-aware timestamp."
        )
    return value


def _parse_optional_datetime(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _canonical_json(payload: object) -> str:
    try:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise SchwabCandleCollectorError(
            "Collector evidence was not canonical JSON."
        ) from exc


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest().upper()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect bounded, read-only Schwab one-minute candle evidence."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-account-ending", required=True)
    parser.add_argument("--candidate-report", type=Path, default=None)
    parser.add_argument("--decision-cycles", type=Path, default=SHADOW_DECISION_CYCLES_PATH)
    parser.add_argument("--shadow-state", type=Path, default=SHADOW_STATE_PATH)
    parser.add_argument("--selected-symbol", default=None)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_COLLECTION_SECONDS)
    parser.add_argument("--regular-hours-only", action="store_true")
    parser.add_argument("--history-attempts", type=int, default=DEFAULT_HISTORY_ATTEMPTS)
    parser.add_argument("--stale-after-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    parser.add_argument("--store-root", type=Path, default=SCHWAB_CANDLE_STORE_ROOT)
    parser.add_argument("--result-json", type=Path, default=None)
    args = parser.parse_args(argv)

    market_date = datetime.now(timezone.utc).astimezone(EASTERN_TZ).date()
    candidate_report = args.candidate_report or (
        DATA_DIR
        / "reports"
        / f"trade-plan-briefing-{market_date.isoformat()}-opening.json"
    )
    universe = resolve_candle_universe(
        CandleUniverseSources(
            candidate_report=candidate_report,
            decision_cycles=args.decision_cycles,
            shadow_state=args.shadow_state,
            explicit_selected_symbol=args.selected_symbol,
        ),
        expected_market_date=market_date,
    )
    options = CandleCollectorOptions(
        expected_account_ending=args.expected_account_ending,
        duration_seconds=args.duration_seconds,
        extended_hours=not args.regular_hours_only,
        history_attempts=args.history_attempts,
        stale_after_seconds=args.stale_after_seconds,
    )
    if not args.execute:
        print(
            json.dumps(
                build_collection_plan(universe, options, store_root=args.store_root),
                indent=2,
            )
        )
        return 0

    store = SchwabCandleStore(args.store_root)
    result = SchwabIncrementalCandleCollector(store=store).collect(universe, options)
    result_path = args.result_json
    if result_path is None:
        timestamp = str(result["startedAt"]).replace(":", "").replace("+", "-")
        result_path = args.store_root / "runs" / f"collector-{timestamp}.json"
    write_result_once(result, result_path)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
