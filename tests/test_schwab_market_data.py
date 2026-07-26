from __future__ import annotations

import inspect
import json
import math
import unittest
from datetime import datetime, timedelta, timezone

import requests

from momentum_hunter.schwab_market_data import (
    HTTP_TIMEOUT,
    MAX_QUOTE_RESPONSE_BYTES,
    SCHWAB_QUOTE_SOURCE,
    SCHWAB_QUOTES_URL,
    BoundSchwabAccessTokenProvider,
    SchwabMarketDataAuthorizationError,
    SchwabMarketDataError,
    SchwabMarketDataNetworkError,
    SchwabMarketDataQuoteSource,
    SchwabMarketDataResponseError,
    SchwabMarketDataTransport,
    StoredSchwabAccessTokenProvider,
    normalize_symbols,
    parse_quote_response,
)
from momentum_hunter.schwab_onboarding import SchwabOAuthTokens


ACCESS_TOKEN = "SYNTHETIC-MARKET-DATA-ACCESS"


class _FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        is_redirect: bool = False,
        content: bytes | None = None,
        json_error: bool = False,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.is_redirect = is_redirect
        self.content = (
            content
            if content is not None
            else json.dumps(payload).encode("utf-8")
        )
        self.json_error = json_error

    def json(self) -> object:
        if self.json_error:
            raise ValueError("synthetic invalid JSON")
        return self.payload


