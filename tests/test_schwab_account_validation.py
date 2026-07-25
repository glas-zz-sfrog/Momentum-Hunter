from __future__ import annotations

import inspect
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

from momentum_hunter.schwab_account_discovery import DiscoveredSchwabAccount
from momentum_hunter.schwab_account_validation import (
    MAX_ACCOUNT_RESPONSE_BYTES,
    SCHWAB_ACCOUNT_DETAILS_BASE_URL,
    VALIDATION_CONFIRMATION,
    SchwabAccountDetailsTransport,
    SchwabAccountIdentity,
    SchwabAccountValidationError,
    SchwabAccountValidationNetworkError,
    SchwabAccountValidationResponseError,
    SchwabCashAccountValidation,
    build_unpersisted_binding_candidate,
    build_validation_report,
    main,
    parse_account_identity,
)
from momentum_hunter.schwab_onboarding import SchwabOAuthTokens


ACCESS_TOKEN = "SYNTHETIC-VALIDATION-ACCESS-TOKEN"
REFRESH_TOKEN = "SYNTHETIC-VALIDATION-REFRESH-TOKEN"
ACCOUNT_NUMBER = "12342573"
ACCOUNT_ENDING = "2573"
ACCOUNT_HASH = "SYNTHETIC/OPAQUE+ACCOUNT=HASH"
BALANCE_SENTINEL = 987654.32


def _account_payload(
    *,
    account_type: str = "CASH",
    account_number: str = ACCOUNT_NUMBER,
    positions: object = None,
    include_balances: bool = True,
) -> dict[str, object]:
    account: dict[str, object] = {
        "type": account_type,
        "accountNumber": account_number,
    }
    if positions is not None:
        account["positions"] = positions
    if include_balances:
        account["currentBalances"] = {"cashAvailableForTrading": BALANCE_SENTINEL}
    return {"securitiesAccount": account}


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
            refresh_token=REFRESH_TOKEN,
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


class _FakeDiscoveryTransport:
    def __init__(self, accounts: list[DiscoveredSchwabAccount]) -> None:
        self.accounts = accounts
        self.tokens: list[str] = []

    def discover(self, access_token: str) -> list[DiscoveredSchwabAccount]:
        self.tokens.append(access_token)
        return self.accounts


class _FakeDetailsTransport:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def fetch(self, access_token: str, account_hash: str) -> object:
        self.calls.append((access_token, account_hash))
        return self.payload


