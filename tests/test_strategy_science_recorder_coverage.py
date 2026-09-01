from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.strategy_science_recorder import (
    CoverageReconciliationError,
    METRIC_IDS,
    RecorderRecoveryError,
    RecorderConflictError,
    SimulatedRecorderCrash,
    StrategyScienceRecorder,
    canonical_json_v1,
    derive_coverage,
    outcome_linkage_sha256,
    outcome_series_binding_sha256,
    owner_identity,
    sha256_hex,
)
from tests.test_strategy_science_recorder_contract import (
    BAR_TIME,
    DECISION_ID,
    MARKET_SNAPSHOT_ID,
    OBSERVATION_ID,
    OUTCOME_ID,
    OUTCOME_SERIES_ID,
    SESSION_ID,
    SETUP_ID,
    SOURCE_ROOT_IDENTITY,
    FixedClock,
    absent,
    decision_payload,
    discovery_payload,
    export_envelope,
    health_payload,
    market_bar_payload,
    outcome_attachment,
    present,
    source_final_envelope,
    start_envelope,
    stored_records,
    time_evidence,
)


class RecorderCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "science"
        self.recorder = StrategyScienceRecorder(
            self.root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="coverage-tests",
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
        observation = stored_records(self.root, "candidate-observation")[0][1]
        self.eligibility_sha = observation["outcome_eligibility"][
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

    def outcome_payload(
        self,
        *,
        semantic: str,
        outcome_id: dict[str, object],
        present_value: bool,
        nonpresent_state: str = "UNAVAILABLE",
    ) -> dict[str, object]:
        decision_bytes = stored_records(self.root, "decision-event")[0][2]
        bar_bytes = stored_records(self.root, "market-snapshot")[0][2]
        if present_value:
            outcome_time = time_evidence("OUTCOME_TIME", BAR_TIME)
            outcome_value = present("12.80")
            state = "PRESENT"
            bars = [MARKET_SNAPSHOT_ID]
            bar_hashes = [sha256_hex(bar_bytes)]
        else:
            state = nonpresent_state
            reason = f"PROVIDER_OUTCOME_{state}"
            outcome_time = {
                "authority": "fixture-outcome-owner",
                "reason_code": reason,
                "role": "OUTCOME_TIME",
                "state": state,
            }
            outcome_value = absent(
                state, reason
            )
            bars = []
            bar_hashes = []
        payload: dict[str, object] = {
            "candidate_or_setup_identity": SETUP_ID,
            "canonical_bar_payload_sha256s": bar_hashes,
            "canonical_bar_record_ids": bars,
            "canonical_path_fingerprint_sha256": (
                present("0" * 64)
                if present_value
                else absent(state, reason)
            ),
            "canonical_series_fingerprint_sha256": "0" * 64,
            "decision_id": DECISION_ID,
            "decision_payload_sha256": sha256_hex(decision_bytes),
            "eligibility_commitment_sha256": self.eligibility_sha,
            "linkage_receipt_sha256": "0" * 64,
            "observation_id": OBSERVATION_ID,
            "outcome_observation_id": outcome_id,
            "outcome_semantic": semantic,
            "outcome_semantic_version": "1.0.0",
            "outcome_series_id": OUTCOME_SERIES_ID,
            "outcome_state": state,
            "outcome_time": outcome_time,
            "outcome_value": outcome_value,
            "path_completeness": (
                present("COMPLETE")
                if present_value
                else absent(state, reason)
            ),
            "target_time": time_evidence(
                "OUTCOME_TIME",
                {
                    "PLUS_5M": "2026-09-01T13:36:31Z",
                    "PLUS_15M": "2026-09-01T13:46:31Z",
                    "PLUS_30M": "2026-09-01T14:01:31Z",
                    "PLUS_60M": "2026-09-01T14:31:31Z",
                    "SESSION_CLOSE": "2026-09-01T20:00:00Z",
                    "MFE": "2026-09-01T20:00:00Z",
                    "MAE": "2026-09-01T20:00:00Z",
                }[semantic],
            ),
            "transform_version": "fixture-transform-v1",
        }
        series_sha = outcome_series_binding_sha256(payload)
        payload["canonical_series_fingerprint_sha256"] = series_sha
        if present_value:
            payload["canonical_path_fingerprint_sha256"] = present(series_sha)
        payload["linkage_receipt_sha256"] = outcome_linkage_sha256(payload)
        return payload

    def append_two_outcomes(self) -> tuple[bytes, bytes]:
        first = outcome_attachment(
            self.outcome_payload(
                semantic="PLUS_5M", outcome_id=OUTCOME_ID, present_value=True
            )
        )
        self.recorder.append_outcome(first)
        second = outcome_attachment(
            self.outcome_payload(
                semantic="PLUS_15M",
                outcome_id=owner_identity(
                    "OUTCOME_OBSERVATION_ID", "fixture-owner", "outcome-2"
                ),
                present_value=False,
            ),
            event_id="outcome-attachment-2",
            sequence=2,
            previous=sha256_hex(first),
        )
        self.recorder.append_outcome(second)
        return first, second

    def append_all_nonpresent_outcomes(
        self, *, state: str, observed_at: str
    ) -> tuple[bytes, ...]:
        raws: list[bytes] = []
        previous = "0" * 64
        for sequence, semantic in enumerate(
            (
                "PLUS_5M",
                "PLUS_15M",
                "PLUS_30M",
                "PLUS_60M",
                "SESSION_CLOSE",
                "MFE",
                "MAE",
            ),
            start=1,
        ):
            raw = outcome_attachment(
                self.outcome_payload(
                    semantic=semantic,
                    outcome_id=owner_identity(
                        "OUTCOME_OBSERVATION_ID",
                        "fixture-owner",
                        f"{state.casefold()}-{semantic.casefold()}",
                    ),
                    present_value=False,
                    nonpresent_state=state,
                ),
                event_id=f"{state.casefold()}-{semantic.casefold()}",
                sequence=sequence,
                previous=previous,
                observed_at=observed_at,
            )
            self.recorder.append_outcome(raw)
            raws.append(raw)
            previous = sha256_hex(raw)
        return tuple(raws)

    def test_coverage_keeps_accounting_and_usable_denominators_distinct(self) -> None:
        self.append_two_outcomes()
        partition = self.recorder._locate_partition(SESSION_ID)
        summary = derive_coverage(self.recorder._all_records(partition))
        self.assertEqual(1, summary.material_decisions)
        self.assertEqual(7, summary.expected_outcome_slots)
        self.assertEqual(2, summary.accounted_outcome_slots)
        self.assertEqual(1, summary.usable_outcome_slots)
        self.assertEqual(1, summary.terminal_gap_slots)
        self.assertEqual(285714, summary.outcome_accounting_rate_ppm)
        self.assertEqual(142857, summary.usable_outcome_rate_ppm)
        self.assertEqual("AVAILABLE", summary.outcome_accounting_rate_state)
        self.assertEqual(5, summary.unaccounted_outcome_slots)
        self.assertEqual(set(METRIC_IDS), set(summary.metrics))
        self.assertEqual(set(summary.by_horizon), {
            "PLUS_5M", "PLUS_15M", "PLUS_30M", "PLUS_60M",
            "SESSION_CLOSE", "MFE", "MAE",
        })

    def test_terminal_slots_before_frozen_finalization_cutoff_do_not_complete(self) -> None:
        self.append_all_nonpresent_outcomes(
            state="UNAVAILABLE", observed_at="2026-09-01T20:30:00Z"
        )
        partition = self.recorder._locate_partition(SESSION_ID)
        coverage = derive_coverage(self.recorder._all_records(partition))
        self.assertEqual(7, coverage.received_outcome_slots)
        self.assertEqual(7, coverage.accounted_outcome_slots)
        self.assertEqual(0, coverage.unaccounted_outcome_slots)
        self.recorder.accept(
            source_final_envelope(
                self.recorder,
                self.start_raw,
                closed_at="2026-09-01T20:31:00Z",
            )
        )
        result = self.recorder.finalize(SESSION_ID)
        self.assertEqual("INCOMPLETE_OFFLINE_REFERENCE", result.custody_classification)
        manifest = json.loads(next(self.root.rglob("*.final.json")).read_bytes())
        self.assertFalse(
            manifest["source_final_reconciliation"][
                "finalization_cutoff_satisfied"
            ]
        )

    def test_partial_slots_after_cutoff_remain_received_but_unaccounted(self) -> None:
        self.append_all_nonpresent_outcomes(
            state="PARTIAL", observed_at="2026-09-01T21:05:00Z"
        )
        partition = self.recorder._locate_partition(SESSION_ID)
        coverage = derive_coverage(self.recorder._all_records(partition))
        self.assertEqual(7, coverage.received_outcome_slots)
        self.assertEqual(0, coverage.accounted_outcome_slots)
        self.assertEqual(7, coverage.nonterminal_outcome_slots)
        self.assertEqual(7, coverage.unaccounted_outcome_slots)
        self.recorder.accept(
            source_final_envelope(
                self.recorder,
                self.start_raw,
                closed_at="2026-09-01T21:06:00Z",
            )
        )
        result = self.recorder.finalize(SESSION_ID)
        self.assertEqual("INCOMPLETE_OFFLINE_REFERENCE", result.custody_classification)
        manifest = json.loads(next(self.root.rglob("*.final.json")).read_bytes())
        self.assertTrue(
            manifest["source_final_reconciliation"][
                "finalization_cutoff_satisfied"
            ]
        )
        self.assertEqual(7, manifest["coverage"]["nonterminal_outcome_slots"])

    def test_coverage_ignores_malformed_empty_identities(self) -> None:
        malformed = {
            "record_type": "candidate-observation",
            "observation_id": {"recorder_id": ""},
            "instrument_identity": {
                "instrument_identity_fingerprint_sha256": ""
            },
        }
        summary = derive_coverage([malformed])
        self.assertEqual(0, summary.candidate_observations)
        self.assertEqual(0, summary.unique_instruments)
        self.assertEqual("NOT_APPLICABLE", summary.outcome_accounting_rate_state)
        self.assertEqual(0, summary.outcome_accounting_rate_ppm)
        self.assertEqual("NOT_APPLICABLE", summary.usable_outcome_rate_state)
        self.assertEqual(16, len(summary.metrics))

    def test_undeclared_metric_denominators_never_create_tautological_or_overflow_rates(self) -> None:
        partition = self.recorder._locate_partition(SESSION_ID)
        records = list(self.recorder._all_records(partition))
        for ordinal in (1, 2):
            records.append(
                {
                    "decision_id": DECISION_ID,
                    "market_snapshot_id": owner_identity(
                        "MARKET_SNAPSHOT_ID",
                        "fixture-owner",
                        f"decision-snapshot-{ordinal}",
                    ),
                    "observation_id": OBSERVATION_ID,
                    "record_type": "market-snapshot",
                    "snapshot_kind": "DECISION_SNAPSHOT",
                }
            )
        summary = derive_coverage(records)
        for metric_id in (
            "QUOTE_SNAPSHOT_COVERAGE",
            "SCORE_COVERAGE",
            "REFERENCE_LEVEL_COVERAGE",
            "KNOWN_AT_COVERAGE",
        ):
            metric = summary.metrics[metric_id]
            self.assertEqual("NOT_PROVEN", metric["state"])
            self.assertNotIn("rate_ppm", metric)

        overclaimed = [
            {
                "record_id": owner_identity(
                    "DISCOVERY_CYCLE_ID", "fixture-owner", "declared-one-row"
                ),
                "record_type": "discovery-cycle",
                "returned_row_count": 1,
            },
            *[
                {
                    "instrument_identity": {
                        "instrument_identity_fingerprint_sha256": str(ordinal) * 64
                    },
                    "observation_id": owner_identity(
                        "OBSERVATION_ID", "fixture-owner", f"overflow-{ordinal}"
                    ),
                    "record_type": "candidate-observation",
                }
                for ordinal in (1, 2)
            ],
        ]
        with self.assertRaises(CoverageReconciliationError):
            derive_coverage(overclaimed)

    def test_final_manifest_and_detached_checksum_reconcile_and_resume_after_crash(self) -> None:
        self.append_two_outcomes()
        source_final = source_final_envelope(self.recorder, self.start_raw)
        self.recorder.accept(source_final)
        with self.assertRaises(SimulatedRecorderCrash):
            self.recorder.finalize(SESSION_ID, crash_phase="after_manifest")
        self.assertEqual(1, len(list(self.root.rglob("*.final.json"))))
        self.assertEqual(0, len(list(self.root.rglob("*.sha256"))))
        self.recorder.close()

        resumed = StrategyScienceRecorder(
            self.root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="coverage-resume",
            clock=FixedClock("2026-09-02T00:00:00Z"),
        )
        result = resumed.finalize(SESSION_ID)
        self.assertEqual("IDEMPOTENT_ACK", result.status)
        self.assertEqual(1, len(list(self.root.rglob("*.sha256"))))
        report = resumed.verify(SESSION_ID)
        self.assertTrue(report.final_manifest_present)
        manifest = json.loads(next(self.root.rglob("*.final.json")).read_bytes())
        self.assertTrue(manifest["source_final_reconciliation"]["reconciled"])
        self.assertEqual(0, manifest["source_final_reconciliation"]["declared_pending_source_events"])
        self.assertEqual(2, manifest["coverage"]["accounted_outcome_slots"])
        self.assertEqual("INCOMPLETE_OFFLINE_REFERENCE", manifest["custody_snapshot_classification"])
        self.assertFalse(manifest["science_recorder_provider_contact_occurred"])
        self.assertEqual(
            "OPAQUE_PRODUCER_ASSERTION_ONLY",
            manifest["producer_provider_evidence_classification"],
        )
        self.assertEqual(
            "SCIENCE_CUSTODY_OWNER_PROFILE_V1",
            manifest["science_custody_owner_profile"]["profile"],
        )
        self.assertEqual("NOT_IMPLEMENTED", manifest["post_final_addendum"]["status"])
        sidecar = next(self.root.rglob("*.sha256")).read_text(encoding="ascii")
        self.assertNotIn(".sha256", sidecar)
        self.assertIn(".final.json", sidecar)
        resumed.close()

    def test_checksum_extra_target_is_detected(self) -> None:
        self.append_two_outcomes()
        self.recorder.accept(source_final_envelope(self.recorder, self.start_raw))
        self.recorder.finalize(SESSION_ID)
        self.recorder.close()
        sidecar = next(self.root.rglob("*.sha256"))
        sidecar.write_text(
            sidecar.read_text(encoding="ascii") + f"{'0' * 64}  unexpected.txt\n",
            encoding="ascii",
        )
        reopened = StrategyScienceRecorder(
            self.root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="tamper-sidecar",
            clock=FixedClock(),
        )
        with self.assertRaises(RecorderRecoveryError):
            reopened.verify(SESSION_ID)
        reopened.close()

    def test_duplicate_outcome_slots_are_reconciliation_errors(self) -> None:
        self.append_two_outcomes()
        records = list(self.recorder._all_records(self.recorder._locate_partition(SESSION_ID)))
        first = next(item for item in records if item.get("record_type") == "outcome-observation")
        duplicate = dict(first)
        duplicate["outcome_observation_id"] = owner_identity(
            "OUTCOME_OBSERVATION_ID", "fixture-owner", "duplicate-slot"
        )
        duplicate["record_id"] = duplicate["outcome_observation_id"]
        with self.assertRaises(CoverageReconciliationError):
            derive_coverage([*records, duplicate])

        wrong_parent = dict(first)
        wrong_parent["observation_id"] = owner_identity(
            "OBSERVATION_ID", "fixture-owner", "wrong-coverage-parent"
        )
        corrupted = [wrong_parent if item is first else item for item in records]
        with self.assertRaises(CoverageReconciliationError):
            derive_coverage(corrupted)

    def test_source_gap_and_pending_truth_are_preserved_as_incomplete(self) -> None:
        self.recorder.accept(
            export_envelope(
                "PROVIDER_HEALTH",
                health_payload(terminal=True),
                stream_id="health-stream",
                event_id="terminal-source-gap",
            )
        )
        self.recorder.accept(
            source_final_envelope(
                self.recorder,
                self.start_raw,
                source_gap_count=1,
                pending_source_events=2,
            )
        )
        result = self.recorder.finalize(SESSION_ID)
        self.assertEqual("INCOMPLETE_OFFLINE_REFERENCE", result.custody_classification)
        manifest = json.loads(next(self.root.rglob("*.final.json")).read_bytes())
        reconciliation = manifest["source_final_reconciliation"]
        self.assertEqual(1, reconciliation["declared_source_gap_count"])
        self.assertEqual(2, reconciliation["declared_pending_source_events"])

    def test_zero_slot_session_can_close_custody_snapshot_without_live_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "empty-custody"
            recorder = StrategyScienceRecorder(
                root,
                source_root_identity=SOURCE_ROOT_IDENTITY,
                writer_instance_id="empty-custody",
                clock=FixedClock(),
            )
            try:
                start_raw = start_envelope()
                recorder.accept(start_raw)
                recorder.accept(source_final_envelope(recorder, start_raw))
                result = recorder.finalize(SESSION_ID)
                self.assertEqual("CUSTODY_SNAPSHOT_COMPLETE", result.custody_classification)
                manifest = json.loads(next(root.rglob("*.final.json")).read_bytes())
                self.assertEqual("NOT_PROVEN", manifest["live_capture_qualification"])
                self.assertEqual(
                    "NOT_APPLICABLE",
                    manifest["coverage"]["outcome_accounting_rate_state"],
                )
            finally:
                recorder.close()

    def test_persisted_conflict_can_only_finalize_as_incomplete(self) -> None:
        accepted = export_envelope(
            "PROVIDER_HEALTH",
            health_payload(),
            stream_id="conflicting-health-stream",
            event_id="conflicting-health",
        )
        self.recorder.accept(accepted)
        changed_payload = health_payload()
        changed_payload["provider_health_event"]["reason_code"] = "SOURCE_OUTAGE_CHANGED"
        conflicting = export_envelope(
            "PROVIDER_HEALTH",
            changed_payload,
            stream_id="conflicting-health-stream",
            event_id="conflicting-health",
        )
        with self.assertRaises(RecorderConflictError):
            self.recorder.accept(conflicting)
        self.recorder.accept(
            source_final_envelope(
                self.recorder, self.start_raw, conflict_count=1
            )
        )
        result = self.recorder.finalize(SESSION_ID)
        self.assertEqual("INCOMPLETE_OFFLINE_REFERENCE", result.custody_classification)
        manifest = json.loads(next(self.root.rglob("*.final.json")).read_bytes())
        self.assertEqual(1, manifest["coverage"]["conflicts"])

    def test_accepted_payload_tamper_is_detected_by_receipt_and_final_inventory(self) -> None:
        self.append_two_outcomes()
        self.recorder.accept(source_final_envelope(self.recorder, self.start_raw))
        self.recorder.finalize(SESSION_ID)
        self.recorder.close()
        decision_path = stored_records(self.root, "decision-event")[0][0]
        decision_path.write_bytes(
            decision_path.read_bytes().replace(
                b'"decision_state":"TRADEPLAN"',
                b'"decision_state":"BLOCKED"',
            )
        )
        reopened = StrategyScienceRecorder(
            self.root,
            source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="tamper-payload",
            clock=FixedClock(),
        )
        with self.assertRaises(RecorderRecoveryError):
            reopened.verify(SESSION_ID)
        reopened.close()


if __name__ == "__main__":
    unittest.main()
