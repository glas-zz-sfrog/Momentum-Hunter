"""Focused diagnostic-only Science readiness lineage checks."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from momentum_hunter.continuous_host_lifecycle import science_state
from momentum_hunter.science_readiness_trace_020y import open_020y_trace
from momentum_hunter.strategy_science_continuous_recorder import ContinuousScienceRecorder
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
        path = self.root / "logs" / "science" / f"readiness-trace-{GENERATION}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]

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
        self.assertEqual(["source_observed", "raw_persisted", "normalization_started",
                          "normalization_completed", "normalized_observed", "trace_closed"],
                         [row["event"] for row in rows])
        self.assertEqual({GENERATION}, {row["generation"] for row in rows})
        self.assertEqual(1, len({row["raw_id"] for row in rows if "raw_id" in row}))
        self.assertEqual(1, len({row["source_id"] for row in rows if "source_id" in row}))
        self.assertEqual(rows[-3]["normalized_ids"], rows[-2]["normalized_ids"])
        self.assertTrue(rows[-2]["normalized_ids"])
        self.assertEqual(0, rows[-1]["lost_events"])

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
        self.assertEqual("normalization_failed", rows[-2]["event"])
        self.assertNotIn("normalized_observed", [row["event"] for row in rows])
        self.assertNotIn("normalization_completed", [row["event"] for row in rows])

    def test_trace_is_absent_outside_exact_qualification_family(self):
        self.config["host"]["instanceId"] = "production"
        self.assertIsNone(open_020y_trace(self.config, generation=GENERATION))
        self.config["host"]["instanceId"] = "qual-015-020y-focused"
        with self.assertRaises(ValueError):
            open_020y_trace(self.config, generation="wrong-generation")


if __name__ == "__main__":
    unittest.main()
