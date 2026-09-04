"""Offline Product-path proof; inputs are candles, never injected identity bindings."""

import ast
import hashlib
import json
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.continuous_composition import CompositionMemberInput, ContinuousCompositionPolicy
from momentum_hunter.continuous_live_qualification import LiveCompositionSource
from momentum_hunter.continuous_tradeplan_producer import (
    ContinuousTradePlanProducerError,
    ContinuousTradePlanProducerStore,
    build_current_market_evidence, inspect_historical_context,
)
from momentum_hunter.lifecycle_position_identity import (
    REPORT_IDENTITY_FIELD,
    authoritative_lifecycle_identity_from_report_row,
)
from momentum_hunter.schwab_candle_contract import SCHWAB_PRICE_HISTORY_SOURCE, SchwabMinuteCandle
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.schwab_daily_candle_store import SchwabDailyCandleStore
from momentum_hunter.schwab_candle_contract import SchwabDailyCandle
from momentum_hunter.shadow_trading import (
    ShadowExecutionPolicy, ShadowStateStore, ShadowTradingService,
    shadow_identity_linkage_status,
)
from tests import test_continuous_natural_setup as natural
from tests import test_continuous_tradeplan_producer as producer


class ProducerShadowProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = natural.ContinuousNaturalSetupTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = LiveCompositionSource(self.fixture.state)

    def compose(self, cutoff, generation):
        self.fixture._prepare(cutoff, generation=generation)
        return self.source.compose(self.fixture._request(cutoff, generation=generation))

    def successor(self):
        SchwabCandleStore(self.fixture.minute_root).append_history((SchwabMinuteCandle(
            symbol="AAA", timestamp=natural.at(11, 21), open=100.1, high=100.15,
            low=100.03, close=100.05, volume=100.0, source=SCHWAB_PRICE_HISTORY_SOURCE,
        ),), received_at=natural.at(11, 22))
        return self.compose(natural.at(11, 22), 2)

    def test_natural_product_persists_bound_rows_and_shadow_consumes_exact_chain(self):
        initial = self.compose(natural.at(11, 21), 1)
        result = self.successor()
        store = self.source.producer.store
        records = store.load()
        document = json.loads(store.path.read_text())
        rows = document["candidates"]
        self.assertGreater(len(rows), 0)
        emitted = [item["producerBoundReportRow"]
                   for output in (initial, result)
                   for item in json.loads(output.evidence_payload_json)["naturalSteps"]
                   if item["producerBoundReportRow"] is not None]
        self.assertEqual(rows, emitted)
        # Every row was produced by the normal composition transaction, not this test.
        row = rows[-1]
        identity = authoritative_lifecycle_identity_from_report_row(row)
        record = next(item for item in records if item.record_id == identity.producer_record_id)
        self.assertEqual(record.fingerprint, identity.producer_record_fingerprint)
        lifecycle = self.source.natural_setup.lifecycle.snapshot(identity.opportunity_id)
        self.assertEqual(lifecycle.current_setup_id, identity.setup_id)
        persisted_plan = json.loads(record.payload_json)["compositionCycle"]["member_results"][0]["intraday_plan"]
        self.assertEqual(persisted_plan, row["trade_plan"]["intraday_evidence"])
        state_path = self.fixture.root / "shadow-state.json"
        service = ShadowTradingService(store=ShadowStateStore(state_path), policy=ShadowExecutionPolicy())
        # Select a unique plan triple from the actual store population.
        selected = next(candidate for candidate in rows if sum(
            other["trade_plan_id"] == candidate["trade_plan_id"] for other in rows) == 1)
        bound = authoritative_lifecycle_identity_from_report_row(selected)
        trade = service.start_trade(
            store.path, symbol=selected["symbol"], simulation_command_id="natural-provenance",
            decision_at=natural.at(11, 22), opportunity_id=bound.opportunity_id,
            setup_id=bound.setup_id, authoritative_trade_plan_id=bound.trade_plan_id,
        )
        self.assertEqual((bound.opportunity_id, bound.setup_id, bound.trade_plan_id),
                         (trade.opportunity_id, trade.setup_id, trade.trade_plan_id))
        self.assertIsNone(trade.position)
        self.assertEqual("UNAVAILABLE", shadow_identity_linkage_status(trade))
        self.assertIn("RESEARCH_ONLY", selected["trade_plan"]["blocking_reasons"])
        self.assertIsNone(selected["trade_plan"]["estimated_shares_for_500"])
        restored = ShadowStateStore(state_path).load().trades[0]
        self.assertEqual(trade, restored)
        self.assertEqual(records, ContinuousTradePlanProducerStore(store.path).load())

    def test_ongoing_setup_without_proposal_retains_identity_and_restarts_once(self):
        self.compose(natural.at(11, 21), 1)
        store = self.source.producer.store
        before = store.load()
        lifecycle = self.source.natural_setup.lifecycle.snapshot(before[-1].opportunity_id)
        result = self.compose(natural.at(11, 21), 2)
        records = store.load()
        last = records[-1]
        self.assertGreater(len(records), len(before))
        steps = json.loads(result.evidence_payload_json)["naturalSteps"]
        self.assertIsNone(steps[-1]["producerRecord"]["compositionCycle"]["member_results"][0]["lifecycle_proposal"])
        self.assertEqual((lifecycle.opportunity_id, lifecycle.current_setup_id),
                         (last.opportunity_id, last.setup_id))
        self.assertEqual(lifecycle.opportunity_id, json.loads(last.payload_json)["lifecycleSnapshot"]["opportunity_id"])
        self.source = LiveCompositionSource(self.fixture.state)
        self.compose(natural.at(11, 21), 2)
        self.assertEqual(records, self.source.producer.store.load())

    def test_successor_row_has_distinct_exact_setup_and_plan_binding(self):
        self.compose(natural.at(11, 21), 1)
        prior = json.loads(self.source.producer.store.path.read_text())["candidates"]
        SchwabCandleStore(self.fixture.minute_root).append_history((SchwabMinuteCandle(
            symbol="AAA", timestamp=natural.at(11, 21), open=100.1, high=100.15,
            low=100.03, close=100.05, volume=100.0, source=SCHWAB_PRICE_HISTORY_SOURCE,
        ),), received_at=natural.at(11, 22))
        self.compose(natural.at(11, 22), 2)
        current = json.loads(self.source.producer.store.path.read_text())["candidates"]
        self.assertEqual(prior, current[:len(prior)])
        new = current[len(prior)]
        self.assertEqual(prior[0]["opportunity_id"], new["opportunity_id"])
        self.assertNotEqual(prior[0]["setup_id"], new["setup_id"])
        self.assertNotEqual(prior[0]["trade_plan_id"], new["trade_plan_id"])

    def test_report_deletion_binding_or_economic_tamper_fails_reload(self):
        self.compose(natural.at(11, 21), 1)
        store = self.source.producer.store
        original = store.path.read_bytes()
        for mutation in ("missing_rows", "binding", "price"):
            with self.subTest(mutation=mutation):
                payload = json.loads(original)
                if mutation == "missing_rows":
                    payload.pop("candidates")
                elif mutation == "binding":
                    payload["candidates"][0][REPORT_IDENTITY_FIELD]["setup_id"] = "a" * 64
                else:
                    payload["candidates"][0]["trade_plan"]["bullish_entry"] += 1
                store.path.write_text(json.dumps(payload))
                with self.assertRaisesRegex(ContinuousTradePlanProducerError, "report rows"):
                    store.load()
                store.path.write_bytes(original)

    def test_product_binding_has_non_test_call_site(self):
        from momentum_hunter import continuous_tradeplan_producer as product
        tree = ast.parse(Path(product.__file__).read_text())
        callers = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name)
                   and node.func.id == "bind_report_row_to_producer_identity"]
        self.assertEqual(1, len(callers))

    def test_binding_failure_does_not_commit_any_authoritative_ledger(self):
        before = {path: path.read_bytes() for path in self.fixture.root.rglob("*.json")}
        with patch("momentum_hunter.continuous_tradeplan_producer.bind_report_row_to_producer_identity",
                   side_effect=ValueError("BOUND_ROW_SERIALIZATION_FAILED")):
            with self.assertRaisesRegex(ValueError, "BOUND_ROW_SERIALIZATION_FAILED"):
                self.compose(natural.at(11, 21), 1)
        self.assertEqual(before, {path: path.read_bytes() for path in self.fixture.root.rglob("*.json")})
        self.assertEqual((), self.source.producer.store.load())
        self.compose(natural.at(11, 21), 1)
        records = self.source.producer.store.load()
        self.source = LiveCompositionSource(self.fixture.state)
        self.compose(natural.at(11, 21), 1)
        self.assertEqual(records, self.source.producer.store.load())

    def test_pre_contract_record_is_not_retrospectively_bound(self):
        self.compose(natural.at(11, 21), 1)
        record = next(item for item in self.source.producer.store.load() if item.trade_plan_id)
        payload = json.loads(record.payload_json)
        payload.pop("reportRowContract")
        payload.pop("lifecycleSnapshot")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        legacy = replace(record, payload_json=encoded,
                         payload_fingerprint=hashlib.sha256(encoded.encode("ascii")).hexdigest())
        core = asdict(legacy)
        core.pop("record_id")
        core.pop("fingerprint")
        legacy = replace(legacy, fingerprint=hashlib.sha256((json.dumps(
            core, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")).hexdigest())
        path = self.fixture.root / "legacy-producer.json"
        path.write_text(json.dumps({"schemaVersion": legacy.schema_version,
                                   "profile": legacy.profile, "records": [asdict(legacy)]}))
        original = path.read_bytes()
        self.assertEqual((legacy,), ContinuousTradePlanProducerStore(path).load())
        self.assertEqual(original, path.read_bytes())
        from momentum_hunter.continuous_tradeplan_producer import producer_bound_report_row
        self.assertIsNone(producer_bound_report_row(legacy))


class ProducerOngoingIdentityTests(unittest.TestCase):
    def test_mu_population_from_product_selects_exact_b_in_either_order(self):
        fixture = producer.ContinuousTradePlanProducerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        state = producer.universe("MU")
        lifecycle = producer.LifecycleFixture(fixture.root, symbol="MU")
        # Only raw market/setup test inputs are supplied; Product issues all IDs and bindings.
        prior = [producer.at(11, 0).replace(day=day) for day in (11, 12, 13, 14)]
        SchwabCandleStore(fixture.minute_root).append_history(tuple(
            replace(fixture.minute_candle(timestamp, i), symbol="MU")
            for i, timestamp in enumerate((*prior, producer.at(11, 21)))
        ), received_at=producer.at(11, 22))
        SchwabDailyCandleStore(fixture.daily_root).append_history(tuple(
            SchwabDailyCandle(symbol="MU", timestamp=t.replace(hour=16), session_date=t.date().isoformat(),
                             open=90, high=92, low=89, close=91, volume=1000000,
                             source=SCHWAB_PRICE_HISTORY_SOURCE)
            for t in prior
        ), received_at=producer.at(11, 22))
        instance = fixture.producer()

        def evaluate(cutoff, successor, existing_plan=None):
            context, canonical = inspect_historical_context(
                minute_store_root=fixture.minute_root, daily_store_root=fixture.daily_root,
                symbol="MU", session_date=producer.SESSION, cutoff=cutoff, policy=fixture.policy,
            )
            return instance.evaluate(
                universe_state=state,
                member_input=CompositionMemberInput(
                    universe_member_id=state.members[0].member_id, canonical_evidence=canonical,
                    rvol_evidence=replace(fixture.rvol(cutoff), symbol="MU"),
                    lifecycle=lifecycle.snapshot, successor_setup=replace(successor, symbol="MU"),
                    existing_plan=existing_plan,
                ), history_context=context,
                current_market_evidence=build_current_market_evidence(
                    symbol="MU", provider_timestamp=cutoff.isoformat(), receipt_timestamp=cutoff.isoformat(),
                    source_identity="OFFLINE_MARKET_INPUT", market_payload={"symbol": "MU", "last": 106},
                ), instrument_admission=replace(fixture.instrument(), symbol="MU"),
                evidence_cutoff=cutoff, trigger="TEST_MARKET_INPUT",
            )

        a = evaluate(producer.at(11, 22), fixture.successor(known_at=producer.at(11, 21)))
        lifecycle.apply(a.member_result.lifecycle_proposal)
        lifecycle.miss_current(occurred_at=producer.at(11, 24))
        SchwabCandleStore(fixture.minute_root).append_history((
            replace(fixture.minute_candle(producer.at(11, 24), 6), symbol="MU"),
        ), received_at=producer.at(11, 25))
        b = evaluate(producer.at(11, 25), fixture.successor(
            known_at=producer.at(11, 24), family=producer.PULLBACK,
            predecessor=a.record.setup_id, terminal=producer.ENTRY_MISSED, generation=2,
        ), producer.transition_intraday_plan(a.member_result.intraday_plan,
                                              lifecycle_status=producer.PLAN_MISSED_ENTRY,
                                              observed_at=producer.at(11, 24)))
        document = json.loads(fixture.store_path.read_text())
        self.assertEqual(2, len(document["candidates"]))
        self.assertEqual(["MU", "MU"], [row["symbol"] for row in document["candidates"]])
        self.assertNotEqual(a.record.setup_id, b.record.setup_id)
        self.assertNotEqual(a.record.trade_plan_id, b.record.trade_plan_id)
        for reversed_rows in (False, True):
            with self.subTest(reversed_rows=reversed_rows):
                path = fixture.store_path
                if reversed_rows:
                    path = fixture.root / "reordered-report.json"
                    document["candidates"].reverse()
                    path.write_text(json.dumps(document))
                service = ShadowTradingService(
                    store=ShadowStateStore(fixture.root / f"shadow-{reversed_rows}.json"),
                    policy=ShadowExecutionPolicy(),
                )
                trade = service.start_trade(
                    path, symbol="MU", simulation_command_id="exact-b",
                    decision_at=producer.at(11, 25), opportunity_id=b.record.opportunity_id,
                    setup_id=b.record.setup_id, authoritative_trade_plan_id=b.record.trade_plan_id,
                )
                self.assertEqual((b.record.opportunity_id, b.record.setup_id, b.record.trade_plan_id),
                                 (trade.opportunity_id, trade.setup_id, trade.trade_plan_id))
                self.assertEqual(b.record.record_id, json.loads(trade.evidence.candidate_json)
                                 [REPORT_IDENTITY_FIELD]["producer_record_id"])
                self.assertIsNone(trade.position)

    def test_active_setup_identity_cannot_be_replaced_by_contradictory_snapshot(self):
        fixture = producer.ContinuousTradePlanProducerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        cutoff = producer.at(11, 22)
        fixture.seed_history()
        context, canonical = fixture.context(cutoff)
        instance = fixture.producer()
        first = instance.evaluate(
            universe_state=fixture.state,
            member_input=fixture.member_input(canonical, cutoff=cutoff, successor=fixture.successor(known_at=producer.at(11, 21))),
            history_context=context, current_market_evidence=fixture.current(cutoff),
            instrument_admission=fixture.instrument(), evidence_cutoff=cutoff, trigger="TEST",
        )
        fixture.lifecycle.apply(first.member_result.lifecycle_proposal)
        original = fixture.store_path.read_bytes()
        for changes in ({"opportunity_id": "a" * 64}, {"current_setup_id": "b" * 64},
                        {"updated_at": producer.at(11, 23).isoformat()}):
            with self.subTest(changes=changes):
                bad = replace(fixture.lifecycle.snapshot, **changes)
                with self.assertRaises(ContinuousTradePlanProducerError):
                    instance.evaluate(
                        universe_state=fixture.state,
                        member_input=fixture.member_input(canonical, cutoff=cutoff, lifecycle=bad),
                        history_context=context, current_market_evidence=fixture.current(cutoff, generation=2),
                        instrument_admission=fixture.instrument(), evidence_cutoff=cutoff, trigger="TEST",
                    )
                self.assertEqual(original, fixture.store_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
