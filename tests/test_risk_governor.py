from __future__ import annotations

import unittest
from datetime import datetime, timezone

from momentum_hunter.execution import ApprovalStatus, RiskStatus, TradePlan, TradePlanMode, evaluate_trade_plan


class RiskGovernorTests(unittest.TestCase):
    def test_incomplete_plan_returns_block_with_missing_field_gates(self) -> None:
        plan = TradePlan(ticker="", direction="", mode=TradePlanMode.SIMULATION)

        result = evaluate_trade_plan(plan)
        gates = {gate.gate: gate for gate in result.gates}

        self.assertEqual(RiskStatus.BLOCK, result.status)
        self.assertEqual(RiskStatus.BLOCK, gates["ticker_present"].status)
        self.assertEqual(RiskStatus.BLOCK, gates["direction_present"].status)
        self.assertEqual(RiskStatus.BLOCK, gates["entry_defined"].status)
        self.assertEqual(RiskStatus.BLOCK, gates["stop_defined"].status)
        self.assertEqual(RiskStatus.BLOCK, gates["targets_defined"].status)
        self.assertIn("Ticker is required.", result.blocking_reasons)

    def test_complete_simulation_plan_passes_first_gates(self) -> None:
        result = evaluate_trade_plan(complete_plan())

        self.assertEqual(RiskStatus.PASS, result.status)
        self.assertTrue(result.allows_simulation)
        self.assertEqual([], result.blocking_reasons)
        self.assertIn("passes first Risk Governor gates", result.summary)

    def test_complete_simulation_plan_without_explicit_approval_is_warn_only(self) -> None:
        result = evaluate_trade_plan(complete_plan(approval_status=ApprovalStatus.DRAFT))

        self.assertEqual(RiskStatus.WARN, result.status)
        self.assertTrue(result.allows_simulation)
        self.assertIn("Simulation plan lacks explicit simulation approval.", result.warning_reasons)

    def test_live_mode_is_locked_by_default(self) -> None:
        result = evaluate_trade_plan(complete_plan(mode=TradePlanMode.LIVE, approval_status=ApprovalStatus.STEVEN_APPROVED))
        gates = {gate.gate: gate for gate in result.gates}

        self.assertEqual(RiskStatus.LOCKED, result.status)
        self.assertEqual(RiskStatus.LOCKED, gates["mode_allowed"].status)
        self.assertEqual(RiskStatus.LOCKED, gates["approval_status"].status)
        self.assertIn("Live mode is locked by default.", result.blocking_reasons)

    def test_live_preview_is_locked_by_default(self) -> None:
        result = evaluate_trade_plan(
            complete_plan(mode=TradePlanMode.LIVE_PREVIEW, approval_status=ApprovalStatus.STEVEN_APPROVED)
        )

        self.assertEqual(RiskStatus.LOCKED, result.status)
        self.assertIn("Live preview is locked by default.", result.blocking_reasons)

    def test_manual_override_requires_recheck_warning(self) -> None:
        result = evaluate_trade_plan(complete_plan(manual_override=True))
        gates = {gate.gate: gate for gate in result.gates}

        self.assertEqual(RiskStatus.WARN, result.status)
        self.assertEqual(RiskStatus.WARN, gates["manual_override_recheck"].status)
        self.assertIn("Manual override requires Risk Governor re-check.", result.warning_reasons)

    def test_paper_mode_requires_steven_approval(self) -> None:
        result = evaluate_trade_plan(complete_plan(mode=TradePlanMode.PAPER, approval_status=ApprovalStatus.DRAFT))
        gates = {gate.gate: gate for gate in result.gates}

        self.assertEqual(RiskStatus.NEEDS_STEVEN, result.status)
        self.assertEqual(RiskStatus.NEEDS_STEVEN, gates["approval_status"].status)
        self.assertIn("Paper-mode advancement requires Steven approval.", result.warning_reasons)

    def test_negative_risk_and_size_are_blocked(self) -> None:
        plan = complete_plan(position_size=-1, max_dollar_risk=-10)

        result = evaluate_trade_plan(plan)
        gates = {gate.gate: gate for gate in result.gates}

        self.assertEqual(RiskStatus.BLOCK, result.status)
        self.assertEqual("Max dollar risk must be nonnegative.", gates["max_dollar_risk_defined"].reason)
        self.assertEqual("Position size must be nonnegative.", gates["position_size_defined"].reason)

    def test_risk_governor_has_no_broker_or_order_side_effect_api(self) -> None:
        import momentum_hunter.execution.risk_governor as risk_governor

        forbidden = [
            "connect_broker",
            "preview_order",
            "place_order",
            "submit_order",
            "submit_live_order",
            "execute_order",
        ]

        self.assertFalse(any(hasattr(risk_governor, name) for name in forbidden))


def complete_plan(
    *,
    mode: TradePlanMode | str = TradePlanMode.SIMULATION,
    approval_status: ApprovalStatus | str = ApprovalStatus.SIMULATION_APPROVED,
    manual_override: bool = False,
    position_size: int | float | None = 10,
    max_dollar_risk: float | None = 27.5,
) -> TradePlan:
    return TradePlan(
        plan_id="tp-risk-complete",
        ticker="NVDA",
        direction="long",
        setup_type="Opening drive continuation",
        entry_trigger="Break over opening range",
        entry_limit=101.25,
        stop_price=98.5,
        target_1=104.0,
        target_2=108.0,
        target_3=112.0,
        trailing_stop_rule="Trail below rising 9 EMA after target 1",
        position_size=position_size,
        max_dollar_risk=max_dollar_risk,
        risk_reward=2.0,
        manual_override=manual_override,
        mode=mode,
        source="unit-test",
        created_at=datetime(2026, 6, 28, 9, 30, tzinfo=timezone.utc),
        approval_status=approval_status,
    )


if __name__ == "__main__":
    unittest.main()
