"""Autonomous execution planning primitives.

This package is intentionally pure model/evaluation code. It does not connect
to brokers, submit orders, preview live orders, or mutate market/runtime data.
"""

from momentum_hunter.execution.risk_governor import RiskGateResult, RiskGovernorResult, RiskStatus, evaluate_trade_plan
from momentum_hunter.execution.trade_plan import ApprovalStatus, TradePlan, TradePlanMode, TradePlanValidationIssue

__all__ = [
    "ApprovalStatus",
    "RiskGateResult",
    "RiskGovernorResult",
    "RiskStatus",
    "TradePlan",
    "TradePlanMode",
    "TradePlanValidationIssue",
    "evaluate_trade_plan",
]
