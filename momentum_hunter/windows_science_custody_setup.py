"""Install-only fixed-parent setup, never a runtime repair or privilege grant.

The trusted install owner holds consumers stopped, supplies pinned ancestry
and a durable evidence sink, and restores setup privileges before admission.
Failed resources remain quarantined for that owner's identity-bound cleanup.
"""
from __future__ import annotations

import ctypes as c
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path, PureWindowsPath
from typing import Callable

from momentum_hunter import science_mutable_policy as mutable
from momentum_hunter.windows_science_custody import (
    CustodyRootBinding, DIRECTORY, REPARSE, _Native, _absolute, _io_path,
    _path_key, _require, _sid, storage,
)

SETUP_ACCESS = 0xE0080
SYNCHRONIZE = 0x100000
SET_SECURITY_INFORMATION = 0x80000017
KINDS = (mutable.COMMON, "owner", "derived", "scratch", "staging", "requests")
MUTATION = 0xD0156 | 0x50000000  # Native mutations plus generic write/all.
NESTED_KINDS = frozenset({"owner", "derived", "scratch"})
LABEL_ONLY = "S:(ML;;NW;;;HI)"
INTERMEDIATE_CONTROL = 0x8C14


@dataclass(frozen=True)
class MutableParentsProvisioned:
    profile: str
    version: int
    common: CustodyRootBinding
    roots: tuple[CustodyRootBinding, ...]


def policy_difference(sec, science_sid, kind):
    expected = dict(owner=mutable.WRITER, group=mutable.WRITER,
                    control=mutable.PARENT_CONTROL, protected=True,
                    aces=mutable.expected_aces(science_sid, kind, directory=True),
                    labels=((0 if kind == mutable.COMMON else 3, 1, mutable.HIGH),))
    return [dict(field=k, expected=v, actual=getattr(sec, k))
            for k, v in expected.items() if getattr(sec, k) != v]


def _safe_grants(aces, trusted):
    _require(bool(aces), "Setup cannot rely on an absent/default/null ACL.")
    _require(all(typ in {0, 1} and not (typ == 0 and mask & MUTATION and sid not in trusted)
                 for typ, flags, mask, sid in aces),
             "Setup namespace/default ACL grants mutation outside setup principals.")


def _safe_parent(sec, trusted):
    _safe_grants(sec.aces, trusted)
    # OWNER RIGHTS suppresses an untrusted owner's implicit WRITE_DAC.
    _require(sec.owner in trusted or any(typ == 0 and not flags & 8 and sid == "S-1-3-4"
                 and not mask & MUTATION for typ, flags, mask, sid in sec.aces),
             "Setup parent owner has implicit security mutation authority.")
    _require(sec.labels and all(mask == 1 and sid == mutable.HIGH for _, mask, sid in sec.labels),
             "Setup requires the accepted High/no-write-up label.")


