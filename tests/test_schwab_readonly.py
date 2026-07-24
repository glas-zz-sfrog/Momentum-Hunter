from __future__ import annotations

import unittest
from dataclasses import replace

from momentum_hunter.schwab_emulator import (
    SYNTHETIC_ACCOUNT_HASH,
    SYNTHETIC_ACCOUNT_LAST_FOUR,
    SyntheticSchwabOAuthEmulator,
    SyntheticSchwabError,
    synthetic_source,
)
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    AccountIsolationPolicy,
    ReadOnlyEndpointAllowlist,
    ReadOnlyOperationError,
    SchwabReadOnlyAdapter,
    redact_mapping,
)


class SchwabAccountIsolationTests(unittest.TestCase):
    def test_exactly_one_cash_account_can_be_bound_and_read(self) -> None:
        source = synthetic_source()
        binding = AccountIsolationPolicy().create_binding(
            source.list_authorized_accounts(),
            manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR,
        )
        adapter = SchwabReadOnlyAdapter(source=source, binding=binding)

        self.assertEqual(SYNTHETIC_ACCOUNT_HASH, binding.account_hash)
        self.assertEqual(100.0, adapter.get_balances().cash_available)
        self.assertEqual(4, len(adapter.list_orders()))
        self.assertEqual("WORKING", adapter.get_order_status("SYNTHETIC-ORDER-0001").status)
        status = adapter.redacted_status()
        self.assertEqual("SCHWAB_READ_ONLY", status["mode"])
        self.assertEqual(SYNTHETIC_ACCOUNT_LAST_FOUR, status["accountEnding"])
        self.assertEqual("UNAVAILABLE", status["orderTransmission"])
        self.assertNotIn(SYNTHETIC_ACCOUNT_HASH, str(status))

    def test_zero_or_multiple_accounts_fail_closed(self) -> None:
        for count in (0, 2):
            with self.subTest(count=count), self.assertRaisesRegex(AccountIsolationError, "Exactly one"):
                AccountIsolationPolicy().create_binding(
                    synthetic_source(account_count=count).list_authorized_accounts(),
                    manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR,
                )

    def test_wrong_last_four_unexpected_type_and_margin_fail_closed(self) -> None:
        cases = [
            (synthetic_source(), "9999", "does not match"),
            (synthetic_source(account_type="MARGIN"), SYNTHETIC_ACCOUNT_LAST_FOUR, "Expected"),
            (synthetic_source(cash_only=False), SYNTHETIC_ACCOUNT_LAST_FOUR, "cash-only"),
        ]
        for source, last_four, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(AccountIsolationError, message):
                AccountIsolationPolicy().create_binding(
                    source.list_authorized_accounts(),
                    manually_confirmed_last_four=last_four,
                )

    def test_changed_hash_and_additional_account_lock_every_read(self) -> None:
        source = synthetic_source()
        policy = AccountIsolationPolicy()
        binding = policy.create_binding(source.list_authorized_accounts(), manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR)
        source.changed_account_hash_after_calls = source.calls
        adapter = SchwabReadOnlyAdapter(source=source, binding=binding)
        with self.assertRaisesRegex(AccountIsolationError, "hash changed"):
            adapter.get_balances()

        extra_source = synthetic_source()
        extra_binding = policy.create_binding(
            extra_source.list_authorized_accounts(),
            manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR,
        )
        extra_source.accounts = synthetic_source(account_count=2).accounts
        with self.assertRaisesRegex(AccountIsolationError, "exactly one"):
            SchwabReadOnlyAdapter(source=extra_source, binding=extra_binding).get_positions()

    def test_returned_account_details_must_still_match_the_pinned_cash_account(self) -> None:
        source = synthetic_source()
        policy = AccountIsolationPolicy()
        binding = policy.create_binding(
            source.list_authorized_accounts(),
            manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR,
        )
        original_get_account = source.get_account
        source.get_account = lambda account_hash: replace(original_get_account(account_hash), cash_only=False)
        with self.assertRaisesRegex(AccountIsolationError, "not cash-only"):
            SchwabReadOnlyAdapter(source=source, binding=binding).get_account()

    def test_adapter_is_physically_read_only_and_allowlist_rejects_write_methods(self) -> None:
        source = synthetic_source()
        binding = AccountIsolationPolicy().create_binding(
            source.list_authorized_accounts(),
            manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR,
        )
        adapter = SchwabReadOnlyAdapter(source=source, binding=binding)
        for method in ("submit_order", "replace_order", "cancel_order", "transfer_money", "withdraw"):
            self.assertFalse(hasattr(adapter, method), method)

        policy = ReadOnlyEndpointAllowlist()
        policy.require("GET", "get_balances")
        with self.assertRaises(ReadOnlyOperationError):
            policy.require("POST", "get_balances")
        with self.assertRaises(ReadOnlyOperationError):
            policy.require("GET", "submit_order")

    def test_synthetic_auth_rate_limit_timeout_and_malformed_scenarios_are_offline_failures(self) -> None:
        for failure in ("unauthorized", "rate_limit", "timeout", "malformed"):
            source = synthetic_source(failure=failure)
            with self.subTest(failure=failure), self.assertRaises(SyntheticSchwabError):
                source.list_authorized_accounts()

    def test_synthetic_oauth_code_expiration_and_rotating_refresh_are_deterministic(self) -> None:
        from datetime import datetime, timedelta, timezone

        observed_at = datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc)
        emulator = SyntheticSchwabOAuthEmulator(token_lifetime_seconds=60)
        code = emulator.create_authorization_code(state="synthetic-state")
        token = emulator.exchange_code(code, expected_state="synthetic-state", observed_at=observed_at)
        self.assertFalse(token.expired(observed_at=observed_at + timedelta(seconds=59)))
        self.assertTrue(token.expired(observed_at=observed_at + timedelta(seconds=60)))

        refreshed = emulator.refresh(token.refresh_token, observed_at=observed_at + timedelta(seconds=60))
        self.assertNotEqual(token.access_token, refreshed.access_token)
        self.assertNotEqual(token.refresh_token, refreshed.refresh_token)
        with self.assertRaisesRegex(SyntheticSchwabError, "invalid"):
            emulator.refresh(token.refresh_token, observed_at=observed_at + timedelta(seconds=61))

    def test_redaction_hides_secret_risk_values(self) -> None:
        payload = redact_mapping(
            {
                "account_hash": SYNTHETIC_ACCOUNT_HASH,
                "access_token": "SYNTHETIC-TOKEN-VALUE",
                "status": "READ_ONLY",
            }
        )
        rendered = str(payload)
        self.assertNotIn(SYNTHETIC_ACCOUNT_HASH, rendered)
        self.assertNotIn("SYNTHETIC-TOKEN-VALUE", rendered)
        self.assertIn("READ_ONLY", rendered)
