"""Explicitly invoked disposable Windows native qualification for custody 007.

This tool does not run in the normal test suite. --execute-new-disposable-fixture
is required. An existing output directory is always refused. No privilege,
service, account, production root or existing ancestor ACL is changed.
"""
from __future__ import annotations

import argparse
import ctypes as c
from ctypes import wintypes as w
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import traceback
from types import SimpleNamespace

# The script is deliberately run from the admitted worktree with approved
# Python. Add only that exact source tree, never predecessor evidence scripts.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))
from momentum_hunter import windows_science_custody as native
from momentum_hunter.science_custody_commit import (
    CustodyCommitRequest, ScienceCustodyFinalizer, canonical_protocol_bytes,
    identity_for_artifact, sha256,
)
from momentum_hunter.science_custody_mailbox import ScienceCustodyMailboxWriter

ANON = "S-1-5-7"
UNTRUSTED = "S-1-16-0"
REC = {"schema": "ARGUS_SCIENCE_CUSTODY_007_PRODUCT_NATIVE_V1",
       "status": "NOT_STARTED", "operations": [], "checks": [], "native_io": [],
       "actual_scm_qualification": False, "science_factory_native_qualification": False,
       "production_changed": False, "provider_contact": False,
       "services_changed": False, "accounts_created": False,
       "privileges_adjusted": False, "uac_requested": False}


def record_check(name, ok, **detail):
    REC["checks"].append({"check": name, "passed": bool(ok), **detail})
    if not ok:
        raise AssertionError(name)


def error_detail(exc):
    return {"type": type(exc).__name__, "message": str(exc),
            "win32Error": getattr(exc, "winerror", None),
            "errno": getattr(exc, "errno", None)}


def bind(lib, name, args, ret):
    fn = getattr(lib, name)
    fn.argtypes, fn.restype = args, ret
    return fn


