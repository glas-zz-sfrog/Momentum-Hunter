from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from momentum_hunter.account_allocation import (
    AccountAllocationDecision,
    account_allocation_decision_findings,
)
from momentum_hunter.autonomy.broker import BrokerAdapter, BrokerOrder, BrokerOrderRequest, FakeBrokerAdapter
from momentum_hunter.autonomy.ledger import ExecutionLedger
from momentum_hunter.autonomy.risk_governor import SIMULATION_MODE
from momentum_hunter.autonomy.view_models import Top5CandidatePlan
from momentum_hunter.time_utils import now_central


@dataclass(frozen=True)
class SimulationResult:
    status: str
    message: str
    preview_order: BrokerOrder | None = None
    submitted_order: BrokerOrder | None = None


class SimulationLabEngine:
    def __init__(self, *, adapter: BrokerAdapter | None = None, ledger: ExecutionLedger | None = None) -> None:
        self.adapter = adapter or FakeBrokerAdapter()
        self.ledger = ledger or ExecutionLedger()

    def run_candidate(
        self,
        candidate: Top5CandidatePlan,
        *,
        allocation: AccountAllocationDecision | None = None,
        decision_at: datetime | None = None,
    ) -> SimulationResult:
        evaluated_at = decision_at or now_central()
        risk = candidate.risk_result
        self.ledger.record(
            event_type="risk_gate_evaluated",
            mode=SIMULATION_MODE,
            ticker=candidate.ticker,
            trade_plan_id=candidate.trade_plan_id,
            risk_result_id=risk.result_id,
            broker_adapter=self.adapter.metadata.adapter_name,
            requested_action="risk_gate_evaluated",
            result=risk.status,
            reason=" | ".join(risk.reasons),
        )
        adapter_block_reason = simulation_adapter_block_reason(self.adapter)
        if adapter_block_reason:
            self.ledger.record(
                event_type="execution_blocked",
                mode=SIMULATION_MODE,
                ticker=candidate.ticker,
                trade_plan_id=candidate.trade_plan_id,
                risk_result_id=risk.result_id,
                broker_adapter=self.adapter.metadata.adapter_name,
                requested_action="simulation_blocked",
                result="blocked",
                reason=adapter_block_reason,
            )
            return SimulationResult("blocked", f"{candidate.ticker} blocked: {adapter_block_reason}")
        if not risk.allows_simulation:
            self.ledger.record(
                event_type="execution_blocked",
                mode=SIMULATION_MODE,
                ticker=candidate.ticker,
                trade_plan_id=candidate.trade_plan_id,
                risk_result_id=risk.result_id,
                broker_adapter=self.adapter.metadata.adapter_name,
                requested_action="simulation_blocked",
                result="blocked",
                reason=" | ".join(risk.reasons),
            )
            return SimulationResult("blocked", f"{candidate.ticker} blocked: {' | '.join(risk.reasons)}")
        allocation_findings = account_allocation_decision_findings(
            allocation,
            trade_plan_id=candidate.trade_plan_id,
            entry_price=candidate.trade_plan.bullish_entry,
            stop_price=candidate.trade_plan.bullish_stop,
            target_price=candidate.trade_plan.bullish_target_1,
            decision_at=evaluated_at,
        )
        if allocation_findings:
            reason = " | ".join(allocation_findings)
            self.ledger.record(
                event_type="allocation_blocked",
                mode=SIMULATION_MODE,
                ticker=candidate.ticker,
                trade_plan_id=candidate.trade_plan_id,
                risk_result_id=risk.result_id,
                broker_adapter=self.adapter.metadata.adapter_name,
                requested_action="simulation_blocked",
                result="blocked",
                reason=reason,
            )
            return SimulationResult("blocked", f"{candidate.ticker} blocked: {reason}")
        assert allocation is not None
        self.ledger.record(
            event_type="account_allocation_authorized",
            mode=SIMULATION_MODE,
            ticker=candidate.ticker,
            trade_plan_id=candidate.trade_plan_id,
            risk_result_id=risk.result_id,
            broker_adapter=self.adapter.metadata.adapter_name,
            requested_action="account_allocation_authorized",
            result=allocation.evidence.status,
            reason="Account-aware fixed-unit-risk allocation passed.",
            payload={
                "allocation_fingerprint": allocation.fingerprint,
                "policy_fingerprint": allocation.policy.fingerprint,
                "account_context_fingerprint": allocation.context.fingerprint,
                "quantity": allocation.evidence.quantity,
            },
        )
        request = build_simulation_order_request(candidate, allocation=allocation)
        if request is None:
            reason = "TradePlan lacks an entry price or authorized account allocation."
            self.ledger.record(
                event_type="execution_blocked",
                mode=SIMULATION_MODE,
                ticker=candidate.ticker,
                trade_plan_id=candidate.trade_plan_id,
                risk_result_id=risk.result_id,
                broker_adapter=self.adapter.metadata.adapter_name,
                requested_action="simulation_blocked",
                result="blocked",
                reason=reason,
            )
            return SimulationResult("blocked", f"{candidate.ticker} blocked: {reason}")
        preview = self.adapter.preview_order(request)
        self.ledger.record(
            event_type="simulated_order_created",
            mode=SIMULATION_MODE,
            ticker=candidate.ticker,
            trade_plan_id=candidate.trade_plan_id,
            risk_result_id=risk.result_id,
            broker_adapter=self.adapter.metadata.adapter_name,
            requested_action="simulated_order_previewed",
            result=preview.status,
            reason=preview.reason,
            payload={"order_id": preview.order_id, "quantity": preview.quantity},
        )
        submitted = self.adapter.submit_order(request)
        self.ledger.record(
            event_type="fake_order_submitted",
            mode=SIMULATION_MODE,
            ticker=candidate.ticker,
            trade_plan_id=candidate.trade_plan_id,
            risk_result_id=risk.result_id,
            broker_adapter=self.adapter.metadata.adapter_name,
            requested_action="fake_order_submitted",
            result=submitted.status,
            reason=submitted.reason,
            payload={
                "order_id": submitted.order_id,
                "quantity": submitted.quantity,
                "filled_quantity": submitted.filled_quantity,
            },
        )
        return SimulationResult(
            submitted.status,
            f"{candidate.ticker} simulated order {submitted.status}.",
            preview_order=preview,
            submitted_order=submitted,
        )


