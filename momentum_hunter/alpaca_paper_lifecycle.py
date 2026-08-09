from __future__ import annotations

"""Bounded, resumable Alpaca Paper lifecycle capability proof."""

import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from momentum_hunter.alpaca_paper_broker import (
    PAPER_PROBE_CONFIRMATION,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperBrokerError,
    AlpacaPaperOrder,
    AlpacaPaperOrderRequest,
    AlpacaPaperPosition,
    AlpacaPaperProviderReceipt,
    PaperOrderResolution,
    authorize_paper_capability_probe,
)
from momentum_hunter.alpaca_fractional_proof import documented_capability_registry
from momentum_hunter.alpaca_paper_onboarding import AlpacaPaperLane
from momentum_hunter.broker_capabilities import (
    CAPABILITY_CANCEL,
    CAPABILITY_CLIENT_ORDER_ID,
    CAPABILITY_FRACTIONAL_LIMIT,
    CAPABILITY_FRACTIONAL_MARKET,
    CAPABILITY_FRACTIONAL_QUANTITY,
    CAPABILITY_FRACTIONAL_REPLACE,
    CAPABILITY_FRACTIONAL_STOP,
    CAPABILITY_FRACTIONAL_STOP_LIMIT,
    CAPABILITY_PAPER_ENVIRONMENT,
    BrokerCapability,
    BrokerCapabilityRegistry,
    CapabilityState,
)
from momentum_hunter.scheduling import is_market_open_day, is_nyse_early_close
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


