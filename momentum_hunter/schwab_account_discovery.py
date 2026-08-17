from __future__ import annotations

"""One-shot, non-persisting discovery of Schwab-authorized account identities."""

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Mapping, Sequence

import requests

from momentum_hunter.schwab_onboarding import (
    SchwabOAuthError,
    SchwabOAuthSecretRepository,
)
from momentum_hunter.schwab_readonly import redact_value


SCHWAB_ACCOUNT_NUMBERS_URL = (
    "https://api.schwabapi.com/trader/v1/accounts/accountNumbers"
)
DISCOVERY_CONFIRMATION = "DISCOVER SCHWAB ACCOUNTS READ ONLY"
HTTP_TIMEOUT = (5.0, 30.0)
MAX_DISCOVERY_RESPONSE_BYTES = 64 * 1024


class SchwabAccountDiscoveryError(RuntimeError):
    pass


class SchwabAccountDiscoveryNetworkError(SchwabAccountDiscoveryError):
    pass


class SchwabAccountDiscoveryResponseError(SchwabAccountDiscoveryError):
    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        if http_status is not None:
            self.http_status = http_status


class SchwabAccountDiscoveryUnauthorizedError(
    SchwabAccountDiscoveryResponseError
):
    """The account-discovery endpoint rejected the bearer token with HTTP 401."""

    http_status = 401


class SchwabAccountDiscoveryForbiddenError(SchwabAccountDiscoveryResponseError):
    """The account-discovery endpoint denied the request with HTTP 403."""

    http_status = 403


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


@dataclass(frozen=True, repr=False)
class DiscoveredSchwabAccount:
    account_number_last_four: str
    account_hash: str

    def __repr__(self) -> str:
        return (
            "DiscoveredSchwabAccount("
            f"account_number_last_four={self.account_number_last_four!r}, "
            f"account_hash={redact_value(self.account_hash)!r})"
        )


