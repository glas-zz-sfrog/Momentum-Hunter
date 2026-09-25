"""Fail-closed Windows account-domain boundary for Science custody 007.

No portable fallback, provisioning, privilege adjustment, service operation or
production activation is provided.  Only the trusted configuration selects
roots and security principals; transport bytes never do.  Normal finalization
does not impersonate Science.  The trust unit is the existing Writer account,
not exclusive attestation of one service executable.
"""
from __future__ import annotations

import ctypes as c
import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from typing import Iterator, Literal

from momentum_hunter.windows_writer_profile import (
    ScmRoleProfile, _extended_token, access_decisions, admission_identity,
    encode_profile, observe_actor, service_sid, MUTATION_RIGHTS, ActorProofCache, _proof_value,
)

from momentum_hunter import windows_writer_storage as storage
from momentum_hunter import science_mutable_policy as mutable
from momentum_hunter.science_custody_commit import (
    CustodyCommitConflict, CustodyCommitIntegrityError, CustodyObjectEvidence,
    MAX_REQUEST_BYTES as PROTOCOL_METADATA_BYTES, completion_path, validate_relative_path,
)

PROFILE = "science-nonowner-native-custody-v1"
TRUSTED = frozenset({"claims", "receipts", "arrivals", "custody", "cursors"})
TRANSPORT = frozenset({"staging", "requests"})
ROOT_NAMES = TRUSTED | TRANSPORT | {"private", "derived"}
READ = 0x120089
DIRECTORY_READ = 0x1200A9
FULL = 0x1F01FF
# Child creation/cleanup does not require DELETE or attribute/EA writes on
# the fixed endpoint directory itself. Transport FILES receive explicit FA.
MODIFY_CHILDREN = 0x1200EF
MUTATE = 0xD0156
READ_CONTROL = 0x20000
DELETE = 0x10000
REPARSE = 0x400
DIRECTORY = 0x10
SECURITY_INFORMATION = 0x17  # owner/group/DACL/label, not privileged whole SACL
PROFILE_VERSION = 1
_HASH = re.compile(r"[0-9a-f]{64}")
_SID = re.compile(r"S-1-(?:[0-9]+-)*[0-9]+")
_STAGE = re.compile(r"[0-9a-f]{32}\.stage")


class ScienceCustodyNativeError(CustodyCommitIntegrityError):
    """Native identity, security, bounds or topology could not be proved."""


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScienceCustodyNativeError(message)


def _hash(value: str) -> None:
    _require(type(value) is str and _HASH.fullmatch(value) is not None,
             "Expected an exact lower-case SHA256 binding.")


def _sid(value: str) -> None:
    _require(type(value) is str and len(value) <= 184 and _SID.fullmatch(value) is not None,
             "Expected an explicit SID, not an account name.")


def _bound(value: int, maximum: int) -> int:
    _require(type(value) is int and 0 < value <= maximum, "Invalid finite native bound.")
    return value


def _absolute(value: str) -> str:
    _require(type(value) is str and value.isascii() and len(value) <= 240,
             "Root paths must be bounded explicit ASCII Windows paths.")
    p = PureWindowsPath(value)
    _require(bool(re.fullmatch(r"[A-Za-z]:", p.drive)) and p.is_absolute()
             and not value.startswith(("\\\\", "//")) and not any(
                 x in {".", ".."} or x.endswith((".", " ")) or ":" in x
                 for x in p.parts[1:]), "Alternate or nonabsolute root namespace.")
    _require("\x00" not in value and not any(x in value for x in "<>\"|?*"),
             "Invalid root path.")
    return str(p)


def _path_key(value: str | Path) -> str:
    return str(PureWindowsPath(str(value))).casefold()


def _io_path(value: Path) -> str:
    """Extended DOS spelling for long admitted paths, not a policy alias."""
    path = PureWindowsPath(str(value))
    if path.is_absolute() and re.fullmatch(r"[A-Za-z]:", path.drive):
        return "\\\\?\\" + str(path)
    # Only private primitive tests use relative paths. Every public backend
    # obtains its absolute path from the validated immutable policy.
    return str(path)


def _relative(value: str, *, empty: bool = False) -> tuple[str, ...]:
    if empty and value == "":
        return ()
    validate_relative_path(value)
    _require(value == value.lower(), "Case aliases are not admitted in custody paths.")
    return tuple(value.split("/"))


@dataclass(frozen=True)
class CustodyRootBinding:
    namespace: str
    path: str
    file_identity: tuple[int, int, int]
    owner_sid: str
    descriptor_sha256: str

    def __post_init__(self) -> None:
        _absolute(self.path)
        _sid(self.owner_sid)
        _hash(self.descriptor_sha256)
        _require(type(self.file_identity) is tuple and len(self.file_identity) == 3
                 and all(type(v) is int and 0 <= v <= 0xFFFFFFFF for v in self.file_identity),
                 "Missing exact volume/file identity.")


@dataclass(frozen=True)
class ScienceCustodyPolicy:
    source_root_identity: str
    science_sid: str
    writer_sid: str
    science_group_sids: tuple[str, ...]
    science_privilege_names: tuple[str, ...]
    science_integrity_sid: str
    object_integrity_sid: str
    roots: tuple[CustodyRootBinding, ...]
    ancestors: tuple[CustodyRootBinding, ...]
    max_artifact_bytes: int
    max_request_bytes: int
    max_history_entries: int
    max_pinned_directories: int
    max_mailbox_entries: int = 2
    science_enabled_group_sids: tuple[str, ...] = ()
    science_enabled_privilege_names: tuple[str, ...] = ()
    version: int = PROFILE_VERSION
    actor_profile: ScmRoleProfile | None = None

    def __post_init__(self) -> None:
        _hash(self.source_root_identity)
        for value in (self.science_sid, self.writer_sid, self.science_integrity_sid,
                      self.object_integrity_sid):
            _sid(value)
        _require(self.science_integrity_sid.startswith("S-1-16-")
                 and self.object_integrity_sid.startswith("S-1-16-"),
                 "Integrity bindings must be integrity SIDs.")
        _require(type(self.roots) is tuple and type(self.ancestors) is tuple
                 and all(type(x) is CustodyRootBinding for x in (*self.roots, *self.ancestors)),
                 "Policy root bindings must be immutable exact value objects.")
        _require(type(self.science_group_sids) is tuple
                 and type(self.science_privilege_names) is tuple
                 and type(self.science_enabled_group_sids) is tuple
                 and type(self.science_enabled_privilege_names) is tuple,
                 "Token bindings must be immutable tuples.")
        for sid in self.science_group_sids:
            _sid(sid)
        _require(len(set(self.science_group_sids)) == len(self.science_group_sids),
                 "Duplicate Science group binding.")
        _require(set(self.science_enabled_group_sids) <= set(self.science_group_sids)
                 and len(set(self.science_enabled_group_sids)) == len(self.science_enabled_group_sids)
                 and set(self.science_enabled_privilege_names) <= set(self.science_privilege_names)
                 and len(set(self.science_enabled_privilege_names)) == len(self.science_enabled_privilege_names),
                 "Enabled token bindings must be exact subsets of the available inventory.")
        _require(len(set(self.science_privilege_names)) == len(self.science_privilege_names)
                 and set(self.science_privilege_names) <= {"SeChangeNotifyPrivilege"},
                 "Science privilege authority exceeds the admitted read/transport profile.")
        _require(self.writer_sid not in self.science_authority_sids
                 and "S-1-5-18" not in self.science_authority_sids,
                 "Science overlaps a trusted Writer/SYSTEM authority.")
        _require(type(self.version) is int and self.version in {PROFILE_VERSION, mutable.VERSION},
                 "Unknown custody policy version.")
        if self.version == mutable.VERSION:
            _require(self.actor_profile is not None and self.writer_sid == mutable.WRITER
                     and self.object_integrity_sid == mutable.HIGH,
                     "Architecture B requires the admitted SCM actors and HIGH/NW policy.")
        if self.actor_profile is not None:
            _require(type(self.actor_profile) is ScmRoleProfile, "Unknown native actor profile.")
            self.actor_profile.__post_init__()
            _require(self.writer_sid == "S-1-5-19" and self.science_sid == service_sid(
                self.actor_profile.science.service_name), "Actor profile disagrees with custody principals.")
            _require(not any(s.startswith("S-1-5-5-") for s in self.science_group_sids),
                     "Volatile native logon identity must not enter the new stable custody policy.")
        _bound(self.max_artifact_bytes, 64 * 1024 * 1024)
        _bound(self.max_request_bytes, 64 * 1024)
        _bound(self.max_history_entries, 10_000_000)
        _bound(self.max_pinned_directories, 1_000_000)
        _require(type(self.max_mailbox_entries) is int and self.max_mailbox_entries == 2,
                 "The fixed orphan-recovery protocol requires exactly two staging entries.")
        _require(len(self.roots) == len(self.root_names)
                 and {x.namespace for x in self.roots} == self.root_names,
                 "Every exact versioned namespace binding is required.")
        if self.version == mutable.VERSION:
            state_root = str(PureWindowsPath(self.root("private").path).parent)
            _require(all(_path_key(x.path) == _path_key(mutable.namespace_path(state_root, x.namespace))
                         for x in self.roots), "Architecture-B namespace is not the fixed v2 topology.")
        root_paths = [_path_key(x.path) for x in self.roots]
        _require(len(set(root_paths)) == len(root_paths), "Root alias collision.")
        for a in root_paths:
            for b in root_paths:
                _require(a == b or not b.startswith(a.rstrip("\\") + "\\"),
                         "Custody role roots must be disjoint, not nested.")
        _require(all(x.owner_sid == self.writer_sid for x in self.roots),
                 "Fixed namespace roots must be Writer-account-owned.")
        expected = {_path_key(str(p)) for root in self.roots
                    for p in PureWindowsPath(root.path).parents}
        actual = [_path_key(x.path) for x in self.ancestors]
        _require(len(set(actual)) == len(actual) and set(actual) == expected,
                 "Every absolute ancestor through the drive root must be bound.")
        _require(len(self.ancestors) + len(self.roots) <= self.max_pinned_directories,
                 "Pinned-directory bound cannot hold the fixed topology.")
        _require(all(x.owner_sid not in self.science_authority_sids
                     for x in self.ancestors), "Science-owned ancestor is unsafe.")

    @property
    def root_names(self) -> frozenset[str]:
        return ROOT_NAMES | {"owner", "scratch"} if self.version == mutable.VERSION else ROOT_NAMES

    @property
    def profile(self) -> str:
        return mutable.PROFILE if self.version == mutable.VERSION else PROFILE

    @property
    def mutable_parent_path(self) -> str:
        _require(self.version == mutable.VERSION, "No v2 common parent in v1 policy.")
        return str(PureWindowsPath(self.root("owner").path).parent)

    @property
    def science_authority_sids(self) -> frozenset[str]:
        return frozenset((self.science_sid, "S-1-1-0", *self.science_group_sids))

    @property
    def policy_sha256(self) -> str:
        values = asdict(self)
        if self.actor_profile is None:
            values.pop("actor_profile")
        else:
            values["actor_profile"] = encode_profile(self.actor_profile)
        return _digest({"profile": self.profile, **values})

    def root(self, namespace: str) -> CustodyRootBinding:
        for item in self.roots:
            if item.namespace == namespace:
                return item
        raise ScienceCustodyNativeError("Unknown fixed custody namespace.")


