"""Deterministic setup interleavings, not elevated physical acceptance."""
from dataclasses import replace
import copy
import ctypes as c
import json
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from momentum_hunter import windows_science_custody_setup as s
from momentum_hunter import windows_science_custody as n
from momentum_hunter import science_mutable_policy as b
from tests.test_science_mutable_policy_020g import SCIENCE, security

USER = "S-1-5-21-1-2-3-1001"
ROOT = "F:/q/science"


def initial_security():
    return n._Security(USER, "setup-only", ((0, 3, 0x1F01FF, USER), (0, 3, 0x1F01FF, "S-1-5-18")),
                       ((3, 1, b.HIGH),), True, USER, 0x9C14)


class Handle:
    def __init__(self, native, path, access):
        self.native, self.path, self.access = native, Path(path), access
        self.obj = native.objects[n._path_key(path)]
        self.closed = False

    def close(self):
        self.closed = True
        self.native.actions.append(("close", str(self.path)))
        self.native.hook("close", self)


class SetupNative:
    def __init__(self):
        self.objects, self.handles, self.actions = {}, [], []
        self.hook = lambda stage, handle: None
        self.initial = dict(thread_token=False, token_type=1, elevation=1,
                            integrity=b.HIGH, user=USER,
                            privilege_attributes=(("SeRestorePrivilege", 2),))
        self.default = initial_security().aces
        for path in (PureWindowsPath(ROOT), *PureWindowsPath(ROOT).parents):
            self.add(path)
        self.approved = tuple(n.CustodyRootBinding("ancestor", str(path), self.objects[n._path_key(path)].identity,
                           USER, initial_security().digest) for path in (PureWindowsPath(ROOT), *PureWindowsPath(ROOT).parents))

    def add(self, path, sec=None):
        obj = SimpleNamespace(identity=(1, 0, len(self.objects) + 1), security=sec or initial_security(),
                              attributes=n.DIRECTORY, children=[])
        self.objects[n._path_key(path)] = obj
        return obj

    def token(self):
        self.hook("token", None)
        return copy.deepcopy(self.initial)

    def default_aces(self):
        return self.default

    def creation_defaults(self):
        return dict(owner=USER, group=USER, control=0x8C14, protected=False,
                    aces=tuple((t, 0, m, sid) for t, _, m, sid in self.default),
                    labels=((0, 1, b.HIGH),))

    def exists(self, path):
        self.hook("exists", path)
        return n._path_key(path) in self.objects

    def open(self, path, **options):
        self.hook("open", path)
        self.actions.append(("open", str(path), options))
        h = Handle(self, path, options["access"])
        self.handles.append(h)
        return h

    def handle_flags(self, h):
        self.hook("handle_flags", h)
        return getattr(h, "flags", 0)

    def granted_access(self, h):
        self.hook("granted_access", h)
        return h.access | 0x100000

    def information(self, h):
        self.hook("information", h)
        return SimpleNamespace(dwFileAttributes=h.obj.attributes)

    def require_path(self, h, path):
        self.hook("path", h)
        n._require(self.objects[n._path_key(path)] is h.obj, "Replaced pathname")

    def security(self, h):
        self.hook("security", h)
        return h.obj.security

    def identity(self, h):
        self.hook("identity", h)
        return h.obj.identity

    def descriptor_bytes(self, h):
        self.hook("descriptor", h)
        return h.obj.security.sddl.encode("ascii")

    def inherited_create(self, path):
        self.hook("create", path)
        n._require(n._path_key(path) not in self.objects, "Already exists; never restamp")
        kind = next(k for k in s.KINDS if n._path_key(b.namespace_path(ROOT, k)) == n._path_key(path))
        sec = initial_security()
        if kind in {"owner", "derived", "scratch"}:
            sec = replace(sec, **dict(self.creation_defaults(), labels=(), control=0x8C04))
        self.add(path, sec)
        self.actions.append(("create", str(path)))
        return dict(api="CreateDirectoryW", boolResult=True, winerror=0, securityAttributes=None)

    def labeled_create(self, path):
        self.hook("create", path)
        n._require(n._path_key(path) not in self.objects, "Already exists; never restamp")
        self.add(path, replace(initial_security(), **self.creation_defaults()))
        self.actions.append(("create", str(path)))
        self.hook("labeled_created", path)
        return dict(api="CreateDirectoryW", boolResult=True, winerror=0,
                    securityAttributes=dict(sddl=s.LABEL_ONLY, handleInherit=False))

    def require_empty(self, h):
        self.hook("empty", h)
        n._require(not h.obj.children, "Not empty")

    def apply_policy(self, h, sddl):
        self.hook("apply", h)
        kind = next(k for k in s.KINDS if n._path_key(b.namespace_path(ROOT, k)) == n._path_key(h.path))
        assert sddl == b.parent_sddl(SCIENCE, kind)
        assert h.access == s.SETUP_ACCESS and not h.closed
        h.obj.security = security(kind, True)
        self.actions.append(("apply", str(h.path), h))
        self.hook("applied", h)
        return 0


