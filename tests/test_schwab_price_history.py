from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from momentum_hunter.schwab_price_history import (
    MAX_PRICE_HISTORY_BARS,
    MAX_PRICE_HISTORY_RESPONSE_BYTES,
    SCHWAB_PRICE_HISTORY_URL,
    SchwabPriceBar,
    SchwabPriceHistoryAuthorizationError,
    SchwabPriceHistoryNetworkError,
    SchwabPriceHistoryResponseError,
    SchwabPriceHistoryResult,
    SchwabPriceHistorySource,
    SchwabPriceHistoryStagingError,
    SchwabPriceHistoryTransport,
    normalize_symbols,
    parse_price_history_response,
    price_history_parameters,
    write_staged_price_history,
)


UTC = timezone.utc
REQUESTED_AT = datetime(2026, 7, 27, 14, 30, tzinfo=UTC)
RECEIVED_AT = REQUESTED_AT + timedelta(milliseconds=250)
REMOTE_DATE = "Mon, 27 Jul 2026 14:30:00 GMT"


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        is_redirect: bool = False,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        json_error: bool = False,
        stream_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.is_redirect = is_redirect
        self.content = (
            content
            if content is not None
            else json.dumps(payload).encode("utf-8")
        )
        self.headers = headers or {"Date": REMOTE_DATE}
        self.json_error = json_error
        self.stream_error = stream_error
        self.closed = False
        self.iterated_bytes = 0

    def json(self) -> object:
        if self.json_error:
            raise ValueError("bad json")
        return self.payload

    def iter_content(self, chunk_size: int) -> object:
        content = b"{bad" if self.json_error else self.content
        for offset in range(0, len(content), chunk_size):
            chunk = content[offset : offset + chunk_size]
            self.iterated_bytes += len(chunk)
            yield chunk
            if self.stream_error is not None:
                raise self.stream_error

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(
        self,
        response: FakeResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self.values = list(values)

    def __call__(self) -> datetime:
        return self.values.pop(0)


class StaticTokenProvider:
    def __init__(self, token: str = "test-token") -> None:
        self.token = token
        self.calls = 0

    def access_token(self) -> str:
        self.calls += 1
        return self.token


class FailingTokenProvider:
    def access_token(self) -> str:
        from momentum_hunter.schwab_market_data import (
            SchwabMarketDataAuthorizationError,
        )

        raise SchwabMarketDataAuthorizationError("redacted")


def valid_payload(symbol: str = "SPY") -> dict[str, object]:
    return {
        "symbol": symbol,
        "empty": False,
        "previousClose": 734.10,
        "previousCloseDate": 1784836800000,
        "candles": [
            {
                "open": 735.0,
                "high": 736.0,
                "low": 734.5,
                "close": 735.75,
                "volume": 1200,
                "datetime": 1784899860000,
            },
            {
                "open": 734.5,
                "high": 735.0,
                "low": 734.0,
                "close": 734.75,
                "volume": 1000,
                "datetime": 1784899800000,
            },
        ],
    }


def valid_result(
    *,
    symbol: str = "SPY",
    interval: str = "1m",
) -> SchwabPriceHistoryResult:
    return SchwabPriceHistoryResult(
        symbol=symbol,
        interval=interval,
        requested_at="2026-07-27T14:30:00Z",
        received_at="2026-07-27T14:30:00.250000Z",
        previous_close=734.10,
        previous_close_date="2026-07-23T20:00:00Z",
        bars=(
            SchwabPriceBar(
                symbol=symbol,
                interval=interval,
                timestamp="2026-07-24T13:30:00Z",
                open=734.5,
                high=735.0,
                low=734.0,
                close=734.75,
                volume=1000,
            ),
        ),
        clock_skew_proof={"status": "PASS"},
    )


class SchwabPriceHistoryTransportTests(unittest.TestCase):
    def test_intraday_request_is_exact_host_get_only_and_locked_to_regular_hours(self) -> None:
        session = FakeSession(FakeResponse(valid_payload()))
        transport = SchwabPriceHistoryTransport(
            session=session,
            clock=SequenceClock(REQUESTED_AT, RECEIVED_AT),
        )

        result = transport.fetch("access", "spy", "1m")

        self.assertEqual("SPY", result.symbol)
        self.assertEqual("1m", result.interval)
        self.assertEqual(2, len(result.bars))
        self.assertLess(result.bars[0].timestamp, result.bars[1].timestamp)
        self.assertEqual("PASS", result.clock_skew_proof["status"])
        self.assertEqual(1, len(session.calls))
        url, request = session.calls[0]
        self.assertEqual(SCHWAB_PRICE_HISTORY_URL, url)
        self.assertEqual(
            {
                "symbol": "SPY",
                "frequencyType": "minute",
                "frequency": 1,
                "startDate": 1784557800000,
                "endDate": 1785162600000,
                "needExtendedHoursData": "false",
                "needPreviousClose": "true",
            },
            request["params"],
        )
        self.assertFalse(request["allow_redirects"])
        self.assertTrue(request["stream"])
        self.assertEqual("Bearer access", request["headers"]["Authorization"])
        self.assertNotIn("account", json.dumps(request).lower())
        self.assertNotIn("order", json.dumps(request).lower())
        self.assertTrue(session.response.closed)

    def test_daily_request_uses_one_year_daily_history(self) -> None:
        self.assertEqual(
            {
                "symbol": "IWM",
                "periodType": "year",
                "period": 1,
                "frequencyType": "daily",
                "frequency": 1,
                "needExtendedHoursData": "false",
                "needPreviousClose": "true",
            },
            price_history_parameters(
                "iwm",
                "Daily",
                observed_at=REQUESTED_AT,
            ),
        )

    def test_empty_token_is_refused_before_network(self) -> None:
        session = FakeSession(FakeResponse(valid_payload()))
        transport = SchwabPriceHistoryTransport(session=session)

        with self.assertRaises(SchwabPriceHistoryAuthorizationError):
            transport.fetch("", "SPY", "1m")

        self.assertEqual([], session.calls)

    def test_network_redirect_http_size_and_json_fail_closed(self) -> None:
        cases = [
            (
                FakeSession(error=requests.ConnectionError("offline")),
                SchwabPriceHistoryNetworkError,
            ),
            (
                FakeSession(
                    FakeResponse(valid_payload(), is_redirect=True)
                ),
                SchwabPriceHistoryResponseError,
            ),
            (
                FakeSession(
                    FakeResponse(valid_payload(), status_code=429)
                ),
                SchwabPriceHistoryResponseError,
            ),
            (
                FakeSession(
                    FakeResponse(
                        valid_payload(),
                        content=b"x" * (MAX_PRICE_HISTORY_RESPONSE_BYTES + 1),
                    )
                ),
                SchwabPriceHistoryResponseError,
            ),
            (
                FakeSession(
                    FakeResponse(valid_payload(), json_error=True)
                ),
                SchwabPriceHistoryResponseError,
            ),
        ]
        for session, expected in cases:
            with self.subTest(expected=expected.__name__):
                transport = SchwabPriceHistoryTransport(
                    session=session,
                    clock=SequenceClock(REQUESTED_AT, RECEIVED_AT),
                )
                with self.assertRaises(expected):
                    transport.fetch("access", "SPY", "1m")
                if session.response is not None:
                    self.assertTrue(session.response.closed)

    def test_response_stream_stops_after_bounded_decoded_bytes(self) -> None:
        response = FakeResponse(
            valid_payload(),
            content=b"x" * (MAX_PRICE_HISTORY_RESPONSE_BYTES + 100_000),
        )
        session = FakeSession(response)
        transport = SchwabPriceHistoryTransport(
            session=session,
            clock=SequenceClock(REQUESTED_AT, RECEIVED_AT),
        )

        with self.assertRaises(SchwabPriceHistoryResponseError):
            transport.fetch("access", "SPY", "1m")

        self.assertTrue(response.closed)
        self.assertLess(
            response.iterated_bytes,
            MAX_PRICE_HISTORY_RESPONSE_BYTES + 100_000,
        )

    def test_stream_failure_is_redacted_and_response_is_closed(self) -> None:
        response = FakeResponse(
            valid_payload(),
            stream_error=requests.ConnectionError("sensitive provider detail"),
        )
        session = FakeSession(response)
        transport = SchwabPriceHistoryTransport(
            session=session,
            clock=SequenceClock(REQUESTED_AT, RECEIVED_AT),
        )

        with self.assertRaisesRegex(
            SchwabPriceHistoryNetworkError,
            "streaming failed safely",
        ) as raised:
            transport.fetch("access", "SPY", "1m")

        self.assertNotIn("sensitive", str(raised.exception))
        self.assertTrue(response.closed)

    def test_malformed_identity_candles_and_clocks_fail_closed(self) -> None:
        malformed = [
            {"symbol": "IWM", "empty": True, "candles": []},
            {"symbol": "SPY", "empty": False, "candles": []},
            {
                **valid_payload(),
                "candles": [
                    {
                        "open": 10.0,
                        "high": 9.0,
                        "low": 8.0,
                        "close": 9.5,
                        "volume": 1,
                        "datetime": 1784899800000,
                    }
                ],
            },
            {
                **valid_payload(),
                "candles": [
                    valid_payload()["candles"][0],
                    valid_payload()["candles"][0],
                ],
            },
            {
                **valid_payload(),
                "candles": [
                    {
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume": -1,
                        "datetime": 1784899800000,
                    }
                ],
            },
            {
                **valid_payload(),
                "candles": [
                    {
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume": 1,
                        "datetime": int(
                            (RECEIVED_AT + timedelta(minutes=1)).timestamp()
                            * 1000
                        ),
                    }
                ],
            },
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                with self.assertRaises(SchwabPriceHistoryResponseError):
                    parse_price_history_response(
                        payload,
                        expected_symbol="SPY",
                        interval="1m",
                        requested_at=REQUESTED_AT,
                        received_at=RECEIVED_AT,
                        remote_date_header=REMOTE_DATE,
                    )
        with self.assertRaises(SchwabPriceHistoryResponseError):
            parse_price_history_response(
                valid_payload(),
                expected_symbol="SPY",
                interval="1m",
                requested_at=RECEIVED_AT,
                received_at=REQUESTED_AT,
                remote_date_header=REMOTE_DATE,
            )
        with self.assertRaises(SchwabPriceHistoryResponseError):
            parse_price_history_response(
                valid_payload(),
                expected_symbol="SPY",
                interval="1m",
                requested_at=REQUESTED_AT,
                received_at=RECEIVED_AT,
                remote_date_header="",
            )

    def test_interval_candle_limits_fail_before_parsing_large_collections(self) -> None:
        for interval in ("1m", "Daily"):
            with self.subTest(interval=interval):
                payload = valid_payload()
                payload["candles"] = [
                    valid_payload()["candles"][0]
                ] * (MAX_PRICE_HISTORY_BARS[interval] + 1)
                with self.assertRaisesRegex(
                    SchwabPriceHistoryResponseError,
                    "interval candle limit",
                ):
                    parse_price_history_response(
                        payload,
                        expected_symbol="SPY",
                        interval=interval,
                        requested_at=REQUESTED_AT,
                        received_at=RECEIVED_AT,
                        remote_date_header=REMOTE_DATE,
                    )


class SchwabPriceHistorySourceTests(unittest.TestCase):
    def test_bound_token_source_passes_token_to_transport(self) -> None:
        token_provider = StaticTokenProvider()
        transport = RecordingTransport()
        source = SchwabPriceHistorySource(
            token_provider=token_provider,
            transport=transport,
        )

        result = source.history("SPY", "1m")

        self.assertEqual("SPY", result.symbol)
        self.assertEqual(1, token_provider.calls)
        self.assertEqual([("test-token", "SPY", "1m")], transport.calls)

    def test_bound_token_failure_is_redacted_and_no_transport_occurs(self) -> None:
        transport = RecordingTransport()
        source = SchwabPriceHistorySource(
            token_provider=FailingTokenProvider(),
            transport=transport,
        )

        with self.assertRaises(SchwabPriceHistoryAuthorizationError):
            source.history("SPY", "1m")

        self.assertEqual([], transport.calls)

    def test_invalid_symbol_is_rejected_before_token_access(self) -> None:
        token_provider = StaticTokenProvider()
        transport = RecordingTransport()
        source = SchwabPriceHistorySource(
            token_provider=token_provider,
            transport=transport,
        )

        with self.assertRaises(ValueError):
            source.history("../SPY", "1m")

        self.assertEqual(0, token_provider.calls)
        self.assertEqual([], transport.calls)

    def test_batch_is_bounded_and_deduplicated(self) -> None:
        token_provider = StaticTokenProvider()
        source = SchwabPriceHistorySource(
            token_provider=token_provider,
            transport=RecordingTransport(),
        )

        results = source.history_batch(
            ["spy", "SPY", "iwm"],
            ["1m", "Daily", "1m"],
        )

        self.assertEqual(
            [
                ("SPY", "1m"),
                ("SPY", "Daily"),
                ("IWM", "1m"),
                ("IWM", "Daily"),
            ],
            [(item.symbol, item.interval) for item in results],
        )
        self.assertEqual(1, token_provider.calls)
        with self.assertRaises(ValueError):
            normalize_symbols([f"S{index}" for index in range(26)])


class SchwabPriceHistoryStagingTests(unittest.TestCase):
    def test_staging_writes_inactive_lineage_without_touching_active_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active_minute = root / "opportunity-minute-bars.json"
            active_daily = root / "daily-ohlc-bars.json"
            active_minute.write_bytes(b"legacy-minute")
            active_daily.write_bytes(b"legacy-daily")
            staged = root / "staging" / "schwab-candles.json"

            result = write_staged_price_history(
                [valid_result(), valid_result(symbol="IWM", interval="Daily")],
                path=staged,
                active_paths=[active_minute, active_daily],
            )

            self.assertEqual(staged, result)
            payload = json.loads(staged.read_text(encoding="utf-8"))
            self.assertFalse(payload["activeChartSource"])
            self.assertTrue(payload["readOnlyProvider"])
            self.assertFalse(payload["transmitting"])
            self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
            self.assertFalse(payload["accountDataIncluded"])
            self.assertEqual(2, len(payload["results"]))
            self.assertEqual(b"legacy-minute", active_minute.read_bytes())
            self.assertEqual(b"legacy-daily", active_daily.read_bytes())
            self.assertEqual([], list(staged.parent.glob("*.tmp")))

    def test_active_source_paths_and_duplicate_results_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = root / "opportunity-minute-bars.json"
            alternate_active_name = root / "alternate" / "daily-ohlc-bars.json"
            active.write_bytes(b"legacy")

            with self.assertRaises(SchwabPriceHistoryStagingError):
                write_staged_price_history(
                    [valid_result()],
                    path=active,
                    active_paths=[active],
                )
            with self.assertRaises(SchwabPriceHistoryStagingError):
                write_staged_price_history(
                    [valid_result(), replace(valid_result())],
                    path=root / "staging.json",
                    active_paths=[active],
                )
            with self.assertRaises(SchwabPriceHistoryStagingError):
                write_staged_price_history(
                    [valid_result()],
                    path=alternate_active_name,
                    active_paths=[active],
                )

            self.assertEqual(b"legacy", active.read_bytes())

    def test_module_has_no_scoring_readiness_alert_or_execution_imports(self) -> None:
        import momentum_hunter.schwab_price_history as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        forbidden = (
            "momentum_hunter.scoring",
            "momentum_hunter.readiness",
            "momentum_hunter.trade_planning",
            "momentum_hunter.autonomy.broker",
            "submit_order",
            "cancel_order",
        )
        for token in forbidden:
            self.assertNotIn(token, source)


class RecordingTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def fetch(
        self,
        access_token: str,
        symbol: str,
        interval: str,
    ) -> SchwabPriceHistoryResult:
        self.calls.append((access_token, symbol, interval))
        return valid_result(symbol=symbol, interval=interval)


if __name__ == "__main__":
    unittest.main()