@dataclass(frozen=True)
class CustodyRootEvidence:
    root: Path
    file_identity: tuple[int, int, int]
    owner_sid: str
    descriptor_sha256: str


@dataclass(frozen=True)
class _Security:
    owner: str
    sddl: str
    aces: tuple[tuple[int, int, int, str], ...]
    labels: tuple[tuple[int, int, str], ...]
    protected: bool
    group: str | None = None
    control: int | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.sddl.encode("ascii")).hexdigest()


def _expected_aces(policy: ScienceCustodyPolicy, kind: str, directory: bool):
    flags = 3 if directory else 0
    profile = getattr(policy, "actor_profile", None)
    if profile is not None:
        writer_role_sid = service_sid(profile.writer.service_name)
        if kind in {"transport", "derived"}:
            # OWNER RIGHTS suppresses implicit owner WRITE_DAC. Science still
            # owns its temporary files; Writer only verifies this handoff.
            access = MODIFY_CHILDREN if directory else FULL
            if kind == "derived":
                writer_reads = (((0, 2, 0x1200A1, policy.writer_sid),
                                 (0, 9, 0x120080, policy.writer_sid)) if directory
                                else ((0, 0, 0x120080, policy.writer_sid),))
            else:
                writer_reads = ((0, flags, DIRECTORY_READ if directory else READ, policy.writer_sid),)
            return ((1, flags, MUTATE, policy.writer_sid),
                    (0, flags, READ_CONTROL, "S-1-3-4"),
                    *writer_reads,
                    (0, flags, FULL, "S-1-5-18"),
                    (0, flags, access, policy.science_sid))
        values = [(0, flags, FULL, policy.writer_sid), (0, flags, FULL, writer_role_sid),
                  (0, flags, FULL, "S-1-5-18")]
        if kind != "private":
            values.append((0, flags, DIRECTORY_READ if directory else READ, policy.science_sid))
        return tuple(values)
    values = [(0, flags, FULL, policy.writer_sid), (0, flags, FULL, "S-1-5-18")]
    if kind != "private":
        access = (MODIFY_CHILDREN if directory else FULL) if kind == "transport" else (
            DIRECTORY_READ if directory else READ)
        values.append((0, flags, access, policy.science_sid))
    return tuple(values)


def creation_sddl(policy: ScienceCustodyPolicy, kind: str, *, directory: bool,
                  include_label: bool = False) -> str:
    """Deterministic template for already-authorized object creation/provisioning.

    This function only returns text. The backend never provisions fixed roots
    or changes an existing object's ACL or integrity label.
    """
    if getattr(policy, "version", 1) == mutable.VERSION:
        if kind in mutable.KINDS | {mutable.COMMON}:
            _require(directory, "Architecture-B children require NULL CreatorDescriptor.")
            return mutable.parent_sddl(policy.science_sid, kind)
        _require(kind in {"private", "trusted"}, "Legacy mutable descriptors are forbidden in v2.")
    _require(kind in {"private", "trusted", "transport"} or
             (kind == "derived" and getattr(policy, "actor_profile", None) is not None), "Unknown descriptor kind.")
    owner = policy.science_sid if kind in {"transport", "derived"} and not directory else policy.writer_sid
    aces = _expected_aces(policy, kind, directory)
    result = f"O:{owner}G:{owner}D:P" + "".join(
        f"({'D' if typ == 1 else 'A'};{''.join(text for bit, text in ((1, 'OI'), (2, 'CI'), (8, 'IO')) if flags & bit)};0x{mask:x};;;{sid})"
        for typ, flags, mask, sid in aces
    )
    # Runtime children inherit the already-verified parent label. Do not ask
    # CreateFile for whole-SACL authority or alter existing object labels.
    if include_label:
        result += f"S:(ML;{'OICI' if directory else ''};NW;;;{policy.object_integrity_sid})"
    return result


def _generic(mask: int) -> int:
    result = mask & 0x0FFFFFFF
    for bit, value in ((0x80000000, READ), (0x40000000, 0x120116),
                       (0x20000000, 0x1200A0), (0x10000000, FULL)):
        if mask & bit:
            result |= value
    return result


def _verify_security(policy: ScienceCustodyPolicy, sec: _Security, kind: str,
                     *, directory: bool) -> None:
    if getattr(policy, "version", 1) == mutable.VERSION and kind in mutable.KINDS | {mutable.COMMON}:
        _require(mutable.security_matches(sec, policy.science_sid, kind, directory=directory),
                 "Actual Architecture-B owner/group/DACL/control/integrity differs from exact policy.")
        return
    expected_owner = policy.science_sid if kind in {"transport", "derived"} and not directory else policy.writer_sid
    _require(sec.owner == expected_owner, "Actual opened object has the wrong owner.")
    _require(sec.protected, "Object DACL inheritance is not protected.")
    _require(sec.aces == _expected_aces(policy, kind, directory),
             "Actual opened object DACL differs from the exact role policy.")
    _require(len(sec.labels) == 1 and sec.labels[0][1:] == (1, policy.object_integrity_sid)
             and sec.labels[0][0] & ~0x10 == (3 if directory else 0),
             "Actual mandatory label differs from bound object policy.")


def _verify_ancestor(policy: ScienceCustodyPolicy, sec: _Security) -> None:
    _require(sec.owner not in policy.science_authority_sids, "Science controls an ancestor owner.")
    for ace_type, flags, mask, sid in sec.aces:
        _require(ace_type in {0, 1}, "Unsupported ancestor ACE prevents safe admission.")
        if ace_type == 0 and not flags & 8 and sid in policy.science_authority_sids:
            _require(not (_generic(mask) & MUTATE),
                     "Science has mutable authority over a replaceable ancestor.")


