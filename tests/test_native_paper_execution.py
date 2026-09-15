from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.intraday_trade_plan import (
    build_intraday_plan_evidence, CONTINUATION_BREAKOUT, transition_intraday_plan,
)
from momentum_hunter.native_paper_broker import SimulatedPaperBroker
from momentum_hunter.native_paper_execution import (
    NativePaperConfiguration, NativePaperExecutionEngine, OfflinePaperDecision,
    SAFETY_HOOKS, entry_findings,
)
from momentum_hunter.native_paper_store import NativePaperError
from tests.test_native_paper_mechanics import NOW, account, policy


def decision(opportunity="opportunity-1", symbol="TEST", setup="setup-1"):
    plan = build_intraday_plan_evidence(
        symbol=symbol, setup_family=CONTINUATION_BREAKOUT, created_at=NOW,
        planned_entry=100, stop_price=99, target_prices=(102, 104),
        source_setup_fingerprint="a" * 64, source_level_kind="RANGE_HIGH",
        source_evidence_ids=(setup,), observed_price=100)
    return OfflinePaperDecision(opportunity, setup, "decision-1", plan, NOW.isoformat(),
                                NOW.isoformat(), "100", NOW.isoformat(), ".01", 100000, 1, 30)


class SimulatedCrash(BaseException):
    pass


class NativeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.broker = SimulatedPaperBroker("fixture")
        self.engine = self.create()

    def create(self, **kwargs):
        return NativePaperExecutionEngine(root=self.root, namespace="fixture", policy=policy(),
                                         simulator=self.broker, **kwargs)

    def entry(self, **kwargs):
        return self.engine.qualification_entry(decision(), at=NOW, account=account(), **kwargs)

    def close_entry(self, trade, quantity="10"):
        self.broker.fill(trade["order_id"], fill_id=trade["order_id"] + "-fill", quantity=quantity,
                         price="99.90", at=NOW.isoformat())
        self.broker.seal_order(trade["order_id"], at=NOW.isoformat())
        self.engine.reconcile(at=NOW)

    def test_configuration_cannot_enable_any_authority(self):
        for field in ("paper_enabled", "broker_enabled", "auto_arm", "live_enabled"):
            with self.subTest(field=field), self.assertRaises(NativePaperError):
                self.create(configuration=replace(NativePaperConfiguration(), **{field: True}))
        self.assertEqual("NONE", self.engine.execution_authority)

    def test_only_exact_offline_adapter_not_a_protocol_claim(self):
        class PretendBroker(SimulatedPaperBroker):
            pass
        with self.assertRaises(NativePaperError):
            NativePaperExecutionEngine(root=self.root, namespace="fixture", policy=policy(),
                                       simulator=PretendBroker("fixture"))

    def test_disabled_intake_never_queries_or_submits(self):
        self.broker.connected = False
        with patch.object(self.broker, "submit", side_effect=AssertionError), \
                patch.object(self.broker, "snapshot", side_effect=AssertionError):
            one = self.engine.record_disabled_decision(source_identity="continuous-1", payload={"plan": "exists"}, at=NOW)
            two = self.engine.record_disabled_decision(source_identity="continuous-1", payload={"plan": "exists"}, at=NOW)
        self.assertEqual(one, two)
        self.assertEqual("DISABLED", self.create().inspect()["disabled_intents"][one]["state"])

    def test_entry_identity_and_repeated_callbacks(self):
        first = self.entry(requested_quantity="10")
        second = self.entry(requested_quantity="10")
        self.assertEqual(first, second)
        self.assertEqual(1, self.broker.submit_calls)
        self.assertEqual("ORDER_SUBMITTED", first["state"])
        self.assertEqual(Decimal("100"), Decimal(first["request"]["limit_price"]))

    def test_missed_stale_future_abstention_and_expiration(self):
        cases = (
            replace(decision(), observed_price="100.01"),
            replace(decision(), source_kind="BACKTEST"),
            replace(decision(), source_kind="SCIENCE"),
            replace(decision(), known_at=(NOW + timedelta(seconds=1)).isoformat()),
            replace(decision(), decision="DO_NOT_TRADE"),
            replace(decision(), opportunity_id=""),
        )
        for value in cases:
            with self.subTest(value=value):
                self.assertTrue(entry_findings(value, NOW))
        self.assertIn("ENTRY_PRICE_STALE", entry_findings(decision(), NOW + timedelta(seconds=31)))
        self.assertIn("ENTRY_WINDOW_CLOSED", entry_findings(decision(), decision().plan.entry_expires_at))
        self.assertEqual(0, self.broker.submit_calls)

    def test_default_engine_cannot_use_offline_entry(self):
        with tempfile.TemporaryDirectory() as root:
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy())
            with self.assertRaises(NativePaperError):
                engine.qualification_entry(decision(), at=NOW, account=account())

    def test_risk_refusal_precedes_adapter(self):
        result = self.engine.qualification_entry(decision(), at=NOW, account=None)
        self.assertEqual("REJECTED", result["state"])
        self.assertEqual(0, self.broker.submit_calls)

    def test_unknown_ack_reconcile_without_submit(self):
        self.broker.next_submit = "ACK_TIMEOUT"
        trade = self.entry(requested_quantity="10")
        self.assertEqual("UNKNOWN", trade["state"])
        self.engine = self.create()
        state = self.engine.reconcile(at=NOW)
        self.assertEqual("ORDER_SUBMITTED", state["trades"][trade["scope"]]["state"])
        self.entry(requested_quantity="10")
        self.assertEqual(1, self.broker.submit_calls)

    def test_absent_unknown_is_not_permission_to_retry(self):
        self.broker.next_submit = "TIMEOUT_BEFORE_ACCEPT"
        trade = self.entry(requested_quantity="10")
        self.engine = self.create()
        self.engine.reconcile(at=NOW)
        self.entry(requested_quantity="10")
        self.assertEqual("UNKNOWN", self.engine.inspect()["trades"][trade["scope"]]["state"])
        self.assertEqual(1, self.broker.submit_calls)

    def test_unresolved_domain_blocks_another_entry(self):
        self.entry(requested_quantity="10")
        result = self.engine.qualification_entry(decision("opportunity-2", "OTHER", "setup-2"), at=NOW, account=account())
        self.assertIn("ACCOUNT_SOURCE_RECONCILIATION_REQUIRED", result["blockers"])
        self.assertEqual(1, self.broker.submit_calls)

    def test_full_fill_is_not_complete_finality(self):
        trade = self.entry(requested_quantity="10")
        self.broker.fill(trade["order_id"], fill_id="f1", quantity="10", price="99.9", at=NOW.isoformat())
        result = self.engine.reconcile(at=NOW)["trades"][trade["scope"]]
        self.assertEqual("TERMINAL_UNKNOWN", result["state"])
        self.assertIsNone(result["closure"])
        self.broker.seal_order(trade["order_id"], at=NOW.isoformat())
        result = self.engine.reconcile(at=NOW)["trades"][trade["scope"]]
        self.assertEqual("POSITION_OPEN", result["state"])
        self.assertEqual(NOW.isoformat(), result["opened_at"])

    def test_partial_fill_cancel_preserves_position_and_partition(self):
        trade = self.entry(requested_quantity="10")
        self.broker.fill(trade["order_id"], fill_id="f1", quantity="3", price="99.8", at=NOW.isoformat())
        self.broker.cancel(trade["order_id"])
        result = self.engine.reconcile(at=NOW)["trades"][trade["scope"]]
        self.assertEqual("7", result["unfilled"])
        self.assertEqual("0", result["closed_unfilled"])
        self.broker.seal_order(trade["order_id"], at=NOW.isoformat())
        result = self.engine.reconcile(at=NOW)["trades"][trade["scope"]]
        self.assertEqual(("3", "0", "7", "3"),
                         tuple(result[k] for k in ("filled", "unfilled", "closed_unfilled", "position_quantity")))

    def test_multiple_opportunities_same_symbol_stay_distinct(self):
        first = self.entry(requested_quantity="10")
        self.close_entry(first)
        second = self.engine.qualification_entry(decision("opportunity-2", "TEST", "setup-2"),
                                                 at=NOW, account=account(), requested_quantity="10")
        self.assertNotEqual(first["position_id"], second["position_id"])
        self.assertNotEqual(first["order_id"], second["order_id"])
        self.assertEqual(2, len(self.create().inspect()["trades"]))

    def test_broker_position_disagreement_quarantines(self):
        trade = self.entry(requested_quantity="10")
        self.close_entry(trade)
        snapshot = self.broker.snapshot()
        snapshot["positions"][trade["position_id"]] = "0"
        with patch.object(self.broker, "snapshot", return_value=snapshot):
            self.assertTrue(self.engine.reconcile(at=NOW)["quarantined"])

    def test_broker_unknown_order_quarantines(self):
        self.entry(requested_quantity="10")
        snapshot = self.broker.snapshot()
        snapshot["orders"]["foreign"] = copy.deepcopy(next(iter(snapshot["orders"].values())))
        with patch.object(self.broker, "snapshot", return_value=snapshot):
            self.assertTrue(self.engine.reconcile(at=NOW)["quarantined"])

    def test_contingent_exit_reconciliation_and_safety_hooks_are_not_armed(self):
        trade = self.entry(requested_quantity="10")
        self.close_entry(trade)
        result = self.engine.qualification_exit(scope=trade["scope"], reason="TARGET", at=NOW)
        self.assertEqual("RECONCILE_EXISTING_CONTINGENT_EXIT", result["reason"])
        self.assertFalse(result["submission_performed"])
        for hook in SAFETY_HOOKS:
            self.assertFalse(self.engine.record_safety_hook(hook, at=NOW)["armed"])
        self.assertEqual(1, self.broker.submit_calls)

    def test_crash_boundaries_never_duplicate_submission(self):
        for boundary in ("before_intent_persistence", "after_intent_persistence", "before_submit", "after_ack"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as root:
                broker = SimulatedPaperBroker("fixture")
                def fail(point):
                    if point == boundary:
                        raise SimulatedCrash(point)
                engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy(),
                                                    simulator=broker, fault=fail)
                with self.assertRaises(SimulatedCrash):
                    engine.qualification_entry(decision(), at=NOW, account=account(), requested_quantity="10")
                resumed = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy(), simulator=broker)
                resumed.reconcile(at=NOW)
                resumed.qualification_entry(decision(), at=NOW, account=account(), requested_quantity="10")
                self.assertLessEqual(broker.submit_calls, 1)

    def test_pending_raw_receipt_survives_projection_crash(self):
        trade = self.entry(requested_quantity="10")
        self.broker.fill(trade["order_id"], fill_id="f1", quantity="3", price="99.9", at=NOW.isoformat())
        def fail(point):
            if point == "before_fill_persistence":
                raise SimulatedCrash
        self.engine = self.create(fault=fail)
        with self.assertRaises(SimulatedCrash):
            self.engine.reconcile(at=NOW)
        pending = self.create().inspect()["trades"][trade["scope"]]
        self.assertIsNotNone(pending["pending_receipt"])
        self.assertEqual("0", pending["filled"])
        result = self.create().reconcile(at=NOW)["trades"][trade["scope"]]
        self.assertEqual("3", result["filled"])


if __name__ == "__main__":
    unittest.main()
