from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


TOOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "run_continuous_producer_001c_atomicity_proof.py"
)


def _load_tool():
    name = "producer_001c_atomicity_proof_tool"
    spec = importlib.util.spec_from_file_location(name, TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("Atomicity proof tool could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ContinuousProducer001CAtomicityProofTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = _load_tool()

    def test_production_runtime_failure_restart_and_single_commit(self) -> None:
        root = Path(tempfile.gettempdir()) / f"producer-001c-proof-{uuid.uuid4().hex}"
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))

        result = self.tool.run_physical_atomicity_proof(root)

        self.assertEqual(
            "ATOMIC_COMPOSITION_PHYSICAL_PROOF_PASSED",
            result["classification"],
        )
        proof = result["proof"]
        self.assertTrue(proof["stagingWasReached"])
        self.assertTrue(proof["failureAppended"])
        self.assertFalse(proof["failureChangedAuthoritativeState"])
        self.assertTrue(proof["failureWasByteIdentical"])
        self.assertTrue(proof["failureCheckpointProjectionWasIdentical"])
        self.assertTrue(proof["restartRecoveredNoPhantomState"])
        self.assertTrue(proof["validCompositionCommittedOnce"])
        self.assertTrue(proof["duplicateReplayWasIdempotent"])
        self.assertTrue(proof["failureChronologySurvivedRestart"])

    def test_rejects_runtime_root_outside_temp(self) -> None:
        with self.assertRaises(ValueError):
            self.tool.run_physical_atomicity_proof(Path(__file__).resolve().parent)


if __name__ == "__main__":
    unittest.main()
