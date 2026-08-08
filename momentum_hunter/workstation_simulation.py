from __future__ import annotations

"""Loopback-host payloads for the FakeBroker-only workstation simulation slice.

The module consumes persisted TradePlan reports and the existing autonomy primitives.
It does not rescore candidates, fetch market data, write source evidence, or expose a
paper/live broker capability.
"""

from dataclasses import asdict
from datetime import datetime
from typing import Any

from momentum_hunter.account_allocation import AccountAllocationDecision
from momentum_hunter.autonomy.auditor import AuditReport, audit_simulation_chain
from momentum_hunter.autonomy.ledger import ExecutionLedgerEvent
from momentum_hunter.autonomy.risk_governor import RiskGovernorResult
from momentum_hunter.autonomy.simulation import SimulationLabEngine, SimulationResult
from momentum_hunter.autonomy.view_models import Top5CandidatePlan, build_candidate_plans_from_report
from momentum_hunter.monitor_targets import latest_trade_report_path
from momentum_hunter.time_utils import now_central
from momentum_hunter.workstation_read_models import WorkstationReadModelPaths, build_read_only_workspace_snapshot


SIMULATION_WORKSPACE_SCHEMA_VERSION = 1
SIMULATION_WORKSPACE_MODE = "SIMULATION_ONLY_FAKE_BROKER"


class SimulationWorkspaceService:
    """Builds host-safe simulation payloads from persisted plans and an in-memory ledger."""

    def __init__(
        self,
        *,
        paths: WorkstationReadModelPaths | None = None,
        simulation_engine: SimulationLabEngine | None = None,
        allocation_source: object | None = None,
    ) -> None:
        self._paths = paths or WorkstationReadModelPaths.from_data_dir()
        self._simulation_engine = simulation_engine or SimulationLabEngine()
        self._allocation_source = allocation_source

    def snapshot(self, *, observed_at: datetime | None = None) -> dict[str, Any]:
        workspace = build_read_only_workspace_snapshot(paths=self._paths, observed_at=observed_at)
        candidates = self._candidate_plans(risk_checked_at=observed_at)
        ledger_events = [ledger_event_payload(event) for event in self._simulation_engine.ledger.events]
        if ledger_events:
            workspace["activity"] = [ledger_activity(event) for event in reversed(ledger_events)] + list(workspace["activity"])
        planning_available = bool(candidates)
        summary = (
            "Python simulation workspace uses persisted TradePlan evidence, the Risk Governor, "
            "an in-memory Execution Ledger, Execution Auditor, and FakeBroker only. "
            "Paper and live execution remain locked."
            if planning_available
            else "No persisted TradePlan candidate is available for simulation. No substitute plan was created."
        )
        return {
            "schemaVersion": SIMULATION_WORKSPACE_SCHEMA_VERSION,
            "mode": SIMULATION_WORKSPACE_MODE,
            "observedAt": workspace["observedAt"],
            "summary": summary,
            "workspace": workspace,
            "planningAvailable": planning_available,
            "plans": [candidate_plan_payload(candidate) for candidate in candidates],
            "ledgerEvents": ledger_events,
        }

    def run_simulation(self, symbol: str) -> dict[str, Any]:
        normalized_symbol = symbol.strip().upper()
        candidate = next((item for item in self._candidate_plans() if item.ticker == normalized_symbol), None)
        if candidate is None:
            return {
                "schemaVersion": SIMULATION_WORKSPACE_SCHEMA_VERSION,
                "mode": SIMULATION_WORKSPACE_MODE,
                "state": "Unavailable",
                "symbol": normalized_symbol,
                "summary": f"No persisted TradePlan candidate is available for {normalized_symbol or 'the requested symbol'}. Simulation was not started.",
                "risk": None,
                "audit": audit_payload(AuditReport("FAIL")),
                "ledgerEvents": [ledger_event_payload(event) for event in self._simulation_engine.ledger.events],
            }

        decision_at = now_central()
        allocation: AccountAllocationDecision | None = None
        if self._allocation_source is not None:
            try:
                allocator = getattr(self._allocation_source, "allocate", self._allocation_source)
                allocation = allocator(
                    symbol=candidate.ticker,
                    trade_plan_id=candidate.trade_plan_id,
                    entry_price=candidate.trade_plan.bullish_entry,
                    stop_price=candidate.trade_plan.bullish_stop,
                    target_price=candidate.trade_plan.bullish_target_1,
                    decision_at=decision_at,
                )
            except Exception:
                allocation = None
        result = self._simulation_engine.run_candidate(
            candidate,
            allocation=allocation,
            decision_at=decision_at,
        )
        audit = audit_simulation_chain(
            self._simulation_engine.ledger,
            ticker=candidate.ticker,
            trade_plan_id=candidate.trade_plan_id,
        )
        return {
            "schemaVersion": SIMULATION_WORKSPACE_SCHEMA_VERSION,
            "mode": SIMULATION_WORKSPACE_MODE,
            "state": simulation_state(result),
            "symbol": candidate.ticker,
            "summary": result.message,
            "risk": risk_payload(candidate.risk_result),
            "audit": audit_payload(audit),
            "order": simulation_result_payload(result),
            "ledgerEvents": [ledger_event_payload(event) for event in self._simulation_engine.ledger.events],
        }

    def _candidate_plans(
        self,
        *,
        risk_checked_at: datetime | None = None,
    ) -> list[Top5CandidatePlan]:
        report_path = latest_trade_report_path(self._paths.reports_dir)
        return (
            build_candidate_plans_from_report(
                report_path,
                limit=None,
                include_all_candidates=True,
                risk_checked_at=risk_checked_at,
            )
            if report_path
            else []
        )