class _Native:
    """Small Win32 primitive layer. Instantiated only after policy validation."""
    def __init__(self) -> None:
        _require(os.name == "nt", "Native Science custody requires Windows; no fallback.")
        from ctypes import wintypes as w
        self.w = w
        self.k = storage._KERNEL32
        self.a = c.WinDLL("advapi32", use_last_error=True)
        self.bind(self.a, "GetSecurityInfo", [w.HANDLE, c.c_int, w.DWORD,
                  c.POINTER(c.c_void_p), c.POINTER(c.c_void_p), c.POINTER(c.c_void_p),
                  c.POINTER(c.c_void_p), c.POINTER(c.c_void_p)], w.DWORD)
        self.bind(self.a, "GetSecurityDescriptorDacl",
                  [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL)
        self.bind(self.a, "GetSecurityDescriptorSacl",
                  [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL)
        self.bind(self.a, "GetSecurityDescriptorControl",
                  [c.c_void_p, c.POINTER(w.WORD), c.POINTER(w.DWORD)], w.BOOL)
        self.bind(self.a, "GetSecurityDescriptorLength", [c.c_void_p], w.DWORD)
        self.bind(self.a, "GetAce", [c.c_void_p, w.DWORD, c.POINTER(c.c_void_p)], w.BOOL)
        self.bind(self.a, "ConvertSidToStringSidW",
                  [c.c_void_p, c.POINTER(w.LPWSTR)], w.BOOL)
        self.bind(self.a, "ConvertSecurityDescriptorToStringSecurityDescriptorW",
                  [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), c.POINTER(w.DWORD)], w.BOOL)
        self.bind(self.a, "ConvertStringSecurityDescriptorToSecurityDescriptorW",
                  [w.LPCWSTR, w.DWORD, c.POINTER(c.c_void_p), c.POINTER(w.DWORD)], w.BOOL)
        self.bind(self.k, "LocalFree", [c.c_void_p], c.c_void_p)
        self.bind(self.k, "CreateDirectoryW", [w.LPCWSTR, c.c_void_p], w.BOOL)
        self.bind(self.k, "SetFileInformationByHandle",
                  [w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL)
        self.bind(self.k, "GetCurrentProcess", [], w.HANDLE)
        self.bind(self.k, "GetCurrentThread", [], w.HANDLE)
        self.bind(self.a, "OpenProcessToken",
                  [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)], w.BOOL)
        self.bind(self.a, "OpenThreadToken",
                  [w.HANDLE, w.DWORD, w.BOOL, c.POINTER(w.HANDLE)], w.BOOL)
        self.bind(self.a, "GetTokenInformation",
                  [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL)
        self.bind(self.a, "LookupPrivilegeNameW",
                  [w.LPCWSTR, c.c_void_p, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL)
        self.nt = c.WinDLL("ntdll", use_last_error=True)
        self.bind(self.nt, "NtOpenFile", [c.POINTER(w.HANDLE), w.DWORD,
                  c.c_void_p, c.c_void_p, w.ULONG, w.ULONG], w.LONG)
        self.bind(self.nt, "RtlNtStatusToDosError", [w.LONG], w.ULONG)
        self._token_cache = None
        self._security_cache = {}

    @staticmethod
    def bind(lib, name, args, restype):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, restype
        return fn

    @staticmethod
    def checked(value, label):
        if not value:
            error = c.get_last_error()
            if error in {5, 1307, 1314, 1338}:
                raise ScienceCustodyNativeError(
                    f"{label}: required native authority/evidence failed (Win32 {error}).")
            raise storage._windows_error(label, error)
        return value

    def sid(self, ptr) -> str:
        text = self.w.LPWSTR()
        self.checked(self.a.ConvertSidToStringSidW(ptr, c.byref(text)), "Convert SID")
        try:
            return text.value
        finally:
            self.k.LocalFree(c.cast(text, c.c_void_p))

    def token(self) -> dict[str, object]:
        fingerprint = self.token_fingerprint()
        if self._token_cache is not None and self._token_cache[0] == fingerprint:
            return dict(self._token_cache[1])
        observed = self._read_token()
        # ModifiedId changes on every token modification, including A->B->A.
        # Cache only an inventory bracketed by matching native statistics.
        _require(all(observed.get(key) == value for key, value in fingerprint.items())
                 and self.token_fingerprint() == fingerprint,
                 "Native token changed while its inventory was being read.")
        self._token_cache = dict(fingerprint), dict(observed)
        return observed

    def _read_token(self) -> dict[str, object]:
        w = self.w
        token = w.HANDLE()
        c.set_last_error(0)
        thread = bool(self.a.OpenThreadToken(self.k.GetCurrentThread(), 8, True, c.byref(token)))
        if not thread:
            error = c.get_last_error()
            if error != 1008:
                raise storage._windows_error("OpenThreadToken", error)
            self.checked(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, c.byref(token)),
                         "OpenProcessToken")
        class SIDATTR(c.Structure):
            _fields_ = [("sid", c.c_void_p), ("attributes", w.DWORD)]
        class GROUPS(c.Structure):
            _fields_ = [("count", w.DWORD), ("entry", SIDATTR)]
        result = {"thread_token": thread}
        try:
            for name, kind in (("user", 1), ("owner", 4), ("groups", 2),
                               ("privileges", 3), ("integrity", 25),
                               ("token_type", 8), ("elevation", 20)):
                length = w.DWORD()
                self.a.GetTokenInformation(token, kind, None, 0, c.byref(length))
                _require(0 < length.value <= 128 * 1024, "Token query size is invalid.")
                buf = c.create_string_buffer(length.value)
                self.checked(self.a.GetTokenInformation(token, kind, buf, len(buf),
                                                       c.byref(length)), "GetTokenInformation")
                if name in {"token_type", "elevation"}:
                    result[name] = int.from_bytes(buf.raw[:length.value], "little")
                elif name in {"user", "owner", "integrity"}:
                    result[name] = self.sid(c.cast(buf, c.POINTER(c.c_void_p))[0])
                elif name == "groups":
                    count = int.from_bytes(buf.raw[:4], "little")
                    offset = GROUPS.entry.offset
                    _require(offset + count * c.sizeof(SIDATTR) <= len(buf),
                             "Token groups exceed native buffer.")
                    observed = tuple((self.sid(x.sid), int(x.attributes)) for x in (
                        SIDATTR.from_buffer(buf, offset + i * c.sizeof(SIDATTR))
                        for i in range(count)))
                    result["group_attributes"] = observed
                    # Disabled non-deny groups may be enabled by the token
                    # holder. Integrity SIDs are not discretionary group grants.
                    result[name] = tuple(sorted(sid for sid, attrs in observed
                                                if not attrs & (0x10 | 0x20)))
                    result["enabled_groups"] = tuple(sorted(sid for sid, attrs in observed
                                                if attrs & 4 and not attrs & (0x10 | 0x20)))
                else:
                    count = int.from_bytes(buf.raw[:4], "little")
                    _require(4 + count * 12 <= len(buf), "Token privileges exceed native buffer.")
                    names = []
                    enabled = []
                    attributes = []
                    for i in range(count):
                        offset = 4 + i * 12
                        attr = int.from_bytes(buf.raw[offset + 8:offset + 12], "little")
                        length = w.DWORD(256)
                        text = c.create_unicode_buffer(256)
                        self.checked(self.a.LookupPrivilegeNameW(
                            None, c.byref(buf, offset), text, c.byref(length)),
                            "LookupPrivilegeNameW")
                        names.append(text.value)
                        attributes.append((text.value, attr))
                        if attr & 2:
                            enabled.append(text.value)
                    result[name] = tuple(sorted(names))
                    result["enabled_privileges"] = tuple(sorted(enabled))
                    result["privilege_attributes"] = tuple(attributes)
            _extended_token(self, token, result)
            return result
        finally:
            self.checked(self.k.CloseHandle(token), "Close token handle")

    def token_fingerprint(self) -> dict[str, object]:
        """Recheck the effective token without rebuilding its admitted SID inventory."""
        w = self.w
        class LUID(c.Structure):
            _fields_ = [("low", w.DWORD), ("high", w.LONG)]
        class STATISTICS(c.Structure):
            _fields_ = [("token", LUID), ("authentication", LUID),
                        ("expiration", c.c_longlong), ("type", w.DWORD),
                        ("level", w.DWORD), ("charged", w.DWORD),
                        ("available", w.DWORD), ("groups", w.DWORD),
                        ("privileges", w.DWORD), ("modified", LUID)]
        token = w.HANDLE()
        c.set_last_error(0)
        thread = bool(self.a.OpenThreadToken(self.k.GetCurrentThread(), 8, True, c.byref(token)))
        if not thread:
            error = c.get_last_error()
            if error != 1008:
                raise storage._windows_error("OpenThreadToken", error)
            self.checked(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, c.byref(token)),
                         "OpenProcessToken")
        try:
            length = w.DWORD()
            self.a.GetTokenInformation(token, 10, None, 0, c.byref(length))
            _require(length.value == c.sizeof(STATISTICS), "Native token statistics size changed.")
            value = STATISTICS()
            self.checked(self.a.GetTokenInformation(token, 10, c.byref(value),
                                                    c.sizeof(value), c.byref(length)),
                         "GetTokenInformation(statistics)")
            _require(length.value == c.sizeof(STATISTICS), "Native token statistics size changed.")
            luid = lambda item: (item.low, item.high & 0xFFFFFFFF)
            return {"thread_token": thread, "token_id": luid(value.token),
                    "authentication_id": luid(value.authentication),
                    "modified_id": luid(value.modified), "token_type": value.type}
        finally:
            self.checked(self.k.CloseHandle(token), "Close token handle")

    def security(self, handle) -> _Security:
        w = self.w
        owner = c.c_void_p(); group = c.c_void_p(); dacl = c.c_void_p()
        sacl = c.c_void_p(); sd = c.c_void_p(); text = w.LPWSTR()
        error = self.a.GetSecurityInfo(handle.value, 1, SECURITY_INFORMATION,
                    c.byref(owner), c.byref(group), c.byref(dacl), c.byref(sacl), c.byref(sd))
        if error:
            if error in {5, 1307, 1314, 1338}:
                raise ScienceCustodyNativeError(
                    f"Native security evidence is unavailable (Win32 {error}).")
            raise storage._windows_error("GetSecurityInfo", error)
        def entries(acl):
            if not acl:
                raise ScienceCustodyNativeError("Null ACL is not an authority proof.")
            count = c.cast(acl.value + 4, c.POINTER(w.WORD)).contents.value
            values = []
            _require(count <= 4096, "Unbounded ACL.")
            for i in range(count):
                ptr = c.c_void_p()
                self.checked(self.a.GetAce(acl, i, c.byref(ptr)), "GetAce")
                header = c.string_at(ptr, 4)
                typ, flags = header[0], header[1]
                _require(typ in {0, 1, 0x11}, "Unsupported object/conditional ACE.")
                mask = c.cast(ptr.value + 4, c.POINTER(w.DWORD)).contents.value
                values.append((typ, flags, mask, self.sid(ptr.value + 8)))
            return tuple(values)
        try:
            control = w.WORD(); revision = w.DWORD()
            self.checked(self.a.GetSecurityDescriptorControl(sd, c.byref(control),
                                                           c.byref(revision)), "SD control")
            _require(bool(control.value & 0x8000), "Native descriptor is not self-relative.")
            size = self.a.GetSecurityDescriptorLength(sd)
            _require(0 < size <= 1024 * 1024, "Native descriptor size is invalid.")
            raw = c.string_at(sd, size)
            cached = self._security_cache.get(raw)
            if cached is not None:
                return cached
            self.checked(self.a.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                sd, 1, SECURITY_INFORMATION, c.byref(text), None), "Canonical SDDL")
            aces = entries(dacl)
            label_aces = entries(sacl) if sacl else ()
            _require(all(x[0] == 0x11 for x in label_aces), "Unexpected label information.")
            result = _Security(self.sid(owner), text.value, aces,
                               tuple((x[1], x[2], x[3]) for x in label_aces),
                               bool(control.value & 0x1000), self.sid(group), control.value)
            # Always query this handle's current descriptor. Reuse decoding,
            # never the query or object/path/security-policy validation.
            if size <= 65536:
                if len(self._security_cache) == 32:
                    self._security_cache.pop(next(iter(self._security_cache)))
                self._security_cache[raw] = result
            return result
        finally:
            if text:
                self.k.LocalFree(c.cast(text, c.c_void_p))
            self.k.LocalFree(sd)

    @contextmanager
    def security_attributes(self, sddl: str):
        w = self.w
        class SA(c.Structure):
            _fields_ = [("length", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]
        sd = c.c_void_p()
        self.checked(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, c.byref(sd), None), "Create security descriptor")
        try:
            yield c.byref(SA(c.sizeof(SA), sd, False))
        finally:
            self.k.LocalFree(sd)

    def _open_transport_read(self, path: Path, parent):
        w = self.w
        _require(not parent.closed and _path_key(path.parent) == _path_key(parent.path)
                 and len(_relative(path.name)) == 1, "Transport read differs from its pinned parent.")

        class NAME(c.Structure):
            _fields_ = [("length", w.USHORT), ("maximum", w.USHORT), ("buffer", w.LPWSTR)]
        class ATTRIBUTES(c.Structure):
            _fields_ = [("length", w.ULONG), ("root", w.HANDLE), ("name", c.POINTER(NAME)),
                        ("flags", w.ULONG), ("security", c.c_void_p), ("qos", c.c_void_p)]
        class IO_STATUS(c.Structure):
            _fields_ = [("status", c.c_void_p), ("information", c.c_size_t)]

        raw_length = len(path.name.encode("utf-16-le"))
        _require(raw_length <= 65532, "Transport leaf name exceeds native bound.")
        text = c.create_unicode_buffer(path.name)
        name = NAME(raw_length, raw_length + 2, c.cast(text, w.LPWSTR))
        attributes = ATTRIBUTES(c.sizeof(ATTRIBUTES), parent.value, c.pointer(name), 0x40, None, None)
        value = w.HANDLE()
        result = IO_STATUS()
        # Same read/share/no-follow/write-through contract as CreateFileW,
        # relative to the already-pinned directory. Preserve native failure
        # identity: CreateFileW conflates DELETE_PENDING with ACCESS_DENIED.
        status = self.nt.NtOpenFile(c.byref(value), 0x120081, c.byref(attributes),
                                   c.byref(result), 5, 0x200062) & 0xFFFFFFFF
        if status:
            if value.value not in (None, 0, storage._INVALID_HANDLE_VALUE):
                self.checked(self.k.CloseHandle(value), "Close unsuccessful transport read")
            if status == 0xC0000056:
                # No object was acquired. This is transport retirement, never
                # successful custody admission or permission to ignore denial.
                error = storage._windows_error("NtOpenFile: transport is delete-pending", 2)
                error.ntstatus = status
                raise error
            error = int(self.nt.RtlNtStatusToDosError(c.c_long(status)))
            if error in {5, 1307, 1314}:
                raise ScienceCustodyNativeError(
                    f"Transport read authority failed (NTSTATUS {status:#010x}, Win32 {error}).")
            raise storage._windows_error(f"NtOpenFile transport (NTSTATUS {status:#010x})", error)
        _require(value.value not in (None, 0, storage._INVALID_HANDLE_VALUE),
                 "Native transport read returned no handle.")
        return storage._WindowsHandle(int(value.value), path)

    def open(self, path: Path, *, directory: bool = False, access: int = READ,
             share: int = 1, disposition: int = 3, sddl: str | None = None,
             relative_to=None):
        if relative_to is not None:
            _require(not directory and access == 0x120081 and share == 5
                     and disposition == 3 and sddl is None,
                     "Relative transport open may only acquire the unchanged read contract.")
            return self._open_transport_read(path, relative_to)
        flags = 0x00200000 | (0x02000000 if directory else 0x08000000)
        if sddl is None:
            value = self.k.CreateFileW(_io_path(path), access, share, None, disposition, flags, None)
        else:
            with self.security_attributes(sddl) as sa:
                value = self.k.CreateFileW(_io_path(path), access, share, sa, disposition, flags, None)
        numeric = c.cast(value, c.c_void_p).value
        if numeric == storage._INVALID_HANDLE_VALUE:
            error = c.get_last_error()
            if error in {5, 1307, 1314}:
                raise ScienceCustodyNativeError(
                    f"Required create/owner authority failed (Win32 {error}).")
            raise storage._windows_error("CreateFileW", error)
        return storage._WindowsHandle(int(numeric), path)

    def mkdir(self, path: Path, sddl: str) -> None:
        with self.security_attributes(sddl) as sa:
            if not self.k.CreateDirectoryW(_io_path(path), sa):
                error = c.get_last_error()
                if error != 183:
                    raise storage._windows_error("CreateDirectoryW", error)

    def information(self, handle):
        return storage._handle_information(handle)

    def identity(self, handle) -> tuple[int, int, int]:
        return storage._file_identity(handle)

    def granted_access(self, handle) -> int:
        query = c.WinDLL("ntdll").NtQueryObject
        query.argtypes = [self.w.HANDLE, c.c_int, c.c_void_p, self.w.ULONG,
                          c.POINTER(self.w.ULONG)]
        query.restype = self.w.LONG
        info = c.create_string_buffer(56)
        returned = self.w.ULONG()
        status = query(handle.value, 0, info, len(info), c.byref(returned))
        _require(status == 0 and returned.value >= 8,
                 "Cannot prove granted native handle access.")
        return int.from_bytes(info.raw[4:8], "little")

    def reader_stream(self, handle):
        """Transfer the already-validated handle; never reopen by pathname."""
        import msvcrt
        fd = msvcrt.open_osfhandle(handle.value, os.O_BINARY | os.O_RDWR)
        handle.closed = True
        try:
            return os.fdopen(fd, "r+b")
        except BaseException:
            os.close(fd)
            raise

    def require_path(self, handle, path: Path) -> None:
        storage._require_final_path(handle, path)

    def read(self, handle, maximum: int) -> bytes:
        _bound(maximum, 64 * 1024 * 1024)
        before = self.information(handle)
        size = (int(before.nFileSizeHigh) << 32) | int(before.nFileSizeLow)
        _require(size <= maximum, "Opened object exceeds admitted byte bound.")
        self.checked(self.k.SetFilePointerEx(handle.value, 0, None, 0), "Seek bounded read")
        chunks = []
        total = 0
        while True:
            request = min(65536, maximum - total + 1)
            buf = c.create_string_buffer(request)
            count = self.w.DWORD()
            self.checked(self.k.ReadFile(handle.value, buf, request, c.byref(count), None),
                         "ReadFile")
            total += count.value
            _require(total <= maximum, "File grew beyond the bounded read.")
            if count.value:
                chunks.append(buf.raw[:count.value])
            if count.value < request:
                break
        after = self.information(handle)
        actual_size = (int(after.nFileSizeHigh) << 32) | int(after.nFileSizeLow)
        _require(total == size == actual_size, "Source size changed or read was incomplete.")
        return b"".join(chunks)

    def write(self, handle, raw: bytes) -> None:
        storage._write_handle(handle, raw)

    def rename(self, handle, target: Path) -> None:
        w = self.w
        class RENAME(c.Structure):
            _fields_ = [("replace", w.BOOL), ("root", w.HANDLE), ("length", w.DWORD),
                        ("name", w.WCHAR * 1)]
        raw = _io_path(target).encode("utf-16-le")
        # FILE_RENAME_INFO.FileName is a NUL-terminated WCHAR string even
        # though FileNameLength counts only payload bytes. Keep the terminator
        # inside the supplied buffer, without relying on neighboring memory.
        buf = c.create_string_buffer(RENAME.name.offset + len(raw) + c.sizeof(w.WCHAR))
        info = RENAME.from_buffer(buf)
        info.replace = False
        info.root = None
        info.length = len(raw)
        c.memmove(c.addressof(buf) + RENAME.name.offset, raw, len(raw))
        self.checked(self.k.SetFileInformationByHandle(handle.value, 3, buf, len(buf)),
                     "SetFileInformationByHandle(FileRenameInfo,no-replace)")
        handle.path = target

    def delete(self, handle) -> None:
        deleted = self.w.BOOL(True)
        self.checked(self.k.SetFileInformationByHandle(handle.value, 4, c.byref(deleted),
                                                      c.sizeof(deleted)),
                     "SetFileInformationByHandle(FileDispositionInfo)")


