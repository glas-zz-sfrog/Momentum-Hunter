"""Pure native-boundary tests. No real Windows roots, ACLs or tokens are touched.

The separately authorized qualification tool supplies physical proof. These
tests exercise production policy and orchestration against an instrumented
primitive double; they must never be represented as native access denial.
"""
from __future__ import annotations

import hashlib
import json
import ctypes
from ctypes import wintypes
import os
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from momentum_hunter import windows_science_custody as mod
from momentum_hunter.science_custody_commit import (
    CustodyCommitConflict, CustodyCommitError, CustodyCommitIdentity, CustodyCommitRequest,
    CustodyCommitReceipt,
    ScienceCustodyFinalizer, canonical_protocol_bytes, claim_path,
    identity_for_artifact, receipt_path, sha256,
)
from momentum_hunter.science_custody_mailbox import ScienceCustodyMailboxWriter
from momentum_hunter.strategy_science_recorder.canonical import canonical_json_bytes
from tools import qualify_science_custody_007 as qualifier

WRITER = "S-1-5-21-1-2-3-1001"
SCIENCE = "S-1-5-7"
CONFIG = SimpleNamespace(writer_sid=WRITER, science_sid=SCIENCE,
                         object_integrity_sid="S-1-16-0")


def security(kind="trusted", directory=False, *, owner=None):
    owner = owner or (SCIENCE if kind == "transport" and not directory else WRITER)
    aces = mod._expected_aces(CONFIG, kind, directory)
    sddl = repr((owner, aces, directory))
    return mod._Security(owner, sddl, aces,
                         ((3 if directory else 16, 1, "S-1-16-0"),), True)


def policy(**changes):
    paths = {name: str(PureWindowsPath("C:/custody-007-pure-test") / name)
             for name in sorted(mod.ROOT_NAMES)}
    roots = []
    for index, (name, path) in enumerate(paths.items(), 10):
        kind = "private" if name == "private" else (
            "transport" if name in mod.TRANSPORT | {"derived"} else "trusted")
        roots.append(mod.CustodyRootBinding(name, path, (1, 0, index), WRITER,
                                           security(kind, True).digest))
    parents = sorted({str(p) for path in paths.values() for p in PureWindowsPath(path).parents})
    ancestors = tuple(mod.CustodyRootBinding("ancestor", path, (1, 0, index),
                    WRITER, security("trusted", True).digest)
                    for index, path in enumerate(parents, 100))
    result = mod.ScienceCustodyPolicy(
        source_root_identity="a" * 64, science_sid=SCIENCE, writer_sid=WRITER,
        science_group_sids=(), science_privilege_names=(),
        science_integrity_sid="S-1-16-0", object_integrity_sid="S-1-16-0",
        roots=tuple(roots), ancestors=ancestors, max_artifact_bytes=4096,
        max_request_bytes=2048, max_history_entries=1000, max_pinned_directories=128)
    return replace(result, **changes) if changes else result


def winerror(code):
    exc = OSError(code, "synthetic native operation")
    exc.winerror = code
    return exc


class Handle:
    def __init__(self, native, obj, path):
        self.native = native
        self.obj = obj
        self.path = path
        self.closed = False
        self.value = len(native.handles) + 1
        native.handles[self.value] = self

    def close(self):
        self.closed = True


class NativeDouble:
    def __init__(self, p, role="writer"):
        self.p = p
        self.role = role
        self.objects = {}
        self.handles = {}
        self.opens = []
        self.deletes = []
        self.renames = []
        self.security_calls = 0
        self.fail_write = False
        self.next_index = 1000
        self.token_override = None
        self.k = SimpleNamespace(FlushFileBuffers=lambda h: 1,
                                 SetFilePointerEx=lambda *a: 1,
                                 SetEndOfFile=self.truncate)
        for binding in (*p.ancestors, *p.roots):
            kind = "trusted" if binding.namespace == "ancestor" else (
                "private" if binding.namespace == "private" else
                "transport" if binding.namespace in mod.TRANSPORT | {"derived"} else "trusted")
            self.add(Path(binding.path), kind=kind, directory=True, identity=binding.file_identity)

    def add(self, path, *, kind="trusted", directory=False, identity=None, raw=b""):
        self.next_index += 1
        obj = SimpleNamespace(path=Path(path), security=security(kind, directory),
                              identity=identity or (1, 0, self.next_index), raw=raw,
                              attributes=mod.DIRECTORY if directory else 32, links=1,
                              deleted=False)
        self.objects[mod._path_key(path)] = obj
        return obj

    def token(self):
        if self.token_override is not None:
            return self.token_override
        sid = WRITER if self.role == "writer" else SCIENCE
        return {"user": sid, "owner": sid, "thread_token": False,
                "groups": (), "enabled_groups": (), "privileges": (),
                "enabled_privileges": (), "group_attributes": (),
                "privilege_attributes": (), "integrity": "S-1-16-0"}

    def open(self, path, **kwargs):
        self.opens.append((Path(path), dict(kwargs)))
        key = mod._path_key(path)
        disposition = kwargs.get("disposition", 3)
        if disposition == 1 and key in self.objects:
            raise winerror(183)
        if key not in self.objects:
            if disposition not in {1, 4}:
                raise winerror(2)
            sddl = kwargs["sddl"]
            kind = "private" if SCIENCE not in sddl else (
                "transport" if "O:" + SCIENCE in sddl else "trusted")
            self.add(path, kind=kind)
        return Handle(self, self.objects[key], Path(path))

    def security(self, handle):
        self.security_calls += 1
        return handle.obj.security

    def information(self, handle):
        return SimpleNamespace(dwFileAttributes=handle.obj.attributes,
                               nNumberOfLinks=handle.obj.links,
                               nFileSizeHigh=0, nFileSizeLow=len(handle.obj.raw))

    def identity(self, handle):
        return handle.obj.identity

    def require_path(self, handle, path):
        if mod._path_key(handle.obj.path) != mod._path_key(path):
            raise mod.ScienceCustodyNativeError("Redirected actual handle.")

    def read(self, handle, maximum):
        if len(handle.obj.raw) > maximum:
            raise mod.ScienceCustodyNativeError("Opened object exceeds admitted byte bound.")
        return handle.obj.raw

    def write(self, handle, raw):
        if self.fail_write:
            self.fail_write = False
            handle.obj.raw = raw[:2]
            raise winerror(112)
        handle.obj.raw = raw

    def truncate(self, value):
        self.handles[value].obj.raw = b""
        return 1

    @staticmethod
    def checked(ok, label):
        if not ok:
            raise winerror(5)

    def mkdir(self, path, sddl):
        self.add(path, directory=True)

    def rename(self, handle, target):
        if mod._path_key(target) in self.objects:
            raise winerror(183)
        self.renames.append((handle.obj.identity, handle.obj.path, target))
        self.objects.pop(mod._path_key(handle.obj.path))
        handle.obj.path = target
        handle.path = target
        self.objects[mod._path_key(target)] = handle.obj

    def delete(self, handle):
        self.deletes.append(handle.obj.identity)
        key = mod._path_key(handle.obj.path)
        if self.objects.get(key) is handle.obj:
            self.objects.pop(key)
        handle.obj.deleted = True


class NativePolicyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Native token statistics require Windows")
    def test_fast_token_fingerprint_matches_full_native_observation(self):
        native = mod._Native()
        full = native.token()
        quick = native.token_fingerprint()
        self.assertEqual({key: full[key] for key in quick}, quick)

    def test_disabled_factory_does_no_native_io(self):
        with patch.object(mod, "_Native", side_effect=AssertionError("native I/O")):
            self.assertIsNone(mod.open_science_custody_backend(None, role="science"))

    def test_policy_is_frozen_and_complete(self):
        p = policy()
        with self.assertRaises(Exception):
            p.science_sid = WRITER
        with self.assertRaises(mod.ScienceCustodyNativeError):
            replace(p, roots=p.roots[:-1])
        with self.assertRaises(mod.ScienceCustodyNativeError):
            replace(p, ancestors=p.ancestors[:-1])
        with self.assertRaises(mod.ScienceCustodyNativeError):
            replace(p, roots=list(p.roots))
        self.assertNotEqual(p.policy_sha256, replace(p, max_history_entries=999).policy_sha256)

    def test_mailbox_requires_exact_two_before_native_io(self):
        with patch.object(mod, "_Native", side_effect=AssertionError("native I/O")):
            for bad in (0, 1, 3, -1, True, False, "2", 2.0):
                with self.subTest(value=bad), self.assertRaisesRegex(
                        mod.ScienceCustodyNativeError, "exactly two"):
                    policy(max_mailbox_entries=bad)
        self.assertEqual(2, policy().max_mailbox_entries)

    def test_native_schema_maxima_fit_existing_fixed_metadata_ceiling(self):
        # Schema encoding bound only: the joint maxima need not describe a
        # mechanically admissible scientific artifact. Native SID size, not a
        # fictional generic backend's unbounded owner text, is the premise.
        identity = CustodyCommitIdentity("a" * 64, "SCIENTIFIC_RECEIPT", "\U0001f642" * 2048,
                                         "\U0001f642" * 1024)
        path = "/".join(["a" * 255] * 7 + ["a" * 254, "a"])
        self.assertEqual(2048, len(path))
        request = CustodyCommitRequest("a" * 64, identity, "custody", path,
            "b" * 64, "b" * 64, 64 * 1024 * 1024, "c" * 32 + ".stage", "c" * 32)
        owner = "S-1-5-" + "1" * 178
        self.assertEqual(184, len(owner))
        mod._sid(owner)
        file_id = (0xFFFFFFFF,) * 3
        claim = {"version": json.loads(request.to_bytes())["version"],
                 "request": json.loads(request.to_bytes()), "request_sha256": request.request_digest(),
                 "staging_file_identity": file_id, "staging_owner_sid": owner,
                 "staging_descriptor_sha256": "d" * 64}
        receipt = CustodyCommitReceipt(identity.digest(), "a" * 64, request.request_digest(),
            request.policy_sha256, request.commit_binding(), file_id, file_id,
            owner, "d" * 64, "b" * 64, "e" * 64)
        for raw, bound in ((request.to_bytes(), 49791), (canonical_protocol_bytes(claim), 50290),
                           (receipt.to_bytes(), 50635)):
            self.assertLessEqual(len(raw), bound)
            self.assertLess(bound, mod.PROTOCOL_METADATA_BYTES)

    def test_sid_owner_and_authority_overlap_rejected(self):
        for change in ({"science_sid": WRITER}, {"science_group_sids": (WRITER,)},
                       {"science_group_sids": ("S-1-5-18",)}):
            with self.subTest(change=change), self.assertRaises(mod.ScienceCustodyNativeError):
                policy(**change)

    def test_all_available_dangerous_privileges_rejected_even_if_disabled(self):
        for name in ("SeTakeOwnershipPrivilege", "SeRestorePrivilege", "SeBackupPrivilege",
                     "SeImpersonatePrivilege", "SeDebugPrivilege"):
            with self.subTest(privilege=name), self.assertRaises(mod.ScienceCustodyNativeError):
                policy(science_privilege_names=(name,), science_enabled_privilege_names=())

    def test_enabled_subsets_cannot_add_unbound_authority(self):
        with self.assertRaises(mod.ScienceCustodyNativeError):
            policy(science_enabled_group_sids=("S-1-5-32-544",))
        with self.assertRaises(mod.ScienceCustodyNativeError):
            policy(science_enabled_privilege_names=("SeChangeNotifyPrivilege",))

    def test_roots_disjoint_and_protected_owner_required(self):
        p = policy()
        roots = list(p.roots)
        roots[1] = replace(roots[1], path=roots[0].path + "\\nested")
        with self.assertRaises(mod.ScienceCustodyNativeError):
            replace(p, roots=tuple(roots))
        roots = list(p.roots)
        roots[1] = replace(roots[1], owner_sid=SCIENCE)
        with self.assertRaises(mod.ScienceCustodyNativeError):
            replace(p, roots=tuple(roots))

    def test_safe_relative_path_and_empty_directory_api(self):
        for name in ("../escape", "a/./b", "a//b", "C:/x", "a:stream",
                     "CON", "con.txt", "a.", "a ", "UPPER.json", "a\\b", "/root", "."):
            with self.subTest(name=name), self.assertRaises(Exception):
                mod._relative(name)
        self.assertEqual((), mod._relative("", empty=True))
        self.assertEqual(("sessions", "day", "file.json"), mod._relative("sessions/day/file.json"))

    def test_wrong_acl_inheritance_owner_and_label_rejected(self):
        p = policy()
        good = security()
        for bad in (replace(good, owner=SCIENCE), replace(good, protected=False),
                    replace(good, aces=good.aces + ((0, 0, mod.FULL, SCIENCE),)),
                    replace(good, labels=((0, 1, "S-1-16-8192"),)),
                    replace(good, labels=())):
            with self.subTest(bad=bad), self.assertRaises(mod.ScienceCustodyNativeError):
                mod._verify_security(p, bad, "trusted", directory=False)

    def test_potentially_enabled_group_grant_blocks_ancestor(self):
        p = policy(science_group_sids=("S-1-5-32-545",), science_enabled_group_sids=())
        sec = security(directory=True)
        broad = replace(sec, aces=sec.aces + ((0, 0, 0x10000000, "S-1-5-32-545"),))
        with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "mutable"):
            mod._verify_ancestor(p, broad)

    def test_inherit_only_creator_owner_does_not_grant_current_ancestor(self):
        sec = security(directory=True)
        sec = replace(sec, aces=sec.aces + ((0, 8, mod.FULL, "S-1-3-0"),))
        mod._verify_ancestor(policy(), sec)

    def test_runtime_creation_inherits_verified_label_without_sacl_authority(self):
        self.assertNotIn("S:", mod.creation_sddl(policy(), "trusted", directory=False))
        self.assertIn("S:(ML;", mod.creation_sddl(
            policy(), "trusted", directory=False, include_label=True))

    def test_fixed_transport_roots_grant_only_child_mutation_not_root_control(self):
        mask = mod.MODIFY_CHILDREN
        self.assertEqual(0x1200EF, mask)
        self.assertEqual(0, mask & (0x10000 | 0x40000 | 0x80000 | 0x100 | 0x10))
        self.assertEqual(0x46, mask & 0x46)
        self.assertEqual(mod.FULL, mod._expected_aces(policy(), "transport", False)[-1][2])

    def test_long_native_spelling_preserves_exact_bound_dos_path(self):
        path = Path("C:/custody/" + "a" * 200 + "/file.json")
        self.assertEqual("\\\\?\\" + str(PureWindowsPath(path)), mod._io_path(path))
        self.assertEqual("staging\\file.stage", mod._io_path(Path("staging/file.stage")))


