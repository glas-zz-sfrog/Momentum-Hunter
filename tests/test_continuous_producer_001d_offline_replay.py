from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.run_continuous_producer_001d_offline_replay import run_offline_replay


class ContinuousProducer001dOfflineReplayTests(unittest.TestCase):
    def test_exact_path_ignores_discarded_provisional_and_replays_stably(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "producer-001d-offline"
            result = run_offline_replay(root)

        self.assertEqual("OFFLINE_EXACT_PATH_REPLAY_PASSED", result["classification"])
        proof = result["proof"]
        self.assertGreater(proof["observedProvisionalVersionCount"], 0)
        self.assertEqual(0, proof["admittedProvisionalBarCount"])
        self.assertTrue(proof["discardedProvisionalDidNotChangeContextIdentity"])
        self.assertEqual("READY", proof["readinessStatus"])
        self.assertIn(proof["naturalCompositionOutcome"], {"TRADEPLAN", "NO_PLAN"})
        self.assertTrue(proof["restartCycleIdentityStable"])
        self.assertTrue(proof["restartFingerprintStable"])
        self.assertTrue(proof["restartPersistenceByteStable"])
        self.assertEqual("UNAVAILABLE", proof["orderCapability"])


if __name__ == "__main__":
    unittest.main()
