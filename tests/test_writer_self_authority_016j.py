"""Synthetic self-observation controls; actual SCM authority needs the UAC proof."""
import ast
import base64
from copy import deepcopy
import ctypes as c
import hashlib
import inspect
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zlib

from momentum_hunter import windows_writer_profile as p
from momentum_hunter import windows_writer_self_diagnostic as d
from tests.test_windows_writer_profile_016d import actor, configured_profile, token


def decode(output):
    payload = json.loads(output.split(d.MARKER, 1)[1])
    raw = zlib.decompress(base64.b64decode(payload["payload"]))
    assert len(raw) == payload["rawBytes"]
    assert hashlib.sha256(raw).hexdigest() == payload["sha256"]
    return json.loads(raw)


class SyntheticApi:
    def __init__(self, native):
        self.native = native

    def own_token(self):
        return deepcopy(self.native.observed)

    def mandatory_policy(self, expected):
        return 1

    def process_binding(self, binding):
        return {"matched": True, "process": {"pid": 123, "birth": 456}}

    def file(self, target, right):
        denied = right in target["forbidden"]
        return d.row(right, not denied, 5 if denied else 0,
                     {"fileId": target["frozenIdentity"] or (1, 0, 1),
                      "attributes": 16 if target["directory"] else 128, "links": 1})

    def services(self, names, deadline, clock):
        return {"rows": [{**d.row(right, False, 5), "service": name, "api": "OpenServiceW"}
                         for name in names for right in p.SERVICE_CONTROL_RIGHTS]}