class NativeBackendFlowTests(unittest.TestCase):
    def make_backend(self, role="writer", **policy_changes):
        p = policy(**policy_changes)
        native = NativeDouble(p, role)
        with patch.object(mod, "_Native", return_value=native):
            backend = mod.WindowsScienceCustodyBackend(p, role=role)
        self.addCleanup(backend.close)
        return backend, native

    def test_writer_and_science_leases_are_separate(self):
        writer, wn = self.make_backend()
        science, sn = self.make_backend("science")
        self.assertEqual(".writer-owner.lock", writer.lease_name)
        self.assertEqual(".science-owner.lock", science.lease_name)
        self.assertNotEqual(writer.lease_identity, science.lease_identity)
        for backend, native in ((writer, wn), (science, sn)):
            self.assertTrue(any(p.name == backend.lease_name and x["share"] == 0
                                for p, x in native.opens))
        self.assertFalse(any(p.name in {"ledger", "sessions"} for p, x in sn.opens))

    def test_reader_child_prepared_after_science_lease_before_scratch_and_closed(self):
        backend, native = self.make_backend("science")
        names = [path.name for path, _ in native.opens]
        self.assertLess(names.index(".science-owner.lock"), names.index(".reader.lock"))
        self.assertLess(names.index(".reader.lock"), names.index(".custody-transport.tmp"))
        options = next(options for path, options in native.opens if path.name == ".reader.lock")
        self.assertEqual({"access": mod.READ, "share": 1, "disposition": 4,
                          "sddl": mod.creation_sddl(backend.policy, "transport", directory=False)}, options)
        reader = native.objects[mod._path_key(backend.derived_root / ".reader.lock")]
        self.assertEqual(security("transport"), reader.security)
        self.assertEqual(b"", reader.raw)
        self.assertTrue(all(h.closed for h in native.handles.values() if h.obj is reader))
        self.assertFalse(backend._lease.closed)
        writer, wn = self.make_backend()
        self.assertFalse(any(path.name == ".reader.lock" for path, _ in wn.opens))
        with self.assertRaises(mod.ScienceCustodyNativeError):
            writer._prepare_reader_lock()

    def test_reader_valid_existing_is_reused_without_write_or_identity_change(self):
        p = policy()
        native = NativeDouble(p, "science")
        path = Path(p.root("derived").path) / ".reader.lock"
        old = native.add(path, kind="transport", raw=b"\0")
        before = (old.identity, old.raw, old.security)
        with patch.object(mod, "_Native", return_value=native):
            backend = mod.WindowsScienceCustodyBackend(p, role="science")
        self.addCleanup(backend.close)
        self.assertIs(old, native.objects[mod._path_key(path)])
        self.assertEqual(before, (old.identity, old.raw, old.security))
        self.assertEqual([], native.deletes)
        self.assertEqual([], native.renames)

    def test_reader_incompatible_existing_fails_unchanged_before_scratch(self):
        for bad in ("inherited", "owner", "label", "hardlink", "reparse"):
            with self.subTest(state=bad):
                p = policy()
                native = NativeDouble(p, "science")
                path = Path(p.root("derived").path) / ".reader.lock"
                old = native.add(path, kind="transport", raw=b"\0")
                if bad == "inherited":
                    old.security = replace(old.security, protected=False,
                        aces=mod._expected_aces(CONFIG, "transport", True))
                elif bad == "owner":
                    old.security = replace(old.security, owner=WRITER)
                elif bad == "label":
                    old.security = replace(old.security, labels=((16, 1, "S-1-16-8192"),))
                elif bad == "hardlink":
                    old.links = 2
                else:
                    old.attributes |= mod.REPARSE
                before = (old.identity, old.raw, old.security, old.links, old.attributes)
                with patch.object(mod, "_Native", return_value=native), self.assertRaises(
                        mod.ScienceCustodyNativeError):
                    mod.WindowsScienceCustodyBackend(p, role="science")
                self.assertIs(old, native.objects[mod._path_key(path)])
                self.assertEqual(before, (old.identity, old.raw, old.security, old.links, old.attributes))
                self.assertFalse(any(path.name == ".custody-transport.tmp" for path, _ in native.opens))
                self.assertTrue(all(h.closed for h in native.handles.values()))
                self.assertEqual([], native.deletes)

    def test_reader_preparation_requires_existing_lifetime_lease(self):
        backend, native = self.make_backend("science")
        lease = backend._lease
        backend._lease = None
        try:
            with self.assertRaises(mod.ScienceCustodyNativeError):
                backend._prepare_reader_lock()
        finally:
            backend._lease = lease

    def test_science_never_creates_trusted_objects_or_directories(self):
        backend, native = self.make_backend("science")
        self.assertFalse(backend.validate_directory("custody", "sessions/absent"))
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.create_trusted("custody", "sessions/file.json", b"x")
        self.assertFalse(any(obj.path.name == "absent" for obj in native.objects.values()))

    def test_actor_wrong_owner_impersonated_writer_and_disabled_privilege_fail(self):
        backend, native = self.make_backend()
        original = native.token()
        for bad in ({**original, "owner": SCIENCE}, {**original, "thread_token": True}):
            native.token_override = bad
            with self.assertRaises(mod.ScienceCustodyNativeError):
                backend.validate_readonly_roots()
        science, sn = self.make_backend("science")
        original = sn.token()
        for name in ("SeTakeOwnershipPrivilege", "SeRestorePrivilege"):
            sn.token_override = {**original, "privileges": (name,),
                                 "enabled_privileges": (), "privilege_attributes": ((name, 0),)}
            with self.assertRaises(mod.ScienceCustodyNativeError):
                science.validate_readonly_roots()

    def test_unbound_disabled_group_is_rejected(self):
        backend, native = self.make_backend("science")
        native.token_override = {**native.token(), "groups": ("S-1-5-32-544",),
                                 "enabled_groups": (),
                                 "group_attributes": (("S-1-5-32-544", 0),)}
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.validate_readonly_roots()

    def test_policy_and_fixed_root_drift_stop(self):
        backend, native = self.make_backend()
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        root.identity = (9, 9, 9)
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.read_trusted("custody", "x.json", maximum=20)

    def test_nested_transactions_share_outer_validation_and_recheck_on_return(self):
        backend, native = self.make_backend("science")
        fixed = len(backend._fixed_keys)
        before = native.security_calls
        with backend.transaction():
            with backend.transaction():
                with backend.transaction():
                    pass
        self.assertEqual(2 * fixed, native.security_calls - before)
        before = native.security_calls
        with backend.transaction():
            pass
        self.assertEqual(fixed, native.security_calls - before)

    def test_qualification_timing_observes_outer_boundary_checks(self):
        backend, native = self.make_backend("science")
        self.assertEqual({}, backend.qualification_pin_timing())
        backend.enable_qualification_pin_timing()
        fixed = len(backend._fixed_keys)
        before = native.security_calls
        with backend.transaction():
            with backend.transaction():
                pass
        profile = backend.qualification_pin_timing()
        self.assertEqual(2, profile["pin_checks"])
        self.assertEqual(2 * fixed, profile["fixed_root_validations"])
        self.assertEqual(2 * fixed, native.security_calls - before)
        self.assertGreaterEqual(profile["pin_check_ns"], profile["actor_ns"])
        self.assertGreaterEqual(profile["pin_check_ns"], profile["fixed_root_ns"])
        backend.reset_qualification_pin_timing()
        self.assertEqual(0, backend.qualification_pin_timing()["pin_checks"])

    def test_nested_transaction_rejects_fixed_root_drift_before_write(self):
        backend, native = self.make_backend("science")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        target = backend.namespace_root("requests") / "request.json"
        with self.assertRaises(mod.ScienceCustodyNativeError):
            with backend.transaction():
                root.identity = (9, 9, 9)
                backend.create_transport("requests", "request.json", b"raw")
        self.assertNotIn(mod._path_key(target), native.objects)
        self.assertEqual(0, backend._transaction_depth)

    def test_nested_transaction_rejects_drift_before_private_copy_write(self):
        backend, native = self.make_backend("science")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        writes = native.write
        native.write = lambda *args: self.fail("Drift reached private copy write")
        try:
            with self.assertRaises(mod.ScienceCustodyNativeError):
                with backend.transaction():
                    root.identity = (9, 9, 9)
                    backend.create_transport("requests", "request.json", b"raw")
        finally:
            native.write = writes

    def test_nested_transaction_rejects_actor_drift_before_read(self):
        backend, native = self.make_backend("science")
        observed = native.token()
        target = backend.namespace_root("custody") / "x.json"
        native.add(target, raw=b"raw")
        with self.assertRaises(mod.ScienceCustodyNativeError):
            with backend.transaction():
                native.token_override = {**observed, "owner": WRITER}
                backend.read_trusted("custody", "x.json", maximum=20)
        self.assertEqual(0, backend._transaction_depth)

    def test_nested_reads_recheck_path_scope_and_revalidate_full_topology_on_return(self):
        backend, native = self.make_backend("science")
        native.add(backend.namespace_root("custody") / "x.json", raw=b"raw")
        backend.enable_qualification_pin_timing()
        fixed = len(backend._fixed_keys)
        scoped = len(backend._read_scopes["custody"])
        self.assertLess(scoped, fixed)
        with backend.transaction():
            for _ in range(40):
                with backend.transaction():
                    self.assertEqual(b"raw", backend.read_trusted("custody", "x.json", maximum=20).raw)
        profile = backend.qualification_pin_timing()
        self.assertEqual(2, profile["full_checks"])
        self.assertEqual(40, profile["scoped_read_checks"])
        self.assertEqual(2 * fixed + 40 * scoped, profile["fixed_root_validations"])

    def test_nested_read_rejects_relevant_root_drift_before_bytes(self):
        backend, native = self.make_backend("science")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        target = native.add(backend.namespace_root("custody") / "x.json", raw=b"raw")
        with self.assertRaises(mod.ScienceCustodyNativeError):
            with backend.transaction():
                root.identity = (9, 9, 9)
                backend.read_trusted("custody", "x.json", maximum=20)
        self.assertEqual(b"raw", target.raw)
        self.assertFalse(any(p.name == "x.json" for p, _ in native.opens))

    def test_cross_root_drift_after_nested_read_blocks_effect_and_return(self):
        backend, native = self.make_backend("science")
        native.add(backend.namespace_root("custody") / "x.json", raw=b"raw")
        unrelated = native.objects[mod._path_key(backend.namespace_root("arrivals"))]
        with self.assertRaises(mod.ScienceCustodyNativeError):
            with backend.transaction():
                backend.read_trusted("custody", "x.json", maximum=20)
                unrelated.identity = (9, 9, 9)
                backend.create_transport("requests", "request.json", b"raw")
        self.assertNotIn(mod._path_key(backend.namespace_root("requests") / "request.json"),
                         native.objects)

    def test_cross_root_drift_after_nested_read_blocks_authoritative_return(self):
        backend, native = self.make_backend("science")
        native.add(backend.namespace_root("custody") / "x.json", raw=b"raw")
        unrelated = native.objects[mod._path_key(backend.namespace_root("arrivals"))]
        with self.assertRaises(mod.ScienceCustodyNativeError):
            with backend.transaction():
                self.assertEqual(b"raw", backend.read_trusted("custody", "x.json", maximum=20).raw)
                unrelated.identity = (9, 9, 9)

    def test_explicit_close_during_nested_read_cannot_return_success(self):
        backend, native = self.make_backend("science")
        native.add(backend.namespace_root("custody") / "x.json", raw=b"raw")
        with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "closed or invalidated"):
            with backend.transaction():
                self.assertEqual(b"raw", backend.read_trusted("custody", "x.json", maximum=20).raw)
                backend.close()

    def test_caught_pin_failure_cannot_return_after_root_restoration(self):
        backend, native = self.make_backend("science")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        original = root.identity
        native.add(backend.namespace_root("custody") / "x.json", raw=b"raw")
        with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "closed or invalidated"):
            with backend.transaction():
                root.identity = (9, 9, 9)
                with self.assertRaises(mod.ScienceCustodyNativeError):
                    backend.read_trusted("custody", "x.json", maximum=20)
                root.identity = original
        self.assertTrue(backend._invalidated)

    def test_unchanged_native_token_fingerprint_reuses_full_admission_only_within_read(self):
        backend, native = self.make_backend("science")
        native.add(backend.namespace_root("custody") / "x.json", raw=b"raw")
        original = native.token
        stable = {"token_id": (1, 2), "authentication_id": (3, 4),
                  "modified_id": (5, 6), "token_type": 1}
        native.token = lambda: {**stable, **original()}
        native.token_fingerprint = lambda: {"thread_token": False, **stable}
        with patch.object(backend, "_actor", wraps=backend._actor) as full:
            with backend.transaction():
                for _ in range(5):
                    backend.read_trusted("custody", "x.json", maximum=20)
            self.assertEqual(2, full.call_count)
        native.token_fingerprint = lambda: {"thread_token": False, **stable,
                                            "modified_id": (5, 7)}
        with self.assertRaises(mod.ScienceCustodyNativeError):
            with backend.transaction():
                native.token_override = {**original(), **stable,
                                         "modified_id": (5, 7), "owner": WRITER}
                backend.read_trusted("custody", "x.json", maximum=20)

    def test_nested_writer_publication_rejects_drift_before_rename(self):
        backend, native = self.make_backend("writer")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        with self.assertRaises(mod.ScienceCustodyNativeError):
            with backend.transaction():
                root.identity = (9, 9, 9)
                backend.create_trusted("custody", "sessions/scope/final.json", b"raw")
        self.assertEqual([], native.renames)

    def test_nested_science_cleanup_rejects_drift_before_delete(self):
        backend, native = self.make_backend("science")
        name = "a" * 32 + ".stage"
        staged = native.add(backend.namespace_root("staging") / name,
                            kind="transport", raw=b"raw")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        with self.assertRaises(mod.ScienceCustodyNativeError):
            with backend.transaction():
                root.identity = (9, 9, 9)
                backend.delete_transport("staging", name,
                                         expected_identity=staged.identity,
                                         expected_sha256=sha256(staged.raw))
        self.assertEqual([], native.deletes)

    def test_drift_during_private_readback_blocks_rename(self):
        backend, native = self.make_backend("science")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        original_read = native.read
        def drift(handle, maximum):
            raw = original_read(handle, maximum)
            if handle.obj.path.name == ".custody-transport.tmp":
                root.identity = (9, 9, 9)
            return raw
        native.read = drift
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.create_transport("requests", "request.json", b"raw")
        self.assertEqual([], native.renames)

    def test_drift_during_cleanup_snapshot_blocks_delete(self):
        backend, native = self.make_backend("science")
        name = "a" * 32 + ".stage"
        staged = native.add(backend.namespace_root("staging") / name,
                            kind="transport", raw=b"raw")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        original_read = native.read
        def drift(handle, maximum):
            raw = original_read(handle, maximum)
            if handle.obj is staged:
                root.identity = (9, 9, 9)
            return raw
        native.read = drift
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.delete_transport("staging", name,
                                     expected_identity=staged.identity,
                                     expected_sha256=sha256(staged.raw))
        self.assertEqual([], native.deletes)

    def test_drift_during_duplicate_read_blocks_private_delete(self):
        backend, native = self.make_backend("writer")
        relative = "sessions/scope/final.json"
        backend.create_trusted("custody", relative, b"raw")
        target = backend.namespace_root("custody") / relative
        root = native.objects[mod._path_key(backend.namespace_root("arrivals"))]
        original_read = native.read
        def drift(handle, maximum):
            raw = original_read(handle, maximum)
            if mod._path_key(handle.obj.path) == mod._path_key(target):
                root.identity = (9, 9, 9)
            return raw
        native.read = drift
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.create_trusted("custody", relative, b"raw")
        self.assertEqual([], native.deletes)

    def test_drift_during_scratch_validation_blocks_delete(self):
        backend, native = self.make_backend("science")
        scratch = native.add(backend.derived_root / ".custody-transport.tmp",
                             kind="transport", raw=b"partial")
        root = native.objects[mod._path_key(backend.namespace_root("custody"))]
        original_security = native.security
        def drift(handle):
            result = original_security(handle)
            if handle.obj is scratch:
                root.identity = (9, 9, 9)
            return result
        native.security = drift
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend._recover_transport_scratch()
        self.assertEqual([], native.deletes)

    def test_copy_never_reuses_source_object_and_closes_all_file_handles(self):
        backend, native = self.make_backend()
        staged = native.add(backend.namespace_root("staging") / ("a" * 32 + ".stage"),
                            kind="transport", raw=b"hello")
        raw = backend.read_staged("a" * 32 + ".stage", maximum=20)
        created, final = backend.create_trusted("custody", "sessions/scope/data.json", raw.raw)
        self.assertTrue(created)
        self.assertNotEqual(staged.identity, final.file_identity)
        self.assertEqual(WRITER, final.owner_sid)
        self.assertEqual(b"hello", final.raw)
        self.assertTrue(all(h.closed for h in native.handles.values()
                            if not h.obj.attributes & mod.DIRECTORY and h is not backend._lease))
        self.assertTrue(all(source.parent == backend.namespace_root("private")
                            for _, source, target in native.renames))

    def test_actual_read_handles_exclude_write_and_delete_sharing(self):
        backend, native = self.make_backend()
        name = "a" * 32 + ".stage"
        native.add(backend.namespace_root("staging") / name, kind="transport", raw=b"x")
        backend.read_staged(name, maximum=2)
        options = [x for p, x in native.opens if p.name == name][-1]
        self.assertEqual(1, options["share"])
        self.assertEqual(mod.READ, options["access"])

    def test_wrong_owner_reparse_hardlink_and_size_stop_before_bytes(self):
        for attack in ("owner", "reparse", "hardlink", "oversize"):
            with self.subTest(attack=attack):
                backend, native = self.make_backend()
                name = "a" * 32 + ".stage"
                obj = native.add(backend.namespace_root("staging") / name,
                                 kind="transport", raw=b"12345")
                if attack == "owner":
                    obj.security = replace(obj.security, owner=WRITER)
                elif attack == "reparse":
                    obj.attributes |= mod.REPARSE
                elif attack == "hardlink":
                    obj.links = 2
                with self.assertRaises(mod.ScienceCustodyNativeError):
                    backend.read_staged(name, maximum=3 if attack == "oversize" else 10)

    def test_descriptor_mutation_during_read_is_not_favorable_snapshot(self):
        backend, native = self.make_backend()
        name = "a" * 32 + ".stage"
        obj = native.add(backend.namespace_root("staging") / name, kind="transport", raw=b"x")
        read = native.read
        def mutate(handle, maximum):
            value = read(handle, maximum)
            obj.security = replace(obj.security, protected=False)
            return value
        native.read = mutate
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.read_staged(name, maximum=10)

    def test_fixed_pin_work_and_retained_handles_do_not_grow_with_history(self):
        backend, native = self.make_backend()
        fixed = len(backend._fixed_keys)
        counts = []
        for index in range(60):
            before = native.security_calls
            backend.create_trusted("custody", f"sessions/scope{index}/final.json", b"x")
            counts.append(native.security_calls - before)
            self.assertEqual(fixed, len(backend._pins))
        self.assertEqual(min(counts), max(counts))
        # Entry, directory creation, and rename each retain a full pre-effect gate.
        self.assertLess(max(counts), 4 * fixed + 20)

    def test_finite_pin_bound_fails_closed(self):
        p = policy()
        count = len(p.roots) + len(p.ancestors)
        backend, native = self.make_backend(max_pinned_directories=count + 2)
        with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "finite bound"):
            backend.create_trusted("custody", "one/two/three/file.json", b"x")
        self.assertEqual(len(backend._fixed_keys), len(backend._pins))

    def test_partial_private_write_is_reused_from_exact_new_raw(self):
        backend, native = self.make_backend()
        native.fail_write = True
        with self.assertRaises(OSError):
            backend.create_trusted("custody", "sessions/scope/file.json", b"payload")
        private = backend.namespace_root("private")
        partials = [o for o in native.objects.values() if o.path.parent == private and o.path.suffix == ".tmp"]
        self.assertEqual(1, len(partials))
        self.assertEqual(b"pa", partials[0].raw)
        self.assertTrue(backend.create_trusted("custody", "sessions/scope/file.json", b"payload")[0])
        self.assertFalse(any(o.path.parent == private and o.path.suffix == ".tmp"
                             for o in native.objects.values()))

    def test_existing_final_readback_matches_or_fails_without_overwrite(self):
        backend, native = self.make_backend()
        first = backend.create_trusted("custody", "sessions/file.json", b"payload")
        second = backend.create_trusted("custody", "sessions/file.json", b"payload")
        self.assertFalse(second[0])
        self.assertEqual(first[1], second[1])
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.create_trusted("custody", "sessions/file.json", b"changed")
        self.assertEqual(b"payload", backend.read_trusted(
            "custody", "sessions/file.json", maximum=100).raw)

    def test_fixed_scratch_is_unpublished_and_recovered_by_handle(self):
        backend, native = self.make_backend("science")
        native.fail_write = True
        with self.assertRaises(OSError):
            backend.create_transport("staging", "a" * 32 + ".stage", b"payload")
        scratch = backend.derived_root / ".custody-transport.tmp"
        prior = native.objects[mod._path_key(scratch)]
        self.assertEqual(b"pa", prior.raw)
        final = backend.create_transport("staging", "a" * 32 + ".stage", b"payload")
        self.assertIn(prior.identity, native.deletes)
        self.assertNotIn(mod._path_key(scratch), native.objects)
        self.assertEqual(b"payload", final.raw)
        self.assertTrue(all(source == scratch for _, source, target in native.renames))

    def test_cleanup_mismatch_is_conflict_not_success_or_false(self):
        backend, native = self.make_backend("science")
        name = "a" * 32 + ".stage"
        e = backend.create_transport("staging", name, b"payload")
        for identity, digest in (((9, 9, 9), hashlib.sha256(b"payload").hexdigest()),
                                 (e.file_identity, hashlib.sha256(b"wrong").hexdigest())):
            with self.assertRaises(CustodyCommitConflict):
                backend.delete_transport("staging", name, expected_identity=identity,
                                         expected_sha256=digest)
        self.assertEqual([], native.deletes)
        self.assertIn(mod._path_key(backend.namespace_root("staging") / name), native.objects)

    def test_cleanup_false_only_when_absent(self):
        backend, native = self.make_backend("science")
        name = "a" * 32 + ".stage"
        self.assertFalse(backend.delete_transport("staging", name, expected_identity=(1, 2, 3),
                                                  expected_sha256="a" * 64))

    def test_handle_cleanup_cannot_delete_newer_path_generation(self):
        backend, native = self.make_backend("science")
        name = "a" * 32 + ".stage"
        old = backend.create_transport("staging", name, b"old")
        path = backend.namespace_root("staging") / name
        deletion = native.delete
        newer = []
        def concurrent_replace(handle):
            newer.append(native.add(path, kind="transport", raw=b"newer"))
            deletion(handle)
        native.delete = concurrent_replace
        self.assertTrue(backend.delete_transport("staging", name,
                expected_identity=old.file_identity, expected_sha256=hashlib.sha256(b"old").hexdigest()))
        self.assertIs(native.objects[mod._path_key(path)], newer[0])
        self.assertEqual(b"newer", newer[0].raw)

    def test_bounded_enumeration_uses_capacity_plus_one_sentinel_only(self):
        backend, native = self.make_backend()
        consumed = []
        class Entries:
            def __enter__(self):
                def values():
                    for i in range(1000):
                        consumed.append(i)
                        yield SimpleNamespace(name=f"{i}.stage")
                return values()
            def __exit__(self, *args):
                return False
        with patch.object(mod.os, "scandir", return_value=Entries()):
            self.assertEqual(("0.stage", "1.stage", "2.stage"), backend.bounded_names("staging", 3))
        self.assertEqual([0, 1, 2], consumed)
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.bounded_names("staging", 4)

    def test_readonly_evidence_never_claims_scm_or_destructive_probe(self):
        backend, native = self.make_backend("science")
        observed = backend.security_contract_evidence
        self.assertFalse(observed["actual_scm_qualification"])
        self.assertFalse(observed["runtime_destructive_probes"])
        self.assertTrue(observed["exact_owner_dacl_label_policy_verified"])
        self.assertEqual(set(mod.TRUSTED), set(backend.validate_readonly_roots()))

    def large_metadata_request(self, backend, native, generation="1" * 32):
        # A real protocol-valid quarantine occurrence has a long logical key,
        # while the request stays below the admitted 2048-byte wire ceiling.
        partial = {"partial_name": "x" * 1024}
        raw = canonical_json_bytes({"partial_before": partial})
        path = "quarantine-receipts/" + sha256(canonical_json_bytes(partial)) + ".quarantine.json"
        request = CustodyCommitRequest(backend.policy_sha256,
            identity_for_artifact(source_root_identity=backend.source_root_identity,
                                  final_root="custody", relative_path=path, raw=raw),
            "custody", path, sha256(raw), sha256(raw), len(raw), generation + ".stage", generation)
        self.assertLessEqual(len(request.to_bytes()), backend.max_request_bytes)
        native.add(backend.namespace_root("staging") / request.staging_name,
                   kind="transport", raw=raw)
        return request

    @staticmethod
    def memory_scandir(native, path):
        values = []
        for obj in tuple(native.objects.values()):
            if mod._path_key(obj.path.parent) == mod._path_key(path):
                values.append(SimpleNamespace(name=obj.path.name,
                    stat=lambda *, follow_symlinks, obj=obj: SimpleNamespace(st_file_attributes=obj.attributes)))
        class Entries:
            def __enter__(self):
                return iter(values)
            def __exit__(self, *args):
                return False
        return Entries()

    def test_lower_wire_cap_real_protocol_publish_duplicate_lookup_and_metadata_audit(self):
        backend, native = self.make_backend(max_request_bytes=2048)
        request = self.large_metadata_request(backend, native)
        finalizer = ScienceCustodyFinalizer(backend)
        result = finalizer.finalize(request)
        self.assertTrue(result.created)
        duplicate = replace(request, generation="2" * 32, staging_name="2" * 32 + ".stage")
        self.assertEqual(result.receipt, finalizer.finalize(duplicate).receipt)
        self.assertEqual(result.receipt, ScienceCustodyFinalizer(backend).lookup(request).receipt)
        for namespace, relative in (("claims", claim_path(request.identity.digest())),
                                    ("receipts", receipt_path(request.identity.digest()))):
            value = backend.read_trusted(namespace, relative, maximum=mod.PROTOCOL_METADATA_BYTES)
            self.assertGreater(len(value.raw), backend.max_request_bytes)
            self.assertLessEqual(len(value.raw), mod.PROTOCOL_METADATA_BYTES)
            expected = [backend.namespace_root(namespace) / relative]
            if namespace == 'receipts':
                from momentum_hunter.science_custody_commit import completion_path
                expected.append(backend.namespace_root(namespace) / completion_path(request.identity.digest()))
            with patch.object(mod.os, "scandir", side_effect=lambda path: self.memory_scandir(native, path)):
                self.assertEqual(tuple(sorted(expected)),
                                 backend.iter_trusted(namespace, suffix=".json"))

    def test_lower_wire_cap_lost_receipt_recovery_preserves_original_final_and_claim(self):
        for phase in ("after_final", "after_receipt"):
            with self.subTest(crash=phase):
                backend, native = self.make_backend(max_request_bytes=2048)
                request = self.large_metadata_request(backend, native)
                def crash(at):
                    if at == phase:
                        raise RuntimeError("synthetic lost receipt")
                with self.assertRaisesRegex(RuntimeError, "lost receipt"):
                    ScienceCustodyFinalizer(backend, fault_hook=crash).finalize(request)
                final = backend.read_trusted(request.final_root, request.final_relative_path,
                                             maximum=backend.max_artifact_bytes)
                claim = backend.read_trusted("claims", claim_path(request.identity.digest()),
                                             maximum=mod.PROTOCOL_METADATA_BYTES)
                backend.close()
                with patch.object(mod, "_Native", return_value=native):
                    reopened = mod.WindowsScienceCustodyBackend(backend.policy, role="writer")
                self.addCleanup(reopened.close)
                recovered = ScienceCustodyFinalizer(reopened).finalize(request)
                self.assertFalse(recovered.created)
                self.assertEqual(phase == "after_final", recovered.recovered_receipt)
                self.assertEqual(final, reopened.read_trusted(request.final_root, request.final_relative_path,
                                                             maximum=reopened.max_artifact_bytes))
                self.assertEqual(claim, reopened.read_trusted("claims", claim_path(request.identity.digest()),
                                                             maximum=mod.PROTOCOL_METADATA_BYTES))
                self.assertEqual(recovered.receipt, ScienceCustodyFinalizer(reopened).lookup(request).receipt)

    def test_metadata_byte_primitive_exact_ceiling_separate_from_wire_and_artifact_caps(self):
        # Arbitrary byte arrays here test only native bounded storage, not
        # semantic validity as a claim/receipt in the protocol decoder.
        backend, native = self.make_backend(max_request_bytes=2048, max_artifact_bytes=64)
        for namespace in ("claims", "receipts"):
            raw = b"x" * mod.PROTOCOL_METADATA_BYTES
            self.assertTrue(backend.create_trusted(namespace, "exact.json", raw)[0])
            self.assertEqual(raw, backend.read_trusted(namespace, "exact.json", maximum=len(raw)).raw)
            before = len(native.objects)
            with self.assertRaises(mod.ScienceCustodyNativeError):
                backend.create_trusted(namespace, "too-big.json", raw + b"x")
            self.assertEqual(before, len(native.objects))
            with self.assertRaises(mod.ScienceCustodyNativeError):
                backend.read_trusted(namespace, "exact.json", maximum=len(raw) + 1)
            native.objects[mod._path_key(backend.namespace_root(namespace) / "exact.json")].raw += b"x"
            with self.assertRaises(mod.ScienceCustodyNativeError):
                backend.read_trusted(namespace, "exact.json", maximum=len(raw))
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.create_trusted("custody", "too-big.json", b"x" * 65)
        with self.assertRaises(mod.ScienceCustodyNativeError):
            backend.read_request("request.json", maximum=2049)
        science, sn = self.make_backend("science", max_request_bytes=2048, max_artifact_bytes=64)
        with self.assertRaises(mod.ScienceCustodyNativeError):
            science.create_transport("requests", "request.json", b"x" * 2049)
        with self.assertRaises(mod.ScienceCustodyNativeError):
            science.create_transport("staging", "a" * 32 + ".stage", b"x" * 65)

    def test_wire_request_oversize_still_rejected_before_finalizer_native_io(self):
        backend, native = self.make_backend()
        request = self.large_metadata_request(backend, native)
        backend, native = self.make_backend(max_request_bytes=len(request.to_bytes()) - 1)
        request = replace(request, policy_sha256=backend.policy_sha256)
        before = len(native.opens)
        with self.assertRaises(CustodyCommitError):
            ScienceCustodyFinalizer(backend).finalize(request)
        self.assertEqual(before, len(native.opens))

    def test_exact_two_capacity_writer_empty_poll_and_overflow_use_three_sentinel(self):
        backend, native = self.make_backend()
        mailbox = ScienceCustodyMailboxWriter(ScienceCustodyFinalizer(backend), mailbox_backend=backend)
        with patch.object(mod.os, "scandir", side_effect=lambda path: self.memory_scandir(native, path)):
            self.assertIsNone(mailbox.poll_once())
            for index in range(3):
                native.add(backend.namespace_root("staging") / (f"{index:032x}.stage"), kind="transport")
            with self.assertRaises(CustodyCommitError):
                mailbox.poll_once()


