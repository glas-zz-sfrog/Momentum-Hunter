from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from momentum_hunter.broker_capabilities import (
    CAPABILITY_FRACTIONAL_MARKET,
    CAPABILITY_FRACTIONAL_PRECISION,
    CAPABILITY_FRACTIONAL_QUANTITY,
    CAPABILITY_MARKET_ORDER,
    CAPABILITY_WHOLE_QUANTITY,
    BrokerCapability,
    BrokerCapabilityRegistry,
    CapabilityState,
)
from momentum_hunter.provider_neutral_allocation import (
    AccountSnapshot,
    AllocationRequest,
    AllocationStatus,
    ProviderNeutralAllocationPolicy,
    QuantityMode,
    QuantityPolicy,
    allocate_provider_neutral_position,
)


def capability(name: str, state: CapabilityState, value: str = "true") -> BrokerCapability:
    return BrokerCapability(
        name=name,
        state=state,
        value=value,
        evidence=("Synthetic test evidence.",),
    )


def registry(
    *,
    fractional: CapabilityState = CapabilityState.PROVEN,
    fractional_market: CapabilityState = CapabilityState.PROVEN,
    whole: CapabilityState = CapabilityState.PROVEN,
    market: CapabilityState = CapabilityState.PROVEN,
    precision: str = "0.001",
    provider: str = "SYNTHETIC_BROKER",
    environment: str = "PAPER",
) -> BrokerCapabilityRegistry:
    return BrokerCapabilityRegistry.build(
        provider=provider,
        environment=environment,
        capabilities=(
            capability(CAPABILITY_FRACTIONAL_QUANTITY, fractional),
            capability(CAPABILITY_FRACTIONAL_PRECISION, fractional, precision),
            capability(CAPABILITY_FRACTIONAL_MARKET, fractional_market),
            capability(CAPABILITY_WHOLE_QUANTITY, whole),
            capability(CAPABILITY_MARKET_ORDER, market),
        ),
    )


def policy(**changes: object) -> ProviderNeutralAllocationPolicy:
    value = ProviderNeutralAllocationPolicy(
        policy_id="synthetic-policy-v1",
        fixed_unit_risk_dollars=Decimal("5"),
        max_position_notional_dollars=Decimal("100"),
        minimum_cash_reserve_dollars=Decimal("10"),
        max_total_open_risk_dollars=Decimal("10"),
        daily_loss_limit_dollars=Decimal("10"),
        max_open_positions=3,
        max_snapshot_age_seconds=30,
    )
    return replace(value, **changes)


def account(**changes: object) -> AccountSnapshot:
    value = AccountSnapshot(
        snapshot_id="account-snapshot-1",
        decision_cycle_id="cycle-1",
        lane="CANARY_REALISTIC",
        provider="SYNTHETIC_BROKER",
        environment="PAPER",
        binding_fingerprint="A" * 64,
        authorized_account_count=1,
        status="ACTIVE",
        cash_available=Decimal("100"),
        buying_power=Decimal("100"),
        committed_notional=Decimal("0"),
        committed_open_risk=Decimal("0"),
        open_position_count=0,
        realized_pnl_today=Decimal("0"),
        provider_timestamp="2026-08-10T14:30:00+00:00",
        portfolio_timestamp="2026-08-10T14:30:00+00:00",
        receipt_timestamp="2026-08-10T14:30:01+00:00",
        source_identity="synthetic-account-source",
    )
    return replace(value, **changes)


def request(**changes: object) -> AllocationRequest:
    value = AllocationRequest(
        decision_cycle_id="cycle-1",
        candidate_id="candidate-1",
        canonical_rank=1,
        symbol="TEST",
        trade_plan_id="plan-1",
        risk_decision_id="risk-1",
        entry_order_type="market",
        entry_price=Decimal("20"),
        stop_price=Decimal("19"),
        target_price=Decimal("22"),
        decision_at="2026-08-10T14:30:02+00:00",
    )
    return replace(value, **changes)


