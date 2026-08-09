from __future__ import annotations

"""Bounded direct proof of Alpaca Paper fractional order capabilities."""

import argparse
import hashlib
import inspect
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable
from uuid import uuid4

from momentum_hunter.alpaca_paper_broker import (
    PAPER_PROBE_CONFIRMATION,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperBrokerError,
    AlpacaPaperOrder,
    AlpacaPaperOrderRequest,
    authorize_paper_capability_probe,
)
from momentum_hunter.alpaca_paper_onboarding import AlpacaPaperLane
from momentum_hunter.broker_capabilities import (
    CAPABILITY_BROKER_RESIDENT_PROTECTION,
    CAPABILITY_CANCEL,
    CAPABILITY_CLIENT_ORDER_ID,
    CAPABILITY_EXTENDED_HOURS,
    CAPABILITY_FRACTIONAL_BRACKET,
    CAPABILITY_FRACTIONAL_LIMIT,
    CAPABILITY_FRACTIONAL_MARKET,
    CAPABILITY_FRACTIONAL_OCO,
    CAPABILITY_FRACTIONAL_OTO,
    CAPABILITY_FRACTIONAL_PRECISION,
    CAPABILITY_FRACTIONAL_QUANTITY,
    CAPABILITY_FRACTIONAL_REPLACE,
    CAPABILITY_FRACTIONAL_STOP,
    CAPABILITY_FRACTIONAL_STOP_LIMIT,
    CAPABILITY_FRACTIONAL_TAKE_PROFIT,
    CAPABILITY_ORDER_STATUS_STREAM,
    CAPABILITY_OVERNIGHT,
    CAPABILITY_PAPER_ENVIRONMENT,
    BrokerCapability,
    BrokerCapabilityRegistry,
    CapabilityState,
)


PROOF_SCHEMA_VERSION = 1
DEFAULT_PROOF_DIRECTORY = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "MomentumHunter"
    / "Alpaca"
    / "proofs"
)
FRACTIONAL_GUIDE = "https://docs.alpaca.markets/us/v1.1/docs/fractional-trading"
CREATE_ORDER_REFERENCE = "https://docs.alpaca.markets/us/reference/postorder"
REPLACE_ORDER_REFERENCE = "https://docs.alpaca.markets/us/reference/patchorderbyorderid-1"
ORDERS_GUIDE = "https://docs.alpaca.markets/us/docs/orders-at-alpaca"
ASSET_REFERENCE = "https://docs.alpaca.markets/us/reference/get-v2-assets-symbol_or_asset_id"


class AlpacaFractionalProofError(RuntimeError):
    pass


@dataclass(frozen=True)
class FractionalLimitCancelPlan:
    symbol: str = "SPY"
    quantity: Decimal = Decimal("0.5")
    limit_price: Decimal = Decimal("2.00")
    maximum_notional: Decimal = Decimal("1.00")
    poll_attempts: int = 10
    poll_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.symbol != "SPY":
            raise AlpacaFractionalProofError(
                "The first direct Paper proof is locked to SPY."
            )
        if self.quantity != Decimal("0.5"):
            raise AlpacaFractionalProofError(
                "The first direct Paper proof is locked to 0.5 shares."
            )
        if self.limit_price != Decimal("2.00"):
            raise AlpacaFractionalProofError(
                "The first direct Paper proof is locked to a $2.00 limit."
            )
        if self.quantity * self.limit_price != self.maximum_notional:
            raise AlpacaFractionalProofError(
                "The Paper proof plan must remain exactly $1.00 notional."
            )
        if self.poll_attempts < 1 or self.poll_attempts > 30:
            raise AlpacaFractionalProofError("Paper proof poll count is invalid.")
        if self.poll_interval_seconds < 0 or self.poll_interval_seconds > 5:
            raise AlpacaFractionalProofError("Paper proof poll interval is invalid.")


