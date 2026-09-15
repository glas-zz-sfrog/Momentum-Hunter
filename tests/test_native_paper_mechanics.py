from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.autonomy.ledger import ExecutionLedgerEvent
from momentum_hunter.native_paper_broker import ENVIRONMENT, PROVIDER, SimulatedPaperBroker
from momentum_hunter.native_paper_risk import NativePaperRiskPolicy, evaluate_native_risk
from momentum_hunter.native_paper_store import NativePaperError, NativePaperStore, fingerprint
from momentum_hunter.provider_neutral_allocation import AccountSnapshot


NOW = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)
PLAN = {"decision_id": "decision-1", "opportunity_id": "opportunity-1",
        "setup_id": "setup-1", "trade_plan_id": "tradeplan-1", "symbol": "TEST",
        "rank": 1, "stop": "99", "target": "102"}


def policy(capital="10000"):
    return NativePaperRiskPolicy(capital, ".01", ".25", ".5", ".1", ".02", ".04", 10, 30)


def account(**changes):
    value = AccountSnapshot("fixture-snapshot", "decision-1", ENVIRONMENT, PROVIDER,
                            ENVIRONMENT, fingerprint([ENVIRONMENT, "fixture"]), 1, "ACTIVE",
                            Decimal("10000"), Decimal("10000"), Decimal(0), Decimal(0),
                            0, Decimal(0), NOW.isoformat(), NOW.isoformat(), NOW.isoformat(),
                            "OFFLINE_FIXTURE")
    return replace(value, **changes)


def request():
    return {"order_id": "order-1", "position_id": "position-1", "environment": ENVIRONMENT,
            "namespace": "fixture", "side": "BUY", "quantity": "10", "limit_price": "100",
            "risk_decision_id": "risk-1"}


