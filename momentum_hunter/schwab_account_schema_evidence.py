from __future__ import annotations

"""Offline evidence inspection for Schwab account-response OpenAPI schemas."""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Final, Mapping, Sequence

from momentum_hunter.schwab_order_schema_evidence import (
    SCHWAB_TRADER_API_HOST,
    SchwabOrderSchemaEvidenceError,
    _decode_json,
    _extract_specification,
    _has_exact_schwab_trader_server,
    _resolve_object,
    _resolve_schema,
    _server_urls,
    _string_value,
)


SCHWAB_ACCOUNT_SCHEMA_EVIDENCE_VERSION: Final = (
    "SCHWAB_ACCOUNT_SCHEMA_EVIDENCE_V1"
)
MAX_OPENAPI_EXPORT_BYTES: Final = 4 * 1024 * 1024
MAX_SCHEMA_DEPTH: Final = 64
MAX_SCHEMA_FIELDS: Final = 10_000
_SUCCESS_RESPONSE_CODES: Final = ("200", "201", "202", "default")
_FIELD_PATHS: Final = {
    "settledCash": "securitiesAccount.currentBalances.settledCash",
    "unsettledCash": "securitiesAccount.currentBalances.unsettledCash",
    "cashAvailableForTrading": (
        "securitiesAccount.currentBalances.cashAvailableForTrading"
    ),
    "cashAvailableForWithdrawal": (
        "securitiesAccount.currentBalances.cashAvailableForWithdrawal"
    ),
    "closingOnlyRestricted": "securitiesAccount.isClosingOnlyRestricted",
    "accountInCall": "securitiesAccount.initialBalances.isInCall",
    "pfcbFlag": "securitiesAccount.pfcbFlag",
}


class SchwabAccountSchemaEvidenceError(ValueError):
    pass


class _RedactedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


@dataclass(frozen=True)
class AccountSchemaFieldEvidence:
    logical_field: str
    source_path: str
    availability: str
    declared_type: str
    description_present: bool
    description_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "logicalField": self.logical_field,
            "sourcePath": self.source_path,
            "availability": self.availability,
            "declaredType": self.declared_type,
            "descriptionPresent": self.description_present,
            "descriptionSha256": self.description_sha256,
            "descriptionRetained": False,
        }


@dataclass(frozen=True)
class _SchemaField:
    path: str
    declared_type: str
    description_sha256: str


@dataclass(frozen=True)
class SchwabAccountSchemaEvidence:
    specification_sha256: str
    openapi_version: str
    document_title: str
    server_urls: tuple[str, ...]
    account_path: str | None
    account_parameter: str | None
    account_operation_id: str | None
    response_field_paths: tuple[str, ...]
    field_evidence: tuple[AccountSchemaFieldEvidence, ...]
    sensitive_envelope_fields: tuple[str, ...]
    findings: tuple[str, ...]
    mapping_limitations: tuple[str, ...]
    ready_for_semantic_review: bool
    settled_cash_mapping: str
    restriction_mapping: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHWAB_ACCOUNT_SCHEMA_EVIDENCE_VERSION,
            "evidenceType": "OFFLINE_OPENAPI_ACCOUNT_SCHEMA_INSPECTION",
            "specificationSha256": self.specification_sha256,
            "rawSourceHashRetained": False,
            "openapiVersion": self.openapi_version,
            "documentTitle": self.document_title,
            "serverUrls": list(self.server_urls),
            "accountPath": self.account_path,
            "accountParameter": self.account_parameter,
            "accountOperationId": self.account_operation_id,
            "responseFieldPaths": list(self.response_field_paths),
            "fieldEvidence": [item.to_dict() for item in self.field_evidence],
            "sensitiveEnvelopeFields": list(self.sensitive_envelope_fields),
            "findings": list(self.findings),
            "mappingLimitations": list(self.mapping_limitations),
            "readyForSemanticReview": self.ready_for_semantic_review,
            "settledCashMapping": self.settled_cash_mapping,
            "restrictionMapping": self.restriction_mapping,
            "fundingGateReady": False,
            "automaticSemanticAcceptance": False,
            "manualSemanticReviewRequired": True,
            "inspectionOnly": True,
            "networkAccessed": False,
            "credentialsAccessed": False,
            "providerEvidence": False,
            "executionPermit": False,
            "brokerActionAllowed": False,
            "retryAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


