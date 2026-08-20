from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.overnight_data_fidelity import TASK_ID, fingerprint, write_checkpoint
from momentum_hunter.overnight_data_fidelity_closeout import (
    EXPECTED_CHECKPOINTS,
    _load_state,
    _secret_scan,
    _service_status,
    build_closeout,
)


class OvernightDataFidelityCloseoutTests(unittest.TestCase):
    def _proof(self, code: str) -> dict[str, object]:
        proof: dict[str, object] = {
            "schemaVersion": 1,
            "taskId": TASK_ID,
            "checkpointCode": code,
            "observationWindow": {
                "phase": "OVERNIGHT",
                "startedEastern": "2026-08-20T03:55:00-04:00",
            },
            "providers": {
                "alpaca": {
                    "currentFeed": "overnight",
                    "requests": [{"apiResult": "SUCCESS"}],
                    "capacity": {"largestSuccessfulCoverageRequest": 263},
                    "websocket": {"status": "PASS"},
                    "assetEligibility": {"status": "NOT_QUERIED_MARKET_DATA_ONLY_BOUNDARY"},
                },
                "schwab": {
                    "status": "NOT_RUN_SHARED_TOKEN_NOT_ACTIVE",
                    "streamer": "NOT_RUN_NO_ACCOUNT_BEARING_BOOTSTRAP",
                    "tokenRefreshAttempted": False,
                },
                "finviz": {"status": "NOT_RUN_OUTSIDE_FINVIZ_EXTENDED_WINDOW"},
            },
        }
        proof["evidenceFingerprint"] = fingerprint(proof)
        return proof

    def _state(self, root: Path, commit: str) -> dict[str, object]:
        results = []
        for code in EXPECTED_CHECKPOINTS:
            json_path, _, json_hash, _ = write_checkpoint(self._proof(code), output_root=root)
            results.append({
                "code": code,
                "classification": "COMPLETED",
                "startLagSeconds": 0.25,
                "path": str(json_path),
                "sha256": json_hash,
            })
        state: dict[str, object] = {
            "taskId": TASK_ID,
            "campaignDate": "2026-08-20",
            "status": "TERMINAL",
            "completedAt": "2026-08-21T00:06:00+00:00",
            "sourceIdentity": {"featureCommit": commit},
            "results": results,
        }
        state["stateFingerprint"] = fingerprint(state)
        (root / "campaign-state.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return state

    def test_terminal_closeout_builds_report_manifest_and_zip(self) -> None:
        commit = "a" * 40
        production = {
            "classification": "PASS",
            "canonicalHead": "b" * 40,
            "originMaster": "b" * 40,
            "expectedCanonicalCommit": "b" * 40,
            "canonicalClean": True,
            "protectedHashes": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "evidence"
            root.mkdir()
            self._state(root, commit)
            with patch(
                "momentum_hunter.overnight_data_fidelity_closeout._production_invariants",
                return_value=production,
            ):
                result = build_closeout(
                    output_root=root,
                    source_contract_bytes=b"official sources\n",
                    expected_feature_commit=commit,
                    canonical_root=Path(temporary),
                    expected_canonical_commit="b" * 40,
                    protected_hashes={},
                )

            self.assertEqual("CAMPAIGN_CLOSEOUT_COMPLETED", result["classification"])
            self.assertEqual("FREE_TIER_SUFFICIENT_FOR_NEXT_RESEARCH_STAGE", result["finalDecision"])
            self.assertTrue((root / "closeout" / "FINAL-REPORT.md").exists())
            self.assertTrue((root / "closeout" / "MANIFEST.json").exists())
            self.assertTrue(Path(str(result["zipPath"])).exists())
            self.assertEqual("PASS", result["secretScan"]["classification"])

    def test_state_fingerprint_tampering_is_rejected(self) -> None:
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self._state(root, commit)
            state["status"] = "RUNNING"
            (root / "campaign-state.json").write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(Exception):
                _load_state(root / "campaign-state.json", expected_feature_commit=commit)

    def test_secret_pattern_scan_rejects_credential_shaped_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.json"
            path.write_bytes(b'{"value":"PKABCDEFGHIJKLMNOPQRSTUV"}')
            self.assertEqual("FAIL", _secret_scan([path])["classification"])

    def test_service_status_parses_running_automatic_service(self) -> None:
        class Completed:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout
                self.returncode = 0

        with patch(
            "momentum_hunter.overnight_data_fidelity_closeout.subprocess.run",
            side_effect=(
                Completed("STATE              : 4  RUNNING\n"),
                Completed("START_TYPE         : 2   AUTO_START\n"),
            ),
        ):
            status = _service_status("Example")
        self.assertEqual("RUNNING", status["state"])
        self.assertEqual("AUTO_START", status["startMode"])


if __name__ == "__main__":
    unittest.main()
