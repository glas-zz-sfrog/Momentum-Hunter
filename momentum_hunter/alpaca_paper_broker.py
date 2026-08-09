from __future__ import annotations

"""Isolated Alpaca Paper adapter for bounded capability proof only."""

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping
from urllib.parse import quote
from uuid import UUID

import requests

from momentum_hunter.alpaca_paper_onboarding import (
    ALPACA_LIVE_BASE_URL,
    ALPACA_PAPER_BASE_URL,
    AlpacaPaperAccount,
    AlpacaPaperCredentialRepository,
    AlpacaPaperCredentials,
    AlpacaPaperLane,
    parse_paper_account,
)


HTTP_TIMEOUT = (5.0, 15.0)
MAX_RESPONSE_BYTES = 256 * 1024
PAPER_PROBE_CLIENT_PREFIX = "mh-paper-capability-"
PAPER_PROBE_CONFIRMATION = "AUTHORIZE BOUNDED ALPACA PAPER CAPABILITY PROBE"
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_CLIENT_ORDER_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")
_ORDER_STATUSES = {
    "new",
    "partially_filled",
    "filled",
    "done_for_day",
    "canceled",
    "expired",
    "replaced",
    "pending_cancel",
    "pending_replace",
    "accepted",
    "pending_new",
    "accepted_for_bidding",
    "stopped",
    "rejected",
    "suspended",
    "calculated",
    "held",
}


class AlpacaPaperBrokerError(RuntimeError):
    pass


class AlpacaPaperBrokerEndpointError(AlpacaPaperBrokerError):
    pass


class AlpacaPaperBrokerRequestError(AlpacaPaperBrokerError):
    pass


class AlpacaPaperBrokerResponseError(AlpacaPaperBrokerError):
    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        provider_code: str = "UNAVAILABLE",
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.provider_code = provider_code


@dataclass(frozen=True)
class AlpacaPaperAsset:
    symbol: str
    asset_class: str
    exchange: str
    status: str
    tradable: bool
    fractionable: bool
    marginable: bool
    shortable: bool
    easy_to_borrow: bool
    attributes: tuple[str, ...]
    request_id_present: bool


@dataclass(frozen=True)
class AlpacaPaperPosition:
    symbol: str
    quantity: Decimal
    side: str
    average_entry_price: Decimal
    market_value: Decimal
    current_price: Decimal


@dataclass(frozen=True)
class AlpacaPaperOrderRequest:
    symbol: str
    side: str
    order_type: str
    time_in_force: str
    client_order_id: str
    quantity: Decimal | None = None
    notional: Decimal | None = None
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    order_class: str = "simple"
    extended_hours: bool = False

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        object.__setattr__(self, "symbol", symbol)
        if not _SYMBOL_PATTERN.fullmatch(symbol):
            raise AlpacaPaperBrokerRequestError("Paper order symbol is invalid.")
        if self.side not in {"buy", "sell"}:
            raise AlpacaPaperBrokerRequestError("Paper order side must be buy or sell.")
        if self.order_type not in {"market", "limit", "stop", "stop_limit"}:
            raise AlpacaPaperBrokerRequestError("Paper order type is not supported by this adapter.")
        if self.time_in_force != "day":
            raise AlpacaPaperBrokerRequestError("Fractional Paper proof requires day time-in-force.")
        if self.order_class != "simple":
            raise AlpacaPaperBrokerRequestError(
                "Advanced Paper order classes remain unproven and blocked."
            )
        if self.extended_hours:
            raise AlpacaPaperBrokerRequestError(
                "Extended-hours Paper execution remains unproven and blocked."
            )
        if not _CLIENT_ORDER_PATTERN.fullmatch(self.client_order_id):
            raise AlpacaPaperBrokerRequestError("Paper client order ID is invalid.")
        if (self.quantity is None) == (self.notional is None):
            raise AlpacaPaperBrokerRequestError(
                "Exactly one of quantity or notional is required."
            )
        if self.quantity is not None:
            _require_positive_decimal(self.quantity, "quantity")
            if _decimal_places(self.quantity) > 9:
                raise AlpacaPaperBrokerRequestError(
                    "Fractional quantity exceeds nine decimal places."
                )
        if self.notional is not None:
            _require_positive_decimal(self.notional, "notional")
            if _decimal_places(self.notional) > 2:
                raise AlpacaPaperBrokerRequestError(
                    "Paper notional exceeds two decimal places."
                )
            if self.order_type != "market":
                raise AlpacaPaperBrokerRequestError(
                    "Nonmarket notional orders remain contract-ambiguous and blocked."
                )
        if self.order_type in {"limit", "stop_limit"}:
            _require_optional_positive(self.limit_price, "limit price")
        elif self.limit_price is not None:
            raise AlpacaPaperBrokerRequestError(
                "Limit price is valid only for limit or stop-limit orders."
            )
        if self.order_type in {"stop", "stop_limit"}:
            _require_optional_positive(self.stop_price, "stop price")
        elif self.stop_price is not None:
            raise AlpacaPaperBrokerRequestError(
                "Stop price is valid only for stop or stop-limit orders."
            )

    @property
    def is_fractional_quantity(self) -> bool:
        return self.quantity is not None and self.quantity != self.quantity.to_integral_value()

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "symbol": self.symbol,
            "side": self.side,
            "type": self.order_type,
            "time_in_force": self.time_in_force,
            "client_order_id": self.client_order_id,
            "order_class": self.order_class,
            "extended_hours": self.extended_hours,
        }
        if self.quantity is not None:
            payload["qty"] = _decimal_text(self.quantity)
        if self.notional is not None:
            payload["notional"] = _decimal_text(self.notional)
        if self.limit_price is not None:
            payload["limit_price"] = _decimal_text(self.limit_price)
        if self.stop_price is not None:
            payload["stop_price"] = _decimal_text(self.stop_price)
        return payload