def documented_capability_registry() -> BrokerCapabilityRegistry:
    documented = (FRACTIONAL_GUIDE, CREATE_ORDER_REFERENCE)
    return BrokerCapabilityRegistry.build(
        provider="ALPACA_TRADING_API",
        environment="PAPER_ONLY",
        capabilities=(
            BrokerCapability(
                CAPABILITY_PAPER_ENVIRONMENT,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "true",
                (CREATE_ORDER_REFERENCE,),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_QUANTITY,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "true",
                documented,
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_PRECISION,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "9 decimal places",
                (FRACTIONAL_GUIDE,),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_MARKET,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "day",
                documented,
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_LIMIT,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "contract conflict requires Paper proof",
                documented,
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_STOP,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "contract conflict requires Paper proof",
                documented,
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_STOP_LIMIT,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "contract conflict requires Paper proof",
                documented,
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_TAKE_PROFIT,
                CapabilityState.UNKNOWN,
                "UNKNOWN",
                (ORDERS_GUIDE,),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_BRACKET,
                CapabilityState.UNKNOWN,
                "UNKNOWN",
                (ORDERS_GUIDE,),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_OCO,
                CapabilityState.UNKNOWN,
                "UNKNOWN",
                (ORDERS_GUIDE,),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_OTO,
                CapabilityState.UNKNOWN,
                "UNKNOWN",
                (ORDERS_GUIDE,),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_REPLACE,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "quantity change documented unsupported; price behavior unproven",
                (REPLACE_ORDER_REFERENCE,),
            ),
            BrokerCapability(
                CAPABILITY_CANCEL,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "pending fractional order cancellation documented",
                (FRACTIONAL_GUIDE,),
            ),
            BrokerCapability(
                CAPABILITY_CLIENT_ORDER_ID,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "up to 128 characters",
                (CREATE_ORDER_REFERENCE,),
            ),
            BrokerCapability(
                CAPABILITY_EXTENDED_HOURS,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "limit orders only in this adapter; direct proof pending",
                (FRACTIONAL_GUIDE, ORDERS_GUIDE),
            ),
            BrokerCapability(
                CAPABILITY_OVERNIGHT,
                CapabilityState.DOCUMENTED_UNPROVEN,
                "context only; execution proof pending",
                (FRACTIONAL_GUIDE,),
            ),
            BrokerCapability(
                CAPABILITY_ORDER_STATUS_STREAM,
                CapabilityState.UNKNOWN,
                "UNKNOWN",
                (ORDERS_GUIDE,),
            ),
            BrokerCapability(
                CAPABILITY_BROKER_RESIDENT_PROTECTION,
                CapabilityState.UNKNOWN,
                "UNKNOWN",
                (ORDERS_GUIDE,),
            ),
        ),
    )


def run_readonly_capability_preflight(
    adapter: AlpacaPaperBrokerAdapter,
    *,
    symbol: str = "SPY",
) -> dict[str, object]:
    account = adapter.get_account()
    asset = adapter.get_asset(symbol)
    positions = adapter.list_positions()
    open_orders = adapter.list_orders(status="open")
    if not account.usable:
        raise AlpacaFractionalProofError("Canary Paper account is not usable.")
    if asset.symbol != symbol or asset.status != "active" or not asset.tradable:
        raise AlpacaFractionalProofError("SPY is not active and tradable in Alpaca Paper.")
    if positions:
        raise AlpacaFractionalProofError(
            "Canary Paper preflight found an unexpected existing position."
        )
    if open_orders:
        raise AlpacaFractionalProofError(
            "Canary Paper preflight found an unexpected existing open order."
        )
    return {
        "schemaVersion": PROOF_SCHEMA_VERSION,
        "mode": "ALPACA_PAPER_READ_ONLY_CAPABILITY_PREFLIGHT",
        "lane": AlpacaPaperLane.CANARY_REALISTIC.value,
        "accountStatus": account.status,
        "accountUsable": account.usable,
        "cash": _decimal_text(account.cash),
        "buyingPower": _decimal_text(account.buying_power),
        "symbol": asset.symbol,
        "assetClass": asset.asset_class,
        "assetStatus": asset.status,
        "tradable": asset.tradable,
        "fractionable": asset.fractionable,
        "assetRequestIdPresent": asset.request_id_present,
        "positions": 0,
        "openOrders": 0,
        "paperHostOnly": True,
        "liveHostReachable": False,
        "mutatingRequestAttempted": False,
        "credentialsIncluded": False,
    }


