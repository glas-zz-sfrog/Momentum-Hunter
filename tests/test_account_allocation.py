from __future__ import annotations

import inspect
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from momentum_hunter.account_allocation import (
    ALLOCATION_AUTHORIZED,
    ALLOCATION_BLOCKED,
    AccountAllocationContext,
    AccountPortfolioSnapshot,
    AccountAllocationPolicy,
    FrozenAccountAllocationSource,
    allocate_account_position,
    build_schwab_account_allocation_context,
    build_account_allocation_decision,
    verify_account_allocation,
    context_findings,
)
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    SchwabAccountBinding,
    SchwabAuthorizedAccount,
    SchwabBalances,
    SchwabPosition,
)
import momentum_hunter.autonomy.simulation as simulation_module
import momentum_hunter.shadow_selection as shadow_selection_module
import momentum_hunter.shadow_trading as shadow_trading_module


DECISION_AT = datetime(2026, 8, 10, 14, 40, tzinfo=timezone.utc)
BINDING_FINGERPRINT = "a" * 64


def configured_policy(**changes: object) -> AccountAllocationPolicy:
    values: dict[str, object] = {
        "policy_id": "synthetic-fixed-unit-risk",
        "fixed_unit_risk_dollars": 5.0,
        "max_position_notional_dollars": 80.0,
        "minimum_cash_reserve_dollars": 20.0,
        "max_total_open_risk_dollars": 10.0,
        "daily_loss_limit_dollars": 10.0,
        "max_open_positions": 1,
        "max_balance_age_seconds": 30,
    }
    values.update(changes)
    return AccountAllocationPolicy(**values)


def fresh_context(**changes: object) -> AccountAllocationContext:
    values: dict[str, object] = {
        "binding_fingerprint": BINDING_FINGERPRINT,
        "account_ending": "2573",
        "account_type": "INDIVIDUAL_CASH",
        "authorized_account_count": 1,
        "cash_available": 100.0,
        "buying_power": 100.0,
        "liquidation_value": 100.0,
        "committed_notional": 0.0,
        "committed_open_risk": 0.0,
        "open_position_count": 0,
        "realized_pnl_today": 0.0,
        "provider_timestamp": (DECISION_AT - timedelta(seconds=2)).isoformat(),
        "portfolio_timestamp": (DECISION_AT - timedelta(seconds=2)).isoformat(),
        "receipt_timestamp": (DECISION_AT - timedelta(seconds=1)).isoformat(),
        "source": "SYNTHETIC_READ_ONLY_ACCOUNT",
        "portfolio_source": "SYNTHETIC_STRATEGY_STATE",
        "order_transmission": "UNAVAILABLE",
    }
    values.update(changes)
    return AccountAllocationContext(**values)


def allocate(
    *,
    policy: AccountAllocationPolicy | None = None,
    context: AccountAllocationContext | None = None,
    entry: float = 20.0,
    stop: float = 18.0,
    target: float = 24.0,
):
    return allocate_account_position(
        trade_plan_id="plan-NVDA",
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        policy=policy or configured_policy(),
        context=context or fresh_context(),
        decision_at=DECISION_AT,
    )


def synthetic_allocation_decision(
    *,
    trade_plan_id: str,
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
    decision_at: datetime,
    cash_available: float = 1_000.0,
    buying_power: float = 1_000.0,
    fixed_unit_risk: float = 25.0,
    max_position_notional: float = 500.0,
    max_total_open_risk: float = 25.0,
    daily_loss_limit: float = 100.0,
    max_open_positions: int = 3,
):
    return build_account_allocation_decision(
        trade_plan_id=trade_plan_id,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        policy=AccountAllocationPolicy(
            policy_id="synthetic-test-fixed-unit-risk",
            fixed_unit_risk_dollars=fixed_unit_risk,
            max_position_notional_dollars=max_position_notional,
            minimum_cash_reserve_dollars=0.0,
            max_total_open_risk_dollars=max_total_open_risk,
            daily_loss_limit_dollars=daily_loss_limit,
            max_open_positions=max_open_positions,
            max_balance_age_seconds=30,
        ),
        context=AccountAllocationContext(
            binding_fingerprint=BINDING_FINGERPRINT,
            account_ending="2573",
            account_type="INDIVIDUAL_CASH",
            authorized_account_count=1,
            cash_available=cash_available,
            buying_power=buying_power,
            liquidation_value=cash_available,
            committed_notional=0.0,
            committed_open_risk=0.0,
            open_position_count=0,
            realized_pnl_today=0.0,
            provider_timestamp=(decision_at - timedelta(seconds=2)).isoformat(),
            portfolio_timestamp=(decision_at - timedelta(seconds=2)).isoformat(),
            receipt_timestamp=(decision_at - timedelta(seconds=1)).isoformat(),
            source="SYNTHETIC_TEST_ACCOUNT",
            portfolio_source="SYNTHETIC_TEST_PORTFOLIO",
        ),
        decision_at=decision_at,
    )


