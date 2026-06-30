from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import uuid4

from momentum_hunter.time_utils import now_central


@dataclass(frozen=True)
class BrokerAdapterMetadata:
    adapter_name: str
    mode: str
    capabilities: list[str]
    order_transmit_allowed: bool
    credential_status: str
    last_health_check: str


@dataclass(frozen=True)
class BrokerAccount:
    account_id: str
    buying_power: float
    mode: str


@dataclass(frozen=True)
class BrokerPosition:
    ticker: str
    quantity: int
    average_price: float
    mode: str


@dataclass(frozen=True)
class BrokerOrderRequest:
    ticker: str
    side: str
    quantity: int
    order_type: str
    limit_price: float | None
    trade_plan_id: str
    risk_result_id: str


@dataclass(frozen=True)
class BrokerOrder:
    order_id: str
    ticker: str
    side: str
    quantity: int
    order_type: str
    limit_price: float | None
    status: str
    filled_quantity: int = 0
    average_fill_price: float | None = None
    created_at: str = ""
    updated_at: str = ""
    reason: str = ""
    trade_plan_id: str = ""
    risk_result_id: str = ""


class BrokerAdapter(ABC):
    @property
    @abstractmethod
    def metadata(self) -> BrokerAdapterMetadata:
        raise NotImplementedError

    @abstractmethod
    def get_account(self) -> BrokerAccount:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError

    @abstractmethod
    def preview_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def get_order_status(self, order_id: str) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def list_orders(self) -> list[BrokerOrder]:
        raise NotImplementedError


class FakeBrokerAdapter(BrokerAdapter):
    def __init__(
        self,
        *,
        buying_power: float = 100_000.0,
        reject_symbols: set[str] | None = None,
        partial_fill_symbols: set[str] | None = None,
        auto_fill: bool = True,
    ) -> None:
        self._buying_power = buying_power
        self._reject_symbols = {symbol.upper() for symbol in (reject_symbols or set())}
        self._partial_fill_symbols = {symbol.upper() for symbol in (partial_fill_symbols or set())}
        self._auto_fill = auto_fill
        self._orders: dict[str, BrokerOrder] = {}
        self._positions: dict[str, BrokerPosition] = {}
        self._health_check = now_central().isoformat()

    @property
    def metadata(self) -> BrokerAdapterMetadata:
        return BrokerAdapterMetadata(
            adapter_name="FakeBrokerAdapter",
            mode="Simulation Lab",
            capabilities=["preview_order", "submit_order", "cancel_order", "get_order_status", "list_orders"],
            order_transmit_allowed=False,
            credential_status="not required",
            last_health_check=self._health_check,
        )

    def get_account(self) -> BrokerAccount:
        return BrokerAccount(account_id="fake-simulation-account", buying_power=self._buying_power, mode="Simulation Lab")

    def get_positions(self) -> list[BrokerPosition]:
        return list(self._positions.values())

    def preview_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        return self._new_order(request, status="previewed", reason="Simulation preview only.")

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        symbol = request.ticker.upper()
        if symbol in self._reject_symbols:
            order = self._new_order(request, status="rejected", reason="FakeBroker configured rejection.")
            self._orders[order.order_id] = order
            return order
        if symbol in self._partial_fill_symbols:
            filled = max(1, request.quantity // 2)
            order = self._new_order(
                request,
                status="partially filled",
                filled_quantity=filled,
                average_fill_price=request.limit_price,
                reason="FakeBroker configured partial fill.",
            )
            self._orders[order.order_id] = order
            self._upsert_position(order)
            return order
        status = "filled" if self._auto_fill else "accepted"
        filled_quantity = request.quantity if self._auto_fill else 0
        order = self._new_order(
            request,
            status=status,
            filled_quantity=filled_quantity,
            average_fill_price=request.limit_price if self._auto_fill else None,
            reason="FakeBroker simulation order accepted.",
        )
        self._orders[order.order_id] = order
        if self._auto_fill:
            self._upsert_position(order)
        return order

    def cancel_order(self, order_id: str) -> BrokerOrder:
        order = self.get_order_status(order_id)
        if order.status in {"filled", "rejected", "cancelled"}:
            raise ValueError(f"Cannot cancel order in terminal state: {order.status}")
        updated = self._replace_order(order, status="cancelled", reason="Cancelled in FakeBroker simulation.")
        self._orders[order_id] = updated
        return updated

    def get_order_status(self, order_id: str) -> BrokerOrder:
        if order_id not in self._orders:
            raise KeyError(order_id)
        return self._orders[order_id]

    def list_orders(self) -> list[BrokerOrder]:
        return list(self._orders.values())

    def _new_order(
        self,
        request: BrokerOrderRequest,
        *,
        status: str,
        filled_quantity: int = 0,
        average_fill_price: float | None = None,
        reason: str = "",
    ) -> BrokerOrder:
        timestamp = now_central().isoformat()
        return BrokerOrder(
            order_id=f"fake-{uuid4().hex[:12]}",
            ticker=request.ticker.upper(),
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            status=status,
            filled_quantity=filled_quantity,
            average_fill_price=average_fill_price,
            created_at=timestamp,
            updated_at=timestamp,
            reason=reason,
            trade_plan_id=request.trade_plan_id,
            risk_result_id=request.risk_result_id,
        )

    def _replace_order(self, order: BrokerOrder, *, status: str, reason: str) -> BrokerOrder:
        return BrokerOrder(
            order_id=order.order_id,
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            order_type=order.order_type,
            limit_price=order.limit_price,
            status=status,
            filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price,
            created_at=order.created_at,
            updated_at=now_central().isoformat(),
            reason=reason,
            trade_plan_id=order.trade_plan_id,
            risk_result_id=order.risk_result_id,
        )

    def _upsert_position(self, order: BrokerOrder) -> None:
        if order.filled_quantity <= 0:
            return
        existing = self._positions.get(order.ticker)
        current_quantity = existing.quantity if existing else 0
        new_quantity = current_quantity + order.filled_quantity
        average_price = order.average_fill_price or order.limit_price or 0.0
        self._positions[order.ticker] = BrokerPosition(
            ticker=order.ticker,
            quantity=new_quantity,
            average_price=average_price,
            mode="Simulation Lab",
        )