class SchwabAccountDetailsTransportTests(unittest.TestCase):
    def test_exact_get_endpoint_has_encoded_hash_and_no_fields_parameter(self) -> None:
        session = _FakeSession(_FakeResponse(_account_payload()))
        payload = SchwabAccountDetailsTransport(session=session).fetch(
            ACCESS_TOKEN,
            ACCOUNT_HASH,
        )

        self.assertEqual(_account_payload(), payload)
        self.assertEqual(1, len(session.calls))
        call = session.calls[0]
        self.assertEqual(
            f"{SCHWAB_ACCOUNT_DETAILS_BASE_URL}/SYNTHETIC%2FOPAQUE%2BACCOUNT%3DHASH",
            call["url"],
        )
        self.assertNotIn("?", call["url"])
        self.assertNotIn("fields", call)
        self.assertFalse(call["allow_redirects"])
        self.assertEqual(("5.0", "30.0"), tuple(map(str, call["timeout"])))
        headers = call["headers"]
        self.assertEqual("application/json", headers["Accept"])
        self.assertEqual(f"Bearer {ACCESS_TOKEN}", headers["Authorization"])
        self.assertEqual("no-store", headers["Cache-Control"])

    def test_empty_access_token_or_hash_fails_before_network(self) -> None:
        session = _FakeSession(_FakeResponse(_account_payload()))
        transport = SchwabAccountDetailsTransport(session=session)
        for token, account_hash in ((" ", ACCOUNT_HASH), (ACCESS_TOKEN, " ")):
            with self.subTest(token=token, account_hash=account_hash):
                with self.assertRaises(SchwabAccountValidationError):
                    transport.fetch(token, account_hash)
        self.assertEqual([], session.calls)

    def test_transport_failures_never_echo_token_or_hash(self) -> None:
        cases = [
            (
                _FakeSession(
                    error=requests.ConnectionError(f"{ACCESS_TOKEN} {ACCOUNT_HASH}")
                ),
                SchwabAccountValidationNetworkError,
            ),
            (
                _FakeSession(_FakeResponse({}, status_code=401)),
                SchwabAccountValidationResponseError,
            ),
            (
                _FakeSession(_FakeResponse({}, status_code=302, is_redirect=True)),
                SchwabAccountValidationResponseError,
            ),
            (
                _FakeSession(
                    _FakeResponse(
                        {},
                        content=b"x" * (MAX_ACCOUNT_RESPONSE_BYTES + 1),
                    )
                ),
                SchwabAccountValidationResponseError,
            ),
            (
                _FakeSession(_FakeResponse({}, json_error=True)),
                SchwabAccountValidationResponseError,
            ),
        ]
        for session, expected_error in cases:
            with self.subTest(error=expected_error.__name__):
                with self.assertRaises(expected_error) as raised:
                    SchwabAccountDetailsTransport(session=session).fetch(
                        ACCESS_TOKEN,
                        ACCOUNT_HASH,
                    )
                rendered = str(raised.exception)
                self.assertNotIn(ACCESS_TOKEN, rendered)
                self.assertNotIn(ACCOUNT_HASH, rendered)


class SchwabAccountIdentityParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.discovered = DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH)

    def test_cash_identity_uses_only_type_suffix_and_balance_presence(self) -> None:
        identity = parse_account_identity(_account_payload(), self.discovered)
        report = build_validation_report(identity)
        rendered = json.dumps(report)

        self.assertEqual("CASH", identity.account_type)
        self.assertEqual(ACCOUNT_ENDING, identity.account_number_last_four)
        self.assertTrue(identity.balances_present)
        self.assertNotIn(ACCOUNT_NUMBER, repr(identity))
        self.assertNotIn(ACCOUNT_HASH, repr(identity))
        self.assertEqual("VERIFIED_CASH", report["cashOnlyState"])
        self.assertTrue(report["balanceValuesSuppressed"])
        self.assertNotIn(str(BALANCE_SENTINEL), rendered)
        self.assertNotIn(ACCOUNT_NUMBER, rendered)
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertFalse(report["positionsRequested"])
        self.assertFalse(report["positionsReceived"])
        self.assertEqual("NOT_BOUND", report["accountBinding"])
        self.assertEqual("NONE", report["persistence"])
        self.assertEqual("UNAVAILABLE", report["orderTransmission"])

    def test_margin_type_is_parsed_for_fail_closed_service_decision(self) -> None:
        identity = parse_account_identity(
            _account_payload(account_type="MARGIN"),
            self.discovered,
        )
        self.assertEqual("MARGIN", identity.account_type)

    def test_cash_identity_maps_to_internal_binding_type_without_persistence(self) -> None:
        identity = parse_account_identity(_account_payload(), self.discovered)
        candidate = build_unpersisted_binding_candidate(identity)

        self.assertEqual("INDIVIDUAL_CASH", candidate.account_type)
        self.assertEqual(ACCOUNT_ENDING, candidate.account_number_last_four)
        self.assertEqual(ACCOUNT_HASH, candidate.account_hash)
        self.assertNotIn(ACCOUNT_HASH, repr(candidate))

    def test_margin_identity_cannot_become_binding_candidate(self) -> None:
        identity = parse_account_identity(
            _account_payload(account_type="MARGIN"),
            self.discovered,
        )
        with self.assertRaisesRegex(SchwabAccountValidationError, "official Schwab CASH"):
            build_unpersisted_binding_candidate(identity)

    def test_invalid_shape_type_number_suffix_and_balance_fail(self) -> None:
        payloads = [
            [],
            {},
            {"securitiesAccount": []},
            _account_payload(account_type="UNKNOWN"),
            _account_payload(account_number=""),
            _account_payload(account_number="MASKED-ABCD"),
            _account_payload(account_number="99992574"),
            _account_payload(include_balances=False),
        ]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(
                SchwabAccountValidationResponseError
            ):
                parse_account_identity(payload, self.discovered)

    def test_nonempty_positions_fail_even_though_transport_omits_fields(self) -> None:
        with self.assertRaisesRegex(
            SchwabAccountValidationResponseError,
            "position data",
        ):
            parse_account_identity(
                _account_payload(positions=[{"symbol": "SYNTHETIC"}]),
                self.discovered,
            )

    def test_empty_positions_are_treated_as_no_position_data(self) -> None:
        identity = parse_account_identity(
            _account_payload(positions=[]),
            self.discovered,
        )
        self.assertEqual("CASH", identity.account_type)


