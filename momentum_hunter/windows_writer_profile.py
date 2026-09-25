"""Read-only native admission for the existing SCM Writer, not a launcher.

The service owner provisions a reviewed profile before activation. This module
never adjusts tokens, DACLs, service configuration or privileges. LOCAL SERVICE
remains the trusted finalizer account; this is not per-executable custody WORM.
"""
from __future__ import annotations

import ctypes as c
from contextlib import ExitStack
from dataclasses import asdict, dataclass, fields, is_dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys
import threading
import uuid


PROFILE = "bounded-existing-scm-writer-v1"
LOCAL_SERVICE = "S-1-5-19"
WORLD = "S-1-1-0"
WRITE_RESTRICTED = "S-1-5-33"
QUALIFIED_WRITER = "a7-qualified-high-scm-writer-v1"
HIGH_INTEGRITY = "S-1-16-12288"
WRITER_BASE_GROUPS = frozenset({
    WORLD, WRITE_RESTRICTED, "S-1-5-6", "S-1-5-11", "S-1-5-32-545",
    "S-1-2-0", "S-1-2-1", "S-1-5-15",
})
HASH = re.compile(r"[0-9a-f]{64}")
SERVICE_NAME = re.compile(r"MomentumHunterContinuous-qual-[a-z0-9][a-z0-9-]{0,31}-(Writer|Science)")
MUTATION_RIGHTS = (2, 4, 16, 64, 256, 65536, 262144, 524288)
FILE_RIGHTS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 65536, 131072, 262144, 524288, 1048576)
SERVICE_CONTROL_RIGHTS = (2, 16, 32, 64, 256, 65536, 262144, 524288)
# All fixed roots stay bound. Dynamic publications are not a durable process
# security invariant; untrusted handoff acquisition is a separate gate.
TRUSTED_WRITER_DYNAMIC_ROOTS = frozenset({"writer_evidence", "writer_logs", "writer_generation"})
MUTABLE_PEER_INPUT_ROOTS = frozenset({
    "science_generation", "science_derived", "runtime_generation", "runtime_state", "producer_publication",
})
DYNAMIC_RESOURCE_ROOTS = TRUSTED_WRITER_DYNAMIC_ROOTS | MUTABLE_PEER_INPUT_ROOTS


class WriterProfileError(RuntimeError):
    def __str__(self):
        message = super().__str__()
        diagnostic = getattr(self, "token_diagnostic", None)
        if diagnostic is not None:
            message += " TOKEN_CLASS_REJECTION=" + json.dumps(
                diagnostic, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return message


def require(condition, message):
    if not condition:
        raise WriterProfileError(message)


def service_sid(name: str) -> str:
    require(type(name) is str and SERVICE_NAME.fullmatch(name), "Unbound qualification service name.")
    raw = hashlib.sha1(name.upper().encode("utf-16-le")).digest()
    return "S-1-5-80-" + "-".join(str(int.from_bytes(raw[i:i + 4], "little")) for i in range(0, 20, 4))


def absolute_path(value):
    require(type(value) is str and value.isascii() and 0 < len(value) <= 240, "Invalid profile path.")
    path = PureWindowsPath(value)
    require(not any(ch in value for ch in '\x00<>"|?*')
            and path.is_absolute() and re.fullmatch(r"[A-Za-z]:", path.drive)
            and not value.startswith(("\\\\", "//")) and not any(
                part in {".", ".."} or part.endswith((".", " ")) or ":" in part
                for part in path.parts[1:]), "Alternate profile namespace.")
    return path


@dataclass(frozen=True)
class QualifiedWriterTokenContract:
    """Reviewed configuration, never learned from the actor being admitted.

    The evidence digest is a provenance reference, not admission authority.
    Actual SCM, generation, image and effective-access gates remain mandatory.
    """
    stable_group_sids: tuple[str, ...]
    authority_evidence_sha256: str
    contract: str = QUALIFIED_WRITER

    def __post_init__(self):
        require(self.contract == QUALIFIED_WRITER, "Unknown qualified Writer contract.")
        require(type(self.authority_evidence_sha256) is str
                and HASH.fullmatch(self.authority_evidence_sha256), "Qualified authority evidence identity missing.")
        require(type(self.stable_group_sids) is tuple and 8 <= len(self.stable_group_sids) <= 64
                and all(type(s) is str for s in self.stable_group_sids), "Bounded immutable Writer group inventory required.")
        require(tuple(sorted(set(self.stable_group_sids))) == self.stable_group_sids
                and WRITER_BASE_GROUPS <= set(self.stable_group_sids), "Exact canonical Writer baseline groups required.")
        for sid in self.stable_group_sids:
            # This constrains binding syntax; admission still requires exact
            # membership in the separately reviewed inventory, never a prefix.
            require(sid in WRITER_BASE_GROUPS or (
                re.fullmatch(r"S-1-5-32-(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*)){7}", sid)
                and all(int(part) <= 0xFFFFFFFF for part in sid.split("-")[4:])),
                "Unreviewed stable Writer group kind.")


@dataclass(frozen=True)
class ScmActorBinding:
    service_name: str
    host_path: str
    host_sha256: str
    python_path: str
    python_sha256: str
    generation_root: str
    integrity_sid: str
    writer_token_contract: QualifiedWriterTokenContract | None = None

    def __post_init__(self):
        service_sid(self.service_name)
        for value in (self.host_path, self.python_path, self.generation_root):
            absolute_path(value)
        require(all(type(v) is str and HASH.fullmatch(v) for v in (self.host_sha256, self.python_sha256)),
                "Exact executable hashes required.")
        require(self.integrity_sid in {"S-1-16-12288", "S-1-16-16384"}, "Unreviewed service integrity class.")
        if self.writer_token_contract is not None:
            require(type(self.writer_token_contract) is QualifiedWriterTokenContract
                    and self.service_name.endswith("-Writer") and self.integrity_sid == HIGH_INTEGRITY,
                    "Qualified contract is only for the proven HIGH Writer class.")
            self.writer_token_contract.__post_init__()


@dataclass(frozen=True)
class WriterResourceBinding:
    name: str
    path: str
    directory: bool
    file_identity: tuple[int, int, int]
    descriptor_sha256: str

    def __post_init__(self):
        require(self.name in RESOURCE_RULES and type(self.directory) is bool, "Unknown Writer support resource.")
        absolute_path(self.path)
        require(type(self.file_identity) is tuple and len(self.file_identity) == 3
                and all(type(v) is int and 0 <= v <= 0xFFFFFFFF for v in self.file_identity), "Missing support file identity.")
        require(type(self.descriptor_sha256) is str and HASH.fullmatch(self.descriptor_sha256), "Missing exact support descriptor.")
        require(self.directory == (self.name not in {"configuration", "writer_key"}), "Support resource type differs.")


# Required and forbidden individual rights, not a claim that generic masks
# attenuate every object type. READ_CONTROL is the explicit inspection minimum.
_READ = (1, 8, 32, 128, 131072, 1048576)
_META = (1, 32, 128, 131072, 1048576)
_MODIFY = (1, 2, 4, 8, 16, 32, 128, 256, 65536, 131072, 1048576)
RESOURCE_RULES = {
    **{name: (_READ, MUTATION_RIGHTS) for name in (
        "runtime_source", "host_image_root", "python_root", "python_base", "configuration", "writer_key",
        "science_generation", "runtime_generation")},
    **{name: (_MODIFY, (262144, 524288)) for name in (
        "writer_evidence", "writer_logs", "writer_generation")},
    **{name: (_META, (*MUTATION_RIGHTS, 8)) for name in (
        "configuration_root", "runtime_state", "producer_publication", "science_derived",
        "unrelated_host", "unrelated_repository", "unrelated_profile",
        "provider_replica", "account_replica", "paper_replica", "scheduler_replica")},
}


def resource_rights(name, directory, relative=None):
    needed, forbidden = RESOURCE_RULES[name]
    handoff = name == "science_derived" and relative == ".custody-transport.tmp" and not directory
    if handoff:
        # This exact existing serialization slot is moved into the handoff;
        # it is not arbitrary Science-derived state or Writer-owned scratch.
        needed, forbidden = _READ, MUTATION_RIGHTS
    if not directory:
        needed = tuple(right for right in needed if right != 32)
        forbidden = tuple(right for right in forbidden if right != 64)
        if RESOURCE_RULES[name][0] == _META and not handoff:
            needed = tuple(right for right in needed if right != 1)
            forbidden = (*forbidden, 1, 32)
    return needed, forbidden


def inherited_sddl(native, parent_sddl, owner, directory):
    """Native in-memory inheritance calculation; never applies an object ACL."""
    w = native.w
    class MAPPING(c.Structure):
        _fields_ = [(key, w.DWORD) for key in ("read", "write", "execute", "all")]
    native.bind(native.a, "CreatePrivateObjectSecurityEx",
        [c.c_void_p, c.c_void_p, c.POINTER(c.c_void_p), c.c_void_p,
         w.BOOL, w.DWORD, w.HANDLE, c.POINTER(MAPPING)], w.BOOL)
    native.bind(native.a, "DestroyPrivateObjectSecurity", [c.POINTER(c.c_void_p)], w.BOOL)
    parent, creator, result, text = c.c_void_p(), c.c_void_p(), c.c_void_p(), w.LPWSTR()
    try:
        for raw, target in ((parent_sddl, parent), (f"O:{owner}G:{owner}", creator)):
            native.checked(native.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                raw, 1, c.byref(target), None), "Projection descriptor input")
        mapping = MAPPING(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        # Owner/privilege checks are unnecessary for a hypothetical descriptor.
        # This buffer is used only for AccessCheck and is never assigned.
        native.checked(native.a.CreatePrivateObjectSecurityEx(parent, creator, c.byref(result),
            None, directory, 0x19, None, c.byref(mapping)), "Native inheritance projection")
        native.checked(native.a.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            result, 1, 7, c.byref(text), None), "Read projected descriptor")
        return text.value
    finally:
        if text:
            native.k.LocalFree(c.cast(text, c.c_void_p))
        if result:
            native.checked(native.a.DestroyPrivateObjectSecurity(c.byref(result)), "Free projected descriptor")
        for memory in (creator, parent):
            if memory:
                native.k.LocalFree(memory)


