"""Pure bounded mailbox tests; no account/token/Windows authority is claimed."""

from dataclasses import replace
import unittest

from momentum_hunter.science_custody_commit import (
    CustodyCommitConflict, CustodyCommitError, CustodyCommitIntegrityError,
    CustodyCommitPending, ScienceCustodyFinalizer, receipt_path, sha256,
)
from momentum_hunter.science_custody_mailbox import (
    REQUEST_NAME, ScienceCustodyMailboxClient, ScienceCustodyMailboxWriter,
)
from tests.test_science_custody_commit_007 import MemoryBackend, arrival


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.backend = MemoryBackend()
        self.client = self.new_client()
        self.writer = ScienceCustodyMailboxWriter(ScienceCustodyFinalizer(self.backend), mailbox_backend=self.backend)

    def new_client(self, **kwargs):
        return ScienceCustodyMailboxClient(policy_sha256=self.backend.policy_sha256,
            source_root_identity=self.backend.source_root_identity, mailbox_backend=self.backend, **kwargs)

    def submit(self, client=None, *, sequence=1, text="original", **kwargs):
        path, raw = arrival(sequence, text)
        return (client or self.client).submit(final_root="arrivals", relative_path=path, raw=raw, **kwargs)

    def test_one_outstanding_requires_explicit_ack_after_receipt(self):
        pending = self.submit()
        self.assertIsNone(self.client.reconcile(pending))
        with self.assertRaises(CustodyCommitPending):
            self.submit(sequence=2)
        self.writer.poll_once()
        result = self.client.reconcile(pending)
        self.assertIsNotNone(result)
        self.assertIn(("requests", REQUEST_NAME), self.backend.objects)
        with self.assertRaises(CustodyCommitPending):
            self.submit(sequence=2)
        self.client.acknowledge(pending, result)
        self.assertNotIn(("requests", REQUEST_NAME), self.backend.objects)
        self.submit(sequence=2)

    def test_writer_never_cleans_transport_and_duplicate_poll_does_not_republish(self):
        pending = self.submit()
        original = self.writer.poll_once()
        duplicate = self.writer.poll_once()
        self.assertEqual(original.receipt, duplicate.receipt)
        self.assertTrue(original.created)
        self.assertFalse(duplicate.created)
        self.assertEqual([], self.backend.deleted)
        self.assertIn(("staging", pending.request.staging_name), self.backend.objects)

    def test_old_slot_completion_cannot_ack_new_generation(self):
        old = self.submit()
        self.writer.poll_once()
        old_result = self.client.reconcile(old)
        self.client.acknowledge(old, old_result)
        new = self.submit(sequence=2)
        self.writer.poll_once()
        with self.assertRaises(CustodyCommitConflict):
            self.client.acknowledge(old, old_result)
        self.assertEqual(new.request_file_identity, self.backend.objects["requests", REQUEST_NAME].file_identity)

    def test_same_path_same_bytes_new_request_object_is_aba_and_rejected(self):
        pending = self.submit()
        self.writer.poll_once()
        result = self.client.reconcile(pending)
        self.backend._new("requests", REQUEST_NAME, pending.request.to_bytes())
        with self.assertRaises(CustodyCommitConflict):
            self.client.acknowledge(pending, result)

    def test_changed_stage_identity_blocks_cleanup_even_with_same_bytes(self):
        pending = self.submit()
        self.writer.poll_once()
        result = self.client.reconcile(pending)
        key = "staging", pending.request.staging_name
        self.backend._new(*key, self.backend.objects[key].raw)
        with self.assertRaises(CustodyCommitConflict):
            self.client.acknowledge(pending, result)
        self.assertIn(("requests", REQUEST_NAME), self.backend.objects)

    def test_crash_after_receipt_before_any_cleanup_recovers_exact_transport(self):
        original = self.submit()
        self.writer.poll_once()
        restarted = self.new_client()
        pending = restarted.recover_pending()
        self.assertEqual(original, pending)
        restarted.acknowledge(pending, restarted.reconcile(pending))
        self.assertIsNone(restarted.recover_pending())

    def test_restart_rejects_replaced_original_stage_even_if_bytes_match(self):
        pending = self.submit()
        self.writer.poll_once()
        key = "staging", pending.request.staging_name
        self.backend._new(*key, self.backend.objects[key].raw)
        with self.assertRaises(CustodyCommitConflict):
            self.new_client().recover_pending()

    def test_crash_after_stage_cleanup_before_request_cleanup_recovers(self):
        def crash(phase):
            if phase == "after_stage_cleanup":
                raise RuntimeError("crash")
        client = self.new_client(fault_hook=crash)
        pending = self.submit(client)
        self.writer.poll_once()
        with self.assertRaises(RuntimeError):
            client.acknowledge(pending, client.reconcile(pending))
        self.assertNotIn(("staging", pending.request.staging_name), self.backend.objects)
        restarted = self.new_client()
        recovered = restarted.recover_pending()
        self.assertIsNone(recovered.staging_file_identity)
        restarted.acknowledge(recovered, restarted.reconcile(recovered))
        self.assertIsNone(restarted.recover_pending())

    def test_missing_stage_without_receipt_stays_pending(self):
        pending = self.submit()
        del self.backend.objects["staging", pending.request.staging_name]
        with self.assertRaises(CustodyCommitPending):
            self.new_client().recover_pending()
        self.assertIn(("requests", REQUEST_NAME), self.backend.objects)

    def test_receipt_for_other_commit_cannot_ack_pending(self):
        first = self.submit()
        self.writer.poll_once()
        old_result = self.client.reconcile(first)
        self.client.acknowledge(first, old_result)
        second = self.submit(sequence=2)
        self.writer.poll_once()
        with self.assertRaises(CustodyCommitIntegrityError):
            self.client.acknowledge(second, old_result)

    def test_receipt_mutation_blocks_readback_and_cleanup(self):
        pending = self.submit()
        self.writer.poll_once()
        path = receipt_path(pending.request.identity.digest())
        receipt = self.backend.objects["receipts", path]
        self.backend.objects["receipts", path] = replace(receipt, raw=b"{}\n")
        with self.assertRaises(CustodyCommitError):
            self.client.reconcile(pending)
        self.assertEqual([], self.backend.deleted)

    def test_unknown_name_flood_stops_after_capacity_plus_sentinel(self):
        for i in range(50):
            self.backend._new("requests", f"unknown-{i}", b"x")
        with self.assertRaises(CustodyCommitIntegrityError):
            self.writer.poll_once()
        self.assertEqual(("requests", 2), self.backend.enumeration_limits[-1])

    def test_oversized_staged_bytes_are_rejected_without_claim(self):
        pending = self.submit()
        key = "staging", pending.request.staging_name
        self.backend.objects[key] = replace(self.backend.objects[key], raw=b"x" * (self.backend.max_artifact_bytes + 1))
        with self.assertRaises(CustodyCommitError):
            self.writer.poll_once()
        self.assertFalse(any(k[0] == "claims" for k in self.backend.objects))

    def test_staging_crash_requires_explicit_honestly_timed_orphan_receipt(self):
        with self.assertRaises(CustodyCommitPending):
            self.submit(crash_after_stage=True)
        self.assertIsNone(self.client.recover_pending())
        with self.assertRaises(CustodyCommitPending):
            self.submit()
        orphan, = self.client.orphaned_staging()
        self.assertEqual(sha256(arrival()[1]), orphan.sha256)
        pending = self.client.submit_orphan_receipt(orphan, observed_at="2026-09-15T16:00:00Z")
        self.assertEqual(2, sum(k[0] == "staging" for k in self.backend.objects))
        self.writer.poll_once()
        result = self.client.reconcile(pending)
        raw = self.backend.objects["custody", pending.request.final_relative_path].raw
        self.assertIn(b"ABANDONED_STAGING_NOT_ADMITTED", raw)
        self.assertIn(b"2026-09-15T16:00:00Z", raw)
        self.assertNotIn(b"original_capture", raw)
        self.client.acknowledge(pending, result)
        self.assertEqual((), self.client.orphaned_staging())
        self.assertFalse(any(k[0] == "arrivals" for k in self.backend.objects))

    def test_orphan_changed_after_metadata_receipt_is_not_deleted(self):
        with self.assertRaises(CustodyCommitPending):
            self.submit(crash_after_stage=True)
        orphan, = self.client.orphaned_staging()
        pending = self.client.submit_orphan_receipt(orphan, observed_at="2026-09-15T16:00:00Z")
        self.writer.poll_once()
        result = self.client.reconcile(pending)
        self.backend._new("staging", orphan.staging_name, b"new generation content")
        with self.assertRaises(CustodyCommitConflict):
            self.client.acknowledge(pending, result)
        self.assertIn(("requests", REQUEST_NAME), self.backend.objects)

    def test_completed_orphan_receipt_stage_before_request_reuses_exact_bytes(self):
        with self.assertRaises(CustodyCommitPending):
            self.submit(crash_after_stage=True)
        orphan, = self.client.orphaned_staging()
        def crash(phase):
            if phase == "after_stage":
                raise RuntimeError("crash")
        client = self.new_client(fault_hook=crash)
        with self.assertRaises(RuntimeError):
            client.submit_orphan_receipt(orphan, observed_at="2026-09-15T16:00:00Z")
        self.assertFalse(any(k[0] == "requests" for k in self.backend.objects))
        restarted = self.new_client()
        pending = restarted.recover_pending()
        self.writer.poll_once()
        result = restarted.reconcile(pending)
        self.assertIn(b"2026-09-15T16:00:00Z", self.backend.objects["custody", pending.request.final_relative_path].raw)
        restarted.acknowledge(pending, result)
        self.assertEqual((), restarted.orphaned_staging())

    def test_crash_after_orphan_delete_before_own_stage_delete_recovers(self):
        with self.assertRaises(CustodyCommitPending):
            self.submit(crash_after_stage=True)
        orphan, = self.client.orphaned_staging()
        def crash(phase):
            if phase == "after_orphan_cleanup":
                raise RuntimeError("crash")
        client = self.new_client(fault_hook=crash)
        pending = client.submit_orphan_receipt(orphan, observed_at="2026-09-15T16:00:00Z")
        self.writer.poll_once()
        with self.assertRaises(RuntimeError):
            client.acknowledge(pending, client.reconcile(pending))
        restarted = self.new_client()
        pending = restarted.recover_pending()
        restarted.acknowledge(pending, restarted.reconcile(pending))
        self.assertEqual((), restarted.orphaned_staging())

    def test_no_request_is_no_work_and_no_history_scan(self):
        for i in range(100):
            self.backend._new("receipts", f"historical-{i}", b"history")
        self.assertIsNone(self.writer.poll_once())
        self.assertEqual([], self.backend.reads)
        self.assertEqual([("requests", 2), ("staging", 3)], self.backend.enumeration_limits)


if __name__ == "__main__":
    unittest.main()
