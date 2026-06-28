from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from momentum_hunter.execution.trade_plan import ApprovalStatus, TradePlan, TradePlanMode


class RiskStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    NEEDS_STEVEN = "NEEDS_STEVEN"
    LOCKED = "LOCKED"


@dataclass(frozen=True)
class RiskGateResult:
    gate: str
    status: RiskStatus
    reason: str


@dataclass(frozen=True)
class RiskGovernorResult:
    status: RiskStatus
    gates: list[RiskGateResult]
    summary: str

    @property
    def blocking_reasons(self) -> list[str]:
        return [gate.reason for gate in self.gates if gate.status in {RiskStatus.BLOCK, RiskStatus.LOCKED}]

    @property
    def warning_reasons(self) -> list[str]:
        return [gate.reason for gate in self.gates if gate.status in {RiskStatus.WARN, RiskStatus.NEEDS_STEVEN}]

    @property
    def allows_simulation(self) -> bool:
        return self.status in {RiskStatus.PASS, RiskStatus.WARN}


def evaluate_trade_plan(plan: TradePlan) -> RiskGovernorResult:
    gates = [
        _gate("ticker_present", bool(plan.ticker), "Ticker present.", "Ticker is required."),
        _gate("direction_present", bool(plan.direction), "Direction present.", "Direction is required."),
        _gate("entry_defined", plan.has_entry, "Entry trigger or limit defined.", "Entry trigger or entry limit is required."),
        _gate("stop_defined", plan.stop_price is not None, "Stop defined.", "Stop is required before risk approval."),
        _gate("targets_defined", plan.has_targets, "At least one target defined.", "At least one target is required."),
        _nonnegative_gate(
            "max_dollar_risk_defined",
            plan.max_dollar_risk,
            "Max dollar risk defined.",
            "Max dollar risk is required.",
            "Max dollar risk must be nonnegative.",
        ),
        _nonnegative_gate(
            "position_size_defined",
            plan.position_size,
            "Position size defined.",
            "Position size is required.",
            "Position size must be nonnegative.",
        ),
        _mode_gate(plan),
        _manual_override_gate(plan),
        _approval_gate(plan),
    ]
    status = aggregate_status(gates)
    summary = risk_summary(status)
    return RiskGovernorResult(status=status, gates=gates, summary=summary)


def _gate(gate: str, condition: bool, pass_reason: str, block_reason: str) -> RiskGateResult:
    if condition:
        return RiskGateResult(gate, RiskStatus.PASS, pass_reason)
    return RiskGateResult(gate, RiskStatus.BLOCK, block_reason)


def _nonnegative_gate(
    gate: str,
    value: int | float | None,
    pass_reason: str,
    missing_reason: str,
    negative_reason: str,
) -> RiskGateResult:
    if value is None:
        return RiskGateResult(gate, RiskStatus.BLOCK, missing_reason)
    if value < 0:
        return RiskGateResult(gate, RiskStatus.BLOCK, negative_reason)
    return RiskGateResult(gate, RiskStatus.PASS, pass_reason)


def _mode_gate(plan: TradePlan) -> RiskGateResult:
    if plan.mode == TradePlanMode.LIVE:
        return RiskGateResult("mode_allowed", RiskStatus.LOCKED, "Live mode is locked by default.")
    if plan.mode == TradePlanMode.LIVE_PREVIEW:
        return RiskGateResult("mode_allowed", RiskStatus.LOCKED, "Live preview is locked by default.")
    if plan.mode in {TradePlanMode.DISPLAY, TradePlanMode.SIMULATION, TradePlanMode.PAPER}:
        return RiskGateResult("mode_allowed", RiskStatus.PASS, f"Mode {plan.mode.value} is allowed for non-broker evaluation.")
    return RiskGateResult("mode_allowed", RiskStatus.BLOCK, "Unsupported TradePlan mode.")


def _manual_override_gate(plan: TradePlan) -> RiskGateResult:
    if plan.manual_override:
        return RiskGateResult("manual_override_recheck", RiskStatus.WARN, "Manual override requires Risk Governor re-check.")
    return RiskGateResult("manual_override_recheck", RiskStatus.PASS, "No manual override pending.")


def _approval_gate(plan: TradePlan) -> RiskGateResult:
    if plan.mode == TradePlanMode.DISPLAY:
        return RiskGateResult("approval_status", RiskStatus.PASS, "Display mode does not require advancement approval.")
    if plan.mode == TradePlanMode.SIMULATION:
        if plan.approval_status in {ApprovalStatus.SIMULATION_APPROVED, ApprovalStatus.STEVEN_APPROVED}:
            return RiskGateResult("approval_status", RiskStatus.PASS, "Simulation approval present.")
        return RiskGateResult("approval_status", RiskStatus.WARN, "Simulation plan lacks explicit simulation approval.")
    if plan.mode == TradePlanMode.PAPER:
        if plan.approval_status == ApprovalStatus.STEVEN_APPROVED:
            return RiskGateResult("approval_status", RiskStatus.PASS, "Steven approval present for paper-mode advancement.")
        return RiskGateResult("approval_status", RiskStatus.NEEDS_STEVEN, "Paper-mode advancement requires Steven approval.")
    if plan.mode in {TradePlanMode.LIVE_PREVIEW, TradePlanMode.LIVE}:
        return RiskGateResult("approval_status", RiskStatus.LOCKED, "Live approval is locked by default.")
    return RiskGateResult("approval_status", RiskStatus.BLOCK, "Unsupported approval state.")


def aggregate_status(gates: list[RiskGateResult]) -> RiskStatus:
    statuses = {gate.status for gate in gates}
    if RiskStatus.LOCKED in statuses:
        return RiskStatus.LOCKED
    if RiskStatus.BLOCK in statuses:
        return RiskStatus.BLOCK
    if RiskStatus.NEEDS_STEVEN in statuses:
        return RiskStatus.NEEDS_STEVEN
    if RiskStatus.WARN in statuses:
        return RiskStatus.WARN
    return RiskStatus.PASS


def risk_summary(status: RiskStatus) -> str:
    if status == RiskStatus.PASS:
        return "TradePlan passes first Risk Governor gates for the current non-broker mode."
    if status == RiskStatus.WARN:
        return "TradePlan is non-blocking but needs review before advancement."
    if status == RiskStatus.NEEDS_STEVEN:
        return "TradePlan requires Steven approval before advancement."
    if status == RiskStatus.LOCKED:
        return "TradePlan is locked; live modes are not enabled."
    return "TradePlan is blocked by missing or invalid required fields."