@dataclass(frozen=True)
class ScmRoleProfile:
    writer: ScmActorBinding
    science: ScmActorBinding
    configuration_path: str
    resources: tuple[WriterResourceBinding, ...]
    profile: str = PROFILE

    def __post_init__(self):
        require(type(self.writer) is ScmActorBinding and type(self.science) is ScmActorBinding
                and self.profile == PROFILE, "Exact native role profile required.")
        self.writer.__post_init__()
        self.science.__post_init__()
        require(self.writer.service_name.endswith("-Writer")
                and self.science.service_name.endswith("-Science")
                and self.writer.service_name.rsplit("-", 1)[0] == self.science.service_name.rsplit("-", 1)[0],
                "Cross-instance actor profile.")
        require(self.writer.host_path == self.science.host_path and self.writer.host_sha256 == self.science.host_sha256
                and self.writer.python_path == self.science.python_path and self.writer.python_sha256 == self.science.python_sha256,
                "Actor images differ from the common installed image.")
        absolute_path(self.configuration_path)
        require(self.science.integrity_sid == "S-1-16-12288", "Science SCM integrity contract changed.")
        require(type(self.resources) is tuple and all(type(row) is WriterResourceBinding for row in self.resources)
                and len(self.resources) == len(RESOURCE_RULES)
                and {row.name for row in self.resources} == set(RESOURCE_RULES), "Complete exact Writer resource profile required.")
        for row in self.resources:
            row.__post_init__()
        require(len({str(absolute_path(row.path)).casefold() for row in self.resources}) == len(self.resources),
                "Writer support-resource alias collision.")


def encode_profile(value):
    value.__post_init__()
    result = asdict(value)
    for role in ("writer", "science"):
        if result[role]["writer_token_contract"] is None:
            result[role].pop("writer_token_contract")
    return result


def decode_profile(value):
    if value is None:
        return None
    from dataclasses import fields
    require(type(value) is dict and set(value) == {f.name for f in fields(ScmRoleProfile)}, "Exact role-profile fields required.")
    actors = {}
    for role in ("writer", "science"):
        raw = value[role]
        expected = {f.name for f in fields(ScmActorBinding)}
        require(type(raw) is dict and set(raw) in (expected, expected - {"writer_token_contract"}),
                "Exact actor binding fields required.")
        raw = dict(raw)
        contract = raw.get("writer_token_contract")
        if contract is not None:
            require(type(contract) is dict and set(contract) == {f.name for f in fields(QualifiedWriterTokenContract)}
                    and type(contract["stable_group_sids"]) is list, "Exact qualified Writer JSON fields required.")
            raw["writer_token_contract"] = QualifiedWriterTokenContract(**{
                **contract, "stable_group_sids": tuple(contract["stable_group_sids"])})
        actors[role] = ScmActorBinding(**raw)
    require(type(value["resources"]) is list, "Support resource JSON array required.")
    resources = []
    for raw in value["resources"]:
        require(type(raw) is dict and set(raw) == {f.name for f in fields(WriterResourceBinding)}
                and type(raw["file_identity"]) is list, "Exact support binding fields required.")
        resources.append(WriterResourceBinding(**{**raw, "file_identity": tuple(raw["file_identity"])}))
    return ScmRoleProfile(**{**value, **actors, "resources": tuple(resources)})


