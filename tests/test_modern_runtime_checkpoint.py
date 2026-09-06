from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_modern_operational import EpochFixture
from tests.test_continuous_runtime import RuntimeFixture
from momentum_hunter import continuous_runtime as runtime_module
from momentum_hunter import modern_operational as modern


class ModernRuntimeCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mh-modern-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.native = RuntimeFixture(self.root / "research")
        self.cutover = EpochFixture(self.root, configuration=self.native.config.fingerprint)
        self.addCleanup(self.cutover.patch.stop)
        self.cutover.start()
        self.native.store = runtime_module.RuntimeCheckpointStore(
            self.cutover.root / "runtime", operational_epoch=self.cutover.epoch,
            runtime_config=self.native.config)
        self.native.runtime = self.native.new_runtime("modern-1")

    def start_with_work(self):
        self.native.runtime.start(self.native.clock.now())
        self.native.runtime.request_discovery(self.native.clock.now())
        self.native.runtime._checkpoint(self.native.clock.now())

    def test_current_modern_runtime_checkpoint_and_queue_roundtrip(self):
        self.start_with_work()
        checkpoint = self.native.store.load(self.native.config.runtime_identity)
        self.assertEqual(checkpoint["operationalEpochId"], self.cutover.epoch.epoch_id)
        works = [item for queue in checkpoint["queues"].values() for item in queue]
        self.assertTrue(works)
        for item in works:
            runtime_module._restore_work(item, self.cutover.epoch, self.native.config.runtime_identity)
        self.native.clock.advance(31)
        restored = runtime_module.ContinuousOpportunityRuntime.restore(
            config=self.native.config, runtime_instance_id="modern-2", now=self.native.clock.now(),
            discovery_source=self.native.discovery, market_data_source=self.native.market,
            event_source=self.native.events, composition_source=self.native.composer,
            denominator_source=self.native.denominator, writer=self.native.writer,
            lease_registry=self.native.leases, checkpoint_store=self.native.store)
        self.assertEqual(restored.started_at, self.native.runtime.started_at)
        self.assertEqual(restored._queues[runtime_module.DISCOVERY_QUEUE].snapshot(),
                         self.native.runtime._queues[runtime_module.DISCOVERY_QUEUE].snapshot())

    def test_04_old_checkpoint_is_not_adopted_or_deleted(self):
        path = self.native.store.path_for(self.native.config.runtime_identity)
        old = b'{"checkpoint_schema_version":2}'
        path.write_bytes(old)
        with self.assertRaises(runtime_module.RuntimeCheckpointError):
            self.native.new_runtime("legacy-restore")
        with self.assertRaises(runtime_module.RuntimeCheckpointError):
            self.native.store.load(self.native.config.runtime_identity)
        self.assertEqual(path.read_bytes(), old)

    def test_05_old_queue_cannot_hide_inside_current_checkpoint(self):
        self.start_with_work()
        payload = self.native.store.load(self.native.config.runtime_identity)
        old = runtime_module.build_work(kind="DISCOVERY", key="old", priority=1,
            requested_at=self.native.clock.now().isoformat(), payload={"old": "decision"})
        payload["queues"][runtime_module.DISCOVERY_QUEUE] = [asdict(old)]
        before = self.native.store.publication.pointer.read_bytes()
        with self.assertRaises(runtime_module.RuntimeCheckpointError):
            self.native.store.save(self.native.config.runtime_identity, payload)
        self.assertEqual(self.native.store.publication.pointer.read_bytes(), before)

    def test_old_direct_enqueue_is_rejected_not_retagged(self):
        self.native.runtime.start(self.native.clock.now())
        work = runtime_module.build_work(kind="DISCOVERY", key="old", priority=1,
            requested_at=self.native.clock.now().isoformat(), payload={})
        with self.assertRaises(runtime_module.RuntimeCheckpointError):
            self.native.runtime._enqueue(runtime_module.DISCOVERY_QUEUE, work, self.native.clock.now())

    def test_current_checkpoint_cannot_silently_restart_as_fresh(self):
        self.start_with_work()
        self.native.clock.advance(31)
        other = self.native.new_runtime("another")
        with self.assertRaisesRegex(runtime_module.RuntimeCheckpointError, "exact restore"):
            other.start(self.native.clock.now())

    def test_mutated_snapshot_cannot_resume(self):
        self.start_with_work()
        publication = self.native.store.publication
        current = publication.current()
        path = publication.root / (current.snapshot_id + ".json")
        before = path.read_bytes()
        path.write_bytes(before + b" ")
        with self.assertRaises(modern.ModernOperationalError):
            self.native.store.load(self.native.config.runtime_identity)
        self.assertEqual(path.read_bytes(), before + b" ")
