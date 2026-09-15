"""Native-owner witnesses of the retained R4 closure/entry contract.

R4 source: 8afc3a3bf35136840728e136352db4f017f57c1a,
test_closure_monotonicity.py. This file imports no Science oracle Product code.
Session labels are remapped to explicit offline fixture dates, quantities stay
Q100, CANCELED maps to native CANCELLED. No fictional arm becomes real authority.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from momentum_hunter.intraday_trade_plan import build_intraday_plan_evidence, CONTINUATION_BREAKOUT
from momentum_hunter.native_paper_broker import SimulatedPaperBroker
from momentum_hunter.native_paper_execution import NativePaperExecutionEngine, OfflinePaperDecision
from momentum_hunter.native_paper_store import NativePaperError
from tests.test_native_paper_mechanics import NOW, account, policy


SEQUENCES = (
    "working_closed", "working_closed_working", "working_terminal_working", "closed_working",
    "terminal_working_closed", "duplicate_closed", "duplicate_terminal", "stale_working_after_closure",
    "reordered_working_after_closure", "restart_closure_later_working", "restart_closure_duplicate_working",
    "terminal_stale_queued_working", "multiple_contradictory_working", "closure_replay_working",
    "partial_history_durable_terminal_working",
)
SESSIONS = {"A": NOW, "B": NOW + timedelta(days=1), "FAR": NOW + timedelta(days=119, hours=1)}
STATUSES = ("CANCELLED", "REJECTED", "EXPIRED")
HISTORY = ("scope", "plan", "request", "order_id", "position_id", "closure", "quantity",
           "filled", "unfilled", "closed_unfilled", "position_quantity", "opened_at", "exit_filled")


def source_decision(now, suffix="1"):
    plan = build_intraday_plan_evidence(symbol="TEST", setup_family=CONTINUATION_BREAKOUT, created_at=now,
        planned_entry=100, stop_price=99, target_prices=(102,), source_setup_fingerprint="a" * 64,
        source_level_kind="RANGE_HIGH", source_evidence_ids=("setup-" + suffix,), observed_price=100)
    return OfflinePaperDecision("opportunity-" + suffix, "setup-" + suffix, "decision-1", plan,
        now.isoformat(), now.isoformat(), "100", now.isoformat(), ".01", 10000, 1, 30)


def source_account(now):
    return account(cash_available=Decimal("100000"), buying_power=Decimal("100000"),
                   provider_timestamp=now.isoformat(), portfolio_timestamp=now.isoformat(), receipt_timestamp=now.isoformat())


class NativeR4ClosureParity(unittest.TestCase):
    def initiation_fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = NOW
        self.broker = SimulatedPaperBroker("fixture")
        self.initiation_at = NOW + timedelta(seconds=10)
        self.engine = self.restart(qualification_clock=lambda: self.initiation_at)
        self.trade = self.engine.qualification_entry(source_decision(NOW), at=NOW,
            account=source_account(NOW), requested_quantity="100")
        self.oid = self.trade["order_id"]

    def test_fill_cannot_predate_actual_initiation(self):
        self.initiation_fixture()
        self.broker.fill(self.oid, fill_id="pre-send", quantity="100", price="99.9", at=NOW.isoformat())
        self.broker.seal_order(self.oid, at=NOW.isoformat())
        state = self.restart(require_existing=True).reconcile(at=self.initiation_at)
        trade = state["trades"][self.trade["scope"]]
        self.assertTrue(state["quarantined"])
        self.assertIsNone(trade["opened_at"])
        self.assertEqual("0", trade["position_quantity"])
        self.assertIsNotNone(trade["pending_receipt"])

    def test_source_observations_cannot_predate_actual_initiation(self):
        for kind in ("ACK", "WORKING", "CLOSURE"):
            with self.subTest(kind=kind):
                self.initiation_fixture()
                if kind == "CLOSURE":
                    self.broker.cancel(self.oid)
                    self.broker.seal_order(self.oid, at=NOW.isoformat())
                self.broker.observe(self.oid, kind=kind, event_at=NOW.isoformat(),
                    known_at=self.initiation_at.isoformat(), receipt_id="pre-send-" + kind)
                self.assertTrue(self.restart().reconcile(at=self.initiation_at)["quarantined"])

    def test_closure_without_observation_cannot_predate_actual_initiation(self):
        self.initiation_fixture()
        self.broker.cancel(self.oid)
        self.broker.seal_order(self.oid, at=NOW.isoformat())
        self.assertTrue(self.restart().reconcile(at=self.initiation_at)["quarantined"])

    def test_fill_at_or_after_actual_initiation_preserves_exact_opened_at(self):
        for offset in (0, 1):
            with self.subTest(offset=offset):
                self.initiation_fixture()
                filled_at = self.initiation_at + timedelta(seconds=offset)
                self.broker.fill(self.oid, fill_id="valid", quantity="100", price="99.9", at=filled_at.isoformat())
                self.broker.seal_order(self.oid, at=filled_at.isoformat())
                state = self.restart(require_existing=True).reconcile(at=filled_at)
                trade = state["trades"][self.trade["scope"]]
                self.assertFalse(state["quarantined"])
                self.assertEqual("POSITION_OPEN", trade["state"])
                self.assertEqual(filled_at.isoformat(), trade["opened_at"])
                self.assertEqual(self.initiation_at.isoformat(), trade["initiation_at"])

    def fixture(self, session="A", status="CANCELLED", initial=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = SESSIONS[session]
        self.broker = SimulatedPaperBroker("fixture")
        self.engine = self.restart()
        if status == "REJECTED":
            self.broker.next_submit = "REJECT"
        self.trade = self.engine.qualification_entry(source_decision(self.now), at=self.now,
                           account=source_account(self.now), requested_quantity="100")
        self.oid = self.trade["order_id"]
        if initial:
            self.observe("WORKING", 0, "initial")
        if status == "CANCELLED":
            self.broker.cancel(self.oid)
        elif status == "EXPIRED":
            self.broker.expire(self.oid)
        self.broker.seal_order(self.oid, at=(self.now + timedelta(seconds=60)).isoformat())
        self.trade = self.project()
        self.assertEqual(status, self.trade["state"])
        self.assertEqual(("100", "0", "0", "100"), tuple(self.trade[k] for k in ("quantity", "filled", "unfilled", "closed_unfilled")))

    def restart(self, **kwargs):
        return NativePaperExecutionEngine(root=self.root, namespace="fixture", policy=policy("100000"),
                                         simulator=self.broker, **kwargs)

    def observe(self, kind, seconds, rid, known_seconds=120):
        self.broker.observe(self.oid, kind=kind, event_at=(self.now + timedelta(seconds=seconds)).isoformat(),
                            known_at=(self.now + timedelta(seconds=known_seconds)).isoformat(), receipt_id=rid)

    def project(self):
        return self.engine.reconcile(at=self.now + timedelta(seconds=120))["trades"][self.trade["scope"]]

    def history(self, trade):
        return {key: copy.deepcopy(trade[key]) for key in HISTORY}

    def run_sequence(self, sequence, session, status):
        initial = sequence not in {"closed_working", "partial_history_durable_terminal_working"}
        self.fixture(session, status, initial)
        historical = self.history(self.trade)
        good = sequence in {"working_closed", "duplicate_closed", "duplicate_terminal", "stale_working_after_closure",
                             "reordered_working_after_closure", "restart_closure_duplicate_working", "terminal_stale_queued_working"}
        if "restart" in sequence or sequence in {"closure_replay_working", "partial_history_durable_terminal_working"}:
            self.engine = self.restart()
        if sequence == "duplicate_closed":
            for _ in range(2):
                self.broker.seal_order(self.oid, at=(self.now + timedelta(seconds=60)).isoformat())
        elif sequence == "duplicate_terminal":
            self.broker.seal_order(self.oid, at=(self.now + timedelta(seconds=120)).isoformat())
        elif sequence == "restart_closure_duplicate_working":
            self.observe("WORKING", 0, "initial")
        elif sequence in {"stale_working_after_closure", "reordered_working_after_closure", "terminal_stale_queued_working"}:
            self.observe("WORKING", 30, "old", 30 if sequence == "reordered_working_after_closure" else 120)
        elif sequence != "working_closed":
            for index in range(4 if sequence == "multiple_contradictory_working" else 1):
                self.observe("WORKING", 120, "late-" + str(index))
        result = self.project()
        self.assertEqual(historical, self.history(result))
        self.assertEqual(not good, self.engine.inspect()["quarantined"])
        if not good:
            self.assertEqual("QUARANTINED", result["state"])
            self.assertIsNotNone(result["pending_receipt"])
            self.engine = self.restart()
            self.assertEqual("QUARANTINED", self.project()["state"])
            self.broker.seal_order(self.oid, at=(self.now + timedelta(seconds=60)).isoformat())
            self.assertEqual("QUARANTINED", self.project()["state"])
        else:
            self.assertIsNone(result["pending_receipt"])
            old = self.engine.qualification_entry(source_decision(self.now), at=self.now + timedelta(seconds=120),
                            account=source_account(self.now + timedelta(seconds=120)), requested_quantity="100")
            self.assertEqual(self.trade["order_id"], old["order_id"])
            self.assertEqual(1, self.broker.submit_calls)
            new_now = self.now + timedelta(seconds=120)
            new = self.engine.qualification_entry(source_decision(new_now, "2"), at=new_now,
                           account=source_account(new_now), requested_quantity="100")
            self.assertNotEqual(self.oid, new["order_id"])
            self.assertEqual(2, self.broker.submit_calls)
        self.assertEqual("NONE", self.engine.execution_authority)

    def test_equal_boundary_ordering_and_duplicate(self):
        self.fixture(initial=False)
        self.observe("WORKING", 60, "equal")
        self.assertEqual("QUARANTINED", self.project()["state"])

    def test_first_equal_time_closure_preserves_prior_working(self):
        self.fixture()
        # Independent economic scenario, not a repair of any persisted evidence.
        with tempfile.TemporaryDirectory() as root:
            broker = SimulatedPaperBroker("fixture")
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy("100000"), simulator=broker)
            trade = engine.qualification_entry(source_decision(self.now), at=self.now, account=source_account(self.now), requested_quantity="100")
            boundary = (self.now + timedelta(seconds=60)).isoformat()
            broker.observe(trade["order_id"], kind="WORKING", event_at=boundary, known_at=boundary, receipt_id="working")
            broker.cancel(trade["order_id"])
            broker.seal_order(trade["order_id"], at=boundary)
            self.assertFalse(engine.reconcile(at=self.now + timedelta(seconds=120))["quarantined"])
            broker.seal_order(trade["order_id"], at=boundary)
            self.assertFalse(engine.reconcile(at=self.now + timedelta(seconds=120))["quarantined"])

    def test_earlier_duplicate_closure_crossing_working_both_orders(self):
        for closure_first in (True, False):
            with self.subTest(closure_first=closure_first):
                self.fixture(initial=False)
                if closure_first:
                    self.broker.seal_order(self.oid, at=(self.now + timedelta(seconds=30)).isoformat())
                    self.project()
                    self.observe("WORKING", 45, "between")
                else:
                    self.observe("WORKING", 45, "between")
                    self.project()
                    self.broker.seal_order(self.oid, at=(self.now + timedelta(seconds=30)).isoformat())
                self.assertEqual("QUARANTINED", self.project()["state"])

    def test_cancel_ack_partial_late_fill_then_complete_closure(self):
        self.fixture()
        with tempfile.TemporaryDirectory() as root:
            broker = SimulatedPaperBroker("fixture")
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy(), simulator=broker)
            trade = engine.qualification_entry(source_decision(NOW), at=NOW, account=account(), requested_quantity="10")
            oid = trade["order_id"]
            broker.fill(oid, fill_id="1", quantity="3", price="99.9", at=NOW.isoformat())
            broker.cancel(oid)
            engine.reconcile(at=NOW)
            broker.fill(oid, fill_id="2", quantity="2", price="99.9", at=NOW.isoformat())
            broker.seal_order(oid, at=NOW.isoformat())
            result = engine.reconcile(at=NOW)["trades"][trade["scope"]]
            self.assertEqual(("5", "0", "5", "5"), tuple(result[k] for k in ("filled", "unfilled", "closed_unfilled", "position_quantity")))

    def test_freshness_rechecked_immediately_before_send(self):
        with tempfile.TemporaryDirectory() as root:
            broker = SimulatedPaperBroker("fixture")
            value = source_decision(NOW)
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy(), simulator=broker,
                qualification_clock=lambda: NOW + timedelta(seconds=31))
            result = engine.qualification_entry(value, at=NOW, account=account(), requested_quantity="10")
            self.assertEqual("KNOWN_NOT_SUBMITTED", result["state"])
            self.assertEqual(0, broker.submit_calls)
            replay = engine.qualification_entry(value, at=NOW + timedelta(seconds=31), account=account(), requested_quantity="10")
            self.assertEqual(result["order_id"], replay["order_id"])

    def test_receipt_arrival_invalidates_prepared_current_source_fence(self):
        self.fixture()
        def changed(point):
            if point == "before_submit":
                self.observe("ACK", 0, "new-raw-receipt")
        self.engine = self.restart(fault=changed)
        current = self.now + timedelta(seconds=120)
        value = self.engine.qualification_entry(source_decision(current, "2"), at=current,
                                                account=source_account(current), requested_quantity="100")
        self.assertEqual("KNOWN_NOT_SUBMITTED", value["state"])
        self.assertEqual(1, self.broker.submit_calls)
        self.assertEqual("100", value["closed_unfilled"])

    def test_account_freshness_cannot_expire_between_risk_and_send(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as root:
            broker = SimulatedPaperBroker("fixture")
            value = replace(source_decision(NOW), max_price_age_seconds=120)
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy(), simulator=broker,
                qualification_clock=lambda: NOW + timedelta(seconds=31))
            result = engine.qualification_entry(value, at=NOW, account=account(), requested_quantity="10")
            self.assertEqual("KNOWN_NOT_SUBMITTED", result["state"])
            self.assertEqual(0, broker.submit_calls)
            self.assertIn("ALLOCATION_ACCOUNT_SNAPSHOT_STALE", result["initiation_risk_recheck"]["blockers"])
            restored = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy(), simulator=broker,
                                                  require_existing=True)
            replay = restored.qualification_entry(value, at=NOW + timedelta(seconds=31), account=account(), requested_quantity="10")
            self.assertEqual(result["order_id"], replay["order_id"])
            self.assertEqual(0, broker.submit_calls)

    def test_current_account_recheck_preserves_original_final_quantity(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as root:
            broker = SimulatedPaperBroker("fixture")
            value = replace(source_decision(NOW), max_price_age_seconds=120)
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy(), simulator=broker,
                qualification_clock=lambda: NOW + timedelta(seconds=20))
            result = engine.qualification_entry(value, at=NOW, account=account(), requested_quantity="10")
            self.assertEqual("ORDER_SUBMITTED", result["state"])
            self.assertEqual("10", result["initiation_risk_recheck"]["quantity"])
            self.assertEqual(result["risk"]["risk_decision_id"], result["request"]["risk_decision_id"])
            self.assertEqual(1, broker.submit_calls)

    def test_missing_custody_cannot_reset_scope_against_existing_broker(self):
        self.fixture()
        with tempfile.TemporaryDirectory() as root:
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy("100000"), simulator=self.broker)
            with self.assertRaisesRegex(NativePaperError, "MISSING_EXECUTION_CUSTODY"):
                engine.qualification_entry(source_decision(self.now), at=self.now, account=source_account(self.now), requested_quantity="100")

    def test_exact_expiry_denied_with_other_freshness_gates_satisfied(self):
        from datetime import datetime
        from momentum_hunter.native_paper_execution import entry_findings
        with tempfile.TemporaryDirectory() as root:
            broker = SimulatedPaperBroker("fixture")
            value = source_decision(NOW)
            expiry = datetime.fromisoformat(value.plan.entry_expires_at)
            fresh = replace(value, known_at=expiry.isoformat(), decision_cutoff=expiry.isoformat(),
                            price_known_at=expiry.isoformat())
            self.assertEqual(["ENTRY_WINDOW_CLOSED"], entry_findings(fresh, expiry))
            before = expiry - timedelta(microseconds=1)
            earlier = replace(fresh, known_at=before.isoformat(), decision_cutoff=before.isoformat(),
                              price_known_at=before.isoformat())
            self.assertEqual([], entry_findings(earlier, before))
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy("100000"), simulator=broker)
            result = engine.qualification_entry(fresh, at=expiry, account=source_account(expiry), requested_quantity="100")
            self.assertEqual(["ENTRY_WINDOW_CLOSED"], result["blockers"])
            self.assertEqual(0, broker.submit_calls)

    def test_native_missed_entry_mapping_uses_canonical_setup_family(self):
        from momentum_hunter.native_paper_execution import entry_findings
        for family in ("OPENING_BREAKOUT", "CONTINUATION_BREAKOUT", "PULLBACK", "RECLAIM"):
            with self.subTest(family=family):
                value = source_decision(NOW)
                predecessor = None
                if family == "RECLAIM":
                    predecessor = build_intraday_plan_evidence(symbol="TEST", setup_family=CONTINUATION_BREAKOUT,
                        created_at=NOW - timedelta(minutes=1), planned_entry=100, stop_price=99,
                        target_prices=(102,), source_setup_fingerprint="b" * 64, source_level_kind="RANGE_HIGH",
                        source_evidence_ids=("missed-setup",), observed_price=100.01)
                plan = build_intraday_plan_evidence(symbol="TEST", setup_family=family, created_at=NOW,
                    planned_entry=100, stop_price=99, target_prices=(102,), source_setup_fingerprint="a" * 64,
                    source_level_kind="RANGE_HIGH", source_evidence_ids=("setup-1",), observed_price=100,
                    predecessor=predecessor, replacement_reason="LEVEL_RECLAIMED" if predecessor else "")
                findings = entry_findings(replace(value, plan=plan, observed_price="100.01"), NOW)
                self.assertEqual(["DO_NOT_TRADE_MISSED_ENTRY"] if "BREAKOUT" in family else [], findings)

    def test_first_closure_cannot_predate_retained_working(self):
        with tempfile.TemporaryDirectory() as root:
            broker = SimulatedPaperBroker("fixture")
            engine = NativePaperExecutionEngine(root=Path(root), namespace="fixture", policy=policy(), simulator=broker)
            trade = engine.qualification_entry(source_decision(NOW), at=NOW, account=account(), requested_quantity="10")
            later = NOW + timedelta(seconds=60)
            broker.observe(trade["order_id"], kind="WORKING", event_at=later.isoformat(), known_at=later.isoformat(), receipt_id="retained")
            engine.reconcile(at=later)
            broker.cancel(trade["order_id"])
            broker.seal_order(trade["order_id"], at=(NOW + timedelta(seconds=30)).isoformat())
            state = engine.reconcile(at=later)
            self.assertTrue(state["quarantined"])
            self.assertIsNotNone(state["trades"][trade["scope"]]["pending_receipt"])


for _sequence in SEQUENCES:
    for _session in SESSIONS:
        for _status in STATUSES:
            def _case(self, sequence=_sequence, session=_session, status=_status):
                self.run_sequence(sequence, session, status)
            setattr(NativeR4ClosureParity, f"test_matrix_{_sequence}_{_session}_{_status}", _case)


if __name__ == "__main__":
    unittest.main()