class QualificationPropagationTests(unittest.TestCase):
    """Pure machinery checks; no Windows identity is queried or impersonated."""

    def test_worker_close_failure_is_recorded_and_propagated(self):
        def checked(value, label):
            if not value:
                raise RuntimeError(label)
            return value
        n = SimpleNamespace(
            k=SimpleNamespace(GetCurrentThreadId=lambda: 123,
                              OpenThread=lambda *args: 456, CloseHandle=lambda handle: False),
            a=SimpleNamespace(ImpersonateAnonymousToken=lambda handle: True,
                              RevertToSelf=lambda: True), checked=checked,
            token=lambda: {"user": qualifier.ANON, "owner": qualifier.ANON,
                           "integrity": qualifier.UNTRUSTED, "privileges": ()})
        receipt = {"operations": [], "checks": []}
        with patch.object(qualifier, "REC", receipt), patch.object(
                qualifier, "absent_thread_token", return_value={"success": False, "win32Error": 1008}):
            with self.assertRaisesRegex(RuntimeError, "Close thread handle"):
                qualifier.anonymous(n, "close-failure", lambda: {"success": True})
        self.assertEqual(1, len(receipt["operations"]))
        self.assertIn("cleanup_failure", receipt["operations"][0])
        self.assertTrue(receipt["operations"][0]["revert"]["success"])

    def test_worker_initial_token_query_failure_is_propagated(self):
        n = SimpleNamespace(k=SimpleNamespace(GetCurrentThreadId=lambda: 123))
        receipt = {"operations": [], "checks": []}
        with patch.object(qualifier, "REC", receipt), patch.object(
                qualifier, "absent_thread_token", side_effect=RuntimeError("snapshot failed")):
            with self.assertRaisesRegex(RuntimeError, "snapshot failed"):
                qualifier.anonymous(n, "initial-failure", lambda: {"success": True})
        self.assertEqual(1, len(receipt["operations"]))
        self.assertIn("failure", receipt["operations"][0])


