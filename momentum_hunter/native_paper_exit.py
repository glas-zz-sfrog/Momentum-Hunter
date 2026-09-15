"""Frozen-plan V1 exit profile; no research or adaptive policy consumer."""

from __future__ import annotations

from decimal import Decimal

from momentum_hunter.native_paper_broker import number
from momentum_hunter.native_paper_store import NativePaperError, identity


MINIMUM_EXIT_POLICY = "FROZEN_TRADEPLAN_FULL_REMAINDER_V1"


def exit_contract(plan: dict, *, position_id: str, entry_order_id: str) -> dict:
    """First canonical target is the full-close target; retain all plan levels."""
    entry = number(plan["entry"], positive=True)
    stop = number(plan["stop"], positive=True)
    targets = tuple(number(value, positive=True) for value in plan["targets"])
    tick = number(plan["tick_size"], positive=True)
    if stop >= entry or not targets or any(target <= entry for target in targets):
        raise NativePaperError("INVALID_CANONICAL_EXIT_GEOMETRY")
    if any(value % tick != Decimal(0) for value in (entry, stop, *targets)):
        raise NativePaperError("CANONICAL_EXIT_TICK_MISMATCH")
    return {
        "policy": MINIMUM_EXIT_POLICY,
        "group_id": identity("native-exit-group", position_id, entry_order_id),
        "position_id": position_id, "trade_plan_id": plan["trade_plan_id"],
        "stop": str(stop), "target": str(targets[0]),
        "forced_flat_at": plan["intraday"]["forced_flat_at"],
        "original_r_per_share": str(entry - stop),
        "quantity_rule": "FULL_ACTUAL_REMAINDER",
        "stop_order_id": identity("native-exit-order", position_id, "STOP"),
        "target_order_id": identity("native-exit-order", position_id, "TARGET"),
        "forced_flat_order_id": identity("native-exit-order", position_id, "FORCED_FLAT"),
    }
