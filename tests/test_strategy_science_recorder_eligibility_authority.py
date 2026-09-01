from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.strategy_science_recorder import (
    RecorderContractError,
    SimulatedRecorderCrash,
    StrategyScienceRecorder,
    canonical_json_v1,
    derive_coverage,
    outcome_linkage_sha256,
    outcome_series_binding_sha256,
    science_eligibility_sha256,
    sha256_hex,
)
from momentum_hunter.strategy_science_recorder.contract import (
    REPAIRED_EXPORT_SCHEMA_VERSION,
    REPAIRED_SOURCE_CONTRACT,
    REPAIRED_SOURCE_CONTRACT_VERSION,
    SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
    parse_export_envelope_v1,
    parse_export_envelope_v2,
)
from tests.test_strategy_science_recorder_contract import (
    BAR_TIME,
    DECISION_ID,
    MARKET_SNAPSHOT_ID,
    OBSERVATION_ID,
    OBSERVATION_ID_2,
    OUTCOME_ID,
    OUTCOME_SERIES_ID,
    SESSION_ID,
    SETUP_ID,
    SOURCE_ROOT_IDENTITY,
    FixedClock,
    decision_payload,
    discovery_payload,
    export_envelope,
    market_bar_payload,
    outcome_attachment,
    observation,
    present,
    start_payload,
    stored_records,
    time_evidence,
)


def decision_payload_v2() -> dict[str, object]:
    payload = decision_payload("0" * 64)
    del payload["decision_event"]["outcome_eligibility_commitment_sha256"]
    return payload


def export_envelope_v2(
    event_type: str,
    payload: dict[str, object],
    *,
    stream_id: str,
    event_id: str,
    sequence: int = 1,
    previous: str = "0" * 64,
) -> bytes:
    legacy = export_envelope(
        event_type,
        payload,
        stream_id=stream_id,
        event_id=event_id,
        sequence=sequence,
        previous=previous,
    )
    value = json.loads(legacy)
    value["schema_version"] = REPAIRED_EXPORT_SCHEMA_VERSION
    value["offline_reference_profile"] = SCIENCE_OFFLINE_EXPORT_PROFILE_V2
    value["source_contract"] = REPAIRED_SOURCE_CONTRACT
    value["source_contract_version"] = REPAIRED_SOURCE_CONTRACT_VERSION
    value["source_interface_identity"] = "fixture-export-interface-v2"
    value["payload"] = payload
    value["payload_sha256"] = sha256_hex(canonical_json_v1(payload))
    return canonical_json_v1(value)


def start_envelope_v2() -> bytes:
    return export_envelope_v2(
        "SESSION_MANIFEST",
        start_payload(),
        stream_id="session-stream",
        event_id="session-start",
    )


def discovery_envelope_v2() -> bytes:
    return export_envelope_v2(
        "DISCOVERY_CYCLE",
        discovery_payload(),
        stream_id="discovery-stream",
        event_id="discovery-1",
    )


def sealed_decision_envelope_v2() -> bytes:
    return export_envelope_v2(
        "DECISION_FACT",
        decision_payload_v2(),
        stream_id="decision-stream",
        event_id="decision-1",
    )


def observation_receipt_sha256(root: Path) -> str:
    observation_path = stored_records(root, "candidate-observation")[0][0]
    key = observation_path.name.removesuffix(".payload.json")
    receipt_path = next(root.rglob(f"{key}.receipt.json"))
    return sha256_hex(receipt_path.read_bytes())