def synthetic_quantity_allocation_decision(
    *,
    trade_plan_id: str,
    entry_price: float | None,
    stop_price: float | None,
    target_price: float | None,
    decision_at: datetime,
    quantity: int = 2,
):
    """Authorize an explicit synthetic quantity without using report reference sizing."""

    entry = float(entry_price) if entry_price is not None else 0.0
    stop = float(stop_price) if stop_price is not None else 0.0
    risk_budget = max((entry - stop) * quantity, 0.01)
    notional_budget = max(entry * quantity, 0.01)
    available = max(notional_budget + 100.0, 1_000.0)
    return synthetic_allocation_decision(
        trade_plan_id=trade_plan_id,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        decision_at=decision_at,
        cash_available=available,
        buying_power=available,
        fixed_unit_risk=risk_budget,
        max_position_notional=notional_budget,
        max_total_open_risk=risk_budget,
    )


class SyntheticAllocationSource:
    def __init__(self, *, quantity: int = 2) -> None:
        self.quantity = quantity

    def allocate(
        self,
        *,
        symbol: str,
        trade_plan_id: str,
        entry_price: float | None,
        stop_price: float | None,
        target_price: float | None,
        decision_at: datetime,
    ):
        del symbol
        return synthetic_quantity_allocation_decision(
            trade_plan_id=trade_plan_id,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            decision_at=decision_at,
            quantity=self.quantity,
        )


