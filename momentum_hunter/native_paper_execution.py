"""One disabled native Paper lifecycle; explicit offline qualification only.

Production/Science intake cannot reach the simulator. No real transport or arm
operation exists here. Offline qualification is a distinct, non-upgradable
namespace, not permission to execute a retained research decision.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable

from momentum_hunter.autonomy.ledger import ExecutionLedgerEvent
from momentum_hunter.intraday_trade_plan import (
    IntradayPlanEvidence, intraday_plan_validation_findings,
    OPENING_BREAKOUT, CONTINUATION_BREAKOUT, TERMINAL_PLAN_STATES,
)
from momentum_hunter.native_paper_broker import (
    ENVIRONMENT, PROVIDER, SimulatedPaperBroker, TERMINAL_ORDERS, number,
)
from momentum_hunter.native_paper_risk import NativePaperRiskPolicy, evaluate_native_risk
from momentum_hunter.native_paper_exit import exit_contract
from momentum_hunter.native_paper_store import (
    NativePaperError, NativePaperStore, encoded, fingerprint, identity,
)
from momentum_hunter.provider_neutral_allocation import AccountSnapshot


SAFETY_HOOKS = frozenset({"STOP_NEW_DECISIONS", "STOP_NEW_ORDERS", "CANCEL_WORKING_ORDERS",
                        "EMERGENCY_FLATTEN_PAPER", "HARD_EXECUTION_SHUTDOWN", "QUARANTINE_EXECUTION"})


def timestamp(value: str | datetime) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise NativePaperError("AWARE_TIMESTAMP_REQUIRED")
    return result


@dataclass(frozen=True)
class NativePaperConfiguration:
    paper_enabled: bool = False
    broker_enabled: bool = False
    auto_arm: bool = False
    live_enabled: bool = False

    def validate(self) -> None:
        if any(value is not False for value in asdict(self).values()):
            raise NativePaperError("EXECUTION_ACTIVATION_NOT_IMPLEMENTED")


@dataclass(frozen=True)
class OfflinePaperDecision:
    opportunity_id: str
    setup_id: str
    decision_id: str
    plan: IntradayPlanEvidence
    known_at: str
    decision_cutoff: str
    observed_price: str
    price_known_at: str
    tick_size: str
    maximum_quantity: int
    rank: int
    max_price_age_seconds: int
    source_kind: str = "OFFLINE_CONTRACT_FIXTURE"
    decision: str = "EXECUTION_READY_TRADE"

    def contract(self) -> dict:
        return json.loads(encoded({"opportunity_id": self.opportunity_id, "setup_id": self.setup_id,
                "trade_plan_id": self.plan.plan_id, "decision_id": self.decision_id,
                "symbol": self.plan.symbol, "rank": self.rank,
                "entry": str(self.plan.planned_entry), "stop": str(self.plan.stop_price),
                "target": str(self.plan.target_prices[0]) if self.plan.target_prices else "",
                "targets": list(self.plan.target_prices), "intraday": asdict(self.plan),
                "known_at": self.known_at, "decision_cutoff": self.decision_cutoff,
                "observed_price": self.observed_price, "price_known_at": self.price_known_at,
                "tick_size": self.tick_size, "maximum_quantity": self.maximum_quantity,
                "max_price_age_seconds": self.max_price_age_seconds,
                "source_kind": self.source_kind, "decision": self.decision}))


def entry_findings(decision: OfflinePaperDecision, at: datetime) -> list[str]:
    findings = []
    if type(decision) is not OfflinePaperDecision or type(decision.plan) is not IntradayPlanEvidence:
        return ["OFFLINE_TYPED_DECISION_REQUIRED"]
    if decision.source_kind != "OFFLINE_CONTRACT_FIXTURE":
        findings.append("NONQUALIFICATION_SOURCE_CANNOT_EXECUTE")
    plan = decision.plan
    findings.extend(intraday_plan_validation_findings(plan))
    if not decision.opportunity_id.strip() or not decision.setup_id.strip() or not decision.decision_id.strip():
        findings.append("AUTHORITATIVE_LINEAGE_REQUIRED")
    if decision.decision != "EXECUTION_READY_TRADE" or not plan.execution_eligible:
        findings.append("DO_NOT_TRADE")
    if plan.lifecycle_status in TERMINAL_PLAN_STATES:
        findings.append("ENTRY_PERMANENTLY_CLOSED")
    try:
        now = timestamp(at)
        if not (timestamp(plan.created_at) <= timestamp(decision.known_at)
                <= timestamp(decision.decision_cutoff) <= now
                and timestamp(decision.price_known_at) <= timestamp(decision.decision_cutoff)):
            findings.append("FUTURE_OR_REORDERED_DECISION_EVIDENCE")
        if not timestamp(plan.entry_valid_from) <= now < timestamp(plan.entry_expires_at):
            findings.append("ENTRY_WINDOW_CLOSED")
        if not timestamp(plan.created_at) <= timestamp(decision.price_known_at):
            findings.append("PRICE_PRECEDES_PLAN")
        if (type(decision.max_price_age_seconds) is not int or decision.max_price_age_seconds <= 0):
            findings.append("PRICE_FRESHNESS_POLICY_REQUIRED")
        elif (now - timestamp(decision.price_known_at)).total_seconds() > decision.max_price_age_seconds:
            findings.append("ENTRY_PRICE_STALE")
        entry = number(plan.planned_entry, positive=True)
        tick = number(decision.tick_size, positive=True)
        observed = number(decision.observed_price, positive=True)
        if entry % tick != 0:
            findings.append("ENTRY_TICK_MISMATCH")
        exit_contract(decision.contract(), position_id="validation", entry_order_id="validation")
        if observed <= number(plan.stop_price):
            findings.append("INVALIDATED")
        if plan.setup_family in {OPENING_BREAKOUT, CONTINUATION_BREAKOUT} and observed > entry:
            findings.append("DO_NOT_TRADE_MISSED_ENTRY")
    except (ValueError, TypeError, ArithmeticError):
        findings.append("ENTRY_EVIDENCE_INVALID")
    if (type(decision.maximum_quantity) is not int or not 0 < decision.maximum_quantity <= 10**12
            or type(decision.rank) is not int or decision.rank <= 0):
        findings.append("INSTRUMENT_OR_RANK_INVALID")
    return list(dict.fromkeys(findings))


class NativePaperExecutionEngine:
    """Sole owner of native trade/order/fill/position projections and audit."""

    def __init__(self, *, root: Path, namespace: str, policy: NativePaperRiskPolicy,
                 configuration: NativePaperConfiguration = NativePaperConfiguration(),
                 simulator: SimulatedPaperBroker | None = None,
                 fault: Callable[[str], None] | None = None,
                 qualification_clock: Callable[[], datetime] | None = None,
                 require_existing: bool = False) -> None:
        configuration.validate()
        policy.validate()
        if not namespace.strip():
            raise NativePaperError("EXECUTION_NAMESPACE_REQUIRED")
        if simulator is not None and (type(simulator) is not SimulatedPaperBroker
                                       or simulator.namespace != namespace):
            raise NativePaperError("ONLY_EXACT_LOCAL_SIMULATOR_ALLOWED")
        self.namespace = namespace
        self.configuration = configuration
        self.policy = policy
        self._simulator = simulator
        self._fault = fault or (lambda _: None)
        self._qualification_clock = qualification_clock
        self.store = NativePaperStore(root, binding={"schema": 1, "environment": ENVIRONMENT,
                                                     "namespace": namespace,
                                                     "configuration": asdict(configuration),
                                                     "policy": asdict(policy)}, require_existing=require_existing)
        self.store.load()

    @property
    def execution_authority(self) -> str:
        return "NONE"

    def inspect(self) -> dict:
        return self.store.load()[0]

    def _audit(self, state: dict, kind: str, at: datetime, *, trade: dict | None = None,
               reason: str = "", payload: dict | None = None) -> None:
        _, records = self.store.load()
        if records and timestamp(at) < timestamp(records[-1]["event"]["timestamp"]):
            raise NativePaperError("EXECUTION_CLOCK_REGRESSION")
        plan = trade["plan"] if trade else {}
        event = ExecutionLedgerEvent(
            event_id=identity("native-execution-event", self.namespace, str(len(records) + 1), kind),
            timestamp=timestamp(at).isoformat(), event_type=kind, mode=ENVIRONMENT,
            ticker=plan.get("symbol", ""), trade_plan_id=plan.get("trade_plan_id", ""),
            risk_result_id=(trade or {}).get("risk", {}).get("risk_decision_id", ""),
            broker_adapter=PROVIDER if self._simulator else "NONE",
            approval_state="DISABLED_OFFLINE_ONLY", requested_action=kind,
            result=(trade or {}).get("state", "DISABLED"), actor="ENGINE",
            source="native-paper-execution-v1", reason=reason, payload=payload or {})
        self.store.commit(state, event)

    def record_disabled_decision(self, *, source_identity: str, payload: dict, at: datetime) -> str:
        """Observation only; there is intentionally no path to qualification_entry."""
        with self.store.lease.transaction():
            state, _ = self.store.load()
            intent_id = identity("disabled-execution-intent", self.namespace, source_identity)
            value = {"source_identity": source_identity, "payload": copy.deepcopy(payload),
                     "state": "DISABLED", "execution_authority": "NONE"}
            existing = state["disabled_intents"].get(intent_id)
            if existing is not None:
                if fingerprint(existing) != fingerprint(value):
                    raise NativePaperError("DISABLED_DECISION_IDENTITY_CONFLICT")
                return intent_id
            state["disabled_intents"][intent_id] = value
            self._audit(state, "DISABLED_INTENT_CREATED", at, payload=value)
            return intent_id

    def record_safety_hook(self, hook: str, *, at: datetime) -> dict:
        if hook not in SAFETY_HOOKS:
            raise NativePaperError("UNKNOWN_SAFETY_HOOK")
        with self.store.lease.transaction():
            state, _ = self.store.load()
            result = {"hook": hook, "armed": False, "performed": False,
                      "status": "PRESENT_PENDING_SAFETY_QUALIFICATION"}
            state["hooks"][hook] = result
            self._audit(state, "SAFETY_HOOK_RECORDED_NOT_EXECUTED", at, payload=result)
            return result

    def qualification_entry(self, decision: OfflinePaperDecision, *, at: datetime,
                            account: AccountSnapshot | None,
                            requested_quantity: str | None = None) -> dict:
        if type(self._simulator) is not SimulatedPaperBroker:
            raise NativePaperError("OFFLINE_SIMULATOR_NOT_ATTACHED")
        with self.store.lease.transaction():
            state, _ = self.store.load()
            if state["quarantined"]:
                raise NativePaperError("EXECUTION_QUARANTINED")
            if type(decision) is not OfflinePaperDecision:
                raise NativePaperError("OFFLINE_TYPED_DECISION_REQUIRED")
            if type(decision.plan) is not IntradayPlanEvidence:
                self._audit(state, "ENTRY_REFUSED", at, reason="OFFLINE_TYPED_PLAN_REQUIRED")
                return {"state": "REJECTED", "blockers": ["OFFLINE_TYPED_PLAN_REQUIRED"]}
            plan = decision.contract()
            scope = identity("native-entry-scope", ENVIRONMENT, self.namespace,
                             decision.opportunity_id, decision.setup_id, decision.plan.plan_id, "LONG_ENTRY")
            prior = state["trades"].get(scope)
            if prior is not None:
                if fingerprint(prior["plan"]) != fingerprint(plan):
                    raise NativePaperError("CONSUMED_SCOPE_CANNOT_CHANGE_OR_REENTER")
                return copy.deepcopy(prior)
            for existing_scope in tuple(state["trades"]):
                self._reconcile_locked(state, existing_scope, at)
            if state["quarantined"]:
                raise NativePaperError("EXECUTION_QUARANTINED")
            source_fence = self._simulator.snapshot()
            if not state["trades"] and (source_fence["orders"] or any(number(q) for q in source_fence["positions"].values())):
                state["quarantined"] = True
                self._audit(state, "UNOWNED_BROKER_STATE", at, reason="MISSING_EXECUTION_CUSTODY", payload=source_fence)
                raise NativePaperError("MISSING_EXECUTION_CUSTODY")
            if any(t["state"] in {"INTENT_CREATED", "UNKNOWN", "ORDER_SUBMITTED",
                                  "PARTIALLY_FILLED", "TERMINAL_UNKNOWN", "QUARANTINED"}
                   or t["pending_receipt"] is not None for t in state["trades"].values()):
                self._audit(state, "ENTRY_REFUSED", at, reason="ACCOUNT_SOURCE_RECONCILIATION_REQUIRED")
                return {"state": "REJECTED", "blockers": ["ACCOUNT_SOURCE_RECONCILIATION_REQUIRED"]}
            findings = entry_findings(decision, at)
            if findings:
                self._audit(state, "ENTRY_REFUSED", at, reason="|".join(findings), payload=plan)
                return {"state": "REJECTED", "blockers": findings}
            risk = evaluate_native_risk(plan=plan, price=plan["entry"], at=at,
                                        account=account, policy=self.policy, namespace=self.namespace,
                                        trades=state["trades"], requested_quantity=requested_quantity)
            if number(risk["quantity"]) > decision.maximum_quantity:
                risk["authorized"] = False
                risk["blockers"].append("PROVIDER_MAXIMUM_QUANTITY_EXCEEDED")
            if not risk["authorized"]:
                self._audit(state, "RISK_REFUSED", at, payload=risk)
                return {"state": "REJECTED", "blockers": risk["blockers"]}
            order_id = identity("native-entry-order", scope, fingerprint(plan), risk["risk_decision_id"])
            position_id = identity("native-position", ENVIRONMENT, self.namespace, scope, order_id)
            protection = exit_contract(plan, position_id=position_id, entry_order_id=order_id)
            request = {"order_id": order_id, "position_id": position_id,
                       "environment": ENVIRONMENT, "namespace": self.namespace,
                       "opportunity_id": decision.opportunity_id, "setup_id": decision.setup_id,
                       "trade_plan_id": decision.plan.plan_id, "side": "BUY", "type": "LIMIT",
                       "time_in_force": "DAY", "order_class": "SIMPLE", "extended_hours": False,
                       "quantity": risk["quantity"], "limit_price": plan["entry"],
                       "risk_decision_id": risk["risk_decision_id"], "created_at": timestamp(at).isoformat(),
                       "exit_contract": protection}
            trade = {"scope": scope, "plan": plan, "risk": risk, "order_id": order_id,
                     "position_id": position_id, "quantity": risk["quantity"], "entry_price": plan["entry"],
                     "state": "INTENT_CREATED", "request": request, "broker_order": None,
                     "filled": "0", "unfilled": risk["quantity"], "closed_unfilled": "0",
                     "position_quantity": "0", "opened_at": None, "entry_cost": "0",
                     "pending_receipt": None, "source_revision": 0, "closure": None,
                     "exit_contract": protection, "exit_orders": {}, "exit_events": [],
                     "exit_filled": "0", "original_r_per_share": protection["original_r_per_share"],
                     "source_observations": [], "source_fence": fingerprint(source_fence),
                     "earliest_closure_at": None,
                     "original_r_authorized": str(number(protection["original_r_per_share"]) * number(risk["quantity"]))}
            self._fault("before_intent_persistence")
            state["trades"][scope] = trade
            self._audit(state, "INTENT_CREATED", at, trade=trade, payload=request)
            self._fault("after_intent_persistence")
            # Persist possible effect BEFORE calling even the nontransmitting adapter.
            trade["state"] = "UNKNOWN"
            self._audit(state, "SUBMISSION_MAY_EXIST", at, trade=trade)
            self._fault("before_submit")
            initiation_at = timestamp(self._qualification_clock()) if self._qualification_clock else timestamp(at)
            initiation_risk = evaluate_native_risk(
                plan=plan, price=plan["entry"], at=initiation_at, account=account,
                policy=self.policy, namespace=self.namespace,
                trades={key: value for key, value in state["trades"].items() if key != scope},
                requested_quantity=risk["quantity"])
            trade["initiation_risk_recheck"] = initiation_risk
            if (initiation_at < timestamp(at) or entry_findings(decision, initiation_at)
                    or not initiation_risk["authorized"] or initiation_risk["quantity"] != risk["quantity"]
                    or fingerprint(self._simulator.snapshot()) != trade["source_fence"]):
                trade.update(state="KNOWN_NOT_SUBMITTED", unfilled="0", closed_unfilled=trade["quantity"])
                self._audit(state, "INITIATION_FENCE_REFUSED", max(initiation_at, timestamp(at)), trade=trade,
                            reason="STALE_CURRENT_AUTHORITY_FENCE_OR_ENTRY_WINDOW")
                return copy.deepcopy(trade)
            trade["initiation_at"] = initiation_at.isoformat()
            self._audit(state, "INITIATION_AUTHORITY_VALIDATED", initiation_at, trade=trade,
                        payload={"original_risk_decision_id": risk["risk_decision_id"],
                                 "current_check": initiation_risk})
            try:
                response = self._simulator.submit(request)
            except (ConnectionError, TimeoutError) as exc:
                self._audit(state, "SUBMISSION_UNKNOWN", initiation_at, trade=trade, reason=str(exc))
                return copy.deepcopy(trade)
            self._fault("after_ack")
            self._audit(state, "SIMULATOR_RESPONSE_OBSERVED", initiation_at, trade=trade, payload=response)
            return self._reconcile_locked(state, scope, initiation_at)

    def reconcile(self, *, at: datetime) -> dict:
        if type(self._simulator) is not SimulatedPaperBroker:
            raise NativePaperError("OFFLINE_SIMULATOR_NOT_ATTACHED")
        with self.store.lease.transaction():
            state, _ = self.store.load()
            for scope in tuple(state["trades"]):
                self._reconcile_locked(state, scope, at)
                if state["quarantined"]:
                    break
            return copy.deepcopy(state)

    def _quarantine(self, state: dict, trade: dict, at: datetime, reason: str) -> dict:
        state["quarantined"] = True
        trade["state"] = "QUARANTINED"
        self._audit(state, "RECONCILIATION_CONFLICT", at, trade=trade, reason=reason)
        return copy.deepcopy(trade)

    def _reconcile_locked(self, state: dict, scope: str, at: datetime) -> dict:
        trade = state["trades"][scope]
        if state["quarantined"]:
            return copy.deepcopy(trade)
        try:
            snapshot = self._simulator.snapshot()
        except (ConnectionError, TimeoutError) as exc:
            pending_position = (trade.get("pending_receipt") or {}).get("positions", {}).get(trade["position_id"], "0")
            if number(trade["position_quantity"]) > 0 or number(pending_position) > 0:
                return self._quarantine(state, trade, at, "OPEN_POSITION_PROTECTION_UNKNOWN: " + str(exc))
            self._audit(state, "RECONCILIATION_UNAVAILABLE", at, trade=trade, reason=str(exc))
            return copy.deepcopy(trade)
        # Unprojected durable evidence is already authoritative custody. Never
        # discard it merely because the next source snapshot appears older.
        retained = trade.get("pending_receipt")
        if retained is not None:
            try:
                self._require_receipt_successor(retained, snapshot)
            except (ValueError, KeyError, TypeError) as exc:
                trade["conflicting_receipt"] = snapshot
                return self._quarantine(state, trade, at, "PENDING_RAW_EVIDENCE_REGRESSION:" + str(exc))
        # Preserve the raw source before changing the financial projection.
        trade["pending_receipt"] = snapshot
        self._audit(state, "RAW_BROKER_RECEIPT", at, trade=trade, payload=snapshot)
        self._fault("before_fill_persistence")
        if snapshot.get("namespace") != self.namespace or snapshot.get("environment") != ENVIRONMENT:
            return self._quarantine(state, trade, at, "BROKER_SNAPSHOT_BOUNDARY_MISMATCH")
        order = snapshot["orders"].get(trade["order_id"])
        owned_orders = {value["order_id"] for value in state["trades"].values()}
        owned_orders.update(value["exit_contract"][role + "_order_id"]
                            for value in state["trades"].values() for role in ("stop", "target", "forced_flat"))
        owned_positions = {value["position_id"] for value in state["trades"].values()}
        if (set(snapshot["orders"]) - owned_orders
                or any(pid not in owned_positions and number(qty) != 0
                       for pid, qty in snapshot["positions"].items())):
            return self._quarantine(state, trade, at, "BROKER_STATE_AHEAD_OF_MH")
        if order is None:
            if trade["broker_order"] is not None or number(trade["filled"]) > 0:
                return self._quarantine(state, trade, at, "MH_STATE_AHEAD_OF_BROKER")
            # Complete absence does not authorize a resend or release the scope.
            if trade["state"] == "KNOWN_NOT_SUBMITTED":
                trade["pending_receipt"] = None
                self._audit(state, "KNOWN_NO_INITIATION_SCOPE_REMAINS_CONSUMED", at, trade=trade)
                return copy.deepcopy(trade)
            trade["state"] = "UNKNOWN"
            trade["pending_receipt"] = None
            self._audit(state, "NO_ORDER_FOUND_NO_RETRY", at, trade=trade)
            return copy.deepcopy(trade)
        if (order["request"] != trade["request"]
                or order.get("broker_order_id") != identity("sim-order", self.namespace, trade["order_id"])):
            return self._quarantine(state, trade, at, "BROKER_ORDER_IDENTITY_CONFLICT")
        prior = trade["broker_order"]
        if prior is not None and order["revision"] < prior["revision"]:
            return self._quarantine(state, trade, at, "BROKER_SOURCE_REGRESSION")
        fills = order["fills"]
        by_id = {}
        total = Decimal(0)
        cost = Decimal(0)
        try:
            last_at = self._initiation_time(trade)
            earliest_closure = self._validate_source_chronology(trade, snapshot, at)
            all_fills = [fill for value in snapshot["orders"].values() for fill in value["fills"]]
            sequences = sorted(fill["sequence"] for fill in all_fills)
            if (any(type(sequence) is not int for sequence in sequences)
                    or sequences != list(range(1, len(all_fills) + 1))
                    or snapshot["sequence"] != len(all_fills)):
                raise NativePaperError("BROKER_ECONOMIC_PREFIX_INCOMPLETE")
            prior_economic_ids = {fill["fill_id"] for other in state["trades"].values()
                                  if other["scope"] != scope and other["broker_order"]
                                  for fill in other["broker_order"]["fills"]}
            for fill in fills:
                if fill["fill_id"] in by_id or fill["fill_id"] in prior_economic_ids:
                    raise NativePaperError("DUPLICATE_ECONOMIC_FILL")
                fill_at = timestamp(fill["at"])
                if not last_at <= fill_at <= timestamp(at):
                    raise NativePaperError("FILL_CHRONOLOGY_INVALID")
                quantity, price = number(fill["quantity"], positive=True), number(fill["price"], positive=True)
                if quantity != quantity.to_integral_value() or set(fill) != {"fill_id", "quantity", "price", "at", "sequence"}:
                    raise NativePaperError("UNSUPPORTED_FILL_PROFILE")
                if price > number(trade["entry_price"]):
                    raise NativePaperError("ENTRY_FILL_EXCEEDS_LIMIT")
                by_id[fill["fill_id"]] = fill
                total += quantity
                cost += quantity * price
                last_at = fill_at
            if prior is not None and any(by_id.get(f["fill_id"]) != f for f in prior["fills"]):
                raise NativePaperError("BROKER_FILL_PREFIX_CONFLICT")
            if total > number(trade["quantity"]):
                raise NativePaperError("BROKER_OVERFILL")
            exited, exit_orders, exit_events = self._exit_projection(trade, snapshot, total, at)
            if number(snapshot["positions"].get(trade["position_id"], "0")) != total - exited:
                raise NativePaperError("BROKER_POSITION_DISAGREEMENT")
            if order["status"] == "REJECTED" and total != 0:
                raise NativePaperError("REJECTED_WITH_FILL")
            if order["status"] == "FILLED" and total != number(trade["quantity"]):
                raise NativePaperError("FILLED_QUANTITY_CONFLICT")
            if trade["closure"] and prior["status"] in TERMINAL_ORDERS and order["status"] != prior["status"]:
                raise NativePaperError("TERMINAL_ORDER_REOPENED")
            closure = snapshot.get("closures", {}).get(trade["order_id"])
            if closure is not None:
                if (closure.get("order_fingerprint") != fingerprint(order)
                        or closure.get("source_complete") is not True
                        or closure.get("children_complete") is not True
                        or closure.get("finality_complete") is not True
                        or closure.get("children") != []
                        or not last_at <= timestamp(closure["closed_at"]) <= timestamp(at)):
                    raise NativePaperError("CLOSURE_PROOF_INCOMPLETE_OR_CONTRADICTORY")
            if trade["closure"] is not None and closure != trade["closure"]:
                raise NativePaperError("CLOSURE_EVIDENCE_REGRESSION")
        except (ValueError, ArithmeticError, KeyError, TypeError) as exc:
            return self._quarantine(state, trade, at, str(exc))
        if total and trade["opened_at"] is None:
            trade["opened_at"] = fills[0]["at"]
        trade.update(broker_order=copy.deepcopy(order), filled=str(total),
                     position_quantity=str(total - exited), entry_cost=str(cost),
                     source_revision=order["revision"], pending_receipt=None,
                     source_observations=copy.deepcopy(snapshot.get("observations", [])),
                     earliest_closure_at=earliest_closure)
        terminal = order["status"] in TERMINAL_ORDERS and closure is not None
        remainder = number(trade["quantity"]) - total
        trade["closed_unfilled"] = str(remainder if terminal else Decimal(0))
        trade["unfilled"] = str(Decimal(0) if terminal else remainder)
        if terminal:
            trade["closure"] = copy.deepcopy(closure)
            trade["state"] = "POSITION_OPEN" if total else order["status"]
        elif order["status"] in TERMINAL_ORDERS:
            trade["state"] = "TERMINAL_UNKNOWN"
        else:
            trade["state"] = "PARTIALLY_FILLED" if total else "ORDER_SUBMITTED"
        if total and total == exited:
            exits_closed = all(snapshot.get("closures", {}).get(value["request"]["order_id"])
                               for value in exit_orders.values())
            trade["state"] = "POSITION_CLOSED" if terminal and exits_closed else "TERMINAL_UNKNOWN"
        elif exited:
            trade["state"] = "POSITION_PARTIALLY_CLOSED" if terminal else "TERMINAL_UNKNOWN"
        old_events = trade["exit_events"]
        trade.update(exit_filled=str(exited), exit_orders=copy.deepcopy(exit_orders),
                     exit_events=copy.deepcopy(exit_events))
        for event in exit_events[len(old_events):]:
            self._audit(state, "EXIT_BROKER_EVENT_RECONCILED", at, trade=trade, payload=event)
        self._audit(state, "BROKER_STATE_RECONCILED", at, trade=trade, payload={"filled": str(total)})
        if total:
            self._fault("after_partial_fill" if remainder else "after_full_fill")
        if trade["state"] == "POSITION_CLOSED":
            self._fault("after_position_closure")
        return copy.deepcopy(trade)

    @staticmethod
    def _initiation_time(trade: dict) -> datetime:
        initiated = timestamp(trade["initiation_at"])
        if (initiated < timestamp(trade["request"]["created_at"])
                or initiated != timestamp(trade["initiation_risk_recheck"]["decision_at"])
                or trade["initiation_risk_recheck"]["authorized"] is not True):
            raise NativePaperError("INITIATION_AUTHORITY_CHRONOLOGY_INVALID")
        return initiated

    @staticmethod
    def _require_receipt_successor(old: dict, new: dict) -> None:
        if (old["namespace"] != new["namespace"] or old["environment"] != new["environment"]
                or new["sequence"] < old["sequence"]):
            raise NativePaperError("RAW_IDENTITY_OR_SEQUENCE_CHANGED")
        for key in ("observations", "exit_events"):
            previous = old.get(key, [])
            if new.get(key, [])[:len(previous)] != previous:
                raise NativePaperError("RAW_EVENT_PREFIX_CHANGED")
        for oid, previous in old["orders"].items():
            current = new["orders"].get(oid)
            if (current is None or current["request"] != previous["request"]
                    or current["broker_order_id"] != previous["broker_order_id"]
                    or current["revision"] < previous["revision"]
                    or current["fills"][:len(previous["fills"])] != previous["fills"]
                    or (previous.get("trigger") is not None and current.get("trigger") != previous["trigger"])
                    or (current["revision"] == previous["revision"] and current != previous)):
                raise NativePaperError("RAW_ORDER_OR_FILL_PREFIX_CHANGED")
        for oid, closure in old.get("closures", {}).items():
            if new.get("closures", {}).get(oid) != closure:
                raise NativePaperError("RAW_CLOSURE_PREFIX_CHANGED")

    def _validate_source_chronology(self, trade: dict, snapshot: dict, at: datetime) -> str | None:
        observations = snapshot.get("observations", [])
        previous = trade["source_observations"]
        if observations[:len(previous)] != previous:
            raise NativePaperError("SOURCE_RECEIPT_PREFIX_CHANGED")
        boundaries = {}
        working = {}
        receipt_ids = set()
        for item in observations:
            oid = item["order_id"]
            if oid not in snapshot["orders"] or item["receipt_id"] in receipt_ids:
                raise NativePaperError("SOURCE_RECEIPT_IDENTITY_INVALID")
            receipt_ids.add(item["receipt_id"])
            event_at, known_at = timestamp(item["event_at"]), timestamp(item["known_at"])
            source_request = snapshot["orders"][oid]["request"]
            floor = (self._initiation_time(trade) if source_request["position_id"] == trade["position_id"]
                     else timestamp(source_request["created_at"]))
            if not floor <= event_at <= known_at <= timestamp(at):
                raise NativePaperError("SOURCE_RECEIPT_CHRONOLOGY_INVALID")
            if item["kind"] == "WORKING":
                if oid in boundaries and event_at >= boundaries[oid]:
                    raise NativePaperError("WORKING_CONTRADICTS_TERMINAL_OR_ORDERING_UNKNOWN")
                working.setdefault(oid, []).append(event_at)
            elif item["kind"] == "CLOSURE":
                proof = snapshot.get("closures", {}).get(oid)
                if (not proof or proof.get("source_complete") is not True
                        or proof.get("children_complete") is not True or proof.get("finality_complete") is not True
                        or proof.get("children") != []
                        or proof.get("order_fingerprint") != fingerprint(snapshot["orders"][oid])
                        or any(timestamp(fill["at"]) > event_at for fill in snapshot["orders"][oid]["fills"])):
                    raise NativePaperError("UNQUALIFIED_CLOSURE_RECEIPT")
                prior_boundary = boundaries.get(oid)
                if any(value > event_at or (prior_boundary is not None and event_at < prior_boundary and value == event_at)
                       for value in working.get(oid, [])):
                    raise NativePaperError("RETROACTIVE_CLOSURE_CONTRADICTS_RETAINED_WORKING")
                boundaries[oid] = min(prior_boundary, event_at) if prior_boundary else event_at
            elif item["kind"] != "ACK":
                raise NativePaperError("UNSUPPORTED_SOURCE_RECEIPT")
        value = boundaries.get(trade["order_id"])
        return value.isoformat() if value else None

    def _exit_projection(self, trade: dict, snapshot: dict, entered: Decimal, at: datetime) -> tuple:
        protection = trade["exit_contract"]
        if protection != exit_contract(trade["plan"], position_id=trade["position_id"], entry_order_id=trade["order_id"]):
            raise NativePaperError("FROZEN_EXIT_CONTRACT_CHANGED")
        orders = {}
        exited = Decimal(0)
        chronological = [(f["sequence"], number(f["quantity"]), f["at"])
                         for f in snapshot["orders"][trade["order_id"]]["fills"]]
        ids = {f["fill_id"] for value in snapshot["orders"].values()
               if value["request"].get("position_id") != trade["position_id"]
               for f in value["fills"]}
        ids.update(f["fill_id"] for f in snapshot["orders"][trade["order_id"]]["fills"])
        for role in ("STOP", "TARGET", "FORCED_FLAT"):
            oid = protection[role.lower() + "_order_id"]
            order = snapshot["orders"].get(oid)
            if order is None:
                if entered or trade["exit_orders"]:
                    raise NativePaperError("REQUIRED_EXIT_ORDER_MISSING")
                continue
            expected = {**trade["request"], "order_id": oid, "parent_order_id": trade["order_id"],
                        "side": "SELL", "exit_type": role,
                        "type": {"STOP": "STOP", "TARGET": "LIMIT", "FORCED_FLAT": "MARKET"}[role],
                        "limit_price": protection.get(role.lower(), trade["request"]["limit_price"])}
            if (order["request"] != expected
                    or order.get("broker_order_id") != identity("sim-order", self.namespace, oid)):
                raise NativePaperError("EXIT_UPSTREAM_IDENTITY_OR_LEVEL_CHANGED")
            old = trade["exit_orders"].get(role)
            if old and (order["revision"] < old["revision"] or order["fills"][:len(old["fills"])] != old["fills"]):
                raise NativePaperError("EXIT_FILL_PREFIX_CONFLICT")
            if old and old.get("trigger") and old["trigger"] != order.get("trigger"):
                raise NativePaperError("FROZEN_EXIT_TRIGGER_CHANGED")
            trigger = order.get("trigger")
            if trigger is not None:
                frontier = trigger.get("economic_frontier")
                trigger_at = timestamp(trigger["at"])
                trigger_price = number(trigger["observed_price"], positive=True)
                level = number(protection.get(role.lower(), trade["entry_price"]))
                acquired = sum((number(f["quantity"]) * (1 if value["request"]["side"] == "BUY" else -1)
                                for value in snapshot["orders"].values()
                                if value["request"]["position_id"] == trade["position_id"]
                                for f in value["fills"] if type(frontier) is int and f["sequence"] <= frontier), Decimal(0))
                if (trigger.get("exit_type") != role or type(frontier) is not int
                        or not 0 < frontier <= snapshot["sequence"] or acquired <= 0
                        or not self._initiation_time(trade) <= trigger_at <= timestamp(at)
                        or (role == "STOP" and trigger_price > level)
                        or (role == "TARGET" and trigger_price < level)
                        or (role == "FORCED_FLAT" and trigger_at < timestamp(protection["forced_flat_at"]))
                        or any(timestamp(f["at"]) > trigger_at for value in snapshot["orders"].values()
                               for f in value["fills"] if f["sequence"] <= frontier)):
                    raise NativePaperError("UNFILLED_OR_FILLED_TRIGGER_AUTHORITY_INVALID")
            for fill in order["fills"]:
                if fill["fill_id"] in ids:
                    raise NativePaperError("DUPLICATE_ECONOMIC_EXIT_FILL")
                ids.add(fill["fill_id"])
                qty, price = number(fill["quantity"], positive=True), number(fill["price"], positive=True)
                if qty != qty.to_integral_value() or set(fill) != {"fill_id", "quantity", "price", "at", "sequence"}:
                    raise NativePaperError("UNSUPPORTED_EXIT_FILL_PROFILE")
                level = number(protection.get(role.lower(), trade["entry_price"]))
                trigger = order.get("trigger")
                if not trigger or trigger.get("exit_type") != role:
                    raise NativePaperError("EXIT_TRIGGER_EVIDENCE_MISSING")
                trigger_price = number(trigger["observed_price"], positive=True)
                frontier = trigger.get("economic_frontier")
                acquired = sum((number(f["quantity"]) * (1 if value["request"]["side"] == "BUY" else -1)
                                for value in snapshot["orders"].values()
                                if value["request"]["position_id"] == trade["position_id"]
                                for f in value["fills"] if type(frontier) is int and f["sequence"] <= frontier), Decimal(0))
                if type(frontier) is not int or not 0 < frontier < fill["sequence"] or acquired <= 0:
                    raise NativePaperError("EXIT_TRIGGER_WITHOUT_ACQUIRED_POSITION")
                if any(timestamp(f["at"]) > timestamp(trigger["at"])
                       for value in snapshot["orders"].values() for f in value["fills"] if f["sequence"] <= frontier):
                    raise NativePaperError("EXIT_TRIGGER_PRECEDES_ACQUIRED_EVIDENCE")
                if (not self._initiation_time(trade) <= timestamp(trigger["at"]) <= timestamp(fill["at"])
                        or (role == "STOP" and trigger_price > level)
                        or (role == "TARGET" and trigger_price < level)):
                    raise NativePaperError("EXIT_TRIGGER_CHRONOLOGY_OR_LEVEL_INVALID")
                if role == "TARGET" and price < level:
                    raise NativePaperError("EXIT_FILL_PRICE_CONFLICT")
                if role == "FORCED_FLAT" and timestamp(fill["at"]) < timestamp(protection["forced_flat_at"]):
                    raise NativePaperError("CANONICAL_DEADLINE_EXIT_PREMATURE")
                exited += qty
                chronological.append((fill["sequence"], -qty, fill["at"]))
            orders[role] = order
        held = Decimal(0)
        last_sequence = 0
        last_time = self._initiation_time(trade)
        quantities_at_exit = {}
        for sequence, delta, event_at in sorted(chronological):
            if type(sequence) is not int or sequence <= last_sequence:
                raise NativePaperError("EXIT_EVENT_SEQUENCE_CONFLICT")
            moment = timestamp(event_at)
            if not last_time <= moment <= timestamp(at):
                raise NativePaperError("EXIT_EVENT_CHRONOLOGY_INVALID")
            before = held
            held += delta
            if held < 0:
                raise NativePaperError("EXIT_BEFORE_FILL_OR_OVERSELL")
            if delta < 0:
                quantities_at_exit[sequence] = (before, held)
            last_time, last_sequence = moment, sequence
        remaining = entered - exited
        if remaining < 0:
            raise NativePaperError("POSITION_OVERSELL")
        for role, order in orders.items():
            if number(order["executable_quantity"]) != remaining:
                raise NativePaperError("EXIT_PROTECTION_QUANTITY_MISMATCH")
            allowed = {"ACK", "PARTIALLY_FILLED", "DORMANT"} if role == "FORCED_FLAT" else {"ACK", "PARTIALLY_FILLED"}
            if remaining and order["status"] not in allowed:
                raise NativePaperError("OPEN_POSITION_WITHOUT_REQUIRED_PROTECTIVE_" + role)
            if not remaining and order["status"] not in TERMINAL_ORDERS | {"DORMANT"}:
                raise NativePaperError("EXIT_WORKING_AFTER_POSITION_FLAT")
            closure = snapshot.get("closures", {}).get(order["request"]["order_id"])
            if closure is not None:
                if (order["status"] not in TERMINAL_ORDERS
                        or closure.get("order_fingerprint") != fingerprint(order)
                        or closure.get("source_complete") is not True
                        or closure.get("children_complete") is not True
                        or closure.get("finality_complete") is not True or closure.get("children") != []
                        or not last_time <= timestamp(closure["closed_at"]) <= timestamp(at)):
                    raise NativePaperError("EXIT_CLOSURE_INCOMPLETE_OR_CONTRADICTORY")
        events = [event for event in snapshot.get("exit_events", []) if event["position_id"] == trade["position_id"]]
        if events[:len(trade["exit_events"])] != trade["exit_events"]:
            raise NativePaperError("EXIT_AUDIT_PREFIX_CONFLICT")
        actual_fills = {f["sequence"]: (role, f) for role, order in orders.items() for f in order["fills"]}
        if len(events) != len(actual_fills) or len({e["sequence"] for e in events}) != len(events):
            raise NativePaperError("EXIT_AUDIT_COVERAGE_INCOMPLETE")
        for event in events:
            role, fill = actual_fills[event["sequence"]]
            requested, residual = quantities_at_exit[event["sequence"]]
            expected_type = "OTHER_CANONICAL_IF_ALREADY_DEFINED" if role == "FORCED_FLAT" else role
            if (event["exit_type"] != expected_type or event["canonical_exit_role"] != role
                    or event["trade_plan_id"] != protection["trade_plan_id"]
                    or event["exit_intent_id"] != protection[role.lower() + "_order_id"]
                    or event["simulated_broker_response"] != fill or event["broker_event_time"] != fill["at"]
                    or number(event["requested_quantity"]) != requested
                    or number(event["remaining_quantity"]) != residual
                    or number(event["filled_quantity"]) != number(fill["quantity"])
                    or event["request_time"] != trade["request"]["created_at"]
                    or event["reason_code"] != "CANONICAL_" + role
                    or event["prior_state"] not in {"ACK", "PARTIALLY_FILLED", "DORMANT"}
                    or event["new_state"] != ("FILLED" if residual == 0 else "PARTIALLY_FILLED")):
                raise NativePaperError("EXIT_AUDIT_IDENTITY_CONFLICT")
        return exited, orders, events

    def qualification_exit(self, *, scope: str, reason: str, at: datetime) -> dict:
        """Reconcile existing contingent exits; never send a second closing order."""
        if reason not in {"STOP", "TARGET", "FORCED_FLAT"}:
            raise NativePaperError("ADAPTIVE_EXIT_POLICY_NOT_AUTHORIZED")
        if type(self._simulator) is not SimulatedPaperBroker:
            raise NativePaperError("OFFLINE_SIMULATOR_NOT_ATTACHED")
        with self.store.lease.transaction():
            state, _ = self.store.load()
            self._fault("before_exit_reconciliation")
            trade = self._reconcile_locked(state, scope, at)
            self._fault("after_exit_reconciliation")
            return {"state": trade["state"], "reason": "RECONCILE_EXISTING_CONTINGENT_EXIT",
                    "exit_intent_id": trade["exit_contract"][reason.lower() + "_order_id"],
                    "submission_performed": False, "remaining_quantity": trade["position_quantity"]}
