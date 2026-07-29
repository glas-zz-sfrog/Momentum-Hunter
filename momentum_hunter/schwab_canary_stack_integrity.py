from __future__ import annotations

"""Content-addressed integration checks for the nontransmitting canary stack."""

import ast
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Final, Mapping, Sequence


CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V1: Final = (
    "SCHWAB_CANARY_STACK_INTEGRITY_V1"
)
CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V2: Final = (
    "SCHWAB_CANARY_STACK_INTEGRITY_V2"
)
CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V3: Final = (
    "SCHWAB_CANARY_STACK_INTEGRITY_V3"
)
CANARY_STACK_INTEGRITY_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_STACK_INTEGRITY_V4"
)
CANARY_STACK_INTEGRITY_MANIFEST_TYPE: Final = (
    "NONAUTHORIZING_CANARY_STACK_INTEGRATION_MANIFEST"
)
DEFAULT_MANIFEST_MAX_AGE_SECONDS: Final = 86_400
_BUILD_IDENTITY = re.compile(r"^[0-9a-f]{7,64}$")
_NETWORK_ENDPOINT_PREFIXES: Final = (
    "http" + "://",
    "https" + "://",
)
_DISALLOWED_IMPORTS: Final = frozenset(
    {
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "momentum_hunter.schwab_account_discovery",
        "momentum_hunter.schwab_bound_account_refresh",
        "momentum_hunter.schwab_market_data",
        "momentum_hunter.schwab_onboarding",
        "momentum_hunter.schwab_setup",
    }
)
_DISALLOWED_ACTION_NAMES: Final = frozenset(
    {
        "cancel_order",
        "delete_credentials",
        "eval",
        "exec",
        "__import__",
        "import_module",
        "kill",
        "place_order",
        "Popen",
        "popen",
        "preview_order",
        "revoke",
        "replace_order",
        "rotate_credentials",
        "run",
        "send_signal",
        "startfile",
        "submit_order",
        "system",
        "terminate",
        "TerminateProcess",
        "transfer_money",
        "transmit_order",
        "withdraw",
        "urlopen",
    }
)
_MANIFEST_KEYS: Final = frozenset(
    {
        "schemaVersion",
        "manifestType",
        "buildIdentity",
        "createdAt",
        "signatureMode",
        "componentCount",
        "components",
        "stackSha256",
        "integrityStatus",
        "integrationOnly",
        "providerEvidence",
        "executionPermit",
        "brokerActionAllowed",
        "retryAllowed",
        "transmitting",
        "orderTransmission",
    }
)
_COMPONENT_KEYS: Final = frozenset(
    {
        "name",
        "role",
        "path",
        "sha256",
        "sizeBytes",
        "sourceReview",
    }
)


class CanaryStackIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class CanaryStackComponent:
    name: str
    role: str
    relative_path: str
    allowed_imports: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()


