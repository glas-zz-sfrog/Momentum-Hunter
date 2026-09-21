"""Product B deterministic controls; doubles are not physical SCM acceptance."""
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path, PureWindowsPath
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from momentum_hunter import science_mutable_policy as b
from momentum_hunter import windows_science_custody as mod
from momentum_hunter import windows_science_custody_setup as setup
from momentum_hunter import windows_writer_profile as actors
from momentum_hunter.strategy_science_source_reader import _ReaderLock, SourceReaderError
from tests.test_science_custody_windows_007 import NativeDouble, Handle, winerror, policy as legacy_policy
from tests.test_windows_writer_profile_016d import role_profile, token

SCIENCE = actors.service_sid(role_profile().science.service_name)
PARAMS = SimpleNamespace(science_sid=SCIENCE, writer_sid=b.WRITER, actor_profile=role_profile(),
                         object_integrity_sid=b.HIGH, version=2)


def security(kind, directory=False):
    if kind in b.KINDS | {b.COMMON}:
        aces = b.expected_aces(SCIENCE, kind, directory=directory)
        owner = b.WRITER if directory else SCIENCE
        flags = (0 if kind == b.COMMON else 3) if directory else 16
        control = b.PARENT_CONTROL if directory else b.CHILD_CONTROL
        labels = ((flags, 1, b.HIGH),)
        protected = directory
    else:
        aces = mod._expected_aces(PARAMS, "trusted" if kind == "ancestor" else kind, directory)
        owner = b.WRITER
        labels = ((3 if directory else 0, 1, b.HIGH),)
        control, protected = 0x9C14, True
    # The native-double digest encodes every field; real native uses canonical SDDL.
    sddl = json.dumps([owner, aces, labels, control])
    return mod._Security(owner, sddl, aces, labels, protected, owner, control)


def policy():
    root = "F:/q/science"
    roots = tuple(mod.CustodyRootBinding(name, b.namespace_path(root, name), (1, 0, index),
                  b.WRITER, security(name if name in b.KINDS else "private" if name == "private" else "trusted", True).digest)
                  for index, name in enumerate(sorted(mod.ROOT_NAMES | {"owner", "scratch"}), 1))
    paths = {str(p) for r in roots for p in PureWindowsPath(r.path).parents}
    ancestors = tuple(mod.CustodyRootBinding("ancestor", path, (1, 1, index), b.WRITER,
        security(b.COMMON if mod._path_key(path) == mod._path_key(b.namespace_path(root, b.COMMON))
                 else "ancestor", True).digest) for index, path in enumerate(sorted(paths), 1))
    return mod.ScienceCustodyPolicy("a" * 64, SCIENCE, b.WRITER, (), (), b.HIGH, b.HIGH,
        roots, ancestors, 1024 * 1024, 64 * 1024, 1000, 100, version=2, actor_profile=role_profile())


class BNative(NativeDouble):
    def __init__(self, p, role="science"):
        super().__init__(p, role)
        for bound in (*p.ancestors, *p.roots):
            kind = (b.COMMON if mod._path_key(bound.path) == mod._path_key(p.mutable_parent_path)
                    else bound.namespace if bound.namespace in b.KINDS | {"private", "ancestor"} else "trusted")
            self.objects[mod._path_key(bound.path)].security = security(kind, True)
        self.grant_override = None
        self.after_rename = None
        self.stream = None
        self.mkdirs = []

    def token(self):
        return self.token_override if self.token_override is not None else token(self.role)

    def kind_for(self, path):
        for bound in self.p.roots:
            if mod._path_key(path).startswith(mod._path_key(bound.path) + "\\"):
                return bound.namespace if bound.namespace in b.KINDS | {"private"} else "trusted"
        raise AssertionError("Unexpected test path: " + str(path))

    def open(self, path, **kwargs):
        self.opens.append((Path(path), dict(kwargs)))
        key = mod._path_key(path)
        disposition = kwargs.get("disposition", 3)
        if disposition == 1 and key in self.objects:
            raise winerror(183)
        if key not in self.objects:
            if disposition not in {1, 4}:
                raise winerror(2)
            kind = self.kind_for(path)
            if kind in b.KINDS:
                assert kwargs.get("sddl") is None
            elif kwargs.get("sddl") == mod.creation_sddl(self.p, "trusted", directory=False):
                kind = "trusted"
            obj = self.add(path)
            obj.security = security(kind)
        handle = Handle(self, self.objects[key], Path(path))
        handle.access = kwargs.get("access", mod.READ)
        return handle

    def granted_access(self, handle):
        return handle.access if self.grant_override is None else self.grant_override

    def reader_stream(self, handle):
        handle.closed = True
        return self.stream

    def rename(self, handle, target):
        super().rename(handle, target)
        if self.after_rename:
            self.after_rename(handle)

    def mkdir(self, path, sddl):
        self.mkdirs.append((path, sddl))
        if mod._path_key(path) in self.objects:
            return
        kind = next((k for k in b.RELATIVE_ROOTS if mod._path_key(path) == mod._path_key(b.namespace_path("F:/q/science", k))), "trusted")
        self.add(path, directory=True).security = security(kind, True)


