from __future__ import annotations

"""Finalize and verify long-running campaign provenance evidence.

This tool is deliberately standalone. Momentum Hunter runtime code does not
import it, and it has no provider, credential, service, scheduler, or broker
capability.
"""

import argparse
import copy
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence


SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CAMPAIGN_ACCESS = {"NONE", "READ_ONLY", "READ_WRITE"}
REVALIDATION_PASS = "AUTHORIZED_EXTERNAL_CHANGE_ISOLATION_REVALIDATED"
REVALIDATION_FAIL = "CAMPAIGN_ISOLATION_BROKEN"
REVALIDATION_CHECKS = (
    "campaignSourceUnchanged",
    "campaignExecutableUnchanged",
    "campaignConfigurationUnchanged",
    "campaignProcessIdentityValid",
    "campaignEvidenceRootValid",
    "campaignLockStateValid",
    "providerContractUnchanged",
    "sharedPathsRevalidated",
    "checkpointsUnrewritten",
)
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


class ProvenanceValidationError(ValueError):
    pass


def canonical_fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def finalize_document(value: Mapping[str, object]) -> dict[str, object]:
    document = copy.deepcopy(dict(value))
    _reject_forbidden_fields(document)
    document.pop("documentFingerprint", None)
    baseline = _mapping(document, "productionBaseline")
    baseline.pop("baselineFingerprint", None)
    baseline["baselineFingerprint"] = canonical_fingerprint(baseline)

    predecessor = str(baseline["baselineFingerprint"])
    for change in _list_of_mappings(document, "authorizedExternalChanges"):
        change.pop("recordFingerprint", None)
        change["predecessorFingerprint"] = predecessor
        change["recordFingerprint"] = canonical_fingerprint(change)
        predecessor = str(change["recordFingerprint"])

    document["integrityResult"] = _derived_integrity(document)
    document["documentFingerprint"] = canonical_fingerprint(document)
    validate_document(document)
    return document


