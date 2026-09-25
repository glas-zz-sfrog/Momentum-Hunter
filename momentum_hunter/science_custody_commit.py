"""Mechanical, write-once Science commits performed by the existing Writer.

This module grants no filesystem authority.  The production construction path
must supply the native, account-separated backend; a structural test backend
is useful for protocol tests but is not proof of Windows ownership or security.
Scientific records retain their exact bytes and their existing semantic gates.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Callable, ContextManager, Mapping, Protocol

from momentum_hunter.strategy_science_recorder.canonical import (
    canonical_json_bytes,
    strict_json_loads,
)


PROTOCOL_VERSION = "SCIENCE_CUSTODY_COMMIT_007_V1"
COMPLETION_VERSION = "SCIENCE_CUSTODY_DURABILITY_016E_V1"
MAX_REQUEST_BYTES = 64 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}")
_GENERATION = re.compile(r"[0-9a-f]{32}")
_EVENT = re.compile(r"([0-9]{20})-([0-9a-f]{64})\.event\.json")
_CURSOR = re.compile(r"([0-9]{20})-([0-9a-f]{64})\.reader-cursor\.json")
_CHECKPOINT = re.compile(r"([0-9]{20})-([0-9a-f]{64})\.checkpoint\.json")
_ROOTS = frozenset({"arrivals", "custody", "cursors"})
_ROLES = frozenset({
    "ARRIVAL", "CURSOR", "SOURCE", "PAYLOAD", "SCIENTIFIC_RECEIPT",
    "CHECKPOINT", "FINAL_MANIFEST", "FINAL_CHECKSUM", "CONFLICT_RAW",
    "CONFLICT_RECEIPT", "QUARANTINE_RECEIPT",
})
_CHANNELS = frozenset({"session", "discovery", "decision", "market", "health", "outcome"})


class CustodyCommitError(RuntimeError):
    """An input or state cannot satisfy the custody protocol."""


class CustodyCommitConflict(CustodyCommitError):
    """One logical identity has already reserved different bytes or a path."""


class CustodyCommitPending(CustodyCommitError):
    """Outcome is pending; staging must not be discarded or replaced."""


class CustodyCommitIntegrityError(CustodyCommitError):
    """Durable identity, bytes or security evidence contradict the protocol."""


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value: object) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise CustodyCommitError("Expected one lower-case SHA256 value.")
    return value


def _text(value: object, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise CustodyCommitError("Invalid bounded identity text.")
    return value


def _integer(value: object, *, minimum: int = 0, maximum: int = MAX_ARTIFACT_BYTES) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CustodyCommitError("Invalid bounded integer.")
    return value


def _file_identity(value: object) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CustodyCommitIntegrityError("Missing native volume/file identity.")
    return tuple(_integer(x, maximum=0xFFFFFFFF) for x in value)


def canonical_protocol_bytes(value: object) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise CustodyCommitError("Invalid protocol serialization.") from exc


def _decode(raw: bytes, *, maximum: int = MAX_REQUEST_BYTES) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > maximum:
        raise CustodyCommitError("Protocol bytes exceed their bound or are empty.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CustodyCommitError("Duplicate protocol field.")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=pairs)
        if not isinstance(value, dict) or canonical_protocol_bytes(value) != raw:
            raise CustodyCommitError("Noncanonical protocol bytes.")
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CustodyCommitError("Invalid protocol JSON.") from exc


def _fields(value: Mapping[str, object], expected: set[str]) -> None:
    if set(value) != expected:
        raise CustodyCommitError("Protocol fields do not match the exact schema.")


def validate_relative_path(value: str) -> str:
    """Accept one unambiguous ASCII relative path, including Windows rules."""
    _text(value, maximum=2048)
    if not value.isascii() or "\\" in value or ":" in value or value.startswith("/"):
        raise CustodyCommitError("Invalid relative path namespace.")
    reserved = {"con", "prn", "aux", "nul", "clock$", "conin$", "conout$",
                *(f"com{x}" for x in range(1, 10)), *(f"lpt{x}" for x in range(1, 10))}
    parts = value.split("/")
    if len(parts) > 16:
        raise CustodyCommitError("Relative path is too deep.")
    for part in parts:
        if (not part or part in {".", ".."} or len(part) > 255
                or part != part.strip() or part.endswith((".", " "))
                or part.split(".", 1)[0].casefold() in reserved
                or any(ord(c) < 32 or c in '<>"|?*' for c in part)):
            raise CustodyCommitError("Invalid relative path component.")
    return value


@dataclass(frozen=True)
class CustodyCommitIdentity:
    source_root_identity: str
    artifact_role: str
    scope: str
    logical_key: str

    def __post_init__(self):
        _hash(self.source_root_identity)
        if self.artifact_role not in _ROLES:
            raise CustodyCommitError("Unknown artifact role.")
        _text(self.scope, maximum=2048)
        _text(self.logical_key, maximum=1024)

    def digest(self) -> str:
        return sha256(canonical_protocol_bytes(asdict(self)))


@dataclass(frozen=True)
class CustodyCommitRequest:
    policy_sha256: str
    identity: CustodyCommitIdentity
    final_root: str
    final_relative_path: str
    content_sha256: str
    staging_sha256: str
    byte_length: int
    staging_name: str
    generation: str

    def __post_init__(self):
        _hash(self.policy_sha256)
        if type(self.identity) is not CustodyCommitIdentity or self.final_root not in _ROOTS:
            raise CustodyCommitError("Invalid identity or final root alias.")
        validate_relative_path(self.final_relative_path)
        _hash(self.content_sha256)
        if _hash(self.staging_sha256) != self.content_sha256:
            raise CustodyCommitError("Staging and content digests differ.")
        _integer(self.byte_length)
        if not isinstance(self.generation, str) or _GENERATION.fullmatch(self.generation) is None:
            raise CustodyCommitError("Invalid transport generation.")
        if self.staging_name != self.generation + ".stage":
            raise CustodyCommitError("Staging name does not bind its generation.")

    def to_bytes(self) -> bytes:
        raw = canonical_protocol_bytes({"version": PROTOCOL_VERSION, **asdict(self)})
        if len(raw) > MAX_REQUEST_BYTES:
            raise CustodyCommitError("Request exceeds its bound.")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes, *, max_bytes: int = MAX_REQUEST_BYTES):
        value = _decode(raw, maximum=min(max_bytes, MAX_REQUEST_BYTES))
        _fields(value, {"version", *cls.__dataclass_fields__})
        if value.pop("version") != PROTOCOL_VERSION:
            raise CustodyCommitError("Unknown commit protocol version.")
        identity = value.pop("identity")
        if not isinstance(identity, dict):
            raise CustodyCommitError("Invalid identity object.")
        _fields(identity, set(CustodyCommitIdentity.__dataclass_fields__))
        return cls(identity=CustodyCommitIdentity(**identity), **value)

    def commit_binding(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items()
                if key not in {"staging_name", "generation"}}

    def request_digest(self) -> str:
        return sha256(self.to_bytes())


@dataclass(frozen=True)
class CustodyObjectEvidence:
    raw: bytes
    file_identity: tuple[int, int, int]
    owner_sid: str
    descriptor_sha256: str


@dataclass(frozen=True)
class CustodyCommitReceipt:
    identity_sha256: str
    claim_sha256: str
    original_request_sha256: str
    policy_sha256: str
    commit_binding: Mapping[str, object]
    original_staging_identity: tuple[int, int, int]
    final_file_identity: tuple[int, int, int]
    final_owner_sid: str
    final_descriptor_sha256: str
    final_sha256: str
    receipt_identity: str

    def to_bytes(self) -> bytes:
        return canonical_protocol_bytes({"version": PROTOCOL_VERSION, **asdict(self)})

    @classmethod
    def from_bytes(cls, raw: bytes):
        value = _decode(raw)
        _fields(value, {"version", *cls.__dataclass_fields__})
        if value.pop("version") != PROTOCOL_VERSION:
            raise CustodyCommitIntegrityError("Unknown receipt version.")
        for key in ("identity_sha256", "claim_sha256", "original_request_sha256",
                    "policy_sha256", "final_descriptor_sha256", "final_sha256", "receipt_identity"):
            _hash(value[key])
        _text(value["final_owner_sid"])
        if not isinstance(value["commit_binding"], dict):
            raise CustodyCommitIntegrityError("Invalid receipt commit binding.")
        for key in ("original_staging_identity", "final_file_identity"):
            value[key] = _file_identity(value[key])
        receipt = cls(**value)
        core = {key: val for key, val in asdict(receipt).items() if key != "receipt_identity"}
        if sha256(canonical_protocol_bytes(core)) != receipt.receipt_identity:
            raise CustodyCommitIntegrityError("Receipt identity does not match its exact core.")
        return receipt


@dataclass(frozen=True)
class CustodyCommitResult:
    receipt: CustodyCommitReceipt
    created: bool
    recovered_receipt: bool


class CustodyCommitBackend(Protocol):
    policy_sha256: str
    source_root_identity: str
    max_artifact_bytes: int
    max_request_bytes: int

    def transaction(self) -> ContextManager[None]: ...
    def read_staged(self, name: str, *, maximum: int) -> CustodyObjectEvidence: ...
    def read_request(self, name: str, *, maximum: int) -> CustodyObjectEvidence: ...
    def read_trusted(self, namespace: str, relative: str, *, maximum: int) -> CustodyObjectEvidence | None: ...
    def create_trusted(self, namespace: str, relative: str, raw: bytes) -> tuple[bool, CustodyObjectEvidence]: ...
    def ensure_durable(self, namespace: str, relative: str, expected: CustodyObjectEvidence) -> None: ...
    def publish_completion(self, relative: str, raw: bytes) -> tuple[bool, CustodyObjectEvidence]: ...
    def close(self) -> None: ...


def _scientific_json(raw: bytes) -> Mapping[str, object]:
    try:
        return strict_json_loads(raw)
    except (ValueError, RecursionError) as exc:
        raise CustodyCommitError("Artifact is not exact canonical scientific JSON.") from exc


def _logical_record(value: Mapping[str, object]) -> str:
    record = value.get("record_id")
    if not isinstance(record, dict):
        raise CustodyCommitError("Artifact has no logical record identity.")
    return _text(record.get("recorder_id"))


def _session_key(value: Mapping[str, object], expected: str) -> str:
    session = value.get("session_id")
    if (not isinstance(session, dict)
            or "s-" + sha256(_text(session.get("recorder_id")).encode("utf-8")) != expected):
        raise CustodyCommitError("Artifact does not bind its logical session namespace.")
    return expected


def identity_for_artifact(*, source_root_identity: str, final_root: str,
                          relative_path: str, raw: bytes) -> CustodyCommitIdentity:
    """Derive mechanical identity without making a scientific admission decision.

    Conflict raw names are existing *evidence occurrence* keys, not accepted
    source identities; their separate role cannot reserve an accepted record.
    """
    _hash(source_root_identity)
    path = validate_relative_path(relative_path)
    if path != path.lower():
        raise CustodyCommitError("Artifact paths must have canonical lower-case spelling.")
    if not isinstance(raw, bytes) or len(raw) > MAX_ARTIFACT_BYTES:
        raise CustodyCommitError("Artifact exceeds its bounded byte contract.")
    parts = path.split("/")
    role = scope = key = None
    if final_root == "arrivals":
        match = _EVENT.fullmatch(parts[-1])
        if len(parts) != 2 or parts[0] != "ledger" or match is None:
            raise CustodyCommitError("Arrival destination is outside the ledger contract.")
        value = _scientific_json(raw)
        sequence = _integer(value.get("sequence"), minimum=1, maximum=10**20-1)
        if match[1] != f"{sequence:020d}" or match[2] != sha256(raw):
            raise CustodyCommitError("Arrival filename does not bind sequence and bytes.")
        role, scope, key = "ARRIVAL", "ledger", str(sequence)
    elif final_root == "cursors":
        match = _CURSOR.fullmatch(parts[-1])
        if len(parts) != 1 or match is None:
            raise CustodyCommitError("Cursor destination is outside its journal.")
        value = _scientific_json(raw)
        ordinal = _integer(value.get("publication_ordinal"), minimum=1, maximum=10**20-1)
        if match[1] != f"{ordinal:020d}" or match[2] != sha256(raw):
            raise CustodyCommitError("Cursor filename does not bind ordinal and bytes.")
        role, scope, key = "CURSOR", "reader-cursors", str(ordinal)
    elif final_root == "custody":
        if len(parts) == 2 and parts[0] == "quarantine-receipts":
            if re.fullmatch(r"[0-9a-f]{64}\.quarantine\.json", parts[1]) is None:
                raise CustodyCommitError("Invalid quarantine receipt name.")
            value = _scientific_json(raw)
            partial = value.get("partial_before")
            if not isinstance(partial, dict):
                raise CustodyCommitError("Missing quarantine occurrence.")
            key = _text(partial.get("partial_name"))
            if parts[1] != sha256(canonical_json_bytes(partial)) + ".quarantine.json":
                raise CustodyCommitError("Quarantine receipt key differs from its occurrence.")
            role, scope = "QUARANTINE_RECEIPT", "quarantine-receipts"
        else:
            if (len(parts) < 5 or parts[0] != "sessions"
                    or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", parts[1]) is None
                    or re.fullmatch(r"s-[0-9a-f]{64}", parts[2]) is None):
                raise CustodyCommitError("Invalid custody session namespace.")
            # The date/destination is separately bound by the immutable claim.
            # It must not allow another identity for the same logical session.
            scope = parts[2]
            section, name = parts[3], parts[-1]
            if section in {"payloads", "receipts"} and len(parts) == 6 and parts[4] in _CHANNELS:
                suffix = ".payload.json" if section == "payloads" else ".receipt.json"
                value = _scientific_json(raw)
                key = sha256(_logical_record(value).encode("utf-8"))
                if name != key + suffix or value.get("channel") != parts[4]:
                    raise CustodyCommitError("Record filename/channel differs from logical identity.")
                if section == "receipts" and value.get("record_key_sha256") != key:
                    raise CustodyCommitError("Scientific receipt key differs.")
                role = "PAYLOAD" if section == "payloads" else "SCIENTIFIC_RECEIPT"
                # Preserve the existing independent logical session domains.
                # A date/path alias within that session cannot mint a new key.
                if section == "payloads":
                    _session_key(value, parts[2])
            elif section in {"sources", "checkpoints"} and len(parts) == 7:
                _hash(parts[5])
                value = _scientific_json(raw)
                _session_key(value, parts[2])
                event_key = sha256(_text(value.get("source_event_id")).encode("utf-8"))
                stream = value.get("stream_id")
                if not isinstance(stream, str):
                    stream = value.get("source_stream_id")
                stream = _text(stream)
                source_kind = parts[4]
                if source_kind not in {"export", "outcome"}:
                    raise CustodyCommitError("Unknown source-kind namespace.")
                if sha256(canonical_json_bytes({"source_kind": source_kind, "stream_id": stream})) != parts[5]:
                    raise CustodyCommitError("Source stream namespace differs from logical identity.")
                scope += "/" + source_kind + "/" + parts[5]
                if section == "sources":
                    if name != event_key + ".source.json":
                        raise CustodyCommitError("Source event path differs.")
                    key, role = event_key, "SOURCE"
                else:
                    match = _CHECKPOINT.fullmatch(name)
                    sequence = _integer(value.get("source_sequence"), minimum=1, maximum=10**20-1)
                    if match is None or match[1] != f"{sequence:020d}" or match[2] != event_key:
                        raise CustodyCommitError("Checkpoint path differs from logical sequence.")
                    key, role = str(sequence), "CHECKPOINT"
            elif section == "manifests" and len(parts) == 5:
                if re.fullmatch(r"[0-9a-f]{64}\.final\.json", name):
                    value = _scientific_json(raw)
                    _session_key(value, parts[2])
                    role = key = "FINAL_MANIFEST"
                elif re.fullmatch(r"[0-9a-f]{64}\.sha256", name):
                    role = key = "FINAL_CHECKSUM"
                else:
                    raise CustodyCommitError("Unknown final manifest artifact.")
            elif section == "conflicts" and len(parts) == 5:
                match = re.fullmatch(r"([0-9a-f]{64})\.(conflicting\.raw|conflict\.json)", name)
                if match is None:
                    raise CustodyCommitError("Invalid conflict occurrence path.")
                key = match[1]
                role = "CONFLICT_RAW" if match[2] == "conflicting.raw" else "CONFLICT_RECEIPT"
                if role == "CONFLICT_RECEIPT":
                    value = _scientific_json(raw)
                    occurrence = {
                        "accepted_sha256": value.get("accepted_payload_sha256"),
                        "conflicting_sha256": value.get("conflicting_payload_sha256"),
                        "logical_record_id": value.get("logical_record_id"),
                        "reason_code": value.get("reason_code"),
                        "source_event_id": value.get("source_event_id"),
                        "stream_id": value.get("stream_id"),
                    }
                    if sha256(canonical_json_bytes(occurrence)) != key:
                        raise CustodyCommitError("Conflict occurrence key differs from receipt.")
            else:
                raise CustodyCommitError("Unsupported custody artifact role.")
    else:
        raise CustodyCommitError("Unknown final root alias.")
    return CustodyCommitIdentity(source_root_identity, role, scope, key)


def claim_path(identity_sha256: str) -> str:
    return f"{_hash(identity_sha256)[:2]}/{identity_sha256}.claim.json"


def receipt_path(identity_sha256: str) -> str:
    return f"{_hash(identity_sha256)[:2]}/{identity_sha256}.commit.json"


def completion_path(identity_sha256: str) -> str:
    return f"{_hash(identity_sha256)[:2]}/{identity_sha256}.complete.json"


def _evidence(value: CustodyObjectEvidence, *, maximum: int) -> CustodyObjectEvidence:
    if (not isinstance(value, CustodyObjectEvidence) or not isinstance(value.raw, bytes)
            or len(value.raw) > maximum):
        raise CustodyCommitIntegrityError("Backend returned invalid or oversized object evidence.")
    _file_identity(value.file_identity)
    _text(value.owner_sid)
    _hash(value.descriptor_sha256)
    return value


class ScienceCustodyFinalizer:
    def __init__(self, backend: CustodyCommitBackend, *, fault_hook: Callable[[str], None] | None = None,
                 trace_hook: Callable[[dict[str, object]], None] | None = None):
        _hash(backend.policy_sha256)
        _hash(backend.source_root_identity)
        _integer(backend.max_artifact_bytes, minimum=1)
        _integer(backend.max_request_bytes, minimum=1, maximum=MAX_REQUEST_BYTES)
        self.backend = backend
        self._fault_hook = fault_hook
        self._trace_hook = trace_hook

    def _trace(self, request, event, relative, *, evidence=None, created=None, error=None):
        if self._trace_hook is None:
            return
        self._trace_hook({
            "event": event, "identity_sha256": request.identity.digest(),
            "request_sha256": request.request_digest(), "generation": request.generation,
            "relative_path": relative,
            "result": "ERROR" if error is not None else (
                "BEGIN" if event.endswith("_begin") else "MISSING" if evidence is None else "PRESENT"),
            "file_identity": None if evidence is None else [str(part) for part in evidence.file_identity],
            "sha256": None if evidence is None else sha256(evidence.raw),
            "created": created, "error_class": None if error is None else type(error).__name__,
        })

    def _fault(self, phase):
        if self._fault_hook is not None:
            self._fault_hook(phase)

    def _validate_request(self, request):
        if type(request) is not CustodyCommitRequest:
            raise CustodyCommitError("Expected a strict commit request.")
        request = CustodyCommitRequest.from_bytes(request.to_bytes(), max_bytes=self.backend.max_request_bytes)
        if (request.policy_sha256 != self.backend.policy_sha256
                or request.identity.source_root_identity != self.backend.source_root_identity
                or request.byte_length > self.backend.max_artifact_bytes):
            raise CustodyCommitError("Request does not match the bound channel policy.")
        return request

    def _read(self, namespace, relative, maximum):
        result = self.backend.read_trusted(namespace, relative, maximum=maximum)
        return None if result is None else _evidence(result, maximum=maximum)

    def _claim(self, request):
        claim_info = self._claim_for_identity(request.identity)
        if claim_info is not None and claim_info[2].commit_binding() != request.commit_binding():
            raise CustodyCommitConflict("Logical commit identity already claims other bytes or destination.")
        return claim_info

    def _claim_for_identity(self, identity):
        evidence = self._read("claims", claim_path(identity.digest()), MAX_REQUEST_BYTES)
        if evidence is None:
            return None
        claim = _decode(evidence.raw)
        _fields(claim, {"version", "request", "request_sha256", "staging_file_identity",
                        "staging_owner_sid", "staging_descriptor_sha256"})
        if claim["version"] != PROTOCOL_VERSION or not isinstance(claim["request"], dict):
            raise CustodyCommitIntegrityError("Invalid durable claim version/request.")
        original = CustodyCommitRequest.from_bytes(canonical_protocol_bytes(claim["request"]))
        if original.request_digest() != claim["request_sha256"]:
            raise CustodyCommitIntegrityError("Durable claim request digest differs.")
        if original.identity != identity:
            raise CustodyCommitIntegrityError("Referenced artifact claim has another identity/root.")
        _file_identity(claim["staging_file_identity"])
        _text(claim["staging_owner_sid"])
        _hash(claim["staging_descriptor_sha256"])
        return evidence, claim, original

    def _verify_final(self, request, final, *, recover_dependencies=False):
        if len(final.raw) != request.byte_length or sha256(final.raw) != request.content_sha256:
            raise CustodyCommitIntegrityError("Final exact bytes differ from the durable binding.")
        actual = identity_for_artifact(source_root_identity=self.backend.source_root_identity,
                                      final_root=request.final_root,
                                      relative_path=request.final_relative_path, raw=final.raw)
        if actual != request.identity:
            raise CustodyCommitIntegrityError("Final logical identity differs from request.")
        if actual.artifact_role == "SCIENTIFIC_RECEIPT":
            self._verify_scientific_receipt(request, final.raw, recover=recover_dependencies)
        elif actual.artifact_role == "FINAL_CHECKSUM":
            self._verify_final_checksum(request, final.raw, recover=recover_dependencies)

    def _required_claim(self, identity):
        claim_info = self._claim_for_identity(identity)
        if claim_info is None:
            raise CustodyCommitIntegrityError("Referenced scientific artifact has no durable claim.")
        self._validate_request(claim_info[2])
        return claim_info

    def _confirmed_dependency(self, identity, expected_path, *, recover):
        claim_info = self._required_claim(identity)
        original = claim_info[2]
        if original.final_root != "custody" or original.final_relative_path != expected_path:
            raise CustodyCommitIntegrityError("Referenced artifact has another identity/root/path.")
        self._trace(original, "lookup_begin", completion_path(original.identity.digest()))
        verified = self._existing(original, claim_info)
        if verified is None:
            if not recover:
                raise CustodyCommitPending("Referenced artifact durability is unconfirmed.")
            self.finalize(original)
            verified = self._existing(original, self._claim(original))
            if verified is None:
                raise CustodyCommitPending("Referenced artifact durability is unconfirmed after recovery.")
        # Return the exact bytes bound by this fresh receipt/completion proof.
        return verified[1]

    def _verify_scientific_receipt(self, request, raw, *, recover=False):
        parts = request.final_relative_path.split("/")
        parts[3] = "payloads"
        parts[-1] = parts[-1].removesuffix(".receipt.json") + ".payload.json"
        payload_path = "/".join(parts)
        identity = CustodyCommitIdentity(self.backend.source_root_identity, "PAYLOAD",
                                         request.identity.scope, request.identity.logical_key)
        payload = self._confirmed_dependency(identity, payload_path, recover=recover)
        value, payload_value = _scientific_json(raw), _scientific_json(payload.raw)
        if (value.get("payload_sha256") != sha256(payload.raw)
                or value.get("record_id") != payload_value.get("record_id")):
            raise CustodyCommitIntegrityError("Scientific receipt does not bind its exact payload/record.")

    def _verify_final_checksum(self, request, raw, *, recover=False):
        identity = CustodyCommitIdentity(self.backend.source_root_identity, "FINAL_MANIFEST",
                                         request.identity.scope, "FINAL_MANIFEST")
        expected_manifest = request.final_relative_path.removesuffix(".sha256") + ".final.json"
        manifest = self._confirmed_dependency(identity, expected_manifest, recover=recover)
        value = _scientific_json(manifest.raw)
        inventory = value.get("artifact_inventory")
        if not isinstance(inventory, list):
            raise CustodyCommitIntegrityError("Manifest inventory is unavailable for checksum binding.")
        prefix = "/".join(expected_manifest.split("/")[:3]) + "/"
        entries = {}
        for entry in inventory:
            if not isinstance(entry, dict):
                raise CustodyCommitIntegrityError("Manifest inventory item is invalid.")
            relative = validate_relative_path(entry.get("relative_path"))
            if not relative.startswith(prefix) or relative in entries or relative == expected_manifest:
                raise CustodyCommitIntegrityError("Manifest inventory is outside its exact partition or duplicated.")
            entries[relative] = _hash(entry.get("sha256"))
        entries[expected_manifest] = sha256(manifest.raw)
        expected = "".join(f"{digest}  {relative}\n" for relative, digest in sorted(entries.items())).encode("ascii")
        if raw != expected:
            raise CustodyCommitIntegrityError("Checksum bytes do not bind the original manifest inventory.")

    def _receipt_for(self, request, claim_info, final):
        evidence, claim, original = claim_info
        core = {
            "identity_sha256": request.identity.digest(), "claim_sha256": sha256(evidence.raw),
            "original_request_sha256": original.request_digest(), "policy_sha256": request.policy_sha256,
            "commit_binding": request.commit_binding(),
            "original_staging_identity": _file_identity(claim["staging_file_identity"]),
            "final_file_identity": _file_identity(final.file_identity), "final_owner_sid": final.owner_sid,
            "final_descriptor_sha256": final.descriptor_sha256, "final_sha256": sha256(final.raw),
        }
        return CustodyCommitReceipt(**core, receipt_identity=sha256(canonical_protocol_bytes(core)))

    def _completion_bytes(self, request, claim_info, final, receipt):
        def binding(value):
            return {"file_identity": value.file_identity, "sha256": sha256(value.raw),
                    "owner_sid": value.owner_sid, "descriptor_sha256": value.descriptor_sha256}
        return canonical_protocol_bytes({
            "version": COMPLETION_VERSION, "policy_sha256": self.backend.policy_sha256,
            "identity_sha256": request.identity.digest(), "claim": binding(claim_info[0]),
            "final": binding(final), "receipt": binding(receipt),
        })

    def _existing(self, request, claim_info, *, recover_dependencies=False):
        receipt_relative = receipt_path(request.identity.digest())
        completion_relative = completion_path(request.identity.digest())
        try:
            completion = self._read("receipts", completion_relative, MAX_REQUEST_BYTES)
        except Exception as exc:
            self._trace(request, "completion_read", completion_relative, error=exc)
            raise
        self._trace(request, "completion_read", completion_relative, evidence=completion)
        try:
            evidence = self._read("receipts", receipt_relative, MAX_REQUEST_BYTES)
        except Exception as exc:
            self._trace(request, "receipt_read", receipt_relative, error=exc)
            raise
        self._trace(request, "receipt_read", receipt_relative, evidence=evidence)
        if evidence is None:
            if completion is not None:
                def state(namespace, relative):
                    try:
                        current = self._read(namespace, relative, MAX_REQUEST_BYTES)
                    except Exception as exc:
                        return {"state": "READ_ERROR", "error_class": type(exc).__name__}
                    if current is None:
                        return {"state": "MISSING", "file_identity": None, "sha256": None}
                    return {"state": "PRESENT", "file_identity": list(current.file_identity),
                            "sha256": sha256(current.raw)}

                failure = CustodyCommitIntegrityError("Completion exists without its exact receipt.")
                failure.receipt_diagnostic = {
                    "request_id": request.identity.digest(), "request_digest": request.request_digest(),
                    "generation": request.generation,
                    "claim_path": claim_path(request.identity.digest()),
                    "claim_at_failure": state("claims", claim_path(request.identity.digest())),
                    "receipt_path": receipt_relative,
                    "receipt_first_read": {"state": "MISSING", "file_identity": None, "sha256": None},
                    "receipt_at_failure": state("receipts", receipt_relative),
                    "completion_path": completion_relative,
                    "completion_read": {"state": "PRESENT", "file_identity": list(completion.file_identity),
                                        "sha256": sha256(completion.raw)},
                }
                raise failure
            return None
        if claim_info is None:
            # Writer may publish the claim and receipt after our first claim read.
            claim_info = self._claim(request)
            if claim_info is None:
                raise CustodyCommitIntegrityError("Receipt exists without its immutable claim.")
        receipt = CustodyCommitReceipt.from_bytes(evidence.raw)
        final = self._read(request.final_root, request.final_relative_path, self.backend.max_artifact_bytes)
        if final is None:
            raise CustodyCommitIntegrityError("Receipted final is missing; recreation is prohibited.")
        self._verify_final(request, final, recover_dependencies=recover_dependencies)
        if receipt.to_bytes() != self._receipt_for(request, claim_info, final).to_bytes():
            raise CustodyCommitIntegrityError("Receipt no longer binds the exact claim/final object.")
        if completion is None:
            return None
        if completion.raw != self._completion_bytes(request, claim_info, final, evidence):
            raise CustodyCommitIntegrityError("Completion no longer binds its exact durable objects.")
        return CustodyCommitResult(receipt, False, False), final

    def lookup(self, request: CustodyCommitRequest) -> CustodyCommitResult | None:
        request = self._validate_request(request)
        self._trace(request, "lookup_begin", completion_path(request.identity.digest()))
        with self.backend.transaction():
            verified = self._existing(request, self._claim(request))
            return None if verified is None else verified[0]

    def _inspect_existing(self, root: str, relative: str):
        if root not in _ROOTS:
            raise CustodyCommitError("Unknown final root alias.")
        relative = validate_relative_path(relative)
        with self.backend.transaction():
            final = self._read(root, relative, self.backend.max_artifact_bytes)
            if final is None:
                return None
            identity = identity_for_artifact(source_root_identity=self.backend.source_root_identity,
                final_root=root, relative_path=relative, raw=final.raw)
            claim_info = self._required_claim(identity)
            original = claim_info[2]
            if original.final_root != root or original.final_relative_path != relative:
                raise CustodyCommitIntegrityError("Visible artifact differs from its claimed destination.")
            if len(final.raw) != original.byte_length or sha256(final.raw) != original.content_sha256:
                raise CustodyCommitIntegrityError("Visible artifact differs from its claimed exact bytes.")
            return original, final, claim_info

    def inspect_existing(self, root: str, relative: str):
        """Validate visible raw/claim for bounded reconfirmation, NOT success."""
        inspected = self._inspect_existing(root, relative)
        return None if inspected is None else inspected[:2]

    def read_confirmed(self, root: str, relative: str) -> CustodyObjectEvidence | None:
        with self.backend.transaction():
            inspected = self._inspect_existing(root, relative)
            if inspected is None:
                return None
            original, final, claim_info = inspected
            self._trace(original, "lookup_begin", completion_path(original.identity.digest()))
            verified = self._existing(original, claim_info)
            if verified is None:
                raise CustodyCommitPending("Visible artifact durability is unconfirmed.")
            result, _ = verified
            if (result.receipt.final_file_identity != final.file_identity
                    or result.receipt.final_descriptor_sha256 != final.descriptor_sha256
                    or result.receipt.final_owner_sid != final.owner_sid
                    or result.receipt.final_sha256 != sha256(final.raw)):
                raise CustodyCommitIntegrityError("Confirmed read object changed during verification.")
            return final

    def finalize(self, request: CustodyCommitRequest) -> CustodyCommitResult:
        request = self._validate_request(request)
        with self.backend.transaction():
            claim_info = self._claim(request)
            existing = self._existing(request, claim_info, recover_dependencies=True)
            if existing is not None:
                return existing[0]
            final = self._read(request.final_root, request.final_relative_path, self.backend.max_artifact_bytes)
            if final is not None and claim_info is None:
                raise CustodyCommitIntegrityError("Unclaimed final cannot be adopted.")
            recovered = final is not None
            created = False
            if claim_info is not None:
                self.backend.ensure_durable("claims", claim_path(request.identity.digest()), claim_info[0])
            if final is not None:
                self.backend.ensure_durable(request.final_root, request.final_relative_path, final)
            if final is None:
                try:
                    staged = _evidence(self.backend.read_staged(request.staging_name,
                                       maximum=self.backend.max_artifact_bytes),
                                       maximum=self.backend.max_artifact_bytes)
                except FileNotFoundError as exc:
                    raise CustodyCommitPending("Staging is absent; no committed outcome can be inferred.") from exc
                if len(staged.raw) != request.byte_length or sha256(staged.raw) != request.staging_sha256:
                    raise CustodyCommitConflict("Pinned staging bytes differ from the request.")
                self._verify_final(request, staged, recover_dependencies=True)
                self._fault("after_staging_read")
                if claim_info is None:
                    claim = {"version": PROTOCOL_VERSION, "request": _decode(request.to_bytes()),
                             "request_sha256": request.request_digest(),
                             "staging_file_identity": staged.file_identity,
                             "staging_owner_sid": staged.owner_sid,
                             "staging_descriptor_sha256": staged.descriptor_sha256}
                    claim_raw = canonical_protocol_bytes(claim)
                    _, persisted = self.backend.create_trusted("claims", claim_path(request.identity.digest()), claim_raw)
                    if _evidence(persisted, maximum=MAX_REQUEST_BYTES).raw != claim_raw:
                        raise CustodyCommitConflict("Concurrent durable claim differs.")
                    claim_info = self._claim(request)
                    if claim_info is None:
                        raise CustodyCommitIntegrityError("New durable claim cannot be read back.")
                self._fault("after_claim")
                self._fault("before_final")
                created, final = self.backend.create_trusted(request.final_root, request.final_relative_path, staged.raw)
                final = _evidence(final, maximum=self.backend.max_artifact_bytes)
                self._fault("after_final")
            self._verify_final(request, final, recover_dependencies=True)
            receipt = self._receipt_for(request, claim_info, final)
            self._fault("before_receipt")
            receipt_relative = receipt_path(request.identity.digest())
            self._trace(request, "receipt_create_begin", receipt_relative)
            receipt_created, persisted = self.backend.create_trusted("receipts", receipt_relative, receipt.to_bytes())
            persisted = _evidence(persisted, maximum=MAX_REQUEST_BYTES)
            self._trace(request, "receipt_create_result", receipt_relative,
                        evidence=persisted, created=receipt_created)
            if persisted.raw != receipt.to_bytes():
                raise CustodyCommitIntegrityError("Concurrent durable receipt differs.")
            self._fault("before_completion")
            # This announces three already-completed barriers. Its own loss
            # means Pending/reconfirmation, never premature cleanup authority.
            completion = self._completion_bytes(request, claim_info, final, persisted)
            completion_relative = completion_path(request.identity.digest())
            self._trace(request, "completion_create_begin", completion_relative)
            completion_created, announced = self.backend.publish_completion(completion_relative, completion)
            announced = _evidence(announced, maximum=MAX_REQUEST_BYTES)
            self._trace(request, "completion_create_result", completion_relative,
                        evidence=announced, created=completion_created)
            if announced.raw != completion:
                raise CustodyCommitIntegrityError("Concurrent completion differs.")
            self._fault("after_receipt")
            verified = self._existing(request, claim_info)
            if verified is None:
                raise CustodyCommitIntegrityError("Durable receipt is not readable.")
            return CustodyCommitResult(verified[0].receipt, bool(created), recovered)
