from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.continuous_research_export import producer_identity, time_evidence
from momentum_hunter.strategy_science_recorder import (
    StrategyScienceRecorder,
    canonical_json_v1,
    parse_export_envelope_v2,
    sha256_hex,
)
from momentum_hunter.strategy_science_source_reader import (
    SimulatedSourceReaderCrash,
    SourceReaderCursorError,
    SourceReaderError,
    SourceReaderPublicationError,
    StrategyScienceSourceReaderV2,
)
from tests.test_continuous_research_export_v2 import (
    DECISION_CUTOFF,
    FINAL_TIME,
    OWNER,
    SESSION,
    SETUP,
    SOURCE_ROOT,
    FixedClock,
    absent,
    decision_payload,
    exporter,
    health_payload,
    market_payload,
    observation,
    observation_receipt_hash,
    publish_decision,
    publish_discovery,
    publish_start,
    stored_records,
    unresolved_instrument,
    OBSERVATION_2,
)
from tests.test_strategy_science_recorder_contract import start_envelope


RECEIPT_T1 = "2026-09-02T22:00:00Z"
RECEIPT_T2 = "2026-09-02T22:00:01Z"


class InterruptingCursorWrite:
    def __init__(self, handle, evidence: dict[str, object]) -> None:
        self.handle = handle
        self.evidence = evidence

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.handle.close()
        return False

    def write(self, raw: bytes) -> int:
        written = max(1, len(raw) // 2)
        self.evidence["attempted"] = len(raw)
        self.evidence["written"] = written
        self.handle.write(raw[:written])
        self.handle.flush()
        raise OSError("synthetic interruption during partial cursor write")

    def __getattr__(self, name: str):
        return getattr(self.handle, name)


def publication_files(root: Path) -> tuple[Path, ...]:
    return tuple(sorted((root / "published").glob("*.json")))


def no_plan_payload() -> dict[str, object]:
    payload = decision_payload()
    payload.pop("reference_plan")
    decision = payload["decision_event"]
    assert isinstance(decision, dict)
    decision["decision_id"] = producer_identity(
        "DECISION_ID", OWNER, "decision-no-plan"
    )
    decision["observation_id"] = OBSERVATION_2
    decision["candidate_or_setup_identity"] = SETUP
    decision["decision_state"] = "NO_PLAN"
    decision["decision_time"] = time_evidence(
        "DECISION_TIME", "2026-09-02T13:32:02Z", OWNER
    )
    decision["decision_cutoff"] = time_evidence(
        "DECISION_CUTOFF", DECISION_CUTOFF, OWNER
    )
    decision["reason_codes"] = [{"code": "NO_PLAN", "version": "1"}]
    decision["tradeplan_id"] = absent(reason="NO_TRADEPLAN")
    decision["reference_plan_id"] = absent(reason="NO_REFERENCE_PLAN")
    return payload


def publish_complete(root: Path, *, unresolved: bool = False) -> tuple[bytes, ...]:
    with exporter(root) as writer:
        publish_start(writer)
        rows = [
            observation(
                instrument=unresolved_instrument() if unresolved else None
            ),
            observation(OBSERVATION_2, ordinal=1),
        ]
        publish_discovery(writer, rows=rows)
        publish_decision(writer)
        writer.publish_event(
            "DECISION_FACT",
            no_plan_payload(),
            stream_id="decision",
            source_event_id="decision-no-plan",
            emitted_at="2026-09-02T13:32:02Z",
        )
        writer.publish_event(
            "MARKET_FACT",
            market_payload(),
            stream_id="market",
            source_event_id="market-1",
            emitted_at="2026-09-02T13:33:00Z",
        )
        writer.publish_event(
            "PROVIDER_HEALTH",
            health_payload(),
            stream_id="health",
            source_event_id="health-1",
            emitted_at="2026-09-02T13:33:00Z",
        )
        writer.finalize(
            stream_id="session",
            source_event_id="session-final",
            closed_at=FINAL_TIME,
            close_reason="OFFLINE_SOURCE_READER_QUALIFICATION_COMPLETE",
            terminal_proven=True,
        )
        return tuple(item.raw_bytes for item in writer.published())


def mutate_envelope(raw: bytes, change: object) -> bytes:
    value = json.loads(raw)
    change(value)
    if "payload" in value:
        value["payload_sha256"] = sha256_hex(canonical_json_v1(value["payload"]))
    return canonical_json_v1(value)


class StrategyScienceSourceReaderV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def recorder(
        self, name: str = "science", *, clock: str = RECEIPT_T1
    ) -> StrategyScienceRecorder:
        return StrategyScienceRecorder(
            self.root / name,
            source_root_identity=SOURCE_ROOT,
            writer_instance_id=f"reader-test-{name}",
            clock=FixedClock(clock),
        )

    def reader(
        self,
        recorder: StrategyScienceRecorder,
        producer_root: Path,
        *,
        state: str = "reader-state",
    ) -> StrategyScienceSourceReaderV2:
        return StrategyScienceSourceReaderV2(
            producer_root / "published",
            self.root / state,
            recorder=recorder,
        )

    def test_direct_complete_export_accepts_start_events_tradeplan_no_plan_and_final(self) -> None:
        producer = self.root / "producer"
        raw_before = publish_complete(producer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                result = reader.consume_available()
            self.assertEqual("TERMINAL_FINAL_ADMITTED", result.status)
            self.assertTrue(result.cursor.terminal)
            self.assertEqual(len(raw_before), len(result.admissions))
            self.assertTrue(all(row.custody.status == "ACCEPTED" for row in result.admissions))
            self.assertEqual(2, len(stored_records(self.root / "science", "decision-event")))
            self.assertEqual(1, len(stored_records(self.root / "science", "reference-plan")))
            self.assertTrue(recorder.verify(SESSION).all_hashes_valid)
        finally:
            recorder.close()

    def test_exact_source_bytes_and_provenance_survive_custody(self) -> None:
        producer = self.root / "producer"
        raw_before = publish_complete(producer)
        producer_hashes = [sha256_hex(raw) for raw in raw_before]
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available()
            custody_hashes = sorted(
                sha256_hex(path.read_bytes())
                for path in (self.root / "science").rglob("*.source.json")
            )
            self.assertEqual(sorted(producer_hashes), custody_hashes)
            cursor_rows = [
                json.loads(path.read_bytes())
                for path in sorted((self.root / "reader-state" / "cursors").glob("*.json"))
            ]
            self.assertEqual(producer_hashes, [row["source_envelope_sha256"] for row in cursor_rows])
            self.assertTrue(all(row["source_owner_identity"] == OWNER for row in cursor_rows))
            self.assertTrue(all(row["source_contract"] == "ResearchExportEnvelopeV2" for row in cursor_rows))
            self.assertTrue(all("source_publication_identity_sha256" in row for row in cursor_rows))
            self.assertEqual(raw_before, tuple(path.read_bytes() for path in publication_files(producer)))
        finally:
            recorder.close()

    def test_producer_known_at_and_science_receipt_are_separate(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            discovery = publish_discovery(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available()
            cursor = json.loads(
                sorted((self.root / "reader-state" / "cursors").glob("*.json"))[1].read_bytes()
            )
            parsed = parse_export_envelope_v2(discovery.raw_bytes)
            self.assertEqual(parsed.effective_known_at, cursor["source_effective_known_at"])
            self.assertNotIn("science_receipt_time", cursor)
            observation_record = stored_records(
                self.root / "science", "candidate-observation"
            )[0][1]
            self.assertEqual(RECEIPT_T1, observation_record["recorder_capture_time"]["normalized_rfc3339"])
            self.assertNotEqual(parsed.effective_known_at, RECEIPT_T1)
        finally:
            recorder.close()

    def test_missing_start_fails_before_custody_or_cursor(self) -> None:
        source = self.root / "source"
        with exporter(source) as writer:
            publish_start(writer)
            publish_discovery(writer)
        malicious = self.root / "malicious" / "published"
        malicious.mkdir(parents=True)
        discovery = publication_files(source)[1]
        target = malicious / discovery.name.replace("00000000000000000002-", "00000000000000000001-")
        target.write_bytes(discovery.read_bytes())
        recorder = self.recorder()
        try:
            with StrategyScienceSourceReaderV2(
                malicious, self.root / "reader-state", recorder=recorder
            ) as reader:
                with self.assertRaises(SourceReaderError):
                    reader.consume_available()
            self.assertEqual([], list((self.root / "science").rglob("*.source.json")))
            self.assertEqual([], list((self.root / "reader-state" / "cursors").glob("*.json")))
        finally:
            recorder.close()

    def test_before_start_read_with_no_publication_remains_incomplete_at_zero(self) -> None:
        producer = self.root / "producer"
        with exporter(producer):
            pass
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                result = reader.consume_available()
            self.assertEqual("INCOMPLETE_AWAITING_PUBLICATION", result.status)
            self.assertEqual(0, result.cursor.last_publication_ordinal)
            self.assertIsNone(result.cursor.session_id)
        finally:
            recorder.close()

    def test_malformed_or_noncanonical_envelope_is_rejected(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        publication_files(producer)[0].write_bytes(b"{}")
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                with self.assertRaises(SourceReaderPublicationError):
                    reader.consume_available()
        finally:
            recorder.close()

    def test_acknowledged_source_hash_change_fails_closed(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available()
            path = publication_files(producer)[0]
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaises((SourceReaderCursorError, SourceReaderPublicationError)):
                self.reader(recorder, producer)
        finally:
            recorder.close()

    def test_valid_conflicting_replacement_of_acknowledged_event_fails_closed(self) -> None:
        producer = self.root / "producer"
        replacement = self.root / "replacement"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
        with exporter(replacement) as writer:
            publish_start(writer)
            changed = observation()
            changed["candidate_facts"]["price"] = {
                "authority": OWNER,
                "reason_code": "PRESENT",
                "state": "PRESENT",
                "value": "99.99",
            }
            publish_discovery(writer, rows=[changed])
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available()
            accepted = publication_files(producer)[1]
            conflicting = publication_files(replacement)[1]
            self.assertNotEqual(accepted.read_bytes(), conflicting.read_bytes())
            accepted.write_bytes(conflicting.read_bytes())
            with self.assertRaises(SourceReaderCursorError):
                self.reader(recorder, producer)
        finally:
            recorder.close()

    def test_per_stream_sequence_gap_stops_before_custody(self) -> None:
        source = self.root / "source"
        with exporter(source) as writer:
            publish_start(writer)
            publish_discovery(writer)
            publish_discovery(writer, event_id="discovery-2")
        malicious = self.root / "malicious" / "published"
        malicious.mkdir(parents=True)
        files = publication_files(source)
        (malicious / files[0].name).write_bytes(files[0].read_bytes())
        gap = files[2]
        target = malicious / gap.name.replace("00000000000000000003-", "00000000000000000002-")
        target.write_bytes(gap.read_bytes())
        recorder = self.recorder()
        try:
            with StrategyScienceSourceReaderV2(
                malicious, self.root / "reader-state", recorder=recorder
            ) as reader:
                reader.consume_available(max_items=1)
                with self.assertRaises(SourceReaderError):
                    reader.consume_available()
                self.assertEqual(1, reader._load_state().last_publication_ordinal)
        finally:
            recorder.close()

    def test_previous_raw_hash_mismatch_stops_stream(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
        path = publication_files(producer)[1]
        path.write_bytes(
            mutate_envelope(
                path.read_bytes(),
                lambda value: value.__setitem__("previous_record_sha256", "f" * 64),
            )
        )
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available(max_items=1)
                with self.assertRaises(SourceReaderError):
                    reader.consume_available()
        finally:
            recorder.close()

    def test_duplicate_replay_is_idempotent_and_does_not_double_eligibility(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                first = reader.consume_available()
            with self.reader(recorder, producer) as restarted:
                second = restarted.consume_available()
            self.assertEqual(2, len(first.admissions))
            self.assertEqual(0, len(second.admissions))
            self.assertEqual(1, len(stored_records(self.root / "science", "science-eligibility")))
        finally:
            recorder.close()

    def test_crash_after_custody_before_cursor_replays_to_one_identity(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                with self.assertRaises(SimulatedSourceReaderCrash):
                    reader.consume_available(crash_phase="after_custody_before_cursor")
            self.assertEqual(1, len(list((self.root / "science").rglob("*.source.json"))))
            self.assertEqual(0, len(list((self.root / "reader-state" / "cursors").glob("*.json"))))
            with self.reader(recorder, producer) as restarted:
                result = restarted.consume_available()
            self.assertEqual("IDEMPOTENT_ACK", result.admissions[0].custody.status)
            self.assertEqual(1, result.cursor.last_publication_ordinal)
            self.assertEqual(1, len(list((self.root / "science").rglob("*.source.json"))))
        finally:
            recorder.close()

    def test_mid_write_interruption_before_first_cursor_leaves_no_authoritative_cursor_and_replays(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        recorder = self.recorder()
        original_open = Path.open
        evidence: dict[str, object] = {}

        def interrupt_temp(path: Path, mode="r", *args, **kwargs):
            handle = original_open(path, mode, *args, **kwargs)
            if mode == "xb" and path.parent.name == ".partial":
                return InterruptingCursorWrite(handle, evidence)
            return handle

        try:
            with self.reader(recorder, producer) as reader:
                with patch.object(Path, "open", interrupt_temp):
                    with self.assertRaisesRegex(OSError, "partial cursor write"):
                        reader.consume_available()
            self.assertGreater(int(evidence["written"]), 0)
            self.assertLess(int(evidence["written"]), int(evidence["attempted"]))
            self.assertEqual(
                [], list((self.root / "reader-state" / "cursors").glob("*.json"))
            )
            self.assertEqual(1, len(list((self.root / "science").rglob("*.source.json"))))
            with self.reader(recorder, producer) as restarted:
                result = restarted.consume_available()
            self.assertEqual("IDEMPOTENT_ACK", result.admissions[0].custody.status)
            self.assertEqual(1, result.cursor.last_publication_ordinal)
            self.assertEqual(1, len(list((self.root / "science").rglob("*.source.json"))))
        finally:
            recorder.close()

    def test_mid_write_interruption_preserves_existing_cursor_and_idempotent_replay(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
        recorder = self.recorder()
        original_open = Path.open
        evidence: dict[str, object] = {}

        def interrupt_temp(path: Path, mode="r", *args, **kwargs):
            handle = original_open(path, mode, *args, **kwargs)
            if mode == "xb" and path.parent.name == ".partial":
                return InterruptingCursorWrite(handle, evidence)
            return handle

        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available(max_items=1)
                existing = next((self.root / "reader-state" / "cursors").glob("*.json"))
                existing_bytes = existing.read_bytes()
                with patch.object(Path, "open", interrupt_temp):
                    with self.assertRaisesRegex(OSError, "partial cursor write"):
                        reader.consume_available(max_items=1)
            self.assertGreater(int(evidence["written"]), 0)
            self.assertLess(int(evidence["written"]), int(evidence["attempted"]))
            self.assertEqual(existing_bytes, existing.read_bytes())
            self.assertEqual(
                [existing],
                list((self.root / "reader-state" / "cursors").glob("*.json")),
            )
            self.assertEqual(2, len(list((self.root / "science").rglob("*.source.json"))))
            with self.reader(recorder, producer) as restarted:
                result = restarted.consume_available()
            self.assertEqual("IDEMPOTENT_ACK", result.admissions[0].custody.status)
            self.assertEqual(2, result.cursor.last_publication_ordinal)
            self.assertEqual(2, len(list((self.root / "science").rglob("*.source.json"))))
        finally:
            recorder.close()

    def test_atomic_install_failure_preserves_existing_cursor_and_restart(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available(max_items=1)
                existing = next((self.root / "reader-state" / "cursors").glob("*.json"))
                existing_bytes = existing.read_bytes()
                with patch(
                    "momentum_hunter.strategy_science_source_reader.os.link",
                    side_effect=OSError("synthetic atomic install failure"),
                ):
                    with self.assertRaisesRegex(OSError, "atomic install failure"):
                        reader.consume_available(max_items=1)
            self.assertEqual(existing_bytes, existing.read_bytes())
            self.assertEqual(
                [existing],
                list((self.root / "reader-state" / "cursors").glob("*.json")),
            )
            with self.reader(recorder, producer) as restarted:
                result = restarted.consume_available()
            self.assertEqual("IDEMPOTENT_ACK", result.admissions[0].custody.status)
            self.assertEqual(2, result.cursor.last_publication_ordinal)
            self.assertEqual(2, len(list((self.root / "science").rglob("*.source.json"))))
        finally:
            recorder.close()

    def test_successful_atomic_install_publishes_exact_cursor_bytes(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        recorder = self.recorder()
        links: list[tuple[Path, Path]] = []
        original_link = os.link

        def record_link(source, target, *args, **kwargs):
            links.append((Path(source), Path(target)))
            return original_link(source, target, *args, **kwargs)

        try:
            with patch(
                "momentum_hunter.strategy_science_source_reader.os.link",
                side_effect=record_link,
            ):
                with self.reader(recorder, producer) as reader:
                    result = reader.consume_available()
            self.assertEqual(1, len(links))
            temporary, authoritative = links[0]
            self.assertEqual(".partial", temporary.parent.name)
            self.assertEqual(authoritative.parent, temporary.parent.parent)
            self.assertFalse(temporary.exists())
            raw = authoritative.read_bytes()
            self.assertEqual(result.admissions[0].cursor_sha256, sha256_hex(raw))
            self.assertIn(result.admissions[0].cursor_sha256, authoritative.name)
            with self.reader(recorder, producer) as restarted:
                self.assertEqual(1, restarted._load_state().last_publication_ordinal)
        finally:
            recorder.close()

    def test_stale_partial_cursor_file_is_not_authority(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        partial_root = self.root / "reader-state" / "cursors" / ".partial"
        partial_root.mkdir(parents=True)
        stale = partial_root / "stale.reader-cursor.tmp"
        stale.write_bytes(b"truncated non-authoritative cursor bytes")
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                result = reader.consume_available()
            self.assertEqual(1, result.cursor.last_publication_ordinal)
            self.assertTrue(stale.is_file())
            self.assertEqual(
                1,
                len(list((self.root / "reader-state" / "cursors").glob("*.json"))),
            )
        finally:
            recorder.close()

    def test_crash_after_read_before_custody_does_not_advance_any_cursor(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                with self.assertRaises(SimulatedSourceReaderCrash):
                    reader.consume_available(crash_phase="after_read_before_custody")
            self.assertEqual([], list((self.root / "science").rglob("*.source.json")))
            self.assertEqual([], list((self.root / "reader-state" / "cursors").glob("*.json")))
        finally:
            recorder.close()

    def test_ordinary_event_crashes_on_both_sides_of_custody_are_restart_safe(self) -> None:
        for case, phase in enumerate(
            ("after_read_before_custody", "after_custody_before_cursor"), start=1
        ):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                producer = root / "producer"
                with exporter(producer) as writer:
                    publish_start(writer)
                    publish_discovery(writer)
                recorder = StrategyScienceRecorder(
                    root / "science",
                    source_root_identity=SOURCE_ROOT,
                    writer_instance_id=f"ordinary-crash-{case}",
                    clock=FixedClock(RECEIPT_T1),
                )
                try:
                    with StrategyScienceSourceReaderV2(
                        producer / "published",
                        root / "reader-state",
                        recorder=recorder,
                    ) as reader:
                        reader.consume_available(max_items=1)
                        with self.assertRaises(SimulatedSourceReaderCrash):
                            reader.consume_available(crash_phase=phase)
                    with StrategyScienceSourceReaderV2(
                        producer / "published",
                        root / "reader-state",
                        recorder=recorder,
                    ) as restarted:
                        result = restarted.consume_available()
                    self.assertEqual(2, result.cursor.last_publication_ordinal)
                    self.assertEqual(
                        "IDEMPOTENT_ACK"
                        if phase == "after_custody_before_cursor"
                        else "ACCEPTED",
                        result.admissions[0].custody.status,
                    )
                    self.assertEqual(
                        1,
                        len(stored_records(root / "science", "science-eligibility")),
                    )
                finally:
                    recorder.close()

    def test_restart_between_sequential_events_continues_exactly_once(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
            publish_decision(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                first = reader.consume_available(max_items=2)
            with self.reader(recorder, producer) as restarted:
                second = restarted.consume_available()
            self.assertEqual([1, 2], [row.publication_ordinal for row in first.admissions])
            self.assertEqual([3], [row.publication_ordinal for row in second.admissions])
            self.assertEqual(3, second.cursor.last_publication_ordinal)
        finally:
            recorder.close()

    def test_crash_after_final_custody_restarts_to_terminal_cursor(self) -> None:
        producer = self.root / "producer"
        publish_complete(producer)
        count = len(publication_files(producer))
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available(max_items=count - 1)
                with self.assertRaises(SimulatedSourceReaderCrash):
                    reader.consume_available(crash_phase="after_custody_before_cursor")
            with self.reader(recorder, producer) as restarted:
                result = restarted.consume_available()
            self.assertTrue(result.cursor.terminal)
            self.assertEqual("IDEMPOTENT_ACK", result.admissions[0].custody.status)
        finally:
            recorder.close()

    def test_partial_temp_and_staging_bytes_are_never_admitted(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        (producer / "staging" / ("a" * 64 + ".json")).write_bytes(b"unpublished")
        (producer / "published" / ".partial.tmp").write_bytes(b"partial")
        recorder = self.recorder()
        try:
            with self.assertRaises(SourceReaderPublicationError):
                self.reader(recorder, producer)
            self.assertEqual([], list((self.root / "science").rglob("*.source.json")))
        finally:
            recorder.close()

    def test_filesystem_enumeration_order_does_not_change_delivery_order(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
            publish_decision(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reversed_entries = tuple(reversed(publication_files(producer)))
                with patch.object(reader, "_directory_entries", return_value=reversed_entries):
                    result = reader.consume_available()
            self.assertEqual([1, 2, 3], [row.publication_ordinal for row in result.admissions])
        finally:
            recorder.close()

    def test_global_publication_gap_never_jumps_to_later_object(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
            publish_decision(writer)
        publication_files(producer)[1].unlink()
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available(max_items=1)
                with self.assertRaises(SourceReaderPublicationError):
                    reader.consume_available()
            self.assertEqual(1, len(list((self.root / "reader-state" / "cursors").glob("*.json"))))
        finally:
            recorder.close()

    def test_unresolved_instrument_fields_remain_unknown(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(
                writer,
                rows=[observation(instrument=unresolved_instrument())],
            )
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available()
            instrument = stored_records(
                self.root / "science", "candidate-observation"
            )[0][1]["instrument_identity"]
            for field in ("asset_type", "venue_or_exchange", "authoritative_security_id"):
                self.assertEqual("UNKNOWN", instrument[field]["state"])
                self.assertNotIn("value", instrument[field])
        finally:
            recorder.close()

    def test_future_science_field_is_rejected_by_canonical_parser(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
            publish_decision(writer)
        decision_path = publication_files(producer)[2]

        def inject(value: dict[str, object]) -> None:
            value["payload"]["decision_event"]["science_receipt_hash"] = "f" * 64

        decision_path.write_bytes(mutate_envelope(decision_path.read_bytes(), inject))
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available(max_items=2)
                with self.assertRaises(SourceReaderPublicationError):
                    reader.consume_available()
        finally:
            recorder.close()

    def test_later_publication_does_not_rewrite_earlier_eligibility(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available()
            early = {
                path.relative_to(self.root / "science").as_posix(): path.read_bytes()
                for path in (self.root / "science").rglob("*")
                if path.is_file() and not path.name.startswith(".")
            }
            with exporter(producer) as writer:
                publish_decision(writer)
            with self.reader(recorder, producer) as restarted:
                restarted.consume_available()
            for relative, raw in early.items():
                self.assertEqual(raw, (self.root / "science" / relative).read_bytes())
        finally:
            recorder.close()

    def test_two_science_clocks_leave_identical_producer_bytes_and_distinct_receipts(self) -> None:
        producer = self.root / "producer"
        raw = publish_complete(producer)
        producer_hashes = tuple(sha256_hex(item) for item in raw)
        evidence: list[tuple[tuple[str, ...], str, str]] = []
        for ordinal, clock in enumerate((RECEIPT_T1, RECEIPT_T2), start=1):
            recorder = self.recorder(f"science-{ordinal}", clock=clock)
            try:
                with self.reader(
                    recorder, producer, state=f"reader-state-{ordinal}"
                ) as reader:
                    reader.consume_available()
                eligibility = stored_records(
                    self.root / f"science-{ordinal}", "science-eligibility"
                )[0][1]["science_eligibility"]["commitment_payload_sha256"]
                evidence.append(
                    (
                        producer_hashes,
                        observation_receipt_hash(self.root / f"science-{ordinal}"),
                        eligibility,
                    )
                )
            finally:
                recorder.close()
        self.assertEqual(evidence[0][0], evidence[1][0])
        self.assertNotEqual(evidence[0][1], evidence[1][1])
        self.assertNotEqual(evidence[0][2], evidence[1][2])
        self.assertEqual(raw, tuple(path.read_bytes() for path in publication_files(producer)))

    def test_final_is_validated_and_absent_final_stays_incomplete(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
            publish_discovery(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                result = reader.consume_available()
            self.assertEqual("INCOMPLETE_AWAITING_PUBLICATION", result.status)
            self.assertFalse(result.cursor.terminal)
        finally:
            recorder.close()

    def test_final_with_wrong_declared_head_fails_before_terminal_cursor(self) -> None:
        producer = self.root / "producer"
        publish_complete(producer)
        final_path = publication_files(producer)[-1]

        def corrupt(value: dict[str, object]) -> None:
            value["payload"]["source_stream_heads_before_final"][0][
                "last_source_envelope_sha256"
            ] = "f" * 64

        final_path.write_bytes(mutate_envelope(final_path.read_bytes(), corrupt))
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                reader.consume_available(max_items=len(publication_files(producer)) - 1)
                with self.assertRaises((SourceReaderError, SourceReaderPublicationError)):
                    reader.consume_available()
                self.assertFalse(reader._load_state().terminal)
        finally:
            recorder.close()

    def test_incomplete_final_disposition_is_preserved_not_upgraded(self) -> None:
        producer = self.root / "producer"
        publish_complete(producer)
        final_path = publication_files(producer)[-1]

        def mark_incomplete(value: dict[str, object]) -> None:
            value["payload"]["pending_source_events"] = 1
            value["payload"]["close_reason"] = "PENDING_SOURCE_EVIDENCE"

        final_path.write_bytes(
            mutate_envelope(final_path.read_bytes(), mark_incomplete)
        )
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                result = reader.consume_available()
            self.assertEqual(
                "TERMINAL_INCOMPLETE_FINAL_ADMITTED", result.status
            )
            self.assertEqual(
                "INCOMPLETE_SOURCE_FINAL", result.cursor.final_disposition
            )
            self.assertTrue(result.cursor.terminal)
        finally:
            recorder.close()

    def test_legacy_class_b_v1_bytes_are_not_upgraded(self) -> None:
        publication = self.root / "producer" / "published"
        publication.mkdir(parents=True)
        raw = start_envelope()
        stream_id = str(json.loads(raw)["stream_id"])
        token = sha256_hex(canonical_json_v1({"stream_id": stream_id}))[:16]
        (publication / f"{1:020d}-{token}-{1:020d}.json").write_bytes(raw)
        recorder = self.recorder()
        try:
            with self.assertRaises(SourceReaderPublicationError):
                with StrategyScienceSourceReaderV2(
                    publication, self.root / "reader-state", recorder=recorder
                ) as reader:
                    reader.consume_available()
            self.assertEqual([], list((self.root / "science").rglob("*.source.json")))
        finally:
            recorder.close()

    def test_filesystem_and_sealed_source_use_same_admit_ingress(self) -> None:
        producer = self.root / "producer"
        with exporter(producer) as writer:
            publish_start(writer)
        recorder = self.recorder()
        try:
            with self.reader(recorder, producer) as reader:
                with patch.object(reader, "admit", wraps=reader.admit) as ingress:
                    reader.consume_available()
                    self.assertEqual(1, ingress.call_count)
                    self.assertEqual(
                        publication_files(producer)[0].read_bytes(),
                        ingress.call_args.args[0],
                    )
        finally:
            recorder.close()

    def test_module_has_no_network_provider_service_scheduler_or_execution_import(self) -> None:
        source = Path("momentum_hunter/strategy_science_source_reader.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported = {
            node.names[0].name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertTrue(
            imported.isdisjoint(
                {
                    "requests",
                    "httpx",
                    "socket",
                    "schwab",
                    "finviz",
                    "broker",
                    "services",
                    "scheduler",
                }
            )
        )
        for prohibited in (
            "submit_order",
            "cancel_order",
            "paper_trade",
            "shadow_trade",
            "refresh_token",
            "provider_login",
        ):
            self.assertNotIn(prohibited, source.lower())


if __name__ == "__main__":
    unittest.main()
