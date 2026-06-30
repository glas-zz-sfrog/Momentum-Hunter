from __future__ import annotations

import unittest

from momentum_hunter.autonomy.auditor import audit_execution_ledger, audit_simulation_chain
from momentum_hunter.autonomy.ledger import ExecutionLedgerEvent
from momentum_hunter.autonomy.broker import BrokerOrderRequest, FakeBrokerAdapter
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

        self.assertEqual("filled", result.status)
        self.assertTrue(audit.passed)
        self.assertIn("fake_order_submitted", {event.requested_action for event in ledger.events})

    def test_simulation_engine_records_fake_rejection(self) -> None:
        candidate = build_candidate_plans_from_candidates(sample_candidates())[0]
        ledger = ExecutionLedger()
        engine = SimulationLabEngine(adapter=FakeBrokerAdapter(reject_symbols={candidate.ticker}), ledger=ledger)

        result = engine.run_candidate(candidate)

        self.assertEqual("rejected", result.status)
        self.assertIn("FakeBroker configured rejection", result.submitted_order.reason)

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


if __name__ == "__main__":
    unittest.main()
