"""Exact-input proof reuse, never time-based admission or physical SCM proof."""
from contextlib import ExitStack
import ctypes as c
from dataclasses import replace
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import windows_science_custody as custody
from momentum_hunter import windows_writer_profile as actors
from momentum_hunter.continuous_host_contract import host_fingerprint
from tests.test_science_mutable_policy_020g import policy, BNative, admission, security
from tests.test_windows_writer_profile_016d import configured_profile, token


class ExactValueTests(unittest.TestCase):
    def test_policy_key_detects_nested_mutation_and_scalar_types(self):
        p = policy()
        key = actors._proof_value(p)
        wire_hash = p.policy_sha256
        self.assertEqual(key, actors._proof_value(p))
        self.assertEqual(wire_hash, p.policy_sha256)
        object.__setattr__(p.actor_profile.resources[0], "directory", 1)
        self.assertNotEqual(key, actors._proof_value(p))
        for unsupported in ([], set(), object()):
            with self.assertRaises(actors.WriterProfileError):
                actors._proof_value(unsupported)

    def backend(self, role):
        p = policy()
        native = BNative(p, role)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(custody, "_Native", return_value=native))
        stack.enter_context(patch.object(custody, "observe_actor", side_effect=admission))
        stack.enter_context(patch.object(custody, "admission_identity", side_effect=lambda row: row))
        access = stack.enter_context(patch.object(custody, "access_decisions",
            return_value={right: False for right in actors.MUTATION_RIGHTS}))
        backend = custody.WindowsScienceCustodyBackend(p, role=role)
        self.addCleanup(backend.close)
        return backend, native, access

    def test_fixed_access_proofs_reuse_for_both_roles_but_security_is_fresh(self):
        for role in ("writer", "science"):
            with self.subTest(role=role):
                backend, native, access = self.backend(role)
                backend._check_pins()
                count = access.call_count
                queried = native.security_calls
                for _ in range(10):
                    backend._check_pins()
                self.assertEqual(count, access.call_count)
                self.assertGreater(native.security_calls, queried)
                root = backend.namespace_root("custody")
                native.objects[custody._path_key(root)].security = replace(
                    security("trusted", True), owner="S-1-5-18")
                with self.assertRaises(custody.ScienceCustodyNativeError):
                    backend._check_pins()

    def test_dynamic_access_is_not_cached_and_changed_fixed_descriptor_rechecks(self):
        backend, native, access = self.backend("writer")
        fixed = backend.namespace_root("requests")
        sec = native.objects[custody._path_key(fixed)].security
        backend._forbidden_access_decisions(fixed, sec)
        access.reset_mock()
        backend._forbidden_access_decisions(fixed, replace(sec, control=sec.control ^ 0x400))
        self.assertEqual(1, access.call_count)
        backend._forbidden_access_decisions(fixed / "child.json", sec)
        backend._forbidden_access_decisions(fixed / "child.json", sec)
        self.assertEqual(3, access.call_count)

    def test_policy_or_token_drift_still_invalidates_before_effects(self):
        for mutation in (lambda b, n: setattr(b, "policy_sha256", "0" * 64),
                         lambda b, n: object.__setattr__(b.policy.roots[0], "owner_sid", "S-1-5-18"),
                         lambda b, n: setattr(n, "token_override", {**n.token(), "modified_id": (999, 1)})):
            backend, native, _ = self.backend("writer")
            mutation(backend, native)
            with self.assertRaises(custody.ScienceCustodyNativeError):
                backend._check_pins()
            self.assertTrue(backend._invalidated)
            self.assertEqual([], native.renames)


class TokenReuseTests(unittest.TestCase):
    def primitive(self):
        native = object.__new__(custody._Native)
        native._token_cache = None
        observed = token("science")
        fingerprint = {key: observed[key] for key in (
            "thread_token", "token_id", "authentication_id", "modified_id", "token_type")}
        native.token_fingerprint = Mock(side_effect=lambda: dict(fingerprint))
        native._read_token = Mock(side_effect=lambda: dict(observed))
        return native, observed, fingerprint

    def test_current_statistics_required_on_every_use_and_return_is_detached(self):
        native, observed, _ = self.primitive()
        native.token()["owner"] = "bad"
        for _ in range(30):
            self.assertEqual(observed, native.token())
        self.assertEqual(1, native._read_token.call_count)
        self.assertEqual(32, native.token_fingerprint.call_count)

    def test_modified_or_replaced_token_never_uses_old_inventory(self):
        for field, value in (("modified_id", (99, 1)), ("token_id", (88, 1)),
                             ("authentication_id", (77, 1)), ("thread_token", True), ("token_type", 2)):
            native, observed, fingerprint = self.primitive()
            native.token()
            fingerprint[field] = observed[field] = value
            self.assertEqual(observed, native.token())
            self.assertEqual(2, native._read_token.call_count)

    def test_inventory_race_or_native_query_failure_is_not_cache_success(self):
        native, _, fingerprint = self.primitive()
        native.token_fingerprint.side_effect = [dict(fingerprint), {**fingerprint, "modified_id": (99, 1)}]
        with self.assertRaises(custody.ScienceCustodyNativeError):
            native.token()
        self.assertIsNone(native._token_cache)
        native, _, _ = self.primitive()
        native.token()
        native.token_fingerprint.side_effect = OSError("query denied")
        with self.assertRaises(OSError):
            native.token()