class SelfDiagnosticTests(unittest.TestCase):
    def collect(self, observed=None, api=SyntheticApi, clock=lambda: 1):
        config, bound = configured_profile()
        observed = token("writer") if observed is None else observed
        with patch.object(d, "SelfNative", api), patch.object(d.sys, "stderr", io.StringIO()):
            return d.collect(SimpleNamespace(observed=observed), config, bound, observed, clock=clock)

    def test_safe_fixture_has_nonempty_complete_individual_matrices(self):
        result = self.collect()
        self.assertTrue(result["completed"])
        self.assertTrue(result["tokenUnchanged"])
        self.assertEqual(56, len(result["services"]["rows"]))
        self.assertGreaterEqual(len(result["files"]), 30)
        self.assertEqual("PASS", result["assumptions"]["A4"]["status"])
        self.assertEqual("PASS", result["assumptions"]["A5"]["status"])
        self.assertEqual("BLOCKED", result["assumptions"]["A6"]["status"])
        for item in result["files"]:
            rights = {row["right"]: row for row in item["rows"]}
            expected = d.required_rights(item) if item["assumption"] == "A5" else item["forbidden"]
            self.assertEqual({0, *expected}, set(rights))
            for right in expected:
                self.assertEqual("GRANTED" if item["assumption"] == "A5" else "SECURITY_DENIED",
                                 rights[right]["classification"])

    def test_operational_failure_is_not_security_denial(self):
        for code, label in ((5, "SECURITY_DENIED"), (32, "SHARING_CONFLICT"), (33, "LOCK_CONFLICT"),
                (2, "OBJECT_MISSING"), (3, "PATH_MISSING"), (1060, "SERVICE_MISSING"),
                (87, "INVALID_PARAMETER"), (123, "MALFORMED_PATH"), (0, "OTHER_API_FAILURE"),
                (999, "OTHER_API_FAILURE")):
            with self.subTest(code=code):
                row = d.row(2, False, code)
                self.assertEqual(label, row["classification"])
                self.assertFalse(row["accessGranted"])
        self.assertEqual("UNKNOWN_API_CONTRADICTION", d.outcome(True, 5))

    def test_actual_forbidden_grant_is_not_hidden_by_other_denials(self):
        class OneGrant(SyntheticApi):
            def services(self, *args):
                result = super().services(*args)
                result["rows"][7] = {**result["rows"][7], **d.row(524288, True, 0)}
                return result
        result = self.collect(api=OneGrant)
        self.assertEqual(1, sum(row["accessGranted"] for row in result["services"]["rows"]))
        self.assertEqual("A6", result["firstFalseAssumption"])

    def test_high_token_observed_but_never_newly_admitted(self):
        value = token("writer")
        value["integrity"] = "S-1-16-12288"
        result = self.collect(value)
        self.assertTrue(result["completed"])
        self.assertEqual("REJECT", result["admissionBefore"]["result"])
        with self.assertRaises(p.WriterProfileError) as raised:
            p.validate_token(value, "writer", actor("writer"))
        output = io.StringIO()
        with patch.object(d.sys, "stderr", output):
            d.emit(result, raised.exception)
        report = decode(output.getvalue())
        self.assertTrue(report["admissionIdentical"])
        self.assertEqual("REJECT", report["admissionAfter"]["result"])

    def test_changed_own_token_is_incomplete_not_authority_proof(self):
        class Changed(SyntheticApi):
            calls = 0
            def own_token(self):
                result = super().own_token()
                self.calls += 1
                if self.calls > 1:
                    result["modified_id"] = (6, 7)
                return result
        result = self.collect(api=Changed)
        self.assertFalse(result["completed"])
        self.assertFalse(result["tokenUnchanged"])
        self.assertEqual([], result["files"])
        self.assertNotIn("A5", result["assumptions"])

    def test_unknown_fields_remain_rejected_and_do_not_leak_secrets(self):
        for field in d.TOKEN_FIELDS:
            value = token("writer")
            value[field] = "DO_NOT_EXPORT_SECRET"
            config, bound = configured_profile()
            with patch.object(d, "SelfNative", SyntheticApi):
                result = d.begin(SimpleNamespace(observed=value), config, bound, value)
            self.assertFalse(result["completed"])
            self.assertNotIn("DO_NOT_EXPORT_SECRET", json.dumps(result))
            with self.assertRaises(p.WriterProfileError):
                p.validate_token(value, "writer", bound.writer)

    def test_budget_failure_retains_partial_results_without_retry(self):
        values = iter([0, 1, 13, 14])
        result = self.collect(clock=lambda: next(values))
        self.assertFalse(result["completed"])
        self.assertEqual(1, len(result["files"][0]["rows"]))
        self.assertEqual("REQUIRED_RIGHTS", result["errors"][0]["step"])
        self.assertNotIn("A6", result["assumptions"])

    def test_required_denial_finishes_only_current_assumption(self):
        class RequiredDenied(SyntheticApi):
            def file(self, target, right):
                value = super().file(target, right)
                if target["name"] == "configuration" and right == 1:
                    value.update(d.row(right, False, 5))
                return value
            def services(self, *args):
                raise AssertionError("DOWNSTREAM_SERVICE_PROBE")
        result = self.collect(api=RequiredDenied)
        self.assertEqual("A5", result["firstFalseAssumption"])
        self.assertEqual("FALSE", result["assumptions"]["A5"]["status"])
        self.assertNotIn("A6", result["assumptions"])
        self.assertEqual({"A5"}, {item["assumption"] for item in result["files"]})
        self.assertGreater(len(result["files"]), 30)

    def test_operational_errors_do_not_become_false_assumptions(self):
        for error in (2, 3, 32, 33, 87, 999):
            class OperationalError(SyntheticApi):
                def file(self, target, right):
                    value = super().file(target, right)
                    if target["name"] == "configuration" and right == 1:
                        value.update(d.row(right, False, error))
                    return value
            with self.subTest(error=error):
                result = self.collect(api=OperationalError)
                self.assertEqual("NONE_REACHED", result["firstFalseAssumption"])
                self.assertEqual("BLOCKED", result["assumptions"]["A5"]["status"])
                self.assertNotIn("A6", result["assumptions"])

    def test_incomplete_self_query_performs_no_right_probes(self):
        class Incomplete(SyntheticApi):
            def mandatory_policy(self, expected):
                raise OSError(5, "denied")
            def file(self, *args):
                raise AssertionError("DOWNSTREAM_FILE_PROBE")
        result = self.collect(api=Incomplete)
        self.assertEqual({"A4"}, set(result["assumptions"]))
        self.assertEqual("BLOCKED", result["assumptions"]["A4"]["status"])
        self.assertEqual([], result["files"])

    def test_wrong_actor_binding_performs_no_right_probes(self):
        class WrongActor(SyntheticApi):
            def process_binding(self, binding):
                return {"matched": False}
        result = self.collect(api=WrongActor)
        self.assertEqual("SCM_WRITER_PARENT_IDENTITY_MISMATCH", result["errors"][0]["diagnosticCode"])
        self.assertNotIn("A5", result["assumptions"])

    def test_unbound_object_denial_is_unknown_not_false_authority(self):
        class Drift(SyntheticApi):
            def file(self, target, right):
                value = super().file(target, right)
                if target["name"] == "configuration":
                    value["objectIdentity"]["fileId"] = (9, 9, 9)
                    if right == 1:
                        value.update(d.row(right, False, 5))
                return value
        result = self.collect(api=Drift)
        self.assertEqual("BLOCKED", result["assumptions"]["A5"]["status"])
        self.assertEqual("NONE_REACHED", result["firstFalseAssumption"])

    def test_required_rights_do_not_invent_acl_administration_or_traverse_need(self):
        config, profile = configured_profile()
        for target in d.targets(config, profile):
            rights = d.required_rights(target)
            self.assertNotIn(262144, rights)
            self.assertNotIn(524288, rights)
            if target["directory"]:
                self.assertNotIn(32, rights)

    def test_a6_filesystem_grant_rechecks_token_before_false_claim(self):
        class DriftAtGrant(SyntheticApi):
            calls = 0
            def own_token(self):
                self.calls += 1
                value = super().own_token()
                if self.calls >= 4:
                    value["modified_id"] = (99, 99)
                return value
            def file(self, target, right):
                value = super().file(target, right)
                if target["name"] == "unrelated_repository" and right == 2:
                    value.update(d.row(right, True, 0, value["objectIdentity"]))
                return value
            def services(self, *args):
                raise AssertionError("DOWNSTREAM_SERVICE_PROBE")
        result = self.collect(api=DriftAtGrant)
        self.assertFalse(result["tokenUnchanged"])
        self.assertEqual("BLOCKED", result["assumptions"]["A6"]["status"])
        self.assertEqual("NONE_REACHED", result["firstFalseAssumption"])

    def test_unbound_paths_or_production_mode_fail_before_any_probe(self):
        for mode in ("RESEARCH_ONLY", "LIVE", None):
            config, bound = configured_profile()
            config["inputMode"] = mode
            with patch.object(d, "SelfNative") as api:
                report = d.begin(Mock(), config, bound, token("writer"))
            api.assert_not_called()
            self.assertFalse(report["completed"])

    def test_diagnostic_failure_and_closed_stderr_preserve_real_rejection(self):
        config, bound = configured_profile()
        value = token("writer")
        value["integrity"] = "S-1-16-12288"
        native = Mock()
        native.token.return_value = value
        stream = Mock()
        stream.write.side_effect = OSError("unavailable")
        with patch("momentum_hunter.windows_science_custody._Native", return_value=native), \
             patch.object(p, "_process", return_value={"pid": 1, "birth": 2}), \
             patch.object(p, "WriterResourceGuard") as guard, \
             patch.object(d, "collect", side_effect=RuntimeError("SECRET")), \
             patch.object(d.sys, "stderr", stream), self.assertRaises(p.WriterProfileError) as raised:
            p.NativeWriterAdmission(config, SimpleNamespace(actor_profile=bound), require_generation=False,
                                    self_authority_diagnostic=True)
        guard.assert_not_called()
        self.assertEqual("Unreviewed SCM token class.", raised.exception.args[0])

    def test_diagnostics_not_enabled_on_normal_generation_path(self):
        config, bound = configured_profile()
        value = token("writer")
        value["integrity"] = "S-1-16-12288"
        with patch("momentum_hunter.windows_science_custody._Native", return_value=Mock(token=lambda: value)), \
             patch.object(p, "_process", return_value={"pid": 1, "birth": 2}), \
             patch.object(d, "begin") as begin, self.assertRaises(p.WriterProfileError):
            p.NativeWriterAdmission(config, SimpleNamespace(actor_profile=bound), self_authority_diagnostic=True)
        begin.assert_not_called()

    def test_native_file_api_only_open_existing_one_right_and_close(self):
        from ctypes import wintypes as w
        native = Mock(w=w)
        native.k.CreateFileW.return_value = 44
        native.k.GetFileInformationByHandle.return_value = 0
        native.k.CloseHandle.return_value = True
        api = d.SelfNative(native)
        target = {"path": "F:\\q\\file", "directory": False}
        for right in p.FILE_RIGHTS:
            if right == 64:
                continue
            result = api.file(target, right)
            self.assertTrue(result["accessGranted"])
            native.k.CreateFileW.assert_called_with(target["path"], right, 7, None, 3, 0x00200000, None)
            native.k.CloseHandle.assert_called_with(44)
        with self.assertRaises(ValueError):
            api.file(target, 3)

    def test_native_diagnostics_do_not_rebind_storage_metadata_abi(self):
        from momentum_hunter.windows_science_custody import _Native
        from momentum_hunter import windows_writer_storage as storage
        native = _Native()
        before = storage._KERNEL32.GetFileInformationByHandle.argtypes
        try:
            d.SelfNative(native)
            self.assertEqual(before, storage._KERNEL32.GetFileInformationByHandle.argtypes)
            handle = native.open(Path(__file__), access=128, share=7)
            try:
                self.assertEqual(3, len(native.identity(handle)))
            finally:
                handle.close()
        finally:
            storage._KERNEL32.GetFileInformationByHandle.argtypes = before

    def test_native_service_api_closes_every_individual_grant(self):
        from ctypes import wintypes as w
        native = Mock(w=w)
        native.a.OpenSCManagerW.return_value = 44
        native.a.OpenServiceW.return_value = 55
        native.a.CloseServiceHandle.return_value = True
        api = d.SelfNative(native)
        result = api.services(["bound"], 10, lambda: 1)
        self.assertEqual(8, len(result["rows"]))
        self.assertEqual(list(p.SERVICE_CONTROL_RIGHTS), [call.args[2] for call in native.a.OpenServiceW.call_args_list])
        self.assertEqual(9, native.a.CloseServiceHandle.call_count)

    def test_static_native_call_allowlist_excludes_all_mutations(self):
        tree = ast.parse(inspect.getsource(d))
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Attribute)
                 and node.func.value.attr in {"k", "a"}}
        self.assertEqual(calls, {"GetCurrentProcess", "OpenProcessToken", "GetTokenInformation",
            "CloseHandle", "CreateFileW", "GetFileInformationByHandle", "OpenSCManagerW",
            "OpenServiceW", "CloseServiceHandle"})
        source = inspect.getsource(d.SelfNative.mandatory_policy)
        self.assertIn("GetCurrentProcess(), 8,", source)

    def test_transport_bound_failure_is_explicit_not_truncated_claim(self):
        stream = io.StringIO()
        with patch.object(d.sys, "stderr", stream):
            d.emit({"huge": "x" * (d.MAX_REPORT_BYTES + 1)}, None)
        self.assertIn("DIAGNOSTIC_OUTPUT_UNAVAILABLE", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
