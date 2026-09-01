"""Pure canonicalization and validation helpers for Science evidence custody.

This module has no filesystem, provider, runtime, account, or execution side
effects.  It deliberately supports only the value types admitted by the
recorder contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Mapping


CANONICALIZATION_VERSION = "ARGUS_CANONICAL_JSON_V1"
IDENTITY_NAMESPACE = "argus-science-recorder-v1"
MAX_JSON_BYTES = 64 * 1024 * 1024

_SHA256 = re.compile(r"[0-9a-f]{64}")
_RFC3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})"
)


class CanonicalizationError(ValueError):
    """Raised when bytes or values violate canonical evidence rules."""


def _reject_constant(value: str) -> object:
    raise CanonicalizationError(f"Non-finite JSON number is prohibited: {value}.")


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalizationError(f"Duplicate JSON key is prohibited: {key}.")
        result[key] = value
    return result


def validate_canonical_value(value: object, *, path: str = "$") -> None:
    """Reject ambiguous or unstable semantic JSON values recursively."""

    if value is None:
        raise CanonicalizationError(f"Semantic null is prohibited at {path}.")
    if isinstance(value, float):
        raise CanonicalizationError(f"Semantic floating-point numbers are prohibited at {path}.")
    if isinstance(value, (str, bool, int)):
        return
    if isinstance(value, list) or isinstance(value, tuple):
        for index, item in enumerate(value):
            validate_canonical_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"Non-string object key is prohibited at {path}.")
            validate_canonical_value(item, path=f"{path}.{key}")
        return
    raise CanonicalizationError(
        f"Unsupported canonical value type at {path}: {type(value).__name__}."
    )


def canonical_json_bytes(value: object) -> bytes:
    """Return the contract's deterministic UTF-8 JSON form, including newline."""

    validate_canonical_value(value)
    try:
        encoded = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8", errors="strict")
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        raise CanonicalizationError("Value cannot be encoded as canonical UTF-8 JSON.") from exc
    return encoded


# Public handoff name: the implementation is deliberately explicit about the
# exact canonicalization major it applies.
canonical_json_v1 = canonical_json_bytes


def strict_json_loads(raw: bytes, *, require_canonical: bool = True) -> dict[str, object]:
    """Decode one strict JSON object without duplicate keys or numeric ambiguity."""

    if not isinstance(raw, bytes):
        raise CanonicalizationError("Evidence input must be bytes.")
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise CanonicalizationError("Evidence input is empty or exceeds the bounded read limit.")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CanonicalizationError("UTF-8 BOM is prohibited.")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except CanonicalizationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalizationError("Evidence input is not strict UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise CanonicalizationError("Evidence input must be a JSON object.")
    validate_canonical_value(value)
    if require_canonical and canonical_json_bytes(value) != raw:
        raise CanonicalizationError(
            "Evidence bytes do not match ARGUS_CANONICAL_JSON_V1."
        )
    return value


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise CanonicalizationError(f"{label} must be lowercase SHA-256 hex.")
    return value


def parse_rfc3339(value: object, label: str) -> datetime:
    """Validate an exact offset-bearing semantic timestamp without rewriting it."""

    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise CanonicalizationError(f"{label} must be strict offset-bearing RFC 3339.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanonicalizationError(f"{label} is not a real RFC 3339 instant.") from exc
    if parsed.tzinfo is None:
        raise CanonicalizationError(f"{label} must carry timezone authority.")
    return parsed


def logical_id(identity_type: str, logical_key: Mapping[str, object]) -> str:
    """Allocate an ID from a logical key, never from a record payload."""

    if not isinstance(identity_type, str) or not identity_type:
        raise CanonicalizationError("identity_type must be a nonempty string.")
    material = {
        "identity_type": identity_type,
        "logical_key": dict(logical_key),
        "namespace": IDENTITY_NAMESPACE,
    }
    digest = sha256_hex(canonical_json_bytes(material))
    label = identity_type.lower().replace("_", "-")
    return f"ar1:{label}:{digest}"


def owner_identity(
    identity_kind: str,
    owner_namespace: str,
    owner_id: str,
    *,
    owner_schema_version: str = "1.0.0",
) -> dict[str, object]:
    """Build the exact deterministic wrapper for an owner-issued identity."""

    for label, value in (
        ("identity_kind", identity_kind),
        ("owner_namespace", owner_namespace),
        ("owner_id", owner_id),
        ("owner_schema_version", owner_schema_version),
    ):
        if not isinstance(value, str) or not value:
            raise CanonicalizationError(f"{label} must be a nonempty string.")
    key = {
        "owner_id": owner_id,
        "owner_namespace": owner_namespace,
        "owner_schema_version": owner_schema_version,
    }
    return {
        "allocation_mode": "OWNER_WRAPPED",
        "identity_kind": identity_kind,
        "identity_version": "ARGUS_RECORDER_IDENTITY_V1",
        "owner_id": owner_id,
        "owner_namespace": owner_namespace,
        "owner_schema_version": owner_schema_version,
        "recorder_id": logical_id(identity_kind, key),
    }


def recorder_identity(
    identity_kind: str,
    logical_key: Mapping[str, object],
) -> dict[str, object]:
    """Allocate a durable Science identity from an explicit frozen logical key."""

    if not isinstance(identity_kind, str) or not identity_kind:
        raise CanonicalizationError("identity_kind must be a nonempty string.")
    if not isinstance(logical_key, Mapping) or not logical_key:
        raise CanonicalizationError("logical_key must be a nonempty object.")
    key = dict(logical_key)
    validate_canonical_value(key, path="$.logical_key")
    fingerprint = sha256_hex(canonical_json_bytes(key))
    return {
        "allocation_mode": "RECORDER_DURABLE_ALLOCATED",
        "identity_kind": identity_kind,
        "identity_version": "ARGUS_RECORDER_IDENTITY_V1",
        "logical_key": key,
        "logical_key_fingerprint_sha256": fingerprint,
        "recorder_id": logical_id(identity_kind, key),
    }


__all__ = [
    "CANONICALIZATION_VERSION",
    "CanonicalizationError",
    "canonical_json_bytes",
    "canonical_json_v1",
    "logical_id",
    "owner_identity",
    "recorder_identity",
    "parse_rfc3339",
    "require_sha256",
    "sha256_hex",
    "strict_json_loads",
    "validate_canonical_value",
]