def validate_document(value: Mapping[str, object]) -> dict[str, object]:
    document = dict(value)
    _reject_forbidden_fields(document)
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise ProvenanceValidationError("Unsupported campaign provenance schema version.")

    campaign = _mapping(document, "campaignFrozenIdentity")
    _nonempty(campaign, "taskId")
    _git_sha(campaign, "sourceGitHead")
    for key in (
        "sourceFileManifestSha256",
        "configurationFingerprint",
        "executableSha256",
        "evidenceRootFingerprint",
        "providerRouteAllowlistSha256",
    ):
        _sha256(campaign, key)
    _aware_timestamp(campaign, "startedAt")
    process = _mapping(campaign, "processIdentity")
    if not isinstance(process.get("processId"), int) or int(process["processId"]) <= 0:
        raise ProvenanceValidationError("Campaign processId must be a positive integer.")
    _sha256(process, "executableSha256")
    _aware_timestamp(process, "startedAt")

    baseline = _mapping(document, "productionBaseline")
    _git_sha(baseline, "canonicalGitHead")
    _git_sha(baseline, "installedProductGitHead")
    _sha256(baseline, "manifestSha256")
    _aware_timestamp(baseline, "observedAt")
    expected_baseline = canonical_fingerprint(_without(baseline, "baselineFingerprint"))
    if baseline.get("baselineFingerprint") != expected_baseline:
        raise ProvenanceValidationError("Production baseline fingerprint mismatch.")
    services = _list_of_mappings(baseline, "services")
    if not services:
        raise ProvenanceValidationError("At least one production service identity is required.")
    service_names: set[str] = set()
    for service in services:
        name = _nonempty(service, "name")
        if name in service_names:
            raise ProvenanceValidationError("Production service names must be unique.")
        service_names.add(name)
        for key in ("executableSha256", "configSha256", "deploymentManifestSha256"):
            _sha256(service, key)

    resources = _list_of_mappings(document, "sharedResources")
    resource_ids: set[str] = set()
    for resource in resources:
        resource_id = _nonempty(resource, "resourceId")
        if resource_id in resource_ids:
            raise ProvenanceValidationError("Shared resource IDs must be unique.")
        resource_ids.add(resource_id)
        _nonempty(resource, "resourceType")
        _nonempty(resource, "owner")
        _nonempty(resource, "mutationRules")
        _sha256(resource, "baselineFingerprint")
        if not isinstance(resource.get("mutable"), bool):
            raise ProvenanceValidationError("Shared resource mutable must be boolean.")
        if resource.get("campaignAccess") not in CAMPAIGN_ACCESS:
            raise ProvenanceValidationError("Shared resource campaignAccess is invalid.")
        writers = resource.get("allowedWriters")
        if not isinstance(writers, list) or any(not isinstance(item, str) or not item for item in writers):
            raise ProvenanceValidationError("Shared resource allowedWriters must be a string list.")
        if resource["mutable"] and not writers:
            raise ProvenanceValidationError("A mutable shared resource requires an allowed writer.")

    changes = _list_of_mappings(document, "authorizedExternalChanges")
    expected_canonical = str(baseline["canonicalGitHead"])
    expected_installed = str(baseline["installedProductGitHead"])
    predecessor = str(baseline["baselineFingerprint"])
    for index, change in enumerate(changes, start=1):
        if change.get("sequence") != index:
            raise ProvenanceValidationError("Authorized change sequence must be contiguous.")
        _aware_timestamp(change, "observedAt")
        _nonempty(change, "taskId")
        _nonempty(change, "authorization")
        canonical = _mapping(change, "canonicalGit")
        installed = _mapping(change, "installedProduct")
        manifests = _mapping(change, "deploymentManifest")
        for target in (canonical, installed):
            _git_sha(target, "oldGitHead")
            _git_sha(target, "newGitHead")
        _sha256(manifests, "oldSha256")
        _sha256(manifests, "newSha256")
        if canonical["oldGitHead"] != expected_canonical:
            raise ProvenanceValidationError("Canonical Git transition chain is broken.")
        if installed["oldGitHead"] != expected_installed:
            raise ProvenanceValidationError("Installed product transition chain is broken.")
        expected_canonical = str(canonical["newGitHead"])
        expected_installed = str(installed["newGitHead"])
        affected = change.get("affectedServices")
        if (
            not isinstance(affected, list)
            or any(not isinstance(item, str) or not item.strip() for item in affected)
            or len(set(affected)) != len(affected)
        ):
            raise ProvenanceValidationError("Authorized change affectedServices must contain unique names.")
        touched = change.get("sharedResourcesTouched")
        if not isinstance(touched, list) or any(item not in resource_ids for item in touched):
            raise ProvenanceValidationError("Authorized change references an undeclared shared resource.")
        revalidation = _mapping(change, "isolationRevalidation")
        if revalidation.get("classification") not in {REVALIDATION_PASS, REVALIDATION_FAIL}:
            raise ProvenanceValidationError("Isolation revalidation classification is invalid.")
        checks = _mapping(revalidation, "checks")
        if set(checks) != set(REVALIDATION_CHECKS):
            raise ProvenanceValidationError("Isolation revalidation checks are incomplete.")
        if any(not isinstance(checks[key], bool) for key in REVALIDATION_CHECKS):
            raise ProvenanceValidationError("Isolation revalidation checks must be boolean.")
        should_pass = all(checks[key] for key in REVALIDATION_CHECKS)
        expected_classification = REVALIDATION_PASS if should_pass else REVALIDATION_FAIL
        if revalidation["classification"] != expected_classification:
            raise ProvenanceValidationError("Isolation revalidation result contradicts its checks.")
        _sha256(revalidation, "evidenceSha256")
        if change.get("predecessorFingerprint") != predecessor:
            raise ProvenanceValidationError("Authorized change predecessor chain is broken.")
        expected_record = canonical_fingerprint(_without(change, "recordFingerprint"))
        if change.get("recordFingerprint") != expected_record:
            raise ProvenanceValidationError("Authorized change fingerprint mismatch.")
        predecessor = expected_record

    expected_integrity = _derived_integrity(document)
    if document.get("integrityResult") != expected_integrity:
        raise ProvenanceValidationError("Campaign integrity result contradicts source evidence.")
    expected_document = canonical_fingerprint(_without(document, "documentFingerprint"))
    if document.get("documentFingerprint") != expected_document:
        raise ProvenanceValidationError("Campaign provenance document fingerprint mismatch.")
    return expected_integrity