CANARY_STACK_COMPONENTS_V1: Final = (
    CanaryStackComponent(
        name="CANARY-001",
        role="position invariant",
        relative_path="momentum_hunter/schwab_canary_positions.py",
    ),
    CanaryStackComponent(
        name="CANARY-002",
        role="immutable position phase evidence",
        relative_path="momentum_hunter/schwab_canary_evidence.py",
    ),
    CanaryStackComponent(
        name="CANARY-003",
        role="settled-cash and restriction gate",
        relative_path="momentum_hunter/schwab_canary_funding.py",
    ),
    CanaryStackComponent(
        name="CANARY-004",
        role="order identity and reconciliation",
        relative_path=(
            "momentum_hunter/schwab_canary_order_reconciliation.py"
        ),
    ),
    CanaryStackComponent(
        name="CANARY-005",
        role="independent stop and revocation evidence",
        relative_path="momentum_hunter/schwab_canary_stop_evidence.py",
    ),
    CanaryStackComponent(
        name="CANARY-006",
        role="preflight composition",
        relative_path="momentum_hunter/schwab_canary_preflight.py",
    ),
    CanaryStackComponent(
        name="CANARY-007",
        role="immutable preflight receipt",
        relative_path="momentum_hunter/schwab_canary_preflight_receipt.py",
    ),
    CanaryStackComponent(
        name="CANARY-008",
        role="exact manual decision intent",
        relative_path="momentum_hunter/schwab_canary_manual_decision.py",
    ),
    CanaryStackComponent(
        name="CANARY-009",
        role="sanitized order contract emulator",
        relative_path="momentum_hunter/schwab_canary_order_emulator.py",
    ),
    CanaryStackComponent(
        name="CANARY-010",
        role="content-addressed stack integrity verifier",
        relative_path="momentum_hunter/schwab_canary_stack_integrity.py",
    ),
)
CANARY_STACK_COMPONENTS_V2: Final = CANARY_STACK_COMPONENTS_V1 + (
    CanaryStackComponent(
        name="CANARY-011",
        role="offline official order schema evidence",
        relative_path="momentum_hunter/schwab_order_schema_evidence.py",
        allowed_imports=("urllib.parse",),
        allowed_actions=("urlparse",),
    ),
    CanaryStackComponent(
        name="CANARY-012",
        role="read-only process identity observer",
        relative_path="momentum_hunter/schwab_canary_process_observer.py",
    ),
    CanaryStackComponent(
        name="CANARY-013",
        role="immutable process evidence chain",
        relative_path="momentum_hunter/schwab_canary_process_evidence.py",
    ),
)
CANARY_STACK_COMPONENTS_V3: Final = CANARY_STACK_COMPONENTS_V2 + (
    CanaryStackComponent(
        name="CANARY-015",
        role="broker-worker identity binding",
        relative_path="momentum_hunter/schwab_canary_worker_identity.py",
    ),
    CanaryStackComponent(
        name="CANARY-016",
        role="bounded nontransmitting broker-worker lifecycle",
        relative_path="momentum_hunter/schwab_canary_broker_worker.py",
    ),
    CanaryStackComponent(
        name="CANARY-017",
        role="bounded broker-worker lifecycle supervision",
        relative_path="momentum_hunter/schwab_canary_worker_lifecycle.py",
        allowed_imports=("subprocess",),
        allowed_actions=("Popen",),
    ),
    CanaryStackComponent(
        name="CANARY-018",
        role="read-only worker-lifecycle package verification",
        relative_path=(
            "momentum_hunter/schwab_canary_worker_lifecycle_evidence.py"
        ),
    ),
)
CANARY_STACK_COMPONENTS: Final = CANARY_STACK_COMPONENTS_V3 + (
    CanaryStackComponent(
        name="CANARY-022",
        role="credential-remediation evidence gate",
        relative_path=(
            "momentum_hunter/schwab_canary_credential_remediation.py"
        ),
    ),
)


def build_canary_stack_integrity_manifest(
    *,
    repository_root: Path,
    build_identity: str,
    created_at: datetime,
    components: Sequence[CanaryStackComponent] = CANARY_STACK_COMPONENTS,
) -> dict[str, object]:
    root = _require_repository_root(repository_root)
    identity = _require_build_identity(build_identity)
    created = _require_aware_datetime(created_at, field="manifest creation")
    expected = _require_component_contract(components)
    schema_version = _schema_version_for_components(expected)
    entries = [
        _build_component_entry(root=root, component=component)
        for component in expected
    ]
    manifest = {
        "schemaVersion": schema_version,
        "manifestType": CANARY_STACK_INTEGRITY_MANIFEST_TYPE,
        "buildIdentity": identity,
        "createdAt": created.isoformat(),
        "signatureMode": "SHA256_CONTENT_ADDRESS",
        "componentCount": len(entries),
        "components": entries,
        "stackSha256": _stack_digest(entries),
        "integrityStatus": "PASS",
        "integrationOnly": True,
        "providerEvidence": False,
        "executionPermit": False,
        "brokerActionAllowed": False,
        "retryAllowed": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }
    findings = verify_canary_stack_integrity_manifest(
        manifest,
        repository_root=root,
        expected_build_identity=identity,
        evaluated_at=created,
        components=expected,
    )
    if findings:
        raise CanaryStackIntegrityError(" | ".join(findings))
    return manifest