def inspect_schwab_account_openapi(
    raw_document: bytes,
) -> SchwabAccountSchemaEvidence:
    if not isinstance(raw_document, bytes) or not raw_document:
        raise SchwabAccountSchemaEvidenceError(
            "OpenAPI account evidence must be non-empty bytes."
        )
    if len(raw_document) > MAX_OPENAPI_EXPORT_BYTES:
        raise SchwabAccountSchemaEvidenceError(
            "OpenAPI account evidence exceeded the size limit."
        )
    try:
        document = _decode_json(raw_document)
        specification, sensitive_fields = _extract_specification(document)
    except SchwabOrderSchemaEvidenceError as exc:
        raise SchwabAccountSchemaEvidenceError(str(exc)) from exc
    try:
        specification_bytes = json.dumps(
            specification,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise SchwabAccountSchemaEvidenceError(
            "OpenAPI account evidence contains unsupported JSON values."
        ) from exc
    specification_sha256 = hashlib.sha256(specification_bytes).hexdigest()
    findings: list[str] = []
    limitations: list[str] = []

    openapi_version = _string_value(specification.get("openapi"))
    if not openapi_version.startswith("3."):
        findings.append("The document is not an OpenAPI 3.x specification.")
    info = specification.get("info")
    document_title = (
        _string_value(info.get("title")) if isinstance(info, Mapping) else ""
    )
    server_urls, unsafe_server_url = _server_urls(
        specification.get("servers")
    )
    if (
        unsafe_server_url
        or not _has_exact_schwab_trader_server(server_urls)
    ):
        findings.append(
            "The specification does not declare Schwab's exact HTTPS API host."
        )

    account = _find_account_operation(specification)
    if account is None:
        findings.append(
            "One unambiguous GET account-detail operation was not found."
        )
    try:
        fields = _operation_response_fields(
            specification,
            account[1] if account else None,
        )
    except SchwabOrderSchemaEvidenceError as exc:
        raise SchwabAccountSchemaEvidenceError(str(exc)) from exc
    if account and not fields:
        findings.append(
            "The GET account-detail response schema could not be resolved."
        )
    field_evidence = tuple(
        _field_evidence(logical_field, source_path, fields)
        for logical_field, source_path in _FIELD_PATHS.items()
    )
    settled_cash = next(
        item for item in field_evidence if item.logical_field == "settledCash"
    )
    restriction_candidates = tuple(
        item
        for item in field_evidence
        if item.logical_field
        in {"closingOnlyRestricted", "accountInCall", "pfcbFlag"}
        and item.availability == "DIRECT"
    )
    if settled_cash.availability != "DIRECT":
        limitations.append(
            "No explicit settled-cash field is declared at the reviewed path."
        )
        settled_cash_mapping = "UNAVAILABLE"
    elif not settled_cash.description_present:
        limitations.append(
            "The explicit settled-cash field lacks an official description."
        )
        settled_cash_mapping = "EXPLICIT_FIELD_DESCRIPTION_UNAVAILABLE"
    else:
        limitations.append(
            "The explicit settled-cash field still requires manual semantic review."
        )
        settled_cash_mapping = "EXPLICIT_FIELD_REQUIRES_MANUAL_REVIEW"
    if not restriction_candidates:
        limitations.append(
            "No reviewed account-restriction candidate fields are declared."
        )
        restriction_mapping = "UNAVAILABLE"
    else:
        missing_descriptions = tuple(
            item.logical_field
            for item in restriction_candidates
            if not item.description_present
        )
        if missing_descriptions:
            limitations.append(
                "Restriction candidate fields lack official descriptions: "
                + ", ".join(missing_descriptions)
                + "."
            )
            restriction_mapping = "CANDIDATE_FIELDS_DESCRIPTION_UNAVAILABLE"
        else:
            limitations.append(
                "Restriction candidate fields require manual completeness and "
                "semantic review."
            )
            restriction_mapping = "CANDIDATE_FIELDS_REQUIRE_MANUAL_REVIEW"
    if sensitive_fields:
        findings.append(
            "The portal export envelope contains credential-shaped fields; "
            "only the nested specification may be retained."
        )
    ready = not findings and bool(fields)
    return SchwabAccountSchemaEvidence(
        specification_sha256=specification_sha256,
        openapi_version=openapi_version,
        document_title=document_title,
        server_urls=server_urls,
        account_path=account[0] if account else None,
        account_parameter=account[2] if account else None,
        account_operation_id=(
            _string_value(account[1].get("operationId"))
            if account
            else None
        ),
        response_field_paths=tuple(sorted(fields)),
        field_evidence=field_evidence,
        sensitive_envelope_fields=sensitive_fields,
        findings=tuple(findings),
        mapping_limitations=tuple(limitations),
        ready_for_semantic_review=ready,
        settled_cash_mapping=settled_cash_mapping,
        restriction_mapping=restriction_mapping,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _RedactedArgumentParser(
        description=(
            "Inspect a local Schwab account OpenAPI export without network, "
            "credentials, or broker access."
        )
    )
    parser.add_argument(
        "specification",
        help="Path to a local JSON OpenAPI document or portal export.",
    )
    args = parser.parse_args(argv)
    try:
        raw_document = _read_local_export(Path(args.specification))
        evidence = inspect_schwab_account_openapi(raw_document)
    except (OSError, SchwabAccountSchemaEvidenceError):
        reason = "OpenAPI account evidence could not be inspected safely."
    else:
        print(json.dumps(evidence.to_dict(), indent=2, sort_keys=True))
        return 0
    print(
        json.dumps(
            {
                "schemaVersion": SCHWAB_ACCOUNT_SCHEMA_EVIDENCE_VERSION,
                "status": "BLOCKED",
                "reason": reason,
                "inspectionOnly": True,
                "networkAccessed": False,
                "credentialsAccessed": False,
                "providerEvidence": False,
                "executionPermit": False,
                "brokerActionAllowed": False,
                "transmitting": False,
                "orderTransmission": "UNAVAILABLE",
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _read_local_export(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SchwabAccountSchemaEvidenceError(
            "OpenAPI account evidence must be one regular local file."
        )
    size = path.stat().st_size
    if size <= 0 or size > MAX_OPENAPI_EXPORT_BYTES:
        raise SchwabAccountSchemaEvidenceError(
            "OpenAPI account evidence size is outside the allowed range."
        )
    return path.read_bytes()


def _find_account_operation(
    specification: Mapping[str, object],
) -> tuple[str, Mapping[str, object], str] | None:
    paths = specification.get("paths")
    if not isinstance(paths, Mapping):
        return None
    matches: list[tuple[str, Mapping[str, object], str]] = []
    for raw_path, raw_path_item in paths.items():
        if not isinstance(raw_path, str) or not isinstance(raw_path_item, Mapping):
            continue
        segments = tuple(
            segment for segment in raw_path.strip("/").split("/") if segment
        )
        if "accounts" not in segments:
            continue
        account_index = segments.index("accounts")
        if len(segments) != account_index + 2:
            continue
        parameter = segments[-1]
        if not (parameter.startswith("{") and parameter.endswith("}")):
            continue
        operation = raw_path_item.get("get")
        if isinstance(operation, Mapping):
            matches.append((raw_path, operation, parameter[1:-1]))
    if len(matches) != 1:
        return None
    return matches[0]


def _operation_response_fields(
    specification: Mapping[str, object],
    operation: Mapping[str, object] | None,
) -> dict[str, _SchemaField]:
    if operation is None:
        return {}
    responses = operation.get("responses")
    if not isinstance(responses, Mapping):
        return {}
    response: Mapping[str, object] | None = None
    for code in _SUCCESS_RESPONSE_CODES:
        candidate = responses.get(code)
        if isinstance(candidate, Mapping):
            response = candidate
            break
    if response is None:
        return {}
    response = _resolve_object(specification, response)
    content = response.get("content")
    if not isinstance(content, Mapping):
        return {}
    media = content.get("application/json")
    if not isinstance(media, Mapping):
        return {}
    schema = media.get("schema")
    if not isinstance(schema, Mapping):
        return {}
    fields = _collect_schema_fields(specification, schema)
    if len(fields) > MAX_SCHEMA_FIELDS:
        raise SchwabAccountSchemaEvidenceError(
            "OpenAPI account response schema exceeded the field limit."
        )
    return fields


def _collect_schema_fields(
    specification: Mapping[str, object],
    schema: Mapping[str, object],
    *,
    prefix: str = "",
    seen: frozenset[str] = frozenset(),
    depth: int = 0,
) -> dict[str, _SchemaField]:
    if depth > MAX_SCHEMA_DEPTH:
        raise SchwabAccountSchemaEvidenceError(
            "OpenAPI account response schema exceeded the depth limit."
        )
    reference = schema.get("$ref")
    if isinstance(reference, str):
        if reference in seen:
            raise SchwabAccountSchemaEvidenceError(
                "OpenAPI schema contains a reference cycle."
            )
        resolved = _resolve_schema(
            specification,
            schema,
            seen=seen,
        )
        return _collect_schema_fields(
            specification,
            resolved,
            prefix=prefix,
            seen=seen | {reference},
            depth=depth + 1,
        )
    resolved = _resolve_schema(specification, schema, seen=seen)
    properties = resolved.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    fields: dict[str, _SchemaField] = {}
    for raw_name, raw_child in properties.items():
        if not isinstance(raw_name, str) or not isinstance(raw_child, Mapping):
            continue
        path = f"{prefix}.{raw_name}" if prefix else raw_name
        child_reference = raw_child.get("$ref")
        child = _resolve_schema(specification, raw_child, seen=seen)
        child_seen = (
            seen | {child_reference}
            if isinstance(child_reference, str)
            else seen
        )
        declared_type = _string_value(child.get("type"))
        if not declared_type and isinstance(child.get("properties"), Mapping):
            declared_type = "object"
        description = _string_value(child.get("description"))
        description_sha256 = (
            hashlib.sha256(description.encode("utf-8")).hexdigest()
            if description
            else ""
        )
        fields[path] = _SchemaField(
            path=path,
            declared_type=declared_type or "UNAVAILABLE",
            description_sha256=description_sha256,
        )
        if declared_type == "array":
            items = child.get("items")
            if isinstance(items, Mapping):
                fields.update(
                    _collect_schema_fields(
                        specification,
                        items,
                        prefix=f"{path}[]",
                        seen=child_seen,
                        depth=depth + 1,
                    )
                )
        else:
            fields.update(
                _collect_schema_fields(
                    specification,
                    child,
                    prefix=path,
                    seen=child_seen,
                    depth=depth + 1,
                )
            )
    return fields


def _field_evidence(
    logical_field: str,
    source_path: str,
    fields: Mapping[str, _SchemaField],
) -> AccountSchemaFieldEvidence:
    field = fields.get(source_path)
    return AccountSchemaFieldEvidence(
        logical_field=logical_field,
        source_path=source_path,
        availability="DIRECT" if field else "UNAVAILABLE",
        declared_type=field.declared_type if field else "UNAVAILABLE",
        description_present=bool(field and field.description_sha256),
        description_sha256=field.description_sha256 if field else "",
    )


if __name__ == "__main__":
    raise SystemExit(main())
