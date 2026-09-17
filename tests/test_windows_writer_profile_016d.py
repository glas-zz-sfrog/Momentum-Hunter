"""016D structural/own-token controls, never an actual SCM-generation claim."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import unittest
import uuid
from contextlib import ExitStack
from unittest.mock import Mock, patch

from momentum_hunter import windows_writer_profile as profile
from momentum_hunter import windows_science_custody as custody
from tests.test_science_custody_windows_007 import policy as legacy_policy


def configured_profile():
    root = PureWindowsPath("F:/q")
    config = dict(inputMode="OFFLINE_QUALIFICATION", installRoot=str(root / "install"),
        configRoot=str(root / "config"), ipcKeyPath=str(root / "config/writer.key"),
        evidenceRoot=str(root / "evidence"), logRoot=str(root / "logs"),
        hostStateRoot=str(root / "generations"), runtimeStateRoot=str(root / "runtime"),
        researchFactExportV2=dict(exportRoot=str(root / "export")),
        host=dict(instanceRoot=str(root), services={role: actor(role).service_name for role in ("writer", "science")},
                  science=dict(stateRoot=str(root / "science"))))
    paths = profile.expected_resource_paths(config)
    resources = tuple(profile.WriterResourceBinding(name, str(path), name not in {"configuration", "writer_key"},
        (1, 0, index), "c" * 64) for index, (name, path) in enumerate(paths.items(), 1))
    return config, replace(role_profile(), resources=resources)


def actor(role):
    return profile.ScmActorBinding(
        "MomentumHunterContinuous-qual-016d-" + ("Writer" if role == "writer" else "Science"),
        "F:/q/install/host/MomentumHunter.ContinuousServiceHost.exe", "a" * 64,
        "F:/q/install/python-base/python.exe", "b" * 64,
        "F:/q/generations/" + role, "S-1-16-16384" if role == "writer" else "S-1-16-12288")


def role_profile():
    resources = tuple(profile.WriterResourceBinding(name, "F:/q/resources/" + name,
        name not in {"configuration", "writer_key"}, (1, 0, index), "c" * 64)
        for index, name in enumerate(profile.RESOURCE_RULES, 1))
    return profile.ScmRoleProfile(actor("writer"), actor("science"), "F:/q/config/continuous-deployment.json", resources)


def token(role, logon="S-1-5-5-1-2"):
    binding = actor(role)
    sid = profile.service_sid(binding.service_name)
    user = profile.LOCAL_SERVICE if role == "writer" else sid
    ordinary = [(s, 7) for s in (profile.WORLD, profile.WRITE_RESTRICTED, "S-1-5-6", "S-1-5-11", "S-1-5-32-545")]
    ordinary += [(logon, 0xC000000F), (binding.integrity_sid, 96)]
    if role == "writer":
        ordinary.append((sid, 15))
    return dict(user=user, owner=user, thread_token=False, token_type=1, elevation=0,
        elevation_type=1, ui_access=0, virtualization=0, session_id=0, integrity=binding.integrity_sid,
        has_restrictions=1, group_attributes=tuple(ordinary),
        restricting_attributes=tuple((s, 7) for s in (sid, profile.WORLD, profile.WRITE_RESTRICTED, logon)),
        privilege_attributes=(("SeChangeNotifyPrivilege", 3),), token_id=(1, 1), authentication_id=(2, 1), modified_id=(3, 1))


class RoleProfileTests(unittest.TestCase):
    def test_exact_json_round_trip(self):
        value = role_profile()
        self.assertEqual(value, profile.decode_profile(json.loads(json.dumps(asdict(value)))))
        self.assertIsNone(profile.decode_profile(None))

    def test_invalid_or_incomplete_profiles_reject(self):
        changes = (
            lambda p: p.update(extra=True), lambda p: p.update(profile="looser"),
            lambda p: p["writer"].update(service_name="MomentumHunterContinuousWriter"),
            lambda p: p["writer"].update(service_name="MomentumHunterContinuous-qual-other-Writer"),
            lambda p: p["writer"].update(host_sha256="g" * 64),
            lambda p: p["writer"].update(host_path="../source"),
            lambda p: p["writer"].update(integrity_sid="S-1-16-8192"),
            lambda p: p["science"].update(integrity_sid="S-1-16-16384"),
            lambda p: p["resources"].pop(),
            lambda p: p["resources"][0].update(directory="true"),
            lambda p: p["resources"][0].update(file_identity=[True, 0, 1]),
            lambda p: p["resources"][0].update(name="arbitrary_write"),
            lambda p: p["resources"][0].update(path=p["resources"][1]["path"]),
        )
        for change in changes:
            raw = json.loads(json.dumps(asdict(role_profile())))
            change(raw)
            with self.subTest(change=change), self.assertRaises(profile.WriterProfileError):
                profile.decode_profile(raw)

    def test_roles_use_distinct_exact_native_principals(self):
        for role in ("writer", "science"):
            self.assertEqual(profile.service_sid(actor(role).service_name),
                             profile.validate_token(token(role), role, actor(role)))
        with self.assertRaises(profile.WriterProfileError):
            profile.validate_token(token("science"), "writer", actor("writer"))
        with self.assertRaises(profile.WriterProfileError):
            profile.validate_token(token("writer"), "science", actor("science"))

    def test_native_authority_negative_matrix(self):
        changes = (
            lambda t: t.update(user="S-1-5-18"), lambda t: t.update(owner="S-1-5-32-544"),
            lambda t: t.update(thread_token=True), lambda t: t.update(token_type=2),
            lambda t: t.update(elevation=1), lambda t: t.update(elevation_type=2),
            lambda t: t.update(ui_access=1), lambda t: t.update(virtualization=1),
            lambda t: t.update(session_id=1), lambda t: t.update(has_restrictions=0),
            lambda t: t.pop("has_restrictions"), lambda t: t.update(restricting_attributes=()),
            lambda t: t.update(restricting_attributes=t["restricting_attributes"][:-1]),
            lambda t: t.update(restricting_attributes=t["restricting_attributes"] + (("S-1-5-11", 7),)),
            lambda t: t.update(group_attributes=t["group_attributes"] + (("S-1-5-32-544", 7),)),
            lambda t: t.update(group_attributes=t["group_attributes"] + (("S-1-5-32-544", 16),)),
            lambda t: t.update(group_attributes=t["group_attributes"] + (t["group_attributes"][0],)),
            lambda t: t.update(group_attributes=tuple((s, 16 if s == "S-1-5-11" else a) for s, a in t["group_attributes"])),
            lambda t: t.update(privilege_attributes=(("SeChangeNotifyPrivilege", 3), ("SeImpersonatePrivilege", 0))),
            lambda t: t.update(privilege_attributes=(("SeChangeNotifyPrivilege", 0),)),
            lambda t: t.pop("modified_id"), lambda t: t.update(token_id=(False, 1)),
            lambda t: t.update(integrity="S-1-16-8192"),
        )
        for role in ("writer", "science"):
            for change in changes:
                observed = token(role)
                change(observed)
                with self.subTest(role=role, change=change), self.assertRaises(profile.WriterProfileError):
                    profile.validate_token(observed, role, actor(role))

    def test_each_generation_observes_its_own_logon_without_rebinding_custody(self):
        bound = role_profile()
        original = asdict(bound)
        for role in ("writer", "science"):
            for logon in ("S-1-5-5-1-2", "S-1-5-5-1-3"):
                profile.validate_token(token(role, logon), role, actor(role))
            stale = token(role)
            stale["restricting_attributes"] = token(role, "S-1-5-5-1-3")["restricting_attributes"]
            with self.assertRaises(profile.WriterProfileError):
                profile.validate_token(stale, role, actor(role))
        self.assertEqual(original, asdict(bound))

    def test_new_policy_removes_volatile_science_logon_from_stable_identity(self):
        base = legacy_policy()
        bound = role_profile()
        with self.assertRaises(custody.ScienceCustodyNativeError):
            replace(base, science_sid=profile.service_sid(bound.science.service_name), actor_profile=bound,
                    science_group_sids=("S-1-5-5-1-2",), science_enabled_group_sids=())

    def test_legacy_policy_digest_is_byte_compatible_not_silently_rebound(self):
        base = legacy_policy()
        original = asdict(base)
        original.pop("actor_profile")
        expected = custody._digest({"profile": custody.PROFILE, **original})
        self.assertEqual(expected, base.policy_sha256)

    def test_transported_owner_write_route_is_explicitly_removed(self):
        bound = role_profile()
        p = SimpleNamespace(writer_sid=profile.LOCAL_SERVICE,
            science_sid=profile.service_sid(bound.science.service_name), actor_profile=bound,
            object_integrity_sid="S-1-16-12288")
        for directory in (False, True):
            transport = custody._expected_aces(p, "transport", directory)
            self.assertIn((1, 3 if directory else 0, custody.MUTATE, p.writer_sid), transport)
            self.assertIn((0, 3 if directory else 0, custody.READ_CONTROL, "S-1-3-4"), transport)
            for kind in ("private", "trusted"):
                final = custody._expected_aces(p, kind, directory)
                self.assertIn((0, 3 if directory else 0, custody.FULL, p.writer_sid), final)
                self.assertIn((0, 3 if directory else 0, custody.FULL,
                               profile.service_sid(bound.writer.service_name)), final)
                self.assertNotIn((1, 3 if directory else 0, custody.MUTATE, p.writer_sid), final)
            self.assertIn("(D;", custody.creation_sddl(p, "transport", directory=directory))

    def test_main_writer_requires_profile_before_any_mutable_initialization(self):
        from momentum_hunter.continuous_production import ProductionWriterServer, ProductionDeploymentError
        with patch("momentum_hunter.continuous_production._topology", side_effect=AssertionError("mutable initialization")):
            with self.assertRaises(ProductionDeploymentError):
                ProductionWriterServer({}, science_custody_policy=SimpleNamespace(actor_profile=role_profile()))

    def test_native_admission_cannot_be_replaced_with_a_launch_boolean(self):
        with self.assertRaises(profile.WriterProfileError):
            profile.NativeWriterAdmission({}, SimpleNamespace(actor_profile=None))
        observed = token("writer")
        with patch.object(profile, "_scm", side_effect=profile.WriterProfileError("no actual SCM")):
            with self.assertRaises(profile.WriterProfileError):
                profile.observe_actor(Mock(), "writer", role_profile(), observed)

    @unittest.skipUnless(os.name == "nt", "Windows native AccessCheck control")
    def test_actual_own_token_extended_queries_and_owner_rights(self):
        native = custody._Native()
        observed = native.token()
        self.assertIn("restricting_attributes", observed)
        self.assertIn("token_id", observed)
        self.assertIn("modified_id", observed)
        user = observed["user"]
        sddl = f"O:{user}G:{user}D:P(D;;0xd0156;;;{user})(A;;RC;;;OW)(A;;FR;;;{user})(A;;FA;;;WD)"
        actual = profile.access_decisions(native, sddl)
        self.assertTrue(actual[1])
        for right in profile.MUTATION_RIGHTS:
            self.assertFalse(actual[right], hex(right))

    @unittest.skipUnless(os.name == "nt", "Windows native AccessCheck control")
    def test_accesscheck_failure_is_not_denial(self):
        native = custody._Native()
        with self.assertRaises((custody.ScienceCustodyNativeError, OSError)):
            profile.access_decisions(native, "not a descriptor")

    def test_native_scalar_boolean_is_not_an_integer_observation(self):
        for key in ("token_type", "elevation", "elevation_type", "ui_access", "virtualization", "session_id", "has_restrictions"):
            row = token("writer")
            row[key] = bool(row[key])
            with self.subTest(key=key), self.assertRaises(profile.WriterProfileError):
                profile.validate_token(row, "writer", actor("writer"))

    def test_complete_resource_paths_and_no_production_activation(self):
        config, bound = configured_profile()
        self.assertEqual(bound, profile.validate_profile_paths(config, bound))
        bad = deepcopy(config)
        bad["inputMode"] = "LIVE_PRODUCTION"
        with self.assertRaises(profile.WriterProfileError):
            profile.validate_profile_paths(bad, bound)
        for index, row in enumerate(bound.resources):
            changed = list(bound.resources)
            changed[index] = replace(row, path="F:/somewhere-else/" + row.name)
            with self.subTest(resource=row.name), self.assertRaises(profile.WriterProfileError):
                profile.validate_profile_paths(config, replace(bound, resources=tuple(changed)))
        with self.assertRaises(profile.WriterProfileError):
            profile.validate_profile_paths(config, replace(bound, writer=replace(bound.writer,
                python_path="F:/q/install/python/Scripts/python.exe"), science=replace(bound.science,
                python_path="F:/q/install/python/Scripts/python.exe")))

    def test_existing_service_role_names_are_not_reinvented(self):
        from momentum_hunter.continuous_host_contract import service_names
        expected = service_names("qual-016d")
        for role in ("writer", "science"):
            self.assertEqual(expected[role], actor(role).service_name)
        with self.assertRaises(profile.WriterProfileError):
            replace(actor("writer"), service_name="MomentumHunterContinuous-qual-016d-ContinuousWriter")

    @unittest.skipUnless(os.name == "nt", "Own-process Windows launch metadata")
    def test_direct_interpreter_keeps_real_parent_without_venv_redirector(self):
        base = Path(sys.base_prefix) / "python.exe"
        paths = list(dict.fromkeys([str(Path(__file__).resolve().parents[1]), *[p for p in sys.path if p]]))
        code = "import sys,json;sys.path[:]=json.loads(" + repr(json.dumps(paths)) + ");" \
            "import os;from momentum_hunter.windows_science_custody import _Native;" \
            "from momentum_hunter.windows_writer_profile import _process;" \
            "n=_Native();print(json.dumps(dict(current=_process(n,os.getpid()),parent=_process(n,os.getppid()))))"
        env = dict(os.environ, PYTHONPATH="F:/untrusted-not-used", PYTHONHOME="F:/untrusted-not-used")
        for key in tuple(env):
            if any(term in key.upper() for term in ("SCHWAB", "ALPACA", "FINVIZ", "IBKR", "API_KEY", "OAUTH", "TOKEN")):
                env.pop(key)
        run = subprocess.run([str(base), "-I", "-S", "-B", "-X", "utf8", "-c", code],
            capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(0, run.returncode, run.stderr)
        observed = json.loads(run.stdout)
        self.assertEqual(PureWindowsPath(base), PureWindowsPath(observed["current"]["image"]))
        self.assertEqual(os.getpid(), observed["parent"]["pid"])

    def test_resource_rights_matrix_rejects_each_missing_or_extra_permission(self):
        for name, (needed, forbidden) in profile.RESOURCE_RULES.items():
            guard = profile.WriterResourceGuard.__new__(profile.WriterResourceGuard)
            guard.native = Mock()
            guard.rows = []
            sec = SimpleNamespace(sddl=name, digest=name)
            good = {right: right in needed for right in profile.FILE_RIGHTS}
            for changed in (None, *needed, *forbidden):
                decisions = dict(good)
                if changed is not None:
                    decisions[changed] = not decisions[changed]
                guard._access_cache = {}
                with self.subTest(resource=name, right=changed), patch.object(profile, "access_decisions", return_value=decisions):
                    if changed is None:
                        guard._rights(name, True, sec)
                    else:
                        with self.assertRaises(profile.WriterProfileError):
                            guard._rights(name, True, sec)

    def test_derived_root_retains_only_writer_inspection_not_content_access(self):
        bound = role_profile()
        p = SimpleNamespace(writer_sid=profile.LOCAL_SERVICE, science_sid=profile.service_sid(bound.science.service_name),
                            actor_profile=bound, object_integrity_sid="S-1-16-12288")
        aces = custody._expected_aces(p, "derived", True)
        self.assertIn((0, 2, 0x1200A1, p.writer_sid), aces)
        self.assertIn((0, 9, 0x120080, p.writer_sid), aces)
        self.assertIn((0, 3, custody.MODIFY_CHILDREN, p.science_sid), aces)
        self.assertIn((1, 3, custody.MUTATE, p.writer_sid), aces)
        self.assertNotEqual(custody._expected_aces(p, "transport", False), custody._expected_aces(p, "derived", False))
        self.assertIn((0, 0, 0x120080, p.writer_sid), custody._expected_aces(p, "derived", False))
        sddl = custody.creation_sddl(p, "derived", directory=True)
        self.assertIn("(A;CI;0x1200a1;", sddl)
        self.assertIn("(A;OIIO;0x120080;", sddl)

    def test_failed_profile_or_service_admission_closes_support_handles(self):
        config, bound = configured_profile()
        native = Mock()
        native.token.return_value = token("writer")
        with patch.object(custody, "_Native", return_value=native), \
             patch.object(profile, "WriterResourceGuard") as guard, \
             patch.object(profile, "observe_actor", return_value={}), \
             patch.object(profile, "verify_service_denials", side_effect=profile.WriterProfileError("control allowed")):
            with self.assertRaises(profile.WriterProfileError):
                profile.NativeWriterAdmission(config, SimpleNamespace(actor_profile=bound))
            guard.return_value.close.assert_called_once()


class DescendantClosureTests(unittest.TestCase):
    def guard(self):
        guard = profile.WriterResourceGuard.__new__(profile.WriterResourceGuard)
        guard.native, guard.rows, guard._access_cache = Mock(), [], {}
        guard._inheritance_cache, guard._bound_paths = set(), set()
        return guard

    def scan(self, guard, name, *, allowed=True, reparse=False, links=1):
        row = next(r for r in role_profile().resources if r.name == name)
        path = Path(row.path) / "unlisted-child.json"
        entry = SimpleNamespace(path=str(path), is_dir=lambda **kwargs: False)
        entries = Mock()
        entries.__enter__ = Mock(return_value=iter([entry]))
        entries.__exit__ = Mock(return_value=False)
        handle = Mock(path=path)
        guard.native.open.return_value = handle
        guard.native.information.return_value = SimpleNamespace(dwFileAttributes=0x400 if reparse else 0,
                                                               nNumberOfLinks=links)
        guard.native.identity.return_value = (1, 0, 123)
        guard.native.security.return_value = SimpleNamespace(sddl=name, digest=name)
        needed, _ = profile.resource_rights(name, False, "unlisted-child.json")
        rights = {right: right in needed for right in profile.FILE_RIGHTS}
        if not allowed:
            rights[262144] = True
        guard._access_cache.clear()
        with patch.object(profile.os, "scandir", return_value=entries), \
             patch.object(profile, "access_decisions", return_value=rights):
            try:
                guard._scan_support(row)
            finally:
                handle.close.assert_called_once()
                handle.close.reset_mock()

    def test_unlisted_forbidden_child_is_checked_in_stable_non_image_subtrees(self):
        for name in profile.RESOURCE_RULES:
            if name in {"runtime_source", "host_image_root", "python_root", "python_base", "configuration", "writer_key"} | profile.DYNAMIC_RESOURCE_ROOTS:
                continue
            with self.subTest(resource=name):
                guard = self.guard()
                self.scan(guard, name)
                with self.assertRaisesRegex(profile.WriterProfileError, "unrelated support authority"):
                    self.scan(guard, name, allowed=False)

    def test_descendant_reparse_and_unrelated_hardlink_fail_closed(self):
        for values in ({"reparse": True}, {"links": 2}):
            with self.subTest(values=values), self.assertRaises(profile.WriterProfileError):
                self.scan(self.guard(), "unrelated_repository", **values)

    def test_metadata_inspection_does_not_request_content_or_deny_peer_sharing(self):
        guard = self.guard()
        self.scan(guard, "unrelated_repository")
        self.assertEqual(0x120080, guard.native.open.call_args.kwargs["access"])
        self.assertEqual(7, guard.native.open.call_args.kwargs["share"])

    def test_readable_temporary_handoff_exception_is_exact_and_not_state_wide(self):
        for name in ("science_derived", "provider_replica", "runtime_state"):
            for path in (".custody-transport.tmp", "other.tmp", "sub/.custody-transport.tmp", ".reader.lock"):
                needed, forbidden = profile.resource_rights(name, False, path)
                exact = name == "science_derived" and path == ".custody-transport.tmp"
                self.assertEqual(exact, 1 in needed)
                self.assertEqual(not exact, 1 in forbidden)
                self.assertIn(2, forbidden)
                self.assertIn(262144, forbidden)

    @unittest.skipUnless(os.name == "nt", "Native in-memory inheritance")
    def test_inherit_only_world_and_creator_owner_authority_is_rejected(self):
        guard = self.guard()
        guard.native = custody._Native()
        user = guard.native.token()["user"]
        for sid in ("WD", "CO"):
            text = f"O:{user}G:{user}D:P(A;;FR;;;{user})(A;OICIIO;FA;;;{sid})"
            security = SimpleNamespace(owner=user, sddl=text, digest=hashlib.sha256(text.encode()).hexdigest())
            with self.subTest(sid=sid), self.assertRaisesRegex(profile.WriterProfileError, "inherited descendant authority"):
                guard._future_children("science_generation", security)

    @unittest.skipUnless(os.name == "nt", "Native in-memory inheritance")
    def test_native_readonly_inheritance_preserves_owner_rights_denial(self):
        guard = self.guard()
        guard.native = custody._Native()
        user = guard.native.token()["user"]
        text = f"O:{user}G:{user}D:P(A;OICI;RC;;;OW)(A;OICI;FR;;;{user})"
        security = SimpleNamespace(owner=user, sddl=text, digest=hashlib.sha256(text.encode()).hexdigest())
        guard._future_children("science_generation", security)
        self.assertEqual(1, len(guard._inheritance_cache))

    @unittest.skipUnless(os.name == "nt", "Own disposable locked file")
    def test_native_metadata_query_coexists_with_exclusive_peer_data_lock(self):
        n = custody._Native()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "own-disposable-peer.dat"
            peer = n.open(path, access=0xC0030000, share=0, disposition=1)
            try:
                observer = n.open(path, access=0x120080, share=7)
                try:
                    identity, digest = n.identity(observer), n.security(observer).digest
                    n.write(peer, b"peer may still update")
                    self.assertEqual(identity, n.identity(observer))
                    self.assertEqual(digest, n.security(observer).digest)
                finally:
                    observer.close()
            finally:
                peer.close()

    def test_generated_writer_plan_uses_bound_direct_interpreter(self):
        from tests.test_continuous_host_boundaries import configuration, seal
        from momentum_hunter.continuous_host_contract import install_plan
        config = configuration(Path("F:/q"))
        _, bound = configured_profile()
        bound = replace(bound, **{role: replace(getattr(bound, role),
            service_name=config["host"]["services"][role],
            generation_root=str(Path(config["hostStateRoot"]) / role)) for role in ("writer", "science")},
            resources=tuple(replace(row, path=str(profile.expected_resource_paths(config)[row.name]))
                            for row in bound.resources))
        config["host"]["science"]["custodyPolicy"]["actor_profile"] = json.loads(json.dumps(asdict(bound)))
        seal(config)
        plan = install_plan(config, Path(config["configRoot"]) / "continuous-deployment.json", Path("F:/q/source"), Path(sys.executable))
        for row in plan["services"]:
            value = row["arguments"][row["arguments"].index("--python-executable") + 1]
            expected = bound.writer.python_path if row["role"] == "writer" else "F:/q/install/python/Scripts/python.exe"
            self.assertEqual(PureWindowsPath(expected), PureWindowsPath(value))

    def test_old_serialized_policy_is_readable_but_never_gets_native_launch_authority(self):
        from tests.test_continuous_host_boundaries import configuration
        from momentum_hunter.continuous_host_contract import science_custody_policy, HostConfigurationError
        config = configuration(Path("F:/q"))
        original = science_custody_policy(config)
        config["host"]["science"]["custodyPolicy"].pop("actor_profile")
        legacy = science_custody_policy(config)
        self.assertEqual(original.policy_sha256, legacy.policy_sha256)
        with patch.object(custody, "_Native", side_effect=AssertionError("must reject before native calls")):
            with self.assertRaises(profile.WriterProfileError):
                profile.NativeWriterAdmission(config, legacy)
        config["host"]["science"]["custodyPolicy"]["unreviewed"] = True
        with self.assertRaises(HostConfigurationError):
            science_custody_policy(config)


class MutableInputAdmissionTests(unittest.TestCase):
    def test_mutable_science_inputs_cannot_be_submitted_to_subtree_scan(self):
        guard = profile.WriterResourceGuard.__new__(profile.WriterResourceGuard)
        for name in profile.DYNAMIC_RESOURCE_ROOTS:
            with self.subTest(name=name), patch.object(profile.os, "scandir",
                    side_effect=AssertionError("must not enumerate mutable input")):
                with self.assertRaisesRegex(profile.WriterProfileError, "not process-admission inputs"):
                    guard._scan_support(SimpleNamespace(name=name, path="F:/untrusted"))


class GenerationBindingTests(unittest.TestCase):
    """Native observation fixtures, not claims that either SCM actor ran."""
    def observe(self, role, mutate=None):
        from momentum_hunter.continuous_host_contract import host_fingerprint
        config, bound = configured_profile()
        config["hostFingerprint"] = host_fingerprint(config)
        current = dict(pid=101, birth=111, image=bound.writer.python_path if role == "writer" else bound.science.host_path)
        parent = dict(pid=202, birth=222, image=bound.writer.host_path) if role == "writer" else dict(current)
        record = dict(role=role, generation=str(uuid.uuid4()), phase="RUNNING", hostFingerprint=config["hostFingerprint"])
        if role == "writer":
            record.update(supervisorPid=parent["pid"], supervisorBirth=parent["birth"], childPid=current["pid"], childBirth=current["birth"])
        else:
            record.update(executionModel="SCM_DIRECT_SCIENCE_SERVICE_PROCESS", servicePid=current["pid"], serviceBirth=current["birth"])
        observed = token(role)
        if mutate:
            mutate(record, current, parent, observed)

        def read(path, *args, **kwargs):
            return io.BytesIO(json.dumps(record if path.name == "generation.json" else config).encode())

        with ExitStack() as stack:
            stack.enter_context(patch.object(profile, "_scm", return_value=dict(pid=202 if role == "writer" else 101)))
            stack.enter_context(patch.object(profile, "_process", side_effect=lambda n, pid: current if pid == 101 else parent))
            stack.enter_context(patch.object(profile.os, "getpid", return_value=101))
            stack.enter_context(patch.object(profile.os, "getppid", return_value=202))
            stack.enter_context(patch.object(Path, "open", read))
            return profile.observe_actor(Mock(), role, bound, observed, check_images=False)

    def test_distinct_fresh_generation_admission_and_stale_record_rejection(self):
        for role in ("writer", "science"):
            first, second = self.observe(role), self.observe(role)
            self.assertNotEqual(first["generation"], second["generation"])
            self.assertNotEqual(profile.admission_identity(first), profile.admission_identity(second))
            common = (
                lambda r, *a: r.update(hostFingerprint="0" * 64),
                lambda r, *a: r.update(role="runtime"),
                lambda r, *a: r.update(phase="EXITED"),
                lambda r, *a: r.update(generation="not-a-uuid"),
                lambda r, cur, *a: cur.update(image="F:/other/python.exe"),
                lambda r, cur, par, t: t.update(restricting_attributes=()),
            )
            fields = ("supervisorPid", "supervisorBirth", "childPid", "childBirth") if role == "writer" else ("servicePid", "serviceBirth")
            for change in (*common, *(lambda r, *a, key=key: r.update({key: 999}) for key in fields)):
                with self.subTest(role=role, change=change), self.assertRaises((profile.WriterProfileError, ValueError)):
                    self.observe(role, change)

    def test_stop_requested_preserves_identity_but_new_token_does_not(self):
        first = self.observe("writer", lambda record, *a: record.update(phase="STOP_REQUESTED"))
        second = deepcopy(first)
        second["token"]["modified_id"] = (11, 12)
        self.assertNotEqual(profile.admission_identity(first), profile.admission_identity(second))


if __name__ == "__main__":
    unittest.main()
