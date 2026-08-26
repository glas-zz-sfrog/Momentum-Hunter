from __future__ import annotations

import importlib.util
import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


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

    def test_external_root_rejects_parent_and_accepts_new_bundle_child(self) -> None:
        with self.assertRaises(self.tool.ForensicCanaryError):
            self.tool._validate_external_root(
                self.tool.EXTERNAL_PARENT,
                require_new=False,
            )
        candidate = self.tool.EXTERNAL_PARENT / "UNIT-TEST-FORENSIC-CANARY-NOT-CREATED"
        self.assertEqual(
            candidate.resolve(strict=False),
            self.tool._validate_external_root(candidate, require_new=True),
        )

    def test_secret_scan_detects_forbidden_local_binding_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence.json").write_text(
                '{"accountEnding":"9999"}', encoding="ascii"
            )

            result = self.tool._secret_scan(root, forbidden_value="9999")

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            result["findings"][0]["term"],
            {"UNREDACTED_SENSITIVE_JSON_VALUE", "BOUND_ENDING_CONTEXT"},
        )

    def test_secret_scan_ignores_binding_digits_inside_market_values_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "market.json").write_text(
                '{"price":25.73,"volume":125731,"fingerprint":"abc2573def"}',
                encoding="ascii",
            )

            result = self.tool._secret_scan(root, forbidden_value="2573")

        self.assertEqual("PASS", result["status"])
        self.assertEqual([], result["findings"])

    def test_capability_scan_has_no_broker_or_order_path(self) -> None:
        result = self.tool._static_capability_scan()

        self.assertEqual("PASS", result["status"])
        self.assertEqual([], result["findings"])

    def test_failed_provider_outcome_is_terminal_and_package_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in self.tool.CORE_FORENSIC_EVIDENCE:
                (root / name).write_text("{}", encoding="ascii")
            (root / self.tool.TERMINAL_FAILURE_MARKER).write_text(
                json.dumps(
                    {
                        "status": "FAILED_PRESERVED",
                        "failureClass": "RuntimeError",
                        "detail": "provider phase failed",
                    }
                ),
                encoding="ascii",
            )

            terminal = self.tool._terminal_evidence_state(root)
            analyzed = self.tool._analyze_terminal(root, terminal)

        self.assertEqual("FAILED_PRESERVED", terminal["terminalOutcome"])
        self.assertFalse(terminal["acceptanceEvidenceComplete"])
        self.assertIn("phase-1-state.json", terminal["missingAcceptanceEvidence"])
        classifications = analyzed["analysis"]["classifications"]
        self.assertEqual("FAILED", classifications["PROVIDER_CANARY_ACCEPTANCE"])
        self.assertEqual(
            "YES", classifications["TERMINAL_FAILURE_EVIDENCE_PRESERVED"]
        )
        self.assertEqual("NO", classifications["MERGE_AUTHORIZED"])

    def test_terminal_runtime_artifacts_are_sanitized_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            evidence = root / "evidence"
            runtime.mkdir()
            evidence.mkdir()
            (runtime / "state.json").write_text(
                '{"accountEnding":"9999","safe":"preserved"}',
                encoding="ascii",
            )

            result = self.tool._preserve_terminal_runtime_artifacts(
                runtime,
                evidence,
            )
            preserved = json.loads(
                (evidence / "runtime-artifacts" / "state.json").read_text(
                    encoding="ascii"
                )
            )

        self.assertEqual("PRESERVED", result["status"])
        self.assertEqual("[REDACTED]", preserved["accountEnding"])
        self.assertEqual("preserved", preserved["safe"])

    def test_failed_acceptance_does_not_block_review_ready_zip(self) -> None:
        result = self.tool._package_review_classifications(
            {
                "PROVIDER_CANARY_ACCEPTANCE": "FAILED",
                "ACCEPTED_COMPOSITION_CYCLE_PROVEN": "NO",
            },
            manifest_verified=True,
            focused_rerun_passed=False,
        )

        self.assertEqual("FAILED", result["PROVIDER_CANARY_ACCEPTANCE"])
        self.assertEqual("NO", result["ACCEPTED_COMPOSITION_CYCLE_PROVEN"])
        self.assertEqual("NO", result["SECOND_EYE_ZIP_SELF_CONTAINED"])
        self.assertEqual("YES", result["READY_FOR_SECOND_EYE_REVIEW"])

    def test_failed_provider_outcome_can_be_sealed_without_phase_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = {
                "sourceGit": "source",
                "canaryTaskGit": "task",
                "canonicalGit": "canonical",
                "services": [],
                "selectedProductionHashes": [],
                "manifestSafety": {},
            }
            core = {
                "campaign-config.json": {"runtimeIdentity": "failed-runtime"},
                "canonical-ownership-map.json": {"status": "PASS"},
                "failed-evidence-preservation.json": {},
                "forensic-standard-verification.json": {"status": "PASS"},
                "production-baseline-before.json": baseline,
                self.tool.TERMINAL_FAILURE_MARKER: {
                    "status": "FAILED_PRESERVED",
                    "failureClass": "RuntimeError",
                    "detail": "provider phase failed",
                },
            }
            for name, payload in core.items():
                (root / name).write_text(json.dumps(payload), encoding="ascii")

            with (
                mock.patch.object(
                    self.tool,
                    "_validate_external_root",
                    return_value=root,
                ),
                mock.patch.object(
                    self.tool,
                    "_validate_failed_evidence",
                    return_value={},
                ),
                mock.patch.object(
                    self.tool,
                    "_production_baseline",
                    return_value=baseline,
                ),
            ):
                result = self.tool._seal(SimpleNamespace(evidence_root=root))

            analysis = json.loads(
                (root / "forensic-analysis.json").read_text(encoding="ascii")
            )
            inventory = json.loads(
                (root / "terminal-evidence-inventory.json").read_text(
                    encoding="ascii"
                )
            )

        self.assertEqual(0, result)
        self.assertEqual(
            "FAILED", analysis["classifications"]["PROVIDER_CANARY_ACCEPTANCE"]
        )
        self.assertIn("phase-2-receipt.json", inventory["missingAcceptanceEvidence"])

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

    def test_completed_bar_analyzer_reconstructs_valid_and_premature_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partition = (
                root
                / "runtime-artifacts"
                / "market-data"
                / "minute"
                / "2026-08-26"
                / "AAA.json"
            )
            partition.parent.mkdir(parents=True)

            def candle(timestamp: str, close: float):
                return {
                    "symbol": "AAA",
                    "timestamp": timestamp,
                    "sessionDate": "2026-08-26",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": close,
                    "volume": 500.0,
                    "source": "schwab-trader-api-price-history",
                    "ohlcvComplete": True,
                }

            early = candle("2026-08-26T14:30:00+00:00", 100.0)
            valid = candle("2026-08-26T14:31:00+00:00", 100.5)
            partition.write_text(
                json.dumps(
                    {
                        "bars": [
                            {
                                "historyVersions": [
                                    {
                                        "versionId": "early",
                                        "firstReceivedAt": "2026-08-26T14:30:30+00:00",
                                        "candle": early,
                                    }
                                ]
                            },
                            {
                                "historyVersions": [
                                    {
                                        "versionId": "valid",
                                        "firstReceivedAt": "2026-08-26T14:32:00+00:00",
                                        "candle": valid,
                                    }
                                ]
                            },
                        ]
                    }
                ),
                encoding="ascii",
            )

            def event_for(value, occurred_at):
                semantic = self.tool._canonical_bar_semantic_identity(value)
                provider_timestamp = value["timestamp"]
                source = self.tool._fingerprint(
                    "continuous-completed-bar-material-v2",
                    {
                        "symbol": "AAA",
                        "providerTimestamp": provider_timestamp,
                        "barFingerprint": semantic,
                        "sourceEvidenceFingerprint": semantic,
                    },
                )
                return {
                    "event_id": f"continuous-completed-bar-{source[:24]}",
                    "trigger": "CANONICAL_BAR_COMPLETED",
                    "occurred_at": occurred_at,
                    "symbol": "AAA",
                    "source_fingerprint": source,
                }

            result = self.tool._completed_bar_finality_accounting(
                root,
                (
                    event_for(early, "2026-08-26T14:30:30+00:00"),
                    event_for(valid, "2026-08-26T14:32:00+00:00"),
                ),
            )

        self.assertEqual(1, result["prematureCompletedEventCount"])
        self.assertEqual(1, result["validCompletedEventCount"])
        self.assertEqual(0, result["unmatchedEventCount"])


if __name__ == "__main__":
    unittest.main()
