from __future__ import annotations

"""Fail-closed identity and promotion contract for opening-capture runtime."""

import hashlib
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence


SURFACE_SCHEMA = "OpeningRuntimeSurfaceV1"
RELEASE_SCHEMA = "OpeningRuntimeReleaseV1"
PROMOTION_SCHEMA = "OpeningRuntimePromotionV1"
POINTER_SCHEMA = "OpeningRuntimeChannelV1"
PROMOTION_POLICY_VERSION = "opening-runtime-promotion-v1"
DEFAULT_CHANNEL = "opening-capture"
DEFAULT_RELEASE_ROOT = (
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "MomentumHunter"
    / "Automation"
    / "opening-runtime"
)
CHANNEL_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
RELEASE_ID_PATTERN = re.compile(r"^OPENING-RUNTIME-[0-9A-F]{20}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

_RUNTIME_FILE_RULES = (
    (
        "momentum_hunter/**/*.py",
        "PYTHON_RUNTIME",
        "All package Python is conservatively included; additions are automatic.",
    ),
    (
        "tools/capture_job.py",
        "OPENING_ORCHESTRATOR",
        "Direct Python entry point invoked by the opening runner.",
    ),
    (
        "tools/run_capture_job.ps1",
        "OPENING_LAUNCHER",
        "PowerShell launcher, retry, and terminal-result behavior.",
    ),
    (
        "requirements.txt",
        "DEPENDENCY_CONTRACT",
        "Declared Python dependency contract.",
    ),
)
_CONFIG_KEYS = frozenset(
    {
        "mode",
        "provider",
        "review_timezone",
        "evening_review_window",
        "morning_review_window",
    }
)


class OpeningRuntimeIdentityError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class RuntimeIdentityContext:
    repository_root: Path
    python_executable: Path
    powershell_executable: Path
    state_directory: Path
    engine_host_state_directory: Path
    poll_interval_seconds: float
    service_host_executable: Path
    release_root: Path = DEFAULT_RELEASE_ROOT
    config_path: Path | None = None


@dataclass(frozen=True)
class OpeningRuntimeGateResult:
    channel: str
    release_id: str
    release_fingerprint: str
    runtime_surface_fingerprint: str
    configuration_fingerprint: str
    environment_fingerprint: str
    approved_runtime_fingerprint: str
    release_source_git_sha: str
    current_git_sha: str
    current_worktree_clean: bool
    runtime_match: bool


CommandRunner = Callable[[Sequence[str]], str]


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def payload_fingerprint(payload: Mapping[str, object], field_name: str) -> str:
    material = dict(payload)
    material.pop(field_name, None)
    return hashlib.sha256(canonical_json_bytes(material)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise OpeningRuntimeIdentityError(
            "RUNTIME_COMPONENT_UNREADABLE",
            f"Runtime component cannot be read: {path}",
        ) from exc
    return digest.hexdigest()


def _run_command(arguments: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            list(arguments),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise OpeningRuntimeIdentityError(
            "ENVIRONMENT_PROBE_FAILED",
            "A runtime environment executable could not be started.",
        ) from exc
    if completed.returncode != 0:
        raise OpeningRuntimeIdentityError(
            "ENVIRONMENT_PROBE_FAILED",
            "A runtime environment identity probe failed.",
            details={"executable": str(arguments[0])},
        )
    return completed.stdout.strip()


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        information = path.lstat()
    except OSError as exc:
        raise OpeningRuntimeIdentityError(
            "RUNTIME_PATH_UNREADABLE",
            f"Runtime path cannot be inspected: {path}",
        ) from exc
    attributes = getattr(information, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _require_regular_path(path: Path, *, directory: bool) -> None:
    if not path.exists():
        raise OpeningRuntimeIdentityError(
            "RUNTIME_PATH_MISSING",
            f"Required runtime path is missing: {path}",
        )
    if _is_reparse_or_symlink(path):
        raise OpeningRuntimeIdentityError(
            "RUNTIME_REPARSE_POINT",
            f"Runtime identity rejects a symlink or reparse point: {path}",
        )
    if directory and not path.is_dir():
        raise OpeningRuntimeIdentityError(
            "RUNTIME_PATH_TYPE_INVALID",
            f"Required runtime directory is not a directory: {path}",
        )
    if not directory and not path.is_file():
        raise OpeningRuntimeIdentityError(
            "RUNTIME_PATH_TYPE_INVALID",
            f"Required runtime file is not a regular file: {path}",
        )


def _require_tree_without_reparse(root: Path, path: Path) -> None:
    root = root.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OpeningRuntimeIdentityError(
            "RUNTIME_PATH_ESCAPE",
            "Runtime component escapes the configured repository root.",
        ) from exc
    cursor = root
    _require_regular_path(cursor, directory=True)
    for part in relative.parts[:-1]:
        cursor = cursor / part
        _require_regular_path(cursor, directory=True)
    _require_regular_path(path, directory=False)


def build_runtime_surface(repository_root: Path) -> dict[str, object]:
    root = repository_root.absolute()
    _require_regular_path(root, directory=True)
    components: dict[str, dict[str, object]] = {}
    for pattern, component_class, reason in _RUNTIME_FILE_RULES:
        matched = sorted(root.glob(pattern))
        if not matched:
            raise OpeningRuntimeIdentityError(
                "RUNTIME_SURFACE_RULE_EMPTY",
                f"Runtime surface rule matched no files: {pattern}",
            )
        for path in matched:
            if path.is_dir():
                continue
            _require_tree_without_reparse(root, path)
            relative = PurePosixPath(path.relative_to(root).as_posix())
            key = str(relative)
            components[key] = {
                "path": key,
                "componentClass": component_class,
                "sha256": file_sha256(path),
                "size": path.stat().st_size,
                "reasonIncluded": reason,
            }
    payload: dict[str, object] = {
        "schemaVersion": SURFACE_SCHEMA,
        "inclusionRules": [rule[0] for rule in _RUNTIME_FILE_RULES],
        "components": [components[key] for key in sorted(components)],
    }
    payload["runtimeSurfaceFingerprint"] = payload_fingerprint(
        payload,
        "runtimeSurfaceFingerprint",
    )
    return payload


def _load_runtime_configuration(context: RuntimeIdentityContext) -> dict[str, object]:
    config_path = context.config_path or (
        context.repository_root / "MomentumHunterData" / "config.json"
    )
    _require_regular_path(config_path, directory=False)
    try:
        project_config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpeningRuntimeIdentityError(
            "RUNTIME_CONFIG_INVALID",
            "Opening runtime configuration is unreadable or malformed.",
        ) from exc
    if not isinstance(project_config, dict):
        raise OpeningRuntimeIdentityError(
            "RUNTIME_CONFIG_INVALID",
            "Opening runtime configuration must be an object.",
        )
    unknown = sorted(set(project_config) - _CONFIG_KEYS)
    if unknown:
        raise OpeningRuntimeIdentityError(
            "RUNTIME_CONFIG_UNCLASSIFIED",
            "Runtime configuration contains unclassified fields.",
            details={"fields": unknown},
        )
    manifest_config = {
        "repositoryRoot": str(context.repository_root.absolute()),
        "pythonExecutable": str(context.python_executable.absolute()),
        "powershellExecutable": str(context.powershell_executable.absolute()),
        "stateDirectory": str(context.state_directory.absolute()),
        "engineHostStateDirectory": str(
            context.engine_host_state_directory.absolute()
        ),
        "pollIntervalSeconds": context.poll_interval_seconds,
        "serviceHostExecutable": str(context.service_host_executable.absolute()),
        "openingRuntimeReleaseRoot": str(context.release_root.absolute()),
    }
    payload: dict[str, object] = {
        "schemaVersion": "OpeningRuntimeConfigurationV1",
        "projectConfiguration": project_config,
        "automationConfiguration": manifest_config,
        "authenticationStateIncluded": False,
    }
    payload["configurationFingerprint"] = payload_fingerprint(
        payload,
        "configurationFingerprint",
    )
    return payload


def _requirement_names(requirements_path: Path) -> list[str]:
    names: list[str] = []
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if match is None:
            raise OpeningRuntimeIdentityError(
                "DEPENDENCY_CONTRACT_INVALID",
                "A requirement cannot be normalized for environment identity.",
            )
        names.append(match.group(1))
    return sorted(set(names), key=str.casefold)


def probe_runtime_environment(
    context: RuntimeIdentityContext,
    *,
    command_runner: CommandRunner = _run_command,
) -> dict[str, object]:
    for executable in (
        context.python_executable,
        context.powershell_executable,
        context.service_host_executable,
    ):
        _require_regular_path(executable, directory=False)
    requirements_path = context.repository_root / "requirements.txt"
    _require_regular_path(requirements_path, directory=False)
    requirement_names = _requirement_names(requirements_path)
    package_script = (
        "import importlib.metadata as m,json;"
        "items={};"
        "[(items.__setitem__((d.metadata.get('Name') or '').lower(),d.version)) "
        "for d in m.distributions() if d.metadata.get('Name')];"
        "print(json.dumps(items,sort_keys=True))"
    )
    package_output = command_runner(
        (
            str(context.python_executable),
            "-B",
            "-c",
            package_script,
        )
    )
    try:
        packages = json.loads(package_output)
    except json.JSONDecodeError as exc:
        raise OpeningRuntimeIdentityError(
            "DEPENDENCY_PROBE_INVALID",
            "Installed dependency identity probe returned malformed output.",
        ) from exc
    timezone_identity = (
        command_runner(("tzutil.exe", "/g"))
        if os.name == "nt"
        else os.environ.get("TZ", "")
    )
    payload: dict[str, object] = {
        "schemaVersion": "OpeningRuntimeEnvironmentV1",
        "python": {
            "path": str(context.python_executable.absolute()),
            "sha256": file_sha256(context.python_executable),
            "version": command_runner(
                (str(context.python_executable), "--version")
            ),
        },
        "powershell": {
            "path": str(context.powershell_executable.absolute()),
            "sha256": file_sha256(context.powershell_executable),
            "version": command_runner(
                (
                    str(context.powershell_executable),
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "$PSVersionTable.PSVersion.ToString()",
                )
            ),
        },
        "serviceHost": {
            "path": str(context.service_host_executable.absolute()),
            "sha256": file_sha256(context.service_host_executable),
        },
        "requirementsSha256": file_sha256(requirements_path),
        "declaredRequirements": requirement_names,
        "installedDistributions": packages,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "timezone": timezone_identity,
        },
    }
    payload["environmentFingerprint"] = payload_fingerprint(
        payload,
        "environmentFingerprint",
    )
    return payload


def build_runtime_identity(
    context: RuntimeIdentityContext,
    *,
    environment: Mapping[str, object] | None = None,
) -> dict[str, object]:
    surface = build_runtime_surface(context.repository_root)
    configuration = _load_runtime_configuration(context)
    environment_payload = dict(environment or probe_runtime_environment(context))
    environment_fingerprint = str(
        environment_payload.get("environmentFingerprint", "")
    )
    if not SHA256_PATTERN.fullmatch(environment_fingerprint):
        raise OpeningRuntimeIdentityError(
            "ENVIRONMENT_IDENTITY_INVALID",
            "Environment identity is missing a valid fingerprint.",
        )
    aggregate = {
        "runtimeSurfaceFingerprint": surface["runtimeSurfaceFingerprint"],
        "configurationFingerprint": configuration["configurationFingerprint"],
        "environmentFingerprint": environment_fingerprint,
        "promotionPolicyVersion": PROMOTION_POLICY_VERSION,
    }
    return {
        "runtimeSurface": surface,
        "configuration": configuration,
        "environment": environment_payload,
        "approvedRuntimeFingerprint": hashlib.sha256(
            canonical_json_bytes(aggregate)
        ).hexdigest(),
    }


def current_git_identity(repository_root: Path) -> tuple[str, str]:
    head = _run_command(("git", "-C", str(repository_root), "rev-parse", "HEAD"))
    if not GIT_SHA_PATTERN.fullmatch(head):
        raise OpeningRuntimeIdentityError(
            "GIT_IDENTITY_INVALID",
            "Current repository HEAD is not a full Git SHA.",
        )
    status = _run_command(
        ("git", "-C", str(repository_root), "status", "--porcelain")
    )
    return head, status


def build_release_record(
    context: RuntimeIdentityContext,
    *,
    source_git_sha: str,
    qualification_evidence: Sequence[str],
    predecessor_release_id: str = "",
    created_at: datetime | None = None,
    environment: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if not GIT_SHA_PATTERN.fullmatch(source_git_sha):
        raise OpeningRuntimeIdentityError(
            "RELEASE_SOURCE_GIT_INVALID",
            "Release source Git identity must be a full SHA.",
        )
    qualifications = sorted({str(item).strip() for item in qualification_evidence})
    if not qualifications or any(not item for item in qualifications):
        raise OpeningRuntimeIdentityError(
            "RELEASE_QUALIFICATION_MISSING",
            "An approved release requires qualification evidence references.",
        )
    identity = build_runtime_identity(context, environment=environment)
    approved = str(identity["approvedRuntimeFingerprint"])
    release_id = f"OPENING-RUNTIME-{approved[:20].upper()}"
    record: dict[str, object] = {
        "schemaVersion": RELEASE_SCHEMA,
        "releaseId": release_id,
        "createdAt": (created_at or datetime.now().astimezone()).isoformat(),
        "sourceGitSha": source_git_sha,
        "runtimeSurfaceVersion": SURFACE_SCHEMA,
        "runtimeSurfaceFingerprint": identity["runtimeSurface"][
            "runtimeSurfaceFingerprint"
        ],
        "configurationFingerprint": identity["configuration"][
            "configurationFingerprint"
        ],
        "environmentFingerprint": identity["environment"][
            "environmentFingerprint"
        ],
        "approvedRuntimeFingerprint": approved,
        "runtimeComponents": identity["runtimeSurface"]["components"],
        "configurationIdentity": identity["configuration"],
        "environmentIdentity": identity["environment"],
        "qualificationEvidence": qualifications,
        "promotionPolicyVersion": PROMOTION_POLICY_VERSION,
        "predecessorReleaseId": predecessor_release_id,
        "authority": {
            "openingCapture": True,
            "paper": False,
            "shadow": False,
            "brokerOrders": False,
            "orderTransmission": "UNAVAILABLE",
        },
    }
    record["releaseFingerprint"] = payload_fingerprint(
        record,
        "releaseFingerprint",
    )
    return record


class OpeningRuntimeReleaseStore:
    def __init__(self, root: Path = DEFAULT_RELEASE_ROOT) -> None:
        self.root = root.absolute()

    @property
    def releases_directory(self) -> Path:
        return self.root / "releases"

    @property
    def promotions_directory(self) -> Path:
        return self.root / "promotions"

    @property
    def channels_directory(self) -> Path:
        return self.root / "channels"

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _require_regular_path(self.root, directory=True)
        for directory in (
            self.releases_directory,
            self.promotions_directory,
            self.channels_directory,
        ):
            directory.mkdir(exist_ok=True)
            _require_regular_path(directory, directory=True)

    def _safe_file(self, directory: Path, name: str) -> Path:
        if not name or name != Path(name).name or not name.isascii():
            raise OpeningRuntimeIdentityError(
                "RELEASE_PATH_INVALID",
                "Release storage filename is invalid.",
            )
        self.initialize()
        _require_regular_path(directory, directory=True)
        candidate = directory / name
        if candidate.exists() and _is_reparse_or_symlink(candidate):
            raise OpeningRuntimeIdentityError(
                "RELEASE_REPARSE_POINT",
                "Release storage rejects symlinks and reparse points.",
            )
        return candidate

    def release_path(self, release_id: str) -> Path:
        if not RELEASE_ID_PATTERN.fullmatch(release_id):
            raise OpeningRuntimeIdentityError(
                "RELEASE_ID_INVALID",
                "Approved runtime release identifier is invalid.",
            )
        return self._safe_file(self.releases_directory, f"{release_id}.json")

    def pointer_path(self, channel: str) -> Path:
        if not CHANNEL_PATTERN.fullmatch(channel):
            raise OpeningRuntimeIdentityError(
                "RELEASE_CHANNEL_INVALID",
                "Approved runtime channel name is invalid.",
            )
        return self._safe_file(self.channels_directory, f"{channel}.json")

    @staticmethod
    def _read_json(path: Path, missing_code: str) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise OpeningRuntimeIdentityError(
                missing_code,
                f"Required approved runtime record is missing: {path.name}",
            ) from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpeningRuntimeIdentityError(
                "RELEASE_RECORD_MALFORMED",
                f"Approved runtime record is unreadable: {path.name}",
            ) from exc
        if not isinstance(payload, dict):
            raise OpeningRuntimeIdentityError(
                "RELEASE_RECORD_MALFORMED",
                f"Approved runtime record is not an object: {path.name}",
            )
        return payload

    @staticmethod
    def _write_once(path: Path, payload: Mapping[str, object]) -> None:
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = OpeningRuntimeReleaseStore._read_json(
                path,
                "RELEASE_RECORD_MISSING",
            )
            if existing != dict(payload):
                raise OpeningRuntimeIdentityError(
                    "RELEASE_WRITE_CONFLICT",
                    f"Conflicting immutable runtime record exists: {path.name}",
                )
            return
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def verify_release(self, release_id: str) -> dict[str, object]:
        path = self.release_path(release_id)
        payload = self._read_json(path, "RELEASE_RECORD_MISSING")
        if payload.get("schemaVersion") != RELEASE_SCHEMA:
            raise OpeningRuntimeIdentityError(
                "RELEASE_SCHEMA_UNSUPPORTED",
                "Approved runtime release schema is unsupported.",
            )
        if payload.get("releaseId") != release_id:
            raise OpeningRuntimeIdentityError(
                "RELEASE_ID_MISMATCH",
                "Approved runtime release identity is contradictory.",
            )
        fingerprint = str(payload.get("releaseFingerprint", ""))
        if not SHA256_PATTERN.fullmatch(fingerprint) or fingerprint != payload_fingerprint(
            payload,
            "releaseFingerprint",
        ):
            raise OpeningRuntimeIdentityError(
                "RELEASE_FINGERPRINT_MISMATCH",
                "Approved runtime release fingerprint does not verify.",
            )
        if payload.get("promotionPolicyVersion") != PROMOTION_POLICY_VERSION:
            raise OpeningRuntimeIdentityError(
                "RELEASE_POLICY_UNSUPPORTED",
                "Approved runtime promotion policy is unsupported.",
            )
        source_git = str(payload.get("sourceGitSha", ""))
        fingerprint_fields = (
            "runtimeSurfaceFingerprint",
            "configurationFingerprint",
            "environmentFingerprint",
            "approvedRuntimeFingerprint",
        )
        if not GIT_SHA_PATTERN.fullmatch(source_git) or any(
            not SHA256_PATTERN.fullmatch(str(payload.get(field, "")))
            for field in fingerprint_fields
        ):
            raise OpeningRuntimeIdentityError(
                "RELEASE_IDENTITY_FIELDS_INVALID",
                "Approved runtime release identity fields are invalid.",
            )
        if release_id != (
            "OPENING-RUNTIME-"
            + str(payload["approvedRuntimeFingerprint"])[:20].upper()
        ):
            raise OpeningRuntimeIdentityError(
                "RELEASE_RUNTIME_ID_MISMATCH",
                "Release identifier does not bind the approved runtime fingerprint.",
            )
        components = payload.get("runtimeComponents")
        environment = payload.get("environmentIdentity")
        configuration = payload.get("configurationIdentity")
        qualifications = payload.get("qualificationEvidence")
        authority = payload.get("authority")
        if (
            not isinstance(components, list)
            or not components
            or not isinstance(environment, dict)
            or not isinstance(configuration, dict)
            or not isinstance(qualifications, list)
            or not qualifications
            or not isinstance(authority, dict)
        ):
            raise OpeningRuntimeIdentityError(
                "RELEASE_STRUCTURE_INVALID",
                "Approved runtime release structure is incomplete.",
            )
        for component in components:
            if (
                not isinstance(component, dict)
                or not str(component.get("path", ""))
                or not SHA256_PATTERN.fullmatch(str(component.get("sha256", "")))
            ):
                raise OpeningRuntimeIdentityError(
                    "RELEASE_COMPONENT_INVALID",
                    "Approved runtime component identity is invalid.",
                )
        if authority != {
            "openingCapture": True,
            "paper": False,
            "shadow": False,
            "brokerOrders": False,
            "orderTransmission": "UNAVAILABLE",
        }:
            raise OpeningRuntimeIdentityError(
                "RELEASE_AUTHORITY_INVALID",
                "Approved runtime release carries unexpected authority.",
            )
        return payload

    def _promotion_files(self) -> list[Path]:
        self.initialize()
        files = sorted(self.promotions_directory.glob("*.json"))
        for path in files:
            _require_regular_path(path, directory=False)
        return files

    def verify_channel(
        self,
        channel: str = DEFAULT_CHANNEL,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        pointer = self._read_json(
            self.pointer_path(channel),
            "RELEASE_POINTER_MISSING",
        )
        if pointer.get("schemaVersion") != POINTER_SCHEMA:
            raise OpeningRuntimeIdentityError(
                "RELEASE_POINTER_SCHEMA_UNSUPPORTED",
                "Approved runtime channel schema is unsupported.",
            )
        pointer_fingerprint = str(pointer.get("pointerFingerprint", ""))
        if not SHA256_PATTERN.fullmatch(
            pointer_fingerprint
        ) or pointer_fingerprint != payload_fingerprint(
            pointer,
            "pointerFingerprint",
        ):
            raise OpeningRuntimeIdentityError(
                "RELEASE_POINTER_FINGERPRINT_MISMATCH",
                "Approved runtime channel fingerprint does not verify.",
            )
        previous_receipt = ""
        previous_release = ""
        receipts: list[dict[str, object]] = []
        for expected_sequence, path in enumerate(self._promotion_files(), start=1):
            receipt = self._read_json(path, "PROMOTION_RECEIPT_MISSING")
            if receipt.get("schemaVersion") != PROMOTION_SCHEMA:
                raise OpeningRuntimeIdentityError(
                    "PROMOTION_SCHEMA_UNSUPPORTED",
                    "Runtime promotion receipt schema is unsupported.",
                )
            fingerprint = str(receipt.get("receiptFingerprint", ""))
            if not SHA256_PATTERN.fullmatch(fingerprint) or fingerprint != payload_fingerprint(
                receipt,
                "receiptFingerprint",
            ):
                raise OpeningRuntimeIdentityError(
                    "PROMOTION_FINGERPRINT_MISMATCH",
                    "Runtime promotion receipt fingerprint does not verify.",
                )
            release_id = str(receipt.get("releaseId", ""))
            if (
                receipt.get("channel") != channel
                or not RELEASE_ID_PATTERN.fullmatch(release_id)
                or path.name != f"{expected_sequence:06d}-{release_id}.json"
            ):
                raise OpeningRuntimeIdentityError(
                    "PROMOTION_RECEIPT_IDENTITY_INVALID",
                    "Runtime promotion receipt path or channel identity is invalid.",
                )
            historical_release = self.verify_release(release_id)
            if (
                receipt.get("releaseFingerprint")
                != historical_release.get("releaseFingerprint")
                or receipt.get("releaseSourceGitSha")
                != historical_release.get("sourceGitSha")
            ):
                raise OpeningRuntimeIdentityError(
                    "PROMOTION_RELEASE_CHAIN_INVALID",
                    "Runtime promotion receipt does not match its immutable release.",
                )
            if (
                receipt.get("sequence") != expected_sequence
                or receipt.get("previousReceiptFingerprint") != previous_receipt
                or receipt.get("predecessorReleaseId") != previous_release
            ):
                raise OpeningRuntimeIdentityError(
                    "PROMOTION_CHAIN_INVALID",
                    "Runtime promotion predecessor chain is invalid.",
                )
            previous_receipt = fingerprint
            previous_release = release_id
            receipts.append(receipt)
        if not receipts:
            raise OpeningRuntimeIdentityError(
                "PROMOTION_RECEIPT_MISSING",
                "Approved runtime channel has no promotion receipt.",
            )
        active = receipts[-1]
        if (
            pointer.get("channel") != channel
            or pointer.get("releaseId") != active.get("releaseId")
            or pointer.get("promotionReceiptFingerprint")
            != active.get("receiptFingerprint")
            or pointer.get("releaseFingerprint")
            != active.get("releaseFingerprint")
            or pointer.get("predecessorReleaseId")
            != active.get("predecessorReleaseId")
        ):
            raise OpeningRuntimeIdentityError(
                "RELEASE_POINTER_CHAIN_INVALID",
                "Approved runtime pointer does not match the promotion chain.",
            )
        release = self.verify_release(str(pointer.get("releaseId", "")))
        if release.get("releaseFingerprint") != pointer.get("releaseFingerprint"):
            raise OpeningRuntimeIdentityError(
                "RELEASE_POINTER_RELEASE_MISMATCH",
                "Approved runtime pointer references the wrong release hash.",
            )
        return release, pointer, active

    def promote(
        self,
        record: Mapping[str, object],
        *,
        channel: str = DEFAULT_CHANNEL,
        promoted_at: datetime | None = None,
        current_git_sha: str,
    ) -> tuple[dict[str, object], dict[str, object], bool]:
        self.initialize()
        release_id = str(record.get("releaseId", ""))
        release_path = self.release_path(release_id)
        existing_release = release_path.exists()
        if existing_release:
            release = self.verify_release(release_id)
            if (
                release.get("approvedRuntimeFingerprint")
                != record.get("approvedRuntimeFingerprint")
                or release.get("sourceGitSha") != record.get("sourceGitSha")
                or release.get("qualificationEvidence")
                != record.get("qualificationEvidence")
            ):
                raise OpeningRuntimeIdentityError(
                    "RELEASE_WRITE_CONFLICT",
                    f"Conflicting immutable runtime record exists: {release_path.name}",
                )
        else:
            self._write_once(release_path, record)
            release = self.verify_release(release_id)
        try:
            active_release, pointer, _ = self.verify_channel(channel)
        except OpeningRuntimeIdentityError as exc:
            if exc.code not in {"RELEASE_POINTER_MISSING", "PROMOTION_RECEIPT_MISSING"}:
                raise
            active_release = {}
            pointer = {}
        if active_release.get("releaseId") == release_id:
            return release, pointer, False
        files = self._promotion_files()
        sequence = len(files) + 1
        previous_receipt = ""
        predecessor_release_id = ""
        if files:
            previous = self._read_json(files[-1], "PROMOTION_RECEIPT_MISSING")
            previous_receipt = str(previous.get("receiptFingerprint", ""))
            predecessor_release_id = str(previous.get("releaseId", ""))
        if (
            not existing_release
            and record.get("predecessorReleaseId") != predecessor_release_id
        ):
            raise OpeningRuntimeIdentityError(
                "PROMOTION_PREDECESSOR_MISMATCH",
                "Candidate release predecessor does not match the active chain.",
            )
        receipt: dict[str, object] = {
            "schemaVersion": PROMOTION_SCHEMA,
            "sequence": sequence,
            "channel": channel,
            "releaseId": release_id,
            "releaseFingerprint": release["releaseFingerprint"],
            "predecessorReleaseId": predecessor_release_id,
            "previousReceiptFingerprint": previous_receipt,
            "promotedAt": (promoted_at or datetime.now().astimezone()).isoformat(),
            "releaseSourceGitSha": release["sourceGitSha"],
            "currentGitShaAtPromotion": current_git_sha,
            "promotionPolicyVersion": PROMOTION_POLICY_VERSION,
        }
        receipt["receiptFingerprint"] = payload_fingerprint(
            receipt,
            "receiptFingerprint",
        )
        receipt_path = self._safe_file(
            self.promotions_directory,
            f"{sequence:06d}-{release_id}.json",
        )
        self._write_once(receipt_path, receipt)
        channel_payload: dict[str, object] = {
            "schemaVersion": POINTER_SCHEMA,
            "channel": channel,
            "releaseId": release_id,
            "releaseFingerprint": release["releaseFingerprint"],
            "promotionReceiptFingerprint": receipt["receiptFingerprint"],
            "predecessorReleaseId": predecessor_release_id,
            "updatedAt": receipt["promotedAt"],
        }
        channel_payload["pointerFingerprint"] = payload_fingerprint(
            channel_payload,
            "pointerFingerprint",
        )
        self._atomic_write(self.pointer_path(channel), channel_payload)
        verified_release, verified_pointer, _ = self.verify_channel(channel)
        if verified_release != release or verified_pointer != channel_payload:
            raise OpeningRuntimeIdentityError(
                "PROMOTION_READBACK_FAILED",
                "Approved runtime promotion did not verify after atomic update.",
            )
        return verified_release, verified_pointer, True


def verify_execution_gate(
    context: RuntimeIdentityContext,
    *,
    channel: str = DEFAULT_CHANNEL,
    loaded_supervisor_sha256: str,
    loaded_identity_module_sha256: str,
    loaded_service_host_sha256: str,
    environment: Mapping[str, object] | None = None,
    git_identity: tuple[str, str] | None = None,
) -> OpeningRuntimeGateResult:
    release, _, _ = OpeningRuntimeReleaseStore(context.release_root).verify_channel(
        channel
    )
    current = build_runtime_identity(context, environment=environment)
    current_git_sha, worktree_status = git_identity or current_git_identity(
        context.repository_root
    )
    if worktree_status:
        raise OpeningRuntimeIdentityError(
            "RUNTIME_WORKTREE_DIRTY",
            "Canonical repository is dirty; opening runtime failed closed.",
        )
    components = {
        str(item.get("path")): str(item.get("sha256"))
        for item in release.get("runtimeComponents", [])
        if isinstance(item, dict)
    }
    if components.get("momentum_hunter/automation_supervisor.py") != loaded_supervisor_sha256:
        raise OpeningRuntimeIdentityError(
            "LOADED_SUPERVISOR_MISMATCH",
            "Loaded Automation Supervisor does not match the approved release.",
        )
    if components.get("momentum_hunter/opening_runtime_identity.py") != loaded_identity_module_sha256:
        raise OpeningRuntimeIdentityError(
            "LOADED_IDENTITY_GATE_MISMATCH",
            "Loaded runtime identity gate does not match the approved release.",
        )
    approved_service_host_sha256 = str(
        release.get("environmentIdentity", {})
        .get("serviceHost", {})
        .get("sha256", "")
    )
    if approved_service_host_sha256 != loaded_service_host_sha256:
        raise OpeningRuntimeIdentityError(
            "LOADED_SERVICE_HOST_MISMATCH",
            "Loaded Automation Service host does not match the approved release.",
        )
    approved = str(release.get("approvedRuntimeFingerprint", ""))
    actual = str(current.get("approvedRuntimeFingerprint", ""))
    if actual != approved:
        raise OpeningRuntimeIdentityError(
            "APPROVED_RUNTIME_MISMATCH",
            "Actual opening runtime does not match the approved release.",
            details={"approved": approved, "actual": actual},
        )
    return OpeningRuntimeGateResult(
        channel=channel,
        release_id=str(release["releaseId"]),
        release_fingerprint=str(release["releaseFingerprint"]),
        runtime_surface_fingerprint=str(release["runtimeSurfaceFingerprint"]),
        configuration_fingerprint=str(release["configurationFingerprint"]),
        environment_fingerprint=str(release["environmentFingerprint"]),
        approved_runtime_fingerprint=approved,
        release_source_git_sha=str(release["sourceGitSha"]),
        current_git_sha=current_git_sha,
        current_worktree_clean=True,
        runtime_match=True,
    )


LOADED_RUNTIME_IDENTITY_MODULE_SHA256 = file_sha256(Path(__file__))
