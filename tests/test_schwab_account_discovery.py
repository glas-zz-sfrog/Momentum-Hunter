from __future__ import annotations

import inspect
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

from momentum_hunter.schwab_account_discovery import (
    DISCOVERY_CONFIRMATION,
    HTTP_TIMEOUT,
    MAX_DISCOVERY_RESPONSE_BYTES,
    SCHWAB_ACCOUNT_NUMBERS_URL,
    DiscoveredSchwabAccount,
    SchwabAccountDiscovery,
    SchwabAccountDiscoveryError,
    SchwabAccountDiscoveryNetworkError,
    SchwabAccountDiscoveryResponseError,
    SchwabAccountNumbersTransport,
    build_discovery_report,
    main,
    parse_discovered_accounts,
)
from momentum_hunter.schwab_onboarding import SchwabOAuthTokens


ACCESS_TOKEN = "SYNTHETIC-DISCOVERY-ACCESS-TOKEN"
ACCOUNT_NUMBER = "12340573"
ACCOUNT_HASH = "SYNTHETIC-OPAQUE-ACCOUNT-HASH"


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
        self.content = content if content is not None else json.dumps(payload).encode("utf-8")
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
            refresh_token="SYNTHETIC-REFRESH-TOKEN",
            token_type="Bearer",
            scope="synthetic",
            issued_at=now - timedelta(minutes=1),
            expires_at=now - timedelta(seconds=1) if expired else now + timedelta(minutes=1),
        )
        self.load_count = 0

    def load_tokens(self) -> SchwabOAuthTokens:
        self.load_count += 1
        return self.tokens

    def status(self) -> dict[str, object]:
        return {
            "credentialsStored": True,
            "oauthAuthorized": True,
            "tokenState": "ACTIVE",
        }


class _FakeTransport:
    def __init__(self, accounts: list[DiscoveredSchwabAccount]) -> None:
        self.accounts = accounts
        self.tokens: list[str] = []

    def discover(self, access_token: str) -> list[DiscoveredSchwabAccount]:
        self.tokens.append(access_token)
        return self.accounts


class SchwabAccountDiscoveryTransportTests(unittest.TestCase):
    def test_exact_get_endpoint_headers_timeout_and_no_redirect(self) -> None:
        session = _FakeSession(
            _FakeResponse([{"accountNumber": ACCOUNT_NUMBER, "hashValue": ACCOUNT_HASH}])
        )
        accounts = SchwabAccountNumbersTransport(session=session).discover(ACCESS_TOKEN)

        self.assertEqual("0573", accounts[0].account_number_last_four)
        self.assertEqual(1, len(session.calls))
        call = session.calls[0]
        self.assertEqual(SCHWAB_ACCOUNT_NUMBERS_URL, call["url"])
        self.assertEqual(HTTP_TIMEOUT, call["timeout"])
        self.assertFalse(call["allow_redirects"])
        headers = call["headers"]
        self.assertEqual("application/json", headers["Accept"])
        self.assertEqual(f"Bearer {ACCESS_TOKEN}", headers["Authorization"])
        self.assertEqual("no-store", headers["Cache-Control"])

    def test_network_status_redirect_size_and_json_fail_without_secret_leak(self) -> None:
        cases = [
            (
                _FakeSession(error=requests.ConnectionError(f"failed {ACCESS_TOKEN}")),
                SchwabAccountDiscoveryNetworkError,
            ),
            (
                _FakeSession(_FakeResponse({}, status_code=401)),
                SchwabAccountDiscoveryResponseError,
            ),
            (
                _FakeSession(_FakeResponse({}, status_code=302, is_redirect=True)),
                SchwabAccountDiscoveryResponseError,
            ),
            (
                _FakeSession(
                    _FakeResponse(
                        {},
                        content=b"x" * (MAX_DISCOVERY_RESPONSE_BYTES + 1),
                    )
                ),
                SchwabAccountDiscoveryResponseError,
            ),
            (
                _FakeSession(_FakeResponse({}, json_error=True)),
                SchwabAccountDiscoveryResponseError,
            ),
        ]
        for session, expected_error in cases:
            with self.subTest(error=expected_error.__name__):
                with self.assertRaises(expected_error) as raised:
                    SchwabAccountNumbersTransport(session=session).discover(ACCESS_TOKEN)
                self.assertNotIn(ACCESS_TOKEN, str(raised.exception))

    def test_empty_access_token_fails_before_network(self) -> None:
        session = _FakeSession(
            _FakeResponse([{"accountNumber": ACCOUNT_NUMBER, "hashValue": ACCOUNT_HASH}])
        )
        with self.assertRaises(SchwabAccountDiscoveryError):
            SchwabAccountNumbersTransport(session=session).discover(" ")
        self.assertEqual([], session.calls)