def write_document_once(path: Path, value: Mapping[str, object]) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _derived_integrity(document: Mapping[str, object]) -> dict[str, object]:
    observed = _mapping(document, "campaignIntegrityObservations")
    required = {
        "campaignSourceUnchanged",
        "campaignExecutableUnchanged",
        "campaignConfigurationUnchanged",
        "campaignEvidenceValid",
        "campaignProcessIdentityValid",
        "externalProductionTouchedCampaignPaths",
        "undeclaredSharedMutableResource",
    }
    if set(observed) != required or any(not isinstance(observed[key], bool) for key in required):
        raise ProvenanceValidationError("Campaign integrity observations are incomplete.")
    changes = _list_of_mappings(document, "authorizedExternalChanges")
    changes_revalidated = all(
        _mapping(change, "isolationRevalidation").get("classification") == REVALIDATION_PASS
        for change in changes
    )
    campaign_pass = (
        observed["campaignSourceUnchanged"]
        and observed["campaignExecutableUnchanged"]
        and observed["campaignConfigurationUnchanged"]
        and observed["campaignEvidenceValid"]
        and observed["campaignProcessIdentityValid"]
        and not observed["externalProductionTouchedCampaignPaths"]
        and not observed["undeclaredSharedMutableResource"]
        and changes_revalidated
    )
    return {
        "campaignNonmutation": "PASS" if campaign_pass else "FAIL",
        "globalProductionNonmutation": not bool(changes),
        "authorizedExternalChangesPresent": bool(changes),
        "authorizedExternalChangesRevalidated": changes_revalidated,
        "classification": "CAMPAIGN_INTEGRITY_PASSED" if campaign_pass else "CAMPAIGN_ISOLATION_BROKEN",
    }


def _mapping(value: Mapping[str, object], key: str) -> dict[str, object]:
    selected = value.get(key)
    if not isinstance(selected, Mapping):
        raise ProvenanceValidationError(f"{key} must be an object.")
    return selected if isinstance(selected, dict) else dict(selected)


def _list_of_mappings(value: Mapping[str, object], key: str) -> list[dict[str, object]]:
    selected = value.get(key)
    if not isinstance(selected, list) or any(not isinstance(item, Mapping) for item in selected):
        raise ProvenanceValidationError(f"{key} must be an object list.")
    return selected  # type: ignore[return-value]


def _without(value: Mapping[str, object], key: str) -> dict[str, object]:
    selected = dict(value)
    selected.pop(key, None)
    return selected


def _nonempty(value: Mapping[str, object], key: str) -> str:
    selected = value.get(key)
    if not isinstance(selected, str) or not selected.strip():
        raise ProvenanceValidationError(f"{key} must be a nonempty string.")
    return selected


def _sha256(value: Mapping[str, object], key: str) -> str:
    selected = _nonempty(value, key)
    if not SHA256_RE.fullmatch(selected):
        raise ProvenanceValidationError(f"{key} must be a full SHA-256 value.")
    return selected.upper()


def _git_sha(value: Mapping[str, object], key: str) -> str:
    selected = _nonempty(value, key)
    if not GIT_SHA_RE.fullmatch(selected):
        raise ProvenanceValidationError(f"{key} must be a lowercase full Git SHA.")
    return selected


def _aware_timestamp(value: Mapping[str, object], key: str) -> datetime:
    selected = _nonempty(value, key)
    try:
        parsed = datetime.fromisoformat(selected.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvenanceValidationError(f"{key} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProvenanceValidationError(f"{key} must include an offset.")
    return parsed


def _reject_forbidden_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, selected in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalized in FORBIDDEN_FIELD_NAMES:
                raise ProvenanceValidationError("Campaign provenance contains a forbidden secret-shaped field.")
            _reject_forbidden_fields(selected)
    elif isinstance(value, list):
        for selected in value:
            _reject_forbidden_fields(selected)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finalize or verify campaign provenance evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("path", type=Path)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("draft", type=Path)
    finalize.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            document = json.loads(args.path.read_text(encoding="utf-8"))
            integrity = validate_document(document)
        else:
            draft = json.loads(args.draft.read_text(encoding="utf-8"))
            document = finalize_document(draft)
            write_document_once(args.output, document)
            integrity = dict(document["integrityResult"])
        print(json.dumps({
            "classification": "CAMPAIGN_PROVENANCE_VALID",
            "campaignNonmutation": integrity["campaignNonmutation"],
            "globalProductionNonmutation": integrity["globalProductionNonmutation"],
            "authorizedExternalChangesPresent": integrity["authorizedExternalChangesPresent"],
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "classification": "CAMPAIGN_PROVENANCE_INVALID",
            "errorType": type(exc).__name__,
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