LIFECYCLE_SCHEMA_VERSION = 1
PAPER_LIFECYCLE_CONFIRMATION = "RUN BOUNDED ALPACA PAPER LIFECYCLE PROOF"
DEFAULT_LIFECYCLE_DIRECTORY = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "MomentumHunter"
    / "Alpaca"
    / "lifecycle-proofs"
)
_PROOF_ID_PATTERN = re.compile(r"^alpaca-paper-lifecycle-[a-f0-9]{24}$")
_SECRET_PATTERNS = (
    re.compile(r"\b(?:PK|AK)[A-Z0-9]{16,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)
_FORBIDDEN_EVIDENCE_KEYS = {
    "account_id",
    "account_number",
    "api_key",
    "authorization",
    "credential",
    "credentials",
    "key_id",
    "password",
    "secret",
    "secret_key",
    "token",
}


class AlpacaPaperLifecycleError(RuntimeError):
    pass


class AlpacaPaperLifecycleAnomaly(AlpacaPaperLifecycleError):
    pass


@dataclass(frozen=True)
class PaperLifecyclePlan:
    schema_version: int
    proof_id: str
    created_at: str
    session_date: str
    symbol: str
    entry_notional: Decimal
    poll_attempts: int
    poll_interval_seconds: float
    entry_client_order_id: str
    stop_client_order_id: str
    stop_limit_client_order_id: str
    target_client_order_id: str
    replacement_client_order_id: str
    exit_client_order_ids: tuple[str, ...]
    fingerprint: str

    @property
    def client_order_ids(self) -> tuple[str, ...]:
        return (
            self.entry_client_order_id,
            self.stop_client_order_id,
            self.stop_limit_client_order_id,
            self.target_client_order_id,
            self.replacement_client_order_id,
            *self.exit_client_order_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "proofId": self.proof_id,
            "createdAt": self.created_at,
            "sessionDate": self.session_date,
            "symbol": self.symbol,
            "entryNotional": _decimal_text(self.entry_notional),
            "pollAttempts": self.poll_attempts,
            "pollIntervalSeconds": self.poll_interval_seconds,
            "entryClientOrderId": self.entry_client_order_id,
            "stopClientOrderId": self.stop_client_order_id,
            "stopLimitClientOrderId": self.stop_limit_client_order_id,
            "targetClientOrderId": self.target_client_order_id,
            "replacementClientOrderId": self.replacement_client_order_id,
            "exitClientOrderIds": list(self.exit_client_order_ids),
            "fingerprint": self.fingerprint,
        }


def create_lifecycle_plan(
    current_time: datetime,
    *,
    poll_attempts: int = 10,
    poll_interval_seconds: float = 1.0,
) -> PaperLifecyclePlan:
    current = _central_time(current_time)
    token = uuid4().hex[:24]
    proof_id = f"alpaca-paper-lifecycle-{token}"
    prefix = f"mh-paper-capability-lc-{token}"
    plan = PaperLifecyclePlan(
        schema_version=LIFECYCLE_SCHEMA_VERSION,
        proof_id=proof_id,
        created_at=current.astimezone(timezone.utc).isoformat(),
        session_date=current.date().isoformat(),
        symbol="SPY",
        entry_notional=Decimal("1.00"),
        poll_attempts=poll_attempts,
        poll_interval_seconds=float(poll_interval_seconds),
        entry_client_order_id=f"{prefix}-entry",
        stop_client_order_id=f"{prefix}-stop",
        stop_limit_client_order_id=f"{prefix}-stop-limit",
        target_client_order_id=f"{prefix}-target",
        replacement_client_order_id=f"{prefix}-replace",
        exit_client_order_ids=tuple(f"{prefix}-exit-{index}" for index in range(1, 4)),
        fingerprint="",
    )
    plan = PaperLifecyclePlan(**{**plan.__dict__, "fingerprint": _plan_fingerprint(plan)})
    _validate_plan(plan)
    return plan


def write_lifecycle_plan(plan: PaperLifecyclePlan, output_directory: Path) -> Path:
    _validate_plan(plan)
    _require_external_output_directory(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"{plan.proof_id}-plan.json"
    _write_exclusive(destination, plan.to_dict())
    return destination


def load_lifecycle_plan(path: Path) -> PaperLifecyclePlan:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AlpacaPaperLifecycleError("Paper lifecycle plan could not be read.") from None
    if not isinstance(payload, dict):
        raise AlpacaPaperLifecycleError("Paper lifecycle plan had invalid shape.")
    try:
        exits = payload["exitClientOrderIds"]
        if not isinstance(exits, list) or any(not isinstance(item, str) for item in exits):
            raise ValueError
        plan = PaperLifecyclePlan(
            schema_version=int(payload["schemaVersion"]),
            proof_id=str(payload["proofId"]),
            created_at=str(payload["createdAt"]),
            session_date=str(payload["sessionDate"]),
            symbol=str(payload["symbol"]),
            entry_notional=Decimal(str(payload["entryNotional"])),
            poll_attempts=int(payload["pollAttempts"]),
            poll_interval_seconds=float(payload["pollIntervalSeconds"]),
            entry_client_order_id=str(payload["entryClientOrderId"]),
            stop_client_order_id=str(payload["stopClientOrderId"]),
            stop_limit_client_order_id=str(payload["stopLimitClientOrderId"]),
            target_client_order_id=str(payload["targetClientOrderId"]),
            replacement_client_order_id=str(payload["replacementClientOrderId"]),
            exit_client_order_ids=tuple(exits),
            fingerprint=str(payload["fingerprint"]),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise AlpacaPaperLifecycleError("Paper lifecycle plan had invalid fields.") from None
    _validate_plan(plan)
    return plan


def run_paper_lifecycle_proof(
    adapter: AlpacaPaperBrokerAdapter,
    *,
    confirmation: str,
    output_directory: Path = DEFAULT_LIFECYCLE_DIRECTORY,
    plan_path: Path | None = None,
    current_time: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    if confirmation != PAPER_LIFECYCLE_CONFIRMATION:
        raise AlpacaPaperLifecycleError(
            "The exact bounded Paper lifecycle confirmation was not provided."
        )
    current = _central_time(current_time or now_central())
    _require_regular_market_hours(current)
    _require_external_output_directory(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    if plan_path is None:
        plan = create_lifecycle_plan(current)
        plan_path = write_lifecycle_plan(plan, output_directory)
    else:
        plan = load_lifecycle_plan(plan_path)
        if plan_path.resolve().parent != output_directory.resolve():
            raise AlpacaPaperLifecycleError(
                "Paper lifecycle plan and evidence directory must be identical."
            )
    if plan.session_date != current.date().isoformat():
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle plan belongs to another market session."
        )
    final_path = output_directory / f"{plan.proof_id}-final.json"
    if final_path.is_file():
        return _load_verified_final_report(final_path, plan)

    receipts: list[AlpacaPaperProviderReceipt] = []
    adapter.evidence_sink = receipts.append
    events: list[dict[str, object]] = []
    failure: str | None = None
    anomaly = False
    execution: dict[str, object] = {}
    try:
        execution = _execute_lifecycle(adapter, plan, events, sleep)
    except AlpacaPaperLifecycleAnomaly as exc:
        failure = _sanitize_text(str(exc))
        anomaly = True
    except (AlpacaPaperBrokerError, AlpacaPaperLifecycleError) as exc:
        failure = _sanitize_text(str(exc))
        _best_effort_cleanup(adapter, plan, events, sleep)

    final_positions: list[AlpacaPaperPosition] | None = None
    final_orders: list[AlpacaPaperOrder] | None = None
    try:
        final_positions = adapter.list_positions()
        final_orders = adapter.list_orders(status="open")
    except AlpacaPaperBrokerError as exc:
        if failure is None:
            failure = f"Final Paper state verification failed: {_sanitize_text(str(exc))}"
        events.append({"event": "FINAL_STATE_READ_FAILED"})
    clean = final_positions == [] and final_orders == []
    passed = failure is None and clean and bool(execution.get("exactLiquidation"))
    report: dict[str, object] = {
        "schemaVersion": LIFECYCLE_SCHEMA_VERSION,
        "proofId": plan.proof_id,
        "planFingerprint": plan.fingerprint,
        "planPath": str(plan_path),
        "attemptId": uuid4().hex,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "classification": (
            "ALPACA_PAPER_LIFECYCLE_PROVEN"
            if passed
            else "ALPACA_PAPER_LIFECYCLE_FAILED"
        ),
        "lane": AlpacaPaperLane.CANARY_REALISTIC.value,
        "provider": "ALPACA_TRADING_API",
        "environment": "PAPER_ONLY",
        "paperHostOnly": True,
        "liveHostReachable": False,
        "symbol": plan.symbol,
        "maximumEntryNotional": _decimal_text(plan.entry_notional),
        "marketSession": plan.session_date,
        "anomaly": anomaly,
        "failure": failure,
        "execution": execution,
        "events": events,
        "providerReceipts": [_receipt_dict(item) for item in receipts],
        "finalStateVerified": final_positions is not None and final_orders is not None,
        "finalPositions": None if final_positions is None else len(final_positions),
        "finalOpenOrders": None if final_orders is None else len(final_orders),
        "cleanAfterProof": clean,
        "runtimeWiring": False,
        "orderTransmissionScope": "ALPACA_PAPER_CAPABILITY_LAB_ONLY",
        "accountIdentityIncluded": False,
        "credentialValuesIncluded": False,
        "maximumEntryNotional": "1.00",
    }
    report["fingerprint"] = _report_fingerprint(report)
    _assert_sanitized(report)
    if passed:
        _write_exclusive(final_path, report)
        report["outputPath"] = str(final_path)
        return report
    attempt_path = output_directory / (
        f"{plan.proof_id}-attempt-{report['attemptId']}.json"
    )
    _write_exclusive(attempt_path, report)
    raise AlpacaPaperLifecycleError(
        f"Alpaca Paper lifecycle proof failed safely; evidence: {attempt_path}"
    )


def _execute_lifecycle(
    adapter: AlpacaPaperBrokerAdapter,
    plan: PaperLifecyclePlan,
    events: list[dict[str, object]],
    sleep: Callable[[float], None],
) -> dict[str, object]:
    position = _preflight(adapter, plan, events)
    entry_order: AlpacaPaperOrder | None = None
    if position is None:
        entry_order, position = _enter_fractional_position(adapter, plan, events, sleep)
    else:
        entry_order = adapter.try_get_order_by_client_id(plan.entry_client_order_id)
        if entry_order is None or entry_order.filled_quantity <= 0:
            raise AlpacaPaperLifecycleAnomaly(
                "Existing Paper position has no matching owned entry evidence."
            )
        events.append(_position_event("RECOVERED_EXISTING_POSITION", position))

    stop_price = _price(position.current_price * Decimal("0.50"))
    stop_limit_price = _price(stop_price * Decimal("0.98"))
    target_price = _price(position.current_price * Decimal("2.00"))
    replacement_price = _price(position.current_price * Decimal("2.10"))
    exit_authorization = authorize_paper_capability_probe(
        confirmation=PAPER_PROBE_CONFIRMATION,
        maximum_notional=plan.entry_notional,
        allowed_sides=("sell",),
        maximum_quantity=position.quantity,
    )
    stop_order = _host_and_cancel(
        adapter,
        plan,
        events,
        sleep,
        request=AlpacaPaperOrderRequest(
            symbol=plan.symbol,
            side="sell",
            order_type="stop",
            time_in_force="day",
            client_order_id=plan.stop_client_order_id,
            quantity=position.quantity,
            stop_price=stop_price,
        ),
        authorization=exit_authorization,
        label="PROTECTIVE_STOP",
    )
    stop_limit_order = _host_and_cancel(
        adapter,
        plan,
        events,
        sleep,
        request=AlpacaPaperOrderRequest(
            symbol=plan.symbol,
            side="sell",
            order_type="stop_limit",
            time_in_force="day",
            client_order_id=plan.stop_limit_client_order_id,
            quantity=position.quantity,
            stop_price=stop_price,
            limit_price=stop_limit_price,
        ),
        authorization=exit_authorization,
        label="PROTECTIVE_STOP_LIMIT",
    )
    target_request = AlpacaPaperOrderRequest(
        symbol=plan.symbol,
        side="sell",
        order_type="limit",
        time_in_force="day",
        client_order_id=plan.target_client_order_id,
        quantity=position.quantity,
        limit_price=target_price,
    )
    target_resolution = adapter.submit_order_idempotently(
        target_request,
        authorization=exit_authorization,
    )
    target_order = target_resolution.order
    events.append(_resolution_event("TARGET_HOSTED", target_resolution))
    if target_order.status == "filled":
        raise AlpacaPaperLifecycleError(
            "The deliberately distant Paper target filled unexpectedly."
        )
    replacement_resolution = adapter.replace_order_idempotently(
        target_order.order_id,
        limit_price=replacement_price,
        client_order_id=plan.replacement_client_order_id,
        authorization=exit_authorization,
    )
    replacement = replacement_resolution.order
    events.append(_resolution_event("TARGET_REPLACED", replacement_resolution))
    if replacement.status == "filled":
        raise AlpacaPaperLifecycleError(
            "The deliberately distant replacement target filled unexpectedly."
        )
    replacement = _cancel_to_terminal(
        adapter,
        replacement,
        exit_authorization,
        plan,
        events,
        sleep,
        "TARGET_REPLACEMENT",
    )
    position = _find_position(adapter.list_positions(), plan.symbol)
    if position is None:
        raise AlpacaPaperLifecycleError(
            "Paper position disappeared before exact liquidation."
        )
    liquidated, exit_orders = _liquidate_exactly(
        adapter,
        plan,
        position,
        events,
        sleep,
    )
    if not liquidated:
        raise AlpacaPaperLifecycleError(
            "Paper position remained after all bounded liquidation attempts."
        )
    return {
        "entryOrder": _order_summary(entry_order),
        "entryFilledQuantity": _decimal_text(entry_order.filled_quantity),
        "positionQuantity": _decimal_text(position.quantity),
        "protectiveStop": _order_summary(stop_order),
        "protectiveStopLimit": _order_summary(stop_limit_order),
        "targetReplacement": _order_summary(replacement),
        "exitOrders": [_order_summary(item) for item in exit_orders],
        "partialFillObserved": any(
            item.get("event") == "PARTIAL_FILL_OBSERVED" for item in events
        ),
        "restartRecoveryUsed": any(
            item.get("event") == "RECOVERED_EXISTING_POSITION"
            or (
                "resolution" in item
                and item.get("resolution") != "SUBMITTED"
            )
            for item in events
        ),
        "exactLiquidation": True,
    }


def _preflight(
    adapter: AlpacaPaperBrokerAdapter,
    plan: PaperLifecyclePlan,
    events: list[dict[str, object]],
) -> AlpacaPaperPosition | None:
    account = adapter.get_account()
    asset = adapter.get_asset(plan.symbol)
    positions = adapter.list_positions()
    open_orders = adapter.list_orders(status="open")
    if not account.usable:
        raise AlpacaPaperLifecycleAnomaly("Canary Paper account is not usable.")
    if not asset.tradable or not asset.fractionable or asset.symbol != plan.symbol:
        raise AlpacaPaperLifecycleAnomaly(
            "SPY is not active, tradable, and fractionable in Alpaca Paper."
        )
    owned_ids = set(plan.client_order_ids)
    foreign_orders = [
        order for order in open_orders if order.client_order_id not in owned_ids
    ]
    if foreign_orders:
        raise AlpacaPaperLifecycleAnomaly(
            "Canary Paper account contains an unexpected open order."
        )
    if any(item.symbol != plan.symbol for item in positions) or len(positions) > 1:
        raise AlpacaPaperLifecycleAnomaly(
            "Canary Paper account contains an unexpected position."
        )
    position = _find_position(positions, plan.symbol)
    entry_evidence = adapter.try_get_order_by_client_id(plan.entry_client_order_id)
    if (
        position is None
        and entry_evidence is None
        and (
            account.cash < plan.entry_notional
            or account.buying_power < plan.entry_notional
        )
    ):
        raise AlpacaPaperLifecycleAnomaly(
            "Canary Paper account cannot fund the bounded one-dollar proof."
        )
    if open_orders and entry_evidence is None:
        raise AlpacaPaperLifecycleAnomaly(
            "Owned Paper orders exist without the frozen entry command."
        )
    if position is None and any(
        order.client_order_id != plan.entry_client_order_id
        for order in open_orders
    ):
        raise AlpacaPaperLifecycleAnomaly(
            "Owned protective Paper order exists without an open position."
        )
    if position is not None:
        if (
            position.side != "long"
            or position.quantity <= 0
            or abs(position.market_value) > Decimal("5.00")
        ):
            raise AlpacaPaperLifecycleAnomaly(
                "Existing SPY position exceeds the bounded recovery envelope."
            )
    events.append(
        {
            "event": "PREFLIGHT_PASSED",
            "accountStatus": account.status,
            "cash": _decimal_text(account.cash),
            "buyingPower": _decimal_text(account.buying_power),
            "positions": len(positions),
            "ownedOpenOrders": len(open_orders),
            "fractionable": asset.fractionable,
        }
    )
    return position


def _enter_fractional_position(
    adapter: AlpacaPaperBrokerAdapter,
    plan: PaperLifecyclePlan,
    events: list[dict[str, object]],
    sleep: Callable[[float], None],
) -> tuple[AlpacaPaperOrder, AlpacaPaperPosition]:
    authorization = authorize_paper_capability_probe(
        confirmation=PAPER_PROBE_CONFIRMATION,
        maximum_notional=plan.entry_notional,
        allowed_sides=("buy",),
    )
    request = AlpacaPaperOrderRequest(
        symbol=plan.symbol,
        side="buy",
        order_type="market",
        time_in_force="day",
        client_order_id=plan.entry_client_order_id,
        notional=plan.entry_notional,
    )
    resolution = adapter.submit_order_idempotently(
        request,
        authorization=authorization,
    )
    order = resolution.order
    events.append(_resolution_event("ENTRY_RESOLVED", resolution))
    order = _poll_order(adapter, order, plan, events, sleep, "ENTRY")
    if order.status == "partially_filled" or (
        not order.terminal and order.filled_quantity > 0
    ):
        events.append(_order_event("PARTIAL_FILL_OBSERVED", order))
    if not order.terminal:
        order = _cancel_to_terminal(
            adapter,
            order,
            authorization,
            plan,
            events,
            sleep,
            "ENTRY_REMAINDER",
        )
    if order.filled_quantity <= 0:
        raise AlpacaPaperLifecycleError(
            f"Paper market entry produced no fill: {order.status}."
        )
    position = _find_position(adapter.list_positions(), plan.symbol)
    if position is None or position.quantity != order.filled_quantity:
        raise AlpacaPaperLifecycleError(
            "Paper position did not match the provider entry fill quantity."
        )
    events.append(_position_event("ENTRY_POSITION_CONFIRMED", position))
    return order, position


def _host_and_cancel(
    adapter: AlpacaPaperBrokerAdapter,
    plan: PaperLifecyclePlan,
    events: list[dict[str, object]],
    sleep: Callable[[float], None],
    *,
    request: AlpacaPaperOrderRequest,
    authorization,
    label: str,
) -> AlpacaPaperOrder:
    resolution = adapter.submit_order_idempotently(
        request,
        authorization=authorization,
    )
    order = resolution.order
    events.append(_resolution_event(f"{label}_HOSTED", resolution))
    if order.status == "filled":
        raise AlpacaPaperLifecycleError(
            f"The deliberately distant {label.lower()} filled unexpectedly."
        )
    return _cancel_to_terminal(
        adapter,
        order,
        authorization,
        plan,
        events,
        sleep,
        label,
    )


def _liquidate_exactly(
    adapter: AlpacaPaperBrokerAdapter,
    plan: PaperLifecyclePlan,
    position: AlpacaPaperPosition,
    events: list[dict[str, object]],
    sleep: Callable[[float], None],
) -> tuple[bool, list[AlpacaPaperOrder]]:
    orders: list[AlpacaPaperOrder] = []
    current = position
    for client_order_id in plan.exit_client_order_ids:
        authorization = authorize_paper_capability_probe(
            confirmation=PAPER_PROBE_CONFIRMATION,
            maximum_notional=plan.entry_notional,
            allowed_sides=("sell",),
            maximum_quantity=current.quantity,
        )
        request = AlpacaPaperOrderRequest(
            symbol=plan.symbol,
            side="sell",
            order_type="market",
            time_in_force="day",
            client_order_id=client_order_id,
            quantity=current.quantity,
        )
        resolution = adapter.submit_order_idempotently(
            request,
            authorization=authorization,
        )
        order = resolution.order
        events.append(_resolution_event("EXIT_RESOLVED", resolution))
        order = _poll_order(adapter, order, plan, events, sleep, "EXIT")
        if order.status == "partially_filled" or (
            not order.terminal and order.filled_quantity > 0
        ):
            events.append(_order_event("PARTIAL_FILL_OBSERVED", order))
        if not order.terminal:
            order = _cancel_to_terminal(
                adapter,
                order,
                authorization,
                plan,
                events,
                sleep,
                "EXIT_REMAINDER",
            )
        orders.append(order)
        current_position = _find_position(adapter.list_positions(), plan.symbol)
        if current_position is None:
            return True, orders
        if current_position.quantity >= current.quantity:
            raise AlpacaPaperLifecycleError(
                "Paper liquidation made no position-reducing progress."
            )
        current = current_position
    return False, orders


def _poll_order(
    adapter: AlpacaPaperBrokerAdapter,
    order: AlpacaPaperOrder,
    plan: PaperLifecyclePlan,
    events: list[dict[str, object]],
    sleep: Callable[[float], None],
    label: str,
) -> AlpacaPaperOrder:
    current = order
    for _attempt in range(plan.poll_attempts):
        if current.terminal:
            return current
        sleep(plan.poll_interval_seconds)
        current = adapter.get_order(current.order_id)
        events.append(_order_event(f"{label}_POLLED", current))
    return current


def _cancel_to_terminal(
    adapter: AlpacaPaperBrokerAdapter,
    order: AlpacaPaperOrder,
    authorization,
    plan: PaperLifecyclePlan,
    events: list[dict[str, object]],
    sleep: Callable[[float], None],
    label: str,
) -> AlpacaPaperOrder:
    current = adapter.cancel_order(order.order_id, authorization=authorization)
    events.append(_order_event(f"{label}_CANCEL_REQUESTED", current))
    current = _poll_order(adapter, current, plan, events, sleep, f"{label}_CANCEL")
    if current.status not in {"canceled", "replaced", "filled"}:
        raise AlpacaPaperLifecycleError(
            f"{label} did not reach a terminal state after cancellation."
        )
    return current


def _best_effort_cleanup(
    adapter: AlpacaPaperBrokerAdapter,
    plan: PaperLifecyclePlan,
    events: list[dict[str, object]],
    sleep: Callable[[float], None],
) -> None:
    try:
        positions = adapter.list_positions()
        open_orders = adapter.list_orders(status="open")
    except AlpacaPaperBrokerError:
        events.append({"event": "CLEANUP_STATE_UNAVAILABLE"})
        return
    owned_ids = set(plan.client_order_ids)
    for order in open_orders:
        if order.client_order_id not in owned_ids:
            events.append({"event": "CLEANUP_BLOCKED_BY_FOREIGN_ORDER"})
            return
    position = _find_position(positions, plan.symbol)
    max_quantity = position.quantity if position is not None else Decimal("1")
    authorization = authorize_paper_capability_probe(
        confirmation=PAPER_PROBE_CONFIRMATION,
        maximum_notional=plan.entry_notional,
        allowed_sides=("buy", "sell"),
        maximum_quantity=max_quantity,
    )
    for order in open_orders:
        try:
            _cancel_to_terminal(
                adapter,
                order,
                authorization,
                plan,
                events,
                sleep,
                "FAILURE_CLEANUP",
            )
        except (AlpacaPaperBrokerError, AlpacaPaperLifecycleError):
            events.append({"event": "FAILURE_CLEANUP_CANCEL_FAILED"})
            return
    position = _find_position(adapter.list_positions(), plan.symbol)
    if position is None:
        return
    try:
        liquidated, _orders = _liquidate_exactly(
            adapter,
            plan,
            position,
            events,
            sleep,
        )
        events.append({"event": "FAILURE_CLEANUP_FLAT", "success": liquidated})
    except (AlpacaPaperBrokerError, AlpacaPaperLifecycleError):
        events.append({"event": "FAILURE_CLEANUP_FLAT_FAILED"})


def _validate_plan(plan: PaperLifecyclePlan) -> None:
    if plan.schema_version != LIFECYCLE_SCHEMA_VERSION:
        raise AlpacaPaperLifecycleError("Paper lifecycle plan schema is unsupported.")
    if not _PROOF_ID_PATTERN.fullmatch(plan.proof_id):
        raise AlpacaPaperLifecycleError("Paper lifecycle proof ID is invalid.")
    try:
        datetime.fromisoformat(plan.created_at)
        datetime.fromisoformat(plan.session_date)
    except ValueError:
        raise AlpacaPaperLifecycleError("Paper lifecycle chronology is invalid.") from None
    if plan.symbol != "SPY" or plan.entry_notional != Decimal("1.00"):
        raise AlpacaPaperLifecycleError("Paper lifecycle plan exceeds its frozen scope.")
    if plan.poll_attempts < 1 or plan.poll_attempts > 30:
        raise AlpacaPaperLifecycleError("Paper lifecycle poll count is invalid.")
    if plan.poll_interval_seconds < 0 or plan.poll_interval_seconds > 5:
        raise AlpacaPaperLifecycleError("Paper lifecycle poll interval is invalid.")
    if len(plan.exit_client_order_ids) != 3:
        raise AlpacaPaperLifecycleError("Paper lifecycle exit budget is invalid.")
    if len(set(plan.client_order_ids)) != len(plan.client_order_ids):
        raise AlpacaPaperLifecycleError("Paper lifecycle client order IDs are not unique.")
    if any(
        not value.startswith("mh-paper-capability-lc-") or len(value) > 128
        for value in plan.client_order_ids
    ):
        raise AlpacaPaperLifecycleError("Paper lifecycle client order ID is invalid.")
    if plan.fingerprint != _plan_fingerprint(plan):
        raise AlpacaPaperLifecycleError("Paper lifecycle plan fingerprint is invalid.")


def _require_regular_market_hours(current: datetime) -> None:
    if not is_market_open_day(current.date()):
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle mutation is restricted to a regular market session."
        )
    close = clock_time(12, 0) if is_nyse_early_close(current.date()) else clock_time(15, 0)
    latest_start_minutes = close.hour * 60 + close.minute - 30
    current_minutes = current.hour * 60 + current.minute
    if current_minutes < 8 * 60 + 35 or current_minutes >= latest_start_minutes:
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle mutation is allowed only from 08:35 CT until 30 minutes before close."
        )


def _plan_fingerprint(plan: PaperLifecyclePlan) -> str:
    payload = plan.to_dict()
    payload.pop("fingerprint", None)
    return _sha256(payload)


def _report_fingerprint(report: dict[str, object]) -> str:
    canonical = dict(report)
    canonical.pop("fingerprint", None)
    canonical.pop("outputPath", None)
    return _sha256(canonical)


def adjudicate_lifecycle_capabilities(
    report: Mapping[str, object],
) -> BrokerCapabilityRegistry:
    """Promote only capabilities proven by a complete direct Paper lifecycle report."""

    candidate = dict(report)
    _assert_sanitized(candidate)
    if candidate.get("fingerprint") != _report_fingerprint(candidate):
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence fingerprint is invalid."
        )
    required_identity = {
        "schemaVersion": LIFECYCLE_SCHEMA_VERSION,
        "classification": "ALPACA_PAPER_LIFECYCLE_PROVEN",
        "lane": AlpacaPaperLane.CANARY_REALISTIC.value,
        "provider": "ALPACA_TRADING_API",
        "environment": "PAPER_ONLY",
        "paperHostOnly": True,
        "liveHostReachable": False,
        "anomaly": False,
        "failure": None,
        "finalStateVerified": True,
        "finalPositions": 0,
        "finalOpenOrders": 0,
        "cleanAfterProof": True,
        "runtimeWiring": False,
        "orderTransmissionScope": "ALPACA_PAPER_CAPABILITY_LAB_ONLY",
        "accountIdentityIncluded": False,
        "credentialValuesIncluded": False,
    }
    if any(candidate.get(key) != value for key, value in required_identity.items()):
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence is not a clean Paper-only final proof."
        )

    execution = _required_mapping(candidate.get("execution"), "execution")
    if execution.get("exactLiquidation") is not True:
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence does not prove exact liquidation."
        )
    symbol = str(candidate.get("symbol", "")).strip().upper()
    if not symbol:
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has no symbol."
        )
    proof_id = str(candidate.get("proofId", ""))
    plan_fingerprint = str(candidate.get("planFingerprint", ""))
    if not _PROOF_ID_PATTERN.fullmatch(proof_id) or not re.fullmatch(
        r"[0-9A-F]{64}", plan_fingerprint
    ):
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has invalid frozen identity."
        )
    command_prefix = f"mh-paper-capability-lc-{proof_id.rsplit('-', 1)[-1]}"
    entry = _required_order_summary(
        execution.get("entryOrder"),
        label="entry",
        symbol=symbol,
        side="buy",
        order_type="market",
        client_suffix="-entry",
        statuses={"filled", "canceled"},
    )
    entry_quantity = _positive_decimal(entry.get("filledQuantity"), "entry fill")
    if entry.get("clientOrderId") != f"{command_prefix}-entry":
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has a mismatched entry command ID."
        )
    position_quantity = _positive_decimal(
        execution.get("positionQuantity"), "position quantity"
    )
    if entry_quantity != position_quantity or entry_quantity == entry_quantity.to_integral_value():
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence does not prove an exact fractional position."
        )
    if _positive_decimal(execution.get("entryFilledQuantity"), "entry quantity") != entry_quantity:
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has contradictory entry quantities."
        )

    stop = _required_order_summary(
        execution.get("protectiveStop"),
        label="protective stop",
        symbol=symbol,
        side="sell",
        order_type="stop",
        client_suffix="-stop",
        statuses={"canceled"},
    )
    stop_limit = _required_order_summary(
        execution.get("protectiveStopLimit"),
        label="protective stop-limit",
        symbol=symbol,
        side="sell",
        order_type="stop_limit",
        client_suffix="-stop-limit",
        statuses={"canceled"},
    )
    replacement = _required_order_summary(
        execution.get("targetReplacement"),
        label="target replacement",
        symbol=symbol,
        side="sell",
        order_type="limit",
        client_suffix="-replace",
        statuses={"canceled"},
    )
    expected_commands = {
        "protective stop": f"{command_prefix}-stop",
        "protective stop-limit": f"{command_prefix}-stop-limit",
        "target replacement": f"{command_prefix}-replace",
    }
    for label, order in (
        ("protective stop", stop),
        ("protective stop-limit", stop_limit),
        ("target replacement", replacement),
    ):
        if (
            order.get("clientOrderId") != expected_commands[label]
            or _positive_decimal(order.get("quantity"), f"{label} quantity")
            != position_quantity
        ):
            raise AlpacaPaperLifecycleError(
                f"Paper lifecycle capability evidence has a mismatched {label} quantity."
            )
    if stop.get("stopPrice") is None:
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has no protective stop price."
        )
    if stop_limit.get("stopPrice") is None or stop_limit.get("limitPrice") is None:
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has incomplete stop-limit prices."
        )
    if replacement.get("limitPrice") is None or not replacement.get("replaces"):
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has no verified target replacement."
        )

    exits = execution.get("exitOrders")
    if not isinstance(exits, list) or not exits:
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has no liquidation orders."
        )
    exit_filled = Decimal("0")
    for index, raw_exit in enumerate(exits, start=1):
        exit_order = _required_order_summary(
            raw_exit,
            label=f"exit {index}",
            symbol=symbol,
            side="sell",
            order_type="market",
            client_suffix=None,
            statuses={"filled", "canceled"},
        )
        client_order_id = str(exit_order.get("clientOrderId", ""))
        if client_order_id != f"{command_prefix}-exit-{index}":
            raise AlpacaPaperLifecycleError(
                "Paper lifecycle capability evidence has an invalid liquidation command ID."
            )
        exit_filled += _positive_decimal(
            exit_order.get("filledQuantity"), f"exit {index} fill"
        )
    if exit_filled != position_quantity:
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence does not prove exact fractional liquidation."
        )

    _require_lifecycle_event_chain(candidate.get("events"))
    _require_provider_receipt_chain(candidate.get("providerReceipts"), symbol=symbol)

    proof = f"paper-lifecycle-proof-sha256:{candidate['fingerprint']}"
    proven_values = {
        CAPABILITY_PAPER_ENVIRONMENT: (
            "exact Paper-only lifecycle reached a verified flat final state"
        ),
        CAPABILITY_FRACTIONAL_QUANTITY: (
            f"fractional quantity {position_quantity:f} entered and liquidated exactly"
        ),
        CAPABILITY_FRACTIONAL_MARKET: (
            "fractional market entry and exact market liquidation filled"
        ),
        CAPABILITY_FRACTIONAL_LIMIT: "standalone fractional limit target was accepted",
        CAPABILITY_FRACTIONAL_STOP: "standalone fractional stop was accepted and canceled",
        CAPABILITY_FRACTIONAL_STOP_LIMIT: (
            "standalone fractional stop-limit was accepted and canceled"
        ),
        CAPABILITY_FRACTIONAL_REPLACE: "fractional limit price replacement was accepted",
        CAPABILITY_CANCEL: "fractional stop, stop-limit, and replacement orders were canceled",
        CAPABILITY_CLIENT_ORDER_ID: "frozen client order IDs were preserved through the lifecycle",
    }
    capabilities: list[BrokerCapability] = []
    for capability in documented_capability_registry().capabilities:
        value = proven_values.get(capability.name)
        if value is None:
            capabilities.append(capability)
            continue
        capabilities.append(
            BrokerCapability(
                capability.name,
                CapabilityState.PROVEN,
                value,
                (proof, *capability.evidence),
            )
        )
    return BrokerCapabilityRegistry.build(
        provider="ALPACA_TRADING_API",
        environment="PAPER_ONLY",
        capabilities=capabilities,
    )


