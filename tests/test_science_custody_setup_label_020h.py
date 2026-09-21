"""Label carrier and deterministic setup lifecycle; no elevated OS creation."""
import ctypes as c
from dataclasses import replace
import unittest
from unittest.mock import patch

from momentum_hunter import windows_science_custody_setup as s
from momentum_hunter import windows_science_custody as n
from momentum_hunter import science_mutable_policy as b
from tests.test_science_custody_setup_parity_020g import SetupNative, ROOT, USER
from tests.test_science_mutable_policy_020g import SCIENCE


class LabelSetupTests(unittest.TestCase):
    def setUp(self):
        self.native, self.rows = SetupNative(), []

    def run_setup(self, sink=None, **kwargs):
        with patch.object(s, "_SetupNative", return_value=self.native):
            return s.provision_mutable_parents(ROOT, SCIENCE, approved_ancestry=self.native.approved,
                                              record=sink or self.rows.append, **kwargs)

    def test_inherited_only_reproduces_missing_nested_label_before_assignment(self):
        self.native.labeled_create = self.native.inherited_create
        with self.assertRaisesRegex(n.ScienceCustodyNativeError, "accepted High/no-write-up label"):
            self.run_setup()
        common = next(r for r in self.rows if r["stage"] == "FINAL_READBACK")
        self.assertEqual(common["actualDescriptor"]["control"], 0x9C14)
        owner = next(r for r in self.rows if r["stage"] == "INTERMEDIATE_READBACK")
        self.assertEqual(owner["actualDescriptor"]["labels"], ())
        self.assertEqual(owner["actualDescriptor"]["control"], 0x8C04)
        self.assertFalse(any(r["stage"] == "SET_SECURITY_INFO" and r["parentClass"] == "owner" for r in self.rows))

    def test_all_six_exact_security_identity_and_no_privilege_change(self):
        self.run_setup()
        for kind in s.KINDS:
            with self.subTest(kind=kind):
                created = next(r for r in self.rows if r["stage"] == "CREATED_INHERITED" and r["parentClass"] == kind)
                final = next(r for r in self.rows if r["stage"] == "FINAL_READBACK" and r["parentClass"] == kind)
                self.assertEqual(created["objectIdentity"], final["objectIdentity"])
                self.assertEqual(final["allDifferingFields"], [])
                self.assertEqual(final["actualDescriptor"]["control"], 0x9C14)
                self.assertEqual(final["actualDescriptor"]["control"] & ~0x810, 0x9404)
                create = next(r for r in self.rows if r["stage"] == "CREATE" and r["parentClass"] == kind)
                self.assertEqual(create["securityAttributes"] is not None, kind in s.NESTED_KINDS)
                if kind in s.NESTED_KINDS:
                    self.assertEqual(created["actualDescriptor"]["labels"], ((0, 1, b.HIGH),))
                    self.assertEqual(created["actualDescriptor"]["control"], 0x8C14)
        last = self.rows[-1]
        self.assertEqual(last["tokenBefore"], last["tokenAfter"])
        self.assertFalse(last["productAdjustedPrivilege"])
        self.assertTrue(all(h.closed for h in self.native.handles))

    def test_native_carrier_rejects_all_nonlabel_contributions(self):
        native = s._SetupNative()
        bad = ("D:(A;;FA;;;SY)", "S:(ML;;NW;;;LW)", "S:(ML;;NW;;;ME)",
               "S:(ML;;;;;HI)", "S:(ML;;NR;;;HI)", "S:(ML;;NWNR;;;HI)",
               "S:(ML;OICI;NW;;;HI)", "S:(ML;;NW;;;HI)(AU;SA;FR;;;WD)",
               "D:(A;;FA;;;SY)S:(ML;;NW;;;HI)", "D:NO_ACCESS_CONTROLS:(ML;;NW;;;HI)",
               "O:SYS:(ML;;NW;;;HI)", "G:SYS:(ML;;NW;;;HI)", "S:AI(ML;;NW;;;HI)", "bad")
        with patch.object(native.k, "CreateDirectoryW") as create:
            for text in bad:
                with self.subTest(text=text), patch.object(s, "LABEL_ONLY", text):
                    with self.assertRaises((n.ScienceCustodyNativeError, OSError)):
                        native.labeled_create("F:/not-created")
            create.assert_not_called()

    def test_native_create_records_success_error_and_frees_carrier(self):
        native = s._SetupNative()
        freed = native.k.LocalFree
        seen = []
        def create(path, sa):
            native.validate_label_carrier(sa._obj.descriptor)
            self.assertFalse(sa._obj.inherit)
            seen.append(path)
            return True
        with patch.object(native.k, "CreateDirectoryW", side_effect=create), patch.object(native.k, "LocalFree", wraps=freed) as free:
            result = native.labeled_create("F:/not-created")
            self.assertEqual(result["winerror"], 0)
            self.assertTrue(result["boolResult"])
            self.assertTrue(result["securityAttributes"]["binarySdHex"])
            self.assertTrue(free.called)
        for error in (5, 183):
            def fail(*args):
                c.set_last_error(error)
                return False
            with patch.object(native.k, "CreateDirectoryW", side_effect=fail):
                with self.assertRaises(OSError) as caught:
                    native.labeled_create("F:/not-created")
                self.assertEqual(caught.exception.creation_receipt["winerror"], error)
                self.assertFalse(caught.exception.creation_receipt["boolResult"])

    def test_wrong_intermediate_fields_and_label_all_fail_closed(self):
        variants = [dict(labels=()), dict(labels=((0, 1, "S-1-16-4096"),)),
            dict(labels=((0, 1, "S-1-16-8192"),)), dict(labels=((0, 0, b.HIGH),)),
            dict(labels=((0, 3, b.HIGH),)), dict(labels=((3, 1, b.HIGH),)),
            dict(labels=((0, 1, b.HIGH), (0, 1, b.HIGH))), dict(owner=SCIENCE),
            dict(group=SCIENCE), dict(control=0x8D14), dict(protected=True),
            dict(aces=((0, 0, 0x1F01FF, SCIENCE),))]
        for changes in variants:
            with self.subTest(changes=changes):
                self.setUp()
                def mutate(stage, path):
                    if stage == "labeled_created":
                        obj = self.native.objects[n._path_key(path)]
                        obj.security = replace(obj.security, **changes)
                self.native.hook = mutate
                with self.assertRaises(n.ScienceCustodyNativeError):
                    self.run_setup()
                self.assertFalse(any(r["stage"] == "SET_SECURITY_INFO" and r["parentClass"] == "owner" for r in self.rows))
                self.assertTrue(all(h.closed for h in self.native.handles))

    def test_nested_path_reparse_nonempty_identity_and_common_drift(self):
        for defect in ("reparse", "replacement", "nonempty", "identity", "common"):
            with self.subTest(defect=defect):
                self.setUp()
                def change(stage, h):
                    if stage != "empty" or n._path_key(h.path) != n._path_key(b.namespace_path(ROOT, "owner")):
                        return
                    if defect == "reparse":
                        h.obj.attributes |= n.REPARSE
                    elif defect == "replacement":
                        self.native.add(h.path)
                    elif defect == "nonempty":
                        h.obj.children.append("foreign")
                    elif defect == "identity":
                        h.obj.identity = (9, 9, 9)
                    else:
                        obj = self.native.objects[n._path_key(b.namespace_path(ROOT, b.COMMON))]
                        obj.security = replace(obj.security, labels=((3, 1, b.HIGH),), sddl=obj.security.sddl + "changed-label")
                self.native.hook = change
                with self.assertRaises(n.ScienceCustodyNativeError):
                    self.run_setup()
                self.assertTrue(all(h.closed for h in self.native.handles))

    def test_every_interruption_quarantines_and_restart_never_adopts(self):
        for stage in ("CREATE", "INTERMEDIATE_READBACK", "SET_SECURITY_INFO", "FINAL_READBACK", "ADMISSION_READY"):
            with self.subTest(stage=stage):
                self.setUp()
                def record(row):
                    self.rows.append(row)
                    if row["stage"] == stage and (stage == "ADMISSION_READY" or row.get("parentClass") == "owner"):
                        raise OSError("receipt interruption")
                with self.assertRaises(OSError):
                    self.run_setup(record)
                self.assertFalse(self.rows[-1]["success"])
                self.assertTrue(all(h.closed for h in self.native.handles))
                applies = len([a for a in self.native.actions if a[0] == "apply"])
                with self.assertRaisesRegex(n.ScienceCustodyNativeError, "quarantined|original approved"):
                    self.run_setup()
                self.assertEqual(applies, len([a for a in self.native.actions if a[0] == "apply"]))
        for stage in ("apply", "applied"):
            self.setUp()
            def hook(actual, h):
                if actual == stage and n._path_key(h.path) == n._path_key(b.namespace_path(ROOT, "owner")):
                    raise OSError("assignment interruption")
            self.native.hook = hook
            with self.assertRaises(OSError):
                self.run_setup()
            self.assertFalse(self.rows[-1]["success"])

    def test_failure_finally_contains_available_evidence_without_inferred_restoration(self):
        self.native.labeled_create = self.native.inherited_create
        with self.assertRaises(n.ScienceCustodyNativeError):
            self.run_setup()
        final = self.rows[-1]
        for field in ("parentClass", "path", "fileId", "expectedIntermediateDescriptor", "expectedFinalDescriptor",
                      "apiSequence", "intermediateNativeDescriptors", "privilegeStateBefore", "privilegeStateDuring",
                      "privilegeStateAfter", "handles", "ownedObjectDisposition"):
            self.assertIsNotNone(final[field], field)
        self.assertIn("UNAVAILABLE_TO_PRODUCT", final["externalPrivilegeRestoration"])
        self.assertEqual(final["privilegeStateDuring"], final["privilegeStateAfter"])

    def test_native_creation_defaults_are_read_only_and_fully_concrete(self):
        defaults = s._SetupNative().creation_defaults()
        self.assertTrue(defaults["owner"].startswith("S-1-"))
        self.assertTrue(defaults["group"].startswith("S-1-"))
        self.assertTrue(defaults["aces"])
        self.assertTrue(all(not mask & 0xF0000000 and flags == 0 for _, flags, mask, _ in defaults["aces"]))

    def test_failed_open_records_attempt_and_unavailable_grant_for_exact_path(self):
        targets = [(kind, b.namespace_path(ROOT, kind)) for kind in s.KINDS]
        targets.append((None, self.native.approved[0].path))
        for kind, path in targets:
            with self.subTest(kind=kind, path=path):
                self.setUp()
                original = self.native.open
                def fail(target, **kwargs):
                    if n._path_key(target) == n._path_key(path):
                        raise OSError(5, "injected open denied")
                    return original(target, **kwargs)
                self.native.open = fail
                with self.assertRaisesRegex(OSError, "injected open denied"):
                    self.run_setup()
                attempts = [r for r in self.rows if r["stage"] == "HANDLE_ATTEMPT" and n._path_key(r["path"]) == n._path_key(path)]
                failures = [r for r in self.rows if r["stage"] == "HANDLE_FAILED" and n._path_key(r["path"]) == n._path_key(path)]
                self.assertEqual(len(attempts), 1)
                self.assertEqual(len(failures), 1)
                self.assertEqual(attempts[0]["parentClass"], kind)
                self.assertEqual(attempts[0]["requested"], s.SETUP_ACCESS if kind else b.PARENT_ACCESS)
                self.assertEqual(attempts[0]["share"], 3)
                self.assertEqual(attempts[0]["createFlags"], 0x02200000)
                self.assertIsNone(failures[0]["granted"])
                self.assertEqual(failures[0]["unavailable"], "OPEN_FAILED_NO_HANDLE_OR_GRANTED_ACCESS")
                self.assertEqual(n._path_key(self.rows[-1]["path"]), n._path_key(path))
                self.assertTrue(all(h.closed for h in self.native.handles))
                self.assertFalse(any(r["stage"] == "ADMISSION_READY" for r in self.rows))


if __name__ == "__main__":
    unittest.main()
