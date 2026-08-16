from __future__ import annotations

import ast
import hashlib
import json
import tempfile
import time
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from momentum_hunter.continuous_evidence_writer import (
    ACTIVATION_BLOCKERS,
    APPEND,
    CRASH_AFTER_ACK_BEFORE_RETURN,
    CRASH_AFTER_COMMIT_BEFORE_ACK,
    CRASH_AFTER_TEMP,
    CRASH_BEFORE_COMMIT,
    DEDICATED_EVIDENCE_WRITER,
    READ,
    STORAGE_FORMAT,
    AuthenticatedEvidenceWriterClient,
    ContinuousEvidenceWriterError,
    DedicatedEvidenceWriter,
    WriterRoleContract,
    artifact_record_path,
    authorize_topology_access,
    build_continuous_writer_topology_v2,
    read_evidence_snapshot,
    topology_contradiction_inventory,
    topology_v1_compatibility,
    validate_continuous_writer_topology_v2,
)
from momentum_hunter.continuous_runtime import (
    WRITER_ACCEPTED,
    WRITER_DUPLICATE,
    WRITER_SLOW,
    WRITER_UNAVAILABLE,
    build_evidence_write_intent,
)
from momentum_hunter.event_runtime_topology import (
    OFFLINE_REVIEW,
    PYTHON_ENGINE_HOST,
    WPF_WORKSTATION,
    build_event_runtime_topology,
)
from momentum_hunter.event_runtime_writer_ipc import (
    MAX_PAYLOAD_BYTES,
    EphemeralWriterCapability,
    WriterEnvelopeSender,
    WriterIpcError,
)
from tests.test_continuous_runtime import RuntimeFixture


CONFIGURATION = "a" * 64
RUNTIME_BUILD = "b" * 64
PROGRAM = "continuous-research-v2"
RUNTIME_1 = "continuous-runtime-instance-1"
RUNTIME_2 = "continuous-runtime-instance-2"


