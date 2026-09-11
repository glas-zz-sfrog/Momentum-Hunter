"""Native synthetic coherence tests; no production paths/provider capability."""
import mmap
import os
from pathlib import Path
import tempfile
import unittest

from momentum_hunter.strategy_science_recorder.verified_reads import VerifiedReads, VerifiedReadError


@unittest.skipUnless(os.name == "nt", "Native Windows R-oplock prototype")
class VerifiedReadsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="science-scaling003-")
        self.root = Path(self.temporary.name)
        self.raw = self.root / "evidence.raw"
        self.raw.write_bytes(b"original raw bytes")
        self.cache = VerifiedReads(self.root)

    def tearDown(self):
        self.cache.close()
        self.temporary.cleanup()

    def test_unchanged_bytes_read_once_but_metadata_is_audited(self):
        for _ in range(3):
            with self.cache.operation():
                self.assertEqual(self.cache.read(self.raw), b"original raw bytes")
        self.assertEqual(self.cache.counters["raw_file_reads"], 1)
        self.assertEqual(self.cache.counters["cache_hits"], 2)
        self.assertGreater(self.cache.counters["metadata_checks"], 0)

    def test_same_size_write_restored_time_fails_without_poll(self):
        self.cache.read(self.raw)
        old = self.raw.stat()
        self.raw.write_bytes(b"changed! raw bytes")
        os.utime(self.raw, ns=(old.st_atime_ns, old.st_mtime_ns))
        with self.assertRaises(VerifiedReadError):
            self.cache.read(self.raw)

    def test_truncation_fails_without_poll(self):
        self.cache.read(self.raw)
        self.raw.write_bytes(b"partial")
        with self.assertRaises(VerifiedReadError):
            self.cache.audit_known()

    def test_deleted_file_fails_without_poll(self):
        self.cache.read(self.raw)
        self.raw.unlink()
        with self.assertRaises((VerifiedReadError, OSError)):
            self.cache.audit_known()

    def test_replaced_file_fails_even_with_equal_bytes(self):
        self.cache.read(self.raw)
        self.raw.rename(self.root / "renamed.raw")
        self.raw.write_bytes(b"original raw bytes")
        with self.assertRaises(VerifiedReadError):
            self.cache.audit_known()

    def test_outside_hardlink_requires_and_fails_metadata_audit(self):
        self.cache.read(self.raw)
        with tempfile.TemporaryDirectory(prefix="science-outside-alias-") as external:
            os.link(self.raw, Path(external) / "alias.raw")
            with self.assertRaises(VerifiedReadError):
                self.cache.audit_known()

    def test_new_writable_mapping_breaks_before_cached_read(self):
        self.cache.read(self.raw)
        with self.raw.open("r+b") as stream, mmap.mmap(stream.fileno(), 0) as mapping:
            mapping[0:1] = b"X"
            with self.assertRaises(VerifiedReadError):
                self.cache.read(self.raw)

    def test_prior_writable_mapping_refuses_cache_without_fallback(self):
        with self.raw.open("r+b") as stream, mmap.mmap(stream.fileno(), 0):
            with self.assertRaisesRegex(VerifiedReadError, "not granted"):
                self.cache.read(self.raw)
        with self.assertRaises(VerifiedReadError):
            self.cache.read(self.raw)

    def test_mutation_during_operation_fails_return_boundary(self):
        self.cache.read(self.raw)
        with self.assertRaises(VerifiedReadError):
            with self.cache.operation():
                self.raw.write_bytes(b"changed")

    def test_restart_discards_cache_and_reads_actual_surviving_bytes(self):
        self.cache.read(self.raw)
        self.cache.close()
        self.raw.write_bytes(b"changed")
        self.cache = VerifiedReads(self.root)
        # This is ONLY a raw read cache: the owner must validate raw hash chains.
        self.assertEqual(self.cache.read(self.raw), b"changed")

    def test_closed_cache_cannot_issue_success(self):
        self.cache.read(self.raw)
        self.cache.close()
        with self.assertRaises(VerifiedReadError):
            self.cache.read(self.raw)

    def test_parent_append_changes_mtime_but_not_parent_identity(self):
        parent = self.root/'nested'
        parent.mkdir()
        original = parent/'first.raw'
        original.write_bytes(b'first')
        with self.cache.operation():
            self.assertEqual(b'first',self.cache.read(original))
        (parent/'second.raw').write_bytes(b'second')
        with self.cache.operation():
            self.assertEqual(b'first',self.cache.read(original))

    def test_parent_replacement_is_prevented_or_rejected_at_scope_boundary(self):
        parent = self.root/'nested'
        parent.mkdir()
        original = parent/'first.raw'
        original.write_bytes(b'first')
        self.cache.read(original)
        try:
            parent.rename(self.root/'old-parent')
        except PermissionError:
            # Windows may prevent moving a directory with an open descendant.
            # This proves prevention for this probe, not a performed replacement.
            with self.cache.operation():
                self.assertEqual(b'first',self.cache.read(original))
            self.assertFalse((self.root/'old-parent').exists())
            return
        parent.mkdir()
        (parent/'first.raw').write_bytes(b'first')
        with self.assertRaises(VerifiedReadError):
            with self.cache.operation():
                self.cache.read(original)


if __name__ == "__main__":
    unittest.main()
