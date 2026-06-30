from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import TradePlan


SIMULATION_MODE = "Simulation Lab"
LIVE_LOCKED_REASON = "Live execution is locked until a separate Steven-approved live task exists."


@dataclass(frozen=True)
class RiskGate:
    name: str
    state: str
    reason: str

    @property
    def blocked(self) -> bool:
        return self.state.lower() == "blocked"


@dataclass(frozen=True)
class RiskGovernorResult:
    result_id: str
    timestamp: str
    ticker: str
    trade_plan_id: str
    mode: str
    status: str
    gates: list[RiskGate] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def allows_simulation(self) -> bool:
        return self.mode == SIMULATION_MODE and not any(gate.blocked for gate in self.gates)


def evaluate_trade_plan(
    plan: TradePlan,
    *,
    ticker: str,
    trade_plan_id: str,
    mode: str = SIMULATION_MODE,
    manual_override_pending: bool = False,
    checked_at: datetime | None = None,
) -> RiskGovernorResult:
    warnings = list(plan.warnings) + list(plan.blocking_reasons)
    gates = [
        data_freshness_gate(warnings),
        required_value_gate("Stop defined", plan.bullish_stop, "A hard stop is required before simulation."),
        required_value_gate("Max risk", plan.estimated_dollar_risk, "Estimated dollar risk is required before simulation."),
        required_value_gate("Risk/reward", plan.risk_reward_ratio, "Risk/reward must be known before simulation."),
        manual_override_gate(manual_override_pending),
        broker_mode_gate(mode),
        approval_gate(mode),
    ]
    blocked_reasons = [gate.reason for gate in gates if gate.blocked]
    review_reasons = [gate.reason for gate in gates if gate.state == "Needs review"]
    if blocked_reasons:
        status = "Blocked"
    elif review_reasons:
        status = "Needs review"
    else:
        status = "Simulation-only"
    return RiskGovernorResult(
        result_id=f"risk-{uuid4().hex[:12]}",
        timestamp=(checked_at or now_central()).isoformat(),
        ticker=ticker,
        trade_plan_id=trade_plan_id,
        mode=mode,
        status=status,
        gates=gates,
        reasons=blocked_reasons or review_reasons or ["Plan can be simulated only. Paper and live trading remain locked."],
    )


def data_freshness_gate(warnings: list[str]) -> RiskGate:
    stale_tokens = {
        "DATA_REQUIRED_DAILY_BARS",
        "TECHNICAL_LEVELS_ESTIMATED",
        "MISSING_PRICE",
        "MISSING_PREMARKET_VOLUME",
        "MISSING_BID_ASK",
        "UNKNOWN_RVOL",
    }
    matched = [warning for warning in warnings if warning in stale_tokens or warning.startswith("MISSING_")]
    if matched:
        return RiskGate("Data freshness", "Needs review", " | ".join(matched))
    return RiskGate("Data freshness", "Ready", "No stale-data blocker detected in the selected TradePlan.")


def required_value_gate(name: str, value: object | None, missing_reason: str) -> RiskGate:
    if value is None:
        return RiskGate(name, "Blocked", missing_reason)
    return RiskGate(name, "Pass", f"{name} is present for simulation review.")


def manual_override_gate(manual_override_pending: bool) -> RiskGate:
    if manual_override_pending:
        return RiskGate(
            "Manual override",
            "Blocked",
            "Steven-edited fields require Risk Governor re-check before simulation.",
        )
    return RiskGate("Manual override", "None", "No manual override is pending.")


def broker_mode_gate(mode: str) -> RiskGate:
    if mode != SIMULATION_MODE:
        return RiskGate("Broker mode", "Blocked", f"{mode} is not enabled for this autonomy slice.")
    return RiskGate("Broker mode", "Simulation-only", "Only FakeBroker simulation is available.")


def approval_gate(mode: str) -> RiskGate:
    if mode == SIMULATION_MODE:
        return RiskGate("Steven approval", "Live-locked", LIVE_LOCKED_REASON)
    return RiskGate("Steven approval", "Blocked", LIVE_LOCKED_REASON)