class AccountAllocationTests(unittest.TestCase):
    def test_fixed_unit_risk_sizes_whole_shares(self) -> None:
        evidence = allocate()

        self.assertEqual(ALLOCATION_AUTHORIZED, evidence.status)
        self.assertEqual(2, evidence.quantity)
        self.assertEqual(40.0, evidence.position_notional)
        self.assertEqual(4.0, evidence.total_risk)
        self.assertEqual(8.0, evidence.target_reward)
        self.assertEqual(2.0, evidence.reward_risk_ratio)
        self.assertEqual(5.0, evidence.effective_risk_budget)
        self.assertEqual(80.0, evidence.effective_cash_available)

    def test_cash_and_notional_caps_are_independent_of_reference_capital(self) -> None:
        cash_limited = allocate(
            policy=configured_policy(
                fixed_unit_risk_dollars=100.0,
                max_total_open_risk_dollars=100.0,
                max_position_notional_dollars=1_000.0,
            ),
            context=fresh_context(cash_available=55.0, buying_power=60.0),
            entry=20.0,
            stop=19.0,
            target=22.0,
        )
        notional_limited = allocate(
            policy=configured_policy(
                fixed_unit_risk_dollars=100.0,
                max_total_open_risk_dollars=100.0,
                max_position_notional_dollars=45.0,
                minimum_cash_reserve_dollars=0.0,
            ),
            context=fresh_context(cash_available=1_000.0, buying_power=1_000.0),
            entry=20.0,
            stop=19.0,
            target=22.0,
        )

        self.assertEqual(1, cash_limited.quantity)
        self.assertEqual(2, notional_limited.quantity)

    def test_existing_commitments_reduce_cash_and_risk(self) -> None:
        evidence = allocate(
            policy=configured_policy(
                fixed_unit_risk_dollars=8.0,
                max_total_open_risk_dollars=10.0,
                max_position_notional_dollars=100.0,
            ),
            context=fresh_context(committed_notional=20.0, committed_open_risk=7.0),
            entry=20.0,
            stop=18.0,
            target=24.0,
        )

        self.assertEqual(1, evidence.quantity)
        self.assertEqual(3.0, evidence.effective_risk_budget)
        self.assertEqual(60.0, evidence.effective_cash_available)

    def test_unconfigured_policy_fails_closed(self) -> None:
        evidence = allocate(policy=AccountAllocationPolicy())

        self.assertEqual(ALLOCATION_BLOCKED, evidence.status)
        self.assertEqual(0, evidence.quantity)
        self.assertIn("ALLOCATION_POLICY_ID_MISSING", evidence.blockers)
        self.assertIn(
            "ALLOCATION_POLICY_FIXED_UNIT_RISK_MISSING_OR_INVALID",
            evidence.blockers,
        )

    def test_stale_or_future_account_evidence_fails_closed(self) -> None:
        stale = allocate(
            context=fresh_context(
                provider_timestamp=(DECISION_AT - timedelta(seconds=31)).isoformat()
            )
        )
        future = allocate(
            context=fresh_context(
                provider_timestamp=(DECISION_AT + timedelta(seconds=1)).isoformat(),
                receipt_timestamp=(DECISION_AT + timedelta(seconds=2)).isoformat(),
            )
        )

        self.assertIn("ALLOCATION_BALANCE_STALE", stale.blockers)
        self.assertIn("ALLOCATION_RECEIPT_TIMESTAMP_AFTER_DECISION", future.blockers)

    def test_stale_portfolio_state_fails_closed_independently_of_balances(self) -> None:
        evidence = allocate(
            context=fresh_context(
                portfolio_timestamp=(DECISION_AT - timedelta(seconds=31)).isoformat()
            )
        )

        self.assertIn("ALLOCATION_PORTFOLIO_STATE_STALE", evidence.blockers)

    def test_account_isolation_and_transmission_anomalies_fail_closed(self) -> None:
        evidence = allocate(
            context=fresh_context(
                authorized_account_count=3,
                account_ending="9999",
                account_type="MARGIN",
                binding_fingerprint="bad",
                order_transmission="AVAILABLE",
            )
        )

        self.assertEqual(ALLOCATION_BLOCKED, evidence.status)
        self.assertIn("ALLOCATION_ACCOUNT_COUNT_NOT_ONE", evidence.blockers)
        self.assertIn("ALLOCATION_ACCOUNT_ENDING_MISMATCH", evidence.blockers)
        self.assertIn("ALLOCATION_ACCOUNT_TYPE_INVALID", evidence.blockers)
        self.assertIn("ALLOCATION_BINDING_FINGERPRINT_INVALID", evidence.blockers)
        self.assertIn("ALLOCATION_ORDER_TRANSMISSION_NOT_LOCKED", evidence.blockers)

    def test_position_and_daily_loss_limits_fail_closed(self) -> None:
        position_limit = allocate(context=fresh_context(open_position_count=1))
        daily_loss = allocate(context=fresh_context(realized_pnl_today=-10.0))

        self.assertIn("ALLOCATION_POSITION_LIMIT_REACHED", position_limit.blockers)
        self.assertIn("ALLOCATION_DAILY_LOSS_LIMIT_REACHED", daily_loss.blockers)

    def test_boolean_counts_and_naive_decision_time_fail_closed_without_exception(self) -> None:
        boolean_values = allocate(
            policy=configured_policy(
                max_open_positions=True,
                max_balance_age_seconds=True,
            ),
            context=fresh_context(
                authorized_account_count=True,
                open_position_count=True,
            ),
        )
        naive_time = allocate_account_position(
            trade_plan_id="plan-NVDA",
            entry_price=20.0,
            stop_price=18.0,
            target_price=24.0,
            policy=configured_policy(),
            context=fresh_context(),
            decision_at=DECISION_AT.replace(tzinfo=None),
        )

        self.assertIn(
            "ALLOCATION_POLICY_MAX_OPEN_POSITIONS_MISSING_OR_INVALID",
            boolean_values.blockers,
        )
        self.assertIn("ALLOCATION_ACCOUNT_COUNT_NOT_ONE", boolean_values.blockers)
        self.assertIn("ALLOCATION_OPEN_POSITION_COUNT_INVALID", boolean_values.blockers)
        self.assertIn("ALLOCATION_DECISION_TIMESTAMP_NAIVE", naive_time.blockers)

    def test_malformed_text_fields_fail_closed_without_exception(self) -> None:
        evidence = allocate(
            policy=replace(configured_policy(), policy_id=123),
            context=replace(
                fresh_context(),
                binding_fingerprint=123,
                source=123,
                portfolio_source=123,
            ),
        )

        self.assertEqual(ALLOCATION_BLOCKED, evidence.status)
        self.assertIn("ALLOCATION_POLICY_ID_MISSING", evidence.blockers)
        self.assertIn("ALLOCATION_BINDING_FINGERPRINT_INVALID", evidence.blockers)
        self.assertIn("ALLOCATION_ACCOUNT_SOURCE_MISSING", evidence.blockers)
        self.assertIn("ALLOCATION_PORTFOLIO_SOURCE_MISSING", evidence.blockers)

    def test_invalid_plan_values_and_zero_whole_share_result_fail_closed(self) -> None:
        invalid = allocate(entry=20.0, stop=21.0, target=19.0)
        too_expensive = allocate(entry=200.0, stop=198.0, target=204.0)

        self.assertIn("ALLOCATION_STOP_INVALID", invalid.blockers)
        self.assertIn("ALLOCATION_TARGET_INVALID", invalid.blockers)
        self.assertIn("ALLOCATION_ZERO_WHOLE_SHARES", too_expensive.blockers)

    def test_exact_input_is_deterministic_and_tampering_is_detected(self) -> None:
        first = allocate()
        second = allocate()

        self.assertEqual(first, second)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(
            (),
            verify_account_allocation(
                first,
                trade_plan_id="plan-NVDA",
                entry_price=20.0,
                stop_price=18.0,
                target_price=24.0,
                policy=configured_policy(),
                context=fresh_context(),
                decision_at=DECISION_AT,
            ),
        )
        self.assertEqual(
            ("ALLOCATION_EVIDENCE_MISMATCH",),
            verify_account_allocation(
                replace(first, quantity=99),
                trade_plan_id="plan-NVDA",
                entry_price=20.0,
                stop_price=18.0,
                target_price=24.0,
                policy=configured_policy(),
                context=fresh_context(),
                decision_at=DECISION_AT,
            ),
        )

    def test_nonfinite_values_fail_closed(self) -> None:
        evidence = allocate(context=fresh_context(cash_available=float("nan")))

        self.assertIn("ALLOCATION_CASH_AVAILABLE_INVALID", evidence.blockers)
        self.assertEqual(0, evidence.quantity)

    def test_schwab_read_model_bridge_redacts_binding_and_rejects_positions(self) -> None:
        binding = SchwabAccountBinding("opaque-synthetic-hash", "2573", "INDIVIDUAL_CASH")
        accounts = [
            SchwabAuthorizedAccount(
                "opaque-synthetic-hash",
                "2573",
                "INDIVIDUAL_CASH",
                True,
            )
        ]
        balances = SchwabBalances(
            "opaque-synthetic-hash",
            100.0,
            100.0,
            100.0,
            (DECISION_AT - timedelta(seconds=2)).isoformat(),
        )
        portfolio = AccountPortfolioSnapshot(
            committed_notional=0.0,
            committed_open_risk=0.0,
            open_position_count=0,
            realized_pnl_today=0.0,
            observed_at=(DECISION_AT - timedelta(seconds=2)).isoformat(),
            source="SYNTHETIC_SHADOW_STATE",
        )

        context = build_schwab_account_allocation_context(
            binding=binding,
            authorized_accounts=accounts,
            balances=balances,
            broker_positions=[],
            portfolio=portfolio,
            received_at=DECISION_AT - timedelta(seconds=1),
        )
        rendered = repr(context)

        self.assertEqual("2573", context.account_ending)
        self.assertEqual("SCHWAB_READ_ONLY_BOUND_ACCOUNT", context.source)
        self.assertNotIn("opaque-synthetic-hash", rendered)
        self.assertEqual(
            (),
            tuple(
                context_findings(
                    context,
                    configured_policy(),
                    decision_at=DECISION_AT,
                )
            ),
        )
        with self.assertRaisesRegex(AccountIsolationError, "unexpected position"):
            build_schwab_account_allocation_context(
                binding=binding,
                authorized_accounts=accounts,
                balances=balances,
                broker_positions=[
                    SchwabPosition(
                        "opaque-synthetic-hash",
                        "NVDA",
                        1.0,
                        100.0,
                        100.0,
                    )
                ],
                portfolio=portfolio,
                received_at=DECISION_AT - timedelta(seconds=1),
            )

    def test_frozen_source_uses_captured_context_without_io_or_reference_sizing(self) -> None:
        source = FrozenAccountAllocationSource(
            policy=configured_policy(),
            context=fresh_context(),
        )

        decision = source.allocate(
            symbol="NVDA",
            trade_plan_id="plan-NVDA",
            entry_price=20.0,
            stop_price=18.0,
            target_price=24.0,
            decision_at=DECISION_AT,
        )

        self.assertEqual(ALLOCATION_AUTHORIZED, decision.evidence.status)
        self.assertEqual(2, decision.evidence.quantity)

    def test_executable_paths_never_read_the_500_dollar_reference_quantity(self) -> None:
        for module in (
            simulation_module,
            shadow_selection_module,
            shadow_trading_module,
        ):
            with self.subTest(module=module.__name__):
                self.assertNotIn(
                    "estimated_shares_for_500",
                    inspect.getsource(module),
                )


if __name__ == "__main__":
    unittest.main()
