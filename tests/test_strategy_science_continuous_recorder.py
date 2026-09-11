"""Offline synthetic receipts only; these fixtures do not reconstruct history."""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter.strategy_science_continuous_recorder import (
    ContinuousRecorderConflict, ContinuousRecorderError, ContinuousScienceRecorder,
    FAMILIES, SimulatedContinuousCrash,
)
from momentum_hunter.strategy_science_recorder.canonical import canonical_json_v1, sha256_hex
from momentum_hunter.strategy_science_recorder.contract import parse_export_envelope_v2, require_time_evidence
from momentum_hunter.strategy_science_recorder.custody import RecorderCustodyError, _capture_time_evidence
from momentum_hunter.strategy_science_source_reader import SimulatedSourceReaderCrash
from momentum_hunter.windows_writer_storage import WriterStorageCrashAfterTemp
from tests.test_strategy_science_source_reader_v2 import InterruptingCursorWrite
from tests.test_strategy_science_recorder_contract import (
    FixedClock, SESSION_ID, SOURCE_ROOT_IDENTITY, OBSERVATION_ID_2, discovery_payload,
    health_payload, market_bar_payload, observation, outcome_attachment,
    source_final_envelope, start_envelope, stored_records, time_evidence,
)
from tests.test_strategy_science_recorder_eligibility_authority import (
    discovery_envelope_v2, export_envelope_v2, sealed_decision_envelope_v2,
    start_envelope_v2, v2_outcome_payload,
)


class TickingClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 1, 22, tzinfo=timezone.utc)

    def __call__(self) -> str:
        result = self.value.isoformat().replace("+00:00", "Z")
        self.value += timedelta(seconds=1)
        return result


def publication(root: Path, raw: bytes, ordinal: int) -> Path:
    """Canonical filename around existing canonical test-fixture bytes."""
    value = json.loads(raw)
    token = sha256_hex(canonical_json_v1({"stream_id": value["stream_id"]}))[:16]
    path = root / f"{ordinal:020d}-{token}-{value['source_sequence']:020d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def core_fixtures() -> tuple[bytes, ...]:
    health = health_payload()
    health["provider_health_event"]["source_event_time"] = time_evidence("SOURCE_EVENT_TIME", "2026-09-01T13:32:00Z")
    discovery = export_envelope_v2(
        "DISCOVERY_CYCLE", discovery_payload([observation(), observation(OBSERVATION_ID_2, ordinal=1)]),
        stream_id="discovery-stream", event_id="discovery-1")
    return (
        start_envelope_v2(), discovery, sealed_decision_envelope_v2(),
        export_envelope_v2("MARKET_FACT", market_bar_payload(), stream_id="market-stream", event_id="bar-1"),
        export_envelope_v2("PROVIDER_HEALTH", health, stream_id="health-stream", event_id="health-1"),
    )


class ContinuousRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="science-continuous-v2-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.published = self.root / "producer" / "published"
        self.published.mkdir(parents=True)
        self.science = self.root / "science"
        self.clock = TickingClock()

    def open(self, **kwargs: object) -> ContinuousScienceRecorder:
        instance = ContinuousScienceRecorder(
            self.published, self.science, source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="synthetic-continuous-test", clock=self.clock, **kwargs,
        )
        self.addCleanup(instance.close)
        return instance

    def populate(self) -> tuple[bytes, ...]:
        raws = core_fixtures()
        for ordinal, raw in enumerate(raws, 1):
            publication(self.published, raw, ordinal)
        return raws

    def test_all_seven_families_raw_readback_outcome_denominator_restart(self) -> None:
        raws = self.populate()
        source_before = {p.name: p.read_bytes() for p in self.published.iterdir()}
        recorder = self.open(lateness_seconds=60)
        result = recorder.poll()
        self.assertEqual(5, result["admitted"])
        before = recorder.coverage()["canonical"]
        self.assertEqual(2, before["candidate_observations"])
        self.assertEqual(1, before["material_decisions"])
        self.assertGreater(before["unaccounted_outcome_slots"], 0)
        prediction = {p: raw for p, _value, raw in stored_records(self.science / "custody", "decision-event")}
        attachment = outcome_attachment(v2_outcome_payload(self.science / "custody"))
        self.assertEqual("ACCEPTED", recorder.append_outcome(attachment)["status"])
        self.assertEqual("IDEMPOTENT_ACK", recorder.append_outcome(attachment)["status"])
        coverage = recorder.coverage()
        self.assertTrue(all(coverage["family_counts"][family] >= 1 for family in FAMILIES))
        self.assertEqual(1, coverage["canonical"]["received_outcome_slots"])
        self.assertEqual(before["expected_outcome_slots"], coverage["canonical"]["expected_outcome_slots"])
        self.assertEqual("NOT_PROVEN", coverage["independent_sample_count"])
        self.assertEqual(tuple(raws) + (attachment,), tuple(recorder.raw_bytes(a["arrival_id"]) for a in recorder.arrivals()))
        self.assertEqual(prediction, {p: p.read_bytes() for p in prediction})
        arrivals = recorder.arrivals()
        recorder.close()
        reopened = self.open(lateness_seconds=60)
        self.assertEqual(0, reopened.run(polls=3, max_items=1)[-1]["admitted"])
        self.assertEqual(arrivals, reopened.arrivals())
        self.assertEqual(coverage["family_counts"], reopened.coverage()["family_counts"])
        self.assertEqual(source_before, {p.name: p.read_bytes() for p in self.published.iterdir()})

    def test_future_delivery_preserves_first_receipt_gap_then_later_eligibility_clock(self) -> None:
        raw = discovery_envelope_v2()
        publication(self.published, raw, 2)
        recorder = self.open()
        first = recorder.poll()["coverage"]
        arrival = recorder.arrivals()[0]
        self.assertEqual(1, first["pending_count"])
        self.assertEqual(0, first["canonical"]["candidate_observations"])
        self.assertEqual("PUBLICATION", first["gaps"][0]["kind"])
        recorder.close()
        self.clock.value += timedelta(hours=1)
        publication(self.published, start_envelope_v2(), 1)
        recorder = self.open()
        after = recorder.poll()["coverage"]
        same = next(a for a in recorder.arrivals() if a["arrival_id"] == arrival["arrival_id"])
        self.assertEqual(arrival["receipt_time"], same["receipt_time"])
        self.assertEqual([], after["gaps"])
        self.assertTrue(any(row["gaps"] for row in after["gap_history"]))
        eligibility = stored_records(self.science / "custody", "science-eligibility")[0][1]["science_eligibility"]
        self.assertGreater(eligibility["science_evaluated_at"]["normalized_rfc3339"], arrival["receipt_time"])
        self.assertEqual(1, after["canonical"]["candidate_observations"])

    def test_receipt_producer_and_persistence_times_are_distinct(self) -> None:
        publication(self.published, start_envelope_v2(), 1)
        recorder = self.open()
        recorder.poll()
        arrival = recorder.arrivals()[0]
        self.assertLess(arrival["metadata"]["event_time"], arrival["receipt_time"])
        self.assertLess(arrival["receipt_time"], arrival["persistence_begin"])
        self.assertLess(arrival["persistence_begin"], arrival["persistence"]["persistence_time"])
        self.assertLess(arrival["persistence"]["persistence_time"], arrival["admission"]["admission_persistence_time"])
        self.assertEqual("UNKNOWN", recorder.coverage()["lateness_classification"])

    def test_exact_clock_precision_truth_table_preserves_all_timestamp_bytes(self) -> None:
        checked = 0
        for digits in range(10):
            for suffix in ("Z", "+02:00", "-05:00"):
                fraction = "." + "123456789"[:digits] if digits else ""
                stamp = f"2026-09-11T14:00:00{fraction}{suffix}"
                with self.subTest(digits=digits, suffix=suffix):
                    evidence = _capture_time_evidence(stamp)
                    require_time_evidence(evidence, "clock_truth_table", role="RECORDER_CAPTURE_TIME")
                    self.assertEqual(stamp, evidence["raw_value"])
                    self.assertEqual(stamp, evidence["normalized_rfc3339"])
                    self.assertEqual(suffix, evidence["timezone_or_offset"])
                    self.assertEqual(f"fractional-{digits}" if digits else "second", evidence["precision"])
                    checked += 1
        self.assertEqual(30, checked)

    def test_actual_fractional_clock_all_families_outcome_and_restart(self) -> None:
        sampled = []
        def actual_clock():
            stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            sampled.append(stamp)
            return stamp
        self.clock = actual_clock
        self.populate()
        recorder = self.open()
        recorder.poll()
        attachment = outcome_attachment(v2_outcome_payload(recorder.custody_root))
        recorder.append_outcome(attachment)
        before = recorder.arrivals()
        self.assertTrue(all(recorder.coverage()["family_counts"][family] for family in FAMILIES))
        for record in recorder.records():
            evidence = record["recorder_capture_time"]
            require_time_evidence(evidence, "real_clock", role="RECORDER_CAPTURE_TIME")
            self.assertEqual("fractional-6", evidence["precision"])
            self.assertIn(evidence["raw_value"], sampled)
            self.assertEqual(evidence["raw_value"], evidence["normalized_rfc3339"])
        recorder.close()
        recorder = self.open()
        self.assertEqual(0, recorder.poll()["admitted"])
        self.assertEqual(before, recorder.arrivals())
        self.assertEqual("IDEMPOTENT_ACK", recorder.append_outcome(attachment)["status"])

    def test_actual_fractional_clock_partial_receipt_recovery_uses_new_evaluation(self) -> None:
        sampled = []
        def actual_clock():
            stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
            sampled.append(stamp)
            return stamp
        self.clock = actual_clock
        self.populate()
        recorder = self.open()
        recorder.poll(max_items=1)
        original = recorder.recorder.accept
        with patch.object(recorder.recorder, "accept", side_effect=lambda raw: original(
            raw, crash_phase="after_candidate_observation_receipt")):
            with self.assertRaises(Exception):
                recorder.poll(max_items=1)
        first_receipt = recorder.arrivals()[1]["receipt_time"]
        recorder.close()
        recorder = self.open()
        recorder.poll()
        eligibility = stored_records(recorder.custody_root, "science-eligibility")[0][1]["science_eligibility"]
        self.assertGreater(eligibility["science_evaluated_at"]["normalized_rfc3339"], first_receipt)
        self.assertEqual(first_receipt, recorder.arrivals()[1]["receipt_time"])
        self.assertIn(eligibility["science_evaluated_at"]["normalized_rfc3339"], sampled)

    def test_event_disorder_and_half_open_windows_need_no_opening_start(self) -> None:
        self.populate()  # Health event-time precedes the earlier-delivered market bar.
        recorder = self.open(lateness_seconds=0)
        recorder.poll()
        self.assertTrue(recorder.coverage()["event_time_disordered_arrivals"])
        self.assertEqual(5, len(recorder.coverage()["late_arrivals"]))
        selected = recorder.query_window("2026-09-01T13:31:00Z", "2026-09-01T13:31:31Z", axis="event", session_id=SESSION_ID)
        self.assertTrue(selected)
        self.assertTrue(all(a["metadata"]["event_time"] < "2026-09-01T13:31:31Z" for a in selected))
        self.assertEqual((), recorder.query_window("2026-09-10T13:35:00Z", "2026-09-10T13:36:00Z", axis="event"))
        with self.assertRaises(ContinuousRecorderError):
            recorder.query_window("2026-09-01T14:00:00Z", "2026-09-01T13:00:00Z")

    def test_all_declared_arrival_and_reader_crash_windows_recover_without_duplicates(self) -> None:
        phases = ("after_arrival_temp", "after_arrival", "after_persistence_marker",
                  "after_custody_before_cursor", "after_cursor_commit", "after_admission")
        for phase in phases:
            with self.subTest(phase=phase):
                self.science = self.root / phase
                publication(self.published, start_envelope_v2(), 1)
                recorder = self.open()
                with self.assertRaises((SimulatedContinuousCrash, SimulatedSourceReaderCrash, WriterStorageCrashAfterTemp)):
                    recorder.poll(crash_phase=phase)
                known = recorder.arrivals()
                recorder.close()
                recorder = self.open()
                recorder.poll()
                recorder.poll()
                self.assertEqual(1, recorder.coverage()["admitted_arrival_count"])
                self.assertEqual(1, recorder.coverage()["raw_arrival_count"])
                arrival = recorder.arrivals()[0]
                if known:
                    self.assertEqual(known[0]["receipt_time"], arrival["receipt_time"])
                if phase == "after_arrival":
                    self.assertEqual("UNKNOWN", arrival["persistence"]["persistence_time"])
                    self.assertEqual("RECOVERED_ORIGINAL_TIME_UNKNOWN", arrival["persistence"]["classification"])
                if phase in {"after_cursor_commit", "after_admission"}:
                    self.assertEqual("UNKNOWN", arrival["admission"]["admission_persistence_time"])
                recorder.close()

    def test_partial_batch_restart_and_duplicate_outcome_recovery(self) -> None:
        self.populate()
        recorder = self.open()
        self.assertEqual(2, recorder.poll(max_items=2)["admitted"])
        recorder.close()
        recorder = self.open()
        self.assertEqual(3, recorder.poll()["admitted"])
        attachment = outcome_attachment(v2_outcome_payload(self.science / "custody"))
        with self.assertRaises(SimulatedContinuousCrash):
            recorder.append_outcome(attachment, crash_phase="after_admission")
        recorder.close()
        recorder = self.open()
        self.assertEqual("IDEMPOTENT_ACK", recorder.append_outcome(attachment)["status"])
        self.assertEqual(1, recorder.coverage()["family_counts"]["outcome-observation"])

    def test_canonical_partial_record_recovery_keeps_first_receipt_and_raw(self) -> None:
        self.populate()
        recorder = self.open()
        recorder.poll(max_items=1)
        original = recorder.recorder.accept
        def interrupted(raw: bytes):
            return original(raw, crash_phase="after_payload")
        with patch.object(recorder.recorder, "accept", side_effect=interrupted):
            with self.assertRaises(Exception):
                recorder.poll(max_items=1)
        recorder.close()
        recorder = self.open()
        self.assertFalse(recorder.coverage()["admission_frozen"])
        recorder.poll()
        self.assertEqual(2, recorder.coverage()["canonical"]["candidate_observations"])

    def test_receipt_before_first_eligibility_recovers_at_actual_later_clock(self) -> None:
        self.populate()
        recorder = self.open()
        recorder.poll(max_items=1)
        original = recorder.recorder.accept
        with patch.object(recorder.recorder, "accept", side_effect=lambda raw: original(
            raw, crash_phase="after_candidate_observation_receipt")):
            with self.assertRaises(Exception):
                recorder.poll(max_items=1)
        first_receipt = recorder.arrivals()[-1]["receipt_time"]
        self.assertEqual([], stored_records(self.science / "custody", "science-eligibility"))
        with self.assertRaises((RecorderCustodyError, ValueError)):
            recorder.records()
        recorder.close()
        self.clock.value += timedelta(hours=2)
        recorder = self.open()
        recorder.poll()
        eligibility = stored_records(self.science / "custody", "science-eligibility")[0][1]["science_eligibility"]
        self.assertGreater(eligibility["science_evaluated_at"]["normalized_rfc3339"], first_receipt)
        self.assertEqual(first_receipt, recorder.arrivals()[1]["receipt_time"])

    @unittest.skipUnless(os.name == "nt", "Windows physical write primitive qualification")
    def test_actual_short_arrival_write_is_quarantined_never_admitted(self) -> None:
        import momentum_hunter.windows_writer_storage as physical
        publication(self.published, start_envelope_v2(), 1)
        recorder = self.open()
        original = physical._write_handle
        evidence = {}
        def interrupt(handle, raw):
            if handle.path.parent == recorder._storage.root / ".partial" and b'"type":"ARRIVAL"' in raw:
                evidence["attempted"] = len(raw)
                evidence["written"] = len(raw) // 2
                original(handle, raw[:evidence["written"]])
                raise physical.WriterPhysicalStorageError("synthetic physical short arrival write")
            return original(handle, raw)
        with patch.object(physical, "_write_handle", side_effect=interrupt):
            with self.assertRaises(physical.WriterPhysicalStorageError):
                recorder.poll()
        self.assertGreater(evidence["written"], 0)
        self.assertLess(evidence["written"], evidence["attempted"])
        self.assertEqual((), recorder.arrivals())
        partial = next((self.science / "arrivals" / ".partial").glob("*.tmp"))
        partial_raw = partial.read_bytes()
        recorder.close()
        recorder = self.open()
        self.assertIn(partial_raw, [p.read_bytes() for p in (self.science / "arrivals" / ".quarantine").glob("*.tmp")])
        recorder.poll()
        self.assertEqual(1, recorder.coverage()["admitted_arrival_count"])

    def test_actual_short_cursor_write_preserves_prior_cursor_and_replays_once(self) -> None:
        self.populate()
        recorder = self.open()
        recorder.poll(max_items=1)
        prior = next((self.science / "reader" / "cursors").glob("*.json"))
        prior_raw = prior.read_bytes()
        original = Path.open
        evidence = {}
        def interrupt(path, mode="r", *args, **kwargs):
            handle = original(path, mode, *args, **kwargs)
            if mode == "xb" and path.parent == self.science / "reader" / "cursors" / ".partial":
                return InterruptingCursorWrite(handle, evidence)
            return handle
        with patch.object(Path, "open", interrupt):
            with self.assertRaises(OSError):
                recorder.poll(max_items=1)
        self.assertLess(evidence["written"], evidence["attempted"])
        self.assertEqual(prior_raw, prior.read_bytes())
        recorder.close()
        recorder = self.open()
        recorder.poll()
        self.assertEqual(2, recorder.coverage()["canonical"]["candidate_observations"])
        self.assertEqual(prior_raw, prior.read_bytes())

    def test_readback_checks_mutated_ledger_without_a_poll(self) -> None:
        publication(self.published, start_envelope_v2(), 1)
        recorder = self.open()
        recorder.poll()
        key = recorder.arrivals()[0]["arrival_id"]
        target = next((self.science / "arrivals" / "ledger").glob(f"*-{key}.event.json"))
        target.write_bytes(target.read_bytes()[:-4])
        for operation in (recorder.arrivals, recorder.records,
                          lambda: recorder.raw_bytes(key),
                          lambda: recorder.query_window("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z")):
            with self.assertRaises(ContinuousRecorderError):
                operation()

    def test_disappeared_pending_publication_stays_an_explicit_gap(self) -> None:
        path = publication(self.published, discovery_envelope_v2(), 2)
        recorder = self.open()
        recorder.poll()
        path.unlink()
        coverage = recorder.poll()["coverage"]
        self.assertEqual("MISSING_OBSERVED_PUBLICATION", coverage["gaps"][0]["kind"])
        self.assertEqual(1, coverage["pending_count"])

    def test_zero_or_exhausted_budget_never_erases_an_unresolved_gap(self) -> None:
        publication(self.published, start_envelope_v2(), 1)
        publication(self.published, discovery_envelope_v2(), 3)
        recorder = self.open()
        first = recorder.poll()["coverage"]
        self.assertEqual(2, first["gaps"][0]["first_missing"])
        before = first["gap_history"]
        for budget in (0, 1, 100):
            coverage = recorder.poll(max_items=budget)["coverage"]
            self.assertEqual(first["gaps"], coverage["gaps"])
            self.assertEqual(before, coverage["gap_history"])

    def test_conflicting_raw_is_retained_and_freeze_survives_restore_and_restart(self) -> None:
        original = start_envelope_v2()
        path = publication(self.published, original, 1)
        recorder = self.open()
        recorder.poll()
        value = json.loads(original)
        value["source_event_fingerprint_sha256"] = "a" * 64
        changed = canonical_json_v1(value)
        path.write_bytes(changed)
        with self.assertRaises(ContinuousRecorderConflict):
            recorder.poll()
        self.assertEqual(2, recorder.coverage()["raw_arrival_count"])
        self.assertIn(changed, tuple(recorder.raw_bytes(a["arrival_id"]) for a in recorder.arrivals()))
        recorder.close()
        path.write_bytes(original)
        recorder = self.open()
        with self.assertRaises(ContinuousRecorderConflict):
            recorder.poll()
        self.assertEqual(1, recorder.coverage()["conflicts"])

    def test_schema_version_profile_unknown_fields_and_partial_bytes_rejected_with_raw(self) -> None:
        base = json.loads(start_envelope_v2())
        cases = [start_envelope(), start_envelope_v2()[:-20]]
        for field in ("schema_version", "source_contract", "source_contract_version", "offline_reference_profile", "execution_authority"):
            value = dict(base)
            value[field] = "UNSUPPORTED"
            cases.append(canonical_json_v1(value))
        value = dict(base, unknown_field="unsupported")
        cases.append(canonical_json_v1(value))
        for index, raw in enumerate(cases):
            with self.subTest(index=index):
                self.science = self.root / f"reject-{index}"
                path = publication(self.published, start_envelope_v2(), 1)
                path.write_bytes(raw)
                recorder = self.open()
                with self.assertRaises(ContinuousRecorderConflict):
                    recorder.poll()
                self.assertEqual(raw, recorder.raw_bytes(recorder.arrivals()[0]["arrival_id"]))
                self.assertEqual(0, recorder.coverage()["admitted_arrival_count"])
                recorder.close()

    def test_same_session_owner_and_interface_drift_fails_before_normal_admission(self) -> None:
        for field in ("source_owner_identity", "source_interface_identity"):
            with self.subTest(field=field):
                self.science = self.root / field
                publication(self.published, start_envelope_v2(), 1)
                value = json.loads(discovery_envelope_v2())
                value[field] = "changed-owner-domain"
                publication(self.published, canonical_json_v1(value), 2)
                recorder = self.open()
                with self.assertRaises(ContinuousRecorderConflict):
                    recorder.poll()
                self.assertEqual(0, recorder.coverage()["canonical"]["candidate_observations"])
                recorder.close()

    def test_missing_source_sequence_is_pending_not_an_observation(self) -> None:
        publication(self.published, start_envelope_v2(), 1)
        value = json.loads(discovery_envelope_v2())
        value["source_sequence"] = 2
        value["previous_record_sha256"] = "b" * 64
        publication(self.published, canonical_json_v1(value), 2)
        recorder = self.open()
        coverage = recorder.poll()["coverage"]
        self.assertEqual("SOURCE_SEQUENCE", coverage["gaps"][0]["kind"])
        self.assertEqual(1, coverage["pending_count"])
        self.assertEqual(0, coverage["canonical"]["candidate_observations"])

    def test_missing_or_truncated_authoritative_ledger_fails_closed(self) -> None:
        for mode in ("missing", "truncated", "corrupt"):
            with self.subTest(mode=mode):
                self.science = self.root / mode
                publication(self.published, start_envelope_v2(), 1)
                recorder = self.open()
                recorder.poll()
                recorder.close()
                paths = sorted((self.science / "arrivals" / "ledger").glob("*.event.json"))
                target = paths[2]
                if mode == "missing":
                    target.unlink()
                elif mode == "truncated":
                    target.write_bytes(target.read_bytes()[:-1])
                else:
                    target.write_bytes(target.read_bytes().replace(b"RECEIVED", b"RECEIVEZ"))
                with self.assertRaises(ContinuousRecorderError):
                    self.open()

    def test_missing_or_truncated_canonical_source_or_payload_fails_closed(self) -> None:
        for suffix, mode in (("*.source.json", "missing"), ("*.payload.json", "truncated")):
            with self.subTest(suffix=suffix):
                self.science = self.root / mode
                publication(self.published, start_envelope_v2(), 1)
                recorder = self.open()
                recorder.poll()
                recorder.close()
                target = next((self.science / "custody").rglob(suffix))
                if mode == "missing":
                    target.unlink()
                else:
                    target.write_bytes(target.read_bytes()[:11])
                with self.assertRaises((ContinuousRecorderError, RecorderCustodyError, ValueError)):
                    self.open()

    def test_post_final_outcome_is_retained_rejected_without_prediction_overwrite(self) -> None:
        self.populate()
        recorder = self.open()
        recorder.poll()
        attachment = outcome_attachment(v2_outcome_payload(self.science / "custody"))
        legacy_final = json.loads(source_final_envelope(recorder.recorder, start_envelope_v2()))
        final = export_envelope_v2(
            "SESSION_MANIFEST", legacy_final["payload"], stream_id="session-stream",
            event_id="session-final", sequence=2, previous=sha256_hex(start_envelope_v2()),
        )
        publication(self.published, final, 6)
        recorder.poll()
        before = {p: raw for p, _value, raw in stored_records(self.science / "custody", "decision-event")}
        with self.assertRaises(ContinuousRecorderError):
            recorder.append_outcome(attachment)
        coverage = recorder.coverage()
        self.assertEqual(1, coverage["rejected_count"])
        self.assertEqual(0, coverage["family_counts"]["outcome-observation"])
        self.assertIn("Source-finalized", recorder.arrivals()[-1]["rejection"]["reason"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_source_root_binding_and_disjoint_roots(self) -> None:
        recorder = self.open()
        recorder.close()
        with self.assertRaises(ContinuousRecorderError):
            ContinuousScienceRecorder(self.published, self.science, source_root_identity="8" * 64,
                                      writer_instance_id="changed", clock=self.clock)
        for root in (self.published, self.published.parent, self.published.parent / "state", self.root):
            with self.subTest(root=root), self.assertRaises(ContinuousRecorderError):
                ContinuousScienceRecorder(self.published, root, source_root_identity=SOURCE_ROOT_IDENTITY,
                                          writer_instance_id="overlap", clock=self.clock)

    def test_second_writer_cannot_own_the_same_root(self) -> None:
        self.open()
        with self.assertRaises(Exception):
            self.open()

    def test_dormant_no_control_or_network_imports_and_explicit_budgets(self) -> None:
        import momentum_hunter.strategy_science_continuous_recorder as module
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        allowed = {
            "__future__", "base64", "collections", "pathlib", "re", "typing",
            "momentum_hunter.continuous_research_export", "momentum_hunter.strategy_science_recorder.canonical",
            "momentum_hunter.strategy_science_recorder.contract", "momentum_hunter.strategy_science_recorder.coverage",
            "momentum_hunter.strategy_science_recorder.custody", "momentum_hunter.strategy_science_recorder.outcomes",
            "momentum_hunter.strategy_science_source_reader", "momentum_hunter.windows_writer_storage",
        }
        self.assertEqual(set(imports), allowed)
        recorder = self.open()
        self.assertEqual((), recorder.run(polls=0))
        for budget in (-1, True, 1.5):
            with self.assertRaises(ContinuousRecorderError):
                recorder.run(polls=budget)
        self.assertEqual("NONE", recorder.coverage()["execution_authority"])


if __name__ == "__main__":
    unittest.main()
