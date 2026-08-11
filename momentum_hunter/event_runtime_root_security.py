"""Dormant security contract for a future installed runtime evidence root.

The contract evaluates supplied Windows path and effective-access evidence. It
does not inspect or create a directory, change an ACL, select an installed root,
start Engine Host, or authorize activation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import PureWindowsPath


READ = "READ"
TRAVERSE = "TRAVERSE"
WRITE = "WRITE"
APPEND = "APPEND"
CREATE_CHILD = "CREATE_CHILD"
DELETE = "DELETE"
DELETE_CHILD = "DELETE_CHILD"
CHANGE_PERMISSIONS = "CHANGE_PERMISSIONS"
TAKE_OWNERSHIP = "TAKE_OWNERSHIP"

ACCESS_RIGHTS = frozenset(
    {
        READ,
        TRAVERSE,
        WRITE,
        APPEND,
        CREATE_CHILD,
        DELETE,
        DELETE_CHILD,
        CHANGE_PERMISSIONS,
        TAKE_OWNERSHIP,
    }
)
ROOT_MUTATION_RIGHTS = frozenset(
    {
        WRITE,
        APPEND,
        CREATE_CHILD,
        DELETE,
        DELETE_CHILD,
        CHANGE_PERMISSIONS,
        TAKE_OWNERSHIP,
    }
)
ANCESTOR_REPLACEMENT_RIGHTS = frozenset(
    {DELETE, DELETE_CHILD, CHANGE_PERMISSIONS, TAKE_OWNERSHIP}
)
DEFAULT_WRITER_RIGHTS = (
    APPEND,
    CREATE_CHILD,
    DELETE,
    DELETE_CHILD,
    READ,
    TRAVERSE,
    WRITE,
)

CONTRACT_ELIGIBLE = "CONTRACT_ELIGIBLE"
BLOCKED = "BLOCKED"
ROOT_SECURITY_STATUSES = frozenset({CONTRACT_ELIGIBLE, BLOCKED})

RUNTIME_ROOT_SECURITY_SCHEMA_VERSION = 1
RUNTIME_ROOT_SECURITY_POLICY_PROFILE = "runtime-root-security-policy-v1"
RUNTIME_ROOT_SECURITY_SNAPSHOT_PROFILE = "runtime-root-security-snapshot-v1"
RUNTIME_ROOT_SECURITY_RESULT_PROFILE = "runtime-root-security-result-v1"
RUNTIME_ROOT_SECURITY_AUTHORITY = "DORMANT_CONTRACT_ONLY"


class RuntimeRootSecurityError(ValueError):
    """Raised when runtime-root security evidence is invalid or contradictory."""


@dataclass(frozen=True)
class RuntimePrincipalAccess:
    principal_sid: str
    effective_rights: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RuntimePathSecurityEvidence:
    path: str
    exists: bool
    is_directory: bool
    is_symlink: bool
    is_reparse_point: bool
    owner_sid: str
    dacl_protected: bool
    principal_access: tuple[RuntimePrincipalAccess, ...]


@dataclass(frozen=True)
class RuntimeRootSecurityPolicy:
    policy_version: str
    approved_base_path: str
    writer_principal_sid: str
    interactive_principal_sids: tuple[str, ...]
    broad_principal_sids: tuple[str, ...]
    trusted_owner_sids: tuple[str, ...]
    required_writer_rights: tuple[str, ...]
    schema_version: int = RUNTIME_ROOT_SECURITY_SCHEMA_VERSION
    profile: str = RUNTIME_ROOT_SECURITY_POLICY_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RuntimeRootSecuritySnapshot:
    root_path: str
    source_identity: str
    observed_at: str
    components: tuple[RuntimePathSecurityEvidence, ...]
    schema_version: int = RUNTIME_ROOT_SECURITY_SCHEMA_VERSION
    profile: str = RUNTIME_ROOT_SECURITY_SNAPSHOT_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RuntimeRootSecurityResult:
    status: str
    root_path: str
    policy_fingerprint: str
    snapshot_fingerprint: str
    blockers: tuple[str, ...]
    activation_authorized: bool = False
    authority: str = RUNTIME_ROOT_SECURITY_AUTHORITY
    schema_version: int = RUNTIME_ROOT_SECURITY_SCHEMA_VERSION
    profile: str = RUNTIME_ROOT_SECURITY_RESULT_PROFILE
    fingerprint: str = ""


def build_runtime_root_security_policy(
    *,
    policy_version: str,
    approved_base_path: str,
    writer_principal_sid: str,
    interactive_principal_sids: tuple[str, ...],
    broad_principal_sids: tuple[str, ...],
    trusted_owner_sids: tuple[str, ...],
    required_writer_rights: tuple[str, ...] = DEFAULT_WRITER_RIGHTS,
) -> RuntimeRootSecurityPolicy:
    provisional = RuntimeRootSecurityPolicy(
        policy_version=_required_text(policy_version, "Policy version"),
        approved_base_path=_windows_path(
            approved_base_path,
            "Approved runtime-root base",
        ),
        writer_principal_sid=_sid(writer_principal_sid, "Writer principal"),
        interactive_principal_sids=_sorted_sids(
            interactive_principal_sids,
            "Interactive principals",
        ),
        broad_principal_sids=_sorted_sids(
            broad_principal_sids,
            "Broad principals",
        ),
        trusted_owner_sids=_sorted_sids(
            trusted_owner_sids,
            "Trusted owners",
        ),
        required_writer_rights=_rights(required_writer_rights),
    )
    result = replace(
        provisional,
        fingerprint=_fingerprint(asdict(provisional)),
    )
    validate_runtime_root_security_policy(result)
    return result


def build_runtime_root_security_snapshot(
    *,
    root_path: str,
    source_identity: str,
    observed_at: datetime,
    components: tuple[RuntimePathSecurityEvidence, ...],
) -> RuntimeRootSecuritySnapshot:
    normalized_components = tuple(_normalize_component(item) for item in components)
    provisional = RuntimeRootSecuritySnapshot(
        root_path=_windows_path(root_path, "Runtime root"),
        source_identity=_required_text(source_identity, "Snapshot source identity"),
        observed_at=_aware(observed_at, "Snapshot observation timestamp").isoformat(),
        components=normalized_components,
    )
    result = replace(
        provisional,
        fingerprint=_fingerprint(asdict(provisional)),
    )
    validate_runtime_root_security_snapshot(result)
    return result


def evaluate_runtime_root_security(
    *,
    policy: RuntimeRootSecurityPolicy,
    snapshot: RuntimeRootSecuritySnapshot,
) -> RuntimeRootSecurityResult:
    validate_runtime_root_security_policy(policy)
    validate_runtime_root_security_snapshot(snapshot)
    blockers: list[str] = []
    root = _windows_path(snapshot.root_path, "Runtime root")
    base = _windows_path(policy.approved_base_path, "Approved runtime-root base")
    if not _is_descendant(root, base) or root.casefold() == base.casefold():
        blockers.append("ROOT_OUTSIDE_APPROVED_DESCENDANT")

    expected_components = _component_paths(root)
    actual_components = tuple(item.path for item in snapshot.components)
    if tuple(item.casefold() for item in actual_components) != tuple(
        item.casefold() for item in expected_components
    ):
        blockers.append("PATH_COMPONENT_CHAIN_INCOMPLETE")

    required_principals = (
        policy.writer_principal_sid,
        *policy.interactive_principal_sids,
        *policy.broad_principal_sids,
    )
    for index, component in enumerate(snapshot.components):
        label = _component_label(index, len(snapshot.components))
        if not component.exists:
            blockers.append(f"{label}_MISSING")
        if not component.is_directory:
            blockers.append(f"{label}_NOT_DIRECTORY")
        if component.is_symlink or component.is_reparse_point:
            blockers.append(f"{label}_REPARSE_OR_SYMLINK")
        if component.owner_sid not in policy.trusted_owner_sids:
            blockers.append(f"{label}_OWNER_UNTRUSTED")
        access_by_sid = {
            item.principal_sid: set(item.effective_rights)
            for item in component.principal_access
        }
        for principal in required_principals:
            if principal not in access_by_sid:
                blockers.append(f"{label}_ACCESS_EVIDENCE_MISSING:{principal}")
        if index == len(snapshot.components) - 1:
            if not component.dacl_protected:
                blockers.append("ROOT_DACL_INHERITANCE_ENABLED")
            writer_rights = access_by_sid.get(policy.writer_principal_sid, set())
            missing = set(policy.required_writer_rights) - writer_rights
            if missing:
                blockers.append(
                    "WRITER_RIGHTS_MISSING:" + ",".join(sorted(missing))
                )
            security_control = writer_rights & {
                CHANGE_PERMISSIONS,
                TAKE_OWNERSHIP,
            }
            if security_control:
                blockers.append(
                    "WRITER_SECURITY_CONTROL_PRESENT:"
                    + ",".join(sorted(security_control))
                )
            for principal in (
                *policy.interactive_principal_sids,
                *policy.broad_principal_sids,
            ):
                unsafe = access_by_sid.get(principal, set()) & ROOT_MUTATION_RIGHTS
                if unsafe:
                    blockers.append(
                        f"ROOT_NONWRITER_MUTATION:{principal}:"
                        + ",".join(sorted(unsafe))
                    )
        else:
            for principal in (
                *policy.interactive_principal_sids,
                *policy.broad_principal_sids,
            ):
                unsafe = (
                    access_by_sid.get(principal, set())
                    & ANCESTOR_REPLACEMENT_RIGHTS
                )
                if unsafe:
                    blockers.append(
                        f"ANCESTOR_REPLACEMENT_ACCESS:{principal}:"
                        + ",".join(sorted(unsafe))
                    )

    blockers = list(dict.fromkeys(blockers))
    provisional = RuntimeRootSecurityResult(
        status=BLOCKED if blockers else CONTRACT_ELIGIBLE,
        root_path=root,
        policy_fingerprint=policy.fingerprint,
        snapshot_fingerprint=snapshot.fingerprint,
        blockers=tuple(blockers),
    )
    result = replace(
        provisional,
        fingerprint=_fingerprint(asdict(provisional)),
    )
    validate_runtime_root_security_result(result)
    return result


def validate_runtime_root_security_policy(
    policy: RuntimeRootSecurityPolicy,
) -> None:
    if (
        policy.schema_version != RUNTIME_ROOT_SECURITY_SCHEMA_VERSION
        or policy.profile != RUNTIME_ROOT_SECURITY_POLICY_PROFILE
    ):
        raise RuntimeRootSecurityError("Runtime-root policy schema is unsupported.")
    _required_text(policy.policy_version, "Policy version")
    if policy.approved_base_path != _windows_path(
        policy.approved_base_path,
        "Approved runtime-root base",
    ):
        raise RuntimeRootSecurityError("Approved runtime-root base is not canonical.")
    writer = _sid(policy.writer_principal_sid, "Writer principal")
    if writer != policy.writer_principal_sid:
        raise RuntimeRootSecurityError("Writer principal is not canonical.")
    for values, name in (
        (policy.interactive_principal_sids, "Interactive principals"),
        (policy.broad_principal_sids, "Broad principals"),
        (policy.trusted_owner_sids, "Trusted owners"),
    ):
        if values != _sorted_sids(values, name):
            raise RuntimeRootSecurityError(f"{name} are not sorted and unique.")
    if not policy.interactive_principal_sids:
        raise RuntimeRootSecurityError("At least one interactive principal is required.")
    if not policy.broad_principal_sids:
        raise RuntimeRootSecurityError("At least one broad principal is required.")
    if not policy.trusted_owner_sids:
        raise RuntimeRootSecurityError("At least one trusted owner is required.")
    denied = set(policy.interactive_principal_sids) | set(
        policy.broad_principal_sids
    )
    if writer in denied:
        raise RuntimeRootSecurityError(
            "Writer principal must be distinct from interactive and broad principals."
        )
    if writer in policy.trusted_owner_sids:
        raise RuntimeRootSecurityError(
            "Writer principal cannot own the protected runtime root."
        )
    if denied & set(policy.trusted_owner_sids):
        raise RuntimeRootSecurityError(
            "Nonwriter principals cannot be trusted runtime-root owners."
        )
    if set(policy.interactive_principal_sids) & set(policy.broad_principal_sids):
        raise RuntimeRootSecurityError(
            "Interactive and broad principal roles must be distinct."
        )
    if policy.required_writer_rights != _rights(policy.required_writer_rights):
        raise RuntimeRootSecurityError("Required writer rights are not canonical.")
    if not set(DEFAULT_WRITER_RIGHTS).issubset(policy.required_writer_rights):
        raise RuntimeRootSecurityError("Required writer rights are incomplete.")
    if policy.fingerprint != _fingerprint(
        asdict(replace(policy, fingerprint=""))
    ):
        raise RuntimeRootSecurityError("Runtime-root policy fingerprint is invalid.")


def validate_runtime_root_security_snapshot(
    snapshot: RuntimeRootSecuritySnapshot,
) -> None:
    if (
        snapshot.schema_version != RUNTIME_ROOT_SECURITY_SCHEMA_VERSION
        or snapshot.profile != RUNTIME_ROOT_SECURITY_SNAPSHOT_PROFILE
    ):
        raise RuntimeRootSecurityError(
            "Runtime-root security snapshot schema is unsupported."
        )
    if snapshot.root_path != _windows_path(snapshot.root_path, "Runtime root"):
        raise RuntimeRootSecurityError("Runtime-root snapshot path is not canonical.")
    _required_text(snapshot.source_identity, "Snapshot source identity")
    _timestamp(snapshot.observed_at, "Snapshot observation timestamp")
    if not snapshot.components:
        raise RuntimeRootSecurityError("Runtime-root component evidence is missing.")
    normalized = tuple(_normalize_component(item) for item in snapshot.components)
    if normalized != snapshot.components:
        raise RuntimeRootSecurityError(
            "Runtime-root component evidence is not canonical."
        )
    if len({item.path.casefold() for item in snapshot.components}) != len(
        snapshot.components
    ):
        raise RuntimeRootSecurityError("Runtime-root path components are duplicated.")
    if snapshot.fingerprint != _fingerprint(
        asdict(replace(snapshot, fingerprint=""))
    ):
        raise RuntimeRootSecurityError(
            "Runtime-root security snapshot fingerprint is invalid."
        )


def validate_runtime_root_security_result(result: RuntimeRootSecurityResult) -> None:
    if (
        result.schema_version != RUNTIME_ROOT_SECURITY_SCHEMA_VERSION
        or result.profile != RUNTIME_ROOT_SECURITY_RESULT_PROFILE
        or result.authority != RUNTIME_ROOT_SECURITY_AUTHORITY
    ):
        raise RuntimeRootSecurityError("Runtime-root result identity is unsupported.")
    if result.status not in ROOT_SECURITY_STATUSES:
        raise RuntimeRootSecurityError("Runtime-root result status is unsupported.")
    if result.activation_authorized:
        raise RuntimeRootSecurityError(
            "Dormant runtime-root contract cannot authorize activation."
        )
    if (result.status == CONTRACT_ELIGIBLE) != (not result.blockers):
        raise RuntimeRootSecurityError(
            "Runtime-root result status contradicts its blockers."
        )
    _windows_path(result.root_path, "Runtime root")
    _sha256(result.policy_fingerprint, "Policy fingerprint")
    _sha256(result.snapshot_fingerprint, "Snapshot fingerprint")
    if len(result.blockers) != len(set(result.blockers)):
        raise RuntimeRootSecurityError("Runtime-root result blockers are duplicated.")
    if result.fingerprint != _fingerprint(
        asdict(replace(result, fingerprint=""))
    ):
        raise RuntimeRootSecurityError("Runtime-root result fingerprint is invalid.")


def _normalize_component(
    component: RuntimePathSecurityEvidence,
) -> RuntimePathSecurityEvidence:
    access = tuple(
        RuntimePrincipalAccess(
            principal_sid=_sid(item.principal_sid, "Access principal"),
            effective_rights=_rights(item.effective_rights, allow_empty=True),
        )
        for item in component.principal_access
    )
    access = tuple(sorted(access, key=lambda item: item.principal_sid))
    if len({item.principal_sid for item in access}) != len(access):
        raise RuntimeRootSecurityError("Effective-access principals are duplicated.")
    return RuntimePathSecurityEvidence(
        path=_windows_path(component.path, "Path component"),
        exists=_boolean(component.exists, "Path existence"),
        is_directory=_boolean(component.is_directory, "Path directory state"),
        is_symlink=_boolean(component.is_symlink, "Path symlink state"),
        is_reparse_point=_boolean(
            component.is_reparse_point,
            "Path reparse state",
        ),
        owner_sid=_sid(component.owner_sid, "Path owner"),
        dacl_protected=_boolean(component.dacl_protected, "DACL protection state"),
        principal_access=access,
    )


def _component_paths(root_path: str) -> tuple[str, ...]:
    root = PureWindowsPath(root_path)
    current = PureWindowsPath(root.anchor)
    paths = [str(current)]
    for part in root.parts[1:]:
        current = current / part
        paths.append(str(current))
    return tuple(paths)


def _component_label(index: int, count: int) -> str:
    return "ROOT" if index == count - 1 else f"ANCESTOR_{index}"


def _windows_path(value: str, name: str) -> str:
    text = _required_text(value, name)
    path = PureWindowsPath(text)
    if not path.is_absolute() or not path.drive or path.drive.startswith("\\"):
        raise RuntimeRootSecurityError(f"{name} must be an absolute local path.")
    if ".." in path.parts:
        raise RuntimeRootSecurityError(f"{name} cannot contain parent traversal.")
    return str(path)


def _is_descendant(path: str, base: str) -> bool:
    path_key = path.casefold().rstrip("\\")
    base_key = base.casefold().rstrip("\\")
    return path_key == base_key or path_key.startswith(base_key + "\\")


def _sid(value: str, name: str) -> str:
    text = _required_text(value, name).upper()
    parts = text.split("-")
    if len(parts) < 4 or parts[0] != "S" or any(
        not part.isdigit() for part in parts[1:]
    ):
        raise RuntimeRootSecurityError(f"{name} is not a canonical SID.")
    return text


def _sorted_sids(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    normalized = tuple(sorted(_sid(value, name) for value in values))
    if len(normalized) != len(set(normalized)):
        raise RuntimeRootSecurityError(f"{name} contain duplicate SIDs.")
    return normalized


def _rights(
    values: tuple[str, ...],
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(sorted(str(value).strip().upper() for value in values))
    if (not normalized and not allow_empty) or any(
        value not in ACCESS_RIGHTS for value in normalized
    ):
        raise RuntimeRootSecurityError("Effective access rights are unsupported.")
    if len(normalized) != len(set(normalized)):
        raise RuntimeRootSecurityError("Effective access rights are duplicated.")
    return normalized


def _required_text(value: object, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise RuntimeRootSecurityError(f"{name} is required.")
    return text


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeRootSecurityError(f"{name} must be boolean.")
    return value


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeRootSecurityError(f"{name} must be timezone-aware.")
    return value


def _timestamp(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise RuntimeRootSecurityError(f"{name} is invalid.") from exc
    return _aware(parsed, name)


def _sha256(value: str, name: str) -> str:
    text = str(value).strip().lower()
    if len(text) != 64 or any(item not in "0123456789abcdef" for item in text):
        raise RuntimeRootSecurityError(f"{name} is invalid.")
    return text


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
