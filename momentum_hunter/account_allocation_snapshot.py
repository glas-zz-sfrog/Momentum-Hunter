from __future__ import annotations

"""Fresh, read-only account and portfolio evidence for account allocation."""

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping, Protocol
from urllib.parse import quote

import requests

from momentum_hunter.account_allocation import (
    EXPECTED_ACCOUNT_ENDING,
    EXPECTED_ACCOUNT_TYPE,
    AccountAllocationContext,
    AccountAllocationDecision,
    AccountAllocationPolicy,
    AccountPortfolioSnapshot,
    account_allocation_decision_from_dict,
    build_account_allocation_decision,
    build_schwab_account_allocation_context,
)
from momentum_hunter.schwab_account_discovery import (
    HTTP_TIMEOUT,
    DiscoveredSchwabAccount,
    SchwabAccountDiscoveryError,
    SchwabAccountNumbersTransport,
)
from momentum_hunter.schwab_market_data import (
    BoundSchwabAccessTokenProvider,
    SchwabMarketDataAuthorizationError,
)
from momentum_hunter.schwab_onboarding import (
    EncryptedSchwabAccountBindingStore,
    SchwabOAuthError,
)
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    SchwabAccountBinding,
    SchwabAuthorizedAccount,
    SchwabBalances,
    SchwabPosition,
)
from momentum_hunter.schwab_setup import SchwabSetupError
from momentum_hunter.shadow_trading import (
    ACTIVE_TRADE_STATES,
    SHADOW_STATE_PATH,
    ShadowStateStore,
    ShadowStateError,
    ShadowTradingState,
    realized_pnl_for_date,
)
from momentum_hunter.time_utils import CENTRAL_TZ


SCHWAB_ACCOUNT_DETAILS_BASE_URL = "https://api.schwabapi.com/trader/v1/accounts"
MAX_ACCOUNT_SNAPSHOT_BYTES = 512 * 1024
PORTFOLIO_SNAPSHOT_SOURCE = "OFFICIAL_SHADOW_STATE_READ_ONLY_V1"


class AccountAllocationSnapshotError(RuntimeError):
    pass


class AccountAllocationSnapshotNetworkError(AccountAllocationSnapshotError):
    pass


class AccountAllocationSnapshotResponseError(AccountAllocationSnapshotError):
    pass


class AccountAllocationBrokerageAnomaly(AccountAllocationSnapshotError):
    """A changed account identity or unexpected brokerage position."""


@dataclass(frozen=True, repr=False)
class SchwabAccountSnapshotResponse:
    payload: object
    provider_timestamp: datetime
    received_at: datetime

    def __repr__(self) -> str:
        return (
            "SchwabAccountSnapshotResponse(payload='[redacted Schwab account snapshot]', "
            f"provider_timestamp={self.provider_timestamp!r}, "
            f"received_at={self.received_at!r})"
        )


@dataclass(frozen=True, repr=False)
class ParsedSchwabAccountSnapshot:
    authorized_account: SchwabAuthorizedAccount
    balances: SchwabBalances
    positions: tuple[SchwabPosition, ...]
    received_at: datetime

    def __repr__(self) -> str:
        return (
            "ParsedSchwabAccountSnapshot("
            f"account_ending={self.authorized_account.account_number_last_four!r}, "
            f"account_type={self.authorized_account.account_type!r}, "
            f"position_count={len(self.positions)!r}, "
            f"received_at={self.received_at!r})"
        )


