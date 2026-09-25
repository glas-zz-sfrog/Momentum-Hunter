"""016E object-acquisition controls, not SCM-token or production ACL proof."""
from contextlib import nullcontext
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import windows_science_custody as custody
from momentum_hunter import windows_writer_profile as profile
from momentum_hunter.science_custody_commit import (
    CustodyCommitError, CustodyCommitRequest, canonical_protocol_bytes,
    ScienceCustodyFinalizer,
)
from tests.test_science_custody_commit_007 import MemoryBackend, request_for
from tests.test_science_custody_windows_007 import NativeDouble, policy


class StableAdmissionTests(unittest.TestCase):
    def guard(self, name):
        guard = profile.WriterResourceGuard.__new__(profile.WriterResourceGuard)
        root = Path('F:/disposable-016e') / name
        handle = Mock(path=root)
        security = SimpleNamespace(digest='pinned', sddl='pinned')
        guard.native = Mock()
        guard.native.information.return_value = SimpleNamespace(dwFileAttributes=16, nNumberOfLinks=1)
        guard.native.identity.return_value = (1, 0, 1)
        guard.native.security.return_value = security
        guard.handles = [(handle, 'pinned', (1, 0, 1), True, False)]
        guard.profile = SimpleNamespace(resources=(SimpleNamespace(name=name, path=str(root), directory=True),))
        guard._scan_lock, guard._closed = threading.RLock(), False
        guard._image_roots, guard._bound_paths = set(), set()
        guard._access_cache, guard._inheritance_cache, guard.rows = {}, set(), []
        return guard

    def test_mutable_child_activity_never_requires_enumeration_or_access_check(self):
        for name in profile.DYNAMIC_RESOURCE_ROOTS:
            for activity in ('dacl-before-open', 'dacl-after-admission', 'rename', 'replace', 'delete', 'new-child'):
                with self.subTest(name=name, activity=activity):
                    guard = self.guard(name)
                    with patch.object(guard, '_scan_support', side_effect=AssertionError(activity)), \
                         patch.object(guard, '_future_children', side_effect=AssertionError(activity)):
                        guard.recheck()
                        guard.recheck()

    def test_mutable_tree_beyond_old_count_bound_is_never_walked(self):
        guard = self.guard('science_derived')
        with patch.object(profile.os, 'scandir', side_effect=AssertionError('30001 mutable children')), \
             patch.object(profile.os, 'walk', side_effect=AssertionError('nested child traversal')):
            guard.recheck()

    def test_fixed_science_root_drift_still_invalidates_admission(self):
        guard = self.guard('science_generation')
        guard.native.identity.return_value = (1, 0, 2)
        with self.assertRaises(profile.WriterProfileError):
            guard.recheck()

    def test_unrelated_protected_subtrees_keep_negative_checks(self):
        for name in ('provider_replica', 'account_replica', 'paper_replica', 'scheduler_replica',
                     'unrelated_host', 'unrelated_repository', 'unrelated_profile', 'configuration_root'):
            with self.subTest(name=name):
                guard = self.guard(name)
                with patch.object(guard, '_future_children'), patch.object(guard, '_scan_support',
                        side_effect=profile.WriterProfileError('forbidden authority')) as check:
                    with self.assertRaisesRegex(profile.WriterProfileError, 'forbidden authority'):
                        guard.recheck()
                    check.assert_called_once()


