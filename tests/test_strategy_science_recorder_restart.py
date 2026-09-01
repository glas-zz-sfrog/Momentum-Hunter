from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.strategy_science_recorder import (
    RecorderRecoveryError,
    SimulatedRecorderCrash,
    StrategyScienceRecorder,
    sha256_hex,
)
from tests.test_strategy_science_recorder_contract import (
    SESSION_ID,
    SOURCE_ROOT_IDENTITY,
    FixedClock,
    decision_payload,
    discovery_payload,
    export_envelope,
    health_payload,
    market_bar_payload,
    outcome_attachment,
    source_final_envelope,
    start_envelope,
    stored_records,
    valid_outcome_payload,
)


class RecorderRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "science"

    def recorder(self, writer: str, clock: str = "2026-09-01T14:00:00Z") -> StrategyScienceRecorder:
        return StrategyScienceRecorder(
            self.root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id=writer,
            clock=FixedClock(clock),
        )

    def test_each_commit_phase_recovers_to_one_deterministic_event(self) -> None:
        for phase in ("after_source", "after_payload", "after_receipt"):
            with self.subTest(phase=phase):
                subroot = Path(self.temporary.name) / phase
                raw = start_envelope()
                first = StrategyScienceRecorder(
                    subroot,
                    source_root_identity=SOURCE_ROOT_IDENTITY,
                    writer_instance_id=f"first-{phase}",
                    clock=FixedClock(),
                )
                with self.assertRaises(SimulatedRecorderCrash):
                    first.accept(raw, crash_phase=phase)
                first.close()
                second = StrategyScienceRecorder(
                    subroot,
                    source_root_identity=SOURCE_ROOT_IDENTITY,
                    writer_instance_id=f"second-{phase}",
                    clock=FixedClock("2026-09-01T15:00:00Z"),
                )
                reports = second.recover()
                self.assertEqual(1, len(reports))
                self.assertEqual(1, reports[0].source_count)
                self.assertEqual(1, reports[0].payload_count)
                self.assertEqual(1, reports[0].checkpoint_count)
                self.assertEqual("IDEMPOTENT_ACK", second.accept(raw).status)
                second.close()

    def test_dependency_aware_recovery_rebuilds_start_before_discovery(self) -> None:
        start_raw = start_envelope()
        discovery_raw = export_envelope(
            "DISCOVERY_CYCLE",
            discovery_payload(),
            stream_id="aaa-discovery-hash-order-not-authority",
            event_id="discovery-1",
        )
        first = self.recorder("first")
        first.accept(start_raw)
        first.accept(discovery_raw)
        first.close()
        for path in self.root.rglob("*.checkpoint.json"):
            path.unlink()
        second = self.recorder("second", "2026-09-01T16:00:00Z")
        reports = second.recover()
        self.assertEqual(1, len(reports))
        self.assertEqual(2, reports[0].source_count)
        self.assertEqual(3, reports[0].payload_count)
        self.assertEqual(2, reports[0].checkpoint_count)
        self.assertEqual(1, len(stored_records(self.root, "candidate-observation")))
        second.close()

    def test_recovery_withholds_final_while_deferred_outcome_waits_for_parent(self) -> None:
        start_raw = start_envelope()
        first = self.recorder("first-deferred")
        first.accept(start_raw)
        first.accept(
            export_envelope(
                "DISCOVERY_CYCLE",
                discovery_payload(),
                stream_id="discovery-stream",
                event_id="discovery-1",
            )
        )
        first.accept(
            export_envelope(
                "MARKET_FACT",
                market_bar_payload(),
                stream_id="market-stream",
                event_id="bar-1",
            )
        )
        health_raw = export_envelope(
            "PROVIDER_HEALTH",
            health_payload(),
            stream_id="mixed-stream",
            event_id="health-1",
        )
        first.accept(health_raw)
        observation_record = stored_records(self.root, "candidate-observation")[0][1]
        eligibility = observation_record["outcome_eligibility"][
            "commitment_payload_sha256"
        ]
        decision_raw = export_envelope(
            "DECISION_FACT",
            decision_payload(eligibility),
            stream_id="mixed-stream",
            event_id="decision-1",
            sequence=2,
            previous=sha256_hex(health_raw),
        )
        first.accept(decision_raw)
        first.append_outcome(outcome_attachment(valid_outcome_payload(self.root)))
        first.accept(source_final_envelope(first, start_raw))
        first.close()

        for suffix in ("*.payload.json", "*.receipt.json", "*.checkpoint.json"):
            for path in self.root.rglob(suffix):
                path.unlink()
        recovered = self.recorder("recover-deferred")
        try:
            reports = recovered.recover()
            self.assertEqual(1, len(reports))
            self.assertEqual(1, len(stored_records(self.root, "outcome-observation")))
            source_finals = [
                item
                for item in stored_records(self.root, "session-manifest")
                if item[1].get("manifest_phase") == "FINAL"
            ]
            self.assertEqual(1, len(source_finals))
            self.assertTrue(reports[0].all_hashes_valid)
        finally:
            recovered.close()

    def test_clock_change_does_not_change_accepted_bytes_or_cursor(self) -> None:
        raw = start_envelope()
        first = self.recorder("first", "2026-09-01T14:00:00Z")
        first.accept(raw)
        payload_before = next(self.root.rglob("*.payload.json")).read_bytes()
        checkpoints_before = [path.read_bytes() for path in self.root.rglob("*.checkpoint.json")]
        first.close()
        second = self.recorder("second", "2030-01-01T00:00:00Z")
        self.assertEqual("IDEMPOTENT_ACK", second.accept(raw).status)
        self.assertEqual(payload_before, next(self.root.rglob("*.payload.json")).read_bytes())
        self.assertEqual(checkpoints_before, [path.read_bytes() for path in self.root.rglob("*.checkpoint.json")])
        second.close()

    def test_source_final_raw_tail_recovers_without_crossing_other_pending_source(self) -> None:
        start_raw = start_envelope()
        first = self.recorder("first-final-tail")
        first.accept(start_raw)
        final_raw = source_final_envelope(first, start_raw)
        with self.assertRaises(SimulatedRecorderCrash):
            first.accept(final_raw, crash_phase="after_source")
        first.close()
        second = self.recorder("second-final-tail")
        try:
            reports = second.recover()
            self.assertEqual(1, len(reports))
            source_finals = [
                item
                for item in stored_records(self.root, "session-manifest")
                if item[1].get("manifest_phase") == "FINAL"
            ]
            self.assertEqual(1, len(source_finals))
        finally:
            second.close()

    def test_corrupt_checkpoint_and_receipt_without_payload_fail_closed(self) -> None:
        raw = start_envelope()
        first = self.recorder("first")
        first.accept(raw)
        first.close()
        checkpoint = next(self.root.rglob("*.checkpoint.json"))
        checkpoint.write_bytes(checkpoint.read_bytes().replace(b'"schema_major_version":1', b'"schema_major_version":9'))
        second = self.recorder("second")
        with self.assertRaises(RecorderRecoveryError):
            second.recover()
        second.close()

        other_root = Path(self.temporary.name) / "receipt-without-payload"
        third = StrategyScienceRecorder(
            other_root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="third",
            clock=FixedClock(),
        )
        third.accept(raw)
        third.close()
        next(other_root.rglob("*.payload.json")).unlink()
        fourth = StrategyScienceRecorder(
            other_root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="fourth",
            clock=FixedClock(),
        )
        with self.assertRaises(RecorderRecoveryError):
            fourth.recover()
        fourth.close()

    def test_partial_discovery_replay_reuses_exact_staged_capture_time(self) -> None:
        start_raw = start_envelope()
        discovery_raw = export_envelope(
            "DISCOVERY_CYCLE",
            discovery_payload(),
            stream_id="discovery-stream",
            event_id="discovery-partial",
        )
        first = self.recorder("partial-first", "2026-09-01T14:00:00Z")
        first.accept(start_raw)
        with self.assertRaises(SimulatedRecorderCrash):
            first.accept(discovery_raw, crash_phase="after_payload")
        first.close()

        second = self.recorder("partial-second", "2030-01-01T00:00:00Z")
        try:
            second.recover()
            observation = stored_records(self.root, "candidate-observation")[0][1]
            self.assertEqual(
                "2026-09-01T14:00:00Z",
                observation["recorder_capture_time"]["normalized_rfc3339"],
            )
            self.assertEqual(
                "2026-09-01T14:00:00Z",
                observation["outcome_eligibility"]["committed_at"][
                    "normalized_rfc3339"
                ],
            )
            self.assertEqual(
                "2026-09-01T13:31:00Z",
                observation["outcome_eligibility"]["eligibility_basis_time"][
                    "normalized_rfc3339"
                ],
            )
        finally:
            second.close()

    def test_shared_partial_quarantine_is_wrapped_by_science_receipt(self) -> None:
        recorder = self.recorder("quarantine-receipt")
        partial = self.root / ".partial" / "surviving-partial.tmp"
        partial.write_bytes(b"surviving partial bytes")
        try:
            self.assertEqual((), recorder.recover())
            receipts = list(self.root.rglob("*.quarantine.json"))
            self.assertEqual(1, len(receipts))
            receipt = json.loads(receipts[0].read_bytes())
            self.assertEqual(
                "SCIENCE_PARTIAL_QUARANTINE_RECEIPT_V1", receipt["profile"]
            )
            self.assertEqual(
                "EXACT_BYTES_SURVIVED", receipt["post_quarantine_match_state"]
            )
            quarantined = self.root / ".quarantine" / receipt[
                "post_quarantine_match"
            ]["quarantine_name"]
            self.assertEqual(b"surviving partial bytes", quarantined.read_bytes())
        finally:
            recorder.close()


if __name__ == "__main__":
    unittest.main()