class SchwabCashAccountValidationBoundaryTests(unittest.TestCase):
    def _build_validation(
        self,
        *,
        accounts: list[DiscoveredSchwabAccount] | None = None,
        payload: object | None = None,
        expired: bool = False,
    ) -> tuple[
        SchwabCashAccountValidation,
        _FakeSecrets,
        _FakeDiscoveryTransport,
        _FakeDetailsTransport,
    ]:
        secrets = _FakeSecrets(expired=expired)
        discovery = _FakeDiscoveryTransport(
            accounts
            if accounts is not None
            else [DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH)]
        )
        details = _FakeDetailsTransport(
            payload if payload is not None else _account_payload()
        )
        return (
            SchwabCashAccountValidation(
                secrets_repository=secrets,
                discovery_transport=discovery,
                details_transport=details,
            ),
            secrets,
            discovery,
            details,
        )

    def test_confirmation_and_expected_suffix_precede_secret_or_network_access(self) -> None:
        validation, secrets, discovery, details = self._build_validation()

        with self.assertRaisesRegex(SchwabAccountValidationError, "confirmation"):
            validation.validate(
                expected_account_ending=ACCOUNT_ENDING,
                confirmation="yes",
            )
        with self.assertRaisesRegex(SchwabAccountValidationError, "four digits"):
            validation.validate(
                expected_account_ending="25",
                confirmation=VALIDATION_CONFIRMATION,
            )

        self.assertEqual(0, secrets.load_count)
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_expired_token_fails_before_discovery_or_details(self) -> None:
        validation, _, discovery, details = self._build_validation(expired=True)
        with self.assertRaisesRegex(SchwabAccountValidationError, "expired"):
            validation.validate(
                expected_account_ending=ACCOUNT_ENDING,
                confirmation=VALIDATION_CONFIRMATION,
            )
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_zero_multiple_or_wrong_account_stops_before_details(self) -> None:
        cases = (
            [],
            [
                DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH),
                DiscoveredSchwabAccount("2574", "OTHER-HASH"),
            ],
            [DiscoveredSchwabAccount("2574", ACCOUNT_HASH)],
        )
        for accounts in cases:
            with self.subTest(accounts=accounts):
                validation, _, discovery, details = self._build_validation(
                    accounts=accounts
                )
                with self.assertRaises(SchwabAccountValidationError):
                    validation.validate(
                        expected_account_ending=ACCOUNT_ENDING,
                        confirmation=VALIDATION_CONFIRMATION,
                    )
                self.assertEqual([ACCESS_TOKEN], discovery.tokens)
                self.assertEqual([], details.calls)

    def test_margin_account_fails_and_never_produces_binding_report(self) -> None:
        validation, _, _, details = self._build_validation(
            payload=_account_payload(account_type="MARGIN")
        )
        with self.assertRaisesRegex(SchwabAccountValidationError, "not a CASH"):
            validation.validate(
                expected_account_ending=ACCOUNT_ENDING,
                confirmation=VALIDATION_CONFIRMATION,
            )
        self.assertEqual([(ACCESS_TOKEN, ACCOUNT_HASH)], details.calls)

    def test_cash_account_returns_redacted_nonpersisting_report(self) -> None:
        validation, _, discovery, details = self._build_validation()
        report = validation.validate(
            expected_account_ending=ACCOUNT_ENDING,
            confirmation=VALIDATION_CONFIRMATION,
        )
        rendered = json.dumps(report)

        self.assertEqual([ACCESS_TOKEN], discovery.tokens)
        self.assertEqual([(ACCESS_TOKEN, ACCOUNT_HASH)], details.calls)
        self.assertEqual("CASH", report["accountType"])
        self.assertEqual("INDIVIDUAL_CASH", report["bindingCandidateType"])
        self.assertEqual("VALIDATED_NOT_PERSISTED", report["bindingEligibility"])
        self.assertEqual(ACCOUNT_ENDING, report["accountEnding"])
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertNotIn(ACCOUNT_NUMBER, rendered)
        self.assertNotIn(str(BALANCE_SENTINEL), rendered)
        self.assertEqual("NOT_BOUND", report["accountBinding"])
        self.assertEqual("NONE", report["persistence"])

    def test_status_is_network_free_and_keeps_every_execution_gate_locked(self) -> None:
        validation, _, discovery, details = self._build_validation()
        status = validation.status()
        self.assertEqual(
            "LOCKED_EXACT_CONFIRMATION_REQUIRED",
            status["accountValidation"],
        )
        self.assertEqual("NOT_BOUND", status["accountBinding"])
        self.assertEqual("NONE", status["persistence"])
        self.assertFalse(status["positionsRequested"])
        self.assertEqual("UNAVAILABLE", status["orderTransmission"])
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_module_is_get_only_and_has_no_binding_or_order_capability(self) -> None:
        import momentum_hunter.schwab_account_validation as module

        source = inspect.getsource(module)
        self.assertEqual(1, source.count("https://api.schwabapi.com/"))
        self.assertIn("/trader/v1/accounts", source)
        self.assertNotIn("/orders", source)
        self.assertNotIn("/marketdata", source)
        self.assertNotIn("save_new(", source)
        self.assertNotIn("save_tokens(", source)
        for method in ("post(", "put(", "patch(", "delete("):
            self.assertNotIn(f".{method}", source.lower())

    def test_cli_accepts_no_token_account_hash_endpoint_or_fields_arguments(self) -> None:
        for value in (
            "--access-token",
            "--account-number",
            "--account-hash",
            "--endpoint",
            "--fields",
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
            self.assertNotIn("SENSITIVE", stdout.getvalue() + stderr.getvalue())

    def test_cli_validation_output_suppresses_hash_number_and_balances(self) -> None:
        report = build_validation_report(
            SchwabAccountIdentity(
                account_number_last_four=ACCOUNT_ENDING,
                account_hash=ACCOUNT_HASH,
                account_type="CASH",
                balances_present=True,
            )
        )
        stdout = io.StringIO()
        with (
            patch(
                "momentum_hunter.schwab_account_validation.SchwabCashAccountValidation.validate",
                return_value=report,
            ),
            patch("getpass.getpass", return_value=ACCOUNT_ENDING),
            patch("builtins.input", return_value=VALIDATION_CONFIRMATION),
            redirect_stdout(stdout),
        ):
            self.assertEqual(0, main(["validate"]))
        rendered = stdout.getvalue()
        self.assertIn(ACCOUNT_ENDING, rendered)
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertNotIn(ACCOUNT_NUMBER, rendered)
        self.assertNotIn(str(BALANCE_SENTINEL), rendered)


if __name__ == "__main__":
    unittest.main()
