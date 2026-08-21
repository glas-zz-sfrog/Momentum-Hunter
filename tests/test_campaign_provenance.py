from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "verify_campaign_provenance.py"
SPEC = importlib.util.spec_from_file_location("verify_campaign_provenance", MODULE_PATH)
assert SPEC and SPEC.loader
PROVENANCE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROVENANCE)


def sha(character: str) -> str:
    return character * 64


def git_sha(character: str) -> str:
    return character * 40


def checks(**overrides: bool) -> dict[str, bool]:
    result = {name: True for name in PROVENANCE.REVALIDATION_CHECKS}
    result.update(overrides)
    return result


def draft(*, changes: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "campaignFrozenIdentity": {
            "taskId": "ARGUS-LONG-CAMPAIGN-TEST",
            "sourceGitHead": git_sha("1"),
            "sourceFileManifestSha256": sha("A"),
            "configurationFingerprint": sha("B"),
            "executableSha256": sha("C"),
            "evidenceRootFingerprint": sha("D"),
            "providerRouteAllowlistSha256": sha("E"),
            "startedAt": "2026-08-20T01:00:00-05:00",
            "processIdentity": {
                "processId": 1234,
                "executableSha256": sha("C"),
                "startedAt": "2026-08-20T01:00:00-05:00",
            },
        },
        "productionBaseline": {
            "canonicalGitHead": git_sha("1"),
            "installedProductGitHead": git_sha("1"),
            "manifestSha256": sha("F"),
            "observedAt": "2026-08-20T01:00:00-05:00",
            "services": [
                {
                    "name": "MomentumHunterContinuousRuntime",
                    "executableSha256": sha("1"),
                    "configSha256": sha("2"),
                    "deploymentManifestSha256": sha("3"),
                }
            ],
        },
        "sharedResources": [
            {
                "resourceId": "schwab-oauth-state",
                "resourceType": "WINDOWS_DPAPI_SECRET_STATE",
                "mutable": True,
                "owner": "MomentumHunterContinuousRuntime",
                "allowedWriters": ["MomentumHunterContinuousRuntime"],
                "campaignAccess": "READ_ONLY",
                "mutationRules": "Production may refresh only with a declared change and revalidation.",
                "baselineFingerprint": sha("4"),
            }
        ],
        "authorizedExternalChanges": changes or [],
        "campaignIntegrityObservations": {
            "campaignSourceUnchanged": True,
            "campaignExecutableUnchanged": True,
            "campaignConfigurationUnchanged": True,
            "campaignEvidenceValid": True,
            "campaignProcessIdentityValid": True,
            "externalProductionTouchedCampaignPaths": False,
            "undeclaredSharedMutableResource": False,
        },
    }


def authorized_change(
    *,
    sequence: int = 1,
    old_canonical: str | None = None,
    new_canonical: str | None = None,
    old_installed: str | None = None,
    new_installed: str | None = None,
    revalidation_checks: dict[str, bool] | None = None,
) -> dict[str, object]:
    selected_checks = revalidation_checks or checks()
    return {
        "sequence": sequence,
        "observedAt": f"2026-08-20T0{sequence + 1}:00:00-05:00",
        "taskId": f"ARGUS-AUTHORIZED-{sequence:03d}",
        "authorization": "CEO directive and bounded task charter",
        "canonicalGit": {
            "oldGitHead": old_canonical or git_sha("1"),
            "newGitHead": new_canonical or git_sha("2"),
        },
        "installedProduct": {
            "oldGitHead": old_installed or git_sha("1"),
            "newGitHead": new_installed or git_sha("2"),
        },
        "deploymentManifest": {
            "oldSha256": sha("F"),
            "newSha256": sha("5"),
        },
        "affectedServices": ["MomentumHunterContinuousRuntime"],
        "sharedResourcesTouched": ["schwab-oauth-state"],
        "isolationRevalidation": {
            "classification": (
                PROVENANCE.REVALIDATION_PASS
                if all(selected_checks.values())
                else PROVENANCE.REVALIDATION_FAIL
            ),
            "checks": selected_checks,
            "evidenceSha256": sha("6"),
        },
    }


