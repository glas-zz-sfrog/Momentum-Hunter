from __future__ import annotations

"""Offline Schwab-shaped scenarios using sanitized synthetic values only."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from momentum_hunter.schwab_readonly import (
    EXPECTED_ACCOUNT_TYPE,
    SchwabAccount,
    SchwabAuthorizedAccount,
    SchwabBalances,
    SchwabOrder,
    SchwabPosition,
    SchwabReadOnlyDataSource,
)


SYNTHETIC_ACCOUNT_HASH = "SYNTHETIC-CANARY-HASH-0001"
SYNTHETIC_ACCOUNT_LAST_FOUR = "0100"


class SyntheticSchwabError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SyntheticOAuthToken:
    access_token: str
    refresh_token: str
    expires_at: str

    def expired(self, *, observed_at: datetime) -> bool:
        expires_at = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        return observed_at.astimezone(timezone.utc) >= expires_at.astimezone(timezone.utc)


class SyntheticSchwabOAuthEmulator:
    """Synthetic authorization-code and refresh lifecycle with no HTTP behavior."""

    def __init__(self, *, token_lifetime_seconds: int = 1800) -> None:
        self.token_lifetime_seconds = max(1, token_lifetime_seconds)
        self._codes: dict[str, str] = {}
        self._refresh_tokens: set[str] = set()

    def create_authorization_code(self, *, state: str) -> str:
        if not state:
            raise SyntheticSchwabError("STATE_REQUIRED", "Synthetic OAuth state is required.")
        code = f"SYNTHETIC-CODE-{uuid4().hex}"
        self._codes[code] = state
        return code

    def exchange_code(self, code: str, *, expected_state: str, observed_at: datetime) -> SyntheticOAuthToken:
        state = self._codes.pop(code, "")
        if not state:
            raise SyntheticSchwabError("INVALID_CODE", "Synthetic authorization code is invalid or already used.")
        if state != expected_state:
            raise SyntheticSchwabError("STATE_MISMATCH", "Synthetic OAuth state mismatch.")
        return self._issue_token(observed_at)

    def refresh(self, refresh_token: str, *, observed_at: datetime) -> SyntheticOAuthToken:
        if refresh_token not in self._refresh_tokens:
            raise SyntheticSchwabError("INVALID_REFRESH_TOKEN", "Synthetic refresh token is invalid.")
        self._refresh_tokens.remove(refresh_token)
        return self._issue_token(observed_at)

    def _issue_token(self, observed_at: datetime) -> SyntheticOAuthToken:
        refresh_token = f"SYNTHETIC-REFRESH-{uuid4().hex}"
        self._refresh_tokens.add(refresh_token)
        expires_at = observed_at.astimezone(timezone.utc) + timedelta(seconds=self.token_lifetime_seconds)
        return SyntheticOAuthToken(
            access_token=f"SYNTHETIC-ACCESS-{uuid4().hex}",
            refresh_token=refresh_token,
            expires_at=expires_at.isoformat().replace("+00:00", "Z"),
        )


@dataclass
class SyntheticSchwabDataSource(SchwabReadOnlyDataSource):
    accounts: list[SchwabAuthorizedAccount] = field(default_factory=list)
    balances: SchwabBalances | None = None
    positions: list[SchwabPosition] = field(default_factory=list)
    orders: list[SchwabOrder] = field(default_factory=list)
    failure: str = ""
    changed_account_hash_after_calls: int | None = None
    calls: int = 0

    def list_authorized_accounts(self) -> list[SchwabAuthorizedAccount]:
        self._before_call()
        accounts = list(self.accounts)
        if self.changed_account_hash_after_calls is not None and self.calls > self.changed_account_hash_after_calls:
            accounts = [
                SchwabAuthorizedAccount(
                    account_hash="SYNTHETIC-CHANGED-HASH",
                    account_number_last_four=account.account_number_last_four,
                    account_type=account.account_type,
                    cash_only=account.cash_only,
                )
                for account in accounts
            ]
        return accounts

    def get_account(self, account_hash: str) -> SchwabAccount:
        self._before_call()
        account = self._account_for_hash(account_hash)
        return SchwabAccount(
            account_hash=account.account_hash,
            account_number_last_four=account.account_number_last_four,
            account_type=account.account_type,
            cash_only=account.cash_only,
            status="OPEN",
        )

    def get_balances(self, account_hash: str) -> SchwabBalances:
        self._before_call()
        self._account_for_hash(account_hash)
        if self.balances is None:
            raise SyntheticSchwabError("MALFORMED_RESPONSE", "Synthetic balance response is missing.")
        return self.balances

    def get_positions(self, account_hash: str) -> list[SchwabPosition]:
        self._before_call()
        self._account_for_hash(account_hash)
        return list(self.positions)

    def list_orders(self, account_hash: str) -> list[SchwabOrder]:
        self._before_call()
        self._account_for_hash(account_hash)
        return list(self.orders)

    def get_order_status(self, account_hash: str, order_id: str) -> SchwabOrder:
        self._before_call()
        self._account_for_hash(account_hash)
        order = next((item for item in self.orders if item.order_id == order_id), None)
        if order is None:
            raise SyntheticSchwabError("ORDER_NOT_FOUND", "Synthetic order was not found.")
        return order

    def _account_for_hash(self, account_hash: str) -> SchwabAuthorizedAccount:
        account = next((item for item in self.accounts if item.account_hash == account_hash), None)
        if account is None:
            raise SyntheticSchwabError("ACCOUNT_NOT_FOUND", "Synthetic account was not found.")
        return account

    def _before_call(self) -> None:
        self.calls += 1
        failures = {
            "unauthorized": ("UNAUTHORIZED", "Synthetic token is unauthorized or expired."),
            "rate_limit": ("RATE_LIMIT", "Synthetic rate limit was reached."),
            "timeout": ("TIMEOUT", "Synthetic network timeout."),
            "malformed": ("MALFORMED_RESPONSE", "Synthetic malformed response."),
        }
        if self.failure in failures:
            code, message = failures[self.failure]
            raise SyntheticSchwabError(code, message)


def synthetic_source(
    *,
    account_count: int = 1,
    account_type: str = EXPECTED_ACCOUNT_TYPE,
    cash_only: bool = True,
    order_statuses: tuple[str, ...] = ("WORKING", "FILLED", "CANCELED", "UNKNOWN"),
    failure: str = "",
) -> SyntheticSchwabDataSource:
    accounts = [
        SchwabAuthorizedAccount(
            account_hash=SYNTHETIC_ACCOUNT_HASH if index == 0 else f"SYNTHETIC-EXTRA-HASH-{index:04d}",
            account_number_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR if index == 0 else f"{index:04d}",
            account_type=account_type,
            cash_only=cash_only,
        )
        for index in range(account_count)
    ]
    orders = [
        SchwabOrder(
            account_hash=SYNTHETIC_ACCOUNT_HASH,
            order_id=f"SYNTHETIC-ORDER-{index:04d}",
            symbol="TEST",
            side="BUY",
            quantity=1,
            order_type="LIMIT",
            status=status,
            entered_at=f"2026-07-23T10:{index:02d}:00-05:00",
        )
        for index, status in enumerate(order_statuses, 1)
    ]
    return SyntheticSchwabDataSource(
        accounts=accounts,
        balances=SchwabBalances(
            account_hash=SYNTHETIC_ACCOUNT_HASH,
            cash_available=100.0,
            buying_power=100.0,
            liquidation_value=100.0,
            as_of="2026-07-23T10:00:00-05:00",
        ),
        positions=[],
        orders=orders,
        failure=failure,
    )
