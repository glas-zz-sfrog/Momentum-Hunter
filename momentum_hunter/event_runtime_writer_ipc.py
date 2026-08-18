"""Offline inherited-capability IPC proof for a future evidence writer.

This module is dormant. It has no provider, broker, scheduler, service-control,
or production-root integration. The subprocess harness is invoked explicitly by
tests or an operator-supplied offline proof command.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
PROTOCOL = "inherited-capability-writer-ipc-v1"
AUTHORITY = "OFFLINE_PROTOTYPE_ONLY"
STATUS_PROVEN_BLOCKED = "PROTOCOL_PROVEN_ACTIVATION_BLOCKED"
MAX_FRAME_BYTES = 1_048_576
MAX_PAYLOAD_BYTES = 524_288
GENESIS_FINGERPRINT = "0" * 64
CAPABILITY_BYTES = 32
BOUNDARY_KIND = "DEDICATED_EVIDENCE_WRITER"
CHANNEL_KIND = "INHERITED_HANDLE"
CHANNEL_AUTHENTICATION = "INHERITED_UNFORGEABLE_CAPABILITY"

ALLOWED_ARTIFACTS = frozenset(
    {
        "candidate-lifecycle-ledger",
        "continuous-plan-ledger",
        "runtime-source-admission-ledger",
        "event-decision-cycle-ledger",
    }
)
ACTIVATION_BLOCKERS = (
    "SAME_SID_PROCESS_HANDLE_ISOLATION_UNPROVEN",
    "INSTALLED_RUNTIME_ROOT_ACL_UNPROVEN",
    "WPF_HANDLE_ISOLATION_UNPROVEN",
    "RESTART_AND_CRASH_RECOVERY_UNPROVEN",
)
FORBIDDEN_PAYLOAD_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "refresh_token",
    "access_token",
)
FORBIDDEN_PAYLOAD_VALUE_PREFIXES = ("sk-", "AKIA")


class WriterIpcError(ValueError):
    """Raised when an offline writer frame is malformed or unauthenticated."""


@dataclass(frozen=True)
class WriterEnvelope:
    session_id: str
    sequence: int
    prior_envelope_fingerprint: str
    configuration_fingerprint: str
    source_identity: str
    artifact_name: str
    payload_json: str
    payload_sha256: str
    authentication_tag: str
    fingerprint: str
    schema_version: int = SCHEMA_VERSION
    protocol: str = PROTOCOL


@dataclass(frozen=True)
class WriterReceipt:
    session_id: str
    sequence: int
    envelope_fingerprint: str
    prior_receipt_fingerprint: str
    artifact_name: str
    record_sha256: str
    accepted: bool
    authority: str = AUTHORITY
    fingerprint: str = ""
    schema_version: int = SCHEMA_VERSION
    protocol: str = PROTOCOL


@dataclass(frozen=True)
class OfflineWriterProofResult:
    status: str
    session_id: str
    source_identity: str
    configuration_fingerprint: str
    records_accepted: int
    child_exit_code: int
    session_receipt_sha256: str
    boundary_kind: str
    channel_kind: str
    channel_authentication: str
    same_principal_prototype: bool
    capability_persisted: bool
    capability_in_arguments: bool
    capability_in_environment: bool
    parent_pid_bound: bool
    activation_authorized: bool
    activation_blockers: tuple[str, ...]
    authority: str = AUTHORITY
    schema_version: int = SCHEMA_VERSION
    protocol: str = PROTOCOL


class EphemeralWriterCapability:
    """One-process-lifetime capability whose key is never serialized by APIs."""

    def __init__(self, *, session_id: str, key_material: bytes) -> None:
        _session_id(session_id)
        if not isinstance(key_material, bytes) or len(key_material) != CAPABILITY_BYTES:
            raise WriterIpcError("Writer capability must contain exactly 32 bytes.")
        self.session_id = session_id
        self._key = bytearray(key_material)
        self._closed = False

    @classmethod
    def create(cls) -> EphemeralWriterCapability:
        return cls(
            session_id=secrets.token_hex(16),
            key_material=secrets.token_bytes(CAPABILITY_BYTES),
        )

    def key_bytes(self) -> bytes:
        if self._closed:
            raise WriterIpcError("Writer capability is closed.")
        return bytes(self._key)

    def close(self) -> None:
        for index in range(len(self._key)):
            self._key[index] = 0
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def __repr__(self) -> str:
        return (
            "EphemeralWriterCapability("
            f"session_id={self.session_id!r}, key_material=<REDACTED>, "
            f"closed={self._closed})"
        )


class WriterEnvelopeSender:
    def __init__(
        self,
        *,
        capability: EphemeralWriterCapability,
        configuration_fingerprint: str,
        source_identity: str,
        starting_sequence: int = 1,
        prior_envelope_fingerprint: str = GENESIS_FINGERPRINT,
    ) -> None:
        self.capability = capability
        self.configuration_fingerprint = _sha256(
            configuration_fingerprint,
            "Configuration fingerprint",
        )
        self.source_identity = _required_text(source_identity, "Source identity")
        if starting_sequence <= 0:
            raise WriterIpcError("Starting envelope sequence must be positive.")
        _sha256(prior_envelope_fingerprint, "Prior envelope fingerprint")
        self._next_sequence = starting_sequence
        self._prior_envelope_fingerprint = prior_envelope_fingerprint

    def build(
        self,
        *,
        artifact_name: str,
        payload: Mapping[str, Any],
    ) -> WriterEnvelope:
        if artifact_name not in ALLOWED_ARTIFACTS:
            raise WriterIpcError("Artifact is outside the writer IPC allowlist.")
        payload_json = _canonical_json(_json_object(payload))
        if len(payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise WriterIpcError("Writer IPC payload exceeds the bounded frame size.")
        provisional = WriterEnvelope(
            session_id=self.capability.session_id,
            sequence=self._next_sequence,
            prior_envelope_fingerprint=self._prior_envelope_fingerprint,
            configuration_fingerprint=self.configuration_fingerprint,
            source_identity=self.source_identity,
            artifact_name=artifact_name,
            payload_json=payload_json,
            payload_sha256=_bytes_sha256(payload_json.encode("utf-8")),
            authentication_tag="",
            fingerprint="",
        )
        tag = _authentication_tag(self.capability.key_bytes(), provisional)
        authenticated = replace(provisional, authentication_tag=tag)
        envelope = replace(
            authenticated,
            fingerprint=_fingerprint(asdict(authenticated)),
        )
        validate_envelope_shape(envelope)
        self._next_sequence += 1
        self._prior_envelope_fingerprint = envelope.fingerprint
        return envelope


class WriterEnvelopeVerifier:
    def __init__(
        self,
        *,
        session_id: str,
        key_material: bytes,
        configuration_fingerprint: str,
        source_identity: str,
    ) -> None:
        self.session_id = _session_id(session_id)
        if not isinstance(key_material, bytes) or len(key_material) != CAPABILITY_BYTES:
            raise WriterIpcError("Verifier capability must contain exactly 32 bytes.")
        self._key = bytearray(key_material)
        self.configuration_fingerprint = _sha256(
            configuration_fingerprint,
            "Configuration fingerprint",
        )
        self.source_identity = _required_text(source_identity, "Source identity")
        self._expected_sequence = 1
        self._prior_envelope_fingerprint = GENESIS_FINGERPRINT
        self._closed = False

    def verify(self, envelope: WriterEnvelope) -> None:
        if self._closed:
            raise WriterIpcError("Writer verifier is closed.")
        verify_envelope_authentication(
            envelope,
            session_id=self.session_id,
            key_material=bytes(self._key),
            configuration_fingerprint=self.configuration_fingerprint,
            source_identity=self.source_identity,
        )
        if envelope.sequence != self._expected_sequence:
            raise WriterIpcError("Envelope sequence is replayed or out of order.")
        if envelope.prior_envelope_fingerprint != self._prior_envelope_fingerprint:
            raise WriterIpcError("Envelope chain predecessor is invalid.")
        self._expected_sequence += 1
        self._prior_envelope_fingerprint = envelope.fingerprint

    def close(self) -> None:
        for index in range(len(self._key)):
            self._key[index] = 0
        self._closed = True


class OfflineWriterSink:
    """Write-once synthetic sink; production paths are never inferred."""

    def __init__(self, output_root: Path, *, session_id: str) -> None:
        self.output_root = _temporary_output_root(output_root)
        self.session_id = _session_id(session_id)
        self.output_root.mkdir(parents=True, exist_ok=True)
        if any(self.output_root.iterdir()):
            raise WriterIpcError("Offline writer sink must start empty.")
        self._prior_receipt_fingerprint = GENESIS_FINGERPRINT
        self._receipts: list[WriterReceipt] = []

    def persist(self, envelope: WriterEnvelope) -> WriterReceipt:
        record = {
            "authority": AUTHORITY,
            "envelope": asdict(envelope),
        }
        record_bytes = (_canonical_json(record) + "\n").encode("utf-8")
        record_name = f"frame-{envelope.sequence:08d}-{envelope.fingerprint}.json"
        record_path = self.output_root / record_name
        _write_once(record_path, record_bytes)
        provisional = WriterReceipt(
            session_id=self.session_id,
            sequence=envelope.sequence,
            envelope_fingerprint=envelope.fingerprint,
            prior_receipt_fingerprint=self._prior_receipt_fingerprint,
            artifact_name=envelope.artifact_name,
            record_sha256=_bytes_sha256(record_bytes),
            accepted=True,
        )
        receipt = replace(provisional, fingerprint=_fingerprint(asdict(provisional)))
        self._receipts.append(receipt)
        self._prior_receipt_fingerprint = receipt.fingerprint
        return receipt

    def finalize(self) -> tuple[Path, str]:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "protocol": PROTOCOL,
            "authority": AUTHORITY,
            "sessionId": self.session_id,
            "recordsAccepted": len(self._receipts),
            "receipts": [asdict(receipt) for receipt in self._receipts],
            "activationAuthorized": False,
            "activationBlockers": list(ACTIVATION_BLOCKERS),
        }
        payload["fingerprint"] = _fingerprint(payload)
        data = (_canonical_json(payload) + "\n").encode("utf-8")
        path = self.output_root / "session-receipt.json"
        _write_once(path, data)
        return path, _bytes_sha256(data)


def run_offline_writer_proof(
    *,
    output_root: Path,
    configuration_fingerprint: str,
    source_identity: str,
    records: Sequence[tuple[str, Mapping[str, Any]]],
    python_executable: str | None = None,
    timeout_seconds: float = 30.0,
) -> OfflineWriterProofResult:
    """Run one explicit child proof with no installed-runtime authority."""

    output_root = _temporary_output_root(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise WriterIpcError("Offline proof output must be an empty directory.")
    capability = EphemeralWriterCapability.create()
    try:
        sender = WriterEnvelopeSender(
            capability=capability,
            configuration_fingerprint=configuration_fingerprint,
            source_identity=source_identity,
        )
        envelopes = [
            sender.build(artifact_name=artifact_name, payload=payload)
            for artifact_name, payload in records
        ]
        parent_pid = os.getpid()
        base_executable = Path(
            getattr(sys, "_base_executable", sys.executable)
        ).resolve()
        selected_executable = (
            Path(python_executable).resolve()
            if python_executable
            else base_executable
        )
        if selected_executable != base_executable:
            raise WriterIpcError(
                "Offline writer proof requires the base Python executable so direct "
                "parent identity is not obscured by a launcher."
            )
        command = [
            str(selected_executable),
            "-B",
            "-m",
            "momentum_hunter.event_runtime_writer_ipc",
            "child",
            "--output-root",
            str(output_root),
            "--expected-parent-pid",
            str(parent_pid),
        ]
        environment = os.environ.copy()
        for name in tuple(environment):
            if name.upper() in {"OPENAI_API_KEY", "CODEX_API_KEY"}:
                environment.pop(name, None)
        bootstrap = {
            "frameType": "BOOTSTRAP",
            "schemaVersion": SCHEMA_VERSION,
            "protocol": PROTOCOL,
            "sessionId": capability.session_id,
            "configurationFingerprint": sender.configuration_fingerprint,
            "sourceIdentity": sender.source_identity,
            "parentPid": parent_pid,
            "capability": base64.b64encode(capability.key_bytes()).decode("ascii"),
        }
        stdin_text = "\n".join(
            [
                _canonical_json(bootstrap),
                *(
                    _canonical_json(
                        {"frameType": "ENVELOPE", "envelope": asdict(item)}
                    )
                    for item in envelopes
                ),
                "",
            ]
        )
        completed = subprocess.run(
            command,
            input=stdin_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env=environment,
        )
    finally:
        capability.close()
    if completed.returncode != 0:
        raise WriterIpcError(
            f"Offline writer child failed with exit code {completed.returncode}."
        )
    try:
        child_result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WriterIpcError("Offline writer child returned malformed status.") from exc
    if not isinstance(child_result, dict):
        raise WriterIpcError("Offline writer child returned malformed status.")
    if (
        child_result.get("status") != "COMPLETED"
        or child_result.get("recordsAccepted") != len(envelopes)
        or child_result.get("sessionReceipt") != "session-receipt.json"
        or child_result.get("activationAuthorized") is not False
    ):
        raise WriterIpcError("Offline writer child returned contradictory status.")
    receipt_sha = _validate_offline_output(
        output_root=output_root,
        expected_session_id=sender.capability.session_id,
        expected_envelopes=envelopes,
    )
    if child_result.get("sessionReceiptSha256") != receipt_sha:
        raise WriterIpcError("Offline writer child receipt hash is contradictory.")
    return OfflineWriterProofResult(
        status=STATUS_PROVEN_BLOCKED,
        session_id=sender.capability.session_id,
        source_identity=sender.source_identity,
        configuration_fingerprint=sender.configuration_fingerprint,
        records_accepted=int(child_result["recordsAccepted"]),
        child_exit_code=completed.returncode,
        session_receipt_sha256=receipt_sha,
        boundary_kind=BOUNDARY_KIND,
        channel_kind=CHANNEL_KIND,
        channel_authentication=CHANNEL_AUTHENTICATION,
        same_principal_prototype=True,
        capability_persisted=False,
        capability_in_arguments=False,
        capability_in_environment=False,
        parent_pid_bound=True,
        activation_authorized=False,
        activation_blockers=ACTIVATION_BLOCKERS,
    )


def _validate_offline_output(
    *,
    output_root: Path,
    expected_session_id: str,
    expected_envelopes: Sequence[WriterEnvelope],
) -> str:
    receipt_path = output_root / "session-receipt.json"
    try:
        receipt_bytes = receipt_path.read_bytes()
        document = json.loads(receipt_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise WriterIpcError("Offline writer session receipt is unreadable.") from exc
    if not isinstance(document, dict):
        raise WriterIpcError("Offline writer session receipt is malformed.")
    if receipt_bytes != (_canonical_json(document) + "\n").encode("utf-8"):
        raise WriterIpcError("Offline writer session receipt is not canonical JSON.")
    if (
        document.get("schemaVersion") != SCHEMA_VERSION
        or document.get("protocol") != PROTOCOL
        or document.get("authority") != AUTHORITY
        or document.get("sessionId") != expected_session_id
        or document.get("recordsAccepted") != len(expected_envelopes)
        or document.get("activationAuthorized") is not False
        or document.get("activationBlockers") != list(ACTIVATION_BLOCKERS)
        or document.get("fingerprint") != _fingerprint(document)
    ):
        raise WriterIpcError("Offline writer session receipt identity is invalid.")
    raw_receipts = document.get("receipts")
    if not isinstance(raw_receipts, list) or len(raw_receipts) != len(
        expected_envelopes
    ):
        raise WriterIpcError("Offline writer session receipt count is invalid.")

    expected_names = {"session-receipt.json"}
    prior_receipt_fingerprint = GENESIS_FINGERPRINT
    for envelope, raw_receipt in zip(expected_envelopes, raw_receipts, strict=True):
        if not isinstance(raw_receipt, dict):
            raise WriterIpcError("Offline writer record receipt is malformed.")
        try:
            receipt = WriterReceipt(**raw_receipt)
        except TypeError as exc:
            raise WriterIpcError("Offline writer record receipt is malformed.") from exc
        record_name = f"frame-{envelope.sequence:08d}-{envelope.fingerprint}.json"
        expected_names.add(record_name)
        try:
            record_bytes = (output_root / record_name).read_bytes()
            record = json.loads(record_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise WriterIpcError("Offline writer record is unreadable.") from exc
        if (
            not isinstance(record, dict)
            or record_bytes != (_canonical_json(record) + "\n").encode("utf-8")
            or record.get("authority") != AUTHORITY
            or record.get("envelope") != asdict(envelope)
        ):
            raise WriterIpcError("Offline writer record identity is invalid.")
        if (
            receipt.session_id != expected_session_id
            or receipt.sequence != envelope.sequence
            or receipt.envelope_fingerprint != envelope.fingerprint
            or receipt.prior_receipt_fingerprint != prior_receipt_fingerprint
            or receipt.artifact_name != envelope.artifact_name
            or receipt.record_sha256 != _bytes_sha256(record_bytes)
            or receipt.accepted is not True
            or receipt.authority != AUTHORITY
            or receipt.schema_version != SCHEMA_VERSION
            or receipt.protocol != PROTOCOL
            or receipt.fingerprint != _fingerprint(asdict(receipt))
        ):
            raise WriterIpcError("Offline writer record receipt identity is invalid.")
        prior_receipt_fingerprint = receipt.fingerprint

    try:
        actual_names = {path.name for path in output_root.iterdir()}
    except OSError as exc:
        raise WriterIpcError("Offline writer output cannot be enumerated.") from exc
    if actual_names != expected_names:
        raise WriterIpcError("Offline writer output contains unexpected artifacts.")
    return _bytes_sha256(receipt_bytes)


def validate_envelope_shape(envelope: WriterEnvelope) -> None:
    if envelope.schema_version != SCHEMA_VERSION or envelope.protocol != PROTOCOL:
        raise WriterIpcError("Envelope protocol identity is invalid.")
    _session_id(envelope.session_id)
    if not isinstance(envelope.sequence, int) or envelope.sequence < 1:
        raise WriterIpcError("Envelope sequence is invalid.")
    _sha256(envelope.prior_envelope_fingerprint, "Prior envelope fingerprint")
    _sha256(envelope.configuration_fingerprint, "Configuration fingerprint")
    _required_text(envelope.source_identity, "Source identity")
    if envelope.artifact_name not in ALLOWED_ARTIFACTS:
        raise WriterIpcError("Envelope artifact is outside the allowlist.")
    if len(envelope.payload_json.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise WriterIpcError("Envelope payload exceeds the bounded frame size.")
    try:
        parsed = json.loads(envelope.payload_json)
    except json.JSONDecodeError as exc:
        raise WriterIpcError("Envelope payload is not valid JSON.") from exc
    if not isinstance(parsed, dict) or _canonical_json(parsed) != envelope.payload_json:
        raise WriterIpcError("Envelope payload is not canonical JSON.")
    if envelope.payload_sha256 != _bytes_sha256(envelope.payload_json.encode("utf-8")):
        raise WriterIpcError("Envelope payload hash is invalid.")
    _sha256(envelope.authentication_tag, "Authentication tag")
    expected_fingerprint = _fingerprint(
        {key: value for key, value in asdict(envelope).items() if key != "fingerprint"}
    )
    if envelope.fingerprint != expected_fingerprint:
        raise WriterIpcError("Envelope fingerprint is invalid.")


def verify_envelope_authentication(
    envelope: WriterEnvelope,
    *,
    session_id: str,
    key_material: bytes,
    configuration_fingerprint: str,
    source_identity: str,
) -> None:
    """Authenticate one envelope without asserting its position in a stream."""

    validate_envelope_shape(envelope)
    expected_session = _session_id(session_id)
    if not isinstance(key_material, bytes) or len(key_material) != CAPABILITY_BYTES:
        raise WriterIpcError("Verifier capability must contain exactly 32 bytes.")
    expected_configuration = _sha256(
        configuration_fingerprint,
        "Configuration fingerprint",
    )
    expected_source = _required_text(source_identity, "Source identity")
    if envelope.session_id != expected_session:
        raise WriterIpcError("Envelope belongs to a different writer session.")
    if envelope.configuration_fingerprint != expected_configuration:
        raise WriterIpcError("Envelope configuration identity is invalid.")
    if envelope.source_identity != expected_source:
        raise WriterIpcError("Envelope source identity is invalid.")
    expected_tag = _authentication_tag(key_material, envelope)
    if not hmac.compare_digest(expected_tag, envelope.authentication_tag):
        raise WriterIpcError("Envelope authentication failed.")


def _run_child(*, output_root: Path, expected_parent_pid: int) -> int:
    if os.getppid() != expected_parent_pid:
        raise WriterIpcError("Writer child parent identity is invalid.")
    bootstrap_line = sys.stdin.readline(MAX_FRAME_BYTES + 1)
    if not bootstrap_line or len(bootstrap_line.encode("utf-8")) > MAX_FRAME_BYTES:
        raise WriterIpcError("Writer bootstrap frame is missing or oversized.")
    bootstrap = json.loads(bootstrap_line)
    if not isinstance(bootstrap, dict):
        raise WriterIpcError("Writer bootstrap frame must be a JSON object.")
    if (
        bootstrap.get("frameType") != "BOOTSTRAP"
        or bootstrap.get("schemaVersion") != SCHEMA_VERSION
        or bootstrap.get("protocol") != PROTOCOL
        or bootstrap.get("parentPid") != expected_parent_pid
    ):
        raise WriterIpcError("Writer bootstrap identity is invalid.")
    try:
        key = base64.b64decode(bootstrap["capability"], validate=True)
    except (KeyError, ValueError) as exc:
        raise WriterIpcError("Writer bootstrap capability is invalid.") from exc
    verifier = WriterEnvelopeVerifier(
        session_id=str(bootstrap.get("sessionId", "")),
        key_material=key,
        configuration_fingerprint=str(bootstrap.get("configurationFingerprint", "")),
        source_identity=str(bootstrap.get("sourceIdentity", "")),
    )
    sink = OfflineWriterSink(output_root, session_id=verifier.session_id)
    try:
        for line in sys.stdin:
            if len(line.encode("utf-8")) > MAX_FRAME_BYTES:
                raise WriterIpcError("Writer envelope frame is oversized.")
            if not line.strip():
                continue
            frame = json.loads(line)
            if not isinstance(frame, dict):
                raise WriterIpcError("Writer envelope frame must be a JSON object.")
            if frame.get("frameType") != "ENVELOPE":
                raise WriterIpcError("Writer received an unexpected frame type.")
            envelope = WriterEnvelope(**frame["envelope"])
            verifier.verify(envelope)
            sink.persist(envelope)
        receipt_path, receipt_sha = sink.finalize()
    finally:
        verifier.close()
    print(
        _canonical_json(
            {
                "status": "COMPLETED",
                "recordsAccepted": len(list(output_root.glob("frame-*.json"))),
                "sessionReceipt": receipt_path.name,
                "sessionReceiptSha256": receipt_sha,
                "activationAuthorized": False,
            }
        )
    )
    return 0


def _authentication_tag(key: bytes, envelope: WriterEnvelope) -> str:
    fields = asdict(envelope)
    fields.pop("authentication_tag", None)
    fields.pop("fingerprint", None)
    return hmac.new(key, _canonical_json(fields).encode("utf-8"), hashlib.sha256).hexdigest().upper()


def _fingerprint(payload: Mapping[str, Any]) -> str:
    normalized = dict(payload)
    normalized.pop("fingerprint", None)
    return _bytes_sha256(_canonical_json(normalized).encode("utf-8"))


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _json_object(payload: Mapping[str, Any]) -> dict[str, Any]:
    try:
        normalized = json.loads(_canonical_json(dict(payload)))
    except (TypeError, ValueError) as exc:
        raise WriterIpcError("Writer payload is not JSON serializable.") from exc
    if not isinstance(normalized, dict):
        raise WriterIpcError("Writer payload must be a JSON object.")
    _reject_sensitive_payload(normalized)
    return normalized


def _reject_sensitive_payload(value: Any, *, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            if any(fragment in normalized_key for fragment in FORBIDDEN_PAYLOAD_KEY_FRAGMENTS):
                raise WriterIpcError(
                    f"Writer payload contains a forbidden sensitive field at {path}."
                )
            _reject_sensitive_payload(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_sensitive_payload(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and any(
        value.startswith(prefix) for prefix in FORBIDDEN_PAYLOAD_VALUE_PREFIXES
    ):
        raise WriterIpcError(
            f"Writer payload contains a forbidden sensitive value at {path}."
        )


def _required_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WriterIpcError(f"{label} is required.")
    return value.strip()


def _session_id(value: str) -> str:
    normalized = _required_text(value, "Session ID").lower()
    if len(normalized) != 32 or any(character not in "0123456789abcdef" for character in normalized):
        raise WriterIpcError("Session ID must be 128-bit lowercase hexadecimal.")
    return normalized


def _sha256(value: str, label: str) -> str:
    normalized = _required_text(value, label).upper()
    if len(normalized) != 64 or any(character not in "0123456789ABCDEF" for character in normalized):
        raise WriterIpcError(f"{label} must be SHA-256 hexadecimal.")
    return normalized


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _temporary_output_root(path: Path) -> Path:
    resolved = path.resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    try:
        resolved.relative_to(temporary)
    except ValueError as exc:
        raise WriterIpcError(
            "Offline writer proof output must remain inside the system temporary root."
        ) from exc
    if resolved == temporary:
        raise WriterIpcError("Offline writer proof requires a dedicated subdirectory.")
    return resolved


def _write_once(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise WriterIpcError(f"Offline proof artifact already exists: {path.name}") from exc


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    child = commands.add_parser("child")
    child.add_argument("--output-root", type=Path, required=True)
    child.add_argument("--expected-parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "child":
            return _run_child(
                output_root=args.output_root,
                expected_parent_pid=args.expected_parent_pid,
            )
    except (WriterIpcError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(
            _canonical_json(
                {
                    "status": "FAILED",
                    "error": f"{type(exc).__name__}: {str(exc)}",
                    "activationAuthorized": False,
                }
            ),
            file=sys.stderr,
        )
        return 1
    raise AssertionError("Unreachable writer IPC command.")


if __name__ == "__main__":
    raise SystemExit(_main())
