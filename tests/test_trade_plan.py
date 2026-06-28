from __future__ import annotations

import unittest
from datetime import datetime, timezone

from momentum_hunter.execution.trade_plan import ApprovalStatus, TradePlan, TradePlanMode


class TradePlanTests(unittest.TestCase):
    def test_trade_plan_can_be_created_with_valid_fields(self) -> None:
        created_at = datetime(2026, 6, 28, 9, 30, tzinfo=timezone.utc)

        plan = TradePlan(
            plan_id="tp-test",
            ticker=" nvda ",
            direction=" LONG ",
            setup_type="Opening drive continuation",
            entry_trigger="Break over opening range",
            entry_limit=101.25,
            stop_price=98.5,
            target_1=104.0,
            target_2=108.0,
            target_3=112.0,
            trailing_stop_rule="Trail below rising 9 EMA after target 1",
            position_size=10,
            max_dollar_risk=27.5,
            risk_reward=2.0,
            manual_override=False,
            mode="simulation",
            source="unit-test",
            created_at=created_at,
            approval_status="simulation-approved",
        )

        self.assertEqual("tp-test", plan.plan_id)
        self.assertEqual("NVDA", plan.ticker)
        self.assertEqual("long", plan.direction)
        self.assertEqual(TradePlanMode.SIMULATION, plan.mode)
        self.assertEqual(ApprovalStatus.SIMULATION_APPROVED, plan.approval_status)
        self.assertEqual([], plan.validation_issues())

    def test_required_fields_and_nonnegative_values_are_validated(self) -> None:
        plan = TradePlan(
            ticker="",
            direction="",
            entry_trigger="",
            entry_limit=None,
            stop_price=None,
            position_size=-1,
            max_dollar_risk=-5,
        )

        issues = {issue.field: issue.message for issue in plan.validation_issues()}

        self.assertIn("ticker", issues)
        self.assertIn("direction", issues)
        self.assertIn("entry", issues)
        self.assertIn("stop_price", issues)
        self.assertEqual("Position size must be nonnegative.", issues["position_size"])
        self.assertEqual("Max dollar risk must be nonnegative.", issues["max_dollar_risk"])

    def test_live_mode_is_locked_by_default_in_validation(self) -> None:
        plan = complete_plan(mode=TradePlanMode.LIVE, approval_status=ApprovalStatus.STEVEN_APPROVED)

        issues = plan.validation_issues()

        self.assertTrue(any(issue.field == "mode" and issue.status == "LOCKED" for issue in issues))

    def test_manual_override_requires_recheck_warning(self) -> None:
        plan = complete_plan(manual_override=True)

        issues = plan.validation_issues()

        self.assertTrue(any(issue.field == "manual_override" and issue.status == "WARN" for issue in issues))

    def test_trade_plan_produces_ladder_compatible_data(self) -> None:
        plan = complete_plan()

        ladder = plan.to_ladder_dict()

        self.assertEqual("NVDA", ladder["Ticker"])
        self.assertEqual("Opening drive continuation", ladder["Setup type"])
        self.assertEqual("Break over opening range", ladder["Entry trigger"])
        self.assertEqual("98.5", ladder["Stop/invalidation"])
        self.assertEqual("104", ladder["Target 1"])
        self.assertEqual("None", ladder["Manual override state"])
        self.assertEqual("simulation", ladder["Mode"])
        self.assertEqual("simulation-approved", ladder["Approval status"])

    def test_no_live_broker_or_order_methods_exist_on_trade_plan(self) -> None:
        forbidden = [
            "connect_broker",
            "preview_order",
            "place_order",
            "submit_order",
            "submit_live_order",
            "execute",
        ]

        self.assertFalse(any(hasattr(TradePlan, name) for name in forbidden))


def complete_plan(
    *,
    mode: TradePlanMode | str = TradePlanMode.SIMULATION,
    approval_status: ApprovalStatus | str = ApprovalStatus.SIMULATION_APPROVED,
    manual_override: bool = False,
) -> TradePlan:
    return TradePlan(
        plan_id="tp-complete",
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
        position_size=10,
        max_dollar_risk=27.5,
        risk_reward=2.0,
        manual_override=manual_override,
        mode=mode,
        source="unit-test",
        created_at=datetime(2026, 6, 28, 9, 30, tzinfo=timezone.utc),
        approval_status=approval_status,
    )


if __name__ == "__main__":
    unittest.main()
