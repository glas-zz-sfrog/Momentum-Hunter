"""Native Producer/lifecycle path with synthetic market data and cutover authority."""
from pathlib import Path
import tempfile
import unittest
import json
from dataclasses import replace
from unittest.mock import patch

from tests import test_continuous_natural_setup as fixture_module
from tests.test_modern_operational import EpochFixture
from momentum_hunter.continuous_tradeplan_producer import ContinuousTradePlanProducerStore
from momentum_hunter import continuous_natural_setup as natural
from momentum_hunter import modern_operational as modern


class ModernSnapshotPublicationTests(unittest.TestCase):
    def setUp(self):
        factory = getattr(self, "market_fixture_factory", fixture_module.ContinuousNaturalSetupTests)
        self.market = factory("test_natural_runtime_owns_missed_entry_and_distinct_pullback_successor")
        self.market.setUp()
        self.addCleanup(self.market.doCleanups)
        temporary = tempfile.TemporaryDirectory(prefix="mh-modern-")
        self.addCleanup(temporary.cleanup)
        self.fixture = EpochFixture(Path(temporary.name), configuration=fixture_module.CONFIGURATION)
        self.addCleanup(self.fixture.patch.stop)
        self.fixture.start()
        self.store = ContinuousTradePlanProducerStore(
            self.fixture.root / "state" / "continuous-tradeplan-producer.json",
            operational_epoch=self.fixture.epoch)
        self.store.initialize_modern()

    def compose(self):
        cutoff = fixture_module.at(11, 21)
        self.market._prepare(cutoff, generation=1)
        source = fixture_module.LiveCompositionSource(self.market.state,
                                                      operational_epoch=self.fixture.epoch)
        result = source.compose(self.market._request(cutoff, generation=1))
        return source, result

    def test_06_13_natural_schema3_uses_historical_market_context_not_old_decisions(self):
        source, result = self.compose()
        records = source.producer_store.load()
        self.assertTrue(records)
        self.assertTrue(all(item.schema_version == 3 for item in records))
        self.assertTrue(all(item.operational_epoch_id == self.fixture.epoch.epoch_id for item in records))
        self.assertTrue(all(item.opportunity_id for item in records))
        self.assertTrue(result.cycle_id)

    def test_14_22_exact_joint_snapshot_reaches_consumer(self):
        source, result = self.compose()
        payload = json.loads(result.evidence_payload_json)
        snapshot = modern.snapshot_from_bytes(payload["operationalSnapshot"].encode("ascii"),
            self.fixture.epoch, kind="COMPOSITION", expected_id=payload["operationalSnapshotId"])
        source.natural_setup.snapshot_publication.require_consumed(snapshot,
            expected_id=payload["operationalSnapshotId"])
        for name, path in source.natural_setup._authoritative_paths().items():
            self.assertEqual(path.read_bytes(), snapshot.component(name))

    def test_15_16_17_valid_modern_b_and_c_cannot_replace_evaluated_a(self):
        original = natural._replace_exact
        original_commit = natural.NaturalCompositionPreview.commit
        observations = []

        def attack(preview):
            a = preview.operational_snapshot
            self.assertIsNotNone(a)
            published = {}

            def replace_file(path, raw):
                original(path, raw)
                if path.name == natural._COMPOSITION_JOURNAL:
                    journal = json.loads(raw)
                    self.assertEqual(journal["operationalSnapshotId"], a.snapshot_id)
                    for name, staged in preview.staged_paths.items():
                        for indent in (2, 4):
                            b = (json.dumps(json.loads(a.component(name)), sort_keys=True,
                                            indent=indent) + "\n").encode("ascii")
                            self.assertNotEqual(a.component(name), b)
                            if name == "producer":
                                preview.producer_store.validate_bytes(b)
                            elif name == "candidateLifecycle":
                                natural.lifecycle_wire.validate_ledger(
                                    natural.lifecycle_wire.ledger_from_wire(json.loads(b)))
                            else:
                                natural.breakout_wire.validate_ledger(
                                    natural.breakout_wire.ledger_from_wire(json.loads(b)))
                            staged.write_bytes(b)
                    observations.append("VALID_MODERN_B_AND_C_STAGED")
                for name, target in preview.owner._authoritative_paths().items():
                    if path == target:
                        # Checked at the write boundary, not after rollback.
                        self.assertEqual(raw, a.component(name))
                        published[name] = raw

            with patch.object(natural, "_replace_exact", replace_file):
                original_commit(preview)
            self.assertEqual(set(published), set(preview.staged_paths))

        with patch.object(natural.NaturalCompositionPreview, "commit", attack):
            self.compose()
        self.assertEqual(observations, ["VALID_MODERN_B_AND_C_STAGED"])

    def test_19_consumer_refuses_another_valid_snapshot_identity(self):
        source, _ = self.compose()
        publication = source.natural_setup.snapshot_publication
        a = publication.current()
        components = tuple((name, raw + b" ") for name, raw in a.components)
        b = modern.freeze_snapshot(self.fixture.epoch, kind="COMPOSITION", components=components,
            sequence=1, predecessor=None, created_at="2026-08-17T11:21:00-04:00",
            known_at="2026-08-17T11:21:00-04:00", decision_cutoff="2026-08-17T11:21:00-04:00")
        source.natural_setup._validate_joint_snapshot(b)
        with self.assertRaises(modern.ModernOperationalError):
            publication.require_consumed(b, expected_id=a.snapshot_id)
        with self.assertRaises(modern.ModernOperationalError):
            publication.require_consumed(b, expected_id=b.snapshot_id)

    def test_valid_but_unrelated_breakout_generation_is_not_joint_authority(self):
        source, _ = self.compose()
        a = source.natural_setup.snapshot_publication.current()
        empty = natural.breakout_wire.SequentialBreakoutLedger(policy=source.natural_setup.breakout_policy)
        raw = natural.breakout_wire.canonical_json_bytes(natural.breakout_wire.ledger_to_wire(empty))
        components = tuple((name, raw if name == "sequentialBreakout" else value)
                           for name, value in a.components)
        manifest = modern.parse_bytes(a.manifest_bytes)
        b = modern.freeze_snapshot(self.fixture.epoch, kind="COMPOSITION", components=components,
            sequence=1, predecessor=None, created_at=manifest["createdAt"],
            known_at=manifest["knownAt"], decision_cutoff=manifest["decisionCutoff"])
        with self.assertRaises(modern.ModernOperationalError):
            source.natural_setup._validate_joint_snapshot(b)

    def test_23_restart_reconstructs_exact_published_current_snapshot(self):
        source, _ = self.compose()
        expected = source.natural_setup.snapshot_publication.current()
        restarted = fixture_module.LiveCompositionSource(self.market.state,
            operational_epoch=self.fixture.epoch)
        with restarted.natural_setup.preview() as preview:
            self.assertEqual(restarted.natural_setup.snapshot_publication.current(), expected)
            self.assertEqual(preview.original_payloads["producer"], expected.component("producer"))

    def test_24_restart_tampered_store_cannot_be_adopted(self):
        source, _ = self.compose()
        path = source.producer_store.path
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(natural.ContinuousNaturalSetupError, "disagree"):
            source.natural_setup.preview()

    def test_process_death_before_publication_rolls_back_all_joint_views_on_restart(self):
        original = natural._replace_exact
        original_producer = self.store.path.read_bytes()
        touched = []

        class Crash(BaseException):
            pass

        def crash(path, raw):
            original(path, raw)
            if path == self.store.path:
                touched.append(path)
                raise Crash()

        with patch.object(natural, "_replace_exact", crash):
            with self.assertRaises(Crash):
                self.compose()
        self.assertTrue(touched)
        self.assertTrue((self.store.path.parent / natural._COMPOSITION_JOURNAL).exists())
        restarted = fixture_module.LiveCompositionSource(self.market.state, operational_epoch=self.fixture.epoch)
        self.assertEqual(restarted.producer_store.path.read_bytes(), original_producer)
        self.assertIsNone(restarted.natural_setup.snapshot_publication.current())
        self.assertFalse(restarted.natural_setup.lifecycle.store.load().events)
        self.compose()
        records = self.store.load()
        self.assertEqual(len(records), len({record.record_id for record in records}))

    def test_process_death_after_publication_preparation_finishes_exact_commit_on_restart(self):
        original = modern._replace

        class Crash(BaseException):
            pass

        def crash(path, raw):
            original(path, raw)
            if path.name == "pending.json" and path.parent.name == "composition":
                raise Crash()

        with patch.object(modern, "_replace", crash):
            with self.assertRaises(Crash):
                self.compose()
        journal = self.store.path.parent / natural._COMPOSITION_JOURNAL
        expected = json.loads(journal.read_bytes())["operationalSnapshotId"]
        restarted = fixture_module.LiveCompositionSource(self.market.state, operational_epoch=self.fixture.epoch)
        current = restarted.natural_setup.snapshot_publication.current()
        self.assertEqual(current.snapshot_id, expected)
        for name, path in restarted.natural_setup._authoritative_paths().items():
            self.assertEqual(path.read_bytes(), current.component(name))
        self.assertFalse(journal.exists())

    def test_01_07_08_09_10_wrong_producer_contract_rejected_without_rewrite(self):
        original = self.store.path.read_bytes()
        for name, value in [("schemaVersion", 2), ("schemaVersion", True),
                             ("schemaVersion", 3.0), ("profile", "old"),
                             ("operationalEpochId", None), ("operationalEpochId", "f" * 64)]:
            with self.subTest(field=name, value=value):
                changed = modern.canonical_bytes({**json.loads(original), name: value})
                self.store.path.write_bytes(changed)
                with self.assertRaises(ValueError):
                    self.store.load()
                self.assertEqual(self.store.path.read_bytes(), changed)
        self.store.path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
