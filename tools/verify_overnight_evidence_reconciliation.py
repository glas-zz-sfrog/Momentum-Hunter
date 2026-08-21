from __future__ import annotations

"""Verify the read-only overnight evidence reconciliation overlay.

This standalone audit tool has no provider, credential, account, broker,
service, scheduler, or runtime imports. It reads an immutable historical
evidence tree and a repository audit overlay only.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence


EXPECTED_FILE_COUNT = 51
EXPECTED_TREE_SHA256 = "5F52C966F5724A940C0B855ED1DC73AD6F60DFA1629FCA7F3CC6F93141573ED6"
EXPECTED_CAMPAIGN_SOURCE = "a75422605e67575d267d7d2980519878ec3a5a26"
EXPECTED_CAMPAIGN_MODULE_SHA256 = "B25E99BB7AB9581A5140F237E872D5133B71C99EC8CBC278FD1F1A4E450EEB13"
EXPECTED_RECONSTRUCTED_SOURCE_MANIFEST_SHA256 = (
    "6F698AA4CE55F6E5C8AE6FC18B70CCF5383D439F0B5402F7736FFA0177A68116"
)
EXPECTED_STDOUT_EXCEPTION = {
    "path": "closeout-147ad75.stdout.log",
    "manifestBytes": 0,
    "manifestSha256": "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
    "retainedBytes": 999,
    "retainedSha256": "423DFF6CD0E30D4549A55416023516AF76E0DBC06A0DB74E2FDB7E49380584EA",
}
EXPECTED_CHECKPOINTS = {
    "BOUNDARY_0355_ET": (
        "D472828ACB5A35E0CEB8F5FFE21588C21FB24C66F19D979FE58714A2F0738840",
        "5AFAF64CDA7229373B6DF2793D11B7DB8D2605F264301260943F428398FDA4D5",
    ),
    "BOUNDARY_0400_ET": (
        "DA6795652A05F5B8BDDC3E9750880F3492B45BCE3EF40FD7F007D5611C53DC91",
        "6E991B7D9866EC79CB172BAFCDA83EB1B552C9B85EE5285060EE46DD235C653E",
    ),
    "BOUNDARY_0405_ET": (
        "C6923C9AEA568845D71942BDA5C6B5A4CFA01C4CC7576E2FD2210017A69DA740",
        "7E407E9C1037FD3E728F2F5E7ECECAF036031140B6393258138BAA961DAC6146",
    ),
    "BOUNDARY_0415_ET": (
        "3A2E56E636C5D0C017706AE1D321776974CC028F3DDB1796FCE20007796862C2",
        "25FCF7EDB085E1E23232FE6FBBEDB301F0B20FEBF33E30837CC99285DD9FD1B3",
    ),
    "EARLY_0500_ET": (
        "40686F42F97BAC3CD4AA6051BB3ABBEAB6BBB4A350F25D4D0F891921A4204F89",
        "0B2EF223828E3D82C9FE21FD8184D3FAE7C4852A823D593437A2A1A30A0CA0AC",
    ),
    "EARLY_0600_ET": (
        "53DCD3074D722408B1A5DEDA878F451FBC8AFE01D8207721BF179ACAD253EAAD",
        "5F1851E609FDAEFFFA4B7FDB25EBF73A576BE5CF481E095F7DFFE5DF55CD1599",
    ),
    "PRE_0655_ET": (
        "D0D3CA961F7E9A6B2588606F5B0DE28212D3355B350933C99F9DEA2579A19C5D",
        "7FF88CCEE0C81EA3C3927CFDAD519039B2A29B5F0D147C49B711A4E504169AC8",
    ),
    "PRE_0700_ET": (
        "CA321503CB5E312F7009D9C95376EA1E4415781282115DB82CE915EE0370E50B",
        "1AA4FE6C6C4911F64FBE576AAD3EDA6EF85F9331E5A5273FAC5A4B34620046FF",
    ),
    "PRE_0705_ET": (
        "B61B9EB1BB81E097AAF47CB8E1C5BAC7F650D7CE9365197273C288DA8E6F7241",
        "FA377F896F990215D5D77AECC6ED1248FFF29C9477EA63883DF4C2887258570B",
    ),
    "PRE_0800_ET": (
        "51211A27B12B0AD3D47CA4D3243F0E41E8B56E153008BE4F5CBC6DBC3C06E825",
        "A0565613172BA713286E37C5EBD93D3770B4418BDD0E26C2DF5AB5CF6C7B974A",
    ),
    "REGULAR_0945_ET": (
        "E9210EB1D5F33B90276410DC3830765345240926AFD637F5EA6E93FCBCAE2969",
        "B872F824ED4DE36437EFE6AC373CA3F391A207BADDA25560FD8067C985ECFFC0",
    ),
    "REGULAR_1000_ET": (
        "0E34F0B01D84D4298C02EB01E1FC87D8212263783535BDFD2408D957A96ED1F9",
        "77605F2EBE676D2E2A20D3E55DE989EF625FEAF35C00BB249420C8E9B2735A88",
    ),
    "AFTER_1605_ET": (
        "6C3F110CD311EBA685408AC970AC9692437980EA13ED131626E32441315E9DB9",
        "19555021D98A694E53C95E9A19A519CE5916A61959F9ECE1A38934A7E4835760",
    ),
    "AFTER_1955_ET": (
        "A255438A3374AF13C8394EFDF9E445B1A51ECD5E85931E1F944B518760C88852",
        "D7F6610EB04B387AC3FBB6D0426DBCAA4900180A0540714D76E1DAD6338028FC",
    ),
    "OVERNIGHT_2005_ET": (
        "D7E301D1EADEA9C3A76E50ADCE2AFDF28F07C484987356705D044008FDFDDC58",
        "40ECEBD6EA57AD4095B9A88BEC0533F8B7DF0C5F320B6590DFDE934C3A43A0F0",
    ),
}
CLAIM_CLASSES = {
    "VALIDATED",
    "VALID_WITH_PROVENANCE_LIMITATION",
    "UNPROVEN",
    "INVALIDATED",
}
DEPENDENCY_CLASSES = {
    "NOT_SHARED",
    "SHARED_IMMUTABLE",
    "SHARED_MUTABLE_UNCHANGED",
    "SHARED_MUTABLE_CHANGED",
    "HISTORICAL_STATE_UNPROVEN",
}
CLAIM_FIELDS = {
    "claimId",
    "provider",
    "marketPhase",
    "checkpoints",
    "originalClaim",
    "evidenceFiles",
    "sourceIdentity",
    "sharedDependencies",
    "authorizedProductionChangeIntersection",
    "materiality",
    "finalClassification",
    "limitation",
    "rerunRequired",
}
CHECKPOINT_FIELDS = {
    "code",
    "scheduledTimeEastern",
    "actualExecutionTimeEastern",
    "completedAtUtc",
    "sourceSha",
    "checkpointHash",
    "evidenceFingerprint",
    "providersAttempted",
    "providerResult",
    "externalProductionState",
    "sharedResourceState",
    "adjudication",
    "limitation",
}
FORBIDDEN_FIELD_NAMES = {
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "secretkey",
    "apikey",
    "password",
    "accounthash",
    "fullaccountnumber",
    "authorizationheader",
    "credentialvalue",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{20,}"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bPK[A-Z0-9]{18,}\b"),
)


class ReconciliationValidationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def evidence_tree_rows(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )
    for path in files:
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def evidence_tree_sha256(rows: Sequence[Mapping[str, object]]) -> str:
    payload = "\n".join(
        f"{row['path']}|{row['bytes']}|{row['sha256']}" for row in rows
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def verify_historical_evidence(root: Path) -> dict[str, object]:
    rows = evidence_tree_rows(root)
    if len(rows) != EXPECTED_FILE_COUNT:
        raise ReconciliationValidationError(
            f"Expected {EXPECTED_FILE_COUNT} historical files; found {len(rows)}."
        )
    tree_sha = evidence_tree_sha256(rows)
    if tree_sha != EXPECTED_TREE_SHA256:
        raise ReconciliationValidationError(
            "OVERNIGHT_EVIDENCE_TREE_MUTATED_AFTER_AUDIT"
        )

    manifest = _load_json(root / "closeout" / "MANIFEST.json")
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, list) or manifest.get("fileCount") != 49:
        raise ReconciliationValidationError("Original manifest file count is invalid.")
    manifest_mismatches: list[dict[str, object]] = []
    for entry in manifest_files:
        if not isinstance(entry, dict):
            raise ReconciliationValidationError("Original manifest entry is invalid.")
        path = root / str(entry.get("path", ""))
        if not path.is_file():
            raise ReconciliationValidationError(f"Manifest file is missing: {path}")
        actual_size = path.stat().st_size
        actual_hash = sha256_file(path)
        if actual_size != entry.get("bytes") or actual_hash != entry.get("sha256"):
            manifest_mismatches.append(
                {
                    "path": str(entry.get("path")),
                    "manifestBytes": entry.get("bytes"),
                    "manifestSha256": entry.get("sha256"),
                    "retainedBytes": actual_size,
                    "retainedSha256": actual_hash,
                }
            )
    if manifest_mismatches != [EXPECTED_STDOUT_EXCEPTION]:
        raise ReconciliationValidationError(
            "Original manifest has an unknown or changed inconsistency."
        )

    stdout_result = _load_json(root / "closeout-147ad75.stdout.log")
    closeout_result = _load_json(root / "closeout" / "CLOSEOUT-RESULT.json")
    if stdout_result != closeout_result:
        raise ReconciliationValidationError(
            "Terminal stdout exception does not match the closeout result."
        )

    closeout = _load_json(root / "closeout" / "CLOSEOUT-RESULT.json")
    if closeout.get("productionNonmutation") != "FAIL":
        raise ReconciliationValidationError(
            "Historical global production nonmutation was rewritten."
        )

    state = _load_json(root / "campaign-state.json")
    if state.get("status") != "TERMINAL" or state.get("processId") != 65020:
        raise ReconciliationValidationError("Campaign terminal/process identity mismatch.")
    source = state.get("sourceIdentity")
    if not isinstance(source, dict) or source.get("featureCommit") != EXPECTED_CAMPAIGN_SOURCE:
        raise ReconciliationValidationError("Campaign source identity mismatch.")
    results = state.get("results")
    if not isinstance(results, list) or len(results) != len(EXPECTED_CHECKPOINTS):
        raise ReconciliationValidationError("Campaign result count mismatch.")
    result_by_code = {entry.get("code"): entry for entry in results if isinstance(entry, dict)}
    if set(result_by_code) != set(EXPECTED_CHECKPOINTS):
        raise ReconciliationValidationError("Campaign checkpoint set mismatch.")

    for code, (expected_hash, expected_fingerprint) in EXPECTED_CHECKPOINTS.items():
        entry = result_by_code[code]
        if entry.get("classification") != "COMPLETED":
            raise ReconciliationValidationError(f"Checkpoint is not COMPLETED: {code}")
        if entry.get("sha256") != expected_hash:
            raise ReconciliationValidationError(f"State hash mismatch: {code}")
        path = root / "checkpoints" / f"{code}.json"
        if sha256_file(path) != expected_hash:
            raise ReconciliationValidationError(f"Checkpoint hash mismatch: {code}")
        checkpoint = _load_json(path)
        if checkpoint.get("checkpointCode") != code:
            raise ReconciliationValidationError(f"Checkpoint code mismatch: {code}")
        if checkpoint.get("evidenceFingerprint") != expected_fingerprint:
            raise ReconciliationValidationError(
                f"Checkpoint fingerprint mismatch: {code}"
            )
        source_identity = checkpoint.get("sourceIdentity")
        if (
            not isinstance(source_identity, dict)
            or source_identity.get("moduleSha256")
            != EXPECTED_CAMPAIGN_MODULE_SHA256
        ):
            raise ReconciliationValidationError(
                f"Checkpoint source module mismatch: {code}"
            )
    return {
        "fileCount": len(rows),
        "treeSha256": tree_sha,
        "manifestFileCount": len(manifest_files),
        "manifestVerification": "PASS_WITH_ONE_SELF_REFERENTIAL_TERMINAL_STDOUT_EXCEPTION",
        "manifestMismatchCount": len(manifest_mismatches),
        "checkpointCount": len(EXPECTED_CHECKPOINTS),
    }


def validate_overlay(overlay: Mapping[str, object]) -> dict[str, object]:
    _reject_secrets(overlay)
    if overlay.get("schemaVersion") != 1:
        raise ReconciliationValidationError("Unsupported overlay schema version.")
    if overlay.get("classification") != "OVERNIGHT_EVIDENCE_RECONCILED":
        raise ReconciliationValidationError("Overlay classification is not reconciled.")

    authority = _mapping(overlay, "authority")
    if (
        authority.get("auditCommit")
        != "75ace1334fe86a77eb09b2e5919cc6afa37dbc28"
        or authority.get("auditCommitPushed") is not True
        or authority.get("auditCommitFastForwardedToMaster") is not True
        or authority.get("masterAtAuditIntegration")
        != authority.get("auditCommit")
        or authority.get("originMasterAtAuditIntegration")
        != authority.get("auditCommit")
    ):
        raise ReconciliationValidationError("Audit integration identity mismatch.")

    historical = _mapping(overlay, "historicalCampaignResult")
    if historical.get("globalProductionNonmutation") != "FAILED":
        raise ReconciliationValidationError(
            "Historical global production nonmutation must remain FAILED."
        )
    if historical.get("historicalFilesRewritten") is not False:
        raise ReconciliationValidationError("Overlay claims historical rewriting.")
    if historical.get("evidenceFileCount") != EXPECTED_FILE_COUNT:
        raise ReconciliationValidationError("Overlay evidence count mismatch.")
    for key in ("originalTreeSha256", "recomputedTreeSha256"):
        if historical.get(key) != EXPECTED_TREE_SHA256:
            raise ReconciliationValidationError("Overlay tree identity mismatch.")
    if (
        historical.get("originalManifestVerification")
        != "PASS_WITH_ONE_SELF_REFERENTIAL_TERMINAL_STDOUT_EXCEPTION"
        or historical.get("originalManifestMismatchCount") != 1
        or historical.get("originalManifestException") != {
            **EXPECTED_STDOUT_EXCEPTION,
            "semanticResultMatches": "closeout/CLOSEOUT-RESULT.json",
            "explanation": "The finisher hashed its stdout log before the terminal JSON was emitted to that same log. The known retained 51-file tree includes the terminal log and remains exact; all other 48 manifest entries match byte-for-byte.",
        }
    ):
        raise ReconciliationValidationError(
            "Original manifest exception is absent or changed."
        )

    source = _mapping(overlay, "sourceIdentity")
    if source.get("classification") != "SOURCE_IDENTITY_STRONGLY_CORROBORATED_POST_HOC":
        raise ReconciliationValidationError("Source limitation was upgraded or lost.")
    if source.get("reconstructedSourceManifestSha256") != EXPECTED_RECONSTRUCTED_SOURCE_MANIFEST_SHA256:
        raise ReconciliationValidationError("Reconstructed source manifest mismatch.")
    if source.get("sourceManifestStatus") != "RECOVERED_POST_HOC_FROM_FROZEN_GIT_NOT_START_TIME_PROOF":
        raise ReconciliationValidationError("Post-hoc source status mismatch.")

    checkpoints = _list_of_mappings(overlay, "checkpointMatrix")
    if len(checkpoints) != len(EXPECTED_CHECKPOINTS):
        raise ReconciliationValidationError("Overlay checkpoint count mismatch.")
    checkpoint_codes: set[str] = set()
    for checkpoint in checkpoints:
        if set(checkpoint) != CHECKPOINT_FIELDS:
            raise ReconciliationValidationError("Checkpoint fields are incomplete.")
        code = str(checkpoint["code"])
        if code in checkpoint_codes or code not in EXPECTED_CHECKPOINTS:
            raise ReconciliationValidationError("Checkpoint code is duplicate or unknown.")
        checkpoint_codes.add(code)
        expected_hash, expected_fingerprint = EXPECTED_CHECKPOINTS[code]
        if checkpoint["checkpointHash"] != expected_hash:
            raise ReconciliationValidationError(f"Overlay hash mismatch: {code}")
        if checkpoint["evidenceFingerprint"] != expected_fingerprint:
            raise ReconciliationValidationError(
                f"Overlay fingerprint mismatch: {code}"
            )
        if checkpoint["sourceSha"] != EXPECTED_CAMPAIGN_SOURCE:
            raise ReconciliationValidationError(f"Overlay source mismatch: {code}")
        if checkpoint["adjudication"] not in CLAIM_CLASSES:
            raise ReconciliationValidationError(
                f"Checkpoint adjudication is invalid: {code}"
            )
    if checkpoint_codes != set(EXPECTED_CHECKPOINTS):
        raise ReconciliationValidationError("Overlay checkpoint set is incomplete.")

    dependencies = _list_of_mappings(overlay, "dependencyMatrix")
    dependency_ids: set[str] = set()
    for dependency in dependencies:
        resource_id = str(dependency.get("resourceId", ""))
        if not resource_id or resource_id in dependency_ids:
            raise ReconciliationValidationError("Dependency ID is missing or duplicate.")
        dependency_ids.add(resource_id)
        if dependency.get("classification") not in DEPENDENCY_CLASSES:
            raise ReconciliationValidationError(
                f"Dependency classification is invalid: {resource_id}"
            )

    changes = _list_of_mappings(overlay, "authorizedProductionChanges")
    if not changes or [change.get("sequence") for change in changes] != list(
        range(1, len(changes) + 1)
    ):
        raise ReconciliationValidationError("Authorized timeline is not contiguous.")

    claims = _list_of_mappings(overlay, "claims")
    claim_ids: set[str] = set()
    observed_counts: Counter[str] = Counter()
    for claim in claims:
        if set(claim) != CLAIM_FIELDS:
            raise ReconciliationValidationError("Claim-table fields are incomplete.")
        claim_id = str(claim["claimId"])
        if not claim_id or claim_id in claim_ids:
            raise ReconciliationValidationError("Claim ID is missing or duplicate.")
        claim_ids.add(claim_id)
        classification = str(claim["finalClassification"])
        if classification not in CLAIM_CLASSES:
            raise ReconciliationValidationError(
                f"Claim classification is invalid: {claim_id}"
            )
        observed_counts[classification] += 1
        if claim["rerunRequired"] not in {"YES", "NO"}:
            raise ReconciliationValidationError(
                f"Claim rerun flag is invalid: {claim_id}"
            )
        if not isinstance(claim["checkpoints"], list) or not claim["checkpoints"]:
            raise ReconciliationValidationError(
                f"Claim checkpoint binding is empty: {claim_id}"
            )
        if not isinstance(claim["evidenceFiles"], list) or not claim["evidenceFiles"]:
            raise ReconciliationValidationError(
                f"Claim evidence binding is empty: {claim_id}"
            )

    declared_counts = _mapping(overlay, "claimCounts")
    for classification in CLAIM_CLASSES:
        if declared_counts.get(classification) != observed_counts[classification]:
            raise ReconciliationValidationError(
                f"Claim count mismatch: {classification}"
            )
    if declared_counts.get("total") != len(claims):
        raise ReconciliationValidationError("Total claim count mismatch.")

    answers = _mapping(overlay, "sevenAnswers")
    expected_answers = {
        "originalGlobalProductionNonmutationStillFailed": "YES",
        "historicalCheckpointsRewritten": "NO",
        "alpacaObservationsUsable": "YES",
        "finvizObservationsUsable": "YES",
        "schwabOvernightCapabilityProven": "NO",
        "usefulConclusionsRetainedWithoutFullRerun": "YES",
    }
    for key, expected in expected_answers.items():
        if answers.get(key) != expected:
            raise ReconciliationValidationError(f"Required answer mismatch: {key}")
    if not str(answers.get("smallestRemainingExperiment", "")).strip():
        raise ReconciliationValidationError("Smallest remaining experiment is absent.")

    protection = _mapping(overlay, "productionProtection")
    zero_fields = (
        "providerCalls",
        "accountCalls",
        "brokerCalls",
        "orders",
        "servicesRestarted",
        "manifestsChanged",
        "schedulerChanged",
        "historicalEvidenceFilesChanged",
    )
    if any(protection.get(key) != 0 for key in zero_fields):
        raise ReconciliationValidationError("Production protection claims mutation.")
    if (
        protection.get("serviceSnapshotMatchesBaseline") is not True
        or protection.get("serviceSnapshotSha256")
        != protection.get("finalServiceSnapshotSha256")
        or protection.get("schedulerSnapshotMatchesBaseline") is not True
        or protection.get("schedulerTaskCount")
        != protection.get("finalSchedulerTaskCount")
        or protection.get("schedulerDefinitionSnapshotSha256")
        != protection.get("finalSchedulerDefinitionSnapshotSha256")
        or protection.get("manifestSnapshotsMatchBaseline") is not True
        or protection.get("automationManifestSha256")
        != protection.get("finalAutomationManifestSha256")
        or protection.get("continuousConfigSha256")
        != protection.get("finalContinuousConfigSha256")
        or protection.get("continuousDeploymentManifestSha256")
        != protection.get("finalContinuousDeploymentManifestSha256")
        or protection.get("canonicalMainCleanAtFinalProtectionCheck") is not True
    ):
        raise ReconciliationValidationError(
            "Production protection before/after identity mismatch."
        )
    return {
        "checkpointCount": len(checkpoints),
        "claimCount": len(claims),
        "claimCounts": dict(observed_counts),
        "dependencyCount": len(dependencies),
        "authorizedChangeCount": len(changes),
    }


def verify(evidence_root: Path, overlay_path: Path) -> dict[str, object]:
    historical = verify_historical_evidence(evidence_root)
    overlay = _load_json(overlay_path)
    reconciliation = validate_overlay(overlay)
    return {
        "classification": "OVERNIGHT_EVIDENCE_RECONCILED",
        "historical": historical,
        "reconciliation": reconciliation,
        "historicalGlobalProductionNonmutation": "FAILED",
        "historicalFilesRewritten": False,
        "providerCalls": 0,
        "accountCalls": 0,
        "brokerCalls": 0,
        "orders": 0,
    }


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationValidationError(f"Cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReconciliationValidationError(f"JSON root must be an object: {path}")
    return value


def _mapping(value: Mapping[str, object], key: str) -> dict[str, object]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ReconciliationValidationError(f"{key} must be an object.")
    return result


def _list_of_mappings(
    value: Mapping[str, object], key: str
) -> list[dict[str, object]]:
    result = value.get(key)
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        raise ReconciliationValidationError(f"{key} must be an object list.")
    return result


def _reject_secrets(value: object, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in FORBIDDEN_FIELD_NAMES:
                raise ReconciliationValidationError(
                    f"Forbidden secret field at {path}.{key}."
                )
            _reject_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{path}[{index}]")
    elif isinstance(value, str):
        for pattern in SECRET_PATTERNS:
            if pattern.search(value):
                raise ReconciliationValidationError(
                    f"Credential-shaped value at {path}."
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the overnight evidence reconciliation overlay."
    )
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify(args.evidence_root, args.overlay)
    except ReconciliationValidationError as exc:
        print(
            json.dumps(
                {
                    "classification": "OVERNIGHT_EVIDENCE_RECONCILIATION_INCOMPLETE",
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