def verify_canary_stack_integrity_manifest(
    manifest: object,
    *,
    repository_root: Path,
    expected_build_identity: str,
    evaluated_at: datetime,
    components: Sequence[CanaryStackComponent] = CANARY_STACK_COMPONENTS,
    maximum_age_seconds: int = DEFAULT_MANIFEST_MAX_AGE_SECONDS,
) -> tuple[str, ...]:
    findings: list[str] = []
    try:
        root = _require_repository_root(repository_root)
        identity = _require_build_identity(expected_build_identity)
        evaluated = _require_aware_datetime(
            evaluated_at,
            field="manifest evaluation",
        )
        expected = _require_component_contract(components)
        expected_schema_version = _schema_version_for_components(expected)
    except CanaryStackIntegrityError as exc:
        return (str(exc),)
    if (
        isinstance(maximum_age_seconds, bool)
        or not isinstance(maximum_age_seconds, int)
        or maximum_age_seconds <= 0
    ):
        return ("Maximum manifest age must be a positive integer.",)
    if not isinstance(manifest, Mapping):
        return ("Canary stack integrity manifest is missing or malformed.",)
    payload = dict(manifest)
    if frozenset(payload) != _MANIFEST_KEYS:
        findings.append(
            "Canary stack integrity manifest fields do not match the schema."
        )
    if payload.get("schemaVersion") != expected_schema_version:
        findings.append("Canary stack integrity schema is unsupported.")
    if payload.get("manifestType") != CANARY_STACK_INTEGRITY_MANIFEST_TYPE:
        findings.append("Canary stack manifest type is invalid.")
    if payload.get("buildIdentity") != identity:
        findings.append("Canary stack build identity does not match.")
    created_at = _parse_aware_datetime(payload.get("createdAt"))
    if created_at is None:
        findings.append("Canary stack manifest creation time is invalid.")
    else:
        age_seconds = (evaluated - created_at).total_seconds()
        if age_seconds < 0:
            findings.append("Canary stack manifest is future-dated.")
        elif age_seconds > maximum_age_seconds:
            findings.append(
                "Canary stack manifest is older than the allowed integration window."
            )
    if payload.get("signatureMode") != "SHA256_CONTENT_ADDRESS":
        findings.append("Canary stack signature mode is invalid.")
    required_flags = {
        "integrityStatus": "PASS",
        "integrationOnly": True,
        "providerEvidence": False,
        "executionPermit": False,
        "brokerActionAllowed": False,
        "retryAllowed": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }
    for field_name, required_value in required_flags.items():
        if payload.get(field_name) != required_value:
            findings.append(
                f"Canary stack authority boundary changed: {field_name}."
            )

    items = payload.get("components")
    if not isinstance(items, list):
        findings.append("Canary stack component list is missing.")
        items = []
    if payload.get("componentCount") != len(expected):
        findings.append("Canary stack component count does not match policy.")
    if len(items) != len(expected):
        findings.append("Canary stack manifest component set is incomplete.")
    expected_by_name = {item.name: item for item in expected}
    seen_names: set[str] = set()
    canonical_entries: list[dict[str, object]] = []
    for raw_item in items:
        if not isinstance(raw_item, Mapping):
            findings.append("Canary stack component entry is malformed.")
            continue
        item = dict(raw_item)
        canonical_entries.append(item)
        if frozenset(item) != _COMPONENT_KEYS:
            findings.append(
                "Canary stack component fields do not match the schema."
            )
        name = str(item.get("name", ""))
        if name in seen_names:
            findings.append(f"Canary stack component is duplicated: {name}.")
        seen_names.add(name)
        component = expected_by_name.get(name)
        if component is None:
            findings.append(
                f"Canary stack component is not allowlisted: {name or 'missing'}."
            )
            continue
        findings.extend(
            _verify_component_entry(
                item,
                root=root,
                component=component,
            )
        )
    missing = set(expected_by_name) - seen_names
    if missing:
        findings.append(
            "Canary stack required components are missing: "
            + ", ".join(sorted(missing))
            + "."
        )
    if canonical_entries:
        try:
            expected_digest = _stack_digest(canonical_entries)
        except (TypeError, ValueError):
            findings.append("Canary stack component manifest is not canonical JSON.")
        else:
            if payload.get("stackSha256") != expected_digest:
                findings.append("Canary stack aggregate fingerprint does not match.")
    elif payload.get("stackSha256"):
        findings.append("Canary stack fingerprint exists without components.")
    return tuple(dict.fromkeys(findings))


