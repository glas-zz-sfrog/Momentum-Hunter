"""Worker delivery suppression is not a cached custody admission result."""
from dataclasses import replace
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from momentum_hunter.science_custody_commit import (
    CustodyCommitError, CustodyCommitIntegrityError, ScienceCustodyFinalizer,
    completion_path,
)
from momentum_hunter.science_custody_mailbox import (
    REQUEST_NAME, ScienceCustodyMailboxClient, ScienceCustodyMailboxWriter,
)
from momentum_hunter.windows_science_custody import _WriterChannel
from momentum_hunter import windows_science_custody as native_module
from tests.test_science_custody_commit_007 import MemoryBackend, arrival
from tests.test_science_custody_windows_007 import NativeDouble, policy


class WorkerDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        clock = patch("momentum_hunter.science_custody_mailbox.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.backend = MemoryBackend()
        self.client = ScienceCustodyMailboxClient(
            policy_sha256=self.backend.policy_sha256,
            source_root_identity=self.backend.source_root_identity,
            mailbox_backend=self.backend)
        self.finalizer = ScienceCustodyFinalizer(self.backend)
        self.finalizer.finalize = Mock(wraps=self.finalizer.finalize)
        self.mailbox = ScienceCustodyMailboxWriter(self.finalizer, mailbox_backend=self.backend)
        self.channel = _WriterChannel(self.backend, self.mailbox)

    def submit(self, sequence=1):
        path, raw = arrival(sequence)
        return self.client.submit(final_root="arrivals", relative_path=path, raw=raw)

    def test_native_worker_has_no_new_work_for_exact_completed_request(self):
        pending = self.submit()
        first = self.channel.poll_once()
        self.assertTrue(first.created)
        request_reads = Mock(wraps=self.backend.read_request)
        self.backend.read_request = request_reads
        for _ in range(12):
            self.assertIsNone(self.channel.poll_once())
        self.assertEqual(1, self.finalizer.finalize.call_count)
        self.assertEqual(12, request_reads.call_count)
        self.assertEqual([], self.backend.deleted)
        self.assertIn(("requests", REQUEST_NAME), self.backend.objects)
        self.client.acknowledge(pending, self.client.reconcile(pending))

    def test_explicit_duplicate_reconciliation_keeps_full_fresh_result(self):
        self.submit()
        first = self.mailbox.poll_once()
        duplicate = self.mailbox.poll_once()
        self.assertEqual(first.receipt, duplicate.receipt)
        self.assertFalse(duplicate.created)
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_new_request_file_identity_requires_fresh_finalization(self):
        pending = self.submit()
        first = self.channel.poll_once()
        self.backend._new("requests", REQUEST_NAME, pending.request.to_bytes())
        duplicate = self.channel.poll_once()
        self.assertEqual(first.receipt, duplicate.receipt)
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_changed_request_security_is_not_same_observation(self):
        self.submit()
        self.channel.poll_once()
        key = "requests", REQUEST_NAME
        self.backend.objects[key] = replace(self.backend.objects[key], descriptor_sha256="d" * 64)
        self.assertIsNotNone(self.channel.poll_once())
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_changed_bytes_and_extra_unknown_slot_are_not_suppressed(self):
        self.submit()
        self.channel.poll_once()
        key = "requests", REQUEST_NAME
        original = self.backend.objects[key]
        self.backend.objects[key] = replace(original, raw=b"not a protocol request")
        with self.assertRaises(CustodyCommitError):
            self.channel.poll_once()
        self.backend.objects[key] = original
        self.backend._new("requests", "unknown.json", b"{}")
        with self.assertRaises(CustodyCommitIntegrityError):
            self.channel.poll_once()

    def test_new_generation_after_ack_and_process_restart_reconciles(self):
        pending = self.submit()
        self.channel.poll_once()
        self.client.acknowledge(pending, self.client.reconcile(pending))
        self.submit(2)
        self.assertIsNotNone(self.channel.poll_once())
        restarted = _WriterChannel(self.backend,
            ScienceCustodyMailboxWriter(self.finalizer, mailbox_backend=self.backend))
        self.assertIsNotNone(restarted.poll_once())
        self.assertEqual(3, self.finalizer.finalize.call_count)

    def test_empty_slot_discards_delivery_observation(self):
        self.submit()
        self.channel.poll_once()
        key = "requests", REQUEST_NAME
        original = self.backend.objects.pop(key)
        self.assertIsNone(self.channel.poll_once())
        self.backend.objects[key] = original
        self.assertIsNotNone(self.channel.poll_once())
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_missing_fresh_request_read_is_idle_then_requires_full_work(self):
        self.submit()
        self.channel.poll_once()
        original = self.backend.read_request
        self.backend.read_request = Mock(side_effect=FileNotFoundError())
        self.assertIsNone(self.channel.poll_once())
        self.backend.read_request = original
        self.assertIsNotNone(self.channel.poll_once())
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_failed_finalization_is_never_marked_delivered(self):
        self.submit()
        self.finalizer._fault_hook = lambda phase: (
            (_ for _ in ()).throw(RuntimeError("interrupted")) if phase == "after_claim" else None)
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.channel.poll_once()
        self.finalizer._fault_hook = None
        self.assertIsNotNone(self.channel.poll_once())
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_no_new_work_never_admits_changed_committed_bytes(self):
        pending = self.submit()
        self.channel.poll_once()
        key = pending.request.final_root, pending.request.final_relative_path
        self.backend.objects[key] = replace(self.backend.objects[key], raw=b"corrupt")
        self.assertIsNone(self.channel.poll_once())
        with self.assertRaises(CustodyCommitIntegrityError):
            self.client.reconcile(pending)
        with self.assertRaises(CustodyCommitIntegrityError):
            self.mailbox.poll_once()
        self.assertEqual([], self.backend.deleted)

    def test_unchanged_slot_full_recheck_deadline_does_not_slide(self):
        self.submit()
        self.channel.poll_once()
        for tick in (0.1, 0.5, 0.99):
            self.now = tick
            self.assertIsNone(self.channel.poll_once())
        self.now = 1.0
        self.assertIsNotNone(self.channel.poll_once())
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_missing_completion_is_recovered_without_a_changed_request(self):
        pending = self.submit()
        self.channel.poll_once()
        key = "receipts", completion_path(pending.request.identity.digest())
        del self.backend.objects[key]
        self.assertIsNone(self.channel.poll_once())
        self.assertIsNone(self.client.reconcile(pending))
        self.now = 1.0
        self.assertIsNotNone(self.channel.poll_once())
        self.assertIsNotNone(self.client.reconcile(pending))
        self.assertEqual([], self.backend.deleted)

    def test_idle_trusted_object_drift_fails_by_full_recheck(self):
        pending = self.submit()
        self.channel.poll_once()
        key = pending.request.final_root, pending.request.final_relative_path
        self.backend.objects[key] = replace(self.backend.objects[key], owner_sid="S-1-5-18")
        self.now = 1.0
        with self.assertRaises(CustodyCommitIntegrityError):
            self.channel.poll_once()

    def test_transient_read_error_clears_suppression(self):
        self.submit()
        self.channel.poll_once()
        original = self.backend.read_request
        self.backend.read_request = Mock(side_effect=PermissionError("read failed"))
        with self.assertRaises(PermissionError):
            self.channel.poll_once()
        self.backend.read_request = original
        self.assertIsNotNone(self.channel.poll_once())
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_deadline_is_checked_after_slow_fresh_slot_read(self):
        self.submit()
        self.channel.poll_once()
        original = self.backend.read_request
        def slow(*args, **kwargs):
            self.now = 1.1
            return original(*args, **kwargs)
        self.backend.read_request = slow
        self.assertIsNotNone(self.channel.poll_once())
        self.assertEqual(2, self.finalizer.finalize.call_count)

    def test_close_discards_nonauthoritative_scheduling_memory(self):
        self.submit()
        self.channel.poll_once()
        self.channel.close()
        self.assertTrue(self.backend.closed)
        self.assertIsNone(self.mailbox._delivered_request)


class NativePollBoundaryTests(unittest.TestCase):
    """Primitive double only: not a physical token/ACL acceptance claim."""
    def setUp(self):
        p = policy()
        self.native = NativeDouble(p, "writer")
        with patch.object(native_module, "_Native", return_value=self.native):
            self.backend = native_module.WindowsScienceCustodyBackend(p, role="writer")
        self.addCleanup(self.backend.close)
        memory = MemoryBackend()
        memory.policy_sha256 = p.policy_sha256
        memory.source_root_identity = p.source_root_identity
        client = ScienceCustodyMailboxClient(policy_sha256=p.policy_sha256,
            source_root_identity=p.source_root_identity, mailbox_backend=memory)
        path, raw = arrival()
        request = client.submit(final_root="arrivals", relative_path=path, raw=raw).request
        self.native.add(self.backend.namespace_root("requests") / REQUEST_NAME,
                        kind="transport", raw=request.to_bytes())
        self.finalizer = ScienceCustodyFinalizer(self.backend)
        self.finalizer.finalize = Mock(return_value=object())
        self.mailbox = ScienceCustodyMailboxWriter(self.finalizer, mailbox_backend=self.backend)
        self.channel = _WriterChannel(self.backend, self.mailbox)
        self.after_names = lambda path: None
        def scandir(path):
            names = [SimpleNamespace(name=obj.path.name) for obj in self.native.objects.values()
                     if obj.path.parent == Path(path)]
            self.after_names(Path(path))
            return nullcontext(iter(names))
        scan = patch.object(native_module.os, "scandir", side_effect=scandir)
        scan.start()
        self.addCleanup(scan.stop)
        self.backend.enable_qualification_pin_timing()

    def test_grouped_poll_keeps_two_full_and_three_fresh_scoped_boundaries(self):
        self.channel.poll_once()
        timing = self.backend.qualification_pin_timing()
        self.assertEqual(2, timing["full_checks"])
        self.assertEqual(3, timing["scoped_read_checks"])
        self.assertEqual(1, self.finalizer.finalize.call_count)

    def test_request_root_drift_blocks_before_request_bytes(self):
        root = self.backend.namespace_root("requests")
        def drift(path):
            if path == self.backend.namespace_root("staging"):
                self.native.objects[native_module._path_key(root)].identity = (9, 9, 9)
        self.after_names = drift
        with self.assertRaises(native_module.ScienceCustodyNativeError):
            self.channel.poll_once()
        self.assertFalse(any(p.name == REQUEST_NAME for p, _ in self.native.opens))
        self.finalizer.finalize.assert_not_called()

    def test_actor_drift_between_enumerations_blocks_finalizer(self):
        def drift(path):
            if path == self.backend.namespace_root("requests"):
                self.native.token_override = {**self.native.token(), "owner": "S-1-5-18"}
        self.after_names = drift
        with self.assertRaises(native_module.ScienceCustodyNativeError):
            self.channel.poll_once()
        self.finalizer.finalize.assert_not_called()

    def test_cross_root_drift_on_return_invalidates_completed_scheduling_state(self):
        def finalizer(_request):
            root = self.backend.namespace_root("custody")
            self.native.objects[native_module._path_key(root)].identity = (9, 9, 9)
            return object()
        self.finalizer.finalize.side_effect = finalizer
        with self.assertRaises(native_module.ScienceCustodyNativeError):
            self.channel.poll_once()
        self.assertIsNone(self.mailbox._delivered_request)
        self.assertTrue(self.backend._invalidated)


if __name__ == "__main__":
    unittest.main()