def fp(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class WriterFixture:
    def __init__(self, root: Path, *, runtime_id: str = RUNTIME_1) -> None:
        self.root = root
        self.runtime_id = runtime_id
        self.topology = build_continuous_writer_topology_v2(
            root_path=root,
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
            runtime_build_hash=RUNTIME_BUILD,
        )
        self.capability = EphemeralWriterCapability.create()
        self.writer = DedicatedEvidenceWriter(self.topology)
        self.writer.activate_session(
            capability=self.capability,
            source_identity=runtime_id,
        )
        self.client = AuthenticatedEvidenceWriterClient(
            topology=self.topology,
            capability=self.capability,
            runtime_instance_id=runtime_id,
            writer=self.writer,
        )

    def close(self) -> None:
        self.writer.close()
        self.capability.close()

    def intent(
        self,
        sequence: int = 1,
        *,
        evidence_type: str = "COMPOSITION_CYCLE",
        record_identity: str | None = None,
        record_fingerprint: str | None = None,
        predecessor_identity: str | None = None,
        runtime_id: str | None = None,
    ):
        return build_evidence_write_intent(
            runtime_instance_id=runtime_id or self.runtime_id,
            sequence=sequence,
            evidence_type=evidence_type,
            record_identity=record_identity or f"record-{sequence}",
            record_fingerprint=record_fingerprint or fp(f"record-{sequence}"),
            predecessor_identity=predecessor_identity,
            requested_at=f"2026-08-17T14:{sequence % 60:02d}:00+00:00",
            payload_fingerprint=fp(f"payload-{sequence}"),
        )

    def envelope_sender(
        self,
        *,
        capability: EphemeralWriterCapability | None = None,
        source_identity: str | None = None,
    ) -> WriterEnvelopeSender:
        return WriterEnvelopeSender(
            capability=capability or self.capability,
            configuration_fingerprint=CONFIGURATION,
            source_identity=source_identity or self.runtime_id,
        )

    def envelope(self, sender: WriterEnvelopeSender, intent, *, artifact=None, extra=None):
        payload = {
            "intent": asdict(intent),
            "topologyFingerprint": self.topology.fingerprint,
        }
        if extra:
            payload.update(extra)
        return sender.build(
            artifact_name=artifact or "event-decision-cycle-ledger",
            payload=payload,
        )


class ContinuousWriterTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def topology(self):
        return build_continuous_writer_topology_v2(
            root_path=self.root,
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
            runtime_build_hash=RUNTIME_BUILD,
        )

    def test_topology_v2_is_deterministic_explicit_and_dormant(self) -> None:
        first = self.topology()
        second = self.topology()
        self.assertEqual(first, second)
        self.assertEqual(2, first.topology_version)
        self.assertEqual(DEDICATED_EVIDENCE_WRITER, first.writer_role)
        self.assertEqual(
            (PYTHON_ENGINE_HOST, WPF_WORKSTATION, OFFLINE_REVIEW),
            first.reader_roles,
        )
        self.assertEqual(STORAGE_FORMAT, first.storage_format)
        self.assertEqual("DORMANT_UNINSTALLED", first.activation_state)
        self.assertEqual(ACTIVATION_BLOCKERS, first.activation_blockers)
        validate_continuous_writer_topology_v2(first)

    def test_v1_contradictions_are_explicit_and_historical_identity_is_preserved(self) -> None:
        inventory = topology_contradiction_inventory()
        self.assertEqual(
            {"WRITER_ROLE", "IPC", "PHYSICAL_STORAGE", "READER_BOUNDARY"},
            {item.topic for item in inventory},
        )
        old = build_event_runtime_topology(
            root_path=self.root / "v1",
            evidence_program_id="old-program",
            configuration_fingerprint=CONFIGURATION,
            runtime_build_hash=RUNTIME_BUILD,
        )
        compatibility = topology_v1_compatibility(old)
        self.assertTrue(compatibility.topology_v1_evidence_readable)
        self.assertFalse(compatibility.topology_v1_historical_identity_rewritten)
        self.assertFalse(compatibility.migration_required)

    def test_only_dedicated_writer_can_append_and_engine_host_wpf_are_read_only(self) -> None:
        topology = self.topology()
        self.assertTrue(
            authorize_topology_access(
                topology,
                role=DEDICATED_EVIDENCE_WRITER,
                operation=APPEND,
            )
        )
        for role in (PYTHON_ENGINE_HOST, WPF_WORKSTATION, OFFLINE_REVIEW):
            self.assertTrue(authorize_topology_access(topology, role=role, operation=READ))
            self.assertFalse(authorize_topology_access(topology, role=role, operation=APPEND))
        self.assertFalse(authorize_topology_access(topology, role="CONTINUOUS_RUNTIME", operation=APPEND))
        self.assertFalse(authorize_topology_access(topology, role="WINDOWS_AUTOMATION_SERVICE", operation=READ))

    def test_writer_role_has_only_minimal_capabilities(self) -> None:
        contract = WriterRoleContract()
        self.assertEqual(("VALIDATE", "ORDER", "PERSIST", "ACKNOWLEDGE"), contract.capabilities)
        self.assertFalse(contract.requires_provider_credentials)
        self.assertEqual("UNAVAILABLE", contract.order_transmission)
        self.assertIn("BROKER_ORDER", contract.forbidden_capabilities)

    def test_runtime_cannot_supply_paths_or_malformed_names(self) -> None:
        topology = self.topology()
        canonical = artifact_record_path(
            topology,
            artifact_name="event-decision-cycle-ledger",
            record_fingerprint=fp("safe"),
        )
        self.assertEqual(f"{fp('safe')}.json", canonical.name)
        self.assertTrue(canonical.is_relative_to(self.root))
        for artifact in ("../escape", "C:\\escape", "CON", "event/ledger"):
            with self.subTest(artifact=artifact):
                with self.assertRaises(ContinuousEvidenceWriterError):
                    artifact_record_path(
                        topology,
                        artifact_name=artifact,
                        record_fingerprint=fp("safe"),
                    )

    def test_program_path_traversal_absolute_unicode_and_devices_are_rejected(self) -> None:
        for program in ("../escape", "C:/escape", "CON", "nul.txt", "bad/name", "café"):
            with self.subTest(program=program):
                with self.assertRaises(ContinuousEvidenceWriterError):
                    build_continuous_writer_topology_v2(
                        root_path=self.root,
                        evidence_program_id=program,
                        configuration_fingerprint=CONFIGURATION,
                        runtime_build_hash=RUNTIME_BUILD,
                    )

    def test_topology_tampering_fails_closed(self) -> None:
        topology = self.topology()
        for changed in (
            replace(topology, writer_role=PYTHON_ENGINE_HOST),
            replace(topology, topology_version=1),
            replace(topology, ipc_contract_version="wrong"),
            replace(topology, storage_format="single-growing-ledger"),
            replace(topology, activation_state="ACTIVE"),
            replace(topology, fingerprint="0" * 64),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ContinuousEvidenceWriterError):
                    validate_continuous_writer_topology_v2(changed)


class DedicatedEvidenceWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = WriterFixture(Path(self.temporary.name).resolve())

    def tearDown(self) -> None:
        self.fixture.close()
        self.temporary.cleanup()

    def test_accept_duplicate_and_validated_reader_snapshot(self) -> None:
        intent = self.fixture.intent()
        self.assertEqual(WRITER_ACCEPTED, self.fixture.client.write_intent(intent))
        self.assertEqual(WRITER_DUPLICATE, self.fixture.client.write_intent(intent))
        for role in (PYTHON_ENGINE_HOST, WPF_WORKSTATION, OFFLINE_REVIEW):
            snapshot = read_evidence_snapshot(self.fixture.topology, reader_role=role)
            self.assertEqual(1, snapshot.record_count)
            self.assertEqual(intent.intent_id, snapshot.records[0].intent_id)
        records = list((self.fixture.root / self.fixture.topology.namespace / "records").rglob("*.json"))
        self.assertEqual(1, len(records))

    def test_conflicting_duplicate_record_identity_fails_closed(self) -> None:
        first = self.fixture.intent(record_identity="same")
        second = self.fixture.intent(
            sequence=2,
            record_identity="same",
            record_fingerprint=fp("different"),
            predecessor_identity=first.intent_id,
        )
        self.assertEqual(WRITER_ACCEPTED, self.fixture.client.write_intent(first))
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "Conflicting duplicate"):
            self.fixture.client.write_intent(second)

    def test_invalid_capability_and_wrong_runtime_identity_are_rejected(self) -> None:
        wrong_capability = EphemeralWriterCapability(
            session_id=self.fixture.capability.session_id,
            key_material=b"x" * 32,
        )
        try:
            wrong_sender = self.fixture.envelope_sender(capability=wrong_capability)
            envelope = self.fixture.envelope(wrong_sender, self.fixture.intent())
            with self.assertRaisesRegex(WriterIpcError, "authentication"):
                self.fixture.writer.accept(envelope)
        finally:
            wrong_capability.close()

        wrong_sender = self.fixture.envelope_sender(source_identity="other-runtime")
        envelope = self.fixture.envelope(wrong_sender, self.fixture.intent())
        with self.assertRaisesRegex(WriterIpcError, "source identity"):
            self.fixture.writer.accept(envelope)

    def test_stale_capability_is_rejected_after_runtime_session_restart(self) -> None:
        old_sender = self.fixture.envelope_sender()
        old_envelope = self.fixture.envelope(old_sender, self.fixture.intent())
        new_capability = EphemeralWriterCapability.create()
        try:
            self.fixture.writer.activate_session(
                capability=new_capability,
                source_identity=RUNTIME_2,
                replay_runtime_instance_ids=(RUNTIME_1,),
            )
            with self.assertRaisesRegex(WriterIpcError, "different writer session"):
                self.fixture.writer.accept(old_envelope)
        finally:
            new_capability.close()

    def test_conflicting_sequence_gap_and_predecessor_mismatch_are_rejected(self) -> None:
        sender = self.fixture.envelope_sender()
        first_intent = self.fixture.intent()
        first = self.fixture.envelope(sender, first_intent)
        self.fixture.writer.accept(first)

        conflict_sender = self.fixture.envelope_sender()
        conflict = self.fixture.envelope(
            conflict_sender,
            self.fixture.intent(record_identity="conflict", record_fingerprint=fp("conflict")),
        )
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "Conflicting duplicate envelope"):
            self.fixture.writer.accept(conflict)

        gap_sender = self.fixture.envelope_sender()
        self.fixture.envelope(gap_sender, first_intent)
        second_intent = self.fixture.intent(sequence=2, predecessor_identity=first_intent.intent_id)
        gap_sender.build(
            artifact_name="event-decision-cycle-ledger",
            payload={"intent": asdict(second_intent), "topologyFingerprint": self.fixture.topology.fingerprint},
        )
        third_intent = self.fixture.intent(sequence=3, predecessor_identity=second_intent.intent_id)
        gap = self.fixture.envelope(gap_sender, third_intent)
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "sequence gap"):
            self.fixture.writer.accept(gap)

        predecessor_sender = self.fixture.envelope_sender()
        self.fixture.envelope(predecessor_sender, self.fixture.intent(record_identity="ignored"))
        wrong_predecessor = self.fixture.envelope(
            predecessor_sender,
            self.fixture.intent(
                sequence=2,
                record_identity="second",
                predecessor_identity=first_intent.intent_id,
            ),
        )
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "predecessor"):
            self.fixture.writer.accept(wrong_predecessor)

    def test_authenticated_envelope_cannot_hide_intent_gap_or_bad_predecessor(self) -> None:
        gap_sender = self.fixture.envelope_sender()
        gapped_intent = self.fixture.intent(sequence=2)
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "intent sequence"):
            self.fixture.writer.accept(self.fixture.envelope(gap_sender, gapped_intent))

        first_sender = self.fixture.envelope_sender()
        first_intent = self.fixture.intent()
        self.fixture.writer.accept(self.fixture.envelope(first_sender, first_intent))
        second_intent = self.fixture.intent(
            sequence=2,
            predecessor_identity="continuous-intent-wrong",
        )
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "intent predecessor"):
            self.fixture.writer.accept(self.fixture.envelope(first_sender, second_intent))

    def test_tampered_intent_payload_record_and_topology_fingerprints_are_rejected(self) -> None:
        cases = (
            replace(self.fixture.intent(), payload_fingerprint=fp("tampered-payload")),
            replace(self.fixture.intent(), record_fingerprint=fp("tampered-record")),
        )
        for index, intent in enumerate(cases):
            with self.subTest(index=index):
                sender = self.fixture.envelope_sender()
                envelope = self.fixture.envelope(sender, intent)
                with self.assertRaisesRegex(ContinuousEvidenceWriterError, "intent payload"):
                    self.fixture.writer.accept(envelope)

        sender = self.fixture.envelope_sender()
        envelope = sender.build(
            artifact_name="event-decision-cycle-ledger",
            payload={
                "intent": asdict(self.fixture.intent()),
                "topologyFingerprint": "0" * 64,
            },
        )
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "topology fingerprint"):
            self.fixture.writer.accept(envelope)

    def test_unsupported_protocol_oversized_payload_and_wrong_artifact_are_rejected(self) -> None:
        sender = self.fixture.envelope_sender()
        envelope = self.fixture.envelope(sender, self.fixture.intent())
        with self.assertRaisesRegex(WriterIpcError, "protocol"):
            self.fixture.writer.accept(replace(envelope, protocol="unsupported"))

        oversized_sender = self.fixture.envelope_sender()
        with self.assertRaisesRegex(WriterIpcError, "bounded frame"):
            oversized_sender.build(
                artifact_name="event-decision-cycle-ledger",
                payload={"payload": "x" * (MAX_PAYLOAD_BYTES + 1)},
            )

        wrong_sender = self.fixture.envelope_sender()
        wrong = self.fixture.envelope(
            wrong_sender,
            self.fixture.intent(),
            artifact="candidate-lifecycle-ledger",
        )
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "maps to another artifact"):
            self.fixture.writer.accept(wrong)

    def test_arbitrary_path_fields_are_rejected_even_though_writer_derives_paths(self) -> None:
        sender = self.fixture.envelope_sender()
        envelope = self.fixture.envelope(
            sender,
            self.fixture.intent(),
            extra={"outputPath": "C:\\Windows\\System32\\escape.json"},
        )
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "payload fields"):
            self.fixture.writer.accept(envelope)

    def test_on_disk_tampering_is_detected_by_reader(self) -> None:
        intent = self.fixture.intent()
        self.assertEqual(WRITER_ACCEPTED, self.fixture.client.write_intent(intent))
        path = next((self.fixture.root / self.fixture.topology.namespace / "records").rglob("*.json"))
        document = json.loads(path.read_text(encoding="ascii"))
        document["intent"]["record_identity"] = "tampered"
        path.write_bytes(
            (
                json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
                + "\n"
            ).encode("ascii")
        )
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "malformed|changed"):
            self.fixture.client.write_intent(intent)
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "malformed|fingerprint"):
            read_evidence_snapshot(self.fixture.topology, reader_role=OFFLINE_REVIEW)

    def test_duplicate_writer_logical_collision_fails_closed(self) -> None:
        with self.assertRaisesRegex(ContinuousEvidenceWriterError, "already owns"):
            DedicatedEvidenceWriter(self.fixture.topology)

    def test_writer_unavailable_is_explicit_and_retry_is_lossless(self) -> None:
        intent = self.fixture.intent()
        self.fixture.client.set_writer(None)
        self.assertEqual(WRITER_UNAVAILABLE, self.fixture.client.write_intent(intent))
        self.assertEqual(0, read_evidence_snapshot(self.fixture.topology, reader_role=OFFLINE_REVIEW).record_count)
        self.fixture.client.set_writer(self.fixture.writer)
        self.assertEqual(WRITER_ACCEPTED, self.fixture.client.write_intent(intent))

    def test_continuous_runtime_flushes_real_intents_through_dedicated_writer(self) -> None:
        runtime_fixture = RuntimeFixture(self.fixture.root / "runtime-integration")
        topology = build_continuous_writer_topology_v2(
            root_path=self.fixture.root / "runtime-writer",
            evidence_program_id="runtime-integration",
            configuration_fingerprint=runtime_fixture.config.fingerprint,
            runtime_build_hash=RUNTIME_BUILD,
        )
        capability = EphemeralWriterCapability.create()
        writer = DedicatedEvidenceWriter(topology)
        try:
            writer.activate_session(
                capability=capability,
                source_identity="runtime-instance-1",
            )
            client = AuthenticatedEvidenceWriterClient(
                topology=topology,
                capability=capability,
                runtime_instance_id="runtime-instance-1",
                writer=writer,
            )
            runtime_fixture.writer = client
            runtime_fixture.runtime = runtime_fixture.new_runtime("runtime-instance-1")
            runtime_fixture.runtime.start(runtime_fixture.clock.now())
            runtime_fixture.runtime.tick(runtime_fixture.clock.now(), work_budget=10_000)
            snapshot = read_evidence_snapshot(topology, reader_role=OFFLINE_REVIEW)
            self.assertGreater(snapshot.record_count, 0)
            self.assertEqual(
                len(runtime_fixture.runtime.evidence_intents),
                snapshot.record_count,
            )
            self.assertEqual(0, runtime_fixture.runtime.pending_work)
        finally:
            writer.close()
            capability.close()

    def test_slow_ack_is_explicit_and_exact_retry_does_not_duplicate(self) -> None:
        intent = self.fixture.intent()
        self.fixture.writer.response_delay_seconds = 0.02
        self.fixture.client.maximum_ack_seconds = 0.001
        self.assertEqual(WRITER_SLOW, self.fixture.client.write_intent(intent))
        self.fixture.writer.response_delay_seconds = 0
        self.fixture.client.maximum_ack_seconds = 1
        self.assertEqual(WRITER_ACCEPTED, self.fixture.client.write_intent(intent))
        snapshot = read_evidence_snapshot(self.fixture.topology, reader_role=OFFLINE_REVIEW)
        self.assertEqual(1, snapshot.record_count)

    def test_crash_before_commit_retries_as_first_accept(self) -> None:
        intent = self.fixture.intent()
        self.fixture.writer.arm_crash(CRASH_BEFORE_COMMIT)
        self.assertEqual(WRITER_UNAVAILABLE, self.fixture.client.write_intent(intent))
        self.assertEqual(WRITER_ACCEPTED, self.fixture.client.write_intent(intent))

    def test_crash_after_temp_is_quarantined_and_retry_commits_once(self) -> None:
        intent = self.fixture.intent()
        self.fixture.writer.arm_crash(CRASH_AFTER_TEMP)
        self.assertEqual(WRITER_UNAVAILABLE, self.fixture.client.write_intent(intent))
        partial_root = self.fixture.root / self.fixture.topology.namespace / ".partial"
        self.assertEqual(1, len(list(partial_root.glob("*.tmp"))))
        self._restart_writer_same_session()
        quarantine = self.fixture.root / self.fixture.topology.namespace / ".quarantine"
        self.assertEqual(1, len(list(quarantine.glob("*.tmp"))))
        self.assertEqual(WRITER_ACCEPTED, self.fixture.client.write_intent(intent))

    def test_crash_after_record_commit_replays_as_duplicate(self) -> None:
        intent = self.fixture.intent()
        self.fixture.writer.arm_crash(CRASH_AFTER_COMMIT_BEFORE_ACK)
        self.assertEqual(WRITER_UNAVAILABLE, self.fixture.client.write_intent(intent))
        self._restart_writer_same_session()
        self.assertEqual(WRITER_DUPLICATE, self.fixture.client.write_intent(intent))
        self.assertEqual(1, read_evidence_snapshot(self.fixture.topology, reader_role=OFFLINE_REVIEW).record_count)

    def test_crash_after_ack_commit_replays_same_ack_without_duplicate(self) -> None:
        intent = self.fixture.intent()
        self.fixture.writer.arm_crash(CRASH_AFTER_ACK_BEFORE_RETURN)
        self.assertEqual(WRITER_UNAVAILABLE, self.fixture.client.write_intent(intent))
        self._restart_writer_same_session()
        self.assertEqual(WRITER_ACCEPTED, self.fixture.client.write_intent(intent))
        self.assertEqual(1, read_evidence_snapshot(self.fixture.topology, reader_role=OFFLINE_REVIEW).record_count)

    def test_writer_restart_restores_order_and_exact_old_replay(self) -> None:
        sender = self.fixture.envelope_sender()
        first_intent = self.fixture.intent()
        first_envelope = self.fixture.envelope(sender, first_intent)
        first_ack = self.fixture.writer.accept(first_envelope)
        self._restart_writer_same_session()
        self.assertEqual(first_ack, self.fixture.writer.accept(first_envelope))
        second_intent = self.fixture.intent(sequence=2, predecessor_identity=first_intent.intent_id)
        second_envelope = self.fixture.envelope(sender, second_intent)
        self.assertEqual(WRITER_ACCEPTED, self.fixture.writer.accept(second_envelope).status)

    def test_runtime_restart_new_capability_can_replay_one_uncertain_old_intent(self) -> None:
        old_intent = self.fixture.intent(runtime_id=RUNTIME_1)
        self.fixture.writer.arm_crash(CRASH_AFTER_COMMIT_BEFORE_ACK)
        self.assertEqual(WRITER_UNAVAILABLE, self.fixture.client.write_intent(old_intent))
        old_pending = self.fixture.client._pending_envelope
        self.fixture.writer.close()

        new_capability = EphemeralWriterCapability.create()
        new_writer = DedicatedEvidenceWriter(self.fixture.topology)
        try:
            new_writer.activate_session(
                capability=new_capability,
                source_identity=RUNTIME_2,
                replay_runtime_instance_ids=(RUNTIME_1,),
            )
            new_client = AuthenticatedEvidenceWriterClient(
                topology=self.fixture.topology,
                capability=new_capability,
                runtime_instance_id=RUNTIME_2,
                replay_runtime_instance_ids=(RUNTIME_1,),
                writer=new_writer,
            )
            self.assertEqual(WRITER_DUPLICATE, new_client.write_intent(old_intent))
            self.assertEqual(1, read_evidence_snapshot(self.fixture.topology, reader_role=OFFLINE_REVIEW).record_count)
            with self.assertRaisesRegex(WriterIpcError, "different writer session"):
                new_writer.accept(old_pending)
        finally:
            new_writer.close()
            new_capability.close()
        self.fixture.writer = new_writer

    def test_provider_broker_and_order_modules_are_not_writer_dependencies(self) -> None:
        source_path = Path(__file__).parents[1] / "momentum_hunter" / "continuous_evidence_writer.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = ("schwab", "alpaca", "broker", "requests", "urllib", "httpx", "finviz")
        self.assertFalse(any(any(part in module.lower() for part in forbidden) for module in imported))

    def _restart_writer_same_session(self) -> None:
        self.fixture.writer.close()
        self.fixture.writer = DedicatedEvidenceWriter(self.fixture.topology)
        self.fixture.writer.activate_session(
            capability=self.fixture.capability,
            source_identity=self.fixture.runtime_id,
        )
        self.fixture.client.set_writer(self.fixture.writer)