class _SetupNative(_Native):
    """Setters are confined here, not added to the runtime native interface."""
    def __init__(self):
        super().__init__()
        w = self.w
        self.bind(self.a, "SetSecurityInfo", [w.HANDLE, c.c_int, w.DWORD,
                  c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p], w.DWORD)
        for name in ("Owner", "Group"):
            self.bind(self.a, "GetSecurityDescriptor" + name,
                      [c.c_void_p, c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL)
        self.bind(self.a, "GetSecurityDescriptorLength", [c.c_void_p], w.DWORD)
        self.bind(self.k, "GetHandleInformation", [w.HANDLE, c.POINTER(w.DWORD)], w.BOOL)
        self.bind(self.k, "GetFileAttributesW", [w.LPCWSTR], w.DWORD)

    def exists(self, path):
        if self.k.GetFileAttributesW(_io_path(path)) != 0xFFFFFFFF:
            return True
        error = c.get_last_error()
        if error in {2, 3}:
            return False
        raise storage._windows_error("Setup existence check", error)

    def inherited_create(self, path):
        # NULL SECURITY_ATTRIBUTES requests inheritance, never a NULL DACL.
        return self._create_directory(path, None, None)

    def _create_directory(self, path, attributes, carrier):
        ok = bool(self.k.CreateDirectoryW(_io_path(path), attributes))
        error = 0 if ok else c.get_last_error()
        receipt = dict(api="CreateDirectoryW", boolResult=ok, winerror=error,
                       securityAttributes=carrier)
        if not ok:
            failure = storage._windows_error("Create fresh setup directory", error)
            failure.creation_receipt = receipt
            raise failure
        return receipt

    def validate_label_carrier(self, sd):
        w = self.w
        control, revision = w.WORD(), w.DWORD()
        self.checked(self.a.GetSecurityDescriptorControl(sd, c.byref(control), c.byref(revision)), "Carrier control")
        _require(revision.value == 1 and control.value == 0x8010,
                 "Carrier must contain only its explicit mandatory label.")
        for name in ("Owner", "Group"):
            value, defaulted = c.c_void_p(), w.BOOL()
            self.checked(getattr(self.a, "GetSecurityDescriptor" + name)(
                sd, c.byref(value), c.byref(defaulted)), "Carrier " + name)
            _require(not value.value and not defaulted.value, "Carrier supplies owner/group.")
        dacl, present, defaulted = c.c_void_p(), w.BOOL(), w.BOOL()
        self.checked(self.a.GetSecurityDescriptorDacl(sd, c.byref(present), c.byref(dacl), c.byref(defaulted)), "Carrier DACL")
        _require(not present.value and not dacl.value and not defaulted.value, "Carrier supplies a DACL.")
        sacl = c.c_void_p()
        self.checked(self.a.GetSecurityDescriptorSacl(sd, c.byref(present), c.byref(sacl), c.byref(defaulted)), "Carrier SACL")
        _require(present.value and sacl.value and not defaulted.value, "Carrier label missing.")
        _require(c.cast(sacl.value + 4, c.POINTER(w.WORD))[0] == 1,
                 "Carrier must contain exactly one mandatory label.")
        ace = c.c_void_p()
        self.checked(self.a.GetAce(sacl, 0, c.byref(ace)), "Carrier label ACE")
        typ, flags = c.string_at(ace, 2)
        mask = c.cast(ace.value + 4, c.POINTER(w.DWORD))[0]
        _require(typ == 0x11 and flags == 0 and mask == 1 and self.sid(ace.value + 8) == mutable.HIGH,
                 "Carrier must be exactly noninheritable HIGH/NO_WRITE_UP.")

    def labeled_create(self, path):
        with self.security_attributes(LABEL_ONLY) as sa:
            sd = sa._obj.descriptor
            self.validate_label_carrier(sd)
            raw = c.string_at(sd, self.a.GetSecurityDescriptorLength(sd))
            return self._create_directory(path, sa, dict(sddl=LABEL_ONLY,
                binarySdHex=raw.hex(), binarySdSha256=hashlib.sha256(raw).hexdigest(),
                handleInherit=False, labelSecurityInformation=0x10))

    def creation_defaults(self):
        token = self.w.HANDLE()
        self.checked(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, c.byref(token)), "Open creation-default token")
        try:
            result = {}
            for name, info_class in (("owner", 4), ("group", 5)):
                size = self.w.DWORD()
                self.a.GetTokenInformation(token, info_class, None, 0, c.byref(size))
                _require(0 < size.value <= 128 * 1024, "Invalid default identity length.")
                buf = c.create_string_buffer(size.value)
                self.checked(self.a.GetTokenInformation(token, info_class, buf, len(buf), c.byref(size)), "Read creation " + name)
                result[name] = self.sid(c.cast(buf, c.POINTER(c.c_void_p))[0])
        finally:
            self.checked(self.k.CloseHandle(token), "Close creation-default token")
        class Mapping(c.Structure):
            _fields_ = [(k, self.w.DWORD) for k in ("read", "write", "execute", "all")]
        mapping = Mapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        self.bind(self.a, "MapGenericMask", [c.POINTER(self.w.DWORD), c.POINTER(Mapping)], None)
        aces = []
        for typ, flags, mask, sid in self.default_aces():
            _require(typ in {0, 1} and flags == 0, "Unqualified token-default ACE inheritance.")
            concrete = self.w.DWORD(mask)
            self.a.MapGenericMask(c.byref(concrete), c.byref(mapping))
            aces.append((typ, flags, concrete.value, sid))
        return dict(**result, aces=tuple(aces), protected=False, control=INTERMEDIATE_CONTROL,
                    labels=((0, 1, mutable.HIGH),))

    def default_aces(self):
        token = self.w.HANDLE()
        self.checked(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, c.byref(token)),
                     "Open setup default-DACL token")
        try:
            size = self.w.DWORD()
            self.a.GetTokenInformation(token, 6, None, 0, c.byref(size))
            _require(0 < size.value <= 128 * 1024, "Invalid default DACL length.")
            buf = c.create_string_buffer(size.value)
            self.checked(self.a.GetTokenInformation(token, 6, buf, len(buf), c.byref(size)),
                         "Read setup default DACL")
            acl = c.cast(buf, c.POINTER(c.c_void_p))[0]
            _require(bool(acl), "Null token default DACL.")
            count = c.cast(acl + 4, c.POINTER(self.w.WORD))[0]
            _require(count <= 4096, "Unbounded default DACL.")
            rows = []
            for index in range(count):
                ace = c.c_void_p()
                self.checked(self.a.GetAce(acl, index, c.byref(ace)), "Default DACL ACE")
                typ, flags = c.string_at(ace, 2)
                _require(typ in {0, 1}, "Unsupported setup default ACE.")
                mask = c.cast(ace.value + 4, c.POINTER(self.w.DWORD))[0]
                rows.append((typ, flags, mask, self.sid(ace.value + 8)))
            return tuple(rows)
        finally:
            self.checked(self.k.CloseHandle(token), "Close setup token")

    def handle_flags(self, handle):
        flags = self.w.DWORD()
        self.checked(self.k.GetHandleInformation(handle.value, c.byref(flags)), "Setup handle flags")
        return flags.value

    def descriptor_bytes(self, handle):
        sd = c.c_void_p()
        error = self.a.GetSecurityInfo(handle.value, 1, 0x17, None, None, None, None, c.byref(sd))
        if error:
            raise storage._windows_error("Setup descriptor bytes", error)
        try:
            length = self.a.GetSecurityDescriptorLength(sd)
            _require(0 < length <= 128 * 1024, "Invalid setup descriptor length.")
            return c.string_at(sd, length)
        finally:
            self.k.LocalFree(sd)

    def require_empty(self, handle):
        # Ancestors and the directory are retained without delete sharing;
        # only trusted setup principals can add entries at this stage.
        self.require_path(handle, handle.path)
        with os.scandir(handle.path) as entries:
            _require(next(entries, None) is None, "New setup directory is not empty.")

    def apply_policy(self, handle, sddl):
        sd = c.c_void_p()
        self.checked(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, c.byref(sd), None), "Parse fixed-parent policy")
        try:
            owner = c.c_void_p(); group = c.c_void_p()
            dacl = c.c_void_p(); sacl = c.c_void_p()
            defaulted = self.w.BOOL(); present = self.w.BOOL()
            for name, target in (("Owner", owner), ("Group", group)):
                self.checked(getattr(self.a, "GetSecurityDescriptor" + name)(
                    sd, c.byref(target), c.byref(defaulted)), "Extract policy " + name)
            for name, target in (("Dacl", dacl), ("Sacl", sacl)):
                self.checked(getattr(self.a, "GetSecurityDescriptor" + name)(
                    sd, c.byref(present), c.byref(target), c.byref(defaulted)), "Extract policy " + name)
                _require(present.value and target.value, "Missing fixed-parent policy component.")
            error = self.a.SetSecurityInfo(handle.value, 1, SET_SECURITY_INFORMATION,
                                           owner, group, dacl, sacl)
            if error != 0:  # DWORD error, not BOOL/GetLastError.
                failure = storage._windows_error("Apply fixed-parent policy", error)
                failure.assignment_receipt = dict(api="SetSecurityInfo", securityInformation=SET_SECURITY_INFORMATION,
                                                  dwordResult=int(error))
                raise failure
            return error
        finally:
            self.k.LocalFree(sd)


