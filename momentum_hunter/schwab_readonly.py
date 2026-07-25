from __future__ import annotations

"""Credential-free contracts for a future physically read-only Schwab adapter.

The module contains no URLs, HTTP client, OAuth token, or order-transmission method.
Authenticated endpoint details must come from Schwab's official developer portal.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable


EXPECTED_ACCOUNT_TYPE = "INDIVIDUAL_CASH"
READ_ONLY_OPERATIONS = frozenset(
    {
        "list_authorized_accounts",
        "get_account",
        "get_balances",
        "get_positions",
        "list_orders",
        "get_order_status",
    }
)


class SchwabReadOnlyError(RuntimeError):
    pass


class AccountIsolationError(SchwabReadOnlyError):
    pass


class ReadOnlyOperationError(SchwabReadOnlyError):
    pass


@dataclass(frozen=True, repr=False)
class SchwabAuthorizedAccount:
    account_hash: str
    account_number_last_four: str
    account_type: str
    cash_only: bool

    def __repr__(self) -> str:
        return (
            "SchwabAuthorizedAccount("
            f"account_hash={redact_value(self.account_hash)!r}, "
            f"account_number_last_four={self.account_number_last_four!r}, "
            f"account_type={self.account_type!r}, "
            f"cash_only={self.cash_only!r})"
        )


@dataclass(frozen=True, repr=False)
class SchwabAccountBinding:
    account_hash: str
    account_number_last_four: str
    account_type: str

    def __repr__(self) -> str:
        return (
            "SchwabAccountBinding("
            f"account_hash={redact_value(self.account_hash)!r}, "
            f"account_number_last_four={self.account_number_last_four!r}, "
            f"account_type={self.account_type!r})"
        )


@dataclass(frozen=True)
class SchwabAccount:
    account_hash: str
    account_number_last_four: str
    account_type: str
    cash_only: bool
    status: str


@dataclass(frozen=True)
class SchwabBalances:
    account_hash: str
    cash_available: float
    buying_power: float
    liquidation_value: float
    as_of: str


@dataclass(frozen=True)
class SchwabPosition:
    account_hash: str
    symbol: str
    quantity: float
    average_price: float
    market_value: float


@dataclass(frozen=True)
class SchwabOrder:
    account_hash: str
    order_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    status: str
    entered_at: str


class SchwabReadOnlyDataSource(ABC):
    """Logical data source; production HTTP details are intentionally absent."""

    @abstractmethod
    def list_authorized_accounts(self) -> list[SchwabAuthorizedAccount]:
        raise NotImplementedError

    @abstractmethod
    def get_account(self, account_hash: str) -> SchwabAccount:
        raise NotImplementedError

    @abstractmethod
    def get_balances(self, account_hash: str) -> SchwabBalances:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self, account_hash: str) -> list[SchwabPosition]:
        raise NotImplementedError

    @abstractmethod
    def list_orders(self, account_hash: str) -> list[SchwabOrder]:
        raise NotImplementedError

    @abstractmethod
    def get_order_status(self, account_hash: str, order_id: str) -> SchwabOrder:
        raise NotImplementedError


class ReadOnlyEndpointAllowlist:
    """Fail-closed logical HTTP policy for the future authenticated transport."""

    def require(self, method: str, operation: str) -> None:
        normalized_method = method.strip().upper()
        normalized_operation = operation.strip()
        if normalized_method != "GET":
            raise ReadOnlyOperationError("Schwab read-only transport permits GET operations only.")
        if normalized_operation not in READ_ONLY_OPERATIONS:
            raise ReadOnlyOperationError(f"Schwab read-only operation is not allowlisted: {normalized_operation or 'missing'}.")


class AccountIsolationPolicy:
    def create_binding(
        self,
        accounts: Iterable[SchwabAuthorizedAccount],
        *,
        manually_confirmed_last_four: str,
    ) -> SchwabAccountBinding:
        items = list(accounts)
        if len(items) != 1:
            raise AccountIsolationError(f"Exactly one Schwab account must be authorized; received {len(items)}.")
        account = items[0]
        self._validate_account(account)
        confirmed = normalize_last_four(manually_confirmed_last_four)
        if account.account_number_last_four != confirmed:
            raise AccountIsolationError("The manually confirmed account ending does not match the authorized account.")
        return SchwabAccountBinding(
            account_hash=account.account_hash,
            account_number_last_four=account.account_number_last_four,
            account_type=account.account_type,
        )

    def validate_binding(
        self,
        binding: SchwabAccountBinding,
        accounts: Iterable[SchwabAuthorizedAccount],
    ) -> SchwabAuthorizedAccount:
        items = list(accounts)
        if len(items) != 1:
            raise AccountIsolationError(f"Account revalidation requires exactly one authorized account; received {len(items)}.")
        account = items[0]
        self._validate_account(account)
        if account.account_hash != binding.account_hash:
            raise AccountIsolationError("The authorized Schwab account hash changed; connection is locked.")
        if account.account_number_last_four != binding.account_number_last_four:
            raise AccountIsolationError("The authorized Schwab account ending changed; connection is locked.")
        if account.account_type != binding.account_type:
            raise AccountIsolationError("The authorized Schwab account type changed; connection is locked.")
        return account

    @staticmethod
    def _validate_account(account: SchwabAuthorizedAccount) -> None:
        if not account.account_hash.strip():
            raise AccountIsolationError("The authorized account is missing its opaque account hash.")
        normalize_last_four(account.account_number_last_four)
        if account.account_type != EXPECTED_ACCOUNT_TYPE:
            raise AccountIsolationError(
                f"Expected an {EXPECTED_ACCOUNT_TYPE} account; received {account.account_type or 'missing'}."
            )
        if not account.cash_only:
            raise AccountIsolationError("The canary account is not confirmed as cash-only.")


class SchwabReadOnlyAdapter:
    """Every operation revalidates the single pinned account before reading."""

    def __init__(
        self,
        *,
        source: SchwabReadOnlyDataSource,
        binding: SchwabAccountBinding,
        isolation_policy: AccountIsolationPolicy | None = None,
        endpoint_policy: ReadOnlyEndpointAllowlist | None = None,
    ) -> None:
        self._source = source
        self._binding = binding
        self._isolation = isolation_policy or AccountIsolationPolicy()
        self._endpoints = endpoint_policy or ReadOnlyEndpointAllowlist()

    @property
    def binding(self) -> SchwabAccountBinding:
        return self._binding

    def list_authorized_accounts(self) -> list[SchwabAuthorizedAccount]:
        self._endpoints.require("GET", "list_authorized_accounts")
        accounts = self._source.list_authorized_accounts()
        self._isolation.validate_binding(self._binding, accounts)
        return accounts

    def get_account(self) -> SchwabAccount:
        self._revalidate("get_account")
        account = self._source.get_account(self._binding.account_hash)
        validate_account_response(self._binding, account)
        return account

    def get_balances(self) -> SchwabBalances:
        self._revalidate("get_balances")
        balances = self._source.get_balances(self._binding.account_hash)
        require_bound_hash(self._binding, balances.account_hash)
        return balances

    def get_positions(self) -> list[SchwabPosition]:
        self._revalidate("get_positions")
        positions = self._source.get_positions(self._binding.account_hash)
        for position in positions:
            require_bound_hash(self._binding, position.account_hash)
        return positions

    def list_orders(self) -> list[SchwabOrder]:
        self._revalidate("list_orders")
        orders = self._source.list_orders(self._binding.account_hash)
        for order in orders:
            require_bound_hash(self._binding, order.account_hash)
        return orders

    def get_order_status(self, order_id: str) -> SchwabOrder:
        if not order_id.strip():
            raise ValueError("A non-empty order ID is required.")
        self._revalidate("get_order_status")
        order = self._source.get_order_status(self._binding.account_hash, order_id)
        require_bound_hash(self._binding, order.account_hash)
        return order

    def redacted_status(self) -> dict[str, object]:
        account = self._isolation.validate_binding(self._binding, self._source.list_authorized_accounts())
        return {
            "mode": "SCHWAB_READ_ONLY",
            "accountEnding": account.account_number_last_four,
            "accountType": account.account_type,
            "cashOnly": account.cash_only,
            "orderTransmission": "UNAVAILABLE",
            "accountHash": redact_value(account.account_hash),
        }

    def _revalidate(self, operation: str) -> None:
        self._endpoints.require("GET", operation)
        self._isolation.validate_binding(self._binding, self._source.list_authorized_accounts())


def require_bound_hash(binding: SchwabAccountBinding, observed_hash: str) -> None:
    if observed_hash != binding.account_hash:
        raise AccountIsolationError("A Schwab response referenced an account other than the pinned canary account.")


def validate_account_response(binding: SchwabAccountBinding, account: SchwabAccount) -> None:
    require_bound_hash(binding, account.account_hash)
    if account.account_number_last_four != binding.account_number_last_four:
        raise AccountIsolationError("The returned Schwab account ending does not match the pinned canary account.")
    if account.account_type != binding.account_type:
        raise AccountIsolationError("The returned Schwab account type does not match the pinned canary account.")
    if not account.cash_only:
        raise AccountIsolationError("The returned Schwab account is not cash-only; connection is locked.")


def normalize_last_four(value: str) -> str:
    normalized = value.strip()
    if len(normalized) != 4 or not normalized.isdigit():
        raise AccountIsolationError("Account confirmation must contain exactly four digits.")
    return normalized


def redact_value(value: str, *, visible: int = 4) -> str:
    clean = str(value)
    if not clean:
        return "[missing]"
    if len(clean) <= visible:
        return "*" * len(clean)
    return "*" * (len(clean) - visible) + clean[-visible:]


def redact_mapping(payload: dict[str, object]) -> dict[str, object]:
    sensitive_markers = ("account", "hash", "token", "secret", "credential", "password")
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if any(marker in key.lower() for marker in sensitive_markers):
            redacted[key] = redact_value(str(value))
        else:
            redacted[key] = value
    return redacted