@dataclass(frozen=True)
class AlpacaPaperOrder:
    order_id: str
    client_order_id: str
    symbol: str
    asset_class: str
    side: str
    order_type: str
    order_class: str
    time_in_force: str
    status: str
    quantity: Decimal | None
    notional: Decimal | None
    filled_quantity: Decimal
    filled_average_price: Decimal | None
    limit_price: Decimal | None
    stop_price: Decimal | None
    submitted_at: str
    updated_at: str
    filled_at: str | None
    canceled_at: str | None
    replaced_at: str | None
    replaced_by: str | None
    replaces: str | None
    request_id_present: bool

    @property
    def terminal(self) -> bool:
        return self.status in {
            "filled",
            "canceled",
            "expired",
            "rejected",
            "replaced",
            "done_for_day",
        }


@dataclass(frozen=True)
class PaperCapabilityAuthorization:
    lane: AlpacaPaperLane
    maximum_notional: Decimal
    allowed_sides: tuple[str, ...]
    client_order_prefix: str = PAPER_PROBE_CLIENT_PREFIX

    def validate(self, request: AlpacaPaperOrderRequest) -> None:
        if self.lane is not AlpacaPaperLane.CANARY_REALISTIC:
            raise AlpacaPaperBrokerRequestError(
                "Paper capability mutation is enabled only for the Canary lane."
            )
        if request.side not in self.allowed_sides:
            raise AlpacaPaperBrokerRequestError(
                "Paper order side exceeds the capability authorization."
            )
        if not request.client_order_id.startswith(self.client_order_prefix):
            raise AlpacaPaperBrokerRequestError(
                "Paper order ID is outside the owned capability-proof namespace."
            )
        estimated = _maximum_request_notional(request)
        if estimated is None or estimated > self.maximum_notional:
            raise AlpacaPaperBrokerRequestError(
                "Paper order exceeds or cannot prove the authorized notional bound."
            )


def authorize_paper_capability_probe(
    *,
    confirmation: str,
    maximum_notional: Decimal = Decimal("1.00"),
    allowed_sides: tuple[str, ...] = ("buy",),
) -> PaperCapabilityAuthorization:
    if confirmation != PAPER_PROBE_CONFIRMATION:
        raise AlpacaPaperBrokerRequestError(
            "The exact bounded Paper capability confirmation was not provided."
        )
    _require_positive_decimal(maximum_notional, "maximum notional")
    if not allowed_sides or any(side not in {"buy", "sell"} for side in allowed_sides):
        raise AlpacaPaperBrokerRequestError("Paper capability sides are invalid.")
    return PaperCapabilityAuthorization(
        lane=AlpacaPaperLane.CANARY_REALISTIC,
        maximum_notional=maximum_notional,
        allowed_sides=allowed_sides,
    )