class CampaignProvenanceTests(unittest.TestCase):
    def test_historical_report_preserves_failure_and_marks_provenance_gaps(self) -> None:
        report_path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "argus-office"
            / "reports"
            / "audits"
            / "ARGUS-GIT-PROVENANCE-RECONCILIATION-001.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        historical = report["historicalResultPreserved"]
        self.assertEqual("FAILED", historical["globalProductionNonmutation"])
        self.assertFalse(historical["rewritten"])
        self.assertFalse(historical["providerEvidenceAdjudicated"])
        self.assertEqual(
            "AUTHORIZED_GOVERNANCE_ONLY_DIVERGENCE",
            report["installedProductVsGovernance"]["classification"],
        )
        self.assertEqual(
            "NOT_RETROACTIVELY_ADJUDICATED",
            report["historicalCampaignAssessmentUnderProspectiveFields"]["campaignNonmutation"],
        )
        gaps = {
            row["resourceId"]
            for row in report["sharedResourceInventory"]
            if row.get("classification") == "CAMPAIGN_PROVENANCE_GAP"
        }
        self.assertIn("SCHWAB_USER_DPAPI_OAUTH_STATE", gaps)
        recovered = report["overnightCampaign"]["recoveredSourceFileManifest"]
        payload = {
            "schemaVersion": 1,
            "sourceGitHead": report["overnightCampaign"]["frozenSourceGitHead"],
            "files": sorted(recovered["files"], key=lambda row: row["path"]),
        }
        self.assertEqual(recovered["sha256"], PROVENANCE.canonical_fingerprint(payload))

    def test_no_change_proves_both_nonmutation_claims(self) -> None:
        document = PROVENANCE.finalize_document(draft())
        integrity = PROVENANCE.validate_document(document)
        self.assertEqual("PASS", integrity["campaignNonmutation"])
        self.assertTrue(integrity["globalProductionNonmutation"])
        self.assertFalse(integrity["authorizedExternalChangesPresent"])

    def test_revalidated_external_change_keeps_campaign_integrity_separate(self) -> None:
        document = PROVENANCE.finalize_document(draft(changes=[authorized_change()]))
        integrity = PROVENANCE.validate_document(document)
        self.assertEqual("PASS", integrity["campaignNonmutation"])
        self.assertFalse(integrity["globalProductionNonmutation"])
        self.assertTrue(integrity["authorizedExternalChangesPresent"])
        self.assertTrue(integrity["authorizedExternalChangesRevalidated"])

    def test_broken_revalidation_fails_campaign_integrity(self) -> None:
        change = authorized_change(
            revalidation_checks=checks(sharedPathsRevalidated=False)
        )
        document = PROVENANCE.finalize_document(draft(changes=[change]))
        self.assertEqual("FAIL", document["integrityResult"]["campaignNonmutation"])
        self.assertEqual("CAMPAIGN_ISOLATION_BROKEN", document["integrityResult"]["classification"])

    def test_tampering_is_rejected(self) -> None:
        document = PROVENANCE.finalize_document(draft(changes=[authorized_change()]))
        document["campaignFrozenIdentity"]["taskId"] = "TAMPERED"
        with self.assertRaisesRegex(PROVENANCE.ProvenanceValidationError, "document fingerprint"):
            PROVENANCE.validate_document(document)

    def test_undeclared_shared_resource_is_rejected(self) -> None:
        change = authorized_change()
        change["sharedResourcesTouched"] = ["undeclared-state"]
        with self.assertRaisesRegex(PROVENANCE.ProvenanceValidationError, "undeclared shared resource"):
            PROVENANCE.finalize_document(draft(changes=[change]))

    def test_transition_chain_mismatch_is_rejected(self) -> None:
        first = authorized_change()
        second = authorized_change(
            sequence=2,
            old_canonical=git_sha("9"),
            new_canonical=git_sha("3"),
            old_installed=git_sha("2"),
            new_installed=git_sha("3"),
        )
        with self.assertRaisesRegex(PROVENANCE.ProvenanceValidationError, "Canonical Git transition chain"):
            PROVENANCE.finalize_document(draft(changes=[first, second]))

    def test_abbreviated_git_identity_is_rejected(self) -> None:
        value = draft()
        value["campaignFrozenIdentity"]["sourceGitHead"] = "a754226"
        with self.assertRaisesRegex(PROVENANCE.ProvenanceValidationError, "full Git SHA"):
            PROVENANCE.finalize_document(value)

    def test_malformed_file_manifest_hash_is_rejected(self) -> None:
        value = draft()
        value["campaignFrozenIdentity"]["sourceFileManifestSha256"] = "NOT_A_HASH"
        with self.assertRaisesRegex(PROVENANCE.ProvenanceValidationError, "full SHA-256"):
            PROVENANCE.finalize_document(value)

    def test_secret_shaped_field_is_rejected(self) -> None:
        value = draft()
        value["campaignFrozenIdentity"]["accessToken"] = "must-not-be-recorded"
        with self.assertRaisesRegex(PROVENANCE.ProvenanceValidationError, "forbidden secret-shaped field"):
            PROVENANCE.finalize_document(value)

    def test_write_is_exactly_once(self) -> None:
        document = PROVENANCE.finalize_document(draft())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "provenance.json"
            PROVENANCE.write_document_once(path, document)
            self.assertEqual(document, json.loads(path.read_text(encoding="utf-8")))
            with self.assertRaises(FileExistsError):
                PROVENANCE.write_document_once(path, document)


if __name__ == "__main__":
    unittest.main()
