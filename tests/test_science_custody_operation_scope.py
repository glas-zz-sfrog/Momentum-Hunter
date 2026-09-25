"""Logical reader boundaries retain current native proofs, not cached admission."""
from dataclasses import replace
from pathlib import Path, PureWindowsPath
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from momentum_hunter import windows_science_custody as custody
from momentum_hunter.science_custody_readonly import SealedScienceStorage
from tests import test_science_custody_exact_proof_reuse as helpers
from tests.test_science_mutable_policy_020g import security


class PurePathKeyTests(unittest.TestCase):
    def test_path_cache_is_bounded_pure_spelling_not_object_identity(self):
        custody._path_text_key.cache_clear()
        for path in ("C:/Mixed/../spelling", "c:\\mixed\\child", "F:/", "relative", "//server/share/a"):
            self.assertEqual(str(PureWindowsPath(path)).casefold(), custody._path_key(path))
        class ChangingPath:
            text = "C:/one"
            def __str__(self):
                return self.text
        value = ChangingPath()
        self.assertEqual("c:\\one", custody._path_key(value))
        value.text = "C:/two"
        self.assertEqual("c:\\two", custody._path_key(value))
        for i in range(2048):
            custody._path_key(f"C:/bounded/{i}")
        self.assertEqual(1024, custody._path_text_key.cache_info().currsize)
        custody._path_text_key.cache_clear()
        self.assertEqual("c:\\" + "x" * 4097, custody._path_key("C:/" + "x" * 4097))
        self.assertEqual(0, custody._path_text_key.cache_info().currsize)


class NativeLogicalOperationTests(unittest.TestCase):
    def setUp(self):
        helper = helpers.ExactValueTests()
        self.addCleanup(helper.doCleanups)
        self.backend, self.native, _ = helper.backend("science")
        self.view = object.__new__(SealedScienceStorage)
        self.view._closed = False
        self.view.storage_set = SimpleNamespace(backend=self.backend, _lock=threading.RLock(),
                                                _ensure_open=lambda: None)
        self.path = self.backend.namespace_root("custody") / "exact.json"
        self.native.add(self.path, raw=b"current").security = security("trusted")
        self.backend.enable_qualification_pin_timing()

    def read(self):
        return self.backend.read_trusted("custody", "exact.json", maximum=100)

    def test_one_operation_groups_full_checks_without_caching_any_read(self):
        read = Mock(wraps=self.native.read)
        self.native.read = read
        with self.view.transaction():
            for _ in range(3):
                with self.backend.transaction():
                    self.assertEqual(b"current", self.read().raw)
        counters = self.backend.qualification_pin_timing()
        self.assertEqual(2, counters["full_checks"])
        self.assertEqual(3, counters["scoped_read_checks"])
        self.assertEqual(3, read.call_count)
        self.assertEqual(0, self.backend._transaction_depth)

    def test_descriptor_reparse_identity_or_token_drift_blocks_before_next_bytes(self):
        for attack in ("descriptor", "reparse", "identity", "token", "policy"):
            with self.subTest(attack=attack):
                self.setUp()
                read = self.native.read = Mock(wraps=self.native.read)
                with self.assertRaises(custody.ScienceCustodyNativeError):
                    with self.view.transaction():
                        self.read()
                        root = self.native.objects[custody._path_key(self.backend.namespace_root("custody"))]
                        if attack == "descriptor":
                            root.security = replace(root.security, owner="S-1-5-18")
                        elif attack == "reparse":
                            root.attributes |= custody.REPARSE
                        elif attack == "identity":
                            root.identity = (99, 99, 99)
                        elif attack == "token":
                            self.native.token_override = {**self.native.token(), "modified_id": (99, 99)}
                        else:
                            object.__setattr__(self.backend.policy, "max_request_bytes", True)
                        self.read()
                self.assertEqual(1, read.call_count)
                self.assertTrue(self.backend._invalidated)

    def test_unrelated_root_drift_rejected_before_authoritative_return(self):
        with self.assertRaises(custody.ScienceCustodyNativeError):
            with self.view.transaction():
                self.read()
                root = self.native.objects[custody._path_key(self.backend.namespace_root("arrivals"))]
                root.identity = (99, 99, 99)
        self.assertTrue(self.backend._invalidated)

    def test_unrelated_root_drift_rejected_before_transport_effect(self):
        before = len(self.native.opens)
        with self.assertRaises(custody.ScienceCustodyNativeError):
            with self.view.transaction():
                root = self.native.objects[custody._path_key(self.backend.namespace_root("arrivals"))]
                root.identity = (99, 99, 99)
                self.backend.create_transport("staging", "a" * 32 + ".stage", b"data")
        self.assertEqual(before, len(self.native.opens))

    def test_current_native_query_failure_is_not_reused_success(self):
        with self.assertRaisesRegex(OSError, "query failed"):
            with self.view.transaction():
                self.read()
                self.native.security = Mock(side_effect=OSError("query failed"))
                self.read()
        self.assertTrue(self.backend._invalidated)

    def test_file_bytes_are_queried_again_inside_shared_operation(self):
        with self.view.transaction():
            self.assertEqual(b"current", self.read().raw)
            self.native.objects[custody._path_key(self.path)].raw = b"changed"
            self.assertEqual(b"changed", self.read().raw)

    def test_ordinary_body_failure_releases_dynamic_pins_and_does_not_return_success(self):
        parent = self.backend.namespace_root("custody") / "nested"
        self.native.add(parent, directory=True).security = security("trusted", True)
        self.native.add(parent / "value.json", raw=b"data").security = security("trusted")
        with self.assertRaisesRegex(ValueError, "stop"):
            with self.view.transaction():
                self.backend.read_trusted("custody", "nested/value.json", maximum=10)
                self.assertIn(custody._path_key(parent), self.backend._pins)
                raise ValueError("stop")
        self.assertNotIn(custody._path_key(parent), self.backend._pins)
        self.assertEqual(0, self.backend._transaction_depth)

    def test_no_grouped_reader_authority_for_writer(self):
        helper = helpers.ExactValueTests()
        self.addCleanup(helper.doCleanups)
        backend, _, _ = helper.backend("writer")
        with self.assertRaises(custody.ScienceCustodyNativeError):
            with backend.read_operation():
                self.fail("Writer entered Science operation")


if __name__ == "__main__":
    unittest.main()
