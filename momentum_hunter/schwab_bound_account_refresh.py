from __future__ import annotations

"""Refresh Schwab OAuth only when the immutable CASH binding revalidates."""

import argparse
import json
import sys

from momentum_hunter.schwab_account_discovery import SchwabAccountNumbersTransport
from momentum_hunter.schwab_account_validation import (
    SchwabAccountDetailsTransport,
    SchwabAccountValidationError,
    build_unpersisted_binding_candidate,
    parse_account_identity,
)
from momentum_hunter.schwab_onboarding import (
    EncryptedSchwabAccountBindingStore,
    SchwabOAuthError,
    SchwabOAuthSecretRepository,
    SchwabOAuthTransport,
)
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    SchwabAccountBinding,
    redact_value,
)
from momentum_hunter.schwab_setup import SchwabSetupError


BOUND_REFRESH_CONFIRMATION = "REFRESH AND REVALIDATE SCHWAB CASH ACCOUNT"


class SchwabBoundAccountRefreshError(RuntimeError):
    pass


class SchwabBoundAccountRefreshPersistenceError(SchwabBoundAccountRefreshError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


class SchwabBoundAccountRefresh:
    """Keep refreshed tokens only after the pinned account passes exact revalidation."""

    def __init__(
        self,
        *,
        secrets_repository: SchwabOAuthSecretRepository | None = None,
        binding_store: EncryptedSchwabAccountBindingStore | None = None,
        oauth_transport: SchwabOAuthTransport | None = None,
        discovery_transport: SchwabAccountNumbersTransport | None = None,
        details_transport: SchwabAccountDetailsTransport | None = None,
    ) -> None:
        self.secrets = secrets_repository or SchwabOAuthSecretRepository()
        self.bindings = binding_store or EncryptedSchwabAccountBindingStore()
        self.oauth_transport = oauth_transport or SchwabOAuthTransport()
        self.discovery_transport = (
            discovery_transport or SchwabAccountNumbersTransport()
        )
        self.details_transport = details_transport or SchwabAccountDetailsTransport()

    def refresh(self, *, confirmation: str) -> dict[str, object]:
        if confirmation != BOUND_REFRESH_CONFIRMATION:
            raise SchwabBoundAccountRefreshError(
                "Bound Schwab refresh requires the exact confirmation phrase."
            )
        binding = self.bindings.load()
        credentials = self.secrets.load_credentials()
        current_tokens = self.secrets.load_tokens()
        refreshed_tokens = self.oauth_transport.refresh(credentials, current_tokens)
        candidate = self._revalidate_binding(
            binding,
            access_token=refreshed_tokens.access_token,
        )
        try:
            self.secrets.save_tokens(refreshed_tokens)
        except (OSError, SchwabSetupError) as exc:
            raise SchwabBoundAccountRefreshPersistenceError(
                "Refreshed Schwab authorization could not be persisted safely."
            ) from exc
        return {
            "mode": "SCHWAB_BOUND_ACCOUNT_REFRESH_READ_ONLY",
            "tokenState": "ACTIVE",
            "accountEnding": candidate.account_number_last_four,
            "accountHash": redact_value(candidate.account_hash),
            "accountType": candidate.account_type,
            "cashOnlyState": "VERIFIED_CASH",
            "accountBinding": "PINNED_UNCHANGED",
            "bindingRevalidated": True,
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
        else:
            binding = self.bindings.load()
            account_ending = binding.account_number_last_four
            binding_state = "PINNED"
        return {
            "credentialsStored": auth_status["credentialsStored"],
            "oauthAuthorized": auth_status["oauthAuthorized"],
            "tokenState": auth_status["tokenState"],
            "accountBinding": binding_state,
            "accountEnding": account_ending,
            "boundRefresh": "LOCKED_EXACT_CONFIRMATION_REQUIRED",
            "positionsRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }

    def _revalidate_binding(
        self,
        binding: SchwabAccountBinding,
        *,
        access_token: str,
    ) -> SchwabAccountBinding:
        accounts = self.discovery_transport.discover(access_token)
        if len(accounts) != 1:
            raise AccountIsolationError(
                "Bound Schwab refresh requires exactly one authorized account."
            )
        discovered = accounts[0]
        if discovered.account_hash != binding.account_hash:
            raise AccountIsolationError(
                "The authorized Schwab account hash changed; refreshed tokens were not saved."
            )
        if discovered.account_number_last_four != binding.account_number_last_four:
            raise AccountIsolationError(
                "The authorized Schwab account ending changed; refreshed tokens were not saved."
            )
        payload = self.details_transport.fetch(access_token, discovered.account_hash)
        identity = parse_account_identity(payload, discovered)
        candidate = build_unpersisted_binding_candidate(identity)
        if candidate != binding:
            raise AccountIsolationError(
                "The authorized Schwab CASH identity changed; refreshed tokens were not saved."
            )
        return candidate


def main(argv: list[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Refresh Schwab OAuth only after immutable CASH binding revalidation."
    )
    parser.add_argument("command", choices=("status", "refresh"))
    args = parser.parse_args(argv)
    bound_refresh = SchwabBoundAccountRefresh()
    try:
        if args.command == "refresh":
            confirmation = input(
                f"Type {BOUND_REFRESH_CONFIRMATION!r} to refresh and revalidate "
                "the pinned CASH account: "
            )
            report = bound_refresh.refresh(confirmation=confirmation)
        else:
            report = bound_refresh.status()
    except (
        AccountIsolationError,
        SchwabAccountValidationError,
        SchwabBoundAccountRefreshError,
        SchwabOAuthError,
    ) as exc:
        print(f"Bound Schwab refresh stopped safely: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