def candidate_plan_payload(candidate: Top5CandidatePlan) -> dict[str, Any]:
    plan = candidate.trade_plan
    return {
        "symbol": candidate.ticker,
        "tradePlanId": candidate.trade_plan_id,
        "entry": plan.bullish_entry,
        "stop": plan.bullish_stop,
        "target": plan.bullish_target_1,
        "target2": plan.bullish_target_2,
        "riskPerShare": risk_per_share(plan.bullish_entry, plan.bullish_stop),
        "simulatedQuantity": 0,
        "referenceQuantityFor500": plan.estimated_shares_for_500,
        "rewardToRisk": plan.risk_reward_ratio,
        "sourceReadinessLabel": plan.readiness,
        "primaryAction": (
            "Account allocation required"
            if candidate.risk_result.allows_simulation
            else "Risk review required"
        ),
        "warnings": list(candidate.warnings),
        "risk": risk_payload(candidate.risk_result),
    }


def risk_payload(result: RiskGovernorResult) -> dict[str, Any]:
    return {
        "resultId": result.result_id,
        "timestamp": result.timestamp,
        "status": result.status,
        "allowsSimulation": result.allows_simulation,
        "reasons": list(result.reasons),
        "gates": [asdict(gate) for gate in result.gates],
    }


def audit_payload(report: AuditReport) -> dict[str, Any]:
    return {
        "state": report.status,
        "passed": report.passed,
        "summary": "Simulation audit passed." if report.passed else "Simulation audit found missing or invalid evidence.",
        "findings": [asdict(finding) for finding in report.findings],
    }


def simulation_result_payload(result: SimulationResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "previewOrder": asdict(result.preview_order) if result.preview_order else None,
        "submittedOrder": asdict(result.submitted_order) if result.submitted_order else None,
    }


def ledger_event_payload(event: ExecutionLedgerEvent) -> dict[str, Any]:
    return event.to_dict()


def ledger_activity(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": event["timestamp"],
        "category": "Simulation",
        "message": f"{event['requested_action']} -> {event['result']}: {event.get('reason') or 'No additional reason.'}",
        "symbol": event["ticker"],
        "state": "Healthy" if event["result"] not in {"blocked", "rejected"} else "Degraded",
    }


def simulation_state(result: SimulationResult) -> str:
    return "Blocked" if result.status == "blocked" else "Completed"


def risk_per_share(entry: float | None, stop: float | None) -> float | None:
    if entry is None or stop is None:
        return None
    return round(entry - stop, 4)