class NativeMarshallingTests(unittest.TestCase):
    def test_rename_has_exact_payload_length_and_in_buffer_wchar_terminator(self):
        """Inspect actual production marshalling; never invoke a Windows API."""
        primitive = object.__new__(mod._Native)
        primitive.w = wintypes
        calls = []
        class RenameInfo(ctypes.Structure):
            _fields_ = [("replace", wintypes.BOOL), ("root", wintypes.HANDLE),
                        ("length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]
        def capture(handle, info_class, buffer, count):
            header = RenameInfo.from_buffer(buffer)
            payload = bytes(buffer)[RenameInfo.name.offset:]
            calls.append((handle, info_class, header.replace, header.root,
                          header.length, count, payload))
            # Model a NUL-scanning wrapper, with nonzero poison immediately
            # AFTER the supplied count. It must terminate inside that count.
            poison = "POISON".encode("utf-16-le")
            tail = payload + poison
            units = [tail[i:i + 2] for i in range(0, len(tail), 2)]
            terminator = units.index(b"\0\0") * 2
            self.assertLess(terminator, len(payload))
            self.assertEqual(header.length, terminator)
            self.assertEqual(payload[:terminator].decode("utf-16-le"), mod._io_path(target))
            return True
        primitive.k = SimpleNamespace(SetFileInformationByHandle=capture)
        handle = SimpleNamespace(value=123, path=Path("C:/old.tmp"))
        for name in ("a.claim.json", "f" * 64 + ".claim.json"):
            target = Path("C:/custody-007-pure-test/claims/ff") / name
            primitive.rename(handle, target)
            recorded = calls[-1]
            self.assertEqual((123, 3, 0, None), recorded[:4])
            self.assertEqual(len(mod._io_path(target).encode("utf-16-le")), recorded[4])
            self.assertEqual(RenameInfo.name.offset + recorded[4] + ctypes.sizeof(wintypes.WCHAR),
                             recorded[5])
            self.assertEqual(b"\0" * ctypes.sizeof(wintypes.WCHAR), recorded[6][recorded[4]:])
            self.assertEqual(target, handle.path)


if __name__ == "__main__":
    unittest.main()
