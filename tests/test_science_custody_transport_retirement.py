"""Exact mutable-transport retirement, not SCM-token/ACL qualification."""
import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import windows_science_custody as mod
from momentum_hunter.science_custody_commit import (
    CustodyCommitPending, ScienceCustodyFinalizer,
)
from momentum_hunter.science_custody_mailbox import ScienceCustodyMailboxWriter
from tests.test_science_custody_commit_007 import MemoryBackend, request_for
from tests import test_writer_handoff_016e as handoff_tests


@unittest.skipUnless(os.name == "nt", "Windows native transport open")
class NativeTransportRetirementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mh-transport-retirement-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "request.json"
        self.path.write_bytes(b"untrusted request bytes")
        self.native = mod._Native()
        self.parent = self.native.open(self.root, directory=True, access=mod.DIRECTORY_READ)
        self.addCleanup(self.parent.close)

    def read_handle(self):
        return self.native.open(self.path, access=0x120081, share=5, relative_to=self.parent)

    def test_old_red_new_green_for_same_delete_pending_object(self):
        retirement = self.native.open(self.path, access=0x130081, share=1)
        self.addCleanup(retirement.close)
        read = self.read_handle()
        try:
            self.assertEqual(self.native.identity(retirement), self.native.identity(read))
            self.assertEqual(b"untrusted request bytes", self.native.read(read, 1024))
            self.assertEqual(0x120081, self.native.granted_access(read))
            self.assertFalse(os.get_handle_inheritable(read.value))
        finally:
            read.close()
        self.native.delete(retirement)
        self.assertIn(self.path.name, [entry.name for entry in self.root.iterdir()])
        with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "Win32 5"):
            self.native.open(self.path, access=0x120081, share=5)
        with self.assertRaises(FileNotFoundError) as failure:
            self.read_handle()
        self.assertEqual(0xC0000056, failure.exception.ntstatus)
        retirement.close()
        with self.assertRaises(FileNotFoundError):
            self.read_handle()
        self.assertEqual([], list(self.root.iterdir()))

    def test_live_object_and_sharing_violation_are_not_retirement(self):
        exclusive = self.native.open(self.path, access=0x120081, share=0)
        try:
            with self.assertRaises(OSError) as failure:
                self.read_handle()
            self.assertEqual(32, failure.exception.winerror)
            self.assertNotIsInstance(failure.exception, FileNotFoundError)
        finally:
            exclusive.close()
        read = self.read_handle()
        read.close()

    def test_exact_pinned_parent_and_unchanged_contract_required(self):
        for changes in ({"directory": True}, {"access": mod.FULL}, {"share": 7},
                        {"disposition": 1}, {"sddl": "D:"}):
            with self.subTest(changes=changes):
                args = dict(access=0x120081, share=5, relative_to=self.parent)
                args.update(changes)
                with self.assertRaises(mod.ScienceCustodyNativeError):
                    self.native.open(self.path, **args)
        with patch.object(self.native.nt, "NtOpenFile", side_effect=AssertionError("native call")):
            for parent in (SimpleNamespace(closed=True, path=self.root),
                           SimpleNamespace(closed=False, path=self.root / "other")):
                with self.assertRaises(mod.ScienceCustodyNativeError):
                    self.native.open(self.path, access=0x120081, share=5, relative_to=parent)

    def test_native_mapping_preserves_real_denial_and_other_errors(self):
        for status, winerror in ((0xC0000022, 5), (0xC0000061, 1314),
                                 (0xC0000043, 32), (0xC0000034, 2)):
            with self.subTest(status=hex(status)):
                with patch.object(self.native.nt, "NtOpenFile", return_value=c.c_long(status).value), \
                     patch.object(self.native.nt, "RtlNtStatusToDosError", return_value=winerror):
                    expected = mod.ScienceCustodyNativeError if winerror in (5, 1314) else OSError
                    with self.assertRaises(expected) as failure:
                        self.read_handle()
                    if winerror in (5, 1314):
                        self.assertIn(f"Win32 {winerror}", str(failure.exception))
                    else:
                        self.assertEqual(winerror, failure.exception.winerror)

    def test_failed_open_closes_unexpected_handle(self):
        def failure(handle, *_args):
            c.cast(handle, c.POINTER(w.HANDLE))[0] = w.HANDLE(1234)
            return c.c_long(0xC0000056).value
        with patch.object(self.native.nt, "NtOpenFile", side_effect=failure), \
             patch.object(self.native.k, "CloseHandle", return_value=1) as close:
            with self.assertRaises(FileNotFoundError):
                self.read_handle()
            self.assertEqual(1, close.call_count)
            self.assertEqual(1234, close.call_args.args[0].value)

    def test_native_call_is_exact_leaf_read_and_noninheritable(self):
        class Name(c.Structure):
            _fields_ = [("length", w.USHORT), ("maximum", w.USHORT), ("buffer", w.LPWSTR)]
        class Attributes(c.Structure):
            _fields_ = [("length", w.ULONG), ("root", w.HANDLE), ("name", c.POINTER(Name)),
                        ("flags", w.ULONG), ("security", c.c_void_p), ("qos", c.c_void_p)]
        def inspect(_handle, access, attrs, _io, share, options):
            value = c.cast(attrs, c.POINTER(Attributes)).contents
            self.assertEqual(self.parent.value, value.root)
            self.assertEqual(self.path.name, value.name.contents.buffer)
            self.assertEqual(len(self.path.name.encode("utf-16-le")), value.name.contents.length)
            self.assertEqual(0x40, value.flags)  # No OBJ_INHERIT or privilege override.
            self.assertIsNone(value.security)
            self.assertIsNone(value.qos)
            self.assertEqual((0x120081, 5, 0x200062), (access, share, options))
            return c.c_long(0xC0000056).value
        with patch.object(self.native.nt, "NtOpenFile", side_effect=inspect):
            with self.assertRaises(FileNotFoundError):
                self.read_handle()