def provision_mutable_parents(state_root: str, science_sid: str, *,
                              approved_ancestry: tuple[CustodyRootBinding, ...],
                              record: Callable[[dict], None],
                              existing_parents: tuple[CustodyRootBinding, ...] = ()) -> MutableParentsProvisioned:
    root = _absolute(state_root)
    _sid(science_sid)
    _require(science_sid.startswith("S-1-5-80-") and science_sid != mutable.WRITER,
             "Setup requires the exact accepted Science service SID.")
    expected = {_path_key(root), *(_path_key(p) for p in PureWindowsPath(root).parents)}
    _require(type(approved_ancestry) is tuple
             and all(type(x) is CustodyRootBinding for x in approved_ancestry)
             and len(approved_ancestry) == len(expected)
             and {_path_key(x.path) for x in approved_ancestry} == expected and callable(record),
             "Setup requires approved ancestry and a durable evidence sink.")
    native = _SetupNative()
    pinned, handles, created, closure = [], [], [], []
    before = kind = current = current_identity = current_owned = current_path = None
    defaults = None
    events = []
    sink = record
    def record(row):
        events.append(row)
        sink(row)
    succeeded = False

    def inspect(handle, path):
        info = native.information(handle)
        _require(bool(info.dwFileAttributes & DIRECTORY) and not info.dwFileAttributes & REPARSE,
                 "Setup encountered a reparse or non-directory parent.")
        native.require_path(handle, path)
        return native.security(handle), native.identity(handle)

    def retain(path, access, *, active_parent=False):
        nonlocal current
        handle = native.open(path, directory=True, access=access, share=3)
        handles.append(handle)
        if active_parent:
            current = handle
        record(dict(stage="HANDLE_ATTEMPT", path=str(path), requested=access, share=3,
                    granted="UNAVAILABLE_UNTIL_QUERY", flags="UNAVAILABLE_UNTIL_QUERY"))
        granted, flags = native.granted_access(handle), native.handle_flags(handle)
        # The sealed Arm-B synchronous handle granted SYNCHRONIZE in addition
        # to the requested 0xE0080. No other grant or handle flag is accepted.
        expected_granted = access | SYNCHRONIZE
        record(dict(stage="HANDLE", path=str(path), requested=access, granted=granted,
                    expectedGranted=expected_granted, flags=flags, share=3,
                    disposition=3, createFlags=0x02200000))
        _require(granted == expected_granted and flags == 0,
                 "Unexpected/inheritable setup handle authority.")
        return handle

    def observation(handle, stage):
        sec, identity = inspect(handle, handle.path)
        raw = native.descriptor_bytes(handle)
        differences = policy_difference(sec, science_sid, kind)
        record(dict(stage=stage, parentClass=kind, path=str(handle.path), objectIdentity=identity,
                    expectedPolicyId=hashlib.sha256(mutable.parent_sddl(science_sid, kind).encode("ascii")).hexdigest(),
                    actualDescriptor=asdict(sec), binarySdHex=raw.hex(), binarySdSha256=hashlib.sha256(raw).hexdigest(),
                    firstDifferingField=differences[0]["field"] if differences else None,
                    allDifferingFields=differences))
        return sec, identity

    def recheck():
        for handle, bound in pinned:
            sec, identity = inspect(handle, handle.path)
            _require(identity == bound.file_identity and sec.digest == bound.descriptor_sha256,
                     "Setup parent changed during provisioning.")
        _require(native.token() == before, "Setup actor/privilege drift.")

    def failure_inspection():
        unavailable = {}
        def attempt(name, read):
            if current is None:
                unavailable[name] = dict(reason="NO_RETAINED_HANDLE")
                return None
            try:
                return read()
            except BaseException as error:
                unavailable[name] = dict(type=type(error).__name__, message=str(error))
                return None
        # Failure of one query must not suppress the other available evidence.
        identity = attempt("identity", lambda: native.identity(current))
        info = attempt("information", lambda: native.information(current))
        path_ok = attempt("path", lambda: (native.require_path(current, current.path), True)[1])
        sec = attempt("descriptor", lambda: native.security(current))
        raw = attempt("descriptorBytes", lambda: native.descriptor_bytes(current))
        differences = policy_difference(sec, science_sid, kind) if sec is not None else None
        return dict(stage="FAILURE_BEFORE_HANDLE_CLOSURE", parentClass=kind,
                    path=str(current_path) if current_path is not None else None,
                    objectIdentity=identity,
                    retainedDirectoryIdentityProven=bool(identity is not None and path_ok and info is not None
                        and info.dwFileAttributes & DIRECTORY and not info.dwFileAttributes & REPARSE),
                    expectedPolicyId=hashlib.sha256(mutable.parent_sddl(science_sid, kind).encode("ascii")).hexdigest() if kind else None,
                    actualDescriptor=asdict(sec) if sec is not None else None,
                    binarySdHex=raw.hex() if raw is not None else None,
                    binarySdSha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
                    firstDifferingField=differences[0]["field"] if differences else None,
                    allDifferingFields=differences, unavailable=unavailable)

    try:
        before = native.token()
        record(dict(stage="SETUP_TOKEN_BEFORE", token=before, privilegeAdjustment=False))
        _require(before["thread_token"] is False and before["token_type"] == 1
                 and before["elevation"] == 1 and before["integrity"] in {mutable.HIGH, "S-1-16-16384"}
                 and before["user"] not in {science_sid, mutable.WRITER}
                 and dict(before["privilege_attributes"]).get("SeRestorePrivilege", 0) & 2,
                 "Only the already-authorized elevated setup owner may provision fixed parents.")
        trusted = {before["user"], "S-1-5-18", "S-1-5-32-544"}
        _safe_grants(native.default_aces(), trusted)
        defaults = native.creation_defaults()
        _safe_grants(defaults["aces"], trusted)
        _require(defaults["owner"] in trusted, "Untrusted creation-default owner.")
        record(dict(stage="CREATION_DEFAULTS", expectedNestedIntermediate=defaults))
        for bound in sorted(approved_ancestry, key=lambda x: len(PureWindowsPath(x.path).parts)):
            handle = retain(Path(bound.path), mutable.PARENT_ACCESS)
            sec, identity = inspect(handle, handle.path)
            _require(identity == bound.file_identity and sec.digest == bound.descriptor_sha256
                     and sec.owner == bound.owner_sid and sec.owner != science_sid,
                     "Approved setup ancestry has drifted.")
            if _path_key(bound.path) == _path_key(root):
                _safe_parent(sec, trusted)
            pinned.append((handle, bound))
        paths = {k: Path(mutable.namespace_path(root, k)) for k in KINDS}
        existing = {k: native.exists(path) for k, path in paths.items()}
        _require(not any(existing.values()) or all(existing.values()),
                 "Incomplete fixed-parent set is quarantined, not resumed or restamped.")
        _require(type(existing_parents) is tuple
                 and all(type(x) is CustodyRootBinding for x in existing_parents),
                 "Existing setup identity contract is invalid.")
        approved_existing = {x.namespace: x for x in existing_parents}
        _require((not any(existing.values()) and not existing_parents)
                 or (all(existing.values()) and len(existing_parents) == 6
                     and set(approved_existing) == set(KINDS)),
                 "Existing parents require their original approved identities.")
        result = {}
        for kind, path in paths.items():
            current = current_identity = current_owned = None
            current_path = path
            recheck()
            if not existing[kind]:
                _require(kind not in NESTED_KINDS or mutable.COMMON in result,
                         "Nested parent requires finalized admitted common parent.")
                record(dict(stage="CREATE_ATTEMPT", parentClass=kind, path=str(path),
                            api="CreateDirectoryW", labelOnly=kind in NESTED_KINDS))
                try:
                    creation = native.labeled_create(path) if kind in NESTED_KINDS else native.inherited_create(path)
                except BaseException as exc:
                    record(dict(stage="CREATE_FAILED", parentClass=kind, path=str(path),
                                result=getattr(exc, "creation_receipt", None),
                                unavailable=None if hasattr(exc, "creation_receipt") else "NATIVE_RETURN_UNAVAILABLE"))
                    raise
                current_owned = dict(parentClass=kind, path=str(path), identity=None)
                created.append(current_owned)
                record(dict(stage="CREATE", parentClass=kind, path=str(path), **creation))
                retain(path, SETUP_ACCESS, active_parent=True)
                sec, current_identity = observation(current, "CREATED_INHERITED")
                created[-1]["identity"] = current_identity
                if kind in NESTED_KINDS:
                    differences = [dict(field=k, expected=v, actual=getattr(sec, k))
                                   for k, v in defaults.items() if getattr(sec, k) != v]
                    record(dict(stage="INTERMEDIATE_READBACK", parentClass=kind, path=str(path),
                        objectIdentity=current_identity, expectedDescriptor=defaults, actualDescriptor=asdict(sec),
                        firstDifferingField=differences[0]["field"] if differences else None,
                        allDifferingFields=differences))
                _safe_parent(sec, trusted)
                if kind in NESTED_KINDS:
                    _require(not differences, "Nested creation intermediate security differs from exact setup defaults/label.")
                native.require_empty(current)
                recheck()
                immediate, immediate_identity = inspect(current, path)
                _require(immediate_identity == current_identity and immediate.digest == sec.digest,
                         "Created setup object/security replaced.")
                record(dict(stage="SET_SECURITY_INFO_ATTEMPT", parentClass=kind, objectIdentity=current_identity,
                            securityInformation=SET_SECURITY_INFORMATION))
                try:
                    code = native.apply_policy(current, mutable.parent_sddl(science_sid, kind))
                except BaseException as exc:
                    record(dict(stage="SET_SECURITY_INFO_FAILED", parentClass=kind, objectIdentity=current_identity,
                                result=getattr(exc, "assignment_receipt", None),
                                unavailable=None if hasattr(exc, "assignment_receipt") else "NATIVE_RETURN_UNAVAILABLE"))
                    raise
                record(dict(stage="SET_SECURITY_INFO", parentClass=kind, objectIdentity=current_identity,
                            securityInformation=SET_SECURITY_INFORMATION, dwordResult=code))
            else:
                retain(path, mutable.PARENT_ACCESS, active_parent=True)
            sec, identity = observation(current, "FINAL_READBACK")
            _require(current_identity is None or current_identity == identity, "Setup object identity changed.")
            _require(mutable.security_matches(sec, science_sid, kind, directory=True),
                     "Provisioned parent does not match exact Architecture-B security.")
            if existing[kind]:
                old = approved_existing[kind]
                _require(_path_key(old.path) == _path_key(path) and old.file_identity == identity
                         and old.descriptor_sha256 == sec.digest and old.owner_sid == sec.owner,
                         "Existing parent identity differs from its original binding.")
            bound = CustodyRootBinding(kind, str(path), identity, sec.owner, sec.digest)
            pinned.append((current, bound))
            result[kind] = bound
        recheck()
        record(dict(stage="ADMISSION_READY", bindings=[asdict(result[k]) for k in KINDS],
                    installerPrivilegeRestorationStillRequired=True))
        succeeded = True
        return MutableParentsProvisioned(mutable.PROFILE, mutable.VERSION, result[mutable.COMMON],
                                         tuple(result[k] for k in sorted(mutable.KINDS)))
    except BaseException as exc:
        details = failure_inspection()
        if current_identity is None and details["retainedDirectoryIdentityProven"]:
            current_identity = details["objectIdentity"]
            if current_owned is not None:
                current_owned["identity"] = current_identity
        try:
            record(details)
        except BaseException as receipt_error:
            details["unavailable"]["inspectionReceipt"] = dict(
                type=type(receipt_error).__name__, message=str(receipt_error))
        record(dict(stage="FAILURE", parentClass=kind, objectIdentity=current_identity,
                    exceptionClass=type(exc).__name__, message=str(exc),
                    winerror=getattr(exc, "winerror", None), failureInspection=details,
                    descriptorUnavailable={k: v for k, v in details["unavailable"].items()
                        if k in {"descriptor", "descriptorBytes"}} or None))
        raise
    finally:
        errors = []
        for handle in reversed(handles):
            try:
                handle.close()
                closure.append(dict(path=str(handle.path), closed=True))
            except BaseException as exc:
                closure.append(dict(path=str(handle.path), closed=False, error=str(exc)))
                errors.append(exc)
        after = None
        try:
            after = native.token()
            _require(before is not None and after == before, "Setup token changed before return.")
        except BaseException as exc:
            errors.append(exc)
        record(dict(stage="SETUP_FINALLY", success=succeeded and not errors, handles=closure,
                    tokenBefore=before, tokenAfter=after, productAdjustedPrivilege=False,
                    tokenUnchanged=before is not None and after == before,
                    privilegeRestoration="INSTALL_OWNER_MUST_RESTORE_BEFORE_ADMISSION",
                    ownedObjects=created, ownedObjectDisposition="PRESERVED_FOR_INSTALL_OWNER_IDENTITY_BOUND_CLEANUP",
                    parentClass=kind, path=str(current_path) if current_path is not None else None,
                    fileId=current_identity, expectedIntermediateDescriptor=defaults if kind in NESTED_KINDS else None,
                    expectedFinalDescriptor=mutable.parent_sddl(science_sid, kind) if kind else None,
                    apiSequence=[r for r in events if r["stage"] in {"CREATE_ATTEMPT", "CREATE", "CREATE_FAILED", "HANDLE_ATTEMPT", "HANDLE", "SET_SECURITY_INFO_ATTEMPT", "SET_SECURITY_INFO_FAILED", "SET_SECURITY_INFO"}],
                    intermediateNativeDescriptors=[r for r in events if r["stage"] in {"CREATED_INHERITED", "INTERMEDIATE_READBACK"}],
                    privilegeStateBefore="EXTERNAL_INSTALL_OWNER_RECEIPT_REQUIRED",
                    privilegeStateDuring=before, privilegeStateAfter=after,
                    externalPrivilegeRestoration="UNAVAILABLE_TO_PRODUCT; REQUIRE_INSTALL_OWNER_FINALLY_RECEIPT",
                    cleanupErrors=[str(x) for x in errors]))
        if errors:
            raise errors[0]