class SchwabAccountDiscoveryParsingTests(unittest.TestCase):
    def test_valid_payload_discards_full_account_number_and_redacts_hash(self) -> None:
        accounts = parse_discovered_accounts(
            [{"accountNumber": ACCOUNT_NUMBER, "hashValue": ACCOUNT_HASH}]
        )
        report = build_discovery_report(accounts)
        rendered = json.dumps(report)

        self.assertEqual(1, report["authorizedAccountCount"])
        self.assertTrue(report["singleCanaryCandidate"])
        self.assertEqual("0573", report["accounts"][0]["accountEnding"])
        self.assertNotIn(ACCOUNT_NUMBER, rendered)
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertNotIn(ACCOUNT_NUMBER, repr(accounts[0]))
        self.assertNotIn(ACCOUNT_HASH, repr(accounts[0]))
        self.assertEqual("NONE", report["persistence"])
        self.assertEqual("NOT_BOUND", report["accountBinding"])
        self.assertFalse(report["balancesRequested"])
        self.assertFalse(report["positionsRequested"])
        self.assertFalse(report["marketDataRequested"])
        self.assertFalse(report["ordersRequested"])
        self.assertEqual("UNAVAILABLE", report["orderTransmission"])

    def test_invalid_shape_missing_fields_bad_suffix_and_entry_fail(self) -> None:
        payloads = [
            {},
            ["bad-entry"],
            [{"accountNumber": "", "hashValue": ACCOUNT_HASH}],
            [{"accountNumber": ACCOUNT_NUMBER, "hashValue": ""}],
            [{"accountNumber": "ABCD", "hashValue": ACCOUNT_HASH}],
        ]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(
                SchwabAccountDiscoveryResponseError
            ):
                parse_discovered_accounts(payload)

    def test_duplicate_number_or_hash_fails_closed(self) -> None:
        duplicate_number = [
            {"accountNumber": ACCOUNT_NUMBER, "hashValue": "HASH-A"},
            {"accountNumber": ACCOUNT_NUMBER, "hashValue": "HASH-B"},
        ]
        duplicate_hash = [
            {"accountNumber": ACCOUNT_NUMBER, "hashValue": ACCOUNT_HASH},
            {"accountNumber": "99990574", "hashValue": ACCOUNT_HASH},
        ]
        for payload in (duplicate_number, duplicate_hash):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                SchwabAccountDiscoveryResponseError, "duplicate"
            ):
                parse_discovered_accounts(payload)

    def test_zero_and_multiple_accounts_are_not_single_canary_candidates(self) -> None:
        empty_report = build_discovery_report([])
        multiple_report = build_discovery_report(
            [
                DiscoveredSchwabAccount("0573", "HASH-A"),
                DiscoveredSchwabAccount("0574", "HASH-B"),
            ]
        )
        self.assertFalse(empty_report["singleCanaryCandidate"])
        self.assertFalse(multiple_report["singleCanaryCandidate"])
        self.assertEqual(0, empty_report["authorizedAccountCount"])
        self.assertEqual(2, multiple_report["authorizedAccountCount"])


class SchwabAccountDiscoveryBoundaryTests(unittest.TestCase):
    def test_exact_confirmation_precedes_token_access_and_network(self) -> None:
        secrets = _FakeSecrets()
        transport = _FakeTransport(
            [DiscoveredSchwabAccount("0573", ACCOUNT_HASH)]
        )
        discovery = SchwabAccountDiscovery(
            secrets_repository=secrets,
            transport=transport,
        )

        with self.assertRaisesRegex(SchwabAccountDiscoveryError, "exact confirmation"):
            discovery.discover(confirmation="yes")
        self.assertEqual(0, secrets.load_count)
        self.assertEqual([], transport.tokens)

        report = discovery.discover(confirmation=DISCOVERY_CONFIRMATION)
        self.assertEqual(1, report["authorizedAccountCount"])
        self.assertEqual([ACCESS_TOKEN], transport.tokens)

    def test_expired_token_fails_before_account_request(self) -> None:
        secrets = _FakeSecrets(expired=True)
        transport = _FakeTransport(
            [DiscoveredSchwabAccount("0573", ACCOUNT_HASH)]
        )
        with self.assertRaisesRegex(SchwabAccountDiscoveryError, "expired"):
            SchwabAccountDiscovery(
                secrets_repository=secrets,
                transport=transport,
            ).discover(confirmation=DISCOVERY_CONFIRMATION)
        self.assertEqual([], transport.tokens)

    def test_status_is_network_free_and_locked(self) -> None:
        secrets = _FakeSecrets()
        transport = _FakeTransport([])
        status = SchwabAccountDiscovery(
            secrets_repository=secrets,
            transport=transport,
        ).status()
        self.assertEqual("LOCKED_EXACT_CONFIRMATION_REQUIRED", status["accountDiscovery"])
        self.assertEqual("NOT_BOUND", status["accountBinding"])
        self.assertEqual("NONE", status["persistence"])
        self.assertEqual("UNAVAILABLE", status["orderTransmission"])
        self.assertEqual([], transport.tokens)

    def test_module_has_one_get_endpoint_and_no_write_or_binding_capability(self) -> None:
        import momentum_hunter.schwab_account_discovery as module

        source = inspect.getsource(module)
        self.assertEqual(1, source.count("https://api.schwabapi.com/"))
        self.assertIn("/trader/v1/accounts/accountNumbers", source)
        self.assertNotIn("/orders", source)
        self.assertNotIn("/marketdata", source)
        self.assertNotIn("save_new(", source)
        self.assertNotIn("save_tokens(", source)
        for method in ("post(", "put(", "patch(", "delete("):
            self.assertNotIn(f".{method}", source.lower())

    def test_cli_accepts_no_token_account_or_endpoint_arguments(self) -> None:
        for value in (
            "--access-token",
            "--account-number",
            "--account-hash",
            "--endpoint",
        ):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                redirect_stdout(stdout),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                main(["status", value, "SENSITIVE"])
            self.assertEqual(2, raised.exception.code)
            rendered = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn("SENSITIVE", rendered)

    def test_cli_discovery_output_is_redacted(self) -> None:
        report = build_discovery_report(
            [DiscoveredSchwabAccount("0573", ACCOUNT_HASH)]
        )
        stdout = io.StringIO()
        with (
            patch(
                "momentum_hunter.schwab_account_discovery.SchwabAccountDiscovery.discover",
                return_value=report,
            ),
            patch("builtins.input", return_value=DISCOVERY_CONFIRMATION),
            redirect_stdout(stdout),
        ):
            self.assertEqual(0, main(["discover"]))
        rendered = stdout.getvalue()
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertIn("0573", rendered)


if __name__ == "__main__":
    unittest.main()