def canonical_manifest_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _build_component_entry(
    *,
    root: Path,
    component: CanaryStackComponent,
) -> dict[str, object]:
    source_path = _resolve_component_path(root, component.relative_path)
    content = source_path.read_bytes()
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanaryStackIntegrityError(
            f"Canary stack component is not UTF-8: {component.name}."
        ) from exc
    source_findings = _source_safety_findings(
        source,
        allowed_imports=component.allowed_imports,
        allowed_actions=component.allowed_actions,
    )
    if source_findings:
        raise CanaryStackIntegrityError(
            f"{component.name}: " + " | ".join(source_findings)
        )
    return {
        "name": component.name,
        "role": component.role,
        "path": component.relative_path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "sizeBytes": len(content),
        "sourceReview": "PASS_NONTRANSMITTING_STATIC_BOUNDARY",
    }


def _verify_component_entry(
    item: Mapping[str, object],
    *,
    root: Path,
    component: CanaryStackComponent,
) -> tuple[str, ...]:
    findings: list[str] = []
    if item.get("role") != component.role:
        findings.append(f"{component.name} role does not match policy.")
    if item.get("path") != component.relative_path:
        findings.append(f"{component.name} path does not match policy.")
        return tuple(findings)
    if item.get("sourceReview") != "PASS_NONTRANSMITTING_STATIC_BOUNDARY":
        findings.append(f"{component.name} source review did not pass.")
    try:
        source_path = _resolve_component_path(root, component.relative_path)
        content = source_path.read_bytes()
    except (CanaryStackIntegrityError, OSError) as exc:
        findings.append(f"{component.name} cannot be re-read: {exc}")
        return tuple(findings)
    if item.get("sha256") != hashlib.sha256(content).hexdigest():
        findings.append(f"{component.name} content fingerprint changed.")
    if item.get("sizeBytes") != len(content):
        findings.append(f"{component.name} byte count changed.")
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(f"{component.name} is not UTF-8.")
    else:
        for source_finding in _source_safety_findings(
            source,
            allowed_imports=component.allowed_imports,
            allowed_actions=component.allowed_actions,
        ):
            findings.append(f"{component.name}: {source_finding}")
    return tuple(findings)


