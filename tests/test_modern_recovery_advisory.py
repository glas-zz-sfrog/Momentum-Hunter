"""Executable challenges for the four bounded non-Astra review findings."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest
from unittest.mock import patch

from momentum_hunter import continuous_runtime as runtime
from momentum_hunter import modern_operational as modern
from momentum_hunter import shadow_trading as shadow
from tests import test_modern_recovery_integrity as recovery


class FillAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.case = recovery.FillRecoveryIntegrityTests("test_fully_filled_restart_has_no_additional_quantity")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.f, self.store, self.epoch = self.case.f, self.case.store, self.case.epoch

    def removed_suffix(self, outside=False):
        first, previous = self.case.initial()
        receipts = modern.SnapshotPublication(self.epoch, "SHADOW_FILL")
        r1, p1 = receipts.pointer.read_bytes(), self.store.publication.pointer.read_bytes()
        order, complete, _ = self.case.next_fill(first)
        self.store.save(complete, expected_previous=previous, recorded_at=order.last_update_at)
        path = receipts.root/(complete.fill_snapshot.snapshot_id+".json")
        preserved = self.f.f.fixture.fixture.path.parent/"removed-receipt-proof.json" if outside else path.with_suffix(".json.missing")
        path.rename(preserved)
        receipts.pointer.write_bytes(r1)
        self.store.publication.pointer.write_bytes(p1)
        with patch.object(self.f.broker, "_fill_entry", side_effect=AssertionError("new fill")) as primitive:
            with self.assertRaises(ValueError):
                restored = shadow.ModernShadowPositionStore(self.epoch).load()[0][0]
                self.f.fill(order=restored.order, prior=restored,
                    quote=replace(self.f.quote, timestamp="2026-08-17T11:21:40-04:00"))
            primitive.assert_not_called()
        self.assertTrue(preserved.is_file())

    def test_removed_receipt_suffix_and_stale_position_pointer_reject_before_fill(self):
        self.removed_suffix()

    def test_missing_receipt_outside_archive_still_conflicts_with_preserved_position_history(self):
        self.removed_suffix(outside=True)

    def test_receipt_ahead_process_restart_explicitly_recovers_exact_committed_bytes(self):
        first, previous = self.case.initial()
        order, complete, _ = self.case.next_fill(first)
        expected = complete.to_wire()
        del order, complete, first
        restarted = shadow.ModernShadowPositionStore(self.epoch)
        with self.assertRaises(ValueError):
            restarted.load()
        recover = getattr(restarted, "recover_pending_fills", None)
        self.assertTrue(callable(recover), "No explicit receipt-backed crash reconstruction API")
        rows, current = recover(expected_previous=previous, recorded_at="2026-08-17T11:21:40-04:00")
        self.assertEqual([row.to_wire() for row in rows], [expected])
        self.assertEqual(restarted.load(), (rows, current))
        self.assertEqual(recover(expected_previous=current, recorded_at="2026-08-17T11:21:40-04:00"), (rows, current))

    def test_first_receipt_without_position_is_explicitly_recoverable_after_memory_loss(self):
        _, first, _ = self.f.fill()
        expected = first.to_wire()
        del first
        restarted = shadow.ModernShadowPositionStore(self.epoch)
        recover = getattr(restarted, "recover_pending_fills", None)
        self.assertTrue(callable(recover), "No explicit first-receipt crash reconstruction API")
        rows, current = recover(expected_previous=None, recorded_at="2026-08-17T11:21:40-04:00")
        self.assertEqual([row.to_wire() for row in rows], [expected])
        self.assertEqual(restarted.load(), (rows, current))

    def test_explicit_recovery_does_not_normalize_contradictory_aggregate(self):
        first, previous = self.case.initial(2)
        body = json.loads(self.store.publication.current().component("positions"))
        body["positions"][0]["order"].update(filled_quantity=1, remaining_quantity=1, status="partially_filled")
        body["positions"][0]["position"]["quantity"] = 1
        changed = recovery.publish_component(self.store.publication, "positions", body, self.f.quote.timestamp)
        recover = getattr(self.store, "recover_pending_fills", None)
        self.assertTrue(callable(recover))
        with self.assertRaises(ValueError):
            recover(expected_previous=changed.snapshot_id, recorded_at="2026-08-17T11:21:40-04:00")
        self.assertEqual(self.store.publication.current(), changed)


class CheckpointAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.case = recovery.CheckpointRecoveryIntegrityTests("test_exact_checkpoint_restarts_with_new_process_not_new_logical_runtime")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.native, self.epoch, self.payload = self.case.native, self.case.epoch, self.case.payload

    def test_prior_valid_checkpoint_pointer_cannot_drop_newer_committed_work(self):
        publication = self.native.store.publication
        previous = publication.pointer.read_bytes()
        self.native.clock.advance(1)
        self.native.runtime._checkpoint(self.native.clock.now())
        current = publication.current()
        publication.pointer.write_bytes(previous)
        with self.assertRaises(ValueError):
            self.native.store.load(self.native.config.runtime_identity)
        self.assertTrue((publication.root/(current.snapshot_id+".json")).exists())

    def test_valid_discovery_item_cannot_move_to_health_queue(self):
        body = deepcopy(self.payload)
        body["queues"][runtime.HEALTH_QUEUE] = body["queues"][runtime.DISCOVERY_QUEUE]
        body["queues"][runtime.DISCOVERY_QUEUE] = []
        with self.assertRaises(ValueError):
            self.native.store.save(self.native.config.runtime_identity, body)
        work = runtime.ModernQueuedWork(**body["queues"][runtime.HEALTH_QUEUE][0])
        with self.assertRaises(ValueError):
            self.native.runtime._enqueue(runtime.HEALTH_QUEUE, work, self.native.clock.now())
        recovery.publish_component(self.native.store.publication, "checkpoint", recovery.checkpoint_body(body),
                                   self.payload["last_heartbeat_at"])
        with self.assertRaises(ValueError):
            recovery.restore(self.native, "foreign-container-restart")

    def test_missing_queue_and_deferred_containers_are_not_defaulted_empty(self):
        for location in (runtime.DISCOVERY_QUEUE, "deferred_readiness", "provider_bound_events", "in_flight", "in_flight_queue"):
            body = deepcopy(self.payload)
            (body["queues"] if location == runtime.DISCOVERY_QUEUE else body).pop(location)
            with self.subTest(location=location), self.assertRaises(ValueError):
                self.native.store.save(self.native.config.runtime_identity, body)
            recovery.publish_component(self.native.store.publication, "checkpoint", recovery.checkpoint_body(body),
                                       self.payload["last_heartbeat_at"])
            with self.subTest(load_location=location), self.assertRaises(ValueError):
                self.native.store.load(self.native.config.runtime_identity)

    def test_current_kind_bound_queue_and_deferred_containers_roundtrip(self):
        body = deepcopy(self.payload)
        kinds = {runtime.DISCOVERY_QUEUE: "DISCOVERY", runtime.READINESS_QUEUE: "READINESS",
            runtime.COMPOSITION_QUEUE: "COMPOSITION", runtime.EVIDENCE_QUEUE: "EVIDENCE", runtime.HEALTH_QUEUE: "HEARTBEAT"}
        def work(kind, key):
            return asdict(self.native.runtime._new_work(kind=kind, key=key,
                requested_at=self.native.clock.now().isoformat(), priority=1, payload={"fixture": key}))
        for queue, kind in kinds.items():
            body["queues"][queue] = [work(kind, queue)]
        body["deferred_readiness"] = [work("READINESS", "deferred")]
        body["provider_bound_events"] = [work("READINESS", "provider-bound")]
        body["in_flight"] = work("DISCOVERY", "flight")
        body["in_flight_queue"] = runtime.DISCOVERY_QUEUE
        self.native.store.save(self.native.config.runtime_identity, body)
        loaded = self.native.store.load(self.native.config.runtime_identity)
        for key in ("queues", "deferred_readiness", "provider_bound_events", "in_flight", "in_flight_queue"):
            self.assertEqual(loaded[key], body[key])

    def test_contradictory_duplicate_runtime_key_fails_strict_modern_parser(self):
        raw = modern.canonical_bytes(self.payload)
        raw = raw.replace(b'"runtime_identity":', b'"runtime_identity":"foreign","runtime_identity":', 1)
        publication = self.native.store.publication
        current = publication.current()
        manifest = json.loads(current.manifest_bytes)
        snapshot = modern.freeze_snapshot(self.epoch, kind="CHECKPOINT", components=(("checkpoint", raw),),
            sequence=manifest["sequence"]+1, predecessor=current.snapshot_id,
            created_at=manifest["createdAt"], known_at=manifest["knownAt"], decision_cutoff=manifest["decisionCutoff"])
        publication.publish(snapshot, expected_previous=current.snapshot_id)
        with self.assertRaises(ValueError):
            self.native.store.load(self.native.config.runtime_identity)


if __name__ == "__main__":
    unittest.main()
