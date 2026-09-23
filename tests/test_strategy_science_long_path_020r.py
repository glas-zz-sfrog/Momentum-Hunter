"""Focused Windows long-path custody checks; disposable local objects only."""

import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from momentum_hunter.strategy_science_recorder.custody import StrategyScienceRecorder
from momentum_hunter.strategy_science_recorder.reusable_views import ReusableViews
from momentum_hunter.strategy_science_recorder.verified_reads import (
    VerifiedReadError,
    VerifiedReads,
    _directory_identity,
    _identity,
    _logical_path,
    _operation_path,
)


@unittest.skipUnless(os.name == "nt", "Windows long-path custody boundary")
class LongPathCustodyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="argus-020r-custody-"))
        suffix = Path(
            "science", "custody", "sessions", "2026-08-27",
            "s-c33638b3b37e35bb66884e4b2168a3a3a17f1066bb4f162468e0eab942dc558b",
            "sources", "export",
            "faff368f975a30b42d5e9770c6ec0cc991b380d903c41f2bb868ae2e4234f46a",
        )
        padding = 262 - len(str(self.root)) - len(str(suffix)) - 2
        self.assertGreater(padding, 0)
        self.custody_root = self.root / ("p" * padding) / "science" / "custody"
        self.parent = self.custody_root / Path(*suffix.parts[2:])
        self.assertEqual(len(str(self.parent)), 262)
        _operation_path(self.parent).mkdir(parents=True)
        self.raw = self.parent / "source.source.json"
        _operation_path(self.raw).write_bytes(b"committed custody bytes")
        self.cache = VerifiedReads(self.root, aggregate_content=True)

    def tearDown(self):
        self.cache.close()
        shutil.rmtree(_operation_path(self.root))

    def test_short_path_and_logical_identity_unchanged(self):
        self.assertEqual(_operation_path(self.root), self.root)
        self.assertEqual(_logical_path(_operation_path(self.parent)), self.parent)
        self.assertEqual(_logical_path(_operation_path(self.raw)), self.raw)
        self.assertEqual(_directory_identity(self.parent), _directory_identity(_operation_path(self.parent)))

    def test_extended_unc_is_not_rewritten_as_local_logical_path(self):
        unc = Path(r"\\?\UNC\server\share\custody")
        self.assertEqual(_logical_path(unc), unc)

    def test_long_path_read_preserves_cache_checks_and_logical_keys(self):
        self.assertEqual(self.cache.read(self.raw), b"committed custody bytes")
        self.assertIn(self.raw, self.cache._entries)
        self.assertNotIn(_operation_path(self.raw), self.cache._entries)
        self.assertEqual(self.cache.read(self.raw), b"committed custody bytes")
        self.cache.check_content()
        self.cache.audit_known()

    def test_published_long_path_records_same_directory_identity(self):
        views = ReusableViews(SimpleNamespace(root=self.custody_root))
        try:
            views.published(self.raw.relative_to(self.custody_root))
            self.assertEqual(views.directories[self.parent], _directory_identity(self.parent))
            self.assertNotIn(_operation_path(self.parent), views.directories)
        finally:
            views.close()

    def test_long_child_inventory_keeps_logical_paths(self):
        partition = self.custody_root / "sessions" / "2026-08-27"
        listed = {
            _logical_path(item)
            for item in _operation_path(partition, recursive=True).rglob("*")
        }
        self.assertIn(self.raw, listed)
        self.assertTrue(all(not str(item).startswith("\\\\?\\") for item in listed))

    def test_recorder_relative_identity_is_unprefixed(self):
        recorder = object.__new__(StrategyScienceRecorder)
        recorder._storage = SimpleNamespace(root=self.custody_root)
        self.assertEqual(recorder._relative(self.raw), self.raw.relative_to(self.custody_root).as_posix())

    def test_missing_long_path_rejects(self):
        missing = self.parent / "absent.source.json"
        with self.assertRaises((VerifiedReadError, OSError)):
            self.cache.read(missing)

    def test_changed_object_identity_rejects(self):
        self.cache.read(self.raw)
        alias = self.parent / "renamed.source.json"
        _operation_path(self.raw).rename(_operation_path(alias))
        _operation_path(self.raw).write_bytes(b"committed custody bytes")
        with self.assertRaises(VerifiedReadError):
            self.cache.audit_known()

    def test_hardlink_alias_rejects(self):
        self.cache.read(self.raw)
        os.link(_operation_path(self.raw), self.root / "outside-alias.raw")
        with self.assertRaises(VerifiedReadError):
            self.cache.audit_known()

    def test_content_mutation_invalidates_cache(self):
        self.cache.read(self.raw)
        _operation_path(self.raw).write_bytes(b"mutated custody bytes")
        with self.assertRaises(VerifiedReadError):
            self.cache.check_content()

    def test_reparse_directory_rejects(self):
        reparse = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "stat", return_value=reparse):
            with self.assertRaises(VerifiedReadError):
                _directory_identity(self.parent)

    def test_raw_reparse_or_nonregular_identity_rejects(self):
        with self.assertRaises(VerifiedReadError):
            _identity(self.parent)


if __name__ == "__main__":
    unittest.main()
