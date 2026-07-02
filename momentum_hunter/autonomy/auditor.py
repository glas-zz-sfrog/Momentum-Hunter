from __future__ import annotations

from dataclasses import dataclass, field

from momentum_hunter.autonomy.ledger import ExecutionLedger, ExecutionLedgerEvent
from momentum_hunter.autonomy.risk_governor import SIMULATION_MODE


ORDER_LIKE_ACTIONS = {"simulated_order_previewed", "fake_order_submitted", "simulation_blocked"}


@dataclass(frozen=True)
class AuditFinding:
    event_id: str
    field: str
    message: str


@dataclass(frozen=True)
class AuditReport:
    status: str
    findings: list[AuditFinding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def audit_execution_ledger(ledger: ExecutionLedger) -> AuditReport:
    findings: list[AuditFinding] = []
    seen_event_ids: set[str] = set()
    for event in ledger.events:
        if event.requested_action not in ORDER_LIKE_ACTIONS:
            continue
        if not event.event_id.strip():
            findings.append(AuditFinding(event.event_id, "event_id", "Missing required audit field: event_id"))
        elif event.event_id in seen_event_ids:
            findings.append(AuditFinding(event.event_id, "event_id", "Duplicate order-like ledger event identifier."))
        seen_event_ids.add(event.event_id)
        findings.extend(audit_order_like_event(event))
    return AuditReport("PASS" if not findings else "FAIL", findings)


def audit_order_like_event(event: ExecutionLedgerEvent) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    required_fields = [
        "timestamp",
        "mode",
        "ticker",
        "trade_plan_id",
        "risk_result_id",
        "broker_adapter",
        "approval_state",
        "result",
        "source",
    ]
    for field_name in required_fields:
        if not str(getattr(event, field_name)).strip():
            findings.append(AuditFinding(event.event_id, field_name, f"Missing required audit field: {field_name}"))
    if event.mode != SIMULATION_MODE:
        findings.append(AuditFinding(event.event_id, "mode", "Simulation events must stay in Simulation Lab mode."))
    if event.broker_adapter != "FakeBrokerAdapter":
        findings.append(AuditFinding(event.event_id, "broker_adapter", "Simulation must use FakeBrokerAdapter."))
    if event.approval_state != "simulation-only":
        findings.append(AuditFinding(event.event_id, "approval_state", "Simulation audit state must be simulation-only."))
    return findings


def audit_simulation_chain(ledger: ExecutionLedger, *, ticker: str, trade_plan_id: str) -> AuditReport:
    events = [
        event
        for event in ledger.events
        if event.ticker == ticker and event.trade_plan_id == trade_plan_id
    ]
    actions = {event.requested_action for event in events}
    findings: list[AuditFinding] = []
    if not ticker.strip():
        findings.append(AuditFinding("chain", "ticker", "Missing ticker for simulation audit."))
    if not trade_plan_id.strip():
        findings.append(AuditFinding("chain", "trade_plan_id", "Missing TradePlan identifier for simulation audit."))
    if "risk_gate_evaluated" not in actions:
        findings.append(AuditFinding("chain", "risk_result_id", "Missing Risk Governor event before simulation."))
    if not ({"fake_order_submitted", "simulation_blocked"} & actions):
        findings.append(AuditFinding("chain", "result", "Missing final simulation order or blocked outcome."))
    findings.extend(audit_simulation_chronology(events))
    findings.extend(audit_execution_ledger(ExecutionLedger(events)).findings)
    return AuditReport("PASS" if not findings else "FAIL", findings)


def audit_simulation_chronology(events: list[ExecutionLedgerEvent]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    indexed_actions: dict[str, list[int]] = {}
    for index, event in enumerate(events):
        indexed_actions.setdefault(event.requested_action, []).append(index)
    risk_indexes = indexed_actions.get("risk_gate_evaluated", [])
    preview_indexes = indexed_actions.get("simulated_order_previewed", [])
    submit_indexes = indexed_actions.get("fake_order_submitted", [])
    blocked_indexes = indexed_actions.get("simulation_blocked", [])
    if not risk_indexes:
        return findings
    first_risk = risk_indexes[0]
    order_like_indexes = preview_indexes + submit_indexes + blocked_indexes
    if any(index < first_risk for index in order_like_indexes):
        findings.append(
            AuditFinding("chain", "chronology", "Risk Governor evidence must precede preview, submit, or block evidence.")
        )
    if submit_indexes and not preview_indexes:
        findings.append(AuditFinding("chain", "preview_order", "Missing simulated preview before fake submit evidence."))
    elif submit_indexes and preview_indexes and min(submit_indexes) < min(preview_indexes):
        findings.append(
            AuditFinding("chain", "chronology", "Simulated preview evidence must precede fake submit evidence.")
        )
    return findings


def audit_paper_advancement_gate(ledger: ExecutionLedger, *, ticker: str, trade_plan_id: str) -> AuditReport:
    """Display-only gate: future paper work must start from a complete simulation audit."""
    report = audit_simulation_chain(ledger, ticker=ticker, trade_plan_id=trade_plan_id)
    if report.passed:
        return report
    return AuditReport("BLOCK", report.findings)