def _validate_token(observed, role, binding):
    """Adjudicate native observations; callers must obtain them from own APIs."""
    require(role in {"writer", "science"} and type(binding) is ScmActorBinding, "Unknown native role.")
    binding.__post_init__()
    require(binding.service_name.endswith("-" + role.title()), "Token role and service binding differ.")
    sid = service_sid(binding.service_name)
    user = LOCAL_SERVICE if role == "writer" else sid
    require(observed.get("user") == observed.get("owner") == user, "Native TokenUser/TokenOwner role mismatch.")
    require(all(type(observed.get(key)) is int for key in (
        "token_type", "elevation", "elevation_type", "ui_access", "virtualization", "session_id", "has_restrictions")),
        "Native token scalar provenance incomplete.")
    require(observed.get("thread_token") is False and observed.get("token_type") == 1,
            "Own primary token required; impersonation is forbidden.")
    require(observed.get("elevation") == 0 and observed.get("elevation_type") == 1
            and observed.get("ui_access") == 0 and observed.get("virtualization") == 0
            and observed.get("session_id") == 0 and observed.get("integrity") == binding.integrity_sid,
            "Unreviewed SCM token class.")
    require(observed.get("has_restrictions") == 1, "Native restrictions missing.")
    groups = observed.get("group_attributes")
    restricting = observed.get("restricting_attributes")
    require(type(groups) is tuple and type(restricting) is tuple, "Native group provenance incomplete.")
    require(all(type(row) is tuple and len(row) == 2 and type(row[0]) is str and type(row[1]) is int
                for row in (*groups, *restricting)), "Malformed native group attributes.")
    require(len({s for s, _ in groups}) == len(groups) and len({s for s, _ in restricting}) == len(restricting),
            "Duplicate native SID observation.")
    logons = [(s, a) for s, a in groups if a & 0xC0000000]
    require(len(logons) == 1 and re.fullmatch(r"S-1-5-5-[0-9]+-[0-9]+", logons[0][0])
            and logons[0][1] in {0xC0000007, 0xC000000F}, "Fresh native logon SID unproven.")
    expected = {sid, WORLD, WRITE_RESTRICTED, logons[0][0]}
    require({s for s, _ in restricting} == expected and all(a == 7 for _, a in restricting),
            "Restricting SID set differs from SCM restricted-service profile.")
    ordinary = dict(groups)
    require(ordinary.get(WORLD) == 7 and ordinary.get(WRITE_RESTRICTED) == 7
            and ordinary.get("S-1-5-6") == 7, "SCM group relationships missing.")
    if binding.writer_token_contract is not None:
        require(type(observed.get("mandatory_policy")) is int and observed["mandatory_policy"] == 3,
                "Qualified Writer mandatory integrity policy differs.")
        require(ordinary.get(sid) == 14, "Qualified Writer service SID semantics differ.")
        require(logons[0][1] == 0xC000000F, "Qualified Writer logon attributes differ.")
        expected_groups = {s: 7 for s in binding.writer_token_contract.stable_group_sids}
        expected_groups.update({sid: 14, binding.integrity_sid: 96, logons[0][0]: 0xC000000F})
        require(ordinary == expected_groups, "Qualified Writer ordinary group envelope differs.")
    else:
        if role == "writer":
            require(ordinary.get(sid) in {7, 15}, "Writer service SID absent from ordinary token.")
        allowed = {WORLD, WRITE_RESTRICTED, sid, user, logons[0][0], binding.integrity_sid,
                   "S-1-2-0", "S-1-2-1", "S-1-5-6", "S-1-5-11", "S-1-5-15", "S-1-5-32-545", "S-1-5-80-0"}
        require(set(ordinary) <= allowed, "Unreviewed ordinary group authority.")
        for group, attributes in groups:
            if group == logons[0][0]:
                continue
            permitted = {96} if group == binding.integrity_sid else {7, 15} if group == sid else {7}
            require(attributes in permitted, "Unreviewed group/deny-only/owner attributes.")
    require(observed.get("privilege_attributes") == (("SeChangeNotifyPrivilege", 3),),
            "Excess or incomplete native privilege inventory.")
    require(all(type(observed.get(key)) is tuple and len(observed[key]) == 2
                and all(type(v) is int and 0 <= v <= 0xFFFFFFFF for v in observed[key])
                for key in ("token_id", "authentication_id", "modified_id")), "Token statistics provenance incomplete.")
    return sid


_TOKEN_REJECTION_FIELDS = {
    "Unknown native role.": ("role",),
    "Token role and service binding differ.": ("role",),
    "Qualified Writer mandatory integrity policy differs.": ("mandatory_policy",),
    "Qualified Writer service SID semantics differ.": ("group_attributes",),
    "Qualified Writer logon attributes differ.": ("group_attributes",),
    "Qualified Writer ordinary group envelope differs.": ("group_attributes",),
    "Unbound qualification service name.": ("binding",),
    "Native TokenUser/TokenOwner role mismatch.": ("user", "owner"),
    "Native token scalar provenance incomplete.": (
        "token_type", "elevation", "elevation_type", "ui_access", "virtualization", "session_id", "has_restrictions"),
    "Own primary token required; impersonation is forbidden.": ("thread_token", "token_type"),
    "Unreviewed SCM token class.": (
        "elevation", "elevation_type", "ui_access", "virtualization", "session_id", "integrity"),
    "Native restrictions missing.": ("has_restrictions",),
    "Native group provenance incomplete.": ("group_attributes", "restricting_attributes"),
    "Malformed native group attributes.": ("group_attributes", "restricting_attributes"),
    "Duplicate native SID observation.": ("group_attributes", "restricting_attributes"),
    "Fresh native logon SID unproven.": ("group_attributes",),
    "Restricting SID set differs from SCM restricted-service profile.": ("restricting_attributes",),
    "SCM group relationships missing.": ("group_attributes",),
    "Writer service SID absent from ordinary token.": ("group_attributes",),
    "Unreviewed ordinary group authority.": ("group_attributes",),
    "Unreviewed group/deny-only/owner attributes.": ("group_attributes",),
    "Excess or incomplete native privilege inventory.": ("privilege_attributes",),
    "Token statistics provenance incomplete.": ("token_id", "authentication_id", "modified_id"),
}

