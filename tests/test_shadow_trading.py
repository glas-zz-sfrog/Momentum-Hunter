from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.engine_host import (
    COMMAND_ADVANCE_SHADOW_TRADES,
    COMMAND_SHADOW_WORKSPACE_SNAPSHOT,
    COMMAND_START_SHADOW_TRADE,
    EngineHostRuntime,
)
from momentum_hunter.shadow_market_validity import (
    SHADOW_SELECTOR_ARM_CONFIRMATION,
    synthetic_pass_proofs,
)
from momentum_hunter.shadow_selection import AutomaticShadowSelector
from momentum_hunter.scheduling import is_market_open_day
from momentum_hunter.shadow_trading import (
    MIN_MEANINGFUL_SAMPLE_SIZE,
    SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
    ShadowExecutionPolicy,
    ShadowOutcome,
    ShadowOrder,
    ShadowQuote,
    ShadowStateStore,
    ShadowTradingService,
    ProspectiveFakeBroker,
    audit_shadow_trade,
    build_shadow_review_snapshot,
    canonical_json,
    shadow_metrics,
    stable_id,
)
from momentum_hunter.workstation_shadow import ShadowWorkspacePaths, ShadowWorkspaceService


class _BatchMarketQuoteSource:
    def __init__(
        self,
        quotes: dict[str, dict],
        *,
        return_unrequested: bool = False,
    ) -> None:
        self.values = quotes
        self.return_unrequested = return_unrequested
        self.calls: list[tuple[tuple[str, ...], datetime]] = []

    def quotes(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime,
    ) -> dict[str, dict]:
        self.calls.append((tuple(symbols), decision_at))
        if self.return_unrequested:
            return {
                symbol: dict(quote)
                for symbol, quote in self.values.items()
            }
        return {
            symbol: dict(self.values[symbol])
            for symbol in symbols
            if symbol in self.values
        }


class ShadowTradingLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report_path = self.root / "trade-plan.json"
        self.state_path = self.root / "shadow-state.json"
        self.report_path.write_text(json.dumps(report_payload()), encoding="utf-8")
        self.policy = ShadowExecutionPolicy(
            slippage_bps=10,
            max_quote_age_seconds=90,
            minimum_fill_delay_seconds=1,
            buying_power=1_000,
            max_open_positions=3,
            daily_loss_limit=100,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def service(self) -> ShadowTradingService:
        return ShadowTradingService(store=ShadowStateStore(self.state_path), policy=self.policy)

    def start(self, *, command_id: str = "shadow-command-1", symbol: str = "TEST"):
        return self.service().start_trade(
            self.report_path,
            symbol=symbol,
            simulation_command_id=command_id,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )

    def test_start_freezes_source_evidence_and_assigns_every_required_identifier(self) -> None:
        before = sha256(self.report_path)
        trade = self.start()

        self.assertEqual(before, sha256(self.report_path))
        self.assertEqual("pending_entry", trade.status)
        self.assertTrue(trade.candidate_id.startswith("candidate-"))
        self.assertTrue(trade.evidence_snapshot_id.startswith("evidence-"))
        self.assertTrue(trade.trade_plan_id.startswith("tp-"))
        self.assertTrue(trade.risk_decision_id.startswith("risk-"))
        self.assertEqual("shadow-command-1", trade.simulation_command_id)
        self.assertTrue(trade.outcome_id.startswith("shadow-outcome-"))
        self.assertEqual(trade.evidence_snapshot_id, trade.evidence.evidence_snapshot_id)
        self.assertEqual("engineering-preflight-v1", trade.sample_metadata.sample_version)
        self.assertEqual(64, len(trade.sample_metadata.strategy_configuration_fingerprint))
        self.assertEqual("prospective-fakebroker-v1", trade.sample_metadata.fill_model_version)
        self.assertEqual(1, trade.sample_metadata.evidence_schema_version)
        self.assertFalse(trade.sample_metadata.official_sample_authorized)
        self.assertEqual(91, trade.evidence.candidate_payload()["scoring"]["composite_score"])
        self.assertEqual(before, hashlib.sha256(trade.evidence.source_report_json.encode("utf-8")).hexdigest())
        receipt = self.service().store.load().command_receipts[0]
        self.assertEqual(
            stable_id(
                "shadow-request",
                trade.evidence.source_sha256,
                trade.symbol,
                trade.plan_fingerprint,
                canonical_json(asdict(trade.sample_metadata)),
            ),
            receipt.request_fingerprint,
        )
        self.assertTrue(audit_shadow_trade(trade).passed)

        updated = report_payload()
        updated["candidates"][0]["scoring"]["composite_score"] = 1
        self.report_path.write_text(json.dumps(updated), encoding="utf-8")
        reloaded = self.service().snapshot()["trades"][0]
        frozen = json.loads(reloaded["evidence"]["candidate_json"])
        self.assertEqual(91, frozen["scoring"]["composite_score"])

    def test_duplicate_command_is_idempotent_across_restart_and_conflicting_reuse_fails(self) -> None:
        first = self.start()
        restarted = self.service()
        repeated = restarted.start_trade(
            self.report_path,
            symbol="TEST",
            simulation_command_id="shadow-command-1",
            decision_at=at("2026-07-23T10:30:00-05:00"),
        )
        self.assertEqual(first, repeated)
        self.assertEqual(1, len(restarted.snapshot()["trades"]))

        changed = report_payload()
        changed["candidates"][0]["trade_plan"]["bullish_entry"] = 10.25
        self.report_path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reused"):
            restarted.start_trade(
                self.report_path,
                symbol="TEST",
                simulation_command_id="shadow-command-1",
                decision_at=at("2026-07-23T10:30:00-05:00"),
            )

    def test_quote_at_or_before_decision_cannot_fill_and_limit_may_remain_unfilled(self) -> None:
        self.start()
        service = self.service()
        service.process_quote(quote("2026-07-23T10:00:00-05:00", bid=9.94, ask=9.95), received_at=at("2026-07-23T10:00:00-05:00"))
        before = service.snapshot()["trades"][0]
        self.assertEqual("pending_entry", before["status"])

        service.process_quote(quote("2026-07-23T10:01:00-05:00", bid=10.04, ask=10.05), received_at=at("2026-07-23T10:01:00-05:00"))
        after = service.snapshot()["trades"][0]
        self.assertEqual("pending_entry", after["status"])
        self.assertEqual(0, after["order"]["filled_quantity"])
        self.assertIn("above the limit", after["last_reason"])

    def test_stale_missing_halted_extended_and_wide_quotes_block_entry(self) -> None:
        scenarios = [
            (
                quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95),
                at("2026-07-23T10:03:00-05:00"),
                "stale",
            ),
            (
                quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95, trading_state="halted"),
                at("2026-07-23T10:01:00-05:00"),
                "unavailable",
            ),
            (
                quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95, session="extended"),
                at("2026-07-23T10:01:00-05:00"),
                "not eligible",
            ),
            (
                quote("2026-07-23T10:01:00-05:00", bid=9.0, ask=9.95),
                at("2026-07-23T10:01:00-05:00"),
                "spread",
            ),
        ]
        for index, (supplied_quote, received_at, expected) in enumerate(scenarios):
            with self.subTest(expected=expected):
                self.report_path.write_text(json.dumps(report_payload()), encoding="utf-8")
                service = ShadowTradingService(
                    store=ShadowStateStore(self.root / f"state-{index}.json"),
                    policy=self.policy,
                )
                service.start_trade(
                    self.report_path,
                    symbol="TEST",
                    simulation_command_id=f"command-{index}",
                    decision_at=at("2026-07-23T10:00:00-05:00"),
                )
                service.process_quote(supplied_quote, received_at=received_at)
                trade = service.snapshot()["trades"][0]
                self.assertEqual("pending_entry", trade["status"])
                self.assertIn(expected, trade["last_reason"].lower())

        missing_service = ShadowTradingService(
            store=ShadowStateStore(self.root / "missing-state.json"),
            policy=self.policy,
        )
        missing_service.start_trade(
            self.report_path,
            symbol="TEST",
            simulation_command_id="missing-command",
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )
        missing_service.process_missing_quote("TEST", observed_at=at("2026-07-23T10:01:00-05:00"))
        first_missing = missing_service.snapshot()["trades"][0]
        missing_service.process_missing_quote("TEST", observed_at=at("2026-07-23T10:01:00-05:00"))
        repeated_missing = missing_service.snapshot()["trades"][0]
        self.assertIn("No quote", first_missing["last_reason"])
        self.assertEqual(first_missing["ledger_events"], repeated_missing["ledger_events"])

    def test_partial_fill_then_completion_uses_executable_ask_and_slippage(self) -> None:
        self.start()
        service = self.service()
        service.process_quote(
            quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95, available_size=1),
            received_at=at("2026-07-23T10:01:00-05:00"),
        )
        partial = service.snapshot()["trades"][0]
        self.assertEqual("partially_filled", partial["status"])
        self.assertEqual(1, partial["order"]["filled_quantity"])
        self.assertEqual(9.96, partial["order"]["average_fill_price"])

        service.process_quote(
            quote("2026-07-23T10:02:00-05:00", bid=9.93, ask=9.94, available_size=1),
            received_at=at("2026-07-23T10:02:00-05:00"),
        )
        filled = service.snapshot()["trades"][0]
        self.assertEqual("open", filled["status"])
        self.assertEqual(2, filled["position"]["quantity"])
        self.assertLess(filled["position"]["average_entry_price"], 10.0)

    def test_partial_fill_cancels_remainder_and_honors_stop_before_another_entry_fill(self) -> None:
        self.start()
        service = self.service()
        service.process_quote(
            quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95, available_size=1),
            received_at=at("2026-07-23T10:01:00-05:00"),
        )
        service.process_quote(
            quote("2026-07-23T10:02:00-05:00", bid=8.95, ask=8.97, open=9.0, available_size=10),
            received_at=at("2026-07-23T10:02:00-05:00"),
        )
        trade = service.snapshot()["trades"][0]
        actions = [event["requested_action"] for event in trade["ledger_events"]]
        self.assertEqual("completed", trade["status"])
        self.assertEqual("cancelled", trade["order"]["status"])
        self.assertEqual(1, trade["position"]["quantity"])
        self.assertEqual("stop", trade["outcome"]["exit_reason"])
        self.assertLess(actions.index("fake_entry_remainder_cancelled"), actions.index("shadow_position_closed"))

    def test_rejected_and_out_of_order_quotes_do_not_contaminate_excursions(self) -> None:
        self.start()
        service = self.service()
        service.process_quote(
            quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95),
            received_at=at("2026-07-23T10:01:00-05:00"),
        )
        baseline = service.snapshot()["trades"][0]["position"]
        service.process_quote(
            quote("2026-07-23T10:02:00-05:00", bid=10.0, ask=10.01, high=100.0, low=1.0),
            received_at=at("2026-07-23T10:05:00-05:00"),
        )
        stale = service.snapshot()["trades"][0]
        self.assertIn("stale", stale["last_reason"].lower())
        self.assertEqual(baseline["highest_price"], stale["position"]["highest_price"])
        self.assertEqual(baseline["lowest_price"], stale["position"]["lowest_price"])

        service.process_quote(
            quote("2026-07-23T10:03:00-05:00", bid=10.0, ask=10.01, high=10.2, low=9.8),
            received_at=at("2026-07-23T10:03:00-05:00"),
        )
        ordered = service.snapshot()["trades"][0]
        service.process_quote(
            quote("2026-07-23T10:02:30-05:00", bid=8.0, ask=8.01, high=50.0, low=1.0),
            received_at=at("2026-07-23T10:03:30-05:00"),
        )
        rejected = service.snapshot()["trades"][0]
        self.assertIn("last processed", rejected["last_reason"])
        self.assertIsNone(rejected["outcome"])
        self.assertEqual(ordered["position"]["highest_price"], rejected["position"]["highest_price"])
        self.assertEqual(ordered["position"]["lowest_price"], rejected["position"]["lowest_price"])

    def test_target_exit_calculates_reproducible_pnl_r_mfe_mae_and_audit(self) -> None:
        self.start()
        service = self.service()
        service.process_quote(
            quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95),
            received_at=at("2026-07-23T10:01:00-05:00"),
        )
        service.process_quote(
            quote(
                "2026-07-23T10:02:00-05:00",
                bid=10.5,
                ask=10.51,
                open=10.0,
                high=10.7,
                low=9.8,
            ),
            received_at=at("2026-07-23T10:02:00-05:00"),
        )
        trade_payload = service.snapshot()["trades"][0]
        outcome = trade_payload["outcome"]
        self.assertEqual("completed", trade_payload["status"])
        self.assertEqual("WIN", outcome["classification"])
        self.assertEqual(10.4895, outcome["exit_price"])
        self.assertEqual(1.06, outcome["executable_pnl"])
        self.assertEqual(1.48, outcome["mfe_dollars"])
        self.assertEqual(-0.32, outcome["mae_dollars"])
        self.assertIsNotNone(outcome["r_multiple"])

        reloaded = self.service().snapshot()
        self.assertEqual(outcome, reloaded["trades"][0]["outcome"])
        self.assertEqual("PASS", reloaded["audits"][trade_payload["shadow_trade_id"]]["status"])
        actions = [event["requested_action"] for event in trade_payload["ledger_events"]]
        self.assertLess(actions.index("risk_gate_evaluated"), actions.index("simulated_order_previewed"))
        self.assertLess(actions.index("simulated_order_previewed"), actions.index("fake_order_submitted"))
        self.assertLess(actions.index("fake_order_submitted"), actions.index("fake_order_filled"))
        self.assertLess(actions.index("fake_order_filled"), actions.index("shadow_position_closed"))
        self.assertLess(actions.index("shadow_position_closed"), actions.index("shadow_outcome_recorded"))

    def test_gap_through_stop_exits_at_slipped_bid_not_ideal_stop(self) -> None:
        self.start()
        service = self.service()
        service.process_quote(
            quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95),
            received_at=at("2026-07-23T10:01:00-05:00"),
        )
        service.process_quote(
            quote(
                "2026-07-23T10:02:00-05:00",
                bid=8.95,
                ask=8.97,
                open=9.0,
                high=9.05,
                low=8.8,
            ),
            received_at=at("2026-07-23T10:02:00-05:00"),
        )
        outcome = self.service().snapshot()["trades"][0]["outcome"]
        self.assertEqual("stop", outcome["exit_reason"])
        self.assertEqual(8.9411, outcome["exit_price"])
        self.assertLess(outcome["executable_pnl"], outcome["gross_pnl"])

    def test_ambiguous_same_observation_exit_is_unknown_not_optimistic(self) -> None:
        self.start()
        service = self.service()
        service.process_quote(
            quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95),
            received_at=at("2026-07-23T10:01:00-05:00"),
        )
        service.process_quote(
            quote(
                "2026-07-23T10:02:00-05:00",
                bid=10.5,
                ask=10.51,
                open=9.0,
                high=10.7,
                low=8.9,
            ),
            received_at=at("2026-07-23T10:02:00-05:00"),
        )
        trade = service.snapshot()["trades"][0]
        self.assertEqual("ambiguous_exit", trade["status"])
        self.assertIsNone(trade["outcome"])
        self.assertIn("ambiguous", trade["last_reason"])

    def test_risk_block_prevents_order_and_manual_ticket(self) -> None:
        payload = report_payload()
        payload["candidates"][0]["trade_plan"]["bullish_stop"] = None
        self.report_path.write_text(json.dumps(payload), encoding="utf-8")
        trade = self.start(command_id="blocked")
        self.assertEqual("blocked", trade.status)
        self.assertIsNone(trade.order)
        self.assertIsNone(trade.ticket)
        self.assertTrue(trade.risk_rejection_reasons)
        self.assertTrue(audit_shadow_trade(trade).passed)

    def test_buying_power_and_position_limits_reject_before_fill(self) -> None:
        cases = [
            (
                ShadowExecutionPolicy(buying_power=10, max_open_positions=3),
                "buying power",
            ),
            (
                ShadowExecutionPolicy(buying_power=1_000, max_open_positions=0),
                "concurrency",
            ),
        ]
        for index, (policy, expected) in enumerate(cases):
            with self.subTest(expected=expected):
                state_path = self.root / f"limits-{index}.json"
                service = ShadowTradingService(store=ShadowStateStore(state_path), policy=policy)
                service.start_trade(
                    self.report_path,
                    symbol="TEST",
                    simulation_command_id=f"limits-{index}",
                    decision_at=at("2026-07-23T10:00:00-05:00"),
                )
                service.process_quote(
                    quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95),
                    received_at=at("2026-07-23T10:01:00-05:00"),
                )
                trade = service.snapshot()["trades"][0]
                self.assertEqual("entry_rejected", trade["status"])
                self.assertIn(expected, trade["last_reason"].lower())

    def test_daily_loss_limit_rejects_new_fakebroker_entry(self) -> None:
        broker = ProspectiveFakeBroker(ShadowExecutionPolicy(daily_loss_limit=25))
        order = ShadowOrder(
            order_id="shadow-order-test",
            shadow_trade_id="shadow-trade-test",
            symbol="TEST",
            side="buy",
            quantity=1,
            remaining_quantity=1,
            order_type="limit",
            limit_price=10.0,
            status="accepted",
            submitted_at="2026-07-23T10:00:00-05:00",
        )
        updated, position, reason = broker.fill_entry(
            order,
            quote("2026-07-23T10:01:00-05:00", bid=9.94, ask=9.95),
            received_at=at("2026-07-23T10:01:00-05:00"),
            committed_notional=0,
            open_position_count=0,
            realized_pnl_today=-25,
        )
        self.assertEqual("rejected", updated.status)
        self.assertIsNone(position)
        self.assertIn("Daily loss", reason)

    def test_missing_target_is_blocked_without_changing_risk_governor_semantics(self) -> None:
        payload = report_payload()
        payload["candidates"][0]["trade_plan"]["bullish_target_1"] = None
        self.report_path.write_text(json.dumps(payload), encoding="utf-8")
        trade = self.start(command_id="missing-target")
        self.assertEqual("blocked", trade.status)
        self.assertIsNone(trade.order)
        self.assertIn("target 1", trade.last_reason)

    def test_malformed_restart_state_fails_closed(self) -> None:
        self.state_path.write_text('{"schema_version":999,"trades":[]}', encoding="utf-8")
        with self.assertRaisesRegex(Exception, "unsupported"):
            self.service().snapshot()

    def test_duplicate_and_missing_persisted_identifiers_fail_closed(self) -> None:
        self.start()
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload["trades"].append(payload["trades"][0])
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(Exception, "duplicate Shadow Trade"):
            self.service().snapshot()

        self.state_path.unlink()
        self.start(command_id="second-command")
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload["command_receipts"][0]["command_id"] = ""
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(Exception, "missing identifier"):
            self.service().snapshot()

    def test_nontransmitting_ticket_writes_json_and_markdown(self) -> None:
        trade = self.start()
        paths = self.service().write_ticket(trade.shadow_trade_id, output_dir=self.root / "reports")
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        markdown = paths["markdown"].read_text(encoding="utf-8")
        self.assertEqual("PAPER SHADOW / NONTRANSMITTING", payload["ticket"]["environment"])
        self.assertEqual(trade.plan_fingerprint, payload["ticket"]["plan_fingerprint"])
        self.assertEqual(trade.sample_metadata.sample_version, payload["ticket"]["sample_version"])
        self.assertIn("Fill-model version", markdown)
        self.assertIn("Manual paperMoney", markdown)
        self.assertIn("nontransmitting", markdown)


