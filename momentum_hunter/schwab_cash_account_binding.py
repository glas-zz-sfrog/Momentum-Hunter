from __future__ import annotations

"""Persist one Schwab CASH account only after exact live revalidation."""

import argparse
import getpass
import json
import sys

from momentum_hunter.schwab_account_discovery import SchwabAccountNumbersTransport
from momentum_hunter.schwab_account_validation import (
    SchwabAccountDetailsTransport,
    SchwabAccountValidationError,
    build_unpersisted_binding_candidate,
    normalize_expected_account_ending,
    parse_account_identity,
    require_single_expected_account,
)
from momentum_hunter.schwab_onboarding import (
    EncryptedSchwabAccountBindingStore,
    SchwabOAuthError,
    SchwabOAuthSecretRepository,
)
from momentum_hunter.schwab_readonly import AccountIsolationError, redact_value


BINDING_CONFIRMATION = "PIN SCHWAB CASH ACCOUNT"


class SchwabCashAccountBindingError(RuntimeError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


class SchwabCashAccountBinder:
    """Exact-confirmation binder with no replacement or order capability."""

    def __init__(
        self,
        *,
        secrets_repository: SchwabOAuthSecretRepository | None = None,
        binding_store: EncryptedSchwabAccountBindingStore | None = None,
        discovery_transport: SchwabAccountNumbersTransport | None = None,
        details_transport: SchwabAccountDetailsTransport | None = None,
    ) -> None:
        self.secrets = secrets_repository or SchwabOAuthSecretRepository()
        self.bindings = binding_store or EncryptedSchwabAccountBindingStore()
        self.discovery_transport = (
            discovery_transport or SchwabAccountNumbersTransport()
        )
        self.details_transport = details_transport or SchwabAccountDetailsTransport()

    def bind(
        self,
        *,
        expected_account_ending: str,
        confirmation: str,
    ) -> dict[str, object]:
        if confirmation != BINDING_CONFIRMATION:
            raise SchwabCashAccountBindingError(
                "Persisting the Schwab CASH binding requires the exact confirmation phrase."
            )
        expected_ending = normalize_expected_account_ending(expected_account_ending)
        if self.bindings.exists:
            raise AccountIsolationError(
                "A Schwab canary account is already bound; replacement is forbidden."
            )
        tokens = self.secrets.load_tokens()
        if tokens.expired:
            raise SchwabCashAccountBindingError(
                "The Schwab OAuth access token expired; refresh it before binding."
            )
        accounts = self.discovery_transport.discover(tokens.access_token)
        discovered = require_single_expected_account(accounts, expected_ending)
        payload = self.details_transport.fetch(
            tokens.access_token,
            discovered.account_hash,
        )
        identity = parse_account_identity(payload, discovered)
        candidate = build_unpersisted_binding_candidate(identity)
        self.bindings.save_new(candidate)
        return {
            "mode": "SCHWAB_CASH_ACCOUNT_BINDING",
            "accountEnding": candidate.account_number_last_four,
            "accountHash": redact_value(candidate.account_hash),
            "accountType": candidate.account_type,
            "cashOnlyState": "VERIFIED_CASH",
            "identityMatch": True,
            "accountBinding": "PINNED",
            "persistence": "ENCRYPTED_DPAPI_IMMUTABLE",
            "positionsRequested": False,
            "positionsReceived": False,
            "balanceValuesSuppressed": True,
            "marketDataRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def status(self) -> dict[str, object]:
        auth_status = self.secrets.status()
        if not self.bindings.exists:
            account_ending = ""
            binding_state = "NOT_BOUND"
            persistence = "NONE"
        else:
            binding = self.bindings.load()
            account_ending = binding.account_number_last_four
            binding_state = "PINNED"
            persistence = "ENCRYPTED_DPAPI_IMMUTABLE"
        return {
            "credentialsStored": auth_status["credentialsStored"],
            "oauthAuthorized": auth_status["oauthAuthorized"],
            "tokenState": auth_status["tokenState"],
            "accountBinding": binding_state,
            "accountEnding": account_ending,
            "persistence": persistence,
            "bindingAction": "LOCKED_EXACT_CONFIRMATION_REQUIRED",
            "positionsRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }


def main(argv: list[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Persist one immutable Schwab CASH account binding."
    )
    parser.add_argument("command", choices=("status", "bind"))
    args = parser.parse_args(argv)
    binder = SchwabCashAccountBinder()
    try:
        if args.command == "bind":
            expected_ending = getpass.getpass(
                "Enter the intended canary account's final four digits: "
            )
            confirmation = input(
                f"Type {BINDING_CONFIRMATION!r} to persist the immutable CASH binding: "
            )
            report = binder.bind(
                expected_account_ending=expected_ending,
                confirmation=confirmation,
            )
        else:
            report = binder.status()
    except (
        AccountIsolationError,
        SchwabAccountBindingError,
        SchwabAccountValidationError,
        SchwabOAuthError,
    ) as exc:
        print(f"Schwab CASH account binding stopped safely: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
