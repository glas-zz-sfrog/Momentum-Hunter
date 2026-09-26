"""Diagnostic parity only; these mocks are not actual restricted-actor proof."""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import continuous_production as production


class WriterDrainObservationTests(unittest.TestCase):
    def test_observation_does_not_change_deadline_or_completion_decision(self):
        for drained in (False, True):
            with self.subTest(drained=drained):
                server = object.__new__(production.ProductionWriterServer)
                server.config = {"host": {"shutdownSeconds": 30}}
                server._native_writer_admission = None
                server._science_custody_worker = None
                server._write_status = Mock()
                server.dependency_drain_observation = None
                generation = Mock(enabled=True)
                listener = Mock()
                observation = {"science": {"accepted": drained, "processLifetime": {
                    "operation": "OpenProcess", "winerror": 5 if not drained else 87,
                    "state": "UNKNOWN" if not drained else "EXITED"}}}

                def check(config, role, *, observation: dict):
                    self.assertIs(config, server.config)
                    self.assertEqual("writer", role)
                    observation.update(details)
                    return drained

                details = observation
                with patch.object(production.socketserver, "ThreadingTCPServer") as constructor, \
                     patch.object(production, "dependencies_drained", side_effect=check) as dependency, \
                     patch.object(production.time, "monotonic", side_effect=[10, 40]):
                    constructor.return_value.__enter__.return_value = listener
                    self.assertEqual(drained, server.serve_forever("127.0.0.1", 1, Mock(is_set=lambda: True), generation))
                dependency.assert_called_once()
                listener.handle_request.assert_not_called()
                self.assertEqual(drained, server.dependency_drain_observation["accepted"])
                self.assertEqual(details, server.dependency_drain_observation["dependencies"])
                server._write_status.assert_any_call("STOPPING")

    def test_terminal_status_preserves_last_same_evaluation_observation(self):
        observation = {"accepted": False, "dependencies": {"science": {
            "accepted": False, "processLifetime": {"state": "UNKNOWN", "winerror": 5}}}}
        server = Mock()
        server.serve_forever.return_value = False
        server.science_custody_status = {"state": "STOPPED", "threadAlive": False}
        server.dependency_drain_observation = observation
        host = Mock(generation="test-generation")
        with patch.object(production, "_read_config", return_value={"ipcHost": "127.0.0.1", "ipcPort": 1}), \
             patch.object(production, "science_custody_policy", return_value=None), \
             patch.object(production, "ProductionWriterServer", return_value=server), \
             patch("momentum_hunter.science_custody_trace_020u.open_020u_trace", return_value=None):
            self.assertEqual(2, production.run_writer(Path("unused-diagnostic-fixture"), Mock(), host))
        server.close.assert_called_once()
        host.status.assert_called_once_with("INCOMPLETE", drainComplete=False,
            cleanupComplete=True, pendingWork="UNKNOWN", dependencies={},
            scienceCustody=server.science_custody_status, dependencyDrain=observation)


if __name__ == "__main__":
    unittest.main()
