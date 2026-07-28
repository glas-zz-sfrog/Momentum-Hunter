from __future__ import annotations

"""Offline evidence inspection for Schwab order-response OpenAPI schemas."""

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Final, Mapping, Sequence
from urllib.parse import urlparse


SCHWAB_ORDER_SCHEMA_EVIDENCE_VERSION: Final = (
    "SCHWAB_ORDER_SCHEMA_EVIDENCE_V1"
)
SCHWAB_TRADER_API_HOST: Final = "api.schwabapi.com"
_SENSITIVE_KEY_MARKERS: Final = (
    "apikey",
    "appkey",
    "bearer",
    "credential",
    "oauth",
    "password",
    "secret",
    "token",
)
_SUCCESS_RESPONSE_CODES: Final = ("200", "201", "202", "default")
_REQUIRED_DIRECT_FIELDS: Final = (
    "providerOrderId",
    "clientCommandId",
    "status",
    "enteredAt",
    "updatedAt",
    "requestedQuantity",
    "filledQuantity",
    "remainingQuantity",
    "symbol",
    "side",
    "orderType",
)
_FIELD_PATHS: Final = {
    "providerOrderId": "orderId",
    "clientCommandId": "clientCommandId",
    "status": "status",
    "enteredAt": "enteredTime",
    "updatedAt": "updatedAt",
    "requestedQuantity": "quantity",
    "filledQuantity": "filledQuantity",
    "remainingQuantity": "remainingQuantity",
    "averageFillPrice": "averageFillPrice",
    "symbol": "orderLegCollection[].instrument.symbol",
    "side": "orderLegCollection[].instruction",
    "orderType": "orderType",
    "limitPrice": "price",
}


class SchwabOrderSchemaEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class OrderSchemaFieldEvidence:
    logical_field: str
    source_path: str
    availability: str

    def to_dict(self) -> dict[str, str]:
        return {
            "logicalField": self.logical_field,
            "sourcePath": self.source_path,
            "availability": self.availability,
        }


@dataclass(frozen=True)
class SchwabOrderSchemaEvidence:
    source_sha256: str
    openapi_version: str
    document_title: str
    server_urls: tuple[str, ...]
    collection_path: str | None
    detail_path: str | None
    collection_operation_id: str | None
    detail_operation_id: str | None
    response_field_paths: tuple[str, ...]
    field_evidence: tuple[OrderSchemaFieldEvidence, ...]
    sensitive_envelope_fields: tuple[str, ...]
    findings: tuple[str, ...]
    ready_for_canary_reconciliation: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHWAB_ORDER_SCHEMA_EVIDENCE_VERSION,
            "evidenceType": "OFFLINE_OPENAPI_ORDER_SCHEMA_INSPECTION",
            "sourceSha256": self.source_sha256,
            "openapiVersion": self.openapi_version,
            "documentTitle": self.document_title,
            "serverUrls": list(self.server_urls),
            "collectionPath": self.collection_path,
            "detailPath": self.detail_path,
            "collectionOperationId": self.collection_operation_id,
            "detailOperationId": self.detail_operation_id,
            "responseFieldPaths": list(self.response_field_paths),
            "fieldEvidence": [item.to_dict() for item in self.field_evidence],
            "sensitiveEnvelopeFields": list(
                self.sensitive_envelope_fields
            ),
            "findings": list(self.findings),
            "readyForCanaryReconciliation": (
                self.ready_for_canary_reconciliation
            ),
            "inspectionOnly": True,
            "networkAccessed": False,
            "credentialsAccessed": False,
            "providerEvidence": False,
            "executionPermit": False,
            "brokerActionAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