def _required_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AlpacaPaperLifecycleError(
            f"Paper lifecycle capability evidence has invalid {label}."
        )
    return dict(value)


def _positive_decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception:
        raise AlpacaPaperLifecycleError(
            f"Paper lifecycle capability evidence has invalid {label}."
        ) from None
    if not result.is_finite() or result <= 0:
        raise AlpacaPaperLifecycleError(
            f"Paper lifecycle capability evidence has invalid {label}."
        )
    return result


def _required_order_summary(
    value: object,
    *,
    label: str,
    symbol: str,
    side: str,
    order_type: str,
    client_suffix: str | None,
    statuses: set[str],
) -> dict[str, object]:
    order = _required_mapping(value, label)
    client_order_id = str(order.get("clientOrderId", ""))
    if (
        order.get("symbol") != symbol
        or order.get("side") != side
        or order.get("type") != order_type
        or order.get("status") not in statuses
        or order.get("requestIdPresent") is not True
        or not str(order.get("orderId", "")).strip()
        or not client_order_id
        or (client_suffix is not None and not client_order_id.endswith(client_suffix))
    ):
        raise AlpacaPaperLifecycleError(
            f"Paper lifecycle capability evidence has invalid {label} order evidence."
        )
    return order


def _require_lifecycle_event_chain(value: object) -> None:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has invalid events."
        )
    names = [str(item.get("event", "")) for item in value]
    entry_event = (
        "ENTRY_RESOLVED"
        if "ENTRY_RESOLVED" in names
        else "RECOVERED_EXISTING_POSITION"
    )
    required = (
        "PREFLIGHT_PASSED",
        entry_event,
        "PROTECTIVE_STOP_HOSTED",
        "PROTECTIVE_STOP_CANCEL_REQUESTED",
        "PROTECTIVE_STOP_LIMIT_HOSTED",
        "PROTECTIVE_STOP_LIMIT_CANCEL_REQUESTED",
        "TARGET_HOSTED",
        "TARGET_REPLACED",
        "TARGET_REPLACEMENT_CANCEL_REQUESTED",
        "EXIT_RESOLVED",
    )
    cursor = -1
    for event in required:
        try:
            cursor = names.index(event, cursor + 1)
        except ValueError:
            raise AlpacaPaperLifecycleError(
                f"Paper lifecycle capability evidence is missing event {event}."
            ) from None