def admission(native, role, profile, observed, **_kwargs):
    actors.validate_token(observed, role, getattr(profile, role))
    return {"identity": {"token": observed, "role": role}}


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.p = policy()
        self.n = BNative(self.p)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(mod, "_Native", return_value=self.n))
        self.stack.enter_context(patch.object(mod, "observe_actor", side_effect=admission))
        self.stack.enter_context(patch.object(mod, "admission_identity", side_effect=lambda x: x))
        self.stack.enter_context(patch.object(mod, "access_decisions", return_value={x: False for x in actors.MUTATION_RIGHTS}))

    def backend(self):
        value = mod.WindowsScienceCustodyBackend(self.p, role="science")
        self.addCleanup(value.close)
        return value

    def test_owner_reader_null_descriptor_exact_masks_and_grants(self):
        value = self.backend()
        opens = {p.name: opts for p, opts in self.n.opens if opts.get("disposition") == 4}
        self.assertEqual(opens[".science-owner.lock"], dict(access=b.OWNER_LEASE_ACCESS, share=0, disposition=4, sddl=None))
        self.assertEqual(opens[".reader.lock"], dict(access=b.READER_LOCK_ACCESS, share=3, disposition=4, sddl=None))
        self.assertIn("owner-lease", str(value._lease.path))
        self.assertEqual(value.policy.profile, b.PROFILE)

    def test_successful_open_is_not_proof_of_exact_granted_rights(self):
        self.n.grant_override = b.OWNER_LEASE_ACCESS | 0x100
        with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "granted handle rights"):
            self.backend()
        self.assertTrue(all(h.closed for h in self.n.handles.values()))

    def test_transport_publication_recovery_and_identity_bound_cleanup(self):
        value = self.backend()
        name = "b" * 32 + ".stage"
        created = value.create_transport("staging", name, b"raw")
        self.assertEqual(created.raw, b"raw")
        temp = [(p, o) for p, o in self.n.opens if o.get("disposition") == 1]
        self.assertEqual(temp[0][1], dict(access=b.TRANSPORT_ACCESS, share=1, disposition=1, sddl=None))
        self.assertIn("transport-scratch", str(temp[0][0]))
        self.assertEqual(created.file_identity, self.n.renames[-1][0])
        self.assertTrue(value.delete_transport("staging", name, expected_identity=created.file_identity,
                        expected_sha256=hashlib.sha256(b"raw").hexdigest()))
        self.assertEqual(self.n.opens[-1][1]["access"], b.RECOVERY_ACCESS)

    def test_replaced_cleanup_target_is_preserved(self):
        value = self.backend()
        name = "b" * 32 + ".stage"
        created = value.create_transport("staging", name, b"raw")
        obj = self.n.objects[mod._path_key(value.namespace_root("staging") / name)]
        obj.identity = (1, 0, 99999)
        with self.assertRaises(mod.CustodyCommitConflict):
            value.delete_transport("staging", name, expected_identity=created.file_identity,
                                   expected_sha256=hashlib.sha256(b"raw").hexdigest())
        self.assertFalse(obj.deleted)

    def test_post_rename_security_and_identity_are_rechecked(self):
        for alteration in (lambda h: setattr(h.obj, "identity", (1, 4, 99)),
                           lambda h: setattr(h.obj, "security", replace(h.obj.security, protected=True))):
            with self.subTest(alteration=alteration):
                value = self.backend()
                self.n.after_rename = alteration
                with self.assertRaises(mod.ScienceCustodyNativeError):
                    value.create_transport("requests", "request.json", b"raw")
                self.n.objects.pop(mod._path_key(value.namespace_root("requests") / "request.json"))
                value.close()

    def test_existing_incompatible_object_never_restamped(self):
        path = Path(self.p.root("owner").path) / ".science-owner.lock"
        obj = self.n.add(path)
        original = obj.security
        with self.assertRaises(mod.ScienceCustodyNativeError):
            self.backend()
        self.assertIs(obj.security, original)
        self.assertEqual(self.n.mkdirs, [])

    def test_startup_parent_security_drift_rejected(self):
        for bound in self.p.roots:
            if bound.namespace not in b.KINDS:
                continue
            obj = self.n.objects[mod._path_key(bound.path)]
            original = obj.security
            for change in (dict(owner=SCIENCE), dict(group=SCIENCE), dict(control=0x8C14),
                           dict(aces=original.aces[::-1]), dict(labels=((3, 1, "S-1-16-8192"),))):
                with self.subTest(root=bound.namespace, change=change):
                    obj.security = replace(original, **change)
                    with self.assertRaises(mod.ScienceCustodyNativeError):
                        self.backend()
                    obj.security = original

    def test_post_start_parent_drift_is_fatal_not_live_repaired(self):
        value = self.backend()
        obj = self.n.objects[mod._path_key(self.p.root("scratch").path)]
        original = obj.security
        obj.security = replace(original, control=0x8C14)
        with self.assertRaises(mod.ScienceCustodyNativeError):
            value.create_transport("requests", "request.json", b"raw")
        self.assertTrue(value._closed)
        obj.security = original
        with self.assertRaises(mod.ScienceCustodyNativeError):
            value.create_transport("requests", "request.json", b"raw")

    def test_parent_drift_during_publish_is_fatal(self):
        value = self.backend()
        parent = self.n.objects[mod._path_key(self.p.root("requests").path)]
        self.n.after_rename = lambda _: setattr(parent, "security", replace(parent.security, group=SCIENCE))
        with self.assertRaises(mod.ScienceCustodyNativeError):
            value.create_transport("requests", "request.json", b"raw")
        self.assertTrue(value._closed)

    def test_wrong_actor_and_changed_generation_reject(self):
        self.n.token_override = token("writer")
        with self.assertRaises(mod.ScienceCustodyNativeError):
            self.backend()
        self.n.token_override = None
        value = self.backend()
        changed = token("science")
        changed["token_id"] = (123, 456)
        self.n.token_override = changed
        with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "generation changed"):
            value.create_transport("requests", "request.json", b"raw")

    def test_reparse_hardlink_wrong_type_and_final_path_fail_before_bytes(self):
        value = self.backend()
        path = value.namespace_root("requests") / "request.json"
        obj = self.n.add(path, raw=b"raw")
        obj.security = security("requests")
        for field, bad in (("attributes", mod.REPARSE), ("attributes", mod.DIRECTORY),
                           ("links", 2), ("path", Path("F:/escape"))):
            old = getattr(obj, field)
            with self.subTest(field=field), patch.object(self.n, "read", side_effect=AssertionError("premature byte read")):
                setattr(obj, field, bad)
                with self.assertRaises(mod.ScienceCustodyNativeError):
                    value.read_request("request.json", maximum=32)
                setattr(obj, field, old)

    def test_failed_write_restart_discards_only_exact_unpublished_scratch(self):
        value = self.backend()
        self.n.fail_write = True
        with self.assertRaises(OSError):
            value.create_transport("requests", "request.json", b"payload")
        scratch = self.n.objects[mod._path_key(value.namespace_root("scratch") / ".custody-transport.tmp")]
        identity = scratch.identity
        value.close()
        successor = self.backend()
        self.assertIn(identity, self.n.deletes)
        self.assertEqual(successor.create_transport("requests", "request.json", b"payload").raw, b"payload")
        self.assertTrue(any(o.get("access") == b.RECOVERY_ACCESS for _, o in self.n.opens))

    def test_existing_transport_no_overwrite(self):
        value = self.backend()
        first = value.create_transport("requests", "request.json", b"first")
        with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "never overwrite"):
            value.create_transport("requests", "request.json", b"second")
        self.assertEqual(value.read_request("request.json", maximum=32), first)

    def test_native_reader_adapter_transfers_validated_handle_not_path(self):
        value = self.backend()
        self.n.stream = io.BytesIO()
        self.assertIs(value.open_reader_lock(), self.n.stream)
        self.assertEqual(self.n.opens[-1][1], dict(access=b.READER_LOCK_ACCESS, share=3, disposition=4, sddl=None))
        self.assertTrue(self.n.handles[max(self.n.handles)].closed)

    def test_native_reader_transfer_failure_closes_handle(self):
        value = self.backend()
        with patch.object(self.n, "reader_stream", side_effect=OSError("fd allocation")):
            with self.assertRaises(OSError):
                value.open_reader_lock()
        self.assertTrue(self.n.handles[max(self.n.handles)].closed)

    def test_b_finalizer_durability_lost_reply_recovery_and_policy_mismatch(self):
        from momentum_hunter.science_custody_commit import (
            ScienceCustodyFinalizer, CustodyCommitRequest, CustodyCommitError, identity_for_artifact,
        )
        from momentum_hunter.science_custody_mailbox import sha256
        from momentum_hunter.strategy_science_recorder.canonical import canonical_json_bytes
        for phase in ("after_final", "after_receipt"):
            with self.subTest(phase=phase):
                science = self.backend()
                partial = {"partial_name": phase}
                raw = canonical_json_bytes({"partial_before": partial})
                relative = "quarantine-receipts/" + sha256(canonical_json_bytes(partial)) + ".quarantine.json"
                generation = ("a" if phase == "after_final" else "b") * 32
                request = CustodyCommitRequest(self.p.policy_sha256,
                    identity_for_artifact(source_root_identity=self.p.source_root_identity,
                        final_root="custody", relative_path=relative, raw=raw),
                    "custody", relative, sha256(raw), sha256(raw), len(raw), generation + ".stage", generation)
                stage = science.create_transport("staging", request.staging_name, raw)
                science.close()
                self.n.role = "writer"
                writer = mod.WindowsScienceCustodyBackend(self.p, role="writer")
                self.addCleanup(writer.close)
                def crash(at):
                    if at == phase:
                        raise RuntimeError("lost reply")
                with self.assertRaisesRegex(RuntimeError, "lost reply"):
                    ScienceCustodyFinalizer(writer, fault_hook=crash).finalize(request)
                final = writer.read_trusted("custody", relative, maximum=len(raw))
                self.assertNotEqual(final.file_identity, stage.file_identity)
                self.assertEqual(final.raw, stage.raw)
                writer.close()
                writer = mod.WindowsScienceCustodyBackend(self.p, role="writer")
                self.addCleanup(writer.close)
                recovered = ScienceCustodyFinalizer(writer).finalize(request)
                self.assertFalse(recovered.created)
                self.assertEqual(final, writer.read_trusted("custody", relative, maximum=len(raw)))
                self.assertEqual(recovered.receipt, ScienceCustodyFinalizer(writer).lookup(request).receipt)
                with self.assertRaises(CustodyCommitError):
                    ScienceCustodyFinalizer(writer).finalize(replace(request, policy_sha256=legacy_policy().policy_sha256))
                writer.close()
                self.n.role = "science"