def _source_safety_findings(
    source: str,
    *,
    allowed_imports: Sequence[str] = (),
    allowed_actions: Sequence[str] = (),
) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ("Python source cannot be parsed.",)
    imports: set[str] = set()
    blocked_import_aliases: dict[str, str] = {}
    defined_names: set[str] = set()
    called_names: set[str] = set()
    blocked_module_calls: set[str] = set()
    url_literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
                if any(
                    alias.name == blocked
                    or alias.name.startswith(f"{blocked}.")
                    for blocked in _DISALLOWED_IMPORTS
                ):
                    local_name = alias.asname or alias.name.split(".", 1)[0]
                    blocked_import_aliases[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            if any(
                node.module == blocked
                or node.module.startswith(f"{blocked}.")
                for blocked in _DISALLOWED_IMPORTS
            ):
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    blocked_import_aliases[local_name] = (
                        f"{node.module}.{alias.name}"
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined_names.add(node.name)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
                blocked_target = blocked_import_aliases.get(node.func.id)
                if blocked_target:
                    blocked_module_calls.add(
                        blocked_target.rsplit(".", 1)[-1]
                    )
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id in blocked_import_aliases
                ):
                    blocked_module_calls.add(node.func.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.strip().lower()
            if lowered.startswith(_NETWORK_ENDPOINT_PREFIXES):
                url_literals.add(node.value)
    unsafe_imports = sorted(
        imported
        for imported in imports
        if imported not in allowed_imports
        if any(
            imported == blocked or imported.startswith(f"{blocked}.")
            for blocked in _DISALLOWED_IMPORTS
        )
    )
    unsafe_actions = sorted(
        action
        for action in (defined_names | called_names) & _DISALLOWED_ACTION_NAMES
        if action not in allowed_actions
    )
    unsafe_module_calls = sorted(
        action
        for action in blocked_module_calls
        if action not in allowed_actions
    )
    findings: list[str] = []
    if unsafe_imports:
        findings.append(
            "Disallowed provider, network, or process import: "
            + ", ".join(unsafe_imports)
            + "."
        )
    if unsafe_actions:
        findings.append(
            "Disallowed broker or process-action name: "
            + ", ".join(unsafe_actions)
            + "."
        )
    if unsafe_module_calls:
        findings.append(
            "Disallowed call through a provider, network, or process import: "
            + ", ".join(unsafe_module_calls)
            + "."
        )
    if url_literals:
        findings.append("Embedded network endpoint is not allowed.")
    return tuple(findings)


def _require_component_contract(
    components: Sequence[CanaryStackComponent],
) -> tuple[CanaryStackComponent, ...]:
    items = tuple(components)
    if not items:
        raise CanaryStackIntegrityError(
            "Canary stack component policy cannot be empty."
        )
    names: set[str] = set()
    paths: set[str] = set()
    for component in items:
        if (
            not isinstance(component, CanaryStackComponent)
            or not component.name.strip()
            or not component.role.strip()
            or not component.relative_path.strip()
            or not isinstance(component.allowed_imports, tuple)
            or not isinstance(component.allowed_actions, tuple)
            or any(
                not isinstance(item, str) or not item
                for item in component.allowed_imports
            )
            or any(
                not isinstance(item, str) or not item
                for item in component.allowed_actions
            )
        ):
            raise CanaryStackIntegrityError(
                "Canary stack component policy is malformed."
            )
        expected_allowed_imports: tuple[str, ...] = ()
        expected_allowed_actions: tuple[str, ...] = ()
        if (
            component.name == "CANARY-011"
            and component.relative_path
            == "momentum_hunter/schwab_order_schema_evidence.py"
        ):
            expected_allowed_imports = ("urllib.parse",)
            expected_allowed_actions = ("urlparse",)
        elif (
            component.name == "CANARY-017"
            and component.relative_path
            == "momentum_hunter/schwab_canary_worker_lifecycle.py"
        ):
            expected_allowed_imports = ("subprocess",)
            expected_allowed_actions = ("Popen",)
        if component.allowed_imports != expected_allowed_imports:
            raise CanaryStackIntegrityError(
                "Canary stack component import exceptions do not match policy."
            )
        if component.allowed_actions != expected_allowed_actions:
            raise CanaryStackIntegrityError(
                "Canary stack component action exceptions do not match policy."
            )
        if component.name in names or component.relative_path in paths:
            raise CanaryStackIntegrityError(
                "Canary stack component policy contains duplicate identity."
            )
        names.add(component.name)
        paths.add(component.relative_path)
    if items not in {
        CANARY_STACK_COMPONENTS_V1,
        CANARY_STACK_COMPONENTS_V2,
        CANARY_STACK_COMPONENTS_V3,
        CANARY_STACK_COMPONENTS,
    }:
        raise CanaryStackIntegrityError(
            "Canary stack components must match a frozen policy version."
        )
    return items


def _schema_version_for_components(
    components: Sequence[CanaryStackComponent],
) -> str:
    if tuple(components) == CANARY_STACK_COMPONENTS_V1:
        return CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V1
    if tuple(components) == CANARY_STACK_COMPONENTS_V2:
        return CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V2
    if tuple(components) == CANARY_STACK_COMPONENTS_V3:
        return CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V3
    return CANARY_STACK_INTEGRITY_SCHEMA_VERSION


def _resolve_component_path(root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise CanaryStackIntegrityError(
            "Canary stack component path must remain inside the repository."
        )
    try:
        resolved = (root / relative).resolve(strict=True)
    except OSError as exc:
        raise CanaryStackIntegrityError(
            f"Canary stack component is missing: {relative_path}."
        ) from exc
    if not resolved.is_file():
        raise CanaryStackIntegrityError(
            f"Canary stack component is not a file: {relative_path}."
        )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CanaryStackIntegrityError(
            "Canary stack component resolved outside the repository."
        ) from exc
    return resolved


def _require_repository_root(value: Path) -> Path:
    try:
        root = Path(value).resolve(strict=True)
    except OSError as exc:
        raise CanaryStackIntegrityError(
            "Canary stack repository root does not exist."
        ) from exc
    if not root.is_dir():
        raise CanaryStackIntegrityError(
            "Canary stack repository root is not a directory."
        )
    return root


def _require_build_identity(value: str) -> str:
    identity = str(value).strip().lower()
    if not _BUILD_IDENTITY.fullmatch(identity):
        raise CanaryStackIntegrityError(
            "Canary stack build identity must be a 7-64 character lowercase hex commit."
        )
    return identity


def _require_aware_datetime(value: datetime, *, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise CanaryStackIntegrityError(
            f"Canary stack {field} time must include a UTC offset."
        )
    return value


def _parse_aware_datetime(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _stack_digest(entries: Sequence[Mapping[str, object]]) -> str:
    canonical = canonical_manifest_json(list(entries)).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()