def initialize_api():
    n = native._Native()
    k, a = n.k, n.a
    bind(k, "GetCurrentThreadId", [], w.DWORD)
    bind(k, "OpenThread", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
    bind(a, "ImpersonateAnonymousToken", [w.HANDLE], w.BOOL)
    bind(a, "RevertToSelf", [], w.BOOL)
    bind(a, "GetSecurityDescriptorSacl",
         [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL)
    bind(a, "GetSecurityDescriptorDacl",
         [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL)
    bind(a, "SetNamedSecurityInfoW",
         [w.LPCWSTR, c.c_int, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p], w.DWORD)
    bind(a, "ConvertStringSidToSidW", [w.LPCWSTR, c.POINTER(c.c_void_p)], w.BOOL)
    bind(k, "DeleteFileW", [w.LPCWSTR], w.BOOL)
    bind(k, "MoveFileExW", [w.LPCWSTR, w.LPCWSTR, w.DWORD], w.BOOL)
    bind(k, "CreateFileMappingW",
         [w.HANDLE, c.c_void_p, w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR], w.HANDLE)
    bind(k, "MapViewOfFile", [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, c.c_size_t], c.c_void_p)
    bind(k, "UnmapViewOfFile", [c.c_void_p], w.BOOL)
    return n


def absent_thread_token(n):
    h = w.HANDLE()
    c.set_last_error(0)
    ok = bool(n.a.OpenThreadToken(n.k.GetCurrentThread(), 8, True, c.byref(h)))
    error = 0 if ok else c.get_last_error()
    if ok:
        n.checked(n.k.CloseHandle(h), "Close unexpected thread token")
    return {"success": ok, "win32Error": error}


def anonymous(n, name, action, expected="ALLOW"):
    result = {}
    failures = []
    def worker():
        row = {"operation": name, "expected": expected}
        thread = None
        impersonated = False
        try:
            row["threadId"] = n.k.GetCurrentThreadId()
            row["before"] = absent_thread_token(n)
            record_check(name + ":initial-no-thread-token",
                         not row["before"]["success"] and row["before"]["win32Error"] == 1008)
            thread = n.k.OpenThread(0x100, False, n.k.GetCurrentThreadId())
            n.checked(thread, "OpenThread THREAD_IMPERSONATE")
            n.checked(n.a.ImpersonateAnonymousToken(thread), "ImpersonateAnonymousToken")
            impersonated = True
            row["token"] = n.token()
            record_check(name + ":matched-anonymous-token",
                         row["token"]["user"] == row["token"]["owner"] == ANON
                         and row["token"]["integrity"] == UNTRUSTED
                         and row["token"]["privileges"] == ())
            row["result"] = action()
            if expected == "ALLOW":
                record_check(name + ":positive", row["result"]["success"], result=row["result"])
            elif expected == "DENY5":
                record_check(name + ":denial",
                             not row["result"]["success"] and row["result"]["win32Error"] == 5,
                             result=row["result"])
            result.update(row["result"])
        except BaseException as exc:
            row["failure"] = error_detail(exc)
            failures.append(exc)
        finally:
            try:
                if impersonated:
                    try:
                        c.set_last_error(0)
                        ok = bool(n.a.RevertToSelf())
                        row["revert"] = {"success": ok, "win32Error": 0 if ok else c.get_last_error()}
                        if not ok:
                            raise RuntimeError("RevertToSelf failed.")
                        row["after"] = absent_thread_token(n)
                        if row["after"]["success"] or row["after"]["win32Error"] != 1008:
                            raise RuntimeError("Reversion could not be verified: thread token remains.")
                    except BaseException as exc:
                        row["fatal_reversion_failure"] = error_detail(exc)
                        print(json.dumps({"fatal": "REVERSION_NOT_VERIFIED", "row": row}), flush=True)
                        os._exit(71)
                if thread:
                    n.checked(n.k.CloseHandle(thread), "Close thread handle")
            except BaseException as exc:
                row["cleanup_failure"] = error_detail(exc)
                failures.append(exc)
            finally:
                REC["operations"].append(row)
    t = threading.Thread(target=worker, name="custody007-native-anonymous-control")
    t.start()
    t.join()
    if failures:
        raise failures[0]
    return result


def safe_new_path(path, base):
    path = Path(path)
    if not path.is_absolute() or not path.resolve().is_relative_to(base.resolve()) or path == base:
        raise RuntimeError("Fixture target must be a strict descendant of the new output root.")
    for ancestor in (path, *path.parents):
        if ancestor.exists() and getattr(ancestor.lstat(), "st_file_attributes", 0) & 0x400:
            raise RuntimeError("Reparse fixture component refused.")
        if ancestor == base:
            break
    return path


def label_new(n, path, base, *, directory):
    path = safe_new_path(path, base)
    sddl = f"S:(ML;{'OICI' if directory else ''};NW;;;{UNTRUSTED})"
    sd = c.c_void_p(); acl = c.c_void_p(); present = w.BOOL(); defaulted = w.BOOL()
    n.checked(n.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, c.byref(sd), None), "Convert explicit fixture label")
    try:
        n.checked(n.a.GetSecurityDescriptorSacl(sd, c.byref(present),
                                                c.byref(acl), c.byref(defaulted)), "Extract label")
        error = int(n.a.SetNamedSecurityInfoW(str(path), 1, 0x10, None, None, None, acl))
        REC.setdefault("label_setup", []).append({"path": str(path),
                     "api": "SetNamedSecurityInfoW", "securityInformation": 0x10,
                     "returnedWin32Error": error})
        record_check("new-object-label:" + path.name, error == 0, win32Error=error)
    finally:
        n.k.LocalFree(sd)


def inspect(n, path, *, directory=False, maximum=1024 * 1024):
    h = n.open(Path(path), directory=directory, access=0x1200A0 if directory else native.READ, share=3)
    try:
        sec = n.security(h)
        value = {"path": str(path), "file_identity": n.identity(h), "owner_sid": sec.owner,
                 "descriptor_sha256": sec.digest, "sddl": sec.sddl,
                 "aces": sec.aces, "labels": sec.labels,
                 "links": int(n.information(h).nNumberOfLinks)}
        if not directory:
            raw = n.read(h, maximum)
            value.update({"bytesHex": raw.hex(), "sha256": sha256(raw), "size": len(raw)})
        return value
    finally:
        h.close()


def create_actor_file(n, path, sddl, raw):
    # The relative path and trusted CWD are the explicit anonymous fixture
    # capability. These operations do not pretend to construct SCM Science.
    h = n.open(Path(path), access=0xC0030000, share=7, disposition=1, sddl=sddl)
    try:
        n.write(h, raw)
        sec = n.security(h)
        return {"success": True, "win32Error": 0,
                "api": "CreateFileW+WriteFile+FlushFileBuffers+CloseHandle",
                "file_identity": n.identity(h), "owner_sid": sec.owner,
                "descriptor_sha256": sec.digest, "sddl": sec.sddl, "labels": sec.labels}
    finally:
        h.close()


def access(n, path, mask, directory=False):
    c.set_last_error(0)
    h = n.k.CreateFileW(str(path), mask, 7, None, 3,
                       0x00200000 | (0x02000000 if directory else 0), None)
    if c.cast(h, c.c_void_p).value == c.c_void_p(-1).value:
        return {"success": False, "win32Error": c.get_last_error(),
                "api": "CreateFileW", "requestedMask": mask, "path": str(path)}
    try:
        return {"success": True, "win32Error": 0, "api": "CreateFileW",
                "requestedMask": mask, "path": str(path)}
    finally:
        n.checked(n.k.CloseHandle(h), "Close access probe")


def move(n, source, target, flags=0):
    c.set_last_error(0)
    ok = bool(n.k.MoveFileExW(str(source), str(target), flags))
    return {"success": ok, "win32Error": 0 if ok else c.get_last_error(),
            "api": "MoveFileExW", "source": str(source), "target": str(target), "flags": flags}


def delete(n, path):
    c.set_last_error(0)
    ok = bool(n.k.DeleteFileW(str(path)))
    return {"success": ok, "win32Error": 0 if ok else c.get_last_error(),
            "api": "DeleteFileW", "path": str(path)}


def delete_exact_handle(n, path, identity, digest):
    """Actual Product FileDispositionInfo primitive; no Science-factory claim."""
    h = n.open(Path(path), access=native.READ | native.DELETE, share=1)
    try:
        sec = n.security(h)
        raw = n.read(h, 1024 * 1024)
        record_check("native-cleanup-same-handle-identity-hash-owner",
                     n.identity(h) == tuple(identity) and sha256(raw) == digest
                     and sec.owner == ANON, actual_identity=n.identity(h),
                     actual_sha256=sha256(raw), owner_sid=sec.owner, sddl=sec.sddl)
        checked_identity = n.identity(h)
        n.delete(h)
        return {"success": True, "win32Error": 0,
                "api": "SetFileInformationByHandle(FileDispositionInfo)",
                "file_identity": checked_identity, "sha256": sha256(raw)}
    finally:
        h.close()


def change_security(n, path, kind):
    sd = c.c_void_p(); ptr = c.c_void_p()
    try:
        if kind == "owner":
            n.checked(n.a.ConvertStringSidToSidW(ANON, c.byref(ptr)), "Convert owner")
            info = 1
            error = int(n.a.SetNamedSecurityInfoW(str(path), 1, info, ptr, None, None, None))
        else:
            n.checked(n.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                f"D:P(A;;FA;;;{ANON})", 1, c.byref(sd), None), "Convert attacker DACL")
            present = w.BOOL(); defaulted = w.BOOL()
            n.checked(n.a.GetSecurityDescriptorDacl(sd, c.byref(present),
                      c.byref(ptr), c.byref(defaulted)), "Extract attacker DACL")
            info = 0x80000004
            error = int(n.a.SetNamedSecurityInfoW(str(path), 1, info, None, None, ptr, None))
        return {"success": error == 0, "win32Error": error,
                "api": "SetNamedSecurityInfoW", "securityInformation": info, "path": str(path)}
    finally:
        if sd:
            n.k.LocalFree(sd)
        elif ptr:
            n.k.LocalFree(ptr)


def trace_backend(backend):
    """Observe calls/results without replacing any native decision or bytes."""
    for name in ("open", "security", "read", "write", "rename", "delete", "mkdir"):
        original = getattr(backend._native, name)
        def traced(*args, _name=name, _original=original, **kwargs):
            row = {"primitive": _name,
                   "subject": str(getattr(args[0], "path", args[0])) if args else "",
                   "kwargs": {key: value for key, value in kwargs.items() if key != "sddl"}}
            try:
                result = _original(*args, **kwargs)
                row["success"] = True
                if isinstance(result, bytes):
                    row.update({"size": len(result), "sha256": sha256(result)})
                elif isinstance(result, native._Security):
                    row.update({"owner_sid": result.owner, "sddl": result.sddl,
                                "descriptor_sha256": result.digest, "labels": result.labels})
                return result
            except BaseException as exc:
                row.update({"success": False, **error_detail(exc)})
                raise
            finally:
                REC["native_io"].append(row)
        setattr(backend._native, name, traced)


def main(args):
    base = Path(args.output_root)
    if (os.name != "nt" or not args.execute_new_disposable_fixture
            or not base.is_absolute() or base.exists() or not base.parent.is_dir()
            or not base.name.startswith("ARGUS-SCIENCE-CUSTODY-007-NATIVE-")
            or base.resolve() != base):
        raise RuntimeError("Explicit fresh absolute task-specific output root required.")
    REC.update({"startedAtUtc": datetime.now(timezone.utc).isoformat(),
                "sourceRoot": str(SOURCE_ROOT), "outputRoot": str(base),
                "scope": "DISPOSABLE_PRODUCT_WRITER_BACKEND_PLUS_ANONYMOUS_ACTOR_NOT_SCM",
                "limitations": ["Anonymous relative CWD operations are representative, not SCM Science.",
                 "Production Science backend absolute-ancestor factory is not bypassed or native-qualified here.",
                 "Conditional transport cleanup has pure production-flow tests; direct actor cleanup is not its native factory proof.",
                 "Power-loss durability and exclusive service-process attestation are not claimed."]})
    REC["source_hashes_before_setup"] = {
        str(p.relative_to(SOURCE_ROOT)): sha256(p.read_bytes()) for p in (
            SOURCE_ROOT / "momentum_hunter/windows_science_custody.py",
            SOURCE_ROOT / "momentum_hunter/science_custody_commit.py",
            SOURCE_ROOT / "momentum_hunter/science_custody_mailbox.py", Path(__file__))}
    base.mkdir()
    n = initialize_api()
    primary = n.token()
    record_check("trusted-primary-role", not primary["thread_token"] and primary["user"] == primary["owner"]
                 and primary["user"] != ANON and primary["elevation"] == 0)
    REC["trusted_primary_token"] = primary
    cfg = SimpleNamespace(writer_sid=primary["user"], science_sid=ANON, object_integrity_sid=UNTRUSTED)
    fixture = base / "fixture"
    for path in (fixture, fixture / "reader"):
        n.mkdir(safe_new_path(path, base), native.creation_sddl(cfg, "trusted", directory=True))
        label_new(n, path, base, directory=True)
    root_paths = {name: fixture / ("reader/cursors" if name == "cursors" else name)
                  for name in sorted(native.ROOT_NAMES)}
    for name, path in root_paths.items():
        kind = "private" if name == "private" else (
            "transport" if name in native.TRANSPORT | {"derived"} else "trusted")
        n.mkdir(safe_new_path(path, base), native.creation_sddl(cfg, kind, directory=True))
        label_new(n, path, base, directory=True)
    roots = []
    for name, path in root_paths.items():
        observed = inspect(n, path, directory=True)
        REC.setdefault("provisioned_roots", []).append(observed)
        roots.append(native.CustodyRootBinding(name, str(path), tuple(observed["file_identity"]),
                     observed["owner_sid"], observed["descriptor_sha256"]))
    ancestors = []
    for path in sorted({p for root in root_paths.values() for p in root.parents},
                       key=lambda p: len(p.parts)):
        observed = inspect(n, path, directory=True)
        REC.setdefault("existing_ancestor_readonly_observations", []).append(observed)
        ancestors.append(native.CustodyRootBinding("ancestor", str(path),
                         tuple(observed["file_identity"]), observed["owner_sid"],
                         observed["descriptor_sha256"]))
    policy = native.ScienceCustodyPolicy(source_root_identity="7" * 64,
        science_sid=ANON, writer_sid=primary["user"], science_group_sids=(),
        science_privilege_names=(), science_integrity_sid=UNTRUSTED,
        object_integrity_sid=UNTRUSTED, roots=tuple(roots), ancestors=tuple(ancestors),
        max_artifact_bytes=1024 * 1024, max_request_bytes=64 * 1024,
        max_history_entries=10000, max_pinned_directories=256)
    REC["policy"] = asdict(policy)
    REC["policy_sha256"] = policy.policy_sha256
    os.chdir(fixture)
    REC["trusted_process_cwd_before_impersonation"] = str(fixture)
    backend = native.WindowsScienceCustodyBackend(policy, role="writer")
    trace_backend(backend)
    handles = {}
    try:
        REC["writer_native_readiness"] = {
            "policy_sha256": backend.policy_sha256, "lease_identity": backend.lease_identity,
            "roots": {key: {**asdict(value), "root": str(value.root)}
                      for key, value in backend.validate_readonly_roots().items()}}
        raw = canonical_protocol_bytes({"sequence": 1, "type": "NATIVE_007_FIXTURE",
                                        "data": {"text": "unchanged-original"}})
        relative = f"ledger/{1:020d}-{sha256(raw)}.event.json"
        generation = "1" * 32
        request = CustodyCommitRequest(policy.policy_sha256,
            identity_for_artifact(source_root_identity=policy.source_root_identity,
                                  final_root="arrivals", relative_path=relative, raw=raw),
            "arrivals", relative, sha256(raw), sha256(raw), len(raw),
            generation + ".stage", generation)
        stage_rel = "staging/" + request.staging_name
        final_rel = "arrivals/" + relative
        file_sddl = native.creation_sddl(policy, "transport", directory=False)
        anonymous(n, "anonymous-create-flush-close-staging",
                  lambda: create_actor_file(n, stage_rel, file_sddl, raw))
        anonymous(n, "anonymous-create-flush-close-request",
                  lambda: create_actor_file(n, "requests/request.json", file_sddl, request.to_bytes()))
        REC["source_before_commit"] = inspect(n, fixture / stage_rel)
        REC["request_before_commit"] = inspect(n, fixture / "requests/request.json")
        finalizer = ScienceCustodyFinalizer(backend)
        mailbox = ScienceCustodyMailboxWriter(finalizer, mailbox_backend=backend)

        def retain_write():
            handles["write"] = n.open(Path(stage_rel), access=0x40000000, share=7)
            return {"success": True, "win32Error": 0, "api": "CreateFileW", "access": 0x40000000}
        anonymous(n, "retain-anonymous-staging-write-handle", retain_write)
        try:
            try:
                mailbox.poll_once()
                raise AssertionError("Retained writable source was admitted.")
            except OSError as exc:
                record_check("product-denies-retained-source-write", exc.winerror == 32,
                             **error_detail(exc))
        finally:
            handles.pop("write").close()
        record_check("no-final-after-retained-write-rejection",
                     backend.read_trusted("arrivals", relative, maximum=len(raw)) is None)

        def retain_map():
            file = n.open(Path(stage_rel), access=0xC0000000, share=7)
            try:
                mapping = n.k.CreateFileMappingW(file.value, None, 4, 0, 0, None)
                n.checked(mapping, "Create writable source mapping")
                handles["mapping"] = mapping
                view = n.k.MapViewOfFile(mapping, 2, 0, 0, 0)
                n.checked(view, "Map writable source view")
                handles["view"] = view
                return {"success": True, "win32Error": 0,
                        "api": "CreateFileMappingW(PAGE_READWRITE)+MapViewOfFile(FILE_MAP_WRITE)"}
            finally:
                file.close()
        anonymous(n, "retain-writable-source-map-after-file-close", retain_map)
        mapped_commit = None
        REC["mapping_expectation"] = {
            "source": "https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew",
            "documented_requirement": "Omitting FILE_SHARE_WRITE fails if a writable file mapping exists.",
            "claim_limit": "Record the actual API result; do not manufacture mapping exclusion."}
        try:
            try:
                mapped_commit = mailbox.poll_once()
                REC["mapping_exclusion"] = "NOT_PROVEN_SOURCE_OPEN_ADMITTED"
                record_check("mapped-source-admission-produced-real-receipt",
                             mapped_commit is not None)
                c.memmove(handles["view"], b"mapped-mutation", len(b"mapped-mutation"))
                record_check("mapped-source-write-does-not-alias-committed-copy",
                             backend.read_trusted("arrivals", relative, maximum=len(raw)).raw == raw)
            except OSError as exc:
                REC["mapping_exclusion"] = "WRITABLE_MAPPING_REJECTED"
                record_check("product-denies-retained-source-map", exc.winerror == 32,
                             **error_detail(exc))
        finally:
            if "view" in handles:
                n.checked(n.k.UnmapViewOfFile(handles.pop("view")), "Unmap source view")
            if "mapping" in handles:
                n.checked(n.k.CloseHandle(handles.pop("mapping")), "Close source mapping")

        result = mapped_commit or mailbox.poll_once()
        record_check("actual-product-mailbox-commit", result is not None and result.created)
        REC["product_commit_receipt"] = json.loads(result.receipt.to_bytes())
        REC["final_before_attacks"] = inspect(n, fixture / final_rel)
        REC["claim_and_receipt_direct_lookup"] = {
            "lookup_original_receipt": finalizer.lookup(request).receipt.to_bytes().hex()}
        record_check("distinct-source-final-object",
                     REC["source_before_commit"]["file_identity"] != REC["final_before_attacks"]["file_identity"]
                     and REC["source_before_commit"]["owner_sid"] == ANON
                     and REC["final_before_attacks"]["owner_sid"] == primary["user"]
                     and REC["final_before_attacks"]["sha256"] == sha256(raw))

        def mutate_stage_after_commit():
            h = n.open(Path(stage_rel), access=0x40000000, share=7)
            try:
                n.write(h, b"attacker-modified-source-after-copy")
                return {"success": True, "win32Error": 0, "api": "CreateFileW+WriteFile+FlushFileBuffers"}
            finally:
                h.close()
        anonymous(n, "positive-staging-remains-writable-after-product-copy", mutate_stage_after_commit)
        REC["source_after_mutation"] = inspect(n, fixture / stage_rel)
        record_check("retained-source-authority-cannot-mutate-final",
                     inspect(n, fixture / final_rel)["sha256"] == sha256(raw))
        backend.close()
        REC["all_product_backend_handles_closed_before_attacks"] = True

        def final_read():
            h = n.open(Path(final_rel), access=native.READ, share=7)
            try:
                observed = n.read(h, len(raw))
                return {"success": observed == raw, "win32Error": 0,
                        "api": "CreateFileW+ReadFile", "sha256": sha256(observed),
                        "file_identity": n.identity(h)}
            finally:
                h.close()
        anonymous(n, "positive-final-read-after-backend-close", final_read)
        for label, mask in (("WRITE", 2), ("APPEND", 4), ("DELETE", 0x10000),
                            ("WRITE_DAC", 0x40000), ("WRITE_OWNER", 0x80000)):
            anonymous(n, "deny-final-" + label, lambda mask=mask: access(n, final_rel, mask), "DENY5")
        anonymous(n, "deny-final-DeleteFileW", lambda: delete(n, final_rel), "DENY5")
        anonymous(n, "deny-final-rename", lambda: move(n, final_rel, "staging/stolen.tmp"), "DENY5")
        anonymous(n, "deny-final-replace", lambda: move(n, stage_rel, final_rel, 1), "DENY5")
        anonymous(n, "deny-final-DACL-regrant", lambda: change_security(n, final_rel, "dacl"), "DENY5")
        anonymous(n, "deny-final-owner-change", lambda: change_security(n, final_rel, "owner"), "DENY5")
        for label, mask in (("ADD_FILE", 2), ("DELETE_CHILD", 0x40), ("DELETE", 0x10000),
                            ("WRITE_DAC", 0x40000), ("WRITE_OWNER", 0x80000)):
            anonymous(n, "deny-parent-" + label, lambda mask=mask: access(n, "arrivals/ledger", mask, True), "DENY5")
        anonymous(n, "deny-parent-rename", lambda: move(n, "arrivals/ledger", "staging/stolen-ledger"), "DENY5")
        anonymous(n, "deny-ancestor-DELETE_CHILD", lambda: access(n, "arrivals", 0x40, True), "DENY5")
        anonymous(n, "deny-parent-add-file", lambda: access_create(n, "arrivals/ledger/forbidden.tmp"), "DENY5")
        REC["final_after_attacks"] = inspect(n, fixture / final_rel)
        record_check("final-bytes-owner-descriptor-label-id-unchanged",
                     REC["final_before_attacks"] == REC["final_after_attacks"])
        backend = native.WindowsScienceCustodyBackend(policy, role="writer")
        trace_backend(backend)
        recovered = ScienceCustodyFinalizer(backend).lookup(request)
        record_check("cold-reopen-original-verified-receipt",
                     recovered is not None and recovered.receipt.to_bytes() == result.receipt.to_bytes())
        backend.close()
        anonymous(n, "post-restart-final-WRITE_DAC-denied", lambda: access(n, final_rel, 0x40000), "DENY5")
        anonymous(n, "post-restart-final-DELETE-denied", lambda: delete(n, final_rel), "DENY5")
        # Preserve original mutated staging/request as adversarial evidence. A
        # separate new synthetic staging object supplies actual cleanup control.
        cleanup = "staging/" + "3" * 32 + ".stage"
        cleanup_evidence = anonymous(n, "positive-cleanup-control-stage-create",
                  lambda: create_actor_file(n, cleanup, file_sddl, b"cleanup-control"))
        anonymous(n, "positive-exact-handle-cleanup-after-real-receipt",
                  lambda: delete_exact_handle(n, cleanup, cleanup_evidence["file_identity"],
                                              sha256(b"cleanup-control")))
        REC["cleanup_classification"] = "ACTUAL_PRODUCT_FILE_DISPOSITION_PRIMITIVE_SAME_HANDLE_ID_HASH_CONTROL_NOT_SCIENCE_FACTORY_OR_CLIENT_ACK"
        REC["status"] = ("PRODUCT_WRITER_NATIVE_REPRESENTATIVE_GATES_PASS_SCIENCE_FACTORY_SCM_UNQUALIFIED"
                         if REC["mapping_exclusion"] == "WRITABLE_MAPPING_REJECTED"
                         else "COPY_BOUNDARY_PROVED_MAPPING_EXCLUSION_UNQUALIFIED_REVIEW_REQUIRED")
    finally:
        backend.close()
        if "write" in handles:
            handles["write"].close()
        if "view" in handles:
            n.checked(n.k.UnmapViewOfFile(handles["view"]), "Unmap remaining view")
        if "mapping" in handles:
            n.checked(n.k.CloseHandle(handles["mapping"]), "Close remaining mapping")
        REC["source_hashes"] = {str(p.relative_to(SOURCE_ROOT)): sha256(p.read_bytes()) for p in (
            SOURCE_ROOT / "momentum_hunter/windows_science_custody.py",
            SOURCE_ROOT / "momentum_hunter/science_custody_commit.py",
            SOURCE_ROOT / "momentum_hunter/science_custody_mailbox.py", Path(__file__))}
    return base


def access_create(n, path):
    c.set_last_error(0)
    h = n.k.CreateFileW(path, 0xC0000000, 7, None, 1, 0x00200000, None)
    if c.cast(h, c.c_void_p).value == c.c_void_p(-1).value:
        return {"success": False, "win32Error": c.get_last_error(),
                "api": "CreateFileW(CREATE_NEW)", "path": path}
    n.checked(n.k.CloseHandle(h), "Close unexpected create")
    return {"success": True, "win32Error": 0, "api": "CreateFileW(CREATE_NEW)", "path": path}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--execute-new-disposable-fixture", action="store_true")
    args = parser.parse_args()
    try:
        main(args)
    except BaseException as exc:
        REC["status"] = "STOP_NO_ESCALATION"
        REC["failure"] = {**error_detail(exc), "traceback": traceback.format_exc()}
    finally:
        REC["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
        out = Path(args.output_root)
        if out.is_dir() and REC.get("outputRoot") == str(out):
            receipt = out / "PRODUCT-NATIVE-RECEIPT.json"
            with receipt.open("x", encoding="utf-8") as stream:
                json.dump(REC, stream, indent=2, default=str)
                stream.flush()
                os.fsync(stream.fileno())
            print(json.dumps({"status": REC["status"], "failure": REC.get("failure"),
                              "receipt": str(receipt), "checks": len(REC["checks"]),
                              "operations": len(REC["operations"])}, indent=2))
        else:
            print(json.dumps({"status": REC["status"], "failure": REC.get("failure")}, indent=2))
    raise SystemExit(0 if REC["status"].startswith("PRODUCT_WRITER_NATIVE_REPRESENTATIVE_GATES_PASS") else 1)
