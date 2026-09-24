"""Focused diagnostic-only Science readiness lineage checks."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from momentum_hunter import continuous_host_lifecycle as lifecycle
from momentum_hunter.continuous_host_lifecycle import science_state
from momentum_hunter.science_custody_commit import CustodyCommitIntegrityError
from momentum_hunter.science_readiness_trace_020y import ScienceReadinessTrace, open_020y_trace
from momentum_hunter.strategy_science_continuous_recorder import ContinuousScienceRecorder
from momentum_hunter.strategy_science_source_reader import SimulatedSourceReaderCrash
from tests.test_strategy_science_continuous_recorder import TickingClock, publication
from tests.test_strategy_science_recorder_contract import SOURCE_ROOT_IDENTITY
from tests.test_strategy_science_recorder_eligibility_authority import start_envelope_v2


GENERATION = "12345678-1234-1234-1234-123456789abc"


class ScienceReadinessTrace020YTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="science-readiness-020y-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.published = self.root / "producer" / "published"
        self.published.mkdir(parents=True)
        self.science = self.root / "science"
        self.config = {"host": {"instanceId": "qual-015-020y-focused"},
                       "logRoot": str(self.root / "logs")}

    def trace(self):
        trace = open_020y_trace(self.config, generation=GENERATION)
        self.addCleanup(trace.close)
        return trace

    def recorder(self, trace):
        recorder = ContinuousScienceRecorder(
            self.published, self.science, source_root_identity=SOURCE_ROOT_IDENTITY,
            writer_instance_id="synthetic-020y-test", clock=TickingClock(),
            readiness_trace=trace)
        self.addCleanup(recorder.close)
        return recorder

    def rows(self, trace):
        trace.close()
        if hasattr(trace, "_thread") and trace._thread is not None:
            trace._thread.join(timeout=2)
        path = Path(self.config["logRoot"]) / "science" / f"readiness-trace-{GENERATION}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]

    def health(self):
        path = Path(self.config["logRoot"]) / "science" / f"readiness-trace-{GENERATION}-health.json"
        return json.loads(path.read_text(encoding="ascii"))

    def test_first_publication_binds_raw_and_normalized_identity(self):
        raw = start_envelope_v2()
        publication(self.published, raw, 1)
        trace = self.trace()
        recorder = self.recorder(trace)
        result = recorder.poll()
        self.assertEqual(1, result["admitted"])
        self.assertGreater(result["coverage"]["raw_arrival_count"], 0)
        self.assertGreater(result["coverage"]["normalized_record_count"], 0)
        self.assertEqual("HEALTHY", science_state(result["coverage"]))
        rows = self.rows(trace)
        self.assertEqual(["source_observed", "raw_persisted", "admission_started",
                          "normalization_completed", "normalized_observed", "trace_closed"],
                         [row["event"] for row in rows])
        self.assertEqual({GENERATION}, {row["generation"] for row in rows})
        self.assertEqual(1, len({row["raw_id"] for row in rows if "raw_id" in row}))
        self.assertEqual(1, len({row["source_id"] for row in rows if "source_id" in row}))
        self.assertEqual(rows[-3]["normalized_ids"], rows[-2]["normalized_ids"])
        self.assertTrue(rows[-2]["normalized_ids"])
        self.assertEqual(0, rows[-1]["lost_events"])
        self.assertEqual(0, self.health()["lost_events"])
        self.assertEqual(len(rows), self.health()["written_events"])
        trace_path = Path(self.config["logRoot"]) / "science" / f"readiness-trace-{GENERATION}.jsonl"
        self.assertEqual(hashlib.sha256(trace_path.read_bytes()).hexdigest().upper(),
                         self.health()["trace_sha256"])

    def test_absent_publication_emits_no_arrival_or_normalization(self):
        trace = self.trace()
        recorder = self.recorder(trace)
        result = recorder.poll()
        self.assertEqual(0, result["coverage"]["raw_arrival_count"])
        self.assertEqual("STARTING", science_state(result["coverage"]))
        self.assertEqual(["trace_closed"], [row["event"] for row in self.rows(trace)])

    def test_failed_admission_has_no_false_normalized_observation(self):
        publication(self.published, start_envelope_v2(), 1)
        trace = self.trace()
        recorder = self.recorder(trace)
        with patch.object(recorder.reader, "admit", side_effect=OSError("bounded interruption")):
            with self.assertRaises(OSError):
                recorder.poll()
        rows = self.rows(trace)
        self.assertEqual("admission_interrupted", rows[-2]["event"])
        self.assertEqual("UNKNOWN", rows[-2]["commit_outcome"])
        self.assertNotIn("normalized_observed", [row["event"] for row in rows])
        self.assertNotIn("normalization_completed", [row["event"] for row in rows])

    def test_post_commit_crash_does_not_claim_normalization_failure(self):
        publication(self.published, start_envelope_v2(), 1)
        for phase in ("after_custody_before_cursor", "after_cursor_commit"):
            with self.subTest(phase=phase):
                self.science = self.root / phase
                self.config["logRoot"] = str(self.root / ("logs-" + phase))
                trace = self.trace()
                recorder = self.recorder(trace)
                with self.assertRaises(SimulatedSourceReaderCrash):
                    recorder.poll(crash_phase=phase)
                rows = self.rows(trace)
                interrupted = [row for row in rows if row["event"] == "admission_interrupted"]
                self.assertEqual(1, len(interrupted))
                self.assertEqual("UNKNOWN", interrupted[0]["commit_outcome"])
                self.assertNotIn("normalization_failed", [row["event"] for row in rows])

    def test_trace_io_failures_do_not_change_recorder_result(self):
        publication(self.published, start_envelope_v2(), 1)
        trace = self.trace()
        recorder = self.recorder(trace)
        with patch("momentum_hunter.science_readiness_trace_020y.os.write", side_effect=OSError("diagnostic write")):
            result = recorder.poll()
            trace.close()
            trace._thread.join(timeout=2)
        self.assertEqual(1, result["admitted"])
        self.assertGreater(self.health()["lost_events"], 0)
        self.assertEqual("HEALTHY", science_state(result["coverage"]))

    def test_open_flush_and_close_failures_are_diagnostic_only(self):
        path = self.root / "trace.jsonl"
        with patch("momentum_hunter.science_readiness_trace_020y.os.open", side_effect=OSError("open")):
            unavailable = ScienceReadinessTrace(path, GENERATION)
            unavailable("source_observed")
            unavailable.close()
            unavailable._thread.join(timeout=2)
        self.assertGreater(unavailable.lost_events, 0)

        working = ScienceReadinessTrace(self.root / "working.jsonl", GENERATION)
        working("source_observed")
        real_close = os.close
        def close_then_fail(handle):
            real_close(handle)
            raise OSError("close result unavailable")
        with patch("momentum_hunter.science_readiness_trace_020y.os.fsync", side_effect=OSError("flush")), \
             patch("momentum_hunter.science_readiness_trace_020y.os.close", side_effect=close_then_fail):
            working.close()
            working._thread.join(timeout=2)
        self.assertGreaterEqual(working.lost_events, 2)
        self.assertEqual("HEALTH:OSError", working.last_error)

    def test_blocked_diagnostic_write_never_blocks_admission_or_shutdown(self):
        path = self.root / "blocked.jsonl"
        publication(self.published, start_envelope_v2(), 1)
        entered, release = threading.Event(), threading.Event()
        real_write = os.write
        def blocked_write(handle, raw):
            entered.set()
            self.assertTrue(release.wait(timeout=2))
            return real_write(handle, raw)
        with patch("momentum_hunter.science_readiness_trace_020y.os.write", side_effect=blocked_write):
            trace = ScienceReadinessTrace(path, GENERATION)
            started = time.monotonic()
            trace("source_observed", raw_id="bounded")
            self.assertLess(time.monotonic() - started, 0.25)
            self.assertTrue(entered.wait(timeout=2))
            recorder = self.recorder(trace)
            started = time.monotonic()
            result = recorder.poll()
            self.assertEqual(1, result["admitted"])
            self.assertEqual("HEALTHY", science_state(result["coverage"]))
            self.assertLess(time.monotonic() - started, 1.5)
            started = time.monotonic()
            trace.close()
            self.assertLess(time.monotonic() - started, 0.8)
            release.set()
            trace._thread.join(timeout=2)
        self.assertFalse(trace._thread.is_alive())
        health = json.loads((self.root / "blocked-health.json").read_text(encoding="ascii"))
        self.assertEqual(0, health["lost_events"])
        self.assertEqual(health["trace_bytes"], path.stat().st_size)

    def test_full_queue_reports_loss_without_waiting_for_diagnostic_sink(self):
        path = self.root / "full.jsonl"
        entered, release = threading.Event(), threading.Event()
        real_write = os.write
        def blocked_write(handle, raw):
            entered.set()
            self.assertTrue(release.wait(timeout=2))
            return real_write(handle, raw)
        with patch("momentum_hunter.science_readiness_trace_020y.os.write", side_effect=blocked_write):
            trace = ScienceReadinessTrace(path, GENERATION)
            trace("source_observed")
            self.assertTrue(entered.wait(timeout=2))
            started = time.monotonic()
            for _ in range(150):
                trace("science_status", state="STARTING")
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertGreater(trace.lost_events, 0)
            trace.close()
            release.set()
            trace._thread.join(timeout=2)
        self.assertFalse(trace._thread.is_alive())
        self.assertGreater(json.loads((self.root / "full-health.json").read_text(encoding="ascii"))["lost_events"], 0)

    def test_health_sync_failure_never_creates_a_clean_final_health_receipt(self):
        path = self.root / "health-fail.jsonl"
        real_fsync = os.fsync
        calls = 0
        def fail_health_sync(handle):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("health fsync")
            return real_fsync(handle)
        with patch("momentum_hunter.science_readiness_trace_020y.os.fsync", side_effect=fail_health_sync):
            trace = ScienceReadinessTrace(path, GENERATION)
            trace("source_observed")
            trace.close()
            trace._thread.join(timeout=2)
        self.assertFalse(trace.health_committed)
        self.assertFalse((self.root / "health-fail-health.json").exists())
        self.assertTrue((self.root / "health-fail-health.json.partial").exists())
        self.assertEqual("HEALTH:OSError", trace.last_error)

    def test_recovered_counts_do_not_claim_new_lineage(self):
        config = {**self.config,
                  "host": {"instanceId": "qual-015-020y-focused",
                           "shutdownSeconds": 10,
                           "science": {"maxItems": 1, "pollSeconds": 0,
                                       "stateRoot": str(self.science)}},
                  "researchFactExportV2": {"exportRoot": str(self.root / "producer")},
                  "runtimeBuildHash": SOURCE_ROOT_IDENTITY,
                  "hostFingerprint": "focused-test"}
        statuses = []
        host = SimpleNamespace(generation=GENERATION,
                               status=lambda state, **detail: statuses.append((state, detail)))
        coverage = {"raw_arrival_count": 1, "normalized_record_count": 1,
                    "admitted_arrival_count": 1, "gaps": []}
        recorder = MagicMock()
        recorder.coverage.return_value = coverage
        recorder.poll.return_value = {"observed": 0, "admitted": 0, "coverage": coverage}
        recorder.reader.consume_available.return_value.cursor = SimpleNamespace(
            last_publication_ordinal=1, terminal=True, final_disposition="FINAL")
        storage = MagicMock()
        storage.backend.security_contract_evidence = {
            "profile": "TEST", "policy_sha256": "test", "role": "science",
            "token": {}, "exact_owner_dacl_label_policy_verified": True}
        with patch.object(lifecycle, "upstream_generations", return_value={"writer": "w", "runtime": "r"}), \
             patch.object(lifecycle, "open_host_science_storage", return_value=storage), \
             patch.object(lifecycle, "completion", return_value=True), \
             patch.object(lifecycle.time, "sleep"), \
             patch("momentum_hunter.strategy_science_continuous_recorder.ContinuousScienceRecorder",
                   return_value=recorder):
            stop = threading.Event()
            stop.set()
            self.assertEqual(0, lifecycle.run_science(config, stop, host))
        rows = self.rows(SimpleNamespace(close=lambda: None))
        snapshot = [row for row in rows if row["event"] == "recovery_snapshot"]
        self.assertEqual(1, len(snapshot))
        self.assertEqual("UNKNOWN_WITHOUT_PER_EVENT_TRACE", snapshot[0]["historical_lineage"])
        self.assertEqual({"writer": "w", "runtime": "r"}, snapshot[0]["dependencies"])
        self.assertEqual(1, snapshot[0]["raw_arrival_count"])
        self.assertEqual("STOPPED", statuses[-1][0])
        self.assertEqual(0, self.health()["lost_events"])

    def test_storage_close_failure_still_finalizes_trace(self):
        (self.root / "logs" / "science").mkdir(parents=True)
        config = {**self.config,
                  "host": {"instanceId": "qual-015-020y-focused",
                           "shutdownSeconds": 10,
                           "science": {"maxItems": 1, "pollSeconds": 0,
                                       "stateRoot": str(self.science)}},
                  "researchFactExportV2": {"exportRoot": str(self.root / "producer")},
                  "runtimeBuildHash": SOURCE_ROOT_IDENTITY,
                  "hostFingerprint": "focused-test"}
        host = SimpleNamespace(generation=GENERATION, status=lambda state, **detail: None)
        storage = MagicMock()
        storage.backend.security_contract_evidence = {
            "profile": "TEST", "policy_sha256": "test", "role": "science",
            "token": {}, "exact_owner_dacl_label_policy_verified": True}
        storage.close.side_effect = OSError("storage close failure")
        traces = []
        def capture_trace(cfg, *, generation):
            trace = open_020y_trace(cfg, generation=generation)
            traces.append(trace)
            return trace
        with patch.object(lifecycle, "upstream_generations", return_value={"writer": "w", "runtime": "r"}), \
             patch.object(lifecycle, "open_host_science_storage", return_value=storage), \
             patch("momentum_hunter.strategy_science_continuous_recorder.ContinuousScienceRecorder",
                   side_effect=ValueError("recorder open failure")), \
             patch("momentum_hunter.science_readiness_trace_020y.open_020y_trace",
                   side_effect=capture_trace):
            with self.assertRaisesRegex(OSError, "storage close failure"):
                lifecycle.run_science(config, threading.Event(), host)
        self.assertEqual(1, storage.close.call_count)
        self.assertEqual(1, len(traces))
        traces[0]._thread.join(timeout=2)
        self.assertTrue(traces[0].health_committed)
        self.assertEqual("trace_closed", self.rows(traces[0])[-1]["event"])

    def test_host_failure_receipt_preserves_exact_custody_request(self):
        (self.root / "logs" / "science").mkdir(parents=True)
        config = {**self.config,
                  "host": {"instanceId": "qual-015-020z-focused", "shutdownSeconds": 10,
                           "science": {"maxItems": 1, "pollSeconds": 0,
                                       "stateRoot": str(self.science)}},
                  "researchFactExportV2": {"exportRoot": str(self.root / "producer")},
                  "runtimeBuildHash": SOURCE_ROOT_IDENTITY,
                  "hostFingerprint": "focused-test"}
        host = SimpleNamespace(generation=GENERATION, status=lambda state, **detail: None)
        failure = CustodyCommitIntegrityError("Completion exists without its exact receipt.")
        failure.receipt_diagnostic = {"request_id": "a" * 64, "request_digest": "b" * 64,
                                      "generation": "c" * 32, "receipt_at_failure": {"state": "MISSING"}}
        with patch.object(lifecycle, "upstream_generations", return_value={"writer": "w", "runtime": "r"}), \
             patch.object(lifecycle, "open_host_science_storage", side_effect=failure):
            self.assertEqual(2, lifecycle.run_science(config, threading.Event(), host))
        path = Path(config["logRoot"]) / "science" / f"failure-{GENERATION}.json"
        report = json.loads(path.read_bytes())
        self.assertEqual(failure.receipt_diagnostic, report["receiptDiagnostic"])

    def test_trace_is_absent_outside_exact_qualification_family(self):
        self.config["host"]["instanceId"] = "production"
        self.assertIsNone(open_020y_trace(self.config, generation=GENERATION))
        self.config["host"]["instanceId"] = "qual-015-020y-focused"
        with self.assertRaises(ValueError):
            open_020y_trace(self.config, generation="wrong-generation")


if __name__ == "__main__":
    unittest.main()
