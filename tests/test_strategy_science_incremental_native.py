"""Native004 aggregate invalidation qualification, synthetic roots only."""
import os
from pathlib import Path, PurePath
import tempfile
import struct
import unittest
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch

from momentum_hunter.strategy_science_recorder import verified_reads as native
from tests.test_strategy_science_verified_reads import VerifiedReadsTests
from momentum_hunter.strategy_science_recorder.namespace_changes import DirectoryChanges, NamespaceRecoveryRequired
from momentum_hunter.windows_writer_storage import WriterPhysicalStorage, WriterPhysicalStorageError


@unittest.skipUnless(os.name == 'nt', 'Native local Windows qualification')
class AggregateVerifiedReadsTests(VerifiedReadsTests):
    def setUp(self):
        super().setUp()
        self.cache.close()
        self.cache = native.VerifiedReads(self.root, aggregate_content=True)

    def test_aggregate_check_does_not_visit_old_files_or_leases(self):
        self.cache.read(self.raw)
        for i in range(100):
            path = self.root / f'{i}.raw'
            path.write_bytes(str(i).encode())
            self.cache.read(path)
        before = dict(self.cache.counters)
        with patch.object(native._ReadLease, 'check', side_effect=AssertionError('historical lease walk')), patch.object(native, '_identity', side_effect=AssertionError('historical metadata walk')):
            for _ in range(20):
                self.cache.check_content()
        self.assertEqual(before, self.cache.counters)

    def test_aggregate_break_is_visible_without_touching_changed_file(self):
        self.cache.read(self.raw)
        self.raw.write_bytes(b'original raw bytes')
        with self.assertRaises(native.VerifiedReadError):
            self.cache.check_content()

    def test_new_request_cannot_reset_an_existing_break(self):
        self.cache.read(self.raw)
        self.raw.write_bytes(b'changed raw bytes')
        other = self.root / 'next.raw'
        other.write_bytes(b'new')
        with self.assertRaises(native.VerifiedReadError):
            self.cache.read(other)

    def test_close_retires_all_exact_completion_requests(self):
        before = len(native._unretired_requests)
        for i in range(20):
            path = self.root / f'close-{i}.raw'
            path.write_bytes(b'abc')
            self.cache.read(path)
        port = self.cache._port
        self.cache.close()
        self.assertEqual({}, port.requests)
        self.assertIsNone(port.handle)
        self.assertEqual(before, len(native._unretired_requests))

    def test_outside_alias_is_audit_only_not_false_content_guarantee(self):
        self.cache.read(self.raw)
        with tempfile.TemporaryDirectory(prefix='science004-external-alias-') as external:
            os.link(self.raw, Path(external) / 'alias.raw')
            # Native R leases do not certify global singleton metadata.
            self.cache.check_content()
            with self.assertRaises(native.VerifiedReadError):
                self.cache.audit_known()

    def test_two_independent_ports_cannot_clear_each_others_invalidation(self):
        other = native.VerifiedReads(self.root, aggregate_content=True)
        self.addCleanup(other.close)
        self.cache.read(self.raw)
        other.read(self.raw)
        self.raw.write_bytes(b'changed both generations')
        for cache in (other, self.cache):
            with self.assertRaises(native.VerifiedReadError):
                cache.check_content()

    def test_constructor_failures_retire_only_acquired_resources(self):
        for failure in ('event', 'association', 'grant'):
            kernel = native._kernel()
            port = native._CompletionPort(kernel)
            name = {'event': 'CreateEventW', 'association': 'CreateIoCompletionPort', 'grant': 'DeviceIoControl'}[failure]
            def failed(*args):
                ctypes.set_last_error(5)
                return 0
            with self.subTest(failure=failure), patch.object(kernel, name, side_effect=failed):
                with self.assertRaises(native.VerifiedReadError):
                    native._ReadLease(self.raw, kernel, port)
            self.assertEqual({}, port.requests)
            port.close()
            self.assertIsNone(port.handle)
        # Every failed read handle released; successful new cache still usable.
        self.assertEqual(self.raw.read_bytes(), self.cache.read(self.raw))

    def test_cancel_error_not_found_does_not_replace_exact_completion_proof(self):
        self.cache.read(self.raw)
        kernel = self.cache._kernel
        original = kernel.CancelIoEx
        def cancelled_but_report_not_found(*args):
            original(*args)
            ctypes.set_last_error(1168)
            return False
        before = len(native._unretired_requests)
        with patch.object(kernel, 'CancelIoEx', side_effect=cancelled_but_report_not_found):
            self.cache.close()
        self.assertEqual(before, len(native._unretired_requests))


