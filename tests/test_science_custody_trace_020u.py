"""Focused 020U observations; these memory tests are not physical A14 proof."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from momentum_hunter import continuous_production
from momentum_hunter.science_custody_commit import (
    CustodyCommitIntegrityError, ScienceCustodyFinalizer, completion_path, receipt_path, sha256,
)
from momentum_hunter.science_custody_trace_020u import open_020u_trace
from test_science_custody_commit_007 import MemoryBackend, request_for
from tools.analyze_020u_custody_trace import load_rows, summarize


class RecordingBackend(MemoryBackend):
    def __init__(self):
        super().__init__()
        self.publications = []

    def create_trusted(self, namespace, relative, raw):
        result = super().create_trusted(namespace, relative, raw)
        if namespace == "receipts" and relative.endswith(".commit.json"):
            self.publications.append(("receipt", relative))
        return result

    def publish_completion(self, relative, raw):
        result = super().publish_completion(relative, raw)
        self.publications.append(("completion", relative))
        return result


class Trace020UTests(unittest.TestCase):
    def test_exact_digest_generation_and_publication_order(self):
        backend = RecordingBackend()
        request = request_for(backend)
        events = []
        result = ScienceCustodyFinalizer(backend, trace_hook=events.append).finalize(request)
        digest = request.identity.digest()
        receipt = receipt_path(digest)
        completion = completion_path(digest)
        self.assertEqual([("receipt", receipt), ("completion", completion)], backend.publications)
        ordered = [e["event"] for e in events if "create" in e["event"]]
        self.assertEqual(["receipt_create_begin", "receipt_create_result",
                          "completion_create_begin", "completion_create_result"], ordered)
        self.assertTrue(all(e["identity_sha256"] == digest and
                            e["request_sha256"] == request.request_digest() and
                            e["generation"] == request.generation for e in events))
        receipt_event = next(e for e in events if e["event"] == "receipt_create_result")
        self.assertEqual((receipt, sha256(result.receipt.to_bytes())),
                         (receipt_event["relative_path"], receipt_event["sha256"]))
        self.assertEqual(completion, next(e["relative_path"] for e in events
                          if e["event"] == "completion_create_result"))
        self.assertTrue(all(e["file_identity"] is not None and e["sha256"] is not None
                            for e in events if e["event"].endswith("_create_result")))

    def test_missing_receipt_is_observed_not_accepted(self):
        backend = MemoryBackend()
        request = request_for(backend)
        ScienceCustodyFinalizer(backend).finalize(request)
        del backend.objects["receipts", receipt_path(request.identity.digest())]
        events = []
        with self.assertRaisesRegex(CustodyCommitIntegrityError,
                                    "Completion exists without its exact receipt"):
            ScienceCustodyFinalizer(backend, trace_hook=events.append).lookup(request)
        self.assertEqual([("lookup_begin", "BEGIN"), ("completion_read", "PRESENT"),
                          ("receipt_read", "MISSING")],
                         [(e["event"], e["result"]) for e in events])
        self.assertIsNone(events[2]["file_identity"])
        self.assertIsNone(events[2]["sha256"])

    def test_same_identity_distinct_generations_remain_distinct(self):
        backend = MemoryBackend()
        first = request_for(backend)
        ScienceCustodyFinalizer(backend).finalize(first)
        second = request_for(backend, generation="2" * 32)
        events = []
        reader = ScienceCustodyFinalizer(backend, trace_hook=events.append)
        self.assertIsNotNone(reader.lookup(first))
        self.assertIsNotNone(reader.lookup(second))
        self.assertEqual(first.identity.digest(), second.identity.digest())
        self.assertNotEqual(first.request_digest(), second.request_digest())
        keys = {(e["identity_sha256"], e["request_sha256"], e["generation"])
                for e in events}
        self.assertEqual(2, len(keys))
        self.assertEqual({first.generation, second.generation}, {key[2] for key in keys})

    def test_trace_sink_is_qualification_only_and_identity_bound(self):
        with TemporaryDirectory() as root:
            config = {"host": {"instanceId": "qual-015-020u-focused"}, "logRoot": root}
            generation = "12345678-1234-1234-1234-123456789abc"
            trace = open_020u_trace(config, role="science", generation=generation)
            self.assertIsNotNone(trace)
            backend = MemoryBackend()
            request = request_for(backend)
            ScienceCustodyFinalizer(backend, trace_hook=trace).lookup(request)
            trace.close()
            path = Path(root) / "science" / ("custody-object-trace-" + generation + ".jsonl")
            rows = [json.loads(line) for line in path.read_text(encoding="ascii").splitlines()]
            self.assertEqual([1, 2, 3], [row["sequence"] for row in rows])
            self.assertEqual(["lookup_begin", "completion_read", "receipt_read"],
                             [row["event"] for row in rows])
            self.assertTrue(all(row["identity_sha256"] == request.identity.digest()
                                for row in rows))
            config["host"]["instanceId"] = "qual-015-020z-focused"
            new_generation = "22345678-1234-1234-1234-123456789abc"
            new_trace = open_020u_trace(config, role="science", generation=new_generation)
            self.assertIsNotNone(new_trace)
            new_trace.close()
            config["host"]["instanceId"] = "production"
            self.assertIsNone(open_020u_trace(config, role="science", generation=generation))

    def test_analyzer_reports_missing_events_without_borrowing_prior_generation(self):
        with TemporaryDirectory() as root:
            config = {"host": {"instanceId": "qual-015-020u-focused"}, "logRoot": root}
            generation = "12345678-1234-1234-1234-123456789abc"
            writer = open_020u_trace(config, role="writer", generation=generation)
            science = open_020u_trace(config, role="science", generation=generation)
            backend = MemoryBackend()
            first = request_for(backend)
            ScienceCustodyFinalizer(backend, trace_hook=writer).finalize(first)
            second = request_for(backend, generation="2" * 32)
            del backend.objects["receipts", receipt_path(first.identity.digest())]
            with self.assertRaises(CustodyCommitIntegrityError):
                ScienceCustodyFinalizer(backend, trace_hook=science).lookup(second)
            writer.close()
            science.close()
            folder = Path(root)
            writer_rows = load_rows(folder / "writer" / ("custody-object-trace-" + generation + ".jsonl"), "writer")
            science_rows = load_rows(folder / "science" / ("custody-object-trace-" + generation + ".jsonl"), "science")
            report = summarize(writer_rows, science_rows)
            self.assertEqual(2, report["request_group_count"])
            self.assertEqual(1, report["failing_request_count"])
            failure = report["failing_requests"][0]
            self.assertEqual(second.request_digest(), failure["request_sha256"])
            self.assertEqual(second.generation, failure["generation"])
            self.assertEqual(["completion_read", "receipt_read"], failure["lookup_read_order"])
            self.assertIn("receipt_create_result", failure["missing_events"])
            self.assertIn("completion_create_result", failure["missing_events"])

    def test_analyzer_preserves_historical_read_order(self):
        backend = MemoryBackend()
        request = request_for(backend)
        ScienceCustodyFinalizer(backend).finalize(request)
        del backend.objects["receipts", receipt_path(request.identity.digest())]
        events = []
        with self.assertRaises(CustodyCommitIntegrityError):
            ScienceCustodyFinalizer(backend, trace_hook=events.append).lookup(request)
        rows = [{"role": "science", "sequence": index, **event}
                for index, event in enumerate(events, 1)]
        rows[1], rows[2] = rows[2], rows[1]
        rows[1]["sequence"], rows[2]["sequence"] = 2, 3
        report = summarize([], rows)
        self.assertEqual(1, report["failing_request_count"])
        self.assertEqual(["receipt_read", "completion_read"],
                         report["failing_requests"][0]["lookup_read_order"])

    def test_analyzer_rejects_wrong_path_and_missing_sequence(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "trace.jsonl"
            config = {"host": {"instanceId": "qual-015-020u-focused"}, "logRoot": root}
            generation = "12345678-1234-1234-1234-123456789abc"
            trace = open_020u_trace(config, role="science", generation=generation)
            backend = MemoryBackend()
            ScienceCustodyFinalizer(backend, trace_hook=trace).lookup(request_for(backend))
            trace.close()
            source = Path(root) / "science" / ("custody-object-trace-" + generation + ".jsonl")
            rows = [json.loads(line) for line in source.read_text(encoding="ascii").splitlines()]
            rows[0]["relative_path"] = "other.complete.json"
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "path differs"):
                load_rows(path, "science")
            rows[0]["relative_path"] = rows[1]["relative_path"].replace(".commit.json", ".complete.json")
            rows[0]["sequence"] = 2
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "missing or duplicated"):
                load_rows(path, "science")

    def test_writer_worker_keeps_trace_open_until_native_poll_exits(self):
        entered, release, closed, trace_closed = (threading.Event() for _ in range(4))

        class Channel:
            def poll_once(self):
                entered.set()
                release.wait(3)
                return None

            def close(self):
                closed.set()

        class Trace:
            def __call__(self, event):
                pass

            def close(self):
                trace_closed.set()

        trace = Trace()
        seen = []

        def factory(policy, *, trace_hook=None):
            seen.append((policy, trace_hook))
            return Channel()

        with patch.object(continuous_production, "_open_science_custody_writer", factory):
            worker = continuous_production._ScienceCustodyWorker("policy", trace_hook=trace)
            try:
                self.assertTrue(entered.wait(1))
                self.assertEqual([("policy", trace)], seen)
                worker.request_stop()
                worker.wait_stopped()
                self.assertFalse(trace_closed.is_set())
            finally:
                release.set()
            self.assertTrue(closed.wait(1))
            self.assertTrue(trace_closed.wait(1))

    def test_trace_write_failure_does_not_change_commit_result(self):
        with TemporaryDirectory() as root:
            config = {"host": {"instanceId": "qual-015-020u-focused"}, "logRoot": root}
            trace = open_020u_trace(config, role="writer",
                                    generation="12345678-1234-1234-1234-123456789abc")
            backend = MemoryBackend()
            request = request_for(backend)
            with patch("momentum_hunter.science_custody_trace_020u.os.write", side_effect=OSError(5, "test")):
                result = ScienceCustodyFinalizer(backend, trace_hook=trace).finalize(request)
            trace.close()
            self.assertIsNotNone(result.receipt)
            self.assertGreater(trace.lost_events, 0)
            self.assertIsNotNone(ScienceCustodyFinalizer(backend).lookup(request))


if __name__ == "__main__":
    unittest.main()
