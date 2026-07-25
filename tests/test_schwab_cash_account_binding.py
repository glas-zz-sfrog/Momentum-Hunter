from __future__ import annotations

import inspect
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from momentum_hunter.schwab_account_discovery import DiscoveredSchwabAccount
from momentum_hunter.schwab_cash_account_binding import (
    BINDING_CONFIRMATION,
    SchwabCashAccountBinder,
    SchwabCashAccountBindingError,
    main,
)
from momentum_hunter.schwab_account_validation import SchwabAccountValidationError
from momentum_hunter.schwab_onboarding import SchwabOAuthTokens
from momentum_hunter.schwab_readonly import AccountIsolationError, SchwabAccountBinding


ACCOUNT_ENDING = "2573"
ACCOUNT_HASH = "SYNTHETIC-BINDING-ACCOUNT-HASH"
ACCOUNT_NUMBER = "12342573"
ACCESS_TOKEN = "SYNTHETIC-BINDING-ACCESS"
BALANCE_SENTINEL = 765432.19


def _account_payload(
    *,
    account_type: str = "CASH",
    account_number: str = ACCOUNT_NUMBER,
    positions: object = None,
) -> dict[str, object]:
    account: dict[str, object] = {
        "type": account_type,
        "accountNumber": account_number,
        "currentBalances": {"cashAvailableForTrading": BALANCE_SENTINEL},
    }
    if positions is not None:
        account["positions"] = positions
    return {"securitiesAccount": account}


class _FakeSecrets:
    def __init__(self, *, expired: bool = False) -> None:
        now = datetime.now(timezone.utc)
        self.tokens = SchwabOAuthTokens(
            access_token=ACCESS_TOKEN,
            refresh_token="SYNTHETIC-BINDING-REFRESH",
            token_type="Bearer",
            scope="synthetic",
            issued_at=now - timedelta(minutes=31 if expired else 1),
            expires_at=now - timedelta(minutes=1) if expired else now + timedelta(minutes=29),
        )
        self.load_count = 0

    def load_tokens(self) -> SchwabOAuthTokens:
        self.load_count += 1
        return self.tokens

    def status(self) -> dict[str, object]:
        return {
            "credentialsStored": True,
            "oauthAuthorized": True,
            "tokenState": "EXPIRED" if self.tokens.expired else "ACTIVE",
        }


class _FakeBindingStore:
    def __init__(
        self,
        *,
        existing: SchwabAccountBinding | None = None,
        error: Exception | None = None,
    ) -> None:
        self.binding = existing
        self.error = error
        self.saved: list[SchwabAccountBinding] = []
        self.load_count = 0

    @property
    def exists(self) -> bool:
        return self.binding is not None

    def save_new(self, binding: SchwabAccountBinding) -> object:
        if self.error is not None:
            raise self.error
        if self.binding is not None:
            raise AccountIsolationError("replacement forbidden")
        self.saved.append(binding)
        self.binding = binding
        return object()

    def load(self) -> SchwabAccountBinding:
        self.load_count += 1
        if self.binding is None:
            raise AccountIsolationError("No binding")
        return self.binding


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


