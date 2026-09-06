"""Synthetic independent cutover records only; no production root is provisioned."""
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter import modern_operational as modern


SOURCE = "a" * 64
CONFIG = "b" * 64
WHEN = "2026-08-17T11:00:00-04:00"


class EpochFixture:
    def __init__(self, root: Path, *, configuration=CONFIG):
        self.path = root / "independent-cutover.json"
        self.root = root / "selected-operational"
        self.document = {"schemaVersion": 1, "operationalContract": modern.MODERN_CONTRACT,
            "operationalEpochId": "d" * 64, "namespaceGeneration": "e" * 64,
            "sourceIdentity": SOURCE, "configurationIdentity": configuration,
            "operationalRoot": str(self.root), "notBefore": WHEN}
        self.path.write_bytes(modern.canonical_bytes(self.document))
        (root / "modern-operational-cutover-established.json").write_bytes(modern.canonical_bytes({
            "schemaVersion": 1, "operationalContract": modern.MODERN_CONTRACT,
            "legacyOperationalAuthority": "PROHIBITED"}))
        self.patch = patch.object(modern, "CURRENT_CUTOVER", self.path)
        self.patch.start()
        self.epoch = modern.load_current_epoch(source_identity=SOURCE,
                                               configuration_identity=configuration)

    def assessment(self, obligations=()):
        return modern.ObligationAssessment(WHEN,
            ("POSITIONS", "WORKING_ORDERS", "BROKER_STATE", "PERSISTED_EXECUTION"), obligations)

    def start(self):
        modern.initialize_epoch(self.epoch, self.assessment())


class ModernOperationalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mh-modern-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = EpochFixture(self.root)
        self.addCleanup(self.fixture.patch.stop)
        self.epoch = self.fixture.epoch

    def test_12_34_fresh_namespace_no_obligations(self):
        self.fixture.start()
        modern.require_epoch_started(self.epoch)
        self.assertEqual([p.name for p in self.fixture.root.iterdir()], ["epoch.json"])

    def test_35_36_37_38_unknown_foreign_and_unresolved_obligations_block_without_mutation(self):
        for identity, epoch, resolved in [("old", "f" * 64, False),
                                          ("unknown", None, False),
                                          ("current", self.epoch.epoch_id, False)]:
            with self.subTest(identity=identity):
                assessment = self.fixture.assessment((modern.Obligation(identity, epoch, resolved),))
                with self.assertRaisesRegex(modern.ModernOperationalError, "BLOCK_RECONCILIATION_REQUIRED"):
                    modern.initialize_epoch(self.epoch, assessment)
                self.assertFalse(self.fixture.root.exists())
                self.assertEqual(assessment.obligations[0].identity, identity)

    def test_obligation_inventory_cannot_be_omitted(self):
        with self.assertRaisesRegex(modern.ModernOperationalError, "RECONCILIATION_REQUIRED"):
            modern.initialize_epoch(self.epoch, replace(self.fixture.assessment(), inspected_sources=()))

    def test_selected_nonempty_namespace_is_not_reset_or_migrated(self):
        self.fixture.root.mkdir()
        historical = self.fixture.root / "legacy.json"
        historical.write_bytes(b'{"schemaVersion":2}')
        with self.assertRaises(modern.ModernOperationalError):
            self.fixture.start()
        self.assertEqual(historical.read_bytes(), b'{"schemaVersion":2}')

    def test_artifact_cannot_self_select_epoch(self):
        self.fixture.path.unlink()
        with self.assertRaisesRegex(modern.ModernOperationalError, "CUTOVER_AUTHORITY_UNAVAILABLE"):
            self.fixture.start()

    def test_27_28_strict_schema_type(self):
        for schema in (True, 1.0, "1"):
            with self.subTest(schema=schema):
                self.fixture.path.write_bytes(modern.canonical_bytes({**self.fixture.document, "schemaVersion": schema}))
                with self.assertRaises(modern.ModernOperationalError):
                    self.fixture.start()

    def test_current_authority_not_caller_object_selects_epoch(self):
        with self.assertRaises(modern.ModernOperationalError):
            modern.initialize_epoch(replace(self.epoch, epoch_id="f" * 64), self.fixture.assessment())

    def test_19_21_snapshot_bytes_not_path_identity(self):
        self.fixture.start()
        snapshot = modern.freeze_snapshot(self.epoch, kind="CHECKPOINT",
            components=(("state", b'{"schemaVersion":3}'),), sequence=1, predecessor=None,
            created_at=WHEN, known_at=WHEN, decision_cutoff=WHEN)
        snapshot.validate(self.epoch, kind="CHECKPOINT", expected_id=snapshot.snapshot_id)
        wrong = replace(snapshot, components=(("state", b'{"schemaVersion":2}'),))
        with self.assertRaises(modern.ModernOperationalError):
            wrong.validate(self.epoch, kind="CHECKPOINT", expected_id=snapshot.snapshot_id)
        recovered = modern.snapshot_from_bytes(snapshot.to_bytes(), self.epoch,
            kind="CHECKPOINT", expected_id=snapshot.snapshot_id)
        self.assertEqual(recovered, snapshot)

    def test_nonfinite_number_encodings_fail_before_use(self):
        for raw in (b'{"quantity":1e999}', b'{"quantity":NaN}', b'{"quantity":Infinity}'):
            with self.assertRaises(modern.ModernOperationalError):
                modern.parse_bytes(raw)

    def test_crash_after_preparation_or_archive_recovers_exact_snapshot_once(self):
        self.fixture.start()
        publication = modern.SnapshotPublication(self.epoch, "CHECKPOINT")
        snapshot = modern.freeze_snapshot(self.epoch, kind="CHECKPOINT",
            components=(("state", b'{"modern":true}'),), sequence=1, predecessor=None,
            created_at=WHEN, known_at=WHEN, decision_cutoff=WHEN)
        replace_file = modern._replace

        class Crash(BaseException):
            pass

        def crash_after_archive(path, raw):
            replace_file(path, raw)
            if path.name == snapshot.snapshot_id + ".json":
                raise Crash()

        with patch.object(modern, "_replace", crash_after_archive):
            with self.assertRaises(Crash):
                publication.publish(snapshot, expected_previous=None)
        self.assertTrue(publication.pending.exists())
        self.assertFalse(publication.pointer.exists())
        restored = modern.SnapshotPublication(self.epoch, "CHECKPOINT")
        self.assertEqual(restored.current(), snapshot)
        self.assertFalse(publication.pending.exists())
        self.assertEqual(restored.current(), snapshot)

    def test_prepared_journal_payload_mismatch_never_publishes(self):
        self.fixture.start()
        publication = modern.SnapshotPublication(self.epoch, "CHECKPOINT")
        publication.root.mkdir(parents=True, exist_ok=True)
        publication.pending.write_bytes(modern.canonical_bytes({"snapshotId": "a" * 64,
            "payloadSha256": "b" * 64, "snapshot": "{}"}))
        with self.assertRaises(modern.ModernOperationalError):
            publication.current()
        self.assertFalse(publication.pointer.exists())

    def test_duck_typed_validate_a_serialize_b_never_reaches_publication(self):
        self.fixture.start()
        a = modern.freeze_snapshot(self.epoch, kind="CHECKPOINT", components=(("state", b'{"value":"A"}'),),
            sequence=1, predecessor=None, created_at=WHEN, known_at=WHEN, decision_cutoff=WHEN)
        b = modern.freeze_snapshot(self.epoch, kind="CHECKPOINT", components=(("state", b'{"value":"B"}'),),
            sequence=1, predecessor=None, created_at=WHEN, known_at=WHEN, decision_cutoff=WHEN)

        class Forged:
            snapshot_id = b.snapshot_id
            def validate(self, epoch, *, kind):
                return a.validate(epoch, kind=kind)
            def to_bytes(self):
                return b.to_bytes()

        publication = modern.SnapshotPublication(self.epoch, "CHECKPOINT")
        with self.assertRaises(modern.ModernOperationalError):
            publication.publish(Forged(), expected_previous=None)
        self.assertFalse(publication.pointer.exists())
        self.assertFalse(publication.pending.exists())

    def test_authority_loss_blocks_modern_namespace_not_unrelated_opening(self):
        self.fixture.start()
        self.fixture.path.unlink()
        with self.assertRaises(modern.ModernOperationalError):
            modern.reject_legacy_operation(self.fixture.root / "legacy.json")
        modern.reject_legacy_operation(self.root / "independent-opening" / "opening.json")

    def test_uncooperative_authority_swap_at_commit_cannot_return_acceptance(self):
        self.fixture.start()
        snapshot = modern.freeze_snapshot(self.epoch, kind="CHECKPOINT", components=(("state", b'{}'),),
            sequence=1, predecessor=None, created_at=WHEN, known_at=WHEN, decision_cutoff=WHEN)
        publication = modern.SnapshotPublication(self.epoch, "CHECKPOINT")
        replace_file = modern._replace

        def swap(path, raw):
            if path == publication.pointer:
                self.fixture.path.write_bytes(modern.canonical_bytes({**self.fixture.document,
                    "operationalEpochId": "f" * 64}))
            replace_file(path, raw)

        with patch.object(modern, "_replace", swap):
            with self.assertRaises(modern.ModernOperationalError):
                publication.publish(snapshot, expected_previous=None)
        with self.assertRaises(modern.ModernOperationalError):
            publication.require_consumed(snapshot, expected_id=snapshot.snapshot_id)


if __name__ == "__main__":
    unittest.main()
