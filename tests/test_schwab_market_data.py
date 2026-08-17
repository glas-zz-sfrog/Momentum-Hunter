from __future__ import annotations

import io
import inspect
import json
import math
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from momentum_hunter.schwab_market_data import (
    HTTP_TIMEOUT,
    INJECTED_QUOTE_PROOF_ORIGIN,
    LIVE_SCHWAB_QUOTE_PROOF_ORIGIN,
    MAX_QUOTE_RESPONSE_BYTES,
    REGULAR_MARKET_QUOTE_PROOF_SCHEMA_VERSION,
    SCHWAB_QUOTE_SOURCE,
    SCHWAB_QUOTES_URL,
    UNSPECIFIED_QUOTE_PROOF_ORIGIN,
    BoundSchwabAccessTokenProvider,
    SchwabAuthPersistenceFailed,
    SchwabAuthRefreshFailed,
    SchwabAuthSecureStoreError,
    SchwabAuthStateMissingError,
    SchwabMarketDataAuthorizationError,
    SchwabMarketDataError,
    SchwabMarketDataNetworkError,
    SchwabMarketDataQuoteSource,
    SchwabMarketDataResponseError,
    SchwabMarketDataTransport,
    SchwabReauthorizationRequired,
    SchwabQuoteEvidenceBatch,
    StoredSchwabAccessTokenProvider,
    build_regular_market_quote_proof,
    main,
    normalize_symbols,
    parse_quote_response,
)
from momentum_hunter.shadow_opening import build_https_clock_skew_proof
from momentum_hunter.schwab_onboarding import (
    SchwabOAuthError,
    SchwabOAuthResponseError,
    SchwabOAuthTokens,
)
from momentum_hunter.schwab_setup import SchwabSetupError


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


