"""Real Product classes, entirely synthetic cutover, orders, quotes and fills."""
from dataclasses import replace
from datetime import datetime
from pathlib import Path
import json
import unittest
from unittest.mock import Mock

from tests import test_lifecycle_position_identity as fixtures
from momentum_hunter import modern_operational as modern
from momentum_hunter import shadow_trading as shadow
from momentum_hunter.alpaca_paper_engineering import AlpacaPaperEngineeringEngine
from tests.continuous_admission_fixtures import eligible_market_fixture, approved_admission


class ModernOperationalHandoffTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ModernLifecyclePositionTests("test_shared_binding_roundtrip")
        self.f.market_fixture_factory = eligible_market_fixture
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.epoch, self.decision = self.f.epoch, self.f.decision
        self.record = self.decision.validate(self.epoch)
        self.admission = approved_admission(self.decision, self.epoch)
        self.plan = next(item for item in json.loads(self.record.payload_json)["compositionCycle"]["member_results"]
                         if item["universe_member_id"] == self.record.member_id)["intraday_plan"]
        self.broker = shadow.ProspectiveFakeBroker(shadow.ShadowExecutionPolicy(slippage_bps=0))
        self.intent, self.order = self.broker.prepare_modern_entry(self.admission, epoch=self.epoch,
                                                                 submitted_at="2026-08-17T11:21:01-04:00")
        self.quote = shadow.ShadowQuote(self.record.symbol, "2026-08-17T11:21:20.123456-04:00",
            self.plan["planned_entry"] - 0.01, self.plan["planned_entry"], self.plan["planned_entry"], available_size=1)
        self.paper = AlpacaPaperEngineeringEngine(adapter=Mock(), quote_source=Mock(),
            output_directory=Path(self.epoch.root) / "paper")

    def fill(self, *, order=None, quote=None, prior=None, decision=None):
        quote = quote or self.quote
        return self.broker.fill_modern_entry(order or self.order, quote,
            decision=decision or self.decision, epoch=self.epoch,
            received_at=datetime.fromisoformat(quote.timestamp), committed_notional=0,
            open_position_count=0, realized_pnl_today=0, prior=prior, admission=self.admission)

    def test_native_fakebroker_first_fill_persists_exact_upstream_position_and_opened_at(self):
        order, fill, reason = self.fill()
        self.assertEqual(reason, "")
        self.assertIsNotNone(fill)
        self.assertEqual(order.filled_quantity, 1)
        self.assertEqual(fill.position.position_id, shadow.stable_id("shadow-position", self.order.shadow_trade_id))
        self.assertEqual(fill.position.opened_at, self.quote.timestamp)
        store = shadow.ModernShadowPositionStore(self.epoch)
        snapshot_id = store.save(fill, expected_previous=None, recorded_at=self.quote.timestamp)
        rows, restored_id = shadow.ModernShadowPositionStore(self.epoch).load()
        self.assertEqual(restored_id, snapshot_id)
        self.assertEqual(rows, (fill,))

    def test_partial_fill_restart_and_idempotency_keep_first_position_identity(self):
        _, fill, _ = self.fill()
        store = shadow.ModernShadowPositionStore(self.epoch)
        initial = store.save(fill, expected_previous=None, recorded_at=self.quote.timestamp)
        recovered, previous = shadow.ModernShadowPositionStore(self.epoch).load()
        quote = replace(self.quote, timestamp="2026-08-17T11:21:30-04:00")
        order, second, _ = self.fill(order=recovered[0].order, quote=quote, prior=recovered[0])
        self.assertEqual(order.filled_quantity, 2)
        self.assertEqual(second.identity, fill.identity)
        self.assertEqual(second.position.opened_at, self.quote.timestamp)
        final = store.save(second, expected_previous=previous, recorded_at=quote.timestamp)
        self.assertNotEqual(final, initial)
        self.assertEqual(store.save(second, expected_previous=final, recorded_at=quote.timestamp), final)
        self.assertEqual(store.load()[0], (second,))

    def test_shadow_and_paper_share_exact_modern_admission(self):
        self.assertEqual(self.paper.admit_modern_decision(self.decision, epoch=self.epoch), self.decision)
        self.fill()
        for field in ("opportunity_id", "setup_id", "trade_plan_id"):
            changed = replace(self.decision, **{field: "f" * 64})
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.fill(decision=changed)
                with self.assertRaises(ValueError):
                    self.paper.admit_modern_decision(changed, epoch=self.epoch)
        self.assertFalse(self.paper.adapter.mock_calls)

    def test_legacy_paper_entry_and_restore_fail_before_any_provider_or_artifact_read(self):
        with self.assertRaises(modern.ModernOperationalError):
            self.paper.run_decision(Path("absent-report.json"), confirmation="any")
        with self.assertRaises(modern.ModernOperationalError):
            self.paper.reconcile_active()
        with self.assertRaises(modern.ModernOperationalError):
            self.paper._reconcile_one({}, Path("absent-outcome.json"), None)
        with self.assertRaises(modern.ModernOperationalError):
            self.paper._recover_intent(intent_path=Path("absent.json"), final_path=Path("absent.json"),
                cycle_id="old", policy=None, arm=None, report_sha="", receipts=[])
        self.assertFalse(self.paper.adapter.mock_calls)
        self.assertFalse(self.paper.quote_source.mock_calls)

    def test_legacy_shadow_quote_and_start_cannot_bypass_cutover_by_omitting_context(self):
        service = shadow.ShadowTradingService(store=shadow.ShadowStateStore(Path(self.epoch.root) / "legacy.json"))
        with self.assertRaises(modern.ModernOperationalError):
            service.start_trade(Path("missing.json"), symbol=self.record.symbol, simulation_command_id="legacy")
        with self.assertRaises(modern.ModernOperationalError):
            service.process_quote(self.quote)
        with self.assertRaises(modern.ModernOperationalError):
            service.process_missing_quote(self.record.symbol)
        # The native Opening economic primitive remains independently usable.
        self.broker.fill_entry(self.order, self.quote, received_at=datetime.fromisoformat(self.quote.timestamp),
            committed_notional=0, open_position_count=0, realized_pnl_today=0)

    def test_legacy_position_and_modern_position_tamper_rejected_without_reset(self):
        _, fill, _ = self.fill()
        store = shadow.ModernShadowPositionStore(self.epoch)
        identity = store.save(fill, expected_previous=None, recorded_at=self.quote.timestamp)
        before = store.publication.pointer.read_bytes()
        for altered in (fill.position, replace(fill, position=replace(fill.position, position_id="wrong")),
                        replace(fill, position=replace(fill.position, opened_at="2026-08-17T11:21:21-04:00"))):
            with self.assertRaises(ValueError):
                store.save(altered, expected_previous=identity, recorded_at=self.quote.timestamp)
            self.assertEqual(before, store.publication.pointer.read_bytes())

    def test_position_snapshot_cannot_predate_fill_or_latest_order_update(self):
        _, fill, _ = self.fill()
        store = shadow.ModernShadowPositionStore(self.epoch)
        with self.assertRaises(modern.ModernOperationalError):
            store.save(fill, expected_previous=None, recorded_at=self.epoch.not_before)
        self.assertIsNone(store.publication.current())

    def test_review_f2_restored_order_identity_is_bound_before_first_save(self):
        _, fill, _ = self.fill()
        store = shadow.ModernShadowPositionStore(self.epoch)
        for changed in (replace(fill.order, order_id="rebound-order"),
                        replace(fill.order, shadow_trade_id="rebound-trade")):
            altered = replace(fill, order=changed)
            with self.subTest(order=changed.order_id):
                with self.assertRaises(ValueError):
                    altered.validate(self.epoch)
                with self.assertRaises(ValueError):
                    store.save(altered, expected_previous=None, recorded_at=self.quote.timestamp)
                self.assertIsNone(store.publication.current())


if __name__ == "__main__":
    unittest.main()