def inspect_schwab_order_openapi(
    raw_document: bytes,
) -> SchwabOrderSchemaEvidence:
    if not isinstance(raw_document, bytes) or not raw_document:
        raise SchwabOrderSchemaEvidenceError(
            "OpenAPI evidence must be non-empty bytes."
        )
    source_sha256 = hashlib.sha256(raw_document).hexdigest()
    document = _decode_json(raw_document)
    specification, sensitive_fields = _extract_specification(document)
    findings: list[str] = []

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

    collection = _find_order_operation(specification, detail=False)
    detail = _find_order_operation(specification, detail=True)
    if collection is None:
        findings.append("A GET order-collection operation was not found.")
    if detail is None:
        findings.append("A GET order-detail operation was not found.")

    collection_fields = _operation_response_fields(
        specification,
        collection[1] if collection else None,
        collection=True,
    )
    detail_fields = _operation_response_fields(
        specification,
        detail[1] if detail else None,
        collection=False,
    )
    if collection and not collection_fields:
        findings.append(
            "The GET order-collection response schema could not be resolved."
        )
    if detail and not detail_fields:
        findings.append(
            "The GET order-detail response schema could not be resolved."
        )
    if collection_fields and detail_fields and collection_fields != detail_fields:
        findings.append(
            "Order collection and detail response fields are inconsistent."
        )
    response_fields = tuple(
        sorted(collection_fields | detail_fields)
    )
    field_evidence = tuple(
        OrderSchemaFieldEvidence(
            logical_field=logical_field,
            source_path=source_path,
            availability=(
                "DIRECT"
                if source_path in response_fields
                else "UNAVAILABLE"
            ),
        )
        for logical_field, source_path in _FIELD_PATHS.items()
    )
    unavailable_required = tuple(
        item.logical_field
        for item in field_evidence
        if item.logical_field in _REQUIRED_DIRECT_FIELDS
        and item.availability != "DIRECT"
    )
    if unavailable_required:
        findings.append(
            "Required reconciliation fields are unavailable: "
            + ", ".join(unavailable_required)
            + "."
        )
    if sensitive_fields:
        findings.append(
            "The portal export envelope contains credential-shaped fields; "
            "only the nested specification may be retained."
        )

    ready = not findings and not unavailable_required
    return SchwabOrderSchemaEvidence(
        source_sha256=source_sha256,
        openapi_version=openapi_version,
        document_title=document_title,
        server_urls=server_urls,
        collection_path=collection[0] if collection else None,
        detail_path=detail[0] if detail else None,
        collection_operation_id=(
            _string_value(collection[1].get("operationId"))
            if collection
            else None
        ),
        detail_operation_id=(
            _string_value(detail[1].get("operationId"))
            if detail
            else None
        ),
        response_field_paths=response_fields,
        field_evidence=field_evidence,
        sensitive_envelope_fields=sensitive_fields,
        findings=tuple(findings),
        ready_for_canary_reconciliation=ready,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect a local Schwab OpenAPI export without network or broker "
            "access."
        )
    )
    parser.add_argument(
        "specification",
        help="Path to a local JSON OpenAPI document or portal export.",
    )
    args = parser.parse_args(argv)
    try:
        raw_document = Path(args.specification).read_bytes()
        evidence = inspect_schwab_order_openapi(raw_document)
    except OSError:
        reason = "OpenAPI evidence could not be read."
    except SchwabOrderSchemaEvidenceError as exc:
        reason = str(exc)
    else:
        print(json.dumps(evidence.to_dict(), indent=2, sort_keys=True))
        return 0
    print(
        json.dumps(
            {
                "schemaVersion": SCHWAB_ORDER_SCHEMA_EVIDENCE_VERSION,
                "status": "BLOCKED",
                "reason": reason,
                "inspectionOnly": True,
                "networkAccessed": False,
                "credentialsAccessed": False,
                "brokerActionAllowed": False,
                "transmitting": False,
                "orderTransmission": "UNAVAILABLE",
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


def _decode_json(raw_document: bytes) -> Mapping[str, object]:
    try:
        decoded = json.loads(raw_document.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabOrderSchemaEvidenceError(
            "OpenAPI evidence is not valid UTF-8 JSON."
        ) from exc
    if not isinstance(decoded, Mapping):
        raise SchwabOrderSchemaEvidenceError(
            "OpenAPI evidence must contain a JSON object."
        )
    return decoded


def _extract_specification(
    document: Mapping[str, object],
) -> tuple[Mapping[str, object], tuple[str, ...]]:
    if "openapi" in document:
        return document, ()
    specification = document.get("specification")
    if isinstance(specification, str):
        nested = _decode_json(specification.encode("utf-8"))
    elif isinstance(specification, Mapping):
        nested = specification
    else:
        raise SchwabOrderSchemaEvidenceError(
            "Portal evidence does not contain an OpenAPI specification."
        )
    sensitive_fields = tuple(
        sorted(
            str(key)
            for key in document
            if key != "specification" and _is_sensitive_key(str(key))
        )
    )
    return nested, sensitive_fields


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _server_urls(value: object) -> tuple[tuple[str, ...], bool]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return (), False
    urls: list[str] = []
    unsafe = False
    for item in value:
        if isinstance(item, Mapping):
            url = _string_value(item.get("url"))
            if url:
                sanitized, item_unsafe = _sanitize_server_url(url)
                if sanitized:
                    urls.append(sanitized)
                unsafe = unsafe or item_unsafe
    return tuple(urls), unsafe


def _sanitize_server_url(url: str) -> tuple[str, bool]:
    parsed = urlparse(url)
    unsafe = bool(
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    )
    hostname = parsed.hostname or ""
    if not parsed.scheme or not hostname:
        return "", unsafe
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        return "", True
    sanitized = f"{parsed.scheme}://{hostname}{port}{parsed.path}"
    return sanitized, unsafe


def _has_exact_schwab_trader_server(urls: Sequence[str]) -> bool:
    for url in urls:
        parsed = urlparse(url)
        if (
            parsed.scheme == "https"
            and parsed.hostname == SCHWAB_TRADER_API_HOST
        ):
            return True
    return False


def _find_order_operation(
    specification: Mapping[str, object],
    *,
    detail: bool,
) -> tuple[str, Mapping[str, object]] | None:
    paths = specification.get("paths")
    if not isinstance(paths, Mapping):
        return None
    matches: list[tuple[str, Mapping[str, object]]] = []
    for raw_path, raw_path_item in paths.items():
        if not isinstance(raw_path, str) or not isinstance(raw_path_item, Mapping):
            continue
        segments = tuple(
            segment for segment in raw_path.strip("/").split("/") if segment
        )
        if "orders" not in segments:
            continue
        order_index = segments.index("orders")
        is_detail = (
            len(segments) == order_index + 2
            and segments[-1].startswith("{")
            and segments[-1].endswith("}")
        )
        is_collection = len(segments) == order_index + 1
        if (detail and not is_detail) or (not detail and not is_collection):
            continue
        operation = raw_path_item.get("get")
        if isinstance(operation, Mapping):
            matches.append((raw_path, operation))
    if len(matches) != 1:
        return None
    return matches[0]


def _operation_response_fields(
    specification: Mapping[str, object],
    operation: Mapping[str, object] | None,
    *,
    collection: bool,
) -> set[str]:
    if operation is None:
        return set()
    responses = operation.get("responses")
    if not isinstance(responses, Mapping):
        return set()
    response: Mapping[str, object] | None = None
    for code in _SUCCESS_RESPONSE_CODES:
        candidate = responses.get(code)
        if isinstance(candidate, Mapping):
            response = candidate
            break
    if response is None:
        return set()
    response = _resolve_object(specification, response)
    content = response.get("content")
    if not isinstance(content, Mapping):
        return set()
    media = content.get("application/json")
    if not isinstance(media, Mapping):
        return set()
    schema = media.get("schema")
    if not isinstance(schema, Mapping):
        return set()
    resolved = _resolve_schema(specification, schema)
    if collection:
        items = resolved.get("items")
        if not isinstance(items, Mapping):
            return set()
        resolved = _resolve_schema(specification, items)
    return _collect_field_paths(specification, resolved)


def _resolve_object(
    specification: Mapping[str, object],
    value: Mapping[str, object],
) -> Mapping[str, object]:
    reference = value.get("$ref")
    if not isinstance(reference, str):
        return value
    return _resolve_local_reference(specification, reference)


def _resolve_schema(
    specification: Mapping[str, object],
    schema: Mapping[str, object],
    *,
    seen: frozenset[str] = frozenset(),
) -> Mapping[str, object]:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        if reference in seen:
            raise SchwabOrderSchemaEvidenceError(
                "OpenAPI schema contains a reference cycle."
            )
        return _resolve_schema(
            specification,
            _resolve_local_reference(specification, reference),
            seen=seen | {reference},
        )
    all_of = schema.get("allOf")
    if isinstance(all_of, Sequence) and not isinstance(all_of, (str, bytes)):
        properties: dict[str, object] = {}
        for item in all_of:
            if not isinstance(item, Mapping):
                continue
            resolved = _resolve_schema(specification, item, seen=seen)
            item_properties = resolved.get("properties")
            if isinstance(item_properties, Mapping):
                properties.update(item_properties)
        merged = dict(schema)
        merged["properties"] = properties
        return merged
    return schema


def _resolve_local_reference(
    specification: Mapping[str, object],
    reference: str,
) -> Mapping[str, object]:
    if not reference.startswith("#/"):
        raise SchwabOrderSchemaEvidenceError(
            "Only local OpenAPI references are permitted."
        )
    current: object = specification
    for raw_segment in reference[2:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or segment not in current:
            raise SchwabOrderSchemaEvidenceError(
                f"OpenAPI reference could not be resolved: {reference}"
            )
        current = current[segment]
    if not isinstance(current, Mapping):
        raise SchwabOrderSchemaEvidenceError(
            f"OpenAPI reference is not an object: {reference}"
        )
    return current


def _collect_field_paths(
    specification: Mapping[str, object],
    schema: Mapping[str, object],
    *,
    prefix: str = "",
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        if reference in seen:
            return set()
        return _collect_field_paths(
            specification,
            _resolve_local_reference(specification, reference),
            prefix=prefix,
            seen=seen | {reference},
        )
    resolved = _resolve_schema(specification, schema, seen=seen)
    properties = resolved.get("properties")
    if not isinstance(properties, Mapping):
        return set()
    fields: set[str] = set()
    for raw_name, raw_child in properties.items():
        if not isinstance(raw_name, str) or not isinstance(raw_child, Mapping):
            continue
        path = f"{prefix}.{raw_name}" if prefix else raw_name
        fields.add(path)
        child = _resolve_schema(specification, raw_child, seen=seen)
        if child.get("type") == "array":
            items = child.get("items")
            if isinstance(items, Mapping):
                array_path = f"{path}[]"
                fields.add(array_path)
                fields.update(
                    _collect_field_paths(
                        specification,
                        items,
                        prefix=array_path,
                        seen=seen,
                    )
                )
        else:
            fields.update(
                _collect_field_paths(
                    specification,
                    child,
                    prefix=path,
                    seen=seen,
                )
            )
    return fields


def _string_value(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""


if __name__ == "__main__":
    raise SystemExit(main())
