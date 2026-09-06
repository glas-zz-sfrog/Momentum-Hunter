"""Dormant Product-class admission proofs; synthetic upstream results only."""
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import json
import unittest
from unittest.mock import Mock, patch

from tests import continuous_admission_fixtures as fixtures
from tests import test_lifecycle_position_identity as lineage_fixture
from tests import test_shadow_trading as opening_fixture
from momentum_hunter import continuous_operational_admission as admission
from momentum_hunter import modern_operational as modern
from momentum_hunter import lifecycle_position_identity as identity
from momentum_hunter import shadow_trading as shadow
from momentum_hunter.alpaca_paper_engineering import AlpacaPaperEngineeringEngine
from momentum_hunter.provider_neutral_allocation import AllocationStatus


def mu_market(method):
    class MuMarket(fixtures.EligibleMarket):
        fixture_symbol = "MU"
    return MuMarket(method)


class ContinuousAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.f = lineage_fixture.ModernLifecyclePositionTests("test_shared_binding_roundtrip")
        self.f.market_fixture_factory = mu_market
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.epoch, self.decision = self.f.epoch, self.f.decision
        self.results = fixtures.strategy_results(self.decision, self.epoch)
        self.when = self.results[0].decision_at
        self.paper = AlpacaPaperEngineeringEngine(adapter=Mock(), quote_source=Mock(),
            output_directory=Path(self.epoch.root) / "paper")

    def publish(self, *, decision=None, results=None):
        risk, request, allocation = results or self.results
        return admission.publish_strategy_result(decision=decision or self.decision,
            epoch=self.epoch, risk=risk, request=request, allocation=allocation, recorded_at=risk.decision_at)

    def admit(self, strategy=None):
        return admission.admit_continuous(epoch=self.epoch,
            strategy_snapshot=strategy or self.publish(), admitted_at=self.when)

    def intent(self, accepted=None):
        return self.paper.prepare_continuous_entry(accepted or self.admit(), epoch=self.epoch, recorded_at=self.when)

    def test_01_to_07_exact_chain_and_no_replacement_plan_id(self):
        accepted = self.admit()
        carried, record, risk, request, allocation, _ = accepted.validate(self.epoch)
        self.assertEqual(carried, self.decision)
        self.assertEqual(record.trade_plan_id, self.decision.trade_plan_id)
        self.assertFalse(record.trade_plan_id.startswith("tp-"))
        self.assertEqual((risk, request, allocation), self.results)
        for consumer in ("SHADOW", "PAPER"):
            intent = admission.prepare_continuous_intent(accepted, self.epoch, consumer=consumer, recorded_at=self.when)
            self.assertEqual(intent.validate(self.epoch, consumer=consumer)[1][0], self.decision)
            body = json.loads(intent.snapshot.component("intent"))
            self.assertNotEqual(body["localOrderId"], record.trade_plan_id)
        self.assertEqual(json.loads(accepted.snapshot.manifest_bytes)["operationalEpochId"], self.epoch.epoch_id)

    def test_duplicate_shadow_order_or_larger_size_cannot_reuse_admission(self):
        accepted = self.admit()
        broker = shadow.ProspectiveFakeBroker(shadow.ShadowExecutionPolicy(slippage_bps=0))
        _, order = broker.prepare_modern_entry(accepted, epoch=self.epoch, submitted_at=self.when)
        quote = shadow.ShadowQuote("MU", "2026-08-17T11:21:20-04:00", order.limit_price-.01,
                                   order.limit_price, order.limit_price, available_size=2)
        for altered in (replace(order, order_id="duplicate"), replace(order, quantity=order.quantity+1)):
            with self.assertRaises(ValueError):
                broker.fill_modern_entry(altered, quote, decision=self.decision, epoch=self.epoch,
                    received_at=datetime.fromisoformat(quote.timestamp), committed_notional=0,
                    open_position_count=0, realized_pnl_today=0, admission=accepted)

    def test_19_risk_rejected_identity_valid_creates_no_intent_or_position(self):
        rejected = fixtures.strategy_results(self.decision, self.epoch, blocked=True)
        self.decision.validate(self.epoch)
        with self.assertRaisesRegex(ValueError, "RISK_BLOCKED"):
            self.admit(self.publish(results=rejected))
        for kind in ("CONTINUOUS_ADMISSION", "CONTINUOUS_INTENT", "POSITION", "CONTINUOUS_FILL"):
            self.assertIsNone(modern.SnapshotPublication(self.epoch, kind).current())
        self.assertFalse(self.paper.adapter.mock_calls)

    def test_allocation_rejection_cannot_be_overridden_by_identity(self):
        risk, request, allocation = self.results
        blocked = replace(allocation, status=AllocationStatus.BLOCKED,
                          blockers=("SYNTHETIC_EXPOSURE_LIMIT",), final_authorized_quantity=Decimal("0"))
        with self.assertRaisesRegex(ValueError, "RISK_BLOCKED"):
            self.admit(self.publish(results=(risk, request, blocked)))

    def test_20_accepted_risk_invalid_identity_creates_no_order(self):
        for key in ("opportunity_id", "setup_id", "trade_plan_id", "producer_record_id"):
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.publish(decision=replace(self.decision, **{key: "f" * 64}))
        self.assertIsNone(modern.SnapshotPublication(self.epoch, "STRATEGY_DECISION").current())
        self.assertFalse(self.paper.adapter.mock_calls)

    def test_21_risk_sizing_and_economics_round_trip_exactly(self):
        for quantity in (1, 2, 5):
            upstream = fixtures.strategy_results(self.decision, self.epoch, quantity=quantity)
            before = [value.fingerprint for value in upstream]
            accepted = self.admit(self.publish(results=upstream))
            carried = accepted.validate(self.epoch)[2:5]
            self.assertEqual(upstream, carried)
            self.assertEqual(before, [value.fingerprint for value in carried])
            self.assertEqual(carried[2].final_authorized_quantity, quantity)
            self.assertEqual(upstream[2].to_dict(), carried[2].to_dict())
            self.assertEqual(upstream[0].to_dict(), carried[0].to_dict())
            self.assertEqual(upstream[1].stop_price, carried[1].stop_price)
            self.assertEqual(upstream[1].target_price, carried[1].target_price)

    def test_risk_and_allocator_are_not_called_by_admission(self):
        with patch("momentum_hunter.paper_risk_governor.evaluate_paper_candidate", side_effect=AssertionError("risk recomputed")), \
             patch("momentum_hunter.provider_neutral_allocation.allocate_provider_neutral_position", side_effect=AssertionError("size recomputed")):
            self.intent().validate(self.epoch, consumer="PAPER")

    def test_later_risk_rejection_revokes_new_entry_not_owned_recovery(self):
        original = self.publish()
        accepted = self.admit(original)
        intent = self.intent(accepted)
        self.publish(results=fixtures.strategy_results(self.decision, self.epoch, blocked=True))
        with self.assertRaises(ValueError):
            self.admit(original)
        with self.assertRaises(ValueError):
            self.intent(accepted)
        self.assertEqual(intent.validate(self.epoch, consumer="PAPER")[1][0], self.decision)

    def test_review_f1_strategy_owner_replay_is_idempotent_without_resurrection(self):
        original = self.publish()
        accepted = self.admit(original)
        intent = self.intent(accepted)
        broker = shadow.ProspectiveFakeBroker(shadow.ShadowExecutionPolicy())
        _, order = broker.prepare_modern_entry(accepted, epoch=self.epoch, submitted_at=self.when)
        replay = self.publish()
        self.assertEqual(replay, original)
        repeated = self.admit(replay)
        self.assertEqual(repeated, accepted)
        self.assertEqual(self.intent(repeated), intent)
        self.assertEqual(broker.prepare_modern_entry(repeated, epoch=self.epoch, submitted_at=self.when)[1], order)
        blocked = self.publish(results=fixtures.strategy_results(self.decision, self.epoch, blocked=True))
        self.assertEqual(self.publish(), original)
        self.assertEqual(modern.SnapshotPublication(self.epoch, "STRATEGY_DECISION").current(), blocked)
        with self.assertRaises(ValueError):
            self.admit(original)

    def test_12_wrong_epoch_rejected(self):
        accepted = self.admit()
        with self.assertRaises(ValueError):
            accepted.validate(replace(self.epoch, epoch_id="f" * 64))

    def test_13_missing_epoch_rejected(self):
        accepted = self.admit()
        authority = self.f.fixture.fixture.path
        authority.unlink()
        with self.assertRaises(ValueError):
            accepted.validate(self.epoch)

    def test_14_wrong_snapshot_identity_rejected(self):
        wire = self.admit().wire()
        wire["admissionId"] = "f" * 64
        with self.assertRaises(ValueError):
            admission.admission_from_wire(wire, self.epoch)

    def test_15_mutated_snapshot_rejected(self):
        accepted = self.admit()
        altered = replace(accepted.snapshot, components=accepted.snapshot.components + (("extra", b"{}"),))
        with self.assertRaises(ValueError):
            admission.ContinuousOperationalAdmission(altered).validate(self.epoch)

    def test_16_legacy_or_stripped_contract_rejected(self):
        wire = self.admit().wire()
        for value in ({}, {"symbol": "MU"}, {"schemaVersion": 2},
                      {key: val for key, val in wire.items() if key != "profile"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                admission.admission_from_wire(value, self.epoch)

    def test_22_23_restart_preserves_exact_intent_without_regeneration(self):
        accepted = self.admit()
        intent = self.intent(accepted)
        raw = intent.snapshot.to_bytes()
        with patch("momentum_hunter.autonomy.view_models.stable_trade_plan_id", side_effect=AssertionError("replacement ID")):
            recovered = self.paper.recover_continuous_entry(raw, epoch=self.epoch,
                                                          expected_intent_id=intent.snapshot.snapshot_id)
            self.assertEqual(recovered, intent)
            self.assertEqual(recovered.validate(self.epoch, consumer="PAPER")[1][0], self.decision)
        self.assertEqual(self.intent(accepted), intent)
        self.assertEqual(self.admit(modern.SnapshotPublication(self.epoch, "STRATEGY_DECISION").current()), accepted)

    def test_26_same_path_changed_bytes_rejected(self):
        strategy = self.publish()
        path = modern.SnapshotPublication(self.epoch, "STRATEGY_DECISION").root / (strategy.snapshot_id + ".json")
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            self.admit(strategy)

    def test_27_28_valid_b_c_cannot_substitute_after_evaluation(self):
        strategy = self.publish()
        components = strategy.components
        original_publish = modern.SnapshotPublication.publish
        observed = []
        def attack(publication, snapshot, **kwargs):
            if publication.kind == "CONTINUOUS_ADMISSION":
                raw = snapshot.component("strategySnapshot")
                self.assertEqual(raw, strategy.to_bytes())
                for spaces in (1, 2):
                    manifest = json.loads(strategy.manifest_bytes)
                    substitute = modern.freeze_snapshot(self.epoch, kind="STRATEGY_DECISION",
                        components=(("strategyResult", components[0][1] + b" " * spaces),),
                        sequence=manifest["sequence"], predecessor=manifest["predecessorSnapshotId"],
                        created_at=manifest["createdAt"], known_at=manifest["knownAt"],
                        decision_cutoff=manifest["decisionCutoff"])
                    admission._strategy_parts(substitute, self.epoch, current_decision=True)
                    self.assertNotEqual(substitute.snapshot_id, strategy.snapshot_id)
                    path = modern.SnapshotPublication(self.epoch, "STRATEGY_DECISION").root / (strategy.snapshot_id + ".json")
                    path.write_bytes(substitute.to_bytes())
                    self.assertEqual(snapshot.component("strategySnapshot"), strategy.to_bytes())
                    observed.append(spaces)
            return original_publish(publication, snapshot, **kwargs)
        with patch.object(modern.SnapshotPublication, "publish", attack):
            accepted = self.admit(strategy)
        self.assertEqual(observed, [1, 2])
        with self.assertRaises(ValueError):
            self.intent(accepted)
        self.assertEqual(accepted.snapshot.component("strategySnapshot"), strategy.to_bytes())

    def test_29_nested_risk_or_producer_identity_mutation_rejected(self):
        risk, request, allocation = self.results
        mutations = ((replace(risk, trade_plan_id="f" * 64), request, allocation),
            (risk, replace(request, stop_price=request.stop_price - 1), allocation),
            (risk, request, replace(allocation, request_fingerprint="f" * 64)),
            (replace(risk, setup_id="f" * 64), request, allocation))
        for values in mutations:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.publish(results=values)

    def test_30_nontransmitting_and_no_broker_or_quote_calls(self):
        intent = self.intent()
        body = json.loads(intent.snapshot.component("intent"))
        self.assertEqual(body["executionAuthority"], "NONE")
        self.assertEqual(body["orderCapability"], "UNAVAILABLE")
        self.assertFalse(self.paper.adapter.mock_calls)
        self.assertFalse(self.paper.quote_source.mock_calls)

    def test_paper_first_fill_exact_position_open_time_and_restart(self):
        intent = self.intent()
        first = modern.canonical_bytes({**json.loads(self.f.fill),
            "localOrderId": json.loads(intent.snapshot.component("intent"))["localOrderId"]})
        bound = self.paper.bind_continuous_first_fill(intent, epoch=self.epoch,
            first_fill=first, recorded_at=json.loads(first)["filledAt"])
        raw = bound.snapshot.to_bytes()
        recovered = admission.ContinuousFillLineage(modern.snapshot_from_bytes(raw, self.epoch,
            kind="CONTINUOUS_FILL", expected_id=bound.snapshot.snapshot_id))
        review = recovered.review(self.epoch, consumer="PAPER")
        self.assertEqual(review["positionId"], "native-position-1")
        self.assertEqual(review["openedAt"], json.loads(self.f.fill)["filledAt"])
        self.assertEqual(review["tradePlanId"], self.decision.trade_plan_id)
        self.assertEqual(review["linkageStatus"], "PROVEN")
        self.assertEqual(self.paper.bind_continuous_first_fill(intent, epoch=self.epoch,
            first_fill=first, recorded_at=json.loads(first)["filledAt"]), bound)
        with self.assertRaises(ValueError):
            self.paper.bind_continuous_first_fill(intent, epoch=self.epoch,
                first_fill=modern.canonical_bytes({**json.loads(first), "fillId": "replacement"}),
                recorded_at=json.loads(first)["filledAt"])
        self.assertFalse(self.paper.adapter.mock_calls)

    def test_opening_mu_coexists_and_cross_admission_fails(self):
        accepted = self.admit()
        opening = opening_fixture.ShadowTradingLifecycleTests()
        opening.setUp()
        self.addCleanup(opening.tearDown)
        def symbol(value):
            if isinstance(value, dict):
                return {key: symbol(item) for key, item in value.items()}
            if isinstance(value, list):
                return [symbol(item) for item in value]
            return "MU" if value == "TEST" else value
        payload = symbol(opening_fixture.report_payload())
        opening_fixture.bind_setup_identity(payload["candidates"][0])
        payload["top_5_for_capital"] = payload["candidates"]
        opening.report_path.write_text(json.dumps(payload), encoding="ascii")
        trade = opening.start(symbol="MU")
        self.assertEqual(trade.symbol, "MU")
        self.assertEqual(trade.status, "pending_entry", trade.last_reason)
        self.assertTrue(trade.trade_plan_id.startswith("tp-"))
        self.assertNotEqual(trade.trade_plan_id, self.decision.trade_plan_id)
        self.assertEqual(self.intent(accepted).validate(self.epoch, consumer="PAPER")[1][0], self.decision)
        with self.assertRaises(ValueError):
            self.paper.prepare_continuous_entry(trade, epoch=self.epoch, recorded_at=self.when)
        with self.assertRaises((TypeError, ValueError, AttributeError)):
            opening.service().start_trade(accepted, symbol="MU", simulation_command_id="cross")

    def test_wrong_consumer_and_expired_plan_denied(self):
        accepted = self.admit()
        intent = self.intent(accepted)
        with self.assertRaises(ValueError):
            intent.validate(self.epoch, consumer="SHADOW")
        with self.assertRaises(ValueError):
            self.paper.prepare_continuous_entry(accepted, epoch=self.epoch,
                                                recorded_at="2026-08-17T15:00:00-04:00")

    def test_08_same_symbol_two_native_opportunities_admit_exact_b(self):
        # Native opportunity identity is (symbol, session, evidence family).
        # Two sessions produce OA/OB honestly; no invented/relabelled identities.
        original_at = fixtures.native.at
        def next_session(*args):
            return original_at(*args) + timedelta(days=1)
        with patch.object(fixtures.native, "SESSION", "2026-08-18"), patch.object(fixtures.native, "at", next_session):
            other = mu_market("test_natural_setup_owner_has_no_broker_account_or_order_capability")
            other.setUp()
            self.addCleanup(other.doCleanups)
            when = next_session(11, 21)
            other._prepare(when, generation=2)
            source = fixtures.native.LiveCompositionSource(other.state, operational_epoch=self.epoch)
            source.compose(other._request(when, generation=2))
        snapshot = source.natural_setup.snapshot_publication.current()
        records = source.producer_store.load()
        b_record = next(record for record in reversed(records)
            if record.trade_plan_id and record.member_id == other.member.member_id)
        b = identity.ModernDecisionIdentity(snapshot, b_record.opportunity_id, b_record.setup_id,
            b_record.trade_plan_id, b_record.record_id, b_record.fingerprint)
        a = replace(self.decision, snapshot=snapshot)
        a.validate(self.epoch)
        b.validate(self.epoch)
        self.assertEqual(a.validate(self.epoch).symbol, "MU")
        self.assertEqual(b_record.symbol, "MU")
        for key in ("opportunity_id", "setup_id", "trade_plan_id"):
            self.assertNotEqual(getattr(a, key), getattr(b, key))
        risk, request, allocated = fixtures.strategy_results(b, self.epoch, when="2026-08-18T11:21:01-04:00")
        accepted = admission.admit_continuous(epoch=self.epoch,
            strategy_snapshot=admission.publish_strategy_result(decision=b, epoch=self.epoch,
                risk=risk, request=request, allocation=allocated, recorded_at=risk.decision_at),
            admitted_at=risk.decision_at)
        for consumer in ("SHADOW", "PAPER"):
            intent = admission.prepare_continuous_intent(accepted, self.epoch, consumer=consumer,
                                                        recorded_at=risk.decision_at)
            self.assertEqual(intent.validate(self.epoch, consumer=consumer)[1][0], b)
        with self.assertRaises(ValueError):
            replace(b, trade_plan_id=a.trade_plan_id).validate(self.epoch)


if __name__ == "__main__":
    unittest.main()