class ShadowMetricsTests(unittest.TestCase):
    def test_metrics_gate_small_sample_and_calculate_ideal_executable_gap(self) -> None:
        trades = [completed_trade(index, executable_pnl=10 if index % 2 == 0 else -5) for index in range(4)]
        metrics = shadow_metrics(trades)
        self.assertEqual("INSUFFICIENT_SAMPLE", metrics["sampleStatus"])
        self.assertEqual(4, metrics["completedTradeCount"])
        self.assertEqual(50.0, metrics["winRatePercent"])
        self.assertIsNone(metrics["profitFactor"])
        self.assertIn("Too few", metrics["conclusion"])

        meaningful = shadow_metrics(
            [completed_trade(index, executable_pnl=10 if index % 2 == 0 else -5) for index in range(MIN_MEANINGFUL_SAMPLE_SIZE)]
        )
        self.assertEqual("MEANINGFUL", meaningful["sampleStatus"])
        self.assertEqual(2.0, meaningful["profitFactor"])

    def test_review_projection_gates_metrics_and_proves_frozen_evidence(self) -> None:
        trade = completed_auditable_trade(1)

        review = build_shadow_review_snapshot([trade])

        item = review["trades"][0]
        self.assertTrue(item["evidenceLock"]["evidenceFrozen"])
        self.assertTrue(item["evidenceLock"]["planFrozen"])
        self.assertFalse(item["evidenceLock"]["postDecisionCorrectionOccurred"])
        self.assertEqual("PASS", item["evidenceLock"]["auditStatus"])
        self.assertTrue(item["evidenceEligible"])
        self.assertTrue(item["countsTowardSample"])
        self.assertEqual(1, review["sample"]["eligibleCompleted"])
        self.assertFalse(review["sample"]["gateSatisfied"])
        self.assertIsNone(review["metrics"]["winRatePercent"])
        self.assertIn("not yet sufficient", review["sample"]["status"])
        self.assertIn("basis points", " ".join(item["executionQuality"]["factors"]))

    def test_review_projection_fails_closed_for_mutated_plan_and_post_decision_correction(self) -> None:
        trade = completed_auditable_trade(2)
        correction = replace(
            trade.ledger_events[-1],
            event_id="manual-correction-event",
            event_type="manual_override",
            requested_action="manual_override",
            result="changed",
            reason="Synthetic post-decision correction.",
        )
        mutated = replace(
            trade,
            trade_plan_json=trade.trade_plan_json.replace('"bullish_entry":10.0', '"bullish_entry":10.1'),
            ledger_events=(*trade.ledger_events, correction),
        )

        review = build_shadow_review_snapshot([mutated])

        item = review["trades"][0]
        self.assertFalse(item["evidenceLock"]["planFrozen"])
        self.assertTrue(item["evidenceLock"]["postDecisionCorrectionOccurred"])
        self.assertFalse(item["evidenceEligible"])
        self.assertFalse(item["countsTowardSample"])
        self.assertEqual(1, review["sample"]["excluded"])
        self.assertEqual(0, review["sample"]["eligibleCompleted"])

    def test_review_projection_recomputes_candidate_and_evidence_identity_chain(self) -> None:
        trade = completed_auditable_trade(3)
        candidate_payload = trade.evidence.candidate_payload()
        candidate_payload["symbol"] = "ALTERED"
        mutated = replace(
            trade,
            evidence=replace(
                trade.evidence,
                candidate_json=json.dumps(candidate_payload, sort_keys=True, separators=(",", ":")),
            ),
        )

        review = build_shadow_review_snapshot([mutated])

        item = review["trades"][0]
        self.assertFalse(item["evidenceLock"]["evidenceFrozen"])
        self.assertEqual("FAIL", item["evidenceLock"]["auditStatus"])
        self.assertFalse(item["countsTowardSample"])
        self.assertTrue(
            any("candidate evidence" in reason.lower() for reason in item["evidenceLock"]["reasons"])
        )

    def test_review_projection_releases_aggregate_metrics_at_thirty_eligible_completed_trades(self) -> None:
        trades = [completed_auditable_trade(index) for index in range(MIN_MEANINGFUL_SAMPLE_SIZE)]

        review = build_shadow_review_snapshot(trades)

        self.assertTrue(review["sample"]["gateSatisfied"])
        self.assertEqual(MIN_MEANINGFUL_SAMPLE_SIZE, review["sample"]["eligibleCompleted"])
        self.assertGreaterEqual(
            review["sample"]["distinctTradingSessions"],
            10,
        )
        self.assertTrue(review["sample"]["strategyConclusionEligible"])
        self.assertEqual("MEANINGFUL", review["metrics"]["sampleStatus"])
        self.assertIsNotNone(review["metrics"]["winRatePercent"])
        self.assertIsNotNone(review["metrics"]["expectancy"])

    def test_thirty_trades_do_not_authorize_strategy_conclusions_without_ten_sessions(
        self,
    ) -> None:
        trades = [
            completed_auditable_trade(
                index,
                trading_day_override=date(2026, 7, 6),
            )
            for index in range(MIN_MEANINGFUL_SAMPLE_SIZE)
        ]

        review = build_shadow_review_snapshot(trades)

        self.assertTrue(review["sample"]["gateSatisfied"])
        self.assertEqual(1, review["sample"]["distinctTradingSessions"])
        self.assertFalse(review["sample"]["strategyConclusionEligible"])
        self.assertIn("distinct trading sessions", review["metrics"]["conclusion"])
        self.assertEqual(
            MIN_MEANINGFUL_SAMPLE_SIZE,
            review["sample"]["concentration"]["symbols"][0]["count"],
        )