def v2_outcome_payload(root: Path) -> dict[str, object]:
    decision_bytes = stored_records(root, "decision-event")[0][2]
    bar_bytes = stored_records(root, "market-snapshot")[0][2]
    eligibility = stored_records(root, "science-eligibility")[0][1][
        "science_eligibility"
    ]
    payload: dict[str, object] = {
        "candidate_or_setup_identity": SETUP_ID,
        "canonical_bar_payload_sha256s": [sha256_hex(bar_bytes)],
        "canonical_bar_record_ids": [MARKET_SNAPSHOT_ID],
        "canonical_path_fingerprint_sha256": present("0" * 64),
        "canonical_series_fingerprint_sha256": "0" * 64,
        "decision_id": DECISION_ID,
        "decision_payload_sha256": sha256_hex(decision_bytes),
        "eligibility_commitment_sha256": eligibility[
            "commitment_payload_sha256"
        ],
        "linkage_receipt_sha256": "0" * 64,
        "observation_id": OBSERVATION_ID,
        "outcome_observation_id": OUTCOME_ID,
        "outcome_semantic": "PLUS_5M",
        "outcome_semantic_version": "1.0.0",
        "outcome_series_id": OUTCOME_SERIES_ID,
        "outcome_state": "PRESENT",
        "outcome_time": time_evidence("OUTCOME_TIME", BAR_TIME),
        "outcome_value": present("12.80"),
        "path_completeness": present("COMPLETE"),
        "target_time": time_evidence(
            "OUTCOME_TIME", "2026-09-01T13:36:31Z"
        ),
        "transform_version": "fixture-transform-v1",
    }
    series_sha = outcome_series_binding_sha256(payload)
    payload["canonical_series_fingerprint_sha256"] = series_sha
    payload["canonical_path_fingerprint_sha256"] = present(series_sha)
    payload["linkage_receipt_sha256"] = outcome_linkage_sha256(payload)
    return payload