class PolicyTests(unittest.TestCase):
    def test_host_and_writer_bind_exact_v2_paths_without_legacy_derived_alias(self):
        from tests.test_continuous_host_boundaries import configuration
        from momentum_hunter import continuous_host_contract as host
        p = policy()
        cfg = configuration(Path("F:/q"))
        cfg["hostStateRoot"] = "F:/q/generations"
        cfg["host"]["instanceId"] = "qual-016d"
        cfg["host"]["services"] = host.service_names("qual-016d")
        cfg["host"]["science"]["custodyPolicy"] = json.loads(json.dumps(asdict(p)))
        paths = actors.expected_resource_paths(cfg)
        profile = replace(p.actor_profile, resources=tuple(replace(r, path=str(paths[r.name]))
                          for r in p.actor_profile.resources))
        p = replace(p, actor_profile=profile)
        cfg["host"]["science"]["custodyPolicy"] = json.loads(json.dumps(asdict(p)))
        self.assertEqual(host.science_custody_policy(cfg), p)
        self.assertEqual(paths["science_derived"], PureWindowsPath("F:/q/science/mutable-v2/reader-lock"))
        cfg["host"]["science"]["stateRoot"] = "F:/other/science"
        with self.assertRaises(host.HostConfigurationError):
            host.science_custody_policy(cfg)

    def test_writer_diagnostic_v2_roots_require_metadata_not_legacy_parent_ea(self):
        from tests.test_writer_admission_contract_017a import configuration
        from momentum_hunter import windows_writer_self_diagnostic as diag
        cfg, profile = configuration()
        cfg["host"]["science"]["custodyPolicy"] = {"version": 2}
        paths = actors.expected_resource_paths(cfg)
        profile = replace(profile, resources=tuple(replace(r, path=str(paths[r.name])) for r in profile.resources))
        rows = diag.targets(cfg, profile)
        for name in ("staging", "requests", "owner", "scratch"):
            row = next(x for x in rows if x["name"] == "custody_" + name)
            self.assertEqual(row["path"], b.namespace_path(cfg["host"]["science"]["stateRoot"], name))
            self.assertEqual(diag.required_rights(row), (1, 128, 131072, 1048576))
            self.assertIn(8, row["forbidden"])
        leaf = next(x for x in rows if x["name"] == "science_derived:.reader.lock")
        self.assertNotIn(1, leaf["needed"])
        self.assertIn(1, leaf["forbidden"])
        self.assertFalse(any(".custody-transport.tmp" in row["name"] for row in rows))

    def test_masks_are_exact_and_distinct(self):
        self.assertEqual((b.OWNER_LEASE_ACCESS, b.READER_LOCK_ACCESS, b.TRANSPORT_ACCESS, b.RECOVERY_ACCESS),
                         (0x120081, 0x120083, 0x130083, 0x130081))
        for mask in b.CHILD_MASKS.values():
            self.assertFalse(mask & (0x10 | 0x100 | 0x40000 | 0x80000))

    def test_exact_parent_child_security_and_each_semantic_mutation(self):
        for kind in b.KINDS | {b.COMMON}:
            for directory in ((True,) if kind == b.COMMON else (True, False)):
                sec = security(kind, directory)
                self.assertTrue(b.security_matches(sec, SCIENCE, kind, directory=directory))
                changes = [dict(owner="S-1-5-18"), dict(group="S-1-5-18"), dict(control=0),
                           dict(protected=not directory), dict(aces=sec.aces[::-1]), dict(labels=()),
                           dict(aces=sec.aces + ((0, 0, 0x1F01FF, SCIENCE),))]
                for index, ace in enumerate(sec.aces):
                    for field, new in ((1, ace[1] ^ 1), (2, ace[2] ^ 2), (3, "S-1-1-0")):
                        row = list(ace)
                        row[field] = new
                        changes.append(dict(aces=sec.aces[:index] + (tuple(row),) + sec.aces[index + 1:]))
                for change in changes:
                    with self.subTest(kind=kind, directory=directory, change=change):
                        self.assertFalse(b.security_matches(replace(sec, **change), SCIENCE, kind, directory=directory))

    def test_parent_policy_disallows_directory_delete_subdirectories_or_security_mutation(self):
        for kind in b.KINDS | {b.COMMON}:
            aces = b.expected_aces(SCIENCE, kind, directory=True)
            science = [mask for typ, flags, mask, sid in aces if typ == 0 and sid == SCIENCE and not flags & 8]
            self.assertEqual(len(science), 1)
            self.assertFalse(science[0] & (4 | 64 | 65536 | 262144 | 524288))
            self.assertIn("D:PAI", b.parent_sddl(SCIENCE, kind))
            self.assertIn("S:AI(ML;", b.parent_sddl(SCIENCE, kind))

    def test_v2_never_emits_explicit_creator_descriptor(self):
        p = policy()
        for kind in b.KINDS | {"transport"}:
            with self.assertRaises(mod.ScienceCustodyNativeError):
                mod.creation_sddl(p, kind, directory=False)

    def test_v1_identity_unchanged_and_v2_cannot_admit_v1_topology(self):
        old = legacy_policy()
        raw = asdict(old)
        raw.pop("actor_profile")
        self.assertEqual(old.policy_sha256, mod._digest({"profile": mod.PROFILE, **raw}))
        with self.assertRaises(mod.ScienceCustodyNativeError):
            replace(old, version=2)
        p = policy()
        with self.assertRaises(mod.ScienceCustodyNativeError):
            replace(p, version=1)
        bad = replace(p.root("staging"), path="F:/q/science/staging")
        with self.assertRaises(mod.ScienceCustodyNativeError):
            replace(p, roots=tuple(bad if x.namespace == "staging" else x for x in p.roots))
        self.assertNotEqual(p.policy_sha256, old.policy_sha256)

    def test_writer_trusted_finalization_policy_is_unchanged(self):
        p = policy()
        before = SimpleNamespace(**{**vars(PARAMS), "version": 1})
        for kind in ("private", "trusted"):
            for directory in (False, True):
                self.assertEqual(mod.creation_sddl(before, kind, directory=directory),
                                 mod.creation_sddl(p, kind, directory=directory))
        for kind in b.KINDS:
            self.assertIn((1, 16, mod.MUTATE, b.WRITER), b.expected_aces(SCIENCE, kind, directory=False))