class ShadowWorkspaceIntegrationTests(unittest.TestCase):
    def test_production_defaults_use_schwab_quote_source_without_network_call(self) -> None:
        source = _BatchMarketQuoteSource({})
        with patch(
            "momentum_hunter.schwab_market_data.SchwabMarketDataQuoteSource",
            return_value=source,
        ) as constructor:
            workspace = ShadowWorkspaceService()

        constructor.assert_called_once_with()
        self.assertIs(source, workspace.quote_source)
        self.assertEqual([], source.calls)

    def test_persisted_monitor_observation_advances_active_trade(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            report = reports / "trade-plan-briefing-test.json"
            report.write_text(json.dumps(report_payload()), encoding="utf-8")
            observations = root / "opportunity-price-observations.json"
            observations.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observations": [
                            {
                                "symbol": "TEST",
                                "timestamp": "2026-07-23T10:01:00-05:00",
                                "quote_timestamp": "2026-07-23T10:01:00-05:00",
                                "quote_source": "provider-fixture",
                                "price": 9.95,
                                "bid": 9.94,
                                "ask": 9.95,
                                "spread_percent": 0.1,
                                "volume": 1000,
                                "rvol": 2.0,
                                "rvol_type": "INTRADAY_RVOL",
                                "state": "EXECUTION_READY_TRADE",
                                "source_report": str(report),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            core = ShadowTradingService(store=ShadowStateStore(root / "shadow-state.json"))
            core.start_trade(
                report,
                symbol="TEST",
                simulation_command_id="workspace-command",
                decision_at=at("2026-07-23T10:00:00-05:00"),
            )
            workspace = ShadowWorkspaceService(
                paths=ShadowWorkspacePaths(reports, observations, root / "shadow-state.json"),
                service=core,
            )

            result = workspace.advance_observations(received_at=at("2026-07-23T10:01:00-05:00"))

            self.assertEqual(1, result["observationsRelevant"])
            self.assertEqual("open", result["snapshot"]["trades"][0]["status"])
            self.assertFalse(result["snapshot"]["transmitting"])

    def test_fresh_monitor_wrapper_without_provider_time_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            report = reports / "trade-plan-briefing-test.json"
            report.write_text(json.dumps(report_payload()), encoding="utf-8")
            observations = root / "opportunity-price-observations.json"
            observations.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observations": [
                            {
                                "symbol": "TEST",
                                "timestamp": "2026-07-23T10:00:59-05:00",
                                "price": 9.95,
                                "bid": 9.94,
                                "ask": 9.95,
                                "source_report": "fresh-monitor-wrapper",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            core = ShadowTradingService(
                store=ShadowStateStore(root / "shadow-state.json")
            )
            core.start_trade(
                report,
                symbol="TEST",
                simulation_command_id="missing-provider-time",
                decision_at=at("2026-07-23T10:00:00-05:00"),
            )
            workspace = ShadowWorkspaceService(
                paths=ShadowWorkspacePaths(
                    reports,
                    observations,
                    root / "shadow-state.json",
                ),
                service=core,
            )

            result = workspace.advance_observations(
                received_at=at("2026-07-23T10:01:00-05:00")
            )

            self.assertEqual(0, result["trustedObservationsSeen"])
            self.assertEqual(0, result["observationsRelevant"])
            self.assertEqual(["TEST"], result["missingQuoteSymbols"])
            self.assertEqual(
                "pending_entry",
                result["snapshot"]["trades"][0]["status"],
            )
            self.assertIn(
                "No quote was available",
                result["snapshot"]["trades"][0]["last_reason"],
            )

    def test_workspace_processes_only_latest_trusted_quote_per_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            report = reports / "trade-plan-briefing-test.json"
            report.write_text(json.dumps(report_payload()), encoding="utf-8")
            observations = root / "opportunity-price-observations.json"
            observations.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "observations": [
                            {
                                "symbol": "TEST",
                                "timestamp": "2026-07-23T10:00:45-05:00",
                                "quote_timestamp": "2026-07-23T10:00:40-05:00",
                                "quote_source": "provider-fixture",
                                "price": 9.95,
                                "bid": 9.94,
                                "ask": 9.95,
                            },
                            {
                                "symbol": "TEST",
                                "timestamp": "2026-07-23T10:00:55-05:00",
                                "quote_timestamp": "2026-07-23T10:00:50-05:00",
                                "quote_source": "provider-fixture",
                                "price": 10.50,
                                "bid": 10.49,
                                "ask": 10.50,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            core = ShadowTradingService(
                store=ShadowStateStore(root / "shadow-state.json")
            )
            core.start_trade(
                report,
                symbol="TEST",
                simulation_command_id="latest-provider-quote",
                decision_at=at("2026-07-23T10:00:00-05:00"),
            )
            workspace = ShadowWorkspaceService(
                paths=ShadowWorkspacePaths(
                    reports,
                    observations,
                    root / "shadow-state.json",
                ),
                service=core,
            )

            result = workspace.advance_observations(
                received_at=at("2026-07-23T10:01:00-05:00")
            )

            trade = result["snapshot"]["trades"][0]
            self.assertEqual(2, result["trustedObservationsSeen"])
            self.assertEqual(1, result["observationsRelevant"])
            self.assertEqual(1, len(trade["processed_observation_ids"]))
            self.assertEqual("pending_entry", trade["status"])

    def test_provider_quote_source_advances_active_trade_without_persisted_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            report = reports / "trade-plan-briefing-test.json"
            report.write_text(json.dumps(report_payload()), encoding="utf-8")
            received_at = at("2026-07-23T10:01:00-05:00")
            source = _BatchMarketQuoteSource(
                {
                    "TEST": {
                        "symbol": "TEST",
                        "timestamp": "2026-07-23T10:00:50-05:00",
                        "bid": 9.94,
                        "ask": 9.95,
                        "last": 9.95,
                        "volume": 1_000,
                        "session": "regular",
                        "trading_state": "tradable",
                        "source": "provider-fixture",
                    }
                }
            )
            core = ShadowTradingService(
                store=ShadowStateStore(root / "shadow-state.json")
            )
            core.start_trade(
                report,
                symbol="TEST",
                simulation_command_id="provider-workspace",
                decision_at=at("2026-07-23T10:00:00-05:00"),
            )
            observations = root / "missing-observations.json"
            workspace = ShadowWorkspaceService(
                paths=ShadowWorkspacePaths(
                    reports,
                    observations,
                    root / "shadow-state.json",
                ),
                service=core,
                quote_source=source,
            )

            result = workspace.advance_observations(
                received_at=received_at,
            )

            self.assertEqual([(("TEST",), received_at)], source.calls)
            self.assertFalse(observations.exists())
            self.assertEqual(1, result["trustedObservationsSeen"])
            self.assertEqual(1, result["observationsRelevant"])
            self.assertEqual([], result["missingQuoteSymbols"])
            self.assertEqual("open", result["snapshot"]["trades"][0]["status"])
            self.assertFalse(result["snapshot"]["transmitting"])

    def test_provider_quote_source_is_not_called_without_tracked_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            source = _BatchMarketQuoteSource({})
            core = ShadowTradingService(
                store=ShadowStateStore(root / "shadow-state.json")
            )
            workspace = ShadowWorkspaceService(
                paths=ShadowWorkspacePaths(
                    reports,
                    root / "observations.json",
                    root / "shadow-state.json",
                ),
                service=core,
                quote_source=source,
            )

            result = workspace.advance_observations(
                received_at=at("2026-07-23T10:01:00-05:00"),
            )

            self.assertEqual([], source.calls)
            self.assertEqual(0, result["observationsSeen"])
            self.assertEqual(0, result["activeTradeCount"])

    def test_provider_quote_symbol_mismatch_fails_as_missing_quote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            report = reports / "trade-plan-briefing-test.json"
            report.write_text(json.dumps(report_payload()), encoding="utf-8")
            source = _BatchMarketQuoteSource(
                {
                    "TEST": {
                        "symbol": "OTHER",
                        "timestamp": "2026-07-23T10:00:50-05:00",
                        "bid": 9.94,
                        "ask": 9.95,
                        "last": 9.95,
                        "session": "regular",
                        "trading_state": "tradable",
                        "source": "provider-fixture",
                    }
                }
            )
            core = ShadowTradingService(
                store=ShadowStateStore(root / "shadow-state.json")
            )
            core.start_trade(
                report,
                symbol="TEST",
                simulation_command_id="provider-mismatch",
                decision_at=at("2026-07-23T10:00:00-05:00"),
            )
            workspace = ShadowWorkspaceService(
                paths=ShadowWorkspacePaths(
                    reports,
                    root / "observations.json",
                    root / "shadow-state.json",
                ),
                service=core,
                quote_source=source,
            )

            result = workspace.advance_observations(
                received_at=at("2026-07-23T10:01:00-05:00"),
            )

            self.assertEqual(["TEST"], result["invalidQuoteSymbols"])
            self.assertEqual(["TEST"], result["missingQuoteSymbols"])
            self.assertEqual(
                "pending_entry",
                result["snapshot"]["trades"][0]["status"],
            )

    def test_provider_quote_source_cannot_record_unrequested_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            source = _BatchMarketQuoteSource(
                {
                    "UNEXPECTED": {
                        "symbol": "UNEXPECTED",
                        "timestamp": "2026-07-23T10:00:50-05:00",
                        "bid": 9.94,
                        "ask": 9.95,
                        "last": 9.95,
                        "session": "regular",
                        "trading_state": "tradable",
                        "source": "provider-fixture",
                    }
                },
                return_unrequested=True,
            )
            core = ShadowTradingService(
                store=ShadowStateStore(root / "shadow-state.json")
            )
            workspace = ShadowWorkspaceService(
                paths=ShadowWorkspacePaths(
                    reports,
                    root / "observations.json",
                    root / "shadow-state.json",
                ),
                service=core,
                quote_source=source,
            )
            workspace.service.decision_cycle_store.save_cycle(
                {
                    "cycle_id": "test-unexpected-provider-symbol",
                    "cycle_kind": "DECISION",
                    "decision_at": "2026-07-23T10:00:00-05:00",
                    "updated_at": "2026-07-23T10:00:00-05:00",
                    "candidate_assessments": [
                        {"symbol": "TEST", "eligible": True}
                    ],
                    "benchmark_symbols": [],
                }
            )

            result = workspace.advance_observations(
                received_at=at("2026-07-23T10:01:00-05:00"),
            )

            self.assertEqual(["UNEXPECTED"], result["invalidQuoteSymbols"])
            self.assertEqual(0, result["observationsSeen"])
            self.assertEqual(
                [],
                workspace.service.decision_cycle_store.load().cycles[0].get(
                    "market_observations",
                    [],
                ),
            )

    def test_provider_nonfinite_quote_fails_before_fill_or_recording(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "reports"
            reports.mkdir()
            report = reports / "trade-plan-briefing-test.json"
            report.write_text(json.dumps(report_payload()), encoding="utf-8")
            source = _BatchMarketQuoteSource(
                {
                    "TEST": {
                        "symbol": "TEST",
                        "timestamp": "2026-07-23T10:00:50-05:00",
                        "bid": math.nan,
                        "ask": 9.95,
                        "last": 9.95,
                        "session": "regular",
                        "trading_state": "tradable",
                        "source": "provider-fixture",
                    }
                }
            )
            core = ShadowTradingService(
                store=ShadowStateStore(root / "shadow-state.json")
            )
            core.start_trade(
                report,
                symbol="TEST",
                simulation_command_id="provider-nonfinite",
                decision_at=at("2026-07-23T10:00:00-05:00"),
            )
            workspace = ShadowWorkspaceService(
                paths=ShadowWorkspacePaths(
                    reports,
                    root / "observations.json",
                    root / "shadow-state.json",
                ),
                service=core,
                quote_source=source,
            )

            result = workspace.advance_observations(
                received_at=at("2026-07-23T10:01:00-05:00"),
            )

            self.assertEqual(["TEST"], result["invalidQuoteSymbols"])
            self.assertEqual(["TEST"], result["missingQuoteSymbols"])
            self.assertEqual(0, result["observationsSeen"])
            self.assertEqual(
                "pending_entry",
                result["snapshot"]["trades"][0]["status"],
            )

    def test_engine_host_exposes_idempotent_shadow_commands_without_broker_capability(self) -> None:
        starts: list[tuple[str, str]] = []
        advances: list[str] = []
        runtime = EngineHostRuntime(
            cycle_runner=lambda: object(),
            external_monitor_running=lambda: False,
            workspace_snapshot_loader=lambda: {},
            simulation_workspace_loader=lambda: {},
            simulation_runner=lambda _symbol: {},
            chart_snapshot_loader=lambda _symbol, _interval: {},
            shadow_workspace_loader=lambda: {"mode": "PAPER SHADOW / NONTRANSMITTING"},
            shadow_starter=lambda symbol, command_id: starts.append((symbol, command_id)) or {"symbol": symbol},
            shadow_observation_runner=lambda: advances.append("advance") or {"processed": 1},
        )

        snapshot = runtime.execute(COMMAND_SHADOW_WORKSPACE_SNAPSHOT, "shadow-snapshot")
        started = runtime.execute(COMMAND_START_SHADOW_TRADE, "shadow-start", {"symbol": "test"})
        repeated = runtime.execute(COMMAND_START_SHADOW_TRADE, "shadow-start", {"symbol": "test"})
        advanced = runtime.execute(COMMAND_ADVANCE_SHADOW_TRADES, "shadow-advance")

        self.assertTrue(snapshot.accepted)
        self.assertTrue(started.accepted)
        self.assertEqual(started, repeated)
        self.assertTrue(advanced.accepted)
        self.assertEqual([("TEST", "shadow-start")], starts)
        self.assertEqual(["advance"], advances)
        capabilities = runtime.snapshot()["capabilities"]
        self.assertIn(COMMAND_START_SHADOW_TRADE, capabilities)
        self.assertNotIn("submit_order", capabilities)


def report_payload() -> dict:
    row = {
        "rank": 1,
        "symbol": "TEST",
        "company": "Synthetic Test Corporation",
        "market_data": {
            "last_price": 9.9,
            "current_bid": 9.89,
            "current_ask": 9.91,
            "spread_percent": 0.2,
            "relative_volume": 2.0,
        },
        "scoring": {
            "composite_score": 91,
            "catalyst_summary": "Synthetic catalyst",
            "catalyst_cluster": "Synthetic setup",
        },
        "trade_plan": {
            "bullish_entry": 10.0,
            "bullish_stop": 9.5,
            "bullish_target_1": 10.5,
            "bullish_target_2": 11.0,
            "risk_reward_ratio": 1.0,
            "estimated_shares_for_500": 2.0,
            "estimated_dollar_risk": 1.0,
            "estimated_target_1_reward": 1.0,
            "confidence": "MEDIUM",
            "tradeability": "MEDIUM",
            "readiness": "EXECUTION_READY_TRADE",
            "blocking_reasons": [],
            "warnings": [],
        },
        "opportunity_notes": ["Synthetic test row"],
    }
    return {
        "schema_version": 1,
        "metadata": {
            "generated_at": "2026-07-23T09:59:00-05:00",
            "source_capture_path": "synthetic/capture.json",
            "source_capture_time": "2026-07-23T09:58:00-05:00",
            "source_provider": "synthetic-test-provider",
            "market_regime": "risk_on",
        },
        "top_5_for_capital": [row],
        "candidates": [row],
    }


def quote(
    timestamp: str,
    *,
    bid: float | None,
    ask: float | None,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    available_size: int | None = None,
    session: str = "regular",
    trading_state: str = "tradable",
) -> ShadowQuote:
    return ShadowQuote(
        symbol="TEST",
        timestamp=timestamp,
        bid=bid,
        ask=ask,
        last=bid,
        open=open,
        high=high,
        low=low,
        available_size=available_size,
        session=session,
        trading_state=trading_state,
        source="synthetic_test",
    )


def completed_trade(index: int, *, executable_pnl: float):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        report = root / "report.json"
        report.write_text(json.dumps(report_payload()), encoding="utf-8")
        service = ShadowTradingService(store=ShadowStateStore(root / "state.json"))
        trade = service.start_trade(
            report,
            symbol="TEST",
            simulation_command_id=f"metrics-{index}",
            decision_at=at(f"2026-07-{(index % 20) + 1:02d}T10:00:00-05:00"),
        )
    outcome = ShadowOutcome(
        outcome_id=trade.outcome_id,
        shadow_trade_id=trade.shadow_trade_id,
        status="COMPLETED",
        classification="WIN" if executable_pnl > 0 else "LOSS",
        exit_timestamp=f"2026-07-{(index % 20) + 1:02d}T10:30:00-05:00",
        exit_reason="target_1" if executable_pnl > 0 else "stop",
        exit_price=10.5 if executable_pnl > 0 else 9.5,
        gross_pnl=12.0 if executable_pnl > 0 else -4.0,
        executable_pnl=executable_pnl,
        r_multiple=1.0 if executable_pnl > 0 else -0.5,
        mfe_dollars=max(0.0, executable_pnl),
        mae_dollars=min(0.0, executable_pnl),
        mfe_percent=1.0,
        mae_percent=-0.5,
        duration_seconds=1800,
    )
    return replace(trade, status="completed", outcome=outcome, setup_type="setup", catalyst="catalyst")


def completed_auditable_trade(
    index: int,
    *,
    trading_day_override: date | None = None,
):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        trading_day = (
            trading_day_override
            or nth_open_day(date(2026, 7, 6), index)
        )
        report = root / (
            f"trade-plan-briefing-{trading_day.isoformat()}-"
            f"{index:03d}.json"
        )
        decision = at(f"{trading_day.isoformat()}T10:00:00-05:00")
        payload = report_payload()
        payload["metadata"]["source_capture_time"] = (
            decision - timedelta(minutes=2)
        ).isoformat()
        payload["metadata"]["generated_at"] = (
            decision - timedelta(minutes=1)
        ).isoformat()
        report.write_text(json.dumps(payload), encoding="utf-8")
        service = ShadowTradingService(
            store=ShadowStateStore(root / "state.json"),
            policy=ShadowExecutionPolicy(
                slippage_bps=10,
                minimum_fill_delay_seconds=1,
                buying_power=10_000,
                max_open_positions=100,
            ),
            sample_version="synthetic-official-v1",
        )
        with patch(
            "momentum_hunter.shadow_trading.now_central",
            return_value=decision - timedelta(minutes=3),
        ):
            service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
                sample_version="synthetic-official-v1",
            )
        service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proofs=synthetic_pass_proofs(f"completed-{index}"),
            armed_at=decision - timedelta(minutes=2),
        )
        selection_quote = {
            "symbol": "TEST",
            "timestamp": (decision - timedelta(seconds=5)).isoformat(),
            "bid": 9.94,
            "ask": 9.95,
            "last": 9.94,
            "session": "regular",
            "trading_state": "tradable",
            "source": "synthetic-selection-quote",
        }
        result = AutomaticShadowSelector(
            service,
            quote_source=lambda symbol, *, decision_at: (
                selection_quote
                if symbol == "TEST"
                else {
                    **selection_quote,
                    "symbol": symbol,
                    "bid": 100.0,
                    "ask": 100.01,
                    "last": 100.0,
                }
            ),
        ).select(report, decision_at=decision)
        trade = next(
            item
            for item in service.store.load().trades
            if item.shadow_trade_id == result.shadow_trade_id
        )
        service.process_quote(
            quote(
                (decision + timedelta(seconds=5)).isoformat(),
                bid=9.94,
                ask=9.95,
                high=9.96,
                low=9.93,
            ),
            received_at=decision + timedelta(seconds=5),
        )
        service.process_quote(
            quote(
                (decision + timedelta(minutes=30)).isoformat(),
                bid=10.55,
                ask=10.56,
                high=10.57,
                low=10.50,
            ),
            received_at=decision + timedelta(minutes=30),
        )
        return service.store.load().trades[0]


def at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nth_open_day(start: date, index: int) -> date:
    current = start
    remaining = max(0, index - 1)
    while remaining:
        current += timedelta(days=1)
        if is_market_open_day(current):
            remaining -= 1
    return current
