"""Synthetic-only authority fixtures and the 29 accepted F4 contract cases."""

from contextlib import ExitStack
import copy
from dataclasses import asdict, replace
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter import historical_producer_admission as admission
from momentum_hunter.continuous_tradeplan_producer import (
    ContinuousTradePlanProducerError, ContinuousTradePlanProducerStore,
    producer_bound_report_row, validate_producer_record,
)


GOLDEN = Path(__file__).parent / "fixtures/identity_precontract/producer.json"
GOLDEN_SHA = "664885014323AC60819AA2BCEA5178003344E81DD60871FE7ADA7E4F995E2596"


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def digest(raw):
    return hashlib.sha256(raw).hexdigest().upper()


class SyntheticAuthority:
    """Test-owned installation substitute, never an application runtime switch."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.checkpoint = self.root / "checkpoint.json"
        self.selector = self.root / "selector.json"
        self.snapshot = self.root / "snapshots/current.json"
        self.snapshot.parent.mkdir()
        self.stack = ExitStack()

    def __enter__(self):
        for name, value in (("_CHECKPOINT_PATH", self.checkpoint), ("_SELECTOR_PATH", self.selector), ("_AUTHORITY_ROOT", self.root)):
            self.stack.enter_context(patch.object(admission, name, value))
        return self

    def __exit__(self, *args):
        self.stack.close()

    def event(self, raw, sequence=1):
        return {"sequence": sequence, "artifactKind": admission.ARTIFACT_KIND,
                "artifactSha256": digest(raw), "artifactBytes": len(raw),
                "evidenceClass": "SYNTHETIC_OLD_CODE_FIXTURE", "sourceCommit": admission.SOURCE_COMMIT,
                "historicalContract": admission.HISTORICAL_CONTRACT, "disposition": admission.ADMITTED,
                "supersedesSequence": None, "custody": {"packetSha256": "A" * 64,
                "packetBytes": 10, "packetRelativePath": "test-only/fixture-custody.zip"},
                "admissionTask": "TEST_ONLY_STEWARD_ADMISSION", "reviewTask": "TEST_ONLY_INDEPENDENT_REVIEW",
                "reason": "Synthetic isolated compatibility test; no production admission."}

    def publish(self, events, generation=1, predecessor=None, purpose=admission.TEST_PURPOSE):
        registry = {"schemaVersion": 1, "registryId": admission.REGISTRY_ID,
                    "generation": generation, "predecessor": predecessor, "events": events}
        self.pin_raw(wire(registry), generation=generation, purpose=purpose)
        return registry

    def pin_raw(self, raw, generation=1, purpose=admission.TEST_PURPOSE, locator="snapshots/current.json"):
        self.snapshot.write_bytes(raw)
        selector = {"schemaVersion": 1, "registryId": admission.REGISTRY_ID, "generation": generation,
                    "registrySha256": digest(raw), "registryBytes": len(raw), "snapshotRelativePath": locator}
        self.selector.write_bytes(wire(selector))
        self.checkpoint.write_bytes(wire({"schemaVersion": 1, "registryId": admission.REGISTRY_ID,
            "generation": generation, "selectorSha256": digest(wire(selector)), "purpose": purpose}))

    def revoke(self, event):
        prior = self.snapshot.read_bytes()
        withdrawn = {**copy.deepcopy(event), "sequence": 2, "disposition": admission.REVOKED,
                     "supersedesSequence": 1, "admissionTask": "TEST_ONLY_WITHDRAWAL",
                     "reviewTask": "TEST_ONLY_WITHDRAWAL_REVIEW", "reason": "Test-only withdrawal."}
        self.publish([event, withdrawn], generation=2,
                     predecessor={"generation": 1, "sha256": digest(prior), "bytes": len(prior)})
        return withdrawn

    def inventory(self):
        return {p.relative_to(self.root).as_posix(): digest(p.read_bytes())
                for p in self.root.rglob("*") if p.is_file()}


def stripped(document, rehash_payload=False, rehash_record=False):
    value = copy.deepcopy(document)
    value.pop("candidates", None)
    for record in value["records"]:
        record.pop("opportunity_id", None)
        payload = json.loads(record["payload_json"])
        for key in ("opportunityId", "setupId", "tradePlanId", "reportRowContract", "lifecycleSnapshot"):
            payload.pop(key, None)
        record["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if rehash_payload:
            record["payload_fingerprint"] = hashlib.sha256(record["payload_json"].encode("ascii")).hexdigest()
        if rehash_record:
            record["fingerprint"] = hashlib.sha256(wire({k: v for k, v in record.items() if k not in ("record_id", "fingerprint")})).hexdigest()
    return value


class HistoricalProducerAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import test_continuous_natural_setup as natural
        from momentum_hunter.continuous_live_qualification import LiveCompositionSource
        fixture = natural.ContinuousNaturalSetupTests()
        fixture.setUp()
        try:
            source = LiveCompositionSource(fixture.state)
            fixture._prepare(natural.at(11, 21), generation=1)
            source.compose(fixture._request(natural.at(11, 21), generation=1))
            cls.modern = source.producer_store.path.read_bytes()
            cls.modern_document = json.loads(cls.modern)
            cls.modern_records = source.producer_store.load()
        finally:
            fixture.doCleanups()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mh-r005-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.authority = SyntheticAuthority(self.root / "authority")
        self.authority.__enter__()
        self.addCleanup(self.authority.__exit__, None, None, None)
        self.raw = GOLDEN.read_bytes()
        self.event = self.authority.event(self.raw)
        self.authority.publish([self.event])
        self.path = self.root / "producer.json"
        self.path.write_bytes(self.raw)
        self.store = ContinuousTradePlanProducerStore(self.path)

    def denied(self, raw=None, disposition=None):
        if raw is not None:
            self.path.write_bytes(raw)
        before = self.path.read_bytes()
        authority_before = self.authority.inventory()
        if disposition is not None:
            self.assertEqual(disposition, admission.resolve_historical_admission(before).disposition)
        with self.assertRaises(ValueError):
            self.store.load()
        with self.assertRaises(ValueError):
            self.store.inspect_legacy()
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(authority_before, self.authority.inventory())

    def test_f4_01_exact_fixture_admitted(self):
        self.assertEqual(GOLDEN_SHA, digest(self.raw))
        before = self.authority.inventory()
        with patch("momentum_hunter.continuous_tradeplan_producer.json.loads", wraps=json.loads) as loads:
            records = self.store.load()
            self.assertLessEqual(sum(call.args[0] == self.raw for call in loads.call_args_list), 3)
        self.assertEqual(3, len(records))
        self.assertTrue(any(r.setup_id for r in records))
        self.assertTrue(all(not r.opportunity_id for r in records))
        self.assertEqual(records, self.store.load())
        self.assertEqual(self.raw, self.path.read_bytes())
        self.assertEqual(before, self.authority.inventory())

    def test_f4_02_no_admission(self):
        self.authority.publish([])
        self.denied(disposition=admission.NOT_ADMITTED)

    def test_f4_03_one_byte_mutation(self):
        self.denied(self.raw + b" ", admission.NOT_ADMITTED)
        decision = admission.resolve_historical_admission(self.path.read_bytes(), expected_sequence=1)
        self.assertEqual(admission.MISMATCH, decision.disposition)

    def test_f4_04_historical_local_hashes_recomputed(self):
        changed = json.loads(self.raw)
        row = changed["records"][0]
        payload = json.loads(row["payload_json"])
        payload["trigger"] = "ALTERED"
        row["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        row["payload_fingerprint"] = hashlib.sha256(row["payload_json"].encode()).hexdigest()
        row["fingerprint"] = hashlib.sha256(wire({k: v for k, v in row.items() if k not in ("record_id", "fingerprint")})).hexdigest()
        self.denied(wire(changed), admission.NOT_ADMITTED)

    def test_f4_05_modern_provenance_removed(self):
        self.denied(wire(stripped(self.modern_document)))

    def test_f4_06_modern_exact_legacy_shape(self):
        self.denied(wire(stripped(self.modern_document, True)))

    def test_f4_07_recomputed_both_hashes(self):
        self.denied(wire(stripped(self.modern_document, True, True)), admission.NOT_ADMITTED)
        self.path.write_bytes(self.modern)
        self.assertEqual(self.modern_records, self.store.load())

    def test_f4_08_historical_filename(self):
        self.path = self.root / "identity_precontract" / "producer.json"
        self.path.parent.mkdir()
        self.store = ContinuousTradePlanProducerStore(self.path)
        self.denied(wire(stripped(self.modern_document, True, True)))

    def test_f4_09_old_filesystem_time(self):
        self.path.write_bytes(wire(stripped(self.modern_document, True, True)))
        os.utime(self.path, (1, 1))
        self.denied()

    def test_f4_10_embedded_flags_or_markers(self):
        for key, value in (("legacy", True), ("origin", "PRECONTRACT"), ("schemaVersion", 1), ("test", True)):
            with self.subTest(field=key):
                changed = stripped(self.modern_document, True, True)
                changed[key] = value
                self.denied(wire(changed))

    def test_f4_11_exact_copy_same_authority(self):
        copied = self.root / "elsewhere" / "different-name.json"
        copied.parent.mkdir()
        copied.write_bytes(self.raw)
        store = ContinuousTradePlanProducerStore(copied)
        self.assertEqual(self.store.load(), store.load())
        self.assertEqual("LEGACY_UNBOUND", store.inspect_legacy()["linkageStatus"])
        self.authority.checkpoint.unlink()
        with self.assertRaises(ValueError):
            store.load()

    def test_f4_12_conflicting_admission(self):
        for field, value in (("sourceCommit", "f" * 40), ("artifactBytes", len(self.raw) + 1), ("reason", "different")):
            with self.subTest(field=field):
                duplicate = {**self.event, "sequence": 2, field: value}
                self.authority.publish([self.event, duplicate])
                self.denied(disposition=admission.AMBIGUOUS)

    def test_f4_13_missing_authority_modern_unaffected(self):
        for name in ("snapshot", "selector", "checkpoint"):
            with self.subTest(missing=name):
                self.authority.publish([self.event])
                getattr(self.authority, name).unlink()
                self.path.write_bytes(self.raw)
                self.denied(disposition=admission.AMBIGUOUS)
                self.path.write_bytes(self.modern)
                self.assertEqual(self.modern_records, self.store.load())

    def test_f4_14_strict_authority_parsing(self):
        registry = self.authority.publish([self.event])
        invalid = [b"{", b"{} garbage", b"[]", b'{"schemaVersion":1,"schemaVersion":1}', b'{"x":NaN}', b" " * (admission._REGISTRY_LIMIT + 1)]
        for value in (True, False, 1.0, 1.5, "1", None, 0, -1, 2, [], {}):
            invalid.append(wire({**registry, "schemaVersion": value}))
        invalid.append(wire({**registry, "unknown": True}))
        invalid.append(wire({**registry, "events": [{**self.event, "artifactSha256": GOLDEN_SHA.lower()}]}))
        invalid.append(wire({**registry, "events": [{**self.event, "artifactBytes": True}]}))
        invalid.append(wire({**registry, "events": [{**self.event, "custody": {**self.event["custody"], "packetRelativePath": "../escape"}}]}))
        for index, raw in enumerate(invalid):
            with self.subTest(raw=index):
                self.authority.pin_raw(raw)
                self.denied(disposition=admission.AMBIGUOUS)
        for locator in ("../outside", "C:/outside", "/absolute", "foo\\bar", "./same", "x//y", "NUL", "x:stream", "x. ", 'x"y', "x*y", "x?y"):
            with self.subTest(locator=locator):
                self.authority.pin_raw(wire(registry), locator=locator)
                self.denied(disposition=admission.AMBIGUOUS)
        for filename, parser in (("checkpoint", admission.parse_authority_checkpoint), ("selector", admission.parse_canonical_selector)):
            self.authority.publish([self.event])
            value = json.loads(getattr(self.authority, filename).read_bytes())
            for bad in (True, 1.0, "1", None, 0, -1, 2):
                with self.subTest(object=filename, schema=bad), self.assertRaises(ValueError):
                    parser(wire({**value, "schemaVersion": bad}))

    def test_f4_15_unbound_review_only(self):
        result = self.store.inspect_legacy()
        self.assertEqual("LEGACY_UNBOUND", result["linkageStatus"])
        for key in ("opportunityId", "setupId", "tradePlanId", "positionId", "openedAt"):
            self.assertIsNone(result[key])
        for record in self.store.load():
            with self.assertRaises(ValueError):
                producer_bound_report_row(record)

    def test_f4_16_duplicate_idempotency_and_sequence_conflict(self):
        self.authority.publish([self.event, copy.deepcopy(self.event)])
        self.assertEqual(3, len(self.store.load()))
        self.authority.publish([self.event, {**self.event, "reason": "conflict"}])
        self.denied(disposition=admission.AMBIGUOUS)

    def test_f4_17_revocation_and_rollback(self):
        old_selector, old_snapshot = self.authority.selector.read_bytes(), self.authority.snapshot.read_bytes()
        self.authority.revoke(self.event)
        self.denied(disposition=admission.REVOKED)
        self.authority.snapshot.write_bytes(old_snapshot)
        self.denied(disposition=admission.AMBIGUOUS)
        self.authority.selector.write_bytes(old_selector)
        self.store = ContinuousTradePlanProducerStore(self.path)
        self.denied(disposition=admission.AMBIGUOUS)

    def test_f4_18_partial_publication_no_alternative_authority(self):
        old_checkpoint = self.authority.checkpoint.read_bytes()
        self.authority.revoke(self.event)
        self.authority.checkpoint.write_bytes(old_checkpoint)
        self.denied(disposition=admission.AMBIGUOUS)
        alternative = self.root / "artifact-owned-checkpoint.json"
        alternative.write_bytes(old_checkpoint)
        self.assertNotIn("root", inspect.signature(admission.resolve_historical_admission).parameters)
        with self.assertRaises(TypeError):
            admission.resolve_historical_admission(self.raw, checkpoint_path=alternative)
        self.authority.checkpoint.write_bytes(wire([json.loads(old_checkpoint), json.loads(old_checkpoint)]))
        self.denied(disposition=admission.AMBIGUOUS)

    def test_f4_19_authority_and_buffer_races(self):
        original_read = admission._read
        changed = False
        def race(path, limit):
            nonlocal changed
            raw = original_read(path, limit)
            if path == self.authority.snapshot and not changed:
                changed = True
                self.authority.checkpoint.write_bytes(b"{}")
            return raw
        with patch.object(admission, "_read", race):
            with self.assertRaises(ValueError):
                self.store.load()
        self.authority.publish([self.event])
        original_revalidate = admission._CurrentAuthority.revalidate
        changed = False
        def input_race(context):
            nonlocal changed
            original_revalidate(context)
            if not changed:
                changed = True
                self.path.write_bytes(self.raw + b" ")
        with patch.object(admission._CurrentAuthority, "revalidate", input_race):
            with self.assertRaises(ValueError):
                self.store.load()

    def test_f4_20_purpose_and_caller_test_flag(self):
        self.authority.publish([self.event], purpose=admission.PRODUCTION_PURPOSE)
        self.denied(disposition=admission.NOT_ADMITTED)
        with self.assertRaises(TypeError):
            admission.resolve_historical_admission(self.raw, test=True)

    def test_f4_21_public_bare_boundaries_modern_only(self):
        records = self.store.load()
        document = json.loads(self.raw)
        for record in records:
            with self.assertRaises(ValueError):
                validate_producer_record(record)
            with self.assertRaises(ValueError):
                producer_bound_report_row(record)
        with self.assertRaises(ValueError):
            self.store.validate_document(document)
        with self.assertRaises(ValueError):
            self.store.validate_document(document, selected_row={})
        with self.assertRaises(TypeError):
            self.store.validate_document(document, historical_document={"trusted": True})
        self.assertEqual(records, self.store.load())

    def test_f4_22_duplicate_only_historical_append(self):
        records = self.store.load()
        for record in records:
            self.assertEqual(record, self.store.append(record))
        self.assertEqual(self.raw, self.path.read_bytes())
        with self.assertRaises(ValueError):
            self.store.append(replace(records[0], record_id="different"))
        target = self.root / "new-cache.json"
        with self.assertRaises(ValueError):
            ContinuousTradePlanProducerStore(target).append(records[0])
        self.assertFalse(target.exists())

    def test_f4_23_no_derivative_or_mixed_authority(self):
        original = json.loads(self.raw)
        variants = [wire(original), self.raw.rstrip(), wire({**original, "candidates": []}),
                    wire({**original, "records": original["records"][:1]}),
                    wire({**original, "records": list(reversed(original["records"]))})]
        for raw in variants:
            with self.subTest(hash=digest(raw)):
                if raw != self.raw:
                    self.denied(raw)
        self.path.write_bytes(self.raw)
        with self.assertRaises(ValueError):
            self.store.append(self.modern_records[0])
        with self.assertRaises(ValueError):
            self.store._write_unlocked(self.store.load())
        self.assertEqual(self.raw, self.path.read_bytes())

    def test_f4_24_historical_preview_cannot_publish(self):
        from tests import test_continuous_natural_setup as natural
        from momentum_hunter.continuous_live_qualification import LiveCompositionSource
        fixture = natural.ContinuousNaturalSetupTests()
        fixture.setUp()
        try:
            source = LiveCompositionSource(fixture.state)
            source.producer_store.path.parent.mkdir(parents=True, exist_ok=True)
            source.producer_store.path.write_bytes(self.raw)
            owner = source.natural_setup
            paths = owner._authoritative_paths()
            before = {k: p.read_bytes() if p.exists() else None for k, p in paths.items()}
            with owner.preview() as preview:
                self.assertEqual(3, len(preview.producer_store.load()))
                with self.assertRaises(ValueError):
                    preview.producer_store.append(self.modern_records[0])
                with self.assertRaises(ValueError):
                    preview.commit()
                self.assertFalse(preview.committed)
                self.assertEqual(before, {k: p.read_bytes() if p.exists() else None for k, p in paths.items()})
                self.assertFalse(list(source.producer_store.path.parent.glob("*composition*journal*")))
        finally:
            fixture.doCleanups()

    def test_f4_25_latest_restart_rechecks_revocation_and_bytes(self):
        record = self.store.load()[0]
        with self.assertRaisesRegex(ValueError, "cannot seed"):
            self.store.latest_material(record.member_id, record.material_evidence_fingerprint)
        self.authority.revoke(self.event)
        for store in (self.store, ContinuousTradePlanProducerStore(self.path)):
            with self.assertRaises(ValueError):
                store.latest_material(record.member_id, record.material_evidence_fingerprint)
            with self.assertRaises(ValueError):
                store.append(record)
        self.authority.publish([self.event])
        self.path.write_bytes(self.raw + b" ")
        with self.assertRaises(ValueError):
            self.store.latest_material(record.member_id, record.material_evidence_fingerprint)

    def test_f4_26_allowlist_never_waives_structure(self):
        for mode in ("schema", "record", "duplicate", "projection", "payload", "missing_records", "null_records"):
            changed = json.loads(self.raw)
            if mode == "schema": changed["schemaVersion"] = True
            elif mode == "record": changed["records"][0]["fingerprint"] = "0" * 64
            elif mode == "duplicate": changed["records"].append(changed["records"][0])
            elif mode == "projection": changed["candidates"] = []
            elif mode == "missing_records": changed.pop("records")
            elif mode == "null_records": changed["records"] = None
            else: changed["records"][0]["payload_json"] = "{}"
            raw = wire(changed)
            with self.subTest(mode=mode):
                self.authority.publish([self.authority.event(raw)])
                self.assertEqual(admission.ADMITTED, admission.resolve_historical_admission(raw).disposition)
                self.denied(raw)

    def test_f4_27_modern_append_projection_unchanged(self):
        self.authority.checkpoint.unlink()
        self.path.write_bytes(self.modern)
        for record in self.modern_records:
            self.assertEqual(record, self.store.append(record))
            producer_bound_report_row(record)
        fresh = ContinuousTradePlanProducerStore(self.root / "modern-new.json")
        for record in self.modern_records:
            fresh.append(record)
        self.assertEqual(self.modern_records, fresh.load())
        self.assertEqual(self.modern_records, self.store.validate_document(json.loads(self.modern)))

    def test_f4_28_complete_history_and_terminal_withdrawal(self):
        withdrawn = self.authority.revoke(self.event)
        registry = json.loads(self.authority.snapshot.read_bytes())
        mutations = [[], [withdrawn], [self.event, withdrawn, {**self.event, "sequence": 3}],
                     [self.event, {**withdrawn, "evidenceClass": "HISTORICAL_CACHE"}],
                     [self.event, {**withdrawn, "supersedesSequence": True}]]
        for events in mutations:
            with self.subTest(events=len(events)):
                altered = wire({**registry, "events": events})
                self.authority.snapshot.write_bytes(altered)
                self.denied(disposition=admission.AMBIGUOUS)
                self.authority.pin_raw(altered, generation=2)
                self.denied(disposition=admission.AMBIGUOUS)
                self.authority.pin_raw(wire(registry), generation=2)

    def test_f4_29_no_authority_write_network_or_bootstrap(self):
        before = self.authority.inventory()
        modes = []
        original_open = Path.open
        def spy(path, mode="r", *args, **kwargs):
            if path.is_relative_to(self.authority.root):
                modes.append(mode)
                self.assertFalse(any(c in mode for c in "wax+"))
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, "open", spy), patch("socket.create_connection", side_effect=AssertionError("No network")):
            self.assertEqual(admission.ADMITTED, admission.resolve_historical_admission(self.raw).disposition)
            records = self.store.load()
            self.store.inspect_legacy()
            with self.assertRaisesRegex(ValueError, "cannot seed"):
                self.store.latest_material(records[0].member_id, records[0].material_evidence_fingerprint)
            self.store.append(records[0])
        self.assertTrue(modes)
        self.assertEqual(before, self.authority.inventory())

    def test_production_inspection_cannot_seed_operational_reads(self):
        self.authority.publish([{**self.event, "evidenceClass": "HISTORICAL_CACHE"}],
                               purpose=admission.PRODUCTION_PURPOSE)
        before = self.authority.inventory()
        result = self.store.inspect_legacy()
        self.assertEqual("LEGACY_UNBOUND", result["linkageStatus"])
        record = json.loads(self.raw)["records"][0]
        with self.assertRaisesRegex(ValueError, "operational load is forbidden"):
            self.store.load()
        with self.assertRaisesRegex(ValueError, "cannot seed"):
            self.store.latest_material(record["member_id"], record["material_evidence_fingerprint"])
        self.assertEqual(before, self.authority.inventory())
        self.assertEqual(self.raw, self.path.read_bytes())

    def test_admission_does_not_waive_nested_json_or_evidence(self):
        for mode in ("nonfinite", "overflow", "duplicate", "history_count", "current_time", "cycle_summary"):
            changed = json.loads(self.raw)
            record = changed["records"][0]
            payload = json.loads(record["payload_json"])
            if mode == "nonfinite":
                payload["historicalContext"]["minute_bar_count"] = float("nan")
            elif mode == "history_count":
                payload["historicalContext"]["minute_bar_count"] += 1
            elif mode == "current_time":
                payload["currentMarketEvidence"]["provider_timestamp"] = "invalid"
            elif mode == "cycle_summary":
                payload["compositionCycle"]["summary"]["ready"] += 1
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            if mode == "duplicate":
                encoded = '{"schemaVersion":1,' + encoded[1:]
            elif mode == "overflow":
                encoded = encoded.replace('"minute_bar_count":25', '"minute_bar_count":1e999')
                self.assertIn("1e999", encoded)
            record["payload_json"] = encoded
            record["payload_fingerprint"] = hashlib.sha256(encoded.encode("ascii")).hexdigest()
            record["fingerprint"] = hashlib.sha256(wire({k: v for k, v in record.items() if k not in ("record_id", "fingerprint")})).hexdigest()
            raw = wire(changed)
            with self.subTest(mode=mode):
                self.authority.publish([self.authority.event(raw)])
                self.assertEqual(admission.ADMITTED, admission.resolve_historical_admission(raw).disposition)
                self.denied(raw)


if __name__ == "__main__":
    unittest.main()
