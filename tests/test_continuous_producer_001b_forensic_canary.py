from __future__ import annotations

import importlib.util
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CANONICAL_ROOT = Path(
    os.environ.get(
        "MH_CANARY_CANONICAL_ROOT",
        str(Path(__file__).resolve().parents[1]),
    )
)
TOOL_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "run_continuous_producer_001b_forensic_canary.py"
)


def _load_tool():
    os.environ["MH_CANARY_CANONICAL_ROOT"] = str(CANONICAL_ROOT)
    name = "producer_001b_forensic_canary_tool"
    spec = importlib.util.spec_from_file_location(name, TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("Forensic canary tool could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ContinuousProducerForensicCanaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = _load_tool()

    def test_ownership_map_binds_every_authoritative_stage_to_canonical(self) -> None:
        environment = os.environ.copy()
        environment["MH_CANARY_CANONICAL_ROOT"] = str(CANONICAL_ROOT)
        completed = subprocess.run(
            (sys.executable, "-B", str(TOOL_PATH), "ownership"),
            cwd=CANONICAL_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        result = json.loads(completed.stdout)

        self.assertEqual("PASS", result["status"])
        self.assertEqual("OBSERVATIONAL_ONLY", result["wrapperAuthority"]["classification"])
        stages = {item["stage"]: item for item in result["stages"]}
        self.assertIn("REAL_FINVIZ_DISCOVERY", stages)
        self.assertIn("HOT_UNIVERSE_ADMISSION", stages)
        self.assertIn("COMPLETED_BAR_MATERIAL_EVENT_DISPATCH", stages)
        self.assertIn("TRADEPLAN_OR_NO_PLAN_PRODUCTION", stages)
        self.assertIn("RESTART_RECONSTRUCTION", stages)
        self.assertIn("ATOMIC_AUTHORITATIVE_COMPOSITION_PUBLICATION", stages)
        for item in stages.values():
            self.assertEqual("CANONICAL_PRODUCTION_CLASS", item["ownership"])
            self.assertTrue(item["owner"]["sourcePath"].startswith("momentum_hunter/"))

    def test_wrapper_does_not_construct_or_call_authoritative_inputs(self) -> None:
        result = self.tool._wrapper_authority_scan()

        self.assertEqual("PASS", result["status"])
        self.assertEqual([], result["findings"])

    def test_recursive_sanitization_redacts_binding_identity_and_handles_sets(self) -> None:
        result = self.tool._sanitize(
            {
                "accountEnding": "9999",
                "metrics": {"symbols": {"NVDA", "AAPL"}},
                "payload_json": '{"expectedAccountEnding":"9999","safe":"ok"}',
            }
        )

        self.assertEqual("[REDACTED]", result["accountEnding"])
        self.assertEqual(["AAPL", "NVDA"], result["metrics"]["symbols"])
        self.assertNotIn("9999", result["payload_json"])
        self.assertIn("[REDACTED]", result["payload_json"])

    def test_runtime_root_rejects_non_temporary_path(self) -> None:
        with self.assertRaises(self.tool.ForensicCanaryError):
            self.tool._validate_runtime_root(CANONICAL_ROOT / "canary", require_new=False)

    def test_external_root_rejects_canonical_and_accepts_new_bundle_child(self) -> None:
        with self.assertRaises(self.tool.ForensicCanaryError):
            self.tool._validate_external_root(CANONICAL_ROOT, require_new=False)
        candidate = self.tool.EXTERNAL_PARENT / "UNIT-TEST-FORENSIC-CANARY-NOT-CREATED"
        self.assertEqual(
            candidate.resolve(strict=False),
            self.tool._validate_external_root(candidate, require_new=True),
        )

    def test_secret_scan_detects_forbidden_local_binding_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence.json").write_text(
                '{"value":"9999"}', encoding="ascii"
            )

            result = self.tool._secret_scan(root, forbidden_value="9999")

        self.assertEqual("FAIL", result["status"])
        self.assertEqual("BOUND_ENDING", result["findings"][0]["term"])

    def test_capability_scan_has_no_broker_or_order_path(self) -> None:
        result = self.tool._static_capability_scan()

        self.assertEqual("PASS", result["status"])
        self.assertEqual([], result["findings"])

    def test_backfill_accounting_separates_attempts_from_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backfill.json"
            path.write_text(
                json.dumps(
                    {
                        "records": {
                            "AAA": {
                                "symbol": "AAA",
                                "status": "COMPLETE",
                                "attemptCount": 2,
                            },
                            "BBB": {
                                "symbol": "BBB",
                                "status": "FAILED",
                                "attemptCount": 1,
                            },
                        }
                    }
                ),
                encoding="ascii",
            )

            result = self.tool._backfill_accounting(path)

        self.assertEqual(3, result["attempts"])
        self.assertEqual(1, result["successful"])
        self.assertEqual(1, result["failed"])


if __name__ == "__main__":
    unittest.main()
