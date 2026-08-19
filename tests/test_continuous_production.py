from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from momentum_hunter.continuous_production import (
    ProductionDeploymentError,
    ProductionRemoteWriter,
    ProductionWriterServer,
    PREMARKET,
    REGULAR_SESSION,
    SESSION_CLOSED,
    _canonical_bytes,
    _fingerprint,
    _market_session_phase,
    _resolved_discovery_cadence,
    _runtime_config,
    _safe_payload,
    deployment_configuration_fingerprint,
)
from momentum_hunter.continuous_runtime import (
    WRITER_ACCEPTED,
    build_evidence_write_intent,
)
from momentum_hunter.event_runtime_writer_ipc import (
    EphemeralWriterCapability,
    WriterEnvelopeSender,
    WriterEnvelope,
)


class ContinuousProductionTests(unittest.TestCase):
    def _config(self, root: Path) -> dict[str, object]:
        value: dict[str, object] = {
            "activationProfile": "research-only-continuous-deployment-v1",
            "mode": "RESEARCH_ONLY",
            "orderCapability": "UNAVAILABLE",
            "runtimeIdentity": "production-continuous-runtime-v1",
            "runtimeBuildHash": "a" * 64,
            "evidenceProgramId": "continuous-opportunity-production",
            "evidenceRoot": str(root / "evidence"),
            "runtimeStateRoot": str(root / "runtime"),
            "ipcKeyPath": str(root / "ipc.key"),
            "ipcHost": "127.0.0.1",
            "ipcPort": 49281,
            "expectedAccountEnding": "2573",
            "broadDiscoverySeconds": 300,
        }
        value["configurationFingerprint"] = deployment_configuration_fingerprint(value)
        return value

    def _intent(self, runtime_id: str, sequence: int = 1):
        payload = {
            "payloadType": "COMPOSITION_CYCLE",
            "cycleId": "cycle-1",
            "knownAt": "2026-08-18T20:00:00+00:00",
        }
        payload_fingerprint = _fingerprint("continuous-evidence-payload-v1", payload)
        return build_evidence_write_intent(
            runtime_instance_id=runtime_id,
            sequence=sequence,
            evidence_type="COMPOSITION_CYCLE",
            record_identity="cycle-1",
            record_fingerprint="b" * 64,
            predecessor_identity=None if sequence == 1 else "prior-intent",
            requested_at="2026-08-18T20:00:00+00:00",
            payload_fingerprint=payload_fingerprint,
            payload=payload,
        )

    def _handshake(self, server: ProductionWriterServer, source: str, session_id: str):
        material = f"{session_id}\n{source}\n{server.topology.configuration_fingerprint}".encode("ascii")
        return server._handshake(
            {
                "sessionId": session_id,
                "sourceIdentity": source,
                "configurationFingerprint": server.topology.configuration_fingerprint,
                "proof": hmac.new(server.ipc_key, material, hashlib.sha256).hexdigest(),
            }
        )

    def test_production_writer_identity_is_active_and_restart_duplicate_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key_path = root / "ipc.key"
            key_path.write_bytes(secrets.token_bytes(32))
            config = self._config(root)
            source = "production-continuous-runtime-test"
            server = ProductionWriterServer(config)
            self.assertEqual("RESEARCH_ONLY_ACTIVE", server.topology.activation_state)
            self.assertEqual("production-continuous-evidence-writer-topology-v1", server.topology.profile)
            session_id = secrets.token_hex(16)
            hello = self._handshake(server, source, session_id)
            capability = EphemeralWriterCapability(
                session_id=session_id,
                key_material=hmac.new(server.ipc_key, f"session:{session_id}".encode("ascii"), hashlib.sha256).digest(),
            )
            sender = WriterEnvelopeSender(
                capability=capability,
                configuration_fingerprint=server.topology.configuration_fingerprint,
                source_identity=source,
                starting_sequence=hello["nextSequence"],
                prior_envelope_fingerprint=hello["priorEnvelopeFingerprint"],
            )
            intent = self._intent(source)
            payload = {
                "topologyFingerprint": server.topology.fingerprint,
                "intent": asdict(intent),
                "payload": json.loads(intent.payload_json or "{}"),
            }
            envelope = sender.build(artifact_name="event-decision-cycle-ledger", payload=payload)
            self.assertEqual("ACCEPTED", server._persist(envelope)["status"])
            stored_paths = list((server.root / "records").rglob("*.json"))
            self.assertEqual(1, len(stored_paths))
            stored = json.loads(stored_paths[0].read_text(encoding="ascii"))
            self.assertEqual(2, stored["schemaVersion"])
            self.assertNotIn("payload_json", stored["intent"])
            self.assertEqual(json.loads(intent.payload_json or "{}"), stored["payload"])
            server.close()

            restarted = ProductionWriterServer(config)
            try:
                next_session = secrets.token_hex(16)
                next_hello = self._handshake(restarted, source, next_session)
                next_capability = EphemeralWriterCapability(
                    session_id=next_session,
                    key_material=hmac.new(restarted.ipc_key, f"session:{next_session}".encode("ascii"), hashlib.sha256).digest(),
                )
                retry_sender = WriterEnvelopeSender(
                    capability=next_capability,
                    configuration_fingerprint=restarted.topology.configuration_fingerprint,
                    source_identity=source,
                    starting_sequence=next_hello["nextSequence"],
                    prior_envelope_fingerprint=next_hello["priorEnvelopeFingerprint"],
                )
                retry_envelope = retry_sender.build(artifact_name="event-decision-cycle-ledger", payload=payload)
                self.assertEqual("DUPLICATE", restarted._persist(retry_envelope)["status"])
            finally:
                restarted.close()

    def test_config_identity_is_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._config(root)
            self.assertEqual(config["configurationFingerprint"], deployment_configuration_fingerprint(config))
            config["broadDiscoverySeconds"] = 301
            self.assertNotEqual(config["configurationFingerprint"], deployment_configuration_fingerprint(config))

    def test_runtime_remote_and_dedicated_writer_compose_without_duplicate_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "ipc.key").write_bytes(secrets.token_bytes(32))
            config = self._config(root)
            source = "production-continuous-runtime-composition"
            server = ProductionWriterServer(config)
            remote = ProductionRemoteWriter(config, source_identity=source)

            def direct_request(frame):
                if frame["frameType"] == "HELLO":
                    return server._handshake(frame)
                return server._persist(WriterEnvelope(**frame["envelope"]))

            remote._request = direct_request
            try:
                result = remote.write_intent(self._intent(source))
                self.assertEqual(WRITER_ACCEPTED, result.status)
                stored_paths = list((server.root / "records").rglob("*.json"))
                self.assertEqual(1, len(stored_paths))
                stored = json.loads(stored_paths[0].read_text(encoding="ascii"))
                self.assertNotIn("payload_json", stored["intent"])
                self.assertEqual("COMPOSITION_CYCLE", stored["payload"]["payloadType"])
            finally:
                server.close()

    def test_payload_secret_shape_is_rejected(self):
        with self.assertRaises(ProductionDeploymentError):
            _safe_payload({"api_key": "redacted-looking-value"})

    def test_market_session_phase_supports_premarket_regular_and_calendar(self):
        eastern = ZoneInfo("America/New_York")

        self.assertEqual(
            PREMARKET,
            _market_session_phase(
                datetime(2026, 8, 19, 7, 5, tzinfo=eastern)
            ),
        )
        self.assertEqual(
            REGULAR_SESSION,
            _market_session_phase(
                datetime(2026, 8, 19, 9, 30, tzinfo=eastern)
            ),
        )
        self.assertEqual(
            SESSION_CLOSED,
            _market_session_phase(
                datetime(2026, 8, 19, 16, 0, tzinfo=eastern)
            ),
        )
        self.assertEqual(
            SESSION_CLOSED,
            _market_session_phase(
                datetime(2026, 8, 22, 10, 0, tzinfo=eastern)
            ),
        )
        self.assertEqual(
            SESSION_CLOSED,
            _market_session_phase(
                datetime(2026, 11, 27, 13, 0, tzinfo=eastern)
            ),
        )

    def test_session_phase_resolves_approved_discovery_cadence(self):
        config = {
            "premarketDiscoverySeconds": 600,
            "broadDiscoverySeconds": 300,
        }

        self.assertEqual(600, _resolved_discovery_cadence(PREMARKET, config))
        self.assertEqual(
            300, _resolved_discovery_cadence(REGULAR_SESSION, config)
        )
        self.assertIsNone(
            _resolved_discovery_cadence(SESSION_CLOSED, config)
        )


if __name__ == "__main__":
    unittest.main()