class TransportBoundaryTests(unittest.TestCase):
    def test_only_actual_writer_handoff_passes_pinned_parent(self):
        helper = handoff_tests.HandoffAcquisitionTests()
        backend, native, path, _ = helper.setup_input()
        parent = backend._directory("staging", ())
        backend._directory = lambda *_args: parent
        backend.read_staged(path.name, maximum=4096)
        self.assertIs(parent, native.opens[-1][1]["relative_to"])

    def test_retiring_request_is_no_work_not_success_and_forgets_observation(self):
        backend = MemoryBackend()
        request = request_for(backend)
        backend._new("requests", "request.json", request.to_bytes())
        backend.list_transport = lambda namespace, maximum: ("request.json",) if namespace == "requests" else ()
        finalizer = ScienceCustodyFinalizer(backend)
        finalizer.finalize = Mock()
        writer = ScienceCustodyMailboxWriter(finalizer, mailbox_backend=backend)
        writer._delivered_request = object()
        backend.read_request = Mock(side_effect=FileNotFoundError("delete pending"))
        self.assertIsNone(writer.poll_once(new_work_only=True))
        self.assertIsNone(writer._delivered_request)
        finalizer.finalize.assert_not_called()

    def test_retiring_stage_is_pending_never_commit_or_ack(self):
        backend = MemoryBackend()
        request = request_for(backend)
        backend.read_staged = Mock(side_effect=FileNotFoundError("delete pending"))
        with self.assertRaises(CustodyCommitPending):
            ScienceCustodyFinalizer(backend).finalize(request)
        self.assertFalse(any(ns in {"claims", "receipts", "arrivals"} for ns, _ in backend.objects))
        self.assertEqual([], backend.deleted)


if __name__ == "__main__":
    unittest.main()
