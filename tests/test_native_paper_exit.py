from __future__ import annotations

import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.native_paper_broker import SimulatedPaperBroker
from momentum_hunter.native_paper_execution import NativePaperExecutionEngine, entry_findings
from momentum_hunter.native_paper_store import NativePaperError
from tests.test_native_paper_execution import decision, SimulatedCrash
from tests.test_native_paper_mechanics import NOW, account, policy


class NativeExitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.broker = SimulatedPaperBroker("fixture")
        self.engine = self.restore()
        self.trade = self.engine.qualification_entry(decision(), at=NOW, account=account(), requested_quantity="10")

    def restore(self, **kwargs):
        return NativePaperExecutionEngine(root=self.root, namespace="fixture", policy=policy(),
                                         simulator=self.broker, **kwargs)

    def enter(self, qty="10", fill_id="entry"):
        self.broker.fill(self.trade["order_id"], fill_id=fill_id, quantity=qty, price="99.90", at=NOW.isoformat())
        if qty == "10":
            self.broker.seal_order(self.trade["order_id"], at=NOW.isoformat())
        return self.project()

    def project(self):
        return self.engine.reconcile(at=NOW)["trades"][self.trade["scope"]]

    def exit(self, role, qty="10", fid=None):
        result = self.broker.fill(self.trade["exit_contract"][role.lower() + "_order_id"],
                                fill_id=fid or role, quantity=qty, price="98.9" if role == "STOP" else "102.1",
                                at=NOW.isoformat())
        if Decimal(self.broker.snapshot()["positions"][self.trade["position_id"]]) == 0:
            for key in ("stop_order_id", "target_order_id", "forced_flat_order_id"):
                self.broker.seal_order(self.trade["exit_contract"][key], at=NOW.isoformat())
        return result

    def assert_remaining(self, qty):
        state = self.project()
        self.assertNotEqual("QUARANTINED", state["state"])
        self.assertEqual(Decimal(qty), Decimal(state["position_quantity"]))
        for role in ("stop", "target"):
            order = self.broker.orders[self.trade["exit_contract"][role + "_order_id"]]
            self.assertEqual(Decimal(qty), Decimal(order["executable_quantity"]))
        self.assertEqual(Decimal("1"), Decimal(state["original_r_per_share"]))
        self.assertEqual(Decimal("10"), Decimal(state["original_r_authorized"]))
        return state

    def test_full_target(self):
        self.enter()
        self.exit("TARGET")
        self.assertEqual("POSITION_CLOSED", self.assert_remaining("0")["state"])

    def test_full_stop(self):
        self.enter()
        self.exit("STOP")
        self.assertEqual("POSITION_CLOSED", self.assert_remaining("0")["state"])

    def test_stop_trigger_is_not_reinterpreted_from_later_fill_price(self):
        self.enter()
        oid = self.trade["exit_contract"]["stop_order_id"]
        self.broker.trigger_exit(oid, observed_price="98.9", at=NOW.isoformat())
        self.broker.fill(oid, fill_id="improved-stop", quantity="10", price="99.2", at=NOW.isoformat())
        self.assert_remaining("0")

    def test_full_exit_without_complete_source_finality_remains_unknown(self):
        self.enter()
        self.broker.fill(self.trade["exit_contract"]["stop_order_id"], fill_id="stop", quantity="10",
                         price="98.9", at=NOW.isoformat())
        self.assertEqual("TERMINAL_UNKNOWN", self.assert_remaining("0")["state"])

    def test_preserved_canonical_deadline_not_research_time_stop(self):
        self.enter()
        oid = self.trade["exit_contract"]["forced_flat_order_id"]
        with self.assertRaisesRegex(NativePaperError, "DEADLINE_NOT_REACHED"):
            self.broker.fill(oid, fill_id="early", quantity="10", price="100", at=NOW.isoformat())
        deadline = decision().plan.forced_flat_at
        self.broker.fill(oid, fill_id="deadline", quantity="10", price="100", at=deadline)
        from datetime import datetime
        state = self.engine.reconcile(at=datetime.fromisoformat(deadline))["trades"][self.trade["scope"]]
        self.assertEqual("0", state["position_quantity"])
        self.assertEqual("OTHER_CANONICAL_IF_ALREADY_DEFINED", state["exit_events"][0]["exit_type"])
        self.assertEqual("FORCED_FLAT", state["exit_events"][0]["canonical_exit_role"])

    def test_expired_protection_is_never_silently_resurrected(self):
        self.enter()
        oid = self.trade["exit_contract"]["stop_order_id"]
        self.broker.expire(oid)
        self.exit("TARGET", "4")
        self.assertEqual("EXPIRED", self.broker.orders[oid]["status"])
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_foreign_broker_identity_cannot_replace_exit_identity(self):
        self.enter()
        oid = self.trade["exit_contract"]["stop_order_id"]
        self.broker.orders[oid]["broker_order_id"] = "foreign-order"
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_foreign_broker_identity_cannot_replace_entry_identity(self):
        self.broker.orders[self.trade["order_id"]]["broker_order_id"] = "foreign-order"
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_partial_target_then_stop(self):
        self.enter()
        self.exit("TARGET", "4")
        self.assert_remaining("6")
        self.exit("STOP", "6")
        self.assert_remaining("0")

    def test_partial_stop_then_target(self):
        self.enter()
        self.exit("STOP", "4")
        self.assert_remaining("6")
        self.exit("TARGET", "6")
        self.assert_remaining("0")

    def test_multiple_partial_entries_and_exits(self):
        self.enter("3", "entry-1")
        self.exit("TARGET", "1", "exit-1")
        self.assert_remaining("2")
        self.enter("7", "entry-2")
        self.broker.seal_order(self.trade["order_id"], at=NOW.isoformat())
        self.assert_remaining("9")
        self.exit("STOP", "3", "exit-2")
        self.assert_remaining("6")
        self.exit("TARGET", "6", "exit-3")
        self.assert_remaining("0")

    def test_no_reopening_from_pending_entry_after_flat(self):
        self.enter("3")
        self.exit("STOP", "3")
        with self.assertRaises(NativePaperError):
            self.enter("7", "entry-late")
        self.assert_remaining("0")

    def test_stop_wins_queued_race(self):
        self.enter()
        self.exit("STOP")
        with self.assertRaises(NativePaperError):
            self.exit("TARGET")
        self.assert_remaining("0")

    def test_target_wins_queued_race(self):
        self.enter()
        self.exit("TARGET")
        with self.assertRaises(NativePaperError):
            self.exit("STOP")
        self.assert_remaining("0")

    def test_simultaneous_callbacks_are_serialized_before_position_mutation(self):
        self.enter()
        def callback(role):
            try:
                self.exit(role)
                return "FILLED"
            except NativePaperError:
                return "REJECTED"
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertCountEqual(["FILLED", "REJECTED"], list(workers.map(callback, ("STOP", "TARGET"))))
        self.assert_remaining("0")

    def test_duplicate_stop_callback(self):
        self.enter()
        one = self.exit("STOP")
        self.assertEqual(one, self.exit("STOP"))
        self.assertEqual(1, len(self.assert_remaining("0")["exit_events"]))

    def test_duplicate_target_callback(self):
        self.enter()
        one = self.exit("TARGET")
        self.assertEqual(one, self.exit("TARGET"))
        self.assertEqual(1, len(self.assert_remaining("0")["exit_events"]))

    def test_exit_economic_id_cannot_duplicate_entry(self):
        self.enter()
        with self.assertRaisesRegex(NativePaperError, "ECONOMIC_FILL_ID_ALREADY_USED"):
            self.exit("STOP", fid="entry")
        self.assert_remaining("10")

    def test_partial_fill_oversell_rejected_before_economic_effect(self):
        self.enter()
        self.exit("TARGET", "4")
        before = self.broker.snapshot()
        with self.assertRaises(NativePaperError):
            self.exit("STOP", "10")
        self.assertEqual(before, self.broker.snapshot())
        self.assert_remaining("6")

    def test_late_callback_and_already_flat_exit_request_do_not_reopen(self):
        self.enter()
        self.exit("TARGET")
        self.project()
        self.engine = self.restore()
        result = self.engine.qualification_exit(scope=self.trade["scope"], reason="STOP", at=NOW)
        self.assertFalse(result["submission_performed"])
        with self.assertRaises(NativePaperError):
            self.exit("TARGET", fid="late")
        self.assert_remaining("0")

    def test_restart_stop_pending(self):
        self.enter()
        self.broker = SimulatedPaperBroker("fixture", restored=self.broker.snapshot())
        self.engine = self.restore()
        self.exit("STOP")
        self.assert_remaining("0")

    def test_restart_target_pending(self):
        self.enter()
        self.broker = SimulatedPaperBroker("fixture", restored=self.broker.snapshot())
        self.engine = self.restore()
        self.exit("TARGET")
        self.assert_remaining("0")

    def test_restart_partially_closed(self):
        self.enter()
        self.exit("TARGET", "4")
        self.project()
        self.engine = self.restore()
        self.assert_remaining("6")
        self.exit("STOP", "6")
        self.assert_remaining("0")

    def test_unknown_stop_callback_reconciles_without_resubmit(self):
        self.enter()
        self.exit("STOP")  # Broker acted; callback deliberately not delivered.
        self.engine = self.restore()
        result = self.engine.qualification_exit(scope=self.trade["scope"], reason="STOP", at=NOW)
        self.assertFalse(result["submission_performed"])
        self.assert_remaining("0")
        self.assertEqual(1, self.broker.submit_calls)

    def test_unknown_target_callback_reconciles_without_resubmit(self):
        self.enter()
        self.exit("TARGET", "4")
        self.engine = self.restore()
        result = self.engine.qualification_exit(scope=self.trade["scope"], reason="TARGET", at=NOW)
        self.assertFalse(result["submission_performed"])
        self.assert_remaining("6")
        self.assertEqual(1, self.broker.submit_calls)

    def test_unknown_protection_is_quarantined_not_blindly_repaired(self):
        self.enter()
        self.broker.connected = False
        state = self.project()
        self.assertEqual("QUARANTINED", state["state"])
        self.broker.connected = True
        self.assertEqual("QUARANTINED", self.restore().reconcile(at=NOW)["trades"][self.trade["scope"]]["state"])
        self.assertEqual(1, self.broker.submit_calls)

    def test_accepted_stop_cancel_quarantines_residual(self):
        self.enter()
        self.broker.cancel(self.trade["exit_contract"]["stop_order_id"])
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_unaccepted_stop_cancel_preserves_protection(self):
        self.enter()
        self.broker.cancel_accepted = False
        self.broker.cancel(self.trade["exit_contract"]["stop_order_id"])
        self.assert_remaining("10")

    def test_missing_stop_after_restart_fails_closed(self):
        self.enter()
        del self.broker.orders[self.trade["exit_contract"]["stop_order_id"]]
        self.engine = self.restore()
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_changed_target_cannot_be_reconciled_as_legitimate_replacement(self):
        self.enter()
        self.broker.orders[self.trade["exit_contract"]["target_order_id"]]["request"]["limit_price"] = "103"
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_no_adaptive_or_science_exit_input(self):
        self.enter()
        for reason in ("SCIENCE", "TRAILING", "BREAK_EVEN", "TIME_STOP", "PARTIAL", "EMERGENCY_FLATTEN_PAPER"):
            with self.subTest(reason=reason), self.assertRaises(NativePaperError):
                self.engine.qualification_exit(scope=self.trade["scope"], reason=reason, at=NOW)
        self.assert_remaining("10")

    def test_canonical_plan_never_rewritten(self):
        original = copy.deepcopy(self.trade["plan"])
        self.enter()
        self.exit("TARGET", "4")
        state = self.assert_remaining("6")
        self.assertEqual(original, state["plan"])
        self.assertEqual(Decimal("99"), Decimal(state["exit_contract"]["stop"]))
        self.assertEqual(Decimal("102"), Decimal(state["exit_contract"]["target"]))

    def test_missing_invalid_or_unticked_required_levels_fail_before_entry(self):
        for values in ({"target_prices": ()}, {"stop_price": None}, {"stop_price": 101},
                       {"target_prices": (99,)}, {"target_prices": (102.001,)}, {"stop_price": 99.001}):
            with self.subTest(values=values):
                self.assertTrue(entry_findings(replace(decision(), plan=replace(decision().plan, **values)), NOW))

    def test_audit_contains_exact_exit_contract_fields(self):
        self.enter()
        self.exit("TARGET", "4")
        self.exit("STOP", "6")
        state = self.assert_remaining("0")
        self.assertEqual(["TARGET", "STOP"], [event["exit_type"] for event in state["exit_events"]])
        for event in state["exit_events"]:
            for key in ("trade_plan_id", "position_id", "exit_intent_id", "exit_type", "requested_quantity",
                        "filled_quantity", "remaining_quantity", "request_time", "broker_event_time",
                        "simulated_broker_response", "reason_code", "prior_state", "new_state"):
                self.assertIn(key, event)

    def test_false_exit_quantity_audit_is_not_accepted(self):
        self.enter()
        self.exit("TARGET", "4")
        self.broker.exit_events[0]["remaining_quantity"] = "10"
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_missing_first_fill_prefix_cannot_rewrite_opened_at(self):
        self.enter("3", "entry-1")
        first = self.project()["opened_at"]
        self.enter("7", "entry-2")
        self.broker.orders[self.trade["order_id"]]["fills"].pop(0)
        state = self.project()
        self.assertEqual("QUARANTINED", state["state"])
        self.assertEqual(first, state["opened_at"])

    def test_exit_receipt_crash_before_projection_preserves_raw_and_exactly_once(self):
        self.enter()
        self.exit("TARGET", "4")
        def fail(point):
            if point == "before_fill_persistence":
                raise SimulatedCrash
        self.engine = self.restore(fault=fail)
        with self.assertRaises(SimulatedCrash):
            self.project()
        self.assertIsNotNone(self.restore().inspect()["trades"][self.trade["scope"]]["pending_receipt"])
        self.engine = self.restore()
        self.assertEqual(1, len(self.assert_remaining("6")["exit_events"]))
        self.assertEqual(1, len(self.assert_remaining("6")["exit_events"]))

    def test_same_symbol_different_position_exit_isolation(self):
        self.enter()
        other = self.engine.qualification_entry(decision("opportunity-2", "TEST", "setup-2"),
                                                  at=NOW, account=account(), requested_quantity="10")
        self.broker.fill(other["order_id"], fill_id="entry-other", quantity="10", price="100", at=NOW.isoformat())
        self.exit("STOP")
        self.assert_remaining("0")
        self.assertEqual("10", self.broker.snapshot()["positions"][other["position_id"]])

    def test_pending_entry_raw_cannot_be_erased_by_broker_regression(self):
        before = self.broker.snapshot()
        self.broker.fill(self.trade["order_id"], fill_id="pending-entry", quantity="3", price="99.9", at=NOW.isoformat())
        def fail(point):
            if point == "before_fill_persistence":
                raise SimulatedCrash
        self.engine = self.restore(fault=fail)
        with self.assertRaises(SimulatedCrash):
            self.project()
        raw = self.restore().inspect()["trades"][self.trade["scope"]]["pending_receipt"]
        self.broker = SimulatedPaperBroker("fixture", restored=before)
        self.engine = self.restore()
        state = self.project()
        self.assertEqual("QUARANTINED", state["state"])
        self.assertEqual(raw, state["pending_receipt"])
        self.assertEqual(before, state["conflicting_receipt"])
        self.assertEqual("3", raw["positions"][self.trade["position_id"]])

    def test_pending_exit_raw_cannot_be_erased_by_broker_regression(self):
        self.enter()
        before = self.broker.snapshot()
        self.exit("TARGET", "4")
        def fail(point):
            if point == "before_fill_persistence":
                raise SimulatedCrash
        self.engine = self.restore(fault=fail)
        with self.assertRaises(SimulatedCrash):
            self.project()
        raw = self.restore().inspect()["trades"][self.trade["scope"]]["pending_receipt"]
        self.broker = SimulatedPaperBroker("fixture", restored=before)
        self.engine = self.restore()
        state = self.project()
        self.assertEqual("QUARANTINED", state["state"])
        self.assertEqual(raw, state["pending_receipt"])
        self.assertEqual("6", raw["positions"][self.trade["position_id"]])

    def test_unfilled_future_stop_trigger_blocks_current_authority(self):
        self.enter()
        from datetime import timedelta
        oid = self.trade["exit_contract"]["stop_order_id"]
        self.broker.trigger_exit(oid, observed_price="98.9", at=(NOW + timedelta(seconds=10)).isoformat())
        self.assertEqual("QUARANTINED", self.project()["state"])
        with self.assertRaisesRegex(NativePaperError, "QUARANTINED"):
            self.engine.qualification_entry(decision("other", "TEST", "other"), at=NOW, account=account())
        self.assertEqual(1, self.broker.submit_calls)

    def test_unfilled_future_target_trigger_blocks_current_authority(self):
        self.enter()
        from datetime import timedelta
        oid = self.trade["exit_contract"]["target_order_id"]
        self.broker.trigger_exit(oid, observed_price="102.1", at=(NOW + timedelta(seconds=10)).isoformat())
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_valid_unfilled_trigger_remains_pending_with_exact_protection(self):
        self.enter()
        oid = self.trade["exit_contract"]["stop_order_id"]
        self.broker.trigger_exit(oid, observed_price="98.9", at=NOW.isoformat())
        self.assertEqual("POSITION_OPEN", self.assert_remaining("10")["state"])

    def test_unfilled_trigger_requires_correct_acquired_frontier(self):
        self.enter()
        oid = self.trade["exit_contract"]["stop_order_id"]
        self.broker.trigger_exit(oid, observed_price="98.9", at=NOW.isoformat())
        self.broker.orders[oid]["trigger"]["economic_frontier"] = 0
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_pending_trigger_cannot_disappear_at_higher_source_revision(self):
        self.enter()
        oid = self.trade["exit_contract"]["stop_order_id"]
        self.broker.trigger_exit(oid, observed_price="98.9", at=NOW.isoformat())
        def fail(point):
            if point == "before_fill_persistence":
                raise SimulatedCrash
        self.engine = self.restore(fault=fail)
        with self.assertRaises(SimulatedCrash):
            self.project()
        raw = self.restore().inspect()["trades"][self.trade["scope"]]["pending_receipt"]
        del self.broker.orders[oid]["trigger"]
        self.broker.orders[oid]["revision"] += 1
        self.engine = self.restore()
        state = self.project()
        self.assertEqual("QUARANTINED", state["state"])
        self.assertEqual(raw, state["pending_receipt"])

    def pending_trigger_replacement(self, future):
        from datetime import timedelta
        self.enter()
        earlier = self.broker.snapshot()
        oid = self.trade["exit_contract"]["stop_order_id"]
        self.broker.trigger_exit(oid, observed_price="99", at=(NOW + timedelta(seconds=10 if future else 0)).isoformat())
        def fail(point):
            if point == "before_fill_persistence":
                raise SimulatedCrash
        self.engine = self.restore(fault=fail)
        with self.assertRaises(SimulatedCrash):
            self.project()
        raw = self.restore().inspect()["trades"][self.trade["scope"]]["pending_receipt"]
        self.broker = SimulatedPaperBroker("fixture", restored=earlier)
        later = NOW + timedelta(seconds=1)
        self.broker.trigger_exit(oid, observed_price="98", at=later.isoformat())
        self.broker.fill(oid, fill_id="replacement", quantity="1", price="98", at=later.isoformat())
        for _ in range(2):
            self.engine = self.restore()
            state = self.engine.reconcile(at=later)["trades"][self.trade["scope"]]
            self.assertEqual("QUARANTINED", state["state"])
            self.assertEqual(raw, state["pending_receipt"])
            self.assertEqual("10", state["position_quantity"])
        self.assertEqual(earlier["submit_calls"], self.broker.submit_calls)

    def test_pending_valid_trigger_replacement_is_retained_across_restart(self):
        self.pending_trigger_replacement(False)

    def test_pending_future_trigger_cannot_be_laundered_after_restart(self):
        self.pending_trigger_replacement(True)


if __name__ == "__main__":
    unittest.main()
