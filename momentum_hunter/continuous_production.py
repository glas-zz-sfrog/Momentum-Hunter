"""Production research-only continuous runtime and dedicated writer IPC.

This module is intentionally separate from the historical dormant qualification
sidecar.  It owns only market-data research, immutable evidence persistence, and
health reporting.  It has no account, position, Paper, Shadow, or order adapter.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import socketserver
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, time as clock_time
from pathlib import Path, PurePath
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from momentum_hunter.continuous_live_qualification import (
    LiveCompositionSource,
    LiveDenominatorSource,
    LiveDiscoverySource,
    LiveMarketDataSource,
    NoEvents,
    QualificationState,
)
from momentum_hunter.continuous_runtime import (
    EXECUTION_AUTHORITY_NONE,
    ORDER_CAPABILITY_UNAVAILABLE,
    RESEARCH_AUTHORITY,
    ContinuousOpportunityRuntime,
    ContinuousRuntimeConfig,
    LogicalRuntimeLeaseRegistry,
    QueueCapacities,
    RuntimeCadence,
    RuntimeCheckpointStore,
    RuntimeHealth,
    build_evidence_write_intent,
)
from momentum_hunter.event_runtime_writer_ipc import (
    ALLOWED_ARTIFACTS,
    CAPABILITY_BYTES,
    EphemeralWriterCapability,
    GENESIS_FINGERPRINT,
    MAX_FRAME_BYTES,
    WriterEnvelope,
    WriterEnvelopeSender,
    verify_envelope_authentication,
)
from momentum_hunter.windows_writer_storage import WriterPhysicalStorage
from momentum_hunter.continuous_evidence_writer import (
    build_production_continuous_writer_topology,
)


CENTRAL = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")
PROFILE = "research-only-continuous-deployment-v1"
AUTHORITY = RESEARCH_AUTHORITY
EXECUTION = EXECUTION_AUTHORITY_NONE
ORDER_CAPABILITY = ORDER_CAPABILITY_UNAVAILABLE
WRITER_PORT = 49281
ARTIFACT_BY_EVIDENCE = {
    "DISCOVERY_CYCLE": "runtime-source-admission-ledger",
    "COMPOSITION_CYCLE": "event-decision-cycle-ledger",
    "OPPORTUNITY_DENOMINATOR": "runtime-source-admission-ledger",
    "PROVIDER_BOUND_DENOMINATOR_ROWS": "runtime-source-admission-ledger",
    "SYSTEM_FAILURE": "runtime-source-admission-ledger",
}


class ProductionDeploymentError(RuntimeError):
    """Raised when research deployment must fail closed."""


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(_canonical_bytes({"domain": domain, "value": value})).hexdigest()


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ProductionDeploymentError(f"Conflicting write-once file: {path.name}")
        return
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_replace(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    with temp.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionDeploymentError("Deployment configuration is unreadable.") from exc
    if not isinstance(value, dict) or value.get("mode") != "RESEARCH_ONLY":
        raise ProductionDeploymentError("Deployment configuration is not research-only.")
    if value.get("orderCapability") != ORDER_CAPABILITY or value.get("activationProfile") != PROFILE:
        raise ProductionDeploymentError("Deployment capability profile is invalid.")
    expected_configuration = _runtime_config(value).fingerprint
    if value.get("configurationFingerprint") != expected_configuration:
        raise ProductionDeploymentError("Deployment configuration identity is invalid.")
    return value


def _read_ipc_key(path: Path) -> bytes:
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise ProductionDeploymentError("IPC key is unavailable.") from exc
    if len(key) != CAPABILITY_BYTES:
        raise ProductionDeploymentError("IPC key has an invalid length.")
    return key


def _safe_payload(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            name = str(key).lower()
            if any(fragment in name for fragment in ("token", "secret", "password", "credential", "authorization", "api_key", "apikey")):
                raise ProductionDeploymentError("Evidence payload contains a forbidden secret field.")
            result[str(key)] = _safe_payload(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_payload(item) for item in value]
    if isinstance(value, str) and (value.startswith("sk-") or value.startswith("AKIA")):
        raise ProductionDeploymentError("Evidence payload contains a credential-shaped value.")
    return value


def _topology(config: Mapping[str, Any]):
    runtime_config = _runtime_config(config)
    return build_production_continuous_writer_topology(
        root_path=Path(str(config["evidenceRoot"])),
        evidence_program_id=str(config["evidenceProgramId"]),
        configuration_fingerprint=runtime_config.fingerprint,
        runtime_build_hash=str(config["runtimeBuildHash"]),
    )


def _runtime_config(config: Mapping[str, Any]) -> ContinuousRuntimeConfig:
    return ContinuousRuntimeConfig(
        runtime_identity=str(config["runtimeIdentity"]),
        # Continuous deployment identity must survive a midnight restart;
        # session dates belong to persisted market evidence, not this config.
        session_date=str(config.get("configurationSessionDate", "1970-01-01")),
        cadence=RuntimeCadence(
            broad_discovery_seconds=float(config["broadDiscoverySeconds"]),
            housekeeping_seconds=15,
            discovery_stale_seconds=float(config["broadDiscoverySeconds"]) * 2,
            composition_stale_seconds=float(config["broadDiscoverySeconds"]) * 2,
        ),
        queues=QueueCapacities(discovery=2, readiness=64, composition=64, evidence=256, health=16),
        lease_ttl_seconds=30,
        shutdown_timeout_seconds=10,
        maximum_tracked_symbols=60,
    )


def deployment_configuration_fingerprint(config: Mapping[str, Any]) -> str:
    """Return the canonical runtime configuration identity used by IPC."""

    return _runtime_config(config).fingerprint


class ProductionWriterServer:
    """Authenticated, single-owner writer process for the production root."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = config
        self.topology = _topology(config)
        self.root = Path(str(config["evidenceRoot"])) / self.topology.namespace
        self.root.mkdir(parents=True, exist_ok=True)
        self.storage = WriterPhysicalStorage(
            self.root,
            writer_instance_id=secrets.token_hex(16),
            topology_fingerprint=self.topology.fingerprint,
            topology_version=self.topology.topology_version,
        )
        self.ipc_key = _read_ipc_key(Path(str(config["ipcKeyPath"])))
        self.expected_sequence, self.prior_envelope = self._load_checkpoint()
        self.session_id: str | None = None
        self.source_identity: str | None = None
        self.session_key: bytes | None = None
        self.status_path = self.root / "status" / "writer-status.json"
        self._write_status("STARTING")

    def _load_checkpoint(self) -> tuple[int, str]:
        generations = self.root / "index" / "generations"
        if not generations.exists():
            return 1, GENESIS_FINGERPRINT
        latest: dict[str, Any] | None = None
        for path in generations.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="ascii"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(item, dict) and isinstance(item.get("sequence"), int):
                if latest is None or int(item["sequence"]) > int(latest["sequence"]):
                    latest = item
        if latest is None:
            return 1, GENESIS_FINGERPRINT
        return int(latest["sequence"]) + 1, str(latest["envelopeFingerprint"])

    def _write_status(self, state: str, **extra: object) -> None:
        payload = {
            "schemaVersion": 1,
            "profile": PROFILE,
            "state": state,
            "expectedSequence": self.expected_sequence,
            "topologyFingerprint": self.topology.fingerprint,
            "authority": AUTHORITY,
            "executionAuthority": EXECUTION,
            "orderCapability": ORDER_CAPABILITY,
            **extra,
        }
        payload["fingerprint"] = _fingerprint("production-writer-status-v1", payload)
        _atomic_replace(self.status_path, _canonical_bytes(payload))

    def close(self) -> None:
        self._write_status("STOPPED")
        self.storage.close()

    def _handshake(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        session_id = str(frame.get("sessionId", ""))
        source = str(frame.get("sourceIdentity", ""))
        configuration = str(frame.get("configurationFingerprint", ""))
        proof = str(frame.get("proof", ""))
        if len(session_id) != 32 or any(c not in "0123456789abcdef" for c in session_id):
            raise ProductionDeploymentError("Writer handshake session is invalid.")
        if not source.startswith("production-continuous-runtime-"):
            raise ProductionDeploymentError("Writer handshake source is invalid.")
        if configuration != self.topology.configuration_fingerprint:
            raise ProductionDeploymentError("Writer handshake configuration is invalid.")
        material = f"{session_id}\n{source}\n{configuration}".encode("ascii")
        expected = hmac.new(self.ipc_key, material, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(proof, expected):
            raise ProductionDeploymentError("Writer handshake authentication failed.")
        self.session_id = session_id
        self.source_identity = source
        self.session_key = hmac.new(self.ipc_key, f"session:{session_id}".encode("ascii"), hashlib.sha256).digest()
        self._write_status("READY", sessionId=session_id, sourceIdentity=source)
        return {"status": "READY", "nextSequence": self.expected_sequence, "priorEnvelopeFingerprint": self.prior_envelope}

    def _persist(self, envelope: WriterEnvelope) -> dict[str, Any]:
        if self.session_id is None or self.source_identity is None or self.session_key is None:
            raise ProductionDeploymentError("Writer session is not established.")
        verify_envelope_authentication(
            envelope,
            session_id=self.session_id,
            key_material=self.session_key,
            configuration_fingerprint=self.topology.configuration_fingerprint,
            source_identity=self.source_identity,
        )
        if envelope.sequence != self.expected_sequence:
            raise ProductionDeploymentError("Writer envelope sequence is not contiguous.")
        if envelope.prior_envelope_fingerprint != self.prior_envelope:
            raise ProductionDeploymentError("Writer envelope predecessor is invalid.")
        try:
            outer = json.loads(envelope.payload_json)
            intent_raw = outer["intent"]
            payload = _safe_payload(outer["payload"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProductionDeploymentError("Writer envelope payload is malformed.") from exc
        if not isinstance(intent_raw, dict) or not isinstance(payload, dict):
            raise ProductionDeploymentError("Writer envelope payload shape is invalid.")
        if outer.get("topologyFingerprint") != self.topology.fingerprint:
            raise ProductionDeploymentError("Writer envelope topology is invalid.")
        if not isinstance(intent_raw.get("sequence"), int) or int(intent_raw["sequence"]) <= 0:
            raise ProductionDeploymentError("Writer intent sequence is invalid.")
        if intent_raw.get("runtime_instance_id") != self.source_identity:
            raise ProductionDeploymentError("Writer intent identity is invalid.")
        evidence_type = str(intent_raw.get("evidence_type", ""))
        artifact = ARTIFACT_BY_EVIDENCE.get(evidence_type)
        if artifact is None or artifact not in ALLOWED_ARTIFACTS:
            raise ProductionDeploymentError("Writer artifact is not allowlisted.")
        record_fingerprint = str(intent_raw.get("record_fingerprint", ""))
        if len(record_fingerprint) != 64 or any(c not in "0123456789abcdef" for c in record_fingerprint):
            raise ProductionDeploymentError("Writer record fingerprint is invalid.")
        record_path = self.root / "records" / artifact / record_fingerprint[:2] / f"{record_fingerprint}.json"
        record = {
            "schemaVersion": 1,
            "profile": "production-continuous-evidence-record-v1",
            "authority": AUTHORITY,
            "executionAuthority": EXECUTION,
            "orderCapability": ORDER_CAPABILITY,
            "topologyFingerprint": self.topology.fingerprint,
            "artifactName": artifact,
            "intent": intent_raw,
            "payload": payload,
        }
        record["recordFingerprint"] = _fingerprint("production-continuous-record-v1", record)
        record_bytes = _canonical_bytes(record)
        created = self.storage.atomic_create(
            PurePath(record_path.relative_to(self.root)),
            record_bytes,
        )
        if not created:
            try:
                existing_record = json.loads(record_path.read_text(encoding="ascii"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ProductionDeploymentError("Existing immutable record is unreadable.") from exc
            if (
                not isinstance(existing_record, dict)
                or existing_record.get("intent") != intent_raw
                or existing_record.get("payload") != payload
                or existing_record.get("topologyFingerprint") != self.topology.fingerprint
            ):
                raise ProductionDeploymentError("Conflicting immutable record already exists.")
            record_bytes = _canonical_bytes(existing_record)
        record_sha = hashlib.sha256(record_bytes).hexdigest()
        ack = {
            "schemaVersion": 1,
            "profile": "production-continuous-ack-v1",
            "sequence": envelope.sequence,
            "sessionId": envelope.session_id,
            "envelopeFingerprint": envelope.fingerprint,
            "recordPath": record_path.relative_to(self.root).as_posix(),
            "recordSha256": record_sha,
            "status": "DUPLICATE" if not created else "ACCEPTED",
        }
        ack["fingerprint"] = _fingerprint("production-continuous-ack-v1", ack)
        ack_path = self.root / "sessions" / envelope.session_id / f"{envelope.sequence:08d}.ack.json"
        self.storage.atomic_create(PurePath(ack_path.relative_to(self.root)), _canonical_bytes(ack))
        checkpoint = {
            "schemaVersion": 1,
            "profile": PROFILE,
            "sequence": envelope.sequence,
            "envelopeFingerprint": envelope.fingerprint,
            "recordIdentity": intent_raw.get("record_identity"),
            "recordSha256": record_sha,
            "checkpointAt": datetime.now(tz=CENTRAL).isoformat(),
        }
        checkpoint["fingerprint"] = _fingerprint("production-continuous-checkpoint-v1", checkpoint)
        checkpoint_path = self.root / "index" / "generations" / f"{envelope.sequence:08d}.json"
        _write_once(checkpoint_path, _canonical_bytes(checkpoint))
        self.expected_sequence += 1
        self.prior_envelope = envelope.fingerprint
        self._write_status("READY", lastAcceptedSequence=envelope.sequence)
        return ack

    def serve_forever(self, host: str, port: int) -> None:
        server = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                for raw in self.rfile:
                    if len(raw) > MAX_FRAME_BYTES:
                        raise ProductionDeploymentError("Writer frame exceeds the bounded size.")
                    frame = json.loads(raw.decode("ascii"))
                    if not isinstance(frame, dict):
                        raise ProductionDeploymentError("Writer frame is not an object.")
                    try:
                        if frame.get("frameType") == "HELLO":
                            response = server._handshake(frame)
                        elif frame.get("frameType") == "WRITE":
                            response = server._persist(WriterEnvelope(**frame["envelope"]))
                        else:
                            raise ProductionDeploymentError("Writer frame type is unsupported.")
                        self.wfile.write(_canonical_bytes(response))
                        self.wfile.flush()
                    except Exception as exc:
                        response = {"status": "REJECTED", "error": type(exc).__name__}
                        self.wfile.write(_canonical_bytes(response))
                        self.wfile.flush()

        with socketserver.ThreadingTCPServer((host, port), Handler) as listener:
            listener.allow_reuse_address = False
            self._write_status("LISTENING", port=port)
            try:
                listener.serve_forever(poll_interval=0.5)
            finally:
                self._write_status("STOPPING")


class ProductionRemoteWriter:
    def __init__(self, config: Mapping[str, Any], *, source_identity: str) -> None:
        self.config = config
        self.topology = _topology(config)
        self.key = _read_ipc_key(Path(str(config["ipcKeyPath"])))
        if not source_identity.startswith("production-continuous-runtime-"):
            raise ProductionDeploymentError("Production runtime identity is invalid.")
        self.source_identity = source_identity
        self.sender: WriterEnvelopeSender | None = None

    def _connect(self) -> None:
        session_id = secrets.token_hex(16)
        session_key = hmac.new(self.key, f"session:{session_id}".encode("ascii"), hashlib.sha256).digest()
        configuration = self.topology.configuration_fingerprint
        material = f"{session_id}\n{self.source_identity}\n{configuration}".encode("ascii")
        hello = {
            "frameType": "HELLO",
            "sessionId": session_id,
            "sourceIdentity": self.source_identity,
            "configurationFingerprint": configuration,
            "proof": hmac.new(self.key, material, hashlib.sha256).hexdigest(),
        }
        response = self._request(hello)
        if response.get("status") != "READY":
            raise ProductionDeploymentError("Writer handshake was rejected.")
        self.sender = WriterEnvelopeSender(
            capability=EphemeralWriterCapability(session_id=session_id, key_material=session_key),
            configuration_fingerprint=configuration,
            source_identity=self.source_identity,
            starting_sequence=int(response["nextSequence"]),
            prior_envelope_fingerprint=str(response["priorEnvelopeFingerprint"]),
        )

    def _request(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        with socket.create_connection((str(self.config["ipcHost"]), int(self.config["ipcPort"])), timeout=5) as connection:
            connection.sendall(_canonical_bytes(frame))
            connection.shutdown(socket.SHUT_WR)
            data = connection.recv(MAX_FRAME_BYTES)
        value = json.loads(data.decode("ascii"))
        if not isinstance(value, dict):
            raise ProductionDeploymentError("Writer response is malformed.")
        return value

    def write_intent(self, intent: Any) -> str:
        if self.sender is None:
            try:
                self._connect()
            except (OSError, ProductionDeploymentError):
                return "UNAVAILABLE"
        try:
            payload = json.loads(intent.payload_json) if intent.payload_json else {
                "payloadType": intent.evidence_type,
                "intent": asdict(intent),
                "knownAt": intent.requested_at,
                "authority": AUTHORITY,
                "executionAuthority": EXECUTION,
            }
            envelope = self.sender.build(
                artifact_name=ARTIFACT_BY_EVIDENCE[intent.evidence_type],
                payload={
                    "topologyFingerprint": self.topology.fingerprint,
                    "intent": asdict(intent),
                    "payload": payload,
                },
            )
            response = self._request({"frameType": "WRITE", "envelope": asdict(envelope)})
            status = str(response.get("status", "REJECTED"))
            if status not in {"ACCEPTED", "DUPLICATE"}:
                self.sender = None
                return "UNAVAILABLE"
            return status
        except (OSError, KeyError, TypeError, ValueError, ProductionDeploymentError):
            self.sender = None
            return "UNAVAILABLE"


def _is_regular_session(now: datetime) -> bool:
    eastern = now.astimezone(EASTERN)
    return eastern.weekday() < 5 and clock_time(9, 30) <= eastern.time() < clock_time(16, 0)


def _write_runtime_status(path: Path, health: RuntimeHealth | None, *, state: str, config: Mapping[str, Any], **extra: object) -> None:
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "profile": PROFILE,
        "state": state,
        "activationStart": config.get("activationStart"),
        "mode": "RESEARCH_ONLY",
        "authority": AUTHORITY,
        "executionAuthority": EXECUTION,
        "orderCapability": ORDER_CAPABILITY,
        "accountReads": "UNAVAILABLE",
        "positionReads": "UNAVAILABLE",
        "brokerOrders": "UNAVAILABLE",
        "alpacaPaper": "UNAVAILABLE",
        "alpacaLive": "UNAVAILABLE",
        "shadowExecution": "UNAVAILABLE",
        "health": asdict(health) if health else None,
        **extra,
    }
    payload["fingerprint"] = _fingerprint("production-continuous-runtime-status-v1", payload)
    _atomic_replace(path, _canonical_bytes(payload))


def run_writer(config_path: Path) -> int:
    config = _read_config(config_path)
    server = ProductionWriterServer(config)
    try:
        server.serve_forever(str(config["ipcHost"]), int(config["ipcPort"]))
    finally:
        server.close()
    return 0


def run_runtime(config_path: Path) -> int:
    config = _read_config(config_path)
    runtime_root = Path(str(config["runtimeStateRoot"]))
    runtime_root.mkdir(parents=True, exist_ok=True)
    status_path = runtime_root / "runtime-status.json"
    state = QualificationState(root=runtime_root / "session", launch_at=datetime.now().astimezone())
    discovery = LiveDiscoverySource(state)
    market = LiveMarketDataSource(state, expected_account_ending=str(config["expectedAccountEnding"]))
    composition = LiveCompositionSource(state)
    denominator = LiveDenominatorSource(state)
    events = NoEvents()
    checkpoints = RuntimeCheckpointStore(runtime_root / "checkpoint", allow_persistent=True)
    checkpoint_path = checkpoints.path_for(str(config["runtimeIdentity"]))
    if checkpoint_path.exists():
        checkpoint_payload = checkpoints.load(str(config["runtimeIdentity"]))
        runtime_instance_id = str(checkpoint_payload.get("runtime_instance_id", ""))
        if not runtime_instance_id.startswith("production-continuous-runtime-"):
            raise ProductionDeploymentError("Persisted runtime identity is invalid.")
    else:
        runtime_instance_id = f"production-continuous-runtime-{secrets.token_hex(12)}"
    remote_writer = ProductionRemoteWriter(config, source_identity=runtime_instance_id)
    leases = LogicalRuntimeLeaseRegistry()
    runtime_config = _runtime_config(config)
    runtime = ContinuousOpportunityRuntime(
        config=runtime_config,
        runtime_instance_id=runtime_instance_id,
        discovery_source=discovery,
        market_data_source=market,
        event_source=events,
        composition_source=composition,
        denominator_source=denominator,
        writer=remote_writer,
        lease_registry=leases,
        checkpoint_store=checkpoints,
    )
    now = datetime.now().astimezone()
    if checkpoint_path.exists():
        runtime = ContinuousOpportunityRuntime.restore(
            config=runtime_config,
            runtime_instance_id=runtime_instance_id,
            now=now,
            discovery_source=discovery,
            market_data_source=market,
            event_source=events,
            composition_source=composition,
            denominator_source=denominator,
            writer=remote_writer,
            lease_registry=leases,
            checkpoint_store=checkpoints,
        )
    else:
        runtime.start(now)
    _write_runtime_status(status_path, runtime.health(now), state="IDLE_OUT_OF_SESSION" if not _is_regular_session(now) else "RUNNING", config=config)
    last_restart = 0.0
    try:
        while True:
            now = datetime.now().astimezone()
            if _is_regular_session(now):
                health = runtime.tick(now, work_budget=512)
                _write_runtime_status(status_path, health, state="DEGRADED" if health.process_state == "DEGRADED" else "RUNNING", config=config)
            else:
                _write_runtime_status(status_path, runtime.health(now), state="IDLE_OUT_OF_SESSION", config=config)
            time.sleep(5)
    except KeyboardInterrupt:
        return 0
    finally:
        now = datetime.now().astimezone()
        try:
            health = runtime.shutdown(now)
            _write_runtime_status(status_path, health, state="STOPPED", config=config)
        except Exception:
            _write_runtime_status(status_path, None, state="FAILED", config=config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Momentum Hunter research-only continuous deployment host")
    parser.add_argument("--role", choices=("writer", "runtime"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--print-config-fingerprint", action="store_true")
    args = parser.parse_args(argv)
    if args.print_config_fingerprint:
        config = json.loads(args.config.read_text(encoding="ascii"))
        if not isinstance(config, dict):
            raise SystemExit("Deployment configuration must be an object.")
        print(deployment_configuration_fingerprint(config))
        return 0
    if args.role is None:
        parser.error("--role is required unless --print-config-fingerprint is used")
    return run_writer(args.config) if args.role == "writer" else run_runtime(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