@unittest.skipUnless(os.name == 'nt', 'Windows last-error semantics')
class CompletionQueueFaultTests(unittest.TestCase):
    def test_nonzero_completion_key_is_not_accepted_as_this_ports_request(self):
        request = SimpleNamespace(overlapped=native._Overlapped(), completion_dequeued=False)
        address = ctypes.addressof(request.overlapped)
        kernel = SimpleNamespace(CreateIoCompletionPort=lambda *a: 77, CloseHandle=Mock())
        def dequeue(handle, count, key, result, timeout):
            ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p))[0] = address
            ctypes.cast(key, ctypes.POINTER(ctypes.c_size_t))[0] = 12
            return True
        kernel.GetQueuedCompletionStatus = dequeue
        port = native._CompletionPort(kernel)
        port.requests[address] = request
        with self.assertRaises(native.VerifiedReadError):
            port.check()
        self.assertFalse(request.completion_dequeued)
        self.assertTrue(port.failed)
        # Mock-only request was never submitted to a kernel; discard explicitly.
        port.discard_unissued(request)
        port.close()

    def test_only_false_null_timeout_is_a_healthy_empty_queue(self):
        for ok, address, error in ((False, None, 258), (True, None, 0),
                (False, None, 5), (True, 12345, 0), (False, 12345, 995)):
            kernel = SimpleNamespace(CreateIoCompletionPort=lambda *a: 77, CloseHandle=Mock())
            def dequeue(handle, count, key, result, timeout):
                ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p))[0] = address
                ctypes.set_last_error(error)
                return ok
            kernel.GetQueuedCompletionStatus = dequeue
            port = native._CompletionPort(kernel)
            with self.subTest(ok=ok, address=address, error=error):
                if (ok, address, error) == (False, None, 258):
                    port.check()
                    self.assertFalse(port.failed)
                else:
                    with self.assertRaises(native.VerifiedReadError):
                        port.check()
                    self.assertTrue(port.failed)
            port.close()