class AlpacaPaperBrokerAdapter:
    """Exact-host Paper adapter not wired into Momentum Hunter runtime."""

    def __init__(
        self,
        *,
        lane: AlpacaPaperLane,
        credentials: AlpacaPaperCredentialRepository | None = None,
        session: requests.Session | None = None,
        base_url: str = ALPACA_PAPER_BASE_URL,
        timeout: tuple[float, float] = HTTP_TIMEOUT,
    ) -> None:
        if lane is not AlpacaPaperLane.CANARY_REALISTIC:
            raise AlpacaPaperBrokerEndpointError(
                "The strategy-research adapter remains disabled in this slice."
            )
        if base_url != ALPACA_PAPER_BASE_URL or base_url == ALPACA_LIVE_BASE_URL:
            raise AlpacaPaperBrokerEndpointError(
                "The adapter is locked to the exact Alpaca Paper endpoint."
            )
        self.lane = lane
        self.credentials = credentials or AlpacaPaperCredentialRepository(lane=lane)
        if self.credentials.lane is not lane:
            raise AlpacaPaperBrokerEndpointError(
                "The credential repository belongs to another Paper lane."
            )
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.base_url = base_url
        self.timeout = timeout

    def get_account(self) -> AlpacaPaperAccount:
        payload, _request_id = self._request("GET", "/v2/account", expected=(200,))
        return parse_paper_account(payload)

    def get_asset(self, symbol: str) -> AlpacaPaperAsset:
        normalized = _normalized_symbol(symbol)
        payload, request_id = self._request(
            "GET",
            f"/v2/assets/{quote(normalized, safe='')}",
            expected=(200,),
        )
        return _parse_asset(payload, request_id_present=bool(request_id))

    def list_positions(self) -> list[AlpacaPaperPosition]:
        payload, _request_id = self._request("GET", "/v2/positions", expected=(200,))
        if not isinstance(payload, list):
            raise AlpacaPaperBrokerResponseError("Paper positions response had invalid shape.")
        return [_parse_position(item) for item in payload]

    def list_orders(
        self,
        *,
        status: str = "open",
        symbols: tuple[str, ...] = (),
    ) -> list[AlpacaPaperOrder]:
        if status not in {"open", "closed", "all"}:
            raise AlpacaPaperBrokerRequestError("Paper order status filter is invalid.")
        params: dict[str, object] = {
            "status": status,
            "limit": 500,
            "direction": "asc",
            "nested": False,
        }
        if symbols:
            params["symbols"] = ",".join(_normalized_symbol(item) for item in symbols)
        payload, request_id = self._request(
            "GET",
            "/v2/orders",
            expected=(200,),
            params=params,
        )
        if not isinstance(payload, list):
            raise AlpacaPaperBrokerResponseError("Paper orders response had invalid shape.")
        return [
            _parse_order(item, request_id_present=bool(request_id))
            for item in payload
        ]

    def get_order(self, order_id: str) -> AlpacaPaperOrder:
        normalized = _normalized_uuid(order_id, "order ID")
        payload, request_id = self._request(
            "GET",
            f"/v2/orders/{normalized}",
            expected=(200,),
        )
        return _parse_order(payload, request_id_present=bool(request_id))

    def get_order_by_client_id(self, client_order_id: str) -> AlpacaPaperOrder:
        if not _CLIENT_ORDER_PATTERN.fullmatch(client_order_id):
            raise AlpacaPaperBrokerRequestError("Paper client order ID is invalid.")
        payload, request_id = self._request(
            "GET",
            "/v2/orders:by_client_order_id",
            expected=(200,),
            params={"client_order_id": client_order_id},
        )
        return _parse_order(payload, request_id_present=bool(request_id))

    def submit_order(
        self,
        request: AlpacaPaperOrderRequest,
        *,
        authorization: PaperCapabilityAuthorization,
    ) -> AlpacaPaperOrder:
        authorization.validate(request)
        payload, request_id = self._request(
            "POST",
            "/v2/orders",
            expected=(200,),
            json_body=request.to_payload(),
        )
        order = _parse_order(payload, request_id_present=bool(request_id))
        _require_owned_order(order, authorization)
        if order.client_order_id != request.client_order_id:
            raise AlpacaPaperBrokerResponseError(
                "Paper submit response contradicted the requested client order ID."
            )
        return order

    def cancel_order(
        self,
        order_id: str,
        *,
        authorization: PaperCapabilityAuthorization,
    ) -> AlpacaPaperOrder:
        existing = self.get_order(order_id)
        _require_owned_order(existing, authorization)
        if existing.terminal:
            return existing
        self._request(
            "DELETE",
            f"/v2/orders/{existing.order_id}",
            expected=(204,),
        )
        return self.get_order(existing.order_id)

    def replace_order(
        self,
        order_id: str,
        *,
        limit_price: Decimal,
        client_order_id: str,
        authorization: PaperCapabilityAuthorization,
    ) -> AlpacaPaperOrder:
        existing = self.get_order(order_id)
        _require_owned_order(existing, authorization)
        if existing.terminal:
            raise AlpacaPaperBrokerRequestError(
                "A terminal Paper order cannot be replaced."
            )
        if existing.order_type not in {"limit", "stop_limit"}:
            raise AlpacaPaperBrokerRequestError(
                "Only an owned limit-bearing Paper order can be price-replaced."
            )
        _require_positive_decimal(limit_price, "replacement limit price")
        if not client_order_id.startswith(authorization.client_order_prefix):
            raise AlpacaPaperBrokerRequestError(
                "Replacement order ID is outside the owned capability-proof namespace."
            )
        if existing.quantity is None:
            raise AlpacaPaperBrokerRequestError(
                "Notional Paper orders require cancel/resubmit and cannot be replaced."
            )
        estimated = existing.quantity * limit_price
        if estimated > authorization.maximum_notional:
            raise AlpacaPaperBrokerRequestError(
                "Replacement would exceed the authorized Paper notional bound."
            )
        payload, request_id = self._request(
            "PATCH",
            f"/v2/orders/{existing.order_id}",
            expected=(200,),
            json_body={
                "limit_price": _decimal_text(limit_price),
                "client_order_id": client_order_id,
            },
        )
        replacement = _parse_order(payload, request_id_present=bool(request_id))
        _require_owned_order(replacement, authorization)
        if replacement.client_order_id != client_order_id:
            raise AlpacaPaperBrokerResponseError(
                "Paper replace response contradicted the replacement client order ID."
            )
        if replacement.replaces not in {None, existing.order_id}:
            raise AlpacaPaperBrokerResponseError(
                "Paper replace response contradicted the original order ID."
            )
        return replacement

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected: tuple[int, ...],
        params: Mapping[str, object] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> tuple[object | None, str]:
        if self.base_url != ALPACA_PAPER_BASE_URL:
            raise AlpacaPaperBrokerEndpointError(
                "The adapter Paper endpoint changed after construction."
            )
        _require_allowed_request(method, path)
        credentials = self.credentials.load()
        try:
            response = self.session.request(
                method,
                f"{ALPACA_PAPER_BASE_URL}{path}",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Cache-Control": "no-store",
                    "APCA-API-KEY-ID": credentials.key_id,
                    "APCA-API-SECRET-KEY": credentials.secret_key,
                },
                params=dict(params or {}),
                json=dict(json_body) if json_body is not None else None,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise AlpacaPaperBrokerResponseError(
                "The Alpaca Paper capability request failed without provider evidence."
            ) from None
        if response.is_redirect:
            raise AlpacaPaperBrokerEndpointError(
                "The Alpaca Paper adapter refused an HTTP redirect."
            )
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise AlpacaPaperBrokerResponseError(
                "The Alpaca Paper response exceeded the bounded size limit.",
                http_status=response.status_code,
            )
        if response.status_code not in expected:
            raise _provider_error(response, credentials)
        request_id = response.headers.get("X-Request-ID", "")
        if response.status_code == 204:
            return None, request_id
        try:
            return response.json(), request_id
        except ValueError:
            raise AlpacaPaperBrokerResponseError(
                "The Alpaca Paper response was not valid JSON.",
                http_status=response.status_code,
            ) from None


