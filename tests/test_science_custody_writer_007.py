"""Writer thread-isolation proof; fake Science I/O is not native ACL proof."""

from __future__ import annotations

import errno
import json
import secrets
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from momentum_hunter import continuous_production as production
from momentum_hunter.continuous_runtime import WRITER_ACCEPTED, WRITER_DUPLICATE
from momentum_hunter.event_runtime_writer_ipc import WriterEnvelope
from momentum_hunter.science_custody_commit import (
    CustodyCommitConflict,
    CustodyCommitError,
    CustodyCommitIntegrityError,
    CustodyCommitPending,
)
from momentum_hunter.windows_science_custody import ScienceCustodyNativeError
from tests import test_continuous_production as production_fixtures


class _ControlledChannel:
    """Deterministic blocked/failing mailbox stand-in; no security assertions."""

    def __init__(self, *, block=False, error=None, close_error=None):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.error = error
        self.close_error = close_error
        self.lock = threading.Lock()
        self.calls = 0
        self.active = 0
        self.maximum_active = 0
        self.thread_ids = set()
        if not block:
            self.release.set()

    def poll_once(self):
        with self.lock:
            self.calls += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.thread_ids.add(threading.get_ident())
            self.entered.set()
            try:
                if not self.release.wait(10):
                    raise TimeoutError("Test failed to release Science I/O")
                if self.error is not None:
                    raise self.error
                return object()  # One receipt observation, possibly a duplicate.
            finally:
                self.active -= 1

    def close(self):
        self.thread_ids.add(threading.get_ident())
        self.closed.set()
        if self.close_error is not None:
            raise self.close_error