class SchwabAccountSnapshotTransport:
    """Exact-host GET transport for one bound account, including positions."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = HTTP_TIMEOUT,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch(
        self,
        access_token: str,
        account_hash: str,
    ) -> SchwabAccountSnapshotResponse:
        if not isinstance(access_token, str) or not access_token.strip():
            raise AccountAllocationSnapshotResponseError(
                "Account allocation snapshot requires an active OAuth access token."
            )
        normalized_hash = account_hash.strip() if isinstance(account_hash, str) else ""
        if not normalized_hash:
            raise AccountAllocationSnapshotResponseError(
                "Account allocation snapshot requires one bound account identity."
            )
        url = f"{SCHWAB_ACCOUNT_DETAILS_BASE_URL}/{quote(normalized_hash, safe='')}"
        try:
            response = self.session.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Cache-Control": "no-store",
                },
                params={"fields": "positions"},
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise AccountAllocationSnapshotNetworkError(
                "Account allocation snapshot could not reach the exact Schwab endpoint."
            ) from None
        received_at = aware_datetime(self.clock(), field="receipt clock")
        if response.is_redirect:
            raise AccountAllocationSnapshotResponseError(
                "Account allocation snapshot refused an HTTP redirect."
            )
        if response.status_code != 200:
            raise AccountAllocationSnapshotResponseError(
                f"Account allocation snapshot failed safely with HTTP {response.status_code}."
            )
        if len(response.content) > MAX_ACCOUNT_SNAPSHOT_BYTES:
            raise AccountAllocationSnapshotResponseError(
                "Account allocation snapshot response exceeded the size limit."
            )
        provider_timestamp = parse_provider_timestamp(response.headers.get("Date"))
        if provider_timestamp > received_at:
            raise AccountAllocationSnapshotResponseError(
                "Account allocation provider timestamp was later than local receipt."
            )
        try:
            payload = response.json()
        except ValueError:
            raise AccountAllocationSnapshotResponseError(
                "Account allocation snapshot response was not valid JSON."
            ) from None
        return SchwabAccountSnapshotResponse(
            payload=payload,
            provider_timestamp=provider_timestamp,
            received_at=received_at,
        )


class SchwabAccountPortfolioSnapshotSource:
    """Capture one fresh, bound account context without order capability."""

    def __init__(
        self,
        *,
        token_provider: object | None = None,
        binding_store: object | None = None,
        discovery_transport: object | None = None,
        snapshot_transport: object | None = None,
        portfolio_loader: Callable[[datetime], AccountPortfolioSnapshot] | None = None,
    ) -> None:
        self.token_provider = token_provider or BoundSchwabAccessTokenProvider()
        self.binding_store = binding_store or EncryptedSchwabAccountBindingStore()
        self.discovery = discovery_transport or SchwabAccountNumbersTransport()
        self.snapshot_transport = snapshot_transport or SchwabAccountSnapshotTransport()
        self.portfolio_loader = portfolio_loader or load_shadow_portfolio_snapshot

    def capture_context(self) -> AccountAllocationContext:
        try:
            binding: SchwabAccountBinding = self.binding_store.load()
            require_expected_binding(binding)
            access_token = self.token_provider.access_token()
            discovered = tuple(self.discovery.discover(access_token))
            require_discovered_binding(binding, discovered)
            response = self.snapshot_transport.fetch(
                access_token,
                binding.account_hash,
            )
            parsed = parse_schwab_account_snapshot(response, binding=binding)
            portfolio = self.portfolio_loader(parsed.received_at)
            return build_schwab_account_allocation_context(
                binding=binding,
                authorized_accounts=(parsed.authorized_account,),
                balances=parsed.balances,
                broker_positions=parsed.positions,
                portfolio=portfolio,
                received_at=parsed.received_at,
            )
        except AccountAllocationSnapshotError:
            raise
        except AccountIsolationError as exc:
            raise AccountAllocationBrokerageAnomaly(str(exc)) from exc
        except (
            SchwabAccountDiscoveryError,
            SchwabMarketDataAuthorizationError,
            SchwabOAuthError,
            SchwabSetupError,
            ShadowStateError,
        ) as exc:
            raise AccountAllocationSnapshotError(
                "Fresh bound account allocation evidence failed closed."
            ) from exc
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AccountAllocationSnapshotError(
                "Fresh account allocation evidence was malformed."
            ) from exc


class AccountAllocationContextSource(Protocol):
    def capture_context(self) -> AccountAllocationContext: ...


class FreshAccountAllocationSource:
    """Build a new allocation decision from a fresh context on every request."""

    def __init__(
        self,
        *,
        policy: AccountAllocationPolicy,
        snapshot_source: AccountAllocationContextSource | None = None,
    ) -> None:
        self.policy = policy
        self.snapshot_source = snapshot_source or SchwabAccountPortfolioSnapshotSource()

    def allocate(
        self,
        *,
        symbol: str,
        trade_plan_id: str,
        entry_price: float | None,
        stop_price: float | None,
        target_price: float | None,
        decision_at: datetime,
    ) -> AccountAllocationDecision:
        del symbol
        context = self.snapshot_source.capture_context()
        return build_account_allocation_decision(
            trade_plan_id=trade_plan_id,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            policy=self.policy,
            context=context,
            decision_at=decision_at,
        )


def parse_schwab_account_snapshot(
    response: SchwabAccountSnapshotResponse,
    *,
    binding: SchwabAccountBinding,
) -> ParsedSchwabAccountSnapshot:
    payload = response.payload
    if not isinstance(payload, Mapping):
        raise AccountAllocationSnapshotResponseError(
            "Account allocation response had an invalid shape."
        )
    account = payload.get("securitiesAccount")
    if not isinstance(account, Mapping):
        raise AccountAllocationSnapshotResponseError(
            "Account allocation response omitted securitiesAccount."
        )
    account_type = account.get("type")
    account_number = account.get("accountNumber")
    if not isinstance(account_type, str) or account_type.upper() != "CASH":
        raise AccountIsolationError(
            "Account allocation response was not the bound cash account."
        )
    if not isinstance(account_number, str) or len(account_number.strip()) < 4:
        raise AccountAllocationSnapshotResponseError(
            "Account allocation response omitted account identity."
        )
    ending = account_number.strip()[-4:]
    if ending != binding.account_number_last_four:
        raise AccountIsolationError(
            "Account allocation response did not match the bound account ending."
        )

    current_balances = account.get("currentBalances")
    if not isinstance(current_balances, Mapping):
        raise AccountAllocationSnapshotResponseError(
            "Account allocation response omitted current balances."
        )
    cash_available = required_nonnegative_number(
        current_balances,
        "cashAvailableForTrading",
    )
    liquidation_value = required_nonnegative_number(
        current_balances,
        "liquidationValue",
    )
    buying_power_raw = current_balances.get("buyingPower", cash_available)
    buying_power = nonnegative_number(
        buying_power_raw,
        field="buyingPower",
    )

    raw_positions = account.get("positions")
    if raw_positions is None:
        raw_positions = []
    if not isinstance(raw_positions, list):
        raise AccountAllocationSnapshotResponseError(
            "Account allocation positions had an invalid shape."
        )
    positions = tuple(
        parse_schwab_position(item, binding=binding)
        for item in raw_positions
    )
    authorized = SchwabAuthorizedAccount(
        account_hash=binding.account_hash,
        account_number_last_four=binding.account_number_last_four,
        account_type=EXPECTED_ACCOUNT_TYPE,
        cash_only=True,
    )
    balances = SchwabBalances(
        account_hash=binding.account_hash,
        cash_available=cash_available,
        buying_power=buying_power,
        liquidation_value=liquidation_value,
        as_of=aware_datetime(
            response.provider_timestamp,
            field="provider timestamp",
        ).isoformat(),
    )
    return ParsedSchwabAccountSnapshot(
        authorized_account=authorized,
        balances=balances,
        positions=positions,
        received_at=aware_datetime(response.received_at, field="receipt timestamp"),
    )


def parse_schwab_position(
    payload: object,
    *,
    binding: SchwabAccountBinding,
) -> SchwabPosition:
    if not isinstance(payload, Mapping):
        raise AccountAllocationSnapshotResponseError(
            "Account allocation response contained an invalid position."
        )
    instrument = payload.get("instrument")
    if not isinstance(instrument, Mapping):
        raise AccountAllocationSnapshotResponseError(
            "Account allocation position omitted its instrument."
        )
    symbol = str(instrument.get("symbol", "")).strip().upper()
    if not symbol:
        raise AccountAllocationSnapshotResponseError(
            "Account allocation position omitted its symbol."
        )
    long_quantity = nonnegative_number(
        payload.get("longQuantity", 0.0),
        field="longQuantity",
    )
    short_quantity = nonnegative_number(
        payload.get("shortQuantity", 0.0),
        field="shortQuantity",
    )
    if long_quantity > 0 and short_quantity > 0:
        raise AccountAllocationSnapshotResponseError(
            "Account allocation position had contradictory long and short quantities."
        )
    quantity = long_quantity - short_quantity
    if quantity == 0:
        raise AccountAllocationSnapshotResponseError(
            "Account allocation position had zero quantity."
        )
    average_price = nonnegative_number(
        payload.get("averagePrice"),
        field="averagePrice",
    )
    market_value = finite_number(payload.get("marketValue"), field="marketValue")
    return SchwabPosition(
        account_hash=binding.account_hash,
        symbol=symbol,
        quantity=quantity,
        average_price=average_price,
        market_value=market_value,
    )


def load_shadow_portfolio_snapshot(
    observed_at: datetime,
    *,
    state_path: Path = SHADOW_STATE_PATH,
) -> AccountPortfolioSnapshot:
    state = ShadowStateStore(state_path).load()
    return build_shadow_portfolio_snapshot(state, observed_at=observed_at)


def build_shadow_portfolio_snapshot(
    state: ShadowTradingState,
    *,
    observed_at: datetime,
) -> AccountPortfolioSnapshot:
    captured_at = aware_datetime(observed_at, field="portfolio timestamp")
    active = tuple(
        trade
        for trade in state.trades
        if trade.status in ACTIVE_TRADE_STATES and trade.outcome is None
    )
    committed_risk = 0.0
    committed_notional_value = 0.0
    for trade in active:
        if not trade.account_allocation_json:
            raise AccountAllocationSnapshotError(
                "Active Shadow commitment omitted frozen account allocation evidence."
            )
        try:
            allocation = account_allocation_decision_from_dict(
                json.loads(trade.account_allocation_json)
            )
        except (TypeError, ValueError) as exc:
            raise AccountAllocationSnapshotError(
                "Active Shadow commitment contained invalid allocation evidence."
            ) from exc
        if allocation.fingerprint != trade.account_allocation_fingerprint:
            raise AccountAllocationSnapshotError(
                "Active Shadow commitment allocation fingerprint did not match."
            )
        if not allocation.evidence.authorized:
            raise AccountAllocationSnapshotError(
                "Active Shadow commitment was not backed by authorized allocation evidence."
            )
        risk_per_share = allocation.evidence.risk_per_share
        if (
            risk_per_share is None
            or not math.isfinite(risk_per_share)
            or risk_per_share <= 0
        ):
            raise AccountAllocationSnapshotError(
                "Active Shadow commitment contained invalid per-share risk evidence."
            )
        quantity, notional = shadow_trade_commitment(trade)
        if quantity <= 0 or quantity > allocation.evidence.quantity:
            raise AccountAllocationSnapshotError(
                "Active Shadow commitment quantity exceeded or contradicted its allocation."
            )
        committed_risk += risk_per_share * quantity
        committed_notional_value += notional
    return AccountPortfolioSnapshot(
        committed_notional=round(committed_notional_value, 4),
        committed_open_risk=round(committed_risk, 4),
        open_position_count=len(active),
        realized_pnl_today=realized_pnl_for_date(
            state.trades,
            captured_at.astimezone(CENTRAL_TZ).date().isoformat(),
        ),
        observed_at=captured_at.isoformat(),
        source=PORTFOLIO_SNAPSHOT_SOURCE,
    )


def shadow_trade_commitment(trade: object) -> tuple[int, float]:
    quantity = 0
    notional = 0.0
    position = getattr(trade, "position", None)
    if position is not None:
        position_quantity = positive_integral_quantity(
            getattr(position, "quantity", None),
            field="position quantity",
        )
        average_entry = positive_number(
            getattr(position, "average_entry_price", None),
            field="position average entry",
        )
        quantity += position_quantity
        notional += position_quantity * average_entry
    order = getattr(trade, "order", None)
    if order is not None and getattr(trade, "status", "") in {
        "pending_entry",
        "partially_filled",
    }:
        remaining = getattr(order, "remaining_quantity", None)
        if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0:
            raise AccountAllocationSnapshotError(
                "Active Shadow order contained invalid remaining quantity."
            )
        if remaining:
            limit_price = positive_number(
                getattr(order, "limit_price", None),
                field="order limit price",
            )
            quantity += remaining
            notional += remaining * limit_price
    return quantity, notional


def require_expected_binding(binding: SchwabAccountBinding) -> None:
    if binding.account_number_last_four != EXPECTED_ACCOUNT_ENDING:
        raise AccountIsolationError(
            "Account allocation binding did not match the expected canary ending."
        )
    if binding.account_type != EXPECTED_ACCOUNT_TYPE:
        raise AccountIsolationError(
            "Account allocation binding was not the expected individual cash account."
        )
    if not binding.account_hash.strip():
        raise AccountIsolationError(
            "Account allocation binding omitted its opaque identity."
        )


def require_discovered_binding(
    binding: SchwabAccountBinding,
    accounts: Iterable[DiscoveredSchwabAccount],
) -> None:
    items = tuple(accounts)
    if len(items) != 1:
        raise AccountIsolationError(
            "Account allocation snapshot requires exactly one authorized account."
        )
    account = items[0]
    if (
        account.account_hash != binding.account_hash
        or account.account_number_last_four != binding.account_number_last_four
    ):
        raise AccountIsolationError(
            "Authorized Schwab account identity changed; allocation remains locked."
        )


def parse_provider_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AccountAllocationSnapshotResponseError(
            "Account allocation response omitted the provider Date header."
        )
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        raise AccountAllocationSnapshotResponseError(
            "Account allocation provider Date header was invalid."
        ) from None
    return aware_datetime(parsed, field="provider Date header")


def aware_datetime(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AccountAllocationSnapshotResponseError(
            f"Account allocation {field} must be timezone-aware."
        )
    return value.astimezone(timezone.utc)


def required_nonnegative_number(payload: Mapping[str, object], key: str) -> float:
    if key not in payload:
        raise AccountAllocationSnapshotResponseError(
            f"Account allocation response omitted {key}."
        )
    return nonnegative_number(payload[key], field=key)


def nonnegative_number(value: object, *, field: str) -> float:
    number = finite_number(value, field=field)
    if number < 0:
        raise AccountAllocationSnapshotResponseError(
            f"Account allocation {field} was negative."
        )
    return number


def positive_number(value: object, *, field: str) -> float:
    number = finite_number(value, field=field)
    if number <= 0:
        raise AccountAllocationSnapshotError(
            f"Active Shadow {field} was not positive."
        )
    return number


def positive_integral_quantity(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AccountAllocationSnapshotError(
            f"Active Shadow {field} was not a positive whole-share quantity."
        )
    return value


def finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AccountAllocationSnapshotResponseError(
            f"Account allocation {field} was not numeric."
        )
    number = float(value)
    if not math.isfinite(number):
        raise AccountAllocationSnapshotResponseError(
            f"Account allocation {field} was not finite."
        )
    return number