def _require_allowed_request(method: str, path: str) -> None:
    normalized_method = method.upper()
    exact = {
        ("GET", "/v2/account"),
        ("GET", "/v2/positions"),
        ("GET", "/v2/orders"),
        ("GET", "/v2/orders:by_client_order_id"),
        ("POST", "/v2/orders"),
    }
    if (normalized_method, path) in exact:
        return
    if re.fullmatch(r"/v2/assets/[A-Z][A-Z0-9.\-]{0,14}", path):
        if normalized_method == "GET":
            return
    if re.fullmatch(r"/v2/orders/[0-9a-fA-F\-]{36}", path):
        if normalized_method in {"GET", "PATCH", "DELETE"}:
            return
    raise AlpacaPaperBrokerEndpointError(
        "The Alpaca Paper request is outside the exact method/path allowlist."
    )


def _parse_asset(payload: object, *, request_id_present: bool) -> AlpacaPaperAsset:
    if not isinstance(payload, Mapping):
        raise AlpacaPaperBrokerResponseError("Paper asset response had invalid shape.")
    attributes = payload.get("attributes", [])
    if attributes is None:
        attributes = []
    if not isinstance(attributes, list) or any(not isinstance(item, str) for item in attributes):
        raise AlpacaPaperBrokerResponseError("Paper asset attributes had invalid shape.")
    return AlpacaPaperAsset(
        symbol=_required_text(payload, "symbol").upper(),
        asset_class=_required_text(payload, "class"),
        exchange=_required_text(payload, "exchange"),
        status=_required_text(payload, "status").lower(),
        tradable=_required_bool(payload, "tradable"),
        fractionable=_required_bool(payload, "fractionable"),
        marginable=_required_bool(payload, "marginable"),
        shortable=_required_bool(payload, "shortable"),
        easy_to_borrow=_required_bool(payload, "easy_to_borrow"),
        attributes=tuple(sorted(attributes)),
        request_id_present=request_id_present,
    )