class _FakeSession:
    def __init__(
        self,
        response: _FakeResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeSecrets:
    def __init__(self, *, expired: bool = False) -> None:
        now = datetime.now(timezone.utc)
        self.tokens = SchwabOAuthTokens(
            access_token=ACCESS_TOKEN,
            refresh_token="SYNTHETIC-REFRESH",
            token_type="Bearer",
            scope="synthetic",
            issued_at=now - timedelta(minutes=1),
            expires_at=(
                now - timedelta(seconds=1)
                if expired
                else now + timedelta(minutes=1)
            ),
        )

    def load_tokens(self) -> SchwabOAuthTokens:
        return self.tokens


class _FakeBoundRefresh:
    def __init__(
        self,
        secrets: _FakeSecrets,
        *,
        keep_expired: bool = False,
    ) -> None:
        self.secrets = secrets
        self.keep_expired = keep_expired
        self.confirmations: list[str] = []

    def refresh(self, *, confirmation: str) -> dict[str, object]:
        self.confirmations.append(confirmation)
        if not self.keep_expired:
            now = datetime.now(timezone.utc)
            self.secrets.tokens = SchwabOAuthTokens(
                access_token="SYNTHETIC-REFRESHED-ACCESS",
                refresh_token="SYNTHETIC-REFRESHED-REFRESH",
                token_type="Bearer",
                scope="synthetic",
                issued_at=now,
                expires_at=now + timedelta(minutes=1),
            )
        return {
            "bindingRevalidated": True,
            "accountEnding": "2573",
            "accountType": "INDIVIDUAL_CASH",
        }


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def fetch_quotes(
        self,
        access_token: str,
        symbols: tuple[str, ...],
    ) -> dict:
        normalized = tuple(symbols)
        self.calls.append((access_token, normalized))
        return parse_quote_response(
            quote_payload(),
            expected_symbols=normalized,
        )


class SchwabMarketDataTransportTests(unittest.TestCase):
    def test_exact_get_contract_is_read_only_and_nonredirecting(self) -> None:
        session = _FakeSession(_FakeResponse(quote_payload()))

        quotes = SchwabMarketDataTransport(session=session).fetch_quotes(
            ACCESS_TOKEN,
            ["crwv"],
        )

        self.assertEqual({"CRWV"}, set(quotes))
        self.assertEqual(1, len(session.calls))
        call = session.calls[0]
        self.assertEqual(SCHWAB_QUOTES_URL, call["url"])
        self.assertEqual(
            {"symbols": "CRWV", "fields": "quote"},
            call["params"],
        )
        self.assertEqual(HTTP_TIMEOUT, call["timeout"])
        self.assertFalse(call["allow_redirects"])
        self.assertEqual("application/json", call["headers"]["Accept"])
        self.assertEqual(
            f"Bearer {ACCESS_TOKEN}",
            call["headers"]["Authorization"],
        )
        self.assertEqual("no-store", call["headers"]["Cache-Control"])

    def test_network_status_redirect_size_and_json_fail_without_token_leak(self) -> None:
        cases = [
            (
                _FakeSession(
                    error=requests.ConnectionError(f"failed {ACCESS_TOKEN}")
                ),
                SchwabMarketDataNetworkError,
            ),
            (
                _FakeSession(_FakeResponse({}, status_code=401)),
                SchwabMarketDataResponseError,
            ),
            (
                _FakeSession(
                    _FakeResponse({}, status_code=302, is_redirect=True)
                ),
                SchwabMarketDataResponseError,
            ),
            (
                _FakeSession(
                    _FakeResponse(
                        {},
                        content=b"x" * (MAX_QUOTE_RESPONSE_BYTES + 1),
                    )
                ),
                SchwabMarketDataResponseError,
            ),
            (
                _FakeSession(_FakeResponse({}, json_error=True)),
                SchwabMarketDataResponseError,
            ),
        ]
        for session, expected_error in cases:
            with self.subTest(error=expected_error.__name__):
                with self.assertRaises(expected_error) as raised:
                    SchwabMarketDataTransport(
                        session=session
                    ).fetch_quotes(ACCESS_TOKEN, ["CRWV"])
                self.assertNotIn(ACCESS_TOKEN, str(raised.exception))

    def test_empty_token_and_invalid_or_excess_symbols_fail_before_network(self) -> None:
        session = _FakeSession(_FakeResponse(quote_payload()))
        transport = SchwabMarketDataTransport(session=session)

        with self.assertRaises(SchwabMarketDataAuthorizationError):
            transport.fetch_quotes(" ", ["CRWV"])
        with self.assertRaises(SchwabMarketDataError):
            transport.fetch_quotes(ACCESS_TOKEN, ["BAD SYMBOL"])
        with self.assertRaises(SchwabMarketDataError):
            normalize_symbols(
                [f"S{index}" for index in range(501)]
            )

        self.assertEqual([], session.calls)


class SchwabMarketDataParsingTests(unittest.TestCase):
    def test_quote_uses_oldest_bid_ask_and_quote_clock(self) -> None:
        parsed = parse_quote_response(
            quote_payload(),
            expected_symbols=["CRWV"],
        )["CRWV"]

        self.assertEqual(
            "2026-07-24T23:59:39.583000+00:00",
            parsed.timestamp,
        )
        self.assertEqual(
            "2026-07-24T23:59:39.839000+00:00",
            parsed.provider_quote_timestamp,
        )
        self.assertEqual(
            "2026-07-24T23:59:39.583000+00:00",
            parsed.provider_bid_timestamp,
        )
        self.assertEqual(
            "2026-07-24T23:59:39.839000+00:00",
            parsed.provider_ask_timestamp,
        )
        self.assertEqual("extended", parsed.session)
        self.assertEqual("closed", parsed.trading_state)
        self.assertEqual(SCHWAB_QUOTE_SOURCE, parsed.source)
        self.assertTrue(parsed.realtime)
        self.assertEqual(118.48, parsed.bid)
        self.assertEqual(118.72, parsed.ask)

    def test_missing_symbol_is_unavailable_but_identity_or_clock_drift_fails(self) -> None:
        self.assertEqual(
            {},
            parse_quote_response({}, expected_symbols=["CRWV"]),
        )
        mismatched = quote_payload()
        mismatched["CRWV"]["symbol"] = "OTHER"
        with self.assertRaises(SchwabMarketDataResponseError):
            parse_quote_response(
                mismatched,
                expected_symbols=["CRWV"],
            )
        for field_name in ("quoteTime", "bidTime", "askTime"):
            with self.subTest(field=field_name):
                malformed = quote_payload()
                malformed["CRWV"]["quote"][field_name] = None
                with self.assertRaises(SchwabMarketDataResponseError):
                    parse_quote_response(
                        malformed,
                        expected_symbols=["CRWV"],
                    )

    def test_delayed_or_unknown_status_never_maps_to_tradable(self) -> None:
        delayed = quote_payload()
        delayed["CRWV"]["realtime"] = False
        self.assertEqual(
            "delayed",
            parse_quote_response(
                delayed,
                expected_symbols=["CRWV"],
            )["CRWV"].trading_state,
        )

        unknown = quote_payload()
        unknown["CRWV"]["quote"]["securityStatus"] = "Mystery"
        self.assertEqual(
            "mystery",
            parse_quote_response(
                unknown,
                expected_symbols=["CRWV"],
            )["CRWV"].trading_state,
        )

    def test_nonfinite_price_and_volume_values_are_unavailable(self) -> None:
        malformed = quote_payload()
        malformed["CRWV"]["quote"]["bidPrice"] = math.nan
        malformed["CRWV"]["quote"]["askPrice"] = math.inf
        malformed["CRWV"]["quote"]["lastPrice"] = -math.inf
        malformed["CRWV"]["quote"]["totalVolume"] = math.inf

        parsed = parse_quote_response(
            malformed,
            expected_symbols=["CRWV"],
        )["CRWV"]

        self.assertIsNone(parsed.bid)
        self.assertIsNone(parsed.ask)
        self.assertIsNone(parsed.last)
        self.assertIsNone(parsed.volume)


class SchwabMarketDataQuoteSourceTests(unittest.TestCase):
    def test_encrypted_token_source_returns_shadow_quote_without_account_data(self) -> None:
        transport = _FakeTransport()
        source = SchwabMarketDataQuoteSource(
            secrets_repository=_FakeSecrets(),
            transport=transport,
        )

        quotes = source.quotes(["crwv"])

        self.assertEqual(
            [(ACCESS_TOKEN, ("CRWV",))],
            transport.calls,
        )
        quote = quotes["CRWV"]
        self.assertEqual("CRWV", quote["symbol"])
        self.assertEqual(SCHWAB_QUOTE_SOURCE, quote["source"])
        self.assertNotIn("account", json.dumps(quote).lower())
        self.assertNotIn("order", json.dumps(quote).lower())

    def test_expired_token_fails_before_transport(self) -> None:
        transport = _FakeTransport()
        source = SchwabMarketDataQuoteSource(
            secrets_repository=_FakeSecrets(expired=True),
            transport=transport,
        )

        with self.assertRaises(SchwabMarketDataAuthorizationError):
            source.quotes(["CRWV"])

        self.assertEqual([], transport.calls)

    def test_bound_token_provider_refreshes_only_through_exact_guard(self) -> None:
        from momentum_hunter.schwab_bound_account_refresh import (
            BOUND_REFRESH_CONFIRMATION,
        )

        secrets = _FakeSecrets(expired=True)
        refresh = _FakeBoundRefresh(secrets)
        provider = BoundSchwabAccessTokenProvider(
            secrets_repository=secrets,
            bound_refresh=refresh,
        )

        token = provider.access_token()

        self.assertEqual("SYNTHETIC-REFRESHED-ACCESS", token)
        self.assertEqual(
            [BOUND_REFRESH_CONFIRMATION],
            refresh.confirmations,
        )

    def test_bound_token_provider_rejects_still_expired_refresh(self) -> None:
        secrets = _FakeSecrets(expired=True)
        provider = BoundSchwabAccessTokenProvider(
            secrets_repository=secrets,
            bound_refresh=_FakeBoundRefresh(
                secrets,
                keep_expired=True,
            ),
        )

        with self.assertRaises(SchwabMarketDataAuthorizationError):
            provider.access_token()

    def test_token_provider_and_secrets_repository_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            SchwabMarketDataQuoteSource(
                secrets_repository=_FakeSecrets(),
                token_provider=StoredSchwabAccessTokenProvider(
                    _FakeSecrets()
                ),
            )

    def test_source_contains_one_marketdata_url_and_no_account_or_order_endpoint(self) -> None:
        import momentum_hunter.schwab_market_data as module

        source = inspect.getsource(module)
        self.assertEqual(1, source.count("https://api.schwabapi.com/"))
        self.assertIn("/marketdata/v1/quotes", source)
        self.assertNotIn("/trader/v1/accounts", source)
        self.assertNotIn("/orders", source)
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)
        self.assertNotIn("replace_order", source)


def quote_payload() -> dict[str, object]:
    return {
        "CRWV": {
            "assetMainType": "EQUITY",
            "quoteType": "NBBO",
            "realtime": True,
            "symbol": "CRWV",
            "quote": {
                "askPrice": 118.72,
                "askSize": 2,
                "askTime": 1784937579839,
                "bidPrice": 118.48,
                "bidSize": 1,
                "bidTime": 1784937579583,
                "lastPrice": 118.50,
                "quoteTime": 1784937579839,
                "securityStatus": "Closed",
                "totalVolume": 9_001_234,
                "tradeTime": 1784937596447,
            },
        }
    }