@unittest.skipUnless(os.name == 'nt', 'Actual Writer005 native coexistence')
class Writer005CoexistenceTests(unittest.TestCase):
    def test_actual_retained_evicted_readback_handles_aggregate_reads_close_and_reopen(self):
        with tempfile.TemporaryDirectory(prefix='science004-writer005-') as temp:
            root = Path(temp)/'custody'
            writer = WriterPhysicalStorage(root, writer_instance_id='science004-native-storage',
                topology_fingerprint='synthetic-coexistence', topology_version=1)
            readers = native.VerifiedReads(root, aggregate_content=True)
            retained = []
            prior_unretired = len(native._unretired_requests)
            try:
                for number in range(12):
                    relative = PurePath('ledger', f'{number}.raw')
                    raw = f'exact-synthetic-{number}\n'.encode()
                    self.assertTrue(writer.atomic_create(relative, raw))
                    self.assertFalse(writer.atomic_create(relative, raw))
                    self.assertEqual(raw, writer.read_committed(relative))
                    self.assertEqual(raw, readers.read(root/relative))
                    self.assertLessEqual(len(writer._backend._readback_handles), 2)
                    retained.extend(h for h in writer._backend._readback_handles.values() if h not in retained)
                self.assertEqual(b'exact-synthetic-0\n', writer.read_committed(PurePath('ledger','0.raw')))
                readers.check_content()
                self.assertTrue(all(h.closed for h in retained[:-2]))
            finally:
                readers.close()
                writer.close()
            self.assertEqual(prior_unretired, len(native._unretired_requests))
            self.assertTrue(all(h.closed for h in retained))
            writer.close()
            with self.assertRaises(WriterPhysicalStorageError):
                writer.read_committed(PurePath('ledger','11.raw'))
            reopened = WriterPhysicalStorage(root, writer_instance_id='science004-native-storage',
                topology_fingerprint='synthetic-coexistence', topology_version=1)
            try:
                reopened.iter_files(PurePath('ledger'), suffix='.raw')
                self.assertEqual(b'exact-synthetic-11\n', reopened.read_committed(PurePath('ledger','11.raw')))
            finally:
                reopened.close()

    def test_known_success_failure_cancel_packets_all_invalidate_and_retire_exact_request(self):
        for ok, error in ((True,0), (False,5), (False,995)):
            request = SimpleNamespace(overlapped=native._Overlapped(), completion_dequeued=False)
            address = ctypes.addressof(request.overlapped)
            kernel = SimpleNamespace(CreateIoCompletionPort=lambda *a: 77, CloseHandle=Mock())
            def dequeue(handle, count, key, result, timeout):
                ctypes.cast(result, ctypes.POINTER(ctypes.c_void_p))[0] = address
                ctypes.set_last_error(error)
                return ok
            kernel.GetQueuedCompletionStatus = dequeue
            port = native._CompletionPort(kernel)
            port.requests[address] = request
            with self.subTest(ok=ok, error=error), self.assertRaises(native.VerifiedReadError):
                port.check()
            self.assertTrue(request.completion_dequeued)
            port.retire(request)
            self.assertEqual({}, port.requests)
            port.close()


@unittest.skipUnless(os.name == 'nt', 'Native local Windows qualification')
class DirectoryChangesTests(unittest.TestCase):
    def test_new_names_and_delete_between_polls_are_observed(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with DirectoryChanges(root) as changes:
                path = root / 'published.raw'
                path.write_bytes(b'new raw')
                self.assertIn(path.name, changes.drain())
                self.assertEqual((), changes.drain())
                path.unlink()
                self.assertIn(path.name, changes.drain())

    def test_baseline_and_rearm_do_not_discard_new_names(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with DirectoryChanges(root) as changes:
                for i in range(100):
                    path = root / f'{i}.raw'
                    path.write_bytes(b'new')
                    self.assertIn(path.name, changes.drain())

    def test_recursive_rename_and_unknown_directory_are_visible(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with DirectoryChanges(root, recursive=True) as changes:
                nested = root / 'new-directory'
                nested.mkdir()
                path = nested / 'first.raw'
                path.write_bytes(b'new')
                names = changes.drain()
                self.assertIn('new-directory', names)
                self.assertIn('new-directory/first.raw', names)
                path.rename(nested / 'second.raw')
                self.assertEqual({'new-directory/first.raw', 'new-directory/second.raw'}, set(changes.drain()))

    def test_overflow_never_reports_empty_success(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            with DirectoryChanges(root, buffer_bytes=1024) as changes:
                for i in range(200):
                    (root / (str(i) + '-' + 'x' * 100)).write_bytes(b'x')
                with self.assertRaises(NamespaceRecoveryRequired):
                    changes.drain()

    def test_malformed_notifications_fail_closed(self):
        encode = lambda name: name.encode('utf-16-le')
        bad = [b'', b'partial', struct.pack('<III', 0, 9, 2) + encode('x'), struct.pack('<III', 0, 1, 3) + b'abc', struct.pack('<III', 0, 1, 4) + encode('..'), struct.pack('<III', 4, 1, 2) + encode('x'), struct.pack('<III', 0, 1, 2) + b'\x00\xd8']
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(NamespaceRecoveryRequired):
                DirectoryChanges._decode(raw)

    def test_close_releases_root_pin_and_cannot_read_again(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / 'root'
            root.mkdir()
            changes = DirectoryChanges(root)
            changes.close()
            changes.close()
            with self.assertRaises(NamespaceRecoveryRequired):
                changes.drain()
            root.rename(Path(parent) / 'moved')


if __name__ == '__main__':
    unittest.main()