def run_fractional_limit_cancel_proof(
    adapter: AlpacaPaperBrokerAdapter,
    *,
    confirmation: str,
    output_directory: Path = DEFAULT_PROOF_DIRECTORY,
    plan: FractionalLimitCancelPlan = FractionalLimitCancelPlan(),
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    preflight = run_readonly_capability_preflight(adapter, symbol=plan.symbol)
    if not preflight["fractionable"]:
        raise AlpacaFractionalProofError("SPY is not marked fractionable by Alpaca Paper.")
    authorization = authorize_paper_capability_probe(
        confirmation=confirmation,
        maximum_notional=plan.maximum_notional,
        allowed_sides=("buy",),
    )
    proof_id = f"alpaca-frac-limit-cancel-{uuid4().hex}"
    client_order_id = f"mh-paper-capability-{uuid4().hex}"
    request = AlpacaPaperOrderRequest(
        symbol=plan.symbol,
        side="buy",
        order_type="limit",
        time_in_force="day",
        client_order_id=client_order_id,
        quantity=plan.quantity,
        limit_price=plan.limit_price,
    )
    events: list[dict[str, object]] = []
    order: AlpacaPaperOrder | None = None
    final_order: AlpacaPaperOrder | None = None
    failure: str | None = None
    try:
        order = adapter.submit_order(request, authorization=authorization)
        events.append(_order_event("SUBMITTED", order))
        looked_up = adapter.get_order_by_client_id(client_order_id)
        events.append(_order_event("LOOKED_UP_BY_CLIENT_ID", looked_up))
        if looked_up.order_id != order.order_id:
            raise AlpacaFractionalProofError(
                "Client-order lookup returned a contradictory provider order ID."
            )
        canceled = adapter.cancel_order(order.order_id, authorization=authorization)
        events.append(_order_event("CANCEL_REQUESTED", canceled))
        final_order = canceled
        for _attempt in range(plan.poll_attempts):
            if final_order.status == "canceled":
                break
            sleep(plan.poll_interval_seconds)
            final_order = adapter.get_order(order.order_id)
            events.append(_order_event("CANCEL_POLLED", final_order))
        if final_order.status != "canceled":
            raise AlpacaFractionalProofError(
                f"Fractional Paper order did not reach canceled state: {final_order.status}."
            )
    except (AlpacaPaperBrokerError, AlpacaFractionalProofError) as exc:
        failure = str(exc)
        if order is not None and (final_order is None or not final_order.terminal):
            try:
                emergency = adapter.cancel_order(
                    order.order_id,
                    authorization=authorization,
                )
                final_order = emergency
                events.append(_order_event("FAILURE_CLEANUP_CANCEL", emergency))
            except AlpacaPaperBrokerError as cleanup_exc:
                events.append(
                    {
                        "event": "FAILURE_CLEANUP_FAILED",
                        "reason": str(cleanup_exc),
                    }
                )

    final_positions = None
    final_open_orders = None
    final_state_verified = False
    try:
        final_positions = adapter.list_positions()
        final_open_orders = adapter.list_orders(status="open")
        final_state_verified = True
    except AlpacaPaperBrokerError as exc:
        final_state_failure = f"Final Paper state verification failed: {exc}"
        if failure is None:
            failure = final_state_failure
        else:
            events.append(
                {
                    "event": "FINAL_STATE_VERIFICATION_FAILED",
                    "reason": final_state_failure,
                }
            )
    clean = (
        final_state_verified
        and final_positions is not None
        and final_open_orders is not None
        and not final_positions
        and not final_open_orders
    )
    passed = (
        failure is None
        and order is not None
        and final_order is not None
        and final_order.status == "canceled"
        and order.quantity == plan.quantity
        and order.client_order_id == client_order_id
        and final_state_verified
        and clean
    )
    report: dict[str, object] = {
        "schemaVersion": PROOF_SCHEMA_VERSION,
        "proofId": proof_id,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "classification": (
            "FRACTIONAL_LIMIT_CANCEL_PROVEN" if passed else "FRACTIONAL_LIMIT_CANCEL_FAILED"
        ),
        "lane": AlpacaPaperLane.CANARY_REALISTIC.value,
        "provider": "ALPACA_TRADING_API",
        "environment": "PAPER_ONLY",
        "paperHostOnly": True,
        "liveHostReachable": False,
        "symbol": plan.symbol,
        "requestedQuantity": _decimal_text(plan.quantity),
        "requestedLimitPrice": _decimal_text(plan.limit_price),
        "maximumPaperNotional": _decimal_text(plan.maximum_notional),
        "clientOrderId": client_order_id,
        "providerOrderId": order.order_id if order is not None else None,
        "providerAcceptedFractionalQuantity": (
            order is not None and order.quantity == plan.quantity
        ),
        "terminalStatus": final_order.status if final_order is not None else None,
        "finalStateVerified": final_state_verified,
        "finalPositions": (
            len(final_positions) if final_positions is not None else None
        ),
        "finalOpenOrders": (
            len(final_open_orders) if final_open_orders is not None else None
        ),
        "cleanAfterProof": clean,
        "failure": failure,
        "events": events,
        "credentialsIncluded": False,
        "accountIdentityIncluded": False,
        "implementationFingerprint": _implementation_fingerprint(),
        "capabilityRegistryBefore": documented_capability_registry().to_dict(),
    }
    report["providerEvidenceFingerprint"] = _fingerprint(report)
    if passed:
        report["capabilityRegistryAfter"] = _proven_limit_cancel_registry(
            str(report["providerEvidenceFingerprint"])
        ).to_dict()
    report["fingerprint"] = _fingerprint(report)
    output_path = _write_once(report, output_directory)
    report["outputPath"] = str(output_path)
    if not passed:
        raise AlpacaFractionalProofError(
            f"Fractional limit/cancel proof failed safely; evidence: {output_path}"
        )
    return report


def _order_event(event: str, order: AlpacaPaperOrder) -> dict[str, object]:
    return {
        "event": event,
        "orderId": order.order_id,
        "clientOrderId": order.client_order_id,
        "symbol": order.symbol,
        "status": order.status,
        "quantity": _optional_decimal_text(order.quantity),
        "filledQuantity": _decimal_text(order.filled_quantity),
        "limitPrice": _optional_decimal_text(order.limit_price),
        "submittedAt": order.submitted_at,
        "updatedAt": order.updated_at,
        "canceledAt": order.canceled_at,
        "requestIdPresent": order.request_id_present,
    }


def _write_once(report: dict[str, object], output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / f"{report['proofId']}.json"
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    except FileExistsError:
        raise AlpacaFractionalProofError("Conflicting Paper proof output already exists.") from None
    return destination


def _fingerprint(report: dict[str, object]) -> str:
    canonical = dict(report)
    canonical.pop("fingerprint", None)
    canonical.pop("outputPath", None)
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()


def _implementation_fingerprint() -> str:
    files = {
        Path(__file__).resolve(),
        Path(inspect.getsourcefile(AlpacaPaperBrokerAdapter) or "").resolve(),
        Path(inspect.getsourcefile(BrokerCapabilityRegistry) or "").resolve(),
    }
    hasher = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.name):
        if not path.is_file():
            raise AlpacaFractionalProofError(
                "Paper proof implementation source could not be fingerprinted."
            )
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest().upper()


def _proven_limit_cancel_registry(
    provider_evidence_fingerprint: str,
) -> BrokerCapabilityRegistry:
    proof_evidence = f"paper-proof-sha256:{provider_evidence_fingerprint}"
    proven_values = {
        CAPABILITY_PAPER_ENVIRONMENT: "exact paper host authenticated and accepted order",
        CAPABILITY_FRACTIONAL_QUANTITY: "0.5 shares accepted",
        CAPABILITY_FRACTIONAL_LIMIT: "0.5 SPY shares at limit accepted",
        CAPABILITY_CANCEL: "accepted fractional limit order canceled",
        CAPABILITY_CLIENT_ORDER_ID: "provider lookup matched exact client order ID",
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
                (proof_evidence, *capability.evidence),
            )
        )
    return BrokerCapabilityRegistry.build(
        provider="ALPACA_TRADING_API",
        environment="PAPER_ONLY",
        capabilities=capabilities,
    )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_text(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded Alpaca Paper fractional capability proof."
    )
    parser.add_argument("command", choices=("readonly", "fractional-limit-cancel"))
    args = parser.parse_args(argv)
    adapter = AlpacaPaperBrokerAdapter(lane=AlpacaPaperLane.CANARY_REALISTIC)
    try:
        if args.command == "readonly":
            report = run_readonly_capability_preflight(adapter)
        else:
            confirmation = input(
                f"Type {PAPER_PROBE_CONFIRMATION} to submit and cancel one bounded "
                "fractional Alpaca Paper order: "
            )
            report = run_fractional_limit_cancel_proof(
                adapter,
                confirmation=confirmation,
            )
    except (AlpacaPaperBrokerError, AlpacaFractionalProofError) as exc:
        print(f"Alpaca Paper capability proof stopped safely: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