_TOKEN_EXPECTED_RULES = {
    "Unknown native role.": "writer or science; exact ScmActorBinding",
    "Token role and service binding differ.": "Exact Writer or Science service role suffix",
    "Qualified Writer mandatory integrity policy differs.": "Exact int 3: no-write-up and new-process minimum",
    "Qualified Writer service SID semantics differ.": "Derived own service SID: enabled, default-enabled, owner; exact attributes 14",
    "Qualified Writer logon attributes differ.": "Observed own logon SID with exact attributes 0xc000000f",
    "Qualified Writer ordinary group envelope differs.": "Exact reviewed stable inventory plus derived own service, HIGH and fresh logon",
    "Unbound qualification service name.": "Exact qualification service-name grammar",
    "Native TokenUser/TokenOwner role mismatch.": "Both exact role principal",
    "Native token scalar provenance incomplete.": "Exact int, not bool, for every required scalar",
    "Own primary token required; impersonation is forbidden.": "thread_token is False; token_type equals 1",
    "Unreviewed SCM token class.": "Exact six bound scalar values",
    "Native restrictions missing.": "has_restrictions equals 1",
    "Native group provenance incomplete.": "Both group inventories are tuples",
    "Malformed native group attributes.": "Every row is (str SID, int attributes) tuple",
    "Duplicate native SID observation.": "Each SID occurs once per inventory",
    "Fresh native logon SID unproven.": "One S-1-5-5-X-Y logon with attributes 0xc0000007 or 0xc000000f",
    "Restricting SID set differs from SCM restricted-service profile.": "Exact service/World/write-restricted/logon set; each attributes 7",
    "SCM group relationships missing.": "World/write-restricted/service-logon groups each attributes 7",
    "Writer service SID absent from ordinary token.": "Own service SID with attributes 7 or 15",
    "Unreviewed ordinary group authority.": "Only the frozen ordinary SID allowlist",
    "Unreviewed group/deny-only/owner attributes.": "Integrity 96; service 7 or 15; ordinary 7; exact logon handled separately",
    "Excess or incomplete native privilege inventory.": "Only SeChangeNotifyPrivilege with attributes 3",
    "Token statistics provenance incomplete.": "Each LUID is an exact two-uint32 tuple",
}


def _token_diagnostic_value(value, depth=0):
    # Rejection text is not a token dump or a channel for arbitrary input text.
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value if value.bit_length() <= 64 else {"type": "int", "outOfRange": True}
    if type(value) is str:
        if len(value) <= 184 and (re.fullmatch(r"S-1-[0-9]+(?:-[0-9]+){1,15}", value)
                                 or re.fullmatch(r"Se[A-Za-z]{1,64}Privilege", value)):
            return value
        return {"type": "str", "length": len(value), "redacted": True}
    if type(value) in {tuple, list} and depth < 2:
        return {"type": "tuple" if type(value) is tuple else "list", "count": len(value),
                "sample": [_token_diagnostic_value(item, depth + 1) for item in value[:8]],
                "truncated": len(value) > 8}
    return {"type": "UNSUPPORTED_VALUE", "redacted": True}


def _token_rejection_diagnostic(message, observed, role, binding):
    fields = _TOKEN_REJECTION_FIELDS.get(message, ())
    values = observed if type(observed) is dict else {}
    diagnostic = {
        "schema": "writer-token-class-rejection-v1", "status": "REJECTED",
        "predicate": message if fields else "UNCLASSIFIED_TOKEN_REJECTION",
        "role": role if role in {"writer", "science"} else "UNREVIEWED",
        "profile": PROFILE, "phase": "TOKEN_CLASSIFICATION", "generation": "NOT_OBSERVED",
        "process": {"pid": os.getpid(), "parentPid": os.getppid(), "birth": "NOT_OBSERVED"},
        "observed": {key: _token_diagnostic_value(values.get(key)) for key in fields},
        "expected": {"rule": _TOKEN_EXPECTED_RULES.get(message, "FROZEN_TOKEN_CONTRACT")},
    }
    if type(binding) is ScmActorBinding and SERVICE_NAME.fullmatch(binding.service_name):
        diagnostic["expectedService"] = binding.service_name
        sid = service_sid(binding.service_name)
        expected_user = LOCAL_SERVICE if role == "writer" else sid
        if message == "Native TokenUser/TokenOwner role mismatch.":
            diagnostic["expected"] = {"user": expected_user, "owner": expected_user}
        elif message == "Unreviewed SCM token class.":
            expected = dict(elevation=0, elevation_type=1, ui_access=0, virtualization=0,
                            session_id=0, integrity=binding.integrity_sid)
            failed = [key for key in fields if values.get(key) != expected[key]]
            diagnostic["failedFields"] = failed
            diagnostic["observed"] = {key: _token_diagnostic_value(values.get(key)) for key in failed}
            diagnostic["expected"] = {key: _token_diagnostic_value(expected[key]) for key in failed}
        elif message == "Writer service SID absent from ordinary token.":
            groups = values.get("group_attributes", ())
            diagnostic["observed"] = {"serviceSidAttributes": _token_diagnostic_value(dict(groups).get(sid))}
            diagnostic["expected"] = {"serviceSid": sid, "attributes": [7, 15]}
        elif message in {"Unreviewed ordinary group authority.", "Unreviewed group/deny-only/owner attributes."}:
            groups = values["group_attributes"]
            logon = next(s for s, a in groups if a & 0xC0000000)
            allowed = {WORLD, WRITE_RESTRICTED, sid, expected_user, logon, binding.integrity_sid,
                       "S-1-2-0", "S-1-2-1", "S-1-5-6", "S-1-5-11", "S-1-5-15", "S-1-5-32-545", "S-1-5-80-0"}
            if message == "Unreviewed ordinary group authority.":
                rejected = tuple((s, a) for s, a in groups if s not in allowed)
            else:
                rejected = tuple((s, a) for s, a in groups if s != logon and a not in (
                    {96} if s == binding.integrity_sid else {7, 15} if s == sid else {7}))
            diagnostic["observed"] = {"rejectedGroups": _token_diagnostic_value(rejected)}
    return diagnostic


def validate_token(observed, role, binding):
    """Keep admission unchanged; annotate its first rejection from the same facts."""
    try:
        return _validate_token(observed, role, binding)
    except WriterProfileError as exc:
        try:
            exc.token_diagnostic = _token_rejection_diagnostic(str(exc), observed, role, binding)
        except Exception:
            # Diagnostic failure never changes the original rejection to success.
            exc.token_diagnostic = {"schema": "writer-token-class-rejection-v1", "status": "REJECTED",
                                    "diagnostic": "UNAVAILABLE", "process": {"pid": os.getpid()}}
        raise


def _bind_token_rejection_process(exc, native, *, require_generation):
    if getattr(exc, "token_diagnostic", None) is None:
        return
    diagnostic = exc.token_diagnostic
    diagnostic["phase"] = "GENERATION_ADMISSION" if require_generation else "PRE_GENERATION"
    diagnostic["generation"] = "NOT_OBSERVED" if require_generation else "NOT_YET_CREATED"
    try:
        process = _process(native, os.getpid())
        diagnostic["process"] = {"pid": process["pid"], "birth": process["birth"], "parentPid": os.getppid()}
    except Exception:
        diagnostic["processIdentityQuery"] = "UNAVAILABLE_REJECTION_PRESERVED"


