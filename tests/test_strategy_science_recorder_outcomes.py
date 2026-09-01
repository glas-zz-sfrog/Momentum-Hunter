from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.strategy_science_recorder import (
    RecorderContractError,
    RecorderConflictError,
    StrategyScienceRecorder,
    canonical_json_v1,
    outcome_linkage_sha256,
    outcome_series_binding_sha256,
    owner_identity,
    recorder_identity,
    sha256_hex,
)
from tests.test_strategy_science_recorder_contract import (
    BAR_TIME,
    DECISION_ID,
    OUTCOME_ID,
    OUTCOME_SERIES_ID,
    OBSERVATION_ID,
    MARKET_SNAPSHOT_ID,
    SESSION_ID,
    SETUP_ID,
    SOURCE_ROOT_IDENTITY,
    FixedClock,
    absent,
    decision_payload,
    discovery_payload,
    export_envelope,
    market_bar_payload,
    outcome_attachment,
    present,
    start_envelope,
    stored_records,
    time_evidence,
)


class RecorderOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "science"
        self.recorder = StrategyScienceRecorder(
            self.root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="outcome-tests",
            clock=FixedClock(),
        )
        self.addCleanup(self.recorder.close)
        self.start_raw = start_envelope()
        self.recorder.accept(self.start_raw)
        self.recorder.accept(
            export_envelope(
                "DISCOVERY_CYCLE",
                discovery_payload(),
                stream_id="discovery-stream",
                event_id="discovery-1",
            )
        )
        observation_record = stored_records(self.root, "candidate-observation")[0][1]
        self.eligibility_sha = observation_record["outcome_eligibility"][
            "commitment_payload_sha256"
        ]
        self.recorder.accept(
            export_envelope(
                "DECISION_FACT",
                decision_payload(self.eligibility_sha),
                stream_id="decision-stream",
                event_id="decision-1",
            )
        )
        self.recorder.accept(
            export_envelope(
                "MARKET_FACT",
                market_bar_payload(),
                stream_id="market-stream",
                event_id="bar-1",
            )
        )
        self.decision_bytes = stored_records(self.root, "decision-event")[0][2]
        self.bar_bytes = stored_records(self.root, "market-snapshot")[0][2]

    def payload(self, *, state: str = "PRESENT") -> dict[str, object]:
        value = present("12.80") if state == "PRESENT" else {
            "authority": "fixture-outcome-owner",
            "reason_code": "TARGET_AFTER_REGULAR_SESSION_CLOSE",
            "state": state,
        }
        payload: dict[str, object] = {
            "candidate_or_setup_identity": SETUP_ID,
            "canonical_bar_payload_sha256s": [sha256_hex(self.bar_bytes)],
            "canonical_bar_record_ids": [MARKET_SNAPSHOT_ID],
            "canonical_path_fingerprint_sha256": present("0" * 64),
            "canonical_series_fingerprint_sha256": "0" * 64,
            "decision_id": DECISION_ID,
            "decision_payload_sha256": sha256_hex(self.decision_bytes),
            "eligibility_commitment_sha256": self.eligibility_sha,
            "linkage_receipt_sha256": "0" * 64,
            "observation_id": OBSERVATION_ID,
            "outcome_observation_id": OUTCOME_ID,
            "outcome_semantic": "PLUS_5M",
            "outcome_semantic_version": "1.0.0",
            "outcome_series_id": OUTCOME_SERIES_ID,
            "outcome_state": state,
            "outcome_time": time_evidence("OUTCOME_TIME", BAR_TIME),
            "outcome_value": value,
            "path_completeness": present("COMPLETE"),
            "target_time": time_evidence("OUTCOME_TIME", "2026-09-01T13:36:31Z"),
            "transform_version": "fixture-transform-v1",
        }
        series_sha = outcome_series_binding_sha256(payload)
        payload["canonical_series_fingerprint_sha256"] = series_sha
        payload["canonical_path_fingerprint_sha256"] = present(series_sha)
        payload["linkage_receipt_sha256"] = outcome_linkage_sha256(payload)
        return payload

    def seal(self, payload: dict[str, object]) -> dict[str, object]:
        series_sha = outcome_series_binding_sha256(payload)
        payload["canonical_series_fingerprint_sha256"] = series_sha
        path = payload["canonical_path_fingerprint_sha256"]
        if isinstance(path, dict) and path.get("state") == "PRESENT":
            payload["canonical_path_fingerprint_sha256"] = present(series_sha)
        payload["linkage_receipt_sha256"] = outcome_linkage_sha256(payload)
        return payload

    def test_outcome_is_separate_append_and_never_mutates_decision(self) -> None:
        before = self.decision_bytes
        raw = outcome_attachment(self.payload())
        result = self.recorder.append_outcome(raw)
        self.assertEqual("ACCEPTED", result.status)
        outcome = stored_records(self.root, "outcome-observation")
        self.assertEqual(1, len(outcome))
        self.assertIn("payloads/outcome", outcome[0][0].as_posix())
        self.assertEqual(before, stored_records(self.root, "decision-event")[0][2])
        self.assertEqual("IDEMPOTENT_ACK", self.recorder.append_outcome(raw).status)
        self.assertEqual(1, len(stored_records(self.root, "outcome-observation")))

    def test_wrong_decision_eligibility_or_bar_hash_fails_before_outcome_write(self) -> None:
        cases = []
        for field in (
            "decision_payload_sha256",
            "eligibility_commitment_sha256",
        ):
            value = self.payload()
            value[field] = "f" * 64
            value["linkage_receipt_sha256"] = outcome_linkage_sha256(value)
            cases.append(value)
        value = self.payload()
        value["canonical_bar_payload_sha256s"] = ["e" * 64]
        value["linkage_receipt_sha256"] = outcome_linkage_sha256(value)
        cases.append(value)
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(RecorderContractError):
                self.recorder.append_outcome(outcome_attachment(payload))
        self.assertEqual([], stored_records(self.root, "outcome-observation"))

    def test_future_time_cannot_be_retroactively_moved_before_target(self) -> None:
        payload = self.payload()
        payload["outcome_time"] = time_evidence(
            "OUTCOME_TIME", "2026-09-01T13:35:00Z"
        )
        payload["linkage_receipt_sha256"] = outcome_linkage_sha256(payload)
        with self.assertRaises(RecorderContractError):
            self.recorder.append_outcome(outcome_attachment(payload))

        terminal = self.payload()
        terminal["canonical_bar_payload_sha256s"] = []
        terminal["canonical_bar_record_ids"] = []
        terminal["outcome_state"] = "UNAVAILABLE"
        terminal["outcome_time"] = absent(
            "UNAVAILABLE", "PROVIDER_OUTCOME_UNAVAILABLE"
        ) | {"role": "OUTCOME_TIME"}
        terminal["outcome_value"] = absent(
            "UNAVAILABLE", "PROVIDER_OUTCOME_UNAVAILABLE"
        )
        terminal["canonical_path_fingerprint_sha256"] = absent(
            "UNAVAILABLE", "PROVIDER_OUTCOME_UNAVAILABLE"
        )
        terminal["path_completeness"] = absent(
            "UNAVAILABLE", "PROVIDER_OUTCOME_UNAVAILABLE"
        )
        with self.assertRaises(RecorderContractError):
            self.recorder.append_outcome(
                outcome_attachment(
                    self.seal(terminal),
                    observed_at="2026-09-01T13:36:30Z",
                )
            )

    def test_outcome_surface_rejects_forbidden_execution_capability_fields(self) -> None:
        raw = json.loads(outcome_attachment(self.payload()))
        payload = copy.deepcopy(raw["payload"])
        payload["order"] = {"side": "BUY"}
        payload["linkage_receipt_sha256"] = outcome_linkage_sha256(payload)
        raw["payload"] = payload
        raw["payload_sha256"] = sha256_hex(canonical_json_v1(payload))
        with self.assertRaises(RecorderContractError):
            self.recorder.append_outcome(canonical_json_v1(raw))

    def test_outcome_surface_rejects_caller_allocated_session_identity(self) -> None:
        raw = json.loads(outcome_attachment(self.payload()))
        raw["session_id"] = recorder_identity(
            "SESSION_ID", {"symbol": "AAA"}
        )
        with self.assertRaises(RecorderContractError):
            self.recorder.append_outcome(canonical_json_v1(raw))

    def test_point_horizon_requires_exact_target_bar_series_and_instrument(self) -> None:
        probes: list[dict[str, object]] = []
        barless = self.payload()
        barless["canonical_bar_record_ids"] = []
        barless["canonical_bar_payload_sha256s"] = []
        probes.append(self.seal(barless))

        wrong_target = self.payload()
        wrong_target["target_time"] = time_evidence(
            "OUTCOME_TIME", "2026-09-01T13:36:30Z"
        )
        probes.append(self.seal(wrong_target))

        wrong_series = self.payload()
        wrong_series["outcome_series_id"] = owner_identity(
            "OUTCOME_SERIES_ID", "fixture-owner", "series-other"
        )
        probes.append(self.seal(wrong_series))

        wrong_candidate = self.payload()
        wrong_candidate["candidate_or_setup_identity"] = owner_identity(
            "SETUP", "fixture-owner", "setup-other"
        )
        probes.append(self.seal(wrong_candidate))

        wrong_observation = self.payload()
        wrong_observation["observation_id"] = owner_identity(
            "OBSERVATION_ID", "fixture-owner", "observation-other"
        )
        probes.append(self.seal(wrong_observation))

        for payload in probes:
            with self.subTest(payload=payload), self.assertRaises(RecorderContractError):
                self.recorder.append_outcome(outcome_attachment(payload))

        other_bar_id = owner_identity(
            "MARKET_SNAPSHOT_ID", "fixture-owner", "bar-other-instrument"
        )
        self.recorder.accept(
            export_envelope(
                "MARKET_FACT",
                market_bar_payload(market_snapshot_id=other_bar_id, symbol="BBB"),
                stream_id="other-market-stream",
                event_id="bar-other-instrument",
            )
        )
        other_bar = next(
            item for item in stored_records(self.root, "market-snapshot")
            if item[1]["record_id"] == other_bar_id
        )
        wrong_instrument = self.payload()
        wrong_instrument["canonical_bar_record_ids"] = [other_bar_id]
        wrong_instrument["canonical_bar_payload_sha256s"] = [sha256_hex(other_bar[2])]
        with self.assertRaises(RecorderContractError):
            self.recorder.append_outcome(outcome_attachment(self.seal(wrong_instrument)))

    def test_session_close_and_early_close_truncation_rules(self) -> None:
        close_bar_id = owner_identity(
            "MARKET_SNAPSHOT_ID", "fixture-owner", "session-close-bar"
        )
        self.recorder.accept(
            export_envelope(
                "MARKET_FACT",
                market_bar_payload(
                    market_snapshot_id=close_bar_id,
                    bar_interval_start="2026-09-01T19:59:00Z",
                    bar_interval_end="2026-09-01T20:00:00Z",
                ),
                stream_id="close-market-stream",
                event_id="session-close-bar",
            )
        )
        close_bar = next(
            item for item in stored_records(self.root, "market-snapshot")
            if item[1]["record_id"] == close_bar_id
        )
        close_payload = self.payload()
        close_payload["outcome_observation_id"] = owner_identity(
            "OUTCOME_OBSERVATION_ID", "fixture-owner", "session-close-outcome"
        )
        close_payload["outcome_semantic"] = "SESSION_CLOSE"
        close_payload["target_time"] = time_evidence("OUTCOME_TIME", "2026-09-01T20:00:00Z")
        close_payload["outcome_time"] = time_evidence("OUTCOME_TIME", "2026-09-01T20:00:00Z")
        close_payload["canonical_bar_record_ids"] = [close_bar_id]
        close_payload["canonical_bar_payload_sha256s"] = [sha256_hex(close_bar[2])]
        result = self.recorder.append_outcome(
            outcome_attachment(
                self.seal(close_payload), observed_at="2026-09-01T20:01:00Z"
            )
        )
        self.assertEqual("ACCEPTED", result.status)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "early-close"
            recorder = StrategyScienceRecorder(
                root,
                source_root_identity=SOURCE_ROOT_IDENTITY,
                writer_instance_id="early-close",
                clock=FixedClock(),
            )
            try:
                recorder.accept(start_envelope(regular_session_close="2026-09-01T13:35:00Z"))
                recorder.accept(export_envelope(
                    "DISCOVERY_CYCLE", discovery_payload(),
                    stream_id="discovery-stream", event_id="discovery-1",
                ))
                observation_record = stored_records(root, "candidate-observation")[0][1]
                eligibility = observation_record["outcome_eligibility"]["commitment_payload_sha256"]
                recorder.accept(export_envelope(
                    "DECISION_FACT", decision_payload(eligibility),
                    stream_id="decision-stream", event_id="decision-1",
                ))
                decision_bytes = stored_records(root, "decision-event")[0][2]
                truncated = self.payload()
                truncated["decision_payload_sha256"] = sha256_hex(decision_bytes)
                truncated["eligibility_commitment_sha256"] = eligibility
                truncated["canonical_bar_record_ids"] = []
                truncated["canonical_bar_payload_sha256s"] = []
                truncated["outcome_state"] = "SESSION_TRUNCATED"
                truncated["outcome_time"] = {
                    "authority": "fixture-exchange-calendar",
                    "reason_code": "TARGET_AFTER_REGULAR_SESSION_CLOSE",
                    "role": "OUTCOME_TIME",
                    "state": "SESSION_TRUNCATED",
                }
                truncated["outcome_value"] = absent(
                    "SESSION_TRUNCATED", "TARGET_AFTER_REGULAR_SESSION_CLOSE"
                )
                truncated["canonical_path_fingerprint_sha256"] = absent(
                    "SESSION_TRUNCATED", "TARGET_AFTER_REGULAR_SESSION_CLOSE"
                )
                truncated["path_completeness"] = absent(
                    "SESSION_TRUNCATED", "TARGET_AFTER_REGULAR_SESSION_CLOSE"
                )
                result = recorder.append_outcome(
                    outcome_attachment(self.seal(truncated))
                )
                self.assertEqual("ACCEPTED", result.status)
            finally:
                recorder.close()

    def test_present_mfe_mae_and_distinct_identity_for_same_slot_fail_closed(self) -> None:
        mfe = self.payload()
        mfe["outcome_semantic"] = "MFE"
        mfe["target_time"] = time_evidence("OUTCOME_TIME", "2026-09-01T20:00:00Z")
        with self.assertRaises(RecorderContractError):
            self.recorder.append_outcome(outcome_attachment(self.seal(mfe)))

        first_raw = outcome_attachment(self.payload())
        self.recorder.append_outcome(first_raw)
        duplicate_slot = self.payload()
        duplicate_slot["outcome_observation_id"] = owner_identity(
            "OUTCOME_OBSERVATION_ID", "fixture-owner", "outcome-distinct-id"
        )
        second_raw = outcome_attachment(
            self.seal(duplicate_slot),
            event_id="outcome-attachment-2",
            sequence=2,
            previous=sha256_hex(first_raw),
        )
        with self.assertRaises(RecorderConflictError):
            self.recorder.append_outcome(second_raw)
        self.assertEqual(1, len(list(self.root.rglob("*.conflict.json"))))


if __name__ == "__main__":
    unittest.main()