def _parse_position(payload: object) -> AlpacaPaperPosition:
    if not isinstance(payload, Mapping):
        raise AlpacaPaperBrokerResponseError("Paper position response had invalid shape.")
    side = _required_text(payload, "side").lower()
    if side not in {"long", "short"}:
        raise AlpacaPaperBrokerResponseError("Paper position side was invalid.")
    return AlpacaPaperPosition(
        symbol=_required_text(payload, "symbol").upper(),
        quantity=_required_decimal(payload, "qty"),
        side=side,
        average_entry_price=_required_decimal(payload, "avg_entry_price"),
        market_value=_required_decimal(payload, "market_value"),
        current_price=_required_decimal(payload, "current_price"),
    )


def _parse_order(payload: object, *, request_id_present: bool) -> AlpacaPaperOrder:
    if not isinstance(payload, Mapping):
        raise AlpacaPaperBrokerResponseError("Paper order response had invalid shape.")
    status = _required_text(payload, "status").lower()
    if status not in _ORDER_STATUSES:
        raise AlpacaPaperBrokerResponseError("Paper order status was unknown.")
    raw_order_class = payload.get("order_class")
    if raw_order_class in {None, ""}:
        order_class = "simple"
    elif isinstance(raw_order_class, str) and raw_order_class.strip():
        order_class = raw_order_class.strip().lower()
    else:
        raise AlpacaPaperBrokerResponseError("Paper order class had invalid shape.")
    return AlpacaPaperOrder(
        order_id=_normalized_uuid(_required_text(payload, "id"), "provider order ID"),
        client_order_id=_required_text(payload, "client_order_id"),
        symbol=_required_text(payload, "symbol").upper(),
        asset_class=_required_text(payload, "asset_class"),
        side=_required_text(payload, "side").lower(),
        order_type=_required_text(payload, "type").lower(),
        order_class=order_class,
        time_in_force=_required_text(payload, "time_in_force").lower(),
        status=status,
        quantity=_optional_decimal(payload, "qty"),
        notional=_optional_decimal(payload, "notional"),
        filled_quantity=_required_decimal(payload, "filled_qty"),
        filled_average_price=_optional_decimal(payload, "filled_avg_price"),
        limit_price=_optional_decimal(payload, "limit_price"),
        stop_price=_optional_decimal(payload, "stop_price"),
        submitted_at=_required_text(payload, "submitted_at"),
        updated_at=_required_text(payload, "updated_at"),
        filled_at=_optional_text(payload, "filled_at"),
        canceled_at=_optional_text(payload, "canceled_at"),
        replaced_at=_optional_text(payload, "replaced_at"),
        replaced_by=_optional_text(payload, "replaced_by"),
        replaces=_optional_text(payload, "replaces"),
        request_id_present=request_id_present,
    )