def _extended_token(native, handle, observed):
    """Additional queries on the same queried process token, never caller JSON."""
    w = native.w
    class SIDATTR(c.Structure):
        _fields_ = [("sid", c.c_void_p), ("attributes", w.DWORD)]
    class GROUPS(c.Structure):
        _fields_ = [("count", w.DWORD), ("entry", SIDATTR)]
    class LUID(c.Structure):
        _fields_ = [("low", w.DWORD), ("high", w.LONG)]
    class STATISTICS(c.Structure):
        _fields_ = [("token", LUID), ("authentication", LUID), ("expiration", c.c_longlong),
                    ("type", w.DWORD), ("level", w.DWORD), ("charged", w.DWORD),
                    ("available", w.DWORD), ("groups", w.DWORD), ("privileges", w.DWORD), ("modified", LUID)]
    for name, kind in (("restricting_attributes", 11), ("statistics", 10), ("has_restrictions", 21),
                       ("session_id", 12), ("elevation_type", 18), ("ui_access", 26), ("virtualization", 24),
                       ("mandatory_policy", 27)):
        length = w.DWORD()
        native.a.GetTokenInformation(handle, kind, None, 0, c.byref(length))
        require(0 < length.value <= 131072, "Native extended-token size invalid.")
        buf = c.create_string_buffer(length.value)
        native.checked(native.a.GetTokenInformation(handle, kind, buf, len(buf), c.byref(length)), "GetTokenInformation(profile)")
        if name == "restricting_attributes":
            count = w.DWORD.from_buffer(buf).value
            require(count <= 256 and (count == 0 or GROUPS.entry.offset + count * c.sizeof(SIDATTR) <= len(buf)),
                    "Restricted SID buffer invalid.")
            rows = []
            for i in range(count):
                row = SIDATTR.from_buffer(buf, GROUPS.entry.offset + i * c.sizeof(SIDATTR))
                rows.append((native.sid(row.sid), row.attributes))
            observed[name] = tuple(rows)
        elif name == "statistics":
            require(length.value == c.sizeof(STATISTICS), "Native token statistics size mismatch.")
            stats = STATISTICS.from_buffer(buf)
            for key, value in (("token_id", stats.token), ("authentication_id", stats.authentication), ("modified_id", stats.modified)):
                observed[key] = (value.low, value.high & 0xFFFFFFFF)
        else:
            require(length.value in ({1, 4} if kind == 21 else {4}), "Native token scalar size mismatch.")
            observed[name] = int.from_bytes(buf.raw[:length.value], "little")