class SchwabAccountNumbersTransport:
    """Exact-host GET transport for Schwab's account-number/hash discovery endpoint."""

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

    def discover(self, access_token: str) -> list[DiscoveredSchwabAccount]:
        if not access_token.strip():
            raise SchwabAccountDiscoveryError(
                "Schwab account discovery requires an active OAuth access token."
            )
        try:
            response = self.session.get(
                SCHWAB_ACCOUNT_NUMBERS_URL,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Cache-Control": "no-store",
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise SchwabAccountDiscoveryNetworkError(
                "Schwab account discovery could not reach the exact configured endpoint."
            ) from None
        if response.is_redirect:
            raise SchwabAccountDiscoveryResponseError(
                "Schwab account discovery refused an HTTP redirect."
            )
        if response.status_code == 401:
            raise SchwabAccountDiscoveryUnauthorizedError(
                "Schwab account discovery failed safely with HTTP 401."
            )
        if response.status_code == 403:
            raise SchwabAccountDiscoveryForbiddenError(
                "Schwab account discovery failed safely with HTTP 403."
            )
        if response.status_code != 200:
            raise SchwabAccountDiscoveryResponseError(
                f"Schwab account discovery failed safely with HTTP {response.status_code}.",
                http_status=response.status_code,
            )
        if len(response.content) > MAX_DISCOVERY_RESPONSE_BYTES:
            raise SchwabAccountDiscoveryResponseError(
                "Schwab account discovery response exceeded the size limit."
            )
        try:
            payload = response.json()
        except ValueError:
            raise SchwabAccountDiscoveryResponseError(
                "Schwab account discovery response was not valid JSON."
            ) from None
        return parse_discovered_accounts(payload)


class SchwabAccountDiscovery:
    """Confirmation-gated discovery with no account binding or result persistence."""

    def __init__(
        self,
        *,
        secrets_repository: SchwabOAuthSecretRepository | None = None,
        transport: SchwabAccountNumbersTransport | None = None,
    ) -> None:
        self.secrets = secrets_repository or SchwabOAuthSecretRepository()
        self.transport = transport or SchwabAccountNumbersTransport()

    def discover(self, *, confirmation: str) -> dict[str, object]:
        if confirmation != DISCOVERY_CONFIRMATION:
            raise SchwabAccountDiscoveryError(
                "Live Schwab account discovery requires the exact confirmation phrase."
            )
        tokens = self.secrets.load_tokens()
        if tokens.expired:
            raise SchwabAccountDiscoveryError(
                "The Schwab OAuth access token expired; complete or refresh authorization before discovery."
            )
        accounts = self.transport.discover(tokens.access_token)
        return build_discovery_report(accounts)

    def status(self) -> dict[str, object]:
        auth_status = self.secrets.status()
        return {
            "credentialsStored": auth_status["credentialsStored"],
            "oauthAuthorized": auth_status["oauthAuthorized"],
            "tokenState": auth_status["tokenState"],
            "accountDiscovery": "LOCKED_EXACT_CONFIRMATION_REQUIRED",
            "accountBinding": "NOT_BOUND",
            "persistence": "NONE",
            "orderTransmission": "UNAVAILABLE",
        }


def parse_discovered_accounts(payload: object) -> list[DiscoveredSchwabAccount]:
    if not isinstance(payload, list):
        raise SchwabAccountDiscoveryResponseError(
            "Schwab account discovery response had an invalid shape."
        )
    accounts: list[DiscoveredSchwabAccount] = []
    seen_numbers: set[str] = set()
    seen_hashes: set[str] = set()
    for item in payload:
        if not isinstance(item, Mapping):
            raise SchwabAccountDiscoveryResponseError(
                "Schwab account discovery response contained an invalid account entry."
            )
        account_number = item.get("accountNumber")
        account_hash = item.get("hashValue")
        if (
            not isinstance(account_number, str)
            or len(account_number.strip()) < 4
            or not isinstance(account_hash, str)
            or not account_hash.strip()
        ):
            raise SchwabAccountDiscoveryResponseError(
                "Schwab account discovery response omitted required identity fields."
            )
        normalized_number = account_number.strip()
        normalized_hash = account_hash.strip()
        last_four = normalized_number[-4:]
        if not last_four.isdigit():
            raise SchwabAccountDiscoveryResponseError(
                "Schwab account discovery returned an invalid account-number suffix."
            )
        if normalized_number in seen_numbers or normalized_hash in seen_hashes:
            raise SchwabAccountDiscoveryResponseError(
                "Schwab account discovery returned duplicate account identity."
            )
        seen_numbers.add(normalized_number)
        seen_hashes.add(normalized_hash)
        accounts.append(
            DiscoveredSchwabAccount(
                account_number_last_four=last_four,
                account_hash=normalized_hash,
            )
        )
    return accounts


def build_discovery_report(
    accounts: Sequence[DiscoveredSchwabAccount],
) -> dict[str, object]:
    return {
        "mode": "SCHWAB_ACCOUNT_DISCOVERY_READ_ONLY",
        "request": "GET_ACCOUNT_NUMBERS_ONLY",
        "authorizedAccountCount": len(accounts),
        "accounts": [
            {
                "accountEnding": account.account_number_last_four,
                "accountHash": redact_value(account.account_hash),
            }
            for account in accounts
        ],
        "singleCanaryCandidate": len(accounts) == 1,
        "accountBinding": "NOT_BOUND",
        "persistence": "NONE",
        "balancesRequested": False,
        "positionsRequested": False,
        "marketDataRequested": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
    }


def main(argv: list[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description="Confirmation-gated Schwab account identity discovery."
    )
    parser.add_argument("command", choices=("status", "discover"))
    args = parser.parse_args(argv)
    discovery = SchwabAccountDiscovery()
    try:
        if args.command == "discover":
            confirmation = input(
                f"Type {DISCOVERY_CONFIRMATION!r} to make one read-only account identity request: "
            )
            report = discovery.discover(confirmation=confirmation)
        else:
            report = discovery.status()
    except (SchwabAccountDiscoveryError, SchwabOAuthError) as exc:
        print(f"Schwab account discovery stopped safely: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