class SchwabCashAccountBinderTests(unittest.TestCase):
    def _build(
        self,
        *,
        expired: bool = False,
        existing: SchwabAccountBinding | None = None,
        binding_error: Exception | None = None,
        accounts: list[DiscoveredSchwabAccount] | None = None,
        payload: object | None = None,
    ) -> tuple[
        SchwabCashAccountBinder,
        _FakeSecrets,
        _FakeBindingStore,
        _FakeDiscoveryTransport,
        _FakeDetailsTransport,
    ]:
        secrets = _FakeSecrets(expired=expired)
        bindings = _FakeBindingStore(existing=existing, error=binding_error)
        discovery = _FakeDiscoveryTransport(
            accounts
            if accounts is not None
            else [DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH)]
        )
        details = _FakeDetailsTransport(
            payload if payload is not None else _account_payload()
        )
        return (
            SchwabCashAccountBinder(
                secrets_repository=secrets,
                binding_store=bindings,
                discovery_transport=discovery,
                details_transport=details,
            ),
            secrets,
            bindings,
            discovery,
            details,
        )

    def test_confirmation_and_suffix_validation_precede_secret_or_network_access(self) -> None:
        binder, secrets, bindings, discovery, details = self._build()
        with self.assertRaisesRegex(
            SchwabCashAccountBindingError,
            "exact confirmation",
        ):
            binder.bind(
                expected_account_ending=ACCOUNT_ENDING,
                confirmation="yes",
            )
        with self.assertRaisesRegex(SchwabAccountValidationError, "four digits"):
            binder.bind(
                expected_account_ending="25",
                confirmation=BINDING_CONFIRMATION,
            )
        self.assertEqual(0, secrets.load_count)
        self.assertEqual([], bindings.saved)
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_existing_binding_stops_before_secret_or_network_access(self) -> None:
        existing = SchwabAccountBinding(
            ACCOUNT_HASH,
            ACCOUNT_ENDING,
            "INDIVIDUAL_CASH",
        )
        binder, secrets, bindings, discovery, details = self._build(
            existing=existing
        )
        with self.assertRaisesRegex(AccountIsolationError, "replacement"):
            binder.bind(
                expected_account_ending=ACCOUNT_ENDING,
                confirmation=BINDING_CONFIRMATION,
            )
        self.assertEqual(0, secrets.load_count)
        self.assertEqual([], bindings.saved)
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_expired_token_stops_before_account_requests_or_persistence(self) -> None:
        binder, secrets, bindings, discovery, details = self._build(expired=True)
        with self.assertRaisesRegex(SchwabCashAccountBindingError, "expired"):
            binder.bind(
                expected_account_ending=ACCOUNT_ENDING,
                confirmation=BINDING_CONFIRMATION,
            )
        self.assertEqual(1, secrets.load_count)
        self.assertEqual([], bindings.saved)
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_count_suffix_or_hash_detail_mismatch_never_persists(self) -> None:
        cases = (
            ([], None),
            (
                [
                    DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH),
                    DiscoveredSchwabAccount("2574", "OTHER-HASH"),
                ],
                None,
            ),
            ([DiscoveredSchwabAccount("2574", ACCOUNT_HASH)], None),
            (
                [DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH)],
                _account_payload(account_number="12342574"),
            ),
        )
        for accounts, payload in cases:
            with self.subTest(accounts=accounts, payload=payload):
                binder, _, bindings, _, _ = self._build(
                    accounts=accounts,
                    payload=payload,
                )
                with self.assertRaises(
                    (AccountIsolationError, SchwabAccountValidationError)
                ):
                    binder.bind(
                        expected_account_ending=ACCOUNT_ENDING,
                        confirmation=BINDING_CONFIRMATION,
                    )
                self.assertEqual([], bindings.saved)

    def test_margin_or_returned_position_data_never_persists(self) -> None:
        for payload in (
            _account_payload(account_type="MARGIN"),
            _account_payload(positions=[{"symbol": "SYNTHETIC"}]),
        ):
            with self.subTest(payload=payload):
                binder, _, bindings, _, _ = self._build(payload=payload)
                with self.assertRaises(SchwabAccountValidationError):
                    binder.bind(
                        expected_account_ending=ACCOUNT_ENDING,
                        confirmation=BINDING_CONFIRMATION,
                    )
                self.assertEqual([], bindings.saved)

    def test_success_persists_once_only_after_live_identity_revalidation(self) -> None:
        binder, _, bindings, discovery, details = self._build()
        report = binder.bind(
            expected_account_ending=ACCOUNT_ENDING,
            confirmation=BINDING_CONFIRMATION,
        )
        rendered = json.dumps(report)

        self.assertEqual([ACCESS_TOKEN], discovery.tokens)
        self.assertEqual([(ACCESS_TOKEN, ACCOUNT_HASH)], details.calls)
        self.assertEqual(1, len(bindings.saved))
        self.assertEqual("INDIVIDUAL_CASH", bindings.saved[0].account_type)
        self.assertEqual("PINNED", report["accountBinding"])
        self.assertEqual("ENCRYPTED_DPAPI_IMMUTABLE", report["persistence"])
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertNotIn(ACCOUNT_NUMBER, rendered)
        self.assertNotIn(str(BALANCE_SENTINEL), rendered)
        self.assertFalse(report["positionsRequested"])
        self.assertEqual("UNAVAILABLE", report["orderTransmission"])

    def test_store_failure_does_not_report_a_successful_binding(self) -> None:
        binder, _, bindings, _, _ = self._build(
            binding_error=AccountIsolationError("synthetic store failure")
        )
        with self.assertRaisesRegex(AccountIsolationError, "store failure"):
            binder.bind(
                expected_account_ending=ACCOUNT_ENDING,
                confirmation=BINDING_CONFIRMATION,
            )
        self.assertEqual([], bindings.saved)

    def test_status_is_network_free_and_reports_unbound_or_pinned(self) -> None:
        binder, _, bindings, discovery, details = self._build()
        status = binder.status()
        self.assertEqual("NOT_BOUND", status["accountBinding"])
        self.assertEqual("NONE", status["persistence"])
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

        bindings.binding = SchwabAccountBinding(
            ACCOUNT_HASH,
            ACCOUNT_ENDING,
            "INDIVIDUAL_CASH",
        )
        status = binder.status()
        self.assertEqual("PINNED", status["accountBinding"])
        self.assertEqual(ACCOUNT_ENDING, status["accountEnding"])
        self.assertEqual("ENCRYPTED_DPAPI_IMMUTABLE", status["persistence"])

    def test_module_has_no_replace_delete_order_or_market_data_capability(self) -> None:
        import momentum_hunter.schwab_cash_account_binding as module

        source = inspect.getsource(module)
        self.assertNotIn("/orders", source)
        self.assertNotIn("/marketdata", source)
        for method in ("post(", "put(", "patch(", "delete("):
            self.assertNotIn(f".{method}", source.lower())

    def test_cli_accepts_no_token_hash_endpoint_or_binding_arguments(self) -> None:
        for value in (
            "--access-token",
            "--account-hash",
            "--endpoint",
            "--binding",
            "--replace",
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

    def test_cli_binding_output_remains_redacted(self) -> None:
        report = {
            "accountEnding": ACCOUNT_ENDING,
            "accountHash": "*" * (len(ACCOUNT_HASH) - 4) + ACCOUNT_HASH[-4:],
            "accountBinding": "PINNED",
            "orderTransmission": "UNAVAILABLE",
        }
        stdout = io.StringIO()
        with (
            patch(
                "momentum_hunter.schwab_cash_account_binding.SchwabCashAccountBinder.bind",
                return_value=report,
            ),
            patch("getpass.getpass", return_value=ACCOUNT_ENDING),
            patch("builtins.input", return_value=BINDING_CONFIRMATION),
            redirect_stdout(stdout),
        ):
            self.assertEqual(0, main(["bind"]))
        rendered = stdout.getvalue()
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertIn(ACCOUNT_ENDING, rendered)


if __name__ == "__main__":
    unittest.main()