def access_decisions(native, sddl, rights=FILE_RIGHTS, *, service=False):
    """AccessCheck on own actual token; failure and denial remain distinct."""
    w = native.w
    class MAPPING(c.Structure):
        _fields_ = [(name, w.DWORD) for name in ("read", "write", "execute", "all")]
    native.bind(native.a, "DuplicateToken", [w.HANDLE, c.c_int, c.POINTER(w.HANDLE)], w.BOOL)
    native.bind(native.a, "AccessCheck", [c.c_void_p, w.HANDLE, w.DWORD, c.POINTER(MAPPING), c.c_void_p,
                c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.POINTER(w.BOOL)], w.BOOL)
    primary, client, sd = w.HANDLE(), w.HANDLE(), c.c_void_p()
    try:
        native.checked(native.a.OpenProcessToken(native.k.GetCurrentProcess(), 0xA, c.byref(primary)), "Own access token")
        native.checked(native.a.DuplicateToken(primary, 2, c.byref(client)), "AccessCheck token duplicate")
        native.checked(native.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, c.byref(sd), None), "Opened descriptor projection")
        mapping = MAPPING(0x2008D, 0x20002, 0x20170, 0xF01FF) if service else MAPPING(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        result = {}
        for right in rights:
            require(type(right) is int and right > 0 and right & (right - 1) == 0, "Individual native rights required.")
            privileges = c.create_string_buffer(16384)
            size, granted, allowed = w.DWORD(len(privileges)), w.DWORD(), w.BOOL()
            native.checked(native.a.AccessCheck(sd, client, right, c.byref(mapping), privileges,
                           c.byref(size), c.byref(granted), c.byref(allowed)), "AccessCheck API")
            require(not allowed.value or granted.value & right == right, "Contradictory native access result.")
            result[right] = bool(allowed.value)
        return result
    finally:
        if sd:
            native.k.LocalFree(sd)
        for handle in (client, primary):
            if handle:
                native.checked(native.k.CloseHandle(handle), "Close native access token")


def _process(native, pid):
    w = native.w
    native.bind(native.k, "OpenProcess", [w.DWORD, w.BOOL, w.DWORD], w.HANDLE)
    native.bind(native.k, "GetProcessTimes", [w.HANDLE, *([c.POINTER(w.FILETIME)] * 4)], w.BOOL)
    native.bind(native.k, "GetExitCodeProcess", [w.HANDLE, c.POINTER(w.DWORD)], w.BOOL)
    native.bind(native.k, "QueryFullProcessImageNameW", [w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL)
    require(type(pid) is int and pid > 0, "Process identity missing.")
    process = native.checked(native.k.OpenProcess(0x1000, False, pid), "Bound process query")
    try:
        times = [w.FILETIME() for _ in range(4)]
        code, size = w.DWORD(), w.DWORD(32768)
        image = c.create_unicode_buffer(size.value)
        native.checked(native.k.GetProcessTimes(process, *(c.byref(t) for t in times)), "Bound process birth")
        native.checked(native.k.GetExitCodeProcess(process, c.byref(code)), "Bound process state")
        native.checked(native.k.QueryFullProcessImageNameW(process, 0, image, c.byref(size)), "Bound process image")
        require(code.value == 259 and not (times[1].dwHighDateTime or times[1].dwLowDateTime), "Bound process exited.")
        return {"pid": pid, "birth": times[0].dwLowDateTime | times[0].dwHighDateTime << 32,
                "image": image.value}
    finally:
        native.checked(native.k.CloseHandle(process), "Close bound process")


def _scm(native, binding):
    w = native.w
    native.bind(native.a, "OpenSCManagerW", [w.LPCWSTR, w.LPCWSTR, w.DWORD], w.HANDLE)
    native.bind(native.a, "OpenServiceW", [w.HANDLE, w.LPCWSTR, w.DWORD], w.HANDLE)
    native.bind(native.a, "CloseServiceHandle", [w.HANDLE], w.BOOL)
    native.bind(native.a, "QueryServiceConfig2W", [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL)
    native.bind(native.a, "QueryServiceStatusEx", [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL)
    manager = native.checked(native.a.OpenSCManagerW(None, None, 1), "Read-only SCM connection")
    service = None
    try:
        service = native.checked(native.a.OpenServiceW(manager, binding.service_name, 5), "Own SCM query-only handle")
        status, needed = (w.DWORD * 9)(), w.DWORD()
        native.checked(native.a.QueryServiceStatusEx(service, 0, status, c.sizeof(status), c.byref(needed)), "Own SCM process status")
        require(status[0] == 0x10 and status[1] in {2, 3, 4} and status[7] > 0, "Dedicated running SCM process unproven.")
        mode = w.DWORD()
        native.checked(native.a.QueryServiceConfig2W(service, 5, c.byref(mode), c.sizeof(mode), c.byref(needed)), "SCM service SID type")
        require(mode.value == 3, "SCM restricted-service launch missing.")
        native.a.QueryServiceConfig2W(service, 6, None, 0, c.byref(needed))
        require(c.sizeof(c.c_void_p) < needed.value <= 8192, "SCM required-privileges buffer invalid.")
        buf = c.create_string_buffer(needed.value)
        native.checked(native.a.QueryServiceConfig2W(service, 6, buf, len(buf), c.byref(needed)), "SCM required privileges")
        ptr = c.c_void_p.from_buffer(buf).value
        require(ptr is not None and c.addressof(buf) <= ptr < c.addressof(buf) + len(buf), "SCM privilege pointer invalid.")
        raw = c.string_at(ptr, c.addressof(buf) + len(buf) - ptr)
        require(len(raw) % 2 == 0, "SCM privilege string alignment invalid.")
        privileges = raw.decode("utf-16-le").split("\0")
        require(privileges[0] == "SeChangeNotifyPrivilege" and len(privileges) >= 3
                and all(not item for item in privileges[1:]), "SCM privilege profile differs.")
        return {"service_name": binding.service_name, "service_sid": service_sid(binding.service_name),
                "sid_type": mode.value, "pid": int(status[7]), "state": int(status[1]),
                "required_privileges": ("SeChangeNotifyPrivilege",)}
    finally:
        if service:
            native.checked(native.a.CloseServiceHandle(service), "Close SCM query")
        native.checked(native.a.CloseServiceHandle(manager), "Close SCM manager")


def _proof_value(value):
    """Detached, type-exact value key; never retain mutable input references."""
    kind = type(value)
    if kind in {str, int, bool, bytes, type(None)}:
        return kind, value
    if kind is tuple:
        return kind, tuple(_proof_value(item) for item in value)
    if kind is dict:
        require(all(type(key) is str for key in value), "Invalid proof dictionary key.")
        return kind, tuple((key, _proof_value(value[key])) for key in sorted(value))
    if is_dataclass(value) and not isinstance(value, type) and value.__dataclass_params__.frozen:
        return kind, tuple((field.name, _proof_value(getattr(value, field.name))) for field in fields(value))
    raise WriterProfileError("Unsupported mutable native proof input.")


class ActorProofCache:
    """One exact accepted value per pure check, not a cached actor observation."""
    def __init__(self):
        self.profile = None
        self.token = None
        self.generation = None


def observe_actor(native, role, profile, observed, *, require_generation=True, check_images=True,
                  proof_cache=None):
    require(type(profile) is ScmRoleProfile, "Frozen native role profile required.")
    profile_key = _proof_value(profile) if proof_cache is not None else None
    if proof_cache is None or proof_cache.profile != profile_key:
        profile.__post_init__()
        if proof_cache is not None:
            proof_cache.profile = profile_key
    binding = getattr(profile, role)
    token_key = (role, _proof_value(binding), _proof_value(observed)) if proof_cache is not None else None
    if proof_cache is None or proof_cache.token != token_key:
        validate_token(observed, role, binding)
        if proof_cache is not None:
            proof_cache.token = token_key
    scm = _scm(native, binding)
    current = _process(native, os.getpid())
    parent = _process(native, scm["pid"])
    expected_self = binding.host_path if role == "science" else binding.python_path
    require(PureWindowsPath(current["image"]) == PureWindowsPath(expected_self)
            and PureWindowsPath(parent["image"]) == PureWindowsPath(binding.host_path), "Native actor image mismatch.")
    require((role == "science" and scm["pid"] == os.getpid()) or
            (role == "writer" and scm["pid"] == os.getppid() and scm["pid"] != os.getpid()), "Native SCM/parent relationship mismatch.")
    if check_images:
        for path, digest in ((binding.host_path, binding.host_sha256), (binding.python_path, binding.python_sha256)):
            require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, "Bound actor executable bytes changed.")
    generation = None
    if require_generation:
        path = Path(binding.generation_root) / "generation.json"
        with path.open("rb") as stream:
            raw = stream.read(16385)
        require(len(raw) <= 16384, "Unbounded generation record.")
        with Path(profile.configuration_path).open("rb") as stream:
            config_bytes = stream.read(1048577)
        require(len(config_bytes) <= 1048576, "Unbounded role configuration.")
        generation_key = (role, str(path), profile.configuration_path, raw, config_bytes,
                          _proof_value(current), _proof_value(parent))
        if proof_cache is not None and proof_cache.generation is not None and proof_cache.generation[0] == generation_key:
            generation = proof_cache.generation[1]
        else:
            record = json.loads(raw)
            require(type(record) is dict and record.get("role") == role, "Role generation missing.")
            from momentum_hunter.continuous_host_contract import host_fingerprint
            configuration = json.loads(config_bytes)
            require(configuration.get("hostFingerprint") == host_fingerprint(configuration)
                    and record.get("hostFingerprint") == configuration["hostFingerprint"]
                    and record.get("phase") in {"RUNNING", "STOP_REQUESTED"},
                    "Generation configuration/phase binding invalid.")
            generation = record.get("generation")
            require(type(generation) is str and str(uuid.UUID(generation)) == generation, "Generation identity invalid.")
            if role == "science":
                require(record.get("executionModel") == "SCM_DIRECT_SCIENCE_SERVICE_PROCESS"
                        and record.get("servicePid") == current["pid"] and record.get("serviceBirth") == current["birth"],
                        "Science generation does not bind native process.")
            else:
                require(record.get("supervisorPid") == parent["pid"] and record.get("supervisorBirth") == parent["birth"]
                        and record.get("childPid") == current["pid"] and record.get("childBirth") == current["birth"],
                        "Writer generation does not bind native process and parent.")
            if proof_cache is not None:
                proof_cache.generation = generation_key, generation
    return {"profile": PROFILE, "role": role, "token": observed, "scm": scm,
            "process": current, "parent": parent, "generation": generation,
            "provenance": "ACTUAL_NATIVE_PROCESS_TOKEN_AND_SCM_QUERY"}


def admission_identity(observation):
    return {key: observation[key] for key in ("profile", "role", "token", "process", "parent", "generation")}


def expected_resource_paths(config):
    p = lambda value: PureWindowsPath(value)
    root = p(config["host"]["instanceRoot"])
    install = p(config["installRoot"])
    custody_version = config["host"]["science"].get("custodyPolicy", {}).get("version", 1)
    require(type(custody_version) is int and custody_version in {1, 2}, "Unknown custody support policy version.")
    science_root = p(config["host"]["science"]["stateRoot"])
    return {
        "runtime_source": install / "source", "host_image_root": install / "host",
        "python_root": install / "python", "python_base": install / "python-base",
        "configuration_root": p(config["configRoot"]),
        "configuration": p(config["configRoot"]) / "continuous-deployment.json",
        "writer_key": p(config["ipcKeyPath"]), "writer_evidence": p(config["evidenceRoot"]),
        "writer_logs": p(config["logRoot"]) / "writer",
        "writer_generation": p(config["hostStateRoot"]) / "writer",
        "science_generation": p(config["hostStateRoot"]) / "science",
        "runtime_generation": p(config["hostStateRoot"]) / "runtime",
        "runtime_state": p(config["runtimeStateRoot"]),
        "producer_publication": p(config["researchFactExportV2"]["exportRoot"]),
        "science_derived": science_root / ("mutable-v2/reader-lock" if custody_version == 2 else "derived"),
        **{name: root / "writer-denial-controls" / name for name in (
            "unrelated_host", "unrelated_repository", "unrelated_profile", "provider_replica",
            "account_replica", "paper_replica", "scheduler_replica")},
    }


def validate_profile_paths(config, profile):
    require(type(profile) is ScmRoleProfile and config.get("inputMode") == "OFFLINE_QUALIFICATION",
            "Bounded Writer profile has no production activation authority.")
    profile.__post_init__()
    expected = expected_resource_paths(config)
    root = absolute_path(config["host"]["instanceRoot"])
    for binding in profile.resources:
        path = absolute_path(binding.path)
        require(path == expected[binding.name] and path.is_relative_to(root) and path != root,
                "Support profile escaped its exact qualification role.")
    require(absolute_path(profile.configuration_path) == expected["configuration"], "Configuration profile misbound.")
    names = config["host"]["services"]
    for role in ("writer", "science"):
        actor = getattr(profile, role)
        require(actor.service_name == names[role] and absolute_path(actor.host_path) ==
                expected["host_image_root"] / "MomentumHunter.ContinuousServiceHost.exe"
                and absolute_path(actor.python_path) == expected["python_base"] / "python.exe"
                and absolute_path(actor.generation_root) == expected[role + "_generation"],
                "Native actor differs from installed qualification role.")
    return profile


class WriterResourceGuard:
    """Pins the frozen support roots before either Writer duty can mutate.

    Denial controls are explicit disposable replicas, not access to a provider
    credential or account. This is not a production confinement attestation.
    """
    def __init__(self, native, config, profile):
        self.native, self.profile = native, validate_profile_paths(config, profile)
        self.handles = []
        self.rows = []
        self._access_cache = {}
        self._inheritance_cache = set()
        self._scan_lock = threading.RLock()
        self._bound_paths = {str(absolute_path(row.path)).casefold() for row in profile.resources}
        self._image_roots = {"runtime_source", "host_image_root", "python_root", "python_base"}
        self._closed = False
        try:
            ancestors = {str(parent).casefold(): parent for binding in profile.resources
                         for parent in absolute_path(binding.path).parents}
            mutable = {str(absolute_path(b.path)).casefold() for b in profile.resources
                       if b.name in {"writer_evidence", "writer_logs", "writer_generation"}}
            for key, path in sorted(ancestors.items(), key=lambda row: len(row[1].parts)):
                if key in mutable:
                    continue
                handle, security = self._pin(Path(path), True)
                decisions = access_decisions(native, security.sddl, MUTATION_RIGHTS)
                require(not any(decisions.values()), "Writer controls a support ancestor.")
                self.rows.append({"name": "ancestor", "path": str(path), "decisions": decisions})
            for binding in profile.resources:
                handle, security = self._pin(Path(binding.path), binding.directory)
                require(native.identity(handle) == binding.file_identity and security.digest == binding.descriptor_sha256,
                        "Frozen Writer support object identity/security changed.")
                self._rights(binding.name, binding.directory, security)
                # Read-only executable trees must not hide a writable descendant.
                if binding.name in self._image_roots:
                    count = 0
                    for directory, dirs, files in os.walk(binding.path, followlinks=False):
                        for name in (*dirs, *files):
                            count += 1
                            require(count <= 30000, "Read-only support inventory exceeded its finite bound.")
                            path = Path(directory) / name
                            is_directory = name in dirs
                            child, sec = self._pin(path, is_directory, runtime_file=not is_directory)
                            self._rights(binding.name, is_directory, sec)
            self.recheck()
        except BaseException:
            self.close()
            raise

    def _pin(self, path, directory, *, runtime_file=False):
        handle = self.native.open(path, directory=directory, access=0x120080, share=1)
        try:
            info = self.native.information(handle)
            require(not info.dwFileAttributes & 0x400 and bool(info.dwFileAttributes & 0x10) == directory,
                    "Support type/reparse identity failed.")
            require(directory or info.nNumberOfLinks == 1, "Support hard-link alias rejected.")
            self.native.require_path(handle, path)
            sec = self.native.security(handle)
            identity = self.native.identity(handle)
            self.handles.append((handle, sec.digest, identity, directory, runtime_file))
            return handle, sec
        except BaseException:
            handle.close()
            raise

    def _rights(self, name, directory, security, relative=None):
        needed, forbidden = resource_rights(name, directory, relative)
        key = security.digest
        if key not in self._access_cache:
            self._access_cache[key] = access_decisions(self.native, security.sddl)
        decisions = self._access_cache[key]
        require(all(decisions[right] for right in needed), "Writer required support access unavailable: " + name)
        require(not any(decisions[right] for right in forbidden), "Writer unrelated support authority: " + name)
        self.rows.append({"name": name, "needed": needed, "forbidden": forbidden, "decisions": decisions})

    def _future_children(self, name, security):
        key = (name, security.digest)
        if key in self._inheritance_cache:
            return
        # Check both owner routes and native OI/CI/IO/creator-owner expansion.
        # Existing explicit/protected children are checked separately below.
        for owner in {security.owner, LOCAL_SERVICE}:
            for directory in (False, True):
                raw = inherited_sddl(self.native, security.sddl, owner, directory)
                forbidden = resource_rights(name, directory)[1]
                decisions = access_decisions(self.native, raw, forbidden)
                require(not any(decisions.values()), "Writer inherited descendant authority: " + name)
        self._inheritance_cache.add(key)

    def _scan_support(self, binding):
        require(binding.name not in DYNAMIC_RESOURCE_ROOTS,
                "Mutable children are not process-admission inputs.")
        root = Path(binding.path)
        pending, count = [root], 0
        with ExitStack() as leases:
            while pending:
                directory = pending.pop()
                with os.scandir(directory) as entries:
                    for entry in entries:
                        count += 1
                        require(count <= 30000, "Writer support subtree exceeds its finite bound.")
                        path = Path(entry.path)
                        if str(absolute_path(str(path))).casefold() in self._bound_paths:
                            continue  # Exact config/key bindings have their own stricter lease.
                        is_directory = entry.is_dir(follow_symlinks=False)
                        relative = path.relative_to(root).as_posix()
                        handle = self.native.open(path, directory=is_directory, access=0x120080,
                                                  share=1 if is_directory else 7)
                        if is_directory:
                            leases.callback(handle.close)
                        try:
                            info = self.native.information(handle)
                            require(not info.dwFileAttributes & 0x400
                                and bool(info.dwFileAttributes & 0x10) == is_directory,
                                "Support descendant type/reparse mismatch.")
                            self.native.require_path(handle, path)
                            # Existing main evidence publication uses a temporary
                            # internal hard link. Other support trees cannot.
                            require(is_directory or binding.name == "writer_evidence" or info.nNumberOfLinks == 1,
                                    "Unrelated support hard-link alias rejected.")
                            identity = self.native.identity(handle)
                            security = self.native.security(handle)
                            self._rights(binding.name, is_directory, security, relative)
                            if is_directory:
                                self._future_children(binding.name, security)
                                pending.append(path)
                            self.native.require_path(handle, path)
                            require(self.native.identity(handle) == identity
                                and self.native.security(handle).digest == security.digest,
                                "Support descendant changed during authority inspection.")
                        finally:
                            if not is_directory:
                                handle.close()

    def recheck(self):
        with self._scan_lock:
            self._recheck()

    def _recheck(self):
        require(not self._closed, "Writer support guard closed.")
        for handle, digest, identity, directory, runtime_file in self.handles:
            # Admission checks every image descendant. Read-only file leases
            # block byte replacement; Writer has no DACL/owner mutation there.
            # Recheck support directories per operation. Privileged external
            # image-policy mutation is outside this frozen qualification.
            if runtime_file:
                continue
            info = self.native.information(handle)
            require(not info.dwFileAttributes & 0x400 and bool(info.dwFileAttributes & 0x10) == directory
                    and (directory or info.nNumberOfLinks == 1), "Writer support topology drift.")
            self.native.require_path(handle, handle.path)
            require(self.native.identity(handle) == identity and self.native.security(handle).digest == digest,
                    "Pinned Writer support identity/security drift.")
        # Stable protected resources retain authority checks. Dynamic peer and
        # trusted-Writer publications cannot invalidate process admission.
        self._access_cache.clear()
        self._inheritance_cache.clear()
        self.rows.clear()
        for binding in self.profile.resources:
            if (binding.directory and binding.name not in self._image_roots
                    and binding.name not in DYNAMIC_RESOURCE_ROOTS):
                bound_path = Path(binding.path)
                handle = next(h for h, *_ in self.handles if h.path == bound_path)
                self._future_children(binding.name, self.native.security(handle))
                self._scan_support(binding)

    def close(self):
        if self._closed:
            return
        self._closed = True
        errors = []
        for handle, *_ in reversed(self.handles):
            try:
                handle.close()
            except Exception as exc:
                errors.append(exc)
        self.handles.clear()
        if errors:
            raise WriterProfileError("Writer support handles did not close.") from errors[0]


def verify_service_denials(native, profile):
    """Acquire/close right-specific handles only; never issue a control command."""
    w = native.w
    prefix = profile.science.service_name[:-8]
    names = [prefix + "-" + role for role in ("Automation", "Runtime", "Writer", "Science")]
    require(profile.writer.service_name in names, "Existing qualification Writer target binding required.")
    manager = native.checked(native.a.OpenSCManagerW(None, None, 1), "SCM denial read-only connection")
    rows = []
    try:
        for name in names:
            for right in SERVICE_CONTROL_RIGHTS:
                c.set_last_error(0)
                handle = native.a.OpenServiceW(manager, name, right)
                if handle:
                    native.checked(native.a.CloseServiceHandle(handle), "Close unexpected service authority")
                    raise WriterProfileError("Writer retained service-control authority.")
                error = c.get_last_error()
                require(error == 5, "Service denial is unproven (missing target or query error).")
                rows.append({"service": name, "right": right, "denied": True, "win32": error})
        return rows
    finally:
        native.checked(native.a.CloseServiceHandle(manager), "Close SCM denial connection")


class NativeWriterAdmission:
    def __init__(self, config, policy, *, require_generation=True, self_authority_diagnostic=False):
        from momentum_hunter.windows_science_custody import _Native
        require(policy is not None and type(policy.actor_profile) is ScmRoleProfile,
                "Native Writer launch/resource profile required before custody activation.")
        self.profile = validate_profile_paths(config, policy.actor_profile)
        self.native = _Native()
        self.guard = None
        try:
            token = self.native.token()
            diagnostic = None
            if self_authority_diagnostic and not require_generation:
                from momentum_hunter import windows_writer_self_diagnostic
                diagnostic = windows_writer_self_diagnostic.begin(self.native, config, self.profile, token)
            try:
                validate_token(token, "writer", self.profile.writer)
            except WriterProfileError as exc:
                _bind_token_rejection_process(exc, self.native, require_generation=require_generation)
                if diagnostic is not None:
                    windows_writer_self_diagnostic.emit(diagnostic, exc)
                raise
            if diagnostic is not None:
                windows_writer_self_diagnostic.emit(diagnostic, None)
            self.guard = WriterResourceGuard(self.native, config, self.profile)
            self.observation = observe_actor(self.native, "writer", self.profile, token,
                                             require_generation=require_generation)
            self.service_denials = verify_service_denials(self.native, self.profile)
        except BaseException:
            self.close()
            raise

    def recheck(self):
        token = self.native.token()
        current = observe_actor(self.native, "writer", self.profile, token, check_images=False)
        require(admission_identity(current) == admission_identity(self.observation), "Writer admission changed or was reused.")
        self.guard.recheck()

    def close(self):
        if self.guard is not None:
            guard, self.guard = self.guard, None
            guard.close()
