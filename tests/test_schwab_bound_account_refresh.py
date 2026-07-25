from __future__ import annotations

import inspect
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from momentum_hunter.schwab_account_discovery import DiscoveredSchwabAccount
from momentum_hunter.schwab_bound_account_refresh import (
    BOUND_REFRESH_CONFIRMATION,
    SchwabBoundAccountRefresh,
    SchwabBoundAccountRefreshError,
    main,
)
from momentum_hunter.schwab_account_validation import SchwabAccountValidationError
from momentum_hunter.schwab_onboarding import (
    SchwabApplicationCredentials,
    SchwabOAuthTokens,
)
from momentum_hunter.schwab_readonly import AccountIsolationError, SchwabAccountBinding


ACCOUNT_ENDING = "2573"
ACCOUNT_HASH = "SYNTHETIC-BOUND-ACCOUNT-HASH"
ACCOUNT_NUMBER = "12342573"
OLD_ACCESS_TOKEN = "SYNTHETIC-OLD-ACCESS"
NEW_ACCESS_TOKEN = "SYNTHETIC-NEW-ACCESS"
OLD_REFRESH_TOKEN = "SYNTHETIC-OLD-REFRESH"
NEW_REFRESH_TOKEN = "SYNTHETIC-NEW-REFRESH"
BALANCE_SENTINEL = 345678.91


def _tokens(
    access_token: str,
    refresh_token: str,
    *,
    expired: bool,
) -> SchwabOAuthTokens:
    now = datetime.now(timezone.utc)
    return SchwabOAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        scope="synthetic",
        issued_at=now - timedelta(minutes=31 if expired else 1),
        expires_at=now - timedelta(minutes=1) if expired else now + timedelta(minutes=29),
    )


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
    def __init__(self) -> None:
        self.credentials = SchwabApplicationCredentials(
            "SYNTHETIC-APP-ID",
            "SYNTHETIC-APP-SECRET",
        )
        self.current_tokens = _tokens(
            OLD_ACCESS_TOKEN,
            OLD_REFRESH_TOKEN,
            expired=True,
        )
        self.saved_tokens: list[SchwabOAuthTokens] = []
        self.events: list[str] = []

    def load_credentials(self) -> SchwabApplicationCredentials:
        self.events.append("load-credentials")
        return self.credentials

    def load_tokens(self) -> SchwabOAuthTokens:
        self.events.append("load-tokens")
        return self.current_tokens

    def save_tokens(self, tokens: SchwabOAuthTokens) -> object:
        self.events.append("save-tokens")
        self.saved_tokens.append(tokens)
        self.current_tokens = tokens
        return object()

    def status(self) -> dict[str, object]:
        return {
            "credentialsStored": True,
            "oauthAuthorized": True,
            "tokenState": "EXPIRED" if self.current_tokens.expired else "ACTIVE",
        }


class _FakeBindingStore:
    def __init__(self, binding: SchwabAccountBinding | None) -> None:
        self.binding = binding
        self.load_count = 0

    @property
    def exists(self) -> bool:
        return self.binding is not None

    def load(self) -> SchwabAccountBinding:
        self.load_count += 1
        if self.binding is None:
            raise AccountIsolationError("No Schwab canary account is bound.")
        return self.binding


class _FakeOAuthTransport:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[
            tuple[SchwabApplicationCredentials, SchwabOAuthTokens]
        ] = []
        self.refreshed_tokens = _tokens(
            NEW_ACCESS_TOKEN,
            NEW_REFRESH_TOKEN,
            expired=False,
        )

    def refresh(
        self,
        credentials: SchwabApplicationCredentials,
        current_tokens: SchwabOAuthTokens,
    ) -> SchwabOAuthTokens:
        self.calls.append((credentials, current_tokens))
        if self.error is not None:
            raise self.error
        return self.refreshed_tokens


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


