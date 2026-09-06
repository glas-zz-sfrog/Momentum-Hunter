"""Synthetic upstream strategy results; no provider or execution authority."""
from decimal import Decimal
import json

from tests import test_continuous_natural_setup as native
from tests import test_provider_neutral_allocation as allocation_fixture
from momentum_hunter.broker_capabilities import CAPABILITY_LIMIT_ORDER, CapabilityState
from momentum_hunter.continuous_tradeplan_producer import InstrumentAdmissionEvidence, COMMON_STOCK
from momentum_hunter.paper_risk_governor import PaperRiskDecision, PAPER_RISK_MODE
from momentum_hunter.provider_neutral_allocation import (
    AllocationRequest, QuantityPolicy, allocate_provider_neutral_position,
)
from momentum_hunter.continuous_operational_admission import publish_strategy_result, admit_continuous


class EligibleMarket(native.ContinuousNaturalSetupTests):
    def _append_initial_sequence(self):
        bars = [native.SchwabMinuteCandle(symbol=self.fixture_symbol, timestamp=native.at(11, minute),
            open=99.9, high=100.0, low=99.8, close=99.9, volume=100.0,
            source=native.SCHWAB_PRICE_HISTORY_SOURCE) for minute in range(20)]
        bars.append(native.SchwabMinuteCandle(symbol=self.fixture_symbol, timestamp=native.at(11, 20),
            open=100.01, high=100.08, low=100.0, close=100.05, volume=200.0,
            source=native.SCHWAB_PRICE_HISTORY_SOURCE))
        native.SchwabCandleStore(self.minute_root).append_history(tuple(bars), received_at=native.at(11, 21))

    def _prepare(self, cutoff, *, generation):
        super()._prepare(cutoff, generation=generation)
        self.state.instrument_admissions[self.fixture_symbol] = InstrumentAdmissionEvidence(
            evidence_id=f"synthetic-instrument-{self.fixture_symbol}", symbol=self.fixture_symbol,
            observed_at=cutoff.isoformat(), source_identity="SYNTHETIC_AUTHORITATIVE_INSTRUMENT_MASTER",
            instrument_class=COMMON_STOCK, authoritative=True,
            evidence_fingerprint=native.fingerprint((self.fixture_symbol, COMMON_STOCK)))


def eligible_market_fixture(method):
    return EligibleMarket(method)




def strategy_results(decision, epoch, *, blocked=False, quantity=2, order_type="limit", when=None):
    record = decision.validate(epoch)
    plan = next(row for row in json.loads(record.payload_json)["compositionCycle"]["member_results"]
                if row["universe_member_id"] == record.member_id)["intraday_plan"]
    when = when or "2026-08-17T11:21:01-04:00"
    risk = PaperRiskDecision("synthetic-risk-" + record.record_id, record.record_id, record.symbol, 1,
        record.trade_plan_id, record.setup_id, when, PAPER_RISK_MODE,
        "BLOCKED" if blocked else "AUTHORIZED", Decimal(str(plan["planned_entry"])),
        Decimal("0.01"), Decimal("2"), ("SYNTHETIC_RISK_REJECTION",) if blocked else (),
        "a" * 64, record.fingerprint, "b" * 64)
    request = AllocationRequest("synthetic-cycle-" + record.record_id, record.record_id, 1, record.symbol,
        record.trade_plan_id, risk.risk_decision_id, order_type, risk.execution_price,
        Decimal(str(plan["stop_price"])), Decimal(str(plan["target_prices"][0])), when)
    capabilities = allocation_fixture.registry()
    capabilities = type(capabilities).build(provider=capabilities.provider, environment=capabilities.environment,
        capabilities=(*capabilities.capabilities,
            allocation_fixture.capability(CAPABILITY_LIMIT_ORDER, CapabilityState.PROVEN)))
    policy = allocation_fixture.policy(fixed_unit_risk_dollars=Decimal("100"),
        max_position_notional_dollars=request.entry_price * quantity,
        max_total_open_risk_dollars=Decimal("1000"), quantity_policy=QuantityPolicy.WHOLE_ONLY)
    account = allocation_fixture.account(decision_cycle_id=request.decision_cycle_id,
        cash_available=Decimal("10000"), buying_power=Decimal("10000"),
        provider_timestamp=when, portfolio_timestamp=when, receipt_timestamp=when)
    allocation = allocate_provider_neutral_position(request=request, policy=policy,
                                                  account=account, capabilities=capabilities)
    return risk, request, allocation


def approved_admission(decision, epoch):
    risk, request, allocation = strategy_results(decision, epoch)
    strategy = publish_strategy_result(decision=decision, epoch=epoch, risk=risk,
        request=request, allocation=allocation, recorded_at=risk.decision_at)
    return admit_continuous(epoch=epoch, strategy_snapshot=strategy, admitted_at=risk.decision_at)
