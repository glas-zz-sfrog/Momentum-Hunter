from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.schwab_candle_backfill import (
    CandleBackfillOptions,
    SchwabCandleBackfillError,
    SchwabHistoricalCandleBackfiller,
    build_backfill_plan,
    explicit_universe,
    main,
)
from momentum_hunter.schwab_candle_contract import (
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabCandleContractError,
    SchwabDailyCandle,
    build_daily_price_history_parameters,
    parse_daily_price_history_response,
)
from momentum_hunter.schwab_candle_observer import (
    GuardedStreamerAccess,
    SchwabCandleObserverHttpUnauthorizedError,
    SchwabCandleObserverNetworkError,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore, SchwabCandleStoreError
from momentum_hunter.schwab_daily_candle_store import (
    SchwabDailyCandleStore,
    SchwabDailyCandleStoreError,
)


UTC = timezone.utc
NOW = datetime(2026, 8, 6, 15, 0, tzinfo=UTC)


class FakeAccessGuard:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.refresh_calls: list[str] = []

    def authorize(self, expected_account_ending: str) -> GuardedStreamerAccess:
        self.calls.append(expected_account_ending)
        return GuardedStreamerAccess(
            access_token="synthetic-token",
            account_ending="2573",
            account_type="INDIVIDUAL_CASH",
            balances_present=True,
        )

    def refresh_after_rejection(
        self,
        expected_account_ending: str,
    ) -> GuardedStreamerAccess:
        self.refresh_calls.append(expected_account_ending)
        return GuardedStreamerAccess(
            access_token="synthetic-refreshed-token",
            account_ending="2573",
            account_type="INDIVIDUAL_CASH",
            balances_present=True,
        )


class FakeHttpTransport:
    def __init__(
        self,
        *,
        minute_rows: int = 35,
        daily_rows: int = 25,
        transient_failures: int = 0,
        unauthorized_failures: int = 0,
    ) -> None:
        self.minute_rows = minute_rows
        self.daily_rows = daily_rows
        self.transient_failures = transient_failures
        self.unauthorized_failures = unauthorized_failures
        self.access_tokens: list[str] = []
        self.minute_calls: list[tuple[str, datetime, datetime, bool]] = []
        self.daily_calls: list[tuple[str, datetime, datetime]] = []

    def fetch_price_history(
        self,
        access_token: str,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        extended_hours: bool,
    ) -> object:
        self.access_tokens.append(access_token)
        self._maybe_reject_authorization()
        self._maybe_fail()
        self.minute_calls.append((symbol, start_at, end_at, extended_hours))
        start = NOW - timedelta(minutes=self.minute_rows)
        rows = [price_row(start + timedelta(minutes=index), 100.0 + index) for index in range(self.minute_rows)]
        return history_payload(symbol, rows)

    def fetch_daily_price_history(
        self,
        access_token: str,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> object:
        self.access_tokens.append(access_token)
        self._maybe_reject_authorization()
        self._maybe_fail()
        self.daily_calls.append((symbol, start_at, end_at))
        start = datetime(2026, 7, 1, 4, 0, tzinfo=UTC)
        rows = [price_row(start + timedelta(days=index), 200.0 + index) for index in range(self.daily_rows)]
        return history_payload(symbol, rows)

    def _maybe_fail(self) -> None:
        if self.transient_failures:
            self.transient_failures -= 1
            raise SchwabCandleObserverNetworkError("synthetic transient")

    def _maybe_reject_authorization(self) -> None:
        if self.unauthorized_failures:
            self.unauthorized_failures -= 1
            raise SchwabCandleObserverHttpUnauthorizedError("synthetic 401")


class SchwabCandleContractBackfillTests(unittest.TestCase):
    def test_daily_parameters_use_official_daily_price_history_shape(self) -> None:
        start = NOW - timedelta(days=365)
        parameters = build_daily_price_history_parameters(
            "nvda",
            start_at=start,
            end_at=NOW,
        )
        self.assertEqual("NVDA", parameters["symbol"])
        self.assertEqual("year", parameters["periodType"])
        self.assertEqual("daily", parameters["frequencyType"])
        self.assertEqual(1, parameters["frequency"])
        self.assertFalse(parameters["needExtendedHoursData"])
        self.assertEqual(int(start.timestamp() * 1000), parameters["startDate"])
        self.assertEqual(int(NOW.timestamp() * 1000), parameters["endDate"])

    def test_daily_response_preserves_provider_timestamp_and_source(self) -> None:
        payload = history_payload(
            "NVDA",
            [price_row(datetime(2026, 8, 5, 4, 0, tzinfo=UTC), 100.0)],
        )
        candle = parse_daily_price_history_response(payload, expected_symbol="NVDA")[0]
        self.assertEqual("2026-08-05", candle.session_date)
        self.assertEqual("1d", candle.to_evidence()["timeframe"])
        self.assertEqual(SCHWAB_PRICE_HISTORY_SOURCE, candle.source)

    def test_daily_response_rejects_duplicate_session_dates(self) -> None:
        first = datetime(2026, 8, 5, 4, 0, tzinfo=UTC)
        payload = history_payload(
            "NVDA",
            [price_row(first, 100.0), price_row(first + timedelta(hours=1), 101.0)],
        )
        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "unique chronological sessions",
        ):
            parse_daily_price_history_response(payload, expected_symbol="NVDA")


class SchwabDailyCandleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = SchwabDailyCandleStore(self.root / "daily")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_replay_is_idempotent_and_correction_is_preserved(self) -> None:
        first = daily_candle(close=101.0)
        corrected = daily_candle(close=102.0, high=103.0)
        inserted = self.store.append_history((first,), received_at=NOW)
        duplicate = self.store.append_history((first,), received_at=NOW + timedelta(minutes=1))
        changed = self.store.append_history((corrected,), received_at=NOW + timedelta(minutes=2))
        bar = self.store.load_symbol("NVDA")["bars"][0]

        self.assertEqual(1, inserted.inserted_count)
        self.assertEqual(1, duplicate.duplicate_count)
        self.assertEqual(1, changed.inserted_count)
        self.assertEqual("CORRECTED", bar["state"])
        self.assertEqual(2, len(bar["historyVersions"]))
        self.assertEqual(102.0, bar["canonicalCandle"]["close"])

    def test_tampered_canonical_value_fails_closed(self) -> None:
        self.store.append_history((daily_candle(),), received_at=NOW)
        path = self.store.symbol_path("NVDA")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["bars"][0]["canonicalCandle"]["close"] = 999.0
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(SchwabDailyCandleStoreError, "derived state"):
            self.store.load_symbol("NVDA")

    def test_daily_reversion_to_prior_values_becomes_canonical(self) -> None:
        original = daily_candle(close=101.0)
        self.store.append_history((original,), received_at=NOW)
        self.store.append_history(
            (daily_candle(close=102.0, high=103.0),),
            received_at=NOW + timedelta(minutes=1),
        )
        reverted = self.store.append_history(
            (original,),
            received_at=NOW + timedelta(minutes=2),
        )
        bar = self.store.load_symbol("NVDA")["bars"][0]

        self.assertEqual(1, reverted.inserted_count)
        self.assertEqual(3, len(bar["historyVersions"]))
        self.assertEqual(101.0, bar["canonicalCandle"]["close"])
        self.assertIn("reassertedAfterVersionId", bar["historyVersions"][-1])

    def test_daily_store_refuses_legacy_cache_as_its_root(self) -> None:
        legacy = self.root / "daily-ohlc-bars.json"
        with patch(
            "momentum_hunter.schwab_daily_candle_store.DAILY_OHLC_SOURCE_PATH",
            legacy,
        ):
            with self.assertRaisesRegex(
                SchwabDailyCandleStoreError,
                "legacy daily OHLC",
            ):
                SchwabDailyCandleStore(self.root)


class SchwabHistoricalCandleBackfillerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.minute_store = SchwabCandleStore(self.root / "minute")
        self.daily_store = SchwabDailyCandleStore(self.root / "daily")
        self.guard = FakeAccessGuard()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_backfill_populates_depth_for_symbols_and_benchmarks(self) -> None:
        transport = FakeHttpTransport()
        result = self._backfiller(transport).backfill(
            explicit_universe(("NVDA",)),
            CandleBackfillOptions(expected_account_ending="2573"),
        )

        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual(["2573"], self.guard.calls)
        self.assertEqual({"NVDA", "SPY", "IWM"}, {call[0] for call in transport.minute_calls})
        self.assertEqual({"NVDA", "SPY", "IWM"}, {call[0] for call in transport.daily_calls})
        self.assertEqual(35, sum(len(self.minute_store.canonical_bars("NVDA", date)) for date in ("2026-08-06",)))
        self.assertEqual(25, len(self.daily_store.canonical_bars("NVDA")))
        self.assertFalse(result["boundaries"]["streamConnected"])
        self.assertFalse(result["boundaries"]["legacyMinuteBarsWritten"])
        self.assertEqual("UNAVAILABLE", result["boundaries"]["orderTransmission"])

    def test_second_backfill_is_idempotent(self) -> None:
        transport = FakeHttpTransport()
        backfiller = self._backfiller(transport)
        universe = explicit_universe(("NVDA",))
        options = CandleBackfillOptions(expected_account_ending="2573")
        first = backfiller.backfill(universe, options)
        second = backfiller.backfill(universe, options)

        self.assertGreater(first["minuteStore"]["insertedVersions"], 0)
        self.assertEqual(0, second["minuteStore"]["insertedVersions"])
        self.assertEqual(0, second["dailyStore"]["insertedVersions"])
        self.assertGreater(second["minuteStore"]["duplicateVersions"], 0)
        self.assertGreater(second["dailyStore"]["duplicateVersions"], 0)

    def test_insufficient_depth_remains_partial_and_explicit(self) -> None:
        result = self._backfiller(
            FakeHttpTransport(minute_rows=2, daily_rows=1)
        ).backfill(
            explicit_universe(("NVDA",)),
            CandleBackfillOptions(expected_account_ending="2573"),
        )
        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(
            "INSUFFICIENT_DEPTH",
            result["symbols"][0]["minute"]["status"],
        )
        self.assertIn("MINUTE_BACKFILL_INSUFFICIENT_DEPTH:NVDA", result["findings"])

    def test_network_retry_is_bounded(self) -> None:
        transport = FakeHttpTransport(transient_failures=1)
        result = self._backfiller(transport).backfill(
            explicit_universe(("NVDA",)),
            CandleBackfillOptions(
                expected_account_ending="2573",
                history_attempts=2,
            ),
        )
        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual(2, result["symbols"][0]["minute"]["attempts"])

    def test_http_401_refreshes_once_and_retries_original_candle_read(self) -> None:
        transport = FakeHttpTransport(unauthorized_failures=1)

        result = self._backfiller(transport).backfill(
            explicit_universe(("NVDA",)),
            CandleBackfillOptions(expected_account_ending="2573"),
        )

        self.assertEqual("COMPLETE", result["status"])
        self.assertEqual(["2573"], self.guard.refresh_calls)
        self.assertEqual("synthetic-token", transport.access_tokens[0])
        self.assertTrue(
            all(
                token == "synthetic-refreshed-token"
                for token in transport.access_tokens[1:]
            )
        )

    def test_second_http_401_is_partial_failure_not_empty_valid_evidence(self) -> None:
        transport = FakeHttpTransport(unauthorized_failures=2)

        result = self._backfiller(transport).backfill(
            explicit_universe(("NVDA",)),
            CandleBackfillOptions(expected_account_ending="2573"),
        )

        self.assertEqual("PARTIAL", result["status"])
        self.assertEqual(["2573"], self.guard.refresh_calls)
        self.assertEqual("FAILED", result["symbols"][0]["minute"]["status"])
        self.assertEqual(
            "SchwabCandleObserverHttpUnauthorizedError",
            result["symbols"][0]["minute"]["error"],
        )

    def test_writer_conflict_fails_before_account_or_network_access(self) -> None:
        transport = FakeHttpTransport()
        with self.minute_store.lease(acquired_at=NOW):
            with self.assertRaises(SchwabCandleStoreError):
                self._backfiller(transport).backfill(
                    explicit_universe(("NVDA",)),
                    CandleBackfillOptions(expected_account_ending="2573"),
                )
        self.assertEqual([], self.guard.calls)
        self.assertEqual([], transport.minute_calls)
        self.assertEqual([], transport.daily_calls)

    def test_legacy_sources_are_not_mutated(self) -> None:
        legacy_minute = self.root / "opportunity-minute-bars.json"
        legacy_daily = self.root / "daily-ohlc-bars.json"
        legacy_minute.write_bytes(b"minute sentinel")
        legacy_daily.write_bytes(b"daily sentinel")

        self._backfiller(FakeHttpTransport()).backfill(
            explicit_universe(("NVDA",)),
            CandleBackfillOptions(expected_account_ending="2573"),
        )

        self.assertEqual(b"minute sentinel", legacy_minute.read_bytes())
        self.assertEqual(b"daily sentinel", legacy_daily.read_bytes())

    def test_plan_is_network_free_and_does_not_write(self) -> None:
        universe = explicit_universe(("NVDA",))
        options = CandleBackfillOptions(expected_account_ending="2573")
        plan = build_backfill_plan(
            universe,
            options,
            minute_store_root=self.root / "minute-plan",
            daily_store_root=self.root / "daily-plan",
        )
        self.assertFalse(plan["networkCalled"])
        self.assertFalse(plan["productionDataWritten"])
        self.assertFalse((self.root / "minute-plan").exists())
        self.assertFalse((self.root / "daily-plan").exists())

    def test_options_reject_minute_window_beyond_provider_contract(self) -> None:
        with self.assertRaisesRegex(SchwabCandleBackfillError, "one-to-ten-day"):
            CandleBackfillOptions(
                expected_account_ending="2573",
                minute_lookback_days=11,
            )

    def test_cli_defaults_to_plan_only(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                [
                    "--expected-account-ending",
                    "2573",
                    "--symbol",
                    "NVDA",
                    "--minute-store-root",
                    str(self.root / "minute-cli"),
                    "--daily-store-root",
                    str(self.root / "daily-cli"),
                ]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertFalse(payload["execute"])
        self.assertFalse(payload["networkCalled"])
        self.assertFalse((self.root / "minute-cli").exists())

    def _backfiller(self, transport: FakeHttpTransport) -> SchwabHistoricalCandleBackfiller:
        return SchwabHistoricalCandleBackfiller(
            minute_store=self.minute_store,
            daily_store=self.daily_store,
            access_guard=self.guard,
            http_transport=transport,
            utc_clock=lambda: NOW,
            sleep=lambda _: None,
        )


def history_payload(symbol: str, rows: list[dict[str, object]]) -> dict[str, object]:
    return {"symbol": symbol, "empty": not rows, "candles": rows}


def price_row(timestamp: datetime, base: float) -> dict[str, object]:
    return {
        "datetime": int(timestamp.timestamp() * 1000),
        "open": base,
        "high": base + 2.0,
        "low": base - 1.0,
        "close": base + 1.0,
        "volume": 1000.0,
    }


def daily_candle(*, close: float = 101.0, high: float = 102.0) -> SchwabDailyCandle:
    timestamp = datetime(2026, 8, 5, 4, 0, tzinfo=UTC)
    return SchwabDailyCandle(
        symbol="NVDA",
        timestamp=timestamp,
        session_date="2026-08-05",
        open=100.0,
        high=high,
        low=99.0,
        close=close,
        volume=1000.0,
        source=SCHWAB_PRICE_HISTORY_SOURCE,
    )


if __name__ == "__main__":
    unittest.main()