class ScienceEligibilityAuthorityContractTests(unittest.TestCase):
    def recorder(
        self,
        root: Path,
        clock: FixedClock,
        writer: str,
    ) -> StrategyScienceRecorder:
        return StrategyScienceRecorder(
            root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id=writer,
            clock=clock,
        )

    def populate_v2(
        self,
        root: Path,
        *,
        clock_value: str,
        include_market: bool = False,
    ) -> tuple[StrategyScienceRecorder, bytes, bytes, bytes]:
        recorder = self.recorder(root, FixedClock(clock_value), root.name)
        start_raw = start_envelope_v2()
        discovery_raw = discovery_envelope_v2()
        decision_raw = sealed_decision_envelope_v2()
        recorder.accept(start_raw)
        recorder.accept(discovery_raw)
        recorder.accept(decision_raw)
        if include_market:
            recorder.accept(
                export_envelope_v2(
                    "MARKET_FACT",
                    market_bar_payload(),
                    stream_id="market-stream",
                    event_id="bar-1",
                )
            )
        return recorder, start_raw, discovery_raw, decision_raw

    def test_exact_two_clock_contract_separates_all_hash_domains(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence: list[dict[str, str]] = []
            for ordinal, clock_value in enumerate(
                ("2026-09-01T14:00:00Z", "2026-09-01T14:00:01Z"),
                start=1,
            ):
                custody_root = root / f"science-{ordinal}"
                recorder, _start, discovery_raw, decision_raw = self.populate_v2(
                    custody_root, clock_value=clock_value
                )
                try:
                    eligibility = stored_records(
                        custody_root, "science-eligibility"
                    )[0][1]["science_eligibility"]
                    decision = stored_records(custody_root, "decision-event")[0][1]
                    evidence.append(
                        {
                            "producer_decision_hash": sha256_hex(decision_raw),
                            "producer_discovery_hash": sha256_hex(discovery_raw),
                            "science_receipt_hash": observation_receipt_sha256(
                                custody_root
                            ),
                            "science_eligibility_hash": eligibility[
                                "commitment_payload_sha256"
                            ],
                        }
                    )
                    self.assertNotIn(
                        "outcome_eligibility_commitment_sha256",
                        parse_export_envelope_v2(decision_raw).payload[
                            "decision_event"
                        ],
                    )
                    self.assertIn("science_eligibility_id", decision)
                    self.assertTrue(recorder.verify(SESSION_ID).all_hashes_valid)
                finally:
                    recorder.close()
            self.assertEqual(
                evidence[0]["producer_decision_hash"],
                evidence[1]["producer_decision_hash"],
            )
            self.assertEqual(
                evidence[0]["producer_discovery_hash"],
                evidence[1]["producer_discovery_hash"],
            )
            self.assertNotEqual(
                evidence[0]["science_receipt_hash"],
                evidence[1]["science_receipt_hash"],
            )
            self.assertNotEqual(
                evidence[0]["science_eligibility_hash"],
                evidence[1]["science_eligibility_hash"],
            )
            for item in evidence:
                self.assertEqual(3, len({
                    item["producer_discovery_hash"],
                    item["science_receipt_hash"],
                    item["science_eligibility_hash"],
                }))

    def test_producer_seals_without_future_science_fields_and_injection_fails(self) -> None:
        raw = sealed_decision_envelope_v2()
        parsed = parse_export_envelope_v2(raw)
        self.assertEqual(REPAIRED_EXPORT_SCHEMA_VERSION, parsed.schema_version)
        for field in (
            "outcome_eligibility_commitment_sha256",
            "science_receipt_hash",
            "science_eligibility_hash",
        ):
            changed = json.loads(raw)
            changed["payload"]["decision_event"][field] = "f" * 64
            changed["payload_sha256"] = sha256_hex(
                canonical_json_v1(changed["payload"])
            )
            with self.subTest(field=field), self.assertRaises(
                RecorderContractError
            ):
                parse_export_envelope_v2(canonical_json_v1(changed))

    def test_v1_and_v2_parsers_do_not_reclassify_the_other_profile(self) -> None:
        legacy = export_envelope(
            "SESSION_MANIFEST",
            start_payload(),
            stream_id="session-stream",
            event_id="session-start",
        )
        with self.assertRaises(RecorderContractError):
            parse_export_envelope_v1(start_envelope_v2())
        with self.assertRaises(RecorderContractError):
            parse_export_envelope_v2(legacy)

    def test_same_instrument_uses_one_first_receipt_bound_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "science"
            recorder = self.recorder(root, FixedClock(), "first-observation")
            try:
                recorder.accept(start_envelope_v2())
                rows = [
                    observation(),
                    observation(OBSERVATION_ID_2, ordinal=1, symbol="AAA"),
                ]
                recorder.accept(
                    export_envelope_v2(
                        "DISCOVERY_CYCLE",
                        discovery_payload(rows),
                        stream_id="discovery-stream",
                        event_id="discovery-two-rows",
                    )
                )
                eligibility_records = stored_records(
                    root, "science-eligibility"
                )
                self.assertEqual(1, len(eligibility_records))
                eligibility = eligibility_records[0][1]["science_eligibility"]
                self.assertEqual(
                    OBSERVATION_ID, eligibility["first_observation_id"]
                )
                self.assertEqual(
                    2, len(stored_records(root, "candidate-observation"))
                )
            finally:
                recorder.close()

    def test_science_receipt_before_producer_known_at_fails_without_partial_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "science"
            clock = FixedClock("2026-09-01T14:00:00Z")
            recorder = self.recorder(root, clock, "negative-clock")
            try:
                recorder.accept(start_envelope_v2())
                clock.value = "2026-09-01T13:30:59Z"
                with self.assertRaises(RecorderContractError):
                    recorder.accept(discovery_envelope_v2())
                self.assertEqual([], stored_records(root, "candidate-observation"))
                self.assertEqual([], stored_records(root, "science-eligibility"))
            finally:
                recorder.close()

    def test_wrong_producer_or_custody_hash_in_science_eligibility_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "science"
            recorder, _start, _discovery, _decision = self.populate_v2(
                root, clock_value="2026-09-01T14:00:00Z"
            )
            try:
                partition = recorder._locate_partition(SESSION_ID)
                record = stored_records(root, "science-eligibility")[0][1]
                for field in (
                    "producer_content_sha256",
                    "science_custody_receipt_sha256",
                ):
                    changed = copy.deepcopy(record)
                    changed["science_eligibility"][field] = "f" * 64
                    changed["science_eligibility"][
                        "commitment_payload_sha256"
                    ] = science_eligibility_sha256(
                        changed["science_eligibility"]
                    )
                    with self.subTest(field=field), self.assertRaises(
                        RecorderContractError
                    ):
                        recorder._validate_science_eligibility_record(
                            partition, changed
                        )
            finally:
                recorder.close()

    def test_initial_eligibility_rejects_outcome_or_future_market_material(self) -> None:
        payload = discovery_payload()
        payload["observations"][0]["outcome_value"] = present("99.99")
        with self.assertRaises(RecorderContractError):
            parse_export_envelope_v2(
                export_envelope_v2(
                    "DISCOVERY_CYCLE",
                    payload,
                    stream_id="discovery-stream",
                    event_id="future-outcome-injection",
                )
            )

    def test_outcome_is_later_and_binds_science_eligibility_without_rewriting_parents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "science"
            recorder, _start, _discovery, _decision = self.populate_v2(
                root,
                clock_value="2026-09-01T14:00:00Z",
                include_market=True,
            )
            try:
                observation_before = stored_records(
                    root, "candidate-observation"
                )[0][2]
                eligibility_before = stored_records(
                    root, "science-eligibility"
                )[0][2]
                decision_before = stored_records(root, "decision-event")[0][2]
                result = recorder.append_outcome(
                    outcome_attachment(v2_outcome_payload(root))
                )
                self.assertEqual("ACCEPTED", result.status)
                partition = recorder._locate_partition(SESSION_ID)
                coverage = derive_coverage(recorder._all_records(partition))
                self.assertEqual(1, coverage.eligible_instruments)
                self.assertEqual(1, coverage.material_decisions)
                self.assertEqual(1, coverage.received_outcome_slots)
                self.assertEqual(
                    observation_before,
                    stored_records(root, "candidate-observation")[0][2],
                )
                self.assertEqual(
                    eligibility_before,
                    stored_records(root, "science-eligibility")[0][2],
                )
                self.assertEqual(
                    decision_before,
                    stored_records(root, "decision-event")[0][2],
                )
            finally:
                recorder.close()

    def test_v2_restart_is_idempotent_and_legacy_v1_records_are_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            v2_root = root / "v2"
            first, start_raw, discovery_raw, decision_raw = self.populate_v2(
                v2_root, clock_value="2026-09-01T14:00:00Z"
            )
            before = sorted(
                (path.relative_to(v2_root).as_posix(), path.read_bytes())
                for path in v2_root.rglob("*.json")
            )
            first.close()
            second = self.recorder(
                v2_root, FixedClock("2030-01-01T00:00:00Z"), "v2-restart"
            )
            try:
                self.assertEqual(1, len(second.recover()))
                for raw in (start_raw, discovery_raw, decision_raw):
                    self.assertEqual("IDEMPOTENT_ACK", second.accept(raw).status)
                after = sorted(
                    (path.relative_to(v2_root).as_posix(), path.read_bytes())
                    for path in v2_root.rglob("*.json")
                )
                self.assertEqual(before, after)
            finally:
                second.close()

            legacy_root = root / "legacy"
            legacy = self.recorder(
                legacy_root, FixedClock("2026-09-01T14:00:00Z"), "legacy"
            )
            try:
                legacy.accept(
                    export_envelope(
                        "SESSION_MANIFEST",
                        start_payload(),
                        stream_id="session-stream",
                        event_id="session-start",
                    )
                )
                legacy.accept(
                    export_envelope(
                        "DISCOVERY_CYCLE",
                        discovery_payload(),
                        stream_id="discovery-stream",
                        event_id="discovery-1",
                    )
                )
                observation = stored_records(
                    legacy_root, "candidate-observation"
                )[0][1]
                self.assertIn("outcome_eligibility", observation)
                self.assertEqual(
                    [], stored_records(legacy_root, "science-eligibility")
                )
                self.assertTrue(legacy.verify(SESSION_ID).all_hashes_valid)
            finally:
                legacy.close()

    def test_v2_discovery_commit_phases_recover_one_receipt_bound_eligibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for phase in ("after_source", "after_payload", "after_receipt"):
                with self.subTest(phase=phase):
                    custody_root = root / phase
                    first = self.recorder(
                        custody_root, FixedClock(), f"first-{phase}"
                    )
                    discovery_raw = discovery_envelope_v2()
                    try:
                        first.accept(start_envelope_v2())
                        with self.assertRaises(SimulatedRecorderCrash):
                            first.accept(discovery_raw, crash_phase=phase)
                    finally:
                        first.close()
                    recovered = self.recorder(
                        custody_root,
                        FixedClock("2030-01-01T00:00:00Z"),
                        f"recovered-{phase}",
                    )
                    try:
                        reports = recovered.recover()
                        self.assertEqual(1, len(reports))
                        self.assertEqual(
                            1,
                            len(
                                stored_records(
                                    custody_root, "science-eligibility"
                                )
                            ),
                        )
                        self.assertEqual(
                            "IDEMPOTENT_ACK",
                            recovered.accept(discovery_raw).status,
                        )
                        self.assertTrue(
                            recovered.verify(SESSION_ID).all_hashes_valid
                        )
                    finally:
                        recovered.close()


if __name__ == "__main__":
    unittest.main()
