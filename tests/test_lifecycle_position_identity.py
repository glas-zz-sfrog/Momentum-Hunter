"""Current modern linkage only. Legacy inspection never returns an admission."""
from dataclasses import replace
import json
import unittest

from tests import test_modern_snapshot_publication as fixture_module
from momentum_hunter import lifecycle_position_identity as identity
from momentum_hunter import modern_operational as modern


def current_market_fixture(method):
    native = fixture_module.fixture_module

    class CurrentMarket(native.ContinuousNaturalSetupTests):
        def _append_initial_sequence(self):
            bars = [native.SchwabMinuteCandle(symbol="AAA", timestamp=native.at(11, minute),
                open=99.9, high=100.0, low=99.8, close=99.9, volume=100.0,
                source=native.SCHWAB_PRICE_HISTORY_SOURCE) for minute in range(20)]
            bars.append(native.SchwabMinuteCandle(symbol="AAA", timestamp=native.at(11, 20),
                open=100.01, high=100.08, low=100.0, close=100.05, volume=200.0,
                source=native.SCHWAB_PRICE_HISTORY_SOURCE))
            native.SchwabCandleStore(self.minute_root).append_history(tuple(bars), received_at=native.at(11, 21))

    return CurrentMarket(method)


class ModernLifecyclePositionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.ModernSnapshotPublicationTests(
            "test_06_13_natural_schema3_uses_historical_market_context_not_old_decisions")
        self.fixture.market_fixture_factory = getattr(self, "market_fixture_factory", current_market_fixture)
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source, self.result = self.fixture.compose()
        self.epoch = self.fixture.fixture.epoch
        self.snapshot = self.source.natural_setup.snapshot_publication.current()
        records = self.source.producer_store.load()
        self.record = next(record for record in reversed(records) if record.trade_plan_id)
        self.decision = identity.ModernDecisionIdentity(self.snapshot,
            self.record.opportunity_id, self.record.setup_id, self.record.trade_plan_id,
            self.record.record_id, self.record.fingerprint)
        self.fill = modern.canonical_bytes({"schemaVersion": 1, **self.epoch.wire(),
            "opportunity_id": self.record.opportunity_id, "setup_id": self.record.setup_id,
            "trade_plan_id": self.record.trade_plan_id, "positionId": "native-position-1",
            "fillId": "native-first-fill-1", "filledAt": "2026-08-17T11:21:20.123456-04:00",
            "filledQuantity": 1, "snapshotId": self.snapshot.snapshot_id})

    def test_32_modern_plan_without_position_is_unavailable_not_proven(self):
        result = identity.review_linkage(self.decision, self.epoch)
        self.assertEqual(result["linkageStatus"], "UNAVAILABLE")
        self.assertIsNone(result["positionId"])
        self.assertEqual(result["tradePlanId"], self.record.trade_plan_id)

    def test_33_modern_position_preserves_exact_first_fill_identity(self):
        position = identity.bind_first_fill(self.decision, self.epoch, first_fill=self.fill)
        result = identity.review_linkage(self.decision, self.epoch, position=position, first_fill=self.fill)
        self.assertEqual(result["linkageStatus"], "PROVEN")
        self.assertEqual(result["positionId"], "native-position-1")
        self.assertEqual(result["openedAt"], "2026-08-17T11:21:20.123456-04:00")

    def test_29_30_tampered_position_and_opened_at_rejected(self):
        position = identity.bind_first_fill(self.decision, self.epoch, first_fill=self.fill)
        for mutated in (replace(position, position_id="replacement"),
                        replace(position, opened_at="2026-08-17T11:22:00-04:00")):
            with self.subTest(position=mutated.position_id, opened=mutated.opened_at):
                with self.assertRaises(modern.ModernOperationalError):
                    identity.review_linkage(self.decision, self.epoch, position=mutated, first_fill=self.fill)

    def test_partial_fill_restart_preserves_first_fill_not_later_fill(self):
        position = identity.bind_first_fill(self.decision, self.epoch, first_fill=self.fill)
        recovered = identity.bind_first_fill(self.decision, self.epoch, first_fill=self.fill, prior=position)
        self.assertEqual(recovered, position)
        second_fill = modern.canonical_bytes({**json.loads(self.fill),
            "fillId": "second-fill", "filledQuantity": 2,
            "filledAt": "2026-08-17T11:22:00-04:00"})
        with self.assertRaises(modern.ModernOperationalError):
            identity.bind_first_fill(self.decision, self.epoch, first_fill=second_fill, prior=position)

    def test_25_26_31_same_symbol_does_not_override_exact_chain_or_successor(self):
        self.decision.validate(self.epoch)
        for field in ("opportunity_id", "setup_id", "trade_plan_id", "producer_record_fingerprint"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    replace(self.decision, **{field: "f" * 64}).validate(self.epoch)

    def test_02_03_11_legacy_or_stripped_binding_never_gets_operational_admission(self):
        for value in ({}, {"schemaVersion": 2}, {"symbol": self.record.symbol},
                      {key: val for key, val in self.decision.wire().items() if key != "setup_id"}):
            with self.subTest(keys=tuple(value)):
                with self.assertRaises(ValueError):
                    identity.decision_from_wire(value, self.epoch, expected_snapshot_id=self.snapshot.snapshot_id)
        self.assertEqual(identity.review_linkage(None, None, historical=True)["linkageStatus"], "LEGACY_UNBOUND")
        self.assertEqual(identity.review_linkage(None, None)["linkageStatus"], "UNKNOWN")

    def test_shared_binding_roundtrip(self):
        wire = json.loads(modern.canonical_bytes(self.decision.wire()))
        restored = identity.decision_from_wire(wire, self.epoch,
                                               expected_snapshot_id=self.snapshot.snapshot_id)
        self.assertEqual(restored, self.decision)