class HandoffAcquisitionTests(unittest.TestCase):
    def setup_input(self, raw=b'candidate', name='a' * 32 + '.stage'):
        # Fixed roots/role admission are separate gates. Exercise real _read and
        # handoff snapshot with an object-aware primitive double, not path bytes.
        p = policy()
        native = NativeDouble(p)
        backend = custody.WindowsScienceCustodyBackend.__new__(custody.WindowsScienceCustodyBackend)
        # These adversarial snapshots exercise the explicit legacy policy.
        backend.policy = SimpleNamespace(actor_profile=object(), root=p.root, version=p.version)
        backend.role = 'writer'
        backend.max_artifact_bytes, backend.max_request_bytes = 4096, 2048
        backend._native = native
        backend.transaction = nullcontext
        backend._read_scope = lambda _namespace: nullcontext()
        backend._directory = lambda ns, parts: SimpleNamespace(path=Path(p.root(ns).path)) if not parts else None
        path = Path(p.root('staging').path) / name
        obj = native.add(path, kind='transport', raw=raw)
        return backend, native, path, obj

    def read(self, backend, path):
        return backend.read_staged(path.name, maximum=4096)

    def test_mutable_child_descriptor_is_diagnostic_not_authority(self):
        for timing in ('before', 'during'):
            with self.subTest(timing=timing):
                b, n, path, obj = self.setup_input()
                changed = replace(obj.security, aces=(), protected=False, sddl='untrusted mutable descriptor')
                if timing == 'before':
                    obj.security = changed
                else:
                    original = n.read
                    def read(handle, bound):
                        obj.security = changed
                        return original(handle, bound)
                    n.read = read
                value = self.read(b, path)
                self.assertEqual(b'candidate', value.raw)
                self.assertEqual(obj.identity, value.file_identity)
                self.assertEqual(1, len(n.opens))
                self.assertTrue(all(h.closed for h in n.handles.values()))

    def test_replace_before_open_consumes_new_object_only(self):
        b, n, path, old = self.setup_input()
        new = n.add(path, kind='transport', raw=b'new untrusted bytes')
        value = self.read(b, path)
        self.assertEqual(new.identity, value.file_identity)
        self.assertNotEqual(old.identity, value.file_identity)
        self.assertEqual(new.raw, value.raw)

    def test_rename_or_delete_before_open_abstains_without_reopen(self):
        for event in ('rename', 'delete'):
            with self.subTest(event=event):
                b, n, path, obj = self.setup_input()
                n.objects.pop(custody._path_key(path))
                with self.assertRaises(OSError):
                    self.read(b, path)
                self.assertEqual(1, len(n.opens))

    def test_rename_and_replacement_after_acquisition_cannot_switch_bytes(self):
        b, n, path, obj = self.setup_input()
        original = n.read
        def read(handle, maximum):
            n.objects.pop(custody._path_key(path))
            obj.path = path.with_name('renamed.stage')
            n.add(path, kind='transport', raw=b'attacker replacement')
            return original(handle, maximum)
        n.read = read
        value = self.read(b, path)
        self.assertEqual(b'candidate', value.raw)
        self.assertEqual(obj.identity, value.file_identity)
        self.assertEqual(1, len(n.opens))

    def test_rename_immediately_after_open_does_not_recheck_mutable_path(self):
        b, n, path, obj = self.setup_input()
        opening = n.open
        def open_then_rename(*args, **kwargs):
            handle = opening(*args, **kwargs)
            obj.path = path.with_name('renamed-immediately.stage')
            n.objects.pop(custody._path_key(path))
            n.add(path, kind='transport', raw=b'other object')
            return handle
        n.open = open_then_rename
        value = self.read(b, path)
        self.assertEqual(obj.identity, value.file_identity)
        self.assertEqual(b'candidate', value.raw)
        self.assertEqual(1, len(n.opens))

    def test_acquisition_rejects_type_reparse_link_volume_and_size(self):
        for attack in ('directory', 'reparse', 'hardlink', 'volume', 'size'):
            with self.subTest(attack=attack):
                b, n, path, obj = self.setup_input()
                if attack == 'directory': obj.attributes |= custody.DIRECTORY
                if attack == 'reparse': obj.attributes |= custody.REPARSE
                if attack == 'hardlink': obj.links = 2
                if attack == 'volume': obj.identity = (2, 0, 1)
                if attack == 'size': obj.raw = b'x' * 4097
                with self.assertRaises(custody.ScienceCustodyNativeError):
                    self.read(b, path)
                self.assertTrue(all(h.closed for h in n.handles.values()))

    def test_identity_change_on_acquired_object_fails_closed(self):
        b, n, path, obj = self.setup_input()
        original = n.read
        def read(handle, maximum):
            obj.identity = (1, 0, 999999)
            return original(handle, maximum)
        n.read = read
        with self.assertRaises(custody.ScienceCustodyNativeError):
            self.read(b, path)

    def test_minimum_read_handle_no_mutation_and_no_write_sharing(self):
        b, n, path, obj = self.setup_input()
        self.read(b, path)
        options = n.opens[0][1]
        self.assertEqual(0x120081, options['access'])
        self.assertEqual(5, options['share'])
        self.assertFalse(options['access'] & custody.MUTATE)

    def test_request_acquisition_and_protocol_validation_use_exact_snapshot(self):
        memory = MemoryBackend()
        request = request_for(memory)
        b, n, _, _ = self.setup_input()
        path = Path(b.policy.root('requests').path) / 'request.json'
        obj = n.add(path, kind='transport', raw=request.to_bytes())
        first = b.read_request('request.json', maximum=2048)
        self.assertEqual(request, CustodyCommitRequest.from_bytes(first.raw))
        self.assertEqual(obj.identity, first.file_identity)
        invalid = json.loads(request.to_bytes())
        invalid['version'] = 'UNAUTHORIZED_PROTOCOL'
        obj.raw = canonical_protocol_bytes(invalid)
        second = b.read_request('request.json', maximum=2048)
        with self.assertRaises(CustodyCommitError):
            CustodyCommitRequest.from_bytes(second.raw)
        with self.assertRaises(custody.ScienceCustodyNativeError):
            b.read_request('../request.json', maximum=2048)

    def test_finalizer_hash_generation_and_identity_are_unchanged(self):
        for attack in ('none', 'bytes', 'identity', 'generation'):
            with self.subTest(attack=attack):
                memory = MemoryBackend()
                request = request_for(memory)
                raw = memory.objects['staging', request.staging_name].raw
                b, n, path, obj = self.setup_input(raw, request.staging_name)
                memory.max_artifact_bytes = b.max_artifact_bytes
                memory.read_staged = b.read_staged
                if attack == 'bytes': obj.raw = b'incorrect'
                if attack == 'identity': request = replace(request, identity=replace(request.identity, logical_key='wrong'))
                if attack == 'generation':
                    with self.assertRaises(CustodyCommitError):
                        replace(request, generation='2' * 32)
                    continue
                finalizer = ScienceCustodyFinalizer(memory)
                if attack != 'none':
                    with self.assertRaises(CustodyCommitError): finalizer.finalize(request)
                else:
                    first = finalizer.finalize(request)
                    second = ScienceCustodyFinalizer(memory).finalize(request)
                    self.assertEqual(first.receipt, second.receipt)
                    self.assertEqual(obj.identity, first.receipt.original_staging_identity)
                    self.assertEqual(1, len(n.opens))

    @unittest.skipUnless(os.name == 'nt', 'Own disposable native file; no service or ACL changes')
    def test_real_handle_survives_rename_and_path_replacement(self):
        native = custody._Native()
        with tempfile.TemporaryDirectory(prefix='argus-016e-handle-') as directory:
            path = Path(directory) / ('a' * 32 + '.stage')
            creator = native.open(path, access=0xC0030000, share=7, disposition=1)
            try: native.write(creator, b'original')
            finally: creator.close()
            b = custody.WindowsScienceCustodyBackend.__new__(custody.WindowsScienceCustodyBackend)
            b._native = native
            h = native.open(path, access=0x120081, share=5)
            try:
                identity = native.identity(h)
                native.require_path(h, path)
                with self.assertRaises(OSError):
                    native.write(h, b'forbidden write')
                with self.assertRaises(OSError):
                    native.open(path, access=0x40000000, share=7)
                path.rename(path.with_name('renamed.stage'))
                replacement = native.open(path, access=0xC0030000, share=7, disposition=1)
                try: native.write(replacement, b'replacement')
                finally: replacement.close()
                value = b._handoff_snapshot(h, identity[0], 100)
                self.assertEqual(identity, value.file_identity)
                self.assertEqual(b'original', value.raw)
            finally: h.close()