class DedicatedEvidenceWriterScaleTests(unittest.TestCase):
    def test_full_session_uses_bounded_sharded_records_without_growing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WriterFixture(Path(temporary).resolve())
            try:
                predecessor = None
                started = time.perf_counter()
                count = 4300
                for sequence in range(1, count + 1):
                    intent = fixture.intent(
                        sequence=sequence,
                        evidence_type=(
                            "COMPOSITION_CYCLE"
                            if sequence % 2
                            else "OPPORTUNITY_DENOMINATOR"
                        ),
                        predecessor_identity=predecessor,
                    )
                    self.assertEqual(WRITER_ACCEPTED, fixture.client.write_intent(intent))
                    predecessor = intent.intent_id
                elapsed = time.perf_counter() - started
                snapshot = read_evidence_snapshot(fixture.topology, reader_role=OFFLINE_REVIEW)
                self.assertEqual(count, snapshot.record_count)
                records_root = fixture.root / fixture.topology.namespace / "records"
                record_files = list(records_root.rglob("*.json"))
                self.assertEqual(count, len(record_files))
                self.assertGreater(len({path.parent.name for path in record_files}), 32)
                self.assertLess(max(path.stat().st_size for path in record_files), 8_192)
                self.assertFalse((fixture.root / fixture.topology.namespace / "ledger.json").exists())
                self.assertLess(elapsed, 180.0)
            finally:
                fixture.close()


if __name__ == "__main__":
    unittest.main()
