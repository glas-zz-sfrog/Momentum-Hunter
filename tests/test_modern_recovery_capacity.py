"""Native temporary residue and retained-checkpoint exhaustion, offline only."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

from momentum_hunter import continuous_runtime as runtime
from momentum_hunter import modern_operational as modern
from momentum_hunter import modern_recovery_integrity as integrity
from momentum_hunter import shadow_trading as shadow
from tests import test_modern_recovery_integrity as recovery
from tests import test_modern_runtime_checkpoint as fixtures
from tests import test_modern_operational_runtime as startup_fixtures


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def temporary(publication, body, target="current.json"):
    path = publication.root / f".{target}.{uuid.uuid4().hex}.tmp"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def successor(publication, *, offset=1):
    previous = publication.current()
    manifest = modern.parse_bytes(previous.manifest_bytes)
    return modern.freeze_snapshot(publication.epoch, kind=publication.kind,
        components=previous.components, sequence=manifest["sequence"] + offset,
        predecessor=previous.snapshot_id, created_at=manifest["createdAt"],
        known_at=manifest["knownAt"], decision_cutoff=manifest["decisionCutoff"])


class CheckpointFixture(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ModernRuntimeCheckpointTests(
            "test_current_modern_runtime_checkpoint_and_queue_roundtrip")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.start_with_work()
        self.native = self.f.native
        self.store = self.native.store
        self.publication = self.store.publication
        self.epoch = self.f.cutover.epoch
        self.payload = self.store.load(self.native.config.runtime_identity)

    def load(self):
        return self.store.load(self.native.config.runtime_identity)


class NativeTemporaryRecoveryTests(CheckpointFixture):
    def test_f3_committed_state_survives_exact_native_crash_window_matrix(self):
        expected = self.load()
        for name, raw in (("empty", b""), ("partial", b'{"snapshotId":'),
                          ("complete", self.publication.pointer.read_bytes()),
                          ("malformed", b"not-json"), ("changed-same-id", b'{"snapshotId":"' +
                           self.publication.current().snapshot_id.encode() + b'","changed":true}')):
            with self.subTest(window=name):
                before = inventory(self.publication.root)
                residue = temporary(self.publication, raw)
                for _ in range(2):
                    self.assertEqual(self.load(), expected)
                self.assertEqual(residue.read_bytes(), raw)
                self.assertEqual({k: v for k, v in inventory(self.publication.root).items()
                                  if k != residue.name}, before)
        self.assertEqual(len(list(self.publication.root.glob(".*.tmp"))), 5)
        self.assertEqual(self.load(), expected)

    def test_f3_native_process_dies_after_flush_before_atomic_promotion(self):
        expected = self.load()
        before = inventory(self.publication.root)
        raw_path = self.f.root / "native-pending-input.json"
        proposed = successor(self.publication)
        raw = proposed.to_bytes()
        raw_path.write_bytes(modern.canonical_bytes({"snapshotId": proposed.snapshot_id,
            "payloadSha256": modern.digest(raw), "snapshot": raw.decode("ascii")}))
        child = """import os,sys
from pathlib import Path
from unittest.mock import patch
from momentum_hunter import modern_operational as modern
with patch.object(modern.os, 'replace', side_effect=lambda *args: os._exit(73)):
    modern._replace(Path(sys.argv[1]), Path(sys.argv[2]).read_bytes())