def simulation_adapter_block_reason(adapter: BrokerAdapter) -> str:
    metadata = adapter.metadata
    problems: list[str] = []
    if not isinstance(adapter, FakeBrokerAdapter) or metadata.adapter_name != "FakeBrokerAdapter":
        problems.append("Simulation Lab requires the local FakeBrokerAdapter.")
    if metadata.mode != SIMULATION_MODE:
        problems.append(f"Adapter mode must be {SIMULATION_MODE}.")
    if metadata.order_transmit_allowed:
        problems.append("Adapter metadata allows transmit; Simulation Lab requires transmit disabled.")
    if metadata.credential_status != "not required":
        problems.append("Simulation Lab cannot use broker credentials.")
    risky_capabilities = [
        capability
        for capability in metadata.capabilities
        if any(marker in capability.lower() for marker in ("transmit", "paper", "live"))
    ]
    if risky_capabilities:
        problems.append(f"Adapter capabilities are not simulation-only: {', '.join(risky_capabilities)}.")
    return " ".join(problems)


def build_simulation_order_request(
    candidate: Top5CandidatePlan,
    *,
    allocation: AccountAllocationDecision | None,
) -> BrokerOrderRequest | None:
    plan = candidate.trade_plan
    if plan.bullish_entry is None or allocation is None or not allocation.evidence.authorized:
        return None
    quantity = allocation.evidence.quantity
    if quantity <= 0:
        return None
    return BrokerOrderRequest(
        ticker=candidate.ticker,
        side="buy",
        quantity=quantity,
        order_type="limit",
        limit_price=plan.bullish_entry,
        trade_plan_id=candidate.trade_plan_id,
        risk_result_id=candidate.risk_result.result_id,
    )
