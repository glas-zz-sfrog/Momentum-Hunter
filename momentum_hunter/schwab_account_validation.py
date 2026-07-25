from __future__ import annotations

"""Read-only validation of one Schwab canary account without binding it."""

import argparse
import getpass
import json
import sys
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import quote

import requests

from momentum_hunter.schwab_account_discovery import (
    HTTP_TIMEOUT,
    DiscoveredSchwabAccount,
    SchwabAccountNumbersTransport,
)
from momentum_hunter.schwab_onboarding import (
    SchwabOAuthError,
    SchwabOAuthSecretRepository,
)
from momentum_hunter.schwab_readonly import (
    EXPECTED_ACCOUNT_TYPE,
    AccountIsolationPolicy,
    SchwabAccountBinding,
    SchwabAuthorizedAccount,
    redact_value,
)


SCHWAB_ACCOUNT_DETAILS_BASE_URL = "https://api.schwabapi.com/trader/v1/accounts"
VALIDATION_CONFIRMATION = "VALIDATE SCHWAB CASH ACCOUNT READ ONLY"
MAX_ACCOUNT_RESPONSE_BYTES = 256 * 1024
ACCOUNT_TYPES = frozenset({"CASH", "MARGIN"})


class SchwabAccountValidationError(RuntimeError):
    pass


class SchwabAccountValidationNetworkError(SchwabAccountValidationError):
    pass