class SchwabBoundAccountRefreshTests(unittest.TestCase):
    def _build(
        self,
        *,
        binding: SchwabAccountBinding | None = None,
        accounts: list[DiscoveredSchwabAccount] | None = None,
        payload: object | None = None,
        oauth_error: Exception | None = None,
    ) -> tuple[
        SchwabBoundAccountRefresh,
        _FakeSecrets,
        _FakeBindingStore,
        _FakeOAuthTransport,
        _FakeDiscoveryTransport,
        _FakeDetailsTransport,
    ]:
        expected_binding = (
            binding
            if binding is not None
            else SchwabAccountBinding(
                account_hash=ACCOUNT_HASH,
                account_number_last_four=ACCOUNT_ENDING,
                account_type="INDIVIDUAL_CASH",
            )
        )
        secrets = _FakeSecrets()
        bindings = _FakeBindingStore(expected_binding)
        oauth = _FakeOAuthTransport(error=oauth_error)
        discovery = _FakeDiscoveryTransport(
            accounts
            if accounts is not None
            else [DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH)]
        )
        details = _FakeDetailsTransport(
            payload if payload is not None else _account_payload()
        )
        return (
            SchwabBoundAccountRefresh(
                secrets_repository=secrets,
                binding_store=bindings,
                oauth_transport=oauth,
                discovery_transport=discovery,
                details_transport=details,
            ),
            secrets,
            bindings,
            oauth,
            discovery,
            details,
        )

    def test_exact_confirmation_precedes_binding_or_secret_access(self) -> None:
        refresh, secrets, bindings, oauth, discovery, details = self._build()
        with self.assertRaisesRegex(
            SchwabBoundAccountRefreshError,
            "exact confirmation",
        ):
            refresh.refresh(confirmation="yes")
        self.assertEqual(0, bindings.load_count)
        self.assertEqual([], secrets.events)
        self.assertEqual([], oauth.calls)
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_missing_binding_stops_before_credentials_or_remote_calls(self) -> None:
        refresh, secrets, bindings, oauth, discovery, details = self._build(
            binding=SchwabAccountBinding("", "0000", "INDIVIDUAL_CASH")
        )
        bindings.binding = None
        with self.assertRaisesRegex(AccountIsolationError, "No Schwab canary"):
            refresh.refresh(confirmation=BOUND_REFRESH_CONFIRMATION)
        self.assertEqual(1, bindings.load_count)
        self.assertEqual([], secrets.events)
        self.assertEqual([], oauth.calls)
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_refresh_revalidates_exact_binding_before_saving_rotated_tokens(self) -> None:
        refresh, secrets, _, oauth, discovery, details = self._build()
        report = refresh.refresh(confirmation=BOUND_REFRESH_CONFIRMATION)
        rendered = json.dumps(report)

        self.assertEqual(1, len(oauth.calls))
        self.assertEqual([NEW_ACCESS_TOKEN], discovery.tokens)
        self.assertEqual([(NEW_ACCESS_TOKEN, ACCOUNT_HASH)], details.calls)
        self.assertEqual([oauth.refreshed_tokens], secrets.saved_tokens)
        self.assertEqual(
            ["load-credentials", "load-tokens", "save-tokens"],
            secrets.events,
        )
        self.assertEqual("PINNED_UNCHANGED", report["accountBinding"])
        self.assertTrue(report["bindingRevalidated"])
        self.assertEqual("INDIVIDUAL_CASH", report["accountType"])
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertNotIn(ACCOUNT_NUMBER, rendered)
        self.assertNotIn(str(BALANCE_SENTINEL), rendered)
        self.assertFalse(report["positionsRequested"])
        self.assertEqual("UNAVAILABLE", report["orderTransmission"])

    def test_oauth_failure_stops_before_account_calls_or_token_save(self) -> None:
        refresh, secrets, _, _, discovery, details = self._build(
            oauth_error=RuntimeError("synthetic refresh failure")
        )
        with self.assertRaisesRegex(RuntimeError, "synthetic refresh"):
            refresh.refresh(confirmation=BOUND_REFRESH_CONFIRMATION)
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)
        self.assertEqual([], secrets.saved_tokens)

    def test_account_count_suffix_or_hash_change_discards_refreshed_tokens(self) -> None:
        account_sets = (
            [],
            [
                DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH),
                DiscoveredSchwabAccount("2574", "OTHER-HASH"),
            ],
            [DiscoveredSchwabAccount("2574", ACCOUNT_HASH)],
            [DiscoveredSchwabAccount(ACCOUNT_ENDING, "OTHER-HASH")],
        )
        for accounts in account_sets:
            with self.subTest(accounts=accounts):
                refresh, secrets, _, _, discovery, details = self._build(
                    accounts=accounts
                )
                with self.assertRaises(AccountIsolationError):
                    refresh.refresh(confirmation=BOUND_REFRESH_CONFIRMATION)
                self.assertEqual([NEW_ACCESS_TOKEN], discovery.tokens)
                self.assertEqual([], details.calls)
                self.assertEqual([], secrets.saved_tokens)

    def test_margin_position_or_detail_identity_change_discards_tokens(self) -> None:
        payloads = (
            _account_payload(account_type="MARGIN"),
            _account_payload(positions=[{"symbol": "SYNTHETIC"}]),
            _account_payload(account_number="12342574"),
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                refresh, secrets, _, _, _, details = self._build(payload=payload)
                with self.assertRaises(
                    (AccountIsolationError, SchwabAccountValidationError)
                ):
                    refresh.refresh(confirmation=BOUND_REFRESH_CONFIRMATION)
                self.assertEqual(
                    [(NEW_ACCESS_TOKEN, ACCOUNT_HASH)],
                    details.calls,
                )
                self.assertEqual([], secrets.saved_tokens)

    def test_status_is_network_free_redacted_and_reports_binding_state(self) -> None:
        refresh, _, bindings, oauth, discovery, details = self._build()
        status = refresh.status()
        self.assertEqual("PINNED", status["accountBinding"])
        self.assertEqual(ACCOUNT_ENDING, status["accountEnding"])
        self.assertEqual("UNAVAILABLE", status["orderTransmission"])
        self.assertEqual(1, bindings.load_count)
        self.assertEqual([], oauth.calls)
        self.assertEqual([], discovery.tokens)
        self.assertEqual([], details.calls)

    def test_module_has_no_order_market_data_or_binding_mutation(self) -> None:
        import momentum_hunter.schwab_bound_account_refresh as module

        source = inspect.getsource(module)
        self.assertNotIn("/orders", source)
        self.assertNotIn("/marketdata", source)
        self.assertNotIn("save_new(", source)
        for method in ("post(", "put(", "patch(", "delete("):
            self.assertNotIn(f".{method}", source.lower())

    def test_cli_accepts_no_token_hash_endpoint_or_binding_arguments(self) -> None:
        for value in (
            "--access-token",
            "--refresh-token",
            "--account-hash",
            "--endpoint",
            "--binding",
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

    def test_cli_refresh_output_remains_redacted(self) -> None:
        report = {
            "accountEnding": ACCOUNT_ENDING,
            "accountHash": "*" * (len(ACCOUNT_HASH) - 4) + ACCOUNT_HASH[-4:],
            "accountBinding": "PINNED_UNCHANGED",
            "orderTransmission": "UNAVAILABLE",
        }
        stdout = io.StringIO()
        with (
            patch(
                "momentum_hunter.schwab_bound_account_refresh.SchwabBoundAccountRefresh.refresh",
                return_value=report,
            ),
            patch("builtins.input", return_value=BOUND_REFRESH_CONFIRMATION),
            redirect_stdout(stdout),
        ):
            self.assertEqual(0, main(["refresh"]))
        rendered = stdout.getvalue()
        self.assertNotIn(ACCOUNT_HASH, rendered)
        self.assertIn(ACCOUNT_ENDING, rendered)


if __name__ == "__main__":
    unittest.main()