class ScienceCustodyWriter007Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="argus-custody007-writer-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "ipc.key").write_bytes(secrets.token_bytes(32))
        self.helper = production_fixtures.ContinuousProductionTests()
        self.config = self.helper._config(self.root)
        self.servers = []
        self.channels = []
        self.seen_failure_receipts = set()
        self.addCleanup(self._close_everything)

    def _close_everything(self):
        for channel in self.channels:
            channel.release.set()
        for server in self.servers:
            server.close()
            worker = server._science_custody_worker
            if worker is not None and worker._thread.is_alive():
                worker._thread.join(timeout=2)
                self.assertFalse(worker._thread.is_alive())

    def _server(self, channel=None, *, factory=None):
        if channel is not None:
            self.channels.append(channel)
        with patch.object(
            production, "_open_science_custody_writer",
            side_effect=factory, return_value=channel,
        ) as opener:
            server = production.ProductionWriterServer(
                self.config, science_custody_policy=SimpleNamespace(actor_profile=None)
            )
            self.servers.append(server)
            self._await(lambda: opener.called)
        return server

    def _await(self, predicate, *, seconds=3):
        deadline = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail("Timed out awaiting a bounded test transition")
            threading.Event().wait(0.005)

    def _failure_receipt(self, server):
        directory = (Path(self.config["logRoot"]) / "writer"
                     if "logRoot" in self.config else server.root / "status")
        self._await(lambda: bool(set(directory.glob("custody-failure-*.json"))
                                 - self.seen_failure_receipts))
        paths = list(set(directory.glob("custody-failure-*.json"))
                     - self.seen_failure_receipts)
        self.assertEqual(1, len(paths))
        self.seen_failure_receipts.add(paths[0])
        return json.loads(paths[0].read_text(encoding="ascii"))

    def _production_write(self, server, *, source="production-continuous-runtime-custody007"):
        remote = production.ProductionRemoteWriter(self.config, source_identity=source)

        def request(frame):
            if frame["frameType"] == "HELLO":
                return server._handshake(frame)
            return server._persist(WriterEnvelope(**frame["envelope"]))

        with patch.object(remote, "_request", side_effect=request):
            result = remote.write_intent(self.helper._intent(source))
        records = list((server.root / "records").rglob("*.json"))
        self.assertEqual(1, len(records))
        record = json.loads(records[0].read_text(encoding="ascii"))
        self.assertEqual("COMPOSITION_CYCLE", record["payload"]["payloadType"])
        self.assertNotIn("payload_json", record["intent"])
        self.assertEqual(256, production._runtime_config(self.config).queues.evidence)
        return result

    def test_absent_policy_does_not_read_science_config_or_construct_worker(self):
        class NoScienceConfig(dict):
            def get(self, key, *args):
                if "science" in key.lower() or "custody" in key.lower():
                    raise AssertionError("Disabled channel accessed Science configuration")
                return super().get(key, *args)

            def __getitem__(self, key):
                if "science" in key.lower() or "custody" in key.lower():
                    raise AssertionError("Disabled channel accessed Science configuration")
                return super().__getitem__(key)

        with patch.object(production, "_ScienceCustodyWorker", side_effect=AssertionError), \
                patch.object(production, "_open_science_custody_writer", side_effect=AssertionError):
            server = production.ProductionWriterServer(NoScienceConfig(self.config))
            self.servers.append(server)
            self.assertEqual(
                {"state": "DISABLED", "threadAlive": False, "inFlight": False},
                server.science_custody_status,
            )
            self.assertEqual(WRITER_ACCEPTED, self._production_write(server).status)
            status = json.loads(server.status_path.read_text(encoding="ascii"))
            self.assertEqual("READY", status["state"])
            self.assertFalse(any("science" in key.lower() for key in status))

    def test_blocked_native_open_does_not_block_production_start_or_durability(self):
        channel = _ControlledChannel()
        opening = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        thread_ids = []

        def factory(policy):
            thread_ids.append(threading.get_ident())
            opening.set()
            if not release.wait(10):
                raise TimeoutError("Test did not release native open")
            return channel

        server = self._server(channel, factory=factory)
        self.assertTrue(opening.wait(1))
        self.assertNotEqual(threading.get_ident(), thread_ids[0])
        self.assertEqual(WRITER_ACCEPTED, self._production_write(server).status)
        self.assertEqual("STARTING", server.science_custody_status["state"])
        release.set()
        self.assertTrue(channel.entered.wait(1))

    def test_blocked_poll_and_science_lock_leave_production_progressing(self):
        channel = _ControlledChannel(block=True)
        server = self._server(channel)
        self.assertTrue(channel.entered.wait(1))
        self.assertFalse(channel.lock.acquire(blocking=False))
        self.assertTrue(server.science_custody_status["inFlight"])
        self.assertEqual(WRITER_ACCEPTED, self._production_write(server).status)
        self.assertEqual(1, channel.calls)
        self.assertEqual(1, channel.maximum_active)
        channel.release.set()

    def test_busy_and_disk_full_science_failures_preserve_production(self):
        cases = (
            CustodyCommitPending("Original request outcome remains unknown"),
            PermissionError("retained writable source handle"),
            OSError(errno.ENOSPC, "Science copy disk full"),
        )
        for ordinal, error in enumerate(cases):
            with self.subTest(error=type(error).__name__):
                channel = _ControlledChannel(error=error)
                server = self._server(channel)
                self._await(lambda: server.science_custody_status["errorCount"] >= 2)
                self.assertEqual(WRITER_ACCEPTED if ordinal == 0 else WRITER_DUPLICATE,
                                 self._production_write(server).status)
                snapshot = server.science_custody_status
                self.assertEqual(type(error).__name__, snapshot["lastError"])
                self.assertNotIn(str(error), str(snapshot))
                server.close()
                self.servers.remove(server)

    def test_malformed_science_fails_closed_without_retry_or_production_failure(self):
        channel = _ControlledChannel(error=ValueError("malformed request"))
        server = self._server(channel)
        self._await(lambda: server.science_custody_status["state"] == "FAILED")
        self.assertEqual(WRITER_ACCEPTED, self._production_write(server).status)
        self.assertEqual(1, channel.calls)
        self.assertEqual(1, server.science_custody_status["pollCount"])
        self.assertEqual("ValueError", server.science_custody_status["lastError"])
        self.assertTrue(channel.closed.is_set())
        receipt = self._failure_receipt(server)
        self.assertEqual("ValueError", receipt["exceptionType"])
        self.assertEqual("malformed request", receipt["exceptionMessage"])
        self.assertEqual("POLL", receipt["writerOperationOrState"])
        self.assertIsNone(receipt["requestIdOrDigestIfAvailable"])
        self.assertIn("continuous_production.py", receipt["traceback"])

    def test_native_failure_preserves_exact_message_cause_and_traceback(self):
        native_message = "GetSecurityInfo: required native authority/evidence failed (Win32 5)."
        self.config["logRoot"] = str(self.root / "logs")

        class NativeFailureChannel(_ControlledChannel):
            def poll_once(self):
                self.entered.set()
                try:
                    raise PermissionError(13, "Access is denied", "C:\\private\\source")
                except PermissionError as cause:
                    raise ScienceCustodyNativeError(native_message) from cause

        channel = NativeFailureChannel()
        server = self._server(channel)
        self._await(lambda: server.science_custody_status["state"] == "FAILED")
        receipt = self._failure_receipt(server)
        self.assertEqual("ScienceCustodyNativeError", receipt["exceptionType"])
        self.assertEqual(native_message, receipt["exceptionMessage"])
        self.assertEqual("PermissionError", receipt["exceptionCauseType"])
        self.assertEqual("Access is denied", receipt["exceptionCauseMessage"])
        self.assertEqual("PermissionError", receipt["exceptionContextType"])
        self.assertIn("test_science_custody_writer_007.py", receipt["traceback"])
        self.assertNotIn("private", json.dumps(receipt))
        self.assertEqual("FAILED", server.science_custody_status["state"])
        self.assertEqual("ScienceCustodyNativeError", server.science_custody_status["lastError"])

    def test_benign_native_token_word_is_not_a_secret_marker(self):
        message = "Token query size is invalid."
        self.assertEqual(message, production._custody_exception_message(
            ScienceCustodyNativeError(message)))

    def test_failure_receipt_omits_secret_and_unbounded_messages(self):
        for message in ("password=very-sensitive-value", "Bearer hidden-value", "X" * 4096):
            with self.subTest(message=message[:24]):
                channel = _ControlledChannel(error=ValueError(message))
                server = self._server(channel)
                self._await(lambda: server.science_custody_status["state"] == "FAILED")
                receipt = self._failure_receipt(server)
                self.assertEqual("[OMITTED:UNSAFE_OR_OVERSIZE]", receipt["exceptionMessage"])
                self.assertNotIn(message, json.dumps(receipt))
                self.assertLess(len(json.dumps(receipt)), 4096)
                self.assertEqual("FAILED", server.science_custody_status["state"])
                server.close()
                self.servers.remove(server)

    def test_integrity_conflict_and_protocol_errors_are_terminal_for_science_only(self):
        cases = (
            CustodyCommitIntegrityError("Pinned owner or identity changed"),
            CustodyCommitConflict("Existing identity has conflicting bytes"),
            CustodyCommitError("Invalid request fields or mailbox capacity"),
        )
        for ordinal, error in enumerate(cases):
            with self.subTest(error=type(error).__name__):
                channel = _ControlledChannel(error=error)
                server = self._server(channel)
                self._await(lambda: server.science_custody_status["state"] == "FAILED")
                self.assertEqual(WRITER_ACCEPTED if ordinal == 0 else WRITER_DUPLICATE,
                                 self._production_write(server).status)
                self.assertEqual(1, channel.calls)
                self.assertEqual(1, server.science_custody_status["errorCount"])
                self.assertTrue(channel.closed.is_set())
                server.close()
                self.servers.remove(server)

    def test_saturated_duplicate_observations_are_serial_and_do_not_change_session(self):
        channel = _ControlledChannel()
        server = self._server(channel)
        self.assertTrue(channel.entered.wait(1))
        self.assertEqual(WRITER_ACCEPTED, self._production_write(server).status)
        session = (server.session_id, server.session_key, server.source_identity,
                   server.expected_sequence, server.prior_envelope)
        self._await(lambda: server.science_custody_status["pollCount"] >= 8)
        self.assertEqual(session, (server.session_id, server.session_key, server.source_identity,
                                  server.expected_sequence, server.prior_envelope))
        self.assertEqual(1, channel.maximum_active)
        self.assertEqual(1, len(channel.thread_ids))
        self.assertNotIn(threading.get_ident(), channel.thread_ids)
        self.assertGreaterEqual(server.science_custody_status["receiptObservationCount"], 8)

    def test_stop_wait_does_not_claim_cancellation_or_close_inflight_native_handles(self):
        channel = _ControlledChannel(block=True)
        server = self._server(channel)
        self.assertTrue(channel.entered.wait(1))
        self.assertEqual(WRITER_ACCEPTED, self._production_write(server).status)
        start = time.monotonic()
        server.close()
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual("STOP_PENDING", server.science_custody_status["state"])
        self.assertTrue(server.science_custody_status["inFlight"])
        self.assertFalse(channel.closed.is_set())
        self.assertEqual("STOPPED", json.loads(server.status_path.read_text(encoding="ascii"))["state"])
        channel.release.set()
        self.assertTrue(channel.closed.wait(1))
        self._await(lambda: not server.science_custody_status["threadAlive"])
        self.assertEqual("STOPPED", server.science_custody_status["state"])
        self.assertEqual(1, channel.calls)
        self.assertEqual(1, len(channel.thread_ids))

    def test_each_restart_reopens_native_boundary_and_preserves_production_duplicate(self):
        opened = []
        for ordinal in range(3):
            channel = _ControlledChannel()

            def factory(policy, channel=channel):
                opened.append(policy)
                return channel

            server = self._server(channel, factory=factory)
            self.assertTrue(channel.entered.wait(1))
            self.assertEqual(WRITER_ACCEPTED if ordinal == 0 else WRITER_DUPLICATE,
                             self._production_write(server).status)
            server.close()
            self.assertTrue(channel.closed.is_set())
            self.servers.remove(server)
        self.assertEqual(3, len(opened))

    def test_native_admission_failure_is_visible_without_blocking_production(self):
        def reject(policy):
            raise PermissionError("Wrong actual owner or pinned root identity")

        server = self._server(factory=reject)
        self._await(lambda: server.science_custody_status["state"] == "FAILED")
        self.assertEqual(WRITER_ACCEPTED, self._production_write(server).status)
        self.assertEqual(0, server.science_custody_status["pollCount"])

    def test_native_close_failure_stays_visible_and_production_closes(self):
        channel = _ControlledChannel(close_error=OSError("Close failed"))
        server = self._server(channel)
        self.assertTrue(channel.entered.wait(1))
        server.close()
        self.assertEqual("CLOSE_FAILED", server.science_custody_status["state"])
        self.assertFalse(server.science_custody_status["threadAlive"])
        self.assertEqual("STOPPED", json.loads(server.status_path.read_text(encoding="ascii"))["state"])

    def test_status_snapshot_is_detached_from_internal_state(self):
        channel = _ControlledChannel(block=True)
        server = self._server(channel)
        self.assertTrue(channel.entered.wait(1))
        snapshot = server.science_custody_status
        snapshot.update(state="FORGED_READY", pollCount=999)
        self.assertEqual("POLLING", server.science_custody_status["state"])
        self.assertEqual(0, server.science_custody_status["pollCount"])


if __name__ == "__main__":
    unittest.main()
