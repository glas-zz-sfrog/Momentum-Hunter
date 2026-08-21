from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "tools" / "verify_overnight_evidence_reconciliation.py"
REPORT_PATH = (
    ROOT
    / "docs"
    / "argus-office"
    / "reports"
    / "audits"
    / "ARGUS-OVERNIGHT-EVIDENCE-ISOLATION-RECONCILIATION-001.json"
)
SPEC = importlib.util.spec_from_file_location("overnight_reconciliation", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class OvernightEvidenceReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    def test_authoritative_overlay_validates(self) -> None:
        result = MODULE.validate_overlay(self.report)
        self.assertEqual(15, result["checkpointCount"])
        self.assertEqual(32, result["claimCount"])
        self.assertEqual(17, result["claimCounts"]["VALIDATED"])

    def test_tree_digest_is_path_size_and_hash_bound(self) -> None:
        rows = [
            {"path": "a.txt", "bytes": 1, "sha256": "A" * 64},
            {"path": "b.txt", "bytes": 2, "sha256": "B" * 64},
        ]
        payload = (
            "a.txt|1|" + "A" * 64 + "\n" + "b.txt|2|" + "B" * 64
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(payload).hexdigest().upper(),
            MODULE.evidence_tree_sha256(rows),
        )

    def test_historical_global_failure_cannot_be_upgraded(self) -> None:
        report = copy.deepcopy(self.report)
        report["historicalCampaignResult"]["globalProductionNonmutation"] = "PASSED"
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "must remain FAILED"
        ):
            MODULE.validate_overlay(report)

    def test_historical_rewrite_claim_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["historicalCampaignResult"]["historicalFilesRewritten"] = True
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "historical rewriting"
        ):
            MODULE.validate_overlay(report)

    def test_manifest_exception_cannot_be_hidden(self) -> None:
        report = copy.deepcopy(self.report)
        report["historicalCampaignResult"]["originalManifestMismatchCount"] = 0
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "manifest exception"
        ):
            MODULE.validate_overlay(report)

    def test_post_hoc_source_manifest_cannot_be_upgraded(self) -> None:
        report = copy.deepcopy(self.report)
        report["sourceIdentity"]["classification"] = "START_TIME_SOURCE_IDENTITY_PROVEN"
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "upgraded or lost"
        ):
            MODULE.validate_overlay(report)

    def test_duplicate_claim_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["claims"][1]["claimId"] = report["claims"][0]["claimId"]
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "missing or duplicate"
        ):
            MODULE.validate_overlay(report)

    def test_claim_count_drift_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["claimCounts"]["VALIDATED"] += 1
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "Claim count mismatch"
        ):
            MODULE.validate_overlay(report)

    def test_unknown_claim_class_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["claims"][0]["finalClassification"] = "PROBABLY_VALID"
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "classification is invalid"
        ):
            MODULE.validate_overlay(report)

    def test_missing_checkpoint_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["checkpointMatrix"].pop()
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "checkpoint count mismatch"
        ):
            MODULE.validate_overlay(report)

    def test_checkpoint_hash_tampering_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["checkpointMatrix"][0]["checkpointHash"] = "0" * 64
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "Overlay hash mismatch"
        ):
            MODULE.validate_overlay(report)

    def test_secret_field_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["apiKey"] = "redacted"
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "Forbidden secret field"
        ):
            MODULE.validate_overlay(report)

    def test_credential_shaped_value_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        authorization_scheme = "Bearer "
        synthetic_value = "abcdefghijklmnopqrstuvwxyz0123456789"
        report["sevenAnswers"]["smallestRemainingExperiment"] = (
            authorization_scheme + synthetic_value
        )
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "Credential-shaped value"
        ):
            MODULE.validate_overlay(report)

    def test_nonzero_provider_activity_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["productionProtection"]["providerCalls"] = 1
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "claims mutation"
        ):
            MODULE.validate_overlay(report)

    def test_production_identity_drift_is_rejected(self) -> None:
        report = copy.deepcopy(self.report)
        report["productionProtection"]["finalServiceSnapshotSha256"] = "0" * 64
        with self.assertRaisesRegex(
            MODULE.ReconciliationValidationError, "before/after identity mismatch"
        ):
            MODULE.validate_overlay(report)


if __name__ == "__main__":
    unittest.main()