raise AssertionError('native crash boundary not reached')
"""
        result = subprocess.run([sys.executable, "-B", "-c", child,
            str(self.publication.pending), str(raw_path)], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 73, result.stderr.decode(errors="replace"))
        residues = list(self.publication.root.glob(".pending.json.*.tmp"))
        self.assertEqual(len(residues), 1)
        self.assertEqual(residues[0].read_bytes(), raw_path.read_bytes())
        self.assertFalse(self.publication.pending.exists())
        self.assertEqual(self.load(), expected)
        self.assertEqual({k: v for k, v in inventory(self.publication.root).items()
                          if k != residues[0].name}, before)
        self.assertFalse((self.publication.root / (proposed.snapshot_id + ".json")).exists())

    def test_f3_temp_only_does_not_create_authority(self):
        empty = modern.SnapshotPublication(self.epoch, "POSITION")
        residue = temporary(empty, self.publication.current().to_bytes())
        self.assertIsNone(empty.current())  # Establish the ordinary nonauthoritative lock first.
        before = inventory(empty.root)
        with self.assertRaisesRegex(ValueError, "missing committed authority"):
            integrity.complete_publication_history(empty)
        with self.assertRaisesRegex(ValueError, "missing committed authority"):
            shadow.ModernShadowPositionStore(self.epoch).load()
        self.assertIsNone(empty.current())
        self.assertEqual(inventory(empty.root), before)
        self.assertTrue(residue.exists())

    def test_f3_unknown_and_almost_native_names_remain_blocking(self):
        for name in ("extra.json", ".current.json.deadbeef.tmp",
                     ".current.json." + "0" * 32 + ".tmp",
                     ".foreign.json." + uuid.uuid4().hex + ".tmp",
                     "current.json." + uuid.uuid4().hex + ".tmp"):
            with self.subTest(name=name):
                path = self.publication.root / name
                path.write_bytes(b"{}")
                before = inventory(self.publication.root)
                with self.assertRaises(ValueError):
                    self.load()
                self.assertEqual(inventory(self.publication.root), before)
                path.unlink()  # Test-owned challenge removed between independent cases.

    def test_f3_directory_or_reparse_named_like_temp_is_not_ignored(self):
        path = self.publication.root / f".current.json.{uuid.uuid4().hex}.tmp"
        path.mkdir()
        with self.assertRaises(ValueError):
            self.load()
        regular = temporary(self.publication, b"")
        info = regular.lstat()
        class ReparseStat:
            st_mode = info.st_mode
            st_file_attributes = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        with patch.object(Path, "lstat", return_value=ReparseStat()):
            self.assertFalse(integrity._uncommitted_native_temp(regular))

    def test_f3_orphan_committed_archive_is_not_hidden_by_valid_temp(self):
        proposed = successor(self.publication)
        path = self.publication.root / (proposed.snapshot_id + ".json")
        path.write_bytes(proposed.to_bytes())
        temporary(self.publication, b"")
        before = inventory(self.publication.root)
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(inventory(self.publication.root), before)

    def test_f3_real_pending_journal_recovers_exact_prepared_snapshot(self):
        proposed = successor(self.publication)
        raw = proposed.to_bytes()
        self.publication.pending.write_bytes(modern.canonical_bytes({
            "snapshotId": proposed.snapshot_id, "payloadSha256": modern.digest(raw),
            "snapshot": raw.decode("ascii")}))
        residue = temporary(self.publication, b"uncommitted")
        self.assertEqual(self.publication.current(), proposed)
        self.assertFalse(self.publication.pending.exists())
        self.assertEqual(self.load(), self.payload)
        self.assertEqual(residue.read_bytes(), b"uncommitted")
        self.assertEqual(len(integrity.complete_publication_history(self.publication)), 3)

    def test_f3_malformed_pending_remains_authoritative_failure(self):
        self.publication.pending.write_bytes(b'{"snapshotId":')
        temporary(self.publication, b"valid-looking")
        before = inventory(self.publication.root)
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(inventory(self.publication.root), before)


class FillTemporaryRecoveryTests(unittest.TestCase):
    def test_f3_fill_and_position_identity_survive_multiple_temp_residues(self):
        f = recovery.FillRecoveryIntegrityTests("test_fully_filled_restart_has_no_additional_quantity")
        f.setUp()
        self.addCleanup(f.doCleanups)
        fill, previous = f.initial()
        for kind in ("POSITION", "SHADOW_FILL"):
            publication = modern.SnapshotPublication(f.epoch, kind)
            temporary(publication, b"")
            temporary(publication, b'{"partial":')
            temporary(publication, publication.current().to_bytes(),
                      publication.current().snapshot_id + ".json")
        before = inventory(Path(f.epoch.root))
        for _ in range(2):
            store = shadow.ModernShadowPositionStore(f.epoch)
            self.assertEqual(store.load(), ((fill,), previous))
            self.assertEqual(store.recover_pending_fills(expected_previous=previous,
                recorded_at=f.f.quote.timestamp), ((fill,), previous))
        self.assertEqual(inventory(Path(f.epoch.root)), before)
        order, complete, _ = f.next_fill(fill)
        self.assertEqual((order.filled_quantity, order.remaining_quantity), (2, 0))
        self.assertEqual((complete.position.position_id, complete.position.opened_at, complete.identity),
                         (fill.position.position_id, fill.position.opened_at, fill.identity))


class StartupCapacityTests(unittest.TestCase):
    def test_installed_entrypoint_contract_does_not_yield_at_or_into_capacity(self):
        # The actual dormant entrypoint, but only fixture roots and mocked transports.
        f = startup_fixtures.ModernOperationalRuntimeTests(
            "test_restore_preserves_start_floor_and_exact_modern_queued_work")
        f.setUp()
        self.addCleanup(f.doCleanups)
        with f.open() as session:
            store = session.runtime.checkpoint_store
        self.assertEqual(store.checkpoint_capacity()["retained_checkpoints"], 2)
        with patch.object(modern, "MAX_RETAINED_CHECKPOINTS", 3), patch.object(
                integrity, "MAX_RETAINED_CHECKPOINTS", 3):
            with self.assertRaises(modern.CheckpointHistoryCapacityError), f.open(fresh=False):
                self.fail("Exhausted entrypoint yielded an active session")
            self.assertEqual(store.checkpoint_capacity()["retained_checkpoints"], 3)
            before = inventory(f.fixture.root)
            from momentum_hunter import modern_operational_runtime as startup
            for _ in range(2):
                with patch.object(startup, "QualificationState",
                        side_effect=AssertionError("session reconstruction at capacity")) as state:
                    with self.assertRaises(modern.CheckpointHistoryCapacityError), f.open(fresh=False):
                        self.fail("Exhausted entrypoint yielded an active session")
                    state.assert_not_called()
                self.assertEqual(inventory(f.fixture.root), before)
                self.assertIsNotNone(store.load(f.native.config.runtime_identity))
            f.assert_no_provider_contact()


class CheckpointCapacityTests(CheckpointFixture):
    def small_limit(self, count=3):
        for module in (modern, integrity):
            limit_patch = patch.object(module, "MAX_RETAINED_CHECKPOINTS", count)
            limit_patch.start()
            self.addCleanup(limit_patch.stop)

    def exhausted(self):
        self.small_limit()
        self.store.save(self.native.config.runtime_identity, self.payload)
        self.assertEqual(self.store.checkpoint_capacity()["write_capacity_remaining"], 0)

    def test_limit_is_exact_4096_not_queue_or_payload_capacity(self):
        self.assertEqual(modern.MAX_RETAINED_CHECKPOINTS, 4096)
        self.assertEqual(integrity.MAX_RETAINED_CHECKPOINTS, 4096)
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 2)
        self.assertEqual(sum(len(v) for v in self.payload["queues"].values()), 1)
        self.assertEqual(self.store.checkpoint_capacity()["maximum_retained_checkpoints"], 4096)

    def test_transition_to_capacity_blocks_active_restart_and_releases_lease(self):
        self.small_limit()
        with self.assertRaises(modern.CheckpointHistoryCapacityError) as raised:
            recovery.restore(self.native, "at-limit-restart")
        self.assertEqual(raised.exception.diagnostic_code,
                         "BLOCKED_CHECKPOINT_HISTORY_CAPACITY_EXHAUSTED")
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 3)
        self.assertEqual(self.load()["runtime_instance_id"], "at-limit-restart")
        self.assertIsNone(self.native.leases.current(self.native.config.runtime_identity))

    def test_at_capacity_restores_never_construct_runtime_or_touch_chain(self):
        self.exhausted()
        before = inventory(self.publication.root)
        for attempt in range(3):
            with patch.object(runtime.ContinuousOpportunityRuntime, "__init__",
                              side_effect=AssertionError("active runtime constructed")) as constructor:
                with self.assertRaises(modern.CheckpointHistoryCapacityError):
                    recovery.restore(self.native, f"blocked-{attempt}")
                constructor.assert_not_called()
            self.assertEqual(self.load(), self.payload)
            self.assertEqual(inventory(self.publication.root), before)

    def test_direct_publication_cannot_bypass_store_limit_plus_one_or_two(self):
        self.exhausted()
        before = inventory(self.publication.root)
        for offset in (1, 2):
            proposed = successor(self.publication, offset=offset)
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                self.publication.publish(proposed,
                    expected_previous=self.publication.current().snapshot_id)
            self.assertEqual(inventory(self.publication.root), before)

    def test_save_at_capacity_preserves_all_bytes_and_readable_state(self):
        self.exhausted()
        before = inventory(self.publication.root)
        for _ in range(2):
            changed = deepcopy(self.payload)
            changed["runtime_instance_id"] = "must-not-be-committed"
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                self.store.save(self.native.config.runtime_identity, changed)
            self.assertEqual(inventory(self.publication.root), before)
            self.assertEqual(self.load(), self.payload)
        self.assertFalse(self.publication.pending.exists())

    def test_runtime_checkpoint_reaching_limit_stops_before_returning_active(self):
        self.small_limit()
        with self.assertRaises(modern.CheckpointHistoryCapacityError):
            self.native.runtime._checkpoint(self.native.clock.now())
        self.assertEqual(self.native.runtime.process_state, runtime.FAILED)
        self.assertFalse(self.native.runtime._accepting_work)
        self.assertIn(modern.CHECKPOINT_HISTORY_CAPACITY_EXHAUSTED,
                      self.native.runtime.health(self.native.clock.now()).health_flags)
        self.assertIsNone(self.native.runtime.lease)
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 3)

    def test_capacity_blocks_live_work_before_provider_writer_or_queue_mutation(self):
        self.exhausted()
        r = self.native.runtime
        before = inventory(self.publication.root)
        queues = {k: v.snapshot() for k, v in r._queues.items()}
        operations = [
            lambda: r.tick(self.native.clock.now()),
            lambda: r.request_discovery(self.native.clock.now()),
            lambda: r.submit_event(None, self.native.clock.now()),
            lambda: r.admit_evidence_intent(None, self.native.clock.now()),
            lambda: r.release_deferred_readiness(self.native.clock.now()),
            lambda: r.set_session_eligibility(True, self.native.clock.now()),
            lambda: r._process_one(runtime.DISCOVERY_QUEUE, self.native.clock.now()),
            lambda: r._process_evidence(self.native.clock.now()),
            lambda: r._enqueue(runtime.DISCOVERY_QUEUE, None, self.native.clock.now()),
            lambda: r.crash_with_in_flight(runtime.DISCOVERY_QUEUE, self.native.clock.now()),
        ]
        with (patch.object(self.native.events, "poll", side_effect=AssertionError("provider")),
             patch.object(self.native.discovery, "discover", side_effect=AssertionError("provider")),
             patch.object(self.native.writer, "write_intent", side_effect=AssertionError("writer"))):
            for operation in operations:
                with self.assertRaises(modern.CheckpointHistoryCapacityError):
                    operation()
        self.assertEqual({k: v.snapshot() for k, v in r._queues.items()}, queues)
        self.assertEqual(inventory(self.publication.root), before)

    def assert_runtime_capacity_blocked(self):
        r = self.native.runtime
        self.assertEqual(r.process_state, runtime.FAILED)
        self.assertFalse(r._accepting_work)
        self.assertIsNone(r.lease)
        self.assertIsNone(self.native.leases.current(self.native.config.runtime_identity))
        self.assertIn(modern.CHECKPOINT_HISTORY_CAPACITY_EXHAUSTED,
                      r.health(self.native.clock.now()).health_flags)

    def last_slot_between_precheck_and_store(self, *, prepared):
        self.small_limit()
        r = self.native.runtime
        proposed = successor(self.publication)
        prior = inventory(self.publication.root)
        original_save = self.store.save

        def interleaved_save(*args, **kwargs):
            if prepared:
                raw = proposed.to_bytes()
                self.publication.pending.write_bytes(modern.canonical_bytes({
                    "snapshotId": proposed.snapshot_id, "payloadSha256": modern.digest(raw),
                    "snapshot": raw.decode("ascii")}))
            else:
                self.publication.publish(proposed,
                    expected_previous=self.publication.current().snapshot_id)
            return original_save(*args, **kwargs)

        with patch.object(self.store, "save", side_effect=interleaved_save):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r._checkpoint(self.native.clock.now())
        self.assert_runtime_capacity_blocked()
        self.assertEqual(self.publication.current(), proposed)
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 3)
        self.assertEqual(self.load(), self.payload)
        after = inventory(self.publication.root)
        self.assertEqual({k: v for k, v in after.items() if k not in {
            "current.json", proposed.snapshot_id + ".json"}},
            {k: v for k, v in prior.items() if k != "current.json"})
        self.assertFalse(self.publication.pending.exists())
        for _ in range(2):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r._checkpoint(self.native.clock.now())
            self.assertEqual(inventory(self.publication.root), after)

    def test_last_slot_direct_publisher_interleave_latches_runtime_failure(self):
        self.last_slot_between_precheck_and_store(prepared=False)

    def test_last_slot_prepared_journal_interleave_latches_runtime_failure(self):
        self.last_slot_between_precheck_and_store(prepared=True)

    def test_last_slot_during_eligibility_update_does_not_return_active(self):
        self.small_limit()
        r = self.native.runtime
        original_require = r._require_checkpoint_capacity
        calls = 0

        def interleaved_require():
            nonlocal calls
            calls += 1
            original_require()
            if calls == 1:
                self.publication.publish(successor(self.publication),
                    expected_previous=self.publication.current().snapshot_id)

        with patch.object(r, "_require_checkpoint_capacity", side_effect=interleaved_require):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r.set_session_eligibility(not r._session_work_eligible, self.native.clock.now())
        self.assert_runtime_capacity_blocked()
        self.assertEqual(self.load(), self.payload)
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 3)

    def test_unsupported_existing_history_is_not_truncated_or_adopted(self):
        self.store.save(self.native.config.runtime_identity, self.payload)
        before = inventory(self.publication.root)
        self.small_limit(2)
        with self.assertRaises(modern.ModernOperationalError) as raised:
            self.load()
        self.assertEqual(raised.exception.diagnostic_code, "BLOCK_RECONCILIATION_REQUIRED")
        self.assertEqual(inventory(self.publication.root), before)

    def test_unsupported_prepared_journal_is_not_promoted(self):
        self.exhausted()
        proposed = successor(self.publication)
        raw = proposed.to_bytes()
        self.publication.pending.write_bytes(modern.canonical_bytes({
            "snapshotId": proposed.snapshot_id, "payloadSha256": modern.digest(raw),
            "snapshot": raw.decode("ascii")}))
        before = inventory(self.publication.root)
        with self.assertRaises(modern.ModernOperationalError) as raised:
            self.load()
        self.assertEqual(raised.exception.diagnostic_code, "BLOCK_RECONCILIATION_REQUIRED")
        self.assertEqual(inventory(self.publication.root), before)

    def test_actual_4095_4096_4097_4098_native_boundary(self):
        # Accelerate only setup with the native immutable publisher; test real store/restore.
        current = self.publication.current()
        while modern.parse_bytes(current.manifest_bytes)["sequence"] < 4094:
            proposed = successor(self.publication)
            self.publication.publish(proposed, expected_previous=current.snapshot_id)
            current = proposed
        self.assertEqual(len(integrity.complete_publication_history(self.publication)), 4094)
        self.store.save(self.native.config.runtime_identity, self.payload)
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 4095)
        self.assertEqual(self.load(), self.payload)
        with self.assertRaises(modern.CheckpointHistoryCapacityError):
            recovery.restore(self.native, "real-4095-to-4096")
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 4096)
        self.assertEqual(self.load()["runtime_instance_id"], "real-4095-to-4096")
        self.assertIsNone(self.native.leases.current(self.native.config.runtime_identity))
        before = inventory(self.publication.root)
        for offset in (1, 2):
            proposed = successor(self.publication, offset=offset)
            self.assertEqual(modern.parse_bytes(proposed.manifest_bytes)["sequence"], 4096 + offset)
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                self.publication.publish(proposed, expected_previous=self.publication.current().snapshot_id)
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                self.store.save(self.native.config.runtime_identity, self.payload)
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                recovery.restore(self.native, f"real-blocked-{offset}")
            self.assertEqual(inventory(self.publication.root), before)
            self.assertEqual(self.load()["runtime_instance_id"], "real-4095-to-4096")
        self.assertFalse(self.publication.pending.exists())


if __name__ == "__main__":
    unittest.main()
