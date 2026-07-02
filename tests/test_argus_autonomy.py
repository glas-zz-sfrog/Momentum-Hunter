from __future__ import annotations

import inspect
import unittest

from momentum_hunter.autonomy.auditor import audit_execution_ledger, audit_paper_advancement_gate, audit_simulation_chain
from momentum_hunter.autonomy.ledger import ExecutionLedgerEvent
from momentum_hunter.autonomy.broker import (
    BrokerAccount,
    BrokerAdapter,
    BrokerAdapterMetadata,
    BrokerOrder,
    BrokerOrderRequest,
    BrokerPosition,
    FakeBrokerAdapter,
)
from momentum_hunter.autonomy.ledger import ExecutionLedger
from momentum_hunter.autonomy.risk_governor import evaluate_trade_plan
from momentum_hunter.autonomy.simulation import SimulationLabEngine
from momentum_hunter.autonomy.view_models import build_candidate_plans_from_candidates, ladder_rows_for_candidate
from momentum_hunter.models import Candidate, NewsItem, NewsStack
from momentum_hunter.trade_planning import TradePlan


class ArgusAutonomyTests(unittest.TestCase):
    def test_top5_candidates_use_tradeplan_objects_and_safe_labels(self) -> None:
        plans = build_candidate_plans_from_candidates(sample_candidates())

        self.assertEqual(5, len(plans))
        self.assertEqual("AAA", plans[0].ticker)
        self.assertIsInstance(plans[0].trade_plan, TradePlan)
        self.assertIn("Gate:", plans[0].button_text)
        self.assertNotIn("approved", plans[0].button_text.lower())
        rows = {row.field: row.value for row in ladder_rows_for_candidate(plans[0])}
        self.assertNotEqual("Missing", rows["Entry/limit"])
        self.assertNotEqual("Missing", rows["Stop/invalidation"])

    def test_risk_governor_blocks_missing_stop_and_max_risk(self) -> None:
        plan = TradePlan(
            bullish_entry=10.0,
            bullish_stop=None,
            bullish_target_1=12.0,
            bullish_target_2=13.0,
            risk_reward_ratio=None,
            estimated_shares_for_500=50.0,
            estimated_dollar_risk=None,
            estimated_target_1_reward=100.0,
            confidence="LOW",
            tradeability="LOW",
            readiness="DO_NOT_TRADE_MISSING_DATA",
            blocking_reasons=["MISSING_STOP"],
            warnings=[],
        )

        result = evaluate_trade_plan(plan, ticker="AAA", trade_plan_id="tp-AAA")

        self.assertEqual("Blocked", result.status)
        self.assertFalse(result.allows_simulation)
        self.assertTrue(any(gate.name == "Stop defined" and gate.state == "Blocked" for gate in result.gates))

    def test_risk_governor_blocks_missing_risk_only(self) -> None:
        plan = complete_trade_plan(estimated_dollar_risk=None)

        result = evaluate_trade_plan(plan, ticker="AAA", trade_plan_id="tp-AAA")

        self.assertEqual("Blocked", result.status)
        self.assertFalse(result.allows_simulation)
        self.assertTrue(any(gate.name == "Max risk" and gate.state == "Blocked" for gate in result.gates))

    def test_risk_governor_blocks_live_mode(self) -> None:
        result = evaluate_trade_plan(complete_trade_plan(), ticker="AAA", trade_plan_id="tp-AAA", mode="Live Preview")

        self.assertEqual("Blocked", result.status)
        self.assertFalse(result.allows_simulation)
        self.assertTrue(any(gate.name == "Broker mode" and gate.state == "Blocked" for gate in result.gates))

    def test_manual_override_requires_risk_recheck(self) -> None:
        result = evaluate_trade_plan(
            complete_trade_plan(),
            ticker="AAA",
            trade_plan_id="tp-AAA",
            manual_override_pending=True,
        )

        self.assertEqual("Blocked", result.status)
        self.assertFalse(result.allows_simulation)
        self.assertTrue(any(gate.name == "Manual override" and gate.state == "Blocked" for gate in result.gates))

    def test_execution_ledger_serializes_events(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="candidate_selected",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="candidate_selected",
            result="selected",
            reason="test",
        )

        restored = ExecutionLedger.from_dicts(ledger.to_dicts())

        self.assertEqual(1, len(restored.events))
        self.assertEqual("AAA", restored.events[0].ticker)
        self.assertEqual("candidate_selected", restored.events[0].requested_action)

    def test_fake_broker_lifecycle_and_rejection(self) -> None:
        adapter = FakeBrokerAdapter(reject_symbols={"BAD"})
        request = BrokerOrderRequest(
            ticker="AAA",
            side="buy",
            quantity=10,
            order_type="limit",
            limit_price=10.0,
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
        )
        rejected_request = BrokerOrderRequest(
            ticker="BAD",
            side="buy",
            quantity=10,
            order_type="limit",
            limit_price=10.0,
            trade_plan_id="tp-BAD",
            risk_result_id="risk-BAD",
        )

        preview = adapter.preview_order(request)
        filled = adapter.submit_order(request)
        rejected = adapter.submit_order(rejected_request)

        self.assertEqual("previewed", preview.status)
        self.assertEqual("filled", filled.status)
        self.assertEqual("rejected", rejected.status)
        self.assertFalse(adapter.metadata.order_transmit_allowed)
        self.assertEqual(1, len(adapter.get_positions()))

    def test_simulation_engine_records_pass_and_audits_chain(self) -> None:
        candidate = build_candidate_plans_from_candidates(sample_candidates())[0]
        ledger = ExecutionLedger()
        engine = SimulationLabEngine(adapter=FakeBrokerAdapter(), ledger=ledger)

        result = engine.run_candidate(candidate)
        audit = audit_simulation_chain(ledger, ticker=candidate.ticker, trade_plan_id=candidate.trade_plan_id)
        order_events = [
            event for event in ledger.events if event.requested_action in {"simulated_order_previewed", "fake_order_submitted"}
        ]

        self.assertEqual("filled", result.status)
        self.assertTrue(audit.passed)
        self.assertIn("fake_order_submitted", {event.requested_action for event in ledger.events})
        self.assertTrue(order_events)
        self.assertTrue(all(event.trade_plan_id == candidate.trade_plan_id for event in order_events))
        self.assertTrue(all(event.risk_result_id == candidate.risk_result.result_id for event in order_events))

    def test_simulation_engine_records_fake_rejection(self) -> None:
        candidate = build_candidate_plans_from_candidates(sample_candidates())[0]
        ledger = ExecutionLedger()
        engine = SimulationLabEngine(adapter=FakeBrokerAdapter(reject_symbols={candidate.ticker}), ledger=ledger)

        result = engine.run_candidate(candidate)

        self.assertEqual("rejected", result.status)
        self.assertIn("FakeBroker configured rejection", result.submitted_order.reason)

    def test_simulation_engine_rejects_non_fake_adapter_before_broker_calls(self) -> None:
        candidate = build_candidate_plans_from_candidates(sample_candidates())[0]
        ledger = ExecutionLedger()
        adapter = RecordingBrokerAdapter(
            BrokerAdapterMetadata(
                adapter_name="ResearchOnlyAdapter",
                mode="Simulation Lab",
                capabilities=["preview_order", "submit_order"],
                order_transmit_allowed=False,
                credential_status="not required",
                last_health_check="2026-07-01T08:00:00-05:00",
            )
        )
        engine = SimulationLabEngine(adapter=adapter, ledger=ledger)

        result = engine.run_candidate(candidate)

        self.assertEqual("blocked", result.status)
        self.assertEqual([], adapter.calls)
        self.assertIn("FakeBrokerAdapter", result.message)
        self.assertIn("simulation_blocked", {event.requested_action for event in ledger.events})
        self.assertNotIn("simulated_order_previewed", {event.requested_action for event in ledger.events})
        self.assertNotIn("fake_order_submitted", {event.requested_action for event in ledger.events})

    def test_simulation_engine_rejects_transmit_capable_adapter_before_broker_calls(self) -> None:
        candidate = build_candidate_plans_from_candidates(sample_candidates())[0]
        ledger = ExecutionLedger()
        adapter = RecordingBrokerAdapter(
            BrokerAdapterMetadata(
                adapter_name="FakeBrokerAdapter",
                mode="Simulation Lab",
                capabilities=["preview_order", "submit_order", "transmit_order"],
                order_transmit_allowed=True,
                credential_status="configured",
                last_health_check="2026-07-01T08:00:00-05:00",
            )
        )
        engine = SimulationLabEngine(adapter=adapter, ledger=ledger)

        result = engine.run_candidate(candidate)

        self.assertEqual("blocked", result.status)
        self.assertEqual([], adapter.calls)
        self.assertIn("transmit", result.message.lower())
        self.assertIn("simulation_blocked", {event.requested_action for event in ledger.events})
        self.assertNotIn("simulated_order_previewed", {event.requested_action for event in ledger.events})
        self.assertNotIn("fake_order_submitted", {event.requested_action for event in ledger.events})

    def test_paper_advancement_gate_passes_complete_simulation_chain(self) -> None:
        candidate = build_candidate_plans_from_candidates(sample_candidates())[0]
        ledger = ExecutionLedger()
        SimulationLabEngine(adapter=FakeBrokerAdapter(), ledger=ledger).run_candidate(candidate)

        report = audit_paper_advancement_gate(ledger, ticker=candidate.ticker, trade_plan_id=candidate.trade_plan_id)

        self.assertTrue(report.passed)
        self.assertEqual("PASS", report.status)

    def test_paper_advancement_gate_blocks_missing_tradeplan_evidence(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="risk_gate_evaluated",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="risk_gate_evaluated",
            result="Simulation-only",
        )
        ledger.record(
            event_type="fake_order_submitted",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="fake_order_submitted",
            result="filled",
        )

        report = audit_paper_advancement_gate(ledger, ticker="AAA", trade_plan_id="")

        self.assertFalse(report.passed)
        self.assertEqual("BLOCK", report.status)
        self.assertTrue(any(finding.field == "trade_plan_id" for finding in report.findings))

    def test_paper_advancement_gate_blocks_missing_order_evidence(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="risk_gate_evaluated",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="risk_gate_evaluated",
            result="Simulation-only",
        )

        report = audit_paper_advancement_gate(ledger, ticker="AAA", trade_plan_id="tp-AAA")

        self.assertFalse(report.passed)
        self.assertEqual("BLOCK", report.status)
        self.assertTrue(any(finding.field == "result" for finding in report.findings))

    def test_fake_broker_has_no_real_broker_network_path(self) -> None:
        source = inspect.getsource(FakeBrokerAdapter)
        metadata = FakeBrokerAdapter().metadata

        self.assertNotIn("requests", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("http", source.lower())
        self.assertEqual("FakeBrokerAdapter", metadata.adapter_name)
        self.assertEqual("not required", metadata.credential_status)
        self.assertFalse(metadata.order_transmit_allowed)

    def test_auditor_fails_missing_required_order_fields(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="fake_order_submitted",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="fake_order_submitted",
            result="filled",
        )

        report = audit_execution_ledger(ledger)

        self.assertFalse(report.passed)
        self.assertTrue(any(finding.field == "trade_plan_id" for finding in report.findings))

    def test_auditor_fails_missing_risk_result_id(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="fake_order_submitted",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="",
            broker_adapter="FakeBrokerAdapter",
            requested_action="fake_order_submitted",
            result="filled",
        )

        report = audit_execution_ledger(ledger)

        self.assertFalse(report.passed)
        self.assertTrue(any(finding.field == "risk_result_id" for finding in report.findings))

    def test_auditor_fails_submit_without_preview_evidence(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="risk_gate_evaluated",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="risk_gate_evaluated",
            result="Simulation-only",
        )
        ledger.record(
            event_type="fake_order_submitted",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="fake_order_submitted",
            result="filled",
        )

        report = audit_simulation_chain(ledger, ticker="AAA", trade_plan_id="tp-AAA")

        self.assertFalse(report.passed)
        self.assertTrue(any(finding.field == "preview_order" for finding in report.findings))

    def test_auditor_fails_order_event_before_risk_gate(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="fake_order_submitted",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="fake_order_submitted",
            result="filled",
        )
        ledger.record(
            event_type="risk_gate_evaluated",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="risk_gate_evaluated",
            result="Simulation-only",
        )
        ledger.record(
            event_type="simulated_order_created",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="simulated_order_previewed",
            result="previewed",
        )

        report = audit_simulation_chain(ledger, ticker="AAA", trade_plan_id="tp-AAA")

        self.assertFalse(report.passed)
        self.assertTrue(any(finding.field == "chronology" for finding in report.findings))

    def test_auditor_fails_invalid_order_evidence(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="fake_order_submitted",
            mode="Live Preview",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="LiveBrokerAdapter",
            approval_state="live-preview",
            requested_action="fake_order_submitted",
            result="filled",
        )

        report = audit_execution_ledger(ledger)

        self.assertFalse(report.passed)
        fields = {finding.field for finding in report.findings}
        self.assertIn("mode", fields)
        self.assertIn("broker_adapter", fields)
        self.assertIn("approval_state", fields)

    def test_auditor_fails_missing_risk_gate_in_simulation_chain(self) -> None:
        ledger = ExecutionLedger()
        ledger.record(
            event_type="fake_order_submitted",
            mode="Simulation Lab",
            ticker="AAA",
            trade_plan_id="tp-AAA",
            risk_result_id="risk-AAA",
            broker_adapter="FakeBrokerAdapter",
            requested_action="fake_order_submitted",
            result="filled",
        )

        report = audit_simulation_chain(ledger, ticker="AAA", trade_plan_id="tp-AAA")

        self.assertFalse(report.passed)
        self.assertTrue(any(finding.field == "risk_result_id" for finding in report.findings))

    def test_auditor_fails_duplicate_order_like_event_ids(self) -> None:
        event = order_like_event(event_id="ledger-duplicate")
        ledger = ExecutionLedger([event, event])

        report = audit_execution_ledger(ledger)

        self.assertFalse(report.passed)
        self.assertTrue(any(finding.field == "event_id" for finding in report.findings))

    def test_auditor_fails_missing_order_like_event_id(self) -> None:
        ledger = ExecutionLedger([order_like_event(event_id="")])

        report = audit_execution_ledger(ledger)

        self.assertFalse(report.passed)
        self.assertTrue(any(finding.field == "event_id" for finding in report.findings))


def sample_candidates() -> list[Candidate]:
    return [
        sample_candidate("AAA", 10.0, 95),
        sample_candidate("BBB", 11.0, 90),
        sample_candidate("CCC", 12.0, 85),
        sample_candidate("DDD", 13.0, 80),
        sample_candidate("EEE", 14.0, 75),
        sample_candidate("FFF", 15.0, 70),
    ]


def sample_candidate(ticker: str, price: float, score: int) -> Candidate:
    headline = f"{ticker} rallies on AI contract momentum"
    return Candidate(
        ticker=ticker,
        company=f"{ticker} Corp",
        price=price,
        percent_change=5.0,
        volume=15_000_000,
        relative_volume=1.8,
        market_cap=12_000_000_000,
        sector="Technology",
        industry="Software",
        news=[NewsItem(headline=headline, source="Test")],
        score=score,
        freshness_score=90,
        news_stack=NewsStack(article_count=1, freshest_headline=headline, freshness_score=90, freshness="HOT"),
    )


def complete_trade_plan(**overrides: object) -> TradePlan:
    values = {
        "bullish_entry": 10.0,
        "bullish_stop": 9.5,
        "bullish_target_1": 11.0,
        "bullish_target_2": 11.5,
        "risk_reward_ratio": 2.0,
        "estimated_shares_for_500": 50.0,
        "estimated_dollar_risk": 25.0,
        "estimated_target_1_reward": 50.0,
        "confidence": "HIGH",
        "tradeability": "HIGH",
        "readiness": "EXECUTION_READY_TRADE",
        "blocking_reasons": [],
        "warnings": [],
    }
    values.update(overrides)
    return TradePlan(**values)


def order_like_event(*, event_id: str) -> ExecutionLedgerEvent:
    return ExecutionLedgerEvent(
        event_id=event_id,
        timestamp="2026-06-30T08:00:00-05:00",
        event_type="fake_order_submitted",
        mode="Simulation Lab",
        ticker="AAA",
        trade_plan_id="tp-AAA",
        risk_result_id="risk-AAA",
        broker_adapter="FakeBrokerAdapter",
        approval_state="simulation-only",
        requested_action="fake_order_submitted",
        result="filled",
        actor="Argus Machine",
        source="test",
    )


class RecordingBrokerAdapter(BrokerAdapter):
    def __init__(self, metadata: BrokerAdapterMetadata) -> None:
        self._metadata = metadata
        self.calls: list[str] = []

    @property
    def metadata(self) -> BrokerAdapterMetadata:
        return self._metadata

    def get_account(self) -> BrokerAccount:
        self.calls.append("get_account")
        return BrokerAccount(account_id="recording", buying_power=0.0, mode=self.metadata.mode)

    def get_positions(self) -> list[BrokerPosition]:
        self.calls.append("get_positions")
        return []

    def preview_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        self.calls.append("preview_order")
        return BrokerOrder(
            order_id="recording-preview",
            ticker=request.ticker,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            status="previewed",
            trade_plan_id=request.trade_plan_id,
            risk_result_id=request.risk_result_id,
        )

    def submit_order(self, request: BrokerOrderRequest) -> BrokerOrder:
        self.calls.append("submit_order")
        return BrokerOrder(
            order_id="recording-submit",
            ticker=request.ticker,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            limit_price=request.limit_price,
            status="filled",
            trade_plan_id=request.trade_plan_id,
            risk_result_id=request.risk_result_id,
        )

    def cancel_order(self, order_id: str) -> BrokerOrder:
        self.calls.append("cancel_order")
        raise KeyError(order_id)

    def get_order_status(self, order_id: str) -> BrokerOrder:
        self.calls.append("get_order_status")
        raise KeyError(order_id)

    def list_orders(self) -> list[BrokerOrder]:
        self.calls.append("list_orders")
        return []


if __name__ == "__main__":
    unittest.main()
