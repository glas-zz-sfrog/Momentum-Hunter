"""Dormant contract for isolating the installed event-runtime writer.

The evaluator compares supplied architecture facts. It does not inspect Windows,
create users, read credentials, provision ACLs, start a process, or authorize an
installed runtime.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace


AUTOMATION_SERVICE = "AUTOMATION_SERVICE"
ENGINE_HOST = "ENGINE_HOST"
WPF_FRONTEND = "WPF_FRONTEND"
EVIDENCE_WRITER = "EVIDENCE_WRITER"
PROCESS_ROLES = frozenset(
    {AUTOMATION_SERVICE, ENGINE_HOST, WPF_FRONTEND, EVIDENCE_WRITER}
)

DISTINCT_ENGINE_HOST_PRINCIPAL = "DISTINCT_ENGINE_HOST_PRINCIPAL"
DEDICATED_EVIDENCE_WRITER = "DEDICATED_EVIDENCE_WRITER"
SAME_PRINCIPAL_LOGICAL_ONLY = "SAME_PRINCIPAL_LOGICAL_ONLY"
BOUNDARY_KINDS = frozenset(
    {
        DISTINCT_ENGINE_HOST_PRINCIPAL,
        DEDICATED_EVIDENCE_WRITER,
        SAME_PRINCIPAL_LOGICAL_ONLY,
    }
)

DIRECT_FILESYSTEM = "DIRECT_FILESYSTEM"
INHERITED_HANDLE = "INHERITED_HANDLE"
NAMED_PIPE = "NAMED_PIPE"
CHANNEL_KINDS = frozenset({DIRECT_FILESYSTEM, INHERITED_HANDLE, NAMED_PIPE})

WINDOWS_PRINCIPAL = "WINDOWS_PRINCIPAL"
INHERITED_UNFORGEABLE_CAPABILITY = "INHERITED_UNFORGEABLE_CAPABILITY"
SHARED_SECRET = "SHARED_SECRET"
NO_AUTHENTICATION = "NO_AUTHENTICATION"
CHANNEL_AUTHENTICATION_KINDS = frozenset(
    {WINDOWS_PRINCIPAL, INHERITED_UNFORGEABLE_CAPABILITY, SHARED_SECRET}
)
CREDENTIAL_BROKER_AUTHENTICATION_KINDS = frozenset(
    {*CHANNEL_AUTHENTICATION_KINDS, NO_AUTHENTICATION}
)

NO_CREDENTIALS = "NO_CREDENTIALS"
DPAPI_CURRENT_USER = "DPAPI_CURRENT_USER"
SEPARATELY_PROVISIONED_DPAPI = "SEPARATELY_PROVISIONED_DPAPI"
BROKERED_EPHEMERAL = "BROKERED_EPHEMERAL"
CREDENTIAL_ACCESS_KINDS = frozenset(
    {
        NO_CREDENTIALS,
        DPAPI_CURRENT_USER,
        SEPARATELY_PROVISIONED_DPAPI,
        BROKERED_EPHEMERAL,
    }
)

CONTRACT_FEASIBLE_PENDING_PROOF = "CONTRACT_FEASIBLE_PENDING_PROOF"
BLOCKED = "BLOCKED"
RESULT_STATUSES = frozenset({CONTRACT_FEASIBLE_PENDING_PROOF, BLOCKED})

RUNTIME_WRITER_BOUNDARY_SCHEMA_VERSION = 1
RUNTIME_WRITER_BOUNDARY_POLICY_PROFILE = "runtime-writer-boundary-policy-v1"
RUNTIME_WRITER_BOUNDARY_PROPOSAL_PROFILE = "runtime-writer-boundary-proposal-v1"
RUNTIME_WRITER_BOUNDARY_RESULT_PROFILE = "runtime-writer-boundary-result-v1"
RUNTIME_WRITER_BOUNDARY_AUTHORITY = "DORMANT_CONTRACT_ONLY"

REQUIRED_INSTALLED_PROOFS = (
    "ELEVATED_EFFECTIVE_ACCESS_PROOF",
    "PROCESS_IDENTITY_AND_PARENTAGE_PROOF",
    "CREDENTIAL_ACCESS_AND_REDACTION_PROOF",
    "CHANNEL_AUTHENTICATION_AND_REPLAY_PROOF",
    "INTERACTIVE_PROCESS_HANDLE_ISOLATION_PROOF",
    "RESTART_AND_CRASH_RECOVERY_PROOF",
    "WPF_NONMUTATION_PROOF",
)


class RuntimeWriterBoundaryError(ValueError):
    """Raised when supplied writer-boundary evidence is malformed."""


@dataclass(frozen=True)
class RuntimeBoundaryProcess:
    role: str
    process_identity: str
    principal_sid: str
    interactive_session: bool
    can_read_runtime_root: bool
    can_write_runtime_root: bool
    requires_provider_credentials: bool
    credential_access: str


@dataclass(frozen=True)
class RuntimeWriterBoundaryPolicy:
    policy_version: str
    current_secret_owner_sid: str
    approved_boundary_kinds: tuple[str, ...]
    required_root_security_policy_fingerprint: str
    schema_version: int = RUNTIME_WRITER_BOUNDARY_SCHEMA_VERSION
    profile: str = RUNTIME_WRITER_BOUNDARY_POLICY_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RuntimeWriterBoundaryProposal:
    proposal_version: str
    boundary_kind: str
    source_identity: str
    processes: tuple[RuntimeBoundaryProcess, ...]
    engine_to_writer_channel: str
    channel_authentication: str
    channel_capability_persisted: bool
    channel_capability_visible_to_interactive_user: bool
    credential_broker_present: bool
    credential_broker_authentication: str
    credential_broker_capability_persisted: bool
    credential_broker_capability_visible_to_interactive_user: bool
    credential_reprovisioning_approved: bool
    credential_material_persisted_for_writer: bool
    credential_material_visible_to_wpf: bool
    root_security_policy_fingerprint: str
    schema_version: int = RUNTIME_WRITER_BOUNDARY_SCHEMA_VERSION
    profile: str = RUNTIME_WRITER_BOUNDARY_PROPOSAL_PROFILE
    fingerprint: str = ""


@dataclass(frozen=True)
class RuntimeWriterBoundaryResult:
    status: str
    boundary_kind: str
    policy_fingerprint: str
    proposal_fingerprint: str
    blockers: tuple[str, ...]
    required_installed_proofs: tuple[str, ...] = field(
        default_factory=lambda: REQUIRED_INSTALLED_PROOFS
    )
    activation_authorized: bool = False
    authority: str = RUNTIME_WRITER_BOUNDARY_AUTHORITY
    schema_version: int = RUNTIME_WRITER_BOUNDARY_SCHEMA_VERSION
    profile: str = RUNTIME_WRITER_BOUNDARY_RESULT_PROFILE
    fingerprint: str = ""


def build_runtime_writer_boundary_policy(
    *,
    policy_version: str,
    current_secret_owner_sid: str,
    required_root_security_policy_fingerprint: str,
    approved_boundary_kinds: tuple[str, ...] = (
        DISTINCT_ENGINE_HOST_PRINCIPAL,
        DEDICATED_EVIDENCE_WRITER,
    ),
) -> RuntimeWriterBoundaryPolicy:
    approved = tuple(sorted(set(approved_boundary_kinds)))
    provisional = RuntimeWriterBoundaryPolicy(
        policy_version=_required_text(policy_version, "Policy version"),
        current_secret_owner_sid=_sid(current_secret_owner_sid, "Secret owner"),
        approved_boundary_kinds=approved,
        required_root_security_policy_fingerprint=_sha256(
            required_root_security_policy_fingerprint,
            "Root-security policy fingerprint",
        ),
    )
    result = replace(provisional, fingerprint=_fingerprint(asdict(provisional)))
    validate_runtime_writer_boundary_policy(result)
    return result


def build_runtime_writer_boundary_proposal(
    *,
    proposal_version: str,
    boundary_kind: str,
    source_identity: str,
    processes: tuple[RuntimeBoundaryProcess, ...],
    engine_to_writer_channel: str,
    channel_authentication: str,
    channel_capability_persisted: bool,
    channel_capability_visible_to_interactive_user: bool,
    credential_broker_present: bool,
    credential_broker_authentication: str,
    credential_broker_capability_persisted: bool,
    credential_broker_capability_visible_to_interactive_user: bool,
    credential_reprovisioning_approved: bool,
    credential_material_persisted_for_writer: bool,
    credential_material_visible_to_wpf: bool,
    root_security_policy_fingerprint: str,
) -> RuntimeWriterBoundaryProposal:
    normalized_processes = tuple(
        sorted(
            (_normalize_process(process) for process in processes),
            key=lambda process: process.role,
        )
    )
    provisional = RuntimeWriterBoundaryProposal(
        proposal_version=_required_text(proposal_version, "Proposal version"),
        boundary_kind=_choice(boundary_kind, BOUNDARY_KINDS, "Boundary kind"),
        source_identity=_required_text(source_identity, "Source identity"),
        processes=normalized_processes,
        engine_to_writer_channel=_choice(
            engine_to_writer_channel,
            CHANNEL_KINDS,
            "Engine-to-writer channel",
        ),
        channel_authentication=_choice(
            channel_authentication,
            CHANNEL_AUTHENTICATION_KINDS,
            "Channel authentication",
        ),
        channel_capability_persisted=_boolean(
            channel_capability_persisted,
            "Channel capability persisted",
        ),
        channel_capability_visible_to_interactive_user=_boolean(
            channel_capability_visible_to_interactive_user,
            "Channel capability interactive visibility",
        ),
        credential_broker_present=_boolean(
            credential_broker_present,
            "Credential broker presence",
        ),
        credential_broker_authentication=_choice(
            credential_broker_authentication,
            CREDENTIAL_BROKER_AUTHENTICATION_KINDS,
            "Credential broker authentication",
        ),
        credential_broker_capability_persisted=_boolean(
            credential_broker_capability_persisted,
            "Credential broker capability persistence",
        ),
        credential_broker_capability_visible_to_interactive_user=_boolean(
            credential_broker_capability_visible_to_interactive_user,
            "Credential broker capability interactive visibility",
        ),
        credential_reprovisioning_approved=_boolean(
            credential_reprovisioning_approved,
            "Credential reprovisioning approval",
        ),
        credential_material_persisted_for_writer=_boolean(
            credential_material_persisted_for_writer,
            "Writer credential persistence",
        ),
        credential_material_visible_to_wpf=_boolean(
            credential_material_visible_to_wpf,
            "WPF credential visibility",
        ),
        root_security_policy_fingerprint=_sha256(
            root_security_policy_fingerprint,
            "Root-security policy fingerprint",
        ),
    )
    result = replace(provisional, fingerprint=_fingerprint(asdict(provisional)))
    validate_runtime_writer_boundary_proposal(result)
    return result


def evaluate_runtime_writer_boundary(
    *,
    policy: RuntimeWriterBoundaryPolicy,
    proposal: RuntimeWriterBoundaryProposal,
) -> RuntimeWriterBoundaryResult:
    validate_runtime_writer_boundary_policy(policy)
    validate_runtime_writer_boundary_proposal(proposal)
    blockers: list[str] = []

    if proposal.boundary_kind not in policy.approved_boundary_kinds:
        blockers.append("BOUNDARY_KIND_NOT_APPROVED")
    if (
        proposal.root_security_policy_fingerprint
        != policy.required_root_security_policy_fingerprint
    ):
        blockers.append("ROOT_SECURITY_POLICY_MISMATCH")

    by_role = {process.role: process for process in proposal.processes}
    service = by_role[AUTOMATION_SERVICE]
    engine = by_role[ENGINE_HOST]
    wpf = by_role[WPF_FRONTEND]
    writer = by_role[EVIDENCE_WRITER]

    if service.can_read_runtime_root or service.can_write_runtime_root:
        blockers.append("AUTOMATION_SERVICE_NOT_SUPERVISOR_ONLY")
    if service.requires_provider_credentials or service.credential_access != NO_CREDENTIALS:
        blockers.append("AUTOMATION_SERVICE_PROVIDER_CREDENTIAL_ACCESS")
    if wpf.can_read_runtime_root or wpf.can_write_runtime_root:
        blockers.append("WPF_DIRECT_RUNTIME_ROOT_ACCESS")
    if wpf.requires_provider_credentials or wpf.credential_access != NO_CREDENTIALS:
        blockers.append("WPF_PROVIDER_CREDENTIAL_ACCESS")
    if writer.interactive_session:
        blockers.append("WRITER_IN_INTERACTIVE_SESSION")
    if not writer.can_read_runtime_root or not writer.can_write_runtime_root:
        blockers.append("WRITER_ROOT_ACCESS_INCOMPLETE")
    if writer.principal_sid in {service.principal_sid, wpf.principal_sid}:
        blockers.append("WRITER_PRINCIPAL_NOT_ISOLATED")

    writer_processes = {
        process.process_identity
        for process in proposal.processes
        if process.can_write_runtime_root
    }
    if writer_processes != {writer.process_identity}:
        blockers.append("MULTIPLE_OR_CONTRADICTORY_ROOT_WRITERS")

    if proposal.boundary_kind == SAME_PRINCIPAL_LOGICAL_ONLY:
        blockers.append("SAME_PRINCIPAL_LOGICAL_BOUNDARY_INSUFFICIENT")
    elif proposal.boundary_kind == DISTINCT_ENGINE_HOST_PRINCIPAL:
        _evaluate_distinct_engine_host(
            proposal=proposal,
            engine=engine,
            writer=writer,
            wpf=wpf,
            blockers=blockers,
        )
    elif proposal.boundary_kind == DEDICATED_EVIDENCE_WRITER:
        _evaluate_dedicated_writer(
            proposal=proposal,
            engine=engine,
            writer=writer,
            wpf=wpf,
            blockers=blockers,
        )

    _evaluate_credentials(
        policy=policy,
        proposal=proposal,
        engine=engine,
        writer=writer,
        blockers=blockers,
    )

    if proposal.credential_material_persisted_for_writer:
        blockers.append("WRITER_CREDENTIAL_MATERIAL_PERSISTED")
    if proposal.credential_material_visible_to_wpf:
        blockers.append("CREDENTIAL_MATERIAL_VISIBLE_TO_WPF")

    blockers = list(dict.fromkeys(blockers))
    provisional = RuntimeWriterBoundaryResult(
        status=BLOCKED if blockers else CONTRACT_FEASIBLE_PENDING_PROOF,
        boundary_kind=proposal.boundary_kind,
        policy_fingerprint=policy.fingerprint,
        proposal_fingerprint=proposal.fingerprint,
        blockers=tuple(blockers),
    )
    result = replace(provisional, fingerprint=_fingerprint(asdict(provisional)))
    validate_runtime_writer_boundary_result(result)
    return result


def validate_runtime_writer_boundary_policy(
    policy: RuntimeWriterBoundaryPolicy,
) -> None:
    if policy.schema_version != RUNTIME_WRITER_BOUNDARY_SCHEMA_VERSION:
        raise RuntimeWriterBoundaryError("Writer-boundary policy schema is unsupported.")
    if policy.profile != RUNTIME_WRITER_BOUNDARY_POLICY_PROFILE:
        raise RuntimeWriterBoundaryError("Writer-boundary policy profile is unsupported.")
    _required_text(policy.policy_version, "Policy version")
    _sid(policy.current_secret_owner_sid, "Secret owner")
    if not policy.approved_boundary_kinds:
        raise RuntimeWriterBoundaryError("At least one boundary kind must be approved.")
    if tuple(sorted(set(policy.approved_boundary_kinds))) != policy.approved_boundary_kinds:
        raise RuntimeWriterBoundaryError("Approved boundary kinds must be unique and sorted.")
    for value in policy.approved_boundary_kinds:
        _choice(value, BOUNDARY_KINDS, "Approved boundary kind")
    _sha256(
        policy.required_root_security_policy_fingerprint,
        "Root-security policy fingerprint",
    )
    _verify_fingerprint(policy, "Writer-boundary policy")


def validate_runtime_writer_boundary_proposal(
    proposal: RuntimeWriterBoundaryProposal,
) -> None:
    if proposal.schema_version != RUNTIME_WRITER_BOUNDARY_SCHEMA_VERSION:
        raise RuntimeWriterBoundaryError("Writer-boundary proposal schema is unsupported.")
    if proposal.profile != RUNTIME_WRITER_BOUNDARY_PROPOSAL_PROFILE:
        raise RuntimeWriterBoundaryError("Writer-boundary proposal profile is unsupported.")
    _required_text(proposal.proposal_version, "Proposal version")
    _required_text(proposal.source_identity, "Source identity")
    _choice(proposal.boundary_kind, BOUNDARY_KINDS, "Boundary kind")
    _choice(proposal.engine_to_writer_channel, CHANNEL_KINDS, "Channel")
    _choice(
        proposal.channel_authentication,
        CHANNEL_AUTHENTICATION_KINDS,
        "Channel authentication",
    )
    for name in (
        "channel_capability_persisted",
        "channel_capability_visible_to_interactive_user",
        "credential_broker_present",
        "credential_broker_capability_persisted",
        "credential_broker_capability_visible_to_interactive_user",
        "credential_reprovisioning_approved",
        "credential_material_persisted_for_writer",
        "credential_material_visible_to_wpf",
    ):
        _boolean(getattr(proposal, name), name)
    _choice(
        proposal.credential_broker_authentication,
        CREDENTIAL_BROKER_AUTHENTICATION_KINDS,
        "Credential broker authentication",
    )
    _sha256(
        proposal.root_security_policy_fingerprint,
        "Root-security policy fingerprint",
    )
    if tuple(sorted(proposal.processes, key=lambda item: item.role)) != proposal.processes:
        raise RuntimeWriterBoundaryError("Boundary processes must be sorted by role.")
    if {process.role for process in proposal.processes} != PROCESS_ROLES:
        raise RuntimeWriterBoundaryError("Boundary proposal must contain each required role once.")
    if len(proposal.processes) != len(PROCESS_ROLES):
        raise RuntimeWriterBoundaryError("Boundary proposal contains a duplicate role.")
    for process in proposal.processes:
        _validate_process(process)
    _validate_shared_process_facts(proposal.processes)
    _verify_fingerprint(proposal, "Writer-boundary proposal")


def validate_runtime_writer_boundary_result(result: RuntimeWriterBoundaryResult) -> None:
    if result.schema_version != RUNTIME_WRITER_BOUNDARY_SCHEMA_VERSION:
        raise RuntimeWriterBoundaryError("Writer-boundary result schema is unsupported.")
    if result.profile != RUNTIME_WRITER_BOUNDARY_RESULT_PROFILE:
        raise RuntimeWriterBoundaryError("Writer-boundary result profile is unsupported.")
    _choice(result.status, RESULT_STATUSES, "Writer-boundary status")
    _choice(result.boundary_kind, BOUNDARY_KINDS, "Boundary kind")
    _sha256(result.policy_fingerprint, "Policy fingerprint")
    _sha256(result.proposal_fingerprint, "Proposal fingerprint")
    if tuple(dict.fromkeys(result.blockers)) != result.blockers:
        raise RuntimeWriterBoundaryError("Writer-boundary blockers must be unique.")
    if result.status == BLOCKED and not result.blockers:
        raise RuntimeWriterBoundaryError("Blocked writer-boundary result needs a blocker.")
    if result.status == CONTRACT_FEASIBLE_PENDING_PROOF and result.blockers:
        raise RuntimeWriterBoundaryError("Feasible writer-boundary result cannot have blockers.")
    if result.required_installed_proofs != REQUIRED_INSTALLED_PROOFS:
        raise RuntimeWriterBoundaryError("Installed proof requirements are incomplete.")
    if result.activation_authorized:
        raise RuntimeWriterBoundaryError("Writer-boundary contract cannot authorize activation.")
    if result.authority != RUNTIME_WRITER_BOUNDARY_AUTHORITY:
        raise RuntimeWriterBoundaryError("Writer-boundary authority is invalid.")
    _verify_fingerprint(result, "Writer-boundary result")


def _evaluate_distinct_engine_host(
    *,
    proposal: RuntimeWriterBoundaryProposal,
    engine: RuntimeBoundaryProcess,
    writer: RuntimeBoundaryProcess,
    wpf: RuntimeBoundaryProcess,
    blockers: list[str],
) -> None:
    if engine.process_identity != writer.process_identity:
        blockers.append("DISTINCT_ENGINE_HOST_WRITER_NOT_COLOCATED")
    if engine.principal_sid != writer.principal_sid:
        blockers.append("DISTINCT_ENGINE_HOST_WRITER_SID_MISMATCH")
    if engine.principal_sid == wpf.principal_sid:
        blockers.append("ENGINE_HOST_PRINCIPAL_NOT_DISTINCT_FROM_WPF")
    if not engine.can_write_runtime_root:
        blockers.append("DISTINCT_ENGINE_HOST_CANNOT_WRITE_ROOT")
    if proposal.engine_to_writer_channel != DIRECT_FILESYSTEM:
        blockers.append("DISTINCT_ENGINE_HOST_CHANNEL_NOT_DIRECT_FILESYSTEM")
    if proposal.channel_authentication != WINDOWS_PRINCIPAL:
        blockers.append("DISTINCT_ENGINE_HOST_AUTH_NOT_WINDOWS_PRINCIPAL")


def _evaluate_dedicated_writer(
    *,
    proposal: RuntimeWriterBoundaryProposal,
    engine: RuntimeBoundaryProcess,
    writer: RuntimeBoundaryProcess,
    wpf: RuntimeBoundaryProcess,
    blockers: list[str],
) -> None:
    if engine.process_identity == writer.process_identity:
        blockers.append("DEDICATED_WRITER_NOT_PROCESS_ISOLATED")
    if engine.principal_sid == writer.principal_sid:
        blockers.append("DEDICATED_WRITER_PRINCIPAL_NOT_ISOLATED_FROM_ENGINE")
    if engine.can_read_runtime_root or engine.can_write_runtime_root:
        blockers.append("ENGINE_HOST_BYPASSES_DEDICATED_WRITER")
    if writer.requires_provider_credentials or writer.credential_access != NO_CREDENTIALS:
        blockers.append("DEDICATED_WRITER_PROVIDER_CREDENTIAL_ACCESS")
    if proposal.engine_to_writer_channel == DIRECT_FILESYSTEM:
        blockers.append("DEDICATED_WRITER_DIRECT_FILESYSTEM_CHANNEL")
    if proposal.channel_authentication == SHARED_SECRET:
        blockers.append("PERSISTABLE_SHARED_SECRET_CHANNEL_FORBIDDEN")
    if proposal.channel_capability_persisted:
        blockers.append("CHANNEL_CAPABILITY_PERSISTED")
    if proposal.channel_capability_visible_to_interactive_user:
        blockers.append("CHANNEL_CAPABILITY_VISIBLE_TO_INTERACTIVE_USER")
    if (
        proposal.engine_to_writer_channel == NAMED_PIPE
        and proposal.channel_authentication == WINDOWS_PRINCIPAL
        and engine.principal_sid == wpf.principal_sid
    ):
        blockers.append("NAMED_PIPE_SID_AUTH_CANNOT_DISTINGUISH_WPF")
    if (
        proposal.engine_to_writer_channel == INHERITED_HANDLE
        and proposal.channel_authentication != INHERITED_UNFORGEABLE_CAPABILITY
    ):
        blockers.append("INHERITED_HANDLE_REQUIRES_UNFORGEABLE_CAPABILITY")


def _evaluate_credentials(
    *,
    policy: RuntimeWriterBoundaryPolicy,
    proposal: RuntimeWriterBoundaryProposal,
    engine: RuntimeBoundaryProcess,
    writer: RuntimeBoundaryProcess,
    blockers: list[str],
) -> None:
    if engine.credential_access != BROKERED_EPHEMERAL and (
        proposal.credential_broker_present
        or proposal.credential_broker_authentication != NO_AUTHENTICATION
        or proposal.credential_broker_capability_persisted
        or proposal.credential_broker_capability_visible_to_interactive_user
    ):
        blockers.append("CREDENTIAL_BROKER_CONFIGURATION_UNEXPECTED")
    if (
        engine.credential_access != SEPARATELY_PROVISIONED_DPAPI
        and proposal.credential_reprovisioning_approved
    ):
        blockers.append("CREDENTIAL_REPROVISIONING_CONFIGURATION_UNEXPECTED")
    if not engine.requires_provider_credentials:
        if engine.credential_access != NO_CREDENTIALS:
            blockers.append("ENGINE_CREDENTIAL_ACCESS_WITHOUT_REQUIREMENT")
        return
    if engine.credential_access == NO_CREDENTIALS:
        blockers.append("ENGINE_PROVIDER_CREDENTIALS_UNAVAILABLE")
    elif engine.credential_access == DPAPI_CURRENT_USER:
        if engine.principal_sid != policy.current_secret_owner_sid:
            blockers.append("DPAPI_CURRENT_USER_OWNER_MISMATCH")
    elif engine.credential_access == SEPARATELY_PROVISIONED_DPAPI:
        if not proposal.credential_reprovisioning_approved:
            blockers.append("CREDENTIAL_REPROVISIONING_NOT_APPROVED")
    elif engine.credential_access == BROKERED_EPHEMERAL:
        if not proposal.credential_broker_present:
            blockers.append("CREDENTIAL_BROKER_MISSING")
        if proposal.credential_broker_authentication not in {
            INHERITED_UNFORGEABLE_CAPABILITY,
            WINDOWS_PRINCIPAL,
        }:
            blockers.append("CREDENTIAL_BROKER_CHANNEL_NOT_AUTHENTICATED")
        if (
            proposal.credential_broker_authentication == WINDOWS_PRINCIPAL
            and engine.principal_sid == policy.current_secret_owner_sid
        ):
            blockers.append("CREDENTIAL_BROKER_SID_AUTH_CANNOT_DISTINGUISH_WPF")
        if proposal.credential_broker_capability_persisted:
            blockers.append("CREDENTIAL_BROKER_CAPABILITY_PERSISTED")
        if proposal.credential_broker_capability_visible_to_interactive_user:
            blockers.append("CREDENTIAL_BROKER_CAPABILITY_VISIBLE_TO_INTERACTIVE_USER")
        if engine.principal_sid == writer.principal_sid and writer.requires_provider_credentials:
            blockers.append("WRITER_UNNECESSARILY_RECEIVES_PROVIDER_CREDENTIALS")


def _normalize_process(process: RuntimeBoundaryProcess) -> RuntimeBoundaryProcess:
    normalized = RuntimeBoundaryProcess(
        role=_choice(process.role, PROCESS_ROLES, "Process role"),
        process_identity=_required_text(process.process_identity, "Process identity"),
        principal_sid=_sid(process.principal_sid, "Process principal"),
        interactive_session=_boolean(process.interactive_session, "Interactive session"),
        can_read_runtime_root=_boolean(process.can_read_runtime_root, "Root read"),
        can_write_runtime_root=_boolean(process.can_write_runtime_root, "Root write"),
        requires_provider_credentials=_boolean(
            process.requires_provider_credentials,
            "Provider credential requirement",
        ),
        credential_access=_choice(
            process.credential_access,
            CREDENTIAL_ACCESS_KINDS,
            "Credential access",
        ),
    )
    _validate_process(normalized)
    return normalized


def _validate_process(process: RuntimeBoundaryProcess) -> None:
    _choice(process.role, PROCESS_ROLES, "Process role")
    _required_text(process.process_identity, "Process identity")
    _sid(process.principal_sid, "Process principal")
    _choice(process.credential_access, CREDENTIAL_ACCESS_KINDS, "Credential access")
    for name in (
        "interactive_session",
        "can_read_runtime_root",
        "can_write_runtime_root",
        "requires_provider_credentials",
    ):
        _boolean(getattr(process, name), name)
    if process.can_write_runtime_root and not process.can_read_runtime_root:
        raise RuntimeWriterBoundaryError("A root writer must also have root read access.")
    if process.role == WPF_FRONTEND and not process.interactive_session:
        raise RuntimeWriterBoundaryError("WPF frontend must be interactive.")
    if process.role != WPF_FRONTEND and process.interactive_session:
        raise RuntimeWriterBoundaryError("Only WPF frontend may be interactive.")


def _validate_shared_process_facts(processes: tuple[RuntimeBoundaryProcess, ...]) -> None:
    grouped: dict[str, list[RuntimeBoundaryProcess]] = {}
    for process in processes:
        grouped.setdefault(process.process_identity, []).append(process)
    for group in grouped.values():
        principals = {item.principal_sid for item in group}
        sessions = {item.interactive_session for item in group}
        reads = {item.can_read_runtime_root for item in group}
        writes = {item.can_write_runtime_root for item in group}
        credentials = {item.credential_access for item in group}
        requirements = {item.requires_provider_credentials for item in group}
        facts = (principals, sessions, reads, writes, credentials, requirements)
        if any(len(values) != 1 for values in facts):
            raise RuntimeWriterBoundaryError(
                "Roles sharing a process identity must report identical process facts."
            )


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeWriterBoundaryError(f"{label} must be nonempty text.")
    return value.strip()


def _sid(value: object, label: str) -> str:
    text = _required_text(value, label)
    parts = text.split("-")
    if len(parts) < 3 or parts[0].upper() != "S" or not all(
        part.isdigit() for part in parts[1:]
    ):
        raise RuntimeWriterBoundaryError(f"{label} must be a Windows SID.")
    return "S-" + "-".join(parts[1:])


def _sha256(value: object, label: str) -> str:
    text = _required_text(value, label).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise RuntimeWriterBoundaryError(f"{label} must be a SHA-256 value.")
    return text


def _choice(value: object, choices: frozenset[str], label: str) -> str:
    text = _required_text(value, label)
    if text not in choices:
        raise RuntimeWriterBoundaryError(f"{label} is unsupported: {text}.")
    return text


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimeWriterBoundaryError(f"{label} must be boolean.")
    return value


def _fingerprint(payload: dict[str, object]) -> str:
    payload = dict(payload)
    payload["fingerprint"] = ""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _verify_fingerprint(value: object, label: str) -> None:
    fingerprint = getattr(value, "fingerprint", "")
    _sha256(fingerprint, f"{label} fingerprint")
    if fingerprint != _fingerprint(asdict(value)):
        raise RuntimeWriterBoundaryError(f"{label} fingerprint is invalid.")
