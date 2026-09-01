from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.strategy_science_recorder import (
    RecorderConflictError,
    RecorderContractError,
    RecorderCustodyError,
    StrategyScienceRecorder,
    canonical_json_v1,
    owner_identity,
    sha256_hex,
)
from tests.test_strategy_science_recorder_contract import (
    CYCLE_ID,
    DECISION_ID,
    DECISION_SNAPSHOT_ID,
    HEALTH_ID,
    MARKET_SNAPSHOT_ID,
    OBSERVATION_ID,
    OBSERVATION_ID_2,
    REFERENCE_PLAN_ID,
    SESSION_ID,
    SOURCE_ROOT_IDENTITY,
    FixedClock,
    decision_payload,
    decision_snapshot_payload,
    discovery_payload,
    export_envelope,
    health_payload,
    market_bar_payload,
    observation,
    present,
    start_envelope,
    stored_records,
    time_evidence,
)


class RecorderCustodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "science"
        self.recorder = StrategyScienceRecorder(
            self.root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="custody-tests",
            clock=FixedClock(),
        )
        self.addCleanup(self.recorder.close)

    def start(self) -> bytes:
        raw = start_envelope()
        result = self.recorder.accept(raw)
        self.assertEqual("ACCEPTED", result.status)
        return raw

    def discovery(self, rows: list[dict[str, object]] | None = None) -> bytes:
        raw = export_envelope(
            "DISCOVERY_CYCLE",
            discovery_payload(rows),
            stream_id="discovery-stream",
            event_id="discovery-1",
        )
        self.recorder.accept(raw)
        return raw

    def test_exact_raw_source_and_opaque_provider_owner_identity_are_preserved(self) -> None:
        start_raw = self.start()
        discovery_raw = self.discovery()
        sources = [path.read_bytes() for path in self.root.rglob("*.source.json")]
        self.assertIn(start_raw, sources)
        self.assertIn(discovery_raw, sources)
        observations = stored_records(self.root, "candidate-observation")
        self.assertEqual(1, len(observations))
        record = observations[0][1]
        self.assertEqual("fixture-producing-owner", record["source_owner"])
        self.assertEqual("fixture-export-interface-v1", record["source_interface_identity"])
        self.assertEqual("ResearchExportEnvelopeV1", record["source_contract"])
        self.assertEqual("NONE", record["execution_authority"])

    def test_all_rows_preserved_and_batch_duplicate_instrument_shares_first_commitment(self) -> None:
        self.start()
        rows = [
            observation(),
            observation(OBSERVATION_ID_2, ordinal=1, symbol="AAA"),
        ]
        self.discovery(rows)
        cycles = stored_records(self.root, "discovery-cycle")
        observations = sorted(
            stored_records(self.root, "candidate-observation"),
            key=lambda item: item[1]["source_row_ordinal"],
        )
        self.assertEqual(1, len(cycles))
        self.assertEqual(2, len(observations))
        commitments = [item[1]["outcome_eligibility"] for item in observations]
        self.assertEqual(commitments[0], commitments[1])
        self.assertEqual(OBSERVATION_ID, commitments[0]["first_observation_id"])
        self.assertEqual("ELIGIBLE", commitments[0]["eligibility_state"])
        self.assertEqual(
            "2026-09-01T14:00:00Z",
            commitments[0]["committed_at"]["normalized_rfc3339"],
        )
        self.assertEqual(
            rows[0]["discovery_time"], commitments[0]["eligibility_basis_time"]
        )
        self.assertEqual(
            "SCIENCE_CUSTODY_OFFLINE_SOURCE_CHAIN_ASSERTION",
            commitments[0]["commitment_provenance"],
        )

    def test_decision_reference_market_and_health_families_are_create_only(self) -> None:
        self.start()
        self.discovery()
        observation_record = stored_records(self.root, "candidate-observation")[0][1]
        eligibility = observation_record["outcome_eligibility"]["commitment_payload_sha256"]
        decision_raw = export_envelope(
            "DECISION_FACT",
            decision_payload(eligibility),
            stream_id="decision-stream",
            event_id="decision-1",
        )
        self.recorder.accept(decision_raw)
        self.recorder.accept(
            export_envelope(
                "MARKET_FACT",
                market_bar_payload(),
                stream_id="market-stream",
                event_id="bar-1",
            )
        )
        self.recorder.accept(
            export_envelope(
                "PROVIDER_HEALTH",
                health_payload(),
                stream_id="health-stream",
                event_id="health-1",
            )
        )
        expected = {
            "decision-event": DECISION_ID,
            "reference-plan": REFERENCE_PLAN_ID,
            "market-snapshot": MARKET_SNAPSHOT_ID,
            "provider-health-event": HEALTH_ID,
        }
        for record_type, identity in expected.items():
            with self.subTest(record_type=record_type):
                records = stored_records(self.root, record_type)
                self.assertEqual(1, len(records))
                self.assertEqual(identity, records[0][1]["record_id"])
        before = stored_records(self.root, "decision-event")[0][2]
        replay = self.recorder.accept(decision_raw)
        self.assertEqual("IDEMPOTENT_ACK", replay.status)
        self.assertEqual(before, stored_records(self.root, "decision-event")[0][2])

    def test_exact_replay_is_noop_and_conflicting_duplicate_freezes_stream(self) -> None:
        raw = self.start()
        self.assertEqual("IDEMPOTENT_ACK", self.recorder.accept(raw).status)
        changed = json.loads(raw)
        payload = copy.deepcopy(changed["payload"])
        payload["market_timezone"] = "Etc/UTC"
        changed["payload"] = payload
        changed["payload_sha256"] = sha256_hex(canonical_json_v1(payload))
        conflicting = canonical_json_v1(changed)
        with self.assertRaises(RecorderConflictError):
            self.recorder.accept(conflicting)
        self.assertEqual(1, len(list(self.root.rglob("*.conflict.json"))))
        self.assertEqual(1, len(list(self.root.rglob("*.conflicting.raw"))))
        with self.assertRaises(RecorderConflictError):
            self.recorder.accept(raw)

    def test_source_gap_does_not_advance_cursor(self) -> None:
        self.start()
        first = export_envelope(
            "PROVIDER_HEALTH",
            health_payload(),
            stream_id="health-stream",
            event_id="health-1",
        )
        self.recorder.accept(first)
        gap = export_envelope(
            "PROVIDER_HEALTH",
            health_payload(),
            stream_id="health-stream",
            event_id="health-3",
            sequence=3,
            previous=sha256_hex(first),
        )
        with self.assertRaises(RecorderCustodyError):
            self.recorder.accept(gap)
        checkpoints = [
            json.loads(path.read_bytes())
            for path in self.root.rglob("*.checkpoint.json")
            if json.loads(path.read_bytes()).get("stream_id") == "health-stream"
        ]
        self.assertEqual([1], [item["source_sequence"] for item in checkpoints])

    def test_decision_known_at_json_pointer_resolves_exact_hashed_parent_clock(self) -> None:
        self.start()
        self.discovery()
        observation_record = stored_records(self.root, "candidate-observation")[0][1]
        eligibility = observation_record["outcome_eligibility"]["commitment_payload_sha256"]
        self.recorder.accept(
            export_envelope(
                "MARKET_FACT",
                decision_snapshot_payload(),
                stream_id="snapshot-stream",
                event_id="snapshot-1",
            )
        )
        snapshot_record = stored_records(self.root, "market-snapshot")[0]
        payload = decision_payload(eligibility)
        decision = payload["decision_event"]
        decision["market_snapshot_id"] = present(DECISION_SNAPSHOT_ID)
        decision["known_at_evidence_refs"] = [
            {
                "evidence_field_path": "/provider_known_at",
                "known_at": snapshot_record[1]["provider_known_at"],
                "payload_sha256": sha256_hex(snapshot_record[2]),
                "record_id": DECISION_SNAPSHOT_ID,
            }
        ]
        self.recorder.accept(
            export_envelope(
                "DECISION_FACT",
                payload,
                stream_id="decision-stream",
                event_id="decision-with-known-at",
            )
        )
        self.assertEqual(1, len(stored_records(self.root, "decision-event")))

        partition = self.recorder._locate_partition(SESSION_ID)
        nonexistent = copy.deepcopy(payload)
        nonexistent["decision_event"]["known_at_evidence_refs"][0][
            "evidence_field_path"
        ] = "/market_facts/nonexistent"
        with self.assertRaises(RecorderContractError):
            self.recorder._validate_decision(partition, nonexistent)

        counterfeit_role = copy.deepcopy(payload)
        counterfeit_role["decision_event"]["known_at_evidence_refs"][0]["known_at"] = (
            time_evidence("PROVIDER_RECEIVED_AT", "2026-09-01T13:31:20Z")
        )
        with self.assertRaises(RecorderContractError):
            self.recorder._validate_decision(partition, counterfeit_role)

        future_known = copy.deepcopy(payload)
        future_known["decision_event"]["known_at_evidence_refs"][0]["known_at"] = (
            time_evidence("PROVIDER_KNOWN_AT", "2026-09-01T13:31:40Z")
        )
        with self.assertRaises(RecorderContractError):
            self.recorder._validate_decision(partition, future_known)

        cutoff_before_discovery = copy.deepcopy(payload)
        cutoff_before_discovery["decision_event"]["decision_cutoff"] = time_evidence(
            "DECISION_CUTOFF", "2026-09-01T13:30:30Z"
        )
        with self.assertRaises(RecorderContractError):
            self.recorder._validate_decision(partition, cutoff_before_discovery)

        wrong_candidate = copy.deepcopy(payload)
        other_setup = owner_identity("SETUP", "fixture-owner", "setup-other")
        wrong_candidate["decision_event"]["candidate_or_setup_identity"] = other_setup
        wrong_candidate["reference_plan"]["candidate_or_setup_identity"] = other_setup
        with self.assertRaises(RecorderContractError):
            self.recorder._validate_decision(partition, wrong_candidate)


if __name__ == "__main__":
    unittest.main()