class SetupParityTests(unittest.TestCase):
    def setUp(self):
        self.native, self.receipts = SetupNative(), []

    def run_setup(self, **kwargs):
        with patch.object(s, "_SetupNative", return_value=self.native):
            return s.provision_mutable_parents(ROOT, SCIENCE, approved_ancestry=self.native.approved,
                                              record=self.receipts.append, **kwargs)

    def assert_closed_failed(self):
        self.assertTrue(all(h.closed for h in self.native.handles))
        self.assertEqual(self.receipts[-1]["stage"], "SETUP_FINALLY")
        self.assertFalse(self.receipts[-1]["success"])

    def test_six_classes_inherited_create_retained_assignment_and_strict_readback(self):
        result = self.run_setup()
        self.assertEqual(result.version, 2)
        self.assertEqual(len(result.roots), 5)
        self.assertEqual(len([x for x in self.native.actions if x[0] == "apply"]), 6)
        for kind in s.KINDS:
            rows = [x for x in self.receipts if x.get("parentClass") == kind]
            final = next(x for x in rows if x["stage"] == "FINAL_READBACK")
            self.assertEqual(final["allDifferingFields"], [])
            self.assertEqual(final["actualDescriptor"]["control"], 0x9C14)
            self.assertEqual(final["actualDescriptor"]["control"] & ~0x810, 0x9404)
        self.assertTrue(self.receipts[-1]["tokenUnchanged"])
        self.assertTrue(all(h.closed for h in self.native.handles))

    def test_exact_existing_objects_require_original_identity_and_never_apply(self):
        result = self.run_setup()
        self.native.actions.clear()
        self.run_setup(existing_parents=(result.common, *result.roots))
        self.assertFalse(any(x[0] in {"create", "apply"} for x in self.native.actions))
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "original approved"):
            self.run_setup()

    def test_existing_replacement_fails_even_with_matching_policy(self):
        result = self.run_setup()
        self.native.objects[n._path_key(result.common.path)].identity = (1, 99, 99)
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "original binding"):
            self.run_setup(existing_parents=(result.common, *result.roots))

    def test_existing_wrong_policy_rejected_not_restamped(self):
        result = self.run_setup()
        obj = self.native.objects[n._path_key(result.common.path)]
        obj.security = replace(obj.security, control=0x9814)
        before = len([x for x in self.native.actions if x[0] == "apply"])
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "exact Architecture-B"):
            self.run_setup(existing_parents=(result.common, *result.roots))
        self.assertEqual(before, len([x for x in self.native.actions if x[0] == "apply"]))

    def test_all_wrong_security_fields_fail_with_field_receipt(self):
        good = security(b.COMMON, True)
        variations = [dict(owner=USER), dict(group=USER), dict(control=0x9814), dict(control=0x9D14),
                      dict(control=0x8C14, protected=False), dict(aces=tuple(reversed(good.aces))),
                      dict(aces=((0, 3, 1, USER), *good.aces[1:])), dict(labels=((0, 1, "S-1-16-8192"),))]
        for changes in variations:
            with self.subTest(changes=changes):
                self.setUp()
                self.native.hook = lambda stage, h: setattr(h.obj, "security", replace(good, **changes)) if stage == "applied" else None
                with self.assertRaises(n.ScienceCustodyNativeError):
                    self.run_setup()
                failure = next(r for r in self.receipts if r["stage"] == "FAILURE_BEFORE_HANDLE_CLOSURE")
                self.assertTrue(failure["allDifferingFields"])
                self.assert_closed_failed()

    def test_create_apply_readback_interrupt_failures_close_and_preserve(self):
        for point in ("create", "apply", "applied", "descriptor"):
            with self.subTest(point=point):
                self.setUp()
                def fail(stage, h):
                    if stage == point:
                        raise OSError("forced " + point)
                self.native.hook = fail
                with self.assertRaises(OSError):
                    self.run_setup()
                self.assert_closed_failed()
                self.assertTrue(any(r["stage"] == "FAILURE" for r in self.receipts))
                self.assertIn("PRESERVED", self.receipts[-1]["ownedObjectDisposition"])

    def test_partial_failure_is_not_resumed_on_restart(self):
        self.native.hook = lambda stage, h: (_ for _ in ()).throw(OSError("apply")) if stage == "apply" else None
        with self.assertRaises(OSError):
            self.run_setup()
        self.native.hook = lambda stage, h: None
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "quarantined"):
            self.run_setup()
        self.assertFalse(any(x[0] == "apply" for x in self.native.actions))

    def test_existing_path_race_fails_before_assignment(self):
        def collision(stage, path):
            if stage == "create":
                self.native.add(path, security(b.COMMON, True))
        self.native.hook = collision
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "Already exists"):
            self.run_setup()
        self.assertFalse(any(x[0] == "apply" for x in self.native.actions))

    def test_reparse_replacement_nonempty_and_ancestor_drift_fail(self):
        for defect in ("reparse", "replacement", "nonempty", "ancestor"):
            with self.subTest(defect=defect):
                self.setUp()
                def mutate(stage, h):
                    if stage != "empty":
                        return
                    if defect == "reparse":
                        h.obj.attributes |= n.REPARSE
                    elif defect == "replacement":
                        self.native.add(h.path)
                    elif defect == "nonempty":
                        h.obj.children.append("foreign")
                    else:
                        self.native.objects[n._path_key(ROOT)].identity = (9, 9, 9)
                self.native.hook = mutate
                with self.assertRaises(n.ScienceCustodyNativeError):
                    self.run_setup()
                self.assert_closed_failed()

    def test_wrong_granted_or_inherited_handle_fails(self):
        for stage, attr, value in (("granted_access", "access", 0x1F01FF), ("handle_flags", "flags", 1)):
            self.setUp()
            self.native.hook = lambda actual, h: setattr(h, attr, value) if actual == stage else None
            with self.assertRaisesRegex(n.ScienceCustodyNativeError, "setup handle authority"):
                self.run_setup()
            self.assert_closed_failed()

    def test_sealed_arm_b_requested_and_granted_rights_remain_distinct(self):
        self.run_setup()
        rows = [r for r in self.receipts if r["stage"] == "HANDLE" and r["requested"] == 0xE0080]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["granted"] == r["expectedGranted"] == 0x1E0080 and r["flags"] == 0 for r in rows))

    def test_unaccounted_grants_and_flags_fail_without_assignment(self):
        for grant, flags in ((0xE0080, 0), (0x1E0081, 0), (0x1F0080, 0),
                             (0x1E0080, 1), (0x1E0080, 2), (0x1E0080, 4)):
            with self.subTest(grant=grant, flags=flags):
                self.setUp()
                self.native.granted_access = lambda h: grant if h.access == s.SETUP_ACCESS else h.access
                self.native.handle_flags = lambda h: flags if h.access == s.SETUP_ACCESS else 0
                with self.assertRaisesRegex(n.ScienceCustodyNativeError, "setup handle authority"):
                    self.run_setup()
                self.assertFalse(any(x[0] == "apply" for x in self.native.actions))
                self.assert_closed_failed()

    def test_early_retained_handle_failures_inspected_before_closure(self):
        for point in ("granted_access", "handle_flags", "HANDLE"):
            with self.subTest(point=point):
                self.setUp()
                inspected = []
                def hook(stage, handle):
                    if handle is None or getattr(handle, "access", None) != s.SETUP_ACCESS:
                        return
                    if stage in ("identity", "descriptor"):
                        inspected.append((stage, not handle.closed))
                    if stage == point:
                        raise OSError(point)
                self.native.hook = hook
                def record(row):
                    if row["stage"] == point and row.get("requested") == s.SETUP_ACCESS:
                        raise OSError(point)
                    self.receipts.append(row)
                with patch.object(s, "_SetupNative", return_value=self.native):
                    with self.assertRaises(OSError):
                        s.provision_mutable_parents(ROOT, SCIENCE, approved_ancestry=self.native.approved, record=record)
                self.assertEqual(set(inspected), {("identity", True), ("descriptor", True)})
                failure = next(r for r in self.receipts if r["stage"] == "FAILURE")
                self.assertIsNotNone(failure["objectIdentity"])
                self.assertEqual(failure["failureInspection"]["unavailable"], {})
                self.assertEqual(self.receipts[-1]["ownedObjects"][0]["identity"], failure["objectIdentity"])
                self.assert_closed_failed()

    def test_failed_queries_are_independent_and_explicitly_unavailable(self):
        for point, missing in (("identity", "identity"), ("security", "descriptor"), ("descriptor", "descriptorBytes")):
            with self.subTest(point=point):
                self.setUp()
                def hook(stage, handle):
                    if handle is not None and getattr(handle, "access", None) == s.SETUP_ACCESS and stage in {"granted_access", point}:
                        raise OSError(stage)
                self.native.hook = hook
                with self.assertRaises(OSError):
                    self.run_setup()
                failure = next(r for r in self.receipts if r["stage"] == "FAILURE")["failureInspection"]
                self.assertEqual(set(failure["unavailable"]), {missing})
                self.assertEqual(failure["objectIdentity"] is None, point == "identity")
                self.assertEqual(failure["actualDescriptor"] is None, point == "security")
                self.assertEqual(failure["binarySdHex"] is None, point == "descriptor")
                self.assert_closed_failed()

    def test_missing_handle_does_not_infer_owned_identity_from_path(self):
        def fail(stage, value):
            if stage == "open" and n._path_key(value) == n._path_key(b.namespace_path(ROOT, b.COMMON)):
                raise OSError("open")
        self.native.hook = fail
        with self.assertRaises(OSError):
            self.run_setup()
        failure = next(r for r in self.receipts if r["stage"] == "FAILURE")["failureInspection"]
        self.assertTrue(all(v["reason"] == "NO_RETAINED_HANDLE" for v in failure["unavailable"].values()))
        self.assertIsNone(self.receipts[-1]["ownedObjects"][0]["identity"])
        self.assert_closed_failed()

    def test_untrusted_intermediate_grant_rejected_before_create(self):
        self.native.default += ((0, 3, 0x1F01FF, SCIENCE),)
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "outside setup"):
            self.run_setup()
        self.assertFalse(any(x[0] == "create" for x in self.native.actions))

    def test_privilege_change_fails_no_admission(self):
        def change(stage, h):
            if stage == "applied":
                self.native.initial["privilege_attributes"] = (("SeRestorePrivilege", 0),)
        self.native.hook = change
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "token changed"):
            self.run_setup()
        self.assert_closed_failed()
        self.assertFalse(self.receipts[-1]["tokenUnchanged"])

    def test_evidence_sink_failure_still_closes_retained_handles(self):
        def fail(row):
            if row["stage"] == "CREATED_INHERITED":
                raise OSError("disk")
            self.receipts.append(row)
        with patch.object(s, "_SetupNative", return_value=self.native):
            with self.assertRaises(OSError):
                s.provision_mutable_parents(ROOT, SCIENCE, approved_ancestry=self.native.approved, record=fail)
        self.assert_closed_failed()

    def test_closure_failure_blocks_success_and_records_failure(self):
        self.native.hook = lambda stage, h: (_ for _ in ()).throw(OSError("close")) if stage == "close" else None
        with self.assertRaises(OSError):
            self.run_setup()
        self.assertTrue(self.receipts[-1]["cleanupErrors"])
        self.assertFalse(self.receipts[-1]["success"])

    def test_native_read_only_token_default_acl_and_abi(self):
        native = s._SetupNative()
        self.assertTrue(native.default_aces())
        self.assertEqual(native.a.SetSecurityInfo.restype, native.w.DWORD)
        self.assertEqual(native.k.GetHandleInformation.argtypes[0], native.w.HANDLE)
        self.assertEqual(s.SET_SECURITY_INFORMATION, 0x80000017)

    def test_native_assignment_exact_components_and_dword_error_contract(self):
        native = s._SetupNative()
        calls = []
        def assignment(handle, object_type, flags, owner, group, dacl, sacl):
            calls.append((handle, object_type, flags, native.sid(owner), native.sid(group)))
            self.assertTrue(dacl.value and sacl.value)
            return 0
        with patch.object(native.a, "SetSecurityInfo", side_effect=assignment):
            self.assertEqual(native.apply_policy(SimpleNamespace(value=77), b.parent_sddl(SCIENCE, b.COMMON)), 0)
        self.assertEqual(calls, [(77, 1, 0x80000017, b.WRITER, b.WRITER)])
        with patch.object(native.a, "SetSecurityInfo", return_value=5):
            with self.assertRaises(OSError):
                native.apply_policy(SimpleNamespace(value=77), b.parent_sddl(SCIENCE, b.COMMON))

    def test_unapproved_actor_rejected_before_filesystem_access(self):
        for changes in (dict(elevation=0), dict(thread_token=True), dict(token_type=2),
                        dict(user=SCIENCE), dict(privilege_attributes=())):
            self.setUp()
            self.native.initial.update(changes)
            with self.assertRaises(n.ScienceCustodyNativeError):
                self.run_setup()
            self.assertEqual(self.native.actions, [])

    def test_unsafe_root_inherited_grant_blocks_before_creation(self):
        obj = self.native.objects[n._path_key(ROOT)]
        obj.security = replace(obj.security, aces=(*obj.security.aces, (0, 3, 0x1F01FF, SCIENCE)))
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "outside setup"):
            self.run_setup()
        self.assertFalse(any(x[0] == "create" for x in self.native.actions))


if __name__ == "__main__":
    unittest.main()