class ProviderNeutralAllocationTests(unittest.TestCase):
    def allocate(
        self,
        *,
        request_value: AllocationRequest | None = None,
        policy_value: ProviderNeutralAllocationPolicy | None = None,
        account_value: AccountSnapshot | None = None,
        registry_value: BrokerCapabilityRegistry | None = None,
    ):
        return allocate_provider_neutral_position(
            request=request_value or request(),
            policy=policy_value or policy(),
            account=account_value or account(),
            capabilities=registry_value or registry(),
        )

    def test_fractional_capabilities_preserve_three_quantity_stages(self) -> None:
        decision = self.allocate()

        self.assertTrue(decision.authorized)
        self.assertEqual(AllocationStatus.AUTHORIZED, decision.status)
        self.assertEqual(QuantityMode.FRACTIONAL, decision.quantity_mode)
        self.assertEqual(Decimal("0.001"), decision.quantity_increment)
        self.assertEqual(Decimal("5"), decision.ideal_risk_quantity)
        self.assertEqual(Decimal("5.000"), decision.provider_executable_quantity)
        self.assertEqual(Decimal("4.500"), decision.final_authorized_quantity)
        self.assertEqual(
            "4.5", decision.to_dict()["finalAuthorizedQuantity"]
        )

    def test_whole_share_fallback_is_explicit(self) -> None:
        capabilities = registry(
            fractional=CapabilityState.DOCUMENTED_UNPROVEN,
            fractional_market=CapabilityState.DOCUMENTED_UNPROVEN,
        )

        decision = self.allocate(registry_value=capabilities)

        self.assertTrue(decision.authorized)
        self.assertEqual(QuantityMode.WHOLE, decision.quantity_mode)
        self.assertEqual(Decimal("5"), decision.provider_executable_quantity)
        self.assertEqual(Decimal("4"), decision.final_authorized_quantity)
        self.assertIn("ALLOCATION_FRACTIONAL_CAPABILITY_NOT_USED", decision.warnings)

    def test_whole_only_policy_requires_proven_whole_quantity(self) -> None:
        capabilities = registry(whole=CapabilityState.UNKNOWN)

        decision = self.allocate(
            policy_value=policy(quantity_policy=QuantityPolicy.WHOLE_ONLY),
            registry_value=capabilities,
        )

        self.assertFalse(decision.authorized)
        self.assertEqual(QuantityMode.UNAVAILABLE, decision.quantity_mode)
        self.assertIn(
            "ALLOCATION_WHOLE_QUANTITY_CAPABILITY_UNPROVEN", decision.blockers
        )

    def test_fractional_order_capability_must_match_order_type(self) -> None:
        capabilities = registry(
            fractional_market=CapabilityState.DOCUMENTED_UNPROVEN,
            whole=CapabilityState.UNSUPPORTED,
        )

        decision = self.allocate(registry_value=capabilities)

        self.assertFalse(decision.authorized)
        self.assertIn(
            "ALLOCATION_FRACTIONAL_ORDER_CAPABILITY_UNPROVEN", decision.blockers
        )

    def test_fractional_order_proof_does_not_require_redundant_generic_flag(self) -> None:
        decision = self.allocate(
            registry_value=registry(market=CapabilityState.DOCUMENTED_UNPROVEN)
        )

        self.assertTrue(decision.authorized)
        self.assertEqual(QuantityMode.FRACTIONAL, decision.quantity_mode)

    def test_whole_share_mode_requires_generic_order_capability(self) -> None:
        decision = self.allocate(
            registry_value=registry(
                fractional=CapabilityState.DOCUMENTED_UNPROVEN,
                fractional_market=CapabilityState.DOCUMENTED_UNPROVEN,
                market=CapabilityState.DOCUMENTED_UNPROVEN,
            )
        )

        self.assertFalse(decision.authorized)
        self.assertIn("ALLOCATION_ENTRY_ORDER_CAPABILITY_UNPROVEN", decision.blockers)

    def test_buying_power_and_cash_reserve_cap_final_quantity(self) -> None:
        decision = self.allocate(
            account_value=account(cash_available=Decimal("80"), buying_power=Decimal("25"))
        )

        self.assertTrue(decision.authorized)
        self.assertEqual(Decimal("15"), decision.effective_cash_available)
        self.assertEqual(Decimal("0.750"), decision.final_authorized_quantity)

    def test_snapshot_freshness_blocks_stale_account(self) -> None:
        decision = self.allocate(
            account_value=account(
                provider_timestamp="2026-08-10T14:29:20+00:00",
                portfolio_timestamp="2026-08-10T14:29:20+00:00",
            )
        )

        self.assertFalse(decision.authorized)
        self.assertIn("ALLOCATION_ACCOUNT_SNAPSHOT_STALE", decision.blockers)
        self.assertEqual(Decimal("0"), decision.final_authorized_quantity)

    def test_aggregate_open_risk_caps_remaining_quantity(self) -> None:
        decision = self.allocate(
            account_value=account(committed_open_risk=Decimal("9"))
        )

        self.assertTrue(decision.authorized)
        self.assertEqual(Decimal("1"), decision.effective_open_risk_available)
        self.assertEqual(Decimal("1.000"), decision.final_authorized_quantity)

    def test_existing_committed_notional_reduces_deployable_cash(self) -> None:
        decision = self.allocate(
            account_value=account(committed_notional=Decimal("50"))
        )

        self.assertTrue(decision.authorized)
        self.assertEqual(Decimal("40"), decision.effective_cash_available)
        self.assertEqual(Decimal("2.000"), decision.final_authorized_quantity)

    def test_account_snapshot_is_bound_to_one_decision_cycle(self) -> None:
        decision = self.allocate(
            account_value=account(decision_cycle_id="different-cycle")
        )

        self.assertFalse(decision.authorized)
        self.assertIn("ALLOCATION_ACCOUNT_DECISION_CYCLE_MISMATCH", decision.blockers)

    def test_configurable_concurrency_blocks_at_limit(self) -> None:
        decision = self.allocate(
            policy_value=policy(max_open_positions=2),
            account_value=account(open_position_count=2),
        )

        self.assertFalse(decision.authorized)
        self.assertIn("ALLOCATION_POSITION_LIMIT_REACHED", decision.blockers)

    def test_daily_loss_limit_blocks_new_position(self) -> None:
        decision = self.allocate(
            account_value=account(realized_pnl_today=Decimal("-10"))
        )

        self.assertFalse(decision.authorized)
        self.assertIn("ALLOCATION_DAILY_LOSS_LIMIT_REACHED", decision.blockers)

    def test_provider_and_environment_must_match_snapshot(self) -> None:
        decision = self.allocate(
            account_value=account(provider="OTHER", environment="LIVE")
        )

        self.assertFalse(decision.authorized)
        self.assertIn("ALLOCATION_PROVIDER_MISMATCH", decision.blockers)
        self.assertIn("ALLOCATION_ENVIRONMENT_MISMATCH", decision.blockers)

    def test_malformed_numeric_values_fail_closed_without_exception(self) -> None:
        decision = self.allocate(
            policy_value=policy(max_open_positions="three"),  # type: ignore[arg-type]
            account_value=account(
                cash_available="unknown",  # type: ignore[arg-type]
                open_position_count="none",  # type: ignore[arg-type]
            ),
        )

        self.assertFalse(decision.authorized)
        self.assertIn("ALLOCATION_POLICY_MAX_POSITIONS_INVALID", decision.blockers)
        self.assertIn("ALLOCATION_ACCOUNT_CASH_INVALID", decision.blockers)
        self.assertIn("ALLOCATION_OPEN_POSITION_COUNT_INVALID", decision.blockers)

    def test_output_is_deterministic_and_inputs_are_immutable(self) -> None:
        source_request = request()
        source_policy = policy()
        source_account = account()
        source_registry = registry()

        first = self.allocate(
            request_value=source_request,
            policy_value=source_policy,
            account_value=source_account,
            registry_value=source_registry,
        )
        second = self.allocate(
            request_value=source_request,
            policy_value=source_policy,
            account_value=source_account,
            registry_value=source_registry,
        )

        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(Decimal("100"), source_account.cash_available)
        self.assertEqual(Decimal("5"), source_policy.fixed_unit_risk_dollars)


if __name__ == "__main__":
    unittest.main()