class _ProofQuoteSource:
    def __init__(
        self,
        quotes: dict[str, dict[str, object]],
        *,
        trusted_remote_at: datetime | None = None,
    ) -> None:
        self.values = quotes
        self.trusted_remote_at = trusted_remote_at
        self.calls: list[tuple[tuple[str, ...], datetime | None]] = []

    def quotes(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime | None = None,
    ) -> dict[str, dict[str, object]]:
        self.calls.append((tuple(symbols), decision_at))
        return {
            symbol: dict(self.values[symbol])
            for symbol in symbols
            if symbol in self.values
        }

    def quotes_with_clock(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime | None = None,
    ) -> SchwabQuoteEvidenceBatch:
        assert decision_at is not None
        return SchwabQuoteEvidenceBatch(
            quotes=self.quotes(symbols, decision_at=decision_at),
            clock_skew_proof=build_https_clock_skew_proof(
                request_started_at=decision_at,
                response_received_at=decision_at,
                remote_date_header=format_datetime(
                    self.trusted_remote_at or decision_at
                ),
                source_identity="synthetic-test-https-date",
            ),
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

    def test_bound_token_provider_uses_valid_token_without_refresh(self) -> None:
        secrets = _FakeSecrets()
        refresh = _FakeBoundRefresh(secrets)
        provider = BoundSchwabAccessTokenProvider(
            secrets_repository=secrets,
            bound_refresh=refresh,
        )

        self.assertEqual(ACCESS_TOKEN, provider.access_token())
        self.assertEqual([], refresh.confirmations)

    def test_bound_token_provider_classifies_missing_and_unreadable_stores(self) -> None:
        class MissingSecrets:
            exists = False

            def load_tokens(self):
                raise SchwabOAuthError("synthetic missing store")

        class UnreadableSecrets:
            exists = True

            def load_tokens(self):
                raise SchwabSetupError("synthetic DPAPI failure")

        with self.assertRaises(SchwabAuthStateMissingError):
            BoundSchwabAccessTokenProvider(
                secrets_repository=MissingSecrets(),
                bound_refresh=object(),
            ).access_token()
        with self.assertRaises(SchwabAuthSecureStoreError):
            BoundSchwabAccessTokenProvider(
                secrets_repository=UnreadableSecrets(),
                bound_refresh=object(),
            ).access_token()

    def test_bound_token_provider_classifies_reauth_and_persistence_failure(self) -> None:
        class RejectedRefresh:
            def refresh(self, *, confirmation: str):
                raise SchwabOAuthResponseError("synthetic HTTP 400")

        class PersistenceFailure:
            def refresh(self, *, confirmation: str):
                raise OSError("synthetic persistence failure")

        for refresh, expected in (
            (RejectedRefresh(), SchwabReauthorizationRequired),
            (PersistenceFailure(), SchwabAuthPersistenceFailed),
        ):
            with self.subTest(expected=expected.__name__):
                with self.assertRaises(expected):
                    BoundSchwabAccessTokenProvider(
                        secrets_repository=_FakeSecrets(expired=True),
                        bound_refresh=refresh,
                    ).access_token()

    def test_provider_rejection_refresh_is_bounded_to_one_attempt(self) -> None:
        secrets = _FakeSecrets()
        refresh = _FakeBoundRefresh(secrets)
        provider = BoundSchwabAccessTokenProvider(
            secrets_repository=secrets,
            bound_refresh=refresh,
        )

        self.assertEqual(
            "SYNTHETIC-REFRESHED-ACCESS",
            provider.refresh_after_rejection(),
        )
        with self.assertRaises(SchwabAuthRefreshFailed):
            provider.refresh_after_rejection()
        self.assertEqual(1, len(refresh.confirmations))

    def test_concurrent_expired_token_reads_share_one_refresh(self) -> None:
        from momentum_hunter.schwab_bound_account_refresh import (
            BOUND_REFRESH_CONFIRMATION,
        )

        class BlockingSecrets(_FakeSecrets):
            def __init__(self) -> None:
                super().__init__(expired=True)
                self.barrier = threading.Barrier(2)
                self.lock = threading.Lock()
                self.load_count = 0

            def load_tokens(self) -> SchwabOAuthTokens:
                with self.lock:
                    self.load_count += 1
                    wait_for_peer = self.load_count <= 2
                    tokens = self.tokens
                if wait_for_peer:
                    self.barrier.wait(timeout=2)
                return tokens

        secrets = BlockingSecrets()
        refresh = _FakeBoundRefresh(secrets)
        provider = BoundSchwabAccessTokenProvider(
            secrets_repository=secrets,
            bound_refresh=refresh,
        )

        with ThreadPoolExecutor(max_workers=2) as pool:
            tokens = tuple(pool.map(lambda _value: provider.access_token(), range(2)))

        self.assertEqual(
            ("SYNTHETIC-REFRESHED-ACCESS", "SYNTHETIC-REFRESHED-ACCESS"),
            tokens,
        )
        self.assertEqual([BOUND_REFRESH_CONFIRMATION], refresh.confirmations)

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


class SchwabRegularMarketQuoteProofTests(unittest.TestCase):
    def test_quote_proof_uses_post_request_evaluation_clock(self) -> None:
        requested_at = datetime(
            2026,
            7,
            27,
            14,
            0,
            tzinfo=timezone.utc,
        )
        evaluated_at = requested_at + timedelta(seconds=5)
        observed_at = requested_at + timedelta(seconds=4)
        source = _ProofQuoteSource(
            {
                symbol: proof_quote(symbol, observed_at)
                for symbol in ("CRWV", "SPY", "IWM")
            }
        )
        clock = Mock(side_effect=(requested_at, evaluated_at))

        proof = build_regular_market_quote_proof(
            source,
            ("CRWV", "SPY", "IWM"),
            clock=clock,
        )

        self.assertEqual("PASS", proof["proofStatus"])
        self.assertEqual(requested_at.isoformat(), proof["requestedAt"])
        self.assertEqual(evaluated_at.isoformat(), proof["checkedAt"])
        self.assertEqual(5.0, proof["requestDurationSeconds"])
        self.assertEqual(
            [(("CRWV", "SPY", "IWM"), requested_at)],
            source.calls,
        )
        self.assertEqual(
            [1.0, 1.0, 1.0],
            [row["quoteAgeSeconds"] for row in proof["quotes"]],
        )

    def test_quote_proof_rejects_invalid_evaluation_clock(self) -> None:
        requested_at = datetime(
            2026,
            7,
            27,
            14,
            0,
            tzinfo=timezone.utc,
        )
        source = _ProofQuoteSource(
            {"CRWV": proof_quote("CRWV", requested_at)}
        )

        with self.assertRaisesRegex(ValueError, "cannot precede"):
            build_regular_market_quote_proof(
                source,
                ("CRWV",),
                clock=Mock(
                    side_effect=(
                        requested_at,
                        requested_at - timedelta(seconds=1),
                    )
                ),
            )

        with self.assertRaisesRegex(ValueError, "UTC offset"):
            build_regular_market_quote_proof(
                source,
                ("CRWV",),
                clock=Mock(
                    side_effect=(
                        requested_at,
                        datetime(2026, 7, 27, 14, 0),
                    )
                ),
            )

    def test_fresh_regular_realtime_quotes_pass_and_cli_writes_redacted_proof(
        self,
    ) -> None:
        checked_at = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        source = _ProofQuoteSource(
            {
                symbol: proof_quote(symbol, checked_at - timedelta(seconds=5))
                for symbol in ("CRWV", "SPY", "IWM")
            }
        )

        proof = build_regular_market_quote_proof(
            source,
            ["crwv", "SPY", "IWM"],
            checked_at=checked_at,
        )

        self.assertEqual("PASS", proof["proofStatus"])
        self.assertEqual(
            REGULAR_MARKET_QUOTE_PROOF_SCHEMA_VERSION,
            proof["schemaVersion"],
        )
        self.assertEqual(
            UNSPECIFIED_QUOTE_PROOF_ORIGIN,
            proof["evidenceOrigin"],
        )
        self.assertFalse(proof["productionSource"])
        self.assertEqual(30, proof["maximumQuoteAgeSeconds"])
        self.assertEqual(
            [(("CRWV", "SPY", "IWM"), checked_at)],
            source.calls,
        )
        self.assertTrue(
            all(row["status"] == "PASS" for row in proof["quotes"])
        )
        self.assertFalse(proof["transmitting"])
        self.assertEqual("UNAVAILABLE", proof["orderTransmission"])
        self.assertFalse(proof["accountDataIncluded"])

        with tempfile.TemporaryDirectory() as temporary:
            output_path = Path(temporary) / "quote-proof.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "proof",
                        "--symbols",
                        "CRWV",
                        "SPY",
                        "IWM",
                        "--output",
                        str(output_path),
                    ],
                    source=source,
                    checked_at=checked_at,
                )
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(0, result)
            self.assertEqual(persisted, json.loads(stdout.getvalue()))
            self.assertEqual(
                INJECTED_QUOTE_PROOF_ORIGIN,
                persisted["evidenceOrigin"],
            )
            self.assertFalse(persisted["productionSource"])
            serialized = json.dumps(persisted).lower()
            self.assertNotIn(ACCESS_TOKEN.lower(), serialized)
            self.assertNotIn("refresh_token", serialized)
            self.assertNotIn("account_hash", serialized)

    def test_default_cli_marks_only_real_transport_as_live_origin(self) -> None:
        checked_at = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        source = _ProofQuoteSource(
            {
                symbol: proof_quote(symbol, checked_at - timedelta(seconds=5))
                for symbol in ("CRWV", "SPY", "IWM")
            }
        )

        with (
            patch(
                "momentum_hunter.schwab_market_data.SchwabMarketDataQuoteSource",
                return_value=source,
            ),
            tempfile.TemporaryDirectory() as temporary,
        ):
            output_path = Path(temporary) / "quote-proof.json"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "proof",
                        "--symbols",
                        "CRWV",
                        "SPY",
                        "IWM",
                        "--output",
                        str(output_path),
                    ],
                    checked_at=checked_at,
                )
            persisted = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(0, result)
        self.assertEqual(
            LIVE_SCHWAB_QUOTE_PROOF_ORIGIN,
            persisted["evidenceOrigin"],
        )
        self.assertTrue(persisted["productionSource"])

    def test_missing_stale_closed_delayed_and_invalid_quotes_fail_honestly(
        self,
    ) -> None:
        checked_at = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        stale = proof_quote("CRWV", checked_at - timedelta(seconds=31))
        stale["session"] = "extended"
        stale["trading_state"] = "closed"
        stale["realtime"] = False
        stale["bid"] = None

        proof = build_regular_market_quote_proof(
            _ProofQuoteSource({"CRWV": stale}),
            ["CRWV", "SPY"],
            checked_at=checked_at,
        )

        self.assertEqual("FAIL", proof["proofStatus"])
        rows = {row["symbol"]: row for row in proof["quotes"]}
        self.assertEqual(
            {
                "NOT_REALTIME",
                "SESSION_NOT_REGULAR",
                "STATE_NOT_TRADABLE",
                "BID_ASK_MISSING",
                "QUOTE_STALE",
            },
            set(rows["CRWV"]["findings"]),
        )
        self.assertIn("QUOTE_MISSING", rows["SPY"]["findings"])
        self.assertEqual("FAIL", rows["SPY"]["status"])

    def test_future_provider_clock_fails_even_when_executable_clock_is_current(
        self,
    ) -> None:
        checked_at = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        quote = proof_quote("CRWV", checked_at - timedelta(seconds=5))
        quote["provider_ask_timestamp"] = (
            checked_at + timedelta(seconds=1)
        ).isoformat()

        proof = build_regular_market_quote_proof(
            _ProofQuoteSource({"CRWV": quote}),
            ["CRWV"],
            checked_at=checked_at,
        )

        self.assertEqual("FAIL", proof["proofStatus"])
        self.assertIn(
            "PROVIDER_ASK_TIMESTAMP_IN_FUTURE",
            proof["quotes"][0]["findings"],
        )

    def test_validated_clock_bound_accepts_provider_time_ahead_of_local_clock(
        self,
    ) -> None:
        local_at = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        trusted_remote_at = local_at + timedelta(seconds=2)
        observed_at = local_at + timedelta(seconds=1.5)
        source = _ProofQuoteSource(
            {"CRWV": proof_quote("CRWV", observed_at)},
            trusted_remote_at=trusted_remote_at,
        )

        proof = build_regular_market_quote_proof(
            source,
            ["CRWV"],
            checked_at=local_at,
            require_clock_proof=True,
        )

        self.assertEqual("PASS", proof["proofStatus"])
        self.assertEqual([], proof["clockSkewFindings"])
        self.assertEqual(
            "VALIDATED_HTTPS_DATE_BOUND",
            proof["quoteTimeBasis"]["basis"],
        )
        self.assertEqual(
            (local_at + timedelta(seconds=3)).isoformat(),
            proof["quoteTimeBasis"]["latestPlausibleTrustedAt"],
        )
        self.assertEqual(1.5, proof["quotes"][0]["quoteAgeSeconds"])
        self.assertEqual([], proof["quotes"][0]["findings"])

    def test_provider_time_beyond_validated_clock_bound_fails(self) -> None:
        local_at = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        source = _ProofQuoteSource(
            {
                "CRWV": proof_quote(
                    "CRWV",
                    local_at + timedelta(seconds=3.001),
                )
            },
            trusted_remote_at=local_at + timedelta(seconds=2),
        )

        proof = build_regular_market_quote_proof(
            source,
            ["CRWV"],
            checked_at=local_at,
            require_clock_proof=True,
        )

        self.assertEqual("FAIL", proof["proofStatus"])
        self.assertIn(
            "QUOTE_IN_FUTURE",
            proof["quotes"][0]["findings"],
        )
        self.assertIn(
            "PROVIDER_QUOTE_TIMESTAMP_IN_FUTURE",
            proof["quotes"][0]["findings"],
        )

    def test_invalid_clock_proof_never_grants_a_future_time_bound(self) -> None:
        local_at = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        source = _ProofQuoteSource(
            {"CRWV": proof_quote("CRWV", local_at)},
            trusted_remote_at=local_at + timedelta(seconds=5),
        )

        proof = build_regular_market_quote_proof(
            source,
            ["CRWV"],
            checked_at=local_at,
            require_clock_proof=True,
        )

        self.assertEqual("FAIL", proof["proofStatus"])
        self.assertNotEqual([], proof["clockSkewFindings"])
        self.assertEqual(
            "LOCAL_EVALUATION_CLOCK",
            proof["quoteTimeBasis"]["basis"],
        )

    def test_clock_uncertainty_uses_conservative_staleness_age(self) -> None:
        local_at = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
        source = _ProofQuoteSource(
            {
                "CRWV": proof_quote(
                    "CRWV",
                    local_at - timedelta(seconds=28),
                )
            },
            trusted_remote_at=local_at + timedelta(seconds=2),
        )

        proof = build_regular_market_quote_proof(
            source,
            ["CRWV"],
            checked_at=local_at,
            require_clock_proof=True,
        )

        self.assertEqual("FAIL", proof["proofStatus"])
        self.assertEqual(31.0, proof["quotes"][0]["quoteAgeSeconds"])
        self.assertIn("QUOTE_STALE", proof["quotes"][0]["findings"])


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


def proof_quote(symbol: str, observed_at: datetime) -> dict[str, object]:
    timestamp = observed_at.isoformat()
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "provider_quote_timestamp": timestamp,
        "provider_bid_timestamp": timestamp,
        "provider_ask_timestamp": timestamp,
        "bid": 100.0,
        "ask": 100.05,
        "last": 100.02,
        "volume": 10_000,
        "session": "regular",
        "trading_state": "tradable",
        "realtime": True,
        "security_status": "Normal",
        "source": SCHWAB_QUOTE_SOURCE,
    }