class ActorReuseTests(unittest.TestCase):
    def setUp(self):
        self.config, self.profile = configured_profile()
        self.config["hostFingerprint"] = host_fingerprint(self.config)
        self.current = dict(pid=101, birth=111, image=self.profile.writer.python_path)
        self.parent = dict(pid=202, birth=222, image=self.profile.writer.host_path)
        self.record = dict(role="writer", generation="11111111-1111-4111-8111-111111111111",
            phase="RUNNING", hostFingerprint=self.config["hostFingerprint"],
            supervisorPid=202, supervisorBirth=222, childPid=101, childBirth=111)
        self.observed = token("writer")
        self.cache = actors.ActorProofCache()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.scm = self.stack.enter_context(patch.object(actors, "_scm", return_value=dict(pid=202)))
        self.process = self.stack.enter_context(patch.object(actors, "_process",
            side_effect=lambda n, pid: self.current if pid == 101 else self.parent))
        self.stack.enter_context(patch.object(actors.os, "getpid", return_value=101))
        self.stack.enter_context(patch.object(actors.os, "getppid", return_value=202))
        self.reads = []
        def read(path, *args, **kwargs):
            self.reads.append(path)
            return io.BytesIO(json.dumps(self.record if path.name == "generation.json" else self.config).encode())
        self.stack.enter_context(patch.object(Path, "open", read))

    def observe(self):
        return actors.observe_actor(Mock(), "writer", self.profile, self.observed,
                                    check_images=False, proof_cache=self.cache)

    def test_live_scm_process_and_raw_file_reads_remain_per_observation(self):
        with patch.object(actors, "validate_token", wraps=actors.validate_token) as validation, \
             patch.object(actors.json, "loads", wraps=json.loads) as decode:
            first = self.observe()
            for _ in range(30):
                self.assertEqual(first, self.observe())
            self.assertEqual(1, validation.call_count)
            self.assertEqual(2, decode.call_count)
            self.assertEqual(31, self.scm.call_count)
            self.assertEqual(62, self.process.call_count)
            self.assertEqual(62, len(self.reads))

    def test_each_changed_input_is_revalidated(self):
        changes = (
            lambda: self.record.update(phase="EXITED"),
            lambda: self.record.update(generation="bad"),
            lambda: self.record.update(childBirth=999),
            lambda: self.config.update(inputMode="unbound"),
            lambda: self.current.update(birth=333),
            lambda: self.parent.update(image="F:/other.exe"),
            lambda: self.observed.update(privilege_attributes=()),
            lambda: object.__setattr__(self.profile.writer, "service_name", "unbound"),
        )
        for change in changes:
            with self.subTest(change=change):
                self.setUp()
                self.observe()
                change()
                with self.assertRaises((actors.WriterProfileError, ValueError)):
                    self.observe()


@unittest.skipUnless(os.name == "nt", "Windows native descriptor decoder")
class DescriptorReuseTests(unittest.TestCase):
    def test_descriptor_is_queried_each_time_and_cache_has_exact_bounded_keys(self):
        native = custody._Native()
        selected = ["O:SYG:SYD:P(A;;FR;;;SY)S:(ML;;NW;;;HI)"]
        original = native.a
        def get(handle, kind, info, owner, group, dacl, sacl, sd):
            memory = c.c_void_p()
            native.checked(original.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                selected[0], 1, c.byref(memory), None), "test descriptor")
            c.cast(sd, c.POINTER(c.c_void_p))[0] = memory
            base = memory.value
            raw = c.string_at(memory, 20)
            for target, offset in ((owner, 4), (group, 8), (sacl, 12), (dacl, 16)):
                relative = int.from_bytes(raw[offset:offset + 4], "little")
                c.cast(target, c.POINTER(c.c_void_p))[0] = base + relative if relative else None
            return 0
        observed_get = Mock(side_effect=get)
        decode = Mock(wraps=original.ConvertSecurityDescriptorToStringSecurityDescriptorW)
        native.a = SimpleNamespace(GetSecurityInfo=observed_get,
            GetSecurityDescriptorControl=original.GetSecurityDescriptorControl,
            GetSecurityDescriptorLength=original.GetSecurityDescriptorLength,
            ConvertSecurityDescriptorToStringSecurityDescriptorW=decode,
            ConvertSidToStringSidW=original.ConvertSidToStringSidW, GetAce=original.GetAce)
        handle = SimpleNamespace(value=1)
        first = native.security(handle)
        self.assertEqual(first, native.security(handle))
        self.assertEqual(2, observed_get.call_count)
        self.assertEqual(1, decode.call_count)
        selected[0] = "O:SYG:SYD:PAI(A;;FR;;;SY)S:(ML;;NW;;;HI)"
        different = native.security(handle)
        self.assertNotEqual(first.control, different.control)
        self.assertEqual(2, decode.call_count)
        for i in range(80):
            selected[0] = f"O:SYG:SYD:P(A;;0x{i+1:x};;;SY)S:(ML;;NW;;;HI)"
            native.security(handle)
        self.assertEqual(32, len(native._security_cache))
        observed_get.side_effect = lambda *args: 5
        with self.assertRaises(custody.ScienceCustodyNativeError):
            native.security(handle)


if __name__ == "__main__":
    unittest.main()
