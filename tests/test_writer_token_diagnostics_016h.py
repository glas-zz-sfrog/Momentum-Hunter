"""Diagnostic-only controls; not SCM launch or authority-envelope acceptance."""
import ast
from copy import deepcopy
import inspect
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import windows_writer_profile as profile
from tests.test_windows_writer_profile_016d import actor, configured_profile, token


class TokenDiagnosticTests(unittest.TestCase):
    def rejected(self, row, role="writer", binding=None):
        with self.assertRaises(profile.WriterProfileError) as raised:
            profile.validate_token(row, role, binding or actor(role))
        error = raised.exception
        self.assertEqual("REJECTED", error.token_diagnostic["status"])
        self.assertEqual(error.token_diagnostic,
                         json.loads(str(error).split(" TOKEN_CLASS_REJECTION=", 1)[1]))
        return error.token_diagnostic

    def test_every_classifier_rejection_has_an_explicit_diagnostic_rule(self):
        tree = ast.parse(inspect.getsource(profile._validate_token))
        messages = {n.args[1].value for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name) and n.func.id == "require"}
        self.assertLessEqual(messages, set(profile._TOKEN_REJECTION_FIELDS))
        self.assertEqual(set(profile._TOKEN_REJECTION_FIELDS), set(profile._TOKEN_EXPECTED_RULES))

    def test_each_generic_conjunct_reports_only_its_own_difference(self):
        changes = dict(elevation=1, elevation_type=2, ui_access=1, virtualization=1,
                       session_id=1, integrity="S-1-16-12288")
        for role in ("writer", "science"):
            for key, value in changes.items():
                if key == "integrity" and role == "science":
                    value = "S-1-16-16384"
                row = token(role)
                expected = row[key]
                row[key] = value
                original = deepcopy(row)
                with self.subTest(role=role, field=key):
                    result = self.rejected(row, role)
                    self.assertEqual([key], result["failedFields"])
                    self.assertEqual({key: value}, result["observed"])
                    self.assertEqual({key: expected}, result["expected"])
                    self.assertEqual(original, row)

    def test_observed_high_integrity_remains_rejected_without_policy_repair(self):
        row = token("writer")
        row["integrity"] = "S-1-16-12288"
        result = self.rejected(row)
        self.assertEqual({"integrity": "S-1-16-16384"}, result["expected"])
        self.assertEqual(os.getpid(), result["process"]["pid"])

    def test_service_attributes_14_and_unknown_capability_group_remain_rejected(self):
        sid = profile.service_sid(actor("writer").service_name)
        row = token("writer")
        row["group_attributes"] = tuple((s, 14 if s == sid else a) for s, a in row["group_attributes"])
        result = self.rejected(row)
        self.assertEqual({"serviceSidAttributes": 14}, result["observed"])
        self.assertEqual([7, 15], result["expected"]["attributes"])
        row = token("writer")
        unknown = "S-1-5-32-1-2-3-4-5-6-7-8"
        row["group_attributes"] += ((unknown, 7),)
        result = self.rejected(row)
        self.assertEqual(1, result["observed"]["rejectedGroups"]["count"])
        self.assertIn(unknown, json.dumps(result))

    def test_diagnostic_never_echoes_arbitrary_text_or_unbounded_values(self):
        for value in ("DO_NOT_ECHO_SECRET_TEXT", "x" * 100000, 1 << 100000, {"credential": "DO_NOT_ECHO_SECRET_TEXT"}):
            row = token("writer")
            row["user"] = value
            text = json.dumps(self.rejected(row))
            self.assertNotIn("DO_NOT_ECHO_SECRET_TEXT", text)
            self.assertLess(len(text), 4096)
        row = token("writer")
        row["group_attributes"] += tuple((f"S-1-5-32-{i}", 7) for i in range(1000, 1200))
        result = self.rejected(row)
        self.assertEqual(200, result["observed"]["rejectedGroups"]["count"])
        self.assertTrue(result["observed"]["rejectedGroups"]["truncated"])
        self.assertEqual(8, len(result["observed"]["rejectedGroups"]["sample"]))

    def test_diagnostic_builder_failure_cannot_turn_rejection_into_success(self):
        row = token("writer")
        row["elevation"] = 1
        with patch.object(profile, "_token_rejection_diagnostic", side_effect=RuntimeError("private diagnostic error")):
            result = self.rejected(row)
        self.assertEqual("UNAVAILABLE", result["diagnostic"])
        self.assertNotIn("private diagnostic error", json.dumps(result))

    def test_pre_generation_rejection_reaches_supervisor_exception_before_guard(self):
        config, bound = configured_profile()
        row = token("writer")
        row["integrity"] = "S-1-16-12288"
        native = Mock()
        native.token.return_value = row
        with patch("momentum_hunter.windows_science_custody._Native", return_value=native), \
             patch.object(profile, "_process", return_value={"pid": os.getpid(), "birth": 123, "image": "not exported"}), \
             patch.object(profile, "WriterResourceGuard", side_effect=AssertionError("must not reach mutable setup")), \
             self.assertRaises(profile.WriterProfileError) as raised:
            profile.NativeWriterAdmission(config, SimpleNamespace(actor_profile=bound), require_generation=False)
        result = raised.exception.token_diagnostic
        self.assertEqual("PRE_GENERATION", result["phase"])
        self.assertEqual("NOT_YET_CREATED", result["generation"])
        self.assertEqual(123, result["process"]["birth"])
        self.assertIn('"failedFields":["integrity"]', str(raised.exception))
        self.assertNotIn("not exported", str(raised.exception))
        native.token.assert_called_once()

    def test_process_identity_query_failure_keeps_original_rejection(self):
        row = token("writer")
        row["elevation"] = 1
        with self.assertRaises(profile.WriterProfileError) as raised:
            profile.validate_token(row, "writer", actor("writer"))
        with patch.object(profile, "_process", side_effect=OSError("do not dump native error")):
            profile._bind_token_rejection_process(raised.exception, Mock(), require_generation=True)
        result = raised.exception.token_diagnostic
        self.assertEqual("UNAVAILABLE_REJECTION_PRESERVED", result["processIdentityQuery"])
        self.assertEqual("NOT_OBSERVED", result["generation"])
        self.assertEqual(["elevation"], result["failedFields"])

    def test_wrapper_and_unchanged_classifier_have_identical_decisions(self):
        changes = [(key, value) for key in (
            "user", "owner", "thread_token", "token_type", "elevation", "elevation_type", "ui_access",
            "virtualization", "session_id", "has_restrictions", "integrity", "group_attributes",
            "restricting_attributes", "privilege_attributes", "token_id", "authentication_id", "modified_id")
            for value in (None, False, True, 0, 1, 2, "S-1-5-18", (), [], (("S-1-5-32-544", 7),))]
        for role in ("writer", "science"):
            for change in (None, *changes):
                row = token(role)
                if change is not None:
                    row[change[0]] = change[1]
                outcomes = []
                for function in (profile._validate_token, profile.validate_token):
                    try:
                        outcomes.append(("RETURN", function(deepcopy(row), role, actor(role))))
                    except Exception as exc:
                        outcomes.append((type(exc).__name__, exc.args))
                with self.subTest(role=role, change=change):
                    self.assertEqual(*outcomes)


if __name__ == "__main__":
    unittest.main()
