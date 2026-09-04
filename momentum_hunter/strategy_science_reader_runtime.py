"""Dormant project-native runtime host for the accepted Science Reader-002.

This module supplies identity, state binding, singleton ownership, and a
deterministic service-compatible command line around the already-reviewed
``StrategyScienceSourceReaderV2``.  Importing it has no side effects.  A host
cannot run until a separate activation task supplies an explicit canonical
configuration and initializes fresh durable state against an already-existing
Continuous V2 publication namespace.

The host has research-custody authority only.  It has no provider, scheduler,
service, broker, Paper, Shadow, order, GUI, or strategy-policy capability.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import os
from pathlib import Path
import re
import signal
import sys
import threading
import uuid
from typing import Mapping, Sequence

from momentum_hunter.continuous_research_export import (
    EXPORTER_PROFILE,
    EXPORTER_VERSION,
)
from momentum_hunter.strategy_science_recorder.canonical import (
    canonical_json_v1,
    parse_rfc3339,
    require_sha256,
    sha256_hex,
    strict_json_loads,
)
from momentum_hunter.strategy_science_recorder.contract import (
    AUTHORITY,
    EXECUTION_AUTHORITY,
    REPAIRED_EXPORT_SCHEMA_VERSION,
    REPAIRED_SOURCE_CONTRACT,
    REPAIRED_SOURCE_CONTRACT_VERSION,
)
from momentum_hunter.strategy_science_recorder.custody import StrategyScienceRecorder
from momentum_hunter.strategy_science_source_reader import (
    READER_PROFILE,
    READER_VERSION,
    SourceReaderError,
    SourceReaderRun,
    StrategyScienceSourceReaderV2,
)


RUNTIME_PROFILE = "ARGUS_SCIENCE_READER_002_RUNTIME_HOST_V1"
RUNTIME_VERSION = "ARGUS-SCIENCE-READER-002-RUNTIME-HOST-AND-STATE-IDENTITY-001-v1"
RUNTIME_IDENTITY = "ARGUS-SCIENCE-READER-002-PROSPECTIVE-RESEARCH-RUNTIME-V1"
RUNTIME_CONFIG_VERSION = 1
STATE_IDENTITY_VERSION = 1
PUBLICATION_IDENTITY_VERSION = 1
RUNTIME_OWNER_VERSION = 1
DEPLOYMENT_CLASS = "AUTHORIZED_DURABLE_RESEARCH_RUNTIME"
STORAGE_CLASS = "DURABLE_NON_EPHEMERAL"
INVOCATION_CONTRACT = "PROJECT_NATIVE_READER_002_RUNTIME_HOST"
UPSTREAM_SOURCE_DEPENDENCY = (
    "REQUIRES_SEPARATE_CONTINUOUS_V2_UPSTREAM_ACTIVATION_AND_IDENTITY_BINDING"
)

# Accepted Git-blob byte identity.  Windows checkout CRLF is normalized to the
# authoritative LF Git blob before this SHA-256 gate is evaluated.
ACCEPTED_READER_MODULE_SHA256 = (
    "985b9823e60b32ab7d080bb5cf4c3c34af8867165e506166b71db553280a311e"
)
ACCEPTED_READER_CANDIDATE_AGGREGATE_SHA256 = (
    "18d2395fa493687aae95c7b858b457d1d9f429bb830cb69fbd6e5335a14c5d92"
)

PUBLICATION_METADATA_FIELDS = frozenset(
    {
        "authority",
        "execution_authority",
        "exporter_profile",
        "exporter_version",
        "schema_version",
        "session_id",
        "source_contract",
        "source_contract_version",
        "source_interface_identity",
        "source_owner_identity",
        "source_root_identity",
    }
)
CONFIG_FIELDS = frozenset(
    {
        "authority",
        "deployment_class",
        "deployment_instance_id",
        "execution_authority",
        "expected_publication_metadata_sha256",
        "expected_publication_root_identity",
        "expected_source_root_identity",
        "invocation_contract",
        "poll_interval_milliseconds",
        "publication_root",
        "runtime_config_version",
        "runtime_identity",
        "runtime_profile",
        "science_root",
        "state_root",
        "storage_class",
        "upstream_source_dependency",
    }
)
_INSTANCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")


class ReaderRuntimeError(RuntimeError):
    """Base fail-closed error for Reader-002 runtime hosting."""


class ReaderRuntimeConfigError(ReaderRuntimeError):
    """The explicit runtime configuration is absent or invalid."""


class ReaderRuntimeIdentityError(ReaderRuntimeError):
    """A source, state, custody, or accepted-code identity differs."""


class ReaderRuntimeSingletonError(ReaderRuntimeError):
    """Runtime ownership is duplicate, malformed, or ambiguous."""


@dataclass(frozen=True)
class PublicationIdentity:
    metadata_sha256: str
    publication_root_identity: str
    source_root_identity: str


@dataclass(frozen=True)
class ReaderRuntimeConfig:
    authority: str
    deployment_class: str
    deployment_instance_id: str
    execution_authority: str
    expected_publication_metadata_sha256: str
    expected_publication_root_identity: str
    expected_source_root_identity: str
    invocation_contract: str
    poll_interval_milliseconds: int
    publication_root: Path
    runtime_config_version: int
    runtime_identity: str
    runtime_profile: str
    science_root: Path
    state_root: Path
    storage_class: str
    upstream_source_dependency: str

    def canonical_value(self) -> dict[str, object]:
        value = asdict(self)
        for field in ("publication_root", "science_root", "state_root"):
            value[field] = str(value[field])
        return value

    @property
    def fingerprint_sha256(self) -> str:
        return sha256_hex(canonical_json_v1(self.canonical_value()))


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReaderRuntimeConfigError(f"{label} must be nonempty text.")
    return value


def _absolute_path(value: object, label: str) -> Path:
    text = _nonempty_text(value, label)
    path = Path(text)
    if not path.is_absolute():
        raise ReaderRuntimeConfigError(f"{label} must be an explicit absolute path.")
    if str(path) != text:
        raise ReaderRuntimeConfigError(f"{label} must use its exact native absolute form.")
    return path


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _require_disjoint(paths: Sequence[tuple[str, Path]]) -> None:
    resolved = [(name, path.resolve(strict=False)) for name, path in paths]
    for index, (left_name, left) in enumerate(resolved):
        for right_name, right in resolved[index + 1 :]:
            if left == right or _is_within(left, right) or _is_within(right, left):
                raise ReaderRuntimeConfigError(
                    f"{left_name} and {right_name} must be disjoint roots."
                )


def load_runtime_config(path: Path) -> ReaderRuntimeConfig:
    """Load one canonical, path-explicit runtime configuration without defaults."""

    config_path = Path(path)
    if not config_path.is_absolute():
        raise ReaderRuntimeConfigError("Runtime configuration path must be absolute.")
    if (
        not config_path.is_file()
        or config_path.is_symlink()
        or config_path.stat(follow_symlinks=False).st_nlink != 1
    ):
        raise ReaderRuntimeConfigError("Runtime configuration must be one regular file.")
    try:
        before = config_path.stat(follow_symlinks=False)
        raw = config_path.read_bytes()
        after = config_path.stat(follow_symlinks=False)
        value = strict_json_loads(raw)
    except (OSError, ValueError) as exc:
        raise ReaderRuntimeConfigError("Runtime configuration is unreadable or noncanonical.") from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise ReaderRuntimeConfigError("Runtime configuration changed while being read.")
    if set(value) != CONFIG_FIELDS:
        raise ReaderRuntimeConfigError("Runtime configuration has missing or unknown fields.")

    required = {
        "authority": AUTHORITY,
        "deployment_class": DEPLOYMENT_CLASS,
        "execution_authority": EXECUTION_AUTHORITY,
        "invocation_contract": INVOCATION_CONTRACT,
        "runtime_config_version": RUNTIME_CONFIG_VERSION,
        "runtime_identity": RUNTIME_IDENTITY,
        "runtime_profile": RUNTIME_PROFILE,
        "storage_class": STORAGE_CLASS,
        "upstream_source_dependency": UPSTREAM_SOURCE_DEPENDENCY,
    }
    for field, expected in required.items():
        if value.get(field) != expected:
            raise ReaderRuntimeConfigError(f"Runtime configuration differs at {field}.")
    deployment_id = value.get("deployment_instance_id")
    if not isinstance(deployment_id, str) or _INSTANCE_ID.fullmatch(deployment_id) is None:
        raise ReaderRuntimeConfigError("deployment_instance_id is invalid.")
    interval = value.get("poll_interval_milliseconds")
    if isinstance(interval, bool) or not isinstance(interval, int) or not 100 <= interval <= 300_000:
        raise ReaderRuntimeConfigError(
            "poll_interval_milliseconds must be an integer from 100 through 300000."
        )
    try:
        metadata_sha = require_sha256(
            value.get("expected_publication_metadata_sha256"),
            "expected_publication_metadata_sha256",
        )
        publication_identity = require_sha256(
            value.get("expected_publication_root_identity"),
            "expected_publication_root_identity",
        )
        source_identity = require_sha256(
            value.get("expected_source_root_identity"),
            "expected_source_root_identity",
        )
    except ValueError as exc:
        raise ReaderRuntimeConfigError(str(exc)) from exc

    publication_root = _absolute_path(value.get("publication_root"), "publication_root")
    state_root = _absolute_path(value.get("state_root"), "state_root")
    science_root = _absolute_path(value.get("science_root"), "science_root")
    if publication_root.name != "published":
        raise ReaderRuntimeConfigError("publication_root must name the canonical published directory.")
    _require_disjoint(
        (
            ("publication_root", publication_root),
            ("state_root", state_root),
            ("science_root", science_root),
        )
    )
    return ReaderRuntimeConfig(
        authority=AUTHORITY,
        deployment_class=DEPLOYMENT_CLASS,
        deployment_instance_id=deployment_id,
        execution_authority=EXECUTION_AUTHORITY,
        expected_publication_metadata_sha256=metadata_sha,
        expected_publication_root_identity=publication_identity,
        expected_source_root_identity=source_identity,
        invocation_contract=INVOCATION_CONTRACT,
        poll_interval_milliseconds=interval,
        publication_root=publication_root,
        runtime_config_version=RUNTIME_CONFIG_VERSION,
        runtime_identity=RUNTIME_IDENTITY,
        runtime_profile=RUNTIME_PROFILE,
        science_root=science_root,
        state_root=state_root,
        storage_class=STORAGE_CLASS,
        upstream_source_dependency=UPSTREAM_SOURCE_DEPENDENCY,
    )


def verify_accepted_reader_bytes() -> str:
    """Prove that the host imports the exact accepted LF-normalized Reader blob."""

    source = inspect.getsourcefile(StrategyScienceSourceReaderV2)
    if source is None:
        raise ReaderRuntimeIdentityError("Accepted Reader source identity is unavailable.")
    try:
        raw = Path(source).read_bytes()
    except OSError as exc:
        raise ReaderRuntimeIdentityError("Accepted Reader source bytes are unreadable.") from exc
    digest = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    if digest != ACCEPTED_READER_MODULE_SHA256 or READER_VERSION != (
        "ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002-v1"
    ):
        raise ReaderRuntimeIdentityError("Loaded Reader bytes are not the accepted Reader-002.")
    return digest


def derive_publication_root_identity(
    publication_root: Path,
    *,
    metadata_sha256: str,
    source_root_identity: str,
) -> str:
    """Bind an already-existing publication namespace to path and contract lineage."""

    try:
        metadata_sha = require_sha256(metadata_sha256, "metadata_sha256")
        source_sha = require_sha256(source_root_identity, "source_root_identity")
    except ValueError as exc:
        raise ReaderRuntimeIdentityError(str(exc)) from exc
    root = Path(publication_root)
    if not root.is_absolute():
        raise ReaderRuntimeIdentityError("Publication identity requires an absolute root.")
    material = {
        "authority": AUTHORITY,
        "execution_authority": EXECUTION_AUTHORITY,
        "identity_type": "CONTINUOUS_V2_PUBLICATION_ROOT",
        "identity_version": PUBLICATION_IDENTITY_VERSION,
        "metadata_sha256": metadata_sha,
        "publication_root": str(root.resolve(strict=True)),
        "schema_version": REPAIRED_EXPORT_SCHEMA_VERSION,
        "source_contract": REPAIRED_SOURCE_CONTRACT,
        "source_contract_version": REPAIRED_SOURCE_CONTRACT_VERSION,
        "source_root_identity": source_sha,
    }
    return sha256_hex(canonical_json_v1(material))


def _read_stable_regular(path: Path, label: str) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ReaderRuntimeIdentityError(f"{label} must be one regular non-link file.")
    try:
        before = path.stat(follow_symlinks=False)
        raw = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ReaderRuntimeIdentityError(f"{label} is not durably readable.") from exc
    if before.st_nlink != 1 or after.st_nlink != 1:
        raise ReaderRuntimeIdentityError(f"{label} must not be hard-linked.")
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise ReaderRuntimeIdentityError(f"{label} changed while being read.")
    return raw


def verify_publication_identity(config: ReaderRuntimeConfig) -> PublicationIdentity:
    root = config.publication_root
    if not root.is_dir() or root.is_symlink():
        raise ReaderRuntimeIdentityError(
            "Authorized Continuous V2 published namespace is absent or linked."
        )
    metadata_path = root.parent / "publication-identity.json"
    raw = _read_stable_regular(metadata_path, "Continuous V2 publication identity")
    if sha256_hex(raw) != config.expected_publication_metadata_sha256:
        raise ReaderRuntimeIdentityError("Publication metadata byte identity differs.")
    try:
        metadata = strict_json_loads(raw)
    except ValueError as exc:
        raise ReaderRuntimeIdentityError("Publication metadata is not canonical JSON.") from exc
    if set(metadata) != PUBLICATION_METADATA_FIELDS:
        raise ReaderRuntimeIdentityError("Publication metadata has missing or unknown fields.")
    required = {
        "authority": AUTHORITY,
        "execution_authority": EXECUTION_AUTHORITY,
        "exporter_profile": EXPORTER_PROFILE,
        "exporter_version": EXPORTER_VERSION,
        "schema_version": REPAIRED_EXPORT_SCHEMA_VERSION,
        "source_contract": REPAIRED_SOURCE_CONTRACT,
        "source_contract_version": REPAIRED_SOURCE_CONTRACT_VERSION,
        "source_root_identity": config.expected_source_root_identity,
    }
    for field, expected in required.items():
        if metadata.get(field) != expected:
            raise ReaderRuntimeIdentityError(f"Publication metadata differs at {field}.")
    for field in ("source_interface_identity", "source_owner_identity"):
        if not isinstance(metadata.get(field), str) or not metadata[field]:
            raise ReaderRuntimeIdentityError(f"Publication metadata {field} is empty.")
    if not isinstance(metadata.get("session_id"), Mapping):
        raise ReaderRuntimeIdentityError("Publication metadata session_id is absent.")
    derived = derive_publication_root_identity(
        root,
        metadata_sha256=sha256_hex(raw),
        source_root_identity=config.expected_source_root_identity,
    )
    if derived != config.expected_publication_root_identity:
        raise ReaderRuntimeIdentityError("Publication root identity differs from configuration.")
    return PublicationIdentity(
        metadata_sha256=sha256_hex(raw),
        publication_root_identity=derived,
        source_root_identity=config.expected_source_root_identity,
    )


def _state_binding(config: ReaderRuntimeConfig, publication: PublicationIdentity) -> dict[str, object]:
    material = {
        "accepted_reader_candidate_aggregate_sha256": (
            ACCEPTED_READER_CANDIDATE_AGGREGATE_SHA256
        ),
        "accepted_reader_module_sha256": ACCEPTED_READER_MODULE_SHA256,
        "authority": AUTHORITY,
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "deployment_instance_id": config.deployment_instance_id,
        "execution_authority": EXECUTION_AUTHORITY,
        "publication_metadata_sha256": publication.metadata_sha256,
        "publication_root": str(config.publication_root.resolve(strict=True)),
        "publication_root_identity": publication.publication_root_identity,
        "reader_profile": READER_PROFILE,
        "reader_version": READER_VERSION,
        "runtime_identity": RUNTIME_IDENTITY,
        "runtime_profile": RUNTIME_PROFILE,
        "runtime_version": RUNTIME_VERSION,
        "schema_version": REPAIRED_EXPORT_SCHEMA_VERSION,
        "science_root": str(config.science_root.resolve(strict=False)),
        "source_contract": REPAIRED_SOURCE_CONTRACT,
        "source_contract_version": REPAIRED_SOURCE_CONTRACT_VERSION,
        "source_root_identity": publication.source_root_identity,
        "state_identity_version": STATE_IDENTITY_VERSION,
        "state_root": str(config.state_root.resolve(strict=False)),
    }
    return {
        **material,
        "state_binding_sha256": sha256_hex(canonical_json_v1(material)),
    }


def _runtime_identity_value(
    config: ReaderRuntimeConfig, state_binding_sha256: str
) -> dict[str, object]:
    return {
        "authority": AUTHORITY,
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "deployment_instance_id": config.deployment_instance_id,
        "execution_authority": EXECUTION_AUTHORITY,
        "invocation_contract": INVOCATION_CONTRACT,
        "runtime_identity": RUNTIME_IDENTITY,
        "runtime_owner_version": RUNTIME_OWNER_VERSION,
        "runtime_profile": RUNTIME_PROFILE,
        "runtime_version": RUNTIME_VERSION,
        "state_binding_sha256": state_binding_sha256,
    }


def _custody_identity_value(
    config: ReaderRuntimeConfig, state_binding_sha256: str
) -> dict[str, object]:
    return {
        "authority": AUTHORITY,
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "custody_root": str(config.science_root.resolve(strict=False)),
        "deployment_instance_id": config.deployment_instance_id,
        "execution_authority": EXECUTION_AUTHORITY,
        "owner_runtime_identity": RUNTIME_IDENTITY,
        "profile": "ARGUS_SCIENCE_READER_002_CUSTODY_ROOT_IDENTITY_V1",
        "source_root_identity": config.expected_source_root_identity,
        "state_binding_sha256": state_binding_sha256,
    }


def _atomic_write_once(path: Path, raw: bytes) -> None:
    partial = path.parent / ".identity-partial"
    partial.mkdir(parents=True, exist_ok=True)
    temp = partial / f"{uuid.uuid4().hex}.tmp"
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            if _read_stable_regular(path, path.name) != raw:
                raise ReaderRuntimeIdentityError(f"Write-once identity conflicts at {path}.")
    finally:
        temp.unlink(missing_ok=True)


def _require_fresh_or_bound_root(path: Path, allowed: frozenset[str], label: str) -> None:
    if path.exists():
        if not path.is_dir() or path.is_symlink():
            raise ReaderRuntimeIdentityError(f"{label} must be one non-link directory.")
        unknown = {entry.name for entry in path.iterdir()} - allowed
        if unknown:
            raise ReaderRuntimeIdentityError(
                f"{label} already contains unbound or historical content."
            )
        return
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ReaderRuntimeIdentityError(
            f"The explicit durable parent for {label} must already exist."
        )
    path.mkdir()


def _owner_value(
    config: ReaderRuntimeConfig,
    state_binding_sha256: str,
    *,
    status: str,
    process_instance_id: str,
    process_id: int,
) -> dict[str, object]:
    return {
        "authority": AUTHORITY,
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "deployment_instance_id": config.deployment_instance_id,
        "execution_authority": EXECUTION_AUTHORITY,
        "invocation_contract": INVOCATION_CONTRACT,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "process_id": process_id,
        "process_instance_id": process_instance_id,
        "runtime_identity": RUNTIME_IDENTITY,
        "runtime_owner_version": RUNTIME_OWNER_VERSION,
        "runtime_profile": RUNTIME_PROFILE,
        "state_binding_sha256": state_binding_sha256,
        "status": status,
    }


def _atomic_replace(path: Path, raw: bytes) -> None:
    partial = path.parent / ".identity-partial"
    partial.mkdir(parents=True, exist_ok=True)
    temp = partial / f"{uuid.uuid4().hex}.tmp"
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def initialize_state(config: ReaderRuntimeConfig) -> dict[str, object]:
    """Bind fresh durable roots; never create source or consume publications."""

    verify_accepted_reader_bytes()
    publication = verify_publication_identity(config)
    _require_fresh_or_bound_root(
        config.state_root,
        frozenset({".identity-partial", "reader-state-identity.json", "runtime"}),
        "Reader state root",
    )
    _require_fresh_or_bound_root(
        config.science_root,
        frozenset({".identity-partial", "reader-custody-root-identity.json"}),
        "Science custody root",
    )
    runtime_root = config.state_root / "runtime"
    runtime_root.mkdir(exist_ok=True)
    if runtime_root.is_symlink():
        raise ReaderRuntimeIdentityError("Runtime state namespace must not be linked.")
    binding = _state_binding(config, publication)
    binding_sha = str(binding["state_binding_sha256"])
    _atomic_write_once(
        config.state_root / "reader-state-identity.json",
        canonical_json_v1(binding),
    )
    _atomic_write_once(
        runtime_root / "runtime-identity.json",
        canonical_json_v1(_runtime_identity_value(config, binding_sha)),
    )
    _atomic_write_once(
        config.science_root / "reader-custody-root-identity.json",
        canonical_json_v1(_custody_identity_value(config, binding_sha)),
    )
    lock_path = runtime_root / "reader-runtime.lock"
    if not lock_path.exists():
        try:
            with lock_path.open("xb") as handle:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            pass
    initialization_lock = _RuntimeLock(lock_path)
    initialization_lock.acquire()
    try:
        owner_path = runtime_root / "active-owner.json"
        if owner_path.exists():
            _validate_owner(config, binding_sha)
        _atomic_replace(
            owner_path,
            canonical_json_v1(
                _owner_value(
                    config,
                    binding_sha,
                    status="STOPPED",
                    process_instance_id="NONE",
                    process_id=0,
                )
            ),
        )
    finally:
        initialization_lock.release()
    return validate_state(config)


def _read_canonical_identity(path: Path, expected: Mapping[str, object], label: str) -> None:
    try:
        raw = _read_stable_regular(path, label)
        value = strict_json_loads(raw)
    except ValueError as exc:
        raise ReaderRuntimeIdentityError(f"{label} is not canonical JSON.") from exc
    if value != dict(expected):
        raise ReaderRuntimeIdentityError(f"{label} differs from the authorized binding.")


def validate_state(config: ReaderRuntimeConfig) -> dict[str, object]:
    """Verify source, accepted Reader bytes, immutable bindings, and owner metadata."""

    reader_sha = verify_accepted_reader_bytes()
    publication = verify_publication_identity(config)
    if not config.state_root.is_dir() or config.state_root.is_symlink():
        raise ReaderRuntimeIdentityError("Reader state root is absent or linked.")
    if not config.science_root.is_dir() or config.science_root.is_symlink():
        raise ReaderRuntimeIdentityError("Science custody root is absent or linked.")
    state_entries = {entry.name for entry in config.state_root.iterdir()}
    allowed_state_entries = {
        ".identity-partial",
        ".reader.lock",
        "cursors",
        "reader-state-identity.json",
        "runtime",
    }
    if state_entries - allowed_state_entries:
        raise ReaderRuntimeIdentityError("Reader state root contains an unknown object.")
    runtime_root = config.state_root / "runtime"
    if not runtime_root.is_dir() or runtime_root.is_symlink():
        raise ReaderRuntimeIdentityError("Reader runtime state namespace is absent or linked.")
    runtime_entries = {entry.name for entry in runtime_root.iterdir()}
    if runtime_entries != {
        ".identity-partial",
        "active-owner.json",
        "reader-runtime.lock",
        "runtime-identity.json",
    }:
        raise ReaderRuntimeIdentityError("Reader runtime state namespace is incomplete or unknown.")
    for partial_root in (
        config.state_root / ".identity-partial",
        runtime_root / ".identity-partial",
        config.science_root / ".identity-partial",
    ):
        if not partial_root.is_dir() or partial_root.is_symlink() or any(partial_root.iterdir()):
            raise ReaderRuntimeIdentityError("Identity partial namespace is not clean.")
    binding = _state_binding(config, publication)
    binding_sha = str(binding["state_binding_sha256"])
    _read_canonical_identity(
        config.state_root / "reader-state-identity.json", binding, "Reader state identity"
    )
    _read_canonical_identity(
        config.state_root / "runtime" / "runtime-identity.json",
        _runtime_identity_value(config, binding_sha),
        "Reader runtime identity",
    )
    _read_canonical_identity(
        config.science_root / "reader-custody-root-identity.json",
        _custody_identity_value(config, binding_sha),
        "Science custody root identity",
    )
    lock_path = config.state_root / "runtime" / "reader-runtime.lock"
    if (
        not lock_path.is_file()
        or lock_path.is_symlink()
        or lock_path.stat(follow_symlinks=False).st_nlink != 1
        or lock_path.stat(follow_symlinks=False).st_size != 1
    ):
        raise ReaderRuntimeIdentityError("Reader runtime lock identity is absent or linked.")
    _validate_owner(config, binding_sha)
    return {
        "accepted_reader_module_sha256": reader_sha,
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "publication_root_identity": publication.publication_root_identity,
        "runtime_identity": RUNTIME_IDENTITY,
        "state_binding_sha256": binding_sha,
        "status": "VALID",
        "upstream_source_dependency": UPSTREAM_SOURCE_DEPENDENCY,
    }


def _validate_owner(
    config: ReaderRuntimeConfig, state_binding_sha256: str
) -> Mapping[str, object]:
    path = config.state_root / "runtime" / "active-owner.json"
    try:
        value = strict_json_loads(_read_stable_regular(path, "Reader runtime owner"))
    except ValueError as exc:
        raise ReaderRuntimeSingletonError("Reader runtime owner is not canonical JSON.") from exc
    expected = {
        "authority": AUTHORITY,
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "deployment_instance_id": config.deployment_instance_id,
        "execution_authority": EXECUTION_AUTHORITY,
        "invocation_contract": INVOCATION_CONTRACT,
        "runtime_identity": RUNTIME_IDENTITY,
        "runtime_owner_version": RUNTIME_OWNER_VERSION,
        "runtime_profile": RUNTIME_PROFILE,
        "state_binding_sha256": state_binding_sha256,
    }
    for field, required in expected.items():
        if value.get(field) != required:
            raise ReaderRuntimeSingletonError(f"Runtime owner differs at {field}.")
    if set(value) != set(expected) | {
        "observed_at", "process_id", "process_instance_id", "status"
    }:
        raise ReaderRuntimeSingletonError("Runtime owner has missing or unknown fields.")
    if value.get("status") not in {"RUNNING", "STOPPED"}:
        raise ReaderRuntimeSingletonError("Runtime owner status is ambiguous.")
    if not isinstance(value.get("process_id"), int) or isinstance(value.get("process_id"), bool):
        raise ReaderRuntimeSingletonError("Runtime owner process_id is invalid.")
    if not isinstance(value.get("process_instance_id"), str) or not value["process_instance_id"]:
        raise ReaderRuntimeSingletonError("Runtime owner process identity is invalid.")
    if not isinstance(value.get("observed_at"), str) or not value["observed_at"]:
        raise ReaderRuntimeSingletonError("Runtime owner timestamp is invalid.")
    try:
        parse_rfc3339(value["observed_at"], "runtime owner observed_at")
    except ValueError as exc:
        raise ReaderRuntimeSingletonError("Runtime owner timestamp is invalid.") from exc
    if value["status"] == "RUNNING":
        if value["process_id"] < 1:
            raise ReaderRuntimeSingletonError("RUNNING owner process_id is invalid.")
        try:
            uuid.UUID(str(value["process_instance_id"]))
        except ValueError as exc:
            raise ReaderRuntimeSingletonError(
                "RUNNING owner process instance identity is invalid."
            ) from exc
    elif value["process_id"] < 0:
        raise ReaderRuntimeSingletonError("STOPPED owner process_id is invalid.")
    return value


class _RuntimeLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: object | None = None

    def acquire(self) -> None:
        try:
            handle = self.path.open("r+b")
        except OSError as exc:
            raise ReaderRuntimeSingletonError("Runtime lock is unavailable.") from exc
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise ReaderRuntimeSingletonError(
                "Another Reader-002 runtime owns the durable Science state."
            ) from exc
        self.handle = handle

    def release(self) -> None:
        handle = self.handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self.handle = None


def probe_instance_state(config: ReaderRuntimeConfig) -> str:
    """Return ZERO_INSTANCES or ONE_AUTHORIZED_INSTANCE; ambiguity raises."""

    state = validate_state(config)
    binding_sha = str(state["state_binding_sha256"])
    lock = _RuntimeLock(config.state_root / "runtime" / "reader-runtime.lock")
    try:
        lock.acquire()
    except ReaderRuntimeSingletonError:
        owner = _validate_owner(config, binding_sha)
        if owner["status"] != "RUNNING":
            raise ReaderRuntimeSingletonError(
                "Runtime lock is held but durable owner does not prove RUNNING."
            )
        return "ONE_AUTHORIZED_INSTANCE"
    else:
        lock.release()
        _validate_owner(config, binding_sha)
        return "ZERO_INSTANCES"


class StrategyScienceReaderRuntime:
    """Own the project-native runtime and the exact accepted Reader lifecycle."""

    def __init__(self, config: ReaderRuntimeConfig) -> None:
        self.config = config
        self._lock: _RuntimeLock | None = None
        self._recorder: StrategyScienceRecorder | None = None
        self._reader: StrategyScienceSourceReaderV2 | None = None
        self._binding_sha256 = ""
        self._process_instance_id = ""

    def __enter__(self) -> "StrategyScienceReaderRuntime":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def start(self) -> None:
        if self._lock is not None:
            raise ReaderRuntimeSingletonError("Runtime host is already started.")
        state = validate_state(self.config)
        binding_sha = str(state["state_binding_sha256"])
        lock = _RuntimeLock(self.config.state_root / "runtime" / "reader-runtime.lock")
        lock.acquire()
        process_instance_id = str(uuid.uuid4())
        try:
            _validate_owner(self.config, binding_sha)
            _atomic_replace(
                self.config.state_root / "runtime" / "active-owner.json",
                canonical_json_v1(
                    _owner_value(
                        self.config,
                        binding_sha,
                        status="RUNNING",
                        process_instance_id=process_instance_id,
                        process_id=os.getpid(),
                    )
                ),
            )
            recorder = StrategyScienceRecorder(
                self.config.science_root,
                source_root_identity=self.config.expected_source_root_identity,
                writer_instance_id=(
                    f"{RUNTIME_IDENTITY}:{self.config.deployment_instance_id}:"
                    f"{self.config.fingerprint_sha256}"
                ),
                clock=lambda: datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            )
            try:
                reader = StrategyScienceSourceReaderV2(
                    self.config.publication_root,
                    self.config.state_root,
                    recorder=recorder,
                )
            except BaseException:
                recorder.close()
                raise
        except BaseException:
            _atomic_replace(
                self.config.state_root / "runtime" / "active-owner.json",
                canonical_json_v1(
                    _owner_value(
                        self.config,
                        binding_sha,
                        status="STOPPED",
                        process_instance_id=process_instance_id,
                        process_id=os.getpid(),
                    )
                ),
            )
            lock.release()
            raise
        self._binding_sha256 = binding_sha
        self._process_instance_id = process_instance_id
        self._lock = lock
        self._recorder = recorder
        self._reader = reader

    def stop(self) -> None:
        lock = self._lock
        if lock is None:
            return
        close_error: BaseException | None = None
        try:
            if self._reader is not None:
                try:
                    self._reader.close()
                except BaseException as exc:
                    close_error = exc
            if self._recorder is not None:
                try:
                    self._recorder.close()
                except BaseException as exc:
                    if close_error is None:
                        close_error = exc
            _atomic_replace(
                self.config.state_root / "runtime" / "active-owner.json",
                canonical_json_v1(
                    _owner_value(
                        self.config,
                        self._binding_sha256,
                        status="STOPPED",
                        process_instance_id=self._process_instance_id,
                        process_id=os.getpid(),
                    )
                ),
            )
        finally:
            lock.release()
            self._reader = None
            self._recorder = None
            self._lock = None
        if close_error is not None:
            raise close_error

    def consume_once(
        self, *, crash_phase: str | None = None, max_items: int | None = None
    ) -> SourceReaderRun:
        if self._reader is None:
            raise ReaderRuntimeError("Runtime host is not started.")
        return self._reader.consume_available(
            crash_phase=crash_phase,
            max_items=max_items,
        )

    def run_until_stopped(self, stop_event: threading.Event) -> dict[str, object]:
        """Poll deterministically until signal, requested stop, or Producer FINAL."""

        if self._reader is None:
            raise ReaderRuntimeError("Runtime host is not started.")
        admitted = 0
        while not stop_event.is_set():
            result = self.consume_once(max_items=1)
            admitted += len(result.admissions)
            if result.cursor.terminal:
                return {
                    "admissions": admitted,
                    "last_publication_ordinal": result.cursor.last_publication_ordinal,
                    "reason": "PRODUCER_FINAL_ADMITTED",
                    "status": result.status,
                }
            stop_event.wait(self.config.poll_interval_milliseconds / 1000)
        return {
            "admissions": admitted,
            "reason": "STOP_REQUESTED",
            "status": "STOPPED_CLEANLY",
        }


def _print_result(value: Mapping[str, object]) -> None:
    sys.stdout.buffer.write(canonical_json_v1(dict(value)))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dormant Strategy Science Reader-002 host")
    parser.add_argument(
        "command", choices=("initialize-state", "validate", "probe", "run-once", "run")
    )
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(args.config)
        if args.command == "initialize-state":
            _print_result(initialize_state(config))
            return 0
        if args.command == "validate":
            _print_result(validate_state(config))
            return 0
        if args.command == "probe":
            _print_result(
                {"runtime_identity": RUNTIME_IDENTITY, "singleton_state": probe_instance_state(config)}
            )
            return 0
        with StrategyScienceReaderRuntime(config) as runtime:
            if args.command == "run-once":
                result = runtime.consume_once()
                _print_result(
                    {
                        "admissions": len(result.admissions),
                        "last_publication_ordinal": result.cursor.last_publication_ordinal,
                        "status": result.status,
                        "terminal": result.cursor.terminal,
                    }
                )
                return 0
            stop = threading.Event()

            def request_stop(_signum: int, _frame: object) -> None:
                stop.set()

            prior = {}
            for signum in (signal.SIGINT, signal.SIGTERM):
                prior[signum] = signal.signal(signum, request_stop)
            try:
                _print_result(runtime.run_until_stopped(stop))
            finally:
                for signum, handler in prior.items():
                    signal.signal(signum, handler)
            return 0
    except (ReaderRuntimeError, SourceReaderError) as exc:
        sys.stderr.write(f"FAIL_CLOSED: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCEPTED_READER_CANDIDATE_AGGREGATE_SHA256",
    "ACCEPTED_READER_MODULE_SHA256",
    "DEPLOYMENT_CLASS",
    "INVOCATION_CONTRACT",
    "PublicationIdentity",
    "RUNTIME_IDENTITY",
    "RUNTIME_PROFILE",
    "RUNTIME_VERSION",
    "ReaderRuntimeConfig",
    "ReaderRuntimeConfigError",
    "ReaderRuntimeError",
    "ReaderRuntimeIdentityError",
    "ReaderRuntimeSingletonError",
    "STORAGE_CLASS",
    "StrategyScienceReaderRuntime",
    "UPSTREAM_SOURCE_DEPENDENCY",
    "derive_publication_root_identity",
    "initialize_state",
    "load_runtime_config",
    "main",
    "probe_instance_state",
    "validate_state",
    "verify_accepted_reader_bytes",
    "verify_publication_identity",
]
