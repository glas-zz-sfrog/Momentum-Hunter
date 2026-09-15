"""Deterministic offline adapter; no network, credential or real broker path."""

from __future__ import annotations

import copy
import threading
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from momentum_hunter.native_paper_store import NativePaperError, fingerprint, identity


ENVIRONMENT = "OFFLINE_NATIVE_PAPER"
PROVIDER = "DETERMINISTIC_LOCAL_SIMULATOR"
TERMINAL_ORDERS = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})


def number(value: object, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except ArithmeticError as exc:
        raise NativePaperError("INVALID_DECIMAL") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise NativePaperError("INVALID_DECIMAL")
    return result


class OfflineExecutionAdapter(Protocol):
    """Future transport implementations require separate authorization."""

    def submit(self, request: dict) -> dict: ...
    def cancel(self, order_id: str) -> dict: ...
    def snapshot(self) -> dict: ...


class SimulatedPaperBroker:
    environment = ENVIRONMENT
    provider = PROVIDER
    order_transmit_allowed = False

    def __init__(self, namespace: str, *, restored: dict | None = None) -> None:
        if not namespace.strip():
            raise NativePaperError("SIMULATOR_NAMESPACE_REQUIRED")
        self.namespace = namespace
        self.orders: dict[str, dict] = {}
        self.closures: dict[str, dict] = {}
        self.connected = True
        self.next_submit = "ACK"
        self.cancel_accepted = True
        self.submit_calls = 0
        self.sequence = 0
        self.exit_events: list[dict] = []
        self.observations: list[dict] = []
        self._lock = threading.RLock()
        if restored is not None:
            if restored.get("namespace") != namespace or restored.get("environment") != ENVIRONMENT:
                raise NativePaperError("SIMULATOR_RESTORE_IDENTITY_MISMATCH")
            self.orders = copy.deepcopy(restored["orders"])
            self.closures = copy.deepcopy(restored.get("closures", {}))
            self.submit_calls = restored["submit_calls"]
            self.sequence = restored.get("sequence", 0)
            self.exit_events = copy.deepcopy(restored.get("exit_events", []))
            self.observations = copy.deepcopy(restored.get("observations", []))

    def submit(self, request: dict) -> dict:
        with self._lock:
            return self._submit(request)

    def _submit(self, request: dict) -> dict:
        if not self.connected:
            raise ConnectionError("SIMULATED_CONNECTION_UNAVAILABLE")
        if (request.get("environment") != ENVIRONMENT
                or request.get("namespace") != self.namespace
                or request.get("side") not in {"BUY", "SELL"}
                or not request.get("risk_decision_id")):
            raise NativePaperError("SIMULATOR_REQUEST_BOUNDARY")
        number(request["quantity"], positive=True)
        if number(request["quantity"]) != number(request["quantity"]).to_integral_value():
            raise NativePaperError("SIMULATOR_WHOLE_QUANTITY_REQUIRED")
        number(request["limit_price"], positive=True)
        if request.get("side") == "SELL":
            raise NativePaperError("STANDALONE_EXIT_AUTHORITY_UNAVAILABLE")
        protection = request.get("exit_contract")
        if protection is not None:
            from momentum_hunter.native_paper_exit import MINIMUM_EXIT_POLICY
            if (protection.get("policy") != MINIMUM_EXIT_POLICY
                    or protection.get("position_id") != request["position_id"]
                    or protection.get("trade_plan_id") != request["trade_plan_id"]
                    or protection.get("quantity_rule") != "FULL_ACTUAL_REMAINDER"
                    or not number(protection["stop"], positive=True)
                    < number(request["limit_price"]) < number(protection["target"], positive=True)):
                raise NativePaperError("INVALID_ATOMIC_PROTECTION_CONTRACT")
        oid = request["order_id"]
        if oid in self.orders:
            if self.orders[oid]["request"] != request:
                raise NativePaperError("ORDER_IDENTITY_REUSE_CONFLICT")
            return copy.deepcopy(self.orders[oid])
        self.submit_calls += 1
        mode, self.next_submit = self.next_submit, "ACK"
        if mode == "TIMEOUT_BEFORE_ACCEPT":
            raise TimeoutError("SIMULATED_SUBMIT_RESULT_UNKNOWN")
        self.orders[oid] = {
            "request": copy.deepcopy(request),
            "broker_order_id": identity("sim-order", self.namespace, oid),
            "status": "REJECTED" if mode == "REJECT" else "ACK",
            "fills": [], "revision": 1,
        }
        if protection is not None and mode != "REJECT":
            # Contingent siblings exist before any entry fill can be accepted.
            for role in ("STOP", "TARGET", "FORCED_FLAT"):
                child_id = protection[role.lower() + "_order_id"]
                child_request = {**copy.deepcopy(request), "order_id": child_id,
                                 "parent_order_id": oid, "side": "SELL", "exit_type": role,
                                 "type": {"STOP": "STOP", "TARGET": "LIMIT", "FORCED_FLAT": "MARKET"}[role],
                                 "limit_price": protection.get(role.lower(), request["limit_price"])}
                self.orders[child_id] = {
                    "request": child_request, "broker_order_id": identity("sim-order", self.namespace, child_id),
                    "status": "DORMANT", "fills": [], "revision": 1,
                    "executable_quantity": "0",
                }
        if mode in {"ACK_TIMEOUT", "DISCONNECT_AFTER_ACCEPT"}:
            if mode == "DISCONNECT_AFTER_ACCEPT":
                self.connected = False
            raise TimeoutError("SIMULATED_ACK_RESULT_UNKNOWN")
        return copy.deepcopy(self.orders[oid])

    def cancel(self, order_id: str) -> dict:
        with self._lock:
            return self._cancel(order_id)

    def _cancel(self, order_id: str) -> dict:
        if not self.connected:
            raise ConnectionError("SIMULATED_CONNECTION_UNAVAILABLE")
        order = self.orders[order_id]
        if self.cancel_accepted and order["status"] not in TERMINAL_ORDERS:
            order["status"] = "CANCELLED"
            if "executable_quantity" in order:
                order["executable_quantity"] = "0"
            order["revision"] += 1
        return copy.deepcopy(order)

    def expire(self, order_id: str) -> dict:
        with self._lock:
            order = self.orders[order_id]
            if order["status"] not in TERMINAL_ORDERS:
                order["status"] = "EXPIRED"
                if "executable_quantity" in order:
                    order["executable_quantity"] = "0"
                order["revision"] += 1
            return copy.deepcopy(order)

    def trigger_exit(self, order_id: str, *, observed_price: str, at: str) -> dict:
        """A quote trigger is separate from the later actual simulated fill price."""
        with self._lock:
            order = self.orders[order_id]
            trigger = self._exit_trigger(order, observed_price, at)
            previous = order.get("trigger")
            if previous is not None and previous != trigger:
                raise NativePaperError("EXIT_TRIGGER_ALREADY_FROZEN")
            if previous is None:
                order["trigger"] = trigger
                order["revision"] += 1
            return copy.deepcopy(trigger)

    def _exit_trigger(self, order: dict, price: str, at: str) -> dict:
        role = order["request"].get("exit_type")
        moment = datetime.fromisoformat(at)
        if (not role or moment.tzinfo is None or order["status"] in TERMINAL_ORDERS
                or number(order["executable_quantity"]) <= 0):
            raise NativePaperError("EXIT_TRIGGER_INVALID")
        observed = number(price, positive=True)
        level = number(order["request"]["limit_price"])
        if (role == "STOP" and observed > level) or (role == "TARGET" and observed < level):
            raise NativePaperError("EXIT_PRICE_NOT_AT_CANONICAL_TRIGGER")
        if moment < datetime.fromisoformat(order["request"]["created_at"]):
            raise NativePaperError("EXIT_TRIGGER_PRECEDES_INTENT")
        if any(moment < datetime.fromisoformat(fill["at"]) for value in self.orders.values() for fill in value["fills"]):
            raise NativePaperError("EXIT_TRIGGER_PRECEDES_ACQUIRED_EVIDENCE")
        if role == "FORCED_FLAT" and moment < datetime.fromisoformat(order["request"]["exit_contract"]["forced_flat_at"]):
            raise NativePaperError("CANONICAL_SESSION_DEADLINE_NOT_REACHED")
        return {"at": at, "observed_price": str(observed), "exit_type": role,
                "economic_frontier": self.sequence}

    def fill(self, order_id: str, *, fill_id: str, quantity: str, price: str, at: str) -> dict:
        with self._lock:
            return self._fill(order_id, fill_id=fill_id, quantity=quantity, price=price, at=at)

    def _fill(self, order_id: str, *, fill_id: str, quantity: str, price: str, at: str) -> dict:
        order = self.orders[order_id]
        fill = {"fill_id": fill_id, "quantity": str(number(quantity, positive=True)),
                "price": str(number(price, positive=True)), "at": at}
        if number(quantity) != number(quantity).to_integral_value() or not fill_id:
            raise NativePaperError("SIMULATOR_FILL_PROFILE_INVALID")
        existing = next((f for f in order["fills"] if f["fill_id"] == fill_id), None)
        if existing is not None:
            if {k: existing[k] for k in fill} != fill:
                raise NativePaperError("FILL_IDENTITY_REUSE_CONFLICT")
            return copy.deepcopy(order)
        if order["status"] in {"FILLED", "REJECTED"} or order_id in self.closures:
            raise NativePaperError("FILL_ON_TERMINAL_ORDER")
        moment = datetime.fromisoformat(at)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise NativePaperError("FILL_TIMESTAMP_REQUIRED")
        all_fills = [f for value in self.orders.values() for f in value["fills"]]
        if any(f["fill_id"] == fill_id for f in all_fills):
            raise NativePaperError("ECONOMIC_FILL_ID_ALREADY_USED")
        if moment < datetime.fromisoformat(order["request"].get("created_at", at)):
            raise NativePaperError("FILL_PRECEDES_ORDER")
        if any(moment < datetime.fromisoformat(f["at"]) for f in all_fills):
            raise NativePaperError("SIMULATED_EVENT_CLOCK_REGRESSION")
        role = order["request"].get("exit_type")
        trigger = None
        if role:
            if role == "FORCED_FLAT" and moment < datetime.fromisoformat(order["request"]["exit_contract"]["forced_flat_at"]):
                raise NativePaperError("CANONICAL_SESSION_DEADLINE_NOT_REACHED")
            if number(quantity) > number(order["executable_quantity"]):
                raise NativePaperError("EXIT_EXCEEDS_ACTUAL_REMAINDER")
            position = order["request"]["position_id"]
            actual = sum((number(f["quantity"]) * (1 if value["request"]["side"] == "BUY" else -1)
                          for value in self.orders.values() if value["request"]["position_id"] == position
                          for f in value["fills"]), Decimal(0))
            if number(quantity) > actual or number(order["executable_quantity"]) != actual:
                raise NativePaperError("EXIT_CAPACITY_DISAGREES_WITH_POSITION")
            level = number(order["request"]["limit_price"])
            trigger = order.get("trigger") or self._exit_trigger(order, price, at)
            if moment < datetime.fromisoformat(trigger["at"]):
                raise NativePaperError("EXIT_FILL_PRECEDES_TRIGGER")
            if role == "TARGET" and number(price) < level:
                raise NativePaperError("EXIT_PRICE_NOT_AT_CANONICAL_TRIGGER")
        elif number(price) > number(order["request"]["limit_price"]):
            raise NativePaperError("ENTRY_FILL_EXCEEDS_LIMIT")
        protection = order["request"].get("exit_contract")
        if not role and protection:
            stop = self.orders.get(protection["stop_order_id"])
            if stop is None or stop["status"] in TERMINAL_ORDERS:
                raise NativePaperError("ENTRY_FILL_WITHOUT_STOP_PROTECTION")
        total = sum((number(f["quantity"]) for f in order["fills"]), Decimal(0)) + number(quantity)
        if total > number(order["request"]["quantity"]):
            raise NativePaperError("SIMULATED_OVERFILL")
        self.sequence += 1
        fill["sequence"] = self.sequence
        prior_status = order["status"]
        requested = order.get("executable_quantity", order["request"]["quantity"])
        if trigger is not None:
            order["trigger"] = trigger
        order["fills"].append(fill)
        order["status"] = "FILLED" if total == number(order["request"]["quantity"]) else "PARTIALLY_FILLED"
        if prior_status in {"CANCELLED", "EXPIRED"} and order["status"] != "FILLED":
            order["status"] = prior_status
        order["revision"] += 1
        parent_id = order["request"].get("parent_order_id", order_id)
        parent = self.orders[parent_id]
        if parent["request"].get("exit_contract"):
            self._resize_protection(parent_id)
            if role:
                protection = parent["request"]["exit_contract"]
                remaining = self.orders[protection["stop_order_id"]]["executable_quantity"]
                self.exit_events.append({
                    "sequence": self.sequence, "trade_plan_id": protection["trade_plan_id"],
                    "position_id": protection["position_id"], "exit_intent_id": order_id,
                    "exit_type": "OTHER_CANONICAL_IF_ALREADY_DEFINED" if role == "FORCED_FLAT" else role,
                    "canonical_exit_role": role, "requested_quantity": requested,
                    "filled_quantity": quantity, "remaining_quantity": remaining,
                    "request_time": order["request"]["created_at"], "broker_event_time": at,
                    "simulated_broker_response": copy.deepcopy(fill), "reason_code": "CANONICAL_" + role,
                    "prior_state": prior_status, "new_state": order["status"],
                })
        return copy.deepcopy(order)

    def _resize_protection(self, parent_id: str) -> None:
        parent = self.orders[parent_id]
        protection = parent["request"]["exit_contract"]
        siblings = [self.orders[protection[role + "_order_id"]] for role in ("stop", "target", "forced_flat")]
        entered = sum((number(f["quantity"]) for f in parent["fills"]), Decimal(0))
        exited = sum((number(f["quantity"]) for sibling in siblings for f in sibling["fills"]), Decimal(0))
        remaining = entered - exited
        if remaining < 0:
            raise NativePaperError("POSITION_OVERSELL")
        if exited and remaining == 0 and parent["status"] not in TERMINAL_ORDERS:
            # Entry remainder cannot reopen an already closed position.
            parent["status"] = "CANCELLED"
            parent["revision"] += 1
        for sibling in siblings:
            prior = (sibling["status"], sibling["executable_quantity"])
            if sibling["status"] in {"CANCELLED", "REJECTED", "EXPIRED"}:
                if remaining > 0:
                    continue  # Never silently repair a missing protection order.
            if remaining == 0:
                sibling["status"] = "FILLED" if sibling["fills"] else ("CANCELLED" if exited else "DORMANT")
            else:
                sibling["status"] = "PARTIALLY_FILLED" if sibling["fills"] else (
                    "DORMANT" if sibling["request"]["exit_type"] == "FORCED_FLAT" else "ACK")
            sibling["executable_quantity"] = str(remaining)
            if prior != (sibling["status"], sibling["executable_quantity"]):
                sibling["revision"] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return self._snapshot()

    def _snapshot(self) -> dict:
        if not self.connected:
            raise ConnectionError("SIMULATED_CONNECTION_UNAVAILABLE")
        positions: dict[str, str] = {}
        for order in self.orders.values():
            request = order["request"]
            pid = request["position_id"]
            sign = 1 if request["side"] == "BUY" else -1
            quantity = sum((number(f["quantity"]) for f in order["fills"]), Decimal(0))
            positions[pid] = str(number(positions.get(pid, "0")) + sign * quantity)
        return {"environment": ENVIRONMENT, "namespace": self.namespace,
                "orders": copy.deepcopy(self.orders), "positions": positions,
                "closures": copy.deepcopy(self.closures),
                "sequence": self.sequence, "exit_events": copy.deepcopy(self.exit_events),
                "observations": copy.deepcopy(self.observations),
                "open_orders": sorted(oid for oid, value in self.orders.items()
                                      if value["status"] not in TERMINAL_ORDERS),
                "submit_calls": self.submit_calls}

    def seal_order(self, order_id: str, *, at: str) -> dict:
        """Separate complete-source finality; an ACK/status is not this proof."""
        with self._lock:
            return self._seal_order(order_id, at=at)

    def _seal_order(self, order_id: str, *, at: str) -> dict:
        order = self.orders[order_id]
        if order["status"] not in TERMINAL_ORDERS:
            raise NativePaperError("CANNOT_SEAL_WORKING_ORDER")
        moment = datetime.fromisoformat(at)
        if moment.tzinfo is None:
            raise NativePaperError("CLOSURE_TIMESTAMP_REQUIRED")
        if any(datetime.fromisoformat(fill["at"]) > moment for fill in order["fills"]):
            raise NativePaperError("CLOSURE_PRECEDES_FILL")
        proof = {"order_fingerprint": fingerprint(order), "closed_at": at,
                 "source_complete": True, "children_complete": True,
                 "children": [], "finality_complete": True}
        previous = self.closures.get(order_id)
        if previous is not None and previous["order_fingerprint"] != proof["order_fingerprint"]:
            raise NativePaperError("SIMULATED_CLOSURE_CONFLICT")
        self.closures.setdefault(order_id, proof)
        self.observe(order_id, kind="CLOSURE", event_at=at, known_at=at,
                     receipt_id=identity("sim-closure-receipt", order_id, at))
        return copy.deepcopy(proof)

    def observe(self, order_id: str, *, kind: str, event_at: str, known_at: str, receipt_id: str) -> None:
        """Read-side callbacks may arrive after newer economic state; no order action."""
        with self._lock:
            if kind not in {"WORKING", "ACK", "CLOSURE"} or order_id not in self.orders or not receipt_id:
                raise NativePaperError("SIMULATED_SOURCE_OBSERVATION_INVALID")
            value = {"order_id": order_id, "kind": kind, "event_at": event_at,
                     "known_at": known_at, "receipt_id": receipt_id}
            previous = next((item for item in self.observations if item["receipt_id"] == receipt_id), None)
            if previous is not None:
                if previous != value:
                    raise NativePaperError("SOURCE_RECEIPT_IDENTITY_CONFLICT")
                return
            self.observations.append(value)

    def snapshot_fingerprint(self) -> str:
        return fingerprint(self.snapshot())