def _require_provider_receipt_chain(value: object, *, symbol: str) -> None:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has no direct provider receipts."
        )
    mutation_counts = {"POST": 0, "PATCH": 0, "DELETE": 0}
    observed_reads: set[str] = set()
    for raw_receipt in value:
        receipt = dict(raw_receipt)
        method = str(receipt.get("method", "")).upper()
        path = str(receipt.get("path", ""))
        status = receipt.get("httpStatus")
        try:
            from momentum_hunter.alpaca_paper_broker import _require_allowed_request

            _require_allowed_request(method, path)
        except Exception:
            raise AlpacaPaperLifecycleError(
                "Paper lifecycle capability evidence contains a non-Paper request path."
            ) from None
        expected = {
            "POST": {200},
            "PATCH": {200},
            "DELETE": {204},
            "GET": {200, 404},
        }
        if method not in expected or status not in expected[method]:
            raise AlpacaPaperLifecycleError(
                "Paper lifecycle capability evidence contains an unsuccessful provider receipt."
            )
        if not str(receipt.get("receivedAt", "")).strip():
            raise AlpacaPaperLifecycleError(
                "Paper lifecycle capability evidence contains an undated provider receipt."
            )
        if method in mutation_counts:
            mutation_counts[method] += 1
        elif method == "GET":
            if path in {
                "/v2/account",
                "/v2/positions",
                "/v2/orders",
                "/v2/orders:by_client_order_id",
                f"/v2/assets/{symbol}",
            }:
                observed_reads.add(path)
    if (
        mutation_counts["POST"] < 4
        or mutation_counts["PATCH"] < 1
        or mutation_counts["DELETE"] < 3
        or observed_reads
        != {
            "/v2/account",
            "/v2/positions",
            "/v2/orders",
            "/v2/orders:by_client_order_id",
            f"/v2/assets/{symbol}",
        }
    ):
        raise AlpacaPaperLifecycleError(
            "Paper lifecycle capability evidence has an incomplete provider mutation chain."
        )


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _write_exclusive(path: Path, payload: dict[str, object]) -> None:
    _assert_sanitized(payload)
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    except FileExistsError:
        raise AlpacaPaperLifecycleError(
            "Conflicting Paper lifecycle evidence already exists."
        ) from None


