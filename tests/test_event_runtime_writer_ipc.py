from __future__ import annotations

import base64
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import momentum_hunter.event_runtime_writer_ipc as writer_ipc
from momentum_hunter.event_runtime_writer_ipc import (
    ACTIVATION_BLOCKERS,
    AUTHORITY,
    BOUNDARY_KIND,
    CHANNEL_AUTHENTICATION,
    CHANNEL_KIND,
    GENESIS_FINGERPRINT,
    STATUS_PROVEN_BLOCKED,
    EphemeralWriterCapability,
    OfflineWriterSink,
    WriterEnvelope,
    WriterEnvelopeSender,
    WriterEnvelopeVerifier,
    WriterIpcError,
    run_offline_writer_proof,
)


CONFIGURATION = "A" * 64
OTHER_CONFIGURATION = "B" * 64
SOURCE = "continuous-runtime-engine-host:test-only"
KEY = bytes(range(32))
SESSION = "1" * 32


class EventRuntimeWriterIpcTests(unittest.TestCase):
    def setUp(self) -> None:
        self.capability = EphemeralWriterCapability(
            session_id=SESSION,
            key_material=KEY,
        )
        self.sender = WriterEnvelopeSender(
            capability=self.capability,
            configuration_fingerprint=CONFIGURATION,
            source_identity=SOURCE,
        )

    def tearDown(self) -> None:
        self.capability.close()

    def verifier(self, **overrides: object) -> WriterEnvelopeVerifier:
        values = {
            "session_id": SESSION,
            "key_material": KEY,
            "configuration_fingerprint": CONFIGURATION,
            "source_identity": SOURCE,
        }
        values.update(overrides)
        return WriterEnvelopeVerifier(**values)

    def envelope(self, sequence_value: str = "first") -> WriterEnvelope:
        return self.sender.build(
            artifact_name="candidate-lifecycle-ledger",
            payload={"event": sequence_value, "symbol": "SYNTH"},
        )

    def test_authenticated_envelopes_are_ordered_and_chained(self) -> None:
        first = self.envelope("first")
        second = self.envelope("second")
        verifier = self.verifier()

        verifier.verify(first)
        verifier.verify(second)
        verifier.close()

        self.assertEqual(1, first.sequence)
        self.assertEqual(2, second.sequence)
        self.assertEqual(GENESIS_FINGERPRINT, first.prior_envelope_fingerprint)
        self.assertEqual(first.fingerprint, second.prior_envelope_fingerprint)
        self.assertNotIn(base64.b64encode(KEY).decode("ascii"), json.dumps(asdict(first)))

    def test_tampering_forgery_replay_and_out_of_order_fail_closed(self) -> None:
        first = self.envelope("first")
        second = self.envelope("second")
        tampered_json = json.dumps(
            {"event": "tampered", "symbol": "SYNTH"},
            sort_keys=True,
            separators=(",", ":"),
        )
        provisional = replace(
            first,
            payload_json=tampered_json,
            payload_sha256=writer_ipc._bytes_sha256(tampered_json.encode("utf-8")),
            fingerprint="",
        )
        forged = replace(
            provisional,
            fingerprint=writer_ipc._fingerprint(asdict(provisional)),
        )

        with self.assertRaisesRegex(WriterIpcError, "authentication"):
            self.verifier().verify(forged)
        with self.assertRaisesRegex(WriterIpcError, "replayed or out of order"):
            self.verifier().verify(second)

        verifier = self.verifier()
        verifier.verify(first)
        with self.assertRaisesRegex(WriterIpcError, "replayed or out of order"):
            verifier.verify(first)

    def test_cross_session_configuration_source_and_artifact_are_rejected(self) -> None:
        envelope = self.envelope()
        with self.assertRaisesRegex(WriterIpcError, "different writer session"):
            self.verifier(session_id="2" * 32).verify(envelope)
        with self.assertRaisesRegex(WriterIpcError, "configuration"):
            self.verifier(configuration_fingerprint=OTHER_CONFIGURATION).verify(envelope)
        with self.assertRaisesRegex(WriterIpcError, "source identity"):
            self.verifier(source_identity="other:test-only").verify(envelope)
        with self.assertRaisesRegex(WriterIpcError, "allowlist"):
            self.sender.build(artifact_name="arbitrary-file", payload={"value": 1})

    def test_capability_is_redacted_and_zeroized_on_close(self) -> None:
        self.assertIn("<REDACTED>", repr(self.capability))
        self.assertNotIn(KEY.hex(), repr(self.capability))
        self.capability.close()
        self.assertTrue(self.capability.closed)
        with self.assertRaisesRegex(WriterIpcError, "closed"):
            self.capability.key_bytes()

    def test_offline_child_proof_persists_no_capability_and_never_activates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proof"
            with (
                patch.object(writer_ipc.secrets, "token_hex", return_value=SESSION),
                patch.object(writer_ipc.secrets, "token_bytes", return_value=KEY),
            ):
                result = run_offline_writer_proof(
                    output_root=output,
                    configuration_fingerprint=CONFIGURATION,
                    source_identity=SOURCE,
                    records=(
                        ("candidate-lifecycle-ledger", {"symbol": "SYNTH", "state": "SEEN"}),
                        ("continuous-plan-ledger", {"symbol": "SYNTH", "plan": "ABSTAIN"}),
                    ),
                )

            self.assertEqual(STATUS_PROVEN_BLOCKED, result.status)
            self.assertEqual(2, result.records_accepted)
            self.assertEqual(BOUNDARY_KIND, result.boundary_kind)
            self.assertEqual(CHANNEL_KIND, result.channel_kind)
            self.assertEqual(CHANNEL_AUTHENTICATION, result.channel_authentication)
            self.assertTrue(result.same_principal_prototype)
            self.assertFalse(result.activation_authorized)
            self.assertEqual(ACTIVATION_BLOCKERS, result.activation_blockers)
            self.assertFalse(result.capability_persisted)
            self.assertFalse(result.capability_in_arguments)
            self.assertFalse(result.capability_in_environment)
            self.assertTrue(result.parent_pid_bound)
            files = sorted(output.iterdir())
            self.assertEqual(3, len(files))
            combined = b"".join(path.read_bytes() for path in files)
            self.assertNotIn(KEY, combined)
            self.assertNotIn(base64.b64encode(KEY), combined)
            receipt = json.loads((output / "session-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(AUTHORITY, receipt["authority"])
            self.assertFalse(receipt["activationAuthorized"])

    def test_conflicting_existing_output_fails_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proof"
            output.mkdir()
            marker = output / "existing.txt"
            marker.write_text("preserve me", encoding="utf-8")

            with self.assertRaisesRegex(WriterIpcError, "empty"):
                run_offline_writer_proof(
                    output_root=output,
                    configuration_fingerprint=CONFIGURATION,
                    source_identity=SOURCE,
                    records=(),
                )

            self.assertEqual("preserve me", marker.read_text(encoding="utf-8"))

    def test_output_outside_system_temporary_root_is_rejected(self) -> None:
        repository_output = Path(__file__).resolve().parents[1] / "forbidden-ipc-proof"
        with self.assertRaisesRegex(WriterIpcError, "temporary root"):
            run_offline_writer_proof(
                output_root=repository_output,
                configuration_fingerprint=CONFIGURATION,
                source_identity=SOURCE,
                records=(),
            )
        self.assertFalse(repository_output.exists())

    def test_interrupted_session_is_incomplete_and_cannot_replay_into_restart(self) -> None:
        first = self.envelope()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "interrupted"
            sink = OfflineWriterSink(output, session_id=SESSION)
            verifier = self.verifier()
            verifier.verify(first)
            sink.persist(first)
            verifier.close()

            self.assertFalse((output / "session-receipt.json").exists())
            self.assertEqual(1, len(list(output.glob("frame-*.json"))))

            restarted = self.verifier(session_id="2" * 32)
            with self.assertRaisesRegex(WriterIpcError, "different writer session"):
                restarted.verify(first)

    def test_source_payload_is_not_mutated(self) -> None:
        payload = {"symbol": "SYNTH", "nested": {"rank": 1}}
        before = json.loads(json.dumps(payload))
        self.sender.build(
            artifact_name="candidate-lifecycle-ledger",
            payload=payload,
        )
        self.assertEqual(before, payload)

    def test_credential_shaped_payload_is_rejected_before_signing(self) -> None:
        for payload in (
            {"api_key": "not-allowed"},
            {"nested": {"refresh-token": "not-allowed"}},
            {"value": "sk-prohibited-shaped-value"},
            {"value": "AKIA0000000000000000"},
        ):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(WriterIpcError, "forbidden sensitive"):
                    self.sender.build(
                        artifact_name="candidate-lifecycle-ledger",
                        payload=payload,
                    )

    def test_capability_closes_when_record_validation_fails(self) -> None:
        capability = EphemeralWriterCapability(
            session_id=SESSION,
            key_material=KEY,
        )
        with patch.object(
            writer_ipc.EphemeralWriterCapability,
            "create",
            return_value=capability,
        ):
            with self.assertRaisesRegex(WriterIpcError, "forbidden sensitive"):
                run_offline_writer_proof(
                    output_root=Path(tempfile.gettempdir()) / "unused-proof-path",
                    configuration_fingerprint=CONFIGURATION,
                    source_identity=SOURCE,
                    records=(("candidate-lifecycle-ledger", {"api_key": "no"}),),
                )
        self.assertTrue(capability.closed)

    def test_parent_validation_rejects_tampered_child_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proof"
            with (
                patch.object(writer_ipc.secrets, "token_hex", return_value=SESSION),
                patch.object(writer_ipc.secrets, "token_bytes", return_value=KEY),
            ):
                run_offline_writer_proof(
                    output_root=output,
                    configuration_fingerprint=CONFIGURATION,
                    source_identity=SOURCE,
                    records=(("candidate-lifecycle-ledger", {"symbol": "SYNTH"}),),
                )
            expected_capability = EphemeralWriterCapability(
                session_id=SESSION,
                key_material=KEY,
            )
            expected_sender = WriterEnvelopeSender(
                capability=expected_capability,
                configuration_fingerprint=CONFIGURATION,
                source_identity=SOURCE,
            )
            expected_envelope = expected_sender.build(
                artifact_name="candidate-lifecycle-ledger",
                payload={"symbol": "SYNTH"},
            )
            expected_capability.close()
            frame_path = next(output.glob("frame-*.json"))
            frame_path.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(WriterIpcError, "record identity"):
                writer_ipc._validate_offline_output(
                    output_root=output,
                    expected_session_id=SESSION,
                    expected_envelopes=(expected_envelope,),
                )

    def test_child_rejects_wrong_parent_before_reading_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-m",
                    "momentum_hunter.event_runtime_writer_ipc",
                    "child",
                    "--output-root",
                    str(Path(temporary) / "proof"),
                    "--expected-parent-pid",
                    str(os.getpid() + 1_000_000),
                ],
                input="",
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(1, completed.returncode)
            self.assertIn("parent identity", completed.stderr)
            self.assertFalse((Path(temporary) / "proof").exists())

    def test_child_rejects_non_object_bootstrap_without_echoing_input(self) -> None:
        sentinel = "SHOULD-NOT-RETURN-IN-DIAGNOSTICS"
        base_executable = str(
            Path(getattr(sys, "_base_executable", sys.executable)).resolve()
        )
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run(
                [
                    base_executable,
                    "-B",
                    "-m",
                    "momentum_hunter.event_runtime_writer_ipc",
                    "child",
                    "--output-root",
                    str(Path(temporary) / "proof"),
                    "--expected-parent-pid",
                    str(os.getpid()),
                ],
                input=json.dumps([sentinel]) + "\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(1, completed.returncode)
            self.assertIn("JSON object", completed.stderr)
            self.assertNotIn(sentinel, completed.stderr)
            self.assertFalse((Path(temporary) / "proof").exists())

    def test_module_is_dormant_and_has_no_provider_broker_or_network_capability(self) -> None:
        source = inspect.getsource(writer_ipc).lower()
        for forbidden in (
            "import requests",
            "import httpx",
            "import socket",
            "api.alpaca.markets",
            "api.schwabapi.com",
            "submit_order(",
            "cancel_order(",
            "replace_order(",
            "query_account(",
        ):
            self.assertNotIn(forbidden, source)

        package_root = Path(writer_ipc.__file__).resolve().parent
        importers = []
        for path in package_root.glob("*.py"):
            if path.name == "event_runtime_writer_ipc.py":
                continue
            text = path.read_text(encoding="utf-8")
            if "event_runtime_writer_ipc" in text:
                importers.append(path.name)
        self.assertEqual(["continuous_evidence_writer.py"], importers)


if __name__ == "__main__":
    unittest.main()
