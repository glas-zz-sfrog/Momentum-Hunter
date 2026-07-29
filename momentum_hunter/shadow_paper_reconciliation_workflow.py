from __future__ import annotations

"""Operator workflow for paperMoney evidence and experiment refresh."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR
from momentum_hunter.shadow_experiment_automation import (
    SHADOW_EXPERIMENT_AUTOMATION_RECEIPTS_DIR,
    ShadowExperimentAutomationResult,
    automate_shadow_experiment_evidence,
)
from momentum_hunter.shadow_experiment_study import (
    SHADOW_EXPERIMENT_STUDIES_DIR,
)
from momentum_hunter.shadow_paper_reconciliation import (
    PAPER_RECONCILIATIONS_DIR,
    PaperMoneyReconciliationResult,
    record_paper_money_reconciliation,
)
from momentum_hunter.shadow_trade_experiments import (
    SHADOW_TRADE_EXPERIMENTS_DIR,
)
from momentum_hunter.shadow_trading import (
    SHADOW_DECISION_CYCLES_PATH,
    SHADOW_STATE_PATH,
)


PAPER_RECONCILIATION_WORKFLOW_MODE = (
    "MANUAL PAPERMONEY EVIDENCE REFRESH / READ-ONLY / NONTRANSMITTING"
)


@dataclass(frozen=True)
class PaperMoneyReconciliationWorkflowResult:
    mode: str
    reconciliation: PaperMoneyReconciliationResult
    experiment_evidence: ShadowExperimentAutomationResult
    transmitting: bool
    broker_request_performed: bool
    order_action_performed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "artifactPath": str(self.reconciliation.path),
            "created": self.reconciliation.created,
            "sourceStateUnchanged": (
                self.reconciliation.source_state_unchanged
            ),
            "reconciliation": self.reconciliation.record.to_dict(),
            "experimentEvidence": self.experiment_evidence.to_dict(),
            "transmitting": self.transmitting,
            "brokerRequestPerformed": self.broker_request_performed,
            "orderActionPerformed": self.order_action_performed,
        }


def record_and_refresh_paper_money_evidence(
    *,
    state_path: Path = SHADOW_STATE_PATH,
    output_dir: Path = PAPER_RECONCILIATIONS_DIR,
    decision_cycles_path: Path | None = None,
    experiments_dir: Path | None = None,
    studies_dir: Path | None = None,
    automation_receipts_dir: Path | None = None,
    shadow_trade_id: str,
    exact_ticket_entered: str,
    paper_money_result: str,
    paper_money_filled_quantity: int | None = None,
    paper_money_fill_price: float | None = None,
    paper_money_exit_price: float | None = None,
    operator_modifications: str = "",
    paper_money_exit: str = "",
    paper_money_outcome: str = "",
    reconciliation_notes: str = "",
    recorded_at: datetime | None = None,
) -> PaperMoneyReconciliationWorkflowResult:
    """Record manual evidence, then refresh derived terminal evidence."""

    resolved_state = state_path.expanduser().resolve()
    report_root = _report_root(resolved_state)
    reconciliation = record_paper_money_reconciliation(
        state_path=resolved_state,
        output_dir=output_dir,
        shadow_trade_id=shadow_trade_id,
        exact_ticket_entered=exact_ticket_entered,
        paper_money_result=paper_money_result,
        paper_money_filled_quantity=paper_money_filled_quantity,
        paper_money_fill_price=paper_money_fill_price,
        paper_money_exit_price=paper_money_exit_price,
        operator_modifications=operator_modifications,
        paper_money_exit=paper_money_exit,
        paper_money_outcome=paper_money_outcome,
        reconciliation_notes=reconciliation_notes,
        recorded_at=recorded_at,
    )
    experiment_evidence = automate_shadow_experiment_evidence(
        state_path=resolved_state,
        decision_cycles_path=(
            decision_cycles_path
            or _decision_cycles_path(resolved_state)
        ),
        paper_reconciliations_dir=output_dir,
        experiments_dir=(
            experiments_dir
            or _experiments_dir(resolved_state, report_root)
        ),
        studies_dir=(
            studies_dir
            or _studies_dir(resolved_state, report_root)
        ),
        receipts_dir=(
            automation_receipts_dir
            or _receipts_dir(resolved_state, report_root)
        ),
    )
    if (
        reconciliation.record.transmitting
        or reconciliation.record.broker_request_performed
        or reconciliation.record.order_action_performed
        or experiment_evidence.transmitting
        or experiment_evidence.broker_request_performed
        or experiment_evidence.order_action_performed
        or not experiment_evidence.source_artifacts_unchanged
    ):
        raise ValueError(
            "paperMoney evidence workflow violated its nontransmitting boundary."
        )
    return PaperMoneyReconciliationWorkflowResult(
        mode=PAPER_RECONCILIATION_WORKFLOW_MODE,
        reconciliation=reconciliation,
        experiment_evidence=experiment_evidence,
        transmitting=False,
        broker_request_performed=False,
        order_action_performed=False,
    )


def _report_root(state_path: Path) -> Path:
    return (
        DATA_DIR / "reports"
        if state_path == SHADOW_STATE_PATH.expanduser().resolve()
        else state_path.parent / "reports"
    )


def _decision_cycles_path(state_path: Path) -> Path:
    return (
        SHADOW_DECISION_CYCLES_PATH.expanduser().resolve()
        if state_path == SHADOW_STATE_PATH.expanduser().resolve()
        else state_path.with_name(
            f"{state_path.stem}-decision-cycles.json"
        )
    )


def _experiments_dir(state_path: Path, report_root: Path) -> Path:
    return (
        SHADOW_TRADE_EXPERIMENTS_DIR
        if state_path == SHADOW_STATE_PATH.expanduser().resolve()
        else report_root / "shadow-trade-experiments"
    )


def _studies_dir(state_path: Path, report_root: Path) -> Path:
    return (
        SHADOW_EXPERIMENT_STUDIES_DIR
        if state_path == SHADOW_STATE_PATH.expanduser().resolve()
        else report_root / "shadow-experiment-studies"
    )


def _receipts_dir(state_path: Path, report_root: Path) -> Path:
    return (
        SHADOW_EXPERIMENT_AUTOMATION_RECEIPTS_DIR
        if state_path == SHADOW_STATE_PATH.expanduser().resolve()
        else report_root / "shadow-experiment-automation-receipts"
    )