def _load_verified_final_report(
    path: Path,
    plan: PaperLifecyclePlan,
) -> dict[str, object]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise AlpacaPaperLifecycleError(
            "Existing Paper lifecycle final evidence is unreadable."
        ) from None
    if (
        not isinstance(report, dict)
        or report.get("classification") != "ALPACA_PAPER_LIFECYCLE_PROVEN"
        or report.get("planFingerprint") != plan.fingerprint
        or report.get("fingerprint") != _report_fingerprint(report)
    ):
        raise AlpacaPaperLifecycleError(
            "Existing Paper lifecycle final evidence conflicts with the plan."
        )
    _assert_sanitized(report)
    report["outputPath"] = str(path)
    return report


def _require_external_output_directory(path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    try:
        path.resolve().relative_to(repository)
    except ValueError:
        return
    raise AlpacaPaperLifecycleError(
        "Paper lifecycle evidence must be stored outside the repository."
    )


def _assert_sanitized(value: object) -> None:
    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                normalized = str(key).strip().lower()
                if normalized in _FORBIDDEN_EVIDENCE_KEYS:
                    raise AlpacaPaperLifecycleError(
                        "Paper lifecycle evidence contains a forbidden secret field."
                    )
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            for pattern in _SECRET_PATTERNS:
                if pattern.search(item):
                    raise AlpacaPaperLifecycleError(
                        "Paper lifecycle evidence contains a credential-shaped value."
                    )

    visit(value)


def _receipt_dict(receipt: AlpacaPaperProviderReceipt) -> dict[str, object]:
    return {
        "method": receipt.method,
        "path": receipt.path,
        "httpStatus": receipt.http_status,
        "requestId": receipt.request_id,
        "requestIdPresent": receipt.request_id_present,
        "receivedAt": receipt.received_at,
        "payload": receipt.payload,
    }


def _resolution_event(event: str, resolution: PaperOrderResolution) -> dict[str, object]:
    result = _order_event(event, resolution.order)
    result["resolution"] = resolution.state.value
    return result


def _order_event(event: str, order: AlpacaPaperOrder) -> dict[str, object]:
    return {"event": event, **_order_summary(order)}


def _order_summary(order: AlpacaPaperOrder) -> dict[str, object]:
    return {
        "orderId": order.order_id,
        "clientOrderId": order.client_order_id,
        "symbol": order.symbol,
        "side": order.side,
        "type": order.order_type,
        "status": order.status,
        "quantity": _optional_decimal_text(order.quantity),
        "notional": _optional_decimal_text(order.notional),
        "filledQuantity": _decimal_text(order.filled_quantity),
        "filledAveragePrice": _optional_decimal_text(order.filled_average_price),
        "limitPrice": _optional_decimal_text(order.limit_price),
        "stopPrice": _optional_decimal_text(order.stop_price),
        "submittedAt": order.submitted_at,
        "updatedAt": order.updated_at,
        "filledAt": order.filled_at,
        "canceledAt": order.canceled_at,
        "replacedAt": order.replaced_at,
        "replacedBy": order.replaced_by,
        "replaces": order.replaces,
        "requestIdPresent": order.request_id_present,
    }


def _position_event(event: str, position: AlpacaPaperPosition) -> dict[str, object]:
    return {
        "event": event,
        "symbol": position.symbol,
        "quantity": _decimal_text(position.quantity),
        "side": position.side,
        "averageEntryPrice": _decimal_text(position.average_entry_price),
        "marketValue": _decimal_text(position.market_value),
        "currentPrice": _decimal_text(position.current_price),
    }


def _find_position(
    positions: list[AlpacaPaperPosition],
    symbol: str,
) -> AlpacaPaperPosition | None:
    matches = [item for item in positions if item.symbol == symbol]
    if len(matches) > 1:
        raise AlpacaPaperLifecycleAnomaly(
            "Paper provider returned duplicate positions for one symbol."
        )
    return matches[0] if matches else None


def _price(value: Decimal) -> Decimal:
    return max(Decimal("0.01"), value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _central_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise AlpacaPaperLifecycleError("Paper lifecycle clock must be timezone-aware.")
    return value.astimezone(CENTRAL_TZ)


def _sanitize_text(value: str) -> str:
    sanitized = value.replace("\r", " ").replace("\n", " ").strip()
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    return sanitized[:500]


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_text(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded, resumable Alpaca Paper lifecycle capability proof."
    )
    parser.add_argument("command", choices=("run", "resume"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LIFECYCLE_DIRECTORY)
    args = parser.parse_args(argv)
    if args.command == "resume" and args.plan is None:
        parser.error("resume requires --plan")
    if args.command == "run" and args.plan is not None:
        parser.error("run does not accept --plan")
    confirmation = input(
        f"Type {PAPER_LIFECYCLE_CONFIRMATION} to run the bounded Alpaca Paper "
        "lifecycle proof: "
    )
    adapter = AlpacaPaperBrokerAdapter(lane=AlpacaPaperLane.CANARY_REALISTIC)
    try:
        report = run_paper_lifecycle_proof(
            adapter,
            confirmation=confirmation,
            output_directory=args.output_dir,
            plan_path=args.plan,
        )
    except (AlpacaPaperBrokerError, AlpacaPaperLifecycleError) as exc:
        print(f"Alpaca Paper lifecycle proof stopped safely: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