def _provider_error(
    response: object,
    credentials: AlpacaPaperCredentials,
) -> AlpacaPaperBrokerResponseError:
    status_code = int(getattr(response, "status_code", 0))
    provider_code = "UNAVAILABLE"
    message = "Alpaca Paper rejected the bounded capability request."
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, Mapping):
        raw_code = payload.get("code")
        if isinstance(raw_code, (str, int)):
            provider_code = str(raw_code)[:64]
        raw_message = payload.get("message")
        if isinstance(raw_message, str):
            sanitized = _redact(raw_message[:500], credentials)
            if sanitized:
                message = f"Alpaca Paper rejected the request: {sanitized}"
    return AlpacaPaperBrokerResponseError(
        message,
        http_status=status_code,
        provider_code=provider_code,
    )


def _redact(value: str, credentials: AlpacaPaperCredentials) -> str:
    sanitized = value.replace(credentials.key_id, "[redacted]").replace(
        credentials.secret_key,
        "[redacted]",
    )
    sanitized = re.sub(r"\b(?:PK|AK)[A-Z0-9]{16,}\b", "[redacted]", sanitized)
    return sanitized.replace("\r", " ").replace("\n", " ").strip()


def _maximum_request_notional(request: AlpacaPaperOrderRequest) -> Decimal | None:
    if request.notional is not None:
        return request.notional
    if request.quantity is None:
        return None
    prices = [
        price
        for price in (request.limit_price, request.stop_price)
        if price is not None
    ]
    if not prices:
        return None
    return request.quantity * max(prices)


def _require_owned_order(
    order: AlpacaPaperOrder,
    authorization: PaperCapabilityAuthorization,
) -> None:
    if not order.client_order_id.startswith(authorization.client_order_prefix):
        raise AlpacaPaperBrokerRequestError(
            "Provider order is outside the owned capability-proof namespace."
        )


def _normalized_symbol(value: str) -> str:
    symbol = value.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise AlpacaPaperBrokerRequestError("Paper symbol is invalid.")
    return symbol


def _normalized_uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise AlpacaPaperBrokerResponseError(f"Paper {field} was invalid.") from None


def _required_text(payload: Mapping[object, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AlpacaPaperBrokerResponseError(f"Paper response omitted {field}.")
    return value.strip()


def _optional_text(payload: Mapping[object, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AlpacaPaperBrokerResponseError(f"Paper response contained invalid {field}.")
    return value.strip()


def _required_bool(payload: Mapping[object, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise AlpacaPaperBrokerResponseError(f"Paper response omitted boolean {field}.")
    return value


def _required_decimal(payload: Mapping[object, object], field: str) -> Decimal:
    value = _optional_decimal(payload, field)
    if value is None:
        raise AlpacaPaperBrokerResponseError(f"Paper response omitted numeric {field}.")
    return value


def _optional_decimal(payload: Mapping[object, object], field: str) -> Decimal | None:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise AlpacaPaperBrokerResponseError(f"Paper response contained invalid {field}.")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AlpacaPaperBrokerResponseError(f"Paper response contained invalid {field}.") from None
    if not normalized.is_finite() or not math.isfinite(float(normalized)):
        raise AlpacaPaperBrokerResponseError(f"Paper response contained nonfinite {field}.")
    return normalized


def _require_positive_decimal(value: Decimal, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise AlpacaPaperBrokerRequestError(f"Paper {field} must be a positive Decimal.")


def _require_optional_positive(value: Decimal | None, field: str) -> None:
    if value is None:
        raise AlpacaPaperBrokerRequestError(f"Paper {field} is required.")
    _require_positive_decimal(value, field)


def _decimal_places(value: Decimal) -> int:
    return max(0, -value.as_tuple().exponent)


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
