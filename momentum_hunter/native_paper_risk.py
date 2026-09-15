"""Scale-independent offline policy bound to canonical allocation machinery."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import Decimal

from momentum_hunter.broker_capabilities import (
    BrokerCapability, BrokerCapabilityRegistry, CapabilityState,
    CAPABILITY_LIMIT_ORDER, CAPABILITY_WHOLE_QUANTITY,
)
from momentum_hunter.native_paper_broker import ENVIRONMENT, PROVIDER, number
from momentum_hunter.native_paper_store import NativePaperError, fingerprint, identity
from momentum_hunter.provider_neutral_allocation import (
    AccountSnapshot, AllocationRequest, ProviderNeutralAllocationPolicy,
    QuantityPolicy, allocate_provider_neutral_position,
)


@dataclass(frozen=True)
class NativePaperRiskPolicy:
    capital_base: str
    risk_fraction: str
    max_position_fraction: str
    max_portfolio_fraction: str
    cash_reserve_fraction: str
    daily_loss_fraction: str
    max_total_risk_fraction: str
    max_positions: int
    max_snapshot_age_seconds: int

    def validate(self) -> None:
        number(self.capital_base, positive=True)
        for key in ("risk_fraction", "max_position_fraction", "max_portfolio_fraction",
                    "daily_loss_fraction", "max_total_risk_fraction"):
            if not 0 < number(getattr(self, key)) <= 1:
                raise NativePaperError("RISK_POLICY_FRACTION_INVALID")
        if not 0 <= number(self.cash_reserve_fraction) < 1:
            raise NativePaperError("RISK_POLICY_RESERVE_INVALID")
        for key in ("max_positions", "max_snapshot_age_seconds"):
            if type(getattr(self, key)) is not int or getattr(self, key) <= 0:
                raise NativePaperError("RISK_POLICY_BOUND_INVALID")

    @property
    def fingerprint(self) -> str:
        return fingerprint(asdict(self))


def evaluate_native_risk(*, plan: dict, price: str, at: datetime,
                         account: AccountSnapshot | None, policy: NativePaperRiskPolicy,
                         namespace: str, trades: dict, requested_quantity: str | None) -> dict:
    policy.validate()
    blockers: list[str] = []
    risk_id = identity("native-paper-risk", namespace, plan["trade_plan_id"],
                       at.isoformat(), price, policy.fingerprint)
    result = {"risk_decision_id": risk_id, "authorized": False,
              "quantity": "0", "blockers": blockers,
              "policy_fingerprint": policy.fingerprint, "decision_at": at.isoformat(),
              "allocation": None}
    if type(account) is not AccountSnapshot:
        blockers.append("RISK_ACCOUNT_SNAPSHOT_MISSING")
        return result
    if (account.environment != ENVIRONMENT or account.provider != PROVIDER
            or account.lane != ENVIRONMENT or account.source_identity != "OFFLINE_FIXTURE"
            or account.binding_fingerprint != fingerprint([ENVIRONMENT, namespace])):
        blockers.append("RISK_ACCOUNT_BOUNDARY_MISMATCH")
        return result
    risk_id = identity("native-paper-risk", namespace, fingerprint(plan), account.fingerprint,
                       at.isoformat(), price, policy.fingerprint, fingerprint(trades), str(requested_quantity))
    result.update(risk_decision_id=risk_id, account_snapshot_fingerprint=account.fingerprint,
                  input_plan_fingerprint=fingerprint(plan), exposure_fingerprint=fingerprint(trades))
    # OFFLINE_FIXTURE is a fixed account baseline EXCLUDING this native ledger.
    # Time/cycle evidence may refresh; rebasing economic fields is not supported.
    baseline = fingerprint({key: str(getattr(account, key)) for key in (
        "cash_available", "buying_power", "committed_notional", "committed_open_risk",
        "open_position_count", "realized_pnl_today", "binding_fingerprint")})
    result.update(accounting_basis="FIXED_OFFLINE_BASELINE_EXCLUDING_NATIVE_LEDGER",
                  account_baseline_fingerprint=baseline)
    if any(t.get("risk", {}).get("account_baseline_fingerprint", baseline) != baseline
           for t in trades.values()):
        blockers.append("RISK_ACCOUNT_BASELINE_DRIFT")
        return result
    # Entry cash is consumed even after closure; exits are not settlement proof.
    notional = Decimal(0)
    open_risk = Decimal(0)
    pending_cash = Decimal(0)
    spent_cash = Decimal(0)
    conservative_losses = Decimal(0)
    active = 0
    for trade in trades.values():
        spent_cash += number(trade.get("entry_cost", "0"))
        entry = number(trade["entry_price"])
        for order in trade.get("exit_orders", {}).values():
            for fill in order["fills"]:
                conservative_losses += min(Decimal(0), number(fill["quantity"]) * (number(fill["price"]) - entry))
        if trade["state"] in {"REJECTED", "CANCELLED", "EXPIRED", "POSITION_CLOSED", "DISABLED", "KNOWN_NOT_SUBMITTED"}:
            continue
        active += 1
        if trade["plan"]["opportunity_id"] == plan["opportunity_id"]:
            blockers.append("RISK_DUPLICATE_OPPORTUNITY_EXPOSURE")
        reserved = (number(trade.get("position_quantity", "0")) + number(trade.get("unfilled", trade["quantity"])))
        pending_cash += number(trade.get("unfilled", trade["quantity"])) * entry
        notional += reserved * entry
        open_risk += reserved * (entry - number(trade["plan"]["stop"]))
    committed = number(account.committed_notional) + notional
    risk_committed = number(account.committed_open_risk) + open_risk
    result["exposure"] = {"native_notional": str(notional), "native_open_risk": str(open_risk),
                          "native_pending_cash": str(pending_cash), "native_spent_cash": str(spent_cash),
                          "native_conservative_realized_losses": str(conservative_losses),
                          "native_active_scopes": active, "combined_notional": str(committed),
                          "settlement_credit": "0", "duplicate_key": "opportunity_id"}
    capital = number(policy.capital_base)
    remaining = capital * number(policy.max_portfolio_fraction) - committed
    if remaining <= 0:
        blockers.append("RISK_PORTFOLIO_CAP_EXCEEDED")
        return result
    adapted = ProviderNeutralAllocationPolicy(
        policy_id=policy.fingerprint,
        fixed_unit_risk_dollars=capital * number(policy.risk_fraction),
        max_position_notional_dollars=min(capital * number(policy.max_position_fraction), remaining),
        minimum_cash_reserve_dollars=capital * number(policy.cash_reserve_fraction),
        max_total_open_risk_dollars=capital * number(policy.max_total_risk_fraction),
        daily_loss_limit_dollars=capital * number(policy.daily_loss_fraction),
        max_open_positions=policy.max_positions,
        max_snapshot_age_seconds=policy.max_snapshot_age_seconds,
        quantity_policy=QuantityPolicy.WHOLE_ONLY,
    )
    capabilities = BrokerCapabilityRegistry.build(
        provider=PROVIDER, environment=ENVIRONMENT,
        capabilities=tuple(BrokerCapability(name, CapabilityState.PROVEN, "true",
                                           ("Deterministic offline simulator only.",))
                           for name in (CAPABILITY_LIMIT_ORDER, CAPABILITY_WHOLE_QUANTITY)),
    )
    allocation = allocate_provider_neutral_position(
        request=AllocationRequest(
            decision_cycle_id=plan["decision_id"], candidate_id=plan["opportunity_id"],
            canonical_rank=plan["rank"], symbol=plan["symbol"],
            trade_plan_id=plan["trade_plan_id"], risk_decision_id=risk_id,
            entry_order_type="limit", entry_price=number(price, positive=True),
            stop_price=number(plan["stop"], positive=True),
            target_price=number(plan["target"], positive=True), decision_at=at.isoformat()),
        policy=adapted,
        account=replace(account,
                        cash_available=max(Decimal(0), number(account.cash_available) - spent_cash),
                        buying_power=max(Decimal(0), number(account.buying_power) - spent_cash),
                        committed_notional=number(account.committed_notional) + pending_cash,
                        committed_open_risk=risk_committed,
                        open_position_count=account.open_position_count + active,
                        realized_pnl_today=number(account.realized_pnl_today) + conservative_losses),
        capabilities=capabilities,
    )
    blockers.extend(allocation.blockers)
    quantity = allocation.final_authorized_quantity
    if requested_quantity is not None:
        try:
            requested = number(requested_quantity, positive=True)
            if requested != requested.to_integral_value() or requested > quantity:
                blockers.append("RISK_REQUESTED_QUANTITY_EXCEEDS_AUTHORIZATION")
            else:
                quantity = requested
        except NativePaperError:
            blockers.append("RISK_REQUESTED_QUANTITY_INVALID")
    result.update(authorized=allocation.authorized and not blockers,
                  quantity=str(quantity) if not blockers else "0",
                  allocator_maximum_quantity=str(allocation.final_authorized_quantity),
                  allocation=allocation.to_dict())
    return result