class OfflineBrokerTests(unittest.TestCase):
    def test_unknown_ack_preserves_order_for_reconciliation(self):
        broker = SimulatedPaperBroker("fixture")
        broker.next_submit = "ACK_TIMEOUT"
        with self.assertRaises(TimeoutError):
            broker.submit(request())
        self.assertEqual(1, broker.submit_calls)
        self.assertEqual(["order-1"], broker.snapshot()["open_orders"])

    def test_unknown_before_accept_does_not_invent_order(self):
        broker = SimulatedPaperBroker("fixture")
        broker.next_submit = "TIMEOUT_BEFORE_ACCEPT"
        with self.assertRaises(TimeoutError):
            broker.submit(request())
        self.assertEqual({}, broker.snapshot()["orders"])

    def test_partial_duplicate_fill_and_full_fill(self):
        broker = SimulatedPaperBroker("fixture")
        broker.submit(request())
        first = broker.fill("order-1", fill_id="fill-1", quantity="3", price="99.8", at=NOW.isoformat())
        duplicate = broker.fill("order-1", fill_id="fill-1", quantity="3", price="99.8", at=NOW.isoformat())
        self.assertEqual(first, duplicate)
        broker.fill("order-1", fill_id="fill-2", quantity="7", price="99.9", at=NOW.isoformat())
        self.assertEqual("10", broker.snapshot()["positions"]["position-1"])
        self.assertEqual([], broker.snapshot()["open_orders"])

    def test_order_idempotence_and_conflict(self):
        broker = SimulatedPaperBroker("fixture")
        self.assertEqual(broker.submit(request()), broker.submit(request()))
        self.assertEqual(1, broker.submit_calls)
        with self.assertRaisesRegex(NativePaperError, "CONFLICT"):
            broker.submit(dict(request(), quantity="11"))

    def test_cancel_rejected_and_accepted(self):
        broker = SimulatedPaperBroker("fixture")
        broker.submit(request())
        broker.cancel_accepted = False
        self.assertEqual("ACK", broker.cancel("order-1")["status"])
        broker.cancel_accepted = True
        self.assertEqual("CANCELLED", broker.cancel("order-1")["status"])

    def test_reject_and_connection_loss(self):
        broker = SimulatedPaperBroker("fixture")
        broker.next_submit = "REJECT"
        self.assertEqual("REJECTED", broker.submit(request())["status"])
        broker.connected = False
        with self.assertRaises(ConnectionError):
            broker.snapshot()

    def test_restore_separates_namespaces(self):
        broker = SimulatedPaperBroker("fixture")
        broker.submit(request())
        snapshot = broker.snapshot()
        self.assertEqual(snapshot, SimulatedPaperBroker("fixture", restored=snapshot).snapshot())
        with self.assertRaises(NativePaperError):
            SimulatedPaperBroker("another", restored=snapshot)

    def test_nontransmitting_even_with_socket_available(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            broker = SimulatedPaperBroker("fixture")
            broker.submit(request())
            broker.snapshot()
        self.assertFalse(broker.order_transmit_allowed)


class NativeRiskTests(unittest.TestCase):
    def evaluate(self, **changes):
        values = dict(plan=PLAN, price="100", at=NOW, account=account(), policy=policy(),
                      namespace="fixture", trades={}, requested_quantity=None)
        values.update(changes)
        return evaluate_native_risk(**values)

    def test_canonical_allocation_and_scale_independence(self):
        small = self.evaluate()
        large = self.evaluate(policy=policy("100000"),
                              account=account(cash_available=Decimal("100000"), buying_power=Decimal("100000")))
        self.assertTrue(small["authorized"])
        self.assertEqual(Decimal(large["quantity"]), Decimal(small["quantity"]) * 10)
        self.assertEqual("provider-neutral-account-allocation-v1", small["allocation"]["profile"])

    def test_missing_snapshot(self):
        self.assertFalse(self.evaluate(account=None)["authorized"])

    def test_stale_snapshot(self):
        old = NOW.replace(minute=59, hour=13).isoformat()
        self.assertIn("ALLOCATION_ACCOUNT_SNAPSHOT_STALE",
                      self.evaluate(account=account(provider_timestamp=old))["blockers"])

    def test_future_snapshot(self):
        future = NOW.replace(minute=1).isoformat()
        self.assertFalse(self.evaluate(account=account(receipt_timestamp=future))["authorized"])

    def test_live_or_unbound_snapshot(self):
        for changes in ({"environment": "LIVE"}, {"provider": "BROKER"},
                        {"binding_fingerprint": "a" * 64}, {"source_identity": "SCIENCE"}):
            with self.subTest(changes=changes):
                self.assertFalse(self.evaluate(account=account(**changes))["authorized"])

    def test_daily_loss_and_reserve(self):
        self.assertFalse(self.evaluate(account=account(realized_pnl_today=Decimal("-200")))["authorized"])
        self.assertFalse(self.evaluate(account=account(cash_available=Decimal("1000")))["authorized"])

    def test_invalid_quantity_and_geometry(self):
        for value in ("0", "-1", "NaN", "0.5", "99999"):
            with self.subTest(value=value):
                self.assertFalse(self.evaluate(requested_quantity=value)["authorized"])
        self.assertFalse(self.evaluate(plan=dict(PLAN, stop="101"))["authorized"])
        self.assertFalse(self.evaluate(plan=dict(PLAN, target="99"))["authorized"])

    def test_pending_reservations_and_duplicate_exposure(self):
        pending = {"t": {"state": "UNKNOWN", "quantity": "25", "entry_price": "100", "plan": PLAN}}
        self.assertIn("RISK_DUPLICATE_OPPORTUNITY_EXPOSURE", self.evaluate(trades=pending)["blockers"])
        pending["t"]["quantity"] = "50"
        self.assertIn("RISK_PORTFOLIO_CAP_EXCEEDED", self.evaluate(trades=pending)["blockers"])

    def test_disjoint_baseline_and_local_exposure_are_added(self):
        local = {"t": {"state": "POSITION_OPEN", "quantity": "30", "unfilled": "0",
                       "position_quantity": "30", "entry_cost": "3000", "entry_price": "100",
                       "plan": dict(PLAN, opportunity_id="other")}}
        result = self.evaluate(trades=local, account=account(committed_notional=Decimal("2500")))
        self.assertIn("RISK_PORTFOLIO_CAP_EXCEEDED", result["blockers"])
        self.assertEqual("5500", result["exposure"]["combined_notional"])

    def test_closed_trade_spent_cash_is_not_settlement(self):
        closed = {"t": {"state": "POSITION_CLOSED", "quantity": "90", "unfilled": "0",
                        "position_quantity": "0", "entry_cost": "9000", "entry_price": "100",
                        "plan": dict(PLAN, opportunity_id="other")}}
        result = self.evaluate(trades=closed)
        self.assertFalse(result["authorized"])
        self.assertEqual("9000", result["exposure"]["native_spent_cash"])
        self.assertEqual("0", result["exposure"]["settlement_credit"])

    def test_native_losses_and_external_position_slots_are_not_lost(self):
        closed = {"t": {"state": "POSITION_CLOSED", "quantity": "10", "entry_cost": "1000",
                        "entry_price": "100", "plan": dict(PLAN, opportunity_id="other"),
                        "exit_orders": {"stop": {"fills": [{"quantity": "10", "price": "79"}]}}}}
        self.assertFalse(self.evaluate(trades=closed)["authorized"])
        opened = {"t": {"state": "POSITION_OPEN", "quantity": "1", "unfilled": "0",
                        "position_quantity": "1", "entry_price": "100", "plan": dict(PLAN, opportunity_id="other")}}
        self.assertFalse(self.evaluate(trades=opened, account=account(open_position_count=9))["authorized"])

    def test_economic_baseline_cannot_silently_rebase(self):
        prior = self.evaluate()
        trade = {"state": "POSITION_CLOSED", "quantity": "1", "entry_price": "100", "plan": PLAN, "risk": prior}
        result = self.evaluate(trades={"t": trade}, account=account(cash_available=Decimal("11000")))
        self.assertIn("RISK_ACCOUNT_BASELINE_DRIFT", result["blockers"])

    def test_published_risk_binds_final_quantity_and_inputs(self):
        ten = self.evaluate(requested_quantity="10")
        eleven = self.evaluate(requested_quantity="11")
        self.assertNotEqual(ten["risk_decision_id"], eleven["risk_decision_id"])
        self.assertEqual("10", ten["quantity"])
        self.assertGreater(Decimal(ten["allocator_maximum_quantity"]), Decimal(ten["quantity"]))


class NativeStoreTests(unittest.TestCase):
    def test_atomic_audit_and_binding(self):
        with tempfile.TemporaryDirectory() as root:
            store = NativePaperStore(Path(root), binding={"environment": ENVIRONMENT})
            state, _ = store.load()
            event = ExecutionLedgerEvent("e1", NOW.isoformat(), "audit", ENVIRONMENT,
                                         "TEST", "plan-1", "risk-1", PROVIDER,
                                         "OFFLINE_ONLY", "intent", "DISABLED", "ENGINE", "TEST")
            store.commit(state, event)
            self.assertEqual(state, store.load()[0])
            self.assertEqual("e1", store.load()[1][0]["event"]["event_id"])
            with self.assertRaisesRegex(NativePaperError, "BINDING_DRIFT"):
                NativePaperStore(Path(root), binding={"environment": "LIVE"}).load()

    def test_tampered_or_missing_transaction_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            store = NativePaperStore(Path(root), binding={})
            (Path(root) / "00000001.json").write_text('{"bad":true}', encoding="ascii")
            with self.assertRaises(NativePaperError):
                store.load()

    def test_partial_write_not_committed(self):
        with tempfile.TemporaryDirectory() as root:
            store = NativePaperStore(Path(root), binding={})
            (Path(root) / ".failed.partial").write_bytes(b"interrupted")
            self.assertEqual([], store.load()[1])


if __name__ == "__main__":
    unittest.main()
