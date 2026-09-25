"""Diagnostic equivalence only; these are not native custody authority proofs."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import continuous_production as production
from momentum_hunter.science_custody_commit import ScienceCustodyFinalizer
from momentum_hunter.science_writer_profile_r19 import WriterStartupProfile, open_writer_startup_profile
from tests.test_science_custody_commit_007 import MemoryBackend, request_for


GENERATION = "12345678-1234-1234-1234-123456789abc"


class WriterStartupProfileTests(unittest.TestCase):
    def test_no_custody_worker_does_not_create_unowned_profile(self):
        config = {"inputMode": "OFFLINE_QUALIFICATION",
                  "host": {"instanceId": "qual-015-013b-sc19-test"},
                  "ipcHost": "127.0.0.1", "ipcPort": 1}
        server = Mock()
        server.serve_forever.return_value = True
        server.science_custody_status = {"state": "DISABLED", "threadAlive": False}
        with patch.object(production, "_read_config", return_value=config), patch.object(
                production, "science_custody_policy", return_value=None), patch(
                "momentum_hunter.science_custody_trace_020u.open_020u_trace", return_value=None), patch(
                "momentum_hunter.science_writer_profile_r19.open_writer_startup_profile") as factory, patch(
                "momentum_hunter.windows_writer_profile.NativeWriterAdmission") as admission, patch.object(
                production, "ProductionWriterServer", return_value=server) as constructor:
            self.assertEqual(0, production.run_writer(Path("unused-test-config")))
        factory.assert_not_called()
        admission.assert_not_called()
        self.assertIsNone(constructor.call_args.kwargs["qualification_profile"])
        server.serve_forever.assert_called_once_with("127.0.0.1", 1, None, None)
        server.close.assert_called_once_with()

    def test_only_exact_disposable_offline_namespace_is_profiled(self):
        for mode, instance in (("LIVE", "qual-015-013b-sc19-test"),
                               ("OFFLINE_QUALIFICATION", "production"),
                               ("OFFLINE_QUALIFICATION", "qual-015-013b-sc18-test"),
                               ("OFFLINE_QUALIFICATION", None)):
            with self.subTest(mode=mode, instance=instance), patch(
                    "momentum_hunter.science_writer_profile_r19.ScienceReadinessTrace",
                    side_effect=AssertionError("Dormant path started diagnostics")):
                self.assertIsNone(open_writer_startup_profile(
                    {"inputMode": mode, "host": {"instanceId": instance}}, generation=GENERATION))

    def test_profile_preserves_exact_protocol_bytes_reads_effects_and_return(self):
        outputs = []
        for profiled in (False, True):
            backend = MemoryBackend()
            request = request_for(backend)
            phases = []
            finalizer = ScienceCustodyFinalizer(backend, fault_hook=phases.append)
            trace = Mock()
            profile = WriterStartupProfile(trace)
            call = lambda: finalizer.finalize(request)
            result = profile.poll(call) if profiled else call()
            profile.close()
            outputs.append((result, backend.objects, backend.reads, phases))
        self.assertEqual(outputs[0], outputs[1])
        self.assertTrue(trace.call_args.kwargs["diagnostic_only"])
        self.assertEqual(1, trace.call_args.kwargs["results"])

    def test_exception_is_same_object_and_operation_runs_once(self):
        error = PermissionError(5, "synthetic diagnostic test")
        operation = Mock(side_effect=error)
        trace = Mock()
        profile = WriterStartupProfile(trace)
        with self.assertRaises(PermissionError) as caught:
            profile.poll(operation)
        self.assertIs(error, caught.exception)
        operation.assert_called_once_with()
        profile.close()
        self.assertEqual(["POLL:PermissionError"], trace.call_args.kwargs["errors"])

    def test_failed_profiler_enable_does_not_retry_or_suppress_operation(self):
        profile = WriterStartupProfile(Mock())
        profile.profile = Mock()
        profile.profile.enable.side_effect = RuntimeError("unavailable")
        profile.profile.getstats.return_value = []
        result = object()
        operation = Mock(return_value=result)
        self.assertIs(result, profile.poll(operation))
        operation.assert_called_once_with()
        self.assertTrue(profile.finished)

    def test_failed_report_or_close_does_not_change_result(self):
        profile = WriterStartupProfile(Mock(side_effect=OSError("diagnostic only")))
        profile.MAX_RESULTS = 1
        profile.trace.close.side_effect = OSError("diagnostic only")
        result = object()
        self.assertIs(result, profile.poll(lambda: result))
        profile.close()
        self.assertIn("REPORT:OSError", profile.errors)
        self.assertIn("CLOSE:OSError", profile.errors)

    def test_profile_finishes_at_result_or_poll_bound(self):
        for result in (None, object()):
            with self.subTest(has_result=result is not None):
                trace = Mock()
                profile = WriterStartupProfile(trace)
                profile.MAX_POLLS = profile.MAX_RESULTS = 2
                operation = Mock(return_value=result)
                for _ in range(5):
                    self.assertIs(result, profile.poll(operation))
                profile.close()
                self.assertEqual(5, operation.call_count)
                self.assertEqual(2, trace.call_args.kwargs["polls"])
                self.assertEqual(2 if result is not None else 0, trace.call_args.kwargs["results"])
                self.assertEqual(1, trace.call_count)

    def test_profile_has_elapsed_and_output_bounds(self):
        trace = Mock()
        profile = WriterStartupProfile(trace)
        profile.MAX_FUNCTIONS = 1
        profile.MAX_SECONDS = 1
        with patch("momentum_hunter.science_writer_profile_r19.time.perf_counter",
                   side_effect=[0.0, 2.0, 2.1]):
            profile.poll(lambda: None)
        self.assertTrue(profile.finished)
        self.assertTrue(trace.call_args.kwargs["truncated"])
        self.assertEqual(1, len(trace.call_args.kwargs["functions"]))

    def test_summary_round_trips_with_bound_generation_and_trace_health(self):
        with TemporaryDirectory() as root:
            profile = open_writer_startup_profile({"inputMode": "OFFLINE_QUALIFICATION",
                "host": {"instanceId": "qual-015-013b-sc19-test"}, "logRoot": root}, generation=GENERATION)
            self.assertIsNotNone(profile)
            profile.poll(lambda: object())
            profile.close()
            profile.trace._thread.join(timeout=2)
            self.assertFalse(profile.trace._thread.is_alive())
            rows = [json.loads(line) for line in profile.trace.path.read_text(encoding="ascii").splitlines()]
            self.assertEqual(GENERATION, rows[0]["generation"])
            self.assertEqual("WRITER_STARTUP_PROFILE", rows[0]["event"])
            self.assertEqual([], rows[0]["errors"])
            self.assertTrue(rows[0]["timing_includes_profiler_overhead"])
            self.assertTrue(profile.trace.health_committed)

    def test_bad_generation_fails_before_creating_diagnostic(self):
        with self.assertRaisesRegex(ValueError, "bound generation"):
            open_writer_startup_profile({"inputMode": "OFFLINE_QUALIFICATION",
                "host": {"instanceId": "qual-015-013b-sc19-test"}}, generation="wrong")

    def test_worker_stop_does_not_close_profiler_or_channel_while_polling(self):
        entered, release, native_closed, profile_closed = (threading.Event() for _ in range(4))
        order = []

        class Channel:
            def poll_once(self):
                order.append("poll-enter")
                entered.set()
                release.wait(3)
                order.append("poll-exit")
                return None

            def close(self):
                order.append("native-close")
                native_closed.set()

        profile = WriterStartupProfile(Mock())
        profile.trace.close.side_effect = lambda: (order.append("profile-close"), profile_closed.set())
        with patch.object(production, "_open_science_custody_writer", return_value=Channel()):
            worker = production._ScienceCustodyWorker("policy", qualification_profile=profile)
            try:
                self.assertTrue(entered.wait(1))
                worker.request_stop()
                worker.wait_stopped()
                self.assertFalse(native_closed.is_set())
                self.assertFalse(profile_closed.is_set())
            finally:
                release.set()
            self.assertTrue(profile_closed.wait(2))
            worker.wait_stopped()
        self.assertEqual(["poll-enter", "poll-exit", "native-close", "profile-close"], order)
        self.assertFalse(worker.snapshot()["threadAlive"])

    def test_failed_worker_start_releases_only_its_diagnostic(self):
        profile = WriterStartupProfile(Mock())
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("test start failure")):
            worker = production._ScienceCustodyWorker("policy", qualification_profile=profile)
        self.assertEqual("START_FAILED", worker.snapshot()["state"])
        self.assertTrue(profile.finished)
        profile.trace.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
