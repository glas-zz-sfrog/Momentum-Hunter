from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "verify_thinkorswim_rtd_campaign.py"
SPEC = importlib.util.spec_from_file_location("verify_thinkorswim_rtd_campaign", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def configuration() -> dict[str, object]:
    return {
        "taskId": verify.TASK_ID,
        "symbols": verify.SYMBOLS.copy(),
        "fields": verify.ORDERED_FIELDS.copy(),
        "sampleIntervalSeconds": 2,
        "phaseAClassification": "CURRENT_SESSION_FUNCTIONAL_SMOKE_NOT_0400_BOUNDARY",
        "excelElevationPolicy": "CURRENT_USER_PROVEN_75_CELL_RTD_SMOKE",
        "sessionConfigurationRequirement": "LIVE_TRADING_WINDOW_TITLE_OBSERVED",
        "phaseADurationSeconds": 1200,
        "checkpointDurationSeconds": 120,
        "checkpointLeadSeconds": 60,
        "checkpoints": [
            {"checkpointId": checkpoint_id, "scheduledAtEastern": timestamp}
            for checkpoint_id, timestamp in verify.CHECKPOINTS
        ],
    }


class ThinkorswimRtdCampaignTests(unittest.TestCase):
    def test_synthetic_observer_preserves_two_dimensional_matrix_mapping(self) -> None:
        powershell = shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")
        project_root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as directory:
            evidence_root = Path(directory) / "synthetic-evidence"
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(project_root / "tools" / "run_thinkorswim_rtd_campaign.ps1"),
                    "-ProjectRoot",
                    str(project_root),
                    "-CanonicalRoot",
                    str(project_root),
                    "-EvidenceRoot",
                    str(evidence_root),
                    "-ExpectedSourceHead",
                    "SYNTHETIC_NO_GIT_CONTACT",
                    "-ConfigurationPath",
                    str(project_root / "config" / "thinkorswim-rtd-001.json"),
                    "-SyntheticObserverTest",
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("SYNTHETIC_OBSERVER_PASS", result.stdout)
            records = [
                json.loads(line)
                for line in (evidence_root / "observations.ndjson").read_text(encoding="utf-8").splitlines()
            ]
            self.assertGreaterEqual(len(records), 1)
            self.assertEqual(75, len(records[0]["values"]))
            self.assertEqual("SYNTHETIC_0_0", records[0]["values"][0]["value"])
            self.assertEqual("SYNTHETIC_4_14", records[0]["values"][-1]["value"])

    def test_market_only_configuration_passes(self) -> None:
        verify.validate_configuration(configuration())

    def test_account_field_is_rejected(self) -> None:
        value = configuration()
        value["fields"] = ["BID", "POSITION_QTY"]
        with self.assertRaisesRegex(verify.VerificationError, "field list"):
            verify.validate_configuration(value)

    def test_shifted_checkpoint_is_rejected(self) -> None:
        value = configuration()
        value["checkpoints"][0]["scheduledAtEastern"] = "2026-08-24T19:56:00-04:00"
        with self.assertRaisesRegex(verify.VerificationError, "schedule"):
            verify.validate_configuration(value)

    def test_shortened_checkpoint_is_rejected(self) -> None:
        value = configuration()
        value["checkpointDurationSeconds"] = 30
        with self.assertRaisesRegex(verify.VerificationError, "checkpoint window"):
            verify.validate_configuration(value)

    def test_phase_a_boundary_overclaim_is_rejected(self) -> None:
        value = configuration()
        value["phaseAClassification"] = "EXACT_0400_BOUNDARY"
        with self.assertRaisesRegex(verify.VerificationError, "overclaim"):
            verify.validate_configuration(value)

    def test_unproven_elevation_policy_is_rejected(self) -> None:
        value = configuration()
        value["excelElevationPolicy"] = "ASSUME_ADMIN_REQUIRED"
        with self.assertRaisesRegex(verify.VerificationError, "elevation policy"):
            verify.validate_configuration(value)

    def test_papermoney_session_substitution_is_rejected(self) -> None:
        value = configuration()
        value["sessionConfigurationRequirement"] = "PAPERMONEY"
        with self.assertRaisesRegex(verify.VerificationError, "session configuration"):
            verify.validate_configuration(value)

    def test_formula_manifest_requires_exact_documented_shape(self) -> None:
        config = configuration()
        cells = []
        for symbol in config["symbols"]:
            for field in config["fields"]:
                cells.append({"symbol": symbol, "field": field, "formula": f'=RTD("tos.rtd",,"{field}","{symbol}")'})
        manifest = {"taskId": verify.TASK_ID, "timestampAuthority": "LOCAL_OBSERVATION_TIMESTAMP_ONLY", "cells": cells}
        verify.validate_formula_manifest(manifest, config)
        cells[0]["formula"] = '=RTD("private.server",,"BID","SPY")'
        with self.assertRaisesRegex(verify.VerificationError, "unauthorized formula"):
            verify.validate_formula_manifest(manifest, config)

    def test_summary_separates_live_static_empty_and_error(self) -> None:
        records = [
            {"values": [
                {"symbol": "SPY", "field": "BID", "state": "PRESENT", "value": "100"},
                {"symbol": "SPY", "field": "ASK", "state": "PRESENT", "value": "101"},
                {"symbol": "SPY", "field": "MARK", "state": "EMPTY", "value": None},
                {"symbol": "SPY", "field": "LAST", "state": "ERROR", "value": "#N/A"},
            ]},
            {"values": [
                {"symbol": "SPY", "field": "BID", "state": "PRESENT", "value": "100.1"},
                {"symbol": "SPY", "field": "ASK", "state": "PRESENT", "value": "101"},
                {"symbol": "SPY", "field": "MARK", "state": "EMPTY", "value": None},
                {"symbol": "SPY", "field": "LAST", "state": "ERROR", "value": "#N/A"},
            ]},
        ]
        result = verify.summarize_observations(records)["series"]
        self.assertEqual("LIVE_UPDATING", result["SPY:BID"]["classification"])
        self.assertEqual("PRESENT_BUT_STATIC", result["SPY:ASK"]["classification"])
        self.assertEqual("EMPTY", result["SPY:MARK"]["classification"])
        self.assertEqual("ERROR", result["SPY:LAST"]["classification"])

    def test_observation_rejects_nonmarket_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.ndjson"
            value = {
                "taskId": verify.TASK_ID,
                "timestampAuthority": "LOCAL_OBSERVATION_TIMESTAMP_ONLY",
                "values": [{"symbol": "SPY", "field": "POSITION_QTY", "state": "PRESENT", "value": "1"}],
            }
            path.write_text(json.dumps(value) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(verify.VerificationError, "forbidden symbol or field"):
                verify.summarize_observations(verify.read_observations(path))

    def test_observation_rejects_unknown_symbol(self) -> None:
        records = [{
            "values": [
                {"symbol": "TSLA", "field": "BID", "state": "PRESENT", "value": "1"},
            ]
        }]
        with self.assertRaisesRegex(verify.VerificationError, "forbidden symbol or field"):
            verify.summarize_observations(records)

    def test_secret_scan_rejects_token_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.json").write_text('{"access_token":"not-allowed"}', encoding="utf-8")
            with self.assertRaisesRegex(verify.VerificationError, "Secret-shaped"):
                verify.scan_secrets(root)


if __name__ == "__main__":
    unittest.main()
