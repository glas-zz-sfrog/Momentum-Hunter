"""Bounded historical Schwab candle backfill for workstation chart context."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.config import DATA_DIR
from momentum_hunter.schwab_candle_collector import (
    CandleSymbolUniverse,
    CandleUniverseSources,
    MAX_COLLECTOR_SYMBOLS,
    SHADOW_DECISION_CYCLES_PATH,
    SHADOW_STATE_PATH,
    resolve_candle_universe,
    write_result_once,
)
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SchwabCandleContractError,
    normalize_symbols,
    parse_daily_price_history_response,
    parse_price_history_response,
)
from momentum_hunter.schwab_candle_observer import (
    GuardedStreamerAccess,
    SchwabCandleAccessGuard,
    SchwabCandleHttpTransport,
    SchwabCandleObserverAuthorizationError,
    SchwabCandleObserverHttpUnauthorizedError,
    SchwabCandleObserverNetworkError,
    SchwabCandleObserverResponseError,
)
from momentum_hunter.schwab_candle_store import (
    SCHWAB_CANDLE_STORE_ROOT,
    SchwabCandleStore,
)
from momentum_hunter.schwab_daily_candle_store import (
    SCHWAB_DAILY_CANDLE_STORE_ROOT,
    SchwabDailyCandleStore,
)


BACKFILL_SCHEMA_VERSION = 1
BACKFILL_MODE = "SCHWAB_HISTORICAL_CANDLE_BACKFILL"
DEFAULT_MINUTE_LOOKBACK_DAYS = 10
DEFAULT_DAILY_LOOKBACK_DAYS = 365
DEFAULT_HISTORY_ATTEMPTS = 2
MIN_REQUIRED_MINUTE_BARS = 30
MIN_REQUIRED_DAILY_BARS = 20


class SchwabCandleBackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandleBackfillOptions:
    expected_account_ending: str
    minute_lookback_days: int = DEFAULT_MINUTE_LOOKBACK_DAYS
    daily_lookback_days: int = DEFAULT_DAILY_LOOKBACK_DAYS
    extended_hours: bool = True
    history_attempts: int = DEFAULT_HISTORY_ATTEMPTS

    def __post_init__(self) -> None:
        if len(self.expected_account_ending) != 4 or not self.expected_account_ending.isdigit():
            raise SchwabCandleBackfillError(
                "Expected account ending must contain exactly four digits."
            )
        if not 1 <= self.minute_lookback_days <= 10:
            raise SchwabCandleBackfillError(
                "Minute backfill must remain within Schwab's documented one-to-ten-day window."
            )
        if not 30 <= self.daily_lookback_days <= 730:
            raise SchwabCandleBackfillError(
                "Daily backfill must remain between 30 and 730 calendar days."
            )
        if not 1 <= self.history_attempts <= 3:
            raise SchwabCandleBackfillError(
                "History attempts must remain between one and three."
            )


class _AuthorizedHistoryReader:
    """Use one guarded token refresh across an entire bounded backfill run."""

    def __init__(
        self,
        *,
        access_guard: object,
        access: GuardedStreamerAccess,
        expected_account_ending: str,
    ) -> None:
        self.access_guard = access_guard
        self.access = access
        self.expected_account_ending = expected_account_ending
        self.recovery_used = False

    def fetch(self, operation: Callable[[str], object]) -> object:
        try:
            return operation(self.access.access_token)
        except SchwabCandleObserverHttpUnauthorizedError:
            if self.recovery_used:
                raise
            self.recovery_used = True
            refresh = getattr(self.access_guard, "refresh_after_rejection", None)
            if not callable(refresh):
                raise
            self.access = refresh(self.expected_account_ending)
            return operation(self.access.access_token)


class SchwabHistoricalCandleBackfiller:
    def __init__(
        self,
        *,
        minute_store: SchwabCandleStore,
        daily_store: SchwabDailyCandleStore,
        access_guard: object | None = None,
        http_transport: object | None = None,
        utc_clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.minute_store = minute_store
        self.daily_store = daily_store
        self.access_guard = access_guard or SchwabCandleAccessGuard()
        self.http = http_transport or SchwabCandleHttpTransport()
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep or time.sleep

    def backfill(
        self,
        universe: CandleSymbolUniverse,
        options: CandleBackfillOptions,
    ) -> dict[str, object]:
        started_at = _aware(self.utc_clock())
        if not universe.symbols or len(universe.symbols) > MAX_COLLECTOR_SYMBOLS:
            raise SchwabCandleBackfillError(
                "Schwab candle backfill universe was empty or exceeded ten symbols."
            )
        minute_start = started_at - timedelta(days=options.minute_lookback_days)
        daily_start = started_at - timedelta(days=options.daily_lookback_days)
        symbols: list[dict[str, object]] = []
        minute_inserted = 0
        minute_duplicates = 0
        daily_inserted = 0
        daily_duplicates = 0
        findings: list[str] = []

        with self.minute_store.lease(acquired_at=started_at):
            with self.daily_store.lease(acquired_at=started_at):
                access: GuardedStreamerAccess = self.access_guard.authorize(
                    options.expected_account_ending
                )
                reader = _AuthorizedHistoryReader(
                    access_guard=self.access_guard,
                    access=access,
                    expected_account_ending=options.expected_account_ending,
                )
                for symbol in universe.symbols:
                    minute_result = self._backfill_minute_symbol(
                        reader,
                        symbol,
                        start_at=minute_start,
                        end_at=started_at,
                        options=options,
                    )
                    daily_result = self._backfill_daily_symbol(
                        reader,
                        symbol,
                        start_at=daily_start,
                        end_at=started_at,
                        options=options,
                    )
                    minute_inserted += int(minute_result["insertedVersions"])
                    minute_duplicates += int(minute_result["duplicateVersions"])
                    daily_inserted += int(daily_result["insertedVersions"])
                    daily_duplicates += int(daily_result["duplicateVersions"])
                    if minute_result["status"] != "PASS":
                        findings.append(
                            f"MINUTE_BACKFILL_{minute_result['status']}:{symbol}"
                        )
                    if daily_result["status"] != "PASS":
                        findings.append(
                            f"DAILY_BACKFILL_{daily_result['status']}:{symbol}"
                        )
                    symbols.append(
                        {
                            "symbol": symbol,
                            "minute": minute_result,
                            "daily": daily_result,
                        }
                    )

        completed_at = _aware(self.utc_clock())
        complete = all(
            item[timeframe]["status"] == "PASS"
            for item in symbols
            for timeframe in ("minute", "daily")
        )
        result: dict[str, object] = {
            "schemaVersion": BACKFILL_SCHEMA_VERSION,
            "mode": BACKFILL_MODE,
            "status": "COMPLETE" if complete else "PARTIAL",
            "startedAt": started_at.isoformat(),
            "completedAt": completed_at.isoformat(),
            "minuteWindow": {
                "startAt": minute_start.isoformat(),
                "endAt": started_at.isoformat(),
                "lookbackDays": options.minute_lookback_days,
                "extendedHours": options.extended_hours,
                "minimumRequiredBarsPerSymbol": MIN_REQUIRED_MINUTE_BARS,
            },
            "dailyWindow": {
                "startAt": daily_start.isoformat(),
                "endAt": started_at.isoformat(),
                "lookbackDays": options.daily_lookback_days,
                "minimumRequiredBarsPerSymbol": MIN_REQUIRED_DAILY_BARS,
            },
            "universe": universe.to_evidence(),
            "symbols": symbols,
            "minuteStore": {
                "root": str(self.minute_store.root),
                "insertedVersions": minute_inserted,
                "duplicateVersions": minute_duplicates,
                "canonicalSource": "schwab_marketdata_v1_pricehistory:v1",
            },
            "dailyStore": {
                "root": str(self.daily_store.root),
                "insertedVersions": daily_inserted,
                "duplicateVersions": daily_duplicates,
                "canonicalSource": "schwab_marketdata_v1_pricehistory:v1",
            },
            "findings": sorted(set(findings)),
            "accountInvariant": {
                "authorizedAccountCount": 1,
                "accountEnding": reader.access.account_ending,
                "accountType": reader.access.account_type,
                "positionsRequested": False,
                "ordersRequested": False,
            },
            "boundaries": {
                "streamConnected": False,
                "legacyMinuteBarsWritten": False,
                "legacyDailyBarsWritten": False,
                "wpfInvoked": False,
                "engineHostInvoked": False,
                "shadowStateMutated": False,
                "scoreOrReadinessChanged": False,
                "orderTransmission": "UNAVAILABLE",
            },
        }
        result["resultFingerprint"] = _fingerprint(result)
        return result

    def _backfill_minute_symbol(
        self,
        reader: _AuthorizedHistoryReader,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        options: CandleBackfillOptions,
    ) -> dict[str, object]:
        payload, attempts, error = self._fetch(
            lambda: reader.fetch(
                lambda access_token: self.http.fetch_price_history(
                    access_token,
                    symbol,
                    start_at=start_at,
                    end_at=end_at,
                    extended_hours=options.extended_hours,
                )
            ),
            attempts=options.history_attempts,
        )
        if error is not None:
            return _failed_result(attempts, error)
        try:
            parsed = parse_price_history_response(payload, expected_symbol=symbol)
        except SchwabCandleContractError as exc:
            return _failed_result(attempts, type(exc).__name__, status="INVALID_RESPONSE")
        bounded = tuple(item for item in parsed if start_at <= item.timestamp <= end_at)
        received_at = _aware(self.utc_clock())
        mutation = self.minute_store.append_history(bounded, received_at=received_at)
        status = "PASS" if len(bounded) >= MIN_REQUIRED_MINUTE_BARS else "INSUFFICIENT_DEPTH"
        return {
            "status": status,
            "attempts": attempts,
            "rows": len(bounded),
            "firstTimestamp": bounded[0].timestamp.isoformat() if bounded else None,
            "lastTimestamp": bounded[-1].timestamp.isoformat() if bounded else None,
            "insertedVersions": mutation.inserted_count,
            "duplicateVersions": mutation.duplicate_count,
        }

    def _backfill_daily_symbol(
        self,
        reader: _AuthorizedHistoryReader,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        options: CandleBackfillOptions,
    ) -> dict[str, object]:
        payload, attempts, error = self._fetch(
            lambda: reader.fetch(
                lambda access_token: self.http.fetch_daily_price_history(
                    access_token,
                    symbol,
                    start_at=start_at,
                    end_at=end_at,
                )
            ),
            attempts=options.history_attempts,
        )
        if error is not None:
            return _failed_result(attempts, error)
        try:
            parsed = parse_daily_price_history_response(
                payload,
                expected_symbol=symbol,
            )
        except SchwabCandleContractError as exc:
            return _failed_result(attempts, type(exc).__name__, status="INVALID_RESPONSE")
        earliest_date = start_at.astimezone(EASTERN_TZ).date().isoformat()
        latest_date = end_at.astimezone(EASTERN_TZ).date().isoformat()
        bounded = tuple(
            item for item in parsed if earliest_date <= item.session_date <= latest_date
        )
        received_at = _aware(self.utc_clock())
        mutation = self.daily_store.append_history(bounded, received_at=received_at)
        status = "PASS" if len(bounded) >= MIN_REQUIRED_DAILY_BARS else "INSUFFICIENT_DEPTH"
        return {
            "status": status,
            "attempts": attempts,
            "rows": len(bounded),
            "firstSessionDate": bounded[0].session_date if bounded else None,
            "lastSessionDate": bounded[-1].session_date if bounded else None,
            "insertedVersions": mutation.inserted_count,
            "duplicateVersions": mutation.duplicate_count,
        }

    def _fetch(
        self,
        operation: Callable[[], object],
        *,
        attempts: int,
    ) -> tuple[object | None, int, str | None]:
        for attempt in range(1, attempts + 1):
            try:
                return operation(), attempt, None
            except SchwabCandleObserverNetworkError as exc:
                if attempt >= attempts:
                    return None, attempt, type(exc).__name__
                self.sleep(0.25 * attempt)
            except (
                SchwabCandleObserverResponseError,
                SchwabCandleObserverAuthorizationError,
            ) as exc:
                return None, attempt, type(exc).__name__
        raise AssertionError("bounded history retry loop did not return")


def build_backfill_plan(
    universe: CandleSymbolUniverse,
    options: CandleBackfillOptions,
    *,
    minute_store_root: Path,
    daily_store_root: Path,
) -> dict[str, object]:
    return {
        "schemaVersion": BACKFILL_SCHEMA_VERSION,
        "mode": f"{BACKFILL_MODE}_PLAN",
        "execute": False,
        "networkCalled": False,
        "productionDataWritten": False,
        "universe": universe.to_evidence(),
        "minuteLookbackDays": options.minute_lookback_days,
        "dailyLookbackDays": options.daily_lookback_days,
        "extendedHours": options.extended_hours,
        "historyAttempts": options.history_attempts,
        "minuteStoreRoot": str(minute_store_root.resolve(strict=False)),
        "dailyStoreRoot": str(daily_store_root.resolve(strict=False)),
        "legacyMinuteBarsWritten": False,
        "legacyDailyBarsWritten": False,
        "streamConnected": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
    }


def explicit_universe(symbols: Sequence[str]) -> CandleSymbolUniverse:
    normalized = list(normalize_symbols(symbols))
    for benchmark in ("SPY", "IWM"):
        if benchmark not in normalized:
            normalized.append(benchmark)
    if len(normalized) > MAX_COLLECTOR_SYMBOLS:
        raise SchwabCandleBackfillError(
            "Explicit candle backfill universe exceeded ten symbols."
        )
    sources = {
        symbol: (("BENCHMARK",) if symbol in {"SPY", "IWM"} else ("EXPLICIT_SYMBOL",))
        for symbol in normalized
    }
    return CandleSymbolUniverse(
        symbols=tuple(normalized),
        sources_by_symbol=sources,
        excluded_symbols=(),
        warnings=(),
        input_fingerprints={},
    )


def _failed_result(
    attempts: int,
    error: str,
    *,
    status: str = "FAILED",
) -> dict[str, object]:
    return {
        "status": status,
        "attempts": attempts,
        "rows": 0,
        "insertedVersions": 0,
        "duplicateVersions": 0,
        "error": error,
    }


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabCandleBackfillError(
            "Schwab candle backfill clock must include a UTC offset."
        )
    return value


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest().upper()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill bounded Schwab one-minute and daily candle history."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-account-ending", required=True)
    parser.add_argument("--symbol", action="append", default=[])
    parser.add_argument("--candidate-report", type=Path, default=None)
    parser.add_argument("--decision-cycles", type=Path, default=SHADOW_DECISION_CYCLES_PATH)
    parser.add_argument("--shadow-state", type=Path, default=SHADOW_STATE_PATH)
    parser.add_argument("--selected-symbol", default=None)
    parser.add_argument("--minute-lookback-days", type=int, default=DEFAULT_MINUTE_LOOKBACK_DAYS)
    parser.add_argument("--daily-lookback-days", type=int, default=DEFAULT_DAILY_LOOKBACK_DAYS)
    parser.add_argument("--regular-hours-only", action="store_true")
    parser.add_argument("--history-attempts", type=int, default=DEFAULT_HISTORY_ATTEMPTS)
    parser.add_argument("--minute-store-root", type=Path, default=SCHWAB_CANDLE_STORE_ROOT)
    parser.add_argument("--daily-store-root", type=Path, default=SCHWAB_DAILY_CANDLE_STORE_ROOT)
    parser.add_argument("--result-json", type=Path, default=None)
    args = parser.parse_args(argv)

    market_date = datetime.now(timezone.utc).astimezone(EASTERN_TZ).date()
    if args.symbol:
        universe = explicit_universe(args.symbol)
    else:
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
    options = CandleBackfillOptions(
        expected_account_ending=args.expected_account_ending,
        minute_lookback_days=args.minute_lookback_days,
        daily_lookback_days=args.daily_lookback_days,
        extended_hours=not args.regular_hours_only,
        history_attempts=args.history_attempts,
    )
    if not args.execute:
        print(
            json.dumps(
                build_backfill_plan(
                    universe,
                    options,
                    minute_store_root=args.minute_store_root,
                    daily_store_root=args.daily_store_root,
                ),
                indent=2,
            )
        )
        return 0

    backfiller = SchwabHistoricalCandleBackfiller(
        minute_store=SchwabCandleStore(args.minute_store_root),
        daily_store=SchwabDailyCandleStore(args.daily_store_root),
    )
    result = backfiller.backfill(universe, options)
    result_path = args.result_json
    if result_path is None:
        timestamp = str(result["startedAt"]).replace(":", "").replace("+", "-")
        result_path = args.minute_store_root / "runs" / f"backfill-{timestamp}.json"
    write_result_once(result, result_path)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
