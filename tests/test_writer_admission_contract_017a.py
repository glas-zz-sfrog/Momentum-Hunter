"""Captured-token contract tests; no SCM launch or physical A9 claim."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import windows_writer_profile as p
from momentum_hunter import windows_science_custody as custody
from tests.test_windows_writer_profile_016d import actor, configured_profile, role_profile, token
from tests.test_science_custody_windows_007 import policy as legacy_policy


FIXTURE = json.loads((Path(__file__).parent / "fixtures/writer_admission_017a.json").read_text())


def actual_token():
    value = deepcopy(FIXTURE["token"])
    for key in ("group_attributes", "restricting_attributes", "privilege_attributes"):
        value[key] = tuple(tuple(row) for row in value[key])
    for key in ("token_id", "authentication_id", "modified_id"):
        value[key] = tuple(value[key])
    return value


def contract():
    return p.QualifiedWriterTokenContract(tuple(FIXTURE["qualifiedStableGroups"]), FIXTURE["a7ReviewSHA256"])


def binding():
    return replace(actor("writer"), service_name=FIXTURE["serviceName"],
                   integrity_sid=p.HIGH_INTEGRITY, writer_token_contract=contract())


def configuration():
    cfg, profile = configured_profile()
    writer = binding()
    science = replace(profile.science, service_name=writer.service_name[:-6] + "Science")
    profile = replace(profile, writer=writer, science=science)
    cfg["host"]["services"].update(writer=writer.service_name, science=science.service_name)
    return cfg, profile


def bound_custody_policy(profile):
    base = legacy_policy()
    return replace(base, writer_sid=p.LOCAL_SERVICE,
        science_sid=p.service_sid(profile.science.service_name), actor_profile=profile,
        roots=tuple(replace(root, owner_sid=p.LOCAL_SERVICE) for root in base.roots))


class QualifiedWriterContractTests(unittest.TestCase):
    def reject(self, value, expected=None, bound=None):
        with self.assertRaises(p.WriterProfileError) as raised:
            p.validate_token(value, "writer", bound or binding())
        if expected:
            self.assertEqual(expected, raised.exception.args[0])
        return raised.exception

    def test_exact_preserved_actual_token_admits_without_mutation(self):
        value = actual_token()
        before = deepcopy(value)
        self.assertEqual(p.service_sid(FIXTURE["serviceName"]), p.validate_token(value, "writer", binding()))
        self.assertEqual(before, value)
        self.assertEqual(16, len(contract().stable_group_sids))

    def test_old_contract_still_reproduces_original_a8_rejection(self):
        old = replace(binding(), integrity_sid="S-1-16-16384", writer_token_contract=None)
        error = self.reject(actual_token(), "Unreviewed SCM token class.", old)
        self.assertEqual(["integrity"], error.token_diagnostic["failedFields"])

    def test_high_substitution_alone_still_rejects_service_attributes(self):
        self.reject(actual_token(), "Writer service SID absent from ordinary token.",
                    replace(binding(), writer_token_contract=None))

    def test_required_integrity_is_one_conjunct_not_admission_by_itself(self):
        for integrity in ("S-1-16-4096", "S-1-16-8192", "S-1-16-16384", "S-1-16-20480", None):
            row = actual_token()
            row["integrity"] = integrity
            with self.subTest(integrity=integrity):
                self.reject(row)
        with self.assertRaises(p.WriterProfileError):
            replace(binding(), integrity_sid="S-1-16-16384")

    def test_each_service_attribute_bit_is_enforced(self):
        sid = p.service_sid(binding().service_name)
        for attributes in range(256):
            if attributes == 14:
                continue
            row = actual_token()
            row["group_attributes"] = tuple((s, attributes if s == sid else a)
                                             for s, a in row["group_attributes"])
            with self.subTest(attributes=attributes):
                self.reject(row, "Qualified Writer service SID semantics differ.")

    def test_missing_wrong_or_extra_service_sid_cannot_substitute(self):
        sid = p.service_sid(binding().service_name)
        wrong = p.service_sid("MomentumHunterContinuous-qual-wrong-Writer")
        for replacement in (None, wrong):
            row = actual_token()
            row["group_attributes"] = tuple((replacement if s == sid else s, a)
                for s, a in row["group_attributes"] if s != sid or replacement is not None)
            with self.subTest(replacement=replacement):
                self.reject(row)
        row = actual_token()
        row["restricting_attributes"] = tuple((wrong if s == sid else s, a)
                                               for s, a in row["restricting_attributes"])
        self.reject(row)
        self.reject(actual_token(), bound=replace(binding(), service_name="MomentumHunterContinuous-qual-wrong-Writer"))

    def test_every_stable_group_is_exactly_bound_not_a_wildcard(self):
        for sid in contract().stable_group_sids:
            row = actual_token()
            row["group_attributes"] = tuple((s, a) for s, a in row["group_attributes"] if s != sid)
            with self.subTest(missing=sid):
                self.reject(row)
            for attributes in (0, 1, 2, 3, 4, 6, 8, 14, 15, 16, 0x20000007, True):
                row = actual_token()
                row["group_attributes"] = tuple((s, attributes if s == sid else a)
                                                 for s, a in row["group_attributes"])
                with self.subTest(sid=sid, attributes=attributes):
                    self.reject(row)
        for added in ("S-1-5-32-544", "S-1-5-18", "S-1-5-32-1-2-3-4-5-6-7-8", "S-1-5-80-0"):
            row = actual_token()
            row["group_attributes"] += ((added, 7),)
            with self.subTest(added=added):
                self.reject(row)

    def test_each_integrity_group_attribute_is_enforced(self):
        for attributes in (0, 32, 64, 7, 96 | 4, 96 | 16):
            row = actual_token()
            row["group_attributes"] = tuple((s, attributes if s == p.HIGH_INTEGRITY else a)
                                             for s, a in row["group_attributes"])
            with self.subTest(attributes=attributes):
                self.reject(row)

    def test_native_scalar_forms_and_authority_reject(self):
        invalid = {
            "user": ("S-1-5-18", "S-1-5-32-544", None),
            "owner": ("S-1-5-18", "S-1-5-32-544", None),
            "thread_token": (True, None, 0), "token_type": (2, True, None),
            "elevation": (1, False, None), "elevation_type": (2, 3, True, None),
            "ui_access": (1, False, None), "virtualization": (1, False, None),
            "session_id": (1, False, None), "has_restrictions": (0, True, None),
            "mandatory_policy": (None, 0, 1, 2, 4, True, "3"),
            "token_id": (None, [1, 2], (True, 1), (-1, 0), (2**32, 0)),
            "authentication_id": (None,), "modified_id": (None,),
        }
        for key, values in invalid.items():
            for value in values:
                row = actual_token()
                row[key] = value
                with self.subTest(key=key, value=value):
                    self.reject(row)

    def test_required_and_forbidden_privileges_reject(self):
        for privileges in ((), (("SeChangeNotifyPrivilege", 0),),
                (("SeChangeNotifyPrivilege", 2),), (("SeChangeNotifyPrivilege", 3), ("SeImpersonatePrivilege", 0)),
                (("SeChangeNotifyPrivilege", 3), ("SeDebugPrivilege", 3)), (("SeBackupPrivilege", 3),)):
            row = actual_token()
            row["privilege_attributes"] = privileges
            with self.subTest(privileges=privileges):
                self.reject(row)

    def test_restricting_inventory_must_match_exactly(self):
        original = actual_token()["restricting_attributes"]
        variants = [(), original[:-1], (*original, ("S-1-5-11", 7)), (*original, original[0])]
        variants += [tuple((s, 16 if s == target else a) for s, a in original) for target, _ in original]
        for restricting in variants:
            row = actual_token()
            row["restricting_attributes"] = restricting
            with self.subTest(restricting=restricting):
                self.reject(row)

    def test_fresh_logon_is_correlated_not_historically_pinned(self):
        row = actual_token()
        original = next(s for s, a in row["group_attributes"] if a & 0xC0000000)
        fresh = "S-1-5-5-9-11"
        for key in ("group_attributes", "restricting_attributes"):
            row[key] = tuple((fresh if s == original else s, a) for s, a in row[key])
        row["token_id"], row["modified_id"] = (8, 1), (9, 1)
        p.validate_token(row, "writer", binding())
        row["restricting_attributes"] = actual_token()["restricting_attributes"]
        self.reject(row)

    def test_logon_and_duplicate_forms_reject(self):
        for attribute in (0xC0000007, 0xC0000004, 7, 0):
            row = actual_token()
            row["group_attributes"] = tuple((s, attribute if a & 0xC0000000 else a)
                                             for s, a in row["group_attributes"])
            with self.subTest(attribute=attribute):
                self.reject(row)
        row = actual_token()
        row["group_attributes"] += (row["group_attributes"][1],)
        self.reject(row)
        for key in ("group_attributes", "restricting_attributes"):
            row = actual_token()
            row[key] = list(row[key])
            self.reject(row)

    def test_qualified_contract_cannot_be_reused_by_science(self):
        with self.assertRaises(p.WriterProfileError):
            replace(actor("science"), writer_token_contract=contract())
        with self.assertRaises(p.WriterProfileError):
            p.validate_token(actual_token(), "science", binding())
        p.validate_token(token("science"), "science", actor("science"))

    def test_contract_is_finite_typed_and_reserved_groups_reject(self):
        original = contract()
        bad_groups = [(), list(original.stable_group_sids), original.stable_group_sids[::-1],
            original.stable_group_sids + (original.stable_group_sids[-1],)]
        for sid in ("S-1-5-32-544", "S-1-5-18", p.HIGH_INTEGRITY, "S-1-5-5-1-2",
                    p.service_sid(binding().service_name), "S-1-5-32-01-2-3-4-5-6-7-8",
                    "S-1-5-32-4294967296-2-3-4-5-6-7-8"):
            bad_groups.append(tuple(sorted((*original.stable_group_sids, sid))))
        for groups in bad_groups:
            with self.subTest(groups=groups), self.assertRaises(p.WriterProfileError):
                replace(original, stable_group_sids=groups)
        for digest in (None, "x" * 64, "a" * 63):
            with self.assertRaises(p.WriterProfileError):
                replace(original, authority_evidence_sha256=digest)

    def test_tampered_frozen_binding_is_revalidated(self):
        bound = binding()
        object.__setattr__(bound.writer_token_contract, "stable_group_sids", ("S-1-5-32-544",))
        self.reject(actual_token(), bound=bound)

    def test_profile_round_trip_and_new_contract_hash_binding(self):
        _, value = configuration()
        self.assertEqual(value, p.decode_profile(json.loads(json.dumps(p.encode_profile(value)))))
        raw = json.loads(json.dumps(p.encode_profile(value)))
        for mutation in (lambda r: r["writer"]["writer_token_contract"].update(extra=True),
                         lambda r: r["writer"]["writer_token_contract"].pop("stable_group_sids"),
                         lambda r: r["writer"]["writer_token_contract"].update(stable_group_sids="invalid")):
            changed = deepcopy(raw)
            mutation(changed)
            with self.assertRaises(p.WriterProfileError):
                p.decode_profile(changed)
        self.assertNotEqual(custody._digest(p.encode_profile(value)),
            custody._digest(p.encode_profile(replace(value, writer=replace(value.writer, writer_token_contract=None)))))

    def test_old_bound_policy_hash_and_json_bytes_remain_compatible(self):
        old = role_profile()
        original = asdict(old)
        for role in ("writer", "science"):
            original[role].pop("writer_token_contract")
        self.assertEqual(original, p.encode_profile(old))
        self.assertEqual(old, p.decode_profile(json.loads(json.dumps(original))))
        policy = bound_custody_policy(old)
        previous = asdict(policy)
        previous["actor_profile"] = original
        self.assertEqual(custody._digest({"profile": custody.PROFILE, **previous}), policy.policy_sha256)

    def test_new_contract_enters_custody_policy_fingerprint(self):
        _, bound = configuration()
        policy = bound_custody_policy(bound)
        changed = replace(bound, writer=replace(bound.writer, writer_token_contract=None))
        self.assertNotEqual(policy.policy_sha256, replace(policy, actor_profile=changed).policy_sha256)

    def test_authority_reference_hash_cannot_admit_an_invalid_actor(self):
        row = actual_token()
        row["user"] = "S-1-5-18"
        self.reject(row)

    def test_qualified_token_does_not_bypass_resource_scm_or_service_gates(self):
        cfg, bound = configuration()
        for failing in (None, "resources", "actor", "services"):
            native = Mock()
            native.token.return_value = actual_token()
            with patch.object(custody, "_Native", return_value=native), \
                 patch.object(p, "WriterResourceGuard") as guard, \
                 patch.object(p, "observe_actor", return_value={}) as observe, \
                 patch.object(p, "verify_service_denials", return_value=[]) as services:
                gates = {"resources": guard, "actor": observe, "services": services}
                if failing:
                    gates[failing].side_effect = p.WriterProfileError(failing)
                    with self.assertRaises(p.WriterProfileError):
                        p.NativeWriterAdmission(cfg, SimpleNamespace(actor_profile=bound))
                    if failing != "resources":
                        guard.return_value.close.assert_called_once()
                else:
                    admitted = p.NativeWriterAdmission(cfg, SimpleNamespace(actor_profile=bound))
                    guard.assert_called_once()
                    observe.assert_called_once()
                    services.assert_called_once()
                    admitted.close()

    def test_invalid_token_fails_before_resource_guard(self):
        cfg, bound = configuration()
        row = actual_token()
        row["mandatory_policy"] = 0
        native = Mock()
        native.token.return_value = row
        with patch.object(custody, "_Native", return_value=native), \
             patch.object(p, "_process", side_effect=OSError("unavailable")), \
             patch.object(p, "WriterResourceGuard") as guard:
            with self.assertRaises(p.WriterProfileError):
                p.NativeWriterAdmission(cfg, SimpleNamespace(actor_profile=bound))
            guard.assert_not_called()

    def test_scm_provenance_remains_mandatory_for_valid_token(self):
        _, bound = configuration()
        with patch.object(p, "_scm", side_effect=p.WriterProfileError("not SCM")), \
             self.assertRaises(p.WriterProfileError):
            p.observe_actor(Mock(), "writer", bound, actual_token())

    def test_qualified_binding_does_not_enable_production_mode(self):
        cfg, bound = configuration()
        p.validate_profile_paths(cfg, bound)
        cfg["inputMode"] = "LIVE_PRODUCTION"
        with self.assertRaises(p.WriterProfileError):
            p.validate_profile_paths(cfg, bound)

    @unittest.skipUnless(os.name == "nt", "Own-token native read only")
    def test_mandatory_policy_is_observed_on_normal_own_token_path(self):
        observed = custody._Native().token()
        self.assertIs(type(observed["mandatory_policy"]), int)
        self.assertIn(observed["mandatory_policy"], range(4))


if __name__ == "__main__":
    unittest.main()