class SchwabAccountValidationResponseError(SchwabAccountValidationError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


@dataclass(frozen=True, repr=False)
class SchwabAccountIdentity:
    account_number_last_four: str
    account_hash: str
    account_type: str
    balances_present: bool

    def __repr__(self) -> str:
        return (
            "SchwabAccountIdentity("
            f"account_number_last_four={self.account_number_last_four!r}, "
            f"account_hash={redact_value(self.account_hash)!r}, "
            f"account_type={self.account_type!r}, "
            f"balances_present={self.balances_present!r})"
        )


class SchwabAccountDetailsTransport:
    """Exact-host GET transport for one encrypted Schwab account identity."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = HTTP_TIMEOUT,
    ) -> None:
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.timeout = timeout

    def fetch(self, access_token: str, account_hash: str) -> object:
        if not access_token.strip():
            raise SchwabAccountValidationError(
                "Schwab account validation requires an active OAuth access token."
            )
        normalized_hash = account_hash.strip()
        if not normalized_hash:
            raise SchwabAccountValidationError(
                "Schwab account validation requires one discovered account hash."
            )
        account_url = (
            f"{SCHWAB_ACCOUNT_DETAILS_BASE_URL}/{quote(normalized_hash, safe='')}"
        )
        try:
            response = self.session.get(
                account_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Cache-Control": "no-store",
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise SchwabAccountValidationNetworkError(
                "Schwab account validation could not reach the exact configured endpoint."
            ) from None
        if response.is_redirect:
            raise SchwabAccountValidationResponseError(
                "Schwab account validation refused an HTTP redirect."
            )
        if response.status_code != 200:
            raise SchwabAccountValidationResponseError(
                f"Schwab account validation failed safely with HTTP {response.status_code}."
            )
        if len(response.content) > MAX_ACCOUNT_RESPONSE_BYTES:
            raise SchwabAccountValidationResponseError(
                "Schwab account validation response exceeded the size limit."
            )
        try:
            return response.json()
        except ValueError:
            raise SchwabAccountValidationResponseError(
                "Schwab account validation response was not valid JSON."
            ) from None


class SchwabCashAccountValidation:
    """Confirmation-gated identity validation with no binding or persistence."""

    def __init__(
        self,
        *,
        secrets_repository: SchwabOAuthSecretRepository | None = None,
        discovery_transport: SchwabAccountNumbersTransport | None = None,
        details_transport: SchwabAccountDetailsTransport | None = None,
    ) -> None:
        self.secrets = secrets_repository or SchwabOAuthSecretRepository()
        self.discovery_transport = (
            discovery_transport or SchwabAccountNumbersTransport()
        )
        self.details_transport = details_transport or SchwabAccountDetailsTransport()

    def validate(
        self,
        *,
        expected_account_ending: str,
        confirmation: str,
    ) -> dict[str, object]:
        if confirmation != VALIDATION_CONFIRMATION:
            raise SchwabAccountValidationError(
                "Live Schwab account validation requires the exact confirmation phrase."
            )
        expected_ending = _normalize_account_ending(expected_account_ending)
        tokens = self.secrets.load_tokens()
        if tokens.expired:
            raise SchwabAccountValidationError(
                "The Schwab OAuth access token expired; complete or refresh authorization before validation."
            )
        accounts = self.discovery_transport.discover(tokens.access_token)
        discovered = _require_single_expected_account(accounts, expected_ending)
        payload = self.details_transport.fetch(
            tokens.access_token,
            discovered.account_hash,
        )
        identity = parse_account_identity(payload, discovered)
        if identity.account_type != "CASH":
            raise SchwabAccountValidationError(
                "The intended Schwab canary account is not a CASH account; "
                "binding remains locked."
            )
        return build_validation_report(identity)

    def status(self) -> dict[str, object]:
        auth_status = self.secrets.status()
        return {
            "credentialsStored": auth_status["credentialsStored"],
            "oauthAuthorized": auth_status["oauthAuthorized"],
            "tokenState": auth_status["tokenState"],
            "accountValidation": "LOCKED_EXACT_CONFIRMATION_REQUIRED",
            "accountBinding": "NOT_BOUND",
            "persistence": "NONE",
            "positionsRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }


def _normalize_account_ending(value: str) -> str:
    normalized = value.strip()
    if len(normalized) != 4 or not normalized.isdigit():
        raise SchwabAccountValidationError(
            "Expected Schwab account ending must contain exactly four digits."
        )
    return normalized


def _require_single_expected_account(
    accounts: list[DiscoveredSchwabAccount],
    expected_ending: str,
) -> DiscoveredSchwabAccount:
    if len(accounts) != 1:
        raise SchwabAccountValidationError(
            "Schwab account validation requires exactly one authorized account; "
            "binding remains locked."
        )
    account = accounts[0]
    if account.account_number_last_four != expected_ending:
        raise SchwabAccountValidationError(
            "The sole authorized Schwab account does not match the intended ending; "
            "binding remains locked."
        )
    return account


def parse_account_identity(
    payload: object,
    discovered: DiscoveredSchwabAccount,
) -> SchwabAccountIdentity:
    if not isinstance(payload, Mapping):
        raise SchwabAccountValidationResponseError(
            "Schwab account validation response had an invalid shape."
        )
    securities_account = payload.get("securitiesAccount")
    if not isinstance(securities_account, Mapping):
        raise SchwabAccountValidationResponseError(
            "Schwab account validation response omitted securitiesAccount."
        )
    account_type = securities_account.get("type")
    account_number = securities_account.get("accountNumber")
    if not isinstance(account_type, str) or account_type.upper() not in ACCOUNT_TYPES:
        raise SchwabAccountValidationResponseError(
            "Schwab account validation response had an unsupported account type."
        )
    if not isinstance(account_number, str) or len(account_number.strip()) < 4:
        raise SchwabAccountValidationResponseError(
            "Schwab account validation response omitted the account identity."
        )
    account_ending = account_number.strip()[-4:]
    if not account_ending.isdigit():
        raise SchwabAccountValidationResponseError(
            "Schwab account validation response had an invalid account-number suffix."
        )
    if account_ending != discovered.account_number_last_four:
        raise SchwabAccountValidationResponseError(
            "Schwab account validation response did not match the discovered account."
        )
    positions = securities_account.get("positions")
    if positions not in (None, []):
        raise SchwabAccountValidationResponseError(
            "Schwab returned position data even though positions were not requested."
        )
    balance_keys = (
        "initialBalances",
        "currentBalances",
        "projectedBalances",
    )
    balances_present = any(
        isinstance(securities_account.get(key), Mapping) for key in balance_keys
    )
    if not balances_present:
        raise SchwabAccountValidationResponseError(
            "Schwab account validation response omitted the documented balance shape."
        )
    return SchwabAccountIdentity(
        account_number_last_four=account_ending,
        account_hash=discovered.account_hash,
        account_type=account_type.upper(),
        balances_present=True,
    )


def build_unpersisted_binding_candidate(
    identity: SchwabAccountIdentity,
) -> SchwabAccountBinding:
    if identity.account_type != "CASH":
        raise SchwabAccountValidationError(
            "Only an official Schwab CASH account can become a binding candidate."
        )
    authorized_account = SchwabAuthorizedAccount(
        account_hash=identity.account_hash,
        account_number_last_four=identity.account_number_last_four,
        account_type=EXPECTED_ACCOUNT_TYPE,
        cash_only=True,
    )
    return AccountIsolationPolicy().create_binding(
        [authorized_account],
        manually_confirmed_last_four=identity.account_number_last_four,
    )


def build_validation_report(identity: SchwabAccountIdentity) -> dict[str, object]:
    candidate = build_unpersisted_binding_candidate(identity)
    return {
        "mode": "SCHWAB_CASH_ACCOUNT_VALIDATION_READ_ONLY",
        "requestSequence": [
            "GET_ACCOUNT_NUMBERS_ONLY",
            "GET_SINGLE_ACCOUNT_WITHOUT_POSITIONS",
        ],
        "authorizedAccountCount": 1,
        "accountEnding": identity.account_number_last_four,
        "accountHash": redact_value(identity.account_hash),
        "accountType": identity.account_type,
        "cashOnlyState": "VERIFIED_CASH",
        "identityMatch": True,
        "bindingCandidateType": candidate.account_type,
        "bindingEligibility": "VALIDATED_NOT_PERSISTED",
        "balancesReturnedByContract": identity.balances_present,
        "balanceValuesSuppressed": True,
        "positionsRequested": False,
        "positionsReceived": False,
        "marketDataRequested": False,
        "ordersRequested": False,
        "accountBinding": "NOT_BOUND",
        "persistence": "NONE",
        "orderTransmission": "UNAVAILABLE",
    }


def main(argv: list[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Confirmation-gated Schwab CASH account validation."
    )
    parser.add_argument("command", choices=("status", "validate"))
    args = parser.parse_args(argv)
    validation = SchwabCashAccountValidation()
    try:
        if args.command == "validate":
            expected_ending = getpass.getpass(
                "Enter the intended canary account's final four digits: "
            )
            confirmation = input(
                f"Type {VALIDATION_CONFIRMATION!r} to make the two read-only "
                "identity requests: "
            )
            report = validation.validate(
                expected_account_ending=expected_ending,
                confirmation=confirmation,
            )
        else:
            report = validation.status()
    except (SchwabAccountValidationError, SchwabOAuthError) as exc:
        print(f"Schwab account validation stopped safely: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