class SetupTests(unittest.TestCase):
    def test_setup_is_fixed_provisioning_with_no_existing_repair(self):
        p = policy()
        native = BNative(p)
        root = "F:/q/science"
        expected = {mod._path_key(root), *(mod._path_key(x) for x in PureWindowsPath(root).parents)}
        approved = tuple(x for x in p.ancestors if mod._path_key(x.path) in expected)
        with patch.object(setup, "_Native", return_value=native):
            result = setup.provision_mutable_parents(root, SCIENCE, approved_ancestry=approved)
        self.assertEqual(result.version, 2)
        self.assertEqual({x.namespace for x in result.roots}, b.KINDS)
        self.assertEqual(len(native.mkdirs), 6)
        self.assertTrue(all(h.closed for h in native.handles.values()))
        bad = native.objects[mod._path_key(p.root("owner").path)]
        bad.security = replace(bad.security, group=SCIENCE)
        with patch.object(setup, "_Native", return_value=native):
            with self.assertRaisesRegex(mod.ScienceCustodyNativeError, "exact Architecture-B"):
                setup.provision_mutable_parents(root, SCIENCE, approved_ancestry=approved)
        self.assertEqual(bad.security.group, SCIENCE)

    def test_unbound_setup_rejected_before_native_io(self):
        with patch.object(setup, "_Native", side_effect=AssertionError("native access")):
            for root in ("F:/q/science", "F:/q/../escape", "relative"):
                with self.assertRaises(mod.ScienceCustodyNativeError):
                    setup.provision_mutable_parents(root, SCIENCE, approved_ancestry=())


class ReaderSemanticsTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows native handle-to-CRT semantics")
    def test_actual_narrow_handle_transfer_and_lock_lifecycle_without_elevation(self):
        native = mod._Native()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "lock"
            def opener():
                handle = native.open(path, access=b.READER_LOCK_ACCESS, share=3, disposition=4)
                try:
                    self.assertEqual(native.granted_access(handle), b.READER_LOCK_ACCESS)
                    return native.reader_stream(handle)
                finally:
                    handle.close()
            first, second = _ReaderLock(path, acquire_stream=opener), _ReaderLock(path, acquire_stream=opener)
            try:
                first.acquire()
                with self.assertRaises(SourceReaderError):
                    second.acquire()
                first.release()
                second.acquire()
            finally:
                first.release()
                second.release()
            self.assertEqual(path.read_bytes(), b"\0")

    def test_bound_stream_initialization_lock_contention_unlock_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "lock"
            path.touch()
            opener = lambda: path.open("r+b")
            first = _ReaderLock(path, acquire_stream=opener)
            second = _ReaderLock(path, acquire_stream=opener)
            try:
                first.acquire()
                first.handle.seek(0)
                self.assertEqual(first.handle.read(), b"\0")
                first.handle.seek(0)
                with self.assertRaises(SourceReaderError):
                    second.acquire()
                self.assertIsNone(second.handle)
                first.release()
                second.acquire()
            finally:
                first.release()
                second.release()
            self.assertEqual(path.read_bytes(), b"\0")

    def test_bound_stream_fails_closed_without_fallback(self):
        with patch.object(Path, "open", side_effect=AssertionError("ordinary open")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("parent mutation")):
            def fail():
                raise PermissionError("native denied")
            with self.assertRaises(PermissionError):
                _ReaderLock(Path("nonexistent"), acquire_stream=fail).acquire()

    def test_initialization_failure_closes_acquired_stream(self):
        handle = tempfile.TemporaryFile()
        with patch("os.fsync", side_effect=OSError("flush failed")):
            with self.assertRaisesRegex(OSError, "flush failed"):
                _ReaderLock(Path("unused"), acquire_stream=lambda: handle).acquire()
        self.assertTrue(handle.closed)


if __name__ == "__main__":
    unittest.main()