class WindowsScienceCustodyBackend:
    """One validated native role. Science never receives a trusted write method."""

    def __init__(self, policy: ScienceCustodyPolicy, *,
                 role: Literal["writer", "science"]) -> None:
        _require(type(policy) is ScienceCustodyPolicy, "Native immutable policy is mandatory.")
        policy.__post_init__()
        _require(role in {"writer", "science"}, "Unknown custody role.")
        self.policy = policy
        self.role = role
        self.policy_sha256 = policy.policy_sha256
        self._admitted_policy_sha256 = self.policy_sha256
        self._policy_value = _proof_value(policy)
        self.source_root_identity = policy.source_root_identity
        self.max_artifact_bytes = policy.max_artifact_bytes
        self.max_request_bytes = policy.max_request_bytes
        self._native = _Native()
        self._lock = threading.RLock()
        self._closed = False
        self._invalidated = False
        self._pins = {}
        self._fixed_keys = frozenset()
        self._read_scopes = {}
        self._fixed_access_cache = {}
        self._transaction_depth = 0
        self._scoped_reads = False
        self._lease = None
        self._root_evidence = {}
        self._admission = None
        self._actor_proof_cache = ActorProofCache()
        self._qualification_pin_timing = None
        try:
            self._actor()
            for item in sorted(policy.ancestors, key=lambda x: len(PureWindowsPath(x.path).parts)):
                self._pin_binding(item, ancestor=True)
            for item in policy.roots:
                if role == "science" and item.namespace == "private":
                    continue
                self._pin_binding(item, ancestor=False)
            self._fixed_keys = frozenset(self._pins)
            for item in policy.roots:
                path = PureWindowsPath(item.path)
                keys = {_path_key(part) for part in (path, *path.parents)}
                if _path_key(path) in self._fixed_keys:
                    self._read_scopes[item.namespace] = tuple(
                        key for key in self._fixed_keys if key in keys)
            self._acquire_lease()
            if role == "writer":
                self._directory("arrivals", ("ledger",), create=True)
                self._directory("custody", ("sessions",), create=True)
                self._release_dynamic_pins()
            else:
                self._prepare_reader_lock()
                self._recover_transport_scratch()
        except BaseException:
            self.close()
            raise

    @property
    def derived_root(self) -> Path:
        return self.namespace_root("derived")

    def namespace_root(self, alias: str) -> Path:
        return Path(self.policy.root(alias).path)

    def completion_hint(self, identity_sha256: str) -> bool | None:
        """Untrusted wakeup hint; only native reconciliation can admit completion."""
        _require(self.role == "science", "Only the Science reader waits for completion.")
        _hash(identity_sha256)
        path = self.namespace_root("receipts") / completion_path(identity_sha256)
        try:
            os.stat(_io_path(path), follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError:
            return None
        return True

    def _actor(self) -> None:
        observed = self._native.token()
        expected = self.policy.writer_sid if self.role == "writer" else self.policy.science_sid
        _require(observed["user"] == observed["owner"] == expected,
                 "Actual effective TokenUser/TokenOwner does not match native role.")
        if self.policy.actor_profile is not None:
            admission = observe_actor(self._native, self.role, self.policy.actor_profile, observed,
                                      check_images=self._admission is None,
                                      proof_cache=self._actor_proof_cache)
            if self._admission is None:
                self._admission = admission
            else:
                _require(admission_identity(admission) == admission_identity(self._admission),
                         "Native process/token/generation changed after role admission.")
        elif self.role == "writer":
            _require(not observed["thread_token"], "Finalizer must not run under impersonation.")
        else:
            _require(observed["groups"] == tuple(sorted(self.policy.science_group_sids))
                     and observed["privileges"] == tuple(sorted(self.policy.science_privilege_names))
                     and observed["enabled_groups"] == tuple(sorted(self.policy.science_enabled_group_sids))
                     and observed["enabled_privileges"] == tuple(sorted(self.policy.science_enabled_privilege_names))
                     and observed["integrity"] == self.policy.science_integrity_sid,
                     "Actual Science token groups/privileges/integrity differ from policy.")
        self.last_token_observation = observed

    def _actor_unchanged(self) -> None:
        fingerprint = getattr(self._native, "token_fingerprint", None)
        if fingerprint is None:
            self._actor()
            return
        observed = fingerprint()
        admitted = self.last_token_observation
        if any(observed.get(key) != admitted.get(key) for key in (
                "thread_token", "token_id", "authentication_id", "modified_id", "token_type")):
            self._actor()

    def _kind(self, namespace: str) -> str:
        if self.policy.version == mutable.VERSION and namespace in mutable.KINDS:
            return namespace
        if namespace == "derived" and self.policy.actor_profile is not None:
            return "derived"
        return "private" if namespace == "private" else (
            "transport" if namespace in TRANSPORT | {"derived"} else "trusted")

    def _validate_handle(self, handle, path: Path, *, kind: str, directory: bool):
        info = self._native.information(handle)
        _require(not info.dwFileAttributes & REPARSE, "Reparse object rejected before byte access.")
        _require(bool(info.dwFileAttributes & DIRECTORY) == directory,
                 "Opened object has the wrong file/directory type.")
        if not directory:
            _require(info.nNumberOfLinks == 1, "External hard-link alias is forbidden.")
        self._native.require_path(handle, path)
        sec = self._native.security(handle)
        if kind == "ancestor":
            if self.policy.actor_profile is None:
                _verify_ancestor(self.policy, sec)
            else:
                decisions = self._forbidden_access_decisions(path, sec)
                _require(not any(decisions.values()),
                         "Actual native actor can mutate a replaceable ancestor.")
        else:
            _verify_security(self.policy, sec, kind, directory=directory)
            if self.policy.actor_profile is not None and (
                    (self.role == "science" and kind in {"trusted", "private"}) or
                    (self.role == "writer" and kind in {"transport", "derived"} | mutable.KINDS | {mutable.COMMON})):
                decisions = self._forbidden_access_decisions(path, sec)
                _require(not any(decisions.values()), "Actual native actor has forbidden namespace authority.")
        return sec

    def _forbidden_access_decisions(self, path: Path, sec: _Security):
        # Fresh actor and descriptor checks precede this lookup. A token's
        # ModifiedId changes with its security context, while dynamic leaves
        # always take the uncached native AccessCheck path.
        observed = self.last_token_observation
        token_id = observed.get("token_id")
        modified_id = observed.get("modified_id")
        key = _path_key(path)
        if (key not in self._fixed_keys
                or type(token_id) is not tuple or len(token_id) != 2
                or type(modified_id) is not tuple or len(modified_id) != 2):
            return access_decisions(self._native, sec.sddl, MUTATION_RIGHTS)
        identity = (token_id, observed.get("authentication_id"), modified_id,
                    observed.get("thread_token"), observed.get("token_type"), sec)
        cached = self._fixed_access_cache.get(key)
        if cached is not None and cached[0] == identity:
            return cached[1]
        decisions = access_decisions(self._native, sec.sddl, MUTATION_RIGHTS)
        self._fixed_access_cache[key] = (identity, decisions)
        return decisions

    def _pin_binding(self, binding: CustodyRootBinding, *, ancestor: bool) -> None:
        path = Path(binding.path)
        key = _path_key(path)
        if key in self._pins:
            return
        try:
            handle = self._native.open(path, directory=True,
                access=mutable.PARENT_ACCESS if self.policy.version == mutable.VERSION else 0x1200A0, share=3)
        except OSError as exc:
            if exc.winerror in {2, 3, 5}:
                raise ScienceCustodyNativeError("Required bound root/ancestor is unavailable.") from exc
            raise
        try:
            kind = "ancestor" if ancestor else self._kind(binding.namespace)
            if (self.policy.version == mutable.VERSION
                    and key == _path_key(self.policy.mutable_parent_path)):
                kind = mutable.COMMON
            sec = self._validate_handle(handle, path, kind=kind, directory=True)
            identity = self._native.identity(handle)
            _require(identity == binding.file_identity and sec.owner == binding.owner_sid
                     and sec.digest == binding.descriptor_sha256,
                     "Pinned root/ancestor identity or descriptor drift.")
            self._pins[key] = (handle, kind, sec.digest, identity)
            if not ancestor:
                self._root_evidence[binding.namespace] = CustodyRootEvidence(
                    path, identity, sec.owner, sec.digest)
        except BaseException:
            handle.close()
            raise

    def _check_pins(self, *, keys=None, quick_actor=False) -> None:
        try:
            self._check_pins_current(keys=keys, quick_actor=quick_actor)
        except BaseException:
            self._invalidated = True
            if self.policy.version == mutable.VERSION:
                self.close()
            raise

    def _check_pins_current(self, *, keys=None, quick_actor=False) -> None:
        timing = self._qualification_pin_timing
        started = time.perf_counter_ns() if timing is not None else 0
        try:
            _require(not self._closed and not self._invalidated,
                     "Native custody backend is closed or invalidated.")
            _require(self.policy_sha256 == self._admitted_policy_sha256
                     and self._policy_value == _proof_value(self.policy), "Immutable policy drift.")
            actor_started = time.perf_counter_ns() if timing is not None else 0
            try:
                if quick_actor:
                    self._actor_unchanged()
                else:
                    self._actor()
            finally:
                if timing is not None:
                    timing["actor_ns"] += time.perf_counter_ns() - actor_started
            # Fixed topology is finite policy state. Revalidating all historical
            # subdirectories here would turn ordinary ingest into a history scan.
            for key in self._fixed_keys if keys is None else keys:
                root_started = time.perf_counter_ns() if timing is not None else 0
                try:
                    handle, kind, digest, identity = self._pins[key]
                    sec = self._validate_handle(handle, handle.path, kind=kind, directory=True)
                    _require(sec.digest == digest and self._native.identity(handle) == identity,
                             "Pinned topology/security changed during the process lifetime.")
                finally:
                    if timing is not None:
                        timing["fixed_root_ns"] += time.perf_counter_ns() - root_started
                        timing["fixed_root_validations"] += 1
        finally:
            if timing is not None:
                timing["pin_check_ns"] += time.perf_counter_ns() - started
                timing["pin_checks"] += 1
                timing["scoped_read_checks" if keys is not None else "full_checks"] += 1

    def enable_qualification_pin_timing(self) -> None:
        self._qualification_pin_timing = {
            "pin_checks": 0, "pin_check_ns": 0, "actor_ns": 0,
            "fixed_root_validations": 0, "fixed_root_ns": 0,
            "full_checks": 0, "scoped_read_checks": 0,
        }

    def reset_qualification_pin_timing(self) -> None:
        if self._qualification_pin_timing is not None:
            self.enable_qualification_pin_timing()

    def qualification_pin_timing(self) -> dict[str, int]:
        return dict(self._qualification_pin_timing or {})

    def _directory(self, namespace: str, parts: tuple[str, ...], *, create: bool = False):
        _require(namespace in self.policy.root_names and not (self.role == "science" and namespace == "private"),
                 "Namespace unavailable to this role.")
        path = self.namespace_root(namespace)
        current = self._pins[_path_key(path)][0]
        for part in parts:
            path = path / part
            key = _path_key(path)
            if key in self._pins:
                current = self._pins[key][0]
                _, kind, digest, identity = self._pins[key]
                sec = self._validate_handle(current, path, kind=kind, directory=True)
                _require(sec.digest == digest and self._native.identity(current) == identity,
                         "Pinned logical directory drift.")
                continue
            _require(len(self._pins) < self.policy.max_pinned_directories,
                     "Pinned topology exceeds its finite bound.")
            try:
                handle = self._native.open(path, directory=True, access=0x1200A0, share=3)
            except OSError as exc:
                if exc.winerror != 2 and exc.winerror != 3:
                    raise
                if not create:
                    return None
                _require(self.role == "writer" and namespace in TRUSTED,
                         "Science cannot create committed directories.")
                self._check_pins()
                self._native.mkdir(path, creation_sddl(self.policy, "trusted", directory=True))
                handle = self._native.open(path, directory=True, access=0x1200A0, share=3)
            try:
                sec = self._validate_handle(handle, path, kind=self._kind(namespace), directory=True)
                self._pins[key] = (handle, self._kind(namespace), sec.digest,
                                   self._native.identity(handle))
                current = handle
            except BaseException:
                handle.close()
                raise
        return current

    def _acquire_lease(self) -> None:
        is_b = self.policy.version == mutable.VERSION and self.role == "science"
        namespace = "private" if self.role == "writer" else ("owner" if is_b else "derived")
        name = ".writer-owner.lock" if self.role == "writer" else ".science-owner.lock"
        path = self.namespace_root(namespace) / name
        kind = self._kind(namespace)
        handle = self._native.open(path, access=mutable.OWNER_LEASE_ACCESS if is_b else 0xC0020000,
                    share=0, disposition=4,
                    sddl=None if is_b else creation_sddl(self.policy, kind, directory=False))
        try:
            self._validate_handle(handle, path, kind=kind, directory=False)
            if is_b:
                self._require_access(handle, mutable.OWNER_LEASE_ACCESS)
            self._lease = handle
            self.lease_identity = _digest({"policy": self.policy_sha256, "role": self.role,
                                          "object": self._native.identity(handle)})
            self.lease_name = name
        except BaseException:
            handle.close()
            raise

    def _prepare_reader_lock(self) -> None:
        """Prepare only the nonauthoritative mutable child before Reader opens it.

        V1 applies its explicit descriptor to a new file; V2 inherits from
        its fixed parent with NULL security attributes. Existing incompatible
        files are rejected, never repaired. This temporary handle closes
        before the Reader acquires its version-specific lock handle.
        """
        _require(self.role == "science" and self._lease is not None,
                 "Reader lock preparation requires the acquired Science lifetime lease.")
        path = self.derived_root / ".reader.lock"
        kind = self._kind("derived")
        is_b = self.policy.version == mutable.VERSION
        handle = self._native.open(path, access=mutable.READER_LOCK_ACCESS if is_b else READ,
                    share=3 if is_b else 1, disposition=4,
                    sddl=None if is_b else creation_sddl(self.policy, kind, directory=False))
        try:
            self._validate_handle(handle, path, kind=kind, directory=False)
            if is_b:
                self._require_access(handle, mutable.READER_LOCK_ACCESS)
        finally:
            handle.close()

    def _require_access(self, handle, expected: int) -> None:
        _require(self._native.granted_access(handle) == expected,
                 "Actual granted handle rights differ from the exact requested B mask.")

    def open_reader_lock(self):
        _require(self.policy.version == mutable.VERSION and self.role == "science"
                 and self._lease is not None, "B Reader acquisition requires its admitted Science owner.")
        with self.transaction():
            path = self.derived_root / ".reader.lock"
            self._check_pins()
            handle = self._native.open(path, access=mutable.READER_LOCK_ACCESS,
                                       share=3, disposition=4, sddl=None)
            try:
                self._validate_handle(handle, path, kind="derived", directory=False)
                self._require_access(handle, mutable.READER_LOCK_ACCESS)
                self._check_pins()
                return self._native.reader_stream(handle)
            finally:
                handle.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            if self._transaction_depth == 0:
                self._check_pins()
                self._scoped_reads = False
            else:
                # Inner protocol operations share the outer lock and lifetime.
                # Reads check their path scope; effects check all pins directly.
                self._scoped_reads = True
            self._transaction_depth += 1
            try:
                yield
                _require(not self._closed and not self._invalidated,
                         "Native custody backend closed or invalidated during operation.")
                if self._transaction_depth == 1 and self._scoped_reads:
                    self._check_pins()
            finally:
                self._transaction_depth -= 1
                if self._transaction_depth == 0:
                    self._scoped_reads = False
                    self._release_dynamic_pins()

    @contextmanager
    def _read_scope(self, namespace: str) -> Iterator[None]:
        _require(namespace in self._read_scopes, "Read namespace is not admitted.")
        with self._lock:
            if self._transaction_depth:
                self._check_pins(keys=self._read_scopes[namespace], quick_actor=True)
                self._scoped_reads = True
            else:
                self._check_pins()
            self._transaction_depth += 1
            try:
                yield
                _require(not self._closed and not self._invalidated,
                         "Native custody backend closed or invalidated during read.")
                if self._transaction_depth == 1:
                    self._check_pins()
            finally:
                self._transaction_depth -= 1
                if self._transaction_depth == 0:
                    self._scoped_reads = False
                    self._release_dynamic_pins()

    def _release_dynamic_pins(self) -> None:
        for key in reversed(tuple(self._pins)):
            if key not in self._fixed_keys:
                self._pins.pop(key)[0].close()

    @property
    def security_contract_evidence(self) -> dict[str, object]:
        with self.transaction():
            return {"profile": self.policy.profile, "policy_sha256": self.policy_sha256,
                    "source_root_identity": self.source_root_identity,
                    "role": self.role, "token": dict(self.last_token_observation),
                    "native_role_admission": self._admission,
                    "root_evidence": dict(self._root_evidence),
                    "fixed_ancestor_count": len(self.policy.ancestors),
                    "exact_owner_dacl_label_policy_verified": True,
                    "runtime_destructive_probes": False,
                    "actual_scm_qualification": False}

    def validate_readonly_roots(self) -> dict[str, CustodyRootEvidence]:
        with self.transaction():
            return {key: self._root_evidence[key] for key in TRUSTED}

    def validate_directory(self, alias: str, relative: str = "") -> bool:
        _require(alias in TRUSTED, "Only trusted directories are exposed for read-only inspection.")
        parts = _relative(relative, empty=True)
        with self._read_scope(alias):
            return self._directory(alias, parts) is not None

    def _snapshot(self, handle, path: Path, kind: str, maximum: int) -> CustodyObjectEvidence:
        sec = self._validate_handle(handle, path, kind=kind, directory=False)
        before = self._native.identity(handle)
        raw = self._native.read(handle, maximum)
        after_sec = self._validate_handle(handle, path, kind=kind, directory=False)
        _require(before == self._native.identity(handle) and sec == after_sec,
                 "Object identity/security changed while pinned for read.")
        return CustodyObjectEvidence(raw, before, sec.owner, sec.digest)

    def _namespace_byte_bound(self, namespace: str) -> int:
        # Internal claim/receipt encoding has the protocol's fixed ceiling;
        # a configured wire-request cap must not shrink that distinct format.
        if namespace in {"claims", "receipts"}:
            return PROTOCOL_METADATA_BYTES
        return self.max_request_bytes if namespace == "requests" else self.max_artifact_bytes

    def _handoff_snapshot(self, handle, volume: int, maximum: int) -> CustodyObjectEvidence:
        """Snapshot untrusted input; its mutable DACL is provenance, not authority.

        _read opens the exact filename under a pinned non-reparse namespace.
        From here onward only this handle supplies identity and bytes, including
        after a peer renames the file or replaces its former directory entry.
        """
        def identity(*, acquired: bool):
            info = self._native.information(handle)
            _require(not info.dwFileAttributes & (REPARSE | DIRECTORY),
                     "Handoff must be an ordinary non-reparse file.")
            # The acquired handle can outlive Science's exact-object transport
            # retirement. Zero links after the read is not an alias; two are.
            allowed_links = (1,) if acquired else (0, 1)
            _require(info.nNumberOfLinks in allowed_links,
                     f"Handoff hard-link alias rejected (links={info.nNumberOfLinks}).")
            value = self._native.identity(handle)
            _require(value[0] == volume, "Handoff volume differs from its pinned namespace.")
            return value

        before = identity(acquired=True)
        security = self._native.security(handle)
        raw = self._native.read(handle, maximum)
        _require(identity(acquired=False) == before, "Acquired handoff object identity changed.")
        return CustodyObjectEvidence(raw, before, security.owner, security.digest)

    def _read(self, namespace: str, relative: str, maximum: int, *, missing: bool):
        _bound(maximum, self._namespace_byte_bound(namespace))
        parts = _relative(relative)
        parent = self._directory(namespace, parts[:-1])
        if parent is None:
            if missing:
                return None
            raise FileNotFoundError("Required bound transport parent is absent.")
        path = parent.path / parts[-1]
        handoff = (self.role == "writer" and self.policy.actor_profile is not None
                   and namespace in TRANSPORT)
        try:
            # Trusted claim/receipt bytes are fixed before rename; the Writer
            # may still hold its write/delete handle for flush and readback.
            # Completion remains the separate durability gate for acceptance.
            narrow = self.policy.version == mutable.VERSION and namespace in TRANSPORT
            handle = self._native.open(path, access=0x120081 if handoff or narrow else READ,
                                       share=5 if handoff else (7 if namespace in {"claims", "receipts"} else 1),
                                       relative_to=parent if handoff else None)
        except OSError as exc:
            if missing and exc.winerror == 2:
                return None
            raise
        try:
            if handoff:
                # Ancestors and this fixed parent are already pinned by the
                # transaction; OPEN_REPARSE_POINT and the handle checks below
                # reject leaf redirects. A post-open pathname check would race
                # legitimate renames of the object we have already acquired.
                return self._handoff_snapshot(handle, self.policy.root(namespace).file_identity[0], maximum)
            return self._snapshot(handle, path, self._kind(namespace), maximum)
        finally:
            handle.close()

    def read_staged(self, name: str, *, maximum: int) -> CustodyObjectEvidence:
        _require(_STAGE.fullmatch(name) is not None, "Staging name must bind one generation.")
        with self._read_scope("staging"):
            return self._read("staging", name, maximum, missing=False)

    def read_request(self, name: str, *, maximum: int) -> CustodyObjectEvidence:
        _require(name == "request.json", "Only the fixed request slot is admitted.")
        with self._read_scope("requests"):
            return self._read("requests", name, maximum, missing=False)

    def read_trusted(self, namespace: str, relative: str, *,
                     maximum: int) -> CustodyObjectEvidence | None:
        _require(namespace in TRUSTED, "Unknown trusted namespace.")
        with self._read_scope(namespace):
            return self._read(namespace, relative, maximum, missing=True)

    def _publish_copy(self, namespace: str, relative: str, raw: bytes, *, transport: bool,
                      completion: bool = False):
        self._check_pins()
        parts = _relative(relative)
        parent = self._directory(namespace, parts[:-1], create=not transport)
        _require(parent is not None, "Bound publish parent is absent.")
        target = parent.path / parts[-1]
        is_b = transport and self.policy.version == mutable.VERSION
        kind = ("scratch" if is_b else "transport") if transport else "trusted"
        private_namespace = ("scratch" if is_b else "derived") if transport else "private"
        if transport:
            self._recover_transport_scratch()
            temp_name = ".custody-transport.tmp"
        else:
            # One deterministic private object for this destination and byte
            # identity; repeated interruptions do not accumulate random copies.
            temp_name = _digest({"policy": self.policy_sha256, "namespace": namespace,
                                 "relative": relative, "sha256": hashlib.sha256(raw).hexdigest()}) + ".tmp"
        temp = self.namespace_root(private_namespace) / temp_name
        try:
            handle = self._native.open(temp, access=mutable.TRANSPORT_ACCESS if is_b else 0xC0030000,
                share=1, disposition=1, sddl=None if is_b else creation_sddl(self.policy, kind, directory=False))
        except OSError as exc:
            if transport or exc.winerror not in {80, 183}:
                raise
            handle = self._native.open(temp, access=0xC0030000, share=1)
            try:
                self._validate_handle(handle, temp, kind=kind, directory=False)
                # This is an unpublished Writer-owned serialization copy, not a
                # final/claim/receipt or Science staging object. The protocol
                # independently supplied and checked raw again before this call.
                self._native.checked(self._native.k.SetFilePointerEx(
                    handle.value, 0, None, 0), "Seek incomplete private copy")
                self._native.checked(self._native.k.SetEndOfFile(handle.value),
                                     "Reset unpublished private copy")
            except BaseException:
                handle.close()
                raise
        try:
            self._validate_handle(handle, temp, kind=kind, directory=False)
            if is_b:
                self._require_access(handle, mutable.TRANSPORT_ACCESS)
            self._native.write(handle, raw)
            written = self._snapshot(handle, temp, kind, max(1, len(raw)))
            _require(written.raw == raw, "Private copy differs from supplied immutable bytes.")
            # Never link or move an untrusted staging object. Only this freshly
            # created current-role object can reach the native rename operation.
            try:
                self._check_pins()
                self._native.rename(handle, target)
            except OSError as exc:
                if exc.winerror not in {80, 183}:
                    raise
                if transport:
                    raise ScienceCustodyNativeError("Mutable slot is occupied; never overwrite.")
                existing = self._read(namespace, relative, max(1, len(raw)), missing=False)
                _require(existing.raw == raw, "Write-once target conflicts.")
                self._check_pins()
                self._native.delete(handle)
                if not completion:
                    self.ensure_durable(namespace, relative, existing)
                return False, existing
            if not completion:
                self._native.checked(self._native.k.FlushFileBuffers(handle.value),
                                     "Flush committed object")
            if is_b:
                self._check_pins()
            result = self._snapshot(handle, target, self._kind(namespace) if is_b else kind, max(1, len(raw)))
            _require(result.raw == raw and result.file_identity == written.file_identity,
                     "Published object identity/bytes changed.")
            return True, result
        finally:
            # Preserve private partials on interruption; never delete by mutable name.
            handle.close()

    def _recover_transport_scratch(self) -> None:
        """Discard only the fixed nonauthoritative unpublished serialization."""
        _require(self.role == "science", "Only Science owns transport scratch recovery.")
        is_b = self.policy.version == mutable.VERSION
        path = (self.namespace_root("scratch") if is_b else self.derived_root) / ".custody-transport.tmp"
        try:
            handle = self._native.open(path, access=mutable.RECOVERY_ACCESS if is_b else READ | DELETE, share=1)
        except OSError as exc:
            if exc.winerror == 2:
                return
            raise
        try:
            self._validate_handle(handle, path, kind="scratch" if is_b else "transport", directory=False)
            if is_b:
                self._require_access(handle, mutable.RECOVERY_ACCESS)
            # No admissible request can reference this fixed derived-root name.
            # Atomic rename uses no second hard link; a completed publication
            # therefore cannot leave a scratch alias behind.
            self._check_pins()
            self._native.delete(handle)
        finally:
            handle.close()

    def create_trusted(self, namespace: str, relative: str,
                       raw: bytes) -> tuple[bool, CustodyObjectEvidence]:
        _require(self.role == "writer" and namespace in TRUSTED,
                 "Only the native Writer role creates trusted objects.")
        _require(type(raw) is bytes and len(raw) <= self._namespace_byte_bound(namespace),
                 "Trusted payload exceeds its immutable bound.")
        _require(not (namespace == "receipts" and relative.endswith(".complete.json")),
                 "Completion requires the separately ordered announcement path.")
        with self.transaction():
            return self._publish_copy(namespace, relative, raw, transport=False)

    def ensure_durable(self, namespace: str, relative: str, expected: CustodyObjectEvidence) -> None:
        _require(self.role == "writer" and namespace in TRUSTED,
                 "Only Writer may establish trusted-object durability.")
        _require(type(expected) is CustodyObjectEvidence
                 and len(expected.raw) <= self._namespace_byte_bound(namespace),
                 "Durability target evidence is invalid or unbounded.")
        with self.transaction():
            parts = _relative(relative)
            parent = self._directory(namespace, parts[:-1], create=False)
            _require(parent is not None, "Durability target parent is absent.")
            path = parent.path / parts[-1]
            handle = self._native.open(path, access=READ | 0x40000000, share=1)
            try:
                before = self._snapshot(handle, path, "trusted", max(1, len(expected.raw)))
                _require(before == expected, "Durability target no longer matches its exact object.")
                self._check_pins()
                self._native.checked(self._native.k.FlushFileBuffers(handle.value),
                                     "Flush existing committed object")
                after = self._snapshot(handle, path, "trusted", max(1, len(expected.raw)))
                _require(after == before, "Durability target changed across its barrier.")
            finally:
                handle.close()

    def publish_completion(self, relative: str, raw: bytes) -> tuple[bool, CustodyObjectEvidence]:
        _require(self.role == "writer", "Only Writer may announce completion.")
        _require(re.fullmatch(r"([0-9a-f]{2})/([0-9a-f]{64})\.complete\.json", relative) is not None
                 and relative[:2] == relative[3:5], "Invalid completion namespace.")
        _require(type(raw) is bytes and len(raw) <= PROTOCOL_METADATA_BYTES,
                 "Completion exceeds its metadata bound.")
        with self.transaction():
            # Prerequisite barriers have already completed in the finalizer.
            # This replayable observation adds no fourth post-visible duty.
            return self._publish_copy("receipts", relative, raw, transport=False, completion=True)

    def bounded_names(self, namespace: str, limit: int) -> tuple[str, ...]:
        _require(namespace in TRANSPORT, "Only mutable transport is bounded-enumerated.")
        _bound(limit, self.policy.max_mailbox_entries + 1)
        with self._read_scope(namespace):
            values = []
            with os.scandir(self.namespace_root(namespace)) as entries:
                for entry in entries:
                    values.append(entry.name)
                    if len(values) == limit:
                        break
            return tuple(values)

    def create_transport(self, namespace: str, name: str, raw: bytes) -> CustodyObjectEvidence:
        _require(self.role == "science" and namespace in TRANSPORT,
                 "Only Science creates mutable transport.")
        _require((namespace == "requests" and name == "request.json") or
                 (namespace == "staging" and _STAGE.fullmatch(name) is not None),
                 "Transport name is outside fixed/generation slots.")
        maximum = self._namespace_byte_bound(namespace)
        _require(type(raw) is bytes and len(raw) <= maximum, "Transport byte bound exceeded.")
        with self.transaction():
            return self._publish_copy(namespace, name, raw, transport=True)[1]

    def delete_transport(self, namespace: str, name: str, *,
                         expected_identity: tuple[int, int, int],
                         expected_sha256: str) -> bool:
        _require(self.role == "science" and namespace in TRANSPORT,
                 "Only Science may clean up its transport.")
        _hash(expected_sha256)
        _require((namespace == "requests" and name == "request.json") or
                 (namespace == "staging" and _STAGE.fullmatch(name) is not None),
                 "Cleanup name is outside admitted generation slots.")
        _require(type(expected_identity) is tuple and len(expected_identity) == 3
                 and all(type(x) is int and 0 <= x <= 0xFFFFFFFF for x in expected_identity),
                 "Cleanup requires exact native identity.")
        maximum = self._namespace_byte_bound(namespace)
        with self.transaction():
            path = self.namespace_root(namespace) / name
            is_b = self.policy.version == mutable.VERSION
            try:
                handle = self._native.open(path, access=mutable.RECOVERY_ACCESS if is_b else READ | DELETE, share=1)
            except OSError as exc:
                if exc.winerror == 2:
                    return False
                raise
            try:
                if is_b:
                    self._require_access(handle, mutable.RECOVERY_ACCESS)
                observed = self._snapshot(handle, path, self._kind(namespace) if is_b else "transport", maximum)
                if observed.file_identity != expected_identity or hashlib.sha256(
                        observed.raw).hexdigest() != expected_sha256:
                    raise CustodyCommitConflict(
                        "Transport generation/object changed; preserve it and block acknowledgment.")
                # FileDispositionInfo deletes this exact opened object. No
                # path-based unlink/reopen exists after generation/hash checks.
                self._check_pins()
                self._native.delete(handle)
                return True
            finally:
                handle.close()

    def iter_trusted(self, alias: str, relative: str = "", *, suffix: str) -> tuple[Path, ...]:
        """Explicit bounded startup/history audit; never called by commit/retry."""
        _require(alias in TRUSTED and type(suffix) is str and len(suffix) <= 128
                 and "/" not in suffix and "\\" not in suffix, "Invalid history audit request.")
        parts = _relative(relative, empty=True)
        with self._read_scope(alias):
            initial = self._directory(alias, parts)
            if initial is None:
                return ()
            result = []
            pending = [(initial, parts)]
            count = 0
            while pending:
                directory, current = pending.pop()
                with os.scandir(directory.path) as entries:
                    for entry in entries:
                        count += 1
                        _require(count <= self.policy.max_history_entries,
                                 "Explicit history audit exceeds configured bound.")
                        child = _relative(entry.name)
                        _require(len(child) == 1, "Unexpected history name.")
                        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
                        _require(not attrs & REPARSE, "History contains a reparse entry.")
                        next_parts = (*current, entry.name)
                        if attrs & DIRECTORY:
                            opened = self._directory(alias, next_parts)
                            _require(opened is not None, "History directory disappeared.")
                            pending.append((opened, next_parts))
                        else:
                            self._read(alias, "/".join(next_parts),
                                       self._namespace_byte_bound(alias), missing=False)
                            if entry.name.endswith(suffix):
                                result.append(self.namespace_root(alias).joinpath(*next_parts))
            return tuple(sorted(result))

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._closed = True
        self._fixed_access_cache.clear()
        errors = []
        if self._lease is not None:
            try:
                self._lease.close()
            except Exception as exc:
                errors.append(exc)
            self._lease = None
        for handle, *_ in reversed(tuple(self._pins.values())):
            try:
                handle.close()
            except Exception as exc:
                errors.append(exc)
        self._pins.clear()
        if errors:
            raise ScienceCustodyNativeError("Native handles did not close cleanly.") from errors[0]


def open_science_custody_backend(policy: ScienceCustodyPolicy | None, *,
                                role: Literal["writer", "science"]):
    if policy is None:
        return None
    return WindowsScienceCustodyBackend(policy, role=role)


class _WriterChannel:
    def __init__(self, backend, mailbox):
        self._backend = backend
        self._mailbox = mailbox

    def poll_once(self):
        return self._mailbox.poll_once(new_work_only=True)

    def close(self):
        self._mailbox.close()


def open_science_custody_writer(policy: ScienceCustodyPolicy, *, trace_hook=None):
    """Production Writer entry point: never accepts a fake/injected backend."""
    _require(type(policy) is ScienceCustodyPolicy, "Explicit immutable Writer policy required.")
    from momentum_hunter.science_custody_commit import ScienceCustodyFinalizer
    from momentum_hunter.science_custody_mailbox import ScienceCustodyMailboxWriter
    backend = WindowsScienceCustodyBackend(policy, role="writer")
    try:
        return _WriterChannel(backend, ScienceCustodyMailboxWriter(
            ScienceCustodyFinalizer(backend, trace_hook=trace_hook), mailbox_backend=backend))
    except BaseException:
        backend.close()
        raise
